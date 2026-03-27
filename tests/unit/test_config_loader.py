"""Unit tests for configuration loader.

This module tests ConfigLoader functionality including JSON loading,
environment variable overrides, caching, validation, and error handling.

Test Classes:
    TestConfigLoader: Tests for ConfigLoader class
    TestConfigLoaderFileOperations: Tests for file I/O operations
    TestConfigLoaderEnvironmentOverrides: Tests for env var overrides
    TestConfigLoaderCaching: Tests for caching behavior
    TestConfigLoaderValidation: Tests for validation and error handling

Coverage:
    - JSON file loading (valid, invalid syntax, missing files)
    - Environment variable overrides and type coercion
    - Configuration merging logic
    - Caching and cache management
    - Save configuration functionality
    - Error handling and clear error messages
"""

import json
import os
from pathlib import Path
from unittest.mock import Mock, mock_open, patch, MagicMock

import pytest
from pydantic import ValidationError

from src.config.config_loader import ConfigLoader
from src.exceptions import ConfigFileError, ConfigValidationError
from src.config.config_models import SanitizationConfig


@pytest.fixture
def sample_config_dict():
    """Sample valid configuration dictionary."""
    return {
        "database": {
            "server": "localhost",
            "database": "TestDB",
            "auth_type": "windows",
            "batch_size": 10000
        },
        "pii_columns": [
            {
                "schema": "dbo",
                "table": "Customers",
                "column": "Email",
                "pii_type": "email",
                "nullable": False
            }
        ]
    }


@pytest.fixture
def sample_config_json(sample_config_dict):
    """Sample valid configuration JSON string."""
    return json.dumps(sample_config_dict, indent=2)


@pytest.fixture
def loader():
    """Fresh ConfigLoader instance."""
    # Reset singleton for testing
    ConfigLoader._instance = None
    loader = ConfigLoader()
    loader.clear_cache()
    return loader


class TestConfigLoader:
    """Tests for ConfigLoader basic functionality."""
    
    def test_singleton_pattern(self):
        """Test ConfigLoader implements singleton pattern."""
        loader1 = ConfigLoader()
        loader2 = ConfigLoader()
        
        assert loader1 is loader2
    
    def test_initialization(self, loader):
        """Test ConfigLoader initialization."""
        assert hasattr(loader, '_cache')
        assert hasattr(loader, '_cache_lock')
    
    def test_coerce_value_boolean_true(self, loader):
        """Test type coercion for boolean true values."""
        assert loader._coerce_value("true") is True
        assert loader._coerce_value("True") is True
        assert loader._coerce_value("yes") is True
        assert loader._coerce_value("1") is True
    
    def test_coerce_value_boolean_false(self, loader):
        """Test type coercion for boolean false values."""
        assert loader._coerce_value("false") is False
        assert loader._coerce_value("False") is False
        assert loader._coerce_value("no") is False
        assert loader._coerce_value("0") is False
    
    def test_coerce_value_integer(self, loader):
        """Test type coercion for integer values."""
        assert loader._coerce_value("42") == 42
        assert loader._coerce_value("0") == 0
        assert loader._coerce_value("-10") == -10
    
    def test_coerce_value_float(self, loader):
        """Test type coercion for float values."""
        assert loader._coerce_value("3.14") == 3.14
        assert loader._coerce_value("0.5") == 0.5
        assert loader._coerce_value("-2.5") == -2.5
    
    def test_coerce_value_string(self, loader):
        """Test type coercion for string values."""
        assert loader._coerce_value("hello") == "hello"
        assert loader._coerce_value("some text") == "some text"


