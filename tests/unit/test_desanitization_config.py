"""
Unit tests for desanitization configuration models.

This module tests the Pydantic-based configuration models for desanitization
operations, including validation, defaults, and field constraints.

Test Classes:
    TestEncryptionConfig: Tests for EncryptionConfig model
    TestMappingSourceConfig: Tests for MappingSourceConfig model
    TestRestorationConfig: Tests for RestorationConfig model
    TestPerformanceConfig: Tests for PerformanceConfig model
    TestCheckpointConfig: Tests for CheckpointConfig model
    TestValidationConfig: Tests for ValidationConfig model
    TestAuditConfig: Tests for AuditConfig model
    TestDesanitizationConfig: Tests for root DesanitizationConfig model
    TestMinimalConfigCreation: Tests for create_minimal_config helper

Coverage:
    - Valid configuration creation with defaults
    - Invalid configurations (out-of-range, missing required)
    - Field validation and constraints
    - Model validators (custom validation logic)
    - Configuration serialization (to_dict)
"""

import pytest
from pydantic import ValidationError

from desanitization.config_models import (
    DesanitizationConfig,
    MappingSourceConfig,
    EncryptionConfig,
    RestorationConfig,
    PerformanceConfig,
    CheckpointConfig,
    ValidationConfig,
    AuditConfig,
    create_minimal_config,
    DatabaseConfig,
)


class TestEncryptionConfig:
    """Tests for EncryptionConfig model."""
    
    def test_encryption_config_defaults(self):
        """Test EncryptionConfig with default values."""
        config = EncryptionConfig()
        
        assert config.enabled is False
        assert config.key_env_var == "MAPPING_ENCRYPTION_KEY"
        assert config.fallback_keys_env_vars == []
    
    def test_encryption_config_custom(self):
        """Test EncryptionConfig with custom values."""
        config = EncryptionConfig(
            enabled=True,
            key_env_var="CUSTOM_KEY",
            fallback_keys_env_vars=["OLD_KEY_1", "OLD_KEY_2"]
        )
        
        assert config.enabled is True
        assert config.key_env_var == "CUSTOM_KEY"
        assert config.fallback_keys_env_vars == ["OLD_KEY_1", "OLD_KEY_2"]
    
    def test_encryption_config_empty_key_var(self):
        """Test EncryptionConfig with empty key_env_var fails."""
        with pytest.raises(ValidationError) as exc_info:
            EncryptionConfig(key_env_var="")
        
        assert "key_env_var" in str(exc_info.value)


class TestMappingSourceConfig:
    """Tests for MappingSourceConfig model."""
    
    def test_mapping_source_defaults(self):
        """Test MappingSourceConfig with default values."""
        config = MappingSourceConfig()
        
        assert config.table_name == "token_mappings"
        assert config.schema_name == "dbo"
        assert isinstance(config.encryption, EncryptionConfig)
    
    def test_mapping_source_custom(self):
        """Test MappingSourceConfig with custom values."""
        config = MappingSourceConfig(
            table_name="custom_mappings",
            schema_name="sanitization"
        )
        
        assert config.table_name == "custom_mappings"
        assert config.schema_name == "sanitization"


class TestRestorationConfig:
    """Tests for RestorationConfig model."""
    
    def test_restoration_config_defaults(self):
        """Test RestorationConfig with safe defaults."""
        config = RestorationConfig()
        
        assert config.dry_run is True  # Safe default
        assert config.skip_verification is False
        assert config.strict is False
        assert config.skip_audit is False
        assert config.skip_missing is False
    
    def test_restoration_config_execute_mode(self):
        """Test RestorationConfig for execute mode."""
        config = RestorationConfig(dry_run=False, strict=True)
        
        assert config.dry_run is False
        assert config.strict is True


