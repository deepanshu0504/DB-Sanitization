"""
Unit tests for Configuration Validator.

Tests cover:
- Column existence validation
- Data type compatibility
- Nullable constraints
- Foreign key validation
- Primary key validation
- Edge cases and error handling

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from unittest.mock import Mock, MagicMock
from typing import Dict, List, Any

from src.validation import ConfigValidator, ValidationResult, IssueSeverity
from src.config.config_models import SanitizationConfig, DatabaseConfig, PIIColumnConfig
from src.database.schema_extractor import SchemaExtractor
from src.error_codes import ErrorCodes


@pytest.fixture
def mock_schema_extractor():
    """Mock SchemaExtractor with realistic responses."""
    extractor = Mock(spec=SchemaExtractor)
    
    # Mock get_schemas
    extractor.get_schemas.return_value = [
        {"schema_name": "dbo"},
        {"schema_name": "sales"}
    ]
    
    # Mock get_tables
    def mock_get_tables(schema):
        if schema == "dbo":
            return [
                {"table_name": "Users", "table_type": "TABLE"},
                {"table_name": "Orders", "table_type": "TABLE"}
            ]
        elif schema == "sales":
            return [
                {"table_name": "Customers", "table_type": "TABLE"}
            ]
        return []
    
    extractor.get_tables.side_effect = mock_get_tables
    
    # Mock get_columns
    def mock_get_columns(schema, table):
        if schema == "dbo" and table == "Users":
            return [
                {
                    "column_name": "UserID",
                    "data_type": "INT",
                    "max_length": 4,
                    "is_nullable": False,
                    "is_identity": True,
                    "is_computed": False,
                    "is_max_type": False
                },
                {
                    "column_name": "Email",
                    "data_type": "VARCHAR",
                    "max_length": 255,
                    "is_nullable": True,
                    "is_identity": False,
                    "is_computed": False,
                    "is_max_type": False
                },
                {
                    "column_name": "PhoneNumber",
                    "data_type": "VARCHAR",
                    "max_length": 20,
                    "is_nullable": True,
                    "is_identity": False,
                    "is_computed": False,
                    "is_max_type": False
                }
            ]
        elif schema == "dbo" and table == "Orders":
            return [
                {
                    "column_name": "OrderID",
                    "data_type": "INT",
                    "max_length": 4,
                    "is_nullable": False,
                    "is_identity": True,
                    "is_computed": False,
                    "is_max_type": False
                },
                {
                    "column_name": "CustomerID",
                    "data_type": "INT",
                    "max_length": 4,
                    "is_nullable": False,
                    "is_identity": False,
                    "is_computed": False,
                    "is_max_type": False
                }
            ]
        return []
    
    extractor.get_columns.side_effect = mock_get_columns
    
    # Mock get_primary_keys
    extractor.get_primary_keys.return_value = [
        {"schema": "dbo", "table": "Users", "column": "UserID"},
        {"schema": "dbo", "table": "Orders", "column": "OrderID"}
    ]
    
    # Mock get_foreign_keys
    extractor.get_foreign_keys.return_value = [
        {
            "child_schema": "dbo",
            "child_table": "Orders",
            "child_column": "CustomerID",
            "parent_schema": "sales",
            "parent_table": "Customers",
            "parent_column": "CustomerID",
            "is_self_referencing": False
        }
    ]
    
    return extractor


@pytest.fixture
def sample_database_config():
    """Sample database configuration."""
    return DatabaseConfig(
        server="localhost",
        database="TestDB",
        auth_type="windows"
    )


class TestConfigValidatorInitialization:
    """Tests for ConfigValidator initialization."""
    
    def test_init_default(self, mock_schema_extractor):
        """Test initialization with default parameters."""
        validator = ConfigValidator(mock_schema_extractor)
        
        assert validator.schema_extractor is mock_schema_extractor
        assert validator.strict_mode is False
    
    def test_init_strict_mode(self, mock_schema_extractor):
        """Test initialization with strict mode."""
        validator = ConfigValidator(mock_schema_extractor, strict_mode=True)
        
        assert validator.strict_mode is True
    
    def test_pii_data_type_compatibility(self):
        """Test PII data type compatibility mapping exists."""
        assert "email" in ConfigValidator.PII_DATA_TYPE_COMPATIBILITY
        assert "phone" in ConfigValidator.PII_DATA_TYPE_COMPATIBILITY
        assert "ssn" in ConfigValidator.PII_DATA_TYPE_COMPATIBILITY
    
    def test_min_length_requirements(self):
        """Test minimum length requirements exist."""
        assert "email" in ConfigValidator.MIN_LENGTH_REQUIREMENTS
        assert ConfigValidator.MIN_LENGTH_REQUIREMENTS["email"] == 7


class TestValidateConfigEmpty:
    """Tests for validating empty or minimal configurations."""
    
    def test_validate_empty_config(self, mock_schema_extractor, sample_database_config):
        """Test validating configuration with no PII columns."""
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        assert result.is_valid is True
        assert result.info_count == 1  # "No PII columns configured"
    
    def test_validate_single_valid_column(self, mock_schema_extractor, sample_database_config):
        """Test validating configuration with single valid column."""
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Users",
                    column="Email",
                    pii_type="email",
                    nullable=True
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        assert result.is_valid is True
        assert result.error_count == 0


class TestColumnExistenceValidation:
    """Tests for column existence validation."""
    
    def test_schema_not_found(self, mock_schema_extractor, sample_database_config):
        """Test error when schema doesn't exist."""
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="nonexistent",
                    table="Users",
                    column="Email",
                    pii_type="email",
                    nullable=True
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        assert result.is_valid is False
        assert result.error_count >= 1
        assert any(ErrorCodes.SCHEMA_NOT_FOUND in str(err.code) for err in result.errors)
    
    def test_table_not_found(self, mock_schema_extractor, sample_database_config):
        """Test error when table doesn't exist."""
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="NonExistentTable",
                    column="Email",
                    pii_type="email",
                    nullable=True
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        assert result.is_valid is False
        assert result.error_count >= 1
        assert any(ErrorCodes.TABLE_NOT_FOUND_IN_SCHEMA in str(err.code) for err in result.errors)
    
    def test_column_not_found(self, mock_schema_extractor, sample_database_config):
        """Test error when column doesn't exist."""
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Users",
                    column="NonExistentColumn",
                    pii_type="email",
                    nullable=True
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        assert result.is_valid is False
        assert result.error_count >= 1
        assert any(ErrorCodes.COLUMN_NOT_FOUND_IN_TABLE in str(err.code) for err in result.errors)
    
    def test_system_schema_warning(self, mock_schema_extractor, sample_database_config):
        """Test warning for system schemas."""
        # Add sys schema to mock
        mock_schema_extractor.get_schemas.return_value.append({"schema_name": "sys"})
        mock_schema_extractor.get_tables.return_value = [{"table_name": "objects", "table_type": "TABLE"}]
        mock_schema_extractor.get_columns.return_value = [
            {
                "column_name": "name",
                "data_type": "NVARCHAR",
                "max_length": 256,
                "is_nullable": True,
                "is_identity": False,
                "is_computed": False,
                "is_max_type": False
            }
        ]
        
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="sys",
                    table="objects",
                    column="name",
                    pii_type="name",
                    nullable=True
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        assert result.warning_count >= 1
        assert any(ErrorCodes.SYSTEM_TABLE_WARNING in str(warn.code) for warn in result.warnings)
    
    def test_temp_table_error(self, mock_schema_extractor, sample_database_config):
        """Test error for temporary tables."""
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="#TempTable",
                    column="Email",
                    pii_type="email",
                    nullable=True
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        assert result.is_valid is False
        assert any(ErrorCodes.TEMP_TABLE_ERROR in str(err.code) for err in result.errors)


