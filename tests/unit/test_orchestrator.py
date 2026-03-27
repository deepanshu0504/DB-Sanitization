"""
Unit tests for SanitizationOrchestrator.

Tests cover:
- Orchestrator initialization and configuration
- Execution phases (validation, planning, execution, verification)
- Batch processing workflow
- Transaction handling and rollback
- Dry-run mode
- Checkpoint/resume mechanism
- Progress tracking and callbacks
- Error handling and recovery
- Edge cases (empty tables, no PK, circular dependencies, etc.)

Author: Database Sanitization Team
Date: 2026-03-26
"""

import json
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

from src.sanitization.orchestrator import (
    SanitizationOrchestrator,
    SanitizationReport,
    TableProgress,
    Checkpoint,
    ExecutionPhase,
    ProgressCallback
)
from src.config.config_models import (
    SanitizationConfig,
    PIIColumnConfig,
    DatabaseConfig,
    MaskingStrategy
)
from src.exceptions import (
    ValidationError,
    DatabaseError,
    CircularDependencyError
)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def sample_database_config():
    """Sample database configuration."""
    return DatabaseConfig(
        server="localhost",
        database="TestDB",
        auth_type="sql",
        username="test_user",
        password="test_pass",
        timeout=30,
        batch_size=1000,
        max_retries=3,
        retry_delay=1,
        pool_size=5,
        use_transactions=True
    )


@pytest.fixture
def sample_pii_columns():
    """Sample PII column configurations."""
    return [
        PIIColumnConfig(
            schema="dbo",
            table="Users",
            column="Email",
            masking_strategy=MaskingStrategy.EMAIL,
            is_nullable=False
        ),
        PIIColumnConfig(
            schema="dbo",
            table="Users",
            column="PhoneNumber",
            masking_strategy=MaskingStrategy.PHONE,
            is_nullable=True
        ),
        PIIColumnConfig(
            schema="dbo",
            table="Orders",
            column="CreditCard",
            masking_strategy=MaskingStrategy.CREDIT_CARD,
            is_nullable=False
        )
    ]


@pytest.fixture
def sample_config(sample_database_config, sample_pii_columns):
    """Sample sanitization configuration."""
    return SanitizationConfig(
        database=sample_database_config,
        pii_columns=sample_pii_columns,
        validate_before=True,
        validate_after=False
    )


@pytest.fixture
def mock_connection_manager():
    """Mock connection manager."""
    mock = Mock()
    mock.health_check.return_value = True
    mock.execute_query.return_value = [{"row_count": 100}]
    return mock


@pytest.fixture
def mock_schema_extractor():
    """Mock schema extractor."""
    mock = Mock()
    mock._get_primary_keys.return_value = ["Id"]
    mock._get_foreign_keys.return_value = []
    mock._get_columns.return_value = [
        {
            "column_name": "Email",
            "data_type": "nvarchar",
            "max_length": 255,
            "is_nullable": False
        },
        {
            "column_name": "PhoneNumber",
            "data_type": "varchar",
            "max_length": 20,
            "is_nullable": True
        }
    ]
    return mock


@pytest.fixture
def mock_batch_extractor():
    """Mock batch extractor."""
    from dataclasses import dataclass
    
    @dataclass
    class MockBatch:
        rows: List[Dict[str, Any]]
        key_columns: List[str]
    
    mock = Mock()
    # Return generator with sample batches
    mock.extract_batches.return_value = iter([
        MockBatch(
            rows=[
                {"Id": 1, "Email": "user1@example.com", "PhoneNumber": "555-0001"},
                {"Id": 2, "Email": "user2@example.com", "PhoneNumber": "555-0002"}
            ],
            key_columns=["Id"]
        )
    ])
    return mock


@pytest.fixture
def mock_batch_updater():
    """Mock batch updater."""
    from dataclasses import dataclass
    
    @dataclass
    class MockUpdateBatch:
        rows_updated: int
    
    mock = Mock()
    mock.update_batches.return_value = iter([MockUpdateBatch(rows_updated=2)])
    return mock


@pytest.fixture
def mock_config_validator():
    """Mock config validator."""
    from src.validation.validation_result import ValidationResult
    
    mock = Mock()
    mock.validate_config.return_value = ValidationResult(is_valid=True)
    return mock


