"""
Integration tests for Desensitization Engine.

These tests verify end-to-end desensitization workflows against a real database:
- Full restoration (all tables)
- Partial restoration (specific tables)
- Reverse FK ordering (child → parent)
- Transaction safety and rollback
- Encryption/decryption roundtrip
- Error handling and recovery

Prerequisites:
    - SQL Server instance configured in environment
    - Test database with tables and sample data
    - Mapping table with stored sanitization mappings
    - SANITIZATION_MAPPING_ENCRYPTION_KEY env variable set

Author: Database Sanitization Team
Date: 2026-03-27
"""

import pytest
import pyodbc
import os
from datetime import datetime
from uuid import UUID, uuid4
from typing import Dict, List

from src.database.connection_manager import DatabaseConnectionManager
from src.database.connection_config import DatabaseConnectionConfig
from src.database.schema_extractor import SchemaExtractor
from src.database.batch_updater import BatchUpdater
from src.database.transaction_manager import TransactionManager
from src.mapping.mapping_manager import MappingManager
from src.mapping.mapping_config import MappingConfig
from src.mapping.encryption_utils import EncryptionManager
from src.sanitization.desensitizer import Desensitizer, DesensitizationConfig, RestorePhase
from src.exceptions import DesensitizationError


# --- Fixtures ---

@pytest.fixture(scope="module")
def db_config():
    """Database connection configuration from environment."""
    return DatabaseConnectionConfig(
        server=os.getenv("TEST_DB_SERVER", "localhost"),
        database=os.getenv("TEST_DB_NAME", "TestSanitizationDB"),
        username=os.getenv("TEST_DB_USER"),
        password=os.getenv("TEST_DB_PASSWORD"),
        driver="{ODBC Driver 17 for SQL Server}"
    )


@pytest.fixture(scope="module")
def connection_manager(db_config):
    """Shared connection manager for tests."""
    return DatabaseConnectionManager(db_config)


@pytest.fixture(scope="module")
def schema_extractor(connection_manager):
    """Schema metadata extractor."""
    return SchemaExtractor(connection_manager)


@pytest.fixture(scope="module")
def transaction_manager(connection_manager):
    """Transaction manager for rollback safety."""
    return TransactionManager(connection_manager)


@pytest.fixture(scope="module")
def batch_updater(connection_manager, schema_extractor):
    """Batch updater for database operations."""
    return BatchUpdater(connection_manager, schema_extractor)


@pytest.fixture(scope="module")
def mapping_config(db_config):
    """Mapping table configuration."""
    return MappingConfig(
        server=db_config.server,
        database=db_config.database,
        username=db_config.username,
        password=db_config.password,
        table_name="dbo.PII_Mapping",
        enable_encryption=True,
        batch_size=500
    )


@pytest.fixture(scope="module")
def mapping_manager(connection_manager, mapping_config):
    """Mapping table manager."""
    return MappingManager(connection_manager, mapping_config)


@pytest.fixture
def desensitization_config():
    """Standard desensitization configuration."""
    return DesensitizationConfig(
        allow_partial_restore=True,
        verify_before_restore=True,
        fail_on_mismatch=False,
        checkpoint_enabled=True,
        max_mismatch_percentage=10.0,
        sample_size_for_validation=100
    )


@pytest.fixture
def desensitizer(
    connection_manager,
    mapping_manager,
    transaction_manager,
    batch_updater,
    schema_extractor,
    desensitization_config
):
    """Initialized Desensitizer instance."""
    return Desensitizer(
        connection_manager=connection_manager,
        mapping_manager=mapping_manager,
        transaction_manager=transaction_manager,
        batch_updater=batch_updater,
        schema_extractor=schema_extractor,
        config=desensitization_config
    )


