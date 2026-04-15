"""
Checkpoint Manager for database-level desanitization fault tolerance.

This module provides the CheckpointManager class for managing the 
desanitization_checkpoints table: creation, validation, status tracking,
and resume operations for long-running database restorations.
"""

import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum

import pyodbc

from desanitization.exceptions import CheckpointError


class CheckpointStatus(str, Enum):
    """Status values for checkpoint records."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class CheckpointRecord:
    """Represents a single checkpoint record."""
    operation_id: str
    table_name: str
    schema_name: str = "dbo"
    status: CheckpointStatus = CheckpointStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    rows_restored: Optional[int] = None
    columns_affected: Optional[int] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    batch_id: Optional[str] = None
    checkpoint_id: Optional[int] = None  # Set after insert


@dataclass
class OperationStatus:
    """Summary of operation progress from checkpoints."""
    operation_id: str
    total_tables: int
    completed_tables: int
    failed_tables: int
    in_progress_tables: int
    pending_tables: int
    started_at: Optional[datetime]
    last_updated: Optional[datetime]
    is_complete: bool
    has_failures: bool


class CheckpointManager:
    """
    Manage desanitization_checkpoints table for fault-tolerant database restoration.
    
    Responsibilities:
    - Create and validate checkpoint table schema
    - Track progress of table-level desanitization operations
    - Enable resume after failures
    - Clean up stale checkpoints
    
    Usage:
        manager = CheckpointManager(connection_string)
        manager.create_table()
        
        # Start operation
        operation_id = "DESAN-20260409..."
        manager.initialize_operation(operation_id, table_list)
        
        # Update progress
        manager.mark_in_progress(operation_id, "Customers")
        manager.mark_completed(operation_id, "Customers", rows=15000, columns=5)
        
        # Resume after failure
        status = manager.get_operation_status(operation_id)
        incomplete = manager.get_incomplete_tables(operation_id)
    """
    
    # Required schema columns for validation
    REQUIRED_COLUMNS = {
        "checkpoint_id": "bigint",
        "operation_id": "nvarchar",
        "table_name": "nvarchar",
        "schema_name": "nvarchar",
        "status": "nvarchar",
        "started_at": "datetime2",
        "completed_at": "datetime2",
        "rows_restored": "int",
        "columns_affected": "int",
        "error_message": "nvarchar",
        "retry_count": "int",
        "created_at": "datetime2",
        "updated_at": "datetime2",
        "batch_id": "nvarchar",
    }
    
    def __init__(
        self,
        connection_string: str,
        table_name: str = "desanitization_checkpoints",
        schema: str = "dbo"
    ):
        """
        Initialize CheckpointManager.
        
        Args:
            connection_string: SQL Server connection string
            table_name: Name of checkpoint table (default: desanitization_checkpoints)
            schema: Database schema (default: dbo)
        """
        self.connection_string = connection_string
        self.table_name = table_name
        self.schema = schema
        self.fully_qualified_table = f"[{schema}].[{table_name}]"
    
    def create_table(self, drop_existing: bool = False) -> bool:
        """
        Create checkpoint table with indexes and constraints.
        
        Args:
            drop_existing: If True, drop existing table before creating
            
        Returns:
            True if table created, False if already exists
            
        Raises:
            CheckpointError: If table creation fails
        """
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            # Check if table exists
            cursor.execute("""
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
                "create_checkpoint_table.sql"
            )
            
            if not os.path.exists(script_path):
                raise CheckpointError(
                    f"SQL script not found: {script_path}",
                    operation_id=None
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
                if 'PRINT' in batch.upper():
                    continue
                cursor.execute(batch)
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return True
            
        except Exception as e:
            raise CheckpointError(
                f"Failed to create checkpoint table: {e}",
                operation_id=None
            )
    
    def validate_schema(self) -> bool:
        """
        Validate checkpoint table schema matches expected structure.
        
        Returns:
            True if schema is valid
            
        Raises:
            CheckpointError: If schema validation fails
        """
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            # Check table exists
            cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            """, (self.schema, self.table_name))
            
            if cursor.fetchone()[0] == 0:
                raise CheckpointError(
                    f"Checkpoint table {self.fully_qualified_table} does not exist",
                    operation_id=None
                )
            
            # Get actual columns
            cursor.execute("""
                SELECT COLUMN_NAME, DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            """, (self.schema, self.table_name))
            
            actual_columns = {
                row.COLUMN_NAME.lower(): row.DATA_TYPE.lower()
                for row in cursor.fetchall()
            }
            
            # Validate required columns exist
            missing_columns = []
            for col_name, expected_type in self.REQUIRED_COLUMNS.items():
                if col_name not in actual_columns:
                    missing_columns.append(col_name)
            
            if missing_columns:
                raise CheckpointError(
                    f"Checkpoint table missing columns: {missing_columns}",
                    operation_id=None
                )
            
            cursor.close()
            conn.close()
            
            return True
            
        except CheckpointError:
            raise
        except Exception as e:
            raise CheckpointError(
                f"Failed to validate checkpoint schema: {e}",
                operation_id=None
            )
    
    def initialize_operation(
        self,
        operation_id: str,
        tables: List[tuple],  # List of (table_name, schema_name) tuples
        batch_id: Optional[str] = None
    ) -> int:
        """
        Initialize checkpoint records for a new database-level operation.
        
        Creates PENDING checkpoint entries for all tables to be processed.
        
        Args:
            operation_id: Unique operation identifier
            tables: List of (table_name, schema_name) tuples
            batch_id: Optional batch ID from sanitization
            
        Returns:
            Number of checkpoint records created
            
        Raises:
            CheckpointError: If initialization fails
        """
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            # Insert PENDING checkpoints for all tables
            insert_sql = f"""
                INSERT INTO {self.fully_qualified_table}
                (operation_id, table_name, schema_name, status, batch_id)
                VALUES (?, ?, ?, ?, ?)
            """
            
            records = [
                (operation_id, table_name, schema_name, CheckpointStatus.PENDING.value, batch_id)
                for table_name, schema_name in tables
            ]
            
            cursor.executemany(insert_sql, records)
            inserted_count = cursor.rowcount
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return inserted_count
            
        except Exception as e:
            raise CheckpointError(
                f"Failed to initialize operation checkpoints: {e}",
                operation_id=operation_id
            )
    
    def mark_in_progress(
        self,
        operation_id: str,
        table_name: str,
        schema_name: str = "dbo"
    ) -> None:
        """
        Mark a table as IN_PROGRESS.
        
        Args:
            operation_id: Operation identifier
            table_name: Table being processed
            schema_name: Schema name
            
        Raises:
            CheckpointError: If update fails
        """
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            update_sql = f"""
                UPDATE {self.fully_qualified_table}
                SET status = ?, started_at = GETDATE()
                WHERE operation_id = ? AND table_name = ? AND schema_name = ?
            """
            
            cursor.execute(
                update_sql,
                (CheckpointStatus.IN_PROGRESS.value, operation_id, table_name, schema_name)
            )
            
            if cursor.rowcount == 0:
                raise CheckpointError(
                    f"Checkpoint not found for table {schema_name}.{table_name}",
                    operation_id=operation_id
                )
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except CheckpointError:
            raise
        except Exception as e:
            raise CheckpointError(
                f"Failed to mark table as in-progress: {e}",
                operation_id=operation_id
            )
    
    def mark_completed(
        self,
        operation_id: str,
        table_name: str,
        schema_name: str = "dbo",
        rows_restored: Optional[int] = None,
        columns_affected: Optional[int] = None
    ) -> None:
        """
        Mark a table as COMPLETED with optional metrics.
        
        Args:
            operation_id: Operation identifier
            table_name: Table that was processed
            schema_name: Schema name
            rows_restored: Number of rows restored
            columns_affected: Number of columns affected
            
        Raises:
            CheckpointError: If update fails
        """
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            update_sql = f"""
                UPDATE {self.fully_qualified_table}
                SET status = ?,
                    completed_at = GETDATE(),
                    rows_restored = ?,
                    columns_affected = ?
                WHERE operation_id = ? AND table_name = ? AND schema_name = ?
            """
            
            cursor.execute(
                update_sql,
                (CheckpointStatus.COMPLETED.value, rows_restored, columns_affected,
                 operation_id, table_name, schema_name)
            )
            
            if cursor.rowcount == 0:
                raise CheckpointError(
                    f"Checkpoint not found for table {schema_name}.{table_name}",
                    operation_id=operation_id
                )
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except CheckpointError:
            raise
        except Exception as e:
            raise CheckpointError(
                f"Failed to mark table as completed: {e}",
                operation_id=operation_id
            )
    
    def mark_failed(
        self,
        operation_id: str,
        table_name: str,
        schema_name: str = "dbo",
        error_message: Optional[str] = None
    ) -> None:
        """
        Mark a table as FAILED with error message.
        
        Args:
            operation_id: Operation identifier
            table_name: Table that failed
            schema_name: Schema name
            error_message: Error description
            
        Raises:
            CheckpointError: If update fails
        """
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            # Increment retry count
            update_sql = f"""
                UPDATE {self.fully_qualified_table}
                SET status = ?,
                    error_message = ?,
                    retry_count = retry_count + 1,
                    completed_at = GETDATE()
                WHERE operation_id = ? AND table_name = ? AND schema_name = ?
            """
            
            cursor.execute(
                update_sql,
                (CheckpointStatus.FAILED.value, error_message,
                 operation_id, table_name, schema_name)
            )
            
            if cursor.rowcount == 0:
                raise CheckpointError(
                    f"Checkpoint not found for table {schema_name}.{table_name}",
                    operation_id=operation_id
                )
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except CheckpointError:
            raise
        except Exception as e:
            raise CheckpointError(
                f"Failed to mark table as failed: {e}",
                operation_id=operation_id
            )
    
    def get_operation_status(self, operation_id: str) -> Optional[OperationStatus]:
        """
        Get progress summary for an operation.
        
        Args:
            operation_id: Operation identifier
            
        Returns:
            OperationStatus object or None if operation not found
            
        Raises:
            CheckpointError: If query fails
        """
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            # Aggregate status counts
            cursor.execute(f"""
                SELECT 
                    COUNT(*) AS total_tables,
                    SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed,
                    SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN status = 'IN_PROGRESS' THEN 1 ELSE 0 END) AS in_progress,
                    SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) AS pending,
                    MIN(created_at) AS started_at,
                    MAX(updated_at) AS last_updated
                FROM {self.fully_qualified_table}
                WHERE operation_id = ?
            """, (operation_id,))
            
            row = cursor.fetchone()
            
            if not row or row.total_tables == 0:
                cursor.close()
                conn.close()
                return None
            
            status = OperationStatus(
                operation_id=operation_id,
                total_tables=row.total_tables or 0,
                completed_tables=row.completed or 0,
                failed_tables=row.failed or 0,
                in_progress_tables=row.in_progress or 0,
                pending_tables=row.pending or 0,
                started_at=row.started_at,
                last_updated=row.last_updated,
                is_complete=(row.completed + row.failed) == row.total_tables,
                has_failures=row.failed > 0
            )
            
            cursor.close()
            conn.close()
            
            return status
            
        except Exception as e:
            raise CheckpointError(
                f"Failed to get operation status: {e}",
                operation_id=operation_id
            )
    
    def get_incomplete_tables(
        self,
        operation_id: str
    ) -> List[tuple]:
        """
        Get list of tables that haven't completed successfully.
        
        Includes tables with status: PENDING, IN_PROGRESS, or FAILED.
        
        Args:
            operation_id: Operation identifier
            
        Returns:
            List of (table_name, schema_name, status) tuples
            
        Raises:
            CheckpointError: If query fails
        """
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            cursor.execute(f"""
                SELECT table_name, schema_name, status
                FROM {self.fully_qualified_table}
                WHERE operation_id = ?
                  AND status IN ('PENDING', 'IN_PROGRESS', 'FAILED')
                ORDER BY created_at
            """, (operation_id,))
            
            tables = [(row.table_name, row.schema_name, row.status) for row in cursor.fetchall()]
            
            cursor.close()
            conn.close()
            
            return tables
            
        except Exception as e:
            raise CheckpointError(
                f"Failed to get incomplete tables: {e}",
                operation_id=operation_id
            )
    
    def list_incomplete_operations(
        self,
        max_age_hours: int = 24
    ) -> List[str]:
        """
        List all operations with incomplete checkpoints.
        
        Args:
            max_age_hours: Only include operations created within this timeframe
            
        Returns:
            List of operation_ids with incomplete tables
            
        Raises:
            CheckpointError: If query fails
        """
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
            
            cursor.execute(f"""
                SELECT DISTINCT operation_id
                FROM {self.fully_qualified_table}
                WHERE status IN ('PENDING', 'IN_PROGRESS', 'FAILED')
                  AND created_at >= ?
                ORDER BY created_at DESC
            """, (cutoff_time,))
            
            operation_ids = [row.operation_id for row in cursor.fetchall()]
            
            cursor.close()
            conn.close()
            
            return operation_ids
            
        except Exception as e:
            raise CheckpointError(
                f"Failed to list incomplete operations: {e}",
                operation_id=None
            )
    
    def clear_stale_checkpoints(
        self,
        max_age_hours: int = 24
    ) -> int:
        """
        Remove old checkpoint records to prevent table bloat.
        
        Only removes checkpoints with status COMPLETED or FAILED.
        PENDING/IN_PROGRESS checkpoints are preserved as they may be resumed.
        
        Args:
            max_age_hours: Remove checkpoints older than this (default: 24)
            
        Returns:
            Number of checkpoint records deleted
            
        Raises:
            CheckpointError: If cleanup fails
        """
        try:
            conn = pyodbc.connect(self.connection_string)
            cursor = conn.cursor()
            
            cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
            
            delete_sql = f"""
                DELETE FROM {self.fully_qualified_table}
                WHERE created_at < ?
                  AND status IN ('COMPLETED', 'FAILED')
            """
            
            cursor.execute(delete_sql, (cutoff_time,))
            deleted_count = cursor.rowcount
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return deleted_count
            
        except Exception as e:
            raise CheckpointError(
                f"Failed to clear stale checkpoints: {e}",
                operation_id=None
            )