class TestConfigLoaderFileOperations:
    """Tests for file loading operations."""
    
    def test_validate_file_exists_valid_file(self, loader, tmp_path):
        """Test file existence validation with valid file."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{}")
        
        # Should not raise exception
        loader._validate_file_exists(str(config_file))
    
    def test_validate_file_exists_missing_file(self, loader):
        """Test file existence validation with missing file."""
        with pytest.raises(FileNotFoundError) as exc_info:
            loader._validate_file_exists("nonexistent.json")
        
        assert "not found" in str(exc_info.value).lower()
    
    def test_validate_file_exists_directory(self, loader, tmp_path):
        """Test file existence validation with directory path."""
        with pytest.raises(ValueError) as exc_info:
            loader._validate_file_exists(str(tmp_path))
        
        assert "not a file" in str(exc_info.value).lower()
    
    def test_load_from_json_valid(self, loader, sample_config_json, tmp_path):
        """Test loading valid JSON file."""
        config_file = tmp_path / "config.json"
        config_file.write_text(sample_config_json)
        
        config_dict = loader._load_from_json(str(config_file))
        
        assert config_dict["database"]["server"] == "localhost"
        assert len(config_dict["pii_columns"]) == 1
    
    def test_load_from_json_invalid_syntax(self, loader, tmp_path):
        """Test loading JSON file with invalid syntax."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{invalid json")
        
        with pytest.raises(json.JSONDecodeError):
            loader._load_from_json(str(config_file))
    
    def test_load_from_json_utf8_encoding(self, loader, tmp_path):
        """Test loading JSON file with UTF-8 characters."""
        config_file = tmp_path / "config.json"
        config_dict = {
            "database": {
                "server": "localhost",
                "database": "TestDB",
                "auth_type": "windows"
            },
            "pii_columns": [{
                "schema": "dbo",
                "table": "Users",
                "column": "Naïme",  # UTF-8 character
                "pii_type": "name",
                "nullable": False
            }]
        }
        config_file.write_text(json.dumps(config_dict), encoding='utf-8')
        
        loaded_dict = loader._load_from_json(str(config_file))
        
        assert loaded_dict["pii_columns"][0]["column"] == "Naïme"
    
    def test_load_complete_valid_file(self, loader, sample_config_json, tmp_path):
        """Test complete load operation with valid file."""
        config_file = tmp_path / "config.json"
        config_file.write_text(sample_config_json)
        
        config = loader.load(str(config_file), use_env_overrides=False)
        
        assert isinstance(config, SanitizationConfig)
        assert config.database.server == "localhost"
        assert len(config.pii_columns) == 1
    
    def test_load_missing_file_error(self, loader):
        """Test loading missing file raises clear error."""
        with pytest.raises(FileNotFoundError) as exc_info:
            loader.load("nonexistent.json", use_env_overrides=False)
        
        assert "not found" in str(exc_info.value).lower()


