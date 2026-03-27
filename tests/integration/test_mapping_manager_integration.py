"""
Integration tests for MappingManager with real SQL Server database.

These tests validate MappingManager functionality against an actual SQL Server
instance, including schema creation, batch operations, encryption, and retrieval.

IMPORTANT: These tests require a running SQL Server instance.

Setup:
    Set environment variables before running:
    - SQLSERVER_HOST=localhost (or your server address)
    - SQLSERVER_DB=TestDB (or test database name)
    - SQLSERVER_AUTH=windows|sql
    - SQLSERVER_USER=sa (required if SQLSERVER_AUTH=sql)
    - SQLSERVER_PASS=YourPassword (required if SQLSERVER_AUTH=sql)

Run:
    # Windows Authentication
    $env:SQLSERVER_HOST="localhost"
    $env:SQLSERVER_DB="TestDB"
    $env:SQLSERVER_AUTH="windows"
    pytest tests/integration/test_mapping_manager_integration.py -v

    # SQL Authentication
    $env:SQLSERVER_HOST="localhost"
    $env:SQLSERVER_DB="TestDB"
    $env:SQLSERVER_AUTH="sql"
    $env:SQLSERVER_USER="sa"
    $env:SQLSERVER_PASS="YourPassword123"
    pytest tests/integration/test_mapping_manager_integration.py -v

Author: Database Sanitization Team
Date: 2026-03-27
"""

import pytest
from uuid import uuid4
import hashlib
from datetime import datetime

from src.database.connection_manager import DatabaseConnectionManager
from src.mapping.mapping_manager import MappingManager
from src.mapping.mapping_config import MappingConfig
from src.mapping.mapping_models import MappingEntry
from src.mapping.encryption_utils import EncryptionManager
from src.exceptions import MappingError

from tests.integration.mapping_test_helpers import (
    get_test_db_config,
    create_test_mapping_table,
    cleanup_mapping_tables,
    generate_mapping_entries,
    verify_mapping_integrity,
    setup_encryption_key,
    cleanup_encryption_key
)


# Mark all tests to run only with --integration flag
pytestmark = pytest.mark.integration


# ==================== Fixtures ====================


@pytest.fixture(scope="module")
def connection_manager():
    """Create connection manager for all tests."""
    config = get_test_db_config()
    manager = DatabaseConnectionManager(config)
    yield manager
    # Connection manager cleanup is automatic


@pytest.fixture(scope="function")
def mapping_manager(connection_manager):
    """Create mapping manager with clean state for each test."""
    config = MappingConfig(
        enabled=True,
        schema_name="test_sanitization",
        table_name="test_pii_mappings",
        encryption_enabled=False,
        batch_size=100,
        index_creation=True,
        transactional=True
    )
    
    manager = MappingManager(connection_manager, config)
    
    yield manager
    
    # Cleanup after each test
    try:
        cleanup_mapping_tables(
            connection_manager,
            schema_name=config.schema_name,
            table_name=config.table_name
        )
    except Exception:
        pass  # Ignore cleanup errors


@pytest.fixture(scope="function")
def mapping_manager_with_encryption(connection_manager):
    """Create mapping manager with encryption enabled."""
    encryption_key = setup_encryption_key()
    
    config = MappingConfig(
        enabled=True,
        schema_name="test_sanitization",
        table_name="test_pii_mappings_encrypted",
        encryption_enabled=True,
        batch_size=100,
        index_creation=True,
        transactional=True
    )
    
    manager = MappingManager(connection_manager, config)
    
    yield manager
    
    # Cleanup
    try:
        cleanup_mapping_tables(
            connection_manager,
            schema_name=config.schema_name,
            table_name=config.table_name
        )
        cleanup_encryption_key()
    except Exception:
        pass


# ==================== Schema & Table Creation Tests ====================