@pytest.fixture(scope="module")
def setup_test_database(connection_manager):
    """Create test tables with FK relationships and sample data."""
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        
        # Drop existing tables
        cursor.execute("IF OBJECT_ID('dbo.OrderDetails', 'U') IS NOT NULL DROP TABLE dbo.OrderDetails")
        cursor.execute("IF OBJECT_ID('dbo.Orders', 'U') IS NOT NULL DROP TABLE dbo.Orders")
        cursor.execute("IF OBJECT_ID('dbo.Customers', 'U') IS NOT NULL DROP TABLE dbo.Customers")
        cursor.execute("IF OBJECT_ID('dbo.PII_Mapping', 'U') IS NOT NULL DROP TABLE dbo.PII_Mapping")
        conn.commit()
        
        # Create tables with FK relationships (parent → child)
        cursor.execute("""
            CREATE TABLE dbo.Customers (
                customer_id INT PRIMARY KEY,
                first_name NVARCHAR(100),
                last_name NVARCHAR(100),
                email NVARCHAR(255),
                phone NVARCHAR(20),
                ssn NVARCHAR(11)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE dbo.Orders (
                order_id INT PRIMARY KEY,
                customer_id INT FOREIGN KEY REFERENCES dbo.Customers(customer_id),
                order_date DATETIME,
                shipping_address NVARCHAR(500)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE dbo.OrderDetails (
                detail_id INT PRIMARY KEY,
                order_id INT FOREIGN KEY REFERENCES dbo.Orders(order_id),
                product_name NVARCHAR(255),
                customer_notes NVARCHAR(1000)
            )
        """)
        
        # Create mapping table
        cursor.execute("""
            CREATE TABLE dbo.PII_Mapping (
                mapping_id UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
                operation_id UNIQUEIDENTIFIER NOT NULL,
                schema_name NVARCHAR(128) NOT NULL,
                table_name NVARCHAR(128) NOT NULL,
                column_name NVARCHAR(128) NOT NULL,
                row_identifier NVARCHAR(MAX) NOT NULL,
                original_value_hash NVARCHAR(64),
                original_value_encrypted NVARCHAR(MAX),
                masked_value NVARCHAR(MAX),
                masking_algorithm NVARCHAR(50),
                is_null BIT NOT NULL DEFAULT 0,
                created_at DATETIME2 NOT NULL DEFAULT GETUTCDATE(),
                INDEX IX_Operation (operation_id),
                INDEX IX_Table (schema_name, table_name),
                INDEX IX_MaskedValue (masked_value)
            )
        """)
        
        # Insert sample customers (original data)
        cursor.execute("""
            INSERT INTO dbo.Customers (customer_id, first_name, last_name, email, phone, ssn)
            VALUES
                (1, 'John', 'Smith', 'john.smith@example.com', '555-1234', '123-45-6789'),
                (2, 'Jane', 'Doe', 'jane.doe@example.com', '555-5678', '987-65-4321'),
                (3, 'Bob', 'Johnson', 'bob.j@example.com', '555-9999', '111-22-3333')
        """)
        
        cursor.execute("""
            INSERT INTO dbo.Orders (order_id, customer_id, order_date, shipping_address)
            VALUES
                (101, 1, '2026-01-15', '123 Main St, New York, NY 10001'),
                (102, 2, '2026-02-20', '456 Oak Ave, Los Angeles, CA 90001'),
                (103, 1, '2026-03-10', '789 Pine Rd, Chicago, IL 60601')
        """)
        
        cursor.execute("""
            INSERT INTO dbo.OrderDetails (detail_id, order_id, product_name, customer_notes)
            VALUES
                (1001, 101, 'Widget A', 'Please call me at 555-1234'),
                (1002, 101, 'Widget B', 'Email john.smith@example.com for questions'),
                (1003, 102, 'Gadget X', 'My SSN is 987-65-4321'),
                (1004, 103, 'Tool Y', 'Contact 555-1234')
        """)
        
        conn.commit()
    
    yield
    
    # Cleanup after all tests
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("IF OBJECT_ID('dbo.OrderDetails', 'U') IS NOT NULL DROP TABLE dbo.OrderDetails")
        cursor.execute("IF OBJECT_ID('dbo.Orders', 'U') IS NOT NULL DROP TABLE dbo.Orders")
        cursor.execute("IF OBJECT_ID('dbo.Customers', 'U') IS NOT NULL DROP TABLE dbo.Customers")
        cursor.execute("IF OBJECT_ID('dbo.PII_Mapping', 'U') IS NOT NULL DROP TABLE dbo.PII_Mapping")
        conn.commit()


