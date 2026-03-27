"""
Batch data extraction from SQL Server tables with intelligent pagination.

This module provides memory-efficient batch extraction of PII data from SQL Server tables
using optimal pagination strategies based on primary key structure. Supports tables with
millions of rows without memory overflow.

Key Features:
    - Key-based pagination (O(log n)) for single numeric primary keys
    - Composite key pagination for multi-column primary keys
    - ROW_NUMBER fallback for tables without suitable primary keys
    - Memory-efficient iterator pattern (yields batches, never loads all data)
    - Progress tracking with row counts
    - Comprehensive error handling and retry logic
    - Proper SQL identifier escaping for special characters

Author: Database Sanitization Team
Date: 2026-03-26
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Tuple
import time

from .connection_manager import DatabaseConnectionManager
from .schema_extractor import SchemaExtractor
from ..exceptions import (
    DataExtractionError,
    DatabaseConnectionError,
    DatabaseQueryError,
)
from ..logging.logger import get_logger
from ..logging.correlation import CorrelationContext


class PaginationStrategy(Enum):
    """Pagination strategy selection based on primary key structure."""
    
    KEY_BASED = "key_based"           # Single numeric PK - O(log n) performance
    COMPOSITE_KEY = "composite_key"    # Multi-column PK - tuple comparison
    ROW_NUMBER = "row_number"         # No suitable PK - OFFSET/FETCH fallback


@dataclass
class Batch:
    """
    Represents a single batch of extracted data.
    
    Attributes:
        rows: List of dictionaries containing column:value pairs for each row
        batch_number: Sequential batch number (1-indexed)
        total_rows_in_batch: Number of rows in this specific batch
        rows_processed: Cumulative rows processed so far (including this batch)
        total_rows: Total rows in the table
        schema_name: Database schema name
        table_name: Table name
        columns: List of column names extracted
        strategy: Pagination strategy used for extraction
    """
    
    rows: List[Dict[str, Any]]
    batch_number: int
    total_rows_in_batch: int
    rows_processed: int
    total_rows: int
    schema_name: str
    table_name: str
    columns: List[str]
    strategy: PaginationStrategy
    
    @property
    def progress_percentage(self) -> float:
        """
        Calculate completion percentage.
        
        Returns:
            Progress as percentage (0.0 to 100.0), or 0.0 if total_rows is 0
        """
        if self.total_rows == 0:
            return 0.0
        return (self.rows_processed / self.total_rows) * 100.0
    
    @property
    def is_last_batch(self) -> bool:
        """Check if this is the final batch."""
        return self.rows_processed >= self.total_rows
    
    @property
    def full_table_name(self) -> str:
        """Get fully qualified table name."""
        return f"{self.schema_name}.{self.table_name}"


class BatchExtractor:
    """
    Extract PII data in batches from SQL Server tables using optimal pagination.
    
    This class automatically selects the best pagination strategy based on primary key
    structure, supports progress tracking, and handles edge cases like empty tables,
    special characters in identifiers, and connection failures.
    
    Attributes:
        connection_manager: DatabaseConnectionManager for query execution
        schema_extractor: SchemaExtractor for metadata retrieval
        batch_size: Number of rows per batch (default: 10,000)
        max_batch_size: Maximum allowed batch size (default: 100,000)
        logger: Logger with context for operation tracking
    
    Example:
        >>> from src.database import DatabaseConnectionManager, SchemaExtractor, BatchExtractor
        >>> conn_mgr = DatabaseConnectionManager(config)
        >>> schema_ext = SchemaExtractor(conn_mgr)
        >>> extractor = BatchExtractor(conn_mgr, schema_ext, batch_size=10000)
        >>> 
        >>> for batch in extractor.extract_batches("dbo", "Customers", ["Email", "Phone"]):
        ...     print(f"Batch {batch.batch_number}: {batch.total_rows_in_batch} rows "
        ...           f"({batch.progress_percentage:.1f}% complete)")
        ...     # Process batch.rows here
    """
    
    def __init__(
        self,
        connection_manager: DatabaseConnectionManager,
        schema_extractor: SchemaExtractor,
        batch_size: int = 10000,
        logger: Optional[Any] = None,
    ) -> None:
        """
        Initialize the BatchExtractor.
        
        Args:
            connection_manager: DatabaseConnectionManager instance for query execution
            schema_extractor: SchemaExtractor instance for metadata retrieval
            batch_size: Number of rows per batch (default: 10,000)
            logger: Optional logger with context (will create if not provided)
        
        Raises:
            DataExtractionError: If batch_size is invalid (< 1 or > 100,000)
        """
        if batch_size < 1 or batch_size > 100000:
            raise DataExtractionError.invalid_batch_size(batch_size)
        
        self.connection_manager = connection_manager
        self.schema_extractor = schema_extractor
        self.batch_size = batch_size
        self.max_batch_size = 100000
        self.logger = logger or get_logger(__name__).with_context(module="batch_extractor")
    
    def extract_batches(
        self,
        schema_name: str,
        table_name: str,
        columns: List[str],
        pk_columns: Optional[List[str]] = None,
    ) -> Iterator[Batch]:
        """
        Extract data in batches using optimal pagination strategy.
        
        This method automatically detects primary keys (if not provided), selects the
        best pagination strategy, and yields batches efficiently without loading the
        entire table into memory.
        
        Args:
            schema_name: Database schema name (e.g., "dbo", "custom_schema")
            table_name: Table name
            columns: List of column names to extract (PII columns)
            pk_columns: Optional list of PK column names (auto-detected if not provided)
        
        Yields:
            Batch objects containing rows and progress metadata
        
        Raises:
            DataExtractionError: If table/columns not found or extraction fails
            DatabaseConnectionError: If connection fails
            DatabaseQueryError: If queries fail
        
        Example:
            >>> for batch in extractor.extract_batches("dbo", "Users", ["Email", "SSN"]):
            ...     for row in batch.rows:
            ...         masked_email = mask_email(row['Email'])
            ...         # Update database with masked value
        """
        full_table_name = f"[{schema_name}].[{table_name}]"
        
        with CorrelationContext() as correlation_id:
            self.logger.info(
                f"Starting batch extraction from {full_table_name}",
                extra={
                    "correlation_id": correlation_id,
                    "schema": schema_name,
                    "table": table_name,
                    "columns": columns,
                    "batch_size": self.batch_size,
                }
            )
            
            # Get total row count for progress tracking
            total_rows = self._get_row_count(schema_name, table_name)
            
            if total_rows == 0:
                self.logger.info(
                    f"Table {full_table_name} is empty, no data to extract",
                    extra={"correlation_id": correlation_id}
                )
                return  # Yield nothing for empty tables
            
            self.logger.info(
                f"Table {full_table_name} contains {total_rows:,} rows",
                extra={"correlation_id": correlation_id, "total_rows": total_rows}
            )
            
            # Get or detect primary key columns
            if pk_columns is None:
                pk_columns = self._get_primary_key_columns(schema_name, table_name)
            
            # Validate that requested columns exist
            self._validate_columns_exist(schema_name, table_name, columns)
            
            # Select pagination strategy based on PK structure
            strategy = self._select_pagination_strategy(schema_name, table_name, pk_columns)
            
            self.logger.info(
                f"Using {strategy.value} pagination strategy for {full_table_name}",
                extra={
                    "correlation_id": correlation_id,
                    "strategy": strategy.value,
                    "pk_columns": pk_columns,
                }
            )
            
            # Execute appropriate extraction strategy
            if strategy == PaginationStrategy.KEY_BASED:
                yield from self._extract_key_based(
                    schema_name, table_name, columns, pk_columns[0], total_rows, correlation_id
                )
            elif strategy == PaginationStrategy.COMPOSITE_KEY:
                yield from self._extract_composite_key(
                    schema_name, table_name, columns, pk_columns, total_rows, correlation_id
                )
            else:  # ROW_NUMBER
                yield from self._extract_row_number(
                    schema_name, table_name, columns, total_rows, correlation_id
                )
            
            self.logger.info(
                f"Completed batch extraction from {full_table_name}",
                extra={"correlation_id": correlation_id, "total_rows": total_rows}
            )
    
    def _get_row_count(self, schema_name: str, table_name: str) -> int:
        """
        Get total row count for a table.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
        
        Returns:
            Total number of rows in the table
        
        Raises:
            DataExtractionError: If query fails or table doesn't exist
        """
        query = f"SELECT COUNT(*) AS row_count FROM [{schema_name}].[{table_name}]"
        
        try:
            result = self.connection_manager.execute_query(query)
            if result and len(result) > 0:
                return result[0][0]  # First row, first column
            return 0
        except DatabaseQueryError as e:
            # Check if table doesn't exist
            if "invalid object name" in str(e).lower():
                raise DataExtractionError.table_not_found(schema_name, table_name)
            raise DataExtractionError.extraction_failed(
                f"{schema_name}.{table_name}",
                reason=f"Failed to get row count: {str(e)}"
            )
        except Exception as e:
            raise DataExtractionError.extraction_failed(
                f"{schema_name}.{table_name}",
                reason=f"Failed to get row count: {str(e)}"
            )
    
    def _get_primary_key_columns(self, schema_name: str, table_name: str) -> List[str]:
        """
        Extract primary key column names from schema metadata.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
        
        Returns:
            List of primary key column names (empty list if no PK)
        
        Raises:
            DataExtractionError: If schema extraction fails
        """
        try:
            # Get database name from connection manager
            db_name = self.connection_manager.config.database
            schema_metadata = self.schema_extractor.extract_schema(db_name)
            
            # Look up table in metadata
            tables = schema_metadata.get("tables", [])
            
            # Find matching table
            for table_info in tables:
                if table_info.get("schema") == schema_name and table_info.get("name") == table_name:
                    # Extract PK columns from primary_keys metadata
                    pk_data = table_info.get("primary_key")
                    if pk_data and "columns" in pk_data:
                        return pk_data["columns"]
                    return []  # No PK found
            
            # Table not found in metadata
            raise DataExtractionError.table_not_found(schema_name, table_name)
        
        except DataExtractionError:
            raise  # Re-raise our custom exceptions
        except Exception as e:
            raise DataExtractionError.extraction_failed(
                f"{schema_name}.{table_name}",
                reason=f"Failed to get primary key columns: {str(e)}"
            )
    
    def _validate_columns_exist(
        self,
        schema_name: str,
        table_name: str,
        columns: List[str]
    ) -> None:
        """
        Validate that all requested columns exist in the table.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            columns: List of column names to validate
        
        Raises:
            DataExtractionError: If any column doesn't exist
        """
        try:
            db_name = self.connection_manager.config.database
            schema_metadata = self.schema_extractor.extract_schema(db_name)
            
            tables = schema_metadata.get("tables", [])
            
            # Find matching table
            for table_info in tables:
                if table_info.get("schema") == schema_name and table_info.get("name") == table_name:
                    # Get list of existing columns
                    existing_columns = {col["name"] for col in table_info.get("columns", [])}
                    
                    # Check each requested column
                    for col in columns:
                        if col not in existing_columns:
                            raise DataExtractionError.column_not_found(schema_name, table_name, col)
                    return  # All columns exist
            
            # Table not found
            raise DataExtractionError.table_not_found(schema_name, table_name)
        
        except DataExtractionError:
            raise  # Re-raise our custom exceptions
        except Exception as e:
            raise DataExtractionError.extraction_failed(
                f"{schema_name}.{table_name}",
                reason=f"Failed to validate columns: {str(e)}"
            )
    
    def _select_pagination_strategy(
        self,
        schema_name: str,
        table_name: str,
        pk_columns: List[str]
    ) -> PaginationStrategy:
        """
        Determine optimal pagination strategy based on primary key structure.
        
        Strategy selection logic:
        - Single numeric PK (INT, BIGINT, SMALLINT, TINYINT) → KEY_BASED (fastest)
        - Multi-column PK (any types) → COMPOSITE_KEY
        - No PK, GUID, or string PK → ROW_NUMBER (slowest fallback)
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            pk_columns: List of primary key column names
        
        Returns:
            Selected pagination strategy
        """
        # No PK or empty PK list → ROW_NUMBER
        if not pk_columns or len(pk_columns) == 0:
            self.logger.warning(
                f"No primary key found for {schema_name}.{table_name}, "
                "using ROW_NUMBER (slower pagination)"
            )
            return PaginationStrategy.ROW_NUMBER
        
        # Multiple PK columns → COMPOSITE_KEY
        if len(pk_columns) > 1:
            if len(pk_columns) > 4:
                self.logger.warning(
                    f"Table {schema_name}.{table_name} has {len(pk_columns)} PK columns. "
                    "Consider limiting to 4 or fewer for better performance."
                )
            return PaginationStrategy.COMPOSITE_KEY
        
        # Single PK → check if numeric for KEY_BASED
        try:
            db_name = self.connection_manager.config.database
            schema_metadata = self.schema_extractor.extract_schema(db_name)
            
            tables = schema_metadata.get("tables", [])
            for table_info in tables:
                if table_info.get("schema") == schema_name and table_info.get("name") == table_name:
                    columns = table_info.get("columns", [])
                    pk_col_name = pk_columns[0]
                    
                    # Find PK column metadata
                    for col in columns:
                        if col["name"] == pk_col_name:
                            data_type = col["data_type"].upper()
                            
                            # Check if numeric type suitable for key-based pagination
                            numeric_types = {"INT", "BIGINT", "SMALLINT", "TINYINT"}
                            if data_type in numeric_types:
                                return PaginationStrategy.KEY_BASED
                            else:
                                self.logger.info(
                                    f"PK column '{pk_col_name}' has type '{data_type}', "
                                    "using ROW_NUMBER pagination"
                                )
                                return PaginationStrategy.ROW_NUMBER
            
            # Column not found in metadata (shouldn't happen)
            return PaginationStrategy.ROW_NUMBER
        
        except Exception as e:
            self.logger.warning(
                f"Failed to determine PK data type for {schema_name}.{table_name}: {str(e)}. "
                "Defaulting to ROW_NUMBER pagination."
            )
            return PaginationStrategy.ROW_NUMBER
    
    def _extract_key_based(
        self,
        schema_name: str,
        table_name: str,
        columns: List[str],
        pk_column: str,
        total_rows: int,
        correlation_id: str,
    ) -> Iterator[Batch]:
        """
        Extract data using key-based pagination (WHERE pk > @last_pk).
        
        This is the fastest pagination method with O(log n) complexity per batch
        due to index seeks on the primary key.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            columns: List of column names to extract
            pk_column: Primary key column name
            total_rows: Total rows in table (for progress tracking)
            correlation_id: Correlation ID for logging
        
        Yields:
            Batch objects containing extracted data
        """
        # Build column list including PK
        all_columns = [pk_column] + [col for col in columns if col != pk_column]
        column_list = ", ".join(f"[{col}]" for col in all_columns)
        
        last_pk_value = None
        batch_number = 0
        rows_processed = 0
        
        while rows_processed < total_rows:
            batch_number += 1
            
            # Build query with WHERE clause for subsequent batches
            if last_pk_value is None:
                # First batch
                query = (
                    f"SELECT {column_list} "
                    f"FROM [{schema_name}].[{table_name}] "
                    f"ORDER BY [{pk_column}] "
                    f"OFFSET 0 ROWS FETCH NEXT {self.batch_size} ROWS ONLY"
                )
                params = ()
            else:
                # Subsequent batches using last PK value
                query = (
                    f"SELECT {column_list} "
                    f"FROM [{schema_name}].[{table_name}] "
                    f"WHERE [{pk_column}] > ? "
                    f"ORDER BY [{pk_column}] "
                    f"OFFSET 0 ROWS FETCH NEXT {self.batch_size} ROWS ONLY"
                )
                params = (last_pk_value,)
            
            try:
                # Execute query with retry logic (built into connection_manager)
                result = self.connection_manager.execute_query(query, params)
                
                if not result:
                    break  # No more rows
                
                # Convert rows to dictionaries
                rows = []
                for row in result:
                    row_dict = {all_columns[i]: row[i] for i in range(len(all_columns))}
                    rows.append(row_dict)
                
                # Update last PK value for next batch
                if rows:
                    last_pk_value = rows[-1][pk_column]
                
                rows_processed += len(rows)
                
                # Create and yield batch
                batch = Batch(
                    rows=rows,
                    batch_number=batch_number,
                    total_rows_in_batch=len(rows),
                    rows_processed=rows_processed,
                    total_rows=total_rows,
                    schema_name=schema_name,
                    table_name=table_name,
                    columns=columns,
                    strategy=PaginationStrategy.KEY_BASED,
                )
                
                self.logger.debug(
                    f"Extracted batch {batch_number}: {len(rows)} rows "
                    f"({batch.progress_percentage:.1f}% complete)",
                    extra={"correlation_id": correlation_id, "batch_number": batch_number}
                )
                
                yield batch
                
                # If we got fewer rows than batch_size, we're done
                if len(rows) < self.batch_size:
                    break
            
            except Exception as e:
                raise DataExtractionError.extraction_failed(
                    f"{schema_name}.{table_name}",
                    reason=f"Batch {batch_number} failed: {str(e)}",
                    batch_number=batch_number,
                )
    
    def _extract_composite_key(
        self,
        schema_name: str,
        table_name: str,
        columns: List[str],
        pk_columns: List[str],
        total_rows: int,
        correlation_id: str,
    ) -> Iterator[Batch]:
        """
        Extract data using composite key pagination with tuple comparison.
        
        Handles multi-column primary keys using WHERE clause with tuple comparison:
        WHERE (pk1 > @last_pk1) OR (pk1 = @last_pk1 AND pk2 > @last_pk2) OR ...
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            columns: List of column names to extract
            pk_columns: List of primary key column names (ordered)
            total_rows: Total rows in table (for progress tracking)
            correlation_id: Correlation ID for logging
        
        Yields:
            Batch objects containing extracted data
        """
        # Build column list including all PK columns
        all_columns = pk_columns + [col for col in columns if col not in pk_columns]
        column_list = ", ".join(f"[{col}]" for col in all_columns)
        order_by = ", ".join(f"[{col}]" for col in pk_columns)
        
        last_pk_values: Optional[Tuple] = None
        batch_number = 0
        rows_processed = 0
        
        while rows_processed < total_rows:
            batch_number += 1
            
            # Build query
            if last_pk_values is None:
                # First batch
                query = (
                    f"SELECT {column_list} "
                    f"FROM [{schema_name}].[{table_name}] "
                    f"ORDER BY {order_by} "
                    f"OFFSET 0 ROWS FETCH NEXT {self.batch_size} ROWS ONLY"
                )
                params = ()
            else:
                # Build tuple comparison WHERE clause
                # (pk1 > ?) OR (pk1 = ? AND pk2 > ?) OR (pk1 = ? AND pk2 = ? AND pk3 > ?) ...
                where_parts = []
                param_values = []
                
                for i in range(len(pk_columns)):
                    conditions = []
                    # Add equality conditions for all previous columns
                    for j in range(i):
                        conditions.append(f"[{pk_columns[j]}] = ?")
                        param_values.append(last_pk_values[j])
                    # Add greater-than condition for current column
                    conditions.append(f"[{pk_columns[i]}] > ?")
                    param_values.append(last_pk_values[i])
                    
                    where_parts.append("(" + " AND ".join(conditions) + ")")
                
                where_clause = " OR ".join(where_parts)
                
                query = (
                    f"SELECT {column_list} "
                    f"FROM [{schema_name}].[{table_name}] "
                    f"WHERE {where_clause} "
                    f"ORDER BY {order_by} "
                    f"OFFSET 0 ROWS FETCH NEXT {self.batch_size} ROWS ONLY"
                )
                params = tuple(param_values)
            
            try:
                result = self.connection_manager.execute_query(query, params)
                
                if not result:
                    break  # No more rows
                
                # Convert rows to dictionaries
                rows = []
                for row in result:
                    row_dict = {all_columns[i]: row[i] for i in range(len(all_columns))}
                    rows.append(row_dict)
                
                # Update last PK values for next batch
                if rows:
                    last_pk_values = tuple(rows[-1][col] for col in pk_columns)
                
                rows_processed += len(rows)
                
                # Create and yield batch
                batch = Batch(
                    rows=rows,
                    batch_number=batch_number,
                    total_rows_in_batch=len(rows),
                    rows_processed=rows_processed,
                    total_rows=total_rows,
                    schema_name=schema_name,
                    table_name=table_name,
                    columns=columns,
                    strategy=PaginationStrategy.COMPOSITE_KEY,
                )
                
                self.logger.debug(
                    f"Extracted batch {batch_number}: {len(rows)} rows "
                    f"({batch.progress_percentage:.1f}% complete)",
                    extra={"correlation_id": correlation_id, "batch_number": batch_number}
                )
                
                yield batch
                
                # If we got fewer rows than batch_size, we're done
                if len(rows) < self.batch_size:
                    break
            
            except Exception as e:
                raise DataExtractionError.extraction_failed(
                    f"{schema_name}.{table_name}",
                    reason=f"Batch {batch_number} failed: {str(e)}",
                    batch_number=batch_number,
                )
    
    def _extract_row_number(
        self,
        schema_name: str,
        table_name: str,
        columns: List[str],
        total_rows: int,
        correlation_id: str,
    ) -> Iterator[Batch]:
        """
        Extract data using ROW_NUMBER with OFFSET/FETCH (fallback strategy).
        
        This is the slowest pagination method with O(n) complexity as it requires
        scanning through rows. Used when no suitable primary key exists (GUID, string PK,
        or no PK at all).
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            columns: List of column names to extract
            total_rows: Total rows in table (for progress tracking)
            correlation_id: Correlation ID for logging
        
        Yields:
            Batch objects containing extracted data
        """
        column_list = ", ".join(f"[{col}]" for col in columns)
        
        batch_number = 0
        offset = 0
        
        while offset < total_rows:
            batch_number += 1
            
            # Build OFFSET/FETCH query
            query = (
                f"SELECT {column_list} "
                f"FROM [{schema_name}].[{table_name}] "
                f"ORDER BY (SELECT NULL) "  # No specific order
                f"OFFSET {offset} ROWS FETCH NEXT {self.batch_size} ROWS ONLY"
            )
            
            try:
                result = self.connection_manager.execute_query(query)
                
                if not result:
                    break  # No more rows
                
                # Convert rows to dictionaries
                rows = []
                for row in result:
                    row_dict = {columns[i]: row[i] for i in range(len(columns))}
                    rows.append(row_dict)
                
                offset += len(rows)
                
                # Create and yield batch
                batch = Batch(
                    rows=rows,
                    batch_number=batch_number,
                    total_rows_in_batch=len(rows),
                    rows_processed=offset,
                    total_rows=total_rows,
                    schema_name=schema_name,
                    table_name=table_name,
                    columns=columns,
                    strategy=PaginationStrategy.ROW_NUMBER,
                )
                
                self.logger.debug(
                    f"Extracted batch {batch_number}: {len(rows)} rows "
                    f"({batch.progress_percentage:.1f}% complete)",
                    extra={"correlation_id": correlation_id, "batch_number": batch_number}
                )
                
                yield batch
                
                # If we got fewer rows than batch_size, we're done
                if len(rows) < self.batch_size:
                    break
            
            except Exception as e:
                raise DataExtractionError.extraction_failed(
                    f"{schema_name}.{table_name}",
                    reason=f"Batch {batch_number} failed: {str(e)}",
                    batch_number=batch_number,
                )
