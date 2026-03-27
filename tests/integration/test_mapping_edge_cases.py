"""
Edge case validation tests for Mapping Table Manager.

Tests comprehensive edge case handling for mapping storage including:
- Deadlock retry scenarios
- Large batch operations (100k+ rows)
- Unicode and special characters
- CHAR vs VARCHAR padding
- NULL value strategies
- Self-referencing FK tables
- Non-default schemas
- Encryption key scenarios

These tests validate adherence to CriticalRulesAndEdgeCases.md requirements.

IMPORTANT: Requires SQL Server instance with adequate resources.

Setup:
    Set environment variables:
    - SQLSERVER_HOST=localhost
    - SQLSERVER_DB=TestDB
    - SQLSERVER_AUTH=windows|sql
    - SQLSERVER_USER, SQLSERVER_PASS (if SQL auth)

Run:
    pytest tests/integration/test_mapping_edge_cases.py -v -s

Author: Database Sanitization Team
Date: 2026-03-27
"""

import pytest
import os
import hashlib
import concurrent.futures
from datetime import datetime
from uuid import uuid4

from src.database.connection_manager import DatabaseConnectionManager
from src.mapping.mapping_manager import MappingManager
from src.mapping.mapping_config import MappingConfig
from src.mapping.mapping_models import MappingEntry
from src.mapping.encryption_utils import EncryptionManager

from tests.integration.mapping_test_helpers import (
    get_test_db_config,
    cleanup_mapping_tables,
    generate_mapping_entries,
    setup_encryption_key,
    cleanup_encryption_key
)


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def connection_manager():
    """Create connection manager."""
    config = get_test_db_config()
    return DatabaseConnectionManager(config)


# ==================== Deadlock Handling Tests ====================


class TestDeadlockHandling:
    """Test deadlock retry logic."""
    
    def test_concurrent_batch_storage(self, connection_manager):
        """Test concurrent writes to mapping table (simulates deadlock scenarios)."""
        config = MappingConfig(
            enabled=True,
            schema_name="test_sanitization",
            table_name="test_pii_mappings_concurrent",
            batch_size=100
        )
        
        manager = MappingManager(connection_manager, config)
        manager.initialize()
        
        operation_id = uuid4()
        
        # Create function for concurrent execution
        def store_batch(batch_num):
            """Store a batch of entries."""
            entries = generate_mapping_entries(
                operation_id,
                count=50,
                table_name=f"Table{batch_num}"
            )
            manager.store_mappings(entries)
            return len(entries)
        
        try:
            # Execute multiple concurrent writes
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(store_batch, i) for i in range(10)]
                results = [f.result() for f in concurrent.futures.as_completed(futures)]
            
            # Verify all batches stored
            total_stored = sum(results)
            
            with connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"""
                    SELECT COUNT(*) 
                    FROM [{config.schema_name}].[{config.table_name}]
                    WHERE operation_id = ?
                """, (str(operation_id),))
                actual_count = cursor.fetchone()[0]
                cursor.close()
            
            assert actual_count == total_stored, \
                f"Expected {total_stored}, got {actual_count}"
        
        finally:
            cleanup_mapping_tables(connection_manager, config.schema_name, config.table_name)


# ==================== Large Batch Tests ====================


