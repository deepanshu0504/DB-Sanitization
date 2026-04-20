"""
Data models for PII value mappings.

This module defines the core data structures used for storing and retrieving
PII value mappings during sanitization and desanitization operations.

Models:
    - MappingEntry: Single mapping between original and masked value
    - MappingBatch: Collection of mapping entries for batch operations
    - MappingStats: Statistics about mapping operations

Author: Database Sanitization Team
Date: 2026-04-16
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, List, Any
from uuid import UUID
from decimal import Decimal


def _value_to_string(value: Any) -> str:
    """Convert any value to string for encoding/hashing."""
    if value is None:
        return ""
    elif isinstance(value, str):
        return value
    elif isinstance(value, (datetime, date)):
        return value.isoformat()
    elif isinstance(value, (int, float, Decimal)):
        return str(value)
    elif isinstance(value, bytes):
        return value.decode('utf-8')
    else:
        return str(value)


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
        - Empty strings: is_null=False, values are empty strings (not None)
        - Composite keys: Not supported in current version (single column only)
    
    Example:
        ```python
        import hashlib
        from uuid import uuid4
        from datetime import datetime
        
        # Create mapping for email column
        entry = MappingEntry(
            operation_id=uuid4(),
            schema_name="dbo",
            table_name="Customers",
            column_name="Email",
            original_value_hash=hashlib.sha256(b"john@example.com").digest(),
            original_value_encrypted=b"encrypted_bytes_here",
            masked_value="user_a1b2c3d4@example.com",
            data_type="NVARCHAR(100)",
            is_null=False,
            created_at=datetime.utcnow()
        )
        ```
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
    primary_key_columns: Optional[str] = None  # JSON array of PK column names
    primary_key_values: Optional[str] = None  # JSON array of PK values
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate the mapping entry after initialization."""
        # Validate operation_id is UUID
        if not isinstance(self.operation_id, UUID):
            raise ValueError(f"operation_id must be UUID, got {type(self.operation_id)}")
        
        # Validate required string fields
        if not self.schema_name or not self.table_name or not self.column_name:
            raise ValueError("schema_name, table_name, and column_name cannot be empty")
        
        # Validate hash is correct length (SHA256 = 32 bytes)
        if not isinstance(self.original_value_hash, bytes) or len(self.original_value_hash) != 32:
            raise ValueError(
                f"original_value_hash must be 32 bytes (SHA256), "
                f"got {len(self.original_value_hash) if isinstance(self.original_value_hash, bytes) else type(self.original_value_hash)}"
            )
        
        # Validate NULL consistency
        if self.is_null:
            # NULL values should have no encrypted or masked values
            if self.masked_value is not None:
                raise ValueError("masked_value must be None when is_null is True")
        else:
            # Non-NULL values must have masked value
            # (original_value_encrypted can be None if encryption disabled)
            if self.masked_value is None:
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
    
    @property
    def fully_qualified_column(self) -> str:
        """Get fully qualified column name: schema.table.column"""
        return f"{self.schema_name}.{self.table_name}.{self.column_name}"


