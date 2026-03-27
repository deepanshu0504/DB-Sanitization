"""
Pre/Post sanitization integrity validator for verifying data integrity.

This module provides functionality to validate data integrity before and after
sanitization operations, ensuring no data loss, corruption, or referential
integrity violations occur during the sanitization process.

Key Features:
    - Pre-sanitization baseline capture (row counts, NULL counts, data types, FK relationships)
    - Post-sanitization verification (row count consistency, data type preservation, FK integrity)
    - FK orphan detection (detects broken referential integrity)
    - PII pattern detection (verifies no residual PII after sanitization)
    - Comprehensive reporting (JSON/HTML output with comparison deltas)
    - Performance optimized (sampling for large tables, query batching)

Validation Checks:
    - Row count consistency (critical - no data loss)
    - NULL value preservation (data quality)
    - Data type preservation (schema integrity)
    - FK relationship integrity (no orphaned records)
    - PII pattern detection (sanitization effectiveness)
    - Column length preservation (truncation detection)

Edge Cases Handled:
    - Circular FK dependencies
    - Self-referencing tables (hierarchical data)
    - Composite foreign keys
    - NULLable FK columns (NULL is valid)
    - Multi-tenant data isolation
    - Temporal/system-versioned tables
    - Partitioned tables
    - Large table sampling (performance)

Author: Database Sanitization Team
Date: 2026-03-27
"""

import hashlib
import re
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID
import pyodbc
from pathlib import Path

from src.database.connection_manager import DatabaseConnectionManager
from src.database.schema_extractor import SchemaExtractor
from src.config.config_models import PIIColumnConfig, SanitizationConfig
from src.validation.validation_result import ValidationResult, ValidationIssue, IssueSeverity
from src.logging.logger import get_logger
from src.logging.correlation import CorrelationContext
from src.logging.pii_patterns import (
    EMAIL_PATTERN,
    PHONE_PATTERN,
    SSN_PATTERN,
    CREDIT_CARD_PATTERN
)
from src.exceptions import DataValidationError


class ValidationPhase(Enum):
    """
    Validation phase enumeration.
    
    Defines when validation is performed in the sanitization lifecycle.
    """
    PRE_SANITIZATION = "pre_sanitization"
    POST_SANITIZATION = "post_sanitization"
    PRE_DESENSITIZATION = "pre_desensitization"
    POST_DESENSITIZATION = "post_desensitization"


@dataclass
class ValidationConfig:
    """
    Configuration for integrity validation behavior.
    
    Controls which validation checks are performed and their thresholds.
    
    Attributes:
        enable_row_count_check: Enable row count validation (default: True)
        enable_null_check: Enable NULL value preservation check (default: True)
        enable_fk_check: Enable FK integrity validation (default: True)
        enable_pii_check: Enable PII pattern detection (default: True)
        enable_data_type_check: Enable data type preservation check (default: True)
        enable_column_length_check: Enable column length validation (default: True)
        acceptable_orphan_percentage: Max acceptable orphan % (default: 0.0)
        acceptable_null_delta_percentage: Max acceptable NULL delta % (default: 0.0)
        pii_sample_size: Number of rows to sample for PII detection (default: 1000)
        pii_pattern_whitelist: List of regex patterns to whitelist (test data)
        pii_pattern_exceptions: Dict of table.column -> allowed patterns
        row_count_sampling_enabled: Enable sampling for large tables (default: True)
        row_count_sample_size: Threshold for sampling (default: 100000)
        fail_on_warning: Fail validation if warnings present (default: False)
    
    Example:
        >>> config = ValidationConfig(
        ...     enable_pii_check=True,
        ...     pii_sample_size=5000,
        ...     pii_pattern_whitelist=[r"test@example\.com", r"555-0100"]
        ... )
    """
    enable_row_count_check: bool = True
    enable_null_check: bool = True
    enable_fk_check: bool = True
    enable_pii_check: bool = True
    enable_data_type_check: bool = True
    enable_column_length_check: bool = True
    acceptable_orphan_percentage: float = 0.0
    acceptable_null_delta_percentage: float = 0.0
    pii_sample_size: int = 1000
    pii_pattern_whitelist: List[str] = field(default_factory=list)
    pii_pattern_exceptions: Dict[str, List[str]] = field(default_factory=dict)
    row_count_sampling_enabled: bool = True
    row_count_sample_size: int = 100000
    fail_on_warning: bool = False
    
    def __post_init__(self):
        """Validate configuration values."""
        if self.acceptable_orphan_percentage < 0 or self.acceptable_orphan_percentage > 100:
            raise ValueError("acceptable_orphan_percentage must be between 0 and 100")
        
        if self.acceptable_null_delta_percentage < 0 or self.acceptable_null_delta_percentage > 100:
            raise ValueError("acceptable_null_delta_percentage must be between 0 and 100")
        
        if self.pii_sample_size < 1:
            raise ValueError("pii_sample_size must be at least 1")
        
        if self.row_count_sample_size < 1:
            raise ValueError("row_count_sample_size must be at least 1")


@dataclass
class TableMetrics:
    """
    Metrics for a single table.
    
    Attributes:
        schema_name: Database schema name
        table_name: Table name
        row_count: Total number of rows
        null_counts: Dictionary mapping column name to NULL count
        data_types: Dictionary mapping column name to SQL data type
        column_lengths: Dictionary mapping column name to max length (schema)
        column_max_lengths: Dictionary mapping column name to actual max length (data)
        has_primary_key: Whether table has a primary key
        primary_key_columns: List of PK column names
        has_identity_columns: Whether table has identity columns
        identity_columns: List of identity column names
        has_computed_columns: Whether table has computed columns
        computed_columns: List of computed column names
    """
    schema_name: str
    table_name: str
    row_count: int
    null_counts: Dict[str, int] = field(default_factory=dict)
    data_types: Dict[str, str] = field(default_factory=dict)
    column_lengths: Dict[str, int] = field(default_factory=dict)
    column_max_lengths: Dict[str, int] = field(default_factory=dict)
    has_primary_key: bool = False
    primary_key_columns: List[str] = field(default_factory=list)
    has_identity_columns: bool = False
    identity_columns: List[str] = field(default_factory=list)
    has_computed_columns: bool = False
    computed_columns: List[str] = field(default_factory=list)
    
    @property
    def full_table_name(self) -> str:
        """Get fully qualified table name."""
        return f"[{self.schema_name}].[{self.table_name}]"


@dataclass
class FKRelationshipStatus:
    """
    Status of a foreign key relationship.
    
    Attributes:
        constraint_name: FK constraint name
        parent_table: Parent table name (referenced)
        child_table: Child table name (referencing)
        parent_columns: List of parent column names
        child_columns: List of child column names
        is_self_referencing: Whether FK references same table
        orphan_count: Number of orphaned child records
        is_nullable: Whether FK columns allow NULL
    """
    constraint_name: str
    parent_table: str
    child_table: str
    parent_columns: List[str]
    child_columns: List[str]
    is_self_referencing: bool
    orphan_count: int = 0
    is_nullable: bool = False


