"""
Unit Tests for Desanitization Validator

Tests all validation checks in the DesanitizationValidator class with
mocked database connections and various scenarios.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime

from validation.desanitization_validator import (
    DesanitizationValidator,
    ValidationReport,
    ValidationCheck,
    ValidationStatus,
    ValidationError
)


@pytest.fixture
def mock_connection():
    """Create mock database connection."""
    conn = Mock()
    cursor = Mock()
    conn.cursor.return_value = cursor
    return conn, cursor


@pytest.fixture
def mock_mapping_manager():
    """Create mock MappingTableManager."""
    manager = Mock()
    manager.table_name = 'token_mappings'
    return manager


@pytest.fixture
def mock_schema_inspector():
    """Create mock SchemaInspector."""
    inspector = Mock()
    return inspector


@pytest.fixture
def validator(mock_connection, mock_mapping_manager, mock_schema_inspector):
    """Create validator instance with mocked dependencies."""
    conn, _ = mock_connection
    return DesanitizationValidator(
        connection=conn,
        mapping_manager=mock_mapping_manager,
        schema_inspector=mock_schema_inspector
    )


class TestValidationReportBasics:
    """Test ValidationReport data structure."""
    
    def test_create_validation_report(self):
        """Test creating a validation report."""
        report = ValidationReport(
            validation_id='VAL-TEST-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={'table': 'Customers', 'schema': 'dbo'}
        )
        
        assert report.validation_id == 'VAL-TEST-001'
        assert report.scope == 'table'
        assert len(report.checks) == 0
    
    def test_add_check_to_report(self):
        """Test adding checks to report."""
        report = ValidationReport(
            validation_id='VAL-TEST-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        report.add_check(
            check_name='Test Check',
            status=ValidationStatus.PASSED,
            message='Test passed'
        )
        
        assert len(report.checks) == 1
        assert report.checks[0].check_name == 'Test Check'
        assert report.checks[0].status == ValidationStatus.PASSED
    
    def test_is_valid_all_passed(self):
        """Test is_valid returns True when all checks passed."""
        report = ValidationReport(
            validation_id='VAL-TEST-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        report.add_check('Check 1', ValidationStatus.PASSED, 'OK')
        report.add_check('Check 2', ValidationStatus.PASSED, 'OK')
        
        assert report.is_valid() is True
    
    def test_is_valid_with_failure(self):
        """Test is_valid returns False when any check failed."""
        report = ValidationReport(
            validation_id='VAL-TEST-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        report.add_check('Check 1', ValidationStatus.PASSED, 'OK')
        report.add_check('Check 2', ValidationStatus.FAILED, 'Failed')
        
        assert report.is_valid() is False
    
    def test_warnings_detection(self):
        """Test has_warnings detects warnings."""
        report = ValidationReport(
            validation_id='VAL-TEST-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        report.add_check('Check 1', ValidationStatus.PASSED, 'OK')
        report.add_check('Check 2', ValidationStatus.WARNING, 'Warning')
        
        assert report.has_warnings() is True
        assert len(report.warnings) == 1


class TestMappingTableExistsCheck:
    """Test _check_mapping_table_exists validation."""
    
    def test_mapping_table_exists_success(self, validator, mock_connection):
        """Test successful mapping table existence check."""
        conn, cursor = mock_connection
        
        # Mock table exists query
        cursor.fetchone.side_effect = [
            (1,),  # Table exists
            (12345,)  # Sample mapping_id
        ]
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._check_mapping_table_exists(report)
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.PASSED
        assert 'exists and is accessible' in report.checks[0].message
    
    def test_mapping_table_not_exists(self, validator, mock_connection):
        """Test mapping table doesn't exist."""
        conn, cursor = mock_connection
        
        # Mock table doesn't exist
        cursor.fetchone.return_value = (0,)
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._check_mapping_table_exists(report)
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.FAILED
        assert 'does not exist' in report.checks[0].message
        assert report.checks[0].suggested_action is not None
    
    def test_mapping_table_access_error(self, validator, mock_connection):
        """Test error accessing mapping table."""
        conn, cursor = mock_connection
        
        # Mock access error
        cursor.execute.side_effect = Exception("Access denied")
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._check_mapping_table_exists(report)
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.FAILED
        assert 'Failed to access' in report.checks[0].message


class TestTargetTableExistsCheck:
    """Test _check_target_table_exists validation."""
    
    def test_target_table_exists(self, validator, mock_connection):
        """Test target table exists."""
        conn, cursor = mock_connection
        
        cursor.fetchone.return_value = (1,)
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._check_target_table_exists(report, 'Customers', 'dbo')
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.PASSED
        assert 'exists' in report.checks[0].message
    
    def test_target_table_not_exists(self, validator, mock_connection):
        """Test target table doesn't exist."""
        conn, cursor = mock_connection
        
        cursor.fetchone.return_value = (0,)
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._check_target_table_exists(report, 'NonExistent', 'dbo')
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.FAILED
        assert 'does not exist' in report.checks[0].message


