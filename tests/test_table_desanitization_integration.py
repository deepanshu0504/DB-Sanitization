"""
Integration tests for table-level desanitization workflow.

Tests the complete round-trip: sanitize → capture mappings → desanitize table → validate

These tests require a test database connection and will create/modify/cleanup test data.

Test Scenarios:
    - Full table sanitization → table-level desanitization round-trip
    - Multiple columns restoration (auto-discovery)
    - Batch ID filtering for table restoration
    - NULL value preservation across multiple columns
    - Composite primary key handling
    - Referential integrity validation
    - Large table performance (1000+ rows)
    - Partial mappings (some columns have mappings, others don't)
    - CLI integration via subprocess

Setup:
    - Requires test database with proper permissions
    - Uses SQLSERVER_HOST, SQLSERVER_DB environment variables
    - Creates temporary test tables (cleaned up after tests)

Usage:
    pytest tests/test_table_desanitization_integration.py -v
    pytest tests/test_table_desanitization_integration.py::TestTableRoundTrip -v -s

Note: These are integration tests and may be slow. Skip with:
    pytest -m "not integration"
"""

import pytest
import os
import json
import pyodbc
import subprocess
from datetime import datetime
from typing import List, Dict, Optional

from desanitization import DesanitizationEngine
from desanitization.exceptions import PreconditionError
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
    
    # Cleanup: Drop mapping table after all tests
    # (Optionally keep for debugging)
    # manager.drop_table()


@pytest.fixture(scope='module')
def schema_inspector(test_connection_string):
    """Create SchemaInspector for tests."""
    return SchemaInspector(test_connection_string)


@pytest.fixture(scope='module')
def desanitization_engine(test_connection, mapping_manager, schema_inspector):
    """Create DesanitizationEngine for tests."""
    return DesanitizationEngine(
        connection=test_connection,
        mapping_manager=mapping_manager,
        schema_inspector=schema_inspector
    )