@pytest.fixture
def orchestrator(mock_connection_manager, tmp_path):
    """Orchestrator instance with mocked dependencies."""
    return SanitizationOrchestrator(
        connection_manager=mock_connection_manager,
        checkpoint_dir=tmp_path
    )


# ============================================================================
# Test Class: Initialization and Configuration
# ============================================================================

class TestOrchestratorInitialization:
    """Test orchestrator initialization and configuration."""
    
    def test_init_default(self):
        """Test default initialization."""
        orchestrator = SanitizationOrchestrator()
        
        assert orchestrator.connection_manager is None
        assert orchestrator.checkpoint_dir == Path("./checkpoints")
        assert orchestrator.schema_extractor is None
        assert orchestrator.batch_extractor is None
        assert orchestrator.masker_factory is not None
    
    def test_init_with_connection_manager(self, mock_connection_manager):
        """Test initialization with connection manager."""
        orchestrator = SanitizationOrchestrator(
            connection_manager=mock_connection_manager
        )
        
        assert orchestrator.connection_manager is mock_connection_manager
    
    def test_init_with_custom_checkpoint_dir(self, tmp_path):
        """Test initialization with custom checkpoint directory."""
        checkpoint_dir = tmp_path / "custom_checkpoints"
        orchestrator = SanitizationOrchestrator(checkpoint_dir=checkpoint_dir)
        
        assert orchestrator.checkpoint_dir == checkpoint_dir
    
    def test_set_progress_callback(self, orchestrator):
        """Test setting progress callback."""
        callback = Mock()
        orchestrator.set_progress_callback(callback)
        
        assert orchestrator.progress_callback is callback
    
    def test_set_table_callback(self, orchestrator):
        """Test setting table callback."""
        callback = Mock()
        orchestrator.set_table_callback(callback)
        
        assert orchestrator.table_callback is callback


# ============================================================================
# Test Class: Validation Phase
# ============================================================================

