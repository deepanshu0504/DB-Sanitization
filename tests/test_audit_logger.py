"""
Unit tests for AuditLogger.

Run with: pytest tests/test_audit_logger.py -v

Tests audit logging functionality for desanitization operations including:
- Operation start/complete/failure logging
- User detection
- Graceful degradation
- Audit history queries
- Export functionality
- JSON serialization
- Error handling

Author: Database Sanitization Team
Date: April 13, 2026
"""

import os
import uuid
import json
import pytest
from datetime import datetime
from typing import Generator
from unittest.mock import Mock, patch, MagicMock

import pyodbc

from audit import AuditLogger, AuditRecord, AuditTableMissingError, AuditError


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
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


@pytest.fixture
def mock_connection():
    """Provide mock database connection."""
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.commit = Mock()
    return mock_conn


@pytest.fixture
def audit_logger_with_mock(mock_connection):
    """Provide AuditLogger with mocked connection."""
    # Mock table verification to succeed
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.fetchone.return_value = (1,)  # Table exists
    
    logger = AuditLogger(mock_connection, fallback_to_file=False)
    return logger


@pytest.fixture
def sample_operation_data():
    """Provide sample operation data for testing."""
    return {
        'operation_id': f'DESAN-{datetime.now().strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:8]}',
        'operation_type': 'RECORD',
        'target_table': 'Customers',
        'target_schema': 'dbo',
        'target_record_ids': ['123', '456'],
        'batch_id': str(uuid.uuid4()),
        'dry_run': False,
        'command_line': 'python desanitize_direct.py --table Customers --record-ids 123 456'
    }


# ============================================================================
# TEST: INITIALIZATION
# ============================================================================

def test_audit_logger_initialization_success(mock_connection):
    """Test successful AuditLogger initialization."""
    # Mock table verification to succeed
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.fetchone.return_value = (1,)  # Table exists
    
    logger = AuditLogger(mock_connection)
    
    assert logger.connection == mock_connection
    assert logger.fallback_to_file == True
    assert logger._current_user is None


def test_audit_logger_initialization_table_missing(mock_connection):
    """Test AuditLogger initialization with missing audit table."""
    # Mock table verification to fail
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.fetchone.return_value = None  # Table doesn't exist
    
    with pytest.raises(AuditTableMissingError) as exc_info:
        AuditLogger(mock_connection)
    
    assert "desanitization_audit_log" in str(exc_info.value)


def test_audit_logger_initialization_without_fallback(mock_connection):
    """Test AuditLogger initialization with fallback disabled."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.fetchone.return_value = (1,)
    
    logger = AuditLogger(mock_connection, fallback_to_file=False)
    
    assert logger.fallback_to_file == False


# ============================================================================
# TEST: USER DETECTION
# ============================================================================

def test_get_current_user_success(audit_logger_with_mock, mock_connection):
    """Test successful user detection via SYSTEM_USER."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.fetchone.return_value = ('DOMAIN\\testuser',)
    
    user = audit_logger_with_mock._get_current_user()
    
    assert user == 'DOMAIN\\testuser'
    assert audit_logger_with_mock._current_user == 'DOMAIN\\testuser'


def test_get_current_user_cached(audit_logger_with_mock):
    """Test that user is cached after first detection."""
    audit_logger_with_mock._current_user = 'cached_user'
    
    user = audit_logger_with_mock._get_current_user()
    
    assert user == 'cached_user'
    # Connection should not be called again
    audit_logger_with_mock.connection.cursor.assert_not_called()


def test_get_current_user_fallback_to_suser_sname(audit_logger_with_mock, mock_connection):
    """Test fallback to SUSER_SNAME() when SYSTEM_USER returns None."""
    mock_cursor = mock_connection.cursor.return_value
    # First call returns None, second call uses SUSER_SNAME
    mock_cursor.fetchone.side_effect = [None, ('testuser',)]
    
    user = audit_logger_with_mock._get_current_user()
    
    assert user == 'testuser'


