"""Unit tests for configuration models.

This module tests all Pydantic configuration models including validation,
type coercion, custom validators, and edge cases.

Test Classes:
    TestEnvironment: Tests for Environment enum
    TestDatabaseConfig: Tests for DatabaseConfig model
    TestPIIColumnConfig: Tests for PIIColumnConfig model
    TestPIIConfig: Tests for PIIConfig collection model
    TestSanitizationConfig: Tests for root configuration model

Coverage:
    - Valid configuration creation
    - Validation error scenarios
    - Type coercion and boundaries
    - Custom validators
    - Serialization (to/from JSON)
    - Security (password masking)
"""

import pytest
from pydantic import ValidationError

from src.config.config_models import (
    DatabaseConfig,
    Environment,
    PIIColumnConfig,
    PIIConfig,
    SanitizationConfig,
)
from src.exceptions import ConfigValidationError


class TestEnvironment:
    """Tests for Environment enum."""
    
    def test_environment_values(self):
        """Test Environment enum has expected values."""
        assert Environment.DEV == "dev"
        assert Environment.STAGING == "staging"
        assert Environment.PROD == "prod"
    
    def test_environment_from_string(self):
        """Test creating Environment from string."""
        assert Environment("dev") == Environment.DEV
        assert Environment("staging") == Environment.STAGING
        assert Environment("prod") == Environment.PROD
    
    def test_invalid_environment(self):
        """Test invalid environment value raises error."""
        with pytest.raises(ValueError):
            Environment("invalid")


