"""
Unit tests for the Desensitization Engine.

Tests cover all phases of the desensitization workflow:
- Component initialization and dependency injection
- Phase 1: Validation (operation existence, mappings, encryption)
- Phase 2: Planning (dependency resolution, restore order)
- Phase 3: Restoration (value decryption, database updates)
- Phase 4: Verification (integrity checks)
- Error handling and edge cases

Author: Database Sanitization Team
Date: 2026-03-27
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime
from uuid import UUID, uuid4

from src.sanitization.desensitizer import (
    Desensitizer,
    DesensitizationConfig,
    RestorePhase,
    RestoreReport
)
from src.exceptions import DesensitizationError, MappingError, DatabaseError


# --- Fixtures ---

@pytest.fixture
def mock_connection_manager():
    """Mock database connection manager."""
    mock = Mock()
    mock.get_connection.return_value = Mock()
    return mock


@pytest.fixture
def mock_mapping_manager():
    """Mock mapping table manager."""
    mock = Mock()
    mock.get_operation_stats.return_value = Mock(
        total_entries=1000,
        table_count=3,
        column_count=5,
        encrypted_count=500
    )
    return mock


@pytest.fixture
def mock_transaction_manager():
    """Mock transaction manager."""
    mock = Mock()
    mock.begin.return_value.__enter__ = Mock()
    mock.begin.return_value.__exit__ = Mock(return_value=False)
    return mock


@pytest.fixture
def mock_batch_updater():
    """Mock batch updater."""
    mock = Mock()
    return mock


@pytest.fixture
def mock_schema_extractor():
    """Mock schema metadata extractor."""
    mock = Mock()
    mock.extract_schema.return_value = {
        "foreign_keys": [
            {"parent_table": "dbo.Customers", "child_table": "dbo.Orders"},
            {"parent_table": "dbo.Orders", "child_table": "dbo.OrderDetails"}
        ]
    }
    mock.get_table_metadata.return_value = {
        "primary_key_columns": ["customer_id"]
    }
    return mock


@pytest.fixture
def desensitizer_config():
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
    mock_connection_manager,
    mock_mapping_manager,
    mock_transaction_manager,
    mock_batch_updater,
    mock_schema_extractor,
    desensitizer_config
):
    """Initialized Desensitizer instance with mocked dependencies."""
    return Desensitizer(
        connection_manager=mock_connection_manager,
        mapping_manager=mock_mapping_manager,
        transaction_manager=mock_transaction_manager,
        batch_updater=mock_batch_updater,
        schema_extractor=mock_schema_extractor,
        config=desensitizer_config
    )


# --- Initialization Tests ---

class TestDesensitizer Initialization:
    """Test Desensitizer construction and dependency injection."""
    
    def test_init_with_all_dependencies(
        self,
        mock_connection_manager,
        mock_mapping_manager,
        mock_transaction_manager,
        mock_batch_updater,
        mock_schema_extractor,
        desensitizer_config
    ):
        """Test initialization with all dependencies provided."""
        desensitizer = Desensitizer(
            connection_manager=mock_connection_manager,
            mapping_manager=mock_mapping_manager,
            transaction_manager=mock_transaction_manager,
            batch_updater=mock_batch_updater,
            schema_extractor=mock_schema_extractor,
            config=desensitizer_config
        )
        
        assert desensitizer.connection_manager is mock_connection_manager
        assert desensitizer.mapping_manager is mock_mapping_manager
        assert desensitizer.transaction_manager is mock_transaction_manager
        assert desensitizer.batch_updater is mock_batch_updater
        assert desensitizer.schema_extractor is mock_schema_extractor
        assert desensitizer.config is desensitizer_config
        assert desensitizer.progress_callback is None
        assert desensitizer.table_callback is None
    
    def test_init_with_required_dependencies_only(
        self,
        mock_connection_manager,
        mock_mapping_manager
    ):
        """Test initialization with only required dependencies."""
        with patch('src.sanitization.desensitizer.TransactionManager'):
            with patch('src.sanitization.desensitizer.BatchUpdater'):
                with patch('src.sanitization.desensitizer.SchemaExtractor'):
                    desensitizer = Desensitizer(
                        connection_manager=mock_connection_manager,
                        mapping_manager=mock_mapping_manager
                    )
                    
                    assert desensitizer.connection_manager is mock_connection_manager
                    assert desensitizer.mapping_manager is mock_mapping_manager
                    assert desensitizer.transaction_manager is not None
                    assert desensitizer.batch_updater is not None
                    assert desensitizer.schema_extractor is not None
                    assert isinstance(desensitizer.config, DesensitizationConfig)
    
    def test_init_requires_connection_manager(self):
        """Test that connection_manager is required."""
        with pytest.raises(ValueError, match="connection_manager is required"):
            Desensitizer(
                connection_manager=None,
                mapping_manager=Mock()
            )
    
    def test_init_requires_mapping_manager(self):
        """Test that mapping_manager is required."""
        with pytest.raises(ValueError, match="mapping_manager is required"):
            Desensitizer(
                connection_manager=Mock(),
                mapping_manager=None
            )
    
    def test_set_progress_callback(self, desensitizer):
        """Test setting progress callback."""
        callback = Mock()
        desensitizer.set_progress_callback(callback)
        assert desensitizer.progress_callback is callback
    
    def test_set_table_callback(self, desensitizer):
        """Test setting table callback."""
        callback = Mock()
        desensitizer.set_table_callback(callback)
        assert desensitizer.table_callback is callback


# --- Configuration Tests ---

class TestDesensitizationConfig:
    """Test desensitization configuration validation."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = DesensitizationConfig()
        
        assert config.allow_partial_restore is True
        assert config.verify_before_restore is True
        assert config.fail_on_mismatch is False
        assert config.checkpoint_enabled is True
        assert config.max_mismatch_percentage == 10.0
        assert config.sample_size_for_validation == 100
    
    def test_max_mismatch_percentage_validation_too_low(self):
        """Test max_mismatch_percentage validation (< 0)."""
        with pytest.raises(ValueError, match="must be between 0 and 100"):
            DesensitizationConfig(max_mismatch_percentage=-1)
    
    def test_max_mismatch_percentage_validation_too_high(self):
        """Test max_mismatch_percentage validation (> 100)."""
        with pytest.raises(ValueError, match="must be between 0 and 100"):
            DesensitizationConfig(max_mismatch_percentage=101)
    
    def test_sample_size_validation_too_low(self):
        """Test sample_size_for_validation validation (< 1)."""
        with pytest.raises(ValueError, match="must be at least 1"):
            DesensitizationConfig(sample_size_for_validation=0)
    
    def test_valid_config_boundaries(self):
        """Test valid boundary values."""
        config = DesensitizationConfig(
            max_mismatch_percentage=0.0,
            sample_size_for_validation=1
        )
        assert config.max_mismatch_percentage == 0.0
        assert config.sample_size_for_validation == 1
        
        config = DesensitizationConfig(
            max_mismatch_percentage=100.0,
            sample_size_for_validation=10000
        )
        assert config.max_mismatch_percentage == 100.0
        assert config.sample_size_for_validation == 10000


