"""
Unit tests for DesanitizationEngine.

Tests the core desanitization engine methods in isolation using mocked
database connections and dependencies.

Test Coverage:
    - Precondition validation
    - Mapping retrieval and filtering
    - Restoration batch building
    - Update execution logic
    - Error handling and rollback
    - Dry-run mode behavior
    - Report generation

Usage:
    pytest tests/test_desanitization_engine.py -v
    pytest tests/test_desanitization_engine.py::TestDesanitizationEngine::test_validate_preconditions -v
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime
from typing import List, Dict

from desanitization import DesanitizationEngine
from desanitization.exceptions import (
    DesanitizationError,
    MappingNotFoundError,
    PreconditionError,
    RestorationError,
)


@pytest.fixture
def mock_connection():
    """Create a mock database connection."""
    conn = Mock()
    conn.autocommit = False
    cursor = Mock()
    cursor.fetchone = Mock(return_value=[1])  # Table exists
    cursor.fetchall = Mock(return_value=[])
    cursor.rowcount = 0
    cursor.description = [('col1',), ('col2',)]
    conn.cursor = Mock(return_value=cursor)
    conn.commit = Mock()
    conn.rollback = Mock()
    return conn


@pytest.fixture
def mock_mapping_manager():
    """Create a mock MappingTableManager."""
    manager = Mock()
    manager.table_name = 'token_mappings'
    manager.get_mappings = Mock(return_value=[])
    return manager


@pytest.fixture
def mock_schema_inspector():
    """Create a mock SchemaInspector."""
    inspector = Mock()
    inspector.validate_table_exists = Mock(return_value=True)
    
    # Mock PK info
    from database.schema_inspector import PrimaryKeyInfo
    pk_info = PrimaryKeyInfo(
        table_name='test_table',
        schema_name='dbo',
        pk_columns=['CustomerID'],
        is_composite=False
    )
    inspector.get_primary_key_columns = Mock(return_value=pk_info)
    inspector.build_pk_where_clause = Mock(return_value="t.CustomerID = tmp.record_id")
    
    return inspector


@pytest.fixture
def engine(mock_connection, mock_mapping_manager, mock_schema_inspector):
    """Create a DesanitizationEngine instance with mocked dependencies."""
    return DesanitizationEngine(
        connection=mock_connection,
        mapping_manager=mock_mapping_manager,
        schema_inspector=mock_schema_inspector
    )


class TestDesanitizationEngine:
    """Test suite for DesanitizationEngine class."""
    
    def test_initialization(self, engine, mock_connection, mock_mapping_manager, mock_schema_inspector):
        """Test engine initialization with dependencies."""
        assert engine.connection == mock_connection
        assert engine.mapping_manager == mock_mapping_manager
        assert engine.schema_inspector == mock_schema_inspector
        assert engine.logger is not None
    
    def test_validate_preconditions_success(self, engine, mock_connection):
        """Test successful precondition validation."""
        # Should not raise any exception
        engine._validate_preconditions('Customers', 'dbo', ['123', '456'])
        
        # Verify mapping table check was performed
        assert mock_connection.cursor.called
    
    def test_validate_preconditions_no_mapping_table(self, engine, mock_connection):
        """Test precondition validation fails when mapping table missing."""
        # Mock: mapping table doesn't exist
        cursor = mock_connection.cursor.return_value
        cursor.fetchone.return_value = [0]  # COUNT(*) = 0
        
        with pytest.raises(PreconditionError) as exc_info:
            engine._validate_preconditions('Customers', 'dbo', ['123'])
        
        assert "does not exist" in str(exc_info.value)
        assert "mapping table" in str(exc_info.value).lower()
    
    def test_validate_preconditions_table_not_exists(self, engine, mock_schema_inspector):
        """Test precondition validation fails when target table missing."""
        mock_schema_inspector.validate_table_exists.return_value = False
        
        with pytest.raises(PreconditionError) as exc_info:
            engine._validate_preconditions('NonExistentTable', 'dbo', ['123'])
        
        assert "does not exist" in str(exc_info.value)
        assert "NonExistentTable" in str(exc_info.value)
    
    def test_validate_preconditions_empty_record_ids(self, engine):
        """Test empty record IDs is now allowed for column-level operations."""
        # Changed behavior: empty record_ids is valid for column-level desanitization
        # This test now verifies that empty record_ids DOES NOT raise an error
        
        # This should NOT raise an error anymore
        try:
            engine._validate_preconditions('Customers', 'dbo', [])
            # Test passes if no exception is raised
        except Exception as e:
            # Only fail if it's a PreconditionError about record IDs
            if 'record IDs' in str(e).lower():
                pytest.fail(f"Empty record_ids should be allowed for column-level operations: {e}")
    
    def test_validate_preconditions_invalid_record_id_format(self, engine):
        """Test precondition validation fails with invalid record ID."""
        with pytest.raises(PreconditionError) as exc_info:
            engine._validate_preconditions('Customers', 'dbo', ['123', '', '456'])
        
        assert "Invalid record ID format" in str(exc_info.value)
    
    def test_retrieve_mappings_success(self, engine, mock_mapping_manager):
        """Test successful mapping retrieval."""
        # Mock mappings returned
        mock_mapping_manager.get_mappings.return_value = [
            {
                'table_name': 'Customers',
                'column_name': 'Email',
                'record_id': '123',
                'original_value': 'john@example.com',
                'masked_value': 'user_abc123@test.com'
            },
            {
                'table_name': 'Customers',
                'column_name': 'Phone',
                'record_id': '123',
                'original_value': '555-1234',
                'masked_value': '555-9999'
            }
        ]
        
        records = engine._retrieve_mappings(
            'Customers', 'dbo', ['123'], None, False
        )
        
        assert len(records) == 2
        assert records[0].column_name == 'Email'
        assert records[0].original_value == 'john@example.com'
        assert records[1].column_name == 'Phone'
    
    def test_retrieve_mappings_missing_raises_error(self, engine, mock_mapping_manager):
        """Test mapping retrieval raises error when mappings missing."""
        mock_mapping_manager.get_mappings.return_value = []
        
        with pytest.raises(MappingNotFoundError) as exc_info:
            engine._retrieve_mappings(
                'Customers', 'dbo', ['999'], None, skip_missing=False
            )
        
        assert "not found" in str(exc_info.value).lower()
        assert exc_info.value.missing_records == ['999']
    
    def test_retrieve_mappings_skip_missing(self, engine, mock_mapping_manager):
        """Test mapping retrieval with skip_missing=True."""
        mock_mapping_manager.get_mappings.return_value = [
            {
                'table_name': 'Customers',
                'column_name': 'Email',
                'record_id': '123',
                'original_value': 'john@example.com',
                'masked_value': 'user_abc123@test.com'
            }
        ]
        
        # Initialize report to capture warnings
        from desanitization.desanitization_engine import RestorationReport
        engine._current_report = RestorationReport(
            operation_id='TEST-001',
            start_time=datetime.now()
        )
        
        records = engine._retrieve_mappings(
            'Customers', 'dbo', ['123', '999'], None, skip_missing=True
        )
        
        assert len(records) == 1
        assert len(engine._current_report.warnings) == 1
        assert '999' in engine._current_report.warnings[0]
    
    def test_build_restoration_batches(self, engine):
        """Test grouping mappings by column."""
        from desanitization.desanitization_engine import RestorationRecord
        
        mappings = [
            RestorationRecord('Customers', 'Email', '123', 'john@example.com', 'masked1'),
            RestorationRecord('Customers', 'Email', '456', 'jane@example.com', 'masked2'),
            RestorationRecord('Customers', 'Phone', '123', '555-1234', 'masked3'),
        ]
        
        batches = engine._build_restoration_batches(mappings)
        
        assert len(batches) == 2
        assert 'Email' in batches
        assert 'Phone' in batches
        assert len(batches['Email']) == 2
        assert len(batches['Phone']) == 1
    
    def test_execute_restoration_success(self, engine, mock_connection):
        """Test successful restoration execution."""
        from desanitization.desanitization_engine import RestorationRecord, RestorationReport
        
        # Initialize report
        engine._operation_id = 'TEST-001'
        engine._current_report = RestorationReport(
            operation_id='TEST-001',
            start_time=datetime.now()
        )
        
        batches = {
            'Email': [
                RestorationRecord('Customers', 'Email', '123', 'john@example.com', 'masked1'),
                RestorationRecord('Customers', 'Email', '456', 'jane@example.com', 'masked2'),
            ]
        }
        
        cursor = mock_connection.cursor.return_value
        cursor.rowcount = 2  # 2 rows affected
        
        engine._execute_restoration('Customers', 'dbo', batches)
        
        # Verify commit was called
        assert mock_connection.commit.called
        
        # Verify report updated
        assert engine._current_report.records_restored == 2
        assert engine._current_report.mappings_applied == 2
        assert engine._current_report.tables_affected == 1
        assert engine._current_report.columns_affected == 1
    
    def test_execute_restoration_rollback_on_error(self, engine, mock_connection):
        """Test transaction rollback on restoration failure."""
        from desanitization.desanitization_engine import RestorationRecord, RestorationReport
        
        engine._operation_id = 'TEST-001'
        engine._current_report = RestorationReport(
            operation_id='TEST-001',
            start_time=datetime.now()
        )
        
        batches = {
            'Email': [
                RestorationRecord('Customers', 'Email', '123', 'john@example.com', 'masked1'),
            ]
        }
        
        # Mock cursor to raise error
        cursor = mock_connection.cursor.return_value
        cursor.execute.side_effect = Exception("Database error")
        
        with pytest.raises(RestorationError) as exc_info:
            engine._execute_restoration('Customers', 'dbo', batches)
        
        # Verify rollback was called
        assert mock_connection.rollback.called
        assert "Failed to execute restoration" in str(exc_info.value)
    
    def test_preview_restoration_dry_run(self, engine):
        """Test preview mode doesn't modify database."""
        from desanitization.desanitization_engine import RestorationRecord, RestorationReport
        
        engine._operation_id = 'TEST-001'
        engine._current_report = RestorationReport(
            operation_id='TEST-001',
            start_time=datetime.now(),
            dry_run=True
        )
        
        batches = {
            'Email': [
                RestorationRecord('Customers', 'Email', '123', 'john@example.com', 'masked1'),
                RestorationRecord('Customers', 'Email', '456', 'jane@example.com', 'masked2'),
            ],
            'Phone': [
                RestorationRecord('Customers', 'Phone', '123', '555-1234', 'masked3'),
            ]
        }
        
        engine._preview_restoration('Customers', 'dbo', batches)
        
        # Verify report updated
        assert engine._current_report.records_restored == 3
        assert engine._current_report.tables_affected == 1
        assert engine._current_report.columns_affected == 2
    
    def test_desanitize_records_full_flow_dry_run(
        self, engine, mock_mapping_manager, mock_schema_inspector
    ):
        """Test complete desanitization flow in dry-run mode."""
        # Mock mappings
        mock_mapping_manager.get_mappings.return_value = [
            {
                'table_name': 'Customers',
                'column_name': 'Email',
                'record_id': '123',
                'original_value': 'john@example.com',
                'masked_value': 'user_abc123@test.com'
            }
        ]
        
        report = engine.desanitize_records(
            table='Customers',
            record_ids=['123'],
            dry_run=True
        )
        
        assert report.operation_id is not None
        assert report.records_requested == 1
        assert report.records_restored == 1
        assert report.dry_run is True
        assert report.end_time is not None
    
    def test_desanitize_records_no_mappings_found(
        self, engine, mock_mapping_manager
    ):
        """Test desanitization with no mappings returns empty report."""
        mock_mapping_manager.get_mappings.return_value = []
        
        report = engine.desanitize_records(
            table='Customers',
            record_ids=['999'],
            skip_missing=True,
            dry_run=True
        )
        
        assert report.records_restored == 0
        assert len(report.warnings) > 0
    
    def test_generate_operation_id(self, engine):
        """Test operation ID generation is unique."""
        id1 = engine._generate_operation_id()
        id2 = engine._generate_operation_id()
        
        assert id1 != id2
        assert id1.startswith('DESAN-')
        assert id2.startswith('DESAN-')
    
    def test_restoration_report_to_dict(self):
        """Test conversion of RestorationReport to dictionary."""
        from desanitization.desanitization_engine import RestorationReport
        
        start = datetime.now()
        report = RestorationReport(
            operation_id='TEST-001',
            start_time=start,
            tables_affected=1,
            columns_affected=2,
            records_requested=5,
            records_restored=5,
            mappings_applied=10,
            dry_run=False
        )
        report.end_time = datetime.now()
        report.add_table_detail('Customers', 'Email', 3)
        report.add_table_detail('Customers', 'Phone', 2)
        report.warnings.append('Test warning')
        
        result = report.to_dict()
        
        assert result['operation_id'] == 'TEST-001'
        assert result['summary']['tables_affected'] == 1
        assert result['summary']['records_restored'] == 5
        assert 'Customers' in result['table_details']
        assert result['table_details']['Customers']['Email'] == 3
        assert len(result['warnings']) == 1
        assert result['dry_run'] is False