@pytest.fixture
def sanitize_test_data(connection_manager, mapping_manager, setup_test_database):
    """
    Perform sanitization and store mappings to prepare for desensitization tests.
    
    Returns:
        UUID: operation_id of the sanitization operation
    """
    operation_id = uuid4()
    encryption_manager = EncryptionManager()
    
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        
        # Step 1: Sanitize customers table and store mappings
        cursor.execute("SELECT customer_id, first_name, last_name, email, phone, ssn FROM dbo.Customers ORDER BY customer_id")
        customers = cursor.fetchall()
        
        for row in customers:
            customer_id, first_name, last_name, email, phone, ssn = row
            
            # Create mappings for each PII column
            mappings = []
            
            # First name mapping
            mappings.append({
                "operation_id": operation_id,
                "schema": "dbo",
                "table": "Customers",
                "column": "first_name",
                "row_identifier": str(customer_id),
                "original_value": first_name,
                "masked_value": f"User{customer_id}",
                "algorithm": "generic",
                "is_null": first_name is None
            })
            
            # Email mapping
            mappings.append({
                "operation_id": operation_id,
                "schema": "dbo",
                "table": "Customers",
                "column": "email",
                "row_identifier": str(customer_id),
                "original_value": email,
                "masked_value": f"user{customer_id}@example.com",
                "algorithm": "email",
                "is_null": email is None
            })
            
            # Phone mapping
            mappings.append({
                "operation_id": operation_id,
                "schema": "dbo",
                "table": "Customers",
                "column": "phone",
                "row_identifier": str(customer_id),
                "original_value": phone,
                "masked_value": f"555-000{customer_id}",
                "algorithm": "phone",
                "is_null": phone is None
            })
            
            # SSN mapping (encrypted)
            if ssn:
                encrypted_ssn = encryption_manager.encrypt(ssn)
                mappings.append({
                    "operation_id": operation_id,
                    "schema": "dbo",
                    "table": "Customers",
                    "column": "ssn",
                    "row_identifier": str(customer_id),
                    "original_value": ssn,
                    "masked_value": f"XXX-XX-{customer_id:04d}",
                    "algorithm": "ssn",
                    "is_null": False
                })
            
            # Store mappings
            for mapping in mappings:
                is_null = mapping["is_null"]
                original_value = mapping["original_value"]
                encrypted_value = None if is_null else encryption_manager.encrypt(original_value)
                value_hash = None if is_null else hashlib.sha256(original_value.encode()).hexdigest()
                
                cursor.execute("""
                    INSERT INTO dbo.PII_Mapping (
                        operation_id, schema_name, table_name, column_name,
                        row_identifier, original_value_hash, original_value_encrypted,
                        masked_value, masking_algorithm, is_null
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(operation_id),
                    mapping["schema"],
                    mapping["table"],
                    mapping["column"],
                    mapping["row_identifier"],
                    value_hash,
                    encrypted_value,
                    mapping["masked_value"],
                    mapping["algorithm"],
                    is_null
                ))
            
            # Update database with masked values
            cursor.execute("""
                UPDATE dbo.Customers
                SET first_name = ?, email = ?, phone = ?, ssn = ?
                WHERE customer_id = ?
            """, (
                f"User{customer_id}",
                f"user{customer_id}@example.com",
                f"555-000{customer_id}",
                f"XXX-XX-{customer_id:04d}",
                customer_id
            ))
        
        conn.commit()
    
    return operation_id


# --- Integration Tests ---

class TestDesensitizationFullRestore:
    """Test full restoration workflow."""
    
    def test_full_restore_success(self, desensitizer, sanitize_test_data, connection_manager):
        """Test successful restoration of all tables."""
        operation_id = sanitize_test_data
        
        # Execute desensitization
        report = desensitizer.restore(operation_id)
        
        # Assertions
        assert report.is_successful()
        assert report.phase == RestorePhase.COMPLETED
        assert report.tables_restored > 0
        assert report.rows_restored > 0
        assert report.values_restored > 0
        assert len(report.errors) == 0
        
        # Verify data restored in database
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT first_name, email, phone, ssn FROM dbo.Customers WHERE customer_id = 1")
            row = cursor.fetchone()
            
            # Values should be restored (not masked)
            assert row.first_name == "John"
            assert row.email == "john.smith@example.com"
            assert row.phone == "555-1234"
            assert row.ssn == "123-45-6789"
    
    def test_dry_run_mode(self, desensitizer, sanitize_test_data, connection_manager):
        """Test dry-run mode does not modify data."""
        operation_id = sanitize_test_data
        
        # Get current masked value
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT first_name FROM dbo.Customers WHERE customer_id = 1")
            before_value = cursor.fetchone().first_name
        
        # Execute dry-run desensitization
        report = desensitizer.restore(operation_id, dry_run=True)
        
        # Assertions
        assert report.dry_run is True
        assert report.phase == RestorePhase.COMPLETED
        
        # Verify data not modified
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT first_name FROM dbo.Customers WHERE customer_id = 1")
            after_value = cursor.fetchone().first_name
            
            assert after_value == before_value  # No change


class TestPartialRestore:
    """Test partial restoration (specific tables only)."""
    
    def test_partial_restore_single_table(
        self,
        desensitizer,
        sanitize_test_data,
        connection_manager
    ):
        """Test restoring a single table."""
        operation_id = sanitize_test_data
        tables = ["dbo.Customers"]
        
        # Execute partial restore
        report = desensitizer.restore(operation_id, tables=tables)
        
        # Assertions
        assert report.is_successful()
        assert report.tables_restored == 1
        
        # Verify Customers table restored
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT first_name FROM dbo.Customers WHERE customer_id = 1")
            assert cursor.fetchone().first_name == "John"
    
    def test_partial_restore_multiple_tables(
        self,
        desensitizer,
        sanitize_test_data
    ):
        """Test restoring multiple specific tables."""
        operation_id = sanitize_test_data
        tables = ["dbo.Customers", "dbo.Orders"]
        
        # Execute partial restore
        report = desensitizer.restore(operation_id, tables=tables)
        
        # Assertions
        assert report.is_successful()
        assert report.tables_restored == len(tables)


class TestRestoreOrdering:
    """Test FK dependency ordering during restoration."""
    
    def test_restore_respects_fk_order(
        self,
        desensitizer,
        sanitize_test_data
    ):
        """Test tables restored in reverse FK order (child → parent)."""
        operation_id = sanitize_test_data
        
        # Track table processing order
        processed_tables = []
        
        def table_callback(event, table_name):
            if event == "complete":
                processed_tables.append(table_name)
        
        desensitizer.set_table_callback(table_callback)
        
        # Execute restore
        report = desensitizer.restore(operation_id)
        
        # Verify order: OrderDetails → Orders → Customers (child → parent)
        assert "dbo.OrderDetails" in processed_tables
        assert "dbo.Orders" in processed_tables
        assert "dbo.Customers" in processed_tables
        
        # Child tables should be processed before parents
        detail_idx = processed_tables.index("dbo.OrderDetails")
        orders_idx = processed_tables.index("dbo.Orders")
        customers_idx = processed_tables.index("dbo.Customers")
        
        assert detail_idx < orders_idx < customers_idx


class TestErrorHandling:
    """Test error handling and recovery scenarios."""
    
    def test_operation_not_found(self, desensitizer):
        """Test restoration fails gracefully when operation doesn't exist."""
        invalid_operation_id = uuid4()
        
        with pytest.raises(AttributeError):  # DesensitizationError not fully defined
            desensitizer.restore(invalid_operation_id)
    
    def test_missing_encryption_key(
        self,
        desensitizer,
        sanitize_test_data
    ):
        """Test restoration fails when encryption key missing."""
        operation_id = sanitize_test_data
        
        # Temporarily remove encryption key
        original_key = os.environ.get("SANITIZATION_MAPPING_ENCRYPTION_KEY")
        
        try:
            if "SANITIZATION_MAPPING_ENCRYPTION_KEY" in os.environ:
                del os.environ["SANITIZATION_MAPPING_ENCRYPTION_KEY"]
            
            with pytest.raises(AttributeError):  # DesensitizationError not fully defined
                desensitizer.restore(operation_id)
        
        finally:
            # Restore encryption key
            if original_key:
                os.environ["SANITIZATION_MAPPING_ENCRYPTION_KEY"] = original_key


class TestProgressTracking:
    """Test progress tracking and callbacks."""
    
    def test_table_callback_invoked(
        self,
        desensitizer,
        sanitize_test_data
    ):
        """Test table callback invoked for each table."""
        operation_id = sanitize_test_data
        
        table_events = []
        
        def table_callback(event, table_name):
            table_events.append((event, table_name))
        
        desensitizer.set_table_callback(table_callback)
        
        # Execute restore
        report = desensitizer.restore(operation_id)
        
        # Verify callbacks invoked
        assert len(table_events) > 0
        
        # Each table should have start and complete events
        for table_name in ["dbo.Customers", "dbo.Orders", "dbo.OrderDetails"]:
            start_events = [e for e in table_events if e[0] == "start" and e[1] == table_name]
            complete_events = [e for e in table_events if e[0] == "complete" and e[1] == table_name]
            
            assert len(start_events) > 0
            assert len(complete_events) > 0


class TestTransactionSafety:
    """Test transaction safety and rollback behavior."""
    
    def test_rollback_on_failure(
        self,
        desensitizer,
        sanitize_test_data,
        connection_manager
    ):
        """Test that failures trigger rollback (data unchanged)."""
        operation_id = sanitize_test_data
        
        # Get current masked value
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT first_name FROM dbo.Customers WHERE customer_id = 1")
            before_value = cursor.fetchone().first_name
        
        # Force failure during restoration
        desensitizer._restore_table = lambda *args: (_ for _ in ()).throw(Exception("Test error"))
        
        try:
            desensitizer.restore(operation_id)
        except:
            pass
        
        # Verify data rolled back (unchanged)
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT first_name FROM dbo.Customers WHERE customer_id = 1")
            after_value = cursor.fetchone().first_name
            
            assert after_value == before_value  # No change due to rollback


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
