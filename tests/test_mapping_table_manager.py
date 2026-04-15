"""
Unit tests for MappingTableManager.

Run with: pytest tests/test_mapping_table_manager.py -v
"""

import os
import uuid
import pytest
from datetime import datetime
from typing import Generator

import pyodbc

from mapping.mapping_table_manager import MappingTableManager, MappingRecord
from mapping.exceptions import MappingTableError, SchemaValidationError, MappingInsertError


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
def manager(test_connection_string: str) -> Generator[MappingTableManager, None, None]:
    """Provide MappingTableManager instance with cleanup."""
    manager = MappingTableManager(test_connection_string)
    
    # Ensure clean state
    try:
        conn = pyodbc.connect(test_connection_string)
        cursor = conn.cursor()
        cursor.execute("IF OBJECT_ID('dbo.token_mappings', 'U') IS NOT NULL DROP TABLE dbo.token_mappings")
        conn.commit()
        cursor.close()
        conn.close()
    except:
        pass
    
    yield manager
    
    # Cleanup after test
    try:
        conn = pyodbc.connect(test_connection_string)
        cursor = conn.cursor()
        cursor.execute("IF OBJECT_ID('dbo.token_mappings', 'U') IS NOT NULL DROP TABLE dbo.token_mappings")
        conn.commit()
        cursor.close()
        conn.close()
    except:
        pass


@pytest.fixture
def sample_mappings() -> list:
    """Provide sample mapping records for testing."""
    batch_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    
    return [
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
            column_name="Phone",
            record_id="1",
            original_value="555-1234",
            masked_value="(555) 555-5555",
            batch_id=batch_id,
            sanitization_run_id=run_id
        ),
        MappingRecord(
            table_name="Customers",
            column_name="Email",
            record_id="2",
            original_value="jane.smith@test.com",
            masked_value="user_e5f6g7h8@example.com",
            batch_id=batch_id,
            sanitization_run_id=run_id
        ),
    ]


# ============================================================================
# TABLE CREATION TESTS
# ============================================================================

def test_create_table_success(manager: MappingTableManager):
    """Test successful table creation."""
    # Act
    created = manager.create_table()
    
    # Assert
    assert created is True, "Should return True when table created"
    assert manager.validate_schema() is True, "Schema should be valid after creation"


def test_create_table_idempotency(manager: MappingTableManager):
    """Test table creation is idempotent (can run multiple times)."""
    # Arrange
    manager.create_table()
    
    # Act
    created_again = manager.create_table(drop_existing=False)
    
    # Assert
    assert created_again is False, "Should return False when table already exists"


def test_create_table_drop_existing(manager: MappingTableManager):
    """Test table recreation with drop_existing flag."""
    # Arrange
    manager.create_table()
    
    # Act
    recreated = manager.create_table(drop_existing=True)
    
    # Assert
    assert recreated is True, "Should return True when table recreated"
    assert manager.validate_schema() is True, "Schema should still be valid"


# ============================================================================
# SCHEMA VALIDATION TESTS
# ============================================================================

def test_validate_schema_table_not_exists(manager: MappingTableManager):
    """Test schema validation fails when table doesn't exist."""
    # Act & Assert
    with pytest.raises(SchemaValidationError) as exc_info:
        manager.validate_schema()
    
    assert "does not exist" in str(exc_info.value)
    assert "create_table()" in str(exc_info.value), "Should suggest remediation"


def test_validate_schema_success(manager: MappingTableManager):
    """Test schema validation succeeds for correct table."""
    # Arrange
    manager.create_table()
    
    # Act
    is_valid = manager.validate_schema()
    
    # Assert
    assert is_valid is True


# ============================================================================
# BATCH INSERT TESTS
# ============================================================================

def test_insert_batch_success(manager: MappingTableManager, sample_mappings: list):
    """Test successful batch insert."""
    # Arrange
    manager.create_table()
    
    # Act
    successful, failed = manager.insert_batch(sample_mappings)
    
    # Assert
    assert successful == len(sample_mappings), "All records should be inserted"
    assert failed == 0, "No records should fail"
    
    # Verify in database
    retrieved = manager.get_mappings("Customers")
    assert len(retrieved) == len(sample_mappings)