class TestPerformanceConfig:
    """Tests for PerformanceConfig model."""
    
    def test_performance_config_defaults(self):
        """Test PerformanceConfig with default values."""
        config = PerformanceConfig()
        
        assert config.enable_parallel is False
        assert config.max_workers == 4
        assert config.rate_limit_ms == 0
        assert config.batch_size == 10000
    
    def test_performance_config_custom(self):
        """Test PerformanceConfig with custom values."""
        config = PerformanceConfig(
            enable_parallel=True,
            max_workers=8,
            rate_limit_ms=500,
            batch_size=50000
        )
        
        assert config.enable_parallel is True
        assert config.max_workers == 8
        assert config.rate_limit_ms == 500
        assert config.batch_size == 50000
    
    def test_performance_config_max_workers_validation(self):
        """Test max_workers validation."""
        # Min value (1) is accepted
        config = PerformanceConfig(max_workers=1)
        assert config.max_workers == 1
        
        # Value < 1 is corrected by validator
        config = PerformanceConfig(max_workers=0)
        assert config.max_workers == 1  # Corrected by validator
        
        # Max value (32) is accepted
        config = PerformanceConfig(max_workers=32)
        assert config.max_workers == 32
        
        # Value > 32 fails validation
        with pytest.raises(ValidationError) as exc_info:
            PerformanceConfig(max_workers=64)
        assert "max_workers" in str(exc_info.value)
    
    def test_performance_config_negative_rate_limit(self):
        """Test negative rate_limit is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PerformanceConfig(rate_limit_ms=-1)
        assert "rate_limit_ms" in str(exc_info.value)
    
    def test_performance_config_batch_size_bounds(self):
        """Test batch_size bounds validation."""
        # Too small
        with pytest.raises(ValidationError):
            PerformanceConfig(batch_size=50)
        
        # Too large
        with pytest.raises(ValidationError):
            PerformanceConfig(batch_size=200000)
        
        # Valid range
        config = PerformanceConfig(batch_size=10000)
        assert config.batch_size == 10000


class TestCheckpointConfig:
    """Tests for CheckpointConfig model."""
    
    def test_checkpoint_config_defaults(self):
        """Test CheckpointConfig with default values."""
        config = CheckpointConfig()
        
        assert config.operation_id is None
        assert config.clear_stale is False
        assert config.stale_threshold_hours == 24
    
    def test_checkpoint_config_with_operation_id(self):
        """Test CheckpointConfig with valid operation ID."""
        config = CheckpointConfig(
            operation_id="DESAN-20260413123456-abcd1234"
        )
        
        assert config.operation_id == "DESAN-20260413123456-abcd1234"
    
    def test_checkpoint_config_invalid_operation_id_warning(self):
        """Test CheckpointConfig with invalid format (logs warning but accepts)."""
        # Should accept but log warning (validation is lenient)
        config = CheckpointConfig(operation_id="INVALID-ID")
        assert config.operation_id == "INVALID-ID"


class TestValidationConfig:
    """Tests for ValidationConfig model."""
    
    def test_validation_config_defaults(self):
        """Test ValidationConfig with default values."""
        config = ValidationConfig()
        
        assert config.skip_pre_validation is False
        assert config.strict_verification is False
        assert config.enable_fk_validation is True
        assert config.enable_row_count_check is True


class TestAuditConfig:
    """Tests for AuditConfig model."""
    
    def test_audit_config_defaults(self):
        """Test AuditConfig with default values."""
        config = AuditConfig()
        
        assert config.enabled is True
        assert config.table_name == "desanitization_audit_log"
        assert config.schema_name == "dbo"


class TestDesanitizationConfig:
    """Tests for root DesanitizationConfig model."""
    
    def test_desanitization_config_minimal(self):
        """Test DesanitizationConfig with minimal required fields."""
        db_config = DatabaseConfig(
            server="localhost",
            database="TestDB",
            auth_type="windows"
        )
        
        config = DesanitizationConfig(database=db_config)
        
        # Database config
        assert config.database.server == "localhost"
        assert config.database.database == "TestDB"
        
        # Defaults for other sections
        assert isinstance(config.mapping, MappingSourceConfig)
        assert isinstance(config.restoration, RestorationConfig)
        assert isinstance(config.performance, PerformanceConfig)
        assert isinstance(config.checkpoint, CheckpointConfig)
        assert isinstance(config.validation, ValidationConfig)
        assert isinstance(config.audit, AuditConfig)
    
    def test_desanitization_config_full(self):
        """Test DesanitizationConfig with all sections customized."""
        db_config = DatabaseConfig(
            server="prod-server",
            database="ProdDB",
            auth_type="sql",
            username="admin",
            password="secret"
        )
        
        config = DesanitizationConfig(
            database=db_config,
            mapping=MappingSourceConfig(table_name="prod_mappings"),
            restoration=RestorationConfig(dry_run=False),
            performance=PerformanceConfig(enable_parallel=True, max_workers=8),
            checkpoint=CheckpointConfig(stale_threshold_hours=48),
            validation=ValidationConfig(strict_verification=True),
            audit=AuditConfig(enabled=True)
        )
        
        assert config.database.server == "prod-server"
        assert config.mapping.table_name == "prod_mappings"
        assert config.restoration.dry_run is False
        assert config.performance.max_workers == 8
        assert config.checkpoint.stale_threshold_hours == 48
        assert config.validation.strict_verification is True
    
    def test_desanitization_config_parallel_validation(self):
        """Test DesanitizationConfig parallel configuration validator."""
        db_config = DatabaseConfig(
            server="localhost",
            database="TestDB",
            auth_type="windows"
        )
        
        # Invalid: parallel enabled but max_workers = 0 (gets corrected)
        config = DesanitizationConfig(
            database=db_config,
            performance=PerformanceConfig(enable_parallel=True, max_workers=0)
        )
        
        # Validator should have corrected max_workers to 1
        assert config.performance.max_workers == 1
    
    def test_desanitization_config_to_dict(self):
        """Test DesanitizationConfig serialization to dictionary."""
        db_config = DatabaseConfig(
            server="localhost",
            database="TestDB",
            auth_type="windows"
        )
        
        config = DesanitizationConfig(database=db_config)
        config_dict = config.to_dict()
        
        assert isinstance(config_dict, dict)
        assert "database" in config_dict
        assert "mapping" in config_dict
        assert "restoration" in config_dict
        assert config_dict["database"]["server"] == "localhost"


class TestMinimalConfigCreation:
    """Tests for create_minimal_config helper function."""
    
    def test_create_minimal_config_basic(self):
        """Test creating minimal config with basic arguments."""
        config = create_minimal_config("localhost", "TestDB")
        
        assert config.database.server == "localhost"
        assert config.database.database == "TestDB"
        assert config.database.auth_type == "windows"  # Default
        assert isinstance(config, DesanitizationConfig)
    
    def test_create_minimal_config_with_auth(self):
        """Test creating minimal config with SQL auth."""
        config = create_minimal_config(
            "prod-server",
            "ProdDB",
            auth_type="sql",
            username="admin",
            password="secret"
        )
        
        assert config.database.server == "prod-server"
        assert config.database.database == "ProdDB"
        assert config.database.auth_type == "sql"
        assert config.database.username == "admin"
        assert config.database.password == "secret"
    
    def test_create_minimal_config_defaults(self):
        """Test minimal config has safe defaults."""
        config = create_minimal_config("localhost", "TestDB")
        
        # Restoration defaults
        assert config.restoration.dry_run is True  # Safe default
        
        # Performance defaults
        assert config.performance.enable_parallel is False
        
        # Audit defaults
        assert config.audit.enabled is True
