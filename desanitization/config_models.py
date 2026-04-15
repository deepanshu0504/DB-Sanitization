"""
Configuration models for database desanitization framework.

This module provides Pydantic-based configuration models specifically for
the desanitization/restoration workflow. These models are separate from
the sanitization configuration to maintain clear separation of concerns.

Classes:
    MappingSourceConfig: Configuration for mapping table source
    EncryptionConfig: Configuration for mapping encryption
    RestorationConfig: Configuration for restoration behavior
    PerformanceConfig: Configuration for performance optimization
    CheckpointConfig: Configuration for checkpoint/resume operations
    ValidationConfig: Configuration for validation behavior
    AuditConfig: Configuration for audit logging
    DesanitizationConfig: Root configuration model

Example:
    >>> from desanitization.config_models import DesanitizationConfig
    >>> config = DesanitizationConfig(
    ...     database=DatabaseConfig(server="localhost", database="TestDB"),
    ...     restoration=RestorationConfig(dry_run=False)
    ... )
    >>> config.restoration.dry_run
    False

Environment Variables:
    Configuration can be overridden with environment variables using the pattern:
    DESANITIZATION_{SECTION}_{KEY}
    
    Examples:
        DESANITIZATION_DATABASE_SERVER=prod-server
        DESANITIZATION_DATABASE_DATABASE=ProductionDB
        DESANITIZATION_RESTORATION_DRY_RUN=false
        DESANITIZATION_PERFORMANCE_MAX_WORKERS=8

Author: Database Sanitization Team
Date: April 13, 2026
"""

import logging
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


# Define DatabaseConfig directly (no external src/ dependencies)
class DatabaseConfig(BaseModel):
    """Database connection configuration.
    
    Attributes:
        server: SQL Server hostname or IP address
        database: Database name to connect to
        auth_type: Authentication type ("windows" or "sql")
        username: SQL Server username (required if auth_type="sql")
        password: SQL Server password (required if auth_type="sql")
        timeout: Connection timeout in seconds (default: 60)
        batch_size: Number of rows to process per batch (default: 5000)
        log_batch_frequency: Log progress every N batches (default: 10)
        bulk_update_strategy: Strategy for bulk updates ("auto")
        enable_fast_executemany: Enable fast executemany (default: True)
        enable_parallel_processing: Enable parallel processing (default: True)
        max_parallel_tables: Maximum parallel tables (default: 4)
        max_retries: Maximum retry attempts (default: 3)
        retry_delay: Retry delay in seconds (default: 1.0)
        pool_size: Connection pool size (default: 5)
        environment: Environment (dev/test/prod, default: "dev")
    
    Example:
        >>> config = DatabaseConfig(
        ...     server="localhost",
        ...     database="TestDB",
        ...     auth_type="windows"
        ... )
        >>> config.server
        'localhost'
    """
    
    server: str = Field(..., min_length=1, description="SQL Server hostname")
    database: str = Field(..., min_length=1, description="Database name")
    auth_type: Literal["windows", "sql"] = Field(..., description="Authentication type")
    username: Optional[str] = Field(None, description="SQL Server username")
    password: Optional[str] = Field(None, description="SQL Server password")
    timeout: int = Field(60, ge=5, le=300, description="Connection timeout in seconds")
    batch_size: int = Field(5000, ge=100, le=100000, description="Batch size for processing")
    log_batch_frequency: int = Field(10, ge=1, description="Log every N batches")
    bulk_update_strategy: str = Field("auto", description="Bulk update strategy")
    enable_fast_executemany: bool = Field(True, description="Enable fast executemany")
    enable_parallel_processing: bool = Field(True, description="Enable parallel processing")
    max_parallel_tables: int = Field(4, ge=1, le=16, description="Max parallel tables")
    
    # Additional fields from sanitization config (for compatibility)
    max_retries: int = Field(3, ge=0, le=10, description="Maximum retry attempts")
    retry_delay: float = Field(1.0, ge=0.1, le=60.0, description="Retry delay in seconds")
    pool_size: int = Field(5, ge=1, le=20, description="Connection pool size")
    environment: Literal["dev", "test", "prod"] = Field("dev", description="Environment")
    
    @model_validator(mode="after")
    def validate_auth_credentials(self) -> "DatabaseConfig":
        """Validate SQL auth has required credentials."""
        if self.auth_type == "sql":
            if not self.username:
                raise ValueError("SQL authentication requires username")
            if not self.password:
                raise ValueError("SQL authentication requires password")
        return self
    
    class Config:
        """Pydantic configuration."""
        frozen = False
        extra = "ignore"  # Allow extra fields from config file


