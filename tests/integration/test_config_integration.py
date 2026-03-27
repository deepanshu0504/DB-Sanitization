"""Integration tests for configuration management.

This module tests configuration loading with actual files and integration
with other components like DatabaseConnectionManager.

Test Classes:
    TestConfigIntegration: Integration tests with real files
    TestConfigConnectionManagerIntegration: Integration with DatabaseConnectionManager

Requirements:
    - Actual config files in config/ directory
    - Optional: SQL Server for ConnectionManager tests
"""

import json
import os
from pathlib import Path

import pytest

from src.config import ConfigLoader, SanitizationConfig, DatabaseConfig, PIIColumnConfig


@pytest.fixture
def test_config_dir(tmp_path):
    """Create temporary config directory with test files."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def sample_config_file(test_config_dir):
    """Create sample configuration file."""
    config = {
        "database": {
            "server": "localhost",
            "database": "SanitizationTest",
            "auth_type": "windows",
            "timeout": 30,
            "batch_size": 10000,
            "environment": "dev"
        },
        "pii_columns": [
            {
                "schema": "dbo",
                "table": "Customers",
                "column": "Email",
                "pii_type": "email",
                "nullable": False
            },
            {
                "schema": "dbo",
                "table": "Customers",
                "column": "Phone",
                "pii_type": "phone",
                "nullable": True
            },
            {
                "schema": "dbo",
                "table": "Employees",
                "column": "SSN",
                "pii_type": "ssn",
                "nullable": False
            }
        ],
        "dry_run": False,
        "validate_before": True,
        "validate_after": True
    }
    
    config_file = test_config_dir / "sanitization.json"
    config_file.write_text(json.dumps(config, indent=2))
    return config_file


@pytest.fixture
def env_file(test_config_dir):
    """Create .env file for testing."""
    env_content = """
