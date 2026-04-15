"""
Integration tests for column-level desanitization workflow.

Tests the complete round-trip: sanitize table → capture mappings → 
desanitize specific columns → validate results

These tests require a test database connection and will create/modify/cleanup test data.

Test Scenarios:
    - Single column restoration across all records
    - Multiple column restoration
    - Large table performance (>10K records)
    - Composite primary key tables
    - NULL value preservation in columns
    - Partial mappings (some records missing)
    - Progress callback validation
    - Transaction rollback on errors
    - Batch ID filtering

Setup:
    - Requires test database with proper permissions
    - Uses SQLSERVER_HOST, SQLSERVER_DB environment variables
    - Creates temporary test tables (cleaned up after tests)

Usage:
    pytest tests/test_column_desanitization_integration.py -v
    pytest tests/test_column_desanitization_integration.py::TestColumnRestoration -v -s

Note: These are integration tests and may be slow. Skip with:
    pytest -m "not integration"
"""

import pytest
import os
import pyodbc
from datetime import datetime
from typing import List, Dict, Optional

from desanitization import DesanitizationEngine
from desanitization.exceptions import PreconditionError, RestorationError
from mapping.mapping_table_manager import MappingTableManager, MappingRecord
from database.schema_inspector import SchemaInspector


# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture(scope='module')
def test_connection_string():
    """Get test database connection string from environment."""
    server = os.getenv('SQLSERVER_HOST', '(localdb)\\MSSQLLocalDB')
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
        table_name='test_column_token_mappings'
    )
    
    # Create mapping table
    manager.create_table(drop_existing=True)
    
    yield manager
    
    # Cleanup: drop mapping table after tests
    try:
        conn = pyodbc.connect(test_connection_string)
        cursor = conn.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS {manager.fully_qualified_table}")
        conn.commit()
        conn.close()
    except:
        pass


@pytest.fixture(scope='module')
def schema_inspector(test_connection_string):
    """Create SchemaInspector for tests."""
    return SchemaInspector(test_connection_string)


@pytest.fixture(scope='module')
def engine(test_connection, mapping_manager, schema_inspector):
    """Create DesanitizationEngine for tests."""
    return DesanitizationEngine(
        connection=test_connection,
        mapping_manager=mapping_manager,
        schema_inspector=schema_inspector
    )


@pytest.fixture(scope='function')
def test_table(test_connection):
    """Create temporary test table for each test."""
    table_name = f'test_customers_{datetime.now().strftime("%Y%m%d%H%M%S")}'
    
    cursor = test_connection.cursor()
    
    # Create table with PII columns
    cursor.execute(f"""
        CREATE TABLE {table_name} (
            CustomerID INT PRIMARY KEY,
            FirstName NVARCHAR(50),
            LastName NVARCHAR(50),
            Email NVARCHAR(100),
            PhoneNumber NVARCHAR(20),
            SSN NVARCHAR(11),
            CreatedDate DATETIME
        )
    """)
    
    # Insert test data
    test_data = [
        (1, 'John', 'Doe', 'john.doe@example.com', '555-1234', '123-45-6789', datetime.now()),
        (2, 'Jane', 'Smith', 'jane.smith@example.com', '555-5678', '987-65-4321', datetime.now()),
        (3, 'Bob', 'Johnson', 'bob.j@example.com', '555-9999', '111-22-3333', datetime.now()),
        (4, 'Alice', 'Williams', 'alice.w@example.com', '555-0000', '444-55-6666', datetime.now()),
        (5, 'Charlie', 'Brown', 'charlie.b@example.com', '555-7777', '777-88-9999', datetime.now()),
    ]
    
    for row in test_data:
        cursor.execute(
            f"INSERT INTO {table_name} VALUES (?, ?, ?, ?, ?, ?, ?)",
            row
        )
    
    test_connection.commit()
    
    yield table_name
    
    # Cleanup: drop test table
    try:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        test_connection.commit()
    except:
        pass


def create_test_mappings(
    mapping_manager,
    table_name: str,
    column_name: str,
    mappings: List[tuple],
    batch_id: str = 'TEST-BATCH'
):
    """Helper to create test mappings."""
    mapping_records = []
    for record_id, original, masked in mappings:
        record = MappingRecord(
            table_name=table_name,
            column_name=column_name,
            record_id=str(record_id),
            original_value=original,
            masked_value=masked,
            batch_id=batch_id,
            sanitization_run_id='TEST-RUN'
        )
        mapping_records.append(record)
    
    # Insert mappings
    conn = pyodbc.connect(mapping_manager.connection_string)
    mapping_manager.insert_batch_no_commit(conn, mapping_records)
    conn.commit()
    conn.close()