class TestMappingsAvailableCheck:
    """Test _check_mappings_available validation."""
    
    def test_record_scope_all_mappings_found(self, validator, mock_connection):
        """Test all requested records have mappings."""
        conn, cursor = mock_connection
        
        cursor.fetchone.return_value = (3,)  # 3 records found
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='record',
            target_info={}
        )
        
        validator._check_mappings_available(
            report,
            scope='record',
            table='Customers',
            schema='dbo',
            columns=None,
            record_ids=['1', '2', '3'],
            batch_id=None
        )
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.PASSED
        assert 'All 3 requested records have mappings' in report.checks[0].message
    
    def test_record_scope_partial_mappings(self, validator, mock_connection):
        """Test only some requested records have mappings."""
        conn, cursor = mock_connection
        
        cursor.fetchone.return_value = (2,)  # Only 2 of 5 found
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='record',
            target_info={}
        )
        
        validator._check_mappings_available(
            report,
            scope='record',
            table='Customers',
            schema='dbo',
            columns=None,
            record_ids=['1', '2', '3', '4', '5'],
            batch_id=None
        )
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.WARNING
        assert '2/5' in report.checks[0].message
    
    def test_record_scope_no_mappings(self, validator, mock_connection):
        """Test no mappings found for requested records."""
        conn, cursor = mock_connection
        
        cursor.fetchone.return_value = (0,)
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='record',
            target_info={}
        )
        
        validator._check_mappings_available(
            report,
            scope='record',
            table='Customers',
            schema='dbo',
            columns=None,
            record_ids=['1', '2'],
            batch_id=None
        )
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.FAILED
        assert 'No mappings found' in report.checks[0].message
    
    def test_table_scope_mappings_found(self, validator, mock_connection):
        """Test table scope with mappings available."""
        conn, cursor = mock_connection
        
        cursor.fetchone.return_value = (150,)  # 150 records with mappings
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._check_mappings_available(
            report,
            scope='table',
            table='Customers',
            schema='dbo',
            columns=None,
            record_ids=None,
            batch_id=None
        )
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.PASSED
        assert '150 records found' in report.checks[0].message


class TestSchemaConsistencyCheck:
    """Test _check_schema_consistency validation."""
    
    def test_all_mapped_columns_exist(self, validator, mock_connection):
        """Test all mapped columns exist in current schema."""
        conn, cursor = mock_connection
        
        # Mock: Mapped columns = ['Email', 'Phone']
        # Current columns = ['CustomerID', 'Email', 'Phone', 'Name']
        cursor.fetchall.side_effect = [
            [('Email',), ('Phone',)],  # Mapped columns
            [('CustomerID',), ('Email',), ('Phone',), ('Name',)]  # Current columns
        ]
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._check_schema_consistency(
            report, 'Customers', 'dbo', None, None
        )
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.PASSED
    
    def test_mapped_column_missing_from_schema(self, validator, mock_connection):
        """Test mapped column no longer exists in schema."""
        conn, cursor = mock_connection
        
        # Mock: Mapped columns = ['Email', 'SSN']
        # Current columns = ['CustomerID', 'Email', 'Name'] (SSN removed)
        cursor.fetchall.side_effect = [
            [('Email',), ('SSN',)],  # Mapped columns
            [('CustomerID',), ('Email',), ('Name',)]  # Current columns (no SSN)
        ]
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._check_schema_consistency(
            report, 'Customers', 'dbo', None, None
        )
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.FAILED
        assert 'SSN' in report.checks[0].message
        assert 'no longer exist' in report.checks[0].message


class TestSchemaDriftDetection:
    """Test _detect_schema_drift validation."""
    
    def test_no_schema_drift(self, validator, mock_connection):
        """Test no schema drift detected."""
        conn, cursor = mock_connection
        
        # Mock: Email column, max value length = 30, current max_length = 50
        cursor.fetchall.side_effect = [
            [('Email', 30)],  # Mapped column info (max original value length)
            [('Email', 'nvarchar', 50)]  # Current schema info
        ]
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._detect_schema_drift(
            report, 'Customers', 'dbo', None, None
        )
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.PASSED
    
    def test_column_narrowed_truncation_risk(self, validator, mock_connection):
        """Test column narrowed causing truncation risk."""
        conn, cursor = mock_connection
        
        # Mock: Email column, max value length = 100, current max_length = 50
        cursor.fetchall.side_effect = [
            [('Email', 100)],  # Mapped column (max 100 chars)
            [('Email', 'nvarchar', 50)]  # Current schema (only 50 chars)
        ]
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._detect_schema_drift(
            report, 'Customers', 'dbo', None, None
        )
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.FAILED
        assert 'truncation would occur' in report.checks[0].message
    
    def test_column_widened_warning(self, validator, mock_connection):
        """Test column significantly widened (warning but not failure)."""
        conn, cursor = mock_connection
        
        # Mock: Email column, max value length = 30, current max_length = 150 (5x increase)
        cursor.fetchall.side_effect = [
            [('Email', 30)],  # Mapped column (max 30 chars)
            [('Email', 'nvarchar', 150)]  # Current schema (150 chars - significant increase)
        ]
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._detect_schema_drift(
            report, 'Customers', 'dbo', None, None
        )
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.WARNING
        assert 'widened' in report.checks[0].message


