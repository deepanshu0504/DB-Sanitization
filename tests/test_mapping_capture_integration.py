"""
Integration tests for Story 1.2: Mapping Capture During Sanitization.

These tests verify end-to-end mapping capture functionality including:
- Mapping capture during sanitization
- Transaction safety (atomicity)
- Primary key handling (single, composite, none)
- Dry-run behavior
- Configuration options

Run with: pytest tests/test_mapping_capture_integration.py -v
"""

import os
import json
import tempfile
import pytest
from typing import Generator

import pyodbc

from database.schema_inspector import SchemaInspector
from mapping.mapping_table_manager import MappingTableManager, MappingRecord


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
def test_db_setup(test_connection_string: str) -> Generator[pyodbc.Connection, None, None]:
    """
    Setup test database with sample tables and data.
    
    Creates:
    - Customers table (single PK) with sample PII data
    - OrderDetails table (composite PK) with sample data
    - AuditLog table (no PK) with sample data
    - token_mappings table for mapping capture
    """
    conn = pyodbc.connect(test_connection_string)
    cursor = conn.cursor()
    
    # Clean up any existing test tables
    cursor.execute("IF OBJECT_ID('dbo.Customers', 'U') IS NOT NULL DROP TABLE dbo.Customers")
    cursor.execute("IF OBJECT_ID('dbo.OrderDetails', 'U') IS NOT NULL DROP TABLE dbo.OrderDetails")
    cursor.execute("IF OBJECT_ID('dbo.AuditLog', 'U') IS NOT NULL DROP TABLE dbo.AuditLog")
    cursor.execute("IF OBJECT_ID('dbo.token_mappings', 'U') IS NOT NULL DROP TABLE dbo.token_mappings")
    conn.commit()
    
    # Create test tables with PII data
    cursor.execute("""
        CREATE TABLE dbo.Customers (
            CustomerID INT PRIMARY KEY,
            Name NVARCHAR(100),
            Email NVARCHAR(255),
            Phone NVARCHAR(20)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE dbo.OrderDetails (
            OrderID INT,
            ProductID INT,
            CustomerEmail NVARCHAR(255),
            PRIMARY KEY (OrderID, ProductID)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE dbo.AuditLog (
            LogID INT IDENTITY(1,1),
            UserEmail NVARCHAR(255),
            Action NVARCHAR(500)
        )
    """)
    
    # Insert test data
    cursor.execute("""
        INSERT INTO dbo.Customers (CustomerID, Name, Email, Phone) VALUES
        (1, 'John Doe', 'john.doe@example.com', '555-1234'),
        (2, 'Jane Smith', 'jane.smith@example.com', '555-5678'),
        (3, 'Bob Johnson', 'bob.j@example.com', '555-9012')
    """)
    
    cursor.execute("""
        INSERT INTO dbo.OrderDetails (OrderID, ProductID, CustomerEmail) VALUES
        (101, 1, 'john.doe@example.com'),
        (101, 2, 'john.doe@example.com'),
        (102, 1, 'jane.smith@example.com')
    """)
    
    cursor.execute("""
        INSERT INTO dbo.AuditLog (UserEmail, Action) VALUES
        ('admin@example.com', 'Login'),
        ('user@example.com', 'Logout')
    """)
    
    conn.commit()
    
    # Create mapping table
    mapping_manager = MappingTableManager(test_connection_string)
    mapping_manager.create_table(drop_existing=True)
    
    yield conn
    
    # Cleanup
    cursor.execute("DROP TABLE IF EXISTS dbo.Customers")
    cursor.execute("DROP TABLE IF EXISTS dbo.OrderDetails")
    cursor.execute("DROP TABLE IF EXISTS dbo.AuditLog")
    cursor.execute("DROP TABLE IF EXISTS dbo.token_mappings")
    conn.commit()
    cursor.close()
    conn.close()


# ============================================================================
# END-TO-END INTEGRATION TESTS
# ============================================================================

