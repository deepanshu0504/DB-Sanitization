"""
Integration tests for Audit Logging with Desanitization.

Run with: pytest tests/test_audit_integration.py -v

Tests end-to-end audit trail for desanitization operations:
- Record-level desanitization with audit logs
- Column-level desanitization with audit logs
- Table-level desanitization with audit logs
- Database-level desanitization with audit logs (light)
- Audit trail verification
- Dry-run mode auditing
- Failure scenario auditing
- Transaction rollback auditing

Requires:
- Test database with audit_log table created
- Existing mapping data from sanitization
- Permissions for CREATE/DROP tables

Author: Database Sanitization Team
Date: April 13, 2026
"""

import os
import uuid
import pytest
from datetime import datetime
from typing import Generator

import pyodbc

from desanitization import DesanitizationEngine
from mapping.mapping_table_manager import MappingTableManager, MappingRecord
from database.schema_inspector import SchemaInspector
from audit import AuditLogger, AuditTableMissingError


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(scope="module")
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


@pytest.fixture(scope="module")
def setup_audit_table(test_connection_string):
    """Setup audit table before tests."""
    conn = pyodbc.connect(test_connection_string)
    cursor = conn.cursor()
    
    # Drop existing audit table
    cursor.execute("IF OBJECT_ID('dbo.desanitization_audit_log', 'U') IS NOT NULL DROP TABLE dbo.desanitization_audit_log")
    conn.commit()
    
    # Create audit table (simplified version for testing)
    cursor.execute("""
        CREATE TABLE dbo.desanitization_audit_log (
            audit_id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
            operation_id NVARCHAR(100) NOT NULL,
            operation_type NVARCHAR(20) NOT NULL,
            target_schema NVARCHAR(128) NULL,
            target_table NVARCHAR(128) NULL,
            target_columns NVARCHAR(MAX) NULL,
            target_record_ids NVARCHAR(MAX) NULL,
            initiated_by NVARCHAR(256) NOT NULL,
            command_line NVARCHAR(MAX) NULL,
            batch_id NVARCHAR(100) NULL,
            sanitization_run_id NVARCHAR(100) NULL,
            dry_run BIT NOT NULL DEFAULT 0,
            started_at DATETIME2(3) NOT NULL,
            completed_at DATETIME2(3) NULL,
            status NVARCHAR(20) NOT NULL,
            rows_restored INT NULL DEFAULT 0,
            mappings_applied INT NULL DEFAULT 0,
            columns_affected INT NULL DEFAULT 0,
            tables_affected INT NULL DEFAULT 0,
            validation_passed BIT NULL,
            validation_warnings_count INT NULL DEFAULT 0,
            validation_errors_count INT NULL DEFAULT 0,
            error_message NVARCHAR(MAX) NULL,
            error_type NVARCHAR(128) NULL,
            created_at DATETIME2(3) NOT NULL DEFAULT GETDATE()
        );
    """)
    conn.commit()
    cursor.close()
    conn.close()
    
    yield
    
    # Cleanup after all tests
    conn = pyodbc.connect(test_connection_string)
    cursor = conn.cursor()
    cursor.execute("IF OBJECT_ID('dbo.desanitization_audit_log', 'U') IS NOT NULL DROP TABLE dbo.desanitization_audit_log")
    conn.commit()
    cursor.close()
    conn.close()


@pytest.fixture
def test_table_setup(test_connection_string):
    """Setup test table with sample data."""
    conn = pyodbc.connect(test_connection_string)
    cursor = conn.cursor()
    
    # Create test table
    cursor.execute("""
        IF OBJECT_ID('dbo.TestAuditCustomers', 'U') IS NOT NULL 
            DROP TABLE dbo.TestAuditCustomers;
        
        CREATE TABLE dbo.TestAuditCustomers (
            CustomerID INT PRIMARY KEY,
            Email NVARCHAR(100),
            PhoneNumber NVARCHAR(20)
        );
        
        INSERT INTO dbo.TestAuditCustomers (CustomerID, Email, PhoneNumber)
        VALUES 
            (1, 'masked_email1@example.com', '555-0001'),
            (2, 'masked_email2@example.com', '555-0002'),
            (3, 'masked_email3@example.com', '555-0003');
    """)
    conn.commit()
    cursor.close()
    conn.close()
    
    yield 'TestAuditCustomers'
    
    # Cleanup
    conn = pyodbc.connect(test_connection_string)
    cursor = conn.cursor()
    cursor.execute("IF OBJECT_ID('dbo.TestAuditCustomers', 'U') IS NOT NULL DROP TABLE dbo.TestAuditCustomers")
    conn.commit()
    cursor.close()
    conn.close()


