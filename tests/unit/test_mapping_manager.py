"""
Unit tests for MappingManager class.

Tests mapping table creation, batch storage, retrieval operations,
and comprehensive edge case handling with mocked database connections.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime
from uuid import UUID, uuid4
import hashlib
import pyodbc

from src.mapping.mapping_manager import MappingManager
from src.mapping.mapping_config import MappingConfig
from src.mapping.mapping_models import MappingEntry, MappingStats
from src.mapping.encryption_utils import EncryptionManager
from src.database.connection_manager import DatabaseConnectionManager
from src.exceptions import MappingError


# ==================== Fixtures ====================


@pytest.fixture
def mock_connection_manager():
    """Create a mock DatabaseConnectionManager."""
    mock_mgr = Mock(spec=DatabaseConnectionManager)
    
    # Mock connection context manager
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = Mock(return_value=mock_conn)
    mock_conn.__exit__ = Mock(return_value=False)
    
    mock_mgr.get_connection.return_value = mock_conn
    
    return mock_mgr


@pytest.fixture
def mock_encryption_manager():
    """Create a mock EncryptionManager."""
    mock_mgr = Mock(spec=EncryptionManager)
    mock_mgr.encrypt.side_effect = lambda x: f"encrypted_{x}".encode() if x else None
    mock_mgr.decrypt.side_effect = lambda x: x.decode().replace("encrypted_", "") if x else None
    return mock_mgr


@pytest.fixture
def mapping_config():
    """Create a default mapping configuration."""
    return MappingConfig(
        enabled=True,
        table_name="pii_mappings",
        schema_name="sanitization",
        encryption_enabled=False,
        batch_size=10,  # Small batch for testing
        index_creation=True,
        transactional=True
    )


@pytest.fixture
def mapping_manager(mock_connection_manager, mapping_config):
    """Create a MappingManager instance with mocked dependencies."""
    return MappingManager(
        connection_manager=mock_connection_manager,
        config=mapping_config
    )


@pytest.fixture
def sample_operation_id():
    """Create a sample operation UUID."""
    return uuid4()


@pytest.fixture
def sample_mapping_entry(sample_operation_id):
    """Create a sample MappingEntry."""
    return MappingEntry(
        operation_id=sample_operation_id,
        schema_name="dbo",
        table_name="Customers",
        column_name="Email",
        original_value_hash=hashlib.sha256(b"test@example.com").digest(),
        original_value_encrypted=None,
        masked_value="user_a1b2c3d4@example.com",
        data_type="VARCHAR",
        is_null=False,
        created_at=datetime.utcnow()
    )


# ==================== Constructor Tests ====================


def test_constructor_with_defaults(mock_connection_manager):
    """Test constructor with default configuration."""
    manager = MappingManager(
        connection_manager=mock_connection_manager
    )
    
    assert manager.connection_manager == mock_connection_manager
    assert manager.config is not None
    assert manager.config.table_name == "pii_mappings"
    assert manager.config.schema_name == "sanitization"
    assert manager.config.encryption_enabled is False
    assert manager.encryption_manager is None
    assert manager._initialized is False


def test_constructor_with_custom_config(mock_connection_manager):
    """Test constructor with custom configuration."""
    config = MappingConfig(
        table_name="custom_mappings",
        schema_name="custom_schema",
        batch_size=5000
    )
    
    manager = MappingManager(
        connection_manager=mock_connection_manager,
        config=config
    )
    
    assert manager.config.table_name == "custom_mappings"
    assert manager.config.schema_name == "custom_schema"
    assert manager.config.batch_size == 5000


def test_constructor_with_encryption_enabled(mock_connection_manager, mock_encryption_manager):
    """Test constructor with encryption enabled."""
    config = MappingConfig(encryption_enabled=True)
    
    manager = MappingManager(
        connection_manager=mock_connection_manager,
        config=config,
        encryption_manager=mock_encryption_manager
    )
    
    assert manager.encryption_manager == mock_encryption_manager
    assert manager.config.encryption_enabled is True


def test_constructor_encryption_without_key(mock_connection_manager):
    """Test constructor fails when encryption enabled but no key provided."""
    config = MappingConfig(encryption_enabled=True)
    
    # Mock EncryptionManager to raise error
    with patch('src.mapping.mapping_manager.EncryptionManager') as mock_enc:
        mock_enc.side_effect = Exception("No encryption key")
        
        with pytest.raises(MappingError) as exc_info:
            MappingManager(
                connection_manager=mock_connection_manager,
                config=config
            )
        
        assert "MAPPING_ENCRYPTION_KEY_MISSING" in str(exc_info.value)


# ==================== Initialization Tests ====================


def test_initialize_creates_schema_and_table(mapping_manager, mock_connection_manager):
    """Test initialize creates schema and table if they don't exist."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock schema doesn't exist
    mock_cursor.fetchone.side_effect = [None, None]  # Schema check, table check
    
    mapping_manager.initialize()
    
    assert mapping_manager._initialized is True
    assert mock_cursor.execute.call_count >= 3  # Schema check, table check, create queries