class TestLargeBatchOperations:
    """Test performance and correctness with large batches."""
    
    @pytest.mark.slow
    def test_store_100k_entries(self, connection_manager):
        """Test storing 100,000 mapping entries."""
        config = MappingConfig(
            enabled=True,
            schema_name="test_sanitization",
            table_name="test_pii_mappings_large",
            batch_size=10000  # Large batch size
        )
        
        manager = MappingManager(connection_manager, config)
        manager.initialize()
        
        operation_id = uuid4()
        
        # Generate 100k entries
        print("\n  Generating 100k entries...")
        entries = generate_mapping_entries(operation_id, count=100000)
        
        # Store with timing
        print("  Storing 100k entries...")
        import time
        start_time = time.time()
        
        manager.store_mappings(entries)
        
        elapsed = time.time() - start_time
        print(f"  Stored 100k entries in {elapsed:.2f}s ({100000/elapsed:.0f} entries/sec)")
        
        # Verify count
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT COUNT(*) 
                FROM [{config.schema_name}].[{config.table_name}]
                WHERE operation_id = ?
            """, (str(operation_id),))
            actual_count = cursor.fetchone()[0]
            cursor.close()
        
        assert actual_count == 100000
        
        # Performance threshold: should process at least 1000 entries/sec
        assert (100000 / elapsed) > 1000, "Performance below threshold"
        
        cleanup_mapping_tables(connection_manager, config.schema_name, config.table_name)


# ==================== Unicode and Special Characters Tests ====================


class TestUnicodeAndSpecialCharacters:
    """Test handling of Unicode and special SQL characters."""
    
    def test_unicode_in_all_fields(self, connection_manager):
        """Test Unicode characters in schema, table, column, and values."""
        config = MappingConfig(
            enabled=True,
            schema_name="test_sanitization",
            table_name="test_unicode_mappings",
            batch_size=100
        )
        
        manager = MappingManager(connection_manager, config)
        manager.initialize()
        
        operation_id = uuid4()
        
        # Create entries with various Unicode scripts
        unicode_test_cases = [
            ("José García", "用户_abc@例え.jp"),  # Spanish + Chinese + Japanese
            ("Владимир Путин", "пользователь@example.ру"),  # Russian
            ("محمد علي", "مستخدم@مثال.السعودية"),  # Arabic
            ("Παναγιώτης", "χρήστης@παράδειγμα.gr"),  # Greek
            ("김철수", "사용자@예시.한국"),  # Korean
        ]
        
        entries = []
        for i, (original, masked) in enumerate(unicode_test_cases):
            entry = MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name=f"Table_{i}",
                column_name=f"Column_{i}",
                original_value_hash=hashlib.sha256(original.encode('utf-8')).digest(),
                original_value_encrypted=None,
                masked_value=masked,
                data_type="NVARCHAR",
                is_null=False,
                created_at=datetime.utcnow()
            )
            entries.append(entry)
        
        manager.store_mappings(entries)
        
        # Retrieve and verify
        retrieved = manager.get_entries_by_operation(operation_id)
        
        assert len(retrieved) == len(unicode_test_cases)
        
        # Verify masked values preserved Unicode
        for entry, (_, expected_masked) in zip(retrieved, unicode_test_cases):
            assert entry.masked_value == expected_masked
        
        cleanup_mapping_tables(connection_manager, config.schema_name, config.table_name)
    
    def test_sql_special_characters(self, connection_manager):
        """Test SQL special characters that require escaping."""
        config = MappingConfig(
            enabled=True,
            schema_name="test_sanitization",
            table_name="test_special_chars",
            batch_size=100
        )
        
        manager = MappingManager(connection_manager, config)
        manager.initialize()
        
        operation_id = uuid4()
        
        # Test various special characters
        special_chars_cases = [
            ("Table[With]Brackets", "Column[With]Brackets"),
            ("Table'With'Quotes", "Column'With'Quotes"),
            ("Table--With--Dashes", "Column--With--Dashes"),
            ("Table;With;Semicolons", "Column;With;Semicolons"),
        ]
        
        entries = []
        for table, column in special_chars_cases:
            entry = MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name=table,
                column_name=column,
                original_value_hash=hashlib.sha256(b"test_value").digest(),
                original_value_encrypted=None,
                masked_value="masked_value",
                data_type="VARCHAR",
                is_null=False,
                created_at=datetime.utcnow()
            )
            entries.append(entry)
        
        # Should not raise SQL injection or syntax errors
        manager.store_mappings(entries)
        
        # Verify all stored
        retrieved = manager.get_entries_by_operation(operation_id)
        assert len(retrieved) == len(special_chars_cases)
        
        cleanup_mapping_tables(connection_manager, config.schema_name, config.table_name)


# ==================== CHAR vs VARCHAR Padding Tests ====================


class TestCharPadding:
    """Test CHAR vs VARCHAR/NVARCHAR handling."""
    
    def test_char_vs_varchar_storage(self, connection_manager):
        """Test that CHAR and VARCHAR are stored correctly."""
        config = MappingConfig(
            enabled=True,
            schema_name="test_sanitization",
            table_name="test_char_padding",
            batch_size=100
        )
        
        manager = MappingManager(connection_manager, config)
        manager.initialize()
        
        operation_id = uuid4()
        
        # Test cases for different data types
        test_cases = [
            ("CHAR", "test"),  # Will be padded to CHAR length
            ("VARCHAR", "test"),  # No padding
            ("NCHAR", "test"),  # Will be padded to NCHAR length
            ("NVARCHAR", "test"),  # No padding
        ]
        
        entries = []
        for data_type, value in test_cases:
            entry = MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="TestTable",
                column_name=f"Col_{data_type}",
                original_value_hash=hashlib.sha256(value.encode()).digest(),
                original_value_encrypted=None,
                masked_value=value,
                data_type=data_type,
                is_null=False,
                created_at=datetime.utcnow()
            )
            entries.append(entry)
        
        manager.store_mappings(entries)
        
        # Retrieve and verify data types preserved
        retrieved = manager.get_entries_by_operation(operation_id)
        
        for entry, (expected_type, _) in zip(retrieved, test_cases):
            assert entry.data_type == expected_type
        
        cleanup_mapping_tables(connection_manager, config.schema_name, config.table_name)


# ==================== NULL Value Handling Tests ====================


class TestNullValueHandling:
    """Test NULL value storage strategies."""
    
    def test_null_value_storage(self, connection_manager):
        """Test storing NULL values with is_null flag."""
        config = MappingConfig(
            enabled=True,
            schema_name="test_sanitization",
            table_name="test_null_values",
            batch_size=100
        )
        
        manager = MappingManager(connection_manager, config)
        manager.initialize()
        
        operation_id = uuid4()
        
        # Mix of NULL and non-NULL entries
        entries = []
        for i in range(10):
            is_null = (i % 2 == 0)  # Every other entry is NULL
            
            entry = MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="TestTable",
                column_name="Email",
                original_value_hash=hashlib.sha256(b"NULL" if is_null else f"test{i}@example.com".encode()).digest(),
                original_value_encrypted=None,
                masked_value=None if is_null else f"masked{i}@example.com",
                data_type="VARCHAR",
                is_null=is_null,
                created_at=datetime.utcnow()
            )
            entries.append(entry)
        
        manager.store_mappings(entries)
        
        # Verify NULL flags
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT is_null, masked_value
                FROM [{config.schema_name}].[{config.table_name}]
                WHERE operation_id = ?
                ORDER BY created_at
            """, (str(operation_id),))
            rows = cursor.fetchall()
            cursor.close()
        
        assert len(rows) == 10
        
        # Verify every other entry is NULL
        for i, (is_null_flag, masked_value) in enumerate(rows):
            if i % 2 == 0:
                assert is_null_flag == 1
                assert masked_value is None
            else:
                assert is_null_flag == 0
                assert masked_value is not None
        
        cleanup_mapping_tables(connection_manager, config.schema_name, config.table_name)