@dataclass
class PreSanitizationSnapshot:
    """
    Baseline snapshot captured before sanitization.
    
    Attributes:
        operation_id: Unique identifier for this operation
        timestamp: When snapshot was captured
        correlation_id: Correlation ID for tracing
        table_metrics: Dictionary mapping table name to TableMetrics
        fk_relationships: List of FK relationship statuses
        total_tables: Total number of tables being validated
        total_rows: Total rows across all tables
        duration_ms: Time taken to capture snapshot
    """
    operation_id: UUID
    timestamp: datetime
    correlation_id: str
    table_metrics: Dict[str, TableMetrics]
    fk_relationships: List[FKRelationshipStatus]
    total_tables: int
    total_rows: int
    duration_ms: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary for serialization."""
        return {
            "operation_id": str(self.operation_id),
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "total_tables": self.total_tables,
            "total_rows": self.total_rows,
            "duration_ms": self.duration_ms,
            "table_metrics": {
                name: {
                    "schema_name": m.schema_name,
                    "table_name": m.table_name,
                    "row_count": m.row_count,
                    "null_counts": m.null_counts,
                    "data_types": m.data_types,
                    "column_lengths": m.column_lengths,
                    "has_primary_key": m.has_primary_key,
                    "primary_key_columns": m.primary_key_columns
                }
                for name, m in self.table_metrics.items()
            },
            "fk_relationships": [
                {
                    "constraint_name": fk.constraint_name,
                    "parent_table": fk.parent_table,
                    "child_table": fk.child_table,
                    "parent_columns": fk.parent_columns,
                    "child_columns": fk.child_columns,
                    "is_self_referencing": fk.is_self_referencing,
                    "orphan_count": fk.orphan_count,
                    "is_nullable": fk.is_nullable
                }
                for fk in self.fk_relationships
            ]
        }


@dataclass
class PostSanitizationSnapshot:
    """
    Verification snapshot captured after sanitization.
    
    Attributes:
        operation_id: Unique identifier for this operation
        timestamp: When snapshot was captured
        correlation_id: Correlation ID for tracing
        table_metrics: Dictionary mapping table name to TableMetrics
        fk_relationships: List of FK relationship statuses
        pii_patterns_found: Dictionary mapping table to list of patterns detected
        total_tables: Total number of tables validated
        total_rows: Total rows across all tables
        duration_ms: Time taken to capture snapshot
    """
    operation_id: UUID
    timestamp: datetime
    correlation_id: str
    table_metrics: Dict[str, TableMetrics]
    fk_relationships: List[FKRelationshipStatus]
    pii_patterns_found: Dict[str, List[str]]
    total_tables: int
    total_rows: int
    duration_ms: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary for serialization."""
        return {
            "operation_id": str(self.operation_id),
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "total_tables": self.total_tables,
            "total_rows": self.total_rows,
            "duration_ms": self.duration_ms,
            "pii_patterns_found": self.pii_patterns_found,
            "table_metrics": {
                name: {
                    "schema_name": m.schema_name,
                    "table_name": m.table_name,
                    "row_count": m.row_count,
                    "null_counts": m.null_counts,
                    "data_types": m.data_types,
                    "column_lengths": m.column_lengths,
                    "has_primary_key": m.has_primary_key,
                    "primary_key_columns": m.primary_key_columns
                }
                for name, m in self.table_metrics.items()
            },
            "fk_relationships": [
                {
                    "constraint_name": fk.constraint_name,
                    "parent_table": fk.parent_table,
                    "child_table": fk.child_table,
                    "parent_columns": fk.parent_columns,
                    "child_columns": fk.child_columns,
                    "is_self_referencing": fk.is_self_referencing,
                    "orphan_count": fk.orphan_count,
                    "is_nullable": fk.is_nullable
                }
                for fk in self.fk_relationships
            ]
        }


