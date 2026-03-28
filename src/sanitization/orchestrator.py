"""
Sanitization Orchestrator for coordinating the entire sanitization workflow.

This module provides a central orchestrator that integrates all components to perform
database sanitization in a safe, efficient, and auditable manner. The orchestrator:
- Validates configuration before execution
- Resolves foreign key dependencies
- Processes tables in topological order (parent → child)
- Masks PII data in batches
- Updates the database with transaction safety
- Provides progress tracking and reporting
- Supports checkpoint/resume for long-running operations
- Offers dry-run mode for validation without changes

Key Features:
    - Dependency injection for all components
    - Progressive execution phases (validate → plan → execute → verify)
    - Batch processing for memory efficiency
    - Transaction safety with rollback support
    - Correlation ID tracking throughout operation
    - Comprehensive error handling and reporting
    - Checkpoint/resume capability
    - Progress callbacks for monitoring
    - Dry-run mode for testing

Usage Example:
    >>> from src.sanitization.orchestrator import SanitizationOrchestrator
    >>> from src.config import ConfigLoader
    >>> 
    >>> # Load configuration
    >>> config = ConfigLoader().load_from_file("config/pii_config.json")
    >>> 
    >>> # Create orchestrator
    >>> orchestrator = SanitizationOrchestrator()
    >>> 
    >>> # Run sanitization (dry-run first to validate)
    >>> dry_run_report = orchestrator.run(config, dry_run=True)
    >>> print(f"Would process {dry_run_report.tables_processed} tables")
    >>> 
    >>> # Run actual sanitization
    >>> report = orchestrator.run(config, dry_run=False)
    >>> print(f"Processed {report.rows_processed} rows in {report.duration_ms}ms")

Author: Database Sanitization Team
Date: 2026-03-26
"""

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Callable, Any, Set
from enum import Enum

from src.config.config_models import SanitizationConfig, PIIColumnConfig
from src.database.connection_manager import DatabaseConnectionManager
from src.database.schema_extractor import SchemaExtractor
from src.database.batch_extractor import BatchExtractor
from src.database.batch_updater import BatchUpdater
from src.database.transaction_manager import TransactionManager
from src.sanitization.dependency_resolver import DependencyResolver
from src.masking.masker_factory import MaskerFactory
from src.masking.base_masker import ColumnInfo, MaskingStrategy
from src.validation.config_validator import ConfigValidator
from src.mapping.mapping_manager import MappingManager
from src.mapping.mapping_models import MappingEntry
from src.exceptions import (
    SanitizationError, 
    DatabaseError, 
    ValidationError,
    CircularDependencyError,
    MappingError
)
from src.logging.logger import get_logger
from src.logging.correlation import CorrelationContext, new_correlation_id
import hashlib


class ExecutionPhase(Enum):
    """Execution phases of the sanitization workflow."""
    VALIDATION = "validation"
    PLANNING = "planning"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TableProgress:
    """Progress tracking for a single table."""
    schema: str
    table: str
    total_rows: int = 0
    rows_processed: int = 0
    batches_completed: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    
    @property
    def fully_qualified_name(self) -> str:
        """Get fully qualified table name."""
        return f"[{self.schema}].[{self.table}]"
    
    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage."""
        if self.total_rows == 0:
            return 100.0 if self.completed_at else 0.0
        return (self.rows_processed / self.total_rows) * 100.0
    
    @property
    def is_completed(self) -> bool:
        """Check if table processing is completed."""
        return self.completed_at is not None
    
    @property
    def is_failed(self) -> bool:
        """Check if table processing failed."""
        return self.error is not None


@dataclass
class Checkpoint:
    """Checkpoint for resuming sanitization after failure."""
    operation_id: str
    config_hash: str
    tables_completed: List[str]
    current_table: Optional[str] = None
    current_batch: int = 0
    rows_processed: int = 0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert checkpoint to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Checkpoint':
        """Create checkpoint from dictionary."""
        return cls(**data)
    
    def save(self, filepath: Path) -> None:
        """Save checkpoint to file."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, filepath: Path) -> Optional['Checkpoint']:
        """Load checkpoint from file."""
        if not filepath.exists():
            return None
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            # Checkpoint file corrupted, return None
            return None


@dataclass
class SanitizationReport:
    """Comprehensive report of sanitization execution.
    
    Attributes:
        operation_id: Unique identifier for this sanitization operation
        phase: Current execution phase
        tables_processed: Number of tables successfully processed
        tables_failed: Number of tables that failed processing
        tables_skipped: Number of tables skipped (e.g., empty tables)
        rows_processed: Total number of rows processed across all tables
        rows_masked: Total number of values actually masked
        duration_ms: Total execution time in milliseconds
        started_at: Operation start timestamp
        completed_at: Operation completion timestamp
        errors: List of error messages encountered
        warnings: List of warning messages
        table_progress: Details per-table progress tracking
        dry_run: Whether this was a dry-run execution
        checkpoint_saved: Whether checkpoint was saved
        total_truncations: Total count of truncations (indicates smart generation bugs)
        truncation_details: Per-table/column truncation details with counts
    """
    operation_id: str
    phase: ExecutionPhase
    tables_processed: int = 0
    tables_failed: int = 0
    tables_skipped: int = 0
    rows_processed: int = 0
    rows_masked: int = 0
    duration_ms: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    table_progress: Dict[str, TableProgress] = field(default_factory=dict)
    dry_run: bool = False
    checkpoint_saved: bool = False
    mappings_stored: int = 0
    mapping_errors: List[str] = field(default_factory=list)
    total_truncations: int = 0
    truncation_details: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    
    @property
    def is_successful(self) -> bool:
        """Check if sanitization completed successfully."""
        return self.phase == ExecutionPhase.COMPLETED and self.tables_failed == 0
    
    @property
    def total_tables(self) -> int:
        """Get total number of tables attempted."""
        return self.tables_processed + self.tables_failed + self.tables_skipped
    
    def add_error(self, error: str) -> None:
        """Add an error message."""
        self.errors.append(error)
    
    def add_warning(self, warning: str) -> None:
        """Add a warning message."""
        self.warnings.append(warning)
    
    def add_truncation(self, table_name: str, column: str, count: int, details: List[Dict[str, Any]]) -> None:
        """Add truncation tracking for a table/column.
        
        Args:
            table_name: Full table name (schema.table)
            column: Column name where truncations occurred
            count: Number of truncations
            details: List of truncation detail dicts from masker
        """
        if table_name not in self.truncation_details:
            self.truncation_details[table_name] = []
        
        self.truncation_details[table_name].append({
            "column": column,
            "count": count,
            "details": details
        })
        self.total_truncations += count
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "operation_id": self.operation_id,
            "phase": self.phase.value,
            "tables_processed": self.tables_processed,
            "tables_failed": self.tables_failed,
            "tables_skipped": self.tables_skipped,
            "rows_processed": self.rows_processed,
            "rows_masked": self.rows_masked,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "errors": self.errors,
            "warnings": self.warnings,
            "dry_run": self.dry_run,
            "checkpoint_saved": self.checkpoint_saved,
            "total_truncations": self.total_truncations,
            "truncation_details": self.truncation_details,
            "table_progress": {
                name: {
                    "schema": prog.schema,
                    "table": prog.table,
                    "total_rows": prog.total_rows,
                    "rows_processed": prog.rows_processed,
                    "batches_completed": prog.batches_completed,
                    "progress_percentage": prog.progress_percentage,
                    "is_completed": prog.is_completed,
                    "error": prog.error
                }
                for name, prog in self.table_progress.items()
            }
        }