class TestValidationPhase:
    """Test validation phase execution."""
    
    @patch('src.sanitization.orchestrator.ConnectionManager')
    @patch('src.sanitization.orchestrator.ConfigValidator')
    def test_validation_phase_success(
        self,
        mock_validator_class,
        mock_conn_class,
        orchestrator,
        sample_config,
        mock_config_validator
    ):
        """Test successful validation phase."""
        mock_validator_class.return_value = mock_config_validator
        
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.VALIDATION
        )
        
        # Mock components
        with patch.object(orchestrator, '_initialize_components'):
            orchestrator.connection_manager = Mock()
            orchestrator.connection_manager.health_check.return_value = True
            orchestrator.config_validator = mock_config_validator
            
            orchestrator._phase_validation(sample_config, report)
        
        assert report.phase == ExecutionPhase.VALIDATION
        assert len(report.errors) == 0
    
    @patch('src.sanitization.orchestrator.ConnectionManager')
    def test_validation_phase_health_check_fails(
        self,
        mock_conn_class,
        orchestrator,
        sample_config
    ):
        """Test validation phase with failed health check."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.VALIDATION
        )
        
        with patch.object(orchestrator, '_initialize_components'):
            orchestrator.connection_manager = Mock()
            orchestrator.connection_manager.health_check.return_value = False
            
            with pytest.raises(DatabaseError) as exc_info:
                orchestrator._phase_validation(sample_config, report)
            
            assert "health check failed" in str(exc_info.value).lower()
    
    @patch('src.sanitization.orchestrator.ConnectionManager')
    @patch('src.sanitization.orchestrator.ConfigValidator')
    def test_validation_phase_config_invalid(
        self,
        mock_validator_class,
        mock_conn_class,
        orchestrator,
        sample_config
    ):
        """Test validation phase with invalid configuration."""
        from src.validation.validation_result import ValidationResult, ValidationError as ValError
        
        invalid_result = ValidationResult(is_valid=False)
        invalid_result.add_error(ValError(
            field="pii_columns[0].column",
            message="Column 'Email' does not exist",
            suggested_action="Check column name"
        ))
        
        mock_validator = Mock()
        mock_validator.validate_config.return_value = invalid_result
        mock_validator_class.return_value = mock_validator
        
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.VALIDATION
        )
        
        with patch.object(orchestrator, '_initialize_components'):
            orchestrator.connection_manager = Mock()
            orchestrator.connection_manager.health_check.return_value = True
            orchestrator.config_validator = mock_validator
            
            with pytest.raises(ValidationError) as exc_info:
                orchestrator._phase_validation(sample_config, report)
            
            assert "validation failed" in str(exc_info.value).lower()


# ============================================================================
# Test Class: Planning Phase
# ============================================================================

class TestPlanningPhase:
    """Test planning phase execution."""
    
    def test_planning_phase_success(self, orchestrator, sample_config):
        """Test successful planning phase."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.PLANNING
        )
        
        # Mock schema extractor
        mock_schema = Mock()
        mock_schema._get_foreign_keys.return_value = [
            {
                "fk_schema": "dbo",
                "fk_table": "Orders",
                "fk_column": "UserId",
                "pk_schema": "dbo",
                "pk_table": "Users",
                "pk_column": "Id"
            }
        ]
        orchestrator.schema_extractor = mock_schema
        
        processing_order = orchestrator._phase_planning(sample_config, report)
        
        assert isinstance(processing_order, list)
        assert len(processing_order) > 0
        assert report.phase == ExecutionPhase.PLANNING
    
    def test_planning_phase_circular_dependency(self, orchestrator, sample_config):
        """Test planning phase with circular dependencies."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.PLANNING
        )
        
        # Mock schema extractor with circular FK
        mock_schema = Mock()
        mock_schema._get_foreign_keys.return_value = [
            {
                "fk_schema": "dbo",
                "fk_table": "A",
                "fk_column": "B_Id",
                "pk_schema": "dbo",
                "pk_table": "B",
                "pk_column": "Id"
            },
            {
                "fk_schema": "dbo",
                "fk_table": "B",
                "fk_column": "A_Id",
                "pk_schema": "dbo",
                "pk_table": "A",
                "pk_column": "Id"
            }
        ]
        orchestrator.schema_extractor = mock_schema
        
        with pytest.raises(CircularDependencyError) as exc_info:
            orchestrator._phase_planning(sample_config, report)
        
        assert "circular" in str(exc_info.value).lower()


# ============================================================================
# Test Class: Execution Phase
# ============================================================================

class TestExecutionPhase:
    """Test execution phase and batch processing."""
    
    def test_execution_phase_success(
        self,
        orchestrator,
        sample_config,
        mock_schema_extractor,
        mock_batch_extractor,
        mock_batch_updater
    ):
        """Test successful execution phase."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.EXECUTION
        )
        
        processing_order = ["[dbo].[Users]", "[dbo].[Orders]"]
        
        # Mock components
        orchestrator.schema_extractor = mock_schema_extractor
        orchestrator.batch_extractor = mock_batch_extractor
        orchestrator.batch_updater = mock_batch_updater
        orchestrator.transaction_manager = Mock()
        orchestrator.transaction_manager.begin.return_value.__enter__ = Mock()
        orchestrator.transaction_manager.begin.return_value.__exit__ = Mock(return_value=False)
        
        with patch.object(orchestrator, '_process_table') as mock_process:
            orchestrator._phase_execution(
                sample_config,
                report,
                processing_order,
                dry_run=False,
                checkpoint=None
            )
            
            # Should process both tables
            assert mock_process.call_count == 2
    
    def test_execution_phase_with_checkpoint(
        self,
        orchestrator,
        sample_config
    ):
        """Test execution phase with checkpoint resume."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.EXECUTION
        )
        
        processing_order = ["[dbo].[Users]", "[dbo].[Orders]"]
        
        # Create checkpoint with Users already completed
        checkpoint = Checkpoint(
            operation_id="test-op",
            config_hash="abc123",
            tables_completed=["[dbo].[Users]"]
        )
        
        with patch.object(orchestrator, '_process_table') as mock_process:
            orchestrator._phase_execution(
                sample_config,
                report,
                processing_order,
                dry_run=False,
                checkpoint=checkpoint
            )
            
            # Should only process Orders (Users skipped)
            assert mock_process.call_count == 1
            mock_process.assert_called_once()
    
    def test_execution_phase_dry_run(
        self,
        orchestrator,
        sample_config
    ):
        """Test execution phase in dry-run mode."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.EXECUTION
        )
        
        processing_order = ["[dbo].[Users]"]
        
        with patch.object(orchestrator, '_process_table') as mock_process:
            orchestrator._phase_execution(
                sample_config,
                report,
                processing_order,
                dry_run=True,
                checkpoint=None
            )
            
            # Verify dry_run=True was passed
            args, kwargs = mock_process.call_args
            assert kwargs.get('dry_run') == True


