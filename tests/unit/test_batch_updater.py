"""
Unit tests for BatchUpdater class.

Tests batch update functionality with mocked database connections,
covering all update strategies, validation, deadlock handling, and edge cases.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from typing import Dict, Any, List
import pyodbc

from src.database.batch_updater import (
    BatchUpdater,
    UpdateBatch,
    UpdateStrategy,
    retry_on_deadlock
)
from src.database.connection_manager import DatabaseConnectionManager
from src.database.schema_extractor import SchemaExtractor
from src.exceptions import DataUpdateError, TransactionError


# ==================== Fixtures ====================


@pytest.fixture
def mock_connection_manager():
    """Create a mock DatabaseConnectionManager."""
    mock_mgr = Mock(spec=DatabaseConnectionManager)
    mock_mgr.config = Mock()
    mock_mgr.config.database = "TestDB"
    return mock_mgr


@pytest.fixture
def mock_schema_extractor():
    """Create a mock SchemaExtractor."""
    return Mock(spec=SchemaExtractor)


@pytest.fixture
def batch_updater(mock_connection_manager, mock_schema_extractor):
    """Create a BatchUpdater instance with mocked dependencies."""
    return BatchUpdater(
        connection_manager=mock_connection_manager,
        schema_extractor=mock_schema_extractor,
        batch_size=10,  # Small batch size for testing
    )


def create_mock_schema(tables: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Helper to create mock schema metadata."""
    return {
        "tables": tables,
        "database_name": "TestDB",
        "extraction_timestamp": "2026-03-26T12:00:00",
    }


# ==================== Constructor Tests ====================


def test_constructor_valid_batch_size(mock_connection_manager, mock_schema_extractor):
    """Test constructor with valid batch size."""
    updater = BatchUpdater(
        connection_manager=mock_connection_manager,
        schema_extractor=mock_schema_extractor,
        batch_size=5000,
    )
    assert updater.batch_size == 5000
    assert updater.max_batch_size == 100000
    assert updater.max_retries == 3


def test_constructor_invalid_batch_size_too_small(mock_connection_manager, mock_schema_extractor):
    """Test constructor with batch size too small."""
    with pytest.raises(DataUpdateError) as exc_info:
        BatchUpdater(
            connection_manager=mock_connection_manager,
            schema_extractor=mock_schema_extractor,
            batch_size=0,
        )
    assert "Invalid batch size: 0" in str(exc_info.value)


def test_constructor_invalid_batch_size_too_large(mock_connection_manager, mock_schema_extractor):
    """Test constructor with batch size too large."""
    with pytest.raises(DataUpdateError) as exc_info:
        BatchUpdater(
            connection_manager=mock_connection_manager,
            schema_extractor=mock_schema_extractor,
            batch_size=100001,
        )
    assert "Invalid batch size: 100001" in str(exc_info.value)


# ==================== Strategy Selection Tests ====================


def test_select_strategy_no_pk(batch_updater, mock_schema_extractor):
    """Test strategy selection with no primary key."""
    mock_schema_extractor.extract_schema.return_value = create_mock_schema([])
    
    strategy = batch_updater._select_update_strategy("dbo", "NoIndex", [])
    assert strategy == UpdateStrategy.ROW_NUMBER