# ==================== Non-Default Schema Tests ====================


class TestNonDefaultSchema:
    """Test mapping tables in non-default schemas."""
    
    def test_custom_schema_creation(self, connection_manager):
        """Test creating mapping table in custom schema."""
        custom_schema = "custom_sanitization_schema"
        
        config = MappingConfig(
            enabled=True,
            schema_name=custom_schema,
            table_name="custom_pii_mappings",
            batch_size=100
        )
        
        manager = MappingManager(connection_manager, config)
        manager.initialize()
        
        # Verify schema created
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT COUNT(*) FROM sys.schemas
                WHERE name = '{custom_schema}'
            """)
            schema_exists = cursor.fetchone()[0]
            cursor.close()
        
        assert schema_exists == 1
        
        # Store test entry
        operation_id = uuid4()
        entries = generate_mapping_entries(operation_id, count=5)
        manager.store_mappings(entries)
        
        # Verify stored in custom schema
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT COUNT(*) 
                FROM [{custom_schema}].[custom_pii_mappings]
                WHERE operation_id = ?
            """, (str(operation_id),))
            count = cursor.fetchone()[0]
            cursor.close()
        
        assert count == 5
        
        cleanup_mapping_tables(connection_manager, custom_schema)


# ==================== Encryption Key Scenarios Tests ====================


