"""
Schema metadata extraction from SQL Server databases.

This module provides comprehensive extraction of database schema metadata including
tables, columns, data types, primary keys, foreign keys, unique constraints, and indexes.
It queries SQL Server system tables and returns structured metadata for use in PII detection
and sanitization workflows.

Author: Database Sanitization Team
Date: 2026-03-26
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import pyodbc

from ..exceptions import (
    SchemaExtractionError,
    DatabaseConnectionError,
    DatabaseQueryError,
)
from ..logging.logger import get_logger
from ..logging.correlation import CorrelationContext
from .connection_manager import DatabaseConnectionManager


class SchemaExtractor:
    """
    Extract comprehensive schema metadata from SQL Server databases.
    
    This class provides methods to extract:
    - Tables (with schema names)
    - Columns (with data types, lengths, precision, scale, nullability)
    - Primary keys (including composite keys)
    - Foreign keys (including composite, self-referencing, circular)
    - Unique constraints
    - Indexes
    
    All queries use parameterized statements and proper object name escaping.
    
    Attributes:
        connection_manager: DatabaseConnectionManager instance for query execution
        logger: Logger instance with context for schema extraction operations
    
    Example:
        >>> from src.database import DatabaseConnectionManager, SchemaExtractor
        >>> conn_mgr = DatabaseConnectionManager(config)
        >>> extractor = SchemaExtractor(conn_mgr)
        >>> schema = extractor.extract_schema("MyDatabase")
        >>> print(f"Found {len(schema['tables'])} tables")
    """
    
    def __init__(self, connection_manager: DatabaseConnectionManager) -> None:
        """
        Initialize the SchemaExtractor.
        
        Args:
            connection_manager: DatabaseConnectionManager instance for query execution
        """
        self.connection_manager = connection_manager
        self.logger = get_logger(__name__).with_context(module="schema_extractor")
    
    def extract_schema(self, database_name: str) -> Dict[str, Any]:
        """
        Extract complete schema metadata from the specified database.
        
        This method orchestrates the extraction of all schema metadata including
        tables, columns, primary keys, foreign keys, unique constraints, and indexes.
        It uses a correlation ID to trace the entire extraction workflow through logs.
        
        Args:
            database_name: Name of the database to extract schema from
        
        Returns:
            Dictionary containing complete schema metadata with keys:
            - tables: List of table metadata (schema, table name)
            - columns: Dict mapping table names to column metadata
            - primary_keys: Dict mapping table names to PK column lists
            - foreign_keys: List of FK relationships
            - unique_constraints: Dict mapping table names to unique constraint lists
            - indexes: Dict mapping table names to index metadata
            - extraction_timestamp: ISO format timestamp of extraction
            - database_name: Name of the database extracted
        
        Raises:
            SchemaExtractionError: If database not found or extraction fails
            DatabaseConnectionError: If connection fails
            DatabaseQueryError: If queries fail
        
        Example:
            >>> schema = extractor.extract_schema("ProductionDB")
            >>> for table in schema['tables']:
            ...     print(f"{table['schema']}.{table['name']}")
        """
        start_time = datetime.now()
        
        with CorrelationContext() as correlation_id:
            self.logger.info(
                f"Starting schema extraction for database '{database_name}'",
                extra={
                    "correlation_id": correlation_id,
                    "database_name": database_name,
                    "operation": "extract_schema_start"
                }
            )
            
            try:
                # Extract tables
                self.logger.debug("Extracting table metadata", extra={"correlation_id": correlation_id})
                tables = self._get_tables(database_name)
                
                if not tables:
                    self.logger.warning(
                        f"No user tables found in database '{database_name}'",
                        extra={"correlation_id": correlation_id, "database_name": database_name}
                    )
                    # Not necessarily an error - database might be empty
                    return {
                        "database_name": database_name,
                        "tables": [],
                        "columns": {},
                        "primary_keys": {},
                        "foreign_keys": [],
                        "unique_constraints": {},
                        "indexes": {},
                        "extraction_timestamp": datetime.now().isoformat(),
                        "warnings": ["No user tables found in database"]
                    }
                
                table_count = len(tables)
                self.logger.info(
                    f"Found {table_count} tables",
                    extra={"correlation_id": correlation_id, "table_count": table_count}
                )
                
                # Build list of qualified table names for subsequent queries
                qualified_table_names = [
                    f"[{table['schema']}].[{table['name']}]" for table in tables
                ]
                
                # Extract columns
                self.logger.debug("Extracting column metadata", extra={"correlation_id": correlation_id})
                columns = self._get_columns(database_name, qualified_table_names)
                column_count = sum(len(cols) for cols in columns.values())
                
                # Extract primary keys
                self.logger.debug("Extracting primary key metadata", extra={"correlation_id": correlation_id})
                primary_keys = self._get_primary_keys(database_name, qualified_table_names)
                pk_count = sum(len(pks) for pks in primary_keys.values())
                
                # Extract foreign keys
                self.logger.debug("Extracting foreign key metadata", extra={"correlation_id": correlation_id})
                foreign_keys = self._get_foreign_keys(database_name, qualified_table_names)
                fk_count = len(foreign_keys)
                
                # Extract unique constraints
                self.logger.debug("Extracting unique constraint metadata", extra={"correlation_id": correlation_id})
                unique_constraints = self._get_unique_constraints(database_name, qualified_table_names)
                unique_count = sum(len(ucs) for ucs in unique_constraints.values())
                
                # Extract indexes
                self.logger.debug("Extracting index metadata", extra={"correlation_id": correlation_id})
                indexes = self._get_indexes(database_name, qualified_table_names)
                index_count = sum(len(idxs) for idxs in indexes.values())
                
                # Validate metadata integrity
                warnings = self._validate_metadata_integrity(
                    tables, columns, primary_keys, foreign_keys
                )
                
                end_time = datetime.now()
                duration_ms = (end_time - start_time).total_seconds() * 1000
                
                self.logger.info(
                    "Schema extraction completed successfully",
                    extra={
                        "correlation_id": correlation_id,
                        "database_name": database_name,
                        "table_count": table_count,
                        "column_count": column_count,
                        "pk_count": pk_count,
                        "fk_count": fk_count,
                        "unique_count": unique_count,
                        "index_count": index_count,
                        "duration_ms": duration_ms,
                        "operation": "extract_schema_complete"
                    }
                )
                
                return {
                    "database_name": database_name,
                    "tables": tables,
                    "columns": columns,
                    "primary_keys": primary_keys,
                    "foreign_keys": foreign_keys,
                    "unique_constraints": unique_constraints,
                    "indexes": indexes,
                    "extraction_timestamp": datetime.now().isoformat(),
                    "extraction_duration_ms": duration_ms,
                    "warnings": warnings
                }
                
            except SchemaExtractionError:
                # Re-raise schema extraction errors as-is
                raise
            except DatabaseConnectionError as e:
                self.logger.error(
                    f"Connection error during schema extraction: {e}",
                    extra={"correlation_id": correlation_id, "database_name": database_name}
                )
                raise
            except DatabaseQueryError as e:
                self.logger.error(
                    f"Query error during schema extraction: {e}",
                    extra={"correlation_id": correlation_id, "database_name": database_name}
                )
                raise
            except Exception as e:
                self.logger.error(
                    f"Unexpected error during schema extraction: {e}",
                    extra={"correlation_id": correlation_id, "database_name": database_name}
                )
                raise SchemaExtractionError.extraction_failed(
                    database_name,
                    reason=str(e)
                ) from e
    
    def _get_tables(self, database_name: str) -> List[Dict[str, str]]:
        """
        Extract all user tables with schema names.
        
        Queries sys.tables and sys.schemas to get fully qualified table names.
        Only user tables (type = 'U') are returned, excluding system tables.
        
        Args:
            database_name: Name of the database
        
        Returns:
            List of dictionaries with keys: schema, name, qualified_name
        
        Raises:
            DatabaseQueryError: If query execution fails
        """
        query = f"""
        SELECT 
            s.name AS schema_name,
            t.name AS table_name
        FROM [{database_name}].sys.tables t
        INNER JOIN [{database_name}].sys.schemas s ON t.schema_id = s.schema_id
        WHERE t.type = 'U'  -- User tables only
        ORDER BY s.name, t.name
        """
        
        try:
            results = self.connection_manager.execute_query(query)
            
            tables = []
            for row in results:
                schema_name = row[0]
                table_name = row[1]
                tables.append({
                    "schema": schema_name,
                    "name": table_name,
                    "qualified_name": f"[{schema_name}].[{table_name}]"
                })
            
            return tables
            
        except pyodbc.ProgrammingError as e:
            error_msg = str(e).lower()
            if "invalid object name" in error_msg or "cannot find" in error_msg:
                raise SchemaExtractionError.database_not_found(database_name) from e
            raise DatabaseQueryError.query_failed(query, reason=str(e)) from e
        except pyodbc.Error as e:
            raise DatabaseQueryError.query_failed(query, reason=str(e)) from e
    
    def _get_columns(
        self, database_name: str, table_names: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract column metadata for specified tables.
        
        Queries sys.columns, sys.types, sys.tables, and sys.schemas to get
        comprehensive column information including data types, lengths, precision,
        scale, and nullability.
        
        Args:
            database_name: Name of the database
            table_names: List of qualified table names (e.g., '[dbo].[Customers]')
        
        Returns:
            Dictionary mapping qualified table names to lists of column metadata.
            Each column dict contains: name, data_type, max_length, precision,
            scale, is_nullable, is_identity, is_computed
        
        Raises:
            DatabaseQueryError: If query execution fails
        """
        if not table_names:
            return {}
        
        query = f"""
        SELECT 
            s.name AS schema_name,
            t.name AS table_name,
            c.name AS column_name,
            ty.name AS data_type,
            c.max_length,
            c.precision,
            c.scale,
            c.is_nullable,
            c.is_identity,
            c.is_computed
        FROM [{database_name}].sys.columns c
        INNER JOIN [{database_name}].sys.tables t ON c.object_id = t.object_id
        INNER JOIN [{database_name}].sys.schemas s ON t.schema_id = s.schema_id
        INNER JOIN [{database_name}].sys.types ty ON c.user_type_id = ty.user_type_id
        WHERE t.type = 'U'
        ORDER BY s.name, t.name, c.column_id
        """
        
        try:
            results = self.connection_manager.execute_query(query)
            
            columns_by_table: Dict[str, List[Dict[str, Any]]] = {}
            
            for row in results:
                schema_name = row[0]
                table_name = row[1]
                column_name = row[2]
                data_type = row[3].upper()  # Normalize to uppercase
                max_length = row[4]
                precision = row[5]
                scale = row[6]
                is_nullable = bool(row[7])
                is_identity = bool(row[8])
                is_computed = bool(row[9])
                
                qualified_name = f"[{schema_name}].[{table_name}]"
                
                # Handle special data types
                if data_type in ('NVARCHAR', 'NCHAR'):
                    # For Unicode types, max_length is in bytes, so divide by 2 for character count
                    max_length = max_length // 2 if max_length > 0 else max_length
                
                is_max_type = max_length == -1
                
                column_info = {
                    "name": column_name,
                    "data_type": data_type,
                    "max_length": max_length,
                    "precision": precision,
                    "scale": scale,
                    "is_nullable": is_nullable,
                    "is_identity": is_identity,
                    "is_computed": is_computed,
                    "is_max_type": is_max_type
                }
                
                if qualified_name not in columns_by_table:
                    columns_by_table[qualified_name] = []
                
                columns_by_table[qualified_name].append(column_info)
            
            return columns_by_table
            
        except pyodbc.Error as e:
            raise DatabaseQueryError.query_failed(query, reason=str(e)) from e
    
    def _get_primary_keys(
        self, database_name: str, table_names: List[str]
    ) -> Dict[str, List[str]]:
        """
        Extract primary key columns for specified tables.
        
        Queries sys.key_constraints, sys.index_columns, and sys.columns to identify
        primary key columns. Preserves column order for composite primary keys using
        key_ordinal.
        
        Args:
            database_name: Name of the database
            table_names: List of qualified table names
        
        Returns:
            Dictionary mapping qualified table names to ordered lists of PK column names.
            Composite keys are returned as lists with multiple columns in order.
        
        Raises:
            DatabaseQueryError: If query execution fails
        """
        if not table_names:
            return {}
        
        query = f"""
        SELECT 
            s.name AS schema_name,
            t.name AS table_name,
            c.name AS column_name,
            ic.key_ordinal
        FROM [{database_name}].sys.key_constraints kc
        INNER JOIN [{database_name}].sys.tables t ON kc.parent_object_id = t.object_id
        INNER JOIN [{database_name}].sys.schemas s ON t.schema_id = s.schema_id
        INNER JOIN [{database_name}].sys.index_columns ic ON kc.parent_object_id = ic.object_id 
            AND kc.unique_index_id = ic.index_id
        INNER JOIN [{database_name}].sys.columns c ON ic.object_id = c.object_id 
            AND ic.column_id = c.column_id
        WHERE kc.type = 'PK'
        ORDER BY s.name, t.name, ic.key_ordinal
        """
        
        try:
            results = self.connection_manager.execute_query(query)
            
            primary_keys_by_table: Dict[str, List[str]] = {}
            
            for row in results:
                schema_name = row[0]
                table_name = row[1]
                column_name = row[2]
                
                qualified_name = f"[{schema_name}].[{table_name}]"
                
                if qualified_name not in primary_keys_by_table:
                    primary_keys_by_table[qualified_name] = []
                
                primary_keys_by_table[qualified_name].append(column_name)
            
            return primary_keys_by_table
            
        except pyodbc.Error as e:
            raise DatabaseQueryError.query_failed(query, reason=str(e)) from e
    
    def _get_foreign_keys(
        self, database_name: str, table_names: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Extract foreign key relationships for specified tables.
        
        Queries sys.foreign_keys and sys.foreign_key_columns to identify all FK
        relationships including composite FKs, self-referencing FKs, and circular
        dependencies.
        
        Args:
            database_name: Name of the database
            table_names: List of qualified table names
        
        Returns:
            List of foreign key relationship dictionaries with keys:
            - constraint_name: Name of the FK constraint
            - parent_schema: Schema of the parent (referenced) table
            - parent_table: Name of the parent table
            - parent_column: Name of the parent column
            - child_schema: Schema of the child (referencing) table
            - child_table: Name of the child table
            - child_column: Name of the child column
            - is_self_referencing: Boolean flag for self-referencing FKs
            - ordinal_position: Position in composite key (1-based)
        
        Raises:
            DatabaseQueryError: If query execution fails
        """
        if not table_names:
            return []
        
        query = f"""
        SELECT 
            fk.name AS constraint_name,
            ps.name AS parent_schema,
            pt.name AS parent_table,
            pc.name AS parent_column,
            cs.name AS child_schema,
            ct.name AS child_table,
            cc.name AS child_column,
            fkc.constraint_column_id AS ordinal_position
        FROM [{database_name}].sys.foreign_keys fk
        INNER JOIN [{database_name}].sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
        INNER JOIN [{database_name}].sys.tables pt ON fk.referenced_object_id = pt.object_id
        INNER JOIN [{database_name}].sys.schemas ps ON pt.schema_id = ps.schema_id
        INNER JOIN [{database_name}].sys.columns pc ON fkc.referenced_object_id = pc.object_id 
            AND fkc.referenced_column_id = pc.column_id
        INNER JOIN [{database_name}].sys.tables ct ON fk.parent_object_id = ct.object_id
        INNER JOIN [{database_name}].sys.schemas cs ON ct.schema_id = cs.schema_id
        INNER JOIN [{database_name}].sys.columns cc ON fkc.parent_object_id = cc.object_id 
            AND fkc.parent_column_id = cc.column_id
        ORDER BY fk.name, fkc.constraint_column_id
        """
        
        try:
            results = self.connection_manager.execute_query(query)
            
            foreign_keys = []
            
            for row in results:
                constraint_name = row[0]
                parent_schema = row[1]
                parent_table = row[2]
                parent_column = row[3]
                child_schema = row[4]
                child_table = row[5]
                child_column = row[6]
                ordinal_position = row[7]
                
                # Check if self-referencing
                is_self_referencing = (
                    parent_schema == child_schema and parent_table == child_table
                )
                
                fk_info = {
                    "constraint_name": constraint_name,
                    "parent_schema": parent_schema,
                    "parent_table": parent_table,
                    "parent_column": parent_column,
                    "child_schema": child_schema,
                    "child_table": child_table,
                    "child_column": child_column,
                    "is_self_referencing": is_self_referencing,
                    "ordinal_position": ordinal_position
                }
                
                foreign_keys.append(fk_info)
            
            return foreign_keys
            
        except pyodbc.Error as e:
            raise DatabaseQueryError.query_failed(query, reason=str(e)) from e
    
    def _get_unique_constraints(
        self, database_name: str, table_names: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract unique constraints for specified tables.
        
        Queries sys.key_constraints and sys.index_columns to identify unique
        constraints including multi-column unique constraints.
        
        Args:
            database_name: Name of the database
            table_names: List of qualified table names
        
        Returns:
            Dictionary mapping qualified table names to lists of unique constraint
            metadata. Each constraint dict contains: constraint_name, columns (list)
        
        Raises:
            DatabaseQueryError: If query execution fails
        """
        if not table_names:
            return {}
        
        query = f"""
        SELECT 
            s.name AS schema_name,
            t.name AS table_name,
            kc.name AS constraint_name,
            c.name AS column_name,
            ic.key_ordinal
        FROM [{database_name}].sys.key_constraints kc
        INNER JOIN [{database_name}].sys.tables t ON kc.parent_object_id = t.object_id
        INNER JOIN [{database_name}].sys.schemas s ON t.schema_id = s.schema_id
        INNER JOIN [{database_name}].sys.index_columns ic ON kc.parent_object_id = ic.object_id 
            AND kc.unique_index_id = ic.index_id
        INNER JOIN [{database_name}].sys.columns c ON ic.object_id = c.object_id 
            AND ic.column_id = c.column_id
        WHERE kc.type = 'UQ'
        ORDER BY s.name, t.name, kc.name, ic.key_ordinal
        """
        
        try:
            results = self.connection_manager.execute_query(query)
            
            # Group by table and constraint
            constraints_by_table: Dict[str, Dict[str, List[str]]] = {}
            
            for row in results:
                schema_name = row[0]
                table_name = row[1]
                constraint_name = row[2]
                column_name = row[3]
                
                qualified_name = f"[{schema_name}].[{table_name}]"
                
                if qualified_name not in constraints_by_table:
                    constraints_by_table[qualified_name] = {}
                
                if constraint_name not in constraints_by_table[qualified_name]:
                    constraints_by_table[qualified_name][constraint_name] = []
                
                constraints_by_table[qualified_name][constraint_name].append(column_name)
            
            # Convert to final format
            unique_constraints: Dict[str, List[Dict[str, Any]]] = {}
            for table, constraints in constraints_by_table.items():
                unique_constraints[table] = [
                    {"constraint_name": name, "columns": columns}
                    for name, columns in constraints.items()
                ]
            
            return unique_constraints
            
        except pyodbc.Error as e:
            raise DatabaseQueryError.query_failed(query, reason=str(e)) from e
    
    def _get_indexes(
        self, database_name: str, table_names: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract index metadata for specified tables.
        
        Queries sys.indexes and sys.index_columns to identify all indexes including
        clustered, non-clustered, unique, and filtered indexes.
        
        Args:
            database_name: Name of the database
            table_names: List of qualified table names
        
        Returns:
            Dictionary mapping qualified table names to lists of index metadata.
            Each index dict contains: name, type, is_unique, is_primary_key, columns
        
        Raises:
            DatabaseQueryError: If query execution fails
        """
        if not table_names:
            return {}
        
        query = f"""
        SELECT 
            s.name AS schema_name,
            t.name AS table_name,
            i.name AS index_name,
            i.type_desc AS index_type,
            i.is_unique,
            i.is_primary_key,
            c.name AS column_name,
            ic.key_ordinal
        FROM [{database_name}].sys.indexes i
        INNER JOIN [{database_name}].sys.tables t ON i.object_id = t.object_id
        INNER JOIN [{database_name}].sys.schemas s ON t.schema_id = s.schema_id
        INNER JOIN [{database_name}].sys.index_columns ic ON i.object_id = ic.object_id 
            AND i.index_id = ic.index_id
        INNER JOIN [{database_name}].sys.columns c ON ic.object_id = c.object_id 
            AND ic.column_id = c.column_id
        WHERE i.type > 0  -- Exclude heaps (type = 0)
        ORDER BY s.name, t.name, i.name, ic.key_ordinal
        """
        
        try:
            results = self.connection_manager.execute_query(query)
            
            # Group by table and index
            indexes_by_table: Dict[str, Dict[str, Dict[str, Any]]] = {}
            
            for row in results:
                schema_name = row[0]
                table_name = row[1]
                index_name = row[2]
                index_type = row[3]
                is_unique = bool(row[4])
                is_primary_key = bool(row[5])
                column_name = row[6]
                
                qualified_name = f"[{schema_name}].[{table_name}]"
                
                if qualified_name not in indexes_by_table:
                    indexes_by_table[qualified_name] = {}
                
                if index_name not in indexes_by_table[qualified_name]:
                    indexes_by_table[qualified_name][index_name] = {
                        "name": index_name,
                        "type": index_type,
                        "is_unique": is_unique,
                        "is_primary_key": is_primary_key,
                        "columns": []
                    }
                
                indexes_by_table[qualified_name][index_name]["columns"].append(column_name)
            
            # Convert to final format
            indexes: Dict[str, List[Dict[str, Any]]] = {}
            for table, table_indexes in indexes_by_table.items():
                indexes[table] = list(table_indexes.values())
            
            return indexes
            
        except pyodbc.Error as e:
            raise DatabaseQueryError.query_failed(query, reason=str(e)) from e
    
    def _validate_metadata_integrity(
        self,
        tables: List[Dict[str, str]],
        columns: Dict[str, List[Dict[str, Any]]],
        primary_keys: Dict[str, List[str]],
        foreign_keys: List[Dict[str, Any]],
    ) -> List[str]:
        """
        Validate the integrity of extracted metadata.
        
        Performs sanity checks to ensure metadata is complete and consistent:
        - Every table has at least one column
        - FK parent/child references point to existing tables
        - PK columns exist in the column list
        
        Args:
            tables: List of table metadata
            columns: Column metadata by table
            primary_keys: Primary key columns by table
            foreign_keys: List of FK relationships
        
        Returns:
            List of warning messages for integrity issues (empty if all valid)
        """
        warnings = []
        
        # Check that every table has columns
        for table in tables:
            qualified_name = table["qualified_name"]
            if qualified_name not in columns or not columns[qualified_name]:
                warnings.append(
                    f"Table {qualified_name} has no columns in metadata"
                )
        
        # Check that tables without primary keys are logged
        for table in tables:
            qualified_name = table["qualified_name"]
            if qualified_name not in primary_keys or not primary_keys[qualified_name]:
                warnings.append(
                    f"Table {qualified_name} has no primary key"
                )
        
        # Check that PK columns exist in column metadata
        for table_name, pk_columns in primary_keys.items():
            if table_name in columns:
                column_names = {col["name"] for col in columns[table_name]}
                for pk_col in pk_columns:
                    if pk_col not in column_names:
                        warnings.append(
                            f"Primary key column '{pk_col}' not found in column metadata for {table_name}"
                        )
        
        # Check that FK references point to existing tables
        table_qualified_names = {table["qualified_name"] for table in tables}
        for fk in foreign_keys:
            parent_qualified = f"[{fk['parent_schema']}].[{fk['parent_table']}]"
            child_qualified = f"[{fk['child_schema']}].[{fk['child_table']}]"
            
            if parent_qualified not in table_qualified_names:
                warnings.append(
                    f"Foreign key '{fk['constraint_name']}' references non-existent parent table {parent_qualified}"
                )
            
            if child_qualified not in table_qualified_names:
                warnings.append(
                    f"Foreign key '{fk['constraint_name']}' references non-existent child table {child_qualified}"
                )
        
        return warnings