class TestDatabaseConfig:
    """Tests for DatabaseConfig model."""
    
    def test_valid_windows_auth_config(self):
        """Test creating valid Windows authentication config."""
        config = DatabaseConfig(
            server="localhost",
            database="TestDB",
            auth_type="windows"
        )
        
        assert config.server == "localhost"
        assert config.database == "TestDB"
        assert config.auth_type == "windows"
        assert config.username is None
        assert config.password is None
        assert config.timeout == 30  # default
        assert config.batch_size == 10000  # default
        assert config.environment == Environment.DEV  # default
    
    def test_valid_sql_auth_config(self):
        """Test creating valid SQL Server authentication config."""
        config = DatabaseConfig(
            server="localhost",
            database="TestDB",
            auth_type="sql",
            username="testuser",
            password="testpass123"
        )
        
        assert config.server == "localhost"
        assert config.database == "TestDB"
        assert config.auth_type == "sql"
        assert config.username == "testuser"
        assert config.password == "testpass123"
    
    def test_custom_values(self):
        """Test config with custom values."""
        config = DatabaseConfig(
            server="prod-server",
            database="ProdDB",
            auth_type="windows",
            timeout=60,
            batch_size=20000,
            max_retries=5,
            retry_delay=2.0,
            pool_size=10,
            environment=Environment.PROD
        )
        
        assert config.timeout == 60
        assert config.batch_size == 20000
        assert config.max_retries == 5
        assert config.retry_delay == 2.0
        assert config.pool_size == 10
        assert config.environment == Environment.PROD
    
    def test_sql_auth_missing_username(self):
        """Test SQL auth without username raises error."""
        with pytest.raises(ConfigValidationError):
            DatabaseConfig(
                server="localhost",
                database="TestDB",
                auth_type="sql",
                password="testpass123"
            )
        
        assert "username is required" in str(exc_info.value)
    
    def test_sql_auth_missing_password(self):
        """Test SQL auth without password raises error."""
        with pytest.raises(ConfigValidationError):
            DatabaseConfig(
                server="localhost",
                database="TestDB",
                auth_type="sql",
                username="testuser"
            )
        
        assert "password is required" in str(exc_info.value)
    
    def test_empty_server_name(self):
        """Test empty server name raises error."""
        with pytest.raises(ValidationError):
            DatabaseConfig(
                server="",
                database="TestDB",
                auth_type="windows"
            )
    
    def test_empty_database_name(self):
        """Test empty database name raises error."""
        with pytest.raises(ValidationError):
            DatabaseConfig(
                server="localhost",
                database="",
                auth_type="windows"
            )
    
    def test_timeout_below_minimum(self):
        """Test timeout below 5 seconds raises error."""
        with pytest.raises(ValidationError):
            DatabaseConfig(
                server="localhost",
                database="TestDB",
                auth_type="windows",
                timeout=3
            )
    
    def test_timeout_above_maximum(self):
        """Test timeout above 300 seconds raises error."""
        with pytest.raises(ValidationError):
            DatabaseConfig(
                server="localhost",
                database="TestDB",
                auth_type="windows",
                timeout=400
            )
    
    def test_batch_size_below_minimum(self):
        """Test batch_size below 100 raises error."""
        with pytest.raises(ValidationError):
            DatabaseConfig(
                server="localhost",
                database="TestDB",
                auth_type="windows",
                batch_size=50
            )
    
    def test_batch_size_above_maximum(self):
        """Test batch_size above 1,000,000 raises error."""
        with pytest.raises(ValidationError):
            DatabaseConfig(
                server="localhost",
                database="TestDB",
                auth_type="windows",
                batch_size=2000000
            )
    
    def test_invalid_auth_type(self):
        """Test invalid auth_type raises error."""
        with pytest.raises(ValidationError):
            DatabaseConfig(
                server="localhost",
                database="TestDB",
                auth_type="invalid"
            )
    
    def test_safe_repr_masks_password(self):
        """Test __repr__ masks password."""
        config = DatabaseConfig(
            server="localhost",
            database="TestDB",
            auth_type="sql",
            username="testuser",
            password="secret123"
        )
        
        repr_str = repr(config)
        assert "secret123" not in repr_str
        assert "password='***'" in repr_str
        assert "localhost" in repr_str
    
    def test_whitespace_stripping(self):
        """Test whitespace is stripped from strings."""
        config = DatabaseConfig(
            server="  localhost  ",
            database="  TestDB  ",
            auth_type="windows"
        )
        
        assert config.server == "localhost"
        assert config.database == "TestDB"
    
    def test_serialization_to_dict(self):
        """Test serialization to dictionary."""
        config = DatabaseConfig(
            server="localhost",
            database="TestDB",
            auth_type="windows",
            batch_size=15000
        )
        
        config_dict = config.model_dump()
        assert config_dict["server"] == "localhost"
        assert config_dict["database"] == "TestDB"
        assert config_dict["batch_size"] == 15000
    
    def test_serialization_to_json(self):
        """Test serialization to JSON."""
        config = DatabaseConfig(
            server="localhost",
            database="TestDB",
            auth_type="windows"
        )
        
        json_str = config.model_dump_json()
        assert "localhost" in json_str
        assert "TestDB" in json_str


