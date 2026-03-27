"""
Batch data update for SQL Server tables with transaction safety and deadlock handling.

This module provides memory-efficient batch updates of PII data in SQL Server tables
using optimal update strategies based on primary key structure. Supports tables with
millions of rows with transaction safety and automatic deadlock retry.

Key Features:
    - Key-based updates (O(log n)) for single numeric primary keys
    - Composite key updates for multi-column primary keys
    - ROW_NUMBER fallback for tables without suitable primary keys
    - Transaction management with automatic commit/rollback
    - Deadlock detection and automatic retry with exponential backoff
    - Memory-efficient iterator pattern (yields batches, never loads all data)
    - Progress tracking with row counts
    - Data type validation before updates
    - Proper SQL identifier escaping for special characters

Author: Database Sanitization Team
Date: 2026-03-26
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Tuple, Callable
from functools import wraps
import time
import pyodbc

from .connection_manager import DatabaseConnectionManager
from .schema_extractor import SchemaExtractor
from ..exceptions import (
    DataUpdateError,
    DatabaseConnectionError,
    DatabaseQueryError,
    CircularDependencyError,
)
from ..logging.logger import get_logger
from ..logging.correlation import CorrelationContext


class UpdateStrategy(Enum):
    """Update strategy selection based on primary key structure."""
    
    KEY_BASED = "key_based"           # Single numeric PK - O(log n) performance
    COMPOSITE_KEY = "composite_key"    # Multi-column PK - tuple comparison
    ROW_NUMBER = "row_number"         # No suitable PK - OFFSET/FETCH fallback


@dataclass
class UpdateBatch:
    """
    Represents a single batch of updated data.
    
    Attributes:
        updated_count: Number of rows updated in this batch
        batch_number: Sequential batch number (1-indexed)
        rows_updated: Cumulative rows updated so far (including this batch)
        total_rows: Total rows to be updated
        schema_name: Database schema name
        table_name: Table name
        columns_updated: List of column names that were updated
        strategy: Update strategy used
    """
    
    updated_count: int
    batch_number: int
    rows_updated: int
    total_rows: int
    schema_name: str
    table_name: str
    columns_updated: List[str]
    strategy: UpdateStrategy
    
    @property
    def progress_percentage(self) -> float:
        """
        Calculate completion percentage.
        
        Returns:
            Progress as percentage (0.0 to 100.0), or 0.0 if total_rows is 0
        """
        if self.total_rows == 0:
            return 0.0
        return (self.rows_updated / self.total_rows) * 100.0
    
    @property
    def is_last_batch(self) -> bool:
        """Check if this is the final batch."""
        return self.rows_updated >= self.total_rows
    
    @property
    def full_table_name(self) -> str:
        """Get fully qualified table name."""
        return f"{self.schema_name}.{self.table_name}"


def retry_on_deadlock(
    max_attempts: int = 3,
    backoff_factor: float = 0.5
) -> Callable:
    """Decorator to retry operations on deadlock detection with exponential backoff.
    
    This decorator automatically retries a function when SQL Server deadlock (error 1205)
    is detected, using exponential backoff to reduce contention.
    
    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
        backoff_factor: Base delay multiplier for exponential backoff (default: 0.5)
            Delays will be: backoff_factor * 2^0, backoff_factor * 2^1, backoff_factor * 2^2, ...
            Example: With backoff_factor=0.5, delays are 0.5s, 1s, 2s
    
    Returns:
        Decorated function with deadlock retry logic
    
    Example:
        >>> @retry_on_deadlock(max_attempts=3, backoff_factor=0.5)
        ... def update_batch(data):
        ...     # Perform batch update
        ...     pass
    
    Raises:
        DataUpdateError.deadlock_retry_exhausted: If all retry attempts fail
        Other exceptions: Passed through without retry
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    # Attempt to execute the function
                    return func(*args, **kwargs)
                
                except pyodbc.Error as e:
                    # Check if this is a deadlock
                    # SQL Server deadlock error codes: 1205 (deadlock victim), -3 (connection broken)
                    # SQLSTATE codes: 40001 (serialization failure)
                    is_deadlock = False
                    
                    # Check native error number (e.args[1] for pyodbc)
                    if len(e.args) > 1 and isinstance(e.args[1], int):
                        error_number = e.args[1]
                        is_deadlock = error_number in (1205, -3)
                    
                    # Fallback: Check SQLSTATE code
                    if not is_deadlock and e.args:
                        sqlstate = str(e.args[0])
                        is_deadlock = sqlstate == "40001"
                    
                    # Final fallback: Check error message (language-dependent but better than nothing)
                    if not is_deadlock:
                        error_msg = str(e).lower()
                        is_deadlock = "deadlock" in error_msg or "was deadlocked" in error_msg
                    
                    if not is_deadlock:
                        # Not a deadlock, re-raise immediately
                        raise
                    
                    last_exception = e
                    
                    # Get table name from args if available (self is args[0] for instance methods)
                    table_name = "unknown"
                    if len(args) >= 3 and isinstance(args[2], str):
                        table_name = args[2]  # Typically table_name is 3rd arg
                    
                    # If this was the last attempt, raise custom exception
                    if attempt == max_attempts:
                        raise DataUpdateError.deadlock_retry_exhausted(
                            table_name=table_name,
                            max_attempts=max_attempts,
                            original_error=str(e)
                        ) from e
                    
                    # Calculate exponential backoff delay
                    delay = backoff_factor * (2 ** (attempt - 1))
                    
                    # Log the retry
                    logger = get_logger(__name__)
                    logger.warning(
                        f"Deadlock detected in {func.__name__} (attempt {attempt}/{max_attempts}). "
                        f"Retrying in {delay}s..."
                    )
                    
                    time.sleep(delay)
            
            # Should never reach here, but satisfy type checker
            if last_exception:
                raise last_exception
        
        return wrapper
    return decorator