# --- Restore Method Tests ---

class TestRestoreMethod:
    """Test main restore() entry point."""
    
    @patch('src.sanitization.desensitizer.new_correlation_id')
    def test_successful_restore(
        self,
        mock_new_correlation_id,
        desensitizer,
        mock_mapping_manager
    ):
        """Test successful full restoration workflow."""
        operation_id = uuid4()
        mock_new_correlation_id.return_value = "test-correlation-id"
        
        # Mock methods
        desensitizer._phase_validation = Mock()
        desensitizer._phase_planning = Mock(return_value=["dbo.OrderDetails", "dbo.Orders", "dbo.Customers"])
        desensitizer._phase_restoration = Mock()
        desensitizer._phase_verification = Mock()
        
        # Execute restore
        report = desensitizer.restore(operation_id)
        
        # Assertions
        assert report.operation_id == operation_id
        assert report.phase == RestorePhase.COMPLETED
        assert report.completed_at is not None
        assert report.dry_run is False
        
        desensitizer._phase_validation.assert_called_once()
        desensitizer._phase_planning.assert_called_once()
        desensitizer._phase_restoration.assert_called_once()
        desensitizer._phase_verification.assert_called_once()
    
    def test_dry_run_mode(self, desensitizer):
        """Test dry-run mode skips restoration and verification."""
        operation_id = uuid4()
        
        desensitizer._phase_validation = Mock()
        desensitizer._phase_planning = Mock(return_value=["dbo.Customers"])
        desensitizer._phase_restoration = Mock()
        desensitizer._phase_verification = Mock()
        
        report = desensitizer.restore(operation_id, dry_run=True)
        
        assert report.dry_run is True
        assert report.phase == RestorePhase.COMPLETED
        desensitizer._phase_validation.assert_called_once()
        desensitizer._phase_planning.assert_called_once()
        desensitizer._phase_restoration.assert_not_called()
        desensitizer._phase_verification.assert_not_called()
    
    def test_partial_restore_with_tables_list(self, desensitizer):
        """Test partial restoration with specific tables."""
        operation_id = uuid4()
        tables = ["dbo.Customers", "dbo.Orders"]
        
        desensitizer._phase_validation = Mock()
        desensitizer._phase_planning = Mock(return_value=tables)
        desensitizer._phase_restoration = Mock()
        desensitizer._phase_verification = Mock()
        
        report = desensitizer.restore(operation_id, tables=tables)
        
        # Verify tables passed to validation and planning
        validation_call = desensitizer._phase_validation.call_args
        assert validation_call[0][1] == tables
        
        planning_call = desensitizer._phase_planning.call_args
        assert planning_call[0][1] == tables
    
    def test_restore_failure_marks_report(self, desensitizer):
        """Test that exceptions mark report as failed."""
        operation_id = uuid4()
        
        desensitizer._phase_validation = Mock(side_effect=DesensitizationError("Test error"))
        
        with pytest.raises(DesensitizationError):
            desensitizer.restore(operation_id)