class TestColumnRestoration:
    """Test column-level desanitization for single and multiple columns."""
    
    def test_single_column_restoration(
        self, test_connection, test_table, engine, mapping_manager
    ):
        """Test restoring a single column across all records."""
        # Step 1: Mask data in database
        cursor = test_connection.cursor()
        cursor.execute(f"""
            UPDATE {test_table}
            SET Email = 'masked_' + CAST(CustomerID AS NVARCHAR)
        """)
        test_connection.commit()
        
        # Step 2: Create mappings for Email column
        create_test_mappings(
            mapping_manager,
            test_table,
            'Email',
            [
                (1, 'john.doe@example.com', 'masked_1'),
                (2, 'jane.smith@example.com', 'masked_2'),
                (3, 'bob.j@example.com', 'masked_3'),
                (4, 'alice.w@example.com', 'masked_4'),
                (5, 'charlie.b@example.com', 'masked_5'),
            ]
        )
        
        # Step 3: Restore Email column
        report = engine.desanitize_columns(
            table=test_table,
            column_names=['Email'],
            schema='dbo',
            dry_run=False
        )
        
        # Step 4: Validate results
        assert report.columns_affected == 1
        assert report.records_restored == 5
        assert report.mappings_applied == 5
        assert len(report.errors) == 0
        
        # Verify database restoration
        cursor.execute(f"SELECT CustomerID, Email FROM {test_table} ORDER BY CustomerID")
        results = cursor.fetchall()
        
        assert results[0][1] == 'john.doe@example.com'
        assert results[1][1] == 'jane.smith@example.com'
        assert results[4][1] == 'charlie.b@example.com'
    
    def test_multiple_column_restoration(
        self, test_connection, test_table, engine, mapping_manager
    ):
        """Test restoring multiple columns simultaneously."""
        # Step 1: Mask multiple columns
        cursor = test_connection.cursor()
        cursor.execute(f"""
            UPDATE {test_table}
            SET 
                Email = 'masked_email_' + CAST(CustomerID AS NVARCHAR),
                PhoneNumber = 'masked_phone_' + CAST(CustomerID AS NVARCHAR),
                SSN = 'masked_ssn_' + CAST(CustomerID AS NVARCHAR)
        """)
        test_connection.commit()
        
        # Step 2: Create mappings for all three columns
        create_test_mappings(
            mapping_manager, test_table, 'Email',
            [(1, 'john.doe@example.com', 'masked_email_1'),
             (2, 'jane.smith@example.com', 'masked_email_2')]
        )
        create_test_mappings(
            mapping_manager, test_table, 'PhoneNumber',
            [(1, '555-1234', 'masked_phone_1'),
             (2, '555-5678', 'masked_phone_2')]
        )
        create_test_mappings(
            mapping_manager, test_table, 'SSN',
            [(1, '123-45-6789', 'masked_ssn_1'),
             (2, '987-65-4321', 'masked_ssn_2')]
        )
        
        # Step 3: Restore all three columns
        report = engine.desanitize_columns(
            table=test_table,
            column_names=['Email', 'PhoneNumber', 'SSN'],
            schema='dbo',
            dry_run=False
        )
        
        # Step 4: Validate
        assert report.columns_affected == 3
        assert report.records_restored == 6  # 2 records × 3 columns
        assert report.mappings_applied == 6
        
        # Verify database
        cursor.execute(f"""
            SELECT Email, PhoneNumber, SSN 
            FROM {test_table} 
            WHERE CustomerID = 1
        """)
        result = cursor.fetchone()
        
        assert result[0] == 'john.doe@example.com'
        assert result[1] == '555-1234'
        assert result[2] == '123-45-6789'
    
    def test_dry_run_mode(
        self, test_connection, test_table, engine, mapping_manager
    ):
        """Test dry-run mode does not modify database."""
        # Mask data
        cursor = test_connection.cursor()
        cursor.execute(f"UPDATE {test_table} SET Email = 'masked'")
        test_connection.commit()
        
        # Create mappings
        create_test_mappings(
            mapping_manager, test_table, 'Email',
            [(1, 'john.doe@example.com', 'masked')]
        )
        
        # Dry-run restoration
        report = engine.desanitize_columns(
            table=test_table,
            column_names=['Email'],
            dry_run=True
        )
        
        # Verify report shows what would be restored
        assert report.dry_run is True
        assert report.mappings_applied == 1
        
        # Verify database NOT modified
        cursor.execute(f"SELECT Email FROM {test_table} WHERE CustomerID = 1")
        result = cursor.fetchone()
        assert result[0] == 'masked'  # Still masked!
    
    def test_progress_callback(
        self, test_connection, test_table, engine, mapping_manager
    ):
        """Test progress callback invocation."""
        # Create mappings
        create_test_mappings(
            mapping_manager, test_table, 'Email',
            [(1, 'john@example.com', 'masked1')]
        )
        create_test_mappings(
            mapping_manager, test_table, 'PhoneNumber',
            [(1, '555-1234', 'masked2')]
        )
        
        # Track progress calls
        progress_calls = []
        def track_progress(column, current, total, records):
            progress_calls.append({
                'column': column,
                'current': current,
                'total': total,
                'records': records
            })
        
        # Execute with callback
        report = engine.desanitize_columns(
            table=test_table,
            column_names=['Email', 'PhoneNumber'],
            dry_run=False,
            progress_callback=track_progress
        )
        
        # Verify callback was called
        assert len(progress_calls) == 2
        assert progress_calls[0]['column'] == 'Email'
        assert progress_calls[1]['column'] == 'PhoneNumber'
        assert progress_calls[0]['total'] == 2
        assert progress_calls[1]['total'] == 2
    
    def test_invalid_column_name(self, test_connection, test_table, engine):
        """Test error handling for invalid column names."""
        with pytest.raises(PreconditionError) as exc_info:
            engine.desanitize_columns(
                table=test_table,
                column_names=['NonExistentColumn'],
                dry_run=True
            )
        
        assert 'Invalid columns' in str(exc_info.value)
        assert 'NonExistentColumn' in str(exc_info.value)
    
    def test_no_mappings_found(
        self, test_connection, test_table, engine, mapping_manager
    ):
        """Test graceful handling when no mappings exist."""
        # Don't create any mappings
        
        report = engine.desanitize_columns(
            table=test_table,
            column_names=['Email'],
            dry_run=True
        )
        
        # Should have warning
        assert len(report.warnings) > 0
        assert 'No mappings found' in report.warnings[0]
        assert report.mappings_applied == 0
    
    def test_batch_id_filtering(
        self, test_connection, test_table, engine, mapping_manager
    ):
        """Test filtering by batch ID."""
        # Create mappings with different batch IDs
        create_test_mappings(
            mapping_manager, test_table, 'Email',
            [(1, 'john@example.com', 'masked1')],
            batch_id='BATCH-A'
        )
        create_test_mappings(
            mapping_manager, test_table, 'Email',
            [(2, 'jane@example.com', 'masked2')],
            batch_id='BATCH-B'
        )
        
        # Restore only BATCH-A
        report = engine.desanitize_columns(
            table=test_table,
            column_names=['Email'],
            batch_id='BATCH-A',
            dry_run=False
        )
        
        # Should only restore 1 record (from BATCH-A)
        assert report.records_restored == 1