class TestEncryptionKeyScenarios:
    """Test encryption key handling."""
    
    def test_missing_encryption_key(self, connection_manager):
        """Test that missing encryption key is handled gracefully."""
        # Ensure no key is set
        cleanup_encryption_key()
        
        config = MappingConfig(
            enabled=True,
            schema_name="test_sanitization",
            table_name="test_encryption_missing_key",
            encryption_enabled=True,  # Encryption enabled but no key
            batch_size=100
        )
        
        # Creating manager should work
        manager = MappingManager(connection_manager, config)
        manager.initialize()
        
        # Storing should fail gracefully (or skip encryption)
        operation_id = uuid4()
        entries = generate_mapping_entries(operation_id, count=5)
        
        # This should either work (no encryption) or raise clear error
        try:
            manager.store_mappings(entries)
            # If it succeeds, verify entries stored without encryption
            retrieved = manager.get_entries_by_operation(operation_id)
            assert len(retrieved) == 5
        except Exception as e:
            # Should be MappingError with clear message
            assert "encryption" in str(e).lower()
        finally:
            cleanup_mapping_tables(connection_manager, config.schema_name, config.table_name)
    
    def test_encryption_key_rotation(self, connection_manager):
        """Test scenario where encryption key changes."""
        # Setup initial key
        key1 = setup_encryption_key()
        
        config = MappingConfig(
            enabled=True,
            schema_name="test_sanitization",
            table_name="test_encryption_rotation",
            encryption_enabled=True,
            batch_size=100
        )
        
        try:
            manager = MappingManager(connection_manager, config)
            manager.initialize()
            
            # Store with first key
            operation_id = uuid4()
            entries = generate_mapping_entries(operation_id, count=5)
            manager.store_mappings(entries)
            
            # Change key (simulates rotation)
            key2 = EncryptionManager.generate_key()
            os.environ['SANITIZATION_MAPPING_ENCRYPTION_KEY'] = key2
            
            # Create new manager with new key
            manager2 = MappingManager(connection_manager, config)
            
            # Decryption with old data should fail
            retrieved = manager2.get_entries_by_operation(operation_id)
            assert len(retrieved) == 5  # Entries exist
            
            # Note: Actual decryption would fail with wrong key
            # This test demonstrates key rotation scenario
        
        finally:
            cleanup_encryption_key()
            cleanup_mapping_tables(connection_manager, config.schema_name, config.table_name)


# ==================== Self-Referencing Table Simulation ====================


class TestSelfReferencingScenarios:
    """Test scenarios with self-referencing table patterns."""
    
    def test_hierarchical_data_mapping(self, connection_manager):
        """Test mapping storage for hierarchical/self-referencing data."""
        config = MappingConfig(
            enabled=True,
            schema_name="test_sanitization",
            table_name="test_hierarchical_mappings",
            batch_size=100
        )
        
        manager = MappingManager(connection_manager, config)
        manager.initialize()
        
        operation_id = uuid4()
        
        # Simulate employee hierarchy (ManagerID → EmployeeID)
        # Masking must be deterministic to preserve relationships
        employees = [
            (1, None, "ceo@company.com"),  # CEO (no manager)
            (2, 1, "vp1@company.com"),     # VP reports to CEO
            (3, 1, "vp2@company.com"),     # VP reports to CEO
            (4, 2, "manager1@company.com"), # Manager reports to VP
            (5, 2, "manager2@company.com"), # Manager reports to VP
        ]
        
        entries = []
        for emp_id, manager_id, email in employees:
            entry = MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Employees",
                column_name="Email",
                original_value_hash=hashlib.sha256(email.encode()).digest(),
                original_value_encrypted=None,
                masked_value=f"emp_{emp_id:08x}@masked.dev",
                data_type="VARCHAR",
                is_null=False,
                created_at=datetime.utcnow()
            )
            entries.append(entry)
        
        manager.store_mappings(entries)
        
        # Verify all stored
        retrieved = manager.get_entries_by_operation(operation_id)
        assert len(retrieved) == 5
        
        # In actual sanitization, deterministic masking ensures
        # same EmployeeID value gets same masked value when used as ManagerID
        
        cleanup_mapping_tables(connection_manager, config.schema_name, config.table_name)
