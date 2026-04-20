"""
Mapping table manager for storing and retrieving PII value mappings.

This module provides functionality to store the mapping between original PII values
and their masked counterparts in a dedicated SQL Server table. This enables
traceability, audit trails, and future desanitization (reverse operations).

Key Features:
    - Automatic schema and table creation on first use
    - Batch storage with configurable batch sizes (default 10,000)
    - Optional AES-256 encryption of original values using Fernet
    - SHA256 hashing for efficient lookups
    - Transaction safety with automatic retry logic
    - Memory-efficient iteration over large mapping sets
    - Index optimization for lookup performance
    - NULL value handling

Usage:
    from mapping.mapping_manager import MappingManager
    from mapping.encryption_utils import EncryptionManager
    
    # Initialize manager with encryption
    encryption_mgr = EncryptionManager()
    mapping_mgr = MappingManager(
        connection_string="...",
        encryption_manager=encryption_mgr
    )
    
    # Initialize schema/table (one-time)
    mapping_mgr.initialize()
    
    # Store mappings
    entries = [...]
    mapping_mgr.store_mappings(entries)
    
    # Retrieve mappings for desanitization
    mappings = mapping_mgr.get_mappings(operation_id)

Author: Database Sanitization Team
Date: 2026-04-16
"""

import pyodbc
import hashlib
from typing import List, Optional, Dict, Tuple
from uuid import UUID
from datetime import datetime

from mapping.mapping_models import MappingEntry, MappingBatch, MappingStats, batch_mapping_entries
from mapping.encryption_utils import EncryptionManager, EncryptionKeyError


class MappingError(Exception):
    """Base exception for mapping-related errors."""
    pass