class TestDataTypeCompatibilityValidation:
    """Tests for data type compatibility validation."""
    
    def test_compatible_data_type(self, mock_schema_extractor, sample_database_config):
        """Test validation passes for compatible data types."""
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Users",
                    column="Email",  # VARCHAR(255)
                    pii_type="email",
                    nullable=True
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        assert result.is_valid is True
        # Should not have data type compatibility errors
        assert not any(ErrorCodes.INCOMPATIBLE_DATA_TYPE in str(err.code) for err in result.errors)
    
    def test_incompatible_data_type(self, mock_schema_extractor, sample_database_config):
        """Test error for incompatible data types."""
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Orders",
                    column="OrderID",  # INT
                    pii_type="email",  # Can't mask INT as email
                    nullable=False
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        assert result.is_valid is False
        assert any(ErrorCodes.INCOMPATIBLE_DATA_TYPE in str(err.code) for err in result.errors)
    
    def test_insufficient_length(self, mock_schema_extractor, sample_database_config):
        """Test error for insufficient column length."""
        # Modify mock to return short column
        def mock_get_columns_short(schema, table):
            if schema == "dbo" and table == "Users":
                return [
                    {
                        "column_name": "ShortEmail",
                        "data_type": "VARCHAR",
                        "max_length": 5,  # Too short for email (min 7)
                        "is_nullable": True,
                        "is_identity": False,
                        "is_computed": False,
                        "is_max_type": False
                    }
                ]
            return []
        
        mock_schema_extractor.get_columns.side_effect = mock_get_columns_short
        mock_schema_extractor.get_tables.return_value = [{"table_name": "Users", "table_type": "TABLE"}]
        
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Users",
                    column="ShortEmail",
                    pii_type="email",
                    nullable=True
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        assert result.is_valid is False
        assert any(ErrorCodes.INSUFFICIENT_COLUMN_LENGTH in str(err.code) for err in result.errors)