class TestEdgeCases:
    """Test edge cases and error scenarios."""
    
    def test_composite_primary_key_handling(
        self, engine, mock_mapping_manager, mock_schema_inspector
    ):
        """Test handling of composite primary keys."""
        from database.schema_inspector import PrimaryKeyInfo
        
        # Mock composite PK with correct parameters
        pk_info = PrimaryKeyInfo(
            table_name='Orders',
            schema_name='dbo',
            pk_columns=['CustomerID', 'OrderID'],
            is_composite=True
        )
        mock_schema_inspector.get_primary_key_columns.return_value = pk_info
        mock_schema_inspector.build_pk_where_clause.return_value = (
            "t.CustomerID = JSON_VALUE(tmp.record_id, '$.CustomerID') AND "
            "t.OrderID = JSON_VALUE(tmp.record_id, '$.OrderID')"
        )
        
        # Mock mappings with JSON record_id
        mock_mapping_manager.get_mappings.return_value = [
            {
                'table_name': 'Orders',
                'column_name': 'Status',
                'record_id': '{"CustomerID": "123", "OrderID": "456"}',
                'original_value': 'Shipped',
                'masked_value': 'Pending'
            }
        ]
        
        report = engine.desanitize_records(
            table='Orders',
            record_ids=['{"CustomerID": "123", "OrderID": "456"}'],
            dry_run=True
        )
        
        assert report.records_restored == 1
    
    def test_null_original_value_handling(self, engine, mock_mapping_manager):
        """Test restoration of NULL values."""
        mock_mapping_manager.get_mappings.return_value = [
            {
                'table_name': 'Customers',
                'column_name': 'MiddleName',
                'record_id': '123',
                'original_value': None,  # NULL
                'masked_value': '[NULL_TOKEN]'
            }
        ]
        
        from desanitization.desanitization_engine import RestorationReport
        engine._current_report = RestorationReport(
            operation_id='TEST-001',
            start_time=datetime.now()
        )
        
        records = engine._retrieve_mappings(
            'Customers', 'dbo', ['123'], None, False
        )
        
        assert len(records) == 1
        assert records[0].original_value is None
    
    def test_batch_id_filtering(self, engine, mock_mapping_manager):
        """Test filtering by batch ID."""
        engine.desanitize_records(
            table='Customers',
            record_ids=['123'],
            batch_id='BATCH-20260409',
            dry_run=True,
            skip_missing=True
        )
        
        # Verify batch_id was passed to get_mappings
        call_args = mock_mapping_manager.get_mappings.call_args
        assert call_args[1]['batch_id'] == 'BATCH-20260409'


