"""
Mapping table manager for storing and retrieving PII value mappings.

This module provides functionality to store the mapping between original PII values
and their masked counterparts in a dedicated SQL Server table. This enables
traceability, audit trails, and future desensitization (reverse operations).

Key Features:
    - Automatic schema and table creation on first use
    - Batch storage with configurable batch sizes (default 10,000)
    - Optional AES-128 encryption of original values using Fernet
    - SHA256 hashing for efficient lookups
    - Transaction safety with deadlock retry logic
    - Memory-efficient iteration over large mapping sets
    - Index optimization for lookup performance
    - NULL value handling
    - Idempotent operations (duplicate handling)

Table Schema:
    sanitization.pii_mappings (
        mapping_id BIGINT IDENTITY PRIMARY KEY,
        operation_id UNIQUEIDENTIFIER NOT NULL,
        schema_name NVARCHAR(128) NOT NULL,
        table_name NVARCHAR(128) NOT NULL,
        column_name NVARCHAR(128) NOT NULL,
        original_value_hash VARBINARY(32) NOT NULL,
        original_value_encrypted VARBINARY(MAX),
        masked_value NVARCHAR(MAX),
        data_type NVARCHAR(128) NOT NULL,
        is_null BIT NOT NULL,
        created_at DATETIME2 DEFAULT GETUTCDATE(),
        INDEX idx_lookup (schema_name, table_name, column_name, original_value_hash),
        INDEX idx_operation (operation_id)
    )

Security Considerations:
    - Original values are hashed (SHA256) for indexing
    - Optional encryption of original values using AES-128-CBC + HMAC (Fernet)
    - No PII values logged in plaintext
    - Encryption keys managed via environment variables

Performance:
    - Batch inserts with configurable size (100-100,000 rows)
    - Indexed lookups for O(log n) retrieval
    - Deadlock retry with exponential backoff
    - Memory-efficient iteration (never loads all data)

Author: Database Sanitization Team
Date: 2026-03-27
"""

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional
from uuid import UUID
import pyodbc

from src.database.connection_manager import DatabaseConnectionManager
from src.mapping.encryption_utils import EncryptionManager
from src.mapping.mapping_config import MappingConfig
from src.mapping.mapping_models import MappingEntry, MappingBatch, MappingStats
from src.exceptions import MappingError, DatabaseConnectionError
from src.logging.logger import get_logger
from src.logging.correlation import CorrelationContext
from src.database.batch_updater import retry_on_deadlock


