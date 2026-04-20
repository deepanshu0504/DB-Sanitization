"""
Configuration models for desanitization operations.

This module defines configuration settings for the desanitization process,
including validation thresholds, batch sizes, and operational parameters.

Author: Database Sanitization Team
Date: 2026-04-16
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class DesanitizationConfig:
    """
    Configuration for desanitization operations.
    
    This class defines settings that control the desanitization workflow,
    including batch processing, validation, and safety features.
    
    Attributes:
        dry_run: If True, preview changes without applying them (default: True)
        batch_size: Number of rows to process per batch (default: 10,000)
        max_mismatch_percentage: Max % of rows that can fail to restore (default: 5.0)
        sample_size_for_validation: Number of rows to sample for verification (default: 100)
        verify_after_restore: Run verification checks after restoration (default: True)
        rollback_on_error: Rollback entire operation on any error (default: True)
        continue_on_table_failure: Continue with other tables if one fails (default: False)
        tables: Optional list of specific tables to restore (None = all tables)
    
    Example:
        ```python
        # Default safe configuration
        config = DesanitizationConfig()
        
        # Production configuration
        config = DesanitizationConfig(
            dry_run=False,
            batch_size=10000,
            max_mismatch_percentage=1.0,
            verify_after_restore=True,
            rollback_on_error=True
        )
        
        # Selective restore configuration
        config = DesanitizationConfig(
            dry_run=False,
            tables=["dbo.Customers", "dbo.Orders"]
        )
        ```
    """
    
    # Safety settings
    dry_run: bool = True
    rollback_on_error: bool = True
    continue_on_table_failure: bool = False
    
    # Performance settings
    batch_size: int = 10000
    
    # Validation settings
    max_mismatch_percentage: float = 5.0
    sample_size_for_validation: int = 100
    verify_after_restore: bool = True
    
    # Scope settings
    tables: Optional[List[str]] = None  # None = all tables, or ["schema.table", ...]
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        # Validate batch_size
        if self.batch_size < 1:
            raise ValueError(f"batch_size must be >= 1, got {self.batch_size}")
        
        if self.batch_size > 100000:
            raise ValueError(
                f"batch_size too large ({self.batch_size}), maximum is 100,000 for safety"
            )
        
        # Validate max_mismatch_percentage
        if not (0.0 <= self.max_mismatch_percentage <= 100.0):
            raise ValueError(
                f"max_mismatch_percentage must be between 0 and 100, "
                f"got {self.max_mismatch_percentage}"
            )
        
        # Validate sample_size_for_validation
        if self.sample_size_for_validation < 0:
            raise ValueError(
                f"sample_size_for_validation must be >= 0, "
                f"got {self.sample_size_for_validation}"
            )
        
        # Validate tables format if specified
        if self.tables is not None:
            if not isinstance(self.tables, list):
                raise ValueError("tables must be a list of strings or None")
            
            for table in self.tables:
                if not isinstance(table, str):
                    raise ValueError(f"table name must be string, got {type(table)}")
                
                if '.' not in table:
                    raise ValueError(
                        f"table name must be in 'schema.table' format, got '{table}'"
                    )
    
    @property
    def is_selective_restore(self) -> bool:
        """Check if this is a selective restore (specific tables only)."""
        return self.tables is not None and len(self.tables) > 0
    
    @property
    def is_full_restore(self) -> bool:
        """Check if this is a full restore (all tables)."""
        return self.tables is None
    
    def to_dict(self) -> dict:
        """Convert configuration to dictionary for serialization."""
        return {
            "dry_run": self.dry_run,
            "rollback_on_error": self.rollback_on_error,
            "continue_on_table_failure": self.continue_on_table_failure,
            "batch_size": self.batch_size,
            "max_mismatch_percentage": self.max_mismatch_percentage,
            "sample_size_for_validation": self.sample_size_for_validation,
            "verify_after_restore": self.verify_after_restore,
            "tables": self.tables,
            "is_selective_restore": self.is_selective_restore,
            "is_full_restore": self.is_full_restore
        }
    
    def summary(self) -> str:
        """Get human-readable configuration summary."""
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        scope = f"Selective ({len(self.tables)} tables)" if self.is_selective_restore else "Full restore"
        
        return (
            f"Mode: {mode} | "
            f"Scope: {scope} | "
            f"Batch: {self.batch_size:,} | "
            f"Rollback: {self.rollback_on_error} | "
            f"Verify: {self.verify_after_restore}"
        )


@dataclass
class RestoreStats:
    """
    Statistics for a desanitization operation.
    
    Attributes:
        operation_id: UUID of the operation being restored
        total_tables: Total tables in the operation
        tables_restored: Number of tables successfully restored
        tables_failed: Number of tables that failed to restore
        total_rows_restored: Total rows restored across all tables
        total_mappings_applied: Total mappings applied
        null_values_restored: Number of NULL values restored
        encrypted_values_decrypted: Number of encrypted values decrypted
        verification_passed: Whether post-restore verification passed
        errors: List of error messages encountered
    """
    
    operation_id: str
    total_tables: int = 0
    tables_restored: int = 0
    tables_failed: int = 0
    total_rows_restored: int = 0
    total_mappings_applied: int = 0
    null_values_restored: int = 0
    encrypted_values_decrypted: int = 0
    verification_passed: bool = False
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert stats to dictionary for serialization."""
        return {
            "operation_id": self.operation_id,
            "total_tables": self.total_tables,
            "tables_restored": self.tables_restored,
            "tables_failed": self.tables_failed,
            "total_rows_restored": self.total_rows_restored,
            "total_mappings_applied": self.total_mappings_applied,
            "null_values_restored": self.null_values_restored,
            "encrypted_values_decrypted": self.encrypted_values_decrypted,
            "verification_passed": self.verification_passed,
            "errors": self.errors
        }
    
    def summary(self) -> str:
        """Get human-readable summary."""
        success_rate = (
            (self.tables_restored / self.total_tables * 100)
            if self.total_tables > 0
            else 0
        )
        
        return (
            f"Tables: {self.tables_restored}/{self.total_tables} ({success_rate:.1f}%) | "
            f"Rows: {self.total_rows_restored:,} | "
            f"Mappings: {self.total_mappings_applied:,} | "
            f"Verified: {self.verification_passed}"
        )
    
    @property
    def has_errors(self) -> bool:
        """Check if any errors occurred."""
        return len(self.errors) > 0 or self.tables_failed > 0
    
    @property
    def is_successful(self) -> bool:
        """Check if operation was fully successful."""
        return (
            self.tables_failed == 0
            and not self.has_errors
            and (self.verification_passed or self.total_tables == 0)
        )