# Database Configuration
SANITIZATION_DATABASE_SERVER=env-server
SANITIZATION_DATABASE_USERNAME=env-user
SANITIZATION_DATABASE_PASSWORD=env-pass
SANITIZATION_DATABASE_BATCH_SIZE=15000
"""
    
    env_file = test_config_dir / ".env"
    env_file.write_text(env_content)
    return env_file


class TestConfigIntegration:
    """Integration tests with actual configuration files."""
    
    def test_load_complete_config_file(self, sample_config_file):
        """Test loading complete configuration from file."""
        loader = ConfigLoader()
        config = loader.load(str(sample_config_file), use_env_overrides=False)
        
        # Verify database config
        assert config.database.server == "localhost"
        assert config.database.database == "SanitizationTest"
        assert config.database.auth_type == "windows"
        assert config.database.batch_size == 10000
        
        # Verify PII columns
        assert len(config.pii_columns) == 3
        
        # Verify flags
        assert config.dry_run is False
        assert config.validate_before is True
        assert config.validate_after is True
    
    def test_load_with_environment_overrides(self, sample_config_file):
        """Test loading config with environment variable overrides."""
        loader = ConfigLoader()
        
        # Set environment variables
        env_vars = {
            "SANITIZATION_DATABASE_SERVER": "prod-server",
            "SANITIZATION_DATABASE_BATCH_SIZE": "20000",
            "SANITIZATION_DATABASE_TIMEOUT": "60"
        }
        
        with pytest.MonkeyPatch.context() as mp:
            for key, value in env_vars.items():
                mp.setenv(key, value)
            
            config = loader.load(str(sample_config_file), use_env_overrides=True)
        
        # Overridden values
        assert config.database.server == "prod-server"
        assert config.database.batch_size == 20000
        assert config.database.timeout == 60
        
        # Non-overridden values preserved
        assert config.database.database == "SanitizationTest"
    
    def test_load_multiple_environments(self, test_config_dir):
        """Test loading different environment configurations."""
        # Create dev config
        dev_config = {
            "database": {
                "server": "localhost",
                "database": "DevDB",
                "auth_type": "windows",
                "environment": "dev"
            },
            "pii_columns": []
        }
        
        # Create prod config
        prod_config = {
            "database": {
                "server": "prod-server",
                "database": "ProdDB",
                "auth_type": "sql",
                "username": "produser",
                "password": "prodpass",
                "environment": "prod"
            },
            "pii_columns": []
        }
        
        dev_file = test_config_dir / "dev.json"
        prod_file = test_config_dir / "prod.json"
        
        dev_file.write_text(json.dumps(dev_config))
        prod_file.write_text(json.dumps(prod_config))
        
        loader = ConfigLoader()
        
        # Load dev config
        dev_cfg = loader.load(str(dev_file), use_env_overrides=False)
        assert dev_cfg.database.server == "localhost"
        assert dev_cfg.database.environment == "dev"
        
        # Load prod config
        prod_cfg = loader.load(str(prod_file), use_env_overrides=False)
        assert prod_cfg.database.server == "prod-server"
        assert prod_cfg.database.environment == "prod"
    
    def test_save_and_reload_config(self, test_config_dir):
        """Test saving configuration and reloading it."""
        # Create config
        config = SanitizationConfig(
            database=DatabaseConfig(
                server="test-server",
                database="TestDB",
                auth_type="windows",
                batch_size=12000
            ),
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="Users",
                    column="Email",
                    pii_type="email",
                    nullable=False
                )
            ]
        )
        
        # Save
        output_file = test_config_dir / "saved.json"
        ConfigLoader.save_config(config, str(output_file))
        
        # Reload
        loader = ConfigLoader()
        loaded_config = loader.load(str(output_file), use_env_overrides=False)
        
        # Verify
        assert loaded_config.database.server == "test-server"
        assert loaded_config.database.batch_size == 12000
        assert len(loaded_config.pii_columns) == 1
        assert loaded_config.pii_columns[0].column == "Email"
    
    def test_cache_behavior_across_loads(self, sample_config_file):
        """Test caching behavior with multiple loads."""
        loader = ConfigLoader()
        loader.clear_cache()
        
        # First load - should cache
        config1 = loader.load(str(sample_config_file), use_cache=True)
        
        # Second load - should return cached
        config2 = loader.load(str(sample_config_file), use_cache=True)
        
        # Should be same instance (cached)
        assert config1 is config2
        
        # Clear cache
        loader.clear_cache()
        
        # Third load - should be new instance
        config3 = loader.load(str(sample_config_file), use_cache=True)
        
        assert config3 is not config1
    
    def test_pii_config_extraction(self, sample_config_file):
        """Test extracting PIIConfig from loaded configuration."""
        loader = ConfigLoader()
        config = loader.load(str(sample_config_file), use_env_overrides=False)
        
        pii_config = config.get_pii_config()
        
        assert len(pii_config.columns) == 3
        
        # Test get_columns_for_table
        customer_cols = pii_config.get_columns_for_table("dbo", "Customers")
        assert len(customer_cols) == 2
        
        employee_cols = pii_config.get_columns_for_table("dbo", "Employees")
        assert len(employee_cols) == 1
        
        # Test get_unique_tables
        tables = pii_config.get_unique_tables()
        assert len(tables) == 2
        assert ("dbo", "Customers") in tables
        assert ("dbo", "Employees") in tables


class TestConfigConnectionManagerIntegration:
    """Integration tests with DatabaseConnectionManager."""
    
    def test_create_connection_manager_from_config(self, sample_config_file):
        """Test creating DatabaseConnectionManager from loaded config."""
        from src.database import ConnectionConfig, AuthType
        
        loader = ConfigLoader()
        config = loader.load(str(sample_config_file), use_env_overrides=False)
        
        # Create ConnectionConfig from DatabaseConfig
        conn_config = ConnectionConfig(
            server=config.database.server,
            database=config.database.database,
            auth_type=AuthType.WINDOWS if config.database.auth_type == "windows" else AuthType.SQL,
            username=config.database.username,
            password=config.database.password,
            timeout=config.database.timeout
        )
        
        assert conn_config.server == "localhost"
        assert conn_config.database == "SanitizationTest"
        assert conn_config.auth_type == AuthType.WINDOWS
        assert conn_config.timeout == 30
    
    @pytest.mark.skipif(
        not os.environ.get("SQLSERVER_HOST"),
        reason="SQL Server connection not configured"
    )
    def test_full_integration_with_database(self, sample_config_file):
        """Test full integration: load config and connect to database."""
        from src.database import DatabaseConnectionManager, ConnectionConfig, AuthType
        
        # Load config
        loader = ConfigLoader()
        config = loader.load(str(sample_config_file), use_env_overrides=False)
        
        # Override with actual test database from environment
        config.database.server = os.environ.get("SQLSERVER_HOST", "localhost")
        config.database.database = os.environ.get("SQLSERVER_DB", "master")
        
        # Create connection config
        conn_config = ConnectionConfig(
            server=config.database.server,
            database=config.database.database,
            auth_type=AuthType.WINDOWS if config.database.auth_type == "windows" else AuthType.SQL,
            username=config.database.username,
            password=config.database.password,
            timeout=config.database.timeout
        )
        
        # Test connection
        with DatabaseConnectionManager(conn_config) as manager:
            if manager.health_check():
                # Run simple query
                results = manager.execute_query("SELECT DB_NAME() as current_db")
                assert len(results) > 0
                assert results[0][0] is not None
    
    def test_config_validation_catches_connection_errors(self):
        """Test that configuration validation catches incompatible settings."""
        # SQL auth without credentials should fail validation
        with pytest.raises(Exception):  # ValidationError
            config = SanitizationConfig(
                database=DatabaseConfig(
                    server="localhost",
                    database="TestDB",
                    auth_type="sql",
                    # Missing username and password
                ),
                pii_columns=[]
            )


class TestConfigEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_unicode_in_config(self, test_config_dir):
        """Test configuration with Unicode characters."""
        config = {
            "database": {
                "server": "localhost",
                "database": "TestDB",
                "auth_type": "windows"
            },
            "pii_columns": [
                {
                    "schema": "dbo",
                    "table": "Customers",
                    "column": "Naïve_Field_Café",  # Unicode
                    "pii_type": "name",
                    "nullable": False
                }
            ]
        }
        
        config_file = test_config_dir / "unicode.json"
        config_file.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
        
        loader = ConfigLoader()
        loaded_config = loader.load(str(config_file), use_env_overrides=False)
        
        assert loaded_config.pii_columns[0].column == "Naïve_Field_Café"
    
    def test_large_config_file(self, test_config_dir):
        """Test loading large configuration file with many PII columns."""
        # Generate large config
        pii_columns = []
        for i in range(100):
            pii_columns.append({
                "schema": "dbo",
                "table": f"Table_{i}",
                "column": f"Column_{i}",
                "pii_type": "email",
                "nullable": i % 2 == 0
            })
        
        config = {
            "database": {
                "server": "localhost",
                "database": "TestDB",
                "auth_type": "windows"
            },
            "pii_columns": pii_columns
        }
        
        config_file = test_config_dir / "large.json"
        config_file.write_text(json.dumps(config))
        
        loader = ConfigLoader()
        loaded_config = loader.load(str(config_file), use_env_overrides=False)
        
        assert len(loaded_config.pii_columns) == 100
    
    def test_minimal_config(self, test_config_dir):
        """Test minimal valid configuration."""
        config = {
            "database": {
                "server": "localhost",
                "database": "TestDB",
                "auth_type": "windows"
            },
            "pii_columns": []
        }
        
        config_file = test_config_dir / "minimal.json"
        config_file.write_text(json.dumps(config))
        
        loader = ConfigLoader()
        loaded_config = loader.load(str(config_file), use_env_overrides=False)
        
        assert loaded_config.database.server == "localhost"
        assert len(loaded_config.pii_columns) == 0
        assert loaded_config.database.batch_size == 10000  # default
        assert loaded_config.dry_run is False  # default