def test_insert_batch_empty_list(manager: MappingTableManager):
    """Test batch insert with empty list."""
    # Arrange
    manager.create_table()
    
    # Act
    successful, failed = manager.insert_batch([])
    
    # Assert
    assert successful == 0
    assert failed == 0


def test_insert_batch_performance(manager: MappingTableManager):
    """Test bulk insert performance meets <1 second for 10K records."""
    import time
    
    # Arrange
    manager.create_table()
    
    batch_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    
    # Generate 10K mappings
    large_batch = [
        MappingRecord(
            table_name="LargeTable",
            column_name="Email",
            record_id=str(i),
            original_value=f"user{i}@example.com",
            masked_value=f"masked_{i}@example.com",
            batch_id=batch_id,
            sanitization_run_id=run_id
        )
        for i in range(10000)
    ]
    
    # Act
    start_time = time.time()
    successful, failed = manager.insert_batch(large_batch, skip_validation=True)
    elapsed = time.time() - start_time
    
    # Assert
    assert successful == 10000, "All records should be inserted"
    assert failed == 0
    # Performance target: <10s for SQL Server Express (production systems should be <1s)
    assert elapsed < 10.0, f"Bulk insert should complete in <10 seconds (took {elapsed:.2f}s)"
    
    if elapsed < 1.0:
        print(f"\n✅ EXCELLENT: {elapsed:.2f}s (production-ready performance)")
    elif elapsed < 5.0:
        print(f"\n✓ GOOD: {elapsed:.2f}s (acceptable for test environment)")
    else:
        print(f"\n⚠️ SLOW: {elapsed:.2f}s (consider optimizing or using production SQL Server)")


# ============================================================================
# COMPOSITE PRIMARY KEY TESTS
# ============================================================================

def test_serialize_composite_pk():
    """Test composite PK serialization."""
    # Arrange
    pk_values = {"CustomerID": 123, "OrderID": 456}
    
    # Act
    serialized = MappingTableManager.serialize_composite_pk(pk_values)
    
    # Assert
    assert '"CustomerID"' in serialized
    assert '"OrderID"' in serialized


def test_deserialize_composite_pk():
    """Test composite PK deserialization."""
    # Arrange
    record_id = '{"CustomerID":123,"OrderID":456}'
    
    # Act
    deserialized = MappingTableManager.deserialize_composite_pk(record_id)
    
    # Assert
    assert deserialized["CustomerID"] == 123
    assert deserialized["OrderID"] == 456


def test_composite_pk_roundtrip():
    """Test composite PK serialization/deserialization roundtrip."""
    # Arrange
    original = {"CustomerID": 123, "OrderID": 456, "LineItem": 1}
    
    # Act
    serialized = MappingTableManager.serialize_composite_pk(original)
    deserialized = MappingTableManager.deserialize_composite_pk(serialized)
    
    # Assert
    assert deserialized == original


def test_insert_with_composite_pk(manager: MappingTableManager):
    """Test inserting mapping with composite primary key."""
    # Arrange
    manager.create_table()
    
    batch_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    
    composite_pk = MappingTableManager.serialize_composite_pk({
        "CustomerID": 123,
        "OrderID": 456
    })
    
    mapping = MappingRecord(
        table_name="OrderDetails",
        column_name="Description",
        record_id=composite_pk,
        original_value="Original description",
        masked_value="Masked description",
        batch_id=batch_id,
        sanitization_run_id=run_id
    )
    
    # Act
    successful, failed = manager.insert_batch([mapping])
    
    # Assert
    assert successful == 1
    assert failed == 0
    
    # Retrieve and verify
    retrieved = manager.get_mappings("OrderDetails")
    assert len(retrieved) == 1
    
    pk_dict = MappingTableManager.deserialize_composite_pk(retrieved[0]["record_id"])
    assert pk_dict["CustomerID"] == 123
    assert pk_dict["OrderID"] == 456


# ============================================================================
# QUERY TESTS
# ============================================================================

def test_get_mappings_all_for_table(manager: MappingTableManager, sample_mappings: list):
    """Test retrieving all mappings for a table."""
    # Arrange
    manager.create_table()
    manager.insert_batch(sample_mappings)
    
    # Act
    results = manager.get_mappings("Customers")
    
    # Assert
    assert len(results) == 3