def test_initialize_skips_if_already_initialized(mapping_manager):
    """Test initialize is idempotent."""
    mapping_manager._initialized = True
    
    mapping_manager.initialize()
    
    # Should return early without database calls
    mapping_manager.connection_manager.get_connection.assert_not_called()


def test_initialize_with_existing_schema_and_table(mapping_manager, mock_connection_manager):
    """Test initialize when schema and table already exist."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock schema and table exist
    mock_cursor.fetchone.side_effect = [
        (1,),  # Schema exists
        (123,),  # Table exists
        (1,),  # Index 1 exists
        (2,)   # Index 2 exists
    ]
    
    mapping_manager.initialize()
    
    assert mapping_manager._initialized is True


def test_initialize_handles_schema_creation_error(mapping_manager, mock_connection_manager):
    """Test initialize handles schema creation errors."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock schema doesn't exist, creation fails
    mock_cursor.fetchone.return_value = None
    mock_cursor.execute.side_effect = pyodbc.Error("Permission denied")
    
    with pytest.raises(MappingError) as exc_info:
        mapping_manager.initialize()
    
    assert "MAPPING_SCHEMA_CREATION_FAILED" in str(exc_info.value)


def test_initialize_handles_table_creation_error(mapping_manager, mock_connection_manager):
    """Test initialize handles table creation errors."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock schema exists, table doesn't exist, creation fails
    def side_effect(*args, **kwargs):
        query = args[0] if args else ""
        if "FROM sys.schemas" in query:
            return (1,)  # Schema exists
        elif "FROM sys.tables" in query:
            return None  # Table doesn't exist
        else:
            raise pyodbc.Error("Invalid object name")
    
    mock_cursor.fetchone.side_effect = side_effect
    mock_cursor.execute.side_effect = [None, pyodbc.Error("Creation failed")]
    
    with pytest.raises(MappingError) as exc_info:
        mapping_manager.initialize()
    
    assert "MAPPING_TABLE_CREATION_FAILED" in str(exc_info.value)


def test_initialize_creates_indexes(mapping_manager, mock_connection_manager):
    """Test initialize creates indexes when configured."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock schema and table exist, indexes don't
    mock_cursor.fetchone.side_effect = [
        (1,),   # Schema exists
        (123,), # Table exists
        None,   # Index 1 doesn't exist
        None    # Index 2 doesn't exist
    ]
    
    mapping_manager.initialize()
    
    # Verify index creation queries were executed
    execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
    index_creates = [c for c in execute_calls if "CREATE NONCLUSTERED INDEX" in str(c)]
    assert len(index_creates) >= 2  # At least 2 index creation calls


def test_initialize_skips_indexes_if_disabled(mock_connection_manager):
    """Test initialize skips index creation when configured."""
    config = MappingConfig(index_creation=False)
    manager = MappingManager(
        connection_manager=mock_connection_manager,
        config=config
    )
    
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock schema and table exist
    mock_cursor.fetchone.side_effect = [(1,), (123,)]
    
    manager.initialize()
    
    # Verify no index creation queries
    execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
    index_creates = [c for c in execute_calls if "CREATE NONCLUSTERED INDEX" in str(c)]
    assert len(index_creates) == 0