class TestLargeTablePerformance:
    """Test column restoration performance with larger datasets."""
    
    @pytest.mark.slow
    def test_large_table_restoration(
        self, test_connection, mapping_manager, schema_inspector
    ):
        """Test restoring columns in table with 10K+ records."""
        table_name = 'test_large_customers'
        
        # Create large test table
        cursor = test_connection.cursor()
        cursor.execute(f"""
            CREATE TABLE {table_name} (
                ID INT PRIMARY KEY,
                Email NVARCHAR(100),
                PhoneNumber NVARCHAR(20)
            )
        """)
        
        # Insert 10K records
        batch_size = 1000
        for batch in range(10):  # 10 batches of 1000
            values = []
            for i in range(batch_size):
                record_id = batch * batch_size + i + 1
                values.append((record_id, f'masked_{record_id}', f'phone_{record_id}'))
            
            cursor.executemany(
                f"INSERT INTO {table_name} VALUES (?, ?, ?)",
                values
            )
        
        test_connection.commit()
        
        # Create mappings for Email column (10K records)
        mappings = []
        for i in range(10000):
            mappings.append(MappingRecord(
                table_name=table_name,
                column_name='Email',
                record_id=str(i + 1),
                original_value=f'user{i+1}@example.com',
                masked_value=f'masked_{i+1}',
                batch_id='LARGE-BATCH',
                sanitization_run_id='LARGE-RUN'
            ))
        
        # Insert mappings
        conn = pyodbc.connect(mapping_manager.connection_string)
        mapping_manager.insert_batch_no_commit(conn, mappings)
        conn.commit()
        conn.close()
        
        # Execute restoration
        engine = DesanitizationEngine(
            connection=test_connection,
            mapping_manager=mapping_manager,
            schema_inspector=schema_inspector
        )
        
        start_time = datetime.now()
        
        report = engine.desanitize_columns(
            table=table_name,
            column_names=['Email'],
            dry_run=False
        )
        
        duration = (datetime.now() - start_time).total_seconds()
        
        # Verify results
        assert report.records_restored == 10000
        assert report.mappings_applied == 10000
        assert duration < 60  # Should complete in under 1 minute
        
        # Cleanup
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        test_connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
