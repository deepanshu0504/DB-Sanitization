"""
Case-insensitive database object name normalization utilities.

This module provides utilities for handling database object names (schemas, tables, columns)
in a case-insensitive manner, ensuring compatibility with any SQL Server collation settings
or naming conventions.

Key Features:
    - Case-insensitive identifier normalization
    - Qualified name building utilities
    - CaseInsensitiveDict for transparent case-insensitive lookups
    - Comparison helpers for schema/table/column matching

Use Cases:
    - Comparing config object names with database metadata
    - Building dictionary keys for schema/table/column lookups
    - Validating PII column configurations against database schema
    - Ensuring sanitization works regardless of case differences

Author: Database Sanitization Team
Date: 2026-03-28
"""

import logging
from typing import Optional, Dict, Any, Tuple, Iterator
from collections.abc import MutableMapping

logger = logging.getLogger(__name__)


def normalize_identifier(identifier: str) -> str:
    """
    Normalize a database identifier to lowercase for case-insensitive comparison.
    
    This function handles schema names, table names, and column names uniformly,
    converting them to lowercase using Python's standard string normalization.
    
    Args:
        identifier: Database identifier (schema, table, or column name)
    
    Returns:
        Lowercase version of the identifier
    
    Raises:
        ValueError: If identifier is None or empty
    
    Examples:
        >>> normalize_identifier("Orders")
        'orders'
        >>> normalize_identifier("dbo")
        'dbo'
        >>> normalize_identifier("Email")
        'email'
        >>> normalize_identifier("UserId")
        'userid'
    
    Notes:
        - Preserves Unicode characters and properly handles non-ASCII names
        - Uses Python's .lower() which is locale-independent
        - Empty strings and None values raise ValueError for safety
    """
    if not identifier:
        raise ValueError("Identifier cannot be None or empty")
    
    if not isinstance(identifier, str):
        raise TypeError(f"Identifier must be string, got {type(identifier)}")
    
    return identifier.strip().lower()


def build_qualified_name(
    schema: str,
    table: str,
    column: Optional[str] = None,
    normalize: bool = True
) -> str:
    """
    Build a qualified database object name with optional normalization.
    
    Creates a fully qualified name in the format:
    - [schema].[table] (if column is None)
    - [schema].[table].[column] (if column provided)
    
    Args:
        schema: Database schema name
        table: Table name
        column: Optional column name
        normalize: If True, normalize to lowercase; if False, preserve case
    
    Returns:
        Qualified name string with SQL Server bracket notation
    
    Raises:
        ValueError: If schema or table is None or empty
    
    Examples:
        >>> build_qualified_name("dbo", "Orders")
        '[dbo].[orders]'
        >>> build_qualified_name("dbo", "Orders", "Email")
        '[dbo].[orders].[email]'
        >>> build_qualified_name("DBO", "Users", "ID", normalize=False)
        '[DBO].[Users].[ID]'
    
    Notes:
        - Always uses SQL Server bracket notation [...] for consistency
        - Normalization applies to all parts equally
        - Preserves original case when normalize=False for SQL generation
    """
    if not schema or not table:
        raise ValueError("Schema and table cannot be None or empty")
    
    if normalize:
        schema = normalize_identifier(schema)
        table = normalize_identifier(table)
        if column:
            column = normalize_identifier(column)
    
    if column:
        return f"[{schema}].[{table}].[{column}]"
    else:
        return f"[{schema}].[{table}]"


def build_simple_key(
    schema: str,
    table: str,
    column: Optional[str] = None,
    separator: str = ".",
    normalize: bool = True
) -> str:
    """
    Build a simple key without SQL brackets for dictionary lookups.
    
    Creates a simple dot-separated key for use as dictionary keys in
    schema metadata structures.
    
    Args:
        schema: Database schema name
        table: Table name
        column: Optional column name
        separator: Separator character (default: ".")
        normalize: If True, normalize to lowercase
    
    Returns:
        Simple key string like "schema.table" or "schema.table.column"
    
    Examples:
        >>> build_simple_key("dbo", "Orders")
        'dbo.orders'
        >>> build_simple_key("dbo", "Orders", "Email")
        'dbo.orders.email'
        >>> build_simple_key("DBO", "Users", separator="|")
        'dbo|users'
    """
    if not schema or not table:
        raise ValueError("Schema and table cannot be None or empty")
    
    if normalize:
        schema = normalize_identifier(schema)
        table = normalize_identifier(table)
        if column:
            column = normalize_identifier(column)
    
    if column:
        return f"{schema}{separator}{table}{separator}{column}"
    else:
        return f"{schema}{separator}{table}"