def test_get_current_user_error_handling(audit_logger_with_mock, mock_connection):
    """Test user detection error handling."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.execute.side_effect = Exception("Database error")
    
    user = audit_logger_with_mock._get_current_user()
    
    assert user == "UNKNOWN"


# ============================================================================
# TEST: LOG OPERATION START
# ============================================================================

def test_log_operation_start_success(audit_logger_with_mock, mock_connection, sample_operation_data):
    """Test successful operation start logging."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.fetchone.return_value = (12345,)  # audit_id
    
    # Mock user detection
    audit_logger_with_mock._current_user = 'testuser'
    
    audit_id = audit_logger_with_mock.log_operation_start(**sample_operation_data)
    
    assert audit_id == 12345
    mock_connection.commit.assert_called_once()


def test_log_operation_start_invalid_operation_type(audit_logger_with_mock, sample_operation_data):
    """Test operation start with invalid operation type."""
    sample_operation_data['operation_type'] = 'INVALID'
    
    audit_id = audit_logger_with_mock.log_operation_start(**sample_operation_data)
    
    assert audit_id is None


def test_log_operation_start_with_null_values(audit_logger_with_mock, mock_connection):
    """Test operation start with minimal required fields."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.fetchone.return_value = (999,)
    audit_logger_with_mock._current_user = 'testuser'
    
    audit_id = audit_logger_with_mock.log_operation_start(
        operation_id='TEST-001',
        operation_type='DATABASE',
        dry_run=False
    )
    
    assert audit_id == 999


def test_log_operation_start_database_error(audit_logger_with_mock, mock_connection, sample_operation_data):
    """Test operation start when database insert fails."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.execute.side_effect = Exception("Insert failed")
    
    audit_id = audit_logger_with_mock.log_operation_start(**sample_operation_data)
    
    assert audit_id is None


def test_log_operation_start_with_fallback(mock_connection, sample_operation_data):
    """Test operation start with file fallback enabled."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.fetchone.side_effect = [(1,), None]  # Table exists, but insert fails
    mock_cursor.execute.side_effect = [None, Exception("Insert failed")]
    
    logger = AuditLogger(mock_connection, fallback_to_file=True)
    
    with patch('audit.audit_logger.logger') as mock_logger:
        audit_id = logger.log_operation_start(**sample_operation_data)
        
        assert audit_id is None
        # Should log warning about fallback
        assert mock_logger.warning.called


# ============================================================================
# TEST: LOG OPERATION COMPLETE
# ============================================================================

def test_log_operation_complete_success(audit_logger_with_mock, mock_connection):
    """Test successful operation complete logging."""
    audit_id = 12345
    operation_id = 'TEST-001'
    
    result = audit_logger_with_mock.log_operation_complete(
        audit_id=audit_id,
        operation_id=operation_id,
        rows_restored=100,
        mappings_applied=200,
        columns_affected=5,
        tables_affected=1,
        validation_passed=True,
        validation_warnings_count=2,
        validation_errors_count=0
    )
    
    assert result == True
    mock_connection.commit.assert_called_once()


def test_log_operation_complete_with_none_audit_id(audit_logger_with_mock):
    """Test operation complete with None audit_id (start failed)."""
    result = audit_logger_with_mock.log_operation_complete(
        audit_id=None,
        operation_id='TEST-001',
        rows_restored=100
    )
    
    assert result == False


def test_log_operation_complete_database_error(audit_logger_with_mock, mock_connection):
    """Test operation complete when database update fails."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.execute.side_effect = Exception("Update failed")
    
    result = audit_logger_with_mock.log_operation_complete(
        audit_id=12345,
        operation_id='TEST-001',
        rows_restored=100
    )
    
    assert result == False


def test_log_operation_complete_with_validation_failed(audit_logger_with_mock, mock_connection):
    """Test operation complete with failed validation."""
    result = audit_logger_with_mock.log_operation_complete(
        audit_id=12345,
        operation_id='TEST-001',
        rows_restored=50,
        validation_passed=False,
        validation_errors_count=3
    )
    
    assert result == True


# ============================================================================
# TEST: LOG OPERATION FAILURE
# ============================================================================

def test_log_operation_failure_success(audit_logger_with_mock, mock_connection):
    """Test successful operation failure logging."""
    audit_id = 12345
    operation_id = 'TEST-001'
    error_message = "MappingNotFoundError: No mappings found for record 999"
    error_type = "MappingNotFoundError"
    
    result = audit_logger_with_mock.log_operation_failure(
        audit_id=audit_id,
        operation_id=operation_id,
        error_message=error_message,
        error_type=error_type,
        rows_restored=25,
        mappings_applied=50
    )
    
    assert result == True
    mock_connection.commit.assert_called_once()