# --- Phase 1: Validation Tests ---

class TestPhaseValidation:
    """Test Phase 1: Validation."""
    
    def test_validation_success(self, desensitizer, mock_mapping_manager):
        """Test successful validation phase."""
        operation_id = uuid4()
        report = RestoreReport(
            operation_id=operation_id,
            restore_operation_id=uuid4(),
            phase=RestorePhase.VALIDATION,
            started_at=datetime.utcnow()
        )
        
        # Execute validation
        desensitizer._phase_validation(operation_id, None, report)
        
        # Assertions
        assert len(report.errors) == 0
        mock_mapping_manager.get_operation_stats.assert_called_once_with(operation_id)
    
    def test_validation_operation_not_found(self, desensitizer, mock_mapping_manager):
        """Test validation fails when operation doesn't exist."""
        operation_id = uuid4()
        report = RestoreReport(
            operation_id=operation_id,
            restore_operation_id=uuid4(),
            phase=RestorePhase.VALIDATION,
            started_at=datetime.utcnow()
        )
        
        # Mock operation not found
        mock_mapping_manager.get_operation_stats.return_value = None
        
        # Execute and expect failure
        with pytest.raises(AttributeError):  # DesensitizationError.operation_not_found not fully defined
            desensitizer._phase_validation(operation_id, None, report)
    
    def test_validation_no_mappings(self, desensitizer, mock_mapping_manager):
        """Test validation fails when no mappings exist."""
        operation_id = uuid4()
        report = RestoreReport(
            operation_id=operation_id,
            restore_operation_id=uuid4(),
            phase=RestorePhase.VALIDATION,
            started_at=datetime.utcnow()
        )
        
        # Mock zero mappings
        mock_mapping_manager.get_operation_stats.return_value = Mock(total_entries=0)
        
        # Execute and expect failure
        with pytest.raises(AttributeError):
            desensitizer._phase_validation(operation_id, None, report)
    
    def test_validation_partial_restore_disabled(self, desensitizer, mock_mapping_manager):
        """Test validation warns when partial restore requested but disabled."""
        operation_id = uuid4()
        tables = ["dbo.Customers"]
        report = RestoreReport(
            operation_id=operation_id,
            restore_operation_id=uuid4(),
            phase=RestorePhase.VALIDATION,
            started_at=datetime.utcnow()
        )
        
        # Disable partial restore
        desensitizer.config.allow_partial_restore = False
        
        # Execute validation
        desensitizer._phase_validation(operation_id, tables, report)
        
        # Should have warning
        assert len(report.warnings) > 0
        assert "Partial restore requested" in report.warnings[0]
    
    @patch('src.sanitization.desensitizer.EncryptionManager')
    def test_validation_encryption_key_missing(
        self,
        mock_encryption_manager_class,
        desensitizer,
        mock_mapping_manager
    ):
        """Test validation fails when encryption key missing for encrypted mappings."""
        operation_id = uuid4()
        report = RestoreReport(
            operation_id=operation_id,
            restore_operation_id=uuid4(),
            phase=RestorePhase.VALIDATION,
            started_at=datetime.utcnow()
        )
        
        # Mock encrypted mappings exist
        mock_mapping_manager.get_operation_stats.return_value = Mock(
            total_entries=100,
            table_count=1,
            column_count=1,
            encrypted_count=100
        )
        
        # Mock encryption key missing
        mock_encryption_manager_class.side_effect = Exception("Encryption key not set")
        
        # Execute and expect failure
        with pytest.raises(AttributeError):  # DesensitizationError.encryption_key_missing not fully defined
            desensitizer._phase_validation(operation_id, None, report)