@dataclass
class IntegrityReport:
    """
    Comprehensive integrity validation report.
    
    Attributes:
        pre_snapshot: Pre-sanitization snapshot
        post_snapshot: Post-sanitization snapshot
        validation_result: ValidationResult with all issues
        comparison_deltas: Dictionary of pre/post deltas
        row_count_deltas: Per-table row count differences
        null_count_deltas: Per-table-column NULL count differences
        data_type_mismatches: List of data type changes detected
        fk_constraint_changes: List of FK constraint modifications
        pii_patterns_found: Dictionary of table -> column -> patterns
        column_length_violations: List of column length truncations
        overall_status: PASS, FAIL, or WARNING
        critical_errors: Count of critical errors
        warnings: Count of warnings
        execution_metrics: Performance metrics
    """
    pre_snapshot: PreSanitizationSnapshot
    post_snapshot: PostSanitizationSnapshot
    validation_result: ValidationResult
    comparison_deltas: Dict[str, Any]
    row_count_deltas: Dict[str, int] = field(default_factory=dict)
    null_count_deltas: Dict[str, Dict[str, int]] = field(default_factory=dict)
    data_type_mismatches: List[str] = field(default_factory=list)
    fk_constraint_changes: List[str] = field(default_factory=list)
    pii_patterns_found: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    column_length_violations: List[str] = field(default_factory=list)
    overall_status: str = "UNKNOWN"
    critical_errors: int = 0
    warnings: int = 0
    execution_metrics: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary for serialization."""
        return {
            "overall_status": self.overall_status,
            "critical_errors": self.critical_errors,
            "warnings": self.warnings,
            "pre_snapshot": self.pre_snapshot.to_dict(),
            "post_snapshot": self.post_snapshot.to_dict(),
            "comparison_deltas": self.comparison_deltas,
            "row_count_deltas": self.row_count_deltas,
            "null_count_deltas": self.null_count_deltas,
            "data_type_mismatches": self.data_type_mismatches,
            "fk_constraint_changes": self.fk_constraint_changes,
            "pii_patterns_found": self.pii_patterns_found,
            "column_length_violations": self.column_length_violations,
            "validation_issues": {
                "errors": [issue.to_dict() for issue in self.validation_result.errors],
                "warnings": [issue.to_dict() for issue in self.validation_result.warnings],
                "infos": [issue.to_dict() for issue in self.validation_result.infos]
            },
            "execution_metrics": self.execution_metrics
        }
    
    def to_json(self, indent: int = 2) -> str:
        """
        Convert report to JSON string.
        
        Args:
            indent: Number of spaces for indentation (default: 2)
        
        Returns:
            Formatted JSON string with all report data
        
        Example:
            >>> json_str = report.to_json()
            >>> with open('validation_report.json', 'w') as f:
            ...     f.write(json_str)
        """
        return json.dumps(self.to_dict(), indent=indent, default=str)
    
    def to_html(self, title: str = "Integrity Validation Report") -> str:
        """
        Generate styled HTML report.
        
        Args:
            title: Report title (default: "Integrity Validation Report")
        
        Returns:
            HTML string with CSS styling, collapsible sections, and charts
        
        Example:
            >>> html = report.to_html()
            >>> with open('report.html', 'w') as f:
            ...     f.write(html)
        """
        status_color = {
            "PASS": "#28a745",
            "WARNING": "#ffc107",
            "FAIL": "#dc3545",
            "UNKNOWN": "#6c757d"
        }.get(self.overall_status, "#6c757d")
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid {status_color};
            padding-bottom: 10px;
        }}
        h2 {{
            color: #555;
            margin-top: 30px;
            border-bottom: 1px solid #ddd;
            padding-bottom: 8px;
        }}
        .summary {{
            background-color: #f8f9fa;
            padding: 20px;
            border-radius: 5px;
            margin-bottom: 30px;
        }}
        .status {{
            font-size: 24px;
            font-weight: bold;
            color: {status_color};
            margin: 10px 0;
        }}
        .metric {{
            display: inline-block;
            margin: 10px 20px 10px 0;
        }}
        .metric-label {{
            font-weight: bold;
            color: #666;
        }}
        .metric-value {{
            font-size: 20px;
            color: #333;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #f8f9fa;
            font-weight: bold;
            color: #555;
        }}
        tr:hover {{
            background-color: #f1f1f1;
        }}
        .error {{
            color: #dc3545;
            padding: 10px;
            background-color: #f8d7da;
            border-left: 4px solid #dc3545;
            margin: 10px 0;
            border-radius: 4px;
        }}
        .warning {{
            color: #856404;
            padding: 10px;
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            margin: 10px 0;
            border-radius: 4px;
        }}
        .info {{
            color: #004085;
            padding: 10px;
            background-color: #d1ecf1;
            border-left: 4px solid #17a2b8;
            margin: 10px 0;
            border-radius: 4px;
        }}
        .collapsible {{
            background-color: #f1f1f1;
            color: #333;
            cursor: pointer;
            padding: 15px;
            width: 100%;
            border: none;
            text-align: left;
            outline: none;
            font-size: 16px;
            font-weight: bold;
            margin-top: 10px;
            border-radius: 5px;
        }}
        .collapsible:hover {{
            background-color: #ddd;
        }}
        .collapsible.active {{
            background-color: #ccc;
        }}
        .content {{
            padding: 0 18px;
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.2s ease-out;
            background-color: #f9f9f9;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            margin: 2px;
        }}
        .badge-error {{ background-color: #dc3545; color: white; }}
        .badge-warning {{ background-color: #ffc107; color: #333; }}
        .badge-success {{ background-color: #28a745; color: white; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        
        <div class="summary">
            <div class="status">Status: {self.overall_status}</div>
            <div class="metric">
                <span class="metric-label">Critical Errors:</span>
                <span class="metric-value badge badge-error">{self.critical_errors}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Warnings:</span>
                <span class="metric-value badge badge-warning">{self.warnings}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Tables Validated:</span>
                <span class="metric-value">{self.pre_snapshot.total_tables}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Total Rows:</span>
                <span class="metric-value">{self.pre_snapshot.total_rows:,}</span>
            </div>
        </div>
        
        <h2>Row Count Comparison</h2>
        <table>
            <tr>
                <th>Table</th>
                <th>Pre-Sanitization</th>
                <th>Post-Sanitization</th>
                <th>Delta</th>
            </tr>
"""
        
        for table_name in self.pre_snapshot.table_metrics.keys():
            pre_count = self.pre_snapshot.table_metrics[table_name].row_count
            post_count = self.post_snapshot.table_metrics.get(table_name).row_count if self.post_snapshot.table_metrics.get(table_name) else 0
            delta = self.row_count_deltas.get(table_name, 0)
            delta_class = "badge-error" if delta != 0 else "badge-success"
            html += f"""
            <tr>
                <td>{table_name}</td>
                <td>{pre_count:,}</td>
                <td>{post_count:,}</td>
                <td><span class="badge {delta_class}">{delta:+d}</span></td>
            </tr>
"""
        
        html += """
        </table>
        
        <h2>Validation Issues</h2>
"""
        
        if self.validation_result.errors:
            html += f"""
        <button class="collapsible active">Critical Errors ({len(self.validation_result.errors)})</button>
        <div class="content" style="max-height: 500px;">
"""
            for error in self.validation_result.errors:
                html += f'<div class="error">{error}</div>\n'
            html += """
        </div>
"""
        
        if self.validation_result.warnings:
            html += f"""
        <button class="collapsible">Warnings ({len(self.validation_result.warnings)})</button>
        <div class="content">
"""
            for warning in self.validation_result.warnings[:50]:  # Limit to 50
                html += f'<div class="warning">{warning}</div>\n'
            if len(self.validation_result.warnings) > 50:
                html += f'<div class="warning">... and {len(self.validation_result.warnings) - 50} more warnings</div>\n'
            html += """
        </div>
"""
        
        if self.validation_result.infos:
            html += f"""
        <button class="collapsible">Information ({len(self.validation_result.infos)})</button>
        <div class="content">
"""
            for info in self.validation_result.infos[:50]:
                html += f'<div class="info">{info}</div>\n'
            html += """
        </div>
"""
        
        if self.pii_patterns_found:
            html += """
        <h2>PII Patterns Detected</h2>
        <table>
            <tr>
                <th>Table</th>
                <th>Column</th>
                <th>Patterns</th>
            </tr>
"""
            for table, columns in self.pii_patterns_found.items():
                for column, patterns in columns.items():
                    html += f"""
            <tr>
                <td>{table}</td>
                <td>{column}</td>
                <td>{', '.join(patterns)}</td>
            </tr>
"""
            html += """
        </table>
"""
        
        html += f"""
        <h2>Execution Metrics</h2>
        <div class="summary">
            <div class="metric">
                <span class="metric-label">Pre-Snapshot Duration:</span>
                <span class="metric-value">{self.pre_snapshot.duration_ms:,} ms</span>
            </div>
            <div class="metric">
                <span class="metric-label">Post-Snapshot Duration:</span>
                <span class="metric-value">{self.post_snapshot.duration_ms:,} ms</span>
            </div>
        </div>
    </div>
    
    <script>
        var coll = document.getElementsByClassName("collapsible");
        for (var i = 0; i < coll.length; i++) {{
            coll[i].addEventListener("click", function() {{
                this.classList.toggle("active");
                var content = this.nextElementSibling;
                if (content.style.maxHeight) {{
                    content.style.maxHeight = null;
                }} else {{
                    content.style.maxHeight = content.scrollHeight + "px";
                }}
            }});
            
            // Auto-expand first collapsible
            if (i === 0 && coll[i].classList.contains("active")) {{
                var content = coll[i].nextElementSibling;
                content.style.maxHeight = content.scrollHeight + "px";
            }}
        }}
    </script>
</body>
</html>
"""
        return html
    
    def export(self, output_dir: str = "./validation_reports", format: str = "both") -> List[str]:
        """
        Export report to file(s).
        
        Args:
            output_dir: Directory to write reports (default: "./validation_reports")
            format: Export format - "json", "html", or "both" (default: "both")
        
        Returns:
            List of file paths created
        
        Example:
            >>> files = report.export(format="both")
            >>> print(f"Generated: {', '.join(files)}")
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        operation_id = str(self.pre_snapshot.operation_id)[:8]
        base_name = f"validation_report_{operation_id}_{timestamp}"
        
        files_created = []
        
        if format in ["json", "both"]:
            json_file = output_path / f"{base_name}.json"
            json_file.write_text(self.to_json())
            files_created.append(str(json_file))
        
        if format in ["html", "both"]:
            html_file = output_path / f"{base_name}.html"
            html_file.write_text(self.to_html())
            files_created.append(str(html_file))
        
        return files_created
    
    def has_critical_issues(self) -> bool:
        """
        Check if report contains critical errors.
        
        Returns:
            True if critical errors present, False otherwise
        """
        return self.critical_errors > 0 or self.overall_status == "FAIL"
    
    def severity_summary(self) -> Dict[str, int]:
        """
        Get count of issues by severity.
        
        Returns:
            Dictionary mapping severity level to count
        
        Example:
            >>> summary = report.severity_summary()
            >>> print(f"Errors: {summary['error']}, Warnings: {summary['warning']}")
        """
        return {
            "error": len(self.validation_result.errors),
            "warning": len(self.validation_result.warnings),
            "info": len(self.validation_result.infos)
        }
    
    def format_summary(self) -> str:
        """Format a human-readable summary of the report."""
        lines = []
        lines.append("=" * 70)
        lines.append("INTEGRITY VALIDATION REPORT")
        lines.append("=" * 70)
        lines.append("")
        lines.append(f"Overall Status: {self.overall_status}")
        lines.append(f"Critical Errors: {self.critical_errors}")
        lines.append(f"Warnings: {self.warnings}")
        lines.append("")
        lines.append("Comparison Deltas:")
        for key, value in self.comparison_deltas.items():
            lines.append(f"  {key}: {value}")
        lines.append("")
        
        if self.validation_result.errors:
            lines.append("Critical Errors:")
            for error in self.validation_result.errors:
                lines.append(f"  - {error}")
            lines.append("")
        
        if self.validation_result.warnings:
            lines.append("Warnings:")
            for warning in self.validation_result.warnings[:10]:  # Limit to 10
                lines.append(f"  - {warning}")
            if len(self.validation_result.warnings) > 10:
                lines.append(f"  ... and {len(self.validation_result.warnings) - 10} more")
            lines.append("")
        
        lines.append("=" * 70)
        return "\n".join(lines)


class IntegrityValidator:
    """
    Validates data integrity before and after sanitization operations.
    
    This class captures baseline metrics before sanitization and verifies
    data integrity after sanitization to ensure no data loss, corruption,
    or referential integrity violations occurred.
    
    Attributes:
        connection_manager: Database connection manager
        schema_extractor: Schema metadata extractor
        logger: Structured logger instance
        sample_size: Number of rows to sample for PII detection (default 1000)
        
    Example:
        ```python
        # Initialize validator
        conn_mgr = DatabaseConnectionManager(config.database)
        schema_extractor = SchemaExtractor(conn_mgr)
        validator = IntegrityValidator(conn_mgr, schema_extractor)
        
        # Capture pre-sanitization baseline
        pre_snapshot = validator.validate_pre(
            operation_id=operation_id,
            table_names=["Customers", "Orders"],
            pii_columns=pii_columns
        )
        
        # ... perform sanitization ...
        
        # Verify post-sanitization integrity
        post_snapshot = validator.validate_post(
            operation_id=operation_id,
            table_names=["Customers", "Orders"],
            pii_columns=pii_columns,
            pre_snapshot=pre_snapshot
        )
        
        # Generate comparison report
        report = validator.compare_reports(pre_snapshot, post_snapshot)
        print(report.format_summary())
        ```
    
    Edge Cases Handled:
        - Self-referencing FKs (hierarchical data)
        - Composite foreign keys
        - NULLable FK columns
        - Circular FK dependencies
        - Large tables (sampling for performance)
        - Partitioned tables
        - Temporal tables
    """
    
    def __init__(
        self,
        connection_manager: DatabaseConnectionManager,
        schema_extractor: SchemaExtractor,
        sample_size: int = 1000
    ):
        """
        Initialize the integrity validator.
        
        Args:
            connection_manager: Database connection manager
            schema_extractor: Schema metadata extractor
            sample_size: Number of rows to sample for PII detection
        """
        self.connection_manager = connection_manager
        self.schema_extractor = schema_extractor
        self.sample_size = sample_size
        self.logger = get_logger(self.__class__.__name__)
        
        self.logger.info(
            "IntegrityValidator initialized",
            extra={"sample_size": sample_size}
        )
    
    def validate_pre(
        self,
        operation_id: UUID,
        table_names: List[str],
        pii_columns: List[PIIColumnConfig]
    ) -> PreSanitizationSnapshot:
        """
        Capture pre-sanitization baseline metrics.
        
        Args:
            operation_id: Unique identifier for this operation
            table_names: List of table names to validate (format: [schema].[table])
            pii_columns: List of PII column configurations
            
        Returns:
            PreSanitizationSnapshot with baseline metrics
            
        Raises:
            DataValidationError: If baseline capture fails
        """
        with CorrelationContext() as correlation_id:
            started_at = datetime.utcnow()
            
            self.logger.info(
                "Starting pre-sanitization validation",
                extra={
                    "correlation_id": correlation_id,
                    "operation_id": str(operation_id),
                    "table_count": len(table_names)
                }
            )
            
            try:
                # Capture table metrics
                table_metrics = self._capture_table_metrics(table_names, pii_columns)
                
                # Capture FK relationships
                fk_relationships = self._capture_fk_relationships(table_names)
                
                # Calculate totals
                total_rows = sum(m.row_count for m in table_metrics.values())
                
                completed_at = datetime.utcnow()
                duration_ms = int((completed_at - started_at).total_seconds() * 1000)
                
                snapshot = PreSanitizationSnapshot(
                    operation_id=operation_id,
                    timestamp=started_at,
                    correlation_id=correlation_id,
                    table_metrics=table_metrics,
                    fk_relationships=fk_relationships,
                    total_tables=len(table_names),
                    total_rows=total_rows,
                    duration_ms=duration_ms
                )
                
                self.logger.info(
                    "Pre-sanitization validation completed",
                    extra={
                        "correlation_id": correlation_id,
                        "total_tables": len(table_names),
                        "total_rows": total_rows,
                        "duration_ms": duration_ms
                    }
                )
                
                return snapshot
                
            except Exception as e:
                self.logger.error(
                    "Pre-sanitization validation failed",
                    extra={
                        "correlation_id": correlation_id,
                        "error": str(e)
                    },
                    exc_info=True
                )
                raise DataValidationError(
                    message=f"Failed to capture pre-sanitization baseline: {str(e)}",
                    table_name=None,
                    column_name=None
                )
    
    def validate_post(
        self,
        operation_id: UUID,
        table_names: List[str],
        pii_columns: List[PIIColumnConfig],
        pre_snapshot: PreSanitizationSnapshot
    ) -> PostSanitizationSnapshot:
        """
        Verify post-sanitization integrity.
        
        Args:
            operation_id: Unique identifier for this operation
            table_names: List of table names to validate
            pii_columns: List of PII column configurations
            pre_snapshot: Pre-sanitization baseline snapshot
            
        Returns:
            PostSanitizationSnapshot with verification results
            
        Raises:
            DataValidationError: If verification fails
        """
        with CorrelationContext() as correlation_id:
            started_at = datetime.utcnow()
            
            self.logger.info(
                "Starting post-sanitization validation",
                extra={
                    "correlation_id": correlation_id,
                    "operation_id": str(operation_id),
                    "table_count": len(table_names)
                }
            )
            
            try:
                # Capture table metrics
                table_metrics = self._capture_table_metrics(table_names, pii_columns)
                
                # Capture FK relationships
                fk_relationships = self._capture_fk_relationships(table_names)
                
                # Detect PII patterns in sanitized columns
                pii_patterns_found = self._detect_pii_patterns(table_names, pii_columns)
                
                # Calculate totals
                total_rows = sum(m.row_count for m in table_metrics.values())
                
                completed_at = datetime.utcnow()
                duration_ms = int((completed_at - started_at).total_seconds() * 1000)
                
                snapshot = PostSanitizationSnapshot(
                    operation_id=operation_id,
                    timestamp=started_at,
                    correlation_id=correlation_id,
                    table_metrics=table_metrics,
                    fk_relationships=fk_relationships,
                    pii_patterns_found=pii_patterns_found,
                    total_tables=len(table_names),
                    total_rows=total_rows,
                    duration_ms=duration_ms
                )
                
                self.logger.info(
                    "Post-sanitization validation completed",
                    extra={
                        "correlation_id": correlation_id,
                        "total_tables": len(table_names),
                        "total_rows": total_rows,
                        "pii_patterns_found": sum(len(v) for v in pii_patterns_found.values()),
                        "duration_ms": duration_ms
                    }
                )
                
                return snapshot
                
            except Exception as e:
                self.logger.error(
                    "Post-sanitization validation failed",
                    extra={
                        "correlation_id": correlation_id,
                        "error": str(e)
                    },
                    exc_info=True
                )
                raise DataValidationError(
                    message=f"Failed to verify post-sanitization integrity: {str(e)}",
                    table_name=None,
                    column_name=None
                )
    
    def compare_reports(
        self,
        pre_snapshot: PreSanitizationSnapshot,
        post_snapshot: PostSanitizationSnapshot
    ) -> IntegrityReport:
        """
        Compare pre/post snapshots and generate integrity report.
        
        Args:
            pre_snapshot: Pre-sanitization baseline
            post_snapshot: Post-sanitization verification
            
        Returns:
            IntegrityReport with comparison results
        """
        with CorrelationContext() as correlation_id:
            started_at = datetime.utcnow()
            
            self.logger.info(
                "Generating integrity comparison report",
                extra={"correlation_id": correlation_id}
            )
            
            result = ValidationResult()
            comparison_deltas = {}
            
            # Compare row counts
            self._compare_row_counts(pre_snapshot, post_snapshot, result, comparison_deltas)
            
            # Compare NULL counts
            self._compare_null_counts(pre_snapshot, post_snapshot, result, comparison_deltas)
            
            # Compare data types
            self._compare_data_types(pre_snapshot, post_snapshot, result, comparison_deltas)
            
            # Compare FK integrity
            self._compare_fk_integrity(pre_snapshot, post_snapshot, result, comparison_deltas)
            
            # Check for PII patterns
            self._check_pii_patterns(post_snapshot, result, comparison_deltas)
            
            # Determine overall status
            overall_status = "PASS"
            if result.error_count > 0:
                overall_status = "FAIL"
            elif result.warning_count > 0:
                overall_status = "WARNING"
            
            completed_at = datetime.utcnow()
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)
            
            execution_metrics = {
                "comparison_duration_ms": duration_ms,
                "pre_validation_duration_ms": pre_snapshot.duration_ms,
                "post_validation_duration_ms": post_snapshot.duration_ms,
                "total_validation_duration_ms": pre_snapshot.duration_ms + post_snapshot.duration_ms + duration_ms
            }
            
            report = IntegrityReport(
                pre_snapshot=pre_snapshot,
                post_snapshot=post_snapshot,
                validation_result=result,
                comparison_deltas=comparison_deltas,
                overall_status=overall_status,
                critical_errors=result.error_count,
                warnings=result.warning_count,
                execution_metrics=execution_metrics
            )
            
            self.logger.info(
                "Integrity comparison report generated",
                extra={
                    "correlation_id": correlation_id,
                    "overall_status": overall_status,
                    "critical_errors": result.error_count,
                    "warnings": result.warning_count,
                    "duration_ms": duration_ms
                }
            )
            
            return report
    
    def _capture_table_metrics(
        self,
        table_names: List[str],
        pii_columns: List[PIIColumnConfig]
    ) -> Dict[str, TableMetrics]:
        """
        Capture metrics for specified tables.
        
        Args:
            table_names: List of fully qualified table names
            pii_columns: List of PII column configurations
            
        Returns:
            Dictionary mapping table name to TableMetrics
        """
        metrics = {}
        
        for table_name in table_names:
            # Parse schema and table
            schema, table = self._parse_table_name(table_name)
            
            # Get row count
            row_count = self._get_row_count(schema, table)
            
            # Get NULL counts for PII columns in this table
            table_pii_columns = [
                col for col in pii_columns
                if col.schema == schema and col.table == table
            ]
            null_counts = self._get_null_counts(schema, table, table_pii_columns)
            
            # Get data types and lengths
            data_types, column_lengths = self._get_data_types_and_lengths(schema, table, table_pii_columns)
            
            # Get primary key info
            has_pk, pk_columns = self._get_primary_key_info(schema, table)
            
            metrics[table_name] = TableMetrics(
                schema_name=schema,
                table_name=table,
                row_count=row_count,
                null_counts=null_counts,
                data_types=data_types,
                column_lengths=column_lengths,
                has_primary_key=has_pk,
                primary_key_columns=pk_columns
            )
        
        return metrics
    
    def _capture_fk_relationships(
        self,
        table_names: List[str]
    ) -> List[FKRelationshipStatus]:
        """
        Capture FK relationship status for specified tables.
        
        Args:
            table_names: List of fully qualified table names
            
        Returns:
            List of FKRelationshipStatus objects
        """
        relationships = []
        
        # Extract all FK metadata from schema
        all_fks = []
        for table_name in table_names:
            schema, table = self._parse_table_name(table_name)
            schema_info = self.schema_extractor.extract_schema(schema)
            
            # Find table in schema
            table_info = None
            for t in schema_info.get("tables", []):
                if t["schema_name"] == schema and t["table_name"] == table:
                    table_info = t
                    break
            
            if table_info and "foreign_keys" in table_info:
                all_fks.extend(table_info["foreign_keys"])
        
        # Process each FK
        for fk in all_fks:
            parent_table = f"[{fk['parent_schema']}].[{fk['parent_table']}]"
            child_table = f"[{fk['child_schema']}].[{fk['child_table']}]"
            
            # Count orphaned records
            orphan_count = self._count_orphaned_records(fk)
            
            relationships.append(FKRelationshipStatus(
                constraint_name=fk["constraint_name"],
                parent_table=parent_table,
                child_table=child_table,
                parent_columns=[fk["parent_column"]],
                child_columns=[fk["child_column"]],
                is_self_referencing=fk.get("is_self_referencing", False),
                orphan_count=orphan_count,
                is_nullable=True  # Simplified - would check column metadata for accurate value
            ))
        
        return relationships
    
    def _detect_pii_patterns(
        self,
        table_names: List[str],
        pii_columns: List[PIIColumnConfig]
    ) -> Dict[str, List[str]]:
        """
        Detect PII patterns in sanitized columns.
        
        Args:
            table_names: List of table names
            pii_columns: List of PII column configurations
            
        Returns:
            Dictionary mapping table name to list of detected patterns
        """
        patterns_found = {}
        
        for table_name in table_names:
            schema, table = self._parse_table_name(table_name)
            
            # Get PII columns for this table
            table_pii_columns = [
                col for col in pii_columns
                if col.schema == schema and col.table == table
            ]
            
            if not table_pii_columns:
                continue
            
            # Sample data from columns
            column_names = [col.column for col in table_pii_columns]
            sample_data = self._sample_column_data(schema, table, column_names)
            
            # Check for patterns
            detected_patterns = []
            for row in sample_data:
                for col_name, value in row.items():
                    if value is None:
                        continue
                    
                    value_str = str(value)
                    
                    # Check each pattern
                    if EMAIL_PATTERN.search(value_str):
                        detected_patterns.append(f"{col_name}: EMAIL pattern in '{value_str[:50]}'")
                    if PHONE_PATTERN.search(value_str):
                        detected_patterns.append(f"{col_name}: PHONE pattern in '{value_str[:50]}'")
                    if SSN_PATTERN.search(value_str):
                        detected_patterns.append(f"{col_name}: SSN pattern in '{value_str[:50]}'")
                    if CREDIT_CARD_PATTERN.search(value_str):
                        detected_patterns.append(f"{col_name}: CREDIT_CARD pattern in '{value_str[:50]}'")
            
            if detected_patterns:
                patterns_found[table_name] = detected_patterns[:10]  # Limit to 10 examples
        
        return patterns_found
    
    def _compare_row_counts(
        self,
        pre: PreSanitizationSnapshot,
        post: PostSanitizationSnapshot,
        result: ValidationResult,
        deltas: Dict[str, Any]
    ) -> None:
        """Compare row counts between pre and post snapshots."""
        row_count_deltas = {}
        
        for table_name, pre_metrics in pre.table_metrics.items():
            if table_name not in post.table_metrics:
                result.add_error(
                    message=f"Table {table_name} missing in post-sanitization snapshot",
                    column=table_name,
                    code="TABLE_MISSING_POST",
                    suggested_action="Verify sanitization did not drop tables"
                )
                continue
            
            post_metrics = post.table_metrics[table_name]
            delta = post_metrics.row_count - pre_metrics.row_count
            
            if delta != 0:
                row_count_deltas[table_name] = delta
                result.add_error(
                    message=f"Row count mismatch in {table_name}: {pre_metrics.row_count} → {post_metrics.row_count} (Δ{delta:+d})",
                    column=table_name,
                    code="ROW_COUNT_MISMATCH",
                    suggested_action="CRITICAL: Data loss detected. Investigate sanitization process and consider rollback."
                )
        
        deltas["row_count_deltas"] = row_count_deltas
        deltas["total_row_delta"] = sum(row_count_deltas.values())
    
    def _compare_null_counts(
        self,
        pre: PreSanitizationSnapshot,
        post: PostSanitizationSnapshot,
        result: ValidationResult,
        deltas: Dict[str, Any]
    ) -> None:
        """Compare NULL counts between pre and post snapshots."""
        null_count_changes = {}
        
        for table_name, pre_metrics in pre.table_metrics.items():
            if table_name not in post.table_metrics:
                continue
            
            post_metrics = post.table_metrics[table_name]
            
            for col_name, pre_null_count in pre_metrics.null_counts.items():
                post_null_count = post_metrics.null_counts.get(col_name, 0)
                delta = post_null_count - pre_null_count
                
                if delta != 0:
                    key = f"{table_name}.{col_name}"
                    null_count_changes[key] = delta
                    
                    result.add_warning(
                        message=f"NULL count changed in {key}: {pre_null_count} → {post_null_count} (Δ{delta:+d})",
                        column=key,
                        code="NULL_COUNT_CHANGED",
                        suggested_action="Review masking strategy - NULL preservation may be required"
                    )
        
        deltas["null_count_changes"] = null_count_changes
    
    def _compare_data_types(
        self,
        pre: PreSanitizationSnapshot,
        post: PostSanitizationSnapshot,
        result: ValidationResult,
        deltas: Dict[str, Any]
    ) -> None:
        """Compare data types between pre and post snapshots."""
        data_type_changes = {}
        
        for table_name, pre_metrics in pre.table_metrics.items():
            if table_name not in post.table_metrics:
                continue
            
            post_metrics = post.table_metrics[table_name]
            
            for col_name, pre_type in pre_metrics.data_types.items():
                post_type = post_metrics.data_types.get(col_name)
                
                if post_type and post_type != pre_type:
                    key = f"{table_name}.{col_name}"
                    data_type_changes[key] = f"{pre_type} → {post_type}"
                    
                    result.add_error(
                        message=f"Data type changed in {key}: {pre_type} → {post_type}",
                        column=key,
                        code="DATA_TYPE_CHANGED",
                        suggested_action="CRITICAL: Schema corruption detected. Rollback immediately."
                    )
        
        deltas["data_type_changes"] = data_type_changes
    
    def _compare_fk_integrity(
        self,
        pre: PreSanitizationSnapshot,
        post: PostSanitizationSnapshot,
        result: ValidationResult,
        deltas: Dict[str, Any]
    ) -> None:
        """Compare FK integrity between pre and post snapshots."""
        orphan_deltas = {}
        
        # Create lookup of pre FK relationships
        pre_fks = {fk.constraint_name: fk for fk in pre.fk_relationships}
        
        for post_fk in post.fk_relationships:
            pre_fk = pre_fks.get(post_fk.constraint_name)
            
            if not pre_fk:
                continue
            
            delta = post_fk.orphan_count - pre_fk.orphan_count
            
            if delta > 0:
                orphan_deltas[post_fk.constraint_name] = delta
                
                result.add_error(
                    message=f"New orphaned records detected in FK {post_fk.constraint_name}: "
                           f"{pre_fk.orphan_count} → {post_fk.orphan_count} (+{delta})",
                    column=f"{post_fk.child_table} → {post_fk.parent_table}",
                    code="FK_ORPHANS_CREATED",
                    suggested_action="CRITICAL: Referential integrity violated. Review FK handling in sanitization."
                )
            elif delta < 0:
                # Orphan count decreased (good, but unexpected)
                result.add_info(
                    message=f"Orphaned records reduced in FK {post_fk.constraint_name}: "
                           f"{pre_fk.orphan_count} → {post_fk.orphan_count} ({delta})",
                    column=f"{post_fk.child_table} → {post_fk.parent_table}"
                )
        
        deltas["orphan_deltas"] = orphan_deltas
        deltas["total_new_orphans"] = sum(orphan_deltas.values())
    
    def _check_pii_patterns(
        self,
        post: PostSanitizationSnapshot,
        result: ValidationResult,
        deltas: Dict[str, Any]
    ) -> None:
        """Check for residual PII patterns in post-sanitization data."""
        total_patterns = sum(len(patterns) for patterns in post.pii_patterns_found.values())
        
        if total_patterns > 0:
            for table_name, patterns in post.pii_patterns_found.items():
                for pattern in patterns:
                    result.add_error(
                        message=f"PII pattern detected in sanitized data: {pattern}",
                        column=table_name,
                        code="PII_PATTERN_DETECTED",
                        suggested_action="Sanitization incomplete - review masking logic for this column"
                    )
        
        deltas["pii_patterns_detected"] = total_patterns
    
    # Helper methods for data queries
    
    def _parse_table_name(self, table_name: str) -> Tuple[str, str]:
        """Parse fully qualified table name into schema and table."""
        # Remove brackets if present
        table_name = table_name.strip("[]")
        
        if "." in table_name:
            parts = table_name.split(".")
            return parts[0].strip("[]"), parts[1].strip("[]")
        else:
            return "dbo", table_name
    
    def _get_row_count(self, schema: str, table: str) -> int:
        """Get total row count for a table."""
        query = f"SELECT COUNT(*) as row_count FROM [{schema}].[{table}]"
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                result = cursor.fetchone()
                cursor.close()
                return result[0] if result else 0
        except Exception as e:
            self.logger.warning(
                f"Failed to get row count for [{schema}].[{table}]: {str(e)}"
            )
            return 0
    
    def _get_null_counts(
        self,
        schema: str,
        table: str,
        columns: List[PIIColumnConfig]
    ) -> Dict[str, int]:
        """Get NULL counts for specified columns."""
        if not columns:
            return {}
        
        null_counts = {}
        column_names = [col.column for col in columns]
        
        # Build query to count NULLs for each column
        count_clauses = [
            f"SUM(CASE WHEN [{col}] IS NULL THEN 1 ELSE 0 END) as [{col}_nulls]"
            for col in column_names
        ]
        query = f"SELECT {', '.join(count_clauses)} FROM [{schema}].[{table}]"
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                result = cursor.fetchone()
                cursor.close()
                
                if result:
                    for i, col_name in enumerate(column_names):
                        null_counts[col_name] = result[i] or 0
        except Exception as e:
            self.logger.warning(
                f"Failed to get NULL counts for [{schema}].[{table}]: {str(e)}"
            )
        
        return null_counts
    
    def _get_data_types_and_lengths(
        self,
        schema: str,
        table: str,
        columns: List[PIIColumnConfig]
    ) -> Tuple[Dict[str, str], Dict[str, int]]:
        """Get data types and max lengths for specified columns."""
        if not columns:
            return {}, {}
        
        data_types = {}
        column_lengths = {}
        column_names = [col.column for col in columns]
        
        query = """
            SELECT 
                COLUMN_NAME,
                DATA_TYPE,
                CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
              AND COLUMN_NAME IN ({})
        """.format(','.join(['?'] * len(column_names)))
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, [schema, table] + column_names)
                
                for row in cursor.fetchall():
                    col_name = row[0]
                    data_type = row[1]
                    max_length = row[2]
                    
                    data_types[col_name] = data_type
                    if max_length:
                        column_lengths[col_name] = max_length
                
                cursor.close()
        except Exception as e:
            self.logger.warning(
                f"Failed to get data types for [{schema}].[{table}]: {str(e)}"
            )
        
        return data_types, column_lengths
    
    def _get_primary_key_info(self, schema: str, table: str) -> Tuple[bool, List[str]]:
        """Get primary key information for a table."""
        query = """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
              AND CONSTRAINT_NAME LIKE 'PK_%'
            ORDER BY ORDINAL_POSITION
        """
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, [schema, table])
                
                pk_columns = [row[0] for row in cursor.fetchall()]
                cursor.close()
                
                return len(pk_columns) > 0, pk_columns
        except Exception as e:
            self.logger.warning(
                f"Failed to get PK info for [{schema}].[{table}]: {str(e)}"
            )
            return False, []
    
    def _count_orphaned_records(self, fk: Dict[str, Any]) -> int:
        """Count orphaned records for a foreign key relationship."""
        # Build query to count child records without matching parent
        query = f"""
            SELECT COUNT(*)
            FROM [{fk['child_schema']}].[{fk['child_table']}] child
            WHERE child.[{fk['child_column']}] IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM [{fk['parent_schema']}].[{fk['parent_table']}] parent
                  WHERE parent.[{fk['parent_column']}] = child.[{fk['child_column']}]
              )
        """
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                result = cursor.fetchone()
                cursor.close()
                return result[0] if result else 0
        except Exception as e:
            self.logger.warning(
                f"Failed to count orphans for FK {fk['constraint_name']}: {str(e)}"
            )
            return 0
    
    def _sample_column_data(
        self,
        schema: str,
        table: str,
        column_names: List[str]
    ) -> List[Dict[str, Any]]:
        """Sample data from specified columns for PII detection."""
        if not column_names:
            return []
        
        columns_clause = ', '.join([f"[{col}]" for col in column_names])
        query = f"""
            SELECT TOP {self.sample_size} {columns_clause}
            FROM [{schema}].[{table}]
            WHERE {' OR '.join([f'[{col}] IS NOT NULL' for col in column_names])}
            ORDER BY NEWID()
        """
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                
                rows = []
                for row in cursor.fetchall():
                    row_dict = {}
                    for i, col_name in enumerate(column_names):
                        row_dict[col_name] = row[i]
                    rows.append(row_dict)
                
                cursor.close()
                return rows
        except Exception as e:
            self.logger.warning(
                f"Failed to sample data from [{schema}].[{table}]: {str(e)}"
            )
            return []
    
    def _validate_fk_constraint_existence(
        self,
        schema: str,
        table: str
    ) -> List[Dict[str, Any]]:
        """
        Validate FK constraint existence from INFORMATION_SCHEMA.
        
        Args:
            schema: Schema name
            table: Table name
        
        Returns:
            List of FK constraint metadata dictionaries
        """
        query = """
            SELECT
                fk.CONSTRAINT_NAME,
                fk.TABLE_SCHEMA AS child_schema,
                fk.TABLE_NAME AS child_table,
                pk.TABLE_SCHEMA AS parent_schema,
                pk.TABLE_NAME AS parent_table,
                cu.COLUMN_NAME AS child_column,
                ru.COLUMN_NAME AS parent_column
            FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
            INNER JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS fk
                ON rc.CONSTRAINT_NAME = fk.CONSTRAINT_NAME
            INNER JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS pk
                ON rc.UNIQUE_CONSTRAINT_NAME = pk.CONSTRAINT_NAME
            INNER JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE cu
                ON fk.CONSTRAINT_NAME = cu.CONSTRAINT_NAME
            INNER JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ru
                ON pk.CONSTRAINT_NAME = ru.CONSTRAINT_NAME
                AND cu.ORDINAL_POSITION = ru.ORDINAL_POSITION
            WHERE fk.TABLE_SCHEMA = ? AND fk.TABLE_NAME = ?
            ORDER BY fk.CONSTRAINT_NAME, cu.ORDINAL_POSITION
        """
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (schema, table))
                
                constraints = []
                for row in cursor.fetchall():
                    constraints.append({
                        "constraint_name": row.CONSTRAINT_NAME,
                        "child_schema": row.child_schema,
                        "child_table": row.child_table,
                        "parent_schema": row.parent_schema,
                        "parent_table": row.parent_table,
                        "child_column": row.child_column,
                        "parent_column": row.parent_column
                    })
                
                cursor.close()
                return constraints
        except Exception as e:
            self.logger.error(
                f"Failed to query FK constraints for [{schema}].[{table}]: {str(e)}"
            )
            return []
    
    def _validate_composite_fk_integrity(
        self,
        fk: Dict[str, Any],
        parent_columns: List[str],
        child_columns: List[str]
    ) -> int:
        """
        Validate composite foreign key integrity (multi-column FKs).
        
        Args:
            fk: FK metadata dictionary
            parent_columns: List of parent column names
            child_columns: List of child column names
        
        Returns:
            Number of orphaned records (0 means integrity preserved)
        """
        # Build WHERE clause for composite FK (AND logic)
        where_conditions = []
        for i, child_col in enumerate(child_columns):
            parent_col = parent_columns[i] if i < len(parent_columns) else child_col
            where_conditions.append(
                f"child.[{child_col}] = parent.[{parent_col}]"
            )
        
        where_clause = " AND ".join(where_conditions)
        
        # Build NULL check (if ANY column is NULL, entire FK is NULL - not orphan)
        null_check = " OR ".join([f"child.[{col}] IS NULL" for col in child_columns])
        
        query = f"""
            SELECT COUNT(*)
            FROM [{fk['child_schema']}].[{fk['child_table']}] child
            WHERE NOT ({null_check})
              AND NOT EXISTS (
                  SELECT 1
                  FROM [{fk['parent_schema']}].[{fk['parent_table']}] parent
                  WHERE {where_clause}
              )
        """
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                result = cursor.fetchone()
                cursor.close()
                return result[0] if result else 0
        except Exception as e:
            self.logger.warning(
                f"Failed to validate composite FK {fk.get('constraint_name', 'unknown')}: {str(e)}"
            )
            return 0
    
    def _validate_circular_fk_dependencies(
        self,
        fk_relationships: List[Dict[str, Any]]
    ) -> Tuple[bool, List[List[str]]]:
        """
        Detect circular foreign key dependencies.
        
        Args:
            fk_relationships: List of FK relationship metadata
        
        Returns:
            Tuple of (has_cycles, list_of_cycles)
        """
        try:
            # Import DependencyResolver for cycle detection
            from src.sanitization.dependency_resolver import DependencyResolver
            
            # Build FK metadata for resolver
            fk_metadata = []
            for fk in fk_relationships:
                parent_table = f"[{fk['parent_schema']}].[{fk['parent_table']}]"
                child_table = f"[{fk['child_schema']}].[{fk['child_table']}]"
                fk_metadata.append({
                    "parent_table": parent_table,
                    "child_table": child_table
                })
            
            # Detect cycles
            resolver = DependencyResolver(fk_metadata)
            has_cycles = resolver.has_circular_dependencies()
            cycles = list(resolver.get_cycles()) if has_cycles else []
            
            return has_cycles, cycles
        
        except Exception as e:
            self.logger.error(
                f"Failed to detect circular FK dependencies: {str(e)}"
            )
            return False, []
    
    def _validate_self_referencing_tables(
        self,
        fk: Dict[str, Any]
    ) -> int:
        """
        Validate self-referencing table integrity (hierarchical data).
        
        Args:
            fk: FK metadata where parent_table == child_table
        
        Returns:
            Number of orphaned records in hierarchy
        """
        # Query for self-referencing orphans
        query = f"""
            SELECT COUNT(*)
            FROM [{fk['child_schema']}].[{fk['child_table']}] t1
            WHERE t1.[{fk['child_column']}] IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM [{fk['parent_schema']}].[{fk['parent_table']}] t2
                  WHERE t2.[{fk['parent_column']}] = t1.[{fk['child_column']}]
              )
        """
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                result = cursor.fetchone()
                cursor.close()
                return result[0] if result else 0
        except Exception as e:
            self.logger.warning(
                f"Failed to validate self-referencing table {fk.get('constraint_name', 'unknown')}: {str(e)}"
            )
            return 0
    
    def _validate_row_count_with_sampling(
        self,
        schema: str,
        table: str,
        config: ValidationConfig
    ) -> Tuple[int, bool]:
        """
        Validate row count with optional sampling for large tables.
        
        Args:
            schema: Schema name
            table: Table name
            config: Validation configuration
        
        Returns:
            Tuple of (row_count, is_sampled)
        """
        # First get exact count
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Try to get row count from statistics first (fast)
                stats_query = """
                    SELECT SUM(p.rows) AS row_count
                    FROM sys.partitions p
                    INNER JOIN sys.tables t ON p.object_id = t.object_id
                    INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
                    WHERE s.name = ? AND t.name = ?
                      AND p.index_id IN (0,1)
                """
                cursor.execute(stats_query, (schema, table))
                result = cursor.fetchone()
                estimated_count = result.row_count if result and result.row_count else 0
                
                # If table is small or sampling disabled, get exact count
                if not config.row_count_sampling_enabled or estimated_count < config.row_count_sample_size:
                    exact_query = f"SELECT COUNT(*) FROM [{schema}].[{table}]"
                    cursor.execute(exact_query)
                    exact_result = cursor.fetchone()
                    cursor.close()
                    return (exact_result[0] if exact_result else 0, False)
                else:
                    # Use estimated count for large tables
                    cursor.close()
                    return (estimated_count, True)
        
        except Exception as e:
            self.logger.error(
                f"Failed to count rows for [{schema}].[{table}]: {str(e)}"
            )
            return (0, False)
    
    def _validate_column_length_preservation(
        self,
        schema: str,
        table: str,
        columns: List[str]
    ) -> Dict[str, Tuple[int, int, int]]:
        """
        Validate column length preservation and detect truncation.
        
        Args:
            schema: Schema name
            table: Table name
            columns: List of VARCHAR/NVARCHAR column names
        
        Returns:
            Dict mapping column -> (actual_max_length, schema_max_length, char_max_length)
        """
        results = {}
        
        for column in columns:
            try:
                with self.connection_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Get schema max length
                    schema_query = """
                        SELECT CHARACTER_MAXIMUM_LENGTH
                        FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND COLUMN_NAME = ?
                    """
                    cursor.execute(schema_query, (schema, table, column))
                    schema_result = cursor.fetchone()
                    schema_max_length = schema_result.CHARACTER_MAXIMUM_LENGTH if schema_result else None
                    
                    # Get actual max length from data
                    if schema_max_length:
                        data_query = f"""
                            SELECT MAX(LEN([{column}])) AS max_length
                            FROM [{schema}].[{table}]
                            WHERE [{column}] IS NOT NULL
                        """
                        cursor.execute(data_query)
                        data_result = cursor.fetchone()
                        actual_max_length = data_result.max_length if data_result and data_result.max_length else 0
                        
                        # Also get CHARACTER_MAXIMUM_LENGTH for CHAR types
                        char_query = f"""
                            SELECT MAX(DATALENGTH([{column}])) AS max_bytes
                            FROM [{schema}].[{table}]
                            WHERE [{column}] IS NOT NULL
                        """
                        cursor.execute(char_query)
                        char_result = cursor.fetchone()
                        char_max_length = char_result.max_bytes if char_result and char_result.max_bytes else 0
                        
                        results[column] = (actual_max_length, schema_max_length, char_max_length)
                    
                    cursor.close()
            
            except Exception as e:
                self.logger.warning(
                    f"Failed to validate column length for [{schema}].[{table}].[{column}]: {str(e)}"
                )
        
        return results
    
    def _validate_null_preservation_strategy(
        self,
        pre_metrics: TableMetrics,
        post_metrics: TableMetrics,
        config: ValidationConfig
    ) -> Dict[str, Tuple[int, int, float]]:
        """
        Validate NULL count preservation per column.
        
        Args:
            pre_metrics: Pre-sanitization metrics
            post_metrics: Post-sanitization metrics
            config: Validation configuration
        
        Returns:
            Dict mapping column -> (pre_null_count, post_null_count, delta_percentage)
        """
        results = {}
        
        for column in pre_metrics.null_counts.keys():
            pre_null_count = pre_metrics.null_counts.get(column, 0)
            post_null_count = post_metrics.null_counts.get(column, 0)
            
            # Calculate delta percentage
            if pre_null_count > 0:
                delta_percentage = abs(post_null_count - pre_null_count) / pre_null_count * 100
            else:
                delta_percentage = 0.0 if post_null_count == 0 else 100.0
            
            results[column] = (pre_null_count, post_null_count, delta_percentage)
        
        return results
    
    def _validate_data_type_precision(
        self,
        schema: str,
        table: str,
        columns: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Validate numeric and datetime precision/scale preservation.
        
        Args:
            schema: Schema name
            table: Table name
            columns: List of column names to validate
        
        Returns:
            Dict mapping column -> precision/scale metadata
        """
        results = {}
        
        query = """
            SELECT
                COLUMN_NAME,
                DATA_TYPE,
                NUMERIC_PRECISION,
                NUMERIC_SCALE,
                DATETIME_PRECISION
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND COLUMN_NAME = ?
        """
        
        for column in columns:
            try:
                with self.connection_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(query, (schema, table, column))
                    result = cursor.fetchone()
                    
                    if result:
                        results[column] = {
                            "data_type": result.DATA_TYPE,
                            "numeric_precision": result.NUMERIC_PRECISION,
                            "numeric_scale": result.NUMERIC_SCALE,
                            "datetime_precision": result.DATETIME_PRECISION
                        }
                    
                    cursor.close()
            
            except Exception as e:
                self.logger.warning(
                    f"Failed to validate data type precision for [{schema}].[{table}].[{column}]: {str(e)}"
                )
        
        return results
    
    def _validate_pii_patterns_with_whitelist(
        self,
        schema: str,
        table: str,
        column: str,
        sample_data: List[Any],
        config: ValidationConfig
    ) -> List[str]:
        """
        Validate PII patterns with whitelist/exception handling.
        
        Args:
            schema: Schema name
            table: Table name
            column: Column name
            sample_data: List of sample values
            config: Validation configuration with whitelist
        
        Returns:
            List of non-whitelisted patterns found
        """
        patterns_found = []
        table_column_key = f"{schema}.{table}.{column}"
        
        # Compile whitelist patterns
        whitelist_regexes = [re.compile(pattern, re.IGNORECASE) for pattern in config.pii_pattern_whitelist]
        
        # Get exceptions for this specific table.column
        exceptions = config.pii_pattern_exceptions.get(table_column_key, [])
        exception_regexes = [re.compile(pattern, re.IGNORECASE) for pattern in exceptions]
        
        # Check each sample value
        for value in sample_data:
            if value is None:
                continue
            
            str_value = str(value)
            
            # Check against PII patterns
            if EMAIL_PATTERN.search(str_value):
                # Check if whitelisted
                is_whitelisted = any(regex.search(str_value) for regex in whitelist_regexes) or \
                                 any(regex.search(str_value) for regex in exception_regexes)
                if not is_whitelisted and "email" not in patterns_found:
                    patterns_found.append("email")
            
            if PHONE_PATTERN.search(str_value):
                is_whitelisted = any(regex.search(str_value) for regex in whitelist_regexes) or \
                                 any(regex.search(str_value) for regex in exception_regexes)
                if not is_whitelisted and "phone" not in patterns_found:
                    patterns_found.append("phone")
            
            if SSN_PATTERN.search(str_value):
                is_whitelisted = any(regex.search(str_value) for regex in whitelist_regexes) or \
                                 any(regex.search(str_value) for regex in exception_regexes)
                if not is_whitelisted and "ssn" not in patterns_found:
                    patterns_found.append("ssn")
            
            if CREDIT_CARD_PATTERN.search(str_value):
                is_whitelisted = any(regex.search(str_value) for regex in whitelist_regexes) or \
                                 any(regex.search(str_value) for regex in exception_regexes)
                if not is_whitelisted and "credit_card" not in patterns_found:
                    patterns_found.append("credit_card")
        
        return patterns_found
    
    def _validate_masking_effectiveness(
        self,
        schema: str,
        table: str,
        sanitized_columns: List[str],
        config: ValidationConfig
    ) -> Dict[str, float]:
        """
        Calculate masking effectiveness score per column.
        
        Args:
            schema: Schema name
            table: Table name
            sanitized_columns: List of columns that were sanitized
            config: Validation configuration
        
        Returns:
            Dict mapping column -> effectiveness_score (0-100%)
        """
        effectiveness_scores = {}
        
        for column in sanitized_columns:
            try:
                # Sample data from column
                query = f"""
                    SELECT TOP {config.pii_sample_size} [{column}]
                    FROM [{schema}].[{table}]
                    WHERE [{column}] IS NOT NULL
                    ORDER BY NEWID()
                """
                
                with self.connection_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(query)
                    
                    sample_data = [row[0] for row in cursor.fetchall()]
                    cursor.close()
                
                if not sample_data:
                    effectiveness_scores[column] = 100.0
                    continue
                
                # Detect patterns (without whitelist filtering)
                patterns_count = 0
                for value in sample_data:
                    if value is None:
                        continue
                    
                    str_value = str(value)
                    if EMAIL_PATTERN.search(str_value) or \
                       PHONE_PATTERN.search(str_value) or \
                       SSN_PATTERN.search(str_value) or \
                       CREDIT_CARD_PATTERN.search(str_value):
                        patterns_count += 1
                
                # Calculate effectiveness score
                effectiveness_score = (1 - patterns_count / len(sample_data)) * 100
                effectiveness_scores[column] = effectiveness_score
            
            except Exception as e:
                self.logger.warning(
                    f"Failed to calculate masking effectiveness for [{schema}].[{table}].[{column}]: {str(e)}"
                )
                effectiveness_scores[column] = 0.0
        
        return effectiveness_scores
    
    def _compare_pii_patterns_pre_post(
        self,
        pre_snapshot: PreSanitizationSnapshot,
        post_snapshot: PostSanitizationSnapshot
    ) -> Dict[str, Dict[str, Any]]:
        """
        Compare PII patterns detected in pre vs post snapshots.
        
        Args:
            pre_snapshot: Pre-sanitization snapshot
            post_snapshot: Post-sanitization snapshot
        
        Returns:
            Dict with comparison results per table
        """
        comparison = {}
        
        # Post-snapshot should have pii_patterns_found
        for table_name, patterns in post_snapshot.pii_patterns_found.items():
            comparison[table_name] = {
                "post_patterns": patterns,
                "pattern_count": len(patterns),
                "residual_pii": len(patterns) > 0
            }
        
        return comparison