class TestPIIColumnConfig:
    """Tests for PIIColumnConfig model."""
    
    def test_valid_pii_column(self):
        """Test creating valid PII column config."""
        pii_col = PIIColumnConfig(
            schema="dbo",
            table="Customers",
            column="Email",
            pii_type="email",
            nullable=False
        )
        
        assert pii_col.schema == "dbo"
        assert pii_col.table == "Customers"
        assert pii_col.column == "Email"
        assert pii_col.pii_type == "email"
        assert pii_col.nullable is False
        assert pii_col.custom_format is None
    
    def test_all_pii_types(self):
        """Test all supported PII types."""
        pii_types = ["email", "phone", "name", "ssn", "generic"]
        
        for pii_type in pii_types:
            pii_col = PIIColumnConfig(
                schema="dbo",
                table="Test",
                column="Col",
                pii_type=pii_type,
                nullable=True
            )
            assert pii_col.pii_type == pii_type
    
    def test_invalid_pii_type(self):
        """Test invalid PII type raises error."""
        with pytest.raises(ValidationError):
            PIIColumnConfig(
                schema="dbo",
                table="Test",
                column="Col",
                pii_type="invalid_type",
                nullable=False
            )
    
    def test_custom_format(self):
        """Test PII column with custom format."""
        pii_col = PIIColumnConfig(
            schema="dbo",
            table="Test",
            column="CustomField",
            pii_type="generic",
            nullable=True,
            custom_format="XXX-XXX-XXXX"
        )
        
        assert pii_col.custom_format == "XXX-XXX-XXXX"
    
    def test_fully_qualified_name(self):
        """Test fully_qualified_name property."""
        pii_col = PIIColumnConfig(
            schema="dbo",
            table="Customers",
            column="Email",
            pii_type="email",
            nullable=False
        )
        
        assert pii_col.fully_qualified_name == "[dbo].[Customers].[Email]"
    
    def test_table_qualified_name(self):
        """Test table_qualified_name property."""
        pii_col = PIIColumnConfig(
            schema="dbo",
            table="Customers",
            column="Email",
            pii_type="email",
            nullable=False
        )
        
        assert pii_col.table_qualified_name == "[dbo].[Customers]"
    
    def test_special_characters_in_names(self):
        """Test handling of special characters in schema/table/column names."""
        pii_col = PIIColumnConfig(
            schema="custom schema",
            table="my-table",
            column="email@address",
            pii_type="email",
            nullable=False
        )
        
        assert pii_col.fully_qualified_name == "[custom schema].[my-table].[email@address]"
    
    def test_empty_schema_name(self):
        """Test empty schema name raises error."""
        with pytest.raises(ValidationError):
            PIIColumnConfig(
                schema="",
                table="Test",
                column="Col",
                pii_type="email",
                nullable=False
            )
    
    def test_empty_table_name(self):
        """Test empty table name raises error."""
        with pytest.raises(ValidationError):
            PIIColumnConfig(
                schema="dbo",
                table="",
                column="Col",
                pii_type="email",
                nullable=False
            )
    
    def test_empty_column_name(self):
        """Test empty column name raises error."""
        with pytest.raises(ValidationError):
            PIIColumnConfig(
                schema="dbo",
                table="Test",
                column="",
                pii_type="email",
                nullable=False
            )


class TestPIIConfig:
    """Tests for PIIConfig collection model."""
    
    def test_empty_pii_config(self):
        """Test creating empty PII config."""
        pii_config = PIIConfig()
        
        assert len(pii_config.columns) == 0
        assert pii_config.version == "1.0"
        assert pii_config.description is None
    
    def test_pii_config_with_columns(self):
        """Test PII config with multiple columns."""
        columns = [
            PIIColumnConfig(
                schema="dbo",
                table="Customers",
                column="Email",
                pii_type="email",
                nullable=False
            ),
            PIIColumnConfig(
                schema="dbo",
                table="Customers",
                column="Phone",
                pii_type="phone",
                nullable=True
            )
        ]
        
        pii_config = PIIConfig(
            columns=columns,
            version="2.0",
            description="Test configuration"
        )
        
        assert len(pii_config.columns) == 2
        assert pii_config.version == "2.0"
        assert pii_config.description == "Test configuration"
    
    def test_duplicate_columns_validation(self):
        """Test duplicate column configurations raise error."""
        columns = [
            PIIColumnConfig(
                schema="dbo",
                table="Customers",
                column="Email",
                pii_type="email",
                nullable=False
            ),
            PIIColumnConfig(
                schema="dbo",
                table="Customers",
                column="Email",  # Duplicate
                pii_type="email",
                nullable=False
            )
        ]
        
        with pytest.raises(ValidationError) as exc_info:
            PIIConfig(columns=columns)
        
        assert "Duplicate" in str(exc_info.value)
    
    def test_get_columns_for_table(self):
        """Test get_columns_for_table method."""
        columns = [
            PIIColumnConfig(
                schema="dbo",
                table="Customers",
                column="Email",
                pii_type="email",
                nullable=False
            ),
            PIIColumnConfig(
                schema="dbo",
                table="Customers",
                column="Phone",
                pii_type="phone",
                nullable=True
            ),
            PIIColumnConfig(
                schema="dbo",
                table="Employees",
                column="SSN",
                pii_type="ssn",
                nullable=False
            )
        ]
        
        pii_config = PIIConfig(columns=columns)
        customer_cols = pii_config.get_columns_for_table("dbo", "Customers")
        
        assert len(customer_cols) == 2
        assert all(col.table == "Customers" for col in customer_cols)
    
    def test_get_unique_tables(self):
        """Test get_unique_tables method."""
        columns = [
            PIIColumnConfig(
                schema="dbo",
                table="Customers",
                column="Email",
                pii_type="email",
                nullable=False
            ),
            PIIColumnConfig(
                schema="dbo",
                table="Customers",
                column="Phone",
                pii_type="phone",
                nullable=True
            ),
            PIIColumnConfig(
                schema="sales",
                table="Orders",
                column="CustomerEmail",
                pii_type="email",
                nullable=False
            )
        ]
        
        pii_config = PIIConfig(columns=columns)
        tables = pii_config.get_unique_tables()
        
        assert len(tables) == 2
        assert ("dbo", "Customers") in tables
        assert ("sales", "Orders") in tables