class TestSchemaAndTableCreation:
    """Test schema, table, and index creation."""
    
    def test_initialize_creates_schema_and_table(self, mapping_manager):
        """Test that initialize creates schema and table."""
        # Initialize (creates schema and table)
        mapping_manager.initialize()
        
        # Verify schema exists
        with mapping_manager.connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM sys.schemas
                WHERE name = 'test_sanitization'
            """)
            schema_count = cursor.fetchone()[0]
            assert schema_count == 1, "Schema should exist"
            
            # Verify table exists
            cursor.execute("""
                SELECT COUNT(*) FROM sys.tables t
                JOIN sys.schemas s ON t.schema_id = s.schema_id
                WHERE s.name = 'test_sanitization' 
                AND t.name = 'test_pii_mappings'
            """)
            table_count = cursor.fetchone()[0]
            assert table_count == 1, "Table should exist"
            
            cursor.close()
    
    def test_initialize_is_idempotent(self, mapping_manager):
        """Test that initialize can be called multiple times safely."""
        # Initialize multiple times
        mapping_manager.initialize()
        mapping_manager.initialize()
        mapping_manager.initialize()
        
        # Verify still only one schema and table
        with mapping_manager.connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM sys.schemas
                WHERE name = 'test_sanitization'
            """)
            schema_count = cursor.fetchone()[0]
            assert schema_count == 1
            cursor.close()
    
    def test_indexes_created(self, mapping_manager):
        """Test that required indexes are created."""
        mapping_manager.initialize()
        
        with mapping_manager.connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sys.indexes
                WHERE object_id = OBJECT_ID('[test_sanitization].[test_pii_mappings]')
                AND name IN ('idx_lookup', 'idx_operation')
                ORDER BY name
            """)
            indexes = [row[0] for row in cursor.fetchall()]
            cursor.close()
        
        assert 'idx_lookup' in indexes, "Lookup index should exist"
        assert 'idx_operation' in indexes, "Operation index should exist"


# ==================== Batch Storage Tests ====================


class TestBatchStorage:
    """Test batch storage operations."""
    
    def test_store_single_batch(self, mapping_manager):
        """Test storing a single batch of entries."""
        mapping_manager.initialize()
        
        operation_id = uuid4()
        entries = generate_mapping_entries(operation_id, count=10)
        
        # Store batch
        mapping_manager.store_mappings(entries)
        
        # Verify storage
        is_valid, errors = verify_mapping_integrity(
            mapping_manager.connection_manager,
            "test_sanitization",
            "test_pii_mappings",
            operation_id,
            expected_count=10
        )
        assert is_valid, f"Integrity check failed: {errors}"
    
    def test_store_large_batch(self, mapping_manager):
        """Test storing large batch (10,000 entries)."""
        mapping_manager.initialize()
        
        operation_id = uuid4()
        entries = generate_mapping_entries(operation_id, count=10000)
        
        # Store batch (should auto-split if needed)
        mapping_manager.store_mappings(entries)
        
        # Verify all entries stored
        is_valid, errors = verify_mapping_integrity(
            mapping_manager.connection_manager,
            "test_sanitization",
            "test_pii_mappings",
            operation_id,
            expected_count=10000
        )
        assert is_valid, f"Integrity check failed: {errors}"
    
    def test_store_multiple_operations(self, mapping_manager):
        """Test storing entries from multiple operations."""
        mapping_manager.initialize()
        
        operation_id_1 = uuid4()
        operation_id_2 = uuid4()
        
        entries_1 = generate_mapping_entries(operation_id_1, count=50)
        entries_2 = generate_mapping_entries(operation_id_2, count=50)
        
        mapping_manager.store_mappings(entries_1)
        mapping_manager.store_mappings(entries_2)
        
        # Verify both operations stored correctly
        for op_id, expected in [(operation_id_1, 50), (operation_id_2, 50)]:
            is_valid, errors = verify_mapping_integrity(
                mapping_manager.connection_manager,
                "test_sanitization",
                "test_pii_mappings",
                op_id,
                expected_count=expected
            )
            assert is_valid, f"Operation {op_id} failed: {errors}"
    
    def test_store_with_null_values(self, mapping_manager):
        """Test storing entries with NULL values."""
        mapping_manager.initialize()
        
        operation_id = uuid4()
        
        # Create entry with NULL value
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="TestTable",
            column_name="Email",
            original_value_hash=hashlib.sha256(b"NULL").digest(),
            original_value_encrypted=None,
            masked_value=None,
            data_type="VARCHAR",
            is_null=True,
            created_at=datetime.utcnow()
        )
        
        mapping_manager.store_mappings([entry])
        
        # Verify stored with is_null=1
        with mapping_manager.connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT is_null, masked_value
                FROM [test_sanitization].[test_pii_mappings]
                WHERE operation_id = ?
            """, (str(operation_id),))
            row = cursor.fetchone()
            cursor.close()
        
        assert row is not None
        assert row[0] == 1, "is_null should be 1"
        assert row[1] is None, "masked_value should be NULL"


# ==================== Encryption Tests ====================