class TestConfigLoaderEnvironmentOverrides:
    """Tests for environment variable override functionality."""
    
    def test_load_from_env_no_variables(self, loader):
        """Test loading from env with no SANITIZATION_ variables."""
        with patch.dict(os.environ, {}, clear=True):
            overrides = loader._load_from_env()
            assert overrides == {}
    
    def test_load_from_env_database_overrides(self, loader):
        """Test loading database configuration from env variables."""
        env_vars = {
            "SANITIZATION_DATABASE_SERVER": "prod-server",
            "SANITIZATION_DATABASE_BATCH_SIZE": "20000",
            "SANITIZATION_DATABASE_TIMEOUT": "60"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            overrides = loader._load_from_env()
        
        assert overrides["database"]["server"] == "prod-server"
        assert overrides["database"]["batch_size"] == 20000
        assert overrides["database"]["timeout"] == 60
    
    def test_load_from_env_password_not_logged(self, loader, caplog):
        """Test password environment variable is not logged."""
        import logging
        caplog.set_level(logging.DEBUG)
        
        env_vars = {
            "SANITIZATION_DATABASE_PASSWORD": "secret123"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            overrides = loader._load_from_env()
        
        # Check that password was loaded
        assert "database" in overrides
        assert "password" in overrides["database"]
        assert overrides["database"]["password"] == "secret123"
        
        # Check that "secret123" doesn't appear in logs
        log_text = caplog.text
        assert "secret123" not in log_text
    
    def test_load_from_env_type_coercion(self, loader):
        """Test environment variable type coercion."""
        env_vars = {
            "SANITIZATION_DATABASE_BATCH_SIZE": "15000",  # int
            "SANITIZATION_DATABASE_RETRY_DELAY": "2.5",  # float
            "SANITIZATION_DATABASE_DRY_RUN": "true",  # bool
            "SANITIZATION_DATABASE_SERVER": "localhost"  # string
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            overrides = loader._load_from_env()
        
        assert isinstance(overrides["database"]["batch_size"], int)
        assert isinstance(overrides["database"]["retry_delay"], float)
        assert isinstance(overrides["database"]["dry_run"], bool)
        assert isinstance(overrides["database"]["server"], str)
    
    def test_load_from_env_invalid_format_ignored(self, loader, caplog):
        """Test invalid env variable format is ignored with warning."""
        env_vars = {
            "SANITIZATION_INVALID": "value",  # Missing section_key split
            "SANITIZATION_DATABASE_SERVER": "localhost"  # Valid
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            overrides = loader._load_from_env()
        
        # Valid one should be loaded
        assert "database" in overrides
        # Invalid one should be ignored
        assert "INVALID" not in str(overrides)
    
    def test_merge_configs_simple(self, loader):
        """Test merging configurations with simple overrides."""
        base = {
            "database": {
                "server": "localhost",
                "timeout": 30
            }
        }
        overrides = {
            "database": {
                "server": "prod-server"
            }
        }
        
        merged = loader._merge_configs(base, overrides)
        
        assert merged["database"]["server"] == "prod-server"
        assert merged["database"]["timeout"] == 30  # Preserved from base
    
    def test_merge_configs_new_section(self, loader):
        """Test merging with new section in overrides."""
        base = {
            "database": {
                "server": "localhost"
            }
        }
        overrides = {
            "new_section": {
                "key": "value"
            }
        }
        
        merged = loader._merge_configs(base, overrides)
        
        assert "database" in merged
        assert "new_section" in merged
        assert merged["new_section"]["key"] == "value"
    
    def test_load_with_env_overrides(self, loader, sample_config_json, tmp_path):
        """Test complete load with environment variable overrides."""
        config_file = tmp_path / "config.json"
        config_file.write_text(sample_config_json)
        
        env_vars = {
            "SANITIZATION_DATABASE_SERVER": "override-server",
            "SANITIZATION_DATABASE_BATCH_SIZE": "25000"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            config = loader.load(str(config_file), use_env_overrides=True)
        
        assert config.database.server == "override-server"
        assert config.database.batch_size == 25000


class TestConfigLoaderCaching:
    """Tests for caching functionality."""
    
    def test_load_without_cache(self, loader, sample_config_json, tmp_path):
        """Test loading without using cache."""
        config_file = tmp_path / "config.json"
        config_file.write_text(sample_config_json)
        
        config1 = loader.load(str(config_file), use_cache=False)
        config2 = loader.load(str(config_file), use_cache=False)
        
        # Different instances (not cached)
        assert config1 is not config2
    
    def test_load_with_cache(self, loader, sample_config_json, tmp_path):
        """Test loading with caching enabled."""
        config_file = tmp_path / "config.json"
        config_file.write_text(sample_config_json)
        
        config1 = loader.load(str(config_file), use_cache=True)
        config2 = loader.load(str(config_file), use_cache=True)
        
        # Same instance (cached)
        assert config1 is config2
    
    def test_cache_key_includes_env_override_flag(self, loader, sample_config_json, tmp_path):
        """Test cache key differentiates between env override settings."""
        config_file = tmp_path / "config.json"
        config_file.write_text(sample_config_json)
        
        config1 = loader.load(str(config_file), use_env_overrides=False, use_cache=True)
        config2 = loader.load(str(config_file), use_env_overrides=True, use_cache=True)
        
        # Different cache keys, so different instances
        assert config1 is not config2
    
    def test_clear_cache(self, loader, sample_config_json, tmp_path):
        """Test clearing the cache."""
        config_file = tmp_path / "config.json"
        config_file.write_text(sample_config_json)
        
        config1 = loader.load(str(config_file), use_cache=True)
        loader.clear_cache()
        config2 = loader.load(str(config_file), use_cache=True)
        
        # Different instances after cache clear
        assert config1 is not config2
    
    def test_get_cached_config_exists(self, loader, sample_config_json, tmp_path):
        """Test getting cached configuration that exists."""
        config_file = tmp_path / "config.json"
        config_file.write_text(sample_config_json)
        
        config = loader.load(str(config_file), use_cache=True)
        cached = loader.get_cached_config(str(config_file))
        
        assert cached is config
    
    def test_get_cached_config_not_exists(self, loader):
        """Test getting cached configuration that doesn't exist."""
        cached = loader.get_cached_config("nonexistent.json")
        assert cached is None


class TestConfigLoaderValidation:
    """Tests for validation and error handling."""
    
    def test_validate_config_valid(self):
        """Test validate_config with valid configuration."""
        config_dict = {
            "database": {
                "server": "localhost",
                "database": "TestDB",
                "auth_type": "windows"
            },
            "pii_columns": []
        }
        
        config = ConfigLoader.validate_config(config_dict)
        
        assert isinstance(config, SanitizationConfig)
        assert config.database.server == "localhost"
    
    def test_validate_config_invalid(self):
        """Test validate_config with invalid configuration."""
        config_dict = {
            "database": {
                "server": "",  # Invalid: empty string
                "database": "TestDB",
                "auth_type": "windows"
            },
            "pii_columns": []
        }
        
        with pytest.raises(ValidationError):
            ConfigLoader.validate_config(config_dict)
    
    def test_validate_config_missing_required_field(self):
        """Test validate_config with missing required field."""
        config_dict = {
            "database": {
                "server": "localhost",
                # Missing "database" field
                "auth_type": "windows"
            },
            "pii_columns": []
        }
        
        with pytest.raises(ValidationError):
            ConfigLoader.validate_config(config_dict)
    
    def test_load_validation_error_propagates(self, loader, tmp_path):
        """Test that validation errors propagate with clear messages."""
        invalid_config = {
            "database": {
                "server": "localhost",
                "database": "TestDB",
                "auth_type": "sql",
                # Missing username and password for SQL auth
            },
            "pii_columns": []
        }
        
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(invalid_config))
        
        with pytest.raises(ValidationError):
            loader.load(str(config_file))


class TestConfigLoaderSave:
    """Tests for configuration saving functionality."""
    
    def test_save_config_valid(self, tmp_path):
        """Test saving valid configuration to file."""
        from src.config import DatabaseConfig, PIIColumnConfig, SanitizationConfig
        
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
        
        output_file = tmp_path / "output.json"
        ConfigLoader.save_config(config, str(output_file))
        
        assert output_file.exists()
        
        # Load and verify
        with open(output_file, 'r') as f:
            saved_dict = json.load(f)
        
        assert saved_dict["database"]["server"] == "localhost"
        assert len(saved_dict["pii_columns"]) == 1
    
    def test_save_config_excludes_password(self, tmp_path):
        """Test saving configuration excludes password."""
        from src.config import DatabaseConfig, SanitizationConfig
        
        config = SanitizationConfig(
            database=DatabaseConfig(
                server="localhost",
                database="TestDB",
                auth_type="sql",
                username="testuser",
                password="secret123"
            ),
            pii_columns=[]
        )
        
        output_file = tmp_path / "output.json"
        ConfigLoader.save_config(config, str(output_file))
        
        # Verify password is not in saved file
        with open(output_file, 'r') as f:
            content = f.read()
        
        assert "secret123" not in content
    
    def test_save_config_creates_directory(self, tmp_path):
        """Test save_config creates parent directory if needed."""
        from src.config import DatabaseConfig, SanitizationConfig
        
        config = SanitizationConfig(
            database=DatabaseConfig(
                server="localhost",
                database="TestDB",
                auth_type="windows"
            ),
            pii_columns=[]
        )
        
        output_file = tmp_path / "subdir" / "config.json"
        ConfigLoader.save_config(config, str(output_file))
        
        assert output_file.exists()
        assert output_file.parent.exists()