class TestSanitizationConfig:
    """Tests for SanitizationConfig root model."""
    
    def test_valid_sanitization_config(self):
        """Test creating valid sanitization config."""
        config = SanitizationConfig(
            database=DatabaseConfig(
                server="localhost",
                database="TestDB",
                auth_type="windows"
            ),
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Customers",
                    column="Email",
                    pii_type="email",
                    nullable=False
                )
            ]
        )
        
        assert config.database.server == "localhost"
        assert len(config.pii_columns) == 1
        assert config.dry_run is False
        assert config.validate_before is True
        assert config.validate_after is True
    
    def test_sanitization_config_with_flags(self):
        """Test sanitization config with custom flags."""
        config = SanitizationConfig(
            database=DatabaseConfig(
                server="localhost",
                database="TestDB",
                auth_type="windows"
            ),
            pii_columns=[],
            dry_run=True,
            validate_before=False,
            validate_after=False
        )
        
        assert config.dry_run is True
        assert config.validate_before is False
        assert config.validate_after is False
    
    def test_duplicate_pii_columns(self):
        """Test duplicate PII columns raise error."""
        with pytest.raises(ValidationError) as exc_info:
            SanitizationConfig(
                database=DatabaseConfig(
                    server="localhost",
                    database="TestDB",
                    auth_type="windows"
                ),
                pii_columns=[
                    PIIColumnConfig(
                        schema="dbo",
                        table="Customers",
                        column="Email",
                        pii_type="email",
                        nullable=False
                    ),
                    PIIColumnConfig(
                        schema="dbo",
                        table="Customers",
                        column="Email",
                        pii_type="email",
                        nullable=False
                    )
                ]
            )
        
        assert "Duplicate" in str(exc_info.value)
    
    def test_get_pii_config(self):
        """Test get_pii_config method."""
        config = SanitizationConfig(
            database=DatabaseConfig(
                server="localhost",
                database="TestDB",
                auth_type="windows"
            ),
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Customers",
                    column="Email",
                    pii_type="email",
                    nullable=False
                ),
                PIIColumnConfig(
                    schema="dbo",
                    table="Customers",
                    column="Phone",
                    pii_type="phone",
                    nullable=True
                )
            ]
        )
        
        pii_config = config.get_pii_config()
        
        assert isinstance(pii_config, PIIConfig)
        assert len(pii_config.columns) == 2
    
    def test_serialization_full_config(self):
        """Test serialization of full configuration."""
        config = SanitizationConfig(
            database=DatabaseConfig(
                server="localhost",
                database="TestDB",
                auth_type="windows",
                batch_size=15000
            ),
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Customers",
                    column="Email",
                    pii_type="email",
                    nullable=False
                )
            ],
            dry_run=True
        )
        
        config_dict = config.model_dump()
        
        assert config_dict["database"]["server"] == "localhost"
        assert config_dict["database"]["batch_size"] == 15000
        assert len(config_dict["pii_columns"]) == 1
        assert config_dict["dry_run"] is True