class EncryptionConfig(BaseModel):
    """Configuration for mapping table encryption.
    
    Attributes:
        enabled: Whether encryption is enabled for mapping table
        key_env_var: Environment variable containing encryption key
        fallback_keys_env_vars: Environment variables for fallback keys (key rotation)
    
    Example:
        >>> config = EncryptionConfig(enabled=True, key_env_var="MAPPING_KEY")
        >>> config.enabled
        True
    """
    
    enabled: bool = Field(
        False,
        description="Enable encryption for mapping table values"
    )
    key_env_var: str = Field(
        "MAPPING_ENCRYPTION_KEY",
        min_length=1,
        description="Environment variable containing encryption key"
    )
    fallback_keys_env_vars: List[str] = Field(
        default_factory=list,
        description="Environment variables for fallback encryption keys"
    )
    
    class Config:
        """Pydantic configuration."""
        frozen = False
        extra = "forbid"


class MappingSourceConfig(BaseModel):
    """Configuration for mapping table source.
    
    Attributes:
        table_name: Name of the mapping table
        schema_name: Schema containing the mapping table
        encryption: Encryption configuration for mapping values
    
    Example:
        >>> config = MappingSourceConfig(table_name="token_mappings")
        >>> config.table_name
        'token_mappings'
    """
    
    table_name: str = Field(
        "token_mappings",
        min_length=1,
        max_length=128,
        description="Name of the mapping table"
    )
    schema_name: str = Field(
        "dbo",
        min_length=1,
        max_length=128,
        description="Schema containing the mapping table"
    )
    encryption: EncryptionConfig = Field(
        default_factory=EncryptionConfig,
        description="Encryption configuration for mapping values"
    )
    
    class Config:
        """Pydantic configuration."""
        frozen = False
        extra = "forbid"


class RestorationConfig(BaseModel):
    """Configuration for restoration behavior.
    
    Attributes:
        dry_run: If True, preview changes without committing
        skip_verification: Skip post-restoration verification
        strict: Stop on first error (default: continue-on-error)
        skip_audit: Skip audit logging (emergency override)
        skip_missing: Skip records with missing mappings instead of failing
    
    Example:
        >>> config = RestorationConfig(dry_run=True, strict=False)
        >>> config.dry_run
        True
    """
    
    dry_run: bool = Field(
        True,
        description="Preview changes without committing (safe default)"
    )
    skip_verification: bool = Field(
        False,
        description="Skip post-restoration verification checks"
    )
    strict: bool = Field(
        False,
        description="Stop on first error (default: continue-on-error)"
    )
    skip_audit: bool = Field(
        False,
        description="Skip audit logging (emergency override, not recommended)"
    )
    skip_missing: bool = Field(
        False,
        description="Skip records with missing mappings instead of failing"
    )
    
    class Config:
        """Pydantic configuration."""
        frozen = False
        extra = "forbid"


class PerformanceConfig(BaseModel):
    """Configuration for performance optimization.
    
    Attributes:
        enable_parallel: Enable parallel table processing
        max_workers: Maximum number of parallel workers
        rate_limit_ms: Delay between operations in milliseconds (0 = no limit)
        batch_size: Batch size for restoration operations
    
    Example:
        >>> config = PerformanceConfig(enable_parallel=True, max_workers=4)
        >>> config.max_workers
        4
    """
    
    enable_parallel: bool = Field(
        False,
        description="Enable parallel table processing for database-level operations"
    )
    max_workers: int = Field(
        4,
        ge=1,
        le=32,
        description="Maximum number of parallel workers"
    )
    rate_limit_ms: int = Field(
        0,
        ge=0,
        description="Delay between column restorations in milliseconds (0 = no limit)"
    )
    batch_size: int = Field(
        10000,
        ge=100,
        le=100000,
        description="Batch size for restoration operations"
    )
    
    @field_validator('max_workers')
    @classmethod
    def validate_max_workers(cls, v: int) -> int:
        """Validate max_workers is positive."""
        if v < 1:
            logger.warning(f"max_workers must be >= 1, got {v}. Setting to 1.")
            return 1
        return v
    
    class Config:
        """Pydantic configuration."""
        frozen = False
        extra = "forbid"


