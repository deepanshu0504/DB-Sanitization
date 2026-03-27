"""
Integration tests for Orchestrator with MappingManager.

These tests validate the complete sanitization workflow with mapping storage,
including schema creation, batch operations, FK integrity, and encryption.

IMPORTANT: These tests require a running SQL Server instance.

Setup:
    Set environment variables before running:
    - SQLSERVER_HOST=localhost
    - SQLSERVER_DB=TestDB
    - SQLSERVER_AUTH=windows|sql
    - SQLSERVER_USER=sa (if SQL auth)
    - SQLSERVER_PASS=YourPassword (if SQL auth)

Run:
    pytest tests/integration/test_orchestrator_mapping_integration.py -v

Author: Database Sanitization Team
Date: 2026-03-27
"""

import pytest
import os
from uuid import UUID
import time

from src.config.config_models import (
    SanitizationConfig,
    DatabaseConfig,
    PIIColumnConfig,
    MaskingStrategy
)
from src.mapping.mapping_config import MappingConfig
from src.sanitization.orchestrator import SanitizationOrchestrator
from src.database.connection_manager import DatabaseConnectionManager

from tests.integration.mapping_test_helpers import (
    get_test_db_config,
    cleanup_mapping_tables,
    verify_mapping_integrity,
    setup_encryption_key,
    cleanup_encryption_key
)


# Mark all tests to run with --integration flag
pytestmark = pytest.mark.integration


# ==================== Fixtures ====================


@pytest.fixture(scope="module")
def connection_manager():
    """Create connection manager for all tests."""
    config = get_test_db_config()
    manager = DatabaseConnectionManager(config)
    yield manager


@pytest.fixture(scope="function")
def test_db_schema(connection_manager):
    """Create test database schema for each test."""
    # Create test tables with FK relationships
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        
        # Clean up if exists
        cursor.execute("""
            IF OBJECT_ID('dbo.TestOrders', 'U') IS NOT NULL 
                DROP TABLE dbo.TestOrders;
            IF OBJECT_ID('dbo.TestCustomers', 'U') IS NOT NULL 
                DROP TABLE dbo.TestCustomers;
        """)
        
        # Create parent table (Customers)
        cursor.execute("""
            CREATE TABLE dbo.TestCustomers (
                CustomerID INT IDENTITY(1,1) PRIMARY KEY,
                Email VARCHAR(255) NOT NULL,
                Phone VARCHAR(50),
                FirstName VARCHAR(100),
                LastName VARCHAR(100)
            );
        """)
        
        # Create child table (Orders)
        cursor.execute("""
            CREATE TABLE dbo.TestOrders (
                OrderID INT IDENTITY(1,1) PRIMARY KEY,
                CustomerID INT NOT NULL,
                OrderDate DATETIME DEFAULT GETDATE(),
                ShipToAddress VARCHAR(500),
                CONSTRAINT FK_Orders_Customers 
                    FOREIGN KEY (CustomerID) 
                    REFERENCES dbo.TestCustomers(CustomerID)
            );
        """)
        
        # Insert test data
        cursor.execute("""
            INSERT INTO dbo.TestCustomers (Email, Phone, FirstName, LastName)
            VALUES 
                ('alice@company.com', '555-1234', 'Alice', 'Smith'),
                ('bob@company.com', '555-5678', 'Bob', 'Jones'),
                ('charlie@company.com', '555-9012', 'Charlie', 'Brown')
        """)
        
        cursor.execute("""
            INSERT INTO dbo.TestOrders (CustomerID, ShipToAddress)
            VALUES 
                (1, '123 Main St, City, ST 12345'),
                (1, '456 Oak Ave, City, ST 67890'),
                (2, '789 Elm St, City, ST 11111'),
                (3, '321 Pine Rd, City, ST 22222')
        """)
        
        conn.commit()
        cursor.close()
    
    yield
    
    # Cleanup
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("DROP TABLE IF EXISTS dbo.TestOrders")
            cursor.execute("DROP TABLE IF EXISTS dbo.TestCustomers")
            conn.commit()
        except Exception:
            pass
        finally:
            cursor.close()


# ==================== Tests ====================