class TestNullableConstraintValidation:
    """Tests for nullable constraint validation."""
    
    def test_nullable_mismatch_config_nullable_schema_not_null(self, mock_schema_extractor, sample_database_config):
        """Test error when config says nullable but schema is NOT NULL."""
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Orders",
                    column="CustomerID",  # NOT NULL in schema
                    pii_type="account_number",
                    nullable=True  # Config says nullable
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        assert result.is_valid is False
        assert any(ErrorCodes.NULLABLE_MISMATCH in str(err.code) for err in result.errors)
    
    def test_nullable_mismatch_config_not_nullable_schema_nullable(self, mock_schema_extractor, sample_database_config):
        """Test warning when config says not nullable but schema allows NULL."""
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Users",
                    column="Email",  # Nullable in schema
                    pii_type="email",
                    nullable=False  # Config says not nullable
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        # Should be valid but with warning
        assert result.is_valid is True
        assert any(ErrorCodes.NULLABLE_MISMATCH in str(warn.code) for warn in result.warnings)


class TestPrimaryKeyValidation:
    """Tests for primary key validation."""
    
    def test_pk_column_warning(self, mock_schema_extractor, sample_database_config):
        """Test warning for primary key columns."""
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Users",
                    column="UserID",  # Primary key
                    pii_type="account_number",
                    nullable=False
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        # Should have warnings about PK
        assert result.warning_count >= 1
        assert any(ErrorCodes.PK_COLUMN_WARNING in str(warn.code) for warn in result.warnings)


class TestForeignKeyValidation:
    """Tests for foreign key validation."""
    
    def test_fk_column_warning(self, mock_schema_extractor, sample_database_config):
        """Test warning for foreign key columns."""
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Orders",
                    column="CustomerID",  # Foreign key
                    pii_type="account_number",
                    nullable=False
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        # Should have warnings about FK
        assert result.warning_count >= 1
        assert any(ErrorCodes.FK_COLUMN_WARNING in str(warn.code) for warn in result.warnings)


class TestSpecialColumnValidation:
    """Tests for special column types (identity, computed)."""
    
    def test_identity_column_error(self, mock_schema_extractor, sample_database_config):
        """Test error for identity columns."""
        config = SanitizationConfig(
            database=sample_database_config,
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Users",
                    column="UserID",  # Identity column
                    pii_type="account_number",
                    nullable=False
                )
            ]
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_config(config)
        
        # Should have error about identity column
        assert result.is_valid is False
        assert any(ErrorCodes.IDENTITY_COLUMN_ERROR in str(err.code) for err in result.errors)


class TestValidateSingleColumn:
    """Tests for validate_single_column method."""
    
    def test_validate_single_column_valid(self, mock_schema_extractor):
        """Test validating single valid column."""
        pii_col = PIIColumnConfig(
            schema="dbo",
            table="Users",
            column="Email",
            pii_type="email",
            nullable=True
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_single_column(pii_col)
        
        assert result.is_valid is True
    
    def test_validate_single_column_invalid(self, mock_schema_extractor):
        """Test validating single invalid column."""
        pii_col = PIIColumnConfig(
            schema="dbo",
            table="Users",
            column="NonExistent",
            pii_type="email",
            nullable=True
        )
        
        validator = ConfigValidator(mock_schema_extractor)
        result = validator.validate_single_column(pii_col)
        
        assert result.is_valid is False
        assert result.error_count >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