# ==================== Storage Tests ====================


def test_store_mappings_empty_list(mapping_manager):
    """Test store_mappings with empty list."""
    stats = mapping_manager.store_mappings([])
    
    assert stats.total_entries == 0
    assert stats.tables_processed == 0
    assert stats.columns_processed == 0


def test_store_mappings_single_entry(mapping_manager, mock_connection_manager, sample_mapping_entry):
    """Test store_mappings with single entry."""
    # Mock initialization checks
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,)]  # Schema, table, indexes exist
    mock_cursor.rowcount = 1
    
    stats = mapping_manager.store_mappings([sample_mapping_entry])
    
    assert stats.total_entries == 1
    assert stats.tables_processed == 1
    assert stats.columns_processed == 1
    assert stats.operation_id == sample_mapping_entry.operation_id


def test_store_mappings_multiple_entries(mapping_manager, mock_connection_manager, sample_operation_id):
    """Test store_mappings with multiple entries."""
    # Create multiple entries
    entries = []
    for i in range(25):  # More than batch size (10)
        entry = MappingEntry(
            operation_id=sample_operation_id,
            schema_name="dbo",
            table_name=f"Table{i % 3}",  # 3 different tables
            column_name=f"Column{i % 5}",  # 5 different columns
            original_value_hash=hashlib.sha256(f"value{i}".encode()).digest(),
            original_value_encrypted=None,
            masked_value=f"masked{i}",
            data_type="VARCHAR",
            is_null=False,
            created_at=datetime.utcnow()
        )
        entries.append(entry)
    
    # Mock initialization and inserts
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,)]  # Initialization mocks
    mock_cursor.rowcount = 10  # Each batch processes 10 rows
    
    stats = mapping_manager.store_mappings(entries, batch_size=10)
    
    assert stats.total_entries == 25  # Note: Limited by rowcount mock
    assert stats.tables_processed == 3
    assert stats.columns_processed <= 5  # Max 5 unique columns


def test_store_mappings_with_null_values(mapping_manager, mock_connection_manager, sample_operation_id):
    """Test store_mappings handles NULL values correctly."""
    entry = MappingEntry(
        operation_id=sample_operation_id,
        schema_name="dbo",
        table_name="Customers",
        column_name="MiddleName",
        original_value_hash=hashlib.sha256(b"NULL").digest(),
        original_value_encrypted=None,
        masked_value=None,
        data_type="VARCHAR",
        is_null=True,
        created_at=datetime.utcnow()
    )
    
    # Mock initialization
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,)]
    mock_cursor.rowcount = 1
    
    stats = mapping_manager.store_mappings([entry])
    
    assert stats.total_entries == 1
    # Verify executemany was called with proper NULL handling
    call_args = mock_cursor.executemany.call_args
    params = call_args[0][1][0]  # First entry parameters
    assert params[8] == 1  # is_null column should be 1 (True)
    assert params[6] is None  # masked_value should be None


def test_store_mappings_auto_initializes(mapping_manager, mock_connection_manager, sample_mapping_entry):
    """Test store_mappings auto-initializes if not done."""
    assert mapping_manager._initialized is False
    
    # Mock initialization
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,)]
    mock_cursor.rowcount = 1
    
    stats = mapping_manager.store_mappings([sample_mapping_entry])
    
    assert mapping_manager._initialized is True
    assert stats.total_entries == 1


def test_store_mappings_handles_deadlock_retry(mapping_manager, mock_connection_manager, sample_mapping_entry):
    """Test store_mappings retries on deadlock."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock initialization
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,)]
    
    # First attempt: deadlock, second: success
    mock_cursor.executemany.side_effect = [
        pyodbc.Error("Deadlock victim", 1205),
        None
    ]
    mock_cursor.rowcount = 1
    
    # Should succeed after retry
    with patch('time.sleep'):  # Skip actual sleep
        stats = mapping_manager.store_mappings([sample_mapping_entry])
    
    assert stats.total_entries == 1
    assert mock_cursor.executemany.call_count == 2  # Initial + 1 retry


def test_store_mappings_fails_after_max_retries(mapping_manager, mock_connection_manager, sample_mapping_entry):
    """Test store_mappings fails after exhausting retries."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock initialization
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,)]
    
    # All attempts fail with deadlock
    mock_cursor.executemany.side_effect = pyodbc.Error("Deadlock victim", 1205)
    
    with patch('time.sleep'):  # Skip actual sleep
        with pytest.raises(MappingError) as exc_info:
            mapping_manager.store_mappings([sample_mapping_entry])
    
    assert "MAPPING_STORAGE_FAILED" in str(exc_info.value)