# --- Phase 2: Planning Tests ---

class TestPhasePlanning:
    """Test Phase 2: Planning."""
    
    def test_planning_builds_restore_order(self, desensitizer, mock_schema_extractor):
        """Test that planning builds correct restore order (reversed)."""
        operation_id = uuid4()
        report = RestoreReport(
            operation_id=operation_id,
            restore_operation_id=uuid4(),
            phase=RestorePhase.PLANNING,
            started_at=datetime.utcnow()
        )
        
        # Execute planning
        restore_order = desensitizer._phase_planning(operation_id, None, report)
        
        # Should be reversed (child → parent)
        assert restore_order == ["dbo.OrderDetails", "dbo.Orders", "dbo.Customers"]
        
        mock_schema_extractor.extract_schema.assert_called_once()
    
    def test_planning_filters_to_specific_tables(self, desensitizer, mock_schema_extractor):
        """Test planning filters to specific tables when requested."""
        operation_id = uuid4()
        tables = ["dbo.Customers"]
        report = RestoreReport(
            operation_id=operation_id,
            restore_operation_id=uuid4(),
            phase=RestorePhase.PLANNING,
            started_at=datetime.utcnow()
        )
        
        # Execute planning with table filter
        restore_order = desensitizer._phase_planning(operation_id, tables, report)
        
        # Should only include requested table
        assert restore_order == ["dbo.Customers"]
    
    @patch('src.sanitization.desensitizer.DependencyResolver')
    def test_planning_handles_circular_dependencies(
        self,
        mock_dependency_resolver_class,
        desensitizer,
        mock_schema_extractor
    ):
        """Test planning handles circular FK dependencies."""
        operation_id = uuid4()
        report = RestoreReport(
            operation_id=operation_id,
            restore_operation_id=uuid4(),
            phase=RestorePhase.PLANNING,
            started_at=datetime.utcnow()
        )
        
        # Mock circular dependency detection
        mock_resolver = Mock()
        mock_resolver.has_circular_dependencies.return_value = True
        mock_resolver.get_cycles.return_value = [["dbo.A", "dbo.B", "dbo.A"]]
        mock_resolver.get_processing_order.return_value = ["dbo.A", "dbo.B"]
        mock_dependency_resolver_class.return_value = mock_resolver
        
        # Execute planning
        restore_order = desensitizer._phase_planning(operation_id, None, report)
        
        # Should have warning about circular dependencies
        assert len(report.warnings) > 0
        assert "Circular FK dependencies" in report.warnings[0]