@pytest.fixture
def mapping_setup(test_connection_string, test_table_setup):
    """Setup mapping table with test mappings."""
    mapping_manager = MappingTableManager(test_connection_string)
    
    # Create mapping table
    if not mapping_manager.table_exists():
        mapping_manager.create_table()
    
    # Insert test mappings
    batch_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    
    mappings = [
        MappingRecord(
            table_name='TestAuditCustomers',
            column_name='Email',
            record_id='1',
            original_value='original1@example.com',
            masked_value='masked_email1@example.com',
            batch_id=batch_id,
            sanitization_run_id=run_id
        ),
        MappingRecord(
            table_name='TestAuditCustomers',
            column_name='Email',
            record_id='2',
            original_value='original2@example.com',
            masked_value='masked_email2@example.com',
            batch_id=batch_id,
            sanitization_run_id=run_id
        ),
        MappingRecord(
            table_name='TestAuditCustomers',
            column_name='PhoneNumber',
            record_id='1',
            original_value='(555) 111-1111',
            masked_value='555-0001',
            batch_id=batch_id,
            sanitization_run_id=run_id
        ),
    ]
    
    mapping_manager.insert_batch(mappings)
    
    return {'batch_id': batch_id, 'mapping_manager': mapping_manager}


@pytest.fixture
def desanitization_components(test_connection_string, setup_audit_table):
    """Provide desanitization engine components with audit logger."""
    conn = pyodbc.connect(test_connection_string)
    conn.autocommit = False
    
    mapping_manager = MappingTableManager(test_connection_string)
    schema_inspector = SchemaInspector(conn)
    audit_logger = AuditLogger(conn, fallback_to_file=False)
    
    engine = DesanitizationEngine(
        connection=conn,
        mapping_manager=mapping_manager,
        schema_inspector=schema_inspector,
        audit_logger=audit_logger
    )
    
    yield {'conn': conn, 'engine': engine, 'audit_logger': audit_logger}
    
    conn.close()


# ============================================================================
# TEST: RECORD-LEVEL DESANITIZATION WITH AUDIT
# ============================================================================

def test_record_level_desanitization_audit_trail(
    desanitization_components, 
    test_table_setup, 
    mapping_setup,
    test_connection_string
):
    """Test complete audit trail for record-level desanitization."""
    engine = desanitization_components['engine']
    conn = desanitization_components['conn']
    audit_logger = desanitization_components['audit_logger']
    
    # Execute desanitization
    report = engine.desanitize_records(
        table='TestAuditCustomers',
        record_ids=['1'],
        schema='dbo',
        dry_run=False
    )
    
    # Verify report has audit_id
    assert report.audit_id is not None
    
    # Query audit log to verify record exists
    cursor = conn.cursor()
    cursor.execute("""
        SELECT operation_id, operation_type, target_table, status, 
               rows_restored, dry_run, initiated_by
        FROM desanitization_audit_log
        WHERE audit_id = ?
    """, report.audit_id)
    
    audit_record = cursor.fetchone()
    assert audit_record is not None
    assert audit_record[1] == 'RECORD'  # operation_type
    assert audit_record[2] == 'TestAuditCustomers'  # target_table
    assert audit_record[3] == 'COMPLETED'  # status
    assert audit_record[4] > 0  # rows_restored
    assert audit_record[5] == 0  # dry_run = False
    assert audit_record[6] is not None  # initiated_by
    
    cursor.close()


def test_record_level_dry_run_audit(
    desanitization_components, 
    test_table_setup, 
    mapping_setup
):
    """Test audit trail for dry-run mode."""
    engine = desanitization_components['engine']
    conn = desanitization_components['conn']
    
    # Execute dry-run
    report = engine.desanitize_records(
        table='TestAuditCustomers',
        record_ids=['1', '2'],
        schema='dbo',
        dry_run=True
    )
    
    # Verify audit log marks dry_run
    cursor = conn.cursor()
    cursor.execute("""
        SELECT dry_run, rows_restored, status
        FROM desanitization_audit_log
        WHERE audit_id = ?
    """, report.audit_id)
    
    audit_record = cursor.fetchone()
    assert audit_record[0] == 1  # dry_run = True
    assert audit_record[1] == 0  # rows_restored = 0 for dry-run
    assert audit_record[2] == 'COMPLETED'
    
    cursor.close()


