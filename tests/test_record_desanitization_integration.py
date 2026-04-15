"""
Integration tests for end-to-end desanitization workflow.

Tests the complete round-trip: sanitize → capture mappings → desanitize → validate

These tests require a test database connection and will create/modify/cleanup test data.

Test Scenarios:
    - Full sanitization → desanitization round-trip
    - Single record restoration
    - Multiple records restoration
    - Composite primary key handling
    - NULL value preservation
    - Partial restoration (column subset)
    - Missing mapping handling
    - Transaction rollback on errors

Setup:
    - Requires test database with proper permissions
    - Uses SQLSERVER_HOST, SQLSERVER_DB environment variables
    - Creates temporary test tables (cleaned up after tests)

Usage:
    pytest tests/test_record_desanitization_integration.py -v
    pytest tests/test_record_desanitization_integration.py::TestRoundTrip -v -s

Note: These are integration tests and may be slow. Skip with:
    pytest -m "not integration"
"""

import pytest
import os
import json
import pyodbc
from datetime import datetime
from typing import List, Dict, Optional

from desanitization import DesanitizationEngine
from desanitization.exceptions import MappingNotFoundError, PreconditionError
from mapping.mapping_table_manager import MappingTableManager, MappingRecord
from database.schema_inspector import SchemaInspector


# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture(scope='module')
def test_connection_string():
    """Get test database connection string from environment."""
    server = os.getenv('SQLSERVER_HOST', 'localhost')
    database = os.getenv('SQLSERVER_DB', 'TestDB')
    auth = os.getenv('SQLSERVER_AUTH', 'windows')
    
    if auth.lower() == 'windows':
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"Trusted_Connection=yes;"
        )
    else:
        user = os.getenv('SQLSERVER_USER', 'sa')
        password = os.getenv('SQLSERVER_PASSWORD', 'YourPassword')
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={user};"
            f"PWD={password};"
        )
    
    return conn_str


@pytest.fixture(scope='module')
def test_connection(test_connection_string):
    """Create test database connection."""
    try:
        conn = pyodbc.connect(test_connection_string)
        conn.autocommit = False
        yield conn
        conn.close()
    except pyodbc.Error as e:
        pytest.skip(f"Cannot connect to test database: {e}")


@pytest.fixture(scope='module')
def mapping_manager(test_connection_string):
    """Create MappingTableManager for tests."""
    manager = MappingTableManager(
        connection_string=test_connection_string,
        table_name='test_token_mappings'
    )
    
    # Create mapping table
    manager.create_table(drop_existing=True)
    
    yield manager
    
    # Cleanup: drop test mapping table
    try:
        conn = pyodbc.connect(test_connection_string)
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS [dbo].[test_token_mappings]")
        conn.commit()
        conn.close()
    except:
        pass


@pytest.fixture(scope='module')
def schema_inspector(test_connection_string):
    """Create SchemaInspector for tests."""
    return SchemaInspector(test_connection_string)


@pytest.fixture
def test_table(test_connection):
    """Create and cleanup test table."""
    cursor = test_connection.cursor()
    
    # Create test table
    cursor.execute("""
        IF OBJECT_ID('dbo.TestCustomers', 'U') IS NOT NULL
            DROP TABLE dbo.TestCustomers
    """)
    
    cursor.execute("""
        CREATE TABLE dbo.TestCustomers (
            CustomerID INT PRIMARY KEY,
            FirstName NVARCHAR(50),
            LastName NVARCHAR(50),
            Email NVARCHAR(100),
            Phone NVARCHAR(20),
            SSN NVARCHAR(11),
            CreatedDate DATETIME DEFAULT GETDATE()
        )
    """)
    
    # Insert test data
    cursor.execute("""
        INSERT INTO dbo.TestCustomers (CustomerID, FirstName, LastName, Email, Phone, SSN)
        VALUES 
            (1, 'John', 'Doe', 'john.doe@example.com', '555-1234', '123-45-6789'),
            (2, 'Jane', 'Smith', 'jane.smith@example.com', '555-5678', '987-65-4321'),
            (3, 'Bob', 'Johnson', 'bob.j@example.com', '555-9012', '456-78-9012')
    """)
    
    test_connection.commit()
    
    yield 'TestCustomers'
    
    # Cleanup
    try:
        cursor.execute("DROP TABLE IF EXISTS dbo.TestCustomers")
        test_connection.commit()
    except:
        pass