def test_store_mappings_custom_batch_size(mapping_manager, mock_connection_manager, sample_operation_id):
    """Test store_mappings respects custom batch size."""
    entries = []
    for i in range(15):
        entry = MappingEntry(
            operation_id=sample_operation_id,
            schema_name="dbo",
            table_name="Table1",
            column_name="Column1",
            original_value_hash=hashlib.sha256(f"value{i}".encode()).digest(),
            original_value_encrypted=None,
            masked_value=f"masked{i}",
            data_type="VARCHAR",
            is_null=False,
            created_at=datetime.utcnow()
        )
        entries.append(entry)
    
    # Mock initialization
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,)]
    mock_cursor.rowcount = 5  # Each batch inserts 5
    
    stats = mapping_manager.store_mappings(entries, batch_size=5)
    
    # Should have 3 batches (5 + 5 + 5)
    assert mock_cursor.executemany.call_count == 3


# ==================== Lookup Tests ====================


def test_get_mapping_found(mapping_manager, mock_connection_manager, sample_operation_id):
    """Test get_mapping retrieves existing mapping."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock initialization
    mock_cursor.fetchone.side_effect = [
        (1,), (123,), (1,), (2,),  # Initialization
        # Actual mapping row
        (
            str(sample_operation_id),
            "dbo",
            "Customers",
            "Email",
            hashlib.sha256(b"test@example.com").digest(),
            None,
            "user_a1b2c3d4@example.com",
            "VARCHAR",
            0,
            datetime.utcnow()
        )
    ]
    
    value_hash = hashlib.sha256(b"test@example.com").digest()
    mapping = mapping_manager.get_mapping(
        operation_id=sample_operation_id,
        schema="dbo",
        table="Customers",
        column="Email",
        value_hash=value_hash
    )
    
    assert mapping is not None
    assert mapping.table_name == "Customers"
    assert mapping.column_name == "Email"
    assert mapping.masked_value == "user_a1b2c3d4@example.com"


def test_get_mapping_not_found(mapping_manager, mock_connection_manager, sample_operation_id):
    """Test get_mapping returns None when not found."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock initialization and no result
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,), None]
    
    value_hash = hashlib.sha256(b"nonexistent@example.com").digest()
    mapping = mapping_manager.get_mapping(
        operation_id=sample_operation_id,
        schema="dbo",
        table="Customers",
        column="Email",
        value_hash=value_hash
    )
    
    assert mapping is None


def test_get_mapping_handles_error(mapping_manager, mock_connection_manager, sample_operation_id):
    """Test get_mapping handles database errors."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock initialization
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,)]
    mock_cursor.execute.side_effect = [None, None, None, None, pyodbc.Error("Connection lost")]
    
    value_hash = hashlib.sha256(b"test@example.com").digest()
    
    with pytest.raises(MappingError) as exc_info:
        mapping_manager.get_mapping(
            operation_id=sample_operation_id,
            schema="dbo",
            table="Customers",
            column="Email",
            value_hash=value_hash
        )
    
    assert "MAPPING_LOOKUP_FAILED" in str(exc_info.value)


def test_get_batch_mappings_with_filters(mapping_manager, mock_connection_manager, sample_operation_id):
    """Test get_batch_mappings with schema/table filters."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock initialization
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,)]
    
    # Mock result rows
    mock_cursor.fetchall.return_value = [
        (
            str(sample_operation_id),
            "dbo",
            "Customers",
            "Email",
            hashlib.sha256(b"user1@example.com").digest(),
            None,
            "masked1@example.com",
            "VARCHAR",
            0,
            datetime.utcnow()
        ),
        (
            str(sample_operation_id),
            "dbo",
            "Customers",
            "Phone",
            hashlib.sha256(b"5551234567").digest(),
            None,
            "5559999999",
            "VARCHAR",
            0,
            datetime.utcnow()
        )
    ]
    
    mappings = mapping_manager.get_batch_mappings(
        operation_id=sample_operation_id,
        filters={"schema": "dbo", "table": "Customers"},
        limit=100
    )
    
    assert len(mappings) == 2
    assert all(m.schema_name == "dbo" for m in mappings)
    assert all(m.table_name == "Customers" for m in mappings)