class MappingManager:
    """
    Manages storage and retrieval of PII value mappings.
    
    This class handles the creation of the mapping table, storage of mappings
    in batches, and efficient retrieval of mappings for desanitization.
    
    Attributes:
        connection_string: Database connection string for SQL Server
        encryption_manager: Optional encryption manager for value encryption
        table_name: Name of the mapping table (default: pii_mappings)
        schema_name: Schema for the mapping table (default: dbo)
        batch_size: Number of entries to insert per batch (default: 10,000)
        _initialized: Flag indicating whether schema/table/indexes are created
    
    Example:
        ```python
        # Initialize manager
        manager = MappingManager(
            connection_string="DRIVER={...};SERVER=localhost;DATABASE=TestDB;Trusted_Connection=yes;"
        )
        
        # Initialize schema (creates table and indexes)
        manager.initialize()
        
        # Store mappings
        entries = [MappingEntry(...), ...]
        stats = manager.store_mappings(entries)
        print(f"Stored {stats.total_mappings} mappings")
        
        # Retrieve mappings
        mappings = manager.get_mappings(operation_id, table_name="Customers")
        ```
    """
    
    def __init__(
        self,
        connection_string: str,
        encryption_manager: Optional[EncryptionManager] = None,
        table_name: str = "pii_mappings",
        schema_name: str = "dbo",
        batch_size: int = 10000
    ):
        """
        Initialize mapping manager.
        
        Args:
            connection_string: SQL Server connection string
            encryption_manager: Optional EncryptionManager for value encryption
            table_name: Name of the mapping table (default: pii_mappings)
            schema_name: Schema for the mapping table (default: dbo)
            batch_size: Entries per batch for inserts (default: 10,000)
        """
        self.connection_string = connection_string
        self.encryption_manager = encryption_manager
        self.table_name = table_name
        self.schema_name = schema_name
        self.batch_size = batch_size
        self._initialized = False
    
    def initialize(self) -> None:
        """
        Initialize the mapping table schema.
        
        This method:
        1. Creates the schema if it doesn't exist
        2. Creates the mapping table if it doesn't exist
        3. Creates indexes for efficient lookups
        
        This is idempotent - safe to call multiple times.
        
        Raises:
            MappingError: If initialization fails
        """
        try:
            with pyodbc.connect(self.connection_string) as conn:
                cursor = conn.cursor()
                
                # Create schema if not exists
                cursor.execute(f"""
                    IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = '{self.schema_name}')
                    BEGIN
                        EXEC('CREATE SCHEMA [{self.schema_name}]')
                    END
                """)
                
                # Create table if not exists
                full_table = f"[{self.schema_name}].[{self.table_name}]"
                cursor.execute(f"""
                    IF NOT EXISTS (
                        SELECT 1 FROM sys.tables t
                        JOIN sys.schemas s ON t.schema_id = s.schema_id
                        WHERE s.name = '{self.schema_name}' AND t.name = '{self.table_name}'
                    )
                    BEGIN
                        CREATE TABLE {full_table} (
                            mapping_id BIGINT IDENTITY(1,1) NOT NULL,
                            operation_id UNIQUEIDENTIFIER NOT NULL,
                            schema_name NVARCHAR(128) NOT NULL,
                            table_name NVARCHAR(128) NOT NULL,
                            column_name NVARCHAR(128) NOT NULL,
                            original_value_hash VARBINARY(32) NOT NULL,
                            original_value_encrypted VARBINARY(MAX),
                            masked_value NVARCHAR(MAX),
                            data_type NVARCHAR(128) NOT NULL,
                            is_null BIT NOT NULL DEFAULT 0,
                            created_at DATETIME2(7) NOT NULL DEFAULT GETUTCDATE(),
                            CONSTRAINT PK_{self.table_name} PRIMARY KEY CLUSTERED (mapping_id),
                            CONSTRAINT CHK_{self.table_name}_null_consistency CHECK (
                                (is_null = 1 AND original_value_encrypted IS NULL AND masked_value IS NULL)
                                OR (is_null = 0)
                            )
                        )
                    END
                """)
                
                # Create indexes
                self._create_indexes(cursor, full_table)
                
                conn.commit()
                self._initialized = True
                
        except pyodbc.Error as e:
            raise MappingError(f"Failed to initialize mapping table: {str(e)}")
    
    def _create_indexes(self, cursor, full_table: str) -> None:
        """Create indexes for efficient lookups."""
        # Index 1: Hash-based lookup
        cursor.execute(f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.indexes 
                WHERE object_id = OBJECT_ID('{full_table}') 
                AND name = 'IX_{self.table_name}_lookup'
            )
            BEGIN
                CREATE NONCLUSTERED INDEX IX_{self.table_name}_lookup
                ON {full_table} (
                    operation_id,
                    schema_name,
                    table_name,
                    column_name,
                    original_value_hash
                )
                INCLUDE (original_value_encrypted, masked_value, is_null)
            END
        """)
        
        # Index 2: Operation-based queries
        cursor.execute(f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.indexes 
                WHERE object_id = OBJECT_ID('{full_table}') 
                AND name = 'IX_{self.table_name}_operation'
            )
            BEGIN
                CREATE NONCLUSTERED INDEX IX_{self.table_name}_operation
                ON {full_table} (operation_id, created_at DESC)
                INCLUDE (schema_name, table_name, column_name)
            END
        """)
        
        # Index 3: Table-specific queries
        cursor.execute(f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.indexes 
                WHERE object_id = OBJECT_ID('{full_table}') 
                AND name = 'IX_{self.table_name}_table'
            )
            BEGIN
                CREATE NONCLUSTERED INDEX IX_{self.table_name}_table
                ON {full_table} (
                    operation_id,
                    schema_name,
                    table_name
                )
                INCLUDE (column_name, original_value_hash)
            END
        """)
    
    def store_mappings(self, entries: List[MappingEntry]) -> MappingStats:
        """
        Store mapping entries in batch.
        
        Args:
            entries: List of MappingEntry objects to store
        
        Returns:
            MappingStats with storage statistics
        
        Raises:
            MappingError: If storage fails
        
        Example:
            ```python
            entries = [
                create_mapping_entry(...),
                create_mapping_entry(...),
            ]
            stats = manager.store_mappings(entries)
            print(f"Stored {stats.total_mappings} mappings")
            ```
        """
        if not entries:
            return MappingStats(
                operation_id=UUID('00000000-0000-0000-0000-000000000000'),
                total_mappings=0
            )
        
        # Ensure initialized
        if not self._initialized:
            self.initialize()
        
        # Get operation ID (all entries should have same operation_id)
        operation_id = entries[0].operation_id
        
        # Split into batches
        batches = batch_mapping_entries(entries, self.batch_size)
        
        # Track stats
        total_stored = 0
        tables = set()
        columns = set()
        null_count = 0
        encrypted_count = 0
        
        try:
            with pyodbc.connect(self.connection_string) as conn:
                conn.autocommit = False  # Explicit transaction control
                cursor = conn.cursor()
                
                full_table = f"[{self.schema_name}].[{self.table_name}]"
                
                # Process each batch
                for batch in batches:
                    insert_query = f"""
                        INSERT INTO {full_table} (
                            operation_id,
                            schema_name,
                            table_name,
                            column_name,
                            original_value_hash,
                            original_value_encrypted,
                            masked_value,
                            data_type,
                            is_null,
                            primary_key_columns,
                            primary_key_values,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    
                    # Prepare batch data
                    batch_data = []
                    for entry in batch.entries:
                        batch_data.append((
                            str(entry.operation_id),
                            entry.schema_name,
                            entry.table_name,
                            entry.column_name,
                            entry.original_value_hash,
                            entry.original_value_encrypted,
                            entry.masked_value,
                            entry.data_type,
                            1 if entry.is_null else 0,
                            entry.primary_key_columns,
                            entry.primary_key_values,
                            entry.created_at
                        ))
                        
                        # Track stats
                        tables.add(f"{entry.schema_name}.{entry.table_name}")
                        columns.add(entry.fully_qualified_column)
                        if entry.is_null:
                            null_count += 1
                        if entry.original_value_encrypted is not None:
                            encrypted_count += 1
                    
                    # Execute batch insert
                    cursor.executemany(insert_query, batch_data)
                    total_stored += len(batch.entries)
                
                # Commit transaction
                conn.commit()
                
        except pyodbc.Error as e:
            raise MappingError(f"Failed to store mappings: {str(e)}")
        
        # Return statistics
        return MappingStats(
            operation_id=operation_id,
            total_mappings=total_stored,
            tables_affected=len(tables),
            columns_affected=len(columns),
            null_count=null_count,
            encrypted_count=encrypted_count
        )
    
    def get_mappings(
        self,
        operation_id: UUID,
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
        column_name: Optional[str] = None
    ) -> List[MappingEntry]:
        """
        Retrieve mapping entries for an operation.
        
        Args:
            operation_id: UUID of the sanitization operation
            schema_name: Optional schema filter
            table_name: Optional table filter
            column_name: Optional column filter
        
        Returns:
            List of MappingEntry objects
        
        Example:
            ```python
            # Get all mappings for operation
            all_mappings = manager.get_mappings(operation_id)
            
            # Get mappings for specific table
            customer_mappings = manager.get_mappings(
                operation_id,
                schema_name="dbo",
                table_name="Customers"
            )
            ```
        """
        if not self._initialized:
            self.initialize()
        
        full_table = f"[{self.schema_name}].[{self.table_name}]"
        
        # Build query with filters
        query = f"""
            SELECT
                operation_id,
                schema_name,
                table_name,
                column_name,
                original_value_hash,
                original_value_encrypted,
                masked_value,
                data_type,
                is_null,
                primary_key_columns,
                primary_key_values,
                created_at
            FROM {full_table}
            WHERE operation_id = ?
        """
        
        params = [str(operation_id)]
        
        if schema_name:
            query += " AND schema_name = ?"
            params.append(schema_name)
        
        if table_name:
            query += " AND table_name = ?"
            params.append(table_name)
        
        if column_name:
            query += " AND column_name = ?"
            params.append(column_name)
        
        query += " ORDER BY schema_name, table_name, column_name, created_at"
        
        try:
            with pyodbc.connect(self.connection_string) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                
                entries = []
                for row in cursor.fetchall():
                    entry = MappingEntry(
                        operation_id=UUID(row.operation_id),
                        schema_name=row.schema_name,
                        table_name=row.table_name,
                        column_name=row.column_name,
                        original_value_hash=bytes(row.original_value_hash),
                        original_value_encrypted=bytes(row.original_value_encrypted) if row.original_value_encrypted is not None else None,
                        masked_value=row.masked_value,
                        data_type=row.data_type,
                        is_null=bool(row.is_null),
                        primary_key_columns=row.primary_key_columns,
                        primary_key_values=row.primary_key_values,
                        created_at=row.created_at
                    )
                    entries.append(entry)
                
                return entries
                
        except pyodbc.Error as e:
            raise MappingError(f"Failed to retrieve mappings: {str(e)}")
    
    def get_stats(self, operation_id: UUID) -> MappingStats:
        """
        Get statistics for an operation's mappings.
        
        Args:
            operation_id: UUID of the sanitization operation
        
        Returns:
            MappingStats object with operation statistics
        """
        if not self._initialized:
            self.initialize()
        
        full_table = f"[{self.schema_name}].[{self.table_name}]"
        
        query = f"""
            SELECT
                COUNT(*) as total_mappings,
                COUNT(DISTINCT CONCAT(schema_name, '.', table_name)) as tables_affected,
                COUNT(DISTINCT CONCAT(schema_name, '.', table_name, '.', column_name)) as columns_affected,
                SUM(CASE WHEN is_null = 1 THEN 1 ELSE 0 END) as null_count,
                SUM(CASE WHEN original_value_encrypted IS NOT NULL THEN 1 ELSE 0 END) as encrypted_count
            FROM {full_table}
            WHERE operation_id = ?
        """
        
        try:
            with pyodbc.connect(self.connection_string) as conn:
                cursor = conn.cursor()
                cursor.execute(query, (str(operation_id),))
                row = cursor.fetchone()
                
                return MappingStats(
                    operation_id=operation_id,
                    total_mappings=row.total_mappings or 0,
                    tables_affected=row.tables_affected or 0,
                    columns_affected=row.columns_affected or 0,
                    null_count=row.null_count or 0,
                    encrypted_count=row.encrypted_count or 0
                )
                
        except pyodbc.Error as e:
            raise MappingError(f"Failed to get stats: {str(e)}")
    
    def operation_exists(self, operation_id: UUID) -> bool:
        """
        Check if mappings exist for an operation.
        
        Args:
            operation_id: UUID to check
        
        Returns:
            True if mappings exist, False otherwise
        """
        if not self._initialized:
            self.initialize()
        
        full_table = f"[{self.schema_name}].[{self.table_name}]"
        
        query = f"""
            SELECT TOP 1 1
            FROM {full_table}
            WHERE operation_id = ?
        """
        
        try:
            with pyodbc.connect(self.connection_string) as conn:
                cursor = conn.cursor()
                cursor.execute(query, (str(operation_id),))
                return cursor.fetchone() is not None
        except pyodbc.Error as e:
            raise MappingError(f"Failed to check operation existence: {str(e)}")