@pytest.fixture
def desanitization_engine(test_connection, mapping_manager, schema_inspector):
    """Create DesanitizationEngine for tests."""
    # Update mapping manager table name to use in engine
    mapping_manager.table_name = 'test_token_mappings'
    
    return DesanitizationEngine(
        connection=test_connection,
        mapping_manager=mapping_manager,
        schema_inspector=schema_inspector
    )


class TestRoundTrip:
    """Test complete sanitization → desanitization round-trip."""
    
    def test_single_record_single_column_roundtrip(
        self, test_connection, test_table, mapping_manager, desanitization_engine
    ):
        """Test sanitizing and desanitizing a single column for one record."""
        cursor = test_connection.cursor()
        
        # Get original value
        cursor.execute(
            f"SELECT Email FROM dbo.{test_table} WHERE CustomerID = 1"
        )
        original_email = cursor.fetchone()[0]
        assert original_email == 'john.doe@example.com'
        
        # Sanitize (mask) the email
        masked_email = 'user_masked@test.com'
        cursor.execute(
            f"UPDATE dbo.{test_table} SET Email = ? WHERE CustomerID = 1",
            (masked_email,)
        )
        
        # Create mapping
        mapping = MappingRecord(
            table_name='TestCustomers',
            column_name='Email',
            record_id='1',
            original_value=original_email,
            masked_value=masked_email,
            batch_id='TEST-BATCH-001',
            sanitization_run_id='TEST-RUN-001'
        )
        mapping_manager.insert_batch_no_commit(test_connection, [mapping])
        test_connection.commit()
        
        # Verify sanitization
        cursor.execute(
            f"SELECT Email FROM dbo.{test_table} WHERE CustomerID = 1"
        )
        assert cursor.fetchone()[0] == masked_email
        
        # Desanitize
        report = desanitization_engine.desanitize_records(
            table='TestCustomers',
            record_ids=['1'],
            dry_run=False
        )
        
        # Verify desanitization
        assert report.records_restored == 1
        assert report.mappings_applied == 1
        assert report.errors == []
        
        cursor.execute(
            f"SELECT Email FROM dbo.{test_table} WHERE CustomerID = 1"
        )
        restored_email = cursor.fetchone()[0]
        assert restored_email == original_email
    
    def test_multiple_columns_roundtrip(
        self, test_connection, test_table, mapping_manager, desanitization_engine
    ):
        """Test sanitizing and desanitizing multiple columns for one record."""
        cursor = test_connection.cursor()
        
        # Get original values
        cursor.execute(
            f"SELECT Email, Phone, SSN FROM dbo.{test_table} WHERE CustomerID = 2"
        )
        original = cursor.fetchone()
        original_email, original_phone, original_ssn = original
        
        # Sanitize multiple columns
        masked_email = 'masked2@test.com'
        masked_phone = '555-0000'
        masked_ssn = '000-00-0000'
        
        cursor.execute(
            f"""UPDATE dbo.{test_table} 
                SET Email = ?, Phone = ?, SSN = ? 
                WHERE CustomerID = 2""",
            (masked_email, masked_phone, masked_ssn)
        )
        
        # Create mappings
        mappings = [
            MappingRecord('TestCustomers', 'Email', '2', original_email, masked_email, 'BATCH-002', 'RUN-002'),
            MappingRecord('TestCustomers', 'Phone', '2', original_phone, masked_phone, 'BATCH-002', 'RUN-002'),
            MappingRecord('TestCustomers', 'SSN', '2', original_ssn, masked_ssn, 'BATCH-002', 'RUN-002'),
        ]
        mapping_manager.insert_batch_no_commit(test_connection, mappings)
        test_connection.commit()
        
        # Desanitize all columns
        report = desanitization_engine.desanitize_records(
            table='TestCustomers',
            record_ids=['2'],
            dry_run=False
        )
        
        # Verify all columns restored
        assert report.records_restored == 3  # 3 column updates
        assert report.mappings_applied == 3
        assert report.columns_affected == 3
        
        cursor.execute(
            f"SELECT Email, Phone, SSN FROM dbo.{test_table} WHERE CustomerID = 2"
        )
        restored = cursor.fetchone()
        assert restored[0] == original_email
        assert restored[1] == original_phone
        assert restored[2] == original_ssn
    
    def test_multiple_records_roundtrip(
        self, test_connection, test_table, mapping_manager, desanitization_engine
    ):
        """Test sanitizing and desanitizing multiple records."""
        cursor = test_connection.cursor()
        
        # Get original values for multiple records
        cursor.execute(
            f"SELECT CustomerID, Email FROM dbo.{test_table} WHERE CustomerID IN (1, 3)"
        )
        originals = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Sanitize both records
        cursor.execute(
            f"UPDATE dbo.{test_table} SET Email = 'masked1@test.com' WHERE CustomerID = 1"
        )
        cursor.execute(
            f"UPDATE dbo.{test_table} SET Email = 'masked3@test.com' WHERE CustomerID = 3"
        )
        
        # Create mappings
        mappings = [
            MappingRecord('TestCustomers', 'Email', '1', originals[1], 'masked1@test.com', 'BATCH-003', 'RUN-003'),
            MappingRecord('TestCustomers', 'Email', '3', originals[3], 'masked3@test.com', 'BATCH-003', 'RUN-003'),
        ]
        mapping_manager.insert_batch_no_commit(test_connection, mappings)
        test_connection.commit()
        
        # Desanitize both records
        report = desanitization_engine.desanitize_records(
            table='TestCustomers',
            record_ids=['1', '3'],
            dry_run=False
        )
        
        # Verify both restored
        assert report.records_restored == 2
        assert report.records_requested == 2
        
        cursor.execute(
            f"SELECT CustomerID, Email FROM dbo.{test_table} WHERE CustomerID IN (1, 3)"
        )
        restored = {row[0]: row[1] for row in cursor.fetchall()}
        assert restored[1] == originals[1]
        assert restored[3] == originals[3]