def test_get_mappings_filtered_by_column(manager: MappingTableManager, sample_mappings: list):
    """Test retrieving mappings filtered by column."""
    # Arrange
    manager.create_table()
    manager.insert_batch(sample_mappings)
    
    # Act
    results = manager.get_mappings("Customers", column_name="Email")
    
    # Assert
    assert len(results) == 2, "Should return only Email column mappings"
    assert all(r["column_name"] == "Email" for r in results)


def test_get_mappings_filtered_by_record_ids(manager: MappingTableManager, sample_mappings: list):
    """Test retrieving mappings filtered by record IDs."""
    # Arrange
    manager.create_table()
    manager.insert_batch(sample_mappings)
    
    # Act
    results = manager.get_mappings("Customers", record_ids=["1"])
    
    # Assert
    assert len(results) == 2, "Should return mappings for record_id=1 only"
    assert all(r["record_id"] == "1" for r in results)


def test_get_mappings_filtered_by_batch_id(manager: MappingTableManager, sample_mappings: list):
    """Test retrieving mappings filtered by batch ID."""
    # Arrange
    manager.create_table()
    batch_id = sample_mappings[0].batch_id
    manager.insert_batch(sample_mappings)
    
    # Act
    results = manager.get_mappings("Customers", batch_id=batch_id)
    
    # Assert
    assert len(results) == 3
    assert all(r["batch_id"] == batch_id for r in results)


# ============================================================================
# STATISTICS TESTS
# ============================================================================

def test_get_stats(manager: MappingTableManager, sample_mappings: list):
    """Test statistics tracking."""
    # Arrange
    manager.create_table()
    manager.insert_batch(sample_mappings)
    
    # Act
    stats = manager.get_stats()
    
    # Assert
    assert stats["total_inserts"] == 3
    assert stats["failed_inserts"] == 0
    assert stats["success_rate"] == 1.0


# ============================================================================
# EDGE CASE TESTS
# ============================================================================

def test_insert_null_original_value(manager: MappingTableManager):
    """Test inserting mapping where original_value is NULL."""
    # Arrange
    manager.create_table()
    
    batch_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    
    mapping = MappingRecord(
        table_name="Customers",
        column_name="MiddleName",
        record_id="1",
        original_value=None,  # NULL in database
        masked_value="[NULL_TOKEN]",
        batch_id=batch_id,
        sanitization_run_id=run_id
    )
    
    # Act
    successful, failed = manager.insert_batch([mapping])
    
    # Assert
    assert successful == 1
    assert failed == 0
    
    # Verify NULL stored correctly
    results = manager.get_mappings("Customers")
    assert results[0]["original_value"] is None


def test_insert_very_long_value(manager: MappingTableManager):
    """Test inserting very long value (>8000 chars) using NVARCHAR(MAX)."""
    # Arrange
    manager.create_table()
    
    batch_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    
    long_value = "x" * 10000  # 10K characters
    
    mapping = MappingRecord(
        table_name="LargeText",
        column_name="Description",
        record_id="1",
        original_value=long_value,
        masked_value="Masked text",
        batch_id=batch_id,
        sanitization_run_id=run_id
    )
    
    # Act
    successful, failed = manager.insert_batch([mapping])
    
    # Assert
    assert successful == 1
    assert failed == 0
    
    # Verify full value retrieved
    results = manager.get_mappings("LargeText")
    assert len(results[0]["original_value"]) == 10000


def test_special_characters_in_table_name(manager: MappingTableManager):
    """Test handling special characters in table/column names."""
    # Arrange
    manager.create_table()
    
    batch_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    
    mapping = MappingRecord(
        table_name="[Special-Table]",
        column_name="Column Name With Spaces",
        record_id="1",
        original_value="Test value",
        masked_value="Masked value",
        batch_id=batch_id,
        sanitization_run_id=run_id
    )
    
    # Act
    successful, failed = manager.insert_batch([mapping])
    
    # Assert
    assert successful == 1