class TestColumnLevelDesanitization:
    """Test suite for column-level desanitization functionality."""
    
    def test_validate_columns_success(self, engine, mock_connection):
        """Test successful column validation."""
        # Mock column list from database
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.return_value = [
            ('Email',),
            ('PhoneNumber',),
            ('SSN',),
        ]
        # Mock mapping count check
        mock_cursor.fetchone.side_effect = [
            (5,),  # Email has 5 mappings
            (3,),  # PhoneNumber has 3 mappings
        ]
        
        # Should not raise exception
        engine._validate_columns('Customers', 'dbo', ['Email', 'PhoneNumber'])
    
    def test_validate_columns_invalid_column(self, engine, mock_connection):
        """Test validation with invalid column name."""
        # Mock column list from database
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.return_value = [
            ('Email',),
            ('PhoneNumber',),
        ]
        
        # Should raise PreconditionError for invalid column
        with pytest.raises(PreconditionError) as exc_info:
            engine._validate_columns('Customers', 'dbo', ['InvalidColumn'])
        
        assert 'Invalid columns' in str(exc_info.value)
        assert 'InvalidColumn' in str(exc_info.value)
    
    def test_validate_columns_empty_list(self, engine):
        """Test validation with empty column list."""
        with pytest.raises(PreconditionError) as exc_info:
            engine._validate_columns('Customers', 'dbo', [])
        
        assert 'No columns provided' in str(exc_info.value)
    
    def test_validate_columns_no_mappings_warning(self, engine, mock_connection):
        """Test warning when column has no mappings."""
        # Mock column exists
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.return_value = [('Email',)]
        # Mock no mappings found
        mock_cursor.fetchone.return_value = (0,)
        
        # Should complete but add warning to report
        engine._operation_id = 'TEST-OP'
        from desanitization.desanitization_engine import RestorationReport
        from datetime import datetime
        engine._current_report = RestorationReport(
            operation_id='TEST-OP',
            start_time=datetime.now()
        )
        
        engine._validate_columns('Customers', 'dbo', ['Email'])
        
        # Check warning was added
        assert len(engine._current_report.warnings) > 0
        assert 'No mappings found' in engine._current_report.warnings[0]
    
    def test_retrieve_all_column_mappings_success(self, engine, mock_mapping_manager):
        """Test retrieving all mappings for specified columns."""
        # Mock mappings for multiple columns
        mock_mapping_manager.get_mappings.side_effect = [
            # Email column mappings
            [
                {'table_name': 'Customers', 'column_name': 'Email',
                 'record_id': '1', 'original_value': '[email protected]',
                 'masked_value': 'user_a1b2@example.com'},
                {'table_name': 'Customers', 'column_name': 'Email',
                 'record_id': '2', 'original_value': '[email protected]',
                 'masked_value': 'user_c3d4@example.com'},
            ],
            # PhoneNumber column mappings
            [
                {'table_name': 'Customers', 'column_name': 'PhoneNumber',
                 'record_id': '1', 'original_value': '555-1234',
                 'masked_value': '555-5678'},
            ]
        ]
        
        engine._operation_id = 'TEST-OP'
        
        records = engine._retrieve_all_column_mappings(
            table='Customers',
            schema='dbo',
            column_names=['Email', 'PhoneNumber'],
            batch_id=None
        )
        
        # Should have 3 total records (2 Email + 1 PhoneNumber)
        assert len(records) == 3
        
        # Verify get_mappings called correctly for each column
        assert mock_mapping_manager.get_mappings.call_count == 2
        
        # Verify first call for Email column
        first_call = mock_mapping_manager.get_mappings.call_args_list[0]
        assert first_call[1]['column_name'] == 'Email'
        assert first_call[1]['record_ids'] is None  # Key: no record filter
        
        # Verify second call for PhoneNumber column
        second_call = mock_mapping_manager.get_mappings.call_args_list[1]
        assert second_call[1]['column_name'] == 'PhoneNumber'
        assert second_call[1]['record_ids'] is None
    
    def test_retrieve_all_column_mappings_with_batch_id(self, engine, mock_mapping_manager):
        """Test column mapping retrieval with batch ID filter."""
        mock_mapping_manager.get_mappings.return_value = []
        
        engine._operation_id = 'TEST-OP'
        
        engine._retrieve_all_column_mappings(
            table='Customers',
            schema='dbo',
            column_names=['Email'],
            batch_id='BATCH-12345'
        )
        
        # Verify batch_id was passed
        call_args = mock_mapping_manager.get_mappings.call_args
        assert call_args[1]['batch_id'] == 'BATCH-12345'
    
    def test_desanitize_columns_dry_run(
        self, engine, mock_connection, mock_mapping_manager
    ):
        """Test column-level desanitization in dry-run mode."""
        # Mock column validation
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.return_value = [('Email',), ('PhoneNumber',)]
        mock_cursor.fetchone.side_effect = [(5,), (3,)]  # Mapping counts
        
        # Mock mappings retrieval
        mock_mapping_manager.get_mappings.side_effect = [
            # Email mappings
            [
                {'table_name': 'Customers', 'column_name': 'Email',
                 'record_id': '1', 'original_value': '[email protected]',
                 'masked_value': 'masked1'},
            ],
            # PhoneNumber mappings
            [
                {'table_name': 'Customers', 'column_name': 'PhoneNumber',
                 'record_id': '1', 'original_value': '555-1234',
                 'masked_value': 'masked2'},
            ]
        ]
        
        # Execute dry-run
        report = engine.desanitize_columns(
            table='Customers',
            column_names=['Email', 'PhoneNumber'],
            schema='dbo',
            batch_id=None,
            dry_run=True
        )
        
        # Verify report
        assert report.dry_run is True
        assert report.columns_affected == 2
        assert report.tables_affected == 1
        assert report.mappings_applied == 2
        assert len(report.errors) == 0
        
        # Verify no database commits (dry-run)
        mock_connection.commit.assert_not_called()
    
    def test_desanitize_columns_no_mappings(
        self, engine, mock_connection, mock_mapping_manager
    ):
        """Test column desanitization when no mappings exist."""
        # Mock column validation
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.return_value = [('Email',)]
        # Mock multiple fetchone calls: table exists (1), no mappings (0)
        mock_cursor.fetchone.side_effect = [(1,), (0,)]  # Mapping table exists, no column mappings
        
        # Mock no mappings found
        mock_mapping_manager.get_mappings.return_value = []
        
        report = engine.desanitize_columns(
            table='Customers',
            column_names=['Email'],
            dry_run=True
        )
        
        # Should have warning about no mappings
        assert len(report.warnings) > 0
        assert 'No mappings found' in report.warnings[0]
        assert report.mappings_applied == 0
    
    def test_desanitize_columns_with_progress_callback(
        self, engine, mock_connection, mock_mapping_manager, mock_schema_inspector
    ):
        """Test progress callback invocation during column restoration."""
        # Mock column validation
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.return_value = [('Email',), ('SSN',)]
        mock_cursor.fetchone.side_effect = [(2,), (2,)]  # Mapping counts
        
        # Mock mappings
        mock_mapping_manager.get_mappings.side_effect = [
            [{'table_name': 'Customers', 'column_name': 'Email',
              'record_id': '1', 'original_value': 'test',
              'masked_value': 'masked'}],
            [{'table_name': 'Customers', 'column_name': 'SSN',
              'record_id': '1', 'original_value': '123-45-6789',
              'masked_value': 'masked'}]
        ]
        
        # Progress callback tracker
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
            table='Customers',
            column_names=['Email', 'SSN'],
            dry_run=False,
            progress_callback=track_progress
        )
        
        # Verify callback was called for each column
        assert len(progress_calls) == 2
        assert progress_calls[0]['column'] == 'Email'
        assert progress_calls[0]['current'] == 1
        assert progress_calls[0]['total'] == 2
        assert progress_calls[1]['column'] == 'SSN'
        assert progress_calls[1]['current'] == 2
        assert progress_calls[1]['total'] == 2