def test_log_operation_failure_with_none_audit_id(audit_logger_with_mock):
    """Test operation failure with None audit_id."""
    result = audit_logger_with_mock.log_operation_failure(
        audit_id=None,
        operation_id='TEST-001',
        error_message="Some error"
    )
    
    assert result == False


def test_log_operation_failure_with_long_error_message(audit_logger_with_mock, mock_connection):
    """Test operation failure with very long error message (truncation)."""
    long_error = "A" * 5000  # 5000 characters
    
    result = audit_logger_with_mock.log_operation_failure(
        audit_id=12345,
        operation_id='TEST-001',
        error_message=long_error,
        error_type="TestError"
    )
    
    assert result == True
    # Verify execute was called (message should be truncated to 4000 chars)
    mock_connection.cursor.return_value.execute.assert_called_once()


def test_log_operation_failure_database_error(audit_logger_with_mock, mock_connection):
    """Test operation failure when database update fails."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.execute.side_effect = Exception("Update failed")
    
    result = audit_logger_with_mock.log_operation_failure(
        audit_id=12345,
        operation_id='TEST-001',
        error_message="Original error"
    )
    
    assert result == False


# ============================================================================
# TEST: JSON SERIALIZATION
# ============================================================================

def test_serialize_json_field_with_list(audit_logger_with_mock):
    """Test JSON serialization of list."""
    test_list = ['column1', 'column2', 'column3']
    
    result = audit_logger_with_mock._serialize_json_field(test_list)
    
    assert result == '["column1", "column2", "column3"]'


def test_serialize_json_field_with_dict(audit_logger_with_mock):
    """Test JSON serialization of dictionary."""
    test_dict = {'key1': 'value1', 'key2': 'value2'}
    
    result = audit_logger_with_mock._serialize_json_field(test_dict)
    
    parsed = json.loads(result)
    assert parsed == test_dict


def test_serialize_json_field_with_none(audit_logger_with_mock):
    """Test JSON serialization of None."""
    result = audit_logger_with_mock._serialize_json_field(None)
    
    assert result is None


def test_serialize_json_field_with_unicode(audit_logger_with_mock):
    """Test JSON serialization with unicode characters."""
    test_list = ['column_名前', 'column_λάμδα']
    
    result = audit_logger_with_mock._serialize_json_field(test_list)
    
    parsed = json.loads(result)
    assert parsed == test_list


def test_serialize_json_field_error_handling(audit_logger_with_mock):
    """Test JSON serialization error handling."""
    # Create an un-serializable object
    class UnserializableClass:
        pass
    
    test_obj = UnserializableClass()
    
    result = audit_logger_with_mock._serialize_json_field(test_obj)
    
    # Should fallback to str()
    assert isinstance(result, str)


# ============================================================================
# TEST: AUDIT RECORD DATACLASS
# ============================================================================

def test_audit_record_to_dict():
    """Test AuditRecord to_dict conversion."""
    record = AuditRecord(
        operation_id='TEST-001',
        operation_type='RECORD',
        target_table='Customers',
        initiated_by='testuser',
        started_at=datetime(2026, 4, 13, 10, 30, 0),
        status='COMPLETED',
        rows_restored=50
    )
    
    result = record.to_dict()
    
    assert result['operation_id'] == 'TEST-001'
    assert result['operation_type'] == 'RECORD'
    assert result['target_table'] == 'Customers'
    assert result['rows_restored'] == 50
    assert result['started_at'] == '2026-04-13T10:30:00'


def test_audit_record_to_dict_with_none_values():
    """Test AuditRecord to_dict with None values."""
    record = AuditRecord(
        operation_id='TEST-001',
        operation_type='DATABASE',
        initiated_by='testuser'
    )
    
    result = record.to_dict()
    
    assert result['target_table'] is None
    assert result['completed_at'] is None
    assert result['error_message'] is None


def test_audit_record_to_dict_with_lists():
    """Test AuditRecord to_dict with list fields."""
    record = AuditRecord(
        operation_id='TEST-001',
        operation_type='COLUMN',
        initiated_by='testuser',
        target_columns=['Email', 'PhoneNumber'],
        target_record_ids=['123', '456']
    )
    
    result = record.to_dict()
    
    assert result['target_columns'] == ['Email', 'PhoneNumber']
    assert result['target_record_ids'] == ['123', '456']


# ============================================================================
# TEST: GET AUDIT HISTORY (requires real DB or more complex mocking)
# ============================================================================

def test_get_audit_history_with_filters(audit_logger_with_mock, mock_connection):
    """Test audit history query with filters."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.description = [
        ('audit_id',), ('operation_id',), ('operation_type',), ('target_table',),
        ('initiated_by',), ('started_at',), ('status',), ('rows_restored',)
    ]
    mock_cursor.fetchall.return_value = [
        (1, 'TEST-001', 'RECORD', 'Customers', 'testuser', datetime.now(), 'COMPLETED', 100),
        (2, 'TEST-002', 'COLUMN', 'Users', 'testuser', datetime.now(), 'COMPLETED', 50)
    ]
    
    results = audit_logger_with_mock.get_audit_history(
        operation_type='RECORD',
        target_table='Customers',
        days=7,
        limit=10
    )
    
    assert len(results) == 2
    assert results[0]['operation_id'] == 'TEST-001'