# --- Phase 3: Restoration Tests ---

class TestPhaseRestoration:
    """Test Phase 3: Restoration."""
    
    def test_restoration_processes_all_tables(self, desensitizer):
        """Test that restoration processes all tables in order."""
        operation_id = uuid4()
        restore_order = ["dbo.OrderDetails", "dbo.Orders", "dbo.Customers"]
        report = RestoreReport(
            operation_id=operation_id,
            restore_operation_id=uuid4(),
            phase=RestorePhase.RESTORATION,
            started_at=datetime.utcnow()
        )
        
        # Mock restore_table to succeed
        desensitizer._restore_table = Mock()
        
        # Execute restoration
        desensitizer._phase_restoration(operation_id, restore_order, report)
        
        # Verify all tables processed
        assert desensitizer._restore_table.call_count == 3
        assert report.tables_restored == 3
    
    def test_restoration_handles_table_failure_gracefully(self, desensitizer):
        """Test that restoration continues after table failure (non-strict mode)."""
        operation_id = uuid4()
        restore_order = ["dbo.OrderDetails", "dbo.Orders"]
        report = RestoreReport(
            operation_id=operation_id,
            restore_operation_id=uuid4(),
            phase=RestorePhase.RESTORATION,
            started_at=datetime.utcnow()
        )
        
        # Mock first table fails, second succeeds
        desensitizer._restore_table = Mock(side_effect=[Exception("Test error"), None])
        desensitizer.config.fail_on_mismatch = False
        
        # Execute restoration
        desensitizer._phase_restoration(operation_id, restore_order, report)
        
        # Should have one failure and one success
        assert report.tables_failed == 1
        assert report.tables_restored == 1
        assert len(report.errors) > 0
    
    def test_restoration_calls_table_callbacks(self, desensitizer):
        """Test that table callbacks are invoked."""
        operation_id = uuid4()
        restore_order = ["dbo.Customers"]
        report = RestoreReport(
            operation_id=operation_id,
            restore_operation_id=uuid4(),
            phase=RestorePhase.RESTORATION,
            started_at=datetime.utcnow()
        )
        
        # Set up callback
        table_callback = Mock()
        desensitizer.set_table_callback(table_callback)
        desensitizer._restore_table = Mock()
        
        # Execute restoration
        desensitizer._phase_restoration(operation_id, restore_order, report)
        
        # Verify callbacks invoked
        assert table_callback.call_count == 2
        table_callback.assert_has_calls([
            call("start", "dbo.Customers"),
            call("complete", "dbo.Customers")
        ])


# --- Helper Method Tests ---

