"""
Unit tests for SchemaInspector.

Run with: pytest tests/test_schema_inspector.py -v
"""

import os
import pytest
from typing import Generator

import pyodbc

from database.schema_inspector import SchemaInspector, PrimaryKeyInfo, SchemaInspectionError


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def test_connection_string() -> str:
    """Provide test database connection string from environment."""
    server = os.getenv("TEST_DB_SERVER", "localhost")
    database = os.getenv("TEST_DB_NAME", "SanitizationTest")
    auth_type = os.getenv("TEST_DB_AUTH", "windows")
    
    if auth_type == "windows":
        return f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};Trusted_Connection=yes;"
    else:
        username = os.getenv("TEST_DB_USER", "sa")
        password = os.getenv("TEST_DB_PASSWORD", "")
        return f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};UID={username};PWD={password};"


@pytest.fixture
def inspector(test_connection_string: str) -> SchemaInspector:
    """Provide SchemaInspector instance."""
    return SchemaInspector(test_connection_string)


@pytest.fixture
def test_db_setup(test_connection_string: str) -> Generator[pyodbc.Connection, None, None]:
    """
    Setup test database with sample tables.
    
    Creates:
    - TestTable_SinglePK: Single column primary key
    - TestTable_CompositePK: Multi-column primary key
    - TestTable_NoPK: No primary key
    """
    conn = pyodbc.connect(test_connection_string)
    cursor = conn.cursor()
    
    # Clean up any existing test tables
    cursor.execute("""
        IF OBJECT_ID('dbo.TestTable_SinglePK', 'U') IS NOT NULL 
            DROP TABLE dbo.TestTable_SinglePK
    """)
    cursor.execute("""
        IF OBJECT_ID('dbo.TestTable_CompositePK', 'U') IS NOT NULL 
            DROP TABLE dbo.TestTable_CompositePK
    """)
    cursor.execute("""
        IF OBJECT_ID('dbo.TestTable_NoPK', 'U') IS NOT NULL 
            DROP TABLE dbo.TestTable_NoPK
    """)
    conn.commit()
    
    # Create test tables
    cursor.execute("""
        CREATE TABLE dbo.TestTable_SinglePK (
            CustomerID INT PRIMARY KEY,
            Name NVARCHAR(100),
            Email NVARCHAR(255)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE dbo.TestTable_CompositePK (
            OrderID INT,
            ProductID INT,
            Quantity INT,
            PRIMARY KEY (OrderID, ProductID)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE dbo.TestTable_NoPK (
            LogID INT,
            Message NVARCHAR(500),
            Timestamp DATETIME2
        )
    """)
    
    conn.commit()
    
    yield conn
    
    # Cleanup
    cursor.execute("DROP TABLE IF EXISTS dbo.TestTable_SinglePK")
    cursor.execute("DROP TABLE IF EXISTS dbo.TestTable_CompositePK")
    cursor.execute("DROP TABLE IF EXISTS dbo.TestTable_NoPK")
    conn.commit()
    cursor.close()
    conn.close()


# ============================================================================
# PRIMARY KEY EXTRACTION TESTS
# ============================================================================

def test_single_primary_key_extraction(inspector: SchemaInspector, test_db_setup):
    """Test PK extraction for single-column primary key."""
    pk_info = inspector.get_primary_key_columns("TestTable_SinglePK", "dbo")
    
    assert pk_info.has_pk
    assert not pk_info.is_composite
    assert pk_info.pk_columns == ["CustomerID"]
    assert pk_info.table_name == "TestTable_SinglePK"
    assert pk_info.schema_name == "dbo"
    assert pk_info.qualified_name == "[dbo].[TestTable_SinglePK]"


def test_composite_primary_key_extraction(inspector: SchemaInspector, test_db_setup):
    """Test PK extraction for composite (multi-column) primary key."""
    pk_info = inspector.get_primary_key_columns("TestTable_CompositePK", "dbo")
    
    assert pk_info.has_pk
    assert pk_info.is_composite
    assert pk_info.pk_columns == ["OrderID", "ProductID"]
    assert len(pk_info.pk_columns) == 2


def test_no_primary_key(inspector: SchemaInspector, test_db_setup):
    """Test behavior when table has no primary key."""
    pk_info = inspector.get_primary_key_columns("TestTable_NoPK", "dbo")
    
    assert not pk_info.has_pk
    assert not pk_info.is_composite
    assert pk_info.pk_columns == []


def test_nonexistent_table(inspector: SchemaInspector, test_db_setup):
    """Test handling of non-existent table."""
    # Should not raise, just return empty PK info
    pk_info = inspector.get_primary_key_columns("NonExistentTable", "dbo")
    
    assert not pk_info.has_pk
    assert pk_info.pk_columns == []