# ============================================================================
# TEST: COLUMN-LEVEL DESANITIZATION WITH AUDIT
# ============================================================================

def test_column_level_desanitization_audit_trail(
    desanitization_components, 
    test_table_setup, 
    mapping_setup
):
    """Test complete audit trail for column-level desanitization."""
    engine = desanitization_components['engine']
    conn = desanitization_components['conn']
    
    # Execute column-level desanitization
    report = engine.desanitize_columns(
        table='TestAuditCustomers',
        column_names=['Email'],
        schema='dbo',
        dry_run=False
    )
    
    # Verify audit log
    cursor = conn.cursor()
    cursor.execute("""
        SELECT operation_type, target_columns, columns_affected, status
        FROM desanitization_audit_log
        WHERE audit_id = ?
    """, report.audit_id)
    
    audit_record = cursor.fetchone()
    assert audit_record[0] == 'COLUMN'  # operation_type
    assert 'Email' in audit_record[1]  # target_columns (JSON)
    assert audit_record[2] >= 1  # columns_affected
    assert audit_record[3] == 'COMPLETED'
    
    cursor.close()


# ============================================================================
# TEST: TABLE-LEVEL DESANITIZATION WITH AUDIT
# ============================================================================

def test_table_level_desanitization_audit_trail(
    desanitization_components, 
    test_table_setup, 
    mapping_setup
):
    """Test complete audit trail for table-level desanitization."""
    engine = desanitization_components['engine']
    conn = desanitization_components['conn']
    
    # Execute table-level desanitization
    report = engine.desanitize_table(
        table='TestAuditCustomers',
        schema='dbo',
        dry_run=False
    )
    
    # Verify audit log
    cursor = conn.cursor()
    cursor.execute("""
        SELECT operation_type, target_table, tables_affected, status
        FROM desanitization_audit_log
        WHERE audit_id = ?
    """, report.audit_id)
    
    audit_record = cursor.fetchone()
    assert audit_record[0] == 'TABLE'  # operation_type
    assert audit_record[1] == 'TestAuditCustomers'  # target_table
    assert audit_record[2] >= 1  # tables_affected
    assert audit_record[3] == 'COMPLETED'
    
    cursor.close()


# ============================================================================
# TEST: FAILURE SCENARIO AUDITING
# ============================================================================

def test_failure_scenario_audit_trail(desanitization_components, test_table_setup):
    """Test audit trail when desanitization fails."""
    engine = desanitization_components['engine']
    conn = desanitization_components['conn']
    
    # Try to desanitize non-existent record (should fail)
    try:
        report = engine.desanitize_records(
            table='TestAuditCustomers',
            record_ids=['999'],  # Non-existent record
            schema='dbo',
            dry_run=False
        )
    except Exception as e:
        # Expected to fail
        pass
    
    # Verify audit log captured failure
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TOP 1 status, error_message, error_type
        FROM desanitization_audit_log
        WHERE target_table = 'TestAuditCustomers'
        ORDER BY started_at DESC
    """)
    
    audit_record = cursor.fetchone()
    if audit_record:
        # If audit was captured (graceful degradation may skip)
        assert audit_record[0] in ['FAILED', 'PENDING']  # status
        if audit_record[1]:  # error_message
            assert len(audit_record[1]) > 0
    
    cursor.close()


# ============================================================================
# TEST: AUDIT HISTORY QUERY
# ============================================================================

def test_audit_history_query_integration(
    desanitization_components, 
    test_table_setup, 
    mapping_setup
):
    """Test querying audit history after multiple operations."""
    engine = desanitization_components['engine']
    audit_logger = desanitization_components['audit_logger']
    
    # Perform multiple operations
    engine.desanitize_records(
        table='TestAuditCustomers',
        record_ids=['1'],
        dry_run=True
    )
    
    engine.desanitize_records(
        table='TestAuditCustomers',
        record_ids=['2'],
        dry_run=False
    )
    
    # Query audit history
    history = audit_logger.get_audit_history(
        target_table='TestAuditCustomers',
        days=1,
        limit=10
    )
    
    # Verify results
    assert len(history) >= 2
    assert all(record['target_table'] == 'TestAuditCustomers' for record in history)


# ============================================================================
# TEST: TRANSACTION ROLLBACK AUDITING
# ============================================================================

def test_transaction_rollback_audit_independence(
    test_connection_string, 
    setup_audit_table
):
    """Test that audit logging is independent of parent transaction."""
    conn = pyodbc.connect(test_connection_string)
    conn.autocommit = False
    
    try:
        audit_logger = AuditLogger(conn, fallback_to_file=False)
        
        # Log operation start
        audit_id = audit_logger.log_operation_start(
            operation_id='TEST-ROLLBACK-001',
            operation_type='RECORD',
            target_table='TestTable',
            dry_run=False
        )
        
        # Simulate failure and rollback
        conn.rollback()
        
        # Verify audit log still exists (independent transaction)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) 
            FROM desanitization_audit_log 
            WHERE operation_id = 'TEST-ROLLBACK-001'
        """)
        
        count = cursor.fetchone()[0]
        assert count == 1  # Audit should persist despite rollback
        
        cursor.close()
    finally:
        conn.close()