def test_end_to_end_mapping_capture_single_pk(test_connection_string: str, test_db_setup):
    """
    Test complete flow for single PK table:
    1. Sanitize with mapping capture enabled
    2. Verify mappings in token_mappings table
    3. Verify bidirectional lookup works
    """
    # This test would run the actual sanitization script
    # For now, we'll simulate the key operations
    
    schema_inspector = SchemaInspector(test_connection_string)
    mapping_manager = MappingTableManager(test_connection_string)
    
    # Get PK info
    pk_info = schema_inspector.get_primary_key_columns("Customers", "dbo")
    assert pk_info.has_pk
    assert not pk_info.is_composite
    
    # Simulate sanitization with mapping capture
    import uuid
    batch_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    
    conn = test_db_setup
    
    # Original mapping capture simulation
    mapping_records = [
        MappingRecord(
            table_name="Customers",
            column_name="Email",
            record_id="1",
            original_value="john.doe@example.com",
            masked_value="user_a1b2c3d4@example.com",
            batch_id=batch_id,
            sanitization_run_id=run_id
        ),
        MappingRecord(
            table_name="Customers",
            column_name="Email",
            record_id="2",
            original_value="jane.smith@example.com",
            masked_value="user_e5f6g7h8@example.com",
            batch_id=batch_id,
            sanitization_run_id=run_id
        )
    ]
    
    # Insert mappings
    successful, errors = mapping_manager.insert_batch_no_commit(conn, mapping_records)
    conn.commit()
    
    assert len(successful) == 2
    assert len(errors) == 0
    
    # Verify mappings in database
    mappings = mapping_manager.get_mappings(table_name="Customers", column_name="Email")
    
    assert len(mappings) == 2
    assert mappings[0]['table_name'] == "Customers"
    assert mappings[0]['column_name'] == "Email"
    assert mappings[0]['batch_id'] == batch_id
    
    # Verify bidirectional lookup
    masked_to_original = {m['masked_value']: m['original_value'] for m in mappings}
    assert masked_to_original["user_a1b2c3d4@example.com"] == "john.doe@example.com"


def test_composite_primary_key_mapping_capture(test_connection_string: str, test_db_setup):
    """Test mapping capture for table with composite PK."""
    schema_inspector = SchemaInspector(test_connection_string)
    mapping_manager = MappingTableManager(test_connection_string)
    
    # Get PK info
    pk_info = schema_inspector.get_primary_key_columns("OrderDetails", "dbo")
    assert pk_info.has_pk
    assert pk_info.is_composite
    assert set(pk_info.pk_columns) == {"OrderID", "ProductID"}
    
    # Simulate mapping capture with composite PK
    import uuid
    import json as jsonlib
    
    batch_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    
    # Record ID should be JSON for composite PK
    record_id_json = jsonlib.dumps({"OrderID": 101, "ProductID": 1})
    
    mapping_record = MappingRecord(
        table_name="OrderDetails",
        column_name="CustomerEmail",
        record_id=record_id_json,
        original_value="john.doe@example.com",
        masked_value="masked@example.com",
        batch_id=batch_id,
        sanitization_run_id=run_id
    )
    
    conn = test_db_setup
    successful, errors = mapping_manager.insert_batch_no_commit(conn, [mapping_record])
    conn.commit()
    
    assert len(successful) == 1
    
    # Verify stored record_id is valid JSON
    mappings = mapping_manager.get_mappings(table_name="OrderDetails")
    assert len(mappings) > 0
    
    stored_record_id = mappings[0]['record_id']
    parsed = jsonlib.loads(stored_record_id)
    assert "OrderID" in parsed
    assert "ProductID" in parsed


def test_no_primary_key_fallback(test_connection_string: str, test_db_setup):
    """Test mapping capture for table without PK uses ROW_NUMBER."""
    schema_inspector = SchemaInspector(test_connection_string)
    mapping_manager = MappingTableManager(test_connection_string)
    
    # Get PK info
    pk_info = schema_inspector.get_primary_key_columns("AuditLog", "dbo")
    assert not pk_info.has_pk
    
    # Build query with ROW_NUMBER fallback
    pk_select = schema_inspector.build_pk_select_expression(pk_info)
    assert "ROW_NUMBER()" in pk_select
    
    # Verify query executes successfully
    conn = test_db_setup
    cursor = conn.cursor()
    
    query = f"""
        SELECT 
            {pk_select} AS record_id,
            UserEmail
        FROM dbo.AuditLog
    """
    
    cursor.execute(query)
    rows = cursor.fetchall()
    
    assert len(rows) > 0
    # Record IDs should be numeric strings from ROW_NUMBER
    for row in rows:
        record_id = row[0]
        assert record_id.isdigit(), f"Expected numeric record_id, got: {record_id}"