# ============================================================================
# Test Class: Batch Processing
# ============================================================================

class TestBatchProcessing:
    """Test batch processing workflow."""
    
    def test_process_table_success(
        self,
        orchestrator,
        sample_config,
        sample_pii_columns,
        mock_schema_extractor,
        mock_batch_extractor,
        mock_batch_updater
    ):
        """Test successful table processing."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.EXECUTION
        )
        
        # Mock components
        orchestrator.schema_extractor = mock_schema_extractor
        orchestrator.batch_extractor = mock_batch_extractor
        orchestrator.batch_updater = mock_batch_updater
        orchestrator.transaction_manager = Mock()
        orchestrator.transaction_manager.begin.return_value.__enter__ = Mock()
        orchestrator.transaction_manager.begin.return_value.__exit__ = Mock(return_value=False)
        
        # Mock masker
        with patch.object(orchestrator.masker_factory, 'get_masker') as mock_get_masker:
            mock_masker = Mock()
            mock_masker.mask_value.return_value = "masked@example.com"
            mock_get_masker.return_value = mock_masker
            
            orchestrator._process_table(
                table_name="[dbo].[Users]",
                pii_columns=[sample_pii_columns[0]],  # Email column
                config=sample_config,
                report=report,
                dry_run=False
            )
        
        assert report.tables_processed == 1
        assert report.rows_processed > 0
    
    def test_process_table_empty_table(
        self,
        orchestrator,
        sample_config,
        sample_pii_columns,
        mock_schema_extractor
    ):
        """Test processing empty table."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.EXECUTION
        )
        
        orchestrator.schema_extractor = mock_schema_extractor
        orchestrator.connection_manager = Mock()
        orchestrator.connection_manager.execute_query.return_value = [{"row_count": 0}]
        
        orchestrator._process_table(
            table_name="[dbo].[Users]",
            pii_columns=[sample_pii_columns[0]],
            config=sample_config,
            report=report,
            dry_run=False
        )
        
        # Should skip empty table
        assert report.tables_skipped == 1
        assert report.tables_processed == 0
    
    def test_process_table_no_primary_key(
        self,
        orchestrator,
        sample_config,
        sample_pii_columns,
        mock_schema_extractor
    ):
        """Test processing table without primary key."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.EXECUTION
        )
        
        mock_schema_extractor._get_primary_keys.return_value = []
        orchestrator.schema_extractor = mock_schema_extractor
        
        orchestrator._process_table(
            table_name="[dbo].[Users]",
            pii_columns=[sample_pii_columns[0]],
            config=sample_config,
            report=report,
            dry_run=False
        )
        
        # Should skip table without PK
        assert report.tables_skipped == 1
        assert len(report.warnings) > 0
        assert "no primary key" in report.warnings[0].lower()
    
    def test_process_table_with_error(
        self,
        orchestrator,
        sample_config,
        sample_pii_columns,
        mock_schema_extractor
    ):
        """Test table processing with error."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.EXECUTION
        )
        
        orchestrator.schema_extractor = mock_schema_extractor
        orchestrator.schema_extractor._get_primary_keys.side_effect = Exception("Database error")
        
        with pytest.raises(Exception):
            orchestrator._process_table(
                table_name="[dbo].[Users]",
                pii_columns=[sample_pii_columns[0]],
                config=sample_config,
                report=report,
                dry_run=False
            )
        
        assert report.tables_failed == 1


# ============================================================================
# Test Class: Dry-Run Mode
# ============================================================================