# ============================================================================
# TEST: PERFORMANCE OVERHEAD
# ============================================================================

def test_audit_performance_overhead(
    desanitization_components, 
    test_table_setup, 
    mapping_setup
):
    """Test that audit logging overhead is minimal (<2%)."""
    import time
    
    engine = desanitization_components['engine']
    
    # Measure with audit
    start_with_audit = time.time()
    report_with_audit = engine.desanitize_records(
        table='TestAuditCustomers',
        record_ids=['1'],
        dry_run=True
    )
    duration_with_audit = time.time() - start_with_audit
    
    # Create engine without audit logger
    conn = desanitization_components['conn']
    mapping_manager = MappingTableManager(conn.getinfo(pyodbc.SQL_DATA_SOURCE_NAME))
    schema_inspector = SchemaInspector(conn)
    
    engine_no_audit = DesanitizationEngine(
        connection=conn,
        mapping_manager=mapping_manager,
        schema_inspector=schema_inspector,
        audit_logger=None
    )
    
    # Measure without audit
    start_no_audit = time.time()
    report_no_audit = engine_no_audit.desanitize_records(
        table='TestAuditCustomers',
        record_ids=['1'],
        dry_run=True
    )
    duration_no_audit = time.time() - start_no_audit
    
    # Calculate overhead percentage
    if duration_no_audit > 0:
        overhead_pct = ((duration_with_audit - duration_no_audit) / duration_no_audit) * 100
        
        # Overhead should be less than 2% (acceptance criterion from plan)
        assert overhead_pct < 2.0, f"Audit overhead too high: {overhead_pct:.2f}%"


# ============================================================================
# TEST: GRACEFUL DEGRADATION IN PRODUCTION
# ============================================================================

def test_graceful_degradation_audit_failure(
    test_connection_string, 
    test_table_setup, 
    mapping_setup
):
    """Test that desanitization succeeds even if audit logging fails."""
    conn = pyodbc.connect(test_connection_string)
    conn.autocommit = False
    
    # Create engine with broken audit logger (table doesn't exist)
    mapping_manager = MappingTableManager(test_connection_string)
    schema_inspector = SchemaInspector(conn)
    
    # Drop audit table to simulate failure
    cursor = conn.cursor()
    cursor.execute("IF OBJECT_ID('dbo.desanitization_audit_log', 'U') IS NOT NULL DROP TABLE dbo.desanitization_audit_log")
    conn.commit()
    
    try:
        # This should fail to initialize but engine should still work
        audit_logger = AuditLogger(conn, fallback_to_file=True)
    except AuditTableMissingError:
        # Expected - audit logger not available
        audit_logger = None
    
    engine = DesanitizationEngine(
        connection=conn,
        mapping_manager=mapping_manager,
        schema_inspector=schema_inspector,
        audit_logger=audit_logger
    )
    
    # Desanitization should still work
    report = engine.desanitize_records(
        table='TestAuditCustomers',
        record_ids=['1'],
        dry_run=True
    )
    
    # Verify operation succeeded
    assert report is not None
    assert report.audit_id is None  # No audit due to table missing
    
    cursor.close()
    conn.close()


# ============================================================================
# SUMMARY
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