class CheckpointConfig(BaseModel):
    """Configuration for checkpoint/resume operations.
    
    Attributes:
        operation_id: Operation ID to resume from checkpoint
        clear_stale: Clear stale checkpoints before starting
        stale_threshold_hours: Hours after which checkpoints are considered stale
    
    Example:
        >>> config = CheckpointConfig(operation_id="DESAN-20260413123456-abcd1234")
        >>> config.operation_id
        'DESAN-20260413123456-abcd1234'
    """
    
    operation_id: Optional[str] = Field(
        None,
        min_length=1,
        description="Operation ID to resume from checkpoint"
    )
    clear_stale: bool = Field(
        False,
        description="Clear stale checkpoints before starting"
    )
    stale_threshold_hours: int = Field(
        24,
        ge=1,
        description="Hours after which checkpoints are considered stale"
    )
    
    @field_validator('operation_id')
    @classmethod
    def validate_operation_id_format(cls, v: Optional[str]) -> Optional[str]:
        """Validate operation ID format if provided."""
        if v is None:
            return v
        
        if not v.startswith("DESAN-"):
            logger.warning(
                f"Operation ID should start with 'DESAN-', got: {v}. "
                f"Proceeding anyway but this may not match existing checkpoints."
            )
        
        return v
    
    class Config:
        """Pydantic configuration."""
        frozen = False
        extra = "forbid"


class ValidationConfig(BaseModel):
    """Configuration for validation behavior.
    
    Attributes:
        skip_pre_validation: Skip pre-restoration validation
        strict_verification: Treat warnings as errors in post-verification
        enable_fk_validation: Validate foreign key constraints
        enable_row_count_check: Verify row counts unchanged
    
    Example:
        >>> config = ValidationConfig(strict_verification=True)
        >>> config.strict_verification
        True
    """
    
    skip_pre_validation: bool = Field(
        False,
        description="Skip pre-restoration validation checks"
    )
    strict_verification: bool = Field(
        False,
        description="Treat warnings as errors in post-restoration verification"
    )
    enable_fk_validation: bool = Field(
        True,
        description="Validate foreign key constraints during verification"
    )
    enable_row_count_check: bool = Field(
        True,
        description="Verify row counts remain unchanged after restoration"
    )
    
    class Config:
        """Pydantic configuration."""
        frozen = False
        extra = "forbid"


class SecurityConfig(BaseModel):
    """Configuration for role-based access control (RBAC).
    
    Attributes:
        enabled: Enable role-based access control
        allowed_roles: List of database roles allowed to perform desanitization
        require_role_for_dry_run: Require role membership for dry-run operations
        deny_on_role_check_failure: Deny access if role validation fails
    
    Example:
        >>> config = SecurityConfig(
        ...     enabled=True,
        ...     allowed_roles=['DataRestorer', 'db_owner']
        ... )
        >>> config.allowed_roles
        ['DataRestorer', 'db_owner']
    
    Notes:
        - Default enabled=False for backward compatibility (opt-in security)
        - allowed_roles can include built-in roles (db_owner) or custom roles
        - require_role_for_dry_run=False allows read-only users to preview
        - deny_on_role_check_failure=True ensures fail-safe behavior
    """
    
    enabled: bool = Field(
        False,
        description="Enable role-based access control for desanitization operations"
    )
    allowed_roles: List[str] = Field(
        default_factory=list,
        description="List of database roles permitted to perform desanitization"
    )
    require_role_for_dry_run: bool = Field(
        False,
        description="Require role membership for dry-run (preview) operations"
    )
    deny_on_role_check_failure: bool = Field(
        True,
        description="Deny access if role validation fails (recommended: True)"
    )
    
    @field_validator('allowed_roles')
    @classmethod
    def validate_allowed_roles(cls, v, info):
        """Validate allowed_roles is non-empty when security is enabled."""
        if info.data.get('enabled') and not v:
            raise ValueError(
                "allowed_roles cannot be empty when security is enabled. "
                "Specify at least one database role (e.g., ['DataRestorer', 'db_owner'])"
            )
        return v
    
    @field_validator('allowed_roles')
    @classmethod
    def validate_role_names(cls, v):
        """Validate role names are non-empty strings."""
        for role in v:
            if not role or not isinstance(role, str):
                raise ValueError(
                    f"Invalid role name: {role}. Role names must be non-empty strings."
                )
            if role.strip() != role:
                raise ValueError(
                    f"Invalid role name: '{role}'. Role names cannot have leading/trailing spaces."
                )
        return v
    
    class Config:
        """Pydantic configuration."""
        frozen = False
        extra = "forbid"