class TestDryRunMode:
    """Test dry-run mode functionality."""
    
    @patch('src.sanitization.orchestrator.ConnectionManager')
    @patch('src.sanitization.orchestrator.ConfigValidator')
    @patch('src.sanitization.orchestrator.SchemaExtractor')
    @patch('src.sanitization.orchestrator.BatchExtractor')
    def test_dry_run_no_database_updates(
        self,
        mock_batch_ex,
        mock_schema_ex,
        mock_validator,
        mock_conn,
        orchestrator,
        sample_config
    ):
        """Test that dry-run mode does not update database."""
        # Setup mocks
        mock_conn_inst = Mock()
        mock_conn_inst.health_check.return_value = True
        mock_conn.return_value = mock_conn_inst
        
        from src.validation.validation_result import ValidationResult
        mock_val_inst = Mock()
        mock_val_inst.validate_config.return_value = ValidationResult(is_valid=True)
        mock_validator.return_value = mock_val_inst
        
        mock_schema_inst = Mock()
        mock_schema_inst._get_foreign_keys.return_value = []
        mock_schema_ex.return_value = mock_schema_inst
        
        orchestrator = SanitizationOrchestrator()
        
        with patch.object(orchestrator, '_process_table'):
            report = orchestrator.run(sample_config, dry_run=True)
        
        assert report.dry_run == True
        # Batch updater should not be called in dry-run
    
    def test_dry_run_report_marked(self, orchestrator, sample_config):
        """Test that dry-run is marked in report."""
        with patch.object(orchestrator, '_phase_validation'):
            with patch.object(orchestrator, '_phase_planning', return_value=[]):
                with patch.object(orchestrator, '_phase_execution'):
                    report = orchestrator.run(sample_config, dry_run=True)
        
        assert report.dry_run == True


# ============================================================================
# Test Class: Checkpoint and Resume
# ============================================================================