def test_get_audit_history_database_error(audit_logger_with_mock, mock_connection):
    """Test audit history query error handling."""
    from audit.exceptions import AuditQueryError
    
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.execute.side_effect = Exception("Query failed")
    
    with pytest.raises(AuditQueryError) as exc_info:
        audit_logger_with_mock.get_audit_history()
    
    assert "Query failed" in str(exc_info.value)


# ============================================================================
# TEST: EXPORT AUDIT LOGS
# ============================================================================

def test_export_audit_logs_json(audit_logger_with_mock, mock_connection, tmp_path):
    """Test export audit logs to JSON format."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.description = [('audit_id',), ('operation_id',), ('status',)]
    mock_cursor.fetchall.return_value = [
        (1, 'TEST-001', 'COMPLETED'),
        (2, 'TEST-002', 'FAILED')
    ]
    
    output_file = tmp_path / "audit_export.json"
    
    count = audit_logger_with_mock.export_audit_logs(
        output_file=str(output_file),
        format='json',
        days=30
    )
    
    assert count == 2
    assert output_file.exists()
    
    # Verify JSON content
    with open(output_file, 'r') as f:
        data = json.load(f)
        assert len(data) == 2
        assert data[0]['operation_id'] == 'TEST-001'


def test_export_audit_logs_csv(audit_logger_with_mock, mock_connection, tmp_path):
    """Test export audit logs to CSV format."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.description = [('audit_id',), ('operation_id',), ('status',)]
    mock_cursor.fetchall.return_value = [
        (1, 'TEST-001', 'COMPLETED')
    ]
    
    output_file = tmp_path / "audit_export.csv"
    
    count = audit_logger_with_mock.export_audit_logs(
        output_file=str(output_file),
        format='csv',
        days=7
    )
    
    assert count == 1
    assert output_file.exists()


def test_export_audit_logs_invalid_format(audit_logger_with_mock):
    """Test export with invalid format."""
    with pytest.raises(ValueError) as exc_info:
        audit_logger_with_mock.export_audit_logs(
            output_file='test.txt',
            format='xml'
        )
    
    assert "Unsupported format" in str(exc_info.value)


# ============================================================================
# TEST: GRACEFUL DEGRADATION
# ============================================================================

def test_graceful_degradation_on_start_failure(mock_connection, sample_operation_data):
    """Test that operation start failure doesn't crash."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.fetchone.side_effect = [(1,), None]  # Table exists, insert fails
    mock_cursor.execute.side_effect = [None, Exception("DB error")]
    
    logger = AuditLogger(mock_connection, fallback_to_file=True)
    
    # Should not raise exception
    audit_id = logger.log_operation_start(**sample_operation_data)
    
    assert audit_id is None  # Gracefully returns None


def test_graceful_degradation_file_fallback(mock_connection, sample_operation_data):
    """Test file fallback when DB logging fails."""
    mock_cursor = mock_connection.cursor.return_value
    mock_cursor.fetchone.side_effect = [(1,), None]
    mock_cursor.execute.side_effect = [None, Exception("DB error")]
    
    logger = AuditLogger(mock_connection, fallback_to_file=True)
    
    with patch('audit.audit_logger.logger') as mock_file_logger:
        logger.log_operation_start(**sample_operation_data)
        
        # Should have logged to file
        assert mock_file_logger.warning.called


# ============================================================================
# SUMMARY
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
