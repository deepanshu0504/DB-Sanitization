"""
Test helper utilities for database sanitization unit tests.

Provides:
- MockCursor class with query tracking and result simulation
- Connection mock builders
- Fake data generators (deterministic)
- Edge case data generators (Unicode, long strings, special characters)
- SQL assertion helpers
- Test data builders

Author: Database Sanitization Team
Date: 2026-03-27
"""

from typing import List, Dict, Any, Optional, Tuple, Callable
from unittest.mock import Mock, MagicMock
from datetime import datetime, date
from decimal import Decimal
import random
import string


# ============================================================================
# MOCK CURSOR CLASS
# ============================================================================

class MockCursor:
    """
    Enhanced mock cursor with query tracking and configurable results.
    
    Features:
    - Tracks all executed queries and parameters
    - Configurable fetchone/fetchall/fetchmany results
    - Simulates rowcount and description
    - Context manager support
    - Side effect simulation (exceptions, delays)
    
    Usage:
        cursor = MockCursor()
        cursor.set_results([('John', 30), ('Jane', 25)])
        cursor.execute("SELECT name, age FROM users")
        assert cursor.fetchall() == [('John', 30), ('Jane', 25)]
        assert len(cursor.executed_queries) == 1
    """
    
    def __init__(self):
        self.executed_queries: List[Tuple[str, Optional[tuple]]] = []
        self._results: List[tuple] = []
        self._current_index: int = 0
        self._description: Optional[List[tuple]] = None
        self._rowcount: int = 0
        self._side_effect: Optional[Callable] = None
        self.closed: bool = False
    
    def set_results(self, results: List[tuple],
                    description: Optional[List[tuple]] = None):
        """
        Set results to return from fetch methods.
        
        Args:
            results: List of tuples to return
            description: Optional cursor.description (column metadata)
        """
        self._results = results
        self._current_index = 0
        self._rowcount = len(results)
        self._description = description
    
    def set_side_effect(self, side_effect: Callable):
        """
        Set side effect function to call on execute().
        
        Args:
            side_effect: Function to call (can raise exceptions)
        
        Usage:
            cursor.set_side_effect(lambda q, p: raise_database_error())
        """
        self._side_effect = side_effect
    
    def execute(self, query: str, params: Optional[tuple] = None):
        """Execute a query and track it."""
        if self.closed:
            raise Exception("Cannot execute on closed cursor")
        
        self.executed_queries.append((query, params))
        
        if self._side_effect:
            self._side_effect(query, params)
        
        self._current_index = 0
        return self
    
    def executemany(self, query: str, param_list: List[tuple]):
        """Execute a query multiple times with different parameters."""
        if self.closed:
            raise Exception("Cannot execute on closed cursor")
        
        for params in param_list:
            self.executed_queries.append((query, params))
        
        return self
    
    def fetchone(self) -> Optional[tuple]:
        """Fetch one row."""
        if self._current_index < len(self._results):
            result = self._results[self._current_index]
            self._current_index += 1
            return result
        return None
    
    def fetchall(self) -> List[tuple]:
        """Fetch all remaining rows."""
        results = self._results[self._current_index:]
        self._current_index = len(self._results)
        return results
    
    def fetchmany(self, size: int = 1) -> List[tuple]:
        """Fetch multiple rows."""
        end_index = min(self._current_index + size, len(self._results))
        results = self._results[self._current_index:end_index]
        self._current_index = end_index
        return results
    
    @property
    def rowcount(self) -> int:
        """Number of rows affected by last query."""
        return self._rowcount
    
    @property
    def description(self) -> Optional[List[tuple]]:
        """Column metadata."""
        return self._description
    
    def close(self):
        """Close the cursor."""
        self.closed = True
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
    
    def get_last_query(self) -> Optional[Tuple[str, Optional[tuple]]]:
        """Get the last executed query and parameters."""
        return self.executed_queries[-1] if self.executed_queries else None
    
    def assert_query_contains(self, substring: str):
        """Assert that the last query contains a substring."""
        last_query = self.get_last_query()
        if not last_query:
            raise AssertionError("No queries executed")
        query_text = last_query[0]
        if substring.lower() not in query_text.lower():
            raise AssertionError(
                f"Query does not contain '{substring}'.\nQuery: {query_text}"
            )
    
    def assert_query_count(self, expected_count: int):
        """Assert the number of queries executed."""
        actual_count = len(self.executed_queries)
        if actual_count != expected_count:
            raise AssertionError(
                f"Expected {expected_count} queries, got {actual_count}.\n"
                f"Queries: {self.executed_queries}"
            )