def test_pk_caching(inspector: SchemaInspector, test_db_setup):
    """Test that PK information is cached for performance."""
    # First call - cache miss
    pk_info_1 = inspector.get_primary_key_columns("TestTable_SinglePK", "dbo")
    
    # Second call - cache hit (should be same object)
    pk_info_2 = inspector.get_primary_key_columns("TestTable_SinglePK", "dbo")
    
    assert pk_info_1 is pk_info_2
    assert id(pk_info_1) == id(pk_info_2)


def test_cache_clear(inspector: SchemaInspector, test_db_setup):
    """Test cache clear functionality."""
    pk_info_1 = inspector.get_primary_key_columns("TestTable_SinglePK", "dbo")
    
    inspector.clear_cache()
    
    pk_info_2 = inspector.get_primary_key_columns("TestTable_SinglePK", "dbo")
    
    # Should be different objects after cache clear
    assert pk_info_1 is not pk_info_2
    # But same content
    assert pk_info_1.pk_columns == pk_info_2.pk_columns


# ============================================================================
# SQL GENERATION TESTS
# ============================================================================

def test_build_pk_select_expression_single_pk(inspector: SchemaInspector, test_db_setup):
    """Test SELECT expression generation for single PK."""
    pk_info = inspector.get_primary_key_columns("TestTable_SinglePK", "dbo")
    select_expr = inspector.build_pk_select_expression(pk_info)
    
    assert "CAST" in select_expr
    assert "[CustomerID]" in select_expr
    assert "NVARCHAR(MAX)" in select_expr


def test_build_pk_select_expression_composite_pk(inspector: SchemaInspector, test_db_setup):
    """Test SELECT expression generation for composite PK."""
    pk_info = inspector.get_primary_key_columns("TestTable_CompositePK", "dbo")
    select_expr = inspector.build_pk_select_expression(pk_info)
    
    # Should contain JSON serialization
    assert "JSON_OBJECT" in select_expr or "{" in select_expr
    assert "OrderID" in select_expr
    assert "ProductID" in select_expr


def test_build_pk_select_expression_no_pk(inspector: SchemaInspector, test_db_setup):
    """Test SELECT expression generation for table without PK (ROW_NUMBER fallback)."""
    pk_info = inspector.get_primary_key_columns("TestTable_NoPK", "dbo")
    select_expr = inspector.build_pk_select_expression(pk_info)
    
    assert "ROW_NUMBER()" in select_expr
    assert "OVER" in select_expr


def test_build_pk_where_clause_single_pk(inspector: SchemaInspector, test_db_setup):
    """Test WHERE clause generation for single PK."""
    pk_info = inspector.get_primary_key_columns("TestTable_SinglePK", "dbo")
    where_clause = inspector.build_pk_where_clause(pk_info, "r.record_id")
    
    assert "[CustomerID]" in where_clause
    assert "r.record_id" in where_clause
    assert "=" in where_clause


def test_build_pk_where_clause_composite_pk(inspector: SchemaInspector, test_db_setup):
    """Test WHERE clause generation for composite PK."""
    pk_info = inspector.get_primary_key_columns("TestTable_CompositePK", "dbo")
    where_clause = inspector.build_pk_where_clause(pk_info, "r.record_id")
    
    assert "[OrderID]" in where_clause
    assert "[ProductID]" in where_clause
    assert "JSON_VALUE" in where_clause
    assert "AND" in where_clause
    assert "$.OrderID" in where_clause
    assert "$.ProductID" in where_clause


def test_build_pk_where_clause_no_pk_raises_error(inspector: SchemaInspector, test_db_setup):
    """Test that WHERE clause generation fails for table without PK."""
    pk_info = inspector.get_primary_key_columns("TestTable_NoPK", "dbo")
    
    with pytest.raises(SchemaInspectionError) as exc_info:
        inspector.build_pk_where_clause(pk_info)
    
    assert "Cannot build WHERE clause" in str(exc_info.value)
    assert "without PK" in str(exc_info.value)


# ============================================================================
# UTILITY TESTS
# ============================================================================

def test_validate_table_exists_true(inspector: SchemaInspector, test_db_setup):
    """Test table existence validation for existing table."""
    exists = inspector.validate_table_exists("TestTable_SinglePK", "dbo")
    assert exists is True


def test_validate_table_exists_false(inspector: SchemaInspector, test_db_setup):
    """Test table existence validation for non-existent table."""
    exists = inspector.validate_table_exists("NonExistentTable", "dbo")
    assert exists is False