class BatchUpdater:
    """
    Update PII data in batches in SQL Server tables with transaction safety.
    
    This class automatically selects the best update strategy based on primary key
    structure, provides transaction safety with automatic commit/rollback, handles
    deadlocks with retry logic, and validates data types before updates.
    
    Attributes:
        connection_manager: DatabaseConnectionManager for query execution
        schema_extractor: SchemaExtractor for metadata retrieval
        batch_size: Number of rows per batch (default: 10,000)
        max_batch_size: Maximum allowed batch size (default: 100,000)
        max_retries: Maximum deadlock retry attempts (default: 3)
        logger: Logger with context for operation tracking
    
    Example:
        >>> from src.database import DatabaseConnectionManager, SchemaExtractor, BatchUpdater
        >>> conn_mgr = DatabaseConnectionManager(config)
        >>> schema_ext = SchemaExtractor(conn_mgr)
        >>> updater = BatchUpdater(conn_mgr, schema_ext, batch_size=10000)
        >>> 
        >>> # Prepare updates: {pk_value: {column: new_value}}
        >>> updates = {
        ...     1: {"Email": "masked1@example.com", "Phone": "555-0001"},
        ...     2: {"Email": "masked2@example.com", "Phone": "555-0002"},
        ... }
        >>> 
        >>> for batch in updater.update_batches("dbo", "Customers", ["CustomerID"], updates):
        ...     print(f"Batch {batch.batch_number}: {batch.updated_count} rows "
        ...           f"({batch.progress_percentage:.1f}% complete)")
    """
    
    def __init__(
        self,
        connection_manager: DatabaseConnectionManager,
        schema_extractor: SchemaExtractor,
        batch_size: int = 10000,
        max_retries: int = 3,
        respect_fk_order: bool = True,
        logger: Optional[Any] = None,
    ) -> None:
        """
        Initialize the BatchUpdater.
        
        Args:
            connection_manager: DatabaseConnectionManager instance for query execution
            schema_extractor: SchemaExtractor instance for metadata retrieval
            batch_size: Number of rows per batch (default: 10,000)
            max_retries: Maximum deadlock retry attempts (default: 3)
            respect_fk_order: Whether to auto-order tables by FK dependencies (default: True)
            logger: Optional logger with context (will create if not provided)
        
        Raises:
            DataUpdateError: If batch_size is invalid (< 1 or > 100,000)
        """
        if batch_size < 1 or batch_size > 100000:
            raise DataUpdateError.invalid_batch_size(batch_size)
        
        self.connection_manager = connection_manager
        self.schema_extractor = schema_extractor
        self.batch_size = batch_size
        self.max_batch_size = 100000
        self.max_retries = max_retries
        self.respect_fk_order = respect_fk_order
        self.logger = logger or get_logger(__name__).with_context(module="batch_updater")
    
    def update_batches(
        self,
        schema_name: str,
        table_name: str,
        pk_columns: List[str],
        updates: Dict[Any, Dict[str, Any]],
    ) -> Iterator[UpdateBatch]:
        """
        Update rows in batches using optimal strategy based on primary key structure.
        
        This is the main entry point for batch updates. It automatically:
        - Selects the best update strategy based on PK structure
        - Validates columns exist in the table
        - Wraps each batch in a transaction
        - Retries on deadlock detection
        - Tracks progress
        
        Args:
            schema_name: Database schema name (e.g., "dbo")
            table_name: Table name (e.g., "Customers")
            pk_columns: List of primary key column names (e.g., ["CustomerID"])
            updates: Dictionary mapping PK value(s) to column updates
                     Format: {pk_value: {column1: new_value1, column2: new_value2}}
                     For composite PK: {(pk1, pk2): {column: value}}
        
        Yields:
            UpdateBatch instances with progress tracking
        
        Raises:
            DataUpdateError: If validation fails or update fails
            DatabaseConnectionError: If connection fails
        
        Example:
            >>> updates = {
            ...     1: {"Email": "masked1@example.com"},
            ...     2: {"Email": "masked2@example.com"},
            ... }
            >>> for batch in updater.update_batches("dbo", "Users", ["UserID"], updates):
            ...     print(f"Updated {batch.updated_count} rows")
        """
        with CorrelationContext() as correlation_id:
            self.logger.info(
                f"Starting batch update for [{schema_name}].[{table_name}]",
                extra={
                    "correlation_id": correlation_id,
                    "schema": schema_name,
                    "table": table_name,
                    "batch_size": self.batch_size,
                    "total_updates": len(updates),
                    "pk_columns": pk_columns,
                }
            )
            
            # Validate inputs
            if not updates:
                self.logger.warning(f"No updates provided for [{schema_name}].[{table_name}]")
                return
            
            # Extract columns to update (from first update entry)
            first_update = next(iter(updates.values()))
            columns_to_update = list(first_update.keys())
            
            # Validate columns exist
            self._validate_columns_exist(schema_name, table_name, columns_to_update)
            
            # Check for computed columns and triggers, filter columns if needed
            columns_to_update = self._check_constraints_and_warnings(
                schema_name,
                table_name,
                columns_to_update
            )
            
            # If all columns were filtered out (all computed), nothing to update
            if not columns_to_update:
                self.logger.error(
                    f"No updateable columns remaining for [{schema_name}].[{table_name}] - "
                    f"all specified columns are computed (read-only)"
                )
                raise DataUpdateError.update_failed(
                    table_name=f"{schema_name}.{table_name}",
                    reason="All specified columns are computed and cannot be updated"
                )
            
            # Validate PK columns
            self._validate_pk_columns(schema_name, table_name, pk_columns)
            
            # Select update strategy
            strategy = self._select_update_strategy(schema_name, table_name, pk_columns)
            
            self.logger.info(
                f"Selected update strategy: {strategy.value}",
                extra={
                    "correlation_id": correlation_id,
                    "strategy": strategy.value,
                    "pk_columns": pk_columns,
                }
            )
            
            # Delegate to appropriate strategy
            if strategy == UpdateStrategy.KEY_BASED:
                yield from self._update_key_based(
                    schema_name,
                    table_name,
                    pk_columns[0],
                    columns_to_update,
                    updates,
                    correlation_id
                )
            elif strategy == UpdateStrategy.COMPOSITE_KEY:
                yield from self._update_composite_key(
                    schema_name,
                    table_name,
                    pk_columns,
                    columns_to_update,
                    updates,
                    correlation_id
                )
            else:  # ROW_NUMBER
                yield from self._update_row_number(
                    schema_name,
                    table_name,
                    pk_columns,
                    columns_to_update,
                    updates,
                    correlation_id
                )
            
            self.logger.info(
                f"Completed batch update for [{schema_name}].[{table_name}]",
                extra={"correlation_id": correlation_id}
            )
    
    def _select_update_strategy(
        self,
        schema_name: str,
        table_name: str,
        pk_columns: List[str]
    ) -> UpdateStrategy:
        """
        Select the optimal update strategy based on primary key structure.
        
        Strategy selection logic:
        - No PK or empty list → ROW_NUMBER (slowest, fallback)
        - Multiple PK columns (>1) → COMPOSITE_KEY (medium)
        - Single numeric PK (INT/BIGINT/SMALLINT/TINYINT) → KEY_BASED (fastest)
        - Single non-numeric PK (GUID, VARCHAR) → ROW_NUMBER (fallback)
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            pk_columns: List of primary key column names
        
        Returns:
            UpdateStrategy enum value
        """
        if not pk_columns or len(pk_columns) == 0:
            self.logger.debug("No primary key columns provided, using ROW_NUMBER strategy")
            return UpdateStrategy.ROW_NUMBER
        
        if len(pk_columns) > 1:
            if len(pk_columns) > 4:
                self.logger.warning(
                    f"Composite key has {len(pk_columns)} columns. "
                    f"Consider limiting to 4 or fewer for better performance"
                )
            self.logger.debug(f"Using COMPOSITE_KEY strategy for {len(pk_columns)} PK columns")
            return UpdateStrategy.COMPOSITE_KEY
        
        # Check if single PK is numeric
        db_name = self.connection_manager.config.database
        schema_metadata = self.schema_extractor.extract_schema(db_name)
        
        for table_info in schema_metadata.get("tables", []):
            if table_info.get("schema") == schema_name and table_info.get("name") == table_name:
                for col in table_info.get("columns", []):
                    if col["name"] == pk_columns[0]:
                        data_type = col["data_type"].upper()
                        numeric_types = {"INT", "BIGINT", "SMALLINT", "TINYINT"}
                        
                        if data_type in numeric_types:
                            self.logger.debug(
                                f"Using KEY_BASED strategy for numeric PK: {pk_columns[0]} ({data_type})"
                            )
                            return UpdateStrategy.KEY_BASED
                        else:
                            self.logger.debug(
                                f"Using ROW_NUMBER strategy for non-numeric PK: {pk_columns[0]} ({data_type})"
                            )
                            return UpdateStrategy.ROW_NUMBER
        
        # Default to ROW_NUMBER if metadata not found
        self.logger.warning(
            f"Could not determine PK data type for [{schema_name}].[{table_name}], "
            f"defaulting to ROW_NUMBER strategy"
        )
        return UpdateStrategy.ROW_NUMBER
    
    @retry_on_deadlock(max_attempts=3, backoff_factor=0.5)
    def _update_key_based(
        self,
        schema_name: str,
        table_name: str,
        pk_column: str,
        columns_to_update: List[str],
        updates: Dict[Any, Dict[str, Any]],
        correlation_id: str,
    ) -> Iterator[UpdateBatch]:
        """
        Update rows using key-based strategy (single numeric PK).
        
        This is the fastest strategy with O(log n) performance on indexed PK.
        Updates are ordered by PK value for consistent batch boundaries.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            pk_column: Primary key column name
            columns_to_update: List of columns to update
            updates: Dictionary mapping PK value to column updates
            correlation_id: Correlation ID for logging
        
        Yields:
            UpdateBatch instances
        """
        # Sort updates by PK value for ordered processing
        sorted_pk_values = sorted(updates.keys())
        total_rows = len(sorted_pk_values)
        
        batch_number = 0
        rows_updated = 0
        
        # Process in batches
        for i in range(0, total_rows, self.batch_size):
            batch_pks = sorted_pk_values[i:i + self.batch_size]
            batch_number += 1
            
            # Build parameterized update query
            set_clause = ", ".join([f"[{col}] = ?" for col in columns_to_update])
            query = (
                f"UPDATE [{schema_name}].[{table_name}] "
                f"SET {set_clause} "
                f"WHERE [{pk_column}] = ?"
            )
            
            # Prepare parameter tuples for executemany
            params_list = []
            for pk_value in batch_pks:
                update_values = updates[pk_value]
                # Values for SET clause + PK value for WHERE clause
                params = tuple(update_values[col] for col in columns_to_update) + (pk_value,)
                params_list.append(params)
            
            # Execute batch update within transaction
            try:
                with self.connection_manager.transaction_context() as conn:
                    cursor = conn.cursor()
                    cursor.executemany(query, params_list)
                    updated_count = cursor.rowcount
                    cursor.close()
                
                rows_updated += updated_count
                
                self.logger.debug(
                    f"Batch {batch_number} updated {updated_count} rows",
                    extra={
                        "correlation_id": correlation_id,
                        "batch_number": batch_number,
                        "updated_count": updated_count,
                        "rows_updated": rows_updated,
                        "total_rows": total_rows,
                    }
                )
                
                yield UpdateBatch(
                    updated_count=updated_count,
                    batch_number=batch_number,
                    rows_updated=rows_updated,
                    total_rows=total_rows,
                    schema_name=schema_name,
                    table_name=table_name,
                    columns_updated=columns_to_update,
                    strategy=UpdateStrategy.KEY_BASED,
                )
                
            except Exception as e:
                self.logger.error(
                    f"Failed to update batch {batch_number}",
                    extra={
                        "correlation_id": correlation_id,
                        "batch_number": batch_number,
                        "error": str(e),
                    }
                )
                raise DataUpdateError.batch_update_failed(
                    table_name=f"{schema_name}.{table_name}",
                    batch_number=batch_number,
                    reason=str(e)
                ) from e
    
    @retry_on_deadlock(max_attempts=3, backoff_factor=0.5)
    def _update_composite_key(
        self,
        schema_name: str,
        table_name: str,
        pk_columns: List[str],
        columns_to_update: List[str],
        updates: Dict[Tuple[Any, ...], Dict[str, Any]],
        correlation_id: str,
    ) -> Iterator[UpdateBatch]:
        """
        Update rows using composite key strategy (multi-column PK).
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            pk_columns: List of primary key column names
            columns_to_update: List of columns to update
            updates: Dictionary mapping composite PK tuple to column updates
            correlation_id: Correlation ID for logging
        
        Yields:
            UpdateBatch instances
        """
        # Sort updates by composite PK values
        sorted_pk_values = sorted(updates.keys())
        total_rows = len(sorted_pk_values)
        
        batch_number = 0
        rows_updated = 0
        
        # Process in batches
        for i in range(0, total_rows, self.batch_size):
            batch_pks = sorted_pk_values[i:i + self.batch_size]
            batch_number += 1
            
            # Build parameterized update query with composite WHERE clause
            set_clause = ", ".join([f"[{col}] = ?" for col in columns_to_update])
            where_clause = " AND ".join([f"[{pk_col}] = ?" for pk_col in pk_columns])
            query = (
                f"UPDATE [{schema_name}].[{table_name}] "
                f"SET {set_clause} "
                f"WHERE {where_clause}"
            )
            
            # Prepare parameter tuples for executemany
            params_list = []
            for pk_tuple in batch_pks:
                update_values = updates[pk_tuple]
                # Values for SET clause + PK values for WHERE clause
                params = tuple(update_values[col] for col in columns_to_update) + pk_tuple
                params_list.append(params)
            
            # Execute batch update within transaction
            try:
                with self.connection_manager.transaction_context() as conn:
                    cursor = conn.cursor()
                    cursor.executemany(query, params_list)
                    updated_count = cursor.rowcount
                    cursor.close()
                
                rows_updated += updated_count
                
                self.logger.debug(
                    f"Batch {batch_number} updated {updated_count} rows",
                    extra={
                        "correlation_id": correlation_id,
                        "batch_number": batch_number,
                        "updated_count": updated_count,
                        "rows_updated": rows_updated,
                        "total_rows": total_rows,
                    }
                )
                
                yield UpdateBatch(
                    updated_count=updated_count,
                    batch_number=batch_number,
                    rows_updated=rows_updated,
                    total_rows=total_rows,
                    schema_name=schema_name,
                    table_name=table_name,
                    columns_updated=columns_to_update,
                    strategy=UpdateStrategy.COMPOSITE_KEY,
                )
                
            except Exception as e:
                self.logger.error(
                    f"Failed to update batch {batch_number}",
                    extra={
                        "correlation_id": correlation_id,
                        "batch_number": batch_number,
                        "error": str(e),
                    }
                )
                raise DataUpdateError.batch_update_failed(
                    table_name=f"{schema_name}.{table_name}",
                    batch_number=batch_number,
                    reason=str(e)
                ) from e
    
    @retry_on_deadlock(max_attempts=3, backoff_factor=0.5)
    def _update_row_number(
        self,
        schema_name: str,
        table_name: str,
        pk_columns: List[str],
        columns_to_update: List[str],
        updates: Dict[Any, Dict[str, Any]],
        correlation_id: str,
    ) -> Iterator[UpdateBatch]:
        """
        Update rows using ROW_NUMBER strategy (fallback for non-numeric or no PK).
        
        This is the slowest strategy but works for all table structures.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            pk_columns: List of primary key column names (may be empty)
            columns_to_update: List of columns to update
            updates: Dictionary mapping PK value(s) to column updates
            correlation_id: Correlation ID for logging
        
        Yields:
            UpdateBatch instances
        """
        # For ROW_NUMBER strategy, we process all updates directly
        # since we can't use efficient indexed lookups
        sorted_pk_values = sorted(updates.keys())
        total_rows = len(sorted_pk_values)
        
        batch_number = 0
        rows_updated = 0
        
        # Process in batches
        for i in range(0, total_rows, self.batch_size):
            batch_pks = sorted_pk_values[i:i + self.batch_size]
            batch_number += 1
            
            # Build parameterized update query
            # For ROW_NUMBER, we identify rows by PK if available, otherwise by all columns
            set_clause = ", ".join([f"[{col}] = ?" for col in columns_to_update])
            
            if not pk_columns:
                # Tables without PKs cannot be safely updated using this strategy
                # The updates dict is keyed by PK values, which don't exist for no-PK tables
                raise DataUpdateError.update_failed(
                    table_name=f"{schema_name}.{table_name}",
                    reason=(
                        "Cannot update table without primary key. Tables must have a primary key "
                        "or unique constraint to serve as row identifier. Consider adding a primary key "
                        "or providing a composite of all columns as identifying columns."
                    )
                )
            
            # Build WHERE clause for PK columns
            where_clause = " AND ".join([f"[{pk_col}] = ?" for pk_col in pk_columns])
            
            query = (
                f"UPDATE [{schema_name}].[{table_name}] "
                f"SET {set_clause} "
                f"WHERE {where_clause}"
            )
            
            # Prepare parameter tuples
            params_list = []
            for pk_value in batch_pks:
                update_values = updates[pk_value]
                # Build params: SET values + WHERE values (PK)
                params = tuple(update_values[col] for col in columns_to_update)
                
                # Add PK values for WHERE clause
                if isinstance(pk_value, tuple):
                    # Composite PK
                    params += pk_value
                else:
                    # Single PK
                    params += (pk_value,)
                
                params_list.append(params)
            
            # Execute batch update within transaction
            try:
                with self.connection_manager.transaction_context() as conn:
                    cursor = conn.cursor()
                    cursor.executemany(query, params_list)
                    updated_count = cursor.rowcount
                    cursor.close()
                
                rows_updated += updated_count
                
                self.logger.debug(
                    f"Batch {batch_number} updated {updated_count} rows",
                    extra={
                        "correlation_id": correlation_id,
                        "batch_number": batch_number,
                        "updated_count": updated_count,
                        "rows_updated": rows_updated,
                        "total_rows": total_rows,
                    }
                )
                
                yield UpdateBatch(
                    updated_count=updated_count,
                    batch_number=batch_number,
                    rows_updated=rows_updated,
                    total_rows=total_rows,
                    schema_name=schema_name,
                    table_name=table_name,
                    columns_updated=columns_to_update,
                    strategy=UpdateStrategy.ROW_NUMBER,
                )
                
            except Exception as e:
                self.logger.error(
                    f"Failed to update batch {batch_number}",
                    extra={
                        "correlation_id": correlation_id,
                        "batch_number": batch_number,
                        "error": str(e),
                    }
                )
                raise DataUpdateError.batch_update_failed(
                    table_name=f"{schema_name}.{table_name}",
                    batch_number=batch_number,
                    reason=str(e)
                ) from e
    
    def _validate_columns_exist(
        self,
        schema_name: str,
        table_name: str,
        columns: List[str]
    ) -> None:
        """
        Validate that all columns exist in the specified table.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            columns: List of column names to validate
        
        Raises:
            DataUpdateError: If any column does not exist
        """
        db_name = self.connection_manager.config.database
        schema_metadata = self.schema_extractor.extract_schema(db_name)
        
        # Find the table in metadata
        table_found = False
        table_columns = set()
        
        for table_info in schema_metadata.get("tables", []):
            if table_info.get("schema") == schema_name and table_info.get("name") == table_name:
                table_found = True
                table_columns = {col["name"] for col in table_info.get("columns", [])}
                break
        
        if not table_found:
            raise DataUpdateError.update_failed(
                table_name=f"{schema_name}.{table_name}",
                reason="Table not found in schema metadata"
            )
        
        # Check each column
        for column in columns:
            if column not in table_columns:
                raise DataUpdateError.invalid_update_data(
                    field=column,
                    value="N/A",
                    reason=f"Column does not exist in table [{schema_name}].[{table_name}]"
                )
    
    def _validate_pk_columns(
        self,
        schema_name: str,
        table_name: str,
        pk_columns: List[str]
    ) -> None:
        """
        Validate that primary key columns are valid.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            pk_columns: List of primary key column names
        
        Raises:
            DataUpdateError: If PK columns are invalid
        """
        if not pk_columns:
            self.logger.warning(
                f"No primary key columns provided for [{schema_name}].[{table_name}]. "
                f"Updates may be slow."
            )
            return
        
        # Validate PK columns exist (reuse column validation)
        self._validate_columns_exist(schema_name, table_name, pk_columns)
    
    def _get_computed_columns(self, schema_name: str, table_name: str) -> List[str]:
        """
        Get list of computed columns for a table.
        
        Computed columns are read-only and generated by SQL Server expressions.
        They cannot be updated and must be excluded from UPDATE statements.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
        
        Returns:
            List of computed column names
        
        Example:
            >>> computed = updater._get_computed_columns("dbo", "Employees")
            >>> # ["FullName", "Age"]  # WHERE FullName AS FirstName + ' ' + LastName
        """
        query = """
            SELECT c.name
            FROM sys.computed_columns c
            INNER JOIN sys.tables t ON c.object_id = t.object_id
            INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE s.name = ? AND t.name = ?
            ORDER BY c.name
        """
        
        try:
            results = self.connection_manager.execute_query(
                query,
                params=(schema_name, table_name),
                fetch= True
            )
            
            computed_columns = [row[0] for row in (results or [])]
            
            if computed_columns:
                self.logger.debug(
                    f"Found {len(computed_columns)} computed columns in [{schema_name}].[{table_name}]",
                    computed_columns=computed_columns
                )
            
            return computed_columns
            
        except Exception as e:
            self.logger.warning(
                f"Failed to query computed columns for [{schema_name}].[{table_name}]: {e}"
            )
            return []
    
    def _get_triggers(self, schema_name: str, table_name: str) -> List[Dict[str, str]]:
        """
        Get list of triggers on a table.
        
        Triggers may modify data during updates. This method identifies triggers
        so we can log warnings about potential side effects.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
        
        Returns:
            List of dictionaries with trigger metadata:
            - name: Trigger name
            - type: Trigger type (e.g., 'AFTER UPDATE', 'INSTEAD OF UPDATE')
            - is_disabled: Whether trigger is disabled
        
        Example:
            >>> triggers = updater._get_triggers("dbo", "Orders")
            >>> # [{"name": "trg_UpdateOrderStatus", "type": "AFTER UPDATE", "is_disabled": False}]
        """
        query = """
            SELECT 
                tr.name,
                CASE 
                    WHEN tr.is_instead_of_trigger = 1 THEN 'INSTEAD OF ' + 
                        CASE 
                            WHEN OBJECTPROPERTY(tr.object_id, 'ExecIsUpdateTrigger') = 1 THEN 'UPDATE'
                            WHEN OBJECTPROPERTY(tr.object_id, 'ExecIsInsertTrigger') = 1 THEN 'INSERT'
                            WHEN OBJECTPROPERTY(tr.object_id, 'ExecIsDeleteTrigger') = 1 THEN 'DELETE'
                            ELSE 'UNKNOWN'
                        END
                    ELSE 'AFTER ' + 
                        CASE 
                            WHEN OBJECTPROPERTY(tr.object_id, 'ExecIsUpdateTrigger') = 1 THEN 'UPDATE'
                            WHEN OBJECTPROPERTY(tr.object_id, 'ExecIsInsertTrigger') = 1 THEN 'INSERT'
                            WHEN OBJECTPROPERTY(tr.object_id, 'ExecIsDeleteTrigger') = 1 THEN 'DELETE'
                            ELSE 'UNKNOWN'
                        END
                END AS trigger_type,
                tr.is_disabled
            FROM sys.triggers tr
            INNER JOIN sys.tables t ON tr.parent_id = t.object_id
            INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE s.name = ? 
                AND t.name = ?
                AND OBJECTPROPERTY(tr.object_id, 'ExecIsUpdateTrigger') = 1
            ORDER BY tr.name
        """
        
        try:
            results = self.connection_manager.execute_query(
                query,
                params=(schema_name, table_name),
                fetch=True
            )
            
            triggers = [
                {
                    "name": row[0],
                    "type": row[1],
                    "is_disabled": bool(row[2])
                }
                for row in (results or [])
            ]
            
            if triggers:
                active_triggers = [t for t in triggers if not t["is_disabled"]]
                if active_triggers:
                    self.logger.warning(
                        f"Table [{schema_name}].[{table_name}] has {len(active_triggers)} active UPDATE triggers. "
                        f"Trigger logic may modify updated values or cause side effects.",
                        triggers=[t["name"] for t in active_triggers]
                    )
            
            return triggers
            
        except Exception as e:
            self.logger.warning(
                f"Failed to query triggers for [{schema_name}].[{table_name}]: {e}"
            )
            return []
    
    def _check_constraints_and_warnings(
        self,
        schema_name: str,
        table_name: str,
        columns_to_update: List[str]
    ) -> List[str]:
        """
        Check for computed columns and triggers, log warnings, and filter update columns.
        
        This method integrates computed column detection and trigger warnings to ensure
        safe updates that don't attempt to modify read-only columns.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            columns_to_update: Original list of columns to update
        
        Returns:
            Filtered list of columns (computed columns removed)
        
        Side Effects:
            - Logs warnings for computed columns (skipped)
            - Logs warnings for active triggers (potential side effects)
        """
        # Check for computed columns
        computed_cols = self._get_computed_columns(schema_name, table_name)
        
        # Filter out computed columns from update list
        filtered_columns = [col for col in columns_to_update if col not in computed_cols]
        
        # Log warning if computed columns were removed
        removed_cols = set(columns_to_update) - set(filtered_columns)
        if removed_cols:
            self.logger.warning(
                f"Skipping {len(removed_cols)} computed column(s) in [{schema_name}].[{table_name}] - "
                f"computed columns are read-only and cannot be updated",
                computed_columns=list(removed_cols)
            )
        
        # Check for triggers (just log warnings, don't block)
        self._get_triggers(schema_name, table_name)
        
        return filtered_columns