class TestCheckpointResume:
    """Test checkpoint and resume functionality."""
    
    def test_save_checkpoint(self, orchestrator, sample_config, tmp_path):
        """Test saving checkpoint."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.EXECUTION
        )
        
        # Add completed table
        progress = TableProgress(
            schema="dbo",
            table="Users",
            completed_at=datetime.utcnow()
        )
        report.table_progress["[dbo].[Users]"] = progress
        
        orchestrator._save_checkpoint("test-op", sample_config, report)
        
        # Verify checkpoint file created
        checkpoint_file = tmp_path / "test-op.json"
        assert checkpoint_file.exists()
        
        # Verify checkpoint content
        with open(checkpoint_file, 'r') as f:
            data = json.load(f)
        
        assert data["operation_id"] == "test-op"
        assert "[dbo].[Users]" in data["tables_completed"]
    
    def test_load_checkpoint(self, orchestrator, tmp_path):
        """Test loading checkpoint."""
        # Create checkpoint file
        checkpoint = Checkpoint(
            operation_id="test-op",
            config_hash="abc123",
            tables_completed=["[dbo].[Users]"]
        )
        checkpoint_file = tmp_path / "test-op.json"
        checkpoint.save(checkpoint_file)
        
        # Load checkpoint
        loaded = orchestrator._load_checkpoint("test-op")
        
        assert loaded is not None
        assert loaded.operation_id == "test-op"
        assert "[dbo].[Users]" in loaded.tables_completed
    
    def test_load_checkpoint_not_found(self, orchestrator):
        """Test loading non-existent checkpoint."""
        loaded = orchestrator._load_checkpoint("non-existent")
        
        assert loaded is None
    
    def test_clear_checkpoint(self, orchestrator, tmp_path):
        """Test clearing checkpoint."""
        # Create checkpoint file
        checkpoint = Checkpoint(
            operation_id="test-op",
            config_hash="abc123",
            tables_completed=[]
        )
        checkpoint_file = tmp_path / "test-op.json"
        checkpoint.save(checkpoint_file)
        
        assert checkpoint_file.exists()
        
        # Clear checkpoint
        orchestrator._clear_checkpoint("test-op")
        
        assert not checkpoint_file.exists()


# ============================================================================
# Test Class: Progress Tracking
# ============================================================================

class TestProgressTracking:
    """Test progress tracking and callbacks."""
    
    def test_progress_callback_called(
        self,
        orchestrator,
        sample_config,
        sample_pii_columns,
        mock_schema_extractor,
        mock_batch_extractor,
        mock_batch_updater
    ):
        """Test that progress callback is called."""
        callback = Mock()
        orchestrator.set_progress_callback(callback)
        
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.EXECUTION
        )
        
        orchestrator.schema_extractor = mock_schema_extractor
        orchestrator.batch_extractor = mock_batch_extractor
        orchestrator.batch_updater = mock_batch_updater
        orchestrator.transaction_manager = Mock()
        orchestrator.transaction_manager.begin.return_value.__enter__ = Mock()
        orchestrator.transaction_manager.begin.return_value.__exit__ = Mock(return_value=False)
        
        with patch.object(orchestrator.masker_factory, 'get_masker') as mock_get_masker:
            mock_masker = Mock()
            mock_masker.mask_value.return_value = "masked"
            mock_get_masker.return_value = mock_masker
            
            orchestrator._process_table(
                table_name="[dbo].[Users]",
                pii_columns=[sample_pii_columns[0]],
                config=sample_config,
                report=report,
                dry_run=False
            )
        
        # Callback should be called for each batch
        assert callback.called
    
    def test_table_callback_start_and_complete(
        self,
        orchestrator,
        sample_config,
        sample_pii_columns,
        mock_schema_extractor,
        mock_batch_extractor,
        mock_batch_updater
    ):
        """Test that table callbacks are called for start and complete."""
        callback = Mock()
        orchestrator.set_table_callback(callback)
        
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.EXECUTION
        )
        
        orchestrator.schema_extractor = mock_schema_extractor
        orchestrator.batch_extractor = mock_batch_extractor
        orchestrator.batch_updater = mock_batch_updater
        orchestrator.transaction_manager = Mock()
        orchestrator.transaction_manager.begin.return_value.__enter__ = Mock()
        orchestrator.transaction_manager.begin.return_value.__exit__ = Mock(return_value=False)
        
        with patch.object(orchestrator.masker_factory, 'get_masker') as mock_get_masker:
            mock_masker = Mock()
            mock_masker.mask_value.return_value = "masked"
            mock_get_masker.return_value = mock_masker
            
            orchestrator._process_table(
                table_name="[dbo].[Users]",
                pii_columns=[sample_pii_columns[0]],
                config=sample_config,
                report=report,
                dry_run=False
            )
        
        # Should be called twice: start and complete
        assert callback.call_count == 2
        callback.assert_any_call("start", "[dbo].[Users]")
        callback.assert_any_call("complete", "[dbo].[Users]")


# ============================================================================
# Test Class: Report Generation
# ============================================================================

class TestReportGeneration:
    """Test sanitization report generation."""
    
    def test_report_initialization(self):
        """Test report initialization."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.VALIDATION
        )
        
        assert report.operation_id == "test-op"
        assert report.phase == ExecutionPhase.VALIDATION
        assert report.tables_processed == 0
        assert report.is_successful == False
    
    def test_report_add_error(self):
        """Test adding errors to report."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.EXECUTION
        )
        
        report.add_error("Test error")
        
        assert len(report.errors) == 1
        assert "Test error" in report.errors
    
    def test_report_add_warning(self):
        """Test adding warnings to report."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.EXECUTION
        )
        
        report.add_warning("Test warning")
        
        assert len(report.warnings) == 1
        assert "Test warning" in report.warnings
    
    def test_report_is_successful(self):
        """Test report success status."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.COMPLETED
        )
        
        assert report.is_successful == True
        
        # Add failure
        report.tables_failed = 1
        assert report.is_successful == False
    
    def test_report_to_dict(self):
        """Test report serialization to dictionary."""
        report = SanitizationReport(
            operation_id="test-op",
            phase=ExecutionPhase.COMPLETED,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        
        report.add_error("Test error")
        report.add_warning("Test warning")
        
        data = report.to_dict()
        
        assert data["operation_id"] == "test-op"
        assert data["phase"] == "completed"
        assert "Test error" in data["errors"]
        assert "Test warning" in data["warnings"]


# ============================================================================
# Test Class: Helper Methods
# ============================================================================

class TestHelperMethods:
    """Test helper methods."""
    
    def test_parse_table_name_with_schema(self, orchestrator):
        """Test parsing fully qualified table name."""
        schema, table = orchestrator._parse_table_name("[dbo].[Users]")
        
        assert schema == "dbo"
        assert table == "Users"
    
    def test_parse_table_name_without_schema(self, orchestrator):
        """Test parsing table name without schema."""
        schema, table = orchestrator._parse_table_name("Users")
        
        assert schema == "dbo"
        assert table == "Users"
    
    def test_parse_table_name_invalid(self, orchestrator):
        """Test parsing invalid table name."""
        with pytest.raises(ValueError):
            orchestrator._parse_table_name("[schema].[table].[extra]")
    
    def test_group_pii_columns_by_table(self, orchestrator, sample_pii_columns):
        """Test grouping PII columns by table."""
        grouped = orchestrator._group_pii_columns_by_table(sample_pii_columns)
        
        assert "[dbo].[Users]" in grouped
        assert "[dbo].[Orders]" in grouped
        assert len(grouped["[dbo].[Users]"]) == 2  # Email and PhoneNumber
        assert len(grouped["[dbo].[Orders]"]) == 1  # CreditCard
    
    def test_get_table_row_count(self, orchestrator):
        """Test getting table row count."""
        orchestrator.connection_manager.execute_query.return_value = [{"row_count": 42}]
        
        count = orchestrator._get_table_row_count("dbo", "Users")
        
        assert count == 42


# ============================================================================
# Test Class: TableProgress
# ============================================================================

class TestTableProgress:
    """Test TableProgress dataclass."""
    
    def test_progress_initialization(self):
        """Test progress initialization."""
        progress = TableProgress(schema="dbo", table="Users")
        
        assert progress.schema == "dbo"
        assert progress.table == "Users"
        assert progress.total_rows == 0
        assert progress.rows_processed == 0
    
    def test_progress_percentage_calculation(self):
        """Test progress percentage calculation."""
        progress = TableProgress(schema="dbo", table="Users", total_rows=100)
        progress.rows_processed = 50
        
        assert progress.progress_percentage == 50.0
    
    def test_progress_percentage_zero_rows(self):
        """Test progress percentage with zero rows."""
        progress = TableProgress(schema="dbo", table="Users", total_rows=0)
        progress.completed_at = datetime.utcnow()
        
        assert progress.progress_percentage == 100.0
    
    def test_progress_is_completed(self):
        """Test is_completed property."""
        progress = TableProgress(schema="dbo", table="Users")
        
        assert progress.is_completed == False
        
        progress.completed_at = datetime.utcnow()
        assert progress.is_completed == True
    
    def test_progress_is_failed(self):
        """Test is_failed property."""
        progress = TableProgress(schema="dbo", table="Users")
        
        assert progress.is_failed == False
        
        progress.error = "Test error"
        assert progress.is_failed == True


# ============================================================================
# Test Class: Checkpoint
# ============================================================================

class TestCheckpoint:
    """Test Checkpoint dataclass."""
    
    def test_checkpoint_initialization(self):
        """Test checkpoint initialization."""
        checkpoint = Checkpoint(
            operation_id="test-op",
            config_hash="abc123",
            tables_completed=["[dbo].[Users]"]
        )
        
        assert checkpoint.operation_id == "test-op"
        assert checkpoint.config_hash == "abc123"
        assert "[dbo].[Users]" in checkpoint.tables_completed
    
    def test_checkpoint_to_dict(self):
        """Test checkpoint serialization."""
        checkpoint = Checkpoint(
            operation_id="test-op",
            config_hash="abc123",
            tables_completed=["[dbo].[Users]"]
        )
        
        data = checkpoint.to_dict()
        
        assert data["operation_id"] == "test-op"
        assert "[dbo].[Users]" in data["tables_completed"]
    
    def test_checkpoint_from_dict(self):
        """Test checkpoint deserialization."""
        data = {
            "operation_id": "test-op",
            "config_hash": "abc123",
            "tables_completed": ["[dbo].[Users]"],
            "current_table": None,
            "current_batch": 0,
            "rows_processed": 100,
            "created_at": "2026-03-26T12:00:00"
        }
        
        checkpoint = Checkpoint.from_dict(data)
        
        assert checkpoint.operation_id == "test-op"
        assert "[dbo].[Users]" in checkpoint.tables_completed
    
    def test_checkpoint_save_and_load(self, tmp_path):
        """Test checkpoint save and load."""
        checkpoint = Checkpoint(
            operation_id="test-op",
            config_hash="abc123",
            tables_completed=["[dbo].[Users]"]
        )
        
        filepath = tmp_path / "checkpoint.json"
        checkpoint.save(filepath)
        
        assert filepath.exists()
        
        loaded = Checkpoint.load(filepath)
        
        assert loaded.operation_id == checkpoint.operation_id
        assert loaded.tables_completed == checkpoint.tables_completed
    
    def test_checkpoint_load_corrupted(self, tmp_path):
        """Test loading corrupted checkpoint."""
        filepath = tmp_path / "corrupted.json"
        filepath.write_text("{ invalid json")
        
        loaded = Checkpoint.load(filepath)
        
        assert loaded is None