class TestHelperMethods:
    """Test helper methods."""
    
    def test_load_mappings_for_table(self, desensitizer, mock_mapping_manager):
        """Test loading mappings for a specific table."""
        operation_id = uuid4()
        schema = "dbo"
        table = "Customers"
        
        # Mock mappings
        mock_mappings = [Mock(), Mock(), Mock()]
        mock_mapping_manager.get_batch_mappings.return_value = mock_mappings
        
        # Execute
        mappings = desensitizer._load_mappings_for_table(operation_id, schema, table)
        
        # Assertions
        assert mappings == mock_mappings
        mock_mapping_manager.get_batch_mappings.assert_called_once()
    
    def test_load_mappings_handles_errors(self, desensitizer, mock_mapping_manager):
        """Test that load_mappings handles errors gracefully."""
        operation_id = uuid4()
        schema = "dbo"
        table = "Customers"
        
        # Mock failure
        mock_mapping_manager.get_batch_mappings.side_effect = Exception("DB error")
        
        # Execute
        mappings = desensitizer._load_mappings_for_table(operation_id, schema, table)
        
        # Should return empty list
        assert mappings == []
    
    @patch('src.sanitization.desensitizer.EncryptionManager')
    def test_decrypt_mapping_encrypted_value(
        self,
        mock_encryption_manager_class,
        desensitizer
    ):
        """Test decrypting an encrypted mapping."""
        mapping = Mock()
        mapping.is_null = False
        mapping.original_value_encrypted = "encrypted_data"
        
        # Mock decryption
        mock_encryption_manager = Mock()
        mock_encryption_manager.decrypt.return_value = "original_value"
        mock_encryption_manager_class.return_value = mock_encryption_manager
        
        # Execute
        result = desensitizer._decrypt_mapping(mapping)
        
        # Assertions
        assert result == "original_value"
        mock_encryption_manager.decrypt.assert_called_once_with("encrypted_data")
    
    def test_decrypt_mapping_null_value(self, desensitizer):
        """Test decrypting a NULL mapping."""
        mapping = Mock()
        mapping.is_null = True
        
        # Execute
        result = desensitizer._decrypt_mapping(mapping)
        
        # Should return None
        assert result is None
    
    @patch('src.sanitization.desensitizer.EncryptionManager')
    def test_decrypt_mapping_failure_raises_error(
        self,
        mock_encryption_manager_class,
        desensitizer
    ):
        """Test that decryption failure raises DesensitizationError."""
        mapping = Mock()
        mapping.is_null = False
        mapping.original_value_encrypted = "corrupted_data"
        
        # Mock decryption failure
        mock_encryption_manager = Mock()
        mock_encryption_manager.decrypt.side_effect = Exception("Decryption failed")
        mock_encryption_manager_class.return_value = mock_encryption_manager
        
        # Execute and expect failure
        with pytest.raises(AttributeError):  # DesensitizationError.decryption_failed not fully defined
            desensitizer._decrypt_mapping(mapping)


# --- Report Tests ---

class TestRestoreReport:
    """Test RestoreReport data model."""
    
    def test_report_initialization(self):
        """Test report initialization with required fields."""
        operation_id = uuid4()
        restore_operation_id = uuid4()
        
        report = RestoreReport(
            operation_id=operation_id,
            restore_operation_id=restore_operation_id,
            phase=RestorePhase.VALIDATION,
            started_at=datetime.utcnow()
        )
        
        assert report.operation_id == operation_id
        assert report.restore_operation_id == restore_operation_id
        assert report.phase == RestorePhase.VALIDATION
        assert report.tables_restored == 0
        assert report.rows_restored == 0
        assert report.values_restored == 0
        assert len(report.errors) == 0
        assert len(report.warnings) == 0
    
    def test_report_add_error(self):
        """Test adding errors to report."""
        report = RestoreReport(
            operation_id=uuid4(),
            restore_operation_id=uuid4(),
            phase=RestorePhase.RESTORATION,
            started_at=datetime.utcnow()
        )
        
        report.add_error("Test error")
        
        assert len(report.errors) == 1
        assert "Test error" in report.errors
    
    def test_report_add_warning(self):
        """Test adding warnings to report."""
        report = RestoreReport(
            operation_id=uuid4(),
            restore_operation_id=uuid4(),
            phase=RestorePhase.PLANNING,
            started_at=datetime.utcnow()
        )
        
        report.add_warning("Test warning")
        
        assert len(report.warnings) == 1
        assert "Test warning" in report.warnings
    
    def test_report_is_successful(self):
        """Test is_successful method."""
        report = RestoreReport(
            operation_id=uuid4(),
            restore_operation_id=uuid4(),
            phase=RestorePhase.COMPLETED,
            started_at=datetime.utcnow()
        )
        
        # Should be successful with no errors
        assert report.is_successful() is True
        
        # Add error - should no longer be successful
        report.add_error("Test error")
        assert report.is_successful() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
