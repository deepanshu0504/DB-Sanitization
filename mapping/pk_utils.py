"""
Primary key detection utilities for database sanitization.

This module provides functions to detect and work with primary keys across
different tables to enable row-specific restoration during desanitization.

Key Features:
    - Detect primary key columns for any table
    - Handle composite primary keys
    - Extract primary key values from result rows
    - Generate SQL fragments for PK-based filtering

Author: Database Sanitization Team
Date: 2026-04-16
"""

import pyodbc
import json
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass


@dataclass
class PrimaryKeyInfo:
    """
    Information about a table's primary key.
    
    Attributes:
        schema_name: Database schema name
        table_name: Table name
        pk_columns: List of primary key column names (ordered)
        is_composite: True if PK has multiple columns
    """
    schema_name: str
    table_name: str
    pk_columns: List[str]
    is_composite: bool = False
    
    def __post_init__(self):
        """Set composite flag based on column count."""
        self.is_composite = len(self.pk_columns) > 1
    
    def to_json(self) -> str:
        """Convert PK columns to JSON string."""
        return json.dumps(self.pk_columns)
    
    @staticmethod
    def from_json(json_str: str) -> List[str]:
        """Parse PK columns from JSON string."""
        return json.loads(json_str) if json_str else []


def get_primary_key_columns(
    connection_string: str,
    schema_name: str,
    table_name: str
) -> Optional[PrimaryKeyInfo]:
    """
    Detect primary key columns for a table.
    
    Args:
        connection_string: Database connection string
        schema_name: Schema name
        table_name: Table name
    
    Returns:
        PrimaryKeyInfo object or None if no PK exists
    
    Example:
        ```python
        pk_info = get_primary_key_columns(
            conn_string,
            "Person",
            "Person"
        )
        if pk_info:
            print(f"PK columns: {pk_info.pk_columns}")
            # Output: PK columns: ['BusinessEntityID']
        ```
    """
    query = """
        SELECT 
            c.name AS column_name,
            ic.key_ordinal AS ordinal_position
        FROM sys.indexes i
        INNER JOIN sys.index_columns ic 
            ON i.object_id = ic.object_id 
            AND i.index_id = ic.index_id
        INNER JOIN sys.columns c 
            ON ic.object_id = c.object_id 
            AND ic.column_id = c.column_id
        INNER JOIN sys.tables t 
            ON i.object_id = t.object_id
        INNER JOIN sys.schemas s 
            ON t.schema_id = s.schema_id
        WHERE 
            i.is_primary_key = 1
            AND s.name = ?
            AND t.name = ?
        ORDER BY ic.key_ordinal;
    """
    
    try:
        with pyodbc.connect(connection_string) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (schema_name, table_name))
            
            pk_columns = [row.column_name for row in cursor.fetchall()]
            cursor.close()
            
            if not pk_columns:
                return None
            
            return PrimaryKeyInfo(
                schema_name=schema_name,
                table_name=table_name,
                pk_columns=pk_columns
            )
    
    except pyodbc.Error as e:
        print(f"[WARNING] Failed to detect primary key for {schema_name}.{table_name}: {e}")
        return None


def extract_pk_values(
    row: pyodbc.Row,
    pk_columns: List[str]
) -> List[Any]:
    """
    Extract primary key values from a query result row.
    
    Args:
        row: pyodbc.Row object from query result
        pk_columns: List of primary key column names
    
    Returns:
        List of PK values in the same order as pk_columns
    
    Example:
        ```python
        # For single PK
        pk_values = extract_pk_values(row, ['CustomerID'])
        # Returns: [12345]
        
        # For composite PK
        pk_values = extract_pk_values(row, ['OrderID', 'ProductID'])
        # Returns: [50123, 778]
        ```
    """
    pk_values = []
    for pk_col in pk_columns:
        try:
            value = getattr(row, pk_col)
            pk_values.append(value)
        except AttributeError:
            # Column not in result set
            raise ValueError(
                f"Primary key column '{pk_col}' not found in query result. "
                f"Ensure PK columns are included in SELECT statement."
            )
    
    return pk_values


def pk_values_to_json(pk_values: List[Any]) -> str:
    """
    Convert primary key values to JSON string for storage.
    
    Args:
        pk_values: List of PK values
    
    Returns:
        JSON string representation
    
    Example:
        ```python
        json_str = pk_values_to_json([12345])
        # Returns: "[12345]"
        
        json_str = pk_values_to_json([50123, 778])
        # Returns: "[50123, 778]"
        ```
    """
    # Convert values to JSON-serializable types
    serializable_values = []
    for val in pk_values:
        if isinstance(val, (str, int, float, bool, type(None))):
            serializable_values.append(val)
        else:
            # Convert other types to string
            serializable_values.append(str(val))
    
    return json.dumps(serializable_values)


def pk_values_from_json(json_str: str) -> List[Any]:
    """
    Parse primary key values from JSON string.
    
    Args:
        json_str: JSON string representation
    
    Returns:
        List of PK values
    """
    return json.loads(json_str) if json_str else []


def build_pk_where_clause(
    pk_columns: List[str],
    pk_values: List[Any],
    table_alias: str = "t"
) -> Tuple[str, List[Any]]:
    """
    Build WHERE clause for matching primary key.
    
    Args:
        pk_columns: List of PK column names
        pk_values: List of PK values
        table_alias: Table alias to use in WHERE clause
    
    Returns:
        Tuple of (where_clause, parameters)
    
    Example:
        ```python
        # Single PK
        where, params = build_pk_where_clause(['CustomerID'], [12345])
        # Returns: ("t.[CustomerID] = ?", [12345])
        
        # Composite PK
        where, params = build_pk_where_clause(
            ['OrderID', 'ProductID'],
            [50123, 778]
        )
        # Returns: ("t.[OrderID] = ? AND t.[ProductID] = ?", [50123, 778])
        ```
    """
    if len(pk_columns) != len(pk_values):
        raise ValueError(
            f"Mismatch between PK columns ({len(pk_columns)}) "
            f"and values ({len(pk_values)})"
        )
    
    conditions = [f"{table_alias}.[{col}] = ?" for col in pk_columns]
    where_clause = " AND ".join(conditions)
    
    return where_clause, pk_values


# Cache for primary key info to avoid repeated queries
_pk_cache: Dict[Tuple[str, str], Optional[PrimaryKeyInfo]] = {}


def get_primary_key_cached(
    connection_string: str,
    schema_name: str,
    table_name: str
) -> Optional[PrimaryKeyInfo]:
    """
    Get primary key info with caching.
    
    Caches results to avoid repeated database queries for the same table.
    
    Args:
        connection_string: Database connection string
        schema_name: Schema name
        table_name: Table name
    
    Returns:
        PrimaryKeyInfo object or None
    """
    cache_key = (schema_name, table_name)
    
    if cache_key not in _pk_cache:
        _pk_cache[cache_key] = get_primary_key_columns(
            connection_string,
            schema_name,
            table_name
        )
    
    return _pk_cache[cache_key]


def clear_pk_cache():
    """Clear the primary key info cache."""
    global _pk_cache
    _pk_cache = {}