def test_select_strategy_composite_key(batch_updater, mock_schema_extractor):
    """Test strategy selection with composite primary key."""
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Orders",
            "columns": [
                {"name": "OrderID", "data_type": "int"},
                {"name": "ProductID", "data_type": "int"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    strategy = batch_updater._select_update_strategy("dbo", "Orders", ["OrderID", "ProductID"])
    assert strategy == UpdateStrategy.COMPOSITE_KEY


def test_select_strategy_single_numeric_pk(batch_updater, mock_schema_extractor):
    """Test strategy selection with single numeric primary key."""
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [
                {"name": "UserID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    strategy = batch_updater._select_update_strategy("dbo", "Users", ["UserID"])
    assert strategy == UpdateStrategy.KEY_BASED


def test_select_strategy_single_non_numeric_pk(batch_updater, mock_schema_extractor):
    """Test strategy selection with single non-numeric primary key."""
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Products",
            "columns": [
                {"name": "ProductGuid", "data_type": "uniqueidentifier"},
                {"name": "ProductName", "data_type": "nvarchar"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    strategy = batch_updater._select_update_strategy("dbo", "Products", ["ProductGuid"])
    assert strategy == UpdateStrategy.ROW_NUMBER


def test_select_strategy_bigint_pk(batch_updater, mock_schema_extractor):
    """Test strategy selection with BIGINT primary key."""
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Logs",
            "columns": [
                {"name": "LogID", "data_type": "bigint"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    strategy = batch_updater._select_update_strategy("dbo", "Logs", ["LogID"])
    assert strategy == UpdateStrategy.KEY_BASED


def test_select_strategy_many_composite_keys_warning(batch_updater, mock_schema_extractor):
    """Test strategy selection with many composite keys triggers warning."""
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "CompositeTable",
            "columns": [
                {"name": f"Key{i}", "data_type": "int"} for i in range(5)
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    # Should still return COMPOSITE_KEY but log warning
    strategy = batch_updater._select_update_strategy(
        "dbo", "CompositeTable", [f"Key{i}" for i in range(5)]
    )
    assert strategy == UpdateStrategy.COMPOSITE_KEY


# ==================== Validation Tests ====================


def test_validate_columns_exist_success(batch_updater, mock_schema_extractor):
    """Test column validation when columns exist."""
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [
                {"name": "UserID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
                {"name": "Phone", "data_type": "varchar"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    # Should not raise
    batch_updater._validate_columns_exist("dbo", "Users", ["Email", "Phone"])


def test_validate_columns_exist_column_missing(batch_updater, mock_schema_extractor):
    """Test column validation when column doesn't exist."""
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [
                {"name": "UserID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    with pytest.raises(DataUpdateError) as exc_info:
        batch_updater._validate_columns_exist("dbo", "Users", ["Email", "NonExistent"])
    
    assert "NonExistent" in str(exc_info.value)
    assert "does not exist" in str(exc_info.value).lower()


def test_validate_columns_exist_table_not_found(batch_updater, mock_schema_extractor):
    """Test column validation when table doesn't exist."""
    mock_schema = create_mock_schema([])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    with pytest.raises(DataUpdateError) as exc_info:
        batch_updater._validate_columns_exist("dbo", "NonExistentTable", ["Email"])
    
    assert "not found" in str(exc_info.value).lower()


def test_validate_pk_columns_no_pk_warning(batch_updater, mock_schema_extractor):
    """Test PK validation with no PK columns logs warning."""
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [{"name": "Email", "data_type": "nvarchar"}]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    # Should not raise, just log warning
    batch_updater._validate_pk_columns("dbo", "Users", [])


def test_validate_pk_columns_valid(batch_updater, mock_schema_extractor):
    """Test PK validation with valid PK columns."""
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [
                {"name": "UserID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    # Should not raise
    batch_updater._validate_pk_columns("dbo", "Users", ["UserID"])


# ==================== Update Batch Tests ====================


def test_update_batch_dataclass_properties():
    """Test UpdateBatch dataclass properties."""
    batch = UpdateBatch(
        updated_count=100,
        batch_number=1,
        rows_updated=100,
        total_rows=1000,
        schema_name="dbo",
        table_name="Users",
        columns_updated=["Email", "Phone"],
        strategy=UpdateStrategy.KEY_BASED,
    )
    
    assert batch.progress_percentage == 10.0
    assert not batch.is_last_batch
    assert batch.full_table_name == "dbo.Users"


def test_update_batch_last_batch():
    """Test UpdateBatch is_last_batch property."""
    batch = UpdateBatch(
        updated_count=100,
        batch_number=10,
        rows_updated=1000,
        total_rows=1000,
        schema_name="dbo",
        table_name="Users",
        columns_updated=["Email"],
        strategy=UpdateStrategy.KEY_BASED,
    )
    
    assert batch.progress_percentage == 100.0
    assert batch.is_last_batch


def test_update_batch_zero_total_rows():
    """Test UpdateBatch with zero total rows."""
    batch = UpdateBatch(
        updated_count=0,
        batch_number=0,
        rows_updated=0,
        total_rows=0,
        schema_name="dbo",
        table_name="Empty",
        columns_updated=[],
        strategy=UpdateStrategy.KEY_BASED,
    )
    
    assert batch.progress_percentage == 0.0


# ==================== Key-Based Update Tests ====================


def test_update_key_based_single_batch(batch_updater, mock_connection_manager, mock_schema_extractor):
    """Test key-based update with single batch."""
    # Setup mock schema
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [
                {"name": "UserID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    # Setup mock transaction context
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_cursor.rowcount = 3
    mock_conn.cursor.return_value = mock_cursor
    mock_connection_manager.transaction_context.return_value.__enter__.return_value = mock_conn
    mock_connection_manager.transaction_context.return_value.__exit__.return_value = False
    
    # Prepare updates
    updates = {
        1: {"Email": "user1@example.com"},
        2: {"Email": "user2@example.com"},
        3: {"Email": "user3@example.com"},
    }
    
    # Execute update
    batches = list(batch_updater.update_batches("dbo", "Users", ["UserID"], updates))
    
    # Verify
    assert len(batches) == 1
    assert batches[0].updated_count == 3
    assert batches[0].strategy == UpdateStrategy.KEY_BASED
    assert batches[0].is_last_batch


def test_update_key_based_multiple_batches(batch_updater, mock_connection_manager, mock_schema_extractor):
    """Test key-based update with multiple batches."""
    # Setup mock schema
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [
                {"name": "UserID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    # Setup mock transaction context - different rowcount for each batch
    mock_conn = Mock()
    mock_cursor1 = Mock()
    mock_cursor1.rowcount = 10  # First batch
    mock_cursor2 = Mock()
    mock_cursor2.rowcount = 5   # Second batch (partial)
    
    call_count = [0]
    
    def get_cursor():
        call_count[0] += 1
        return mock_cursor1 if call_count[0] == 1 else mock_cursor2
    
    mock_conn.cursor.side_effect = get_cursor
    mock_connection_manager.transaction_context.return_value.__enter__.return_value = mock_conn
    mock_connection_manager.transaction_context.return_value.__exit__.return_value = False
    
    # Prepare updates (15 rows, batch size 10)
    updates = {i: {"Email": f"user{i}@example.com"} for i in range(1, 16)}
    
    # Execute update
    batches = list(batch_updater.update_batches("dbo", "Users", ["UserID"], updates))
    
    # Verify
    assert len(batches) == 2
    assert batches[0].updated_count == 10
    assert batches[0].batch_number == 1
    assert batches[1].updated_count == 5
    assert batches[1].batch_number == 2
    assert batches[1].is_last_batch


def test_update_key_based_multiple_columns(batch_updater, mock_connection_manager, mock_schema_extractor):
    """Test key-based update with multiple columns."""
    # Setup mock schema
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [
                {"name": "UserID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
                {"name": "Phone", "data_type": "varchar"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    # Setup mock transaction context
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_cursor.rowcount = 2
    mock_conn.cursor.return_value = mock_cursor
    mock_connection_manager.transaction_context.return_value.__enter__.return_value = mock_conn
    mock_connection_manager.transaction_context.return_value.__exit__.return_value = False
    
    # Prepare updates with multiple columns
    updates = {
        1: {"Email": "user1@example.com", "Phone": "555-0001"},
        2: {"Email": "user2@example.com", "Phone": "555-0002"},
    }
    
    # Execute update
    batches = list(batch_updater.update_batches("dbo", "Users", ["UserID"], updates))
    
    # Verify
    assert len(batches) == 1
    assert batches[0].updated_count == 2
    assert len(batches[0].columns_updated) == 2
    assert "Email" in batches[0].columns_updated
    assert "Phone" in batches[0].columns_updated


# ==================== Composite Key Update Tests ====================


def test_update_composite_key(batch_updater, mock_connection_manager, mock_schema_extractor):
    """Test composite key update."""
    # Setup mock schema
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "OrderItems",
            "columns": [
                {"name": "OrderID", "data_type": "int"},
                {"name": "ProductID", "data_type": "int"},
                {"name": "Quantity", "data_type": "int"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    # Setup mock transaction context
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_cursor.rowcount = 2
    mock_conn.cursor.return_value = mock_cursor
    mock_connection_manager.transaction_context.return_value.__enter__.return_value = mock_conn
    mock_connection_manager.transaction_context.return_value.__exit__.return_value = False
    
    # Prepare updates with composite key
    updates = {
        (1, 100): {"Quantity": 5},
        (1, 101): {"Quantity": 10},
    }
    
    # Execute update
    batches = list(batch_updater.update_batches(
        "dbo", "OrderItems", ["OrderID", "ProductID"], updates
    ))
    
    # Verify
    assert len(batches) == 1
    assert batches[0].updated_count == 2
    assert batches[0].strategy == UpdateStrategy.COMPOSITE_KEY


# ==================== Empty Updates Test ====================


def test_update_batches_empty_updates(batch_updater, mock_schema_extractor):
    """Test update with empty updates dictionary."""
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [{"name": "UserID", "data_type": "int"}]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    updates = {}
    
    # Execute update
    batches = list(batch_updater.update_batches("dbo", "Users", ["UserID"], updates))
    
    # Verify - should be empty
    assert len(batches) == 0


# ==================== Deadlock Retry Tests ====================


@patch('time.sleep')  # Mock sleep to speed up tests
def test_deadlock_retry_success_on_second_attempt(mock_sleep):
    """Test deadlock retry succeeds on second attempt."""
    call_count = [0]
    
    @retry_on_deadlock(max_attempts=3, backoff_factor=0.5)
    def mock_update():
        call_count[0] += 1
        if call_count[0] == 1:
            # First attempt: raise deadlock error
            error = pyodbc.Error()
            error.args = ("40001", "deadlock victim")
            raise error
        # Second attempt: succeed
        return "success"
    
    result = mock_update()
    
    assert result == "success"
    assert call_count[0] == 2
    assert mock_sleep.call_count == 1  # One retry


@patch('time.sleep')
def test_deadlock_retry_exhausted(mock_sleep):
    """Test deadlock retry exhaustion after max attempts."""
    call_count = [0]
    
    @retry_on_deadlock(max_attempts=3, backoff_factor=0.5)
    def mock_update():
        call_count[0] += 1
        # Always raise deadlock error
        error = pyodbc.Error()
        error.args = ("40001", "deadlock victim")
        raise error
    
    with pytest.raises(DataUpdateError) as exc_info:
        mock_update()
    
    assert call_count[0] == 3
    assert "deadlock_retry_exhausted" in str(exc_info.value).lower() or "after 3 attempts" in str(exc_info.value).lower()
    assert mock_sleep.call_count == 2  # Two retries (between 3 attempts)


@patch('time.sleep')
def test_deadlock_retry_non_deadlock_error_no_retry(mock_sleep):
    """Test non-deadlock error is not retried."""
    call_count = [0]
    
    @retry_on_deadlock(max_attempts=3, backoff_factor=0.5)
    def mock_update():
        call_count[0] += 1
        # Raise non-deadlock error
        error = pyodbc.Error()
        error.args = ("42000", "syntax error")
        raise error
    
    with pytest.raises(pyodbc.Error):
        mock_update()
    
    assert call_count[0] == 1  # No retry
    assert mock_sleep.call_count == 0


@patch('time.sleep')
def test_deadlock_retry_with_error_number_1205(mock_sleep):
    """Test deadlock detection using SQL Server error number 1205."""
    call_count = [0]
    
    @retry_on_deadlock(max_attempts=3, backoff_factor=0.5)
    def mock_update():
        call_count[0] += 1
        if call_count[0] == 1:
            # First attempt: raise deadlock error with native error number
            error = pyodbc.Error()
            error.args = ("40001", 1205)  # SQLSTATE, native error number
            raise error
        # Second attempt: succeed
        return "success"
    
    result = mock_update()
    
    assert result == "success"
    assert call_count[0] == 2
    assert mock_sleep.call_count == 1


@patch('time.sleep')
def test_deadlock_retry_with_message_string(mock_sleep):
    """Test deadlock detection using error message string."""
    call_count = [0]
    
    @retry_on_deadlock(max_attempts=3, backoff_factor=0.5)
    def mock_update():
        call_count[0] += 1
        if call_count[0] == 1:
            # First attempt: raise error with "deadlock" in message
            error = pyodbc.Error("Transaction was deadlocked on lock resources")
            error.args = ("42000",)  # Non-deadlock SQLSTATE
            raise error
        # Second attempt: succeed
        return "success"
    
    result = mock_update()
    
    assert result == "success"
    assert call_count[0] == 2
    assert mock_sleep.call_count == 1


@patch('time.sleep')
def test_deadlock_retry_with_error_number_minus_3(mock_sleep):
    """Test deadlock detection using error number -3 (connection broken during deadlock)."""
    call_count = [0]
    
    @retry_on_deadlock(max_attempts=3, backoff_factor=0.5)
    def mock_update():
        call_count[0] += 1
        if call_count[0] == 1:
            # First attempt: raise error with -3 (connection broken)
            error = pyodbc.Error()
            error.args = ("08S01", -3)  # Communication link failure, native error -3
            raise error
        # Second attempt: succeed
        return "success"
    
    result = mock_update()
    
    assert result == "success"
    assert call_count[0] == 2
    assert mock_sleep.call_count == 1


def test_row_number_update_without_pk_raises_error(batch_updater, mock_connection_manager, mock_schema_extractor):
    """Test that ROW_NUMBER strategy raises error for tables without primary key."""
    # Setup mock schema with no primary key
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "TempData",
            "columns": [
                {"name": "Data1", "data_type": "nvarchar"},
                {"name": "Data2", "data_type": "int"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    # Prepare updates
    updates = {1: {"Data1": "updated"}}
    
    # Execute update with empty pk_columns - should raise clear error
    with pytest.raises(DataUpdateError) as exc_info:
        list(batch_updater._update_row_number(
            "dbo",
            "TempData",
            [],  # No PK columns
            ["Data1"],
            updates,
            "test-correlation-id"
        ))
    
    error_msg = str(exc_info.value).lower()
    assert "without primary key" in error_msg or "row identifier" in error_msg
    assert "cannot update" in error_msg


# ==================== Transaction Error Tests ====================


def test_update_transaction_commit_failure(batch_updater, mock_connection_manager, mock_schema_extractor):
    """Test handling of transaction commit failure."""
    # Setup mock schema
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [
                {"name": "UserID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    # Setup mock transaction context to raise error on exit (commit)
    mock_connection_manager.transaction_context.return_value.__enter__.return_value = Mock()
    mock_connection_manager.transaction_context.return_value.__exit__.side_effect = TransactionError.commit_failed(
        reason="Connection lost"
    )
    
    # Prepare updates
    updates = {1: {"Email": "user1@example.com"}}
    
    # Execute update - should raise TransactionError
    with pytest.raises(TransactionError):
        list(batch_updater.update_batches("dbo", "Users", ["UserID"], updates))


# ==================== Special Characters in Identifiers Tests ====================


def test_update_with_special_characters_in_table_name(batch_updater, mock_connection_manager, mock_schema_extractor):
    """Test update with special characters in table name."""
    # Setup mock schema with table name containing spaces
    mock_schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Order Details",
            "columns": [
                {"name": "OrderID", "data_type": "int"},
                {"name": "Total", "data_type": "decimal"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    # Setup mock transaction context
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_cursor.rowcount = 1
    mock_conn.cursor.return_value = mock_cursor
    mock_connection_manager.transaction_context.return_value.__enter__.return_value = mock_conn
    mock_connection_manager.transaction_context.return_value.__exit__.return_value = False
    
    # Prepare updates
    updates = {1: {"Total": 99.99}}
    
    # Execute update
    batches = list(batch_updater.update_batches("dbo", "Order Details", ["OrderID"], updates))
    
    # Verify - check that bracket escaping was used in the SQL
    assert len(batches) == 1
    assert batches[0].table_name == "Order Details"
    
    # Verify that executemany was called (indirectly confirms SQL was executed)
    mock_cursor.executemany.assert_called_once()


# ==================== Non-dbo Schema Tests ====================


def test_update_non_dbo_schema(batch_updater, mock_connection_manager, mock_schema_extractor):
    """Test update with non-dbo schema."""
    # Setup mock schema with custom schema
    mock_schema = create_mock_schema([
        {
            "schema": "custom_schema",
            "name": "Customers",
            "columns": [
                {"name": "CustomerID", "data_type": "int"},
                {"name": "ContactName", "data_type": "nvarchar"},
            ]
        }
    ])
    mock_schema_extractor.extract_schema.return_value = mock_schema
    
    # Setup mock transaction context
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_cursor.rowcount = 1
    mock_conn.cursor.return_value = mock_cursor
    mock_connection_manager.transaction_context.return_value.__enter__.return_value = mock_conn
    mock_connection_manager.transaction_context.return_value.__exit__.return_value = False
    
    # Prepare updates
    updates = {1: {"ContactName": "John Doe"}}
    
    # Execute update
    batches = list(batch_updater.update_batches(
        "custom_schema", "Customers", ["CustomerID"], updates
    ))
    
    # Verify
    assert len(batches) == 1
    assert batches[0].schema_name == "custom_schema"
    assert batches[0].full_table_name == "custom_schema.Customers"