# ============================================================================
# CONNECTION MOCK BUILDERS
# ============================================================================

def create_mock_connection(cursor: Optional[MockCursor] = None) -> MagicMock:
    """
    Create a mock database connection with optional cursor.
    
    Args:
        cursor: Optional MockCursor to return from connection.cursor()
    
    Returns:
        Configured MagicMock connection
    
    Usage:
        cursor = MockCursor()
        cursor.set_results([('result',)])
        conn = create_mock_connection(cursor)
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
    """
    if cursor is None:
        cursor = MockCursor()
    
    connection = MagicMock()
    connection.cursor = Mock(return_value=cursor)
    connection.commit = Mock()
    connection.rollback = Mock()
    connection.close = Mock()
    connection.autocommit = False
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    
    return connection


def create_mock_connection_manager(connection: Optional[MagicMock] = None) -> Mock:
    """
    Create a mock DatabaseConnectionManager.
    
    Args:
        connection: Optional mock connection to return
    
    Returns:
        Mock DatabaseConnectionManager
    
    Usage:
        cursor = MockCursor()
        cursor.set_results([('data',)])
        conn = create_mock_connection(cursor)
        manager = create_mock_connection_manager(conn)
        with manager.get_connection() as c:
            assert c == conn
    """
    from src.database.connection_manager import DatabaseConnectionManager
    
    if connection is None:
        connection = create_mock_connection()
    
    manager = Mock(spec=DatabaseConnectionManager)
    manager.get_connection = Mock()
    manager.get_connection.return_value.__enter__ = Mock(return_value=connection)
    manager.get_connection.return_value.__exit__ = Mock(return_value=False)
    
    return manager


# ============================================================================
# FAKE DATA GENERATORS
# ============================================================================

class FakeDataGenerator:
    """
    Deterministic fake data generator for testing.
    
    Uses fixed seeds for reproducible test data.
    """
    
    def __init__(self, seed: int = 42):
        """Initialize with seed for deterministic output."""
        self.seed = seed
        self._rng = random.Random(seed)
    
    def email(self, length: int = 20) -> str:
        """Generate a fake email address."""
        username_length = max(5, length - 15)  # Reserve space for @domain.com
        username = self._random_string(username_length)
        return f"{username}@example.com"
    
    def name(self, length: int = 10) -> str:
        """Generate a fake name."""
        return self._random_name(length)
    
    def phone(self, format_style: str = "us") -> str:
        """Generate a fake phone number."""
        if format_style == "us":
            return f"{self._random_digits(3)}-{self._random_digits(3)}-{self._random_digits(4)}"
        elif format_style == "us_parens":
            return f"({self._random_digits(3)}) {self._random_digits(3)}-{self._random_digits(4)}"
        elif format_style == "international":
            return f"+1-{self._random_digits(3)}-{self._random_digits(3)}-{self._random_digits(4)}"
        else:
            return self._random_digits(10)
    
    def ssn(self) -> str:
        """Generate a fake SSN."""
        return f"{self._random_digits(3)}-{self._random_digits(2)}-{self._random_digits(4)}"
    
    def _random_string(self, length: int) -> str:
        """Generate random lowercase string."""
        return ''.join(self._rng.choices(string.ascii_lowercase, k=length))
    
    def _random_name(self, length: int) -> str:
        """Generate random name-like string (capitalized)."""
        return ''.join(self._rng.choices(string.ascii_lowercase, k=length)).capitalize()
    
    def _random_digits(self, count: int) -> str:
        """Generate random digit string."""
        return ''.join(self._rng.choices(string.digits, k=count))