@dataclass
class MappingBatch:
    """
    Collection of mapping entries for batch operations.
    
    This class groups multiple mapping entries together for efficient
    batch insertion into the mapping table.
    
    Attributes:
        entries: List of MappingEntry objects
        batch_number: Sequential batch number (1-based)
        total_entries: Total number of entries across all batches
        operation_id: Operation ID for all entries (for validation)
        table_name: Optional table name filter (for table-specific batches)
        column_name: Optional column name filter (for column-specific batches)
    
    Example:
        ```python
        entries = [entry1, entry2, entry3]
        batch = MappingBatch(
            entries=entries,
            batch_number=1,
            total_entries=3,
            operation_id=uuid4()
        )
        ```
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
            raise ValueError("entries list cannot be empty")
        
        if self.batch_number < 1:
            raise ValueError(f"batch_number must be >= 1, got {self.batch_number}")
        
        if self.total_entries < len(self.entries):
            raise ValueError(
                f"total_entries ({self.total_entries}) cannot be less than "
                f"entries count ({len(self.entries)})"
            )
        
        # Validate all entries have same operation_id
        mismatched = [e for e in self.entries if e.operation_id != self.operation_id]
        if mismatched:
            raise ValueError(
                f"All entries must have operation_id {self.operation_id}, "
                f"found {len(mismatched)} mismatched entries"
            )
    
    @property
    def size(self) -> int:
        """Get number of entries in this batch."""
        return len(self.entries)
    
    @property
    def is_complete(self) -> bool:
        """Check if this is the final batch."""
        return self.size == self.total_entries or self.batch_number * self.size >= self.total_entries


@dataclass
class MappingStats:
    """
    Statistics about mapping operations.
    
    This class tracks metrics about mapping storage and retrieval operations
    for monitoring and reporting purposes.
    
    Attributes:
        operation_id: Operation ID being tracked
        total_mappings: Total number of mappings for this operation
        tables_affected: Number of tables with mappings
        columns_affected: Number of columns with mappings
        null_count: Number of NULL value mappings
        encrypted_count: Number of encrypted value mappings
        storage_size_bytes: Approximate storage size in bytes
        created_at: When the stats were generated
    
    Example:
        ```python
        stats = MappingStats(
            operation_id=uuid4(),
            total_mappings=1000,
            tables_affected=5,
            columns_affected=12,
            null_count=50,
            encrypted_count=950,
            storage_size_bytes=1024000
        )
        print(f"Stored {stats.total_mappings} mappings across {stats.tables_affected} tables")
        ```
    """
    
    operation_id: UUID
    total_mappings: int = 0
    tables_affected: int = 0
    columns_affected: int = 0
    null_count: int = 0
    encrypted_count: int = 0
    storage_size_bytes: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> dict:
        """Convert stats to dictionary for reporting."""
        return {
            "operation_id": str(self.operation_id),
            "total_mappings": self.total_mappings,
            "tables_affected": self.tables_affected,
            "columns_affected": self.columns_affected,
            "null_count": self.null_count,
            "encrypted_count": self.encrypted_count,
            "storage_size_mb": round(self.storage_size_bytes / (1024 * 1024), 2),
            "created_at": self.created_at.isoformat()
        }
    
    def summary(self) -> str:
        """Get human-readable summary."""
        return (
            f"Mappings: {self.total_mappings:,} | "
            f"Tables: {self.tables_affected} | "
            f"Columns: {self.columns_affected} | "
            f"NULLs: {self.null_count} | "
            f"Encrypted: {self.encrypted_count} | "
            f"Size: {self.storage_size_bytes / (1024 * 1024):.2f} MB"
        )


def create_mapping_entry(
    operation_id: UUID,
    schema: str,
    table: str,
    column: str,
    original_value: Optional[str],
    masked_value: Optional[str],
    data_type: str,
    encrypted_original: Optional[bytes] = None,
    primary_key_columns: Optional[str] = None,
    primary_key_values: Optional[str] = None
) -> MappingEntry:
    """
    Factory function to create a MappingEntry with automatic hash generation.
    
    Args:
        operation_id: UUID of the sanitization operation
        schema: Schema name
        table: Table name
        column: Column name
        original_value: Original PII value (None for NULL)
        masked_value: Masked/fake value (None for NULL)
        data_type: SQL Server data type
        encrypted_original: Pre-encrypted original value (optional)
        primary_key_columns: JSON array of PK column names (optional)
        primary_key_values: JSON array of PK values (optional)
    
    Returns:
        MappingEntry with computed hash
    
    Example:
        ```python
        entry = create_mapping_entry(
            operation_id=uuid4(),
            schema="dbo",
            table="Customers",
            column="Email",
            original_value="john@example.com",
            masked_value="user_a1b2c3d4@example.com",
            data_type="NVARCHAR(100)",
            primary_key_columns='["CustomerID"]',
            primary_key_values='[12345]'
        )
        ```
    """
    # Determine if NULL
    is_null = original_value is None
    
    # Compute hash
    if is_null:
        # Use special hash for NULL values
        original_hash = hashlib.sha256(b"__NULL__").digest()
    else:
        # Convert to string first (handles dates, numbers, etc.), then hash
        value_str = _value_to_string(original_value)
        original_hash = hashlib.sha256(value_str.encode('utf-8')).digest()
    
    return MappingEntry(
        operation_id=operation_id,
        schema_name=schema,
        table_name=table,
        column_name=column,
        original_value_hash=original_hash,
        original_value_encrypted=encrypted_original,
        masked_value=masked_value,
        data_type=data_type,
        is_null=is_null,
        primary_key_columns=primary_key_columns,
        primary_key_values=primary_key_values
    )


def batch_mapping_entries(
    entries: List[MappingEntry],
    batch_size: int = 10000
) -> List[MappingBatch]:
    """
    Split mapping entries into batches for efficient processing.
    
    Args:
        entries: List of MappingEntry objects
        batch_size: Maximum entries per batch (default: 10,000)
    
    Returns:
        List of MappingBatch objects
    
    Example:
        ```python
        entries = [entry1, entry2, ..., entry25000]
        batches = batch_mapping_entries(entries, batch_size=10000)
        # Returns 3 batches: [10000, 10000, 5000]
        
        for batch in batches:
            print(f"Batch {batch.batch_number}: {batch.size} entries")
        ```
    """
    if not entries:
        return []
    
    # Validate all entries have same operation_id
    operation_ids = {e.operation_id for e in entries}
    if len(operation_ids) > 1:
        raise ValueError(
            f"Cannot batch entries with different operation_ids: {operation_ids}"
        )
    
    operation_id = entries[0].operation_id
    total_entries = len(entries)
    batches = []
    
    for i in range(0, total_entries, batch_size):
        batch_entries = entries[i:i + batch_size]
        batch_number = (i // batch_size) + 1
        
        batch = MappingBatch(
            entries=batch_entries,
            batch_number=batch_number,
            total_entries=total_entries,
            operation_id=operation_id
        )
        batches.append(batch)
    
    return batches