class TestEncryption:
    """Test encryption functionality."""
    
    def test_store_with_encryption(self, mapping_manager_with_encryption):
        """Test storing encrypted original values."""
        mapping_manager_with_encryption.initialize()
        
        operation_id = uuid4()
        original_value = "test@example.com"
        
        # Create entry
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="TestTable",
            column_name="Email",
            original_value_hash=hashlib.sha256(original_value.encode()).digest(),
            original_value_encrypted=original_value.encode(),  # Will be encrypted by manager
            masked_value="masked@example.com",
            data_type="VARCHAR",
            is_null=False,
            created_at=datetime.utcnow()
        )
        
        mapping_manager_with_encryption.store_mappings([entry])
        
        # Verify encrypted value is stored
        with mapping_manager_with_encryption.connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT original_value_encrypted
                FROM [test_sanitization].[test_pii_mappings_encrypted]
                WHERE operation_id = ?
            """, (str(operation_id),))
            row = cursor.fetchone()
            cursor.close()
        
        assert row is not None
        assert row[0] is not None, "Encrypted value should be stored"
        assert row[0] != original_value.encode(), "Value should be encrypted"
    
    def test_encryption_decryption_roundtrip(self, mapping_manager_with_encryption):
        """Test that encrypted values can be decrypted."""
        mapping_manager_with_encryption.initialize()
        
        operation_id = uuid4()
        original_value = "test@example.com"
        
        # Create and store entry
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="TestTable",
            column_name="Email",
            original_value_hash=hashlib.sha256(original_value.encode()).digest(),
            original_value_encrypted=original_value.encode(),
            masked_value="masked@example.com",
            data_type="VARCHAR",
            is_null=False,
            created_at=datetime.utcnow()
        )
        
        mapping_manager_with_encryption.store_mappings([entry])
        
        # Retrieve and decrypt
        entries = mapping_manager_with_encryption.get_entries_by_operation(operation_id)
        
        assert len(entries) == 1
        retrieved_entry = entries[0]
        
        # Decrypt the value
        encryption_manager = mapping_manager_with_encryption.encryption_manager
        decrypted = encryption_manager.decrypt(retrieved_entry.original_value_encrypted)
        
        assert decrypted == original_value


# ==================== Retrieval Tests ====================


class TestRetrieval:
    """Test entry retrieval operations."""
    
    def test_get_entries_by_operation(self, mapping_manager):
        """Test retrieving entries by operation ID."""
        mapping_manager.initialize()
        
        operation_id = uuid4()
        entries = generate_mapping_entries(operation_id, count=10)
        mapping_manager.store_mappings(entries)
        
        # Retrieve entries
        retrieved = mapping_manager.get_entries_by_operation(operation_id)
        
        assert len(retrieved) == 10
        assert all(e.operation_id == operation_id for e in retrieved)
    
    def test_get_entries_by_table(self, mapping_manager):
        """Test retrieving entries by table."""
        mapping_manager.initialize()
        
        operation_id = uuid4()
        
        # Store entries for different tables
        entries_table1 = generate_mapping_entries(
            operation_id, count=5, table_name="Table1"
        )
        entries_table2 = generate_mapping_entries(
            operation_id, count=5, table_name="Table2"
        )
        
        mapping_manager.store_mappings(entries_table1 + entries_table2)
        
        # Retrieve Table1 entries only
        retrieved = mapping_manager.get_entries_by_table(
            operation_id, "dbo", "Table1"
        )
        
        assert len(retrieved) == 5
        assert all(e.table_name == "Table1" for e in retrieved)
    
    def test_get_operations_stats(self, mapping_manager):
        """Test retrieving operation statistics."""
        mapping_manager.initialize()
        
        operation_id = uuid4()
        entries = generate_mapping_entries(operation_id, count=100)
        mapping_manager.store_mappings(entries)
        
        # Get stats
        stats = mapping_manager.get_operation_stats(operation_id)
        
        assert stats is not None
        assert stats.operation_id == operation_id
        assert stats.total_entries == 100
        assert stats.table_count == 1


# ==================== Edge Cases Tests ====================


class TestEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_unicode_values(self, mapping_manager):
        """Test storing Unicode characters in all fields."""
        mapping_manager.initialize()
        
        operation_id = uuid4()
        
        # Unicode values
        original = "José García <josé@例え.jp>"
        masked = "用户_abc123@示例.中国"
        
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="Ταβλε",  # Greek
            column_name="Имя",  # Cyrillic
            original_value_hash=hashlib.sha256(original.encode()).digest(),
            original_value_encrypted=None,
            masked_value=masked,
            data_type="NVARCHAR",
            is_null=False,
            created_at=datetime.utcnow()
        )
        
        mapping_manager.store_mappings([entry])
        
        # Retrieve and verify
        entries = mapping_manager.get_entries_by_operation(operation_id)
        assert len(entries) == 1
        assert entries[0].masked_value == masked
    
    def test_special_sql_characters(self, mapping_manager):
        """Test SQL special characters in names."""
        mapping_manager.initialize()
        
        operation_id = uuid4()
        
         # Table/column with special chars
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="Table[With]Brackets",
            column_name="Column'With'Quotes",
            original_value_hash=hashlib.sha256(b"test").digest(),
            original_value_encrypted=None,
            masked_value="masked_value",
            data_type="VARCHAR",
            is_null=False,
            created_at=datetime.utcnow()
        )
        
        mapping_manager.store_mappings([entry])
        
        # Retrieve
        entries = mapping_manager.get_entries_by_operation(operation_id)
        assert len(entries) == 1
    
    def test_empty_batch(self, mapping_manager):
        """Test storing empty batch (should handle gracefully)."""
        mapping_manager.initialize()
        
        # Store empty list
        mapping_manager.store_mappings([])
        
        # Should not raise error
        assert True
    
    def test_table_info(self, mapping_manager):
        """Test retrieving table information."""
        mapping_manager.initialize()
        
        info = mapping_manager.get_table_info()
        
        assert info is not None
        assert "row_count" in info
        assert "size_mb" in info
        assert info["schema_name"] == "test_sanitization"
        assert info["table_name"] == "test_pii_mappings"