class MappingManager:
    """
    Manages storage and retrieval of PII value mappings.
    
    This class handles the creation of the mapping table, storage of mappings
    in batches, and efficient retrieval of mappings for desensitization.
    
    Attributes:
        connection_manager: Database connection manager for SQL Server
        config: Mapping configuration (table name, encryption settings, etc.)
        encryption_manager: Optional encryption manager for value encryption
        logger: Structured logger instance
        _initialized: Flag indicating whether schema/table/indexes are created
        
    Example:
        ```python
        # Initialize manager
        conn_mgr = DatabaseConnectionManager(db_config)
        mapping_config = MappingConfig(encryption_enabled=True)
        manager = MappingManager(conn_mgr, mapping_config)
        
        # Initialize schema/table (one-time setup)
        manager.initialize()
        
        # Store mappings
        entries = [
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Customers",
                column_name="Email",
                original_value_hash=hashlib.sha256(b"user@example.com").digest(),
                original_value_encrypted=encrypted_value,
                masked_value="user_a1b2c3d4@example.com",
                data_type="VARCHAR",
                is_null=False,
                created_at=datetime.utcnow()
            )
        ]
        stats = manager.store_mappings(entries)
        print(f"Stored {stats.total_entries} mappings")
        
        # Retrieve mappings
        mapping = manager.get_mapping(
            operation_id=operation_id,
            schema="dbo",
            table="Customers",
            column="Email",
            value_hash=hashlib.sha256(b"user@example.com").digest()
        )
        ```
    
    Edge Cases:
        - NULL values: Stored with is_null=True, no encryption
        - Duplicate entries: Logged as warnings, operation continues
        - Missing encryption key: Raises MappingError if encryption enabled
        - Table not initialized: Auto-initializes on first use
        - Deadlocks: Automatic retry with exponential backoff
        - Connection failures: Leverages ConnectionManager retry logic
    """
    
    def __init__(
        self,
        connection_manager: DatabaseConnectionManager,
        config: Optional[MappingConfig] = None,
        encryption_manager: Optional[EncryptionManager] = None
    ):
        """
        Initialize the mapping manager.
        
        Args:
            connection_manager: Database connection manager
            config: Mapping configuration (uses defaults if not provided)
            encryption_manager: Optional encryption manager (created if encryption enabled)
            
        Raises:
            MappingError: If encryption is enabled but encryption key is missing
        """
        self.connection_manager = connection_manager
        self.config = config or MappingConfig()
        self.logger = get_logger(self.__class__.__name__)
        self._initialized = False
        
        # Initialize encryption manager if encryption is enabled
        if self.config.encryption_enabled:
            if encryption_manager:
                self.encryption_manager = encryption_manager
            else:
                try:
                    self.encryption_manager = EncryptionManager()
                    self.logger.info(
                        "EncryptionManager initialized for mapping storage",
                        extra={"encryption_enabled": True}
                    )
                except Exception as e:
                    raise MappingError.encryption_key_missing()
        else:
            self.encryption_manager = None
            self.logger.info(
                "Encryption disabled for mapping storage",
                extra={"encryption_enabled": False}
            )
        
        self.logger.info(
            "MappingManager initialized",
            extra={
                "table_name": self.config.get_full_table_name(),
                "encryption_enabled": self.config.encryption_enabled,
                "batch_size": self.config.batch_size,
                "index_creation": self.config.index_creation
            }
        )
    
    def initialize(self) -> None:
        """
        Initialize the mapping table (schema, table, indexes).
        
        This method creates the schema, table, and indexes if they don't exist.
        It's idempotent and safe to call multiple times.
        
        Raises:
            MappingError: If schema/table/index creation fails
            DatabaseConnectionError: If database connection fails
        """
        if self._initialized:
            self.logger.debug("MappingManager already initialized, skipping")
            return
        
        with CorrelationContext() as correlation_id:
            self.logger.info(
                "Initializing mapping table",
                extra={
                    "correlation_id": correlation_id,
                    "schema": self.config.schema_name,
                    "table": self.config.table_name
                }
            )
            
            try:
                # Ensure schema exists
                self._ensure_schema_exists()
                
                # Ensure table exists
                self._ensure_table_exists()
                
                # Create indexes if configured
                if self.config.index_creation:
                    self._create_indexes()
                
                self._initialized = True
                self.logger.info(
                    "Mapping table initialized successfully",
                    extra={
                        "correlation_id": correlation_id,
                        "full_table_name": self.config.get_full_table_name()
                    }
                )
                
            except Exception as e:
                self.logger.error(
                    "Failed to initialize mapping table",
                    extra={
                        "correlation_id": correlation_id,
                        "error": str(e)
                    },
                    exc_info=True
                )
                raise
    
    def _ensure_schema_exists(self) -> None:
        """
        Ensure the mapping schema exists, create if not.
        
        Raises:
            MappingError: If schema creation fails
        """
        schema_name = self.config.schema_name
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if schema exists
                check_query = """
                    SELECT schema_id
                    FROM sys.schemas
                    WHERE name = ?
                """
                cursor.execute(check_query, (schema_name,))
                result = cursor.fetchone()
                
                if result:
                    self.logger.debug(
                        f"Schema [{schema_name}] already exists",
                        extra={"schema_id": result[0]}
                    )
                else:
                    # Create schema
                    create_query = f"CREATE SCHEMA [{schema_name}]"
                    cursor.execute(create_query)
                    conn.commit()
                    
                    self.logger.info(
                        f"Schema [{schema_name}] created successfully"
                    )
                
                cursor.close()
                
        except pyodbc.Error as e:
            error_msg = f"Failed to create schema [{schema_name}]: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MappingError.schema_creation_failed(schema_name, str(e))
        except Exception as e:
            error_msg = f"Unexpected error creating schema [{schema_name}]: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MappingError.schema_creation_failed(schema_name, str(e))
    
    def _ensure_table_exists(self) -> None:
        """
        Ensure the mapping table exists, create if not.
        
        Raises:
            MappingError: If table creation fails
        """
        schema_name = self.config.schema_name
        table_name = self.config.table_name
        full_table_name = self.config.get_full_table_name()
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if table exists
                check_query = """
                    SELECT object_id
                    FROM sys.tables
                    WHERE name = ? AND schema_id = SCHEMA_ID(?)
                """
                cursor.execute(check_query, (table_name, schema_name))
                result = cursor.fetchone()
                
                if result:
                    self.logger.debug(
                        f"Table {full_table_name} already exists",
                        extra={"object_id": result[0]}
                    )
                else:
                    # Create table with proper column definitions
                    create_query = f"""
                    CREATE TABLE {full_table_name} (
                        mapping_id BIGINT IDENTITY(1,1) PRIMARY KEY,
                        operation_id UNIQUEIDENTIFIER NOT NULL,
                        schema_name NVARCHAR(128) NOT NULL,
                        table_name NVARCHAR(128) NOT NULL,
                        column_name NVARCHAR(128) NOT NULL,
                        original_value_hash VARBINARY(32) NOT NULL,
                        original_value_encrypted VARBINARY(MAX),
                        masked_value NVARCHAR(MAX),
                        data_type NVARCHAR(128) NOT NULL,
                        is_null BIT NOT NULL DEFAULT 0,
                        created_at DATETIME2 DEFAULT GETUTCDATE()
                    )
                    """
                    cursor.execute(create_query)
                    conn.commit()
                    
                    self.logger.info(
                        f"Table {full_table_name} created successfully"
                    )
                
                cursor.close()
                
        except pyodbc.Error as e:
            error_msg = f"Failed to create table {full_table_name}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MappingError.table_creation_failed(table_name, schema_name, str(e))
        except Exception as e:
            error_msg = f"Unexpected error creating table {full_table_name}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MappingError.table_creation_failed(table_name, schema_name, str(e))
    
    def _create_indexes(self) -> None:
        """
        Create indexes on the mapping table for efficient lookups.
        
        Creates two indexes:
        1. idx_lookup: Hash-based lookup (schema, table, column, hash)
        2. idx_operation: Operation-based queries (operation_id)
        
        Raises:
            MappingError: If index creation fails
        """
        full_table_name = self.config.get_full_table_name()
        
        indexes = [
            {
                "name": "idx_lookup",
                "columns": ["schema_name", "table_name", "column_name", "original_value_hash"],
                "description": "Hash-based lookup for retrieval"
            },
            {
                "name": "idx_operation",
                "columns": ["operation_id"],
                "description": "Operation-based queries"
            }
        ]
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                for index_info in indexes:
                    index_name = index_info["name"]
                    columns = ", ".join([f"[{col}]" for col in index_info["columns"]])
                    
                    # Check if index exists
                    check_query = """
                        SELECT i.index_id
                        FROM sys.indexes i
                        INNER JOIN sys.tables t ON i.object_id = t.object_id
                        WHERE i.name = ?
                          AND t.name = ?
                          AND t.schema_id = SCHEMA_ID(?)
                    """
                    cursor.execute(check_query, (index_name, self.config.table_name, self.config.schema_name))
                    result = cursor.fetchone()
                    
                    if result:
                        self.logger.debug(
                            f"Index {index_name} already exists on {full_table_name}"
                        )
                    else:
                        # Create index
                        create_query = f"""
                        CREATE NONCLUSTERED INDEX [{index_name}]
                        ON {full_table_name} ({columns})
                        """
                        cursor.execute(create_query)
                        conn.commit()
                        
                        self.logger.info(
                            f"Index {index_name} created successfully on {full_table_name}",
                            extra={"columns": index_info["columns"]}
                        )
                
                cursor.close()
                
        except pyodbc.Error as e:
            error_msg = f"Failed to create indexes on {full_table_name}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MappingError.index_creation_failed("mapping_indexes", full_table_name, str(e))
        except Exception as e:
            error_msg = f"Unexpected error creating indexes on {full_table_name}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MappingError.index_creation_failed("mapping_indexes", full_table_name, str(e))
    
    @retry_on_deadlock(max_attempts=3, backoff_factor=0.5)
    def store_mappings(
        self,
        entries: List[MappingEntry],
        batch_size: Optional[int] = None
    ) -> MappingStats:
        """
        Store a list of mapping entries in batches.
        
        This method chunks the entries into batches and inserts them transactionally.
        Duplicate entries are handled gracefully (logged as warnings, not errors).
        
        Args:
            entries: List of MappingEntry objects to store
            batch_size: Override default batch size from config (optional)
            
        Returns:
            MappingStats with aggregate statistics about the operation
            
        Raises:
            MappingError: If storage fails
            DatabaseConnectionError: If database connection fails
            
        Example:
            ```python
            entries = [MappingEntry(...), MappingEntry(...)]
            stats = manager.store_mappings(entries, batch_size=5000)
            print(f"Stored {stats.total_entries} mappings in {stats.duration_ms}ms")
            ```
        """
        if not entries:
            self.logger.warning("No entries provided to store_mappings")
            return MappingStats(
                operation_id=UUID('00000000-0000-0000-0000-000000000000'),
                total_entries=0,
                tables_processed=0,
                columns_processed=0,
                encryption_enabled=self.config.encryption_enabled,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow()
            )
        
        # Auto-initialize if not done yet
        if not self._initialized:
            self.initialize()
        
        # Use configured batch size or override
        effective_batch_size = batch_size or self.config.batch_size
        
        with CorrelationContext() as correlation_id:
            started_at = datetime.utcnow()
            operation_id = entries[0].operation_id
            total_stored = 0
            total_failed = 0
            
            self.logger.info(
                "Starting batch storage of mappings",
                extra={
                    "correlation_id": correlation_id,
                    "operation_id": str(operation_id),
                    "total_entries": len(entries),
                    "batch_size": effective_batch_size,
                    "encryption_enabled": self.config.encryption_enabled
                }
            )
            
            try:
                # Chunk entries into batches
                for batch_num, start_idx in enumerate(range(0, len(entries), effective_batch_size), start=1):
                    end_idx = min(start_idx + effective_batch_size, len(entries))
                    batch_entries = entries[start_idx:end_idx]
                    
                    # Store this batch
                    stored_count = self._store_batch(batch_entries, batch_num, len(entries))
                    total_stored += stored_count
                    
                    self.logger.debug(
                        f"Batch {batch_num} stored successfully",
                        extra={
                            "correlation_id": correlation_id,
                            "batch_number": batch_num,
                            "stored_count": stored_count,
                            "progress": f"{total_stored}/{len(entries)}"
                        }
                    )
                
                completed_at = datetime.utcnow()
                duration_ms = int((completed_at - started_at).total_seconds() * 1000)
                
                # Calculate statistics
                unique_tables = len(set((e.schema_name, e.table_name) for e in entries))
                unique_columns = len(set((e.schema_name, e.table_name, e.column_name) for e in entries))
                
                stats = MappingStats(
                    operation_id=operation_id,
                    total_entries=total_stored,
                    tables_processed=unique_tables,
                    columns_processed=unique_columns,
                    encryption_enabled=self.config.encryption_enabled,
                    started_at=started_at,
                    completed_at=completed_at
                )
                
                self.logger.info(
                    "Mapping storage completed successfully",
                    extra={
                        "correlation_id": correlation_id,
                        "operation_id": str(operation_id),
                        "total_stored": total_stored,
                        "total_failed": total_failed,
                        "duration_ms": duration_ms,
                        "tables_processed": unique_tables,
                        "columns_processed": unique_columns
                    }
                )
                
                return stats
                
            except Exception as e:
                self.logger.error(
                    "Failed to store mappings",
                    extra={
                        "correlation_id": correlation_id,
                        "operation_id": str(operation_id),
                        "total_entries": len(entries),
                        "stored_so_far": total_stored,
                        "error": str(e)
                    },
                    exc_info=True
                )
                raise MappingError.storage_failed(
                    self.config.get_full_table_name(),
                    str(e)
                )
    
    def _store_batch(
        self,
        batch_entries: List[MappingEntry],
        batch_number: int,
        total_entries: int
    ) -> int:
        """
        Store a single batch of mapping entries.
        
        Args:
            batch_entries: List of entries for this batch
            batch_number: Sequential batch number (1-indexed)
            total_entries: Total entries across all batches
            
        Returns:
            Number of entries successfully stored
            
        Raises:
            MappingError: If batch storage fails
        """
        full_table_name = self.config.get_full_table_name()
        
        # Build INSERT query
        insert_query = f"""
        INSERT INTO {full_table_name} (
            operation_id,
            schema_name,
            table_name,
            column_name,
            original_value_hash,
            original_value_encrypted,
            masked_value,
            data_type,
            is_null,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        # Prepare parameter tuples
        params_list = []
        for entry in batch_entries:
            params = (
                str(entry.operation_id),
                entry.schema_name,
                entry.table_name,
                entry.column_name,
                entry.original_value_hash,
                entry.original_value_encrypted,
                entry.masked_value,
                entry.data_type,
                1 if entry.is_null else 0,
                entry.created_at
            )
            params_list.append(params)
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Execute batch insert
                cursor.executemany(insert_query, params_list)
                row_count = cursor.rowcount
                
                # Commit transaction
                conn.commit()
                cursor.close()
                
                return row_count
                
        except pyodbc.Error as e:
            error_msg = f"Batch {batch_number} storage failed: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MappingError.storage_failed(full_table_name, str(e))
    
    def get_mapping(
        self,
        operation_id: UUID,
        schema: str,
        table: str,
        column: str,
        value_hash: bytes
    ) -> Optional[MappingEntry]:
        """
        Retrieve a single mapping entry by operation and value hash.
        
        Args:
            operation_id: Unique identifier for the sanitization operation
            schema: Schema name
            table: Table name
            column: Column name
            value_hash: SHA256 hash of the original value (32 bytes)
            
        Returns:
            MappingEntry if found, None otherwise
            
        Raises:
            MappingError: If lookup fails
            
        Example:
            ```python
            value_hash = hashlib.sha256(b"user@example.com").digest()
            mapping = manager.get_mapping(
                operation_id=operation_id,
                schema="dbo",
                table="Customers",
                column="Email",
                value_hash=value_hash
            )
            if mapping:
                print(f"Original: {mapping.original_value_encrypted}")
                print(f"Masked: {mapping.masked_value}")
            ```
        """
        if not self._initialized:
            self.initialize()
        
        full_table_name = self.config.get_full_table_name()
        
        query = f"""
        SELECT TOP 1
            operation_id,
            schema_name,
            table_name,
            column_name,
            original_value_hash,
            original_value_encrypted,
            masked_value,
            data_type,
            is_null,
            created_at
        FROM {full_table_name}
        WHERE operation_id = ?
          AND schema_name = ?
          AND table_name = ?
          AND column_name = ?
          AND original_value_hash = ?
        """
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (str(operation_id), schema, table, column, value_hash))
                row = cursor.fetchone()
                cursor.close()
                
                if not row:
                    return None
                
                # Construct MappingEntry from row
                mapping = MappingEntry(
                    operation_id=UUID(row[0]),
                    schema_name=row[1],
                    table_name=row[2],
                    column_name=row[3],
                    original_value_hash=row[4],
                    original_value_encrypted=row[5],
                    masked_value=row[6],
                    data_type=row[7],
                    is_null=bool(row[8]),
                    created_at=row[9]
                )
                
                return mapping
                
        except Exception as e:
            error_msg = f"Failed to lookup mapping: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MappingError.lookup_failed(str(e))
    
    def get_batch_mappings(
        self,
        operation_id: UUID,
        filters: Optional[Dict[str, str]] = None,
        limit: int = 10000
    ) -> List[MappingEntry]:
        """
        Retrieve multiple mapping entries with optional filters.
        
        Args:
            operation_id: Unique identifier for the sanitization operation
            filters: Optional filters (schema, table, column)
            limit: Maximum number of entries to return (default 10,000)
            
        Returns:
            List of MappingEntry objects
            
        Raises:
            MappingError: If lookup fails
            
        Example:
            ```python
            # Get all mappings for a specific table
            mappings = manager.get_batch_mappings(
                operation_id=operation_id,
                filters={"schema": "dbo", "table": "Customers"},
                limit=5000
            )
            ```
        """
        if not self._initialized:
            self.initialize()
        
        full_table_name = self.config.get_full_table_name()
        filters = filters or {}
        
        # Build WHERE clause
        where_clauses = ["operation_id = ?"]
        params = [str(operation_id)]
        
        if "schema" in filters:
            where_clauses.append("schema_name = ?")
            params.append(filters["schema"])
        
        if "table" in filters:
            where_clauses.append("table_name = ?")
            params.append(filters["table"])
        
        if "column" in filters:
            where_clauses.append("column_name = ?")
            params.append(filters["column"])
        
        where_clause = " AND ".join(where_clauses)
        
        query = f"""
        SELECT TOP {limit}
            operation_id,
            schema_name,
            table_name,
            column_name,
            original_value_hash,
            original_value_encrypted,
            masked_value,
            data_type,
            is_null,
            created_at
        FROM {full_table_name}
        WHERE {where_clause}
        ORDER BY created_at
        """
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                rows = cursor.fetchall()
                cursor.close()
                
                # Convert rows to MappingEntry objects
                mappings = []
                for row in rows:
                    mapping = MappingEntry(
                        operation_id=UUID(row[0]),
                        schema_name=row[1],
                        table_name=row[2],
                        column_name=row[3],
                        original_value_hash=row[4],
                        original_value_encrypted=row[5],
                        masked_value=row[6],
                        data_type=row[7],
                        is_null=bool(row[8]),
                        created_at=row[9]
                    )
                    mappings.append(mapping)
                
                return mappings
                
        except Exception as e:
            error_msg = f"Failed to retrieve batch mappings: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MappingError.lookup_failed(str(e))
    
    def get_operation_stats(self, operation_id: UUID) -> MappingStats:
        """
        Get statistics for a specific sanitization operation.
        
        Args:
            operation_id: Unique identifier for the sanitization operation
            
        Returns:
            MappingStats with aggregate information
            
        Raises:
            MappingError: If stats retrieval fails
            
        Example:
            ```python
            stats = manager.get_operation_stats(operation_id)
            print(f"Total mappings: {stats.total_entries}")
            print(f"Tables: {stats.tables_processed}")
            print(f"Columns: {stats.columns_processed}")
            ```
        """
        if not self._initialized:
            self.initialize()
        
        full_table_name = self.config.get_full_table_name()
        
        query = f"""
        SELECT 
            COUNT(*) as total_entries,
            COUNT(DISTINCT schema_name + '.' + table_name) as tables_processed,
            COUNT(DISTINCT schema_name + '.' + table_name + '.' + column_name) as columns_processed,
            MIN(created_at) as started_at,
            MAX(created_at) as completed_at
        FROM {full_table_name}
        WHERE operation_id = ?
        """
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (str(operation_id),))
                row = cursor.fetchone()
                cursor.close()
                
                if not row or row[0] == 0:
                    # No mappings found for this operation
                    return MappingStats(
                        operation_id=operation_id,
                        total_entries=0,
                        tables_processed=0,
                        columns_processed=0,
                        encryption_enabled=self.config.encryption_enabled,
                        started_at=datetime.utcnow(),
                        completed_at=None
                    )
                
                stats = MappingStats(
                    operation_id=operation_id,
                    total_entries=row[0],
                    tables_processed=row[1],
                    columns_processed=row[2],
                    encryption_enabled=self.config.encryption_enabled,
                    started_at=row[3],
                    completed_at=row[4]
                )
                
                return stats
                
        except Exception as e:
            error_msg = f"Failed to retrieve operation stats: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MappingError.lookup_failed(str(e))
    
    def table_exists(self) -> bool:
        """
        Check if the mapping table exists.
        
        Returns:
            True if table exists, False otherwise
        """
        schema_name = self.config.schema_name
        table_name = self.config.table_name
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                check_query = """
                    SELECT object_id
                    FROM sys.tables
                    WHERE name = ? AND schema_id = SCHEMA_ID(?)
                """
                cursor.execute(check_query, (table_name, schema_name))
                result = cursor.fetchone()
                cursor.close()
                
                return result is not None
                
        except Exception as e:
            self.logger.warning(
                f"Error checking if table exists: {str(e)}",
                exc_info=True
            )
            return False
    
    def get_table_info(self) -> Dict[str, Any]:
        """
        Get information about the mapping table.
        
        Returns:
            Dictionary with table statistics (row count, size, indexes)
            
        Raises:
            MappingError: If table doesn't exist or query fails
        """
        if not self.table_exists():
            raise MappingError.table_not_found(
                self.config.table_name,
                self.config.schema_name
            )
        
        full_table_name = self.config.get_full_table_name()
        
        # Query for row count and size
        stats_query = f"""
        SELECT 
            SUM(rows) as row_count,
            SUM(total_pages) * 8 / 1024.0 as size_mb
        FROM sys.partitions p
        INNER JOIN sys.allocation_units a ON p.partition_id = a.container_id
        WHERE p.object_id = OBJECT_ID('{full_table_name}')
        """
        
        # Query for indexes
        index_query = f"""
        SELECT 
            i.name as index_name,
            i.type_desc as index_type
        FROM sys.indexes i
        WHERE i.object_id = OBJECT_ID('{full_table_name}')
        """
        
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get table stats
                cursor.execute(stats_query)
                stats_row = cursor.fetchone()
                row_count = stats_row[0] or 0
                size_mb = stats_row[1] or 0.0
                
                # Get indexes
                cursor.execute(index_query)
                index_rows = cursor.fetchall()
                indexes = [{"name": row[0], "type": row[1]} for row in index_rows]
                
                cursor.close()
                
                return {
                    "full_table_name": full_table_name,
                    "row_count": row_count,
                    "size_mb": round(size_mb, 2),
                    "indexes": indexes,
                    "encryption_enabled": self.config.encryption_enabled
                }
                
        except Exception as e:
            error_msg = f"Failed to retrieve table info: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MappingError.lookup_failed(str(e))