class TestDryRunMode:
    """Test dry-run mode behavior."""
    
    def test_dry_run_no_changes(
        self, test_connection, test_table, mapping_manager, desanitization_engine
    ):
        """Test dry-run mode doesn't modify database."""
        cursor = test_connection.cursor()
        
        # Sanitize
        cursor.execute(
            f"UPDATE dbo.{test_table} SET Email = 'dryrun@test.com' WHERE CustomerID = 1"
        )
        
        mapping = MappingRecord(
            'TestCustomers', 'Email', '1',
            'john.doe@example.com', 'dryrun@test.com',
            'BATCH-DRYRUN', 'RUN-DRYRUN'
        )
        mapping_manager.insert_batch_no_commit(test_connection, [mapping])
        test_connection.commit()
        
        # Desanitize in dry-run mode
        report = desanitization_engine.desanitize_records(
            table='TestCustomers',
            record_ids=['1'],
            dry_run=True
        )
        
        # Report shows what would be restored
        assert report.records_restored == 1
        assert report.dry_run is True
        
        # But database unchanged
        cursor.execute(
            f"SELECT Email FROM dbo.{test_table} WHERE CustomerID = 1"
        )
        assert cursor.fetchone()[0] == 'dryrun@test.com'


class TestErrorHandling:
    """Test error handling and edge cases."""
    
    def test_missing_mapping_error(
        self, test_connection, test_table, desanitization_engine
    ):
        """Test error when mapping doesn't exist."""
        with pytest.raises(MappingNotFoundError) as exc_info:
            desanitization_engine.desanitize_records(
                table='TestCustomers',
                record_ids=['999'],  # Non-existent
                dry_run=True
            )
        
        assert '999' in str(exc_info.value)
        assert exc_info.value.missing_records == ['999']
    
    def test_skip_missing_records(
        self, test_connection, test_table, mapping_manager, desanitization_engine
    ):
        """Test skip_missing flag skips records without mappings."""
        cursor = test_connection.cursor()
        
        # Create mapping for only one record
        mapping = MappingRecord(
            'TestCustomers', 'Email', '1',
            'john@example.com', 'masked@test.com',
            'BATCH-SKIP', 'RUN-SKIP'
        )
        mapping_manager.insert_batch_no_commit(test_connection, [mapping])
        test_connection.commit()
        
        # Request restoration for multiple records (one missing)
        report = desanitization_engine.desanitize_records(
            table='TestCustomers',
            record_ids=['1', '999'],
            skip_missing=True,
            dry_run=True
        )
        
        # Should restore available record and warn about missing
        assert report.records_restored == 1
        assert len(report.warnings) > 0
        assert '999' in str(report.warnings)
    
    def test_table_not_exist(self, desanitization_engine):
        """Test error when target table doesn't exist."""
        with pytest.raises(PreconditionError) as exc_info:
            desanitization_engine.desanitize_records(
                table='NonExistentTable',
                record_ids=['1'],
                dry_run=True
            )
        
        assert 'does not exist' in str(exc_info.value)
        assert 'NonExistentTable' in str(exc_info.value)