# ============================================================================
# EDGE CASE GENERATORS
# ============================================================================

def generate_unicode_strings() -> Dict[str, str]:
    """
    Generate Unicode test strings covering various character sets.
    
    Returns:
        Dict with keys: chinese, arabic, emoji, mixed, cyrillic, etc.
    """
    return {
        "chinese": "李明 (Lǐ Míng)",
        "arabic": "محمد أحمد (Muhammad Ahmad)",
        "emoji": "John 😀 Doe 🎉",
        "mixed": "José María O'Brien-Smith Ñoño",
        "cyrillic": "Александр Иванов",
        "greek": "Αλέξανδρος Παπαδόπουλος",
        "hebrew": "דוד כהן",
        "korean": "김철수",
        "thai": "สมชาย ใจดี",
        "vietnamese": "Nguyễn Văn An",
        "japanese": "山田太郎 (Yamada Tarō)",
        "hindi": "राज कुमार (Raj Kumar)"
    }


def generate_special_character_strings() -> Dict[str, str]:
    """
    Generate strings with special characters for edge case testing.
    
    Returns:
        Dict with keys: sql_injection, quotes, backslashes, etc.
    """
    return {
        "sql_injection": "'; DROP TABLE Users--",
        "single_quotes": "O'Brien's Restaurant",
        "double_quotes": 'The "Best" Product',
        "backslashes": r"C:\Users\Test\File.txt",
        "newlines": "Line1\nLine2\nLine3",
        "tabs": "Column1\tColumn2\tColumn3",
        "null_bytes": "Test\x00Data",
        "control_chars": "Test\x01\x02\x03Data",
        "html_entities": "<script>alert('XSS')</script>",
        "unicode_escape": "Test\\u0041\\u0042\\u0043"
    }


def generate_long_strings() -> Dict[str, str]:
    """
    Generate long strings for length constraint testing.
    
    Returns:
        Dict with keys: varchar_255, varchar_max, text_64kb, etc.
    """
    return {
        "varchar_50": "A" * 50,
        "varchar_255": "B" * 255,
        "varchar_500": "C" * 500,
        "varchar_1000": "D" * 1000,
        "varchar_4000": "E" * 4000,
        "varchar_8000": "F" * 8000,
        "varchar_max": "G" * 10000,
        "text_64kb": "H" * 65536
    }


def generate_edge_numbers() -> Dict[str, Any]:
    """
    Generate edge case numbers for numeric testing.
    
    Returns:
        Dict with keys: int_min, int_max, decimal_precision, etc.
    """
    return {
        "int_min": -2147483648,
        "int_max": 2147483647,
        "bigint_min": -9223372036854775808,
        "bigint_max": 9223372036854775807,
        "zero": 0,
        "negative_one": -1,
        "decimal_precision": Decimal("123456789.123456789"),
        "decimal_large": Decimal("999999999999999999.99"),
        "decimal_small": Decimal("0.00000000001"),
        "float_infinity": float('inf'),
        "float_neg_infinity": float('-inf'),
        "float_nan": float('nan')
    }


def generate_edge_dates() -> Dict[str, Any]:
    """
    Generate edge case dates for date/datetime testing.
    
    Returns:
        Dict with keys: min_date, max_date, y2k, leap_year, etc.
    """
    return {
        "min_date": date(1753, 1, 1),  # SQL Server minimum
        "max_date": date(9999, 12, 31),  # SQL Server maximum
        "y2k": date(2000, 1, 1),
        "leap_year": date(2024, 2, 29),
        "epoch": date(1970, 1, 1),
        "today": date.today(),
        "null_date": None,
        "min_datetime": datetime(1753, 1, 1, 0, 0, 0),
        "max_datetime": datetime(9999, 12, 31, 23, 59, 59)
    }


