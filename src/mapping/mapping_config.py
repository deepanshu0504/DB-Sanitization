"""
Configuration models for mapping table operations.

This module provides Pydantic models for mapping table configuration with
validation, type safety, and sensible defaults.

Models:
    MappingConfig: Configuration for mapping table storage and encryption
"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class MappingConfig(BaseModel):
    """
    Configuration for mapping table operations.
    
    This model defines settings for mapping table storage, encryption,
    and operational parameters.
    
    Attributes:
        enabled: Whether mapping table functionality is enabled (default: True)
        table_name: Name of the mapping table (default: "pii_mappings")
        schema_name: Schema for the mapping table (default: "sanitization")
        encryption_enabled: Whether to encrypt original values (default: False)
        batch_size: Number of mapping entries to insert per batch (default: 10000)
        index_creation: Whether to create indexes on the mapping table (default: True)
        transactional: Whether to couple mapping insert with database update (default: False)
        
    Configuration Options:
        - enabled: Set to False to disable mapping functionality entirely
        - encryption_enabled: Set to True to encrypt original values at rest
          (requires SANITIZATION_MAPPING_ENCRYPTION_KEY environment variable)
        - transactional: 
          * False (default): Better performance, mapping insert after DB update commit
          * True: Strict consistency, mapping and DB update in same transaction
        - batch_size: Larger batches = better performance but longer transactions
        
    Security Considerations:
        - Enable encryption in production for compliance (requires key management)
        - Mapping table contains sensitive data; restrict access via database permissions
        - Use separate encryption keys per environment
        
    Performance Tuning:
        - Increase batch_size for large datasets (up to 50,000)
        - Disable index_creation during initial load, create indexes afterward
        - For very large operations, use transactional=False for better throughput
    
    Example:
        ```python
        # Development configuration (no encryption)
        config = MappingConfig(
            enabled=True,
            encryption_enabled=False,
            batch_size=10000
        )
        
        # Production configuration (with encryption)
        config = MappingConfig(
            enabled=True,
            encryption_enabled=True,
            transactional=True,  # Strict consistency
            batch_size=5000      # Smaller batches for transaction safety
        )
        ```
    """
    
    model_config = {"validate_assignment": True}
    
    # Core settings
    enabled: bool = Field(
        default=True,
        description="Whether mapping table functionality is enabled"
    )
    
    table_name: str = Field(
        default="pii_mappings",
        min_length=1,
        max_length=128,
        description="Name of the mapping table"
    )
    
    schema_name: str = Field(
        default="sanitization",
        min_length=1,
        max_length=128,
        description="Schema for the mapping table"
    )
    
    # Encryption settings
    encryption_enabled: bool = Field(
        default=False,
        description="Whether to encrypt original values"
    )
    
    # Operational settings
    batch_size: int = Field(
        default=10000,
        ge=100,
        le=100000,
        description="Number of mapping entries to insert per batch"
    )
    
    index_creation: bool = Field(
        default=True,
        description="Whether to create indexes on the mapping table"
    )
    
    transactional: bool = Field(
        default=False,
        description="Whether to couple mapping insert with database update in same transaction"
    )
    
    @field_validator("table_name", "schema_name")
    @classmethod
    def validate_sql_identifier(cls, v: str) -> str:
        """
        Validate SQL identifier names.
        
        Ensures table and schema names are valid SQL Server identifiers
        (alphanumeric, underscore, no leading digit).
        
        Args:
            v: The identifier to validate
            
        Returns:
            Validated identifier
            
        Raises:
            ValueError: If identifier is invalid
        """
        if not v:
            raise ValueError("Identifier cannot be empty")
        
        # Allow alphanumeric and underscore
        if not all(c.isalnum() or c == '_' for c in v):
            raise ValueError(
                f"Invalid SQL identifier '{v}': must contain only alphanumeric characters and underscores"
            )
        
        # Cannot start with digit
        if v[0].isdigit():
            raise ValueError(
                f"Invalid SQL identifier '{v}': cannot start with a digit"
            )
        
        return v
    
    @field_validator("batch_size")
    @classmethod
    def validate_batch_size(cls, v: int) -> int:
        """
        Validate batch size is within reasonable range.
        
        Args:
            v: Batch size to validate
            
        Returns:
            Validated batch size
            
        Raises:
            ValueError: If batch size is out of range
        """
        if v < 100:
            raise ValueError("batch_size must be at least 100 for efficiency")
        
        if v > 100000:
            raise ValueError(
                "batch_size exceeds 100,000; large batches may cause transaction log issues"
            )
        
        # Warn if batch size is very large and transactional mode is enabled
        if v > 10000 and not hasattr(cls, '_warned_large_batch'):
            cls._warned_large_batch = True
            # Note: actual logging happens in MappingManager
        
        return v
    
    def get_full_table_name(self) -> str:
        """
        Get fully qualified table name.
        
        Returns:
            Fully qualified table name in format: [schema].[table]
            
        Example:
            >>> config = MappingConfig()
            >>> config.get_full_table_name()
            '[sanitization].[pii_mappings]'
        """
        return f"[{self.schema_name}].[{self.table_name}]"
    
    def to_dict(self) -> dict:
        """
        Convert configuration to dictionary.
        
        Returns:
            Dictionary representation of the configuration
        """
        return {
            "enabled": self.enabled,
            "table_name": self.table_name,
            "schema_name": self.schema_name,
            "full_table_name": self.get_full_table_name(),
            "encryption_enabled": self.encryption_enabled,
            "batch_size": self.batch_size,
            "index_creation": self.index_creation,
            "transactional": self.transactional,
        }
    
    def __repr__(self) -> str:
        """String representation for debugging (safe, no sensitive data)."""
        return (
            f"MappingConfig("
            f"enabled={self.enabled}, "
            f"full_table_name={self.get_full_table_name()}, "
            f"encryption_enabled={self.encryption_enabled}, "
            f"batch_size={self.batch_size})"
        )