class TestOrchestratorWithMapping:
    """Test orchestrator with mapping storage enabled."""
    
    def test_sanitize_with_mapping_enabled(self, connection_manager, test_db_schema):
        """Test complete sanitization workflow with mapping storage."""
        # Create configuration
        config = SanitizationConfig(
            database=DatabaseConfig(
                server=os.getenv("SQLSERVER_HOST"),
                database=os.getenv("SQLSERVER_DB", "TestDB"),
                auth_type="windows" if os.getenv("SQLSERVER_AUTH") == "windows" else "sql",
                username=os.getenv("SQLSERVER_USER") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                password=os.getenv("SQLSERVER_PASS") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                batch_size=10
            ),
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="TestCustomers",
                    column="Email",
                    pii_type="email",
                    nullable=False
                ),
                PIIColumnConfig(
                    schema="dbo",
                    table="TestCustomers",
                    column="Phone",
                    pii_type="phone",
                    nullable=True
                ),
                PIIColumnConfig(
                    schema="dbo",
                    table="TestOrders",
                    column="ShipToAddress",
                    pii_type="generic",
                    nullable=True
                )
            ],
            mapping=MappingConfig(
                enabled=True,
                schema_name="test_sanitization",
                table_name="test_pii_mappings",
                encryption_enabled=False,
                batch_size=10
            ),
            validate_before=False,
            validate_after=False
        )
        
        # Create orchestrator
        orchestrator = SanitizationOrchestrator(connection_manager=connection_manager)
        
        # Run sanitization
        report = orchestrator.run(config, dry_run=False)
        
        # Verify report
        assert report.is_successful, f"Sanitization failed: {report.errors}"
        assert report.tables_processed >= 2  # At least Customers and Orders
        assert report.rows_processed >= 7  # 3 customers + 4 orders
        assert report.mappings_stored > 0, "No mappings were stored"
        
        # Verify mapping table integrity
        operation_id = UUID(report.operation_id)
        is_valid, errors = verify_mapping_integrity(
            connection_manager,
            "test_sanitization",
            "test_pii_mappings",
            operation_id,
            expected_count=report.mappings_stored
        )
        assert is_valid, f"Mapping integrity check failed: {errors}"
        
        # Verify original values were masked
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT Email FROM dbo.TestCustomers WHERE Email LIKE '%@company.com'")
            original_emails = cursor.fetchall()
            assert len(original_emails) == 0, "Original emails still exist"
            
            cursor.execute("SELECT Email FROM dbo.TestCustomers")
            masked_emails = cursor.fetchall()
            assert len(masked_emails) == 3, "Not all emails were masked"
            cursor.close()
        
        # Cleanup
        cleanup_mapping_tables(connection_manager, "test_sanitization")
    
    def test_sanitize_with_mapping_disabled(self, connection_manager, test_db_schema):
        """Test that mapping table is not created when disabled."""
        config = SanitizationConfig(
            database=DatabaseConfig(
                server=os.getenv("SQLSERVER_HOST"),
                database=os.getenv("SQLSERVER_DB", "TestDB"),
                auth_type="windows" if os.getenv("SQLSERVER_AUTH") == "windows" else "sql",
                username=os.getenv("SQLSERVER_USER") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                password=os.getenv("SQLSERVER_PASS") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                batch_size=10
            ),
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="TestCustomers",
                    column="Email",
                    pii_type="email",
                    nullable=False
                )
            ],
            mapping=MappingConfig(enabled=False),  # Mapping disabled
            validate_before=False
        )
        
        orchestrator = SanitizationOrchestrator(connection_manager=connection_manager)
        
        # Run sanitization
        report = orchestrator.run(config, dry_run=False)
        
        # Verify success
        assert report.is_successful
        assert report.mappings_stored == 0, "No mappings should be stored when disabled"
        
        # Verify mapping table does not exist
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM sys.tables t
                JOIN sys.schemas s ON t.schema_id = s.schema_id
                WHERE s.name = 'test_sanitization' 
                AND t.name = 'test_pii_mappings'
            """)
            table_count = cursor.fetchone()[0]
            cursor.close()
        
        assert table_count == 0, "Mapping table should not exist"
    
    def test_sanitize_with_encryption(self, connection_manager, test_db_schema):
        """Test sanitization with encrypted mapping storage."""
        # Setup encryption key
        encryption_key = setup_encryption_key()
        
        try:
            config = SanitizationConfig(
                database=DatabaseConfig(
                    server=os.getenv("SQLSERVER_HOST"),
                    database=os.getenv("SQLSERVER_DB", "TestDB"),
                    auth_type="windows" if os.getenv("SQLSERVER_AUTH") == "windows" else "sql",
                    username=os.getenv("SQLSERVER_USER") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                    password=os.getenv("SQLSERVER_PASS") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                    batch_size=10
                ),
                pii_columns=[
                    PIIColumnConfig(
                        schema="dbo",
                        table="TestCustomers",
                        column="Email",
                        pii_type="email",
                        nullable=False
                    )
                ],
                mapping=MappingConfig(
                    enabled=True,
                    schema_name="test_sanitization",
                    table_name="test_pii_mappings_encrypted",
                    encryption_enabled=True,  # Encryption enabled
                    batch_size=10
                ),
                validate_before=False
            )
            
            orchestrator = SanitizationOrchestrator(connection_manager=connection_manager)
            report = orchestrator.run(config, dry_run=False)
            
            # Verify success
            assert report.is_successful
            assert report.mappings_stored > 0
            
            # Verify encrypted values are stored
            with connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM [test_sanitization].[test_pii_mappings_encrypted]
                    WHERE original_value_encrypted IS NOT NULL
                """)
                encrypted_count = cursor.fetchone()[0]
                cursor.close()
            
            assert encrypted_count > 0, "No encrypted values found"
            
            # Cleanup
            cleanup_mapping_tables(connection_manager, "test_sanitization", "test_pii_mappings_encrypted")
        
        finally:
            cleanup_encryption_key()
    
    def test_mapping_entry_count_matches_masked_values(self, connection_manager, test_db_schema):
        """Test that mapping entries match the number of masked values."""
        config = SanitizationConfig(
            database=DatabaseConfig(
                server=os.getenv("SQLSERVER_HOST"),
                database=os.getenv("SQLSERVER_DB", "TestDB"),
                auth_type="windows" if os.getenv("SQLSERVER_AUTH") == "windows" else "sql",
                username=os.getenv("SQLSERVER_USER") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                password=os.getenv("SQLSERVER_PASS") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                batch_size=10
            ),
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="TestCustomers",
                    column="Email",
                    pii_type="email",
                    nullable=False
                ),
                PIIColumnConfig(
                    schema="dbo",
                    table="TestCustomers",
                    column="Phone",
                    pii_type="phone",
                    nullable=True
                )
            ],
            mapping=MappingConfig(
                enabled=True,
                schema_name="test_sanitization",
                table_name="test_pii_mappings",
                batch_size=10
            ),
            validate_before=False
        )
        
        orchestrator = SanitizationOrchestrator(connection_manager=connection_manager)
        report = orchestrator.run(config, dry_run=False)
        
        # Count actual rows
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM dbo.TestCustomers")
            customer_count = cursor.fetchone()[0]
            cursor.close()
        
        # Expected mappings: customers * 2 columns (Email + Phone)
        expected_mappings = customer_count * 2
        
        assert report.mappings_stored == expected_mappings, \
            f"Expected {expected_mappings} mappings, got {report.mappings_stored}"
        
        # Cleanup
        cleanup_mapping_tables(connection_manager, "test_sanitization")
    
    def test_mapping_consistency_across_tables(self, connection_manager, test_db_schema):
        """Test that mappings are stored for all tables correctly."""
        config = SanitizationConfig(
            database=DatabaseConfig(
                server=os.getenv("SQLSERVER_HOST"),
                database=os.getenv("SQLSERVER_DB", "TestDB"),
                auth_type="windows" if os.getenv("SQLSERVER_AUTH") == "windows" else "sql",
                username=os.getenv("SQLSERVER_USER") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                password=os.getenv("SQLSERVER_PASS") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                batch_size=10
            ),
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="TestCustomers",
                    column="Email",
                    pii_type="email",
                    nullable=False
                ),
                PIIColumnConfig(
                    schema="dbo",
                    table="TestOrders",
                    column="ShipToAddress",
                    pii_type="generic",
                    nullable=True
                )
            ],
            mapping=MappingConfig(
                enabled=True,
                schema_name="test_sanitization",
                table_name="test_pii_mappings",
                batch_size=10
            ),
            validate_before=False
        )
        
        orchestrator = SanitizationOrchestrator(connection_manager=connection_manager)
        report = orchestrator.run(config, dry_run=False)
        
        assert report.is_successful
        operation_id = report.operation_id
        
        # Query mappings by table
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check Customers mappings
            cursor.execute("""
                SELECT COUNT(*) 
                FROM [test_sanitization].[test_pii_mappings]
                WHERE operation_id = ?
                AND table_name = 'TestCustomers'
            """, (operation_id,))
            customer_mappings = cursor.fetchone()[0]
            
            # Check Orders mappings
            cursor.execute("""
                SELECT COUNT(*) 
                FROM [test_sanitization].[test_pii_mappings]
                WHERE operation_id = ?
                AND table_name = 'TestOrders'
            """, (operation_id,))
            order_mappings = cursor.fetchone()[0]
            
            cursor.close()
        
        assert customer_mappings > 0, "No mappings for TestCustomers"
        assert order_mappings > 0, "No mappings for TestOrders"
        assert customer_mappings + order_mappings == report.mappings_stored
        
        # Cleanup
        cleanup_mapping_tables(connection_manager, "test_sanitization")
    
    def test_fk_integrity_maintained_with_mapping(self, connection_manager, test_db_schema):
        """Test that FK integrity is maintained when mapping is enabled."""
        config = SanitizationConfig(
            database=DatabaseConfig(
                server=os.getenv("SQLSERVER_HOST"),
                database=os.getenv("SQLSERVER_DB", "TestDB"),
                auth_type="windows" if os.getenv("SQLSERVER_AUTH") == "windows" else "sql",
                username=os.getenv("SQLSERVER_USER") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                password=os.getenv("SQLSERVER_PASS") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                batch_size=10
            ),
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="TestCustomers",
                    column="Email",
                    pii_type="email",
                    nullable=False
                )
            ],
            mapping=MappingConfig(
                enabled=True,
                schema_name="test_sanitization",
                table_name="test_pii_mappings",
                batch_size=10
            ),
            validate_before=False
        )
        
        orchestrator = SanitizationOrchestrator(connection_manager=connection_manager)
        report = orchestrator.run(config, dry_run=False)
        
        assert report.is_successful
        
        # Verify FK integrity - no orphaned orders
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) 
                FROM dbo.TestOrders o
                LEFT JOIN dbo.TestCustomers c ON o.CustomerID = c.CustomerID
                WHERE c.CustomerID IS NULL
            """)
            orphan_count = cursor.fetchone()[0]
            cursor.close()
        
        assert orphan_count == 0, f"Found {orphan_count} orphaned orders"
        
        # Cleanup
        cleanup_mapping_tables(connection_manager, "test_sanitization")


class TestOrchestratorDryRun:
    """Test dry-run mode with mapping."""
    
    def test_dry_run_does_not_create_mappings(self, connection_manager, test_db_schema):
        """Test that dry-run does not create mapping entries."""
        config = SanitizationConfig(
            database=DatabaseConfig(
                server=os.getenv("SQLSERVER_HOST"),
                database=os.getenv("SQLSERVER_DB", "TestDB"),
                auth_type="windows" if os.getenv("SQLSERVER_AUTH") == "windows" else "sql",
                username=os.getenv("SQLSERVER_USER") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                password=os.getenv("SQLSERVER_PASS") if os.getenv("SQLSERVER_AUTH") == "sql" else None,
                batch_size=10
            ),
            pii_columns=[
                PIIColumnConfig(
                    schema="dbo",
                    table="TestCustomers",
                    column="Email",
                    pii_type="email",
                    nullable=False
                )
            ],
            mapping=MappingConfig(
                enabled=True,
                schema_name="test_sanitization",
                table_name="test_pii_mappings",
                batch_size=10
            ),
            validate_before=False
        )
        
        orchestrator = SanitizationOrchestrator(connection_manager=connection_manager)
        
        # Run in dry-run mode
        report = orchestrator.run(config, dry_run=True)
        
        # Verify no mappings stored
        assert report.mappings_stored == 0, "Dry-run should not store mappings"
        
        # Verify original data unchanged
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM dbo.TestCustomers WHERE Email LIKE '%@company.com'")
            original_count = cursor.fetchone()[0]
            cursor.close()
        
        assert original_count == 3, "Original data should be unchanged in dry-run"
        
        # Cleanup (should be nothing, but be safe)
        try:
            cleanup_mapping_tables(connection_manager, "test_sanitization")
        except Exception:
            pass