# ============================================================================
# SQL ASSERTION HELPERS
# ============================================================================

def assert_sql_contains(query: str, *substrings: str):
    """
    Assert that a SQL query contains all specified substrings (case-insensitive).
    
    Args:
        query: SQL query string
        substrings: Substrings to search for
    
    Raises:
        AssertionError: If any substring not found
    
    Usage:
        assert_sql_contains(query, "SELECT", "FROM Users", "WHERE email")
    """
    query_lower = query.lower()
    for substring in substrings:
        if substring.lower() not in query_lower:
            raise AssertionError(
                f"SQL query does not contain '{substring}'.\nQuery: {query}"
            )


def assert_sql_not_contains(query: str, *substrings: str):
    """
    Assert that a SQL query does NOT contain any specified substrings.
    
    Args:
        query: SQL query string
        substrings: Substrings to check absence of
    
    Raises:
        AssertionError: If any substring found
    """
    query_lower = query.lower()
    for substring in substrings:
        if substring.lower() in query_lower:
            raise AssertionError(
                f"SQL query should not contain '{substring}'.\nQuery: {query}"
            )


def assert_parameterized_query(query: str):
    """
    Assert that a SQL query uses parameterized queries (no string concatenation).
    
    Args:
        query: SQL query string
    
    Raises:
        AssertionError: If query appears to use string interpolation
    """
    # Check for common SQL injection patterns
    dangerous_patterns = ["' +", "+ '", "format(", "%s" % ", "f'{", "f\"{"]
    query_lower = query.lower()
    
    for pattern in dangerous_patterns:
        if pattern in query_lower:
            raise AssertionError(
                f"Query may use string concatenation: '{pattern}' found.\n"
                f"Use parameterized queries instead.\nQuery: {query}"
            )


# ============================================================================
# TEST DATA BUILDERS
# ============================================================================

def build_column_info(
    name: str = "test_column",
    data_type: str = "VARCHAR(255)",
    max_length: int = 255,
    is_nullable: bool = True,
    is_identity: bool = False,
    is_computed: bool = False
) -> Dict[str, Any]:
    """
    Build a column info dictionary for testing.
    
    Args:
        name: Column name
        data_type: SQL data type
        max_length: Maximum length for string types
        is_nullable: Whether column allows NULLs
        is_identity: Whether column is identity/autoincrement
        is_computed: Whether column is computed
    
    Returns:
        Column info dictionary
    """
    return {
        "column_name": name,
        "data_type": data_type,
        "max_length": max_length,
        "is_nullable": is_nullable,
        "is_identity": is_identity,
        "is_computed": is_computed
    }


def build_fk_metadata(
    fk_table: str,
    fk_columns: List[str],
    pk_table: str,
    pk_columns: List[str],
    fk_schema: str = "dbo",
    pk_schema: str = "dbo",
    constraint_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Build foreign key metadata dictionary for testing.
    
    Args:
        fk_table: Foreign key table name
        fk_columns: Foreign key column names
        pk_table: Primary key table name
        pk_columns: Primary key column names
        fk_schema: Foreign key table schema
        pk_schema: Primary key table schema
        constraint_name: Constraint name (auto-generated if None)
    
    Returns:
        FK metadata dictionary
    """
    if constraint_name is None:
        constraint_name = f"FK_{fk_table}_{pk_table}"
    
    return {
        "fk_table_schema": fk_schema,
        "fk_table": fk_table,
        "fk_columns": fk_columns,
        "pk_table_schema": pk_schema,
        "pk_table": pk_table,
        "pk_columns": pk_columns,
        "constraint_name": constraint_name
    }