def test_get_batch_mappings_no_filters(mapping_manager, mock_connection_manager, sample_operation_id):
    """Test get_batch_mappings without filters."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock initialization
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,)]
    mock_cursor.fetchall.return_value = []
    
    mappings = mapping_manager.get_batch_mappings(
        operation_id=sample_operation_id,
        limit=1000
    )
    
    assert len(mappings) == 0


def test_get_batch_mappings_respects_limit(mapping_manager, mock_connection_manager, sample_operation_id):
    """Test get_batch_mappings respects limit parameter."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock initialization
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,)]
    mock_cursor.fetchall.return_value = []
    
    mapping_manager.get_batch_mappings(
        operation_id=sample_operation_id,
        limit=50
    )
    
    # Verify query included limit
    execute_call = str(mock_cursor.execute.call_args_list[-1])
    assert "TOP 50" in execute_call


# ==================== Statistics Tests ====================


def test_get_operation_stats_with_data(mapping_manager, mock_connection_manager, sample_operation_id):
    """Test get_operation_stats returns correct statistics."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock initialization
    started = datetime(2026, 3, 27, 10, 0, 0)
    completed = datetime(2026, 3, 27, 10, 5, 0)
    
    mock_cursor.fetchone.side_effect = [
        (1,), (123,), (1,), (2,),  # Initialization
        (100, 5, 10, started, completed)  # Stats: total, tables, columns, start, end
    ]
    
    stats = mapping_manager.get_operation_stats(sample_operation_id)
    
    assert stats.total_entries == 100
    assert stats.tables_processed == 5
    assert stats.columns_processed == 10
    assert stats.started_at == started
    assert stats.completed_at == completed


def test_get_operation_stats_no_data(mapping_manager, mock_connection_manager, sample_operation_id):
    """Test get_operation_stats with no mappings."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock initialization and no results
    mock_cursor.fetchone.side_effect = [
        (1,), (123,), (1,), (2,),  # Initialization
        (0, 0, 0, None, None)  # No mappings
    ]
    
    stats = mapping_manager.get_operation_stats(sample_operation_id)
    
    assert stats.total_entries == 0
    assert stats.tables_processed == 0
    assert stats.columns_processed == 0


# ==================== Utility Tests ====================


def test_table_exists_true(mapping_manager, mock_connection_manager):
    """Test table_exists returns True when table exists."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    mock_cursor.fetchone.return_value = (123,)  # Table exists
    
    assert mapping_manager.table_exists() is True


def test_table_exists_false(mapping_manager, mock_connection_manager):
    """Test table_exists returns False when table doesn't exist."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    mock_cursor.fetchone.return_value = None
    
    assert mapping_manager.table_exists() is False