# Type alias for progress callback
ProgressCallback = Callable[[str, int, int, float], None]


class SanitizationOrchestrator:
    """
    Central orchestrator for coordinating database sanitization workflow.
    
    The orchestrator integrates all components to execute a complete sanitization
    workflow with proper ordering, error handling, progress tracking, and the
    ability to resume from checkpoints.
    
    Architecture:
        The orchestrator follows a phased approach:
        1. Validation: Validate configuration and prerequisites
        2. Planning: Build dependency graph and execution plan
        3. Execution: Process tables in dependency order
        4. Verification: Validate results and data integrity
    
    Key Responsibilities:
        - Coordinate all sanitization components
        - Handle foreign key dependency resolution
        - Manage batch processing workflow
        - Provide transaction safety with rollback
        - Track progress and report statistics
        - Enable checkpoint/resume for long operations
        - Support dry-run mode for validation
    
    Example:
        >>> orchestrator = SanitizationOrchestrator()
        >>> report = orchestrator.run(config, dry_run=False)
        >>> if report.is_successful:
        ...     print(f"Success: {report.rows_processed} rows processed")
        ... else:
        ...     print(f"Failed with {len(report.errors)} errors")
    """
    
    def __init__(
        self,
        connection_manager: Optional[DatabaseConnectionManager] = None,
        mapping_manager: Optional[MappingManager] = None,
        checkpoint_dir: Optional[Path] = None
    ):
        """
        Initialize the sanitization orchestrator.
        
        Args:
            connection_manager: Optional pre-configured connection manager.
                If not provided, will be created from config during run().
            mapping_manager: Optional pre-configured mapping manager.
                If not provided, will be created from config.mapping during run().
            checkpoint_dir: Directory for storing checkpoints.
                Defaults to './checkpoints' in current directory.
        
        Example:
            >>> # Default initialization
            >>> orchestrator = SanitizationOrchestrator()
            >>> 
            >>> # With custom connection manager
            >>> conn_mgr = DatabaseConnectionManager("connection_string")
            >>> orchestrator = SanitizationOrchestrator(connection_manager=conn_mgr)
            >>> 
            >>> # With mapping manager
            >>> mapping_mgr = MappingManager(conn_mgr, mapping_config)
            >>> orchestrator = SanitizationOrchestrator(
            ...     connection_manager=conn_mgr,
            ...     mapping_manager=mapping_mgr
            ... )
            >>> 
            >>> # With custom checkpoint directory
            >>> checkpoint_dir = Path("/var/sanitization/checkpoints")
            >>> orchestrator = SanitizationOrchestrator(checkpoint_dir=checkpoint_dir)
        """
        self.connection_manager = connection_manager
        self.mapping_manager = mapping_manager
        self.checkpoint_dir = checkpoint_dir or Path("./checkpoints")
        self.logger = get_logger(__name__)
        
        # Component instances (initialized during run)
        self.schema_extractor: Optional[SchemaExtractor] = None
        self.batch_extractor: Optional[BatchExtractor] = None
        self.batch_updater: Optional[BatchUpdater] = None
        self.transaction_manager: Optional[TransactionManager] = None
        self.dependency_resolver: Optional[DependencyResolver] = None
        self.config_validator: Optional[ConfigValidator] = None
        self.masker_factory: MaskerFactory = MaskerFactory()
        
        # Progress tracking
        self.progress_callback: Optional[ProgressCallback] = None
        self.table_callback: Optional[Callable[[str, str], None]] = None
        
        # Performance optimization settings (set during run from config)
        self.log_batch_frequency: int = 10  # Log every Nth batch
    
    def set_progress_callback(self, callback: ProgressCallback) -> None:
        """
        Set callback for batch-level progress updates.
        
        Args:
            callback: Function called after each batch with signature:
                (table_name, rows_processed, total_rows, percentage)
        
        Example:
            >>> def on_progress(table, rows_done, rows_total, pct):
            ...     print(f"{table}: {pct:.1f}% ({rows_done}/{rows_total})")
            >>> 
            >>> orchestrator = SanitizationOrchestrator()
            >>> orchestrator.set_progress_callback(on_progress)
        """
        self.progress_callback = callback
    
    def set_table_callback(self, callback: Callable[[str, str], None]) -> None:
        """
        Set callback for table-level events (start/complete).
        
        Args:
            callback: Function called when table processing starts/completes
                with signature: (event_type, table_name)
                where event_type is "start" or "complete"
        
        Example:
            >>> def on_table_event(event, table):
            ...     print(f"Table {table}: {event}")
            >>> 
            >>> orchestrator = SanitizationOrchestrator()
            >>> orchestrator.set_table_callback(on_table_event)
        """
        self.table_callback = callback
    
    def run(
        self,
        config: SanitizationConfig,
        dry_run: bool = False,
        resume_from_checkpoint: bool = False
    ) -> SanitizationReport:
        """
        Execute the complete sanitization workflow.
        
        This is the main entry point for sanitization. It coordinates all phases:
        validation, planning, execution, and verification.
        
        Args:
            config: Sanitization configuration containing database settings
                and PII column specifications
            dry_run: If True, validate and report without making changes.
                Useful for testing configuration before actual execution.
            resume_from_checkpoint: If True, attempt to resume from last
                checkpoint. Skips already-processed tables.
        
        Returns:
            SanitizationReport: Comprehensive report with statistics, errors,
                warnings, and per-table progress details
        
        Raises:
            ValidationError: If configuration validation fails critically
            DatabaseError: If database operations fail critically
            CircularDependencyError: If circular FK dependencies detected
        
        Example:
            >>> config = ConfigLoader().load_from_file("config/pii_config.json")
            >>> orchestrator = SanitizationOrchestrator()
            >>> 
            >>> #Dry-run first
            >>> dry_report = orchestrator.run(config, dry_run=True)
            >>> print(f"Validation: {'OK' if dry_report.is_successful else 'FAILED'}")
            >>> 
            >>> # Actual execution
            >>> report = orchestrator.run(config, dry_run=False)
            >>> print(f"Processed {report.rows_processed} rows")
        """
        # Generate operation ID and correlation ID
        operation_id = str(uuid.uuid4())
        correlation_id = new_correlation_id()
        
        # Initialize report
        report = SanitizationReport(
            operation_id=operation_id,
            phase=ExecutionPhase.VALIDATION,
            started_at=datetime.utcnow(),
            dry_run=dry_run
        )
        
        start_time = time.time()
        
        # Execute within correlation context
        with CorrelationContext(correlation_id):
            try:
                self.logger.info(
                    f"Starting sanitization workflow",
                    extra={
                        "operation_id": operation_id,
                        "dry_run": dry_run,
                        "resume_from_checkpoint": resume_from_checkpoint
                    }
                )
                
                # Phase 1: Validation
                self._phase_validation(config, report)
                
                # Phase 2: Planning
                processing_order = self._phase_planning(config, report)
                
                # Load checkpoint if resuming
                checkpoint = None
                if resume_from_checkpoint:
                    checkpoint = self._load_checkpoint(operation_id)
                    if checkpoint:
                        self.logger.info(
                            f"Loaded checkpoint, {len(checkpoint.tables_completed)} tables already processed",
                            extra={"checkpoint": checkpoint.to_dict()}
                        )
                
                # Phase 3: Execution
                self._phase_execution(config, report, processing_order, dry_run, checkpoint)
                
                # Phase 4: Verification (skip in dry-run)
                if not dry_run:
                    self._phase_verification(config, report)
                
                # Mark as completed
                report.phase = ExecutionPhase.COMPLETED
                report.completed_at = datetime.utcnow()
                
                # Clear checkpoint on success
                if checkpoint and not dry_run:
                    self._clear_checkpoint(operation_id)
                
                self.logger.info(
                    f"Sanitization completed successfully",
                    extra={
                        "operation_id": operation_id,
                        "tables_processed": report.tables_processed,
                        "rows_processed": report.rows_processed,
                        "duration_ms": report.duration_ms
                    }
                )
                
            except Exception as e:
                # Mark as failed
                report.phase = ExecutionPhase.FAILED
                report.completed_at = datetime.utcnow()
                report.add_error(f"Orchestration failed: {str(e)}")
                
                self.logger.error(
                    f"Sanitization failed: {str(e)}",
                    extra={"operation_id": operation_id},
                    exc_info=True
                )
                
                # Save checkpoint on failure (if not dry-run)
                if not dry_run and report.tables_processed > 0:
                    try:
                        self._save_checkpoint(operation_id, config, report)
                        report.checkpoint_saved = True
                    except Exception as checkpoint_error:
                        self.logger.warning(
                            f"Failed to save checkpoint: {str(checkpoint_error)}",
                            extra={"operation_id": operation_id}
                        )
                
                # Re-raise if critical error
                if isinstance(e, (ValidationError, CircularDependencyError)):
                    raise
            
            finally:
                # Calculate final duration
                end_time = time.time()
                report.duration_ms = int((end_time - start_time) * 1000)
        
        return report
    
    def _initialize_components(self, config: SanitizationConfig) -> None:
        """Initialize all required components from configuration."""
        # Load performance optimization settings from config
        self.log_batch_frequency = config.database.log_batch_frequency
        
        # Auto-scale connection pool based on parallel processing settings
        pool_size = config.database.pool_size
        if config.database.enable_parallel_processing:
            # Ensure pool size can support parallel workers + overhead
            min_pool_size = config.database.max_parallel_tables + 2
            if pool_size < min_pool_size:
                self.logger.warning(
                    f"Connection pool size ({pool_size}) is less than recommended for "
                    f"parallel processing (min: {min_pool_size}). Auto-scaling to {min_pool_size}.",
                    extra={
                        "configured_pool_size": pool_size,
                        "recommended_pool_size": min_pool_size,
                        "max_parallel_tables": config.database.max_parallel_tables
                    }
                )
                pool_size = min_pool_size
        
        # Create connection manager if not provided
        if self.connection_manager is None:
            self.connection_manager = DatabaseConnectionManager(
                server=config.database.server,
                database=config.database.database,
                auth_type=config.database.auth_type,
                username=config.database.username,
                password=config.database.password,
                timeout=config.database.timeout,
                max_retries=config.database.max_retries,
                retry_delay=config.database.retry_delay,
                pool_size=pool_size  # Use auto-scaled pool size
            )
        
        # Initialize dependent components
        self.schema_extractor = SchemaExtractor(self.connection_manager)
        self.batch_extractor = BatchExtractor(
            self.connection_manager,
            self.schema_extractor,
            batch_size=config.database.batch_size
        )
        self.batch_updater = BatchUpdater(
            self.connection_manager,
            self.schema_extractor,
            batch_size=config.database.batch_size,
            bulk_update_strategy=config.database.bulk_update_strategy,
            enable_fast_executemany=config.database.enable_fast_executemany
        )
        self.transaction_manager = TransactionManager(self.connection_manager)
        self.config_validator = ConfigValidator(self.schema_extractor)
        
        # Initialize mapping manager if enabled
        if config.mapping and config.mapping.enabled:
            if self.mapping_manager is None:
                self.mapping_manager = MappingManager(
                    self.connection_manager,
                    config.mapping
                )
                self.logger.info("Mapping manager created from configuration")
            
            # Initialize mapping table
            try:
                self.mapping_manager.initialize()
                self.logger.info(
                    "Mapping table initialized",
                    extra={
                        "schema": config.mapping.schema_name,
                        "table": config.mapping.table_name,
                        "encryption_enabled": config.mapping.encryption_enabled
                    }
                )
            except MappingError as e:
                self.logger.warning(
                    f"Failed to initialize mapping table: {e.message}",
                    extra={"error_code": e.error_code}
                )
        else:
            self.mapping_manager = None
            self.logger.info("Mapping storage disabled (config.mapping not enabled)")
        
        self.logger.info("All components initialized successfully")
    
    def _phase_validation(self, config: SanitizationConfig, report: SanitizationReport) -> None:
        """
        Phase 1: Validate configuration and prerequisites.
        
        Validates:
        - Configuration structure and values
        - Database connectivity
        - Schema existence
        - Column existence and data types
        - Nullable constraints
        """
        self.logger.info("Phase 1: Validation started")
        report.phase = ExecutionPhase.VALIDATION
        
        # Initialize components
        self._initialize_components(config)
        
        # Health check
        if not self.connection_manager.health_check():
            raise DatabaseError(
                message="Database health check failed",
                error_code="DB_HEALTH_CHECK_FAILED",
                suggested_action="Verify database connection settings and network connectivity"
            )
        
        # Validate configuration
        if config.validate_before:
            validation_result = self.config_validator.validate_config(config)
            
            # Add warnings to report
            for warning in validation_result.warnings:
                report.add_warning(warning.message)
            
            # Add errors to report
            for error in validation_result.errors:
                report.add_error(error.message)
            
            # Fail if validation has errors
            if not validation_result.is_valid:
                raise ValidationError(
                    message=f"Configuration validation failed with {validation_result.error_count} errors",
                    error_code="CONFIG_VALIDATION_FAILED",
                    suggested_action="Fix configuration errors and retry"
                )
            
            self.logger.info(
                f"Configuration validated: {validation_result.warning_count} warnings",
                extra={
                    "error_count": validation_result.error_count,
                    "warning_count": validation_result.warning_count
                }
            )
        
        self.logger.info("Phase 1: Validation completed")
    
    def _phase_planning(self, config: SanitizationConfig, report: SanitizationReport) -> List[str]:
        """
        Phase 2: Build dependency graph and execution plan.
        
        Returns:
            List of fully qualified table names in processing order
        """
        self.logger.info("Phase 2: Planning started")
        report.phase = ExecutionPhase.PLANNING
        
        # Extract foreign key metadata
        foreign_keys = self.schema_extractor._get_foreign_keys()
        
        self.logger.info(f"Extracted {len(foreign_keys)} foreign key relationships")
        
        # Build dependency resolver
        self.dependency_resolver = DependencyResolver(foreign_keys)
        
        # Check for circular dependencies
        if self.dependency_resolver.has_circular_dependencies():
            cycles = self.dependency_resolver.get_cycles()
            cycle_str = " → ".join(cycles[0]) if cycles else "unknown"
            raise CircularDependencyError(
                message=f"Circular foreign key dependencies detected: {cycle_str}",
                error_code="CIRCULAR_FK_DEPENDENCY",
                tables_in_cycle=cycles[0] if cycles else [],
                suggested_action="Disable FK constraints, sanitize, re-enable and validate constraints"
            )
        
        # Get processing order (topological sort)
        processing_order = self.dependency_resolver.get_processing_order()
        
        self.logger.info(
            f"Execution plan built: {len(processing_order)} tables to process",
            extra={
                "processing_order": processing_order,
                "self_referencing_tables": list(self.dependency_resolver.self_referencing_tables)
            }
        )
        
        self.logger.info("Phase 2: Planning completed")
        
        return processing_order
    
    def _phase_execution(
        self,
        config: SanitizationConfig,
        report: SanitizationReport,
        processing_order: List[str],
        dry_run: bool,
        checkpoint: Optional[Checkpoint]
    ) -> None:
        """
        Phase 3: Execute sanitization for all tables in dependency order.
        """
        self.logger.info(f"Phase 3: Execution started (dry_run={dry_run})")
        report.phase = ExecutionPhase.EXECUTION
        
        # Group PII columns by table
        pii_by_table = self._group_pii_columns_by_table(config.pii_columns)
        
        # Auto-tune performance settings based on dataset size
        total_rows = self._estimate_dataset_size(pii_by_table)
        auto_settings = self._apply_auto_tuning(total_rows, len(pii_by_table))
        
        # Apply auto-tuning (user config always takes precedence)
        if hasattr(config.database, 'bulk_update_strategy'):
            # User explicitly set this, don't override
            pass
        else:
            # Apply auto-tuning recommendation
            if "bulk_update_strategy" in auto_settings and self.batch_updater:
                self.batch_updater.bulk_update_strategy = auto_settings["bulk_update_strategy"]
            if "log_batch_frequency" in auto_settings:
                self.log_batch_frequency = auto_settings["log_batch_frequency"]
        
        # Filter to only tables that have PII configured
        tables_to_process = [
            table for table in processing_order
            if table in pii_by_table
        ]
        
        # Apply checkpoint filter if resuming
        if checkpoint:
            tables_to_process = [
                table for table in tables_to_process
                if table not in checkpoint.tables_completed
            ]
            self.logger.info(
                f"Resuming: {len(tables_to_process)} tables remaining after checkpoint",
                extra={"checkpoint_tables_completed": len(checkpoint.tables_completed)}
            )
        
        self.logger.info(f"Processing {len(tables_to_process)} tables with PII columns")
        
        # Determine if parallel processing is enabled
        enable_parallel = config.database.enable_parallel_processing
        
        if enable_parallel and len(tables_to_process) > 1:
            # Use parallel processing with level-based groups
            self.logger.info(
                "Using parallel table processing",
                extra={"max_parallel_tables": config.database.max_parallel_tables}
            )
            self._execute_parallel(
                processing_order=tables_to_process,
                pii_by_table=pii_by_table,
                config=config,
                report=report,
                dry_run=dry_run
            )
        else:
            # Use sequential processing (original behavior)
            if not enable_parallel:
                self.logger.info("Parallel processing disabled by configuration")
            else:
                self.logger.info("Only 1 table to process, using sequential mode")
            
            self._execute_sequential(
                tables_to_process=tables_to_process,
                pii_by_table=pii_by_table,
                config=config,
                report=report,
                dry_run=dry_run
            )
        
        self.logger.info(
            f"Phase 3: Execution completed",
            extra={
                "tables_processed": report.tables_processed,
                "tables_failed": report.tables_failed,
                "tables_skipped": report.tables_skipped,
                "rows_processed": report.rows_processed
            }
        )
    
    def _execute_sequential(
        self,
        tables_to_process: List[str],
        pii_by_table: Dict[str, List[PIIColumnConfig]],
        config: SanitizationConfig,
        report: SanitizationReport,
        dry_run: bool
    ) -> None:
        """Execute table processing sequentially (original behavior)."""
        for table_name in tables_to_process:
            try:
                self._process_table(
                    table_name=table_name,
                    pii_columns=pii_by_table[table_name],
                    config=config,
                    report=report,
                    dry_run=dry_run
                )
            except Exception as e:
                # Log error but continue to next table
                error_msg = f"Table {table_name} failed: {str(e)}"
                report.add_error(error_msg)
                report.tables_failed += 1
                
                self.logger.error(
                    error_msg,
                    extra={"table": table_name},
                    exc_info=True
                )
    
    def _execute_parallel(
        self,
        processing_order: List[str],
        pii_by_table: Dict[str, List[PIIColumnConfig]],
        config: SanitizationConfig,
        report: SanitizationReport,
        dry_run: bool
    ) -> None:
        """
        Execute table processing in parallel using level-based dependency groups.
        
        Tables within the same dependency level can be processed concurrently.
        Levels are processed sequentially to respect FK constraints.
        """
        # Get level-based processing order from dependency resolver
        processing_levels = self.dependency_resolver.get_processing_levels()
        
        # Filter to only tables that need processing
        filtered_levels = []
        for level in processing_levels:
            filtered_level = [table for table in level if table in processing_order]
            if filtered_level:
                filtered_levels.append(filtered_level)
        
        # Determine worker count
        max_workers = min(
            config.database.max_parallel_tables,
            self.connection_manager.config.pool_size,  # Don't exceed connection pool
            os.cpu_count() or 4  # Fallback to 4 if cpu_count is None
        )
        
        self.logger.info(
            f"Parallel processing with {len(filtered_levels)} dependency levels",
            extra={
                "level_count": len(filtered_levels),
                "max_workers": max_workers,
                "total_tables": sum(len(level) for level in filtered_levels)
            }
        )
        
        # Thread-safe report lock
        report_lock = threading.Lock()
        
        # Process each level sequentially, but tables within level in parallel
        for level_num, level_tables in enumerate(filtered_levels):
            self.logger.info(
                f"Processing dependency level {level_num}: {len(level_tables)} tables",
                extra={
                    "level": level_num,
                    "table_count": len(level_tables),
                    "tables": level_tables
                }
            )
            
            # Use ThreadPoolExecutor for parallel table processing within this level
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"Level{level_num}") as executor:
                # Submit all tables in this level
                future_to_table = {
                    executor.submit(
                        self._process_table_safe,
                        table_name=table,
                        pii_columns=pii_by_table[table],
                        config=config,
                        report=report,
                        report_lock=report_lock,
                        dry_run=dry_run
                    ): table for table in level_tables
                }
                
                # Wait for all tables in this level to complete
                for future in as_completed(future_to_table):
                    table_name = future_to_table[future]
                    try:
                        future.result()  # Raises exception if table processing failed
                        self.logger.debug(
                            f"Table {table_name} completed successfully",
                            extra={"table": table_name, "level": level_num}
                        )
                    except Exception as e:
                        # Error already logged in _process_table_safe
                        self.logger.warning(
                            f"Table {table_name} failed in parallel execution",
                            extra={"table": table_name, "level": level_num, "error": str(e)}
                        )
            
            self.logger.info(
                f"Dependency level {level_num} completed",
                extra={"level": level_num}
            )
    
    def _process_table_safe(
        self,
        table_name: str,
        pii_columns: List[PIIColumnConfig],
        config: SanitizationConfig,
        report: SanitizationReport,
        report_lock: threading.Lock,
        dry_run: bool
    ) -> None:
        """
        Thread-safe wrapper for _process_table.
        
        Handles thread-safe report updates and error logging.
        """
        try:
            self._process_table(
                table_name=table_name,
                pii_columns=pii_columns,
                config=config,
                report=report,
                dry_run=dry_run
            )
        except Exception as e:
            # Thread-safe error reporting
            with report_lock:
                error_msg = f"Table {table_name} failed: {str(e)}"
                report.add_error(error_msg)
                report.tables_failed += 1
            
            self.logger.error(
                f"Table {table_name} processing failed",
                extra={"table": table_name},
                exc_info=True
            )
            # Re-raise to signal failure to executor
            raise
    
    def _phase_verification(self, config: SanitizationConfig, report: SanitizationReport) -> None:
        """
        Phase 4: Verify sanitization results and data integrity.
        """
        self.logger.info("Phase 4: Verification started")
        report.phase = ExecutionPhase.VERIFICATION
        
        # TODO: Implement verification logic
        # - Row count validation (before == after)
        # - Referential integrity check
        # - Data type consistency check
        
        self.logger.info("Phase 4: Verification completed (not yet implemented)")
    
    def _group_pii_columns_by_table(
        self,
        pii_columns: List[PIIColumnConfig]
    ) -> Dict[str, List[PIIColumnConfig]]:
        """Group PII columns by fully qualified table name."""
        grouped: Dict[str, List[PIIColumnConfig]] = {}
        
        for pii_col in pii_columns:
            table_name = pii_col.table_qualified_name
            if table_name not in grouped:
                grouped[table_name] = []
            grouped[table_name].append(pii_col)
        
        return grouped
    
    def _process_table(
        self,
        table_name: str,
        pii_columns: List[PIIColumnConfig],
        config: SanitizationConfig,
        report: SanitizationReport,
        dry_run: bool
    ) -> None:
        """
        Process a single table: extract, mask, and update in batches.
        
        Args:
            table_name: Fully qualified table name [schema].[table]
            pii_columns: List of PII column configurations for this table
            config: Full sanitization configuration
            report: Report to update with progress
            dry_run: If True, skip database updates
        
        Processing Flow:
            1. Initialize table progress tracking
            2. Get primary key columns for this table
            3. Create maskers for each PII column
            4. Extract batches (memory-efficient generator)
            5. For each batch:
                a. Mask data using appropriate maskers
                b. Update database (if not dry-run)
                c. Update progress tracking
                d. Call progress callbacks
            6. Mark table as complete or failed
        
        Transaction Behavior:
            - Outer transaction per table (optional, based on config)
            - Continue processing other tables if one fails
            - Rollback only the failed table, not entire operation
        """
        # Fire table start callback
        if self.table_callback:
            self.table_callback("start", table_name)
        
        # Initialize table progress
        schema, table = self._parse_table_name(table_name)
        progress = TableProgress(schema=schema, table=table, started_at=datetime.utcnow())
        report.table_progress[table_name] = progress
        
        self.logger.info(
            f"Processing table: {table_name}",
            extra={
                "table": table_name,
                "pii_columns": len(pii_columns),
                "dry_run": dry_run
            }
        )
        
        try:
            # Get primary key columns
            primary_keys = self.schema_extractor._get_primary_keys(schema, table)
            if not primary_keys:
                report.add_warning(f"Table {table_name} has no primary key, skipping")
                report.tables_skipped += 1
                progress.error = "No primary key"
                self.logger.warning(f"Table {table_name} has no primary key, skipping")
                return
            
            # Get total row count for progress tracking
            total_rows = self._get_table_row_count(schema, table)
            progress.total_rows = total_rows
            
            if total_rows == 0:
                report.add_warning(f"Table {table_name} is empty, skipping")
                report.tables_skipped += 1
                progress.completed_at = datetime.utcnow()
                self.logger.info(f"Table {table_name} is empty, skipping")
                return
            
            self.logger.info(
                f"Table {table_name}: {total_rows} rows to process",
                extra={"table": table_name, "total_rows": total_rows}
            )
            
            # Build maskers for each PII column
            maskers = self._build_maskers(pii_columns, schema, table)
            
            # Column info for maskers
            column_infos = self._build_column_infos(pii_columns, schema, table)
            
            # Process in batches
            rows_processed = 0
            batch_count = 0
            
            # Outer transaction (per table)
            # Use transaction only if not dry-run
            if not dry_run and config.database.use_transactions:
                with self.transaction_manager.begin() as tx:
                    rows_processed, batch_count = self._process_batches(
                        schema=schema,
                        table=table,
                        table_name=table_name,
                        pii_columns=pii_columns,
                        maskers=maskers,
                        column_infos=column_infos,
                        progress=progress,
                        report=report,
                        dry_run=dry_run
                    )
            else:
                rows_processed, batch_count = self._process_batches(
                    schema=schema,
                    table=table,
                    table_name=table_name,
                    pii_columns=pii_columns,
                    maskers=maskers,
                    column_infos=column_infos,
                    progress=progress,
                    report=report,
                    dry_run=dry_run
                )
            
            # Collect truncation metrics from all maskers
            for column_name, masker in maskers.items():
                if hasattr(masker, 'get_truncation_metrics'):
                    truncation_count, truncation_details = masker.get_truncation_metrics()
                    
                    if truncation_count > 0:
                        # Log warning - truncations indicate smart generation bugs
                        warning_msg = (
                            f"⚠️ TRUNCATION WARNING: {truncation_count} truncations detected in "
                            f"{table_name}.{column_name}. This indicates a bug in smart generation logic."
                        )
                        report.add_warning(warning_msg)
                        self.logger.error(
                            warning_msg,
                            extra={
                                "table": table_name,
                                "column": column_name,
                                "truncation_count": truncation_count,
                                "truncation_details": truncation_details
                            }
                        )
                        
                        # Add to report truncation tracking
                        report.add_truncation(
                            table_name=table_name,
                            column=column_name,
                            count=truncation_count,
                            details=truncation_details
                        )
                    
                    # Reset metrics for next table (even if zero, for consistency)
                    masker.reset_truncation_metrics()
            
            # Mark table as completed
            progress.completed_at = datetime.utcnow()
            progress.rows_processed = rows_processed
            progress.batches_completed = batch_count
            report.tables_processed += 1
            report.rows_processed += rows_processed
            
            self.logger.info(
                f"Table {table_name} completed: {rows_processed} rows in {batch_count} batches",
                extra={
                    "table": table_name,
                    "rows_processed": rows_processed,
                    "batches": batch_count
                }
            )
            
            # Fire table complete callback
            if self.table_callback:
                self.table_callback("complete", table_name)
            
        except Exception as e:
            # Mark table as failed
            progress.error = str(e)
            progress.completed_at = datetime.utcnow()
            report.tables_failed += 1
            
            error_msg = f"Table {table_name} processing failed: {str(e)}"
            report.add_error(error_msg)
            
            self.logger.error(
                error_msg,
                extra={"table": table_name},
                exc_info=True
            )
            
            # Re-raise to allow caller to handle
            raise
    
    def _process_batches(
        self,
        schema: str,
        table: str,
        table_name: str,
        pii_columns: List[PIIColumnConfig],
        maskers: Dict[str, Any],
        column_infos: Dict[str, ColumnInfo],
        progress: TableProgress,
        report: SanitizationReport,
        dry_run: bool
    ) -> tuple[int, int]:
        """
        Process all batches for a table.
        
        Returns:
            Tuple of (rows_processed, batch_count)
        """
        rows_processed = 0
        batch_count = 0
        
        # Get all columns we need (PKs + PII columns)
        pii_column_names = [col.column for col in pii_columns]
        
        # Extract and process batches
        for batch in self.batch_extractor.extract_batches(
            schema=schema,
            table=table,
            columns=pii_column_names
        ):
            batch_count += 1
            
            # Mask data in batch and collect mapping entries
            masked_batch, mapping_entries = self._mask_batch(
                batch=batch,
                pii_columns=pii_columns,
                maskers=maskers,
                column_infos=column_infos,
                operation_id=report.operation_id,
                schema=schema,
                table=table
            )
            
            # Count masked values
            masked_count = sum(
                1 for row in masked_batch.rows
                for col in pii_column_names
                if col in row
            )
            report.rows_masked += masked_count
            
            # Update database (skip in dry-run)
            if not dry_run:
                # Update batch (with inner transaction for safety)
                for update_batch in self.batch_updater.update_batches(
                    schema=schema,
                    table=table,
                    batches=[masked_batch],
                    key_columns=batch.key_columns
                ):
                    # Update processed in batch updater
                    pass
                
                # Store mappings if enabled
                if self.mapping_manager and mapping_entries:
                    try:
                        self.mapping_manager.store_mappings(mapping_entries)
                        report.mappings_stored += len(mapping_entries)
                        # Only log every Nth batch to reduce overhead
                        if batch_count % self.log_batch_frequency == 0:
                            self.logger.info(
                                f"Stored {len(mapping_entries)} mapping entries (batch {batch_count})",
                                extra={
                                    "table": table_name,
                                    "batch": batch_count,
                                    "entries": len(mapping_entries)
                                }
                            )
                    except MappingError as e:
                        error_msg = f"Failed to store mappings for {table_name} batch {batch_count}: {e.message}"
                        report.mapping_errors.append(error_msg)
                        self.logger.warning(
                            error_msg,
                            extra={
                                "error_code": e.error_code,
                                "table": table_name,
                                "batch": batch_count
                            }
                        )
            
            # Update progress
            rows_processed += len(batch.rows)
            progress.rows_processed = rows_processed
            progress.batches_completed = batch_count
            
            # Fire progress callback
            if self.progress_callback:
                percentage = (rows_processed / progress.total_rows) * 100.0
                self.progress_callback(
                    table_name,
                    rows_processed,
                    progress.total_rows,
                    percentage
                )
        
        return rows_processed, batch_count
    
    def _mask_batch(
        self,
        batch: Any,  # Batch dataclass from batch_extractor
        pii_columns: List[PIIColumnConfig],
        maskers: Dict[str, Any],
        column_infos: Dict[str, ColumnInfo],
        operation_id: str,
        schema: str,
        table: str
    ) -> tuple[Any, List[MappingEntry]]:
        """
        Apply masking to all PII columns in a batch.
        
        Args:
            batch: Batch object containing rows and metadata
            pii_columns: PII column configurations
            maskers: Dictionary of maskers by column name
            column_infos: Dictionary of column infos by column name
            operation_id: Current operation UUID
            schema: Schema name
            table: Table name
        
        Returns:
            Tuple of (modified_batch, mapping_entries)
        """
        mapping_entries = []
        
        # Mask each PII column in each row
        for row in batch.rows:
            for pii_col in pii_columns:
                column_name = pii_col.column
                
                # Skip if column not in row
                if column_name not in row:
                    continue
                
                original_value = row[column_name]
                
                # Handle NULL values
                if original_value is None:
                    # Create mapping entry for NULL if mapping enabled
                    if self.mapping_manager:
                        mapping_entry = MappingEntry(
                            operation_id=uuid.UUID(operation_id),
                            schema_name=schema,
                            table_name=table,
                            column_name=column_name,
                            original_value_hash=hashlib.sha256(b"NULL").digest(),
                            original_value_encrypted=None,
                            masked_value=None,
                            data_type=column_infos.get(column_name).data_type if column_infos.get(column_name) else "UNKNOWN",
                            is_null=True,
                            created_at=datetime.utcnow()
                        )
                        mapping_entries.append(mapping_entry)
                    continue
                
                # Get masker for this column
                masker = maskers.get(column_name)
                column_info = column_infos.get(column_name)
                
                if masker and column_info:
                    # Apply masking
                    masked_value = masker.mask_value(original_value, column_info)
                    row[column_name] = masked_value
                    
                    # Create mapping entry if mapping enabled
                    if self.mapping_manager:
                        # Convert original value to bytes for hashing
                        original_bytes = str(original_value).encode('utf-8')
                        
                        # Prepare encrypted value if encryption enabled
                        original_encrypted = None
                        if self.mapping_manager.config.encryption_enabled:
                            original_encrypted = original_bytes
                        
                        mapping_entry = MappingEntry(
                            operation_id=uuid.UUID(operation_id),
                            schema_name=schema,
                            table_name=table,
                            column_name=column_name,
                            original_value_hash=hashlib.sha256(original_bytes).digest(),
                            original_value_encrypted=original_encrypted,
                            masked_value=str(masked_value),
                            data_type=column_info.data_type,
                            is_null=False,
                            created_at=datetime.utcnow()
                        )
                        mapping_entries.append(mapping_entry)
        
        return batch, mapping_entries
    
    def _build_maskers(
        self,
        pii_columns: List[PIIColumnConfig],
        schema: str,
        table: str
    ) -> Dict[str, Any]:
        """
        Build maskers for each PII column.
        
        Returns:
            Dictionary mapping column name to masker instance
        """
        maskers = {}
        
        for pii_col in pii_columns:
            try:
                masker = self.masker_factory.get_masker(pii_col.masking_strategy)
                maskers[pii_col.column] = masker
            except Exception as e:
                self.logger.warning(
                    f"Failed to create masker for {pii_col.table_qualified_name}.{pii_col.column}: {str(e)}",
                    extra={
                        "schema": schema,
                        "table": table,
                        "column": pii_col.column,
                        "strategy": pii_col.masking_strategy.value
                    }
                )
        
        return maskers
    
    def _build_column_infos(
        self,
        pii_columns: List[PIIColumnConfig],
        schema: str,
        table: str
    ) -> Dict[str, ColumnInfo]:
        """
        Build ColumnInfo objects for each PII column.
        
        Returns:
            Dictionary mapping column name to ColumnInfo
        """
        column_infos = {}
        
        # Get column metadata from schema
        columns_metadata = self.schema_extractor._get_columns(schema, table)
        
        for pii_col in pii_columns:
            # Find matching column in metadata
            col_meta = next(
                (col for col in columns_metadata if col["column_name"] == pii_col.column),
                None
            )
            
            if col_meta:
                column_info = ColumnInfo(
                    name=pii_col.column,
                    data_type=col_meta["data_type"],
                    max_length=col_meta.get("max_length"),
                    is_nullable=col_meta["is_nullable"],
                    custom_format=pii_col.custom_format if pii_col.masking_strategy == MaskingStrategy.GENERIC else None
                )
                column_infos[pii_col.column] = column_info
        
        return column_infos
    
    def _get_table_row_count(self, schema: str, table: str) -> int:
        """Get total row count for a table (fast method using sys.partitions)."""
        # Use sys.partitions for fast estimation (avoids table scan)
        query = """
            SELECT SUM(p.rows) as row_count
            FROM sys.partitions p
            INNER JOIN sys.objects o ON p.object_id = o.object_id
            INNER JOIN sys.schemas s ON o.schema_id = s.schema_id
            WHERE s.name = ? AND o.name = ?
                AND p.index_id IN (0, 1)  -- Heap or clustered index
        """
        try:
            result = self.connection_manager.execute_query(query, params=(schema, table))
            count = result[0]["row_count"] if result and result[0]["row_count"] else 0
            return int(count)
        except:
            # Fallback to COUNT(*) if sys.partitions fails
            fallback_query = f"SELECT COUNT(*) as row_count FROM [{schema}].[{table}]"
            result = self.connection_manager.execute_query(fallback_query)
            return result[0]["row_count"] if result else 0
    
    def _estimate_dataset_size(
        self,
        pii_by_table: Dict[str, List[PIIColumnConfig]]
    ) -> int:
        """
        Estimate total rows across all tables to be sanitized.
        
        Args:
            pii_by_table: Dictionary mapping table names to PII columns
        
        Returns:
            Estimated total row count
        """
        total_rows = 0
        for table_name in pii_by_table.keys():
            schema, table = self._parse_table_name(table_name)
            try:
                table_rows = self._get_table_row_count(schema, table)
                total_rows += table_rows
            except Exception as e:
                self.logger.warning(
                    f"Failed to estimate row count for {table_name}: {e}",
                    extra={"table": table_name}
                )
        return total_rows
    
    def _apply_auto_tuning(
        self,
        total_rows: int,
        table_count: int
    ) -> Dict[str, Any]:
        """
        Auto-tune performance settings based on dataset size.
        
        Args:
            total_rows: Total rows across all tables
            table_count: Number of tables
        
        Returns:
            Dictionary of recommended settings
        """
        settings = {}
        
        # Tiny dataset: < 1000 rows
        if total_rows < 1000:
            settings["bulk_update_strategy"] = "parameter"  # MERGE overhead too high
            settings["log_batch_frequency"] = 1  # Log all batches
            self.logger.info(
                f"Auto-tuning: Tiny dataset ({total_rows} rows) - using parameter updates",
                extra={"total_rows": total_rows, "table_count": table_count}
            )
        
        # Medium dataset: 1K - 100K rows
        elif total_rows < 100000:
            settings["bulk_update_strategy"] = "auto"  # Try MERGE, fallback if needed
            settings["log_batch_frequency"] = 5
            self.logger.info(
                f"Auto-tuning: Medium dataset ({total_rows} rows) - using auto MERGE strategy",
                extra={"total_rows": total_rows, "table_count": table_count}
            )
        
        # Large dataset: 100K - 1M rows
        elif total_rows < 1000000:
            settings["bulk_update_strategy"] = "merge"  # Force MERGE
            settings["log_batch_frequency"] = 10
            self.logger.info(
                f"Auto-tuning: Large dataset ({total_rows} rows) - using MERGE strategy",
                extra={"total_rows": total_rows, "table_count": table_count}
            )
        
        # Very large dataset: > 1M rows
        else:
            settings["bulk_update_strategy"] = "merge"  # Force MERGE
            settings["log_batch_frequency"] = 20  # Reduce logging overhead
            self.logger.info(
                f"Auto-tuning: Very large dataset ({total_rows} rows) - using aggressive MERGE strategy",
                extra={"total_rows": total_rows, "table_count": table_count}
            )
        
        return settings
    
    def _parse_table_name(self, table_name: str) -> tuple[str, str]:
        """
        Parse fully qualified table name into schema and table.
        
        Args:
            table_name: Fully qualified name like '[schema].[table]'
        
        Returns:
            Tuple of (schema, table)
        """
        # Remove brackets and split
        parts = table_name.replace("[", "").replace("]", "").split(".")
        if len(parts) == 2:
            return parts[0], parts[1]
        elif len(parts) == 1:
            return "dbo", parts[0]
        else:
            raise ValueError(f"Invalid table name format: {table_name}")
    
    def _save_checkpoint(
        self,
        operation_id: str,
        config: SanitizationConfig,
        report: SanitizationReport
    ) -> None:
        """Save checkpoint for resuming on failure."""
        tables_completed = [
            name for name, progress in report.table_progress.items()
            if progress.is_completed
        ]
        
        checkpoint = Checkpoint(
            operation_id=operation_id,
            config_hash=str(hash(str(config))),  # Simple hash for now
            tables_completed=tables_completed
        )
        
        checkpoint_file = self.checkpoint_dir / f"{operation_id}.json"
        checkpoint.save(checkpoint_file)
        
        self.logger.info(
            f"Checkpoint saved: {len(tables_completed)} tables completed",
            extra={"checkpoint_file": str(checkpoint_file)}
        )
    
    def _load_checkpoint(self, operation_id: str) -> Optional[Checkpoint]:
        """Load checkpoint for resuming."""
        checkpoint_file = self.checkpoint_dir / f"{operation_id}.json"
        return Checkpoint.load(checkpoint_file)
    
    def _clear_checkpoint(self, operation_id: str) -> None:
        """Clear checkpoint file on successful completion."""
        checkpoint_file = self.checkpoint_dir / f"{operation_id}.json"
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            self.logger.info(f"Checkpoint cleared", extra={"checkpoint_file": str(checkpoint_file)})