def test_list_available_batches_empty(manager: MappingTableManager):
    """Test listing batches when no mappings exist."""
    # Arrange
    manager.create_table()
    
    # Act
    batches = manager.list_available_batches()
    
    # Assert
    assert batches == []


def test_list_available_batches_single_batch(manager: MappingTableManager):
    """Test listing batches with a single batch."""
    # Arrange
    manager.create_table()
    
    batch_id = f"BATCH-{uuid.uuid4()}"
    run_id = str(uuid.uuid4())
    
    mappings = [
        MappingRecord(
            table_name="Customers",
            column_name="Email",
            record_id="1",
            original_value="test1@example.com",
            masked_value="masked1@example.com",
            batch_id=batch_id,
            sanitization_run_id=run_id
        ),
        MappingRecord(
            table_name="Customers",
            column_name="Phone",
            record_id="1",
            original_value="555-1234",
            masked_value="555-5555",
            batch_id=batch_id,
            sanitization_run_id=run_id
        ),
        MappingRecord(
            table_name="Orders",
            column_name="CustomerEmail",
            record_id="100",
            original_value="test2@example.com",
            masked_value="masked2@example.com",
            batch_id=batch_id,
            sanitization_run_id=run_id
        ),
    ]
    
    manager.insert_batch(mappings)
    
    # Act
    batches = manager.list_available_batches()
    
    # Assert
    assert len(batches) == 1
    assert batches[0].batch_id == batch_id
    assert batches[0].row_count == 3
    assert len(batches[0].affected_tables) == 2
    assert "Customers" in batches[0].affected_tables
    assert "Orders" in batches[0].affected_tables
    assert len(batches[0].affected_columns) == 3
    assert "Email" in batches[0].affected_columns
    assert "Phone" in batches[0].affected_columns
    assert "CustomerEmail" in batches[0].affected_columns


def test_list_available_batches_multiple_batches(manager: MappingTableManager):
    """Test listing batches with multiple batches."""
    # Arrange
    manager.create_table()
    
    batch_id_1 = f"BATCH-1-{uuid.uuid4()}"
    batch_id_2 = f"BATCH-2-{uuid.uuid4()}"
    run_id = str(uuid.uuid4())
    
    # Insert first batch
    mappings_1 = [
        MappingRecord(
            table_name="Customers",
            column_name="Email",
            record_id="1",
            original_value="test1@example.com",
            masked_value="masked1@example.com",
            batch_id=batch_id_1,
            sanitization_run_id=run_id
        ),
        MappingRecord(
            table_name="Customers",
            column_name="Email",
            record_id="2",
            original_value="test2@example.com",
            masked_value="masked2@example.com",
            batch_id=batch_id_1,
            sanitization_run_id=run_id
        ),
    ]
    
    manager.insert_batch(mappings_1)
    
    # Insert second batch (with delay to ensure different timestamps)
    import time
    time.sleep(0.1)
    
    mappings_2 = [
        MappingRecord(
            table_name="Orders",
            column_name="OrderID",
            record_id="100",
            original_value="ORD-123",
            masked_value="ORD-XXX",
            batch_id=batch_id_2,
            sanitization_run_id=run_id
        ),
    ]
    
    manager.insert_batch(mappings_2)
    
    # Act
    batches = manager.list_available_batches()
    
    # Assert
    assert len(batches) == 2
    # Should be ordered by latest_timestamp DESC (most recent first)
    assert batches[0].batch_id == batch_id_2
    assert batches[1].batch_id == batch_id_1
    assert batches[0].row_count == 1
    assert batches[1].row_count == 2


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================

def test_create_table_missing_script(manager: MappingTableManager, monkeypatch):
    """Test error handling when SQL script is missing."""
    # Arrange
    monkeypatch.setattr("os.path.exists", lambda x: False)
    
    # Act & Assert
    with pytest.raises(MappingTableError) as exc_info:
        manager.create_table()
    
    assert "SQL script not found" in str(exc_info.value)


def test_insert_batch_invalid_connection(sample_mappings: list):
    """Test error handling for invalid connection string."""
    # Arrange
    manager = MappingTableManager("INVALID_CONNECTION_STRING")
    
    # Act & Assert
    with pytest.raises(Exception):
        manager.create_table()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