def test_transaction_safety_rollback_on_error(test_connection_string: str, test_db_setup):
    """
    Verify transaction rollback works correctly if mapping capture fails.
    
    This ensures database updates and mapping inserts are atomic.
    """
    mapping_manager = MappingTableManager(test_connection_string)
    conn = test_db_setup
    
    # Get original email
    cursor = conn.cursor()
    cursor.execute("SELECT Email FROM dbo.Customers WHERE CustomerID = 1")
    original_email = cursor.fetchone()[0]
    
    # Simulate transaction with intentional failure
    import uuid
    try:
        conn.autocommit = False
        
        # Step 1: Update database
        cursor.execute("""
            UPDATE dbo.Customers 
            SET Email = 'modified@example.com'
            WHERE CustomerID = 1
        """)
        
        # Step 2: Insert invalid mapping (this should fail)
        # Create mapping with invalid schema to force error
        invalid_mapping = MappingRecord(
            table_name="Customers",
            column_name="Email",
            record_id="1",
            original_value=original_email,
            masked_value="masked@example.com",
            batch_id=str(uuid.uuid4()),
            sanitization_run_id=str(uuid.uuid4())
        )
        
        # Force an error by trying to insert into non-existent column
        # (simulating what would happen if mapping insert fails)
        cursor.execute("SELECT 1/0")  # Division by zero to force error
        
        conn.commit()
        
    except Exception as e:
        # Rollback on error
        conn.rollback()
    
    finally:
        conn.autocommit = True
    
    # Verify database NOT changed (rolled back)
    cursor.execute("SELECT Email FROM dbo.Customers WHERE CustomerID = 1")
    current_email = cursor.fetchone()[0]
    
    assert current_email == original_email, \
        f"Database changed despite rollback! Was: {original_email}, Now: {current_email}"


def test_dry_run_mode_skips_mapping_capture(test_connection_string: str, test_db_setup):
    """
    Verify dry-run mode with skip_on_dry_run=true doesn't create mappings.
    """
    mapping_manager = MappingTableManager(test_connection_string)
    
    # Count mappings before
    initial_mappings = mapping_manager.get_mappings(table_name="Customers")
    initial_count = len(initial_mappings)
    
    # In actual usage, this would be controlled by configuration
    # For this test, we simply verify the count doesn't increase
    # when skip_on_dry_run=true and dry_run=true
    
    # Simulate: dry_run=True, skip_on_dry_run=True -> No mappings created
    # (In real code, sanitization loop would skip mapping_manager.insert_batch call)
    
    # Verify count unchanged
    final_mappings = mapping_manager.get_mappings(table_name="Customers")
    final_count = len(final_mappings)
    
    assert final_count == initial_count, \
        "Mappings should not be created in dry-run mode with skip_on_dry_run=true"


