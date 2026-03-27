"""
Data models for mapping table operations.

This module defines the core data structures used to represent mapping entries,
batches of mappings, and statistics about mapping operations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from uuid import UUID


@dataclass
class MappingEntry:
    """
    Represents a single mapping entry for a PII value.
    
    This class stores the mapping between an original value and its masked
    counterpart, along with metadata needed for storage and retrieval.
    
    Attributes:
        operation_id: Unique identifier for the sanitization operation
        schema_name: Database schema containing the table
        table_name: Name of the table containing the PII column
        column_name: Name of the PII column
        original_value_hash: SHA256 hash of the original value (for indexing)
        original_value_encrypted: Encrypted original value (bytes), None if encryption disabled
        masked_value: The masked/fake value that replaced the original
        data_type: SQL Server data type of the column (e.g., 'VARCHAR', 'NVARCHAR')
        is_null: True if the original value was NULL
        created_at: Timestamp when the mapping was created
        
    Edge Cases:
        - NULL values: is_null=True, original_value_encrypted=None, masked_value=None
        - Composite keys: original_value_hash is hash of JSON-serialized list
        - CHAR padding: Hash is computed after normalizing (stripping) trailing spaces
        - Encryption disabled: original_value_encrypted=None (not stored)
    """
    
    operation_id: UUID
    schema_name: str
    table_name: str
    column_name: str
    original_value_hash: bytes  # VARBINARY(32) - SHA256 hash
    original_value_encrypted: Optional[bytes]  # VARBINARY(MAX) - encrypted original value
    masked_value: Optional[str]  # NVARCHAR(MAX) - the fake value
    data_type: str  # SQL Server data type (VARCHAR, NVARCHAR, CHAR, etc.)
    is_null: bool  # True if original value was NULL
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate the mapping entry after initialization."""
        if not isinstance(self.operation_id, UUID):
            raise ValueError(f"operation_id must be UUID, got {type(self.operation_id)}")
        
        if not self.schema_name or not self.table_name or not self.column_name:
            raise ValueError("schema_name, table_name, and column_name cannot be empty")
        
        if not isinstance(self.original_value_hash, bytes) or len(self.original_value_hash) != 32:
            raise ValueError(f"original_value_hash must be 32 bytes (SHA256), got {len(self.original_value_hash) if isinstance(self.original_value_hash, bytes) else type(self.original_value_hash)}")
        
        # If is_null is True, masked_value should be None
        if self.is_null and self.masked_value is not None:
            raise ValueError("masked_value must be None when is_null is True")
        
        # If is_null is False, masked_value should be set
        if not self.is_null and self.masked_value is None:
            raise ValueError("masked_value cannot be None when is_null is False")
    
    def to_dict(self) -> dict:
        """
        Convert the mapping entry to a dictionary for serialization.
        
        Returns:
            Dictionary representation of the mapping entry
        """
        return {
            "operation_id": str(self.operation_id),
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "original_value_hash": self.original_value_hash.hex(),
            "original_value_encrypted": self.original_value_encrypted.hex() if self.original_value_encrypted else None,
            "masked_value": self.masked_value,
            "data_type": self.data_type,
            "is_null": self.is_null,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class MappingBatch:
    """
    Represents a batch of mapping entries for bulk operations.
    
    This class groups multiple mapping entries together for efficient batch
    processing and progress tracking.
    
    Attributes:
        entries: List of MappingEntry objects in this batch
        batch_number: Sequential batch number (1-based)
        total_entries: Total number of entries across all batches
        operation_id: Unique identifier for the sanitization operation
        table_name: Name of the table being processed (optional, for filtering)
        column_name: Name of the column being processed (optional, for filtering)
        
    Note:
        Batch size is configurable (default 10,000) to balance transaction
        log management with atomicity requirements.
    """
    
    entries: List[MappingEntry]
    batch_number: int
    total_entries: int
    operation_id: UUID
    table_name: Optional[str] = None
    column_name: Optional[str] = None
    
    def __post_init__(self):
        """Validate the batch after initialization."""
        if not self.entries:
            raise ValueError("Batch cannot be empty")
        
        if self.batch_number < 1:
            raise ValueError(f"batch_number must be >= 1, got {self.batch_number}")
        
        if self.total_entries < len(self.entries):
            raise ValueError(f"total_entries ({self.total_entries}) cannot be less than batch size ({len(self.entries)})")
        
        # Validate all entries belong to the same operation
        for entry in self.entries:
            if entry.operation_id != self.operation_id:
                raise ValueError(f"All entries must have operation_id {self.operation_id}, found {entry.operation_id}")
    
    @property
    def entry_count(self) -> int:
        """Get the number of entries in this batch."""
        return len(self.entries)
    
    @property
    def progress_percent(self) -> float:
        """
        Calculate the progress percentage based on cumulative entries processed.
        
        Returns:
            Progress percentage (0.0 to 100.0)
        """
        entries_so_far = (self.batch_number - 1) * len(self.entries) + len(self.entries)
        return min(100.0, (entries_so_far / self.total_entries) * 100.0)
    
    def to_dict(self) -> dict:
        """
        Convert the batch to a dictionary for serialization.
        
        Returns:
            Dictionary representation of the batch
        """
        return {
            "batch_number": self.batch_number,
            "entry_count": self.entry_count,
            "total_entries": self.total_entries,
            "operation_id": str(self.operation_id),
            "table_name": self.table_name,
            "column_name": self.column_name,
            "progress_percent": round(self.progress_percent, 2),
        }


@dataclass
class MappingStats:
    """
    Statistics about a mapping operation.
    
    This class provides aggregate information about mapping entries created
    during a sanitization operation.
    
    Attributes:
        operation_id: Unique identifier for the sanitization operation
        total_entries: Total number of mapping entries created
        tables_processed: Number of distinct tables with mappings
        columns_processed: Number of distinct columns with mappings
        encryption_enabled: Whether encryption was enabled for this operation
        started_at: Timestamp when the operation started
        completed_at: Timestamp when the operation completed (optional)
        
    Usage:
        Used for audit trails, progress reporting, and validation that
        all expected mappings were created.
    """
    
    operation_id: UUID
    total_entries: int
    tables_processed: int
    columns_processed: int
    encryption_enabled: bool
    started_at: datetime
    completed_at: Optional[datetime] = None
    
    def __post_init__(self):
        """Validate the statistics after initialization."""
        if self.total_entries < 0:
            raise ValueError(f"total_entries cannot be negative, got {self.total_entries}")
        
        if self.tables_processed < 0:
            raise ValueError(f"tables_processed cannot be negative, got {self.tables_processed}")
        
        if self.columns_processed < 0:
            raise ValueError(f"columns_processed cannot be negative, got {self.columns_processed}")
        
        if self.completed_at and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be before started_at")
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """
        Calculate the duration of the operation in seconds.
        
        Returns:
            Duration in seconds if completed, None otherwise
        """
        if not self.completed_at:
            return None
        return (self.completed_at - self.started_at).total_seconds()
    
    @property
    def avg_entries_per_table(self) -> float:
        """
        Calculate the average number of entries per table.
        
        Returns:
            Average entries per table, or 0.0 if no tables processed
        """
        if self.tables_processed == 0:
            return 0.0
        return self.total_entries / self.tables_processed
    
    @property
    def avg_entries_per_column(self) -> float:
        """
        Calculate the average number of entries per column.
        
        Returns:
            Average entries per column, or 0.0 if no columns processed
        """
        if self.columns_processed == 0:
            return 0.0
        return self.total_entries / self.columns_processed
    
    def to_dict(self) -> dict:
        """
        Convert the statistics to a dictionary for serialization.
        
        Returns:
            Dictionary representation of the statistics
        """
        return {
            "operation_id": str(self.operation_id),
            "total_entries": self.total_entries,
            "tables_processed": self.tables_processed,
            "columns_processed": self.columns_processed,
            "encryption_enabled": self.encryption_enabled,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "avg_entries_per_table": round(self.avg_entries_per_table, 2),
            "avg_entries_per_column": round(self.avg_entries_per_column, 2),
        }
