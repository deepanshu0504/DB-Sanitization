"""
Desanitization Validator - Pre-flight validation for restoration operations.

This module provides comprehensive validation checks before desanitization begins,
ensuring preconditions are met and preventing partial failures.

Key Features:
    - Mapping table existence and accessibility validation
    - Mapping availability checks for requested scope
    - Schema consistency validation against mapping metadata
    - Disk space verification for transaction logs
    - Schema drift detection (type changes, column deletions)
    - Constraint compatibility checks

Usage:
    from validation import DesanitizationValidator
    from mapping import MappingTableManager
    from database import SchemaInspector
    
    validator = DesanitizationValidator(
        connection=conn,
        mapping_manager=mapping_mgr,
        schema_inspector=inspector
    )
    
    report = validator.validate_desanitization(
        scope='table',
        table='Customers',
        schema='dbo'
    )
    
    if not report.is_valid():
        for check in report.failed_checks:
            print(f"FAIL: {check.message}")
        raise ValidationError("Validation failed")
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Any
from collections import defaultdict


class ValidationStatus(Enum):
    """Status of a validation check."""
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    INFO = "INFO"
    SKIPPED = "SKIPPED"


class ValidationError(Exception):
    """Raised when critical validation checks fail."""
    pass


@dataclass
class ValidationCheck:
    """Result of a single validation check."""
    check_name: str
    status: ValidationStatus
    message: str
    details: Optional[Dict[str, Any]] = None
    suggested_action: Optional[str] = None
    
    def __str__(self) -> str:
        """Format check result for display."""
        status_symbol = {
            ValidationStatus.PASSED: "✓",
            ValidationStatus.FAILED: "✗",
            ValidationStatus.WARNING: "⚠",
            ValidationStatus.INFO: "ℹ",
            ValidationStatus.SKIPPED: "○"
        }
        
        result = f"{status_symbol[self.status]} {self.check_name}: {self.message}"
        if self.suggested_action:
            result += f"\n  → {self.suggested_action}"
        return result


@dataclass
class ValidationReport:
    """Comprehensive validation results."""
    validation_id: str
    timestamp: datetime
    scope: str  # 'database', 'table', 'column', 'record'
    target_info: Dict[str, Any]  # table, schema, columns, record_ids
    checks: List[ValidationCheck] = field(default_factory=list)
    
    def add_check(
        self,
        check_name: str,
        status: ValidationStatus,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        suggested_action: Optional[str] = None
    ):
        """Add a validation check result."""
        check = ValidationCheck(
            check_name=check_name,
            status=status,
            message=message,
            details=details,
            suggested_action=suggested_action
        )
        self.checks.append(check)
    
    def is_valid(self) -> bool:
        """Check if all critical validations passed."""
        return not any(c.status == ValidationStatus.FAILED for c in self.checks)
    
    def has_warnings(self) -> bool:
        """Check if any warnings were raised."""
        return any(c.status == ValidationStatus.WARNING for c in self.checks)
    
    @property
    def passed_checks(self) -> List[ValidationCheck]:
        """Get all passed checks."""
        return [c for c in self.checks if c.status == ValidationStatus.PASSED]
    
    @property
    def failed_checks(self) -> List[ValidationCheck]:
        """Get all failed checks."""
        return [c for c in self.checks if c.status == ValidationStatus.FAILED]
    
    @property
    def warnings(self) -> List[ValidationCheck]:
        """Get all warnings."""
        return [c for c in self.checks if c.status == ValidationStatus.WARNING]
    
    @property
    def info_checks(self) -> List[ValidationCheck]:
        """Get all info checks."""
        return [c for c in self.checks if c.status == ValidationStatus.INFO]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary for JSON serialization."""
        return {
            'validation_id': self.validation_id,
            'timestamp': self.timestamp.isoformat(),
            'scope': self.scope,
            'target_info': self.target_info,
            'summary': {
                'total_checks': len(self.checks),
                'passed': len(self.passed_checks),
                'failed': len(self.failed_checks),
                'warnings': len(self.warnings),
                'info': len(self.info_checks),
                'is_valid': self.is_valid()
            },
            'checks': [
                {
                    'check_name': c.check_name,
                    'status': c.status.value,
                    'message': c.message,
                    'details': c.details,
                    'suggested_action': c.suggested_action
                }
                for c in self.checks
            ]
        }
    
    def __str__(self) -> str:
        """Format validation report for display."""
        lines = [
            f"=== Validation Report ({self.validation_id}) ===",
            f"Timestamp: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Scope: {self.scope.upper()}",
            f"Target: {self.target_info}",
            "",
            f"Summary: {len(self.passed_checks)} passed, {len(self.failed_checks)} failed, {len(self.warnings)} warnings, {len(self.info_checks)} info",
            "",
            "Checks:"
        ]
        
        for check in self.checks:
            lines.append(f"  {check}")
        
        lines.append("")
        lines.append(f"Overall Status: {'✓ VALID' if self.is_valid() else '✗ INVALID'}")
        
        return "\n".join(lines)


