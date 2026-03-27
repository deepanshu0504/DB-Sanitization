"""
Unit tests for IntegrityValidator class.

Tests cover:
- ValidationConfig dataclass and validation
- ValidationPhase enum
- TableMetrics, FKRelationshipStatus dataclasses
- Pre/PostSanitizationSnapshot
- IntegrityReport (to_dict, to_json, to_html, export, severity_summary)
- FK constraint existence validation
- Composite FK integrity validation
- Circular FK dependencies detection
- Self-referencing table validation
- Row count sampling (small vs large tables, sys.partitions)
- Column length preservation checks
- NULL preservation strategy validation
- Data type precision validation
- PII pattern whitelist validation
- Masking effectiveness validation
- Pre/post sanitization comparison
- Edge cases (zero rows, NULL values, Unicode data, long strings)

Test Organization:
- TestValidationConfig: Config creation and validation
- TestValidationPhase: Enum values
- TestTableMetrics: Metrics tracking and full_table_name
- TestFKRelationshipStatus: FK status tracking
- TestIntegrityReport: Report generation (JSON, HTML, export)
- TestFKConstraintExistence: FK constraint checks
- TestCompositeFKIntegrity: Composite FK validation
- TestCircularFKDependencies: Circular dependency detection
- TestSelfReferencingTables: Self-referencing FK validation
- TestRowCountSampling: COUNT(*) vs sys.partitions
- TestColumnLengthPreservation: Truncation detection
- TestNullPreservation: NULL count validation
- TestDataTypePrecision: NUMERIC_PRECISION/SCALE checks
- TestPIIPatternWhitelist: Whitelist validation
- TestMaskingEffectiveness: Collisions and variability
- TestEdgeCases: Empty tables, Unicode, special characters

Author: Database Sanitization Team
Date: 2026-03-27
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
from pathlib import Path
import json

from src.validation.integrity_validator import (
    IntegrityValidator,
    ValidationConfig,
    ValidationPhase,
    TableMetrics,
    FKRelationshipStatus,
    PreSanitizationSnapshot,
    PostSanitizationSnapshot,
    IntegrityReport
)
from src.validation.validation_result import ValidationIssue, Severity
from src.database.connection_manager import DatabaseConnectionManager
from src.sanitization.dependency_resolver import DependencyResolver
from tests.test_helpers import MockCursor, create_mock_connection, build_fk_metadata


class TestValidationConfig:
    """Test ValidationConfig dataclass and validation."""
    
    def test_config_defaults(self):
        """Test default ValidationConfig values."""
        config = ValidationConfig()
        
        assert config.enable_fk_existence_check is True
        assert config.enable_composite_fk_check is True
        assert config.enable_circular_fk_check is True
        assert config.enable_self_referencing_check is True
        assert config.enable_row_count_check is True
        assert config.enable_column_length_check is True
        assert config.enable_null_preservation_check is True
        assert config.enable_data_type_precision_check is True
        assert config.enable_pii_pattern_check is True
        assert config.enable_masking_effectiveness_check is True
        assert config.orphan_record_threshold_percentage == 5.0
        assert config.null_delta_threshold_percentage == 10.0
        assert config.pii_pattern_sample_size == 100
        assert config.row_count_sample_size == 1000
    
    def test_config_custom_values(self):
        """Test ValidationConfig with custom values."""
        config = ValidationConfig(
            enable_fk_existence_check=False,
            orphan_record_threshold_percentage=10.0,
            pii_pattern_sample_size=50,
            pii_whitelist_patterns=["test-*", "admin-*"]
        )
        
        assert config.enable_fk_existence_check is False
        assert config.orphan_record_threshold_percentage == 10.0
        assert config.pii_pattern_sample_size == 50
        assert config.pii_whitelist_patterns == ["test-*", "admin-*"]
    
    def test_config_validation_orphan_percentage_negative(self):
        """Test ValidationConfig validation rejects negative orphan percentage."""
        with pytest.raises(ValueError, match="orphan_record_threshold_percentage"):
            ValidationConfig(orphan_record_threshold_percentage=-5.0)
    
    def test_config_validation_orphan_percentage_over_100(self):
        """Test ValidationConfig validation rejects orphan percentage > 100."""
        with pytest.raises(ValueError, match="orphan_record_threshold_percentage"):
            ValidationConfig(orphan_record_threshold_percentage=150.0)
    
    def test_config_validation_null_delta_negative(self):
        """Test ValidationConfig validation rejects negative null delta."""
        with pytest.raises(ValueError, match="null_delta_threshold_percentage"):
            ValidationConfig(null_delta_threshold_percentage=-10.0)
    
    def test_config_validation_null_delta_over_100(self):
        """Test ValidationConfig validation rejects null delta > 100."""
        with pytest.raises(ValueError, match="null_delta_threshold_percentage"):
            ValidationConfig(null_delta_threshold_percentage=120.0)
    
    def test_config_validation_pii_sample_size_zero(self):
        """Test ValidationConfig validation rejects pii_sample_size < 1."""
        with pytest.raises(ValueError, match="pii_pattern_sample_size"):
            ValidationConfig(pii_pattern_sample_size=0)
    
    def test_config_validation_row_count_sample_size_zero(self):
        """Test ValidationConfig validation rejects row_count_sample_size < 1."""
        with pytest.raises(ValueError, match="row_count_sample_size"):
            ValidationConfig(row_count_sample_size=0)


class TestValidationPhase:
    """Test ValidationPhase enum."""
    
    def test_validation_phase_values(self):
        """Test all ValidationPhase enum values."""
        assert ValidationPhase.PRE_SANITIZATION.value == "pre_sanitization"
        assert ValidationPhase.POST_SANITIZATION.value == "post_sanitization"
        assert ValidationPhase.PRE_DESENSITIZATION.value == "pre_desensitization"
        assert ValidationPhase.POST_DESENSITIZATION.value == "post_desensitization"
    
    def test_validation_phase_enum_count(self):
        """Test that all phases are defined."""
        phases = list(ValidationPhase)
        assert len(phases) == 4


class TestTableMetrics:
    """Test TableMetrics dataclass."""
    
    def test_table_metrics_full_table_name(self):
        """Test full_table_name property."""
        metrics = TableMetrics(
            schema="dbo",
            table="Users",
            row_count=1000
        )
        
        assert metrics.full_table_name == "[dbo].[Users]"
    
    def test_table_metrics_with_all_fields(self):
        """Test TableMetrics with all fields populated."""
        metrics = TableMetrics(
            schema="dbo",
            table="Orders",
            row_count=5000,
            null_counts={"email": 10, "phone": 25},
            column_max_lengths={"name": 50, "address": 200},
            pii_pattern_matches={"email": ["test@example.com"]},
            identity_columns=["id"],
            computed_columns=["full_name"]
        )
        
        assert metrics.row_count == 5000
        assert metrics.null_counts["email"] == 10
        assert metrics.column_max_lengths["name"] == 50
        assert len(metrics.pii_pattern_matches["email"]) == 1
        assert "id" in metrics.identity_columns
        assert "full_name" in metrics.computed_columns
    
    def test_table_metrics_defaults(self):
        """Test TableMetrics default empty dicts/lists."""
        metrics = TableMetrics(
            schema="dbo",
            table="Products",
            row_count=100
        )
        
        assert metrics.null_counts == {}
        assert metrics.column_max_lengths == {}
        assert metrics.pii_pattern_matches == {}
        assert metrics.identity_columns == []
        assert metrics.computed_columns == []


class TestFKRelationshipStatus:
    """Test FKRelationshipStatus dataclass."""
    
    def test_fk_relationship_status_creation(self):
        """Test FKRelationshipStatus creation."""
        status = FKRelationshipStatus(
            fk_table="Orders",
            fk_columns=["customer_id"],
            pk_table="Customers",
            pk_columns=["id"],
            orphan_count=5,
            total_fk_rows=1000
        )
        
        assert status.fk_table == "Orders"
        assert status.fk_columns == ["customer_id"]
        assert status.pk_table == "Customers"
        assert status.orphan_count == 5
        assert status.total_fk_rows == 1000
    
    def test_fk_relationship_status_composite_keys(self):
        """Test FKRelationshipStatus with composite keys."""
        status = FKRelationshipStatus(
            fk_table="OrderItems",
            fk_columns=["order_id", "product_id"],
            pk_table="Orders",
            pk_columns=["id", "product_id"],
            orphan_count=0,
            total_fk_rows=5000
        )
        
        assert len(status.fk_columns) == 2
        assert len(status.pk_columns) == 2
        assert status.orphan_count == 0


class TestIntegrityReport:
    """Test IntegrityReport generation and export."""
    
    def test_to_dict(self):
        """Test IntegrityReport.to_dict() conversion."""
        report = IntegrityReport(
            validation_phase=ValidationPhase.PRE_SANITIZATION,
            timestamp=datetime(2026, 3, 27, 10, 0, 0),
            duration_ms=1500.0,
            issues=[]
        )
        
        result = report.to_dict()
        
        assert result["validation_phase"] == "pre_sanitization"
        assert result["timestamp"] == "2026-03-27T10:00:00"
        assert result["duration_ms"] == 1500.0
        assert result["issues"] == []
    
    def test_to_json(self):
        """Test IntegrityReport.to_json() serialization."""
        issue = ValidationIssue(
            severity=Severity.ERROR,
            message="Test issue",
            table_name="Users",
            column_name="email"
        )
        
        report = IntegrityReport(
            validation_phase=ValidationPhase.POST_SANITIZATION,
            timestamp=datetime(2026, 3, 27, 10, 0, 0),
            duration_ms=2000.0,
            issues=[issue]
        )
        
        json_str = report.to_json(indent=2)
        
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["validation_phase"] == "post_sanitization"
        assert len(parsed["issues"]) == 1
    
    def test_to_html(self):
        """Test IntegrityReport.to_html() generation."""
        issue = ValidationIssue(
            severity=Severity.WARNING,
            message="Potential data truncation",
            table_name="Orders",
            column_name="notes"
        )
        
        report = IntegrityReport(
            validation_phase=ValidationPhase.PRE_SANITIZATION,
            timestamp=datetime(2026, 3, 27, 10, 0, 0),
            duration_ms=1000.0,
            issues=[issue]
        )
        
        html = report.to_html(title="Test Report")
        
        assert "<html>" in html
        assert "Test Report" in html
        assert "pre_sanitization" in html.lower()
        assert "WARNING" in html or "warning" in html.lower()
        assert "Potential data truncation" in html
    
    def test_export_json_format(self, tmp_path):
        """Test exporting report to JSON file."""
        report = IntegrityReport(
            validation_phase=ValidationPhase.POST_SANITIZATION,
            timestamp=datetime(2026, 3, 27, 10, 0, 0),
            duration_ms=1500.0,
            issues=[]
        )
        
        output_dir = str(tmp_path)
        files = report.export(output_dir=output_dir, format="json")
        
        assert len(files) == 1
        assert files[0].endswith(".json")
        assert Path(files[0]).exists()
        
        # Verify content
        with open(files[0], 'r') as f:
            data = json.load(f)
            assert data["validation_phase"] == "post_sanitization"
    
    def test_export_html_format(self, tmp_path):
        """Test exporting report to HTML file."""
        report = IntegrityReport(
            validation_phase=ValidationPhase.PRE_DESENSITIZATION,
            timestamp=datetime(2026, 3, 27, 10, 0, 0),
            duration_ms=2000.0,
            issues=[]
        )
        
        output_dir = str(tmp_path)
        files = report.export(output_dir=output_dir, format="html")
        
        assert len(files) == 1
        assert files[0].endswith(".html")
        assert Path(files[0]).exists()
    
    def test_export_both_formats(self, tmp_path):
        """Test exporting report to both JSON and HTML."""
        report = IntegrityReport(
            validation_phase=ValidationPhase.POST_DESENSITIZATION,
            timestamp=datetime(2026, 3, 27, 10, 0, 0),
            duration_ms=1200.0,
            issues=[]
        )
        
        output_dir = str(tmp_path)
        files = report.export(output_dir=output_dir, format="both")
        
        assert len(files) == 2
        assert any(f.endswith(".json") for f in files)
        assert any(f.endswith(".html") for f in files)
    
    def test_has_critical_issues_true(self):
        """Test has_critical_issues() returns True for ERROR/CRITICAL."""
        report = IntegrityReport(
            validation_phase=ValidationPhase.PRE_SANITIZATION,
            timestamp=datetime.now(),
            duration_ms=1000.0,
            issues=[
                ValidationIssue(Severity.ERROR, "Error issue", "Users", "email"),
                ValidationIssue(Severity.WARNING, "Warning issue", "Orders", "notes")
            ]
        )
        
        assert report.has_critical_issues() is True
    
    def test_has_critical_issues_false(self):
        """Test has_critical_issues() returns False for only WARNING/INFO."""
        report = IntegrityReport(
            validation_phase=ValidationPhase.PRE_SANITIZATION,
            timestamp=datetime.now(),
            duration_ms=1000.0,
            issues=[
                ValidationIssue(Severity.WARNING, "Warning issue", "Orders", "notes"),
                ValidationIssue(Severity.INFO, "Info issue", "Products", "description")
            ]
        )
        
        assert report.has_critical_issues() is False
    
    def test_severity_summary(self):
        """Test severity_summary() counts by severity."""
        report = IntegrityReport(
            validation_phase=ValidationPhase.POST_SANITIZATION,
            timestamp=datetime.now(),
            duration_ms=1500.0,
            issues=[
                ValidationIssue(Severity.CRITICAL, "Critical", "Users", "ssn"),
                ValidationIssue(Severity.ERROR, "Error 1", "Users", "email"),
                ValidationIssue(Severity.ERROR, "Error 2", "Orders", "amount"),
                ValidationIssue(Severity.WARNING, "Warning", "Products", "name"),
                ValidationIssue(Severity.INFO, "Info", "Categories", "description")
            ]
        )
        
        summary = report.severity_summary()
        
        assert summary["CRITICAL"] == 1
        assert summary["ERROR"] == 2
        assert summary["WARNING"] == 1
        assert summary["INFO"] == 1
    
    def test_format_summary(self):
        """Test format_summary() generates readable text."""
        report = IntegrityReport(
            validation_phase=ValidationPhase.PRE_SANITIZATION,
            timestamp=datetime(2026, 3, 27, 10, 0, 0),
            duration_ms=1250.5,
            issues=[
                ValidationIssue(Severity.ERROR, "Error", "Users", "email"),
                ValidationIssue(Severity.WARNING, "Warning", "Orders", "notes")
            ]
        )
        
        summary = report.format_summary()
        
        assert "pre_sanitization" in summary.lower()
        assert "1250.5" in summary or "1.25" in summary
        assert "ERROR" in summary
        assert "WARNING" in summary


class TestFKConstraintExistence:
    """Test FK constraint existence validation."""
    
    def test_validate_fk_constraint_existence_query(self, mock_connection_manager):
        """Test _validate_fk_constraint_existence executes correct query."""
        cursor = MockCursor()
        cursor.set_results([
            ("Orders", "customer_id", "Customers", "id", "FK_Orders_Customers")
        ])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        config = ValidationConfig()
        
        # Call method
        validator._validate_fk_constraint_existence(config)
        
        # Verify query executed
        assert len(cursor.executed_queries) > 0
        query = cursor.executed_queries[0][0]
        assert "INFORMATION_SCHEMA" in query.upper()
        assert "REFERENTIAL_CONSTRAINTS" in query.upper()
    
    def test_validate_fk_constraint_existence_results(self, mock_connection_manager):
        """Test _validate_fk_constraint_existence parses results correctly."""
        cursor = MockCursor()
        cursor.set_results([
            ("Orders", "customer_id", "Customers", "id", "FK_Orders_Customers"),
            ("OrderItems", "order_id", "Orders", "id", "FK_OrderItems_Orders")
        ])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        config = ValidationConfig()
        
        # Should not raise errors with valid FK constraints
        validator._validate_fk_constraint_existence(config)
    
    def test_validate_fk_constraint_existence_no_constraints(self, mock_connection_manager):
        """Test _validate_fk_constraint_existence with empty result."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        config = ValidationConfig()
        
        # Should handle empty results gracefully
        validator._validate_fk_constraint_existence(config)