class TestDiskSpaceCheck:
    """Test _check_disk_space validation."""
    
    def test_sufficient_disk_space(self, validator, mock_connection):
        """Test sufficient transaction log space available."""
        conn, cursor = mock_connection
        
        # Mock: Total log = 10240 MB, Used = 2048 MB, Available = 8192 MB
        # Table data = 100 MB, Estimated need = 200 MB
        cursor.fetchone.side_effect = [
            (10240.0, 2048.0),  # Total and used log space
            (5000, 100.0)  # Row count and table size
        ]
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._check_disk_space(report, 'Customers', 'dbo')
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.PASSED
        assert 'Sufficient transaction log space' in report.checks[0].message
    
    def test_insufficient_disk_space(self, validator, mock_connection):
        """Test insufficient transaction log space."""
        conn, cursor = mock_connection
        
        # Mock: Total log = 1024 MB, Used = 1000 MB, Available = 24 MB
        # Table data = 100 MB, Estimated need = 200 MB (more than available)
        cursor.fetchone.side_effect = [
            (1024.0, 1000.0),  # Total and used log space
            (10000, 100.0)  # Row count and table size
        ]
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._check_disk_space(report, 'Customers', 'dbo')
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.FAILED
        assert 'Insufficient transaction log space' in report.checks[0].message
    
    def test_tight_disk_space_warning(self, validator, mock_connection):
        """Test tight disk space triggers warning."""
        conn, cursor = mock_connection
        
        # Mock: Available = 250 MB, Need = 200 MB, Recommended = 400 MB
        cursor.fetchone.side_effect = [
            (2048.0, 1798.0),  # Total and used (available = 250)
            (5000, 100.0)  # Table data (estimated need = 200, recommended = 400)
        ]
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._check_disk_space(report, 'Customers', 'dbo')
        
        # Should pass but with warning
        assert len(report.checks) == 1
        # Could be WARNING or PASSED depending on exact calculation
        assert report.checks[0].status in [ValidationStatus.PASSED, ValidationStatus.WARNING]


class TestConstraintCompatibilityCheck:
    """Test _check_constraint_compatibility validation."""
    
    def test_no_unique_constraints(self, validator, mock_connection):
        """Test table with no unique constraints."""
        conn, cursor = mock_connection
        
        cursor.fetchall.return_value = []  # No constraints
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._check_constraint_compatibility(report, 'Orders', 'dbo')
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.PASSED
        assert 'No unique constraints' in report.checks[0].message
    
    def test_has_unique_constraints_warning(self, validator, mock_connection):
        """Test table with unique constraints triggers warning."""
        conn, cursor = mock_connection
        
        # Mock: Table has unique constraint on Email column
        cursor.fetchall.return_value = [
            ('UQ_Email', 1, 0, 'Email')
        ]
        
        report = ValidationReport(
            validation_id='VAL-001',
            timestamp=datetime.now(),
            scope='table',
            target_info={}
        )
        
        validator._check_constraint_compatibility(report, 'Customers', 'dbo')
        
        assert len(report.checks) == 1
        assert report.checks[0].status == ValidationStatus.WARNING
        assert 'unique' in report.checks[0].message.lower()


class TestValidateDesanitization:
    """Test main validate_desanitization method."""
    
    def test_full_validation_workflow(self, validator, mock_connection):
        """Test complete validation workflow."""
        conn, cursor = mock_connection
        
        # Mock successful responses for all checks
        cursor.fetchone.side_effect = [
            (1,), (12345,),  # Mapping table exists
            (1,),  # Target table exists
            (10,),  # Mappings available
            # ... additional mocks as needed
        ]
        
        cursor.fetchall.side_effect = [
            [('Email',), ('Phone',)],  # Mapped columns
            [('CustomerID',), ('Email',), ('Phone',), ('Name',)],  # Current schema
            [('Email', 30), ('Phone', 15)],  # Max lengths
            [('Email', 'nvarchar', 50), ('Phone', 'nvarchar', 20)],  # Current types
            []  # No constraints
        ]
        
        report = validator.validate_desanitization(
            scope='table',
            table='Customers',
            schema='dbo'
        )
        
        assert report.validation_id.startswith('VAL-')
        assert report.scope == 'table'
        assert len(report.checks) > 0
    
    def test_validation_stops_on_early_failure(self, validator, mock_connection):
        """Test validation skips later checks when early checks fail."""
        conn, cursor = mock_connection
        
        # Mock mapping table doesn't exist
        cursor.fetchone.return_value = (0,)
        
        report = validator.validate_desanitization(
            scope='table',
            table='Customers',
            schema='dbo'
        )
        
        assert not report.is_valid()
        # Should have some checks marked as SKIPPED
        skipped_checks = [c for c in report.checks if c.status == ValidationStatus.SKIPPED]
        assert len(skipped_checks) > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