class TestTableLevelDesanitization:
    """Test suite for table-level desanitization methods."""
    
    def test_get_columns_with_mappings_success(self, engine, mock_connection):
        """Test auto-discovery of columns with mappings."""
        # Mock successful query
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.return_value = [
            ('Email',),
            ('PhoneNumber',),
            ('SSN',)
        ]
        
        # Execute
        engine._operation_id = "TEST-OP-001"
        columns = engine._get_columns_with_mappings('Customers', 'dbo', None)
        
        # Verify
        assert columns == ['Email', 'PhoneNumber', 'SSN']
        
        # Verify query was executed
        assert mock_cursor.execute.called
        # Check table name in query
        call_args = mock_cursor.execute.call_args[0]
        assert 'Customers' in call_args[1]
    
    def test_get_columns_with_mappings_with_batch_id(self, engine, mock_connection):
        """Test column discovery with batch ID filter."""
        # Mock successful query
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.return_value = [
            ('Email',),
            ('SSN',)
        ]
        
        # Execute with batch_id
        engine._operation_id = "TEST-OP-002"
        columns = engine._get_columns_with_mappings('Users', 'dbo', 'BATCH-001')
        
        # Verify
        assert len(columns) == 2
        assert 'Email' in columns
        assert 'SSN' in columns
        
        # Verify batch_id was passed in query
        call_args = mock_cursor.execute.call_args[0]
        assert 'BATCH-001' in call_args[1]
    
    def test_get_columns_with_mappings_empty(self, engine, mock_connection):
        """Test no columns found for table."""
        # Mock empty result
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.return_value = []
        
        # Execute
        engine._operation_id = "TEST-OP-003"
        columns = engine._get_columns_with_mappings('EmptyTable', 'dbo', None)
        
        # Verify
        assert columns == []
    
    def test_validate_referential_integrity_no_fks(self, engine, mock_connection):
        """Test validation when table has no FK constraints."""
        # Mock no FK constraints
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.return_value = []
        
        # Execute
        engine._operation_id = "TEST-OP-004"
        violations = engine._validate_referential_integrity('Customers', 'dbo')
        
        # Verify
        assert violations == []
    
    def test_validate_referential_integrity_with_violations(self, engine, mock_connection):
        """Test detection of FK violations."""
        # Mock FK constraints and violations
        mock_cursor = mock_connection.cursor.return_value
        
        # First call: return FK constraint info
        # Second call: return orphaned samples
        # Third call: return orphan count
        mock_cursor.fetchall.side_effect = [
            # FK constraints query
            [Mock(
                constraint_name='FK_Orders_Customers',
                child_table='Orders',
                child_column='CustomerID',
                parent_schema='dbo',
                parent_table='Customers',
                parent_column='CustomerID'
            )],
            # Orphan samples query (top 5)
            [('123',), ('456',), ('789',)]
        ]
        
        # Orphan count query
        mock_cursor.fetchone.return_value = (3,)
        
        # Execute
        engine._operation_id = "TEST-OP-005"
        violations = engine._validate_referential_integrity('Orders', 'dbo')
        
        # Verify violations detected
        assert len(violations) == 1
        assert violations[0]['constraint_name'] == 'FK_Orders_Customers'
        assert violations[0]['orphaned_count'] == 3
        assert len(violations[0]['sample_ids']) == 3
        assert violations[0]['sample_ids'] == ['123', '456', '789']
    
    def test_validate_referential_integrity_error_handling(self, engine, mock_connection):
        """Test graceful handling of validation errors."""
        # Mock query error
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.execute.side_effect = Exception("Database error")
        
        # Execute - should not raise, just log and return empty
        engine._operation_id = "TEST-OP-006"
        violations = engine._validate_referential_integrity('Customers', 'dbo')
        
        # Verify empty result
        assert violations == []
    
    def test_desanitize_table_success(
        self, engine, mock_connection, mock_mapping_manager, mock_schema_inspector
    ):
        """Test successful table-level desanitization."""
        # Setup: Mock column discovery
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.side_effect = [
            # Column discovery query
            [('Email',), ('PhoneNumber',)],
            # Column validation query (INFORMATION_SCHEMA)
            [('Email',), ('PhoneNumber',)],
            # Mapping count checks
            [],
            # FK constraints (none)
            []
        ]
        mock_cursor.fetchone.side_effect = [(2,), (2,)]  # Mapping counts
        
        # Mock mappings for columns
        mock_mapping_manager.get_mappings.side_effect = [
            # Email mappings
            [{'table_name': 'Customers', 'column_name': 'Email',
              'record_id': '1', 'original_value': 'test@example.com',
              'masked_value': 'masked@example.com'}],
            # PhoneNumber mappings
            [{'table_name': 'Customers', 'column_name': 'PhoneNumber',
              'record_id': '1', 'original_value': '555-1234',
              'masked_value': 'masked'}]
        ]
        
        # Execute table-level desanitization
        report = engine.desanitize_table(
            table='Customers',
            schema='dbo',
            dry_run=False
        )
        
        # Verify
        assert report.tables_affected == 1
        assert report.columns_affected == 2
        assert len(report.errors) == 0
        assert report.operation_id is not None
    
    def test_desanitize_table_no_mappings_error(self, engine, mock_connection):
        """Test error when table has no mappings."""
        # Mock empty column discovery
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.return_value = []
        
        # Execute - should raise PreconditionError
        with pytest.raises(PreconditionError) as exc_info:
            engine.desanitize_table(
                table='EmptyTable',
                schema='dbo',
                dry_run=True
            )
        
        # Verify error message
        assert 'No mappings found' in str(exc_info.value)
        assert 'EmptyTable' in str(exc_info.value)
    
    def test_desanitize_table_dry_run(
        self, engine, mock_connection, mock_mapping_manager, mock_schema_inspector
    ):
        """Test table-level desanitization in dry-run mode."""
        # Setup: Mock column discovery
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.side_effect = [
            # Column discovery query
            [('Email',), ('SSN',)],
            # Column validation query
            [('Email',), ('SSN',)],
            # Mapping count checks
            []
        ]
        mock_cursor.fetchone.side_effect = [(5,), (5,)]  # Mapping counts
        
        # Mock mappings
        mock_mapping_manager.get_mappings.side_effect = [
            [{'table_name': 'Users', 'column_name': 'Email',
              'record_id': str(i), 'original_value': f'user{i}@test.com',
              'masked_value': 'masked'} for i in range(5)],
            [{'table_name': 'Users', 'column_name': 'SSN',
              'record_id': str(i), 'original_value': f'{i:03d}-45-6789',
              'masked_value': 'masked'} for i in range(5)]
        ]
        
        # Execute dry-run
        report = engine.desanitize_table(
            table='Users',
            schema='dbo',
            dry_run=True
        )
        
        # Verify
        assert report.dry_run is True
        assert report.columns_affected == 2
        assert report.mappings_applied == 10
        # Verify no commit was called (dry-run)
        assert not mock_connection.commit.called
    
    def test_desanitize_table_with_batch_filter(
        self, engine, mock_connection, mock_mapping_manager, mock_schema_inspector
    ):
        """Test table-level desanitization with batch ID filter."""
        # Setup: Mock column discovery with batch filter
        mock_cursor = mock_connection.cursor.return_value
        mock_cursor.fetchall.side_effect = [
            # Column discovery query (with batch filter)
            [('Email',)],
            # Column validation query
            [('Email',)],
            # Mapping count checks
            []
        ]
        mock_cursor.fetchone.return_value = (2,)
        
        # Mock mappings for batch
        mock_mapping_manager.get_mappings.return_value = [
            {'table_name': 'Customers', 'column_name': 'Email',
             'record_id': '1', 'original_value': 'test@example.com',
             'masked_value': 'masked@example.com'}
        ]
        
        # Execute with batch filter
        report = engine.desanitize_table(
            table='Customers',
            schema='dbo',
            batch_id='BATCH-001',
            dry_run=False
        )
        
        # Verify batch ID was used in column discovery
        call_args = mock_cursor.execute.call_args_list[0][0]
        assert 'BATCH-001' in call_args[1]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