def test_get_column_info(inspector: SchemaInspector, test_db_setup):
    """Test column metadata extraction."""
    column_info = inspector.get_column_info("TestTable_SinglePK", "Name", "dbo")
    
    assert column_info is not None
    assert column_info["data_type"] == "nvarchar"
    assert column_info["max_length"] == 100
    assert column_info["is_nullable"] is True


def test_get_column_info_nonexistent(inspector: SchemaInspector, test_db_setup):
    """Test column metadata for non-existent column."""
    column_info = inspector.get_column_info("TestTable_SinglePK", "NonExistent", "dbo")
    assert column_info is None


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

def test_end_to_end_single_pk_flow(inspector: SchemaInspector, test_db_setup):
    """
    Test complete flow for single PK table:
    1. Extract PK info
    2. Build SELECT expression
    3. Build WHERE clause
    4. Verify SQL execution (without actual data)
    """
    # Step 1: Extract PK
    pk_info = inspector.get_primary_key_columns("TestTable_SinglePK", "dbo")
    assert pk_info.has_pk
    
    # Step 2: Build SELECT
    select_expr = inspector.build_pk_select_expression(pk_info)
    assert "CustomerID" in select_expr
    
    # Step 3: Build WHERE
    where_clause = inspector.build_pk_where_clause(pk_info)
    assert "CustomerID" in where_clause
    
    # Step 4: Verify expressions are valid SQL (syntax check)
    conn = test_db_setup
    cursor = conn.cursor()
    
    # Test SELECT expression
    query = f"SELECT {select_expr} AS record_id FROM dbo.TestTable_SinglePK"
    cursor.execute(query)
    # Should not raise


def test_end_to_end_composite_pk_flow(inspector: SchemaInspector, test_db_setup):
    """
    Test complete flow for composite PK table:
    1. Extract PK info
    2. Build SELECT expression  
    3. Build WHERE clause
    """
    # Step 1: Extract PK
    pk_info = inspector.get_primary_key_columns("TestTable_CompositePK", "dbo")
    assert pk_info.has_pk
    assert pk_info.is_composite
    
    # Step 2: Build SELECT
    select_expr = inspector.build_pk_select_expression(pk_info)
    assert "OrderID" in select_expr
    assert "ProductID" in select_expr
    
    # Step 3: Build WHERE
    where_clause = inspector.build_pk_where_clause(pk_info)
    assert "OrderID" in where_clause
    assert "ProductID" in where_clause


def test_end_to_end_no_pk_flow(inspector: SchemaInspector, test_db_setup):
    """
    Test complete flow for table without PK:
    1. Extract PK info
    2. Build SELECT expression (ROW_NUMBER fallback)
    3. WHERE clause should raise error
    """
    # Step 1: Extract PK
    pk_info = inspector.get_primary_key_columns("TestTable_NoPK", "dbo")
    assert not pk_info.has_pk
    
    # Step 2: Build SELECT (falls back to ROW_NUMBER)
    select_expr = inspector.build_pk_select_expression(pk_info)
    assert "ROW_NUMBER()" in select_expr
    
    # Step 3: WHERE clause should fail
    with pytest.raises(SchemaInspectionError):
        inspector.build_pk_where_clause(pk_info)


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================

def test_schema_inspection_error_with_suggested_action():
    """Test SchemaInspectionError formatting with suggested action."""
    error = SchemaInspectionError(
        "Test error",
        suggested_action="Run setup script"
    )
    
    error_str = str(error)
    assert "Test error" in error_str
    assert "Suggested action: Run setup script" in error_str


def test_schema_inspection_error_without_suggested_action():
    """Test SchemaInspectionError formatting without suggested action."""
    error = SchemaInspectionError("Test error")
    
    error_str = str(error)
    assert "Test error" in error_str
    assert "Suggested action" not in error_str


# ============================================================================
# PERFORMANCE TESTS
# ============================================================================

def test_pk_extraction_performance(inspector: SchemaInspector, test_db_setup):
    """Test that PK extraction with caching is fast."""
    import time
    
    # First call - cache miss
    start = time.time()
    inspector.get_primary_key_columns("TestTable_SinglePK", "dbo")
    first_call_time = time.time() - start
    
    # Second call - cache hit
    start = time.time()
    for _ in range(100):
        inspector.get_primary_key_columns("TestTable_SinglePK", "dbo")
    cached_calls_time = time.time() - start
    
    avg_cached_time = cached_calls_time / 100
    
    # Cached calls should be much faster (at least 10x)
    assert avg_cached_time < first_call_time / 10, (
        f"Cached call ({avg_cached_time:.6f}s) not significantly faster "
        f"than first call ({first_call_time:.6f}s)"
    )