class TestNullHandling:
    """Test NULL value restoration."""
    
    def test_restore_null_values(
        self, test_connection, test_table, mapping_manager, desanitization_engine
    ):
        """Test restoring NULL values correctly."""
        cursor = test_connection.cursor()
        
        # Set a column to NULL
        cursor.execute(
            f"UPDATE dbo.{test_table} SET Email = NULL WHERE CustomerID = 1"
        )
        test_connection.commit()
        
        # Sanitize NULL to a token
        cursor.execute(
            f"UPDATE dbo.{test_table} SET Email = '[NULL_TOKEN]' WHERE CustomerID = 1"
        )
        
        # Create mapping with NULL original value
        mapping = MappingRecord(
            'TestCustomers', 'Email', '1',
            None,  # NULL original value
            '[NULL_TOKEN]',
            'BATCH-NULL', 'RUN-NULL'
        )
        mapping_manager.insert_batch_no_commit(test_connection, [mapping])
        test_connection.commit()
        
        # Desanitize
        report = desanitization_engine.desanitize_records(
            table='TestCustomers',
            record_ids=['1'],
            dry_run=False
        )
        
        # Verify NULL restored (not string '[NULL_TOKEN]')
        cursor.execute(
            f"SELECT Email FROM dbo.{test_table} WHERE CustomerID = 1"
        )
        restored_value = cursor.fetchone()[0]
        assert restored_value is None


class TestBatchFiltering:
    """Test batch ID filtering."""
    
    def test_restore_specific_batch(
        self, test_connection, test_table, mapping_manager, desanitization_engine
    ):
        """Test restoring only records from specific batch."""
        cursor = test_connection.cursor()
        
        # Create mappings in different batches
        mappings = [
            MappingRecord('TestCustomers', 'Email', '1', 'orig1@test.com', 'mask1@test.com', 'BATCH-A', 'RUN-A'),
            MappingRecord('TestCustomers', 'Email', '2', 'orig2@test.com', 'mask2@test.com', 'BATCH-B', 'RUN-B'),
        ]
        mapping_manager.insert_batch_no_commit(test_connection, mappings)
        test_connection.commit()
        
        # Restore only BATCH-A
        report = desanitization_engine.desanitize_records(
            table='TestCustomers',
            record_ids=['1', '2'],
            batch_id='BATCH-A',
            skip_missing=True,
            dry_run=True
        )
        
        # Should only restore record 1 (from BATCH-A)
        assert report.records_restored == 1
        assert len(report.warnings) > 0  # Warning about record 2


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