def create_safe_config() -> DesanitizationConfig:
    """
    Create a safe default configuration for desanitization.
    
    This configuration uses the most conservative settings:
    - Dry-run mode enabled
    - Rollback on any error
    - Full verification enabled
    
    Returns:
        DesanitizationConfig with safe defaults
    
    Example:
        ```python
        config = create_safe_config()
        # Always safe to run - won't modify database
        ```
    """
    return DesanitizationConfig(
        dry_run=True,
        rollback_on_error=True,
        continue_on_table_failure=False,
        verify_after_restore=True,
        batch_size=10000
    )


def create_production_config(
    tables: Optional[List[str]] = None,
    batch_size: int = 10000
) -> DesanitizationConfig:
    """
    Create a production configuration for desanitization.
    
    This configuration is suitable for production use with proper safety measures.
    
    Args:
        tables: Optional list of specific tables to restore
        batch_size: Number of rows per batch
    
    Returns:
        DesanitizationConfig for production use
    
    Example:
        ```python
        # Full restore
        config = create_production_config()
        
        # Selective restore
        config = create_production_config(
            tables=["dbo.Customers", "dbo.Orders"]
        )
        ```
    """
    return DesanitizationConfig(
        dry_run=False,
        rollback_on_error=True,
        continue_on_table_failure=False,
        verify_after_restore=True,
        batch_size=batch_size,
        max_mismatch_percentage=1.0,  # Stricter for production
        tables=tables
    )