def test_table_exists_handles_errors(mapping_manager, mock_connection_manager):
    """Test table_exists handles errors gracefully."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    mock_cursor.execute.side_effect = Exception("Connection error")
    
    # Should return False on error, not raise
    assert mapping_manager.table_exists() is False


def test_get_table_info_success(mapping_manager, mock_connection_manager):
    """Test get_table_info returns correct information."""
    # First check table exists
    mapping_manager._initialized = True
    
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    
    # Mock table exists check
    mock_cursor.fetchone.side_effect = [
        (123,),  # Table exists
        (1000, 5.5),  # Stats: row count, size in MB
    ]
    
    # Mock index query
    mock_cursor.fetchall.return_value = [
        ("PK_pii_mappings", "CLUSTERED"),
        ("idx_lookup", "NONCLUSTERED"),
        ("idx_operation", "NONCLUSTERED")
    ]
    
    info = mapping_manager.get_table_info()
    
    assert info["row_count"] == 1000
    assert info["size_mb"] == 5.5
    assert len(info["indexes"]) == 3
    assert info["encryption_enabled"] is False


def test_get_table_info_table_not_found(mapping_manager, mock_connection_manager):
    """Test get_table_info raises error if table doesn't exist."""
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    mock_cursor.fetchone.return_value = None  # Table doesn't exist
    
    with pytest.raises(MappingError) as exc_info:
        mapping_manager.get_table_info()
    
    assert "MAPPING_TABLE_NOT_FOUND" in str(exc_info.value)


# ==================== Edge Case Tests ====================


def test_handles_special_characters_in_names(mapping_manager, mock_connection_manager, sample_operation_id):
    """Test handles special characters in schema/table/column names."""
    entry = MappingEntry(
        operation_id=sample_operation_id,
        schema_name="dbo-special",
        table_name="Table With Spaces",
        column_name="Column[Special]",
        original_value_hash=hashlib.sha256(b"test").digest(),
        original_value_encrypted=None,
        masked_value="masked",
        data_type="VARCHAR",
        is_null=False,
        created_at=datetime.utcnow()
    )
    
    # Mock initialization
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,)]
    mock_cursor.rowcount = 1
    
    # Should not raise, handles special characters
    stats = mapping_manager.store_mappings([entry])
    assert stats.total_entries == 1


def test_handles_very_large_batch(mapping_manager, mock_connection_manager, sample_operation_id):
    """Test handles batches with many entries."""
    entries = []
    for i in range(1000):  # Large number of entries
        entry = MappingEntry(
            operation_id=sample_operation_id,
            schema_name="dbo",
            table_name="LargeTable",
            column_name="Column1",
            original_value_hash=hashlib.sha256(f"value{i}".encode()).digest(),
            original_value_encrypted=None,
            masked_value=f"masked{i}",
            data_type="VARCHAR",
            is_null=False,
            created_at=datetime.utcnow()
        )
        entries.append(entry)
    
    # Mock initialization
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,)]
    mock_cursor.rowcount = 10  # Each batch
    
    stats = mapping_manager.store_mappings(entries, batch_size=100)
    
    # Should process all entries in batches
    assert mock_cursor.executemany.call_count == 10  # 1000 / 100


def test_handles_concurrent_operations(mapping_manager, mock_connection_manager):
    """Test mapping manager handles concurrent operation IDs."""
    op_id_1 = uuid4()
    op_id_2 = uuid4()
    
    entries_1 = [
        MappingEntry(
            operation_id=op_id_1,
            schema_name="dbo",
            table_name="Table1",
            column_name="Col1",
            original_value_hash=hashlib.sha256(b"val1").digest(),
            original_value_encrypted=None,
            masked_value="masked1",
            data_type="VARCHAR",
            is_null=False,
            created_at=datetime.utcnow()
        )
    ]
    
    entries_2 = [
        MappingEntry(
            operation_id=op_id_2,
            schema_name="dbo",
            table_name="Table1",
            column_name="Col1",
            original_value_hash=hashlib.sha256(b"val2").digest(),
            original_value_encrypted=None,
            masked_value="masked2",
            data_type="VARCHAR",
            is_null=False,
            created_at=datetime.utcnow()
        )
    ]
    
    # Mock initialization
    mock_conn = mock_connection_manager.get_connection.return_value.__enter__.return_value
    mock_cursor = mock_conn.cursor.return_value
    mock_cursor.fetchone.side_effect = [(1,), (123,), (1,), (2,), (1,), (123,), (1,), (2,)]
    mock_cursor.rowcount = 1
    
    stats_1 = mapping_manager.store_mappings(entries_1)
    stats_2 = mapping_manager.store_mappings(entries_2)
    
    assert stats_1.operation_id != stats_2.operation_id
    assert stats_1.total_entries == 1
    assert stats_2.total_entries == 1