def parse_qualified_name(qualified_name: str) -> Tuple[str, str, Optional[str]]:
    """
    Parse a qualified name into schema, table, and optional column components.
    
    Handles both bracket notation [schema].[table].[column] and simple
    dot notation schema.table.column.
    
    Args:
        qualified_name: Qualified name string to parse
    
    Returns:
        Tuple of (schema, table, column) where column may be None
    
    Raises:
        ValueError: If qualified_name is invalid or has wrong format
    
    Examples:
        >>> parse_qualified_name("[dbo].[Orders].[Email]")
        ('dbo', 'Orders', 'Email')
        >>> parse_qualified_name("[dbo].[Orders]")
        ('dbo', 'Orders', None)
        >>> parse_qualified_name("dbo.orders.email")
        ('dbo', 'orders', 'email')
    """
    if not qualified_name:
        raise ValueError("Qualified name cannot be None or empty")
    
    # Remove brackets if present
    name = qualified_name.replace("[", "").replace("]", "")
    
    # Split by dot
    parts = name.split(".")
    
    if len(parts) == 2:
        return parts[0], parts[1], None
    elif len(parts) == 3:
        return parts[0], parts[1], parts[2]
    else:
        raise ValueError(
            f"Invalid qualified name format: {qualified_name}. "
            f"Expected 'schema.table' or 'schema.table.column'"
        )


def identifiers_match(
    identifier1: str,
    identifier2: str,
    case_sensitive: bool = False
) -> bool:
    """
    Compare two database identifiers for equality.
    
    Args:
        identifier1: First identifier to compare
        identifier2: Second identifier to compare
        case_sensitive: If True, use case-sensitive comparison
    
    Returns:
        True if identifiers match, False otherwise
    
    Examples:
        >>> identifiers_match("Orders", "orders")
        True
        >>> identifiers_match("Email", "EMAIL")
        True
        >>> identifiers_match("Orders", "Users")
        False
        >>> identifiers_match("Orders", "orders", case_sensitive=True)
        False
    """
    if identifier1 is None or identifier2 is None:
        return identifier1 == identifier2
    
    if case_sensitive:
        return identifier1 == identifier2
    else:
        return normalize_identifier(identifier1) == normalize_identifier(identifier2)


class CaseInsensitiveDict(MutableMapping):
    """
    Dictionary that performs case-insensitive key lookups while preserving original keys.
    
    This class wraps a standard dictionary and normalizes all keys to lowercase
    for lookups, while maintaining the original case in stored keys for display
    and SQL generation purposes.
    
    Attributes:
        _data: Internal dictionary storing normalized key -> (original_key, value) pairs
    
    Examples:
        >>> d = CaseInsensitiveDict()
        >>> d["Orders"] = {"count": 10}
        >>> d["orders"]  # Case-insensitive lookup
        {'count': 10}
        >>> d["ORDERS"]  # Also works
        {'count': 10}
        >>> list(d.keys())  # Original case preserved
        ['Orders']
        >>> "orders" in d
        True
        >>> "ORDERS" in d
        True
    
    Notes:
        - Preserves original key case for iteration and display
        - All lookups are case-insensitive
        - Updates with different case overwrite but preserve the new case
        - Compatible with dict() constructor and update() method
    """
    
    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """
        Initialize CaseInsensitiveDict.
        
        Args:
            data: Optional initial dictionary data
        """
        self._data: Dict[str, Tuple[str, Any]] = {}
        if data:
            self.update(data)
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Set an item with case-insensitive key storage."""
        if not isinstance(key, str):
            raise TypeError(f"Keys must be strings, got {type(key)}")
        
        normalized_key = normalize_identifier(key)
        self._data[normalized_key] = (key, value)  # Store original key and value
    
    def __getitem__(self, key: str) -> Any:
        """Get an item using case-insensitive lookup."""
        if not isinstance(key, str):
            raise TypeError(f"Keys must be strings, got {type(key)}")
        
        normalized_key = normalize_identifier(key)
        if normalized_key not in self._data:
            raise KeyError(key)
        
        _, value = self._data[normalized_key]
        return value
    
    def __delitem__(self, key: str) -> None:
        """Delete an item using case-insensitive lookup."""
        if not isinstance(key, str):
            raise TypeError(f"Keys must be strings, got {type(key)}")
        
        normalized_key = normalize_identifier(key)
        if normalized_key not in self._data:
            raise KeyError(key)
        
        del self._data[normalized_key]
    
    def __contains__(self, key: object) -> bool:
        """Check if key exists using case-insensitive lookup."""
        if not isinstance(key, str):
            return False
        
        try:
            normalized_key = normalize_identifier(key)
            return normalized_key in self._data
        except (ValueError, TypeError):
            return False
    
    def __iter__(self) -> Iterator[str]:
        """Iterate over original keys (preserves case)."""
        for original_key, _ in self._data.values():
            yield original_key
    
    def __len__(self) -> int:
        """Return number of items in dictionary."""
        return len(self._data)
    
    def __repr__(self) -> str:
        """Return string representation."""
        items = {original_key: value for original_key, value in self._data.values()}
        return f"CaseInsensitiveDict({items})"
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get value with default if key not found (case-insensitive)."""
        try:
            return self[key]
        except KeyError:
            return default
    
    def keys(self):
        """Return view of original keys."""
        return (original_key for original_key, _ in self._data.values())
    
    def values(self):
        """Return view of values."""
        return (value for _, value in self._data.values())
    
    def items(self):
        """Return view of (original_key, value) pairs."""
        return ((original_key, value) for original_key, value in self._data.values())
    
    def copy(self) -> "CaseInsensitiveDict":
        """Return shallow copy of the dictionary."""
        new_dict = CaseInsensitiveDict()
        new_dict._data = self._data.copy()
        return new_dict
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to standard dictionary with original keys."""
        return {original_key: value for original_key, value in self._data.values()}