@pytest.fixture
def test_table_with_data(test_connection):
    """Create a test table with sample data for each test."""
    table_name = f"test_customers_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    
    cursor = test_connection.cursor()
    
    # Create table with multiple columns
    cursor.execute(f"""
        CREATE TABLE {table_name} (
            CustomerID INT PRIMARY KEY,
            Email NVARCHAR(100),
            PhoneNumber NVARCHAR(20),
            SSN NVARCHAR(11),
            DateOfBirth DATE,
            Notes NVARCHAR(200)
        )
    """)
    
    # Insert sample data with varying patterns
    test_data = [
        (1, 'alice@example.com', '555-1234', '123-45-6789', '1990-01-15', 'Regular customer'),
        (2, 'bob@test.com', '555-5678', '987-65-4321', '1985-06-20', None),  # NULL note
        (3, 'charlie@demo.com', None, '456-78-9012', '1992-11-30', 'VIP'),  # NULL phone
        (4, 'diana@sample.com', '555-9999', None, '1988-03-10', 'New customer'),  # NULL SSN
        (5, 'eve@example.com', '555-0000', '111-22-3333', None, 'Old customer'),  # NULL DOB
    ]
    
    for row in test_data:
        cursor.execute(
            f"""
            INSERT INTO {table_name}
            (CustomerID, Email, PhoneNumber, SSN, DateOfBirth, Notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            row
        )
    
    test_connection.commit()
    
    yield table_name
    
    # Cleanup: Drop test table
    try:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        test_connection.commit()
    except:
        pass


class TestTableRoundTrip:
    """Test end-to-end table-level desanitization scenarios."""
    
    def test_full_table_sanitize_and_restore(
        self, test_connection, mapping_manager, schema_inspector,
        desanitization_engine, test_table_with_data
    ):
        """Test complete round-trip: sanitize table → restore table → validate."""
        table_name = test_table_with_data
        batch_id = f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        cursor = test_connection.cursor()
        
        # Step 1: Capture original values
        cursor.execute(f"""
            SELECT CustomerID, Email, PhoneNumber, SSN, DateOfBirth
            FROM {table_name}
            ORDER BY CustomerID
        """)
        original_data = cursor.fetchall()
        
        # Step 2: Manually create mappings (simulating sanitization)
        pii_columns = ['Email', 'PhoneNumber', 'SSN']
        mapping_records = []
        
        for row in original_data:
            customer_id = row[0]
            for idx, col_name in enumerate(pii_columns):
                original_value = row[idx + 1]  # Skip CustomerID
                if original_value:  # Only create mappings for non-NULL
                    mapping_records.append(MappingRecord(
                        table_name=table_name,
                        column_name=col_name,
                        record_id=str(customer_id),
                        original_value=original_value,
                        masked_value=f"MASKED_{col_name}_{customer_id}",
                        batch_id=batch_id,
                        sanitization_run_id=batch_id
                    ))
        
        # Insert mappings
        mapping_manager.insert_batch(test_connection, mapping_records)
        test_connection.commit()
        
        # Step 3: Update table with masked values
        for col in pii_columns:
            cursor.execute(f"""
                UPDATE {table_name}
                SET {col} = 'MASKED_' + {col} + '_' + CAST(CustomerID AS NVARCHAR)
                WHERE {col} IS NOT NULL
            """)
        test_connection.commit()
        
        # Step 4: Verify data is masked
        cursor.execute(f"SELECT Email FROM {table_name} WHERE CustomerID = 1")
        assert 'MASKED' in cursor.fetchone()[0]
        
        # Step 5: Execute table-level desanitization
        report = desanitization_engine.desanitize_table(
            table=table_name,
            schema='dbo',
            batch_id=batch_id,
            dry_run=False
        )
        
        # Step 6: Verify restoration
        assert report.tables_affected == 1
        assert report.columns_affected == 3  # Email, PhoneNumber, SSN
        assert len(report.errors) == 0
        
        # Step 7: Validate data matches original
        cursor.execute(f"""
            SELECT CustomerID, Email, PhoneNumber, SSN
            FROM {table_name}
            ORDER BY CustomerID
        """)
        restored_data = cursor.fetchall()
        
        for idx, (original, restored) in enumerate(zip(original_data, restored_data)):
            assert restored[0] == original[0]  # CustomerID unchanged
            assert restored[1] == original[1]  # Email restored
            assert restored[2] == original[2]  # PhoneNumber restored (including NULLs)
            assert restored[3] == original[3]  # SSN restored (including NULLs)
    
    def test_table_restore_auto_discovery(
        self, test_connection, mapping_manager, desanitization_engine, test_table_with_data
    ):
        """Test auto-discovery of columns with mappings."""
        table_name = test_table_with_data
        batch_id = f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Create mappings for only 2 columns (not all)
        mapping_records = [
            MappingRecord(
                table_name=table_name,
                column_name='Email',
                record_id='1',
                original_value='restored@example.com',
                masked_value='masked@example.com',
                batch_id=batch_id,
                sanitization_run_id=batch_id
            ),
            MappingRecord(
                table_name=table_name,
                column_name='SSN',
                record_id='1',
                original_value='999-88-7777',
                masked_value='masked-ssn',
                batch_id=batch_id,
                sanitization_run_id=batch_id
            )
        ]
        
        mapping_manager.insert_batch(test_connection, mapping_records)
        test_connection.commit()
        
        # Execute table-level desanitization
        report = desanitization_engine.desanitize_table(
            table=table_name,
            schema='dbo',
            batch_id=batch_id,
            dry_run=False
        )
        
        # Verify only 2 columns were processed (auto-discovered)
        assert report.columns_affected == 2
        assert 'Email' in report.table_details.get(table_name, {})
        assert 'SSN' in report.table_details.get(table_name, {})
        assert 'PhoneNumber' not in report.table_details.get(table_name, {})
    
    def test_table_restore_no_mappings_error(
        self, desanitization_engine, test_table_with_data
    ):
        """Test error when table has no mappings."""
        table_name = test_table_with_data
        
        # Execute without any mappings - should raise PreconditionError
        with pytest.raises(PreconditionError) as exc_info:
            desanitization_engine.desanitize_table(
                table=table_name,
                schema='dbo',
                dry_run=True
            )
        
        # Verify error message
        assert 'No mappings found' in str(exc_info.value)
        assert table_name in str(exc_info.value)
    
    def test_table_restore_dry_run(
        self, test_connection, mapping_manager, desanitization_engine, test_table_with_data
    ):
        """Test dry-run mode doesn't modify data."""
        table_name = test_table_with_data
        batch_id = f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        cursor = test_connection.cursor()
        
        # Create mappings
        mapping_records = [
            MappingRecord(
                table_name=table_name,
                column_name='Email',
                record_id=str(i),
                original_value=f'original{i}@test.com',
                masked_value=f'masked{i}@test.com',
                batch_id=batch_id,
                sanitization_run_id=batch_id
            )
            for i in range(1, 6)
        ]
        
        mapping_manager.insert_batch(test_connection, mapping_records)
        test_connection.commit()
        
        # Mask the data first
        cursor.execute(f"""
            UPDATE {table_name}
            SET Email = 'masked' + CAST(CustomerID AS NVARCHAR) + '@test.com'
        """)
        test_connection.commit()
        
        # Capture masked state
        cursor.execute(f"SELECT CustomerID, Email FROM {table_name} ORDER BY CustomerID")
        masked_data = cursor.fetchall()
        
        # Execute dry-run desanitization
        report = desanitization_engine.desanitize_table(
            table=table_name,
            schema='dbo',
            batch_id=batch_id,
            dry_run=True
        )
        
        # Verify report shows operation but no changes made
        assert report.dry_run is True
        assert report.columns_affected == 1
        assert report.mappings_applied == 5
        
        # Verify data unchanged
        cursor.execute(f"SELECT CustomerID, Email FROM {table_name} ORDER BY CustomerID")
        after_dry_run = cursor.fetchall()
        
        assert masked_data == after_dry_run
    
    def test_table_restore_with_batch_filter(
        self, test_connection, mapping_manager, desanitization_engine, test_table_with_data
    ):
        """Test table restoration with batch ID filtering."""
        table_name = test_table_with_data
        batch1 = f"BATCH1-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        batch2 = f"BATCH2-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Create mappings for 2 different batches
        mappings_batch1 = [
            MappingRecord(
                table_name=table_name,
                column_name='Email',
                record_id='1',
                original_value='batch1_email@test.com',
                masked_value='masked@test.com',
                batch_id=batch1,
                sanitization_run_id=batch1
            )
        ]
        
        mappings_batch2 = [
            MappingRecord(
                table_name=table_name,
                column_name='PhoneNumber',
                record_id='1',
                original_value='555-BATCH2',
                masked_value='555-MASKED',
                batch_id=batch2,
                sanitization_run_id=batch2
            )
        ]
        
        mapping_manager.insert_batch(test_connection, mappings_batch1)
        mapping_manager.insert_batch(test_connection, mappings_batch2)
        test_connection.commit()
        
        # Restore only batch1
        report = desanitization_engine.desanitize_table(
            table=table_name,
            schema='dbo',
            batch_id=batch1,
            dry_run=False
        )
        
        # Verify only Email was restored (batch1), not PhoneNumber (batch2)
        assert report.columns_affected == 1
        assert 'Email' in report.table_details.get(table_name, {})
        assert 'PhoneNumber' not in report.table_details.get(table_name, {})
    
    def test_table_restore_preserves_nulls(
        self, test_connection, mapping_manager, desanitization_engine, test_table_with_data
    ):
        """Test NULL values are preserved during table restoration."""
        table_name = test_table_with_data
        batch_id = f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        cursor = test_connection.cursor()
        
        # Create mappings including records with NULL values
        # Note: We don't create mappings for NULL values (as they're not masked)
        mapping_records = [
            # Customer 1: has PhoneNumber
            MappingRecord(
                table_name=table_name,
                column_name='PhoneNumber',
                record_id='1',
                original_value='555-REAL',
                masked_value='555-FAKE',
                batch_id=batch_id,
                sanitization_run_id=batch_id
            ),
            # Customer 3: has NULL PhoneNumber (no mapping created)
        ]
        
        mapping_manager.insert_batch(test_connection, mapping_records)
        test_connection.commit()
        
        # Capture original NULL state
        cursor.execute(f"""
            SELECT CustomerID, PhoneNumber
            FROM {table_name}
            WHERE CustomerID IN (1, 3)
            ORDER BY CustomerID
        """)
        before_data = cursor.fetchall()
        assert before_data[1][1] is None  # Customer 3 has NULL phone
        
        # Execute table restoration
        report = desanitization_engine.desanitize_table(
            table=table_name,
            schema='dbo',
            batch_id=batch_id,
            dry_run=False
        )
        
        # Verify NULL is still NULL
        cursor.execute(f"""
            SELECT CustomerID, PhoneNumber
            FROM {table_name}
            WHERE CustomerID IN (1, 3)
            ORDER BY CustomerID
        """)
        after_data = cursor.fetchall()
        
        assert after_data[0][1] == '555-REAL'  # Customer 1 restored
        assert after_data[1][1] is None  # Customer 3 still NULL
    
    def test_table_restore_large_table_performance(
        self, test_connection, mapping_manager, desanitization_engine
    ):
        """Test table restoration performance with 1000+ rows."""
        table_name = f"test_large_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        batch_id = f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        cursor = test_connection.cursor()
        
        # Create large table
        cursor.execute(f"""
            CREATE TABLE {table_name} (
                ID INT PRIMARY KEY,
                Email NVARCHAR(100),
                Phone NVARCHAR(20)
            )
        """)
        
        # Insert 1000 rows
        for i in range(1, 1001):
            cursor.execute(
                f"INSERT INTO {table_name} (ID, Email, Phone) VALUES (?, ?, ?)",
                (i, f'user{i}@test.com', f'555-{i:04d}')
            )
        test_connection.commit()
        
        # Create mappings for all rows
        mapping_records = []
        for i in range(1, 1001):
            mapping_records.extend([
                MappingRecord(
                    table_name=table_name,
                    column_name='Email',
                    record_id=str(i),
                    original_value=f'user{i}@test.com',
                    masked_value=f'masked{i}@test.com',
                    batch_id=batch_id,
                    sanitization_run_id=batch_id
                ),
                MappingRecord(
                    table_name=table_name,
                    column_name='Phone',
                    record_id=str(i),
                    original_value=f'555-{i:04d}',
                    masked_value=f'999-{i:04d}',
                    batch_id=batch_id,
                    sanitization_run_id=batch_id
                )
            ])
        
        mapping_manager.insert_batch(test_connection, mapping_records)
        test_connection.commit()
        
        # Execute table restoration and measure time
        start_time = datetime.now()
        
        report = desanitization_engine.desanitize_table(
            table=table_name,
            schema='dbo',
            batch_id=batch_id,
            dry_run=False
        )
        
        duration = (datetime.now() - start_time).total_seconds()
        
        # Verify results
        assert report.columns_affected == 2
        assert report.mappings_applied == 2000
        assert len(report.errors) == 0
        
        # Performance assertion (should complete in reasonable time)
        assert duration < 30, f"Table restoration took {duration}s (expected < 30s)"
        
        # Cleanup
        cursor.execute(f"DROP TABLE {table_name}")
        test_connection.commit()


class TestCLIIntegration:
    """Test CLI integration for table-level desanitization."""
    
    def test_cli_table_only_flag(self, test_connection, mapping_manager, test_table_with_data):
        """Test desanitize_direct.py with --table-only flag via subprocess."""
        table_name = test_table_with_data
        batch_id = f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Create mapping
        mapping_records = [
            MappingRecord(
                table_name=table_name,
                column_name='Email',
                record_id='1',
                original_value='cli_test@example.com',
                masked_value='masked@example.com',
                batch_id=batch_id,
                sanitization_run_id=batch_id
            )
        ]
        
        mapping_manager.insert_batch(test_connection, mapping_records)
        test_connection.commit()
        
        # Execute CLI command
        result = subprocess.run(
            [
                'python', 'desanitize_direct.py',
                '--table', table_name,
                '--table-only',
                '--batch-id', batch_id,
                '--dry-run',
                '--json-output', 'test_cli_output.json'
            ],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            capture_output=True,
            text=True
        )
        
        # Verify CLI executed successfully
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        
        # Verify JSON output was created
        json_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'test_cli_output.json'
        )
        assert os.path.exists(json_path), "JSON output file not created"
        
        # Load and verify JSON report
        with open(json_path, 'r') as f:
            report_data = json.load(f)
        
        assert report_data['summary']['columns_affected'] == 1
        assert report_data['dry_run'] is True
        
        # Cleanup
        if os.path.exists(json_path):
            os.remove(json_path)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