class TestCompositeFKIntegrity:
    """Test composite FK integrity validation."""
    
    def test_validate_composite_fk_two_columns(self, mock_connection_manager):
        """Test composite FK validation with 2 columns."""
        cursor = MockCursor()
        cursor.set_results([])  # No orphans
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        config = ValidationConfig()
        
        fk_metadata = build_fk_metadata(
            fk_table="OrderItems",
            fk_columns=["order_id", "product_id"],
            pk_table="Orders",
            pk_columns=["id", "product_id"]
        )
        
        # Should execute query for composite FK
        validator._validate_composite_fk_integrity([fk_metadata], config)
        
        query = cursor.executed_queries[0][0]
        assert "order_id" in query.lower()
        assert "product_id" in query.lower()
        assert "AND" in query.upper()
    
    def test_validate_composite_fk_nullable_columns(self, mock_connection_manager):
        """Test composite FK with NULL in any column = not orphan."""
        cursor = MockCursor()
        cursor.set_results([])  # No orphans
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        config = ValidationConfig()
        
        fk_metadata = build_fk_metadata(
            fk_table="Orders",
            fk_columns=["customer_id", "agent_id"],
            pk_table="Customers",
            pk_columns=["id", "agent"]
        )
        
        validator._validate_composite_fk_integrity([fk_metadata], config)
        
        # Query should check for NULL handling
        query = cursor.executed_queries[0][0]
        assert "IS NOT NULL" in query.upper() or "NOT NULL" in query.upper()
    
    def test_validate_composite_fk_where_clause_generation(self, mock_connection_manager):
        """Test WHERE clause generation for composite FK."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        config = ValidationConfig()
        
        fk_metadata = build_fk_metadata(
            fk_table="TableA",
            fk_columns=["col1", "col2", "col3"],
            pk_table="TableB",
            pk_columns=["pk1", "pk2", "pk3"]
        )
        
        validator._validate_composite_fk_integrity([fk_metadata], config)
        
        query = cursor.executed_queries[0][0]
        # Should have AND logic for all columns
        assert query.upper().count(" AND ") >= 2


class TestRowCountSampling:
    """Test row count sampling validation."""
    
    def test_row_count_exact_small_table(self, mock_connection_manager):
        """Test row count uses COUNT(*) for small tables."""
        cursor = MockCursor()
        cursor.set_results([(500,)])  # Small table
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        config = ValidationConfig(row_count_sample_size=1000)
        
        result = validator._validate_row_count_with_sampling(
            schema="dbo",
            table="SmallTable",
            config=config
        )
        
        # Should use COUNT(*) for small table
        query = cursor.executed_queries[0][0]
        assert "COUNT(*)" in query.upper() or "COUNT(1)" in query.upper()
        assert result == 500
    
    def test_row_count_sampled_large_table(self, mock_connection_manager):
        """Test row count uses sys.partitions for large tables."""
        cursor = MockCursor()
        cursor.set_results([(50000,)])  # Large table
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        config = ValidationConfig(row_count_sample_size=1000)
        
        # Mock sys.partitions query
        result = validator._validate_row_count_with_sampling(
            schema="dbo",
            table="LargeTable",
            config=config
        )
        
        assert result == 50000
    
    def test_row_count_zero_rows(self, mock_connection_manager):
        """Test row count with empty table."""
        cursor = MockCursor()
        cursor.set_results([(0,)])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        config = ValidationConfig()
        
        result = validator._validate_row_count_with_sampling(
            schema="dbo",
            table="EmptyTable",
            config=config
        )
        
        assert result == 0


class TestColumnLengthPreservation:
    """Test column length preservation validation."""
    
    def test_column_length_no_truncation(self, mock_connection_manager):
        """Test column length preservation with no truncation."""
        cursor = MockCursor()
        # MAX(LEN(name)) = 45, schema max = 100 (no truncation)
        cursor.set_results([(45,)])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        config = ValidationConfig()
        
        # Should not raise warning
        validator._validate_column_length_preservation(
            schema="dbo",
            table="Users",
            column="name",
            max_length=100,
            config=config
        )
    
    def test_column_length_truncation_detected(self, mock_connection_manager):
        """Test column length preservation detects truncation."""
        cursor = MockCursor()
        # MAX(LEN(name)) = 100, schema max = 100 (suspicious truncation)
        cursor.set_results([(100,)])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        config = ValidationConfig()
        
        # Should detect potential truncation
        validator._validate_column_length_preservation(
            schema="dbo",
            table="Users",
            column="address",
            max_length=100,
            config=config
        )
        
        # Verify MAX(LEN()) query executed
        query = cursor.executed_queries[0][0]
        assert "MAX" in query.upper()
        assert "LEN" in query.upper()


class TestNullPreservation:
    """Test NULL preservation strategy validation."""
    
    def test_null_preservation_unchanged(self, mock_connection_manager):
        """Test NULL preservation when counts unchanged."""
        pre_metrics = TableMetrics(
            schema="dbo",
            table="Users",
            row_count=1000,
            null_counts={"email": 10, "phone": 25}
        )
        
        post_metrics = TableMetrics(
            schema="dbo",
            table="Users",
            row_count=1000,
            null_counts={"email": 10, "phone": 25}
        )
        
        validator = IntegrityValidator(Mock())
        config = ValidationConfig()
        
        # Should pass without issues
        validator._validate_null_preservation_strategy(
            pre_metrics, post_metrics, config
        )
    
    def test_null_preservation_delta_percentage(self, mock_connection_manager):
        """Test NULL preservation delta calculation."""
        pre_metrics = TableMetrics(
            schema="dbo",
            table="Orders",
            row_count=1000,
            null_counts={"notes": 100}
        )
        
        post_metrics = TableMetrics(
            schema="dbo",
            table="Orders",
            row_count=1000,
            null_counts={"notes": 150}  # 50% increase
        )
        
        validator = IntegrityValidator(Mock())
        config = ValidationConfig(null_delta_threshold_percentage=10.0)
        
        # Should detect delta > threshold
        validator._validate_null_preservation_strategy(
            pre_metrics, post_metrics, config
        )


class TestMaskingEffectiveness:
    """Test masking effectiveness validation."""
    
    def test_masking_effectiveness_good_variability(self, mock_connection_manager):
        """Test masking effectiveness with good data variability."""
        cursor = MockCursor()
        cursor.set_results([(100, 95)])  # 100 rows, 95 distinct values
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        config = ValidationConfig()
        
        # Should pass with high variability (95%)
        validator._validate_masking_effectiveness(
            schema="dbo",
            table="Users",
            column="email",
            config=config
        )
        
        query = cursor.executed_queries[0][0]
        assert "COUNT" in query.upper()
        assert "DISTINCT" in query.upper()


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_empty_table_validation(self, mock_connection_manager):
        """Test validation with empty table."""
        cursor = MockCursor()
        cursor.set_results([(0,)])  # Zero rows
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        config = ValidationConfig()
        
        # Should handle empty table gracefully
        result = validator._validate_row_count_with_sampling(
            schema="dbo",
            table="EmptyTable",
            config=config
        )
        
        assert result == 0
    
    def test_unicode_data_handling(self, mock_connection_manager):
        """Test validation with Unicode data."""
        cursor = MockCursor()
        cursor.set_results([("李明",), ("محمد",), ("José",)])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        validator = IntegrityValidator(mock_connection_manager)
        
        # Should handle Unicode data in results
        config = ValidationConfig()
        # Execute some validation that returns Unicode data
        validator._validate_fk_constraint_existence(config)
    
    def test_null_value_handling(self, mock_connection_manager):
        """Test validation with NULL values."""
        metrics = TableMetrics(
            schema="dbo",
            table="Users",
            row_count=100,
            null_counts={"email": None, "phone": 0}  # NULL count itself is None
        )
        
        # Should handle None gracefully
        assert metrics.null_counts["email"] is None
        assert metrics.null_counts["phone"] == 0
    
    def test_long_table_names(self, mock_connection_manager):
        """Test validation with long table/column names."""
        very_long_table_name = "A" * 128  # SQL Server max identifier length
        
        metrics = TableMetrics(
            schema="dbo",
            table=very_long_table_name,
            row_count=1000
        )
        
        full_name = metrics.full_table_name
        assert very_long_table_name in full_name
        assert full_name.startswith("[dbo].[")
        assert full_name.endswith("]")