class AuditConfig(BaseModel):
    """Configuration for audit logging.
    
    Attributes:
        enabled: Enable audit logging
        table_name: Name of the audit log table
        schema_name: Schema containing the audit log table
    
    Example:
        >>> config = AuditConfig(enabled=True)
        >>> config.table_name
        'desanitization_audit_log'
    """
    
    enabled: bool = Field(
        True,
        description="Enable audit logging for desanitization operations"
    )
    table_name: str = Field(
        "desanitization_audit_log",
        min_length=1,
        max_length=128,
        description="Name of the audit log table"
    )
    schema_name: str = Field(
        "dbo",
        min_length=1,
        max_length=128,
        description="Schema containing the audit log table"
    )
    
    class Config:
        """Pydantic configuration."""
        frozen = False
        extra = "forbid"


class DesanitizationConfig(BaseModel):
    """Root configuration model for desanitization operations.
    
    This is the main configuration model that combines all desanitization-specific
    settings. It reuses DatabaseConfig from the sanitization module for database
    connection settings.
    
    Attributes:
        database: Database connection configuration
        mapping: Mapping table source configuration
        restoration: Restoration behavior configuration
        performance: Performance optimization configuration
        checkpoint: Checkpoint/resume configuration
        validation: Validation behavior configuration
        audit: Audit logging configuration
        security: Role-based access control configuration
    
    Example:
        >>> config = DesanitizationConfig(
        ...     database=DatabaseConfig(server="localhost", database="TestDB"),
        ...     restoration=RestorationConfig(dry_run=False)
        ... )
        >>> config.database.server
        'localhost'
        >>> config.restoration.dry_run
        False
    
    Notes:
        - All sections have sensible defaults
        - Minimal configuration requires only database settings
        - Can be loaded from JSON file with ConfigLoader
        - Supports environment variable overrides with DESANITIZATION_ prefix
    """
    
    database: DatabaseConfig = Field(
        ...,
        description="Database connection settings (reused from sanitization config)"
    )
    mapping: MappingSourceConfig = Field(
        default_factory=MappingSourceConfig,
        description="Mapping table source configuration"
    )
    restoration: RestorationConfig = Field(
        default_factory=RestorationConfig,
        description="Restoration behavior configuration"
    )
    performance: PerformanceConfig = Field(
        default_factory=PerformanceConfig,
        description="Performance optimization configuration"
    )
    checkpoint: CheckpointConfig = Field(
        default_factory=CheckpointConfig,
        description="Checkpoint/resume configuration"
    )
    validation: ValidationConfig = Field(
        default_factory=ValidationConfig,
        description="Validation behavior configuration"
    )
    audit: AuditConfig = Field(
        default_factory=AuditConfig,
        description="Audit logging configuration"
    )
    security: SecurityConfig = Field(
        default_factory=SecurityConfig,
        description="Role-based access control configuration"
    )
    
    @model_validator(mode='after')
    def validate_parallel_config(self) -> 'DesanitizationConfig':
        """Validate parallel configuration consistency."""
        if self.performance.enable_parallel and self.performance.max_workers < 1:
            logger.warning(
                f"Parallel processing enabled but max_workers is {self.performance.max_workers}. "
                f"Setting max_workers to 1."
            )
            self.performance.max_workers = 1
        
        return self
    
    def to_dict(self) -> dict:
        """Convert configuration to dictionary.
        
        Returns:
            Dictionary representation of the configuration
        
        Example:
            >>> config = DesanitizationConfig(database=DatabaseConfig(...))
            >>> config_dict = config.to_dict()
            >>> 'database' in config_dict
            True
        """
        return self.model_dump(mode='python', exclude_none=False)
    
    class Config:
        """Pydantic configuration."""
        frozen = False
        extra = "forbid"
        validate_assignment = True


# Convenience function for creating minimal configuration
def create_minimal_config(
    server: str,
    database: str,
    auth_type: str = "windows",
    **kwargs
) -> DesanitizationConfig:
    """Create a minimal desanitization configuration.
    
    Args:
        server: SQL Server hostname
        database: Database name
        auth_type: Authentication type ('windows' or 'sql')
        **kwargs: Additional database or config overrides
    
    Returns:
        DesanitizationConfig with minimal required settings
    
    Example:
        >>> config = create_minimal_config("localhost", "TestDB")
        >>> config.database.server
        'localhost'
        >>> config.restoration.dry_run
        True
    """
    db_config = DatabaseConfig(
        server=server,
        database=database,
        auth_type=auth_type,
        **{k: v for k, v in kwargs.items() if k in DatabaseConfig.model_fields}
    )
    
    return DesanitizationConfig(database=db_config)