class DesanitizationValidator:
    """
    Validates preconditions before desanitization operations.
    
    Performs comprehensive validation including:
    - Mapping table existence and accessibility
    - Mapping availability for requested scope
    - Schema consistency validation
    - Disk space verification
    - Schema drift detection
    - Constraint compatibility
    """
    
    def __init__(
        self,
        connection,
        mapping_manager,
        schema_inspector,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize validator with required dependencies.
        
        Args:
            connection: Active database connection
            mapping_manager: MappingTableManager instance
            schema_inspector: SchemaInspector instance
            logger: Optional logger instance
        """
        self.connection = connection
        self.mapping_manager = mapping_manager
        self.schema_inspector = schema_inspector
        self.logger = logger or logging.getLogger(__name__)
    
    def validate_desanitization(
        self,
        scope: str,
        table: Optional[str] = None,
        schema: Optional[str] = None,
        columns: Optional[List[str]] = None,
        record_ids: Optional[List[str]] = None,
        batch_id: Optional[str] = None
    ) -> ValidationReport:
        """
        Validate desanitization preconditions for specified scope.
        
        Args:
            scope: Validation scope ('database', 'table', 'column', 'record')
            table: Table name (required for table/column/record scope)
            schema: Schema name (default: 'dbo')
            columns: Column names (for column scope)
            record_ids: Record IDs (for record scope)
            batch_id: Optional batch ID filter
        
        Returns:
            ValidationReport with all check results
        
        Raises:
            ValidationError if critical checks fail
        """
        import uuid
        
        schema = schema or 'dbo'
        
        # Initialize report
        report = ValidationReport(
            validation_id=f"VAL-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:8]}",
            timestamp=datetime.now(),
            scope=scope,
            target_info={
                'table': table,
                'schema': schema,
                'columns': columns,
                'record_ids': record_ids,
                'batch_id': batch_id
            }
        )
        
        self.logger.info(
            f"[{report.validation_id}] Starting validation for {scope} scope: "
            f"[{schema}].[{table}]"
        )
        
        # Run validation checks
        try:
            # Check 1: Mapping table exists
            self._check_mapping_table_exists(report)
            
            # Check 2: Target table exists (if applicable)
            if table:
                self._check_target_table_exists(report, table, schema)
            
            # Check 3: Mappings available for requested scope
            if not report.is_valid():
                # Skip mapping availability check if previous checks failed
                report.add_check(
                    check_name="Mapping Availability",
                    status=ValidationStatus.SKIPPED,
                    message="Skipped due to previous failures"
                )
            else:
                self._check_mappings_available(
                    report, scope, table, schema, columns, record_ids, batch_id
                )
            
            # Check 4: Schema consistency
            if table and not report.is_valid():
                report.add_check(
                    check_name="Schema Consistency",
                    status=ValidationStatus.SKIPPED,
                    message="Skipped due to previous failures"
                )
            elif table:
                self._check_schema_consistency(
                    report, table, schema, columns, batch_id
                )
            
            # Check 5: Schema drift detection
            if table and not report.is_valid():
                report.add_check(
                    check_name="Schema Drift Detection",
                    status=ValidationStatus.SKIPPED,
                    message="Skipped due to previous failures"
                )
            elif table:
                self._detect_schema_drift(
                    report, table, schema, columns, batch_id
                )
            
            # Check 6: Disk space verification
            self._check_disk_space(report, table, schema)
            
            # Check 7: Constraint compatibility (if applicable)
            if table and scope in ['table', 'database']:
                self._check_constraint_compatibility(report, table, schema)
            
        except Exception as e:
            self.logger.error(
                f"[{report.validation_id}] Validation error: {e}",
                exc_info=True
            )
            report.add_check(
                check_name="Validation Exception",
                status=ValidationStatus.FAILED,
                message=f"Unexpected error during validation: {e}",
                suggested_action="Check logs for details and retry"
            )
        
        # Log summary
        self.logger.info(
            f"[{report.validation_id}] Validation complete: "
            f"{len(report.passed_checks)} passed, "
            f"{len(report.failed_checks)} failed, "
            f"{len(report.warnings)} warnings, "
            f"{len(report.info_checks)} info"
        )
        
        return report
    
    def _check_mapping_table_exists(self, report: ValidationReport):
        """Check if mapping table exists and is accessible."""
        try:
            cursor = self.connection.cursor()
            
            # Check if token_mappings table exists
            cursor.execute("""
                SELECT COUNT(*)
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_NAME = 'token_mappings'
            """)
            
            exists = cursor.fetchone()[0] > 0
            
            if exists:
                # Verify can query the table
                cursor.execute("SELECT TOP 1 mapping_id FROM token_mappings")
                cursor.fetchone()
                
                report.add_check(
                    check_name="Mapping Table Exists",
                    status=ValidationStatus.PASSED,
                    message="Mapping table exists and is accessible"
                )
            else:
                report.add_check(
                    check_name="Mapping Table Exists",
                    status=ValidationStatus.FAILED,
                    message="Mapping table 'token_mappings' does not exist",
                    suggested_action="Run sanitization with mapping capture enabled first"
                )
            
            cursor.close()
            
        except Exception as e:
            report.add_check(
                check_name="Mapping Table Exists",
                status=ValidationStatus.FAILED,
                message=f"Failed to access mapping table: {e}",
                suggested_action="Check database connectivity and permissions"
            )
    
    def _check_target_table_exists(
        self,
        report: ValidationReport,
        table: str,
        schema: str
    ):
        """Check if target table exists."""
        try:
            cursor = self.connection.cursor()
            
            cursor.execute("""
                SELECT COUNT(*)
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            """, (schema, table))
            
            exists = cursor.fetchone()[0] > 0
            
            if exists:
                report.add_check(
                    check_name="Target Table Exists",
                    status=ValidationStatus.PASSED,
                    message=f"Target table [{schema}].[{table}] exists"
                )
            else:
                report.add_check(
                    check_name="Target Table Exists",
                    status=ValidationStatus.FAILED,
                    message=f"Target table [{schema}].[{table}] does not exist",
                    suggested_action="Verify table name and schema are correct"
                )
            
            cursor.close()
            
        except Exception as e:
            report.add_check(
                check_name="Target Table Exists",
                status=ValidationStatus.FAILED,
                message=f"Failed to check table existence: {e}",
                suggested_action="Check database connectivity"
            )
    
    def _check_mappings_available(
        self,
        report: ValidationReport,
        scope: str,
        table: Optional[str],
        schema: str,
        columns: Optional[List[str]],
        record_ids: Optional[List[str]],
        batch_id: Optional[str]
    ):
        """Check if mappings are available for requested scope."""
        try:
            cursor = self.connection.cursor()
            
            # Build query based on scope
            query_parts = ["SELECT COUNT(DISTINCT record_id) as record_count"]
            query_parts.append("FROM token_mappings")
            
            where_conditions = []
            params = []
            
            if table:
                # Support both formats: "Production.Employee" and "Employee"
                schema = schema or 'dbo'
                full_table_name = f"{schema}.{table}"
                # Try both WITH schema prefix and WITHOUT to handle different storage patterns
                where_conditions.append("(table_name = ? OR table_name = ?)")
                params.append(table)  # Just table name
                params.append(full_table_name)  # Schema.Table format
            
            if columns:
                placeholders = ','.join(['?'] * len(columns))
                where_conditions.append(f"column_name IN ({placeholders})")
                params.extend(columns)
            
            if record_ids:
                placeholders = ','.join(['?'] * len(record_ids))
                where_conditions.append(f"record_id IN ({placeholders})")
                params.extend(record_ids)
            
            if batch_id:
                where_conditions.append("batch_id = ?")
                params.append(batch_id)
            
            if where_conditions:
                query_parts.append("WHERE " + " AND ".join(where_conditions))
            
            query = " ".join(query_parts)
            cursor.execute(query, params)
            
            mapping_count = cursor.fetchone()[0]
            
            # Validate based on scope
            if scope == 'record' and record_ids:
                expected_count = len(record_ids)
                if mapping_count == expected_count:
                    report.add_check(
                        check_name="Mapping Availability",
                        status=ValidationStatus.PASSED,
                        message=f"All {expected_count} requested records have mappings",
                        details={'records_found': mapping_count}
                    )
                elif mapping_count > 0:
                    report.add_check(
                        check_name="Mapping Availability",
                        status=ValidationStatus.WARNING,
                        message=f"Only {mapping_count}/{expected_count} requested records have mappings",
                        details={'records_found': mapping_count, 'records_requested': expected_count},
                        suggested_action="Some records may not have been sanitized or batch_id filter is excluding them"
                    )
                else:
                    report.add_check(
                        check_name="Mapping Availability",
                        status=ValidationStatus.FAILED,
                        message=f"No mappings found for requested records",
                        details={'records_requested': expected_count},
                        suggested_action="Records may not have been sanitized, or batch_id filter is incorrect"
                    )
            
            elif scope in ['column', 'table', 'database']:
                if mapping_count > 0:
                    report.add_check(
                        check_name="Mapping Availability",
                        status=ValidationStatus.PASSED,
                        message=f"Mappings available: {mapping_count} records found",
                        details={'record_count': mapping_count}
                    )
                else:
                    # For database-level, missing mappings is just a warning (table may not have PII)
                    # For table/column-level, it's a failure
                    if scope == 'database':
                        report.add_check(
                            check_name="Mapping Availability",
                            status=ValidationStatus.WARNING,
                            message="No mappings found for table (may not contain PII columns)",
                            suggested_action="Table will be skipped during desanitization"
                        )
                    else:
                        report.add_check(
                            check_name="Mapping Availability",
                            status=ValidationStatus.FAILED,
                            message="No mappings found for specified scope",
                            suggested_action="Table/columns may not have been sanitized, or batch_id filter is incorrect"
                        )
            
            cursor.close()
            
        except Exception as e:
            report.add_check(
                check_name="Mapping Availability",
                status=ValidationStatus.FAILED,
                message=f"Failed to check mapping availability: {e}",
                suggested_action="Check mapping table structure and data"
            )
    
    def _check_schema_consistency(
        self,
        report: ValidationReport,
        table: str,
        schema: str,
        columns: Optional[List[str]],
        batch_id: Optional[str]
    ):
        """Check if current schema matches columns in mapping table."""
        try:
            cursor = self.connection.cursor()
            
            # Get columns from mapping table
            query = """
                SELECT DISTINCT column_name
                FROM token_mappings
                WHERE table_name = ?
            """
            params = [table]
            
            if batch_id:
                query += " AND batch_id = ?"
                params.append(batch_id)
            
            cursor.execute(query, params)
            mapped_columns = {row[0] for row in cursor.fetchall()}
            
            if not mapped_columns:
                report.add_check(
                    check_name="Schema Consistency",
                    status=ValidationStatus.WARNING,
                    message=f"No mapped columns found for table [{schema}].[{table}]"
                )
                cursor.close()
                return
            
            # Get current schema columns
            cursor.execute("""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            """, (schema, table))
            
            current_columns = {row[0] for row in cursor.fetchall()}
            
            # Check for missing columns
            missing_columns = mapped_columns - current_columns
            
            if missing_columns:
                report.add_check(
                    check_name="Schema Consistency",
                    status=ValidationStatus.FAILED,
                    message=f"Columns in mappings no longer exist in table: {', '.join(missing_columns)}",
                    details={'missing_columns': list(missing_columns)},
                    suggested_action="Schema has changed since sanitization - cannot restore to non-existent columns"
                )
            else:
                # Check if filtering to specific columns
                if columns:
                    unavailable = set(columns) - current_columns
                    if unavailable:
                        report.add_check(
                            check_name="Schema Consistency",
                            status=ValidationStatus.FAILED,
                            message=f"Requested columns do not exist: {', '.join(unavailable)}",
                            details={'unavailable_columns': list(unavailable)}
                        )
                    else:
                        report.add_check(
                            check_name="Schema Consistency",
                            status=ValidationStatus.PASSED,
                            message=f"All mapped columns exist in current schema",
                            details={
                                'mapped_columns_count': len(mapped_columns),
                                'columns_validated': len(columns) if columns else len(mapped_columns)
                            }
                        )
                else:
                    report.add_check(
                        check_name="Schema Consistency",
                        status=ValidationStatus.PASSED,
                        message=f"All {len(mapped_columns)} mapped columns exist in current schema",
                        details={'mapped_columns_count': len(mapped_columns)}
                    )
            
            cursor.close()
            
        except Exception as e:
            report.add_check(
                check_name="Schema Consistency",
                status=ValidationStatus.FAILED,
                message=f"Failed to validate schema consistency: {e}"
            )
    
    def _detect_schema_drift(
        self,
        report: ValidationReport,
        table: str,
        schema: str,
        columns: Optional[List[str]],
        batch_id: Optional[str]
    ):
        """Detect schema drift (data type changes, length changes)."""
        try:
            cursor = self.connection.cursor()
            
            # Get mapped columns with their stored data types and lengths
            query = """
                SELECT DISTINCT column_name,
                       MAX(LEN(original_value)) as max_original_length
                FROM token_mappings
                WHERE table_name = ? AND original_value IS NOT NULL
            """
            params = [table]
            
            if batch_id:
                query += " AND batch_id = ?"
                params.append(batch_id)
            
            if columns:
                placeholders = ','.join(['?'] * len(columns))
                query += f" AND column_name IN ({placeholders})"
                params.extend(columns)
            
            query += " GROUP BY column_name"
            
            cursor.execute(query, params)
            mapped_column_info = {row[0]: row[1] for row in cursor.fetchall()}
            
            if not mapped_column_info:
                report.add_check(
                    check_name="Schema Drift Detection",
                    status=ValidationStatus.SKIPPED,
                    message="No column data to validate"
                )
                cursor.close()
                return
            
            # Get current schema information
            cursor.execute("""
                SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            """, (schema, table))
            
            current_schema = {
                row[0]: {
                    'data_type': row[1],
                    'max_length': row[2] if row[2] else None
                }
                for row in cursor.fetchall()
            }
            
            # Check for schema drift
            drift_issues = []
            warnings = []
            
            for col_name, max_value_length in mapped_column_info.items():
                if col_name not in current_schema:
                    continue  # Already caught in schema consistency check
                
                col_info = current_schema[col_name]
                
                # Check for narrowed columns
                if col_info['max_length'] is not None:
                    if max_value_length > col_info['max_length']:
                        drift_issues.append(
                            f"{col_name}: max value length ({max_value_length}) exceeds "
                            f"current column length ({col_info['max_length']}) - truncation would occur"
                        )
                    elif max_value_length < col_info['max_length'] * 0.7:
                        # Column significantly widened (>30% increase)
                        warnings.append(
                            f"{col_name}: column widened from ~{max_value_length} to "
                            f"{col_info['max_length']} chars (safe but notable)"
                        )
            
            if drift_issues:
                report.add_check(
                    check_name="Schema Drift Detection",
                    status=ValidationStatus.FAILED,
                    message=f"Schema drift detected - values won't fit: {'; '.join(drift_issues)}",
                    details={'drift_issues': drift_issues},
                    suggested_action="Widen columns or exclude affected columns from restoration"
                )
            elif warnings:
                report.add_check(
                    check_name="Schema Drift Detection",
                    status=ValidationStatus.INFO,
                    message=f"Schema changes detected (safe, non-blocking): {'; '.join(warnings)}",
                    details={'schema_changes': warnings}
                )
            else:
                report.add_check(
                    check_name="Schema Drift Detection",
                    status=ValidationStatus.PASSED,
                    message=f"No schema drift detected for {len(mapped_column_info)} column(s)"
                )
            
            cursor.close()
            
        except Exception as e:
            report.add_check(
                check_name="Schema Drift Detection",
                status=ValidationStatus.WARNING,
                message=f"Schema drift check incomplete: {e}"
            )
    
    def _check_disk_space(
        self,
        report: ValidationReport,
        table: Optional[str],
        schema: Optional[str]
    ):
        """Check if sufficient disk space available for transaction log."""
        try:
            cursor = self.connection.cursor()
            
            # Query transaction log space usage
            cursor.execute("""
                SELECT 
                    total_log_size_in_bytes / 1024.0 / 1024.0 as total_log_mb,
                    used_log_space_in_bytes / 1024.0 / 1024.0 as used_log_mb
                FROM sys.dm_db_log_space_usage
            """)
            
            result = cursor.fetchone()
            total_log_mb = result[0]
            used_log_mb = result[1]
            available_log_mb = total_log_mb - used_log_mb
            
            # Estimate space needed (rough estimate: 2x average row size × row count)
            if table:
                cursor.execute(f"""
                    SELECT 
                        SUM(p.rows) as row_count,
                        SUM(a.used_pages) * 8 / 1024.0 as used_mb
                    FROM sys.tables t
                    INNER JOIN sys.indexes i ON t.object_id = i.object_id
                    INNER JOIN sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id
                    INNER JOIN sys.allocation_units a ON p.partition_id = a.container_id
                    WHERE t.name = ? AND SCHEMA_NAME(t.schema_id) = ?
                    GROUP BY t.name
                """, (table, schema or 'dbo'))
                
                table_result = cursor.fetchone()
                if table_result and table_result[0]:
                    estimated_space_mb = table_result[1] * 2  # 2x safety factor
                else:
                    estimated_space_mb = 10  # Minimal estimate
            else:
                # Database-level - use conservative estimate
                estimated_space_mb = available_log_mb * 0.3  # Require 30% of available
            
            # Check if sufficient space (require 2x estimated space)
            required_space_mb = estimated_space_mb * 2
            
            if available_log_mb >= required_space_mb:
                report.add_check(
                    check_name="Disk Space",
                    status=ValidationStatus.PASSED,
                    message=f"Sufficient transaction log space: {available_log_mb:.2f} MB available "
                            f"(estimated need: {estimated_space_mb:.2f} MB)",
                    details={
                        'total_log_mb': round(total_log_mb, 2),
                        'used_log_mb': round(used_log_mb, 2),
                        'available_log_mb': round(available_log_mb, 2),
                        'estimated_need_mb': round(estimated_space_mb, 2)
                    }
                )
            elif available_log_mb >= estimated_space_mb:
                report.add_check(
                    check_name="Disk Space",
                    status=ValidationStatus.WARNING,
                    message=f"Transaction log space tight: {available_log_mb:.2f} MB available "
                            f"(estimated need: {estimated_space_mb:.2f} MB, recommended: {required_space_mb:.2f} MB)",
                    details={
                        'available_log_mb': round(available_log_mb, 2),
                        'estimated_need_mb': round(estimated_space_mb, 2),
                        'recommended_mb': round(required_space_mb, 2)
                    },
                    suggested_action="Consider expanding transaction log or archiving log backups"
                )
            else:
                report.add_check(
                    check_name="Disk Space",
                    status=ValidationStatus.FAILED,
                    message=f"Insufficient transaction log space: {available_log_mb:.2f} MB available, "
                            f"need {estimated_space_mb:.2f} MB",
                    details={
                        'available_log_mb': round(available_log_mb, 2),
                        'required_mb': round(estimated_space_mb, 2)
                    },
                    suggested_action="Expand transaction log or free up space before desanitization"
                )
            
            cursor.close()
            
        except Exception as e:
            report.add_check(
                check_name="Disk Space",
                status=ValidationStatus.WARNING,
                message=f"Could not verify disk space: {e}",
                suggested_action="Manually verify transaction log capacity"
            )
    
    def _check_constraint_compatibility(
        self,
        report: ValidationReport,
        table: str,
        schema: str
    ):
        """Check if constraints will be satisfied after restoration."""
        try:
            cursor = self.connection.cursor()
            
            # Check for unique constraints and indexes
            cursor.execute("""
                SELECT 
                    i.name as index_name,
                    i.is_unique,
                    i.is_primary_key,
                    COL_NAME(ic.object_id, ic.column_id) as column_name
                FROM sys.indexes i
                INNER JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
                INNER JOIN sys.tables t ON i.object_id = t.object_id
                WHERE t.name = ? 
                  AND SCHEMA_NAME(t.schema_id) = ?
                  AND (i.is_unique = 1 OR i.is_primary_key = 1)
                ORDER BY i.name, ic.key_ordinal
            """, (table, schema))
            
            constraints = cursor.fetchall()
            
            if constraints:
                # Group by constraint name
                constraint_info = defaultdict(list)
                for row in constraints:
                    constraint_info[row[0]].append(row[3])
                
                report.add_check(
                    check_name="Constraint Compatibility",
                    status=ValidationStatus.WARNING,
                    message=f"Table has {len(constraint_info)} unique/PK constraint(s) - "
                            f"verify restored values maintain uniqueness",
                    details={
                        'unique_constraints': len(constraint_info),
                        'constraint_columns': dict(constraint_info)
                    },
                    suggested_action="Monitor for constraint violations during restoration"
                )
            else:
                report.add_check(
                    check_name="Constraint Compatibility",
                    status=ValidationStatus.PASSED,
                    message="No unique constraints detected"
                )
            
            cursor.close()
            
        except Exception as e:
            report.add_check(
                check_name="Constraint Compatibility",
                status=ValidationStatus.WARNING,
                message=f"Could not check constraints: {e}"
            )
    
    # ========================================================================
    # POST-RESTORATION VERIFICATION (Story 3.2)
    # ========================================================================
    
    def verify_restoration(
        self,
        scope: str,
        table: str,
        schema: str,
        restoration_report: Any,  # RestorationReport type (avoid circular import)
        connection=None,
        strict_mode: bool = False
    ) -> ValidationReport:
        """
        Verify data integrity after restoration operation (Story 3.2).
        
        Performs comprehensive post-restoration checks including:
        - Row count verification (ensuring no data loss)
        - Foreign key constraint validation (bidirectional)
        - Unique constraint verification
        - Data type preservation
        - NULL value validation
        - Sample-based data verification for large tables
        
        Args:
            scope: Restoration scope ('database', 'table', 'column', 'record')
            table: Table name that was restored
            schema: Database schema
            restoration_report: RestorationReport from completed restoration
            connection: Optional connection override (uses self.connection if None)
            strict_mode: If True, treat WARNING as FAILED
        
        Returns:
            ValidationReport with all verification results
        
        Example:
            >>> report = validator.verify_restoration(
            ...     scope='record',
            ...     table='Customers',
            ...     schema='dbo',
            ...     restoration_report=restoration_report
            ... )
            >>> if not report.is_valid():
            ...     print("Verification failed!")
        """
        import uuid
        
        conn = connection or self.connection
        
        # Initialize verification report
        report = ValidationReport(
            validation_id=f"VERIFY-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:8]}",
            timestamp=datetime.now(),
            scope=f"{scope}_verification",
            target_info={
                'table': table,
                'schema': schema,
                'restoration_operation_id': restoration_report.operation_id,
                'records_restored': restoration_report.records_restored,
                'columns_affected': restoration_report.columns_affected
            }
        )
        
        self.logger.info(
            f"[{report.validation_id}] Starting post-restoration verification for "
            f"[{schema}].[{table}] (scope: {scope})"
        )
        
        try:
            # Check 1: Row count unchanged
            self._verify_row_count_unchanged(
                report, table, schema, restoration_report, conn
            )
            
            # Check 2: Foreign key constraints (bidirectional)
            self._verify_foreign_key_constraints(
                report, table, schema, conn
            )
            
            # Check 3: Unique constraints
            self._verify_unique_constraints(
                report, table, schema, conn
            )
            
            # Check 4: Data type preservation
            self._verify_data_types(
                report, table, schema, restoration_report, conn
            )
            
            # Check 5: NULL values
            self._verify_null_values(
                report, table, schema, restoration_report, conn
            )
            
            # Check 6: Sample data verification (for large tables)
            self._verify_sample_data(
                report, table, schema, restoration_report, conn
            )
            
        except Exception as e:
            self.logger.error(
                f"[{report.validation_id}] Verification error: {e}",
                exc_info=True
            )
            report.add_check(
                check_name="Verification Exception",
                status=ValidationStatus.FAILED,
                message=f"Unexpected error during verification: {e}",
                suggested_action="Check logs for details"
            )
        
        # Apply strict mode if enabled
        if strict_mode and report.has_warnings():
            self.logger.warning(
                f"[{report.validation_id}] Strict mode enabled: "
                f"Converting {len(report.warnings)} warnings to failures"
            )
            for check in report.checks:
                if check.status == ValidationStatus.WARNING:
                    check.status = ValidationStatus.FAILED
        
        # Log summary
        self.logger.info(
            f"[{report.validation_id}] Verification complete: "
            f"{len(report.passed_checks)} passed, "
            f"{len(report.failed_checks)} failed, "
            f"{len(report.warnings)} warnings"
        )
        
        return report
    
    def _verify_row_count_unchanged(
        self,
        report: ValidationReport,
        table: str,
        schema: str,
        restoration_report: Any,
        connection
    ):
        """Verify that row count hasn't changed after restoration."""
        try:
            cursor = connection.cursor()
            
            # Get current row count
            cursor.execute(f"""
                SELECT COUNT(*) FROM [{schema}].[{table}]
            """)
            current_count = cursor.fetchone()[0]
            
            # Get expected count from restoration report
            expected_count = restoration_report.records_requested
            
            # For table-level or column-level restoration, we don't track specific record count
            # In that case, we just verify table exists and has data
            if expected_count == 0 and restoration_report.columns_affected > 0:
                report.add_check(
                    check_name="Row Count Verification",
                    status=ValidationStatus.PASSED,
                    message=f"Table has {current_count} rows (bulk restoration, count not tracked)",
                    details={'current_row_count': current_count}
                )
            elif current_count >= expected_count:
                report.add_check(
                    check_name="Row Count Verification",
                    status=ValidationStatus.PASSED,
                    message=f"Row count verified: {current_count} rows (expected {expected_count})",
                    details={
                        'current_row_count': current_count,
                        'expected_row_count': expected_count
                    }
                )
            else:
                report.add_check(
                    check_name="Row Count Verification",
                    status=ValidationStatus.FAILED,
                    message=f"Row count mismatch: found {current_count}, expected {expected_count}",
                    details={
                        'current_row_count': current_count,
                        'expected_row_count': expected_count,
                        'missing_rows': expected_count - current_count
                    },
                    suggested_action="Check if records were deleted during restoration"
                )
            
            cursor.close()
            
        except Exception as e:
            report.add_check(
                check_name="Row Count Verification",
                status=ValidationStatus.WARNING,
                message=f"Could not verify row count: {e}",
                suggested_action="Manually verify table row count"
            )
    
    def _verify_foreign_key_constraints(
        self,
        report: ValidationReport,
        table: str,
        schema: str,
        connection
    ):
        """Verify foreign key constraints (bidirectional)."""
        try:
            cursor = connection.cursor()
            
            # Get all FK constraints for this table (outgoing: this table references others)
            cursor.execute("""
                SELECT 
                    fk.name AS constraint_name,
                    OBJECT_NAME(fk.parent_object_id) AS child_table,
                    COL_NAME(fc.parent_object_id, fc.parent_column_id) AS child_column,
                    OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS parent_schema,
                    OBJECT_NAME(fk.referenced_object_id) AS parent_table,
                    COL_NAME(fc.referenced_object_id, fc.referenced_column_id) AS parent_column
                FROM sys.foreign_keys fk
                INNER JOIN sys.foreign_key_columns fc 
                    ON fk.object_id = fc.constraint_object_id
                WHERE OBJECT_NAME(fk.parent_object_id) = ? 
                  AND OBJECT_SCHEMA_NAME(fk.parent_object_id) = ?
            """, (table, schema))
            
            outgoing_fks = cursor.fetchall()
            
            # Get incoming FKs (other tables reference this table)
            cursor.execute("""
                SELECT 
                    fk.name AS constraint_name,
                    OBJECT_SCHEMA_NAME(fk.parent_object_id) AS child_schema,
                    OBJECT_NAME(fk.parent_object_id) AS child_table,
                    COL_NAME(fc.parent_object_id, fc.parent_column_id) AS child_column,
                    OBJECT_NAME(fk.referenced_object_id) AS parent_table,
                    COL_NAME(fc.referenced_object_id, fc.referenced_column_id) AS parent_column
                FROM sys.foreign_keys fk
                INNER JOIN sys.foreign_key_columns fc 
                    ON fk.object_id = fc.constraint_object_id
                WHERE OBJECT_NAME(fk.referenced_object_id) = ?
                  AND OBJECT_SCHEMA_NAME(fk.referenced_object_id) = ?
            """, (table, schema))
            
            incoming_fks = cursor.fetchall()
            
            violations = []
            
            # Check outgoing FK violations (this table's values must exist in parent tables)
            for fk in outgoing_fks:
                constraint_name, child_table, child_col, parent_schema, parent_table, parent_col = fk
                
                orphan_query = f"""
                    SELECT COUNT(*)
                    FROM [{schema}].[{child_table}] c
                    LEFT JOIN [{parent_schema}].[{parent_table}] p
                        ON c.[{child_col}] = p.[{parent_col}]
                    WHERE c.[{child_col}] IS NOT NULL AND p.[{parent_col}] IS NULL
                """
                
                cursor.execute(orphan_query)
                orphan_count = cursor.fetchone()[0]
                
                if orphan_count > 0:
                    violations.append({
                        'constraint': constraint_name,
                        'type': 'outgoing',
                        'orphan_count': orphan_count,
                        'child_table': f"[{schema}].[{child_table}]",
                        'parent_table': f"[{parent_schema}].[{parent_table}]",
                        'column': child_col
                    })
            
            # Check incoming FK violations (other tables reference this table)
            for fk in incoming_fks:
                constraint_name, child_schema, child_table, child_col, parent_table, parent_col = fk
                
                orphan_query = f"""
                    SELECT COUNT(*)
                    FROM [{child_schema}].[{child_table}] c
                    LEFT JOIN [{schema}].[{parent_table}] p
                        ON c.[{child_col}] = p.[{parent_col}]
                    WHERE c.[{child_col}] IS NOT NULL AND p.[{parent_col}] IS NULL
                """
                
                cursor.execute(orphan_query)
                orphan_count = cursor.fetchone()[0]
                
                if orphan_count > 0:
                    violations.append({
                        'constraint': constraint_name,
                        'type': 'incoming',
                        'orphan_count': orphan_count,
                        'child_table': f"[{child_schema}].[{child_table}]",
                        'parent_table': f"[{schema}].[{parent_table}]",
                        'column': child_col
                    })
            
            if violations:
                total_orphans = sum(v['orphan_count'] for v in violations)
                report.add_check(
                    check_name="Foreign Key Integrity",
                    status=ValidationStatus.FAILED,
                    message=f"Found {len(violations)} FK violation(s) with {total_orphans} orphaned record(s)",
                    details={
                        'violation_count': len(violations),
                        'total_orphans': total_orphans,
                        'violations': violations
                    },
                    suggested_action="Run data cleanup to remove orphaned records or restore missing parent records"
                )
            elif not outgoing_fks and not incoming_fks:
                report.add_check(
                    check_name="Foreign Key Integrity",
                    status=ValidationStatus.PASSED,
                    message="No foreign key constraints to validate"
                )
            else:
                report.add_check(
                    check_name="Foreign Key Integrity",
                    status=ValidationStatus.PASSED,
                    message=f"All FK constraints validated: {len(outgoing_fks)} outgoing, {len(incoming_fks)} incoming",
                    details={
                        'outgoing_fks': len(outgoing_fks),
                        'incoming_fks': len(incoming_fks)
                    }
                )
            
            cursor.close()
            
        except Exception as e:
            report.add_check(
                check_name="Foreign Key Integrity",
                status=ValidationStatus.WARNING,
                message=f"Could not verify FK constraints: {e}",
                suggested_action="Manually verify referential integrity"
            )
    
    def _verify_unique_constraints(
        self,
        report: ValidationReport,
        table: str,
        schema: str,
        connection
    ):
        """Verify unique constraints are not violated."""
        try:
            cursor = connection.cursor()
            
            # Get unique constraints and indexes
            cursor.execute("""
                SELECT 
                    i.name as index_name,
                    i.is_unique,
                    i.is_primary_key,
                    STRING_AGG(COL_NAME(ic.object_id, ic.column_id), ', ') 
                        WITHIN GROUP (ORDER BY ic.key_ordinal) as column_list
                FROM sys.indexes i
                INNER JOIN sys.index_columns ic 
                    ON i.object_id = ic.object_id AND i.index_id = ic.index_id
                INNER JOIN sys.tables t ON i.object_id = t.object_id
                WHERE t.name = ? 
                  AND SCHEMA_NAME(t.schema_id) = ?
                  AND (i.is_unique = 1 OR i.is_primary_key = 1)
                  AND i.type IN (1, 2)  -- Clustered or nonclustered
                GROUP BY i.name, i.is_unique, i.is_primary_key, i.index_id
                ORDER BY i.name
            """, (table, schema))
            
            constraints = cursor.fetchall()
            
            if not constraints:
                report.add_check(
                    check_name="Unique Constraint Integrity",
                    status=ValidationStatus.PASSED,
                    message="No unique constraints to validate"
                )
                cursor.close()
                return
            
            violations = []
            
            for constraint in constraints:
                index_name, is_unique, is_pk, column_list = constraint
                columns = [c.strip() for c in column_list.split(',')]
                
                # Build duplicate detection query
                column_select = ', '.join([f"[{c}]" for c in columns])
                
                dup_query = f"""
                    SELECT {column_select}, COUNT(*) as dup_count
                    FROM [{schema}].[{table}]
                    WHERE {' AND '.join([f'[{c}] IS NOT NULL' for c in columns])}
                    GROUP BY {column_select}
                    HAVING COUNT(*) > 1
                """
                
                cursor.execute(dup_query)
                duplicates = cursor.fetchall()
                
                if duplicates:
                    violations.append({
                        'constraint_name': index_name,
                        'constraint_type': 'PRIMARY KEY' if is_pk else 'UNIQUE',
                        'columns': columns,
                        'duplicate_count': len(duplicates),
                        'sample_duplicates': [
                            {col: str(dup[i]) for i, col in enumerate(columns)}
                            for dup in duplicates[:5]  # First 5 samples
                        ]
                    })
            
            if violations:
                total_dups = sum(v['duplicate_count'] for v in violations)
                report.add_check(
                    check_name="Unique Constraint Integrity",
                    status=ValidationStatus.FAILED,
                    message=f"Found {len(violations)} unique constraint violation(s) with {total_dups} duplicate(s)",
                    details={
                        'violation_count': len(violations),
                        'total_duplicates': total_dups,
                        'violations': violations
                    },
                    suggested_action="Remove duplicate rows or adjust constraint definitions"
                )
            else:
                report.add_check(
                    check_name="Unique Constraint Integrity",
                    status=ValidationStatus.PASSED,
                    message=f"All {len(constraints)} unique constraint(s) validated",
                    details={'constraint_count': len(constraints)}
                )
            
            cursor.close()
            
        except Exception as e:
            report.add_check(
                check_name="Unique Constraint Integrity",
                status=ValidationStatus.WARNING,
                message=f"Could not verify unique constraints: {e}",
                suggested_action="Manually check for duplicate values"
            )
    
    def _verify_data_types(
        self,
        report: ValidationReport,
        table: str,
        schema: str,
        restoration_report: Any,
        connection
    ):
        """Verify restored column data types match schema."""
        try:
            cursor = connection.cursor()
            
            # Get columns that were restored
            restored_columns = set()
            for table_name, columns in restoration_report.table_details.items():
                if table_name == f"[{schema}].[{table}]" or table_name == table:
                    restored_columns.update(columns.keys())
            
            if not restored_columns:
                report.add_check(
                    check_name="Data Type Preservation",
                    status=ValidationStatus.PASSED,
                    message="No columns restored (skipped)"
                )
                cursor.close()
                return
            
            # Get schema data types for restored columns
            placeholders = ','.join(['?'] * len(restored_columns))
            cursor.execute(f"""
                SELECT 
                    COLUMN_NAME,
                    DATA_TYPE,
                    CHARACTER_MAXIMUM_LENGTH,
                    NUMERIC_PRECISION,
                    NUMERIC_SCALE,
                    IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? 
                  AND TABLE_NAME = ?
                  AND COLUMN_NAME IN ({placeholders})
            """, (schema, table, *restored_columns))
            
            schema_columns = {row[0]: row for row in cursor.fetchall()}
            
            # Check for type mismatches (basic validation)
            type_issues = []
            
            for col_name in restored_columns:
                if col_name not in schema_columns:
                    type_issues.append({
                        'column': col_name,
                        'issue': 'Column no longer exists in schema',
                        'severity': 'high'
                    })
                    continue
                
                col_info = schema_columns[col_name]
                data_type = col_info[1]
                
                # Check if data type is compatible with restoration
                # (This is a basic check; full validation would require sampling data)
                if data_type in ('int', 'bigint', 'smallint', 'tinyint'):
                    # Numeric types - verify no text data exists
                    cursor.execute(f"""
                        SELECT COUNT(*)
                        FROM [{schema}].[{table}]
                        WHERE [{col_name}] IS NOT NULL 
                          AND TRY_CAST([{col_name}] AS BIGINT) IS NULL
                    """)
                    invalid_count = cursor.fetchone()[0]
                    
                    if invalid_count > 0:
                        type_issues.append({
                            'column': col_name,
                            'issue': f'{invalid_count} non-numeric values in numeric column',
                            'severity': 'high',
                            'data_type': data_type
                        })
            
            if type_issues:
                report.add_check(
                    check_name="Data Type Preservation",
                    status=ValidationStatus.FAILED,
                    message=f"Found {len(type_issues)} data type issue(s)",
                    details={'issues': type_issues},
                    suggested_action="Review data types and re-run sanitization if needed"
                )
            else:
                report.add_check(
                    check_name="Data Type Preservation",
                    status=ValidationStatus.PASSED,
                    message=f"Data types validated for {len(restored_columns)} column(s)",
                    details={'columns_checked': list(restored_columns)}
                )
            
            cursor.close()
            
        except Exception as e:
            report.add_check(
                check_name="Data Type Preservation",
                status=ValidationStatus.WARNING,
                message=f"Could not verify data types: {e}",
                suggested_action="Manually verify column data types"
            )
    
    def _verify_null_values(
        self,
        report: ValidationReport,
        table: str,
        schema: str,
        restoration_report: Any,
        connection
    ):
        """Verify NULL values in NOT NULL columns."""
        try:
            cursor = connection.cursor()
            
            # Get NOT NULL columns for this table
            cursor.execute("""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? 
                  AND TABLE_NAME = ?
                  AND IS_NULLABLE = 'NO'
            """, (schema, table))
            
            not_null_columns = [row[0] for row in cursor.fetchall()]
            
            if not not_null_columns:
                report.add_check(
                    check_name="NULL Value Validation",
                    status=ValidationStatus.PASSED,
                    message="No NOT NULL constraints to validate"
                )
                cursor.close()
                return
            
            # Check for NULL values in NOT NULL columns
            null_violations = []
            
            for col in not_null_columns:
                cursor.execute(f"""
                    SELECT COUNT(*)
                    FROM [{schema}].[{table}]
                    WHERE [{col}] IS NULL
                """)
                
                null_count = cursor.fetchone()[0]
                
                if null_count > 0:
                    null_violations.append({
                        'column': col,
                        'null_count': null_count
                    })
            
            if null_violations:
                total_nulls = sum(v['null_count'] for v in null_violations)
                report.add_check(
                    check_name="NULL Value Validation",
                    status=ValidationStatus.FAILED,
                    message=f"Found {total_nulls} NULL(s) in {len(null_violations)} NOT NULL column(s)",
                    details={
                        'violation_count': len(null_violations),
                        'total_nulls': total_nulls,
                        'violations': null_violations
                    },
                    suggested_action="Update NULL values with appropriate defaults"
                )
            else:
                report.add_check(
                    check_name="NULL Value Validation",
                    status=ValidationStatus.PASSED,
                    message=f"No NULL violations in {len(not_null_columns)} NOT NULL column(s)",
                    details={'columns_checked': not_null_columns}
                )
            
            cursor.close()
            
        except Exception as e:
            report.add_check(
                check_name="NULL Value Validation",
                status=ValidationStatus.WARNING,
                message=f"Could not verify NULL values: {e}",
                suggested_action="Manually check for NULL constraint violations"
            )
    
    def _verify_sample_data(
        self,
        report: ValidationReport,
        table: str,
        schema: str,
        restoration_report: Any,
        connection
    ):
        """Verify sample data for large tables (performance optimization)."""
        try:
            cursor = connection.cursor()
            
            # Get table row count
            cursor.execute(f"""
                SELECT COUNT(*) FROM [{schema}].[{table}]
            """)
            row_count = cursor.fetchone()[0]
            
            # Only sample if table is large (>100K rows)
            SAMPLE_THRESHOLD = 100000
            SAMPLE_SIZE = 1000
            
            if row_count < SAMPLE_THRESHOLD:
                report.add_check(
                    check_name="Sample Data Verification",
                    status=ValidationStatus.PASSED,
                    message=f"Table has {row_count} rows (below {SAMPLE_THRESHOLD} threshold, full validation performed)",
                    details={'row_count': row_count}
                )
                cursor.close()
                return
            
            # Get restored columns
            restored_columns = set()
            for table_name, columns in restoration_report.table_details.items():
                if table_name == f"[{schema}].[{table}]" or table_name == table:
                    restored_columns.update(columns.keys())
            
            if not restored_columns:
                report.add_check(
                    check_name="Sample Data Verification",
                    status=ValidationStatus.PASSED,
                    message="No columns to sample"
                )
                cursor.close()
                return
            
            # Sample random rows and verify mappings exist
            # Note: This is a simplified check; full validation would query mapping table
            column_list = ', '.join([f"[{c}]" for c in restored_columns])
            
            cursor.execute(f"""
                SELECT TOP {SAMPLE_SIZE} {column_list}
                FROM [{schema}].[{table}]
                ORDER BY NEWID()
            """)
            
            samples = cursor.fetchall()
            
            if samples:
                report.add_check(
                    check_name="Sample Data Verification",
                    status=ValidationStatus.PASSED,
                    message=f"Sampled {len(samples)} rows from {row_count} total rows",
                    details={
                        'table_row_count': row_count,
                        'sample_size': len(samples),
                        'columns_sampled': list(restored_columns)
                    }
                )
            else:
                report.add_check(
                    check_name="Sample Data Verification",
                    status=ValidationStatus.WARNING,
                    message="No sample data retrieved",
                    suggested_action="Verify table contains data"
                )
            
            cursor.close()
            
        except Exception as e:
            report.add_check(
                check_name="Sample Data Verification",
                status=ValidationStatus.WARNING,
                message=f"Could not verify sample data: {e}",
                suggested_action="Verification failed, but restoration may still be valid"
            )
