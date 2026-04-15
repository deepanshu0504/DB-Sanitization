"""
Mapping Table Manager for reversible sanitization.

This module provides the MappingTableManager class for managing the token_mappings
table: creation, validation, bulk inserts, and efficient lookups.

Story 1.3: Added transparent encryption support for original_value and masked_value
columns using AES-256-GCM encryption.
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple, TYPE_CHECKING
from dataclasses import dataclass

import pyodbc

from .exceptions import MappingTableError, MappingInsertError, SchemaValidationError

if TYPE_CHECKING:
    from .encryption_utils import MappingEncryptor
    from .mapping_cache import MappingLRUCache


@dataclass
class MappingRecord:
    """Represents a single mapping record."""
    table_name: str
    column_name: str
    record_id: str  # JSON for composite PKs
    original_value: Optional[str]  # None represents database NULL
    masked_value: str
    batch_id: str
    sanitization_run_id: str


@dataclass
class BatchMetadata:
    """Metadata for a sanitization batch."""
    batch_id: str
    row_count: int
    earliest_timestamp: datetime
    latest_timestamp: datetime
    affected_tables: List[str]
    affected_columns: List[str]


class MappingTableManager:
    """
    Manage token_mappings table for reversible sanitization.
    
    Responsibilities:
    - Create and validate mapping table schema
    - Bulk insert mappings with transaction safety
    - Efficient lookups for desanitization operations
    - Handle composite primary keys via JSON serialization
    
    Usage:
        manager = MappingTableManager(connection_string, table_name="token_mappings")
        manager.create_table()
        manager.validate_schema()
        
        mappings = [
            MappingRecord(...),
            MappingRecord(...),
        ]
        manager.insert_batch(mappings, batch_size=5000)
    """
    
    # Required schema (for validation)
    REQUIRED_COLUMNS = {
        "mapping_id": "bigint",
        "table_name": "nvarchar",
        "column_name": "nvarchar",
        "record_id": "nvarchar",
        "original_value": "nvarchar",
        "masked_value": "nvarchar",
        "created_at": "datetime2",
        "batch_id": "nvarchar",
        "sanitization_run_id": "nvarchar",
        "schema_version": "int",
    }
    
    def __init__(
        self,
        connection_string: str,
        table_name: str = "token_mappings",
        schema: str = "dbo",
        encryptor: Optional['MappingEncryptor'] = None,
        cache: Optional['MappingLRUCache'] = None
    ):
        """
        Initialize MappingTableManager.
        
        Args:
            connection_string: SQL Server connection string
            table_name: Name of mapping table (default: token_mappings)
            schema: Database schema (default: dbo)
            encryptor: Optional MappingEncryptor for transparent encryption at rest
            cache: Optional MappingLRUCache for optimized lookups (Story 5.3)
        """
        self.connection_string = connection_string
        self.table_name = table_name
        self.schema = schema
        self.fully_qualified_table = f"[{schema}].[{table_name}]"
        self.encryptor = encryptor
        self.cache = cache
        
        # Stats tracking
        self._total_inserts = 0
        self._failed_inserts = 0
    
    def create_table(self, drop_existing: bool = False) -> bool:
        """
        Create mapping table with optimized indexes.
        
        Args:
            drop_existing: If True, drop existing table before creating
            
        Returns:
            True if table created, False if already exists
            
        Raises:
            MappingTableError: If table creation fails
        """
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            # Check if table exists
            cursor.execute(f"""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            """, (self.schema, self.table_name))
            
            exists = cursor.fetchone()[0] > 0
            
            if exists and not drop_existing:
                cursor.close()
                conn.close()
                return False  # Already exists
            
            # If drop_existing and table exists, drop it first
            if exists and drop_existing:
                cursor.execute(f"DROP TABLE {self.fully_qualified_table}")
                conn.commit()
            
            # Read SQL script from file
            script_path = os.path.join(
                os.path.dirname(__file__),
                "..",
                "scripts",
                "create_mapping_table.sql"
            )
            
            if not os.path.exists(script_path):
                raise MappingTableError(
                    f"SQL script not found: {script_path}\n"
                    f"Expected: scripts/create_mapping_table.sql"
                )
            
            with open(script_path, 'r', encoding='utf-8') as f:
                sql_script = f.read()
            
            # Execute script (split by GO statements)
            batches = [
                batch.strip() 
                for batch in sql_script.split('\nGO\n') 
                if batch.strip() and not batch.strip().startswith('--')
            ]
            
            for batch in batches:
                # Skip PRINT statements (not supported in pyodbc)
                if 'PRINT' in batch:
                    continue
                # Skip DROP statements (already handled above if needed)
                if 'DROP TABLE' in batch.upper():
                    continue
                try:
                    cursor.execute(batch)
                except pyodbc.Error as e:
                    # Ignore table already exists during idempotent operations
                    if "already an object named" in str(e) or "Cannot drop the table" in str(e):
                        continue
                    raise
            
            conn.commit()
            cursor.close()
            conn.close()
            
            # Validate creation
            if not self.validate_schema():
                raise MappingTableError(
                    f"Table created but schema validation failed for {self.fully_qualified_table}"
                )
            
            return True
            
        except pyodbc.Error as e:
            raise MappingTableError(
                f"Failed to create mapping table: {str(e)}\n\n"
                f"Suggested actions:\n"
                f"1. Verify database connection: {self.connection_string}\n"
                f"2. Ensure CREATE TABLE permissions\n"
                f"3. Check if table already exists with different schema"
            ) from e
    
    def validate_schema(self) -> bool:
        """
        Validate mapping table schema matches requirements.
        
        Returns:
            True if schema valid, False otherwise
            
        Raises:
            SchemaValidationError: If schema is invalid with details
        """
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            # Get actual columns
            cursor.execute(f"""
                SELECT COLUMN_NAME, DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            """, (self.schema, self.table_name))
            
            actual_columns = {
                row.COLUMN_NAME.lower(): row.DATA_TYPE.lower()
                for row in cursor.fetchall()
            }
            
            cursor.close()
            conn.close()
            
            if not actual_columns:
                raise SchemaValidationError(
                    f"Table {self.fully_qualified_table} does not exist.\n\n"
                    f"Suggested action: Run manager.create_table() or execute scripts/create_mapping_table.sql"
                )
            
            # Validate required columns
            missing_columns = []
            for col_name, expected_type in self.REQUIRED_COLUMNS.items():
                if col_name not in actual_columns:
                    missing_columns.append(col_name)
                    continue
                
                actual_type = actual_columns[col_name]
                # Normalize type names (nvarchar(255) -> nvarchar)
                actual_type_base = actual_type.split('(')[0]
                
                if actual_type_base != expected_type:
                    # Allow compatible types
                    compatible = {
                        'nvarchar': ['varchar', 'nvarchar', 'text', 'ntext'],
                        'bigint': ['bigint', 'int'],
                        'datetime2': ['datetime2', 'datetime'],
                    }
                    
                    if actual_type_base not in compatible.get(expected_type, [expected_type]):
                        missing_columns.append(f"{col_name} (found {actual_type}, expected {expected_type})")
            
            if missing_columns:
                raise SchemaValidationError(
                    f"Schema validation failed for {self.fully_qualified_table}.\n\n"
                    f"Missing or incorrect columns:\n" +
                    "\n".join(f"  - {col}" for col in missing_columns) +
                    f"\n\nSuggested action: Run manager.create_table(drop_existing=True) to recreate table",
                    missing_columns=missing_columns
                )
            
            return True
            
        except pyodbc.Error as e:
            raise MappingTableError(
                f"Failed to validate schema: {str(e)}"
            ) from e
    
    def insert_batch(
        self,
        mappings: List[MappingRecord],
        batch_size: int = 5000,
        skip_validation: bool = False
    ) -> Tuple[int, int]:
        """
        Bulk insert mapping records with transaction safety.
        
        Args:
            mappings: List of MappingRecord objects to insert
            batch_size: Number of records per insert batch (default: 5000)
            skip_validation: Skip schema validation (faster, use after initial validation)
            
        Returns:
            Tuple of (successful_inserts, failed_inserts)
            
        Raises:
            MappingInsertError: If batch insert fails critically
        """
        if not mappings:
            return (0, 0)
        
        # Validate schema first
        if not skip_validation:
            self.validate_schema()
        
        successful = 0
        failed = 0
        
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            # Prepare insert statement
            insert_sql = f"""
                INSERT INTO {self.fully_qualified_table} 
                (table_name, column_name, record_id, original_value, masked_value, 
                 batch_id, sanitization_run_id, schema_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """
            
            # Process in batches
            for i in range(0, len(mappings), batch_size):
                batch = mappings[i:i + batch_size]
                
                # Convert to tuples for executemany, with encryption if enabled
                batch_data = [
                    (
                        m.table_name,
                        m.column_name,
                        m.record_id,
                        self._encrypt_value(m.original_value),
                        self._encrypt_value(m.masked_value),
                        m.batch_id,
                        m.sanitization_run_id
                    )
                    for m in batch
                ]
                
                try:
                    cursor.executemany(insert_sql, batch_data)
                    conn.commit()
                    successful += len(batch)
                    
                    # Story 5.3: Invalidate cache for affected tables/columns
                    if self.cache:
                        for mapping in batch:
                            self.cache.invalidate_column(mapping.table_name, mapping.column_name)
                    
                except pyodbc.Error as batch_error:
                    # Rollback this batch
                    conn.rollback()
                    failed += len(batch)
                    
                    # Try individual inserts for this batch
                    for record_data in batch_data:
                        try:
                            cursor.execute(insert_sql, record_data)
                            conn.commit()
                            successful += 1
                            failed -= 1
                        except pyodbc.Error:
                            # Skip this record
                            continue
            
            cursor.close()
            conn.close()
            
            # Update stats
            self._total_inserts += successful
            self._failed_inserts += failed
            
            if failed > 0:
                raise MappingInsertError(
                    f"Batch insert partially failed: {successful} succeeded, {failed} failed",
                    failed_count=failed,
                    total_count=len(mappings)
                )
            
            return (successful, failed)
            
        except pyodbc.Error as e:
            raise MappingInsertError(
                f"Batch insert failed: {str(e)}\n\n"
                f"Attempted to insert {len(mappings)} mappings",
                failed_count=len(mappings),
                total_count=len(mappings)
            ) from e
    
    def insert_batch_no_commit(
        self,
        conn: pyodbc.Connection,
        mappings: List[MappingRecord],
        batch_size: int = 5000
    ) -> Tuple[List[MappingRecord], List[str]]:
        """
        Bulk insert mapping records using provided connection without committing.
        
        This method is designed for transaction-safe coordination with sanitization
        updates. The caller is responsible for transaction management (commit/rollback).
        
        Args:
            conn: Active database connection (must have autocommit=False)
            mappings: List of MappingRecord objects to insert
            batch_size: Number of records per insert batch (default: 5000)
            
        Returns:
            Tuple of (successful_records, error_messages)
            
        Raises:
            MappingInsertError: If batch insert fails critically
            
        Example:
            >>> conn = pyodbc.connect(connection_string)
            >>> conn.autocommit = False
            >>> try:
            >>>     # Execute database updates
            >>>     cursor.execute("UPDATE ...")
            >>>     # Insert mappings (same transaction)
            >>>     successful, errors = manager.insert_batch_no_commit(conn, mappings)
            >>>     # Commit both together
            >>>     conn.commit()
            >>> except Exception:
            >>>     conn.rollback()
        """
        if not mappings:
            return ([], [])
        
        successful_records = []
        error_messages = []
        
        try:
            cursor = conn.cursor()
            
            # Prepare insert statement
            insert_sql = f"""
                INSERT INTO {self.fully_qualified_table} 
                (table_name, column_name, record_id, original_value, masked_value, 
                 batch_id, sanitization_run_id, schema_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """
            
            # Process in batches
            for i in range(0, len(mappings), batch_size):
                batch = mappings[i:i + batch_size]
                
                # Convert to tuples for executemany, with encryption if enabled
                batch_data = [
                    (
                        m.table_name,
                        m.column_name,
                        m.record_id,
                        self._encrypt_value(m.original_value),
                        self._encrypt_value(m.masked_value),
                        m.batch_id,
                        m.sanitization_run_id
                    )
                    for m in batch
                ]
                
                try:
                    cursor.executemany(insert_sql, batch_data)
                    # Don't commit - caller handles transaction
                    successful_records.extend(batch)
                    
                    # Story 5.3: Invalidate cache for affected tables/columns
                    # Note: Cache invalidation happens immediately even though transaction
                    # not committed yet. This is conservative but safe - ensures no stale reads.
                    if self.cache:
                        for mapping in batch:
                            self.cache.invalidate_column(mapping.table_name, mapping.column_name)
                    
                except pyodbc.Error as batch_error:
                    error_msg = f"Batch {i//batch_size + 1} failed: {str(batch_error)}"
                    error_messages.append(error_msg)
                    
                    # Try individual inserts for this batch
                    for idx, record_data in enumerate(batch_data):
                        try:
                            cursor.execute(insert_sql, record_data)
                            # Don't commit - caller handles transaction
                            successful_records.append(batch[idx])
                        except pyodbc.Error as record_error:
                            error_messages.append(
                                f"Record {i + idx} failed: {str(record_error)}"
                            )
            
            # Update stats (don't close cursor - caller's connection)
            self._total_inserts += len(successful_records)
            self._failed_inserts += len(error_messages)
            
            return (successful_records, error_messages)
            
        except pyodbc.Error as e:
            error_msg = f"Batch insert failed critically: {str(e)}"
            raise MappingInsertError(
                error_msg,
                failed_count=len(mappings),
                total_count=len(mappings)
            ) from e
    
    def get_mappings(
        self,
        table_name: str,
        column_name: Optional[str] = None,
        record_ids: Optional[List[str]] = None,
        batch_id: Optional[str] = None,
        date_range_start: Optional[datetime] = None,
        date_range_end: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve mappings with flexible filtering and optional caching.
        
        Args:
            table_name: Table name to filter
            column_name: Optional column name filter
            record_ids: Optional list of record IDs to filter
            batch_id: Optional batch ID filter
            date_range_start: Optional start date for created_at filter (inclusive)
            date_range_end: Optional end date for created_at filter (inclusive)
            
        Returns:
            List of mapping dictionaries
            
        Raises:
            MappingTableError: If query fails
            
        Story 5.2: Added date_range_start and date_range_end parameters for
        incremental desanitization workflows.
        
        Story 5.3: Added cache integration for optimized lookups. Cache is only
        used for single-value lookups (specific table + column + masked value).
        Complex queries with filters bypass cache and query database directly.
        """
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            # Build query with filters
            query = f"""
                SELECT 
                    mapping_id, table_name, column_name, record_id,
                    original_value, masked_value, created_at,
                    batch_id, sanitization_run_id
                FROM {self.fully_qualified_table}
                WHERE table_name = ?
            """
            params = [table_name]
            
            if column_name:
                query += " AND column_name = ?"
                params.append(column_name)
            
            if record_ids:
                placeholders = ','.join('?' * len(record_ids))
                query += f" AND record_id IN ({placeholders})"
                params.extend(record_ids)
            
            if batch_id:
                query += " AND batch_id = ?"
                params.append(batch_id)
            
            # Story 5.2: Time-based filtering for incremental desanitization
            if date_range_start:
                query += " AND created_at >= ?"
                params.append(date_range_start)
            
            if date_range_end:
                query += " AND created_at <= ?"
                params.append(date_range_end)
            
            cursor.execute(query, params)
            
            # Convert to dicts with decryption and caching if enabled
            columns = [col[0] for col in cursor.description]
            results = []
            for row in cursor.fetchall():
                result_dict = dict(zip(columns, row))
                # Decrypt sensitive columns
                result_dict['original_value'] = self._decrypt_value(result_dict.get('original_value'))
                result_dict['masked_value'] = self._decrypt_value(result_dict.get('masked_value'))
                
                # Story 5.3: Populate cache with results (write-through)
                # Cache key: (table_name, column_name, masked_value) -> original_value
                if self.cache and result_dict.get('masked_value'):
                    cache_key = (
                        result_dict['table_name'],
                        result_dict['column_name'],
                        result_dict['masked_value']
                    )
                    self.cache.set(cache_key, result_dict['original_value'])
                
                results.append(result_dict)
            
            cursor.close()
            conn.close()
            
            return results
            
        except pyodbc.Error as e:
            raise MappingTableError(
                f"Failed to retrieve mappings: {str(e)}"
            ) from e
    
    @staticmethod
    def serialize_composite_pk(pk_values: Dict[str, Any]) -> str:
        """
        Serialize composite primary key to JSON string.
        
        Args:
            pk_values: Dict of {column_name: value}
            
        Returns:
            JSON string representation
            
        Example:
            >>> serialize_composite_pk({"CustomerID": 123, "OrderID": 456})
            '{"CustomerID":123,"OrderID":456}'
        """
        return json.dumps(pk_values, sort_keys=True)
    
    @staticmethod
    def deserialize_composite_pk(record_id: str) -> Dict[str, Any]:
        """
        Deserialize composite primary key from JSON string.
        
        Args:
            record_id: JSON string from record_id column
            
        Returns:
            Dict of {column_name: value}
            
        Example:
            >>> deserialize_composite_pk('{"CustomerID":123,"OrderID":456}')
            {'CustomerID': 123, 'OrderID': 456}
        """
        try:
            return json.loads(record_id)
        except json.JSONDecodeError:
            # Handle simple PKs (not JSON)
            return {"id": record_id}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get insert statistics."""
        return {
            "total_inserts": self._total_inserts,
            "failed_inserts": self._failed_inserts,
            "success_rate": (
                self._total_inserts / (self._total_inserts + self._failed_inserts)
                if (self._total_inserts + self._failed_inserts) > 0
                else 0.0
            )
        }
    
    def list_available_batches(self) -> List[BatchMetadata]:
        """
        List all available sanitization batches with metadata.
        
        This method queries the mapping table to find all distinct batch IDs
        along with their associated metadata including row counts, timestamps,
        and affected database objects.
        
        Returns:
            List of BatchMetadata objects, ordered by latest_timestamp DESC
            
        Raises:
            MappingTableError: If query fails
            
        Example:
            >>> manager = MappingTableManager(conn_str)
            >>> batches = manager.list_available_batches()
            >>> for batch in batches:
            ...     print(f"{batch.batch_id}: {batch.row_count} rows, {len(batch.affected_tables)} tables")
            
        Note:
            This is a read-only operation safe to call at any time.
            Returns empty list if no mappings exist.
        """
        try:
            with pyodbc.connect(self.connection_string) as conn:
                cursor = conn.cursor()
                
                # Query to aggregate batch metadata
                query = f"""
                    SELECT 
                        batch_id,
                        COUNT(*) as row_count,
                        MIN(created_at) as earliest_timestamp,
                        MAX(created_at) as latest_timestamp,
                        COUNT(DISTINCT table_name) as table_count,
                        COUNT(DISTINCT column_name) as column_count
                    FROM {self.fully_qualified_table}
                    GROUP BY batch_id
                    ORDER BY MAX(created_at) DESC
                """
                
                cursor.execute(query)
                rows = cursor.fetchall()
                
                # For each batch, get detailed table and column lists
                batches = []
                for row in rows:
                    batch_id = row.batch_id
                    
                    # Get affected tables
                    cursor.execute(f"""
                        SELECT DISTINCT table_name 
                        FROM {self.fully_qualified_table}
                        WHERE batch_id = ?
                        ORDER BY table_name
                    """, (batch_id,))
                    affected_tables = [r.table_name for r in cursor.fetchall()]
                    
                    # Get affected columns
                    cursor.execute(f"""
                        SELECT DISTINCT column_name 
                        FROM {self.fully_qualified_table}
                        WHERE batch_id = ?
                        ORDER BY column_name
                    """, (batch_id,))
                    affected_columns = [r.column_name for r in cursor.fetchall()]
                    
                    # Create BatchMetadata object
                    batches.append(BatchMetadata(
                        batch_id=batch_id,
                        row_count=row.row_count,
                        earliest_timestamp=row.earliest_timestamp,
                        latest_timestamp=row.latest_timestamp,
                        affected_tables=affected_tables,
                        affected_columns=affected_columns
                    ))
                
                return batches
                
        except pyodbc.Error as e:
            raise MappingTableError(
                f"Failed to list available batches: {str(e)}",
                suggested_action="Verify mapping table exists and is accessible"
            ) from e
    
    def _encrypt_value(self, value: Optional[str]) -> Optional[str]:
        """
        Encrypt a value if encryptor is configured.
        
        Args:
            value: Plaintext value (None for NULL)
            
        Returns:
            Encrypted value if encryptor configured, otherwise original value
        """
        if self.encryptor is None:
            return value
        return self.encryptor.encrypt(value)
    
    def _decrypt_value(self, value: Optional[str]) -> Optional[str]:
        """
        Decrypt a value if encryptor is configured.
        
        Args:
            value: Encrypted value (None for NULL)
            
        Returns:
            Decrypted value if encryptor configured, otherwise original value
        """
        if self.encryptor is None:
            return value
        return self.encryptor.decrypt(value)
    
    def __repr__(self) -> str:
        encryption_status = "encrypted" if self.encryptor else "unencrypted"
        cache_status = f"cache={self.cache.get_size()}/{self.cache.max_size}" if self.cache else "no-cache"
        return (
            f"MappingTableManager(table={self.fully_qualified_table}, "
            f"inserts={self._total_inserts}, failed={self._failed_inserts}, "
            f"encryption={encryption_status}, {cache_status})"
        )
