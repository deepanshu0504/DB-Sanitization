"""
Integration tests for Configuration Validator.

These tests validate the ConfigValidator against real database schema
(or realistic mocked schema) to ensure end-to-end functionality.

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from unittest.mock import Mock, MagicMock
from pathlib import Path

from src.validation import ConfigValidator, ValidationResult, IssueSeverity
from src.config.config_models import SanitizationConfig, DatabaseConfig, PIIColumnConfig
from src.database.schema_extractor import SchemaExtractor
from src.error_codes import ErrorCodes


# Skip integration tests if no database connection
pytestmark = pytest.mark.integration


@pytest.fixture
def realistic_schema_extractor():
    """
    Mock SchemaExtractor with realistic database schema.
    
    Simulates a typical e-commerce database with:
    - dbo schema with Users, Orders, OrderDetails tables
    - sales schema with Customers table
    - Foreign key relationships
    - Primary keys
    - Various data types
    """
    extractor = Mock(spec=SchemaExtractor)
    
    # Schemas
    extractor.get_schemas.return_value = [
        {"schema_name": "dbo"},
        {"schema_name": "sales"}
    ]
    
    # Tables
    def mock_get_tables(schema):
        if schema == "dbo":
            return [
                {"table_name": "Users", "table_type": "TABLE"},
                {"table_name": "Orders", "table_type": "TABLE"},
                {"table_name": "OrderDetails", "table_type": "TABLE"}
            ]
        elif schema == "sales":
            return [
                {"table_name": "Customers", "table_type": "TABLE"}
            ]
        return []
    
    extractor.get_tables.side_effect = mock_get_tables
    
    # Columns
    def mock_get_columns(schema, table):
        columns_map = {
            ("dbo", "Users"): [
                {"column_name": "UserID", "data_type": "INT", "max_length": 4, "is_nullable": False, "is_identity": True, "is_computed": False, "is_max_type": False},
                {"column_name": "Email", "data_type": "NVARCHAR", "max_length": 510, "is_nullable": False, "is_identity": False, "is_computed": False, "is_max_type": False},
                {"column_name": "PhoneNumber", "data_type": "VARCHAR", "max_length": 20, "is_nullable": True, "is_identity": False, "is_computed": False, "is_max_type": False},
                {"column_name": "FirstName", "data_type": "NVARCHAR", "max_length": 100, "is_nullable": False, "is_identity": False, "is_computed": False, "is_max_type": False},
                {"column_name": "LastName", "data_type": "NVARCHAR", "max_length": 100, "is_nullable": False, "is_identity": False, "is_computed": False, "is_max_type": False},
                {"column_name": "DateOfBirth", "data_type": "DATE", "max_length": 3, "is_nullable": True, "is_identity": False, "is_computed": False, "is_max_type": False},
            ],
            ("dbo", "Orders"): [
                {"column_name": "OrderID", "data_type": "INT", "max_length": 4, "is_nullable": False, "is_identity": True, "is_computed": False, "is_max_type": False},
                {"column_name": "UserID", "data_type": "INT", "max_length": 4, "is_nullable": False, "is_identity": False, "is_computed": False, "is_max_type": False},
                {"column_name": "CustomerID", "data_type": "INT", "max_length": 4, "is_nullable": False, "is_identity": False, "is_computed": False, "is_max_type": False},
                {"column_name": "OrderDate", "data_type": "DATETIME", "max_length": 8, "is_nullable": False, "is_identity": False, "is_computed": False, "is_max_type": False},
                {"column_name": "TotalAmount", "data_type": "DECIMAL", "max_length": 9, "precision": 18, "scale": 2, "is_nullable": False, "is_identity": False, "is_computed": False, "is_max_type": False},
            ],
            ("dbo", "OrderDetails"): [
                {"column_name": "OrderDetailID", "data_type": "INT", "max_length": 4, "is_nullable": False, "is_identity": True, "is_computed": False, "is_max_type": False},
                {"column_name": "OrderID", "data_type": "INT", "max_length": 4, "is_nullable": False, "is_identity": False, "is_computed": False, "is_max_type": False},
                {"column_name": "ProductName", "data_type": "NVARCHAR", "max_length": 200, "is_nullable": False, "is_identity": False, "is_computed": False, "is_max_type": False},
            ],
            ("sales", "Customers"): [
                {"column_name": "CustomerID", "data_type": "INT", "max_length": 4, "is_nullable": False, "is_identity": True, "is_computed": False, "is_max_type": False},
                {"column_name": "CompanyName", "data_type": "NVARCHAR", "max_length": 200, "is_nullable": False, "is_identity": False, "is_computed": False, "is_max_type": False},
                {"column_name": "ContactEmail", "data_type": "NVARCHAR", "max_length": 255, "is_nullable": True, "is_identity": False, "is_computed": False, "is_max_type": False},
                {"column_name": "ContactPhone", "data_type": "VARCHAR", "max_length": 15, "is_nullable": True, "is_identity": False, "is_computed": False, "is_max_type": False},
            ]
        }
        return columns_map.get((schema, table), [])
    
    extractor.get_columns.side_effect = mock_get_columns
    
    # Primary keys
    extractor.get_primary_keys.return_value = [
        {"schema": "dbo", "table": "Users", "column": "UserID"},
        {"schema": "dbo", "table": "Orders", "column": "OrderID"},
        {"schema": "dbo", "table": "OrderDetails", "column": "OrderDetailID"},
        {"schema": "sales", "table": "Customers", "column": "CustomerID"}
    ]
    
    # Foreign keys
    extractor.get_foreign_keys.return_value = [
        {
            "child_schema": "dbo", "child_table": "Orders", "child_column": "UserID",
            "parent_schema": "dbo", "parent_table": "Users", "parent_column": "UserID",
            "is_self_referencing": False
        },
        {
            "child_schema": "dbo", "child_table": "Orders", "child_column": "CustomerID",
            "parent_schema": "sales", "parent_table": "Customers", "parent_column": "CustomerID",
            "is_self_referencing": False
        },
        {
            "child_schema": "dbo", "child_table": "OrderDetails", "child_column": "OrderID",
            "parent_schema": "dbo", "parent_table": "Orders", "parent_column": "OrderID",
            "is_self_referencing": False
        }
    ]
    
    return extractor


class TestEndToEndValidation:
    """End-to-end validation tests with realistic scenarios."""
    
    def test_validate_valid_configuration(self, realistic_schema_extractor):
        """Test validating a completely valid configuration."""
        config = SanitizationConfig(
            database=DatabaseConfig(server="localhost", database="TestDB", auth_type="windows"),
            pii_columns=[
                PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="email", nullable=False),
                PIIColumnConfig(schema="dbo", table="Users", column="PhoneNumber", pii_type="phone", nullable=True),
                PIIColumnConfig(schema="dbo", table="Users", column="FirstName", pii_type="name", nullable=False),
                PIIColumnConfig(schema="sales", table="Customers", column="ContactEmail", pii_type="email", nullable=True),
            ]
        )
        
        validator = ConfigValidator(realistic_schema_extractor)
        result = validator.validate_config(config)
        
        assert result.is_valid is True
        assert result.error_count == 0
        # May have warnings about nullable mismatch or other non-blocking issues
    
    def test_validate_mixed_errors_and_warnings(self, realistic_schema_extractor):
        """Test configuration with both errors and warnings."""
        config = SanitizationConfig(
            database=DatabaseConfig(server="localhost", database="TestDB", auth_type="windows"),
            pii_columns=[
                # Valid
                PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="email", nullable=False),
                # Error: Column doesn't exist
                PIIColumnConfig(schema="dbo", table="Users", column="NonExistent", pii_type="email", nullable=True),
                # Error: Wrong data type (INT as email)
                PIIColumnConfig(schema="dbo", table="Users", column="UserID", pii_type="email", nullable=False),
                # Warning: Foreign key
                PIIColumnConfig(schema="dbo", table="Orders", column="UserID", pii_type="account_number", nullable=False),
            ]
        )
        
        validator = ConfigValidator(realistic_schema_extractor)
        result = validator.validate_config(config)
        
        assert result.is_valid is False
        assert result.error_count >= 2  # NonExistent column + wrong data type
        assert result.warning_count >= 1  # Foreign key warning
    
    def test_validate_all_pii_types(self, realistic_schema_extractor):
        """Test validation with various PII types."""
        config = SanitizationConfig(
            database=DatabaseConfig(server="localhost", database="TestDB", auth_type="windows"),
            pii_columns=[
                PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="email", nullable=False),
                PIIColumnConfig(schema="dbo", table="Users", column="PhoneNumber", pii_type="phone", nullable=True),
                PIIColumnConfig(schema="dbo", table="Users", column="FirstName", pii_type="name", nullable=False),
                PIIColumnConfig(schema="dbo", table="Users", column="LastName", pii_type="name", nullable=False),
                PIIColumnConfig(schema="dbo", table="Users", column="DateOfBirth", pii_type="date_of_birth", nullable=True),
            ]
        )
        
        validator = ConfigValidator(realistic_schema_extractor)
        result = validator.validate_config(config)
        
        # All should be valid
        assert result.is_valid is True
    
    def test_validate_foreign_key_chain(self, realistic_schema_extractor):
        """Test validation with foreign key chains."""
        config = SanitizationConfig(
            database=DatabaseConfig(server="localhost", database="TestDB", auth_type="windows"),
            pii_columns=[
                # Parent
                PIIColumnConfig(schema="sales", table="Customers", column="CustomerID", pii_type="account_number", nullable=False),
                # Child
                PIIColumnConfig(schema="dbo", table="Orders", column="CustomerID", pii_type="account_number", nullable=False),
            ]
        )
        
        validator = ConfigValidator(realistic_schema_extractor)
        result = validator.validate_config(config)
        
        # Should have warnings about FK relationships and PK
        assert result.warning_count >= 2


class TestValidationReportGeneration:
    """Tests for validation report generation and formatting."""
    
    def test_generate_detailed_report(self, realistic_schema_extractor):
        """Test generating detailed validation report."""
        config = SanitizationConfig(
            database=DatabaseConfig(server="localhost", database="TestDB", auth_type="windows"),
            pii_columns=[
                PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="email", nullable=False),
                PIIColumnConfig(schema="dbo", table="Users", column="NonExistent", pii_type="email", nullable=True),
            ]
        )
        
        validator = ConfigValidator(realistic_schema_extractor)
        result = validator.validate_config(config)
        
        # Test report generation
        report = result.to_dict()
        
        assert "is_valid" in report
        assert "error_count" in report
        assert "errors" in report
        assert "warnings" in report
        
        # Test formatted summary
        summary = result.format_summary(show_issues=True)
        assert "FAILED" in summary or "PASSED" in summary
    
    def test_validation_result_serialization(self, realistic_schema_extractor):
        """Test that validation results can be serialized."""
        config = SanitizationConfig(
            database=DatabaseConfig(server="localhost", database="TestDB", auth_type="windows"),
            pii_columns=[
                PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="email", nullable=False),
            ]
        )
        
        validator = ConfigValidator(realistic_schema_extractor)
        result = validator.validate_config(config)
        
        # Should be serializable to dict
        report_dict = result.to_dict()
        assert isinstance(report_dict, dict)
        
        # Should be JSON-serializable
        import json
        json_str = json.dumps(report_dict)
        assert isinstance(json_str, str)


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    def test_validate_large_configuration(self, realistic_schema_extractor):
        """Test validating configuration with many PII columns."""
        pii_columns = []
        
        # Add multiple columns from different tables
        for _ in range(10):
            pii_columns.append(
                PIIColumnConfig(
                    schema="dbo",
                    table="Users",
                    column="Email",
                    pii_type="email",
                    nullable=False
                )
            )
        
        config = SanitizationConfig(
            database=DatabaseConfig(server="localhost", database="TestDB", auth_type="windows"),
            pii_columns=pii_columns
        )
        
        validator = ConfigValidator(realistic_schema_extractor)
        result = validator.validate_config(config)
        
        # Should handle large configs
        assert isinstance(result, ValidationResult)
    
    def test_validate_with_extraction_failure(self):
        """Test handling of schema extraction failures."""
        extractor = Mock(spec=SchemaExtractor)
        extractor.get_schemas.side_effect = Exception("Database connection failed")
        
        config = SanitizationConfig(
            database=DatabaseConfig(server="localhost", database="TestDB", auth_type="windows"),
            pii_columns=[
                PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="email", nullable=False),
            ]
        )
        
        validator = ConfigValidator(extractor)
        result = validator.validate_config(config)
        
        # Should return error result, not crash
        assert result.is_valid is False
        assert result.error_count >= 1
    
    def test_validate_duplicate_columns(self, realistic_schema_extractor):
        """Test validation with duplicate column configurations."""
        config = SanitizationConfig(
            database=DatabaseConfig(server="localhost", database="TestDB", auth_type="windows"),
            pii_columns=[
                PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="email", nullable=False),
                PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="email", nullable=False),  # Duplicate
            ]
        )
        
        validator = ConfigValidator(realistic_schema_extractor)
        result = validator.validate_config(config)
        
        # Validator should process both (Pydantic handles duplicate prevention at config level)
        assert isinstance(result, ValidationResult)


class TestStrictMode:
    """Tests for strict mode validation."""
    
    def test_strict_mode_disabled(self, realistic_schema_extractor):
        """Test that warnings don't block in normal mode."""
        config = SanitizationConfig(
            database=DatabaseConfig(server="localhost", database="TestDB", auth_type="windows"),
            pii_columns=[
                # This will generate FK warning
                PIIColumnConfig(schema="dbo", table="Orders", column="UserID", pii_type="account_number", nullable=False),
            ]
        )
        
        validator = ConfigValidator(realistic_schema_extractor, strict_mode=False)
        result = validator.validate_config(config)
        
        # Should be valid despite warnings
        assert result.is_valid is True or result.error_count == 0  # Warnings don't affect validity


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