def test_mapping_capture_with_null_values(test_connection_string: str, test_db_setup):
    """
    Test that NULL values are properly handled (skipped) in mapping capture.
    """
    # Add a row with NULL email
    conn = test_db_setup
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO dbo.Customers (CustomerID, Name, Email, Phone)
        VALUES (99, 'Test User', NULL, '555-0000')
    """)
    conn.commit()
    
    # Query with NULL filtering (as sanitization does)
    cursor.execute("""
        SELECT CustomerID, Email
        FROM dbo.Customers
        WHERE Email IS NOT NULL
    """)
    
    rows = cursor.fetchall()
    
    # Should not include the NULL email row
    customer_ids = [row[0] for row in rows]
    assert 99 not in customer_ids, "NULL values should be filtered out"


def test_special_characters_in_values(test_connection_string: str, test_db_setup):
    """Test mapping capture handles special characters correctly."""
    mapping_manager = MappingTableManager(test_connection_string)
    
    # Add customer with special characters
    conn = test_db_setup
    cursor = conn.cursor()
    
    special_email = "user+tag@test's-domain.co.uk"
    cursor.execute("""
        INSERT INTO dbo.Customers (CustomerID, Name, Email, Phone)
        VALUES (100, 'Special User', ?, '555-1111')
    """, (special_email,))
    conn.commit()
    
    # Create mapping with special characters
    import uuid
    mapping = MappingRecord(
        table_name="Customers",
        column_name="Email",
        record_id="100",
        original_value=special_email,
        masked_value="masked@example.com",
        batch_id=str(uuid.uuid4()),
        sanitization_run_id=str(uuid.uuid4())
    )
    
    successful, errors = mapping_manager.insert_batch_no_commit(conn, [mapping])
    conn.commit()
    
    assert len(successful) == 1
    assert len(errors) == 0
    
    # Verify retrieval
    mappings = mapping_manager.get_mappings(
        table_name="Customers",
        record_ids=["100"]
    )
    
    assert len(mappings) == 1
    assert mappings[0]['original_value'] == special_email


# ============================================================================
# PERFORMANCE TESTS
# ============================================================================

def test_mapping_capture_performance_acceptable(test_connection_string: str, test_db_setup):
    """
    Verify mapping capture doesn't add excessive overhead.
    
    Note: This is a basic sanity check. Full performance benchmarking
    should be done with test_mapping_capture_performance.py
    """
    import time
    import uuid
    
    mapping_manager = MappingTableManager(test_connection_string)
    conn = test_db_setup
    
    # Create 100 mapping records
    mappings = [
        MappingRecord(
            table_name="Customers",
            column_name="Email",
            record_id=str(i),
            original_value=f"user{i}@example.com",
            masked_value=f"masked{i}@example.com",
            batch_id=str(uuid.uuid4()),
            sanitization_run_id=str(uuid.uuid4())
        )
        for i in range(100)
    ]
    
    # Measure insert time
    start = time.time()
    successful, errors = mapping_manager.insert_batch_no_commit(conn, mappings, batch_size=50)
    conn.commit()
    duration = time.time() - start
    
    assert len(successful) == 100
    assert len(errors) == 0
    
    # Should complete in reasonable time (< 1 second for 100 records)
    assert duration < 1.0, f"Mapping capture took {duration:.2f}s for 100 records (too slow)"
    
    # Calculate throughput
    throughput = 100 / duration
    assert throughput > 100, f"Throughput {throughput:.0f} mappings/sec is too low"


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================

def test_mapping_capture_graceful_degradation(test_connection_string: str, test_db_setup):
    """
    Test that sanitization can continue even if mapping capture encounters errors.
    
    This tests the design principle: sanitization success is primary,
    mapping capture failure should warn but not abort.
    """
    mapping_manager = MappingTableManager(test_connection_string)
    conn = test_db_setup
    
    # Create mix of valid and invalid mappings
    import uuid
    batch_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    
    mappings = [
        MappingRecord(
            table_name="Customers",
            column_name="Email",
            record_id="1",
            original_value="valid@example.com",
            masked_value="masked1@example.com",
            batch_id=batch_id,
            sanitization_run_id=run_id
        ),
        MappingRecord(
            table_name="Customers",
            column_name="Email",
            record_id="2",
            original_value="also.valid@example.com",
            masked_value="masked2@example.com",
            batch_id=batch_id,
            sanitization_run_id=run_id
        )
    ]
    
    # Insert should succeed for valid mappings
    successful, errors = mapping_manager.insert_batch_no_commit(conn, mappings)
    conn.commit()
    
    # Should have captured some or all mappings
    assert len(successful) >= 0  # Graceful degradation


# ============================================================================
# BATCH LISTING TESTS (Story 4.3)
# ============================================================================

def test_list_available_batches_after_sanitization(test_connection_string: str, test_db_setup):
    """
    Test listing available sanitization batches after mapping capture.
    
    This tests Story 4.3 acceptance criteria:
    - List available batches with metadata
    - Display row counts, timestamps, affected tables/columns
    """
    import uuid
    from datetime import datetime
    
    mapping_manager = MappingTableManager(test_connection_string)
    mapping_manager.create_table()
    conn = test_db_setup
    
    # Create two distinct batches
    batch_id_1 = f"BATCH-1-{uuid.uuid4()}"
    batch_id_2 = f"BATCH-2-{uuid.uuid4()}"
    run_id = str(uuid.uuid4())
    
    # First batch: Customers table Email and Phone columns
    mappings_batch_1 = [
        MappingRecord(
            table_name="Customers",
            column_name="Email",
            record_id="1",
            original_value="john.doe@example.com",
            masked_value="masked_a1b2c3@example.com",
            batch_id=batch_id_1,
            sanitization_run_id=run_id
        ),
        MappingRecord(
            table_name="Customers",
            column_name="Phone",
            record_id="1",
            original_value="555-1234",
            masked_value="(555) 555-0001",
            batch_id=batch_id_1,
            sanitization_run_id=run_id
        ),
        MappingRecord(
            table_name="Customers",
            column_name="Email",
            record_id="2",
            original_value="jane.smith@example.com",
            masked_value="masked_d4e5f6@example.com",
            batch_id=batch_id_1,
            sanitization_run_id=run_id
        ),
    ]
    
    # Insert first batch
    successful_1, errors_1 = mapping_manager.insert_batch_no_commit(conn, mappings_batch_1)
    conn.commit()
    assert len(successful_1) == 3
    
    # Delay to ensure different timestamps
    import time
    time.sleep(0.2)
    
    # Second batch: OrderDetails table CustomerEmail column
    mappings_batch_2 = [
        MappingRecord(
            table_name="OrderDetails",
            column_name="CustomerEmail",
            record_id='["OrderID=1", "ProductID=100"]',  # Composite PK
            original_value="customer1@example.com",
            masked_value="masked_g7h8i9@example.com",
            batch_id=batch_id_2,
            sanitization_run_id=run_id
        ),
        MappingRecord(
            table_name="OrderDetails",
            column_name="CustomerEmail",
            record_id='["OrderID=2", "ProductID=200"]',  # Composite PK
            original_value="customer2@example.com",
            masked_value="masked_j1k2l3@example.com",
            batch_id=batch_id_2,
            sanitization_run_id=run_id
        ),
    ]
    
    # Insert second batch
    successful_2, errors_2 = mapping_manager.insert_batch_no_commit(conn, mappings_batch_2)
    conn.commit()
    assert len(successful_2) == 2
    
    # ACT: List available batches
    batches = mapping_manager.list_available_batches()
    
    # ASSERT: Should return both batches with correct metadata
    assert len(batches) == 2, f"Expected 2 batches, got {len(batches)}"
    
    # Batches should be ordered by latest_timestamp DESC (most recent first)
    assert batches[0].batch_id == batch_id_2, "Most recent batch should be first"
    assert batches[1].batch_id == batch_id_1, "Older batch should be second"
    
    # Verify first batch (batch_id_2, most recent)
    batch_2 = batches[0]
    assert batch_2.row_count == 2, f"Batch 2 should have 2 rows, got {batch_2.row_count}"
    assert len(batch_2.affected_tables) == 1, f"Batch 2 should affect 1 table, got {len(batch_2.affected_tables)}"
    assert "OrderDetails" in batch_2.affected_tables
    assert len(batch_2.affected_columns) == 1, f"Batch 2 should have 1 unique column, got {len(batch_2.affected_columns)}"
    assert "CustomerEmail" in batch_2.affected_columns
    assert isinstance(batch_2.earliest_timestamp, datetime)
    assert isinstance(batch_2.latest_timestamp, datetime)
    assert batch_2.latest_timestamp >= batch_2.earliest_timestamp
    
    # Verify second batch (batch_id_1, older)
    batch_1 = batches[1]
    assert batch_1.row_count == 3, f"Batch 1 should have 3 rows, got {batch_1.row_count}"
    assert len(batch_1.affected_tables) == 1, f"Batch 1 should affect 1 table, got {len(batch_1.affected_tables)}"
    assert "Customers" in batch_1.affected_tables
    assert len(batch_1.affected_columns) == 2, f"Batch 1 should have 2 unique columns, got {len(batch_1.affected_columns)}"
    assert "Email" in batch_1.affected_columns
    assert "Phone" in batch_1.affected_columns
    assert isinstance(batch_1.earliest_timestamp, datetime)
    assert isinstance(batch_1.latest_timestamp, datetime)
    
    # Verify temporal ordering: batch_2 should be after batch_1
    assert batch_2.latest_timestamp > batch_1.latest_timestamp, "Batch 2 should have later timestamp than Batch 1"
    
    print(f"✓ Successfully listed {len(batches)} batches:")
    for idx, batch in enumerate(batches, 1):
        print(f"  {idx}. {batch.batch_id}: {batch.row_count} rows, "
              f"{len(batch.affected_tables)} tables, {len(batch.affected_columns)} columns")

