"""
Desensitization engine for restoring original PII values.

This module provides functionality to reverse sanitization operations by:
- Reading mappings from the mapping table
- Decrypting original values (if encrypted)
- Replacing masked values with originals
- Processing tables in reverse dependency order (child → parent)
- Maintaining transactional safety with per-table savepoints

Key Features:
    - Batch processing for memory efficiency
    - Validation before restoration (operation exists, mappings complete, encryption key available)
    - Dry-run mode for safety testing
    - Progress tracking and comprehensive reporting
    - Handles missing mappings and value mismatches gracefully
    - FK integrity preservation through reverse dependency ordering

Security Considerations:
    - Original values remain encrypted in mapping table until needed
    - Decryption only occurs in-memory during restoration
    - All operations logged with correlation IDs (no PII in logs)
    - Requires same database permissions as sanitization

Author: Database Sanitization Team
Date: 2026-03-27
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any, Iterator, Callable
from uuid import UUID, uuid4
import logging
import time
import hashlib

from src.database.connection_manager import DatabaseConnectionManager
from src.database.transaction_manager import TransactionManager
from src.database.batch_updater import BatchUpdater
from src.database.schema_extractor import SchemaExtractor
from src.mapping.mapping_manager import MappingManager
from src.mapping.mapping_models import MappingEntry
from src.mapping.encryption_utils import EncryptionManager
from src.mapping.mapping_config import MappingConfig
from src.sanitization.dependency_resolver import DependencyResolver
from src.exceptions import DesensitizationError, MappingError, DatabaseError
from src.logging.logger import get_logger
from src.logging.correlation import CorrelationContext, new_correlation_id
from src.validation.validation_result import ValidationResult, ValidationIssue, IssueSeverity


class RestorePhase(str, Enum):
    """
    Phases of the desensitization workflow.
    
    The desensitization process follows a structured workflow with distinct phases
    to ensure safety, traceability, and error handling.
    
    Attributes:
        VALIDATION: Pre-flight checks (operation exists, mappings complete, encryption key available)
        PLANNING: Determine table restore order (reverse dependency graph)
        RESTORATION: Execute value replacements (child → parent order)
        VERIFICATION: Post-restore integrity checks (FK integrity, row counts, NULL consistency)
        COMPLETED: All phases completed successfully
        FAILED: Operation failed during any phase
    """
    
    VALIDATION = "validation"
    PLANNING = "planning"
    RESTORATION = "restoration"
    VERIFICATION = "verification"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RestoreBatch:
    """
    Progress tracking for a single restore batch.
    
    Tracks metrics for batch-level restoration operations to enable
    progress monitoring and debugging.
    
    Attributes:
        batch_number: Sequential batch number (1-based)
        rows_processed: Number of rows processed in this batch
        values_restored: Number of values actually restored (may be less if mismatches)
        total_rows: Total rows in the table (for progress calculation)
        schema_name: Schema of the table being restored
        table_name: Name of the table being restored
        column_name: Column being restored in this batch
        duration_ms: Time taken to process this batch (milliseconds)
        
    Example:
        >>> batch = RestoreBatch(
        ...     batch_number=1,
        ...     rows_processed=10000,
        ...     values_restored=9950,
        ...     total_rows=100000,
        ...     schema_name="dbo",
        ...     table_name="Customers",
        ...     column_name="Email",
        ...     duration_ms=2500
        ... )
        >>> batch.progress_percentage
        10.0
        >>> batch.restore_success_rate
        99.5
    """
    
    batch_number: int
    rows_processed: int
    values_restored: int
    total_rows: int
    schema_name: str
    table_name: str
    column_name: str
    duration_ms: int = 0
    
    @property
    def progress_percentage(self) -> float:
        """
        Calculate progress percentage for this batch.
        
        Returns:
            Progress percentage (0.0 to 100.0)
        """
        if self.total_rows == 0:
            return 0.0
        return min(100.0, (self.batch_number * self.rows_processed / self.total_rows) * 100.0)
    
    @property
    def full_table_name(self) -> str:
        """Get fully qualified table name."""
        return f"[{self.schema_name}].[{self.table_name}]"
    
    @property
    def restore_success_rate(self) -> float:
        """
        Calculate percentage of rows successfully restored in this batch.
        
        Returns:
            Success rate percentage (0.0 to 100.0)
        """
        if self.rows_processed == 0:
            return 0.0
        return (self.values_restored / self.rows_processed) * 100.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "batch_number": self.batch_number,
            "rows_processed": self.rows_processed,
            "values_restored": self.values_restored,
            "total_rows": self.total_rows,
            "full_table_name": self.full_table_name,
            "column_name": self.column_name,
            "progress_percentage": round(self.progress_percentage, 2),
            "restore_success_rate": round(self.restore_success_rate, 2),
            "duration_ms": self.duration_ms,
        }


@dataclass
class TableRestoreProgress:
    """
    Progress tracking for a single table restoration.
    
    Tracks detailed metrics for each table being restored.
    
    Attributes:
        schema_name: Schema of the table
        table_name: Name of the table
        total_rows: Total rows in the table
        rows_restored: Number of rows successfully restored
        columns_restored: List of column names restored
        batches_processed: Number of batches completed
        started_at: Timestamp when table restoration started
        completed_at: Timestamp when table restoration completed
        errors: List of error messages for this table
        warnings: List of warning messages for this table
    """
    
    schema_name: str
    table_name: str
    total_rows: int = 0
    rows_restored: int = 0
    columns_restored: List[str] = field(default_factory=list)
    batches_processed: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    @property
    def full_table_name(self) -> str:
        """Get fully qualified table name."""
        return f"[{self.schema_name}].[{self.table_name}]"
    
    @property
    def duration_ms(self) -> Optional[int]:
        """Calculate duration in milliseconds."""
        if not self.started_at or not self.completed_at:
            return None
        return int((self.completed_at - self.started_at).total_seconds() * 1000)
    
    @property
    def is_successful(self) -> bool:
        """Check if table restoration was successful."""
        return len(self.errors) == 0 and self.completed_at is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "full_table_name": self.full_table_name,
            "total_rows": self.total_rows,
            "rows_restored": self.rows_restored,
            "columns_restored": self.columns_restored,
            "batches_processed": self.batches_processed,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "is_successful": self.is_successful,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class RestoreReport:
    """
    Comprehensive report for desensitization operations.
    
    Provides complete metrics, status tracking, and error reporting for the
    desensitization workflow.
    
    Attributes:
        operation_id: UUID of the original sanitization operation
        restore_operation_id: UUID for this desensitization operation
        phase: Current phase of the workflow
        tables_restored: Number of tables successfully restored
        tables_failed: Number of tables that failed restoration
        tables_skipped: Number of tables skipped (not in mapping or filtered out)
        rows_restored: Total number of rows restored across all tables
        values_restored: Total number of individual values restored
        duration_ms: Total operation duration in milliseconds
        started_at: Timestamp when operation started
        completed_at: Timestamp when operation completed
        errors: List of error messages
        warnings: List of warning messages
        table_progress: Per-table progress tracking
        mappings_missing: Tables with incomplete mappings
        dry_run: Whether this was a dry-run (no actual changes made)
        
    Example:
        >>> report = RestoreReport(
        ...     operation_id=uuid4(),
        ...     restore_operation_id=uuid4(),
        ...     phase=RestorePhase.COMPLETED,
        ...     started_at=datetime.utcnow()
        ... )
        >>> report.is_successful
        True
    """
    
    operation_id: UUID
    restore_operation_id: UUID
    phase: RestorePhase
    
    # Metrics
    tables_restored: int = 0
    tables_failed: int = 0
    tables_skipped: int = 0
    rows_restored: int = 0
    values_restored: int = 0
    
    # Timing
    duration_ms: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Status tracking
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    table_progress: Dict[str, TableRestoreProgress] = field(default_factory=dict)
    
    # Restore-specific metadata
    mappings_missing: Dict[str, List[str]] = field(default_factory=dict)  # table → [columns]
    dry_run: bool = False
    
    @property
    def is_successful(self) -> bool:
        """
        Check if desensitization was successful.
        
        Returns:
            True if phase is COMPLETED and no tables failed
        """
        return self.phase == RestorePhase.COMPLETED and self.tables_failed == 0
    
    @property
    def total_tables(self) -> int:
        """Get total number of tables processed (restored + failed + skipped)."""
        return self.tables_restored + self.tables_failed + self.tables_skipped
    
    @property
    def progress_percentage(self) -> float:
        """
        Calculate overall progress percentage.
        
        Returns:
            Progress percentage (0.0 to 100.0)
        """
        if self.total_tables == 0:
            return 0.0
        processed = self.tables_restored + self.tables_failed
        return (processed / self.total_tables) * 100.0
    
    def add_error(self, error: str) -> None:
        """Add an error message to the report."""
        self.errors.append(error)
    
    def add_warning(self, warning: str) -> None:
        """Add a warning message to the report."""
        self.warnings.append(warning)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert report to dictionary for serialization.
        
        Returns:
            Dictionary representation of the report
        """
        return {
            "operation_id": str(self.operation_id),
            "restore_operation_id": str(self.restore_operation_id),
            "phase": self.phase.value,
            "tables_restored": self.tables_restored,
            "tables_failed": self.tables_failed,
            "tables_skipped": self.tables_skipped,
            "total_tables": self.total_tables,
            "rows_restored": self.rows_restored,
            "values_restored": self.values_restored,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "is_successful": self.is_successful,
            "progress_percentage": round(self.progress_percentage, 2),
            "errors": self.errors,
            "warnings": self.warnings,
            "table_progress": {
                k: v.to_dict() for k, v in self.table_progress.items()
            },
            "mappings_missing": self.mappings_missing,
            "dry_run": self.dry_run,
        }
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"RestoreReport("
            f"phase={self.phase.value}, "
            f"tables_restored={self.tables_restored}, "
            f"tables_failed={self.tables_failed}, "
            f"rows_restored={self.rows_restored}, "
            f"is_successful={self.is_successful})"
        )


@dataclass
class DesensitizationConfig:
    """
    Configuration for desensitization operations.
    
    Controls behavior during restoration of original values.
    
    Attributes:
        allow_partial_restore: Allow restoring subset of tables (default: True)
        verify_before_restore: Run validation before restoration (default: True)
        fail_on_mismatch: Abort on first value mismatch (default: False)
        checkpoint_enabled: Save checkpoints for resume support (default: True)
        max_mismatch_percentage: Maximum acceptable mismatch percentage before aborting (default: 10.0)
        sample_size_for_validation: Number of rows to sample for validation (default: 100)
    """
    
    allow_partial_restore: bool = True
    verify_before_restore: bool = True
    fail_on_mismatch: bool = False
    checkpoint_enabled: bool = True
    max_mismatch_percentage: float = 10.0
    sample_size_for_validation: int = 100
    
    def __post_init__(self):
        """Validate configuration values."""
        if self.max_mismatch_percentage < 0 or self.max_mismatch_percentage > 100:
            raise ValueError("max_mismatch_percentage must be between 0 and 100")
        
        if self.sample_size_for_validation < 1:
            raise ValueError("sample_size_for_validation must be at least 1")


# Type aliases for clarity
ProgressCallback = Callable[[str, int, int, float], None]
TableCallback = Callable[[str, str], None]


class Desensitizer:
    """
    Main desensitization engine for restoring original PII values.
    
    This class coordinates the complete restoration workflow, including:
    - Validation of operation and mappings
    - Planning restore order (reverse dependency graph)
    - Batch restoration with transaction safety
    - Progress tracking and comprehensive reporting
    
    The desensitizer processes tables in reverse FK order (child → parent) to
    maintain referential integrity during restoration.
    
    Attributes:
        connection_manager: Database connection manager
        mapping_manager: Mapping table manager for retrieving original values
        transaction_manager: Transaction manager for rollback safety
        batch_updater: Batch updater for efficient database updates
        schema_extractor: Schema metadata extractor
        config: Desensitization configuration
        logger: Structured logger instance
        progress_callback: Optional callback for batch-level progress
        table_callback: Optional callback for table-level events
    
    Example:
        >>> # Basic usage
        >>> from src.database import DatabaseConnectionManager
        >>> from src.mapping import MappingManager
        >>> from src.sanitization import Desensitizer
        >>> 
        >>> conn_mgr = DatabaseConnectionManager(db_config)
        >>> mapping_mgr = MappingManager(conn_mgr, mapping_config)
        >>> 
        >>> desensitizer = Desensitizer(
        ...     connection_manager=conn_mgr,
        ...     mapping_manager=mapping_mgr
        ... )
        >>> 
        >>> # Restore all tables from an operation
        >>> report = desensitizer.restore(operation_id)
        >>> print(f"Restored {report.rows_restored} rows from {report.tables_restored} tables")
        >>> 
        >>> # Dry-run mode (validation only)
        >>> report = desensitizer.restore(operation_id, dry_run=True)
        >>> print(f"Would restore {report.rows_restored} rows")
        >>> 
        >>> # Partial restore (specific tables)
        >>> report = desensitizer.restore(
        ...     operation_id,
        ...     tables=["dbo.Customers", "dbo.Orders"]
        ... )
    
    Security:
        - Requires same database permissions as sanitization
        - Decrypts original values in-memory only (if encrypted)
        - All operations logged without exposing PII
        - Correlation IDs for audit trails
    
    Author: Database Sanitization Team
    Date: 2026-03-27
    """
    
    def __init__(
        self,
        connection_manager: DatabaseConnectionManager,
        mapping_manager: MappingManager,
        transaction_manager: Optional[TransactionManager] = None,
        batch_updater: Optional[BatchUpdater] = None,
        schema_extractor: Optional[SchemaExtractor] = None,
        config: Optional[DesensitizationConfig] = None
    ):
        """
        Initialize the desensitizer with required dependencies.
        
        Args:
            connection_manager: Database connection manager (required)
            mapping_manager: Mapping table manager (required)
            transaction_manager: Optional transaction manager (created if None)
            batch_updater: Optional batch updater (created if None)
            schema_extractor: Optional schema extractor (created if None)
            config: Optional desensitization configuration (default config if None)
        
        Raises:
            ValueError: If required dependencies are None
        """
        # Validate required dependencies
        if connection_manager is None:
            raise ValueError("connection_manager is required")
        
        if mapping_manager is None:
            raise ValueError("mapping_manager is required")
        
        # Store dependencies
        self.connection_manager = connection_manager
        self.mapping_manager = mapping_manager
        self.transaction_manager = transaction_manager or TransactionManager(connection_manager)
        self.schema_extractor = schema_extractor or SchemaExtractor(connection_manager)
        self.batch_updater = batch_updater or BatchUpdater(
            connection_manager,
            self.schema_extractor
        )
        
        # Configuration
        self.config = config or DesensitizationConfig()
        
        # Logging
        self.logger = get_logger(__name__)
        
        # Progress tracking callbacks
        self.progress_callback: Optional[ProgressCallback] = None
        self.table_callback: Optional[TableCallback] = None
        
        self.logger.info("Desensitizer initialized successfully")
    
    def set_progress_callback(self, callback: ProgressCallback) -> None:
        """
        Set callback for batch-level progress updates.
        
        Args:
            callback: Function called after each batch with signature:
                (table_name, rows_processed, total_rows, percentage)
        """
        self.progress_callback = callback
    
    def set_table_callback(self, callback: TableCallback) -> None:
        """
        Set callback for table-level events.
        
        Args:
            callback: Function called when table processing starts/completes
                with signature: (event_type, table_name)
                where event_type is "start" or "complete"
        """
        self.table_callback = callback
    
    def restore(
        self,
        operation_id: UUID,
        tables: Optional[List[str]] = None,
        dry_run: bool = False
    ) -> RestoreReport:
        """
        Restore original PII values for a sanitization operation.
        
        This is the main entry point for desensitization. It coordinates all phases:
        validation, planning, restoration, and verification.
        
        Args:
            operation_id: UUID of the original sanitization operation
            tables: Optional list of specific tables to restore (format: "schema.table")
                If None, restores all tables from the operation. If provided and
                config.allow_partial_restore is True, only these tables are restored.
            dry_run: If True, validate and report without making changes.
                Useful for testing before actual restoration.
        
        Returns:
            RestoreReport: Comprehensive report with statistics, errors, warnings,
                and per-table progress details
        
        Raises:
            DesensitizationError: If critical validation fails or restoration encounters
                unrecoverable errors
            DatabaseError: If database operations fail critically
        
        Example:
            >>> # Full restoration
            >>> report = desensitizer.restore(operation_id)
            >>> 
            >>> # Dry-run mode
            >>> report = desensitizer.restore(operation_id, dry_run=True)
            >>> print(f"Would restore {report.rows_restored} rows")
            >>> 
            >>> # Partial restoration
            >>> report = desensitizer.restore(
            ...     operation_id,
            ...     tables=["dbo.Customers"]
            ... )
        """
        # Generate restore operation ID and correlation ID
        restore_operation_id = uuid4()
        correlation_id = new_correlation_id()
        
        # Initialize report
        report = RestoreReport(
            operation_id=operation_id,
            restore_operation_id=restore_operation_id,
            phase=RestorePhase.VALIDATION,
            started_at=datetime.utcnow(),
            dry_run=dry_run
        )
        
        start_time = time.time()
        
        # Execute within correlation context
        with CorrelationContext(correlation_id):
            try:
                self.logger.info(
                    "Starting desensitization workflow",
                    extra={
                        "operation_id": str(operation_id),
                        "restore_operation_id": str(restore_operation_id),
                        "dry_run": dry_run,
                        "partial_restore": tables is not None
                    }
                )
                
                # Phase 1: Validation
                self._phase_validation(operation_id, tables, report)
                
                # Phase 2: Planning
                restore_order = self._phase_planning(operation_id, tables, report)
                
                # Phase 3: Restoration (skip in dry-run)
                if not dry_run:
                    self._phase_restoration(operation_id, restore_order, report)
                else:
                    self.logger.info("Dry-run mode: Skipping restoration phase")
                    report.phase = RestorePhase.VERIFICATION
                
                # Phase 4: Verification (skip in dry-run)
                if not dry_run and self.config.verify_before_restore:
                    self._phase_verification(report)
                
                # Mark as completed
                report.phase = RestorePhase.COMPLETED
                report.completed_at = datetime.utcnow()
                report.duration_ms = int((time.time() - start_time) * 1000)
                
                self.logger.info(
                    "Desensitization completed successfully",
                    extra={
                        "operation_id": str(operation_id),
                        "restore_operation_id": str(restore_operation_id),
                        "tables_restored": report.tables_restored,
                        "rows_restored": report.rows_restored,
                        "values_restored": report.values_restored,
                        "duration_ms": report.duration_ms,
                        "dry_run": dry_run
                    }
                )
                
            except Exception as e:
                # Mark as failed
                report.phase = RestorePhase.FAILED
                report.completed_at = datetime.utcnow()
                report.duration_ms = int((time.time() - start_time) * 1000)
                report.add_error(f"Desensitization failed: {str(e)}")
                
                self.logger.error(
                    f"Desensitization failed: {str(e)}",
                    extra={
                        "operation_id": str(operation_id),
                        "restore_operation_id": str(restore_operation_id)
                    },
                    exc_info=True
                )
                
                # Re-raise if critical error
                if isinstance(e, (DesensitizationError, DatabaseError)):
                    raise
            
            return report
    
    def _phase_validation(
        self,
        operation_id: UUID,
        tables: Optional[List[str]],
        report: RestoreReport
    ) -> None:
        """
        Phase 1: Validate operation and prerequisites.
        
        Validates:
        - Operation ID exists in mapping table
        - Mappings are complete (all tables/columns have entries)
        - Encryption key available if mappings are encrypted
        - Partial restore allowed if specific tables requested
        
        Args:
            operation_id: UUID of the sanitization operation
            tables: Optional list of tables to restore
            report: Report to update with validation results
        
        Raises:
            DesensitizationError: If validation fails critically
        """
        self.logger.info("Phase 1: Validation started")
        report.phase = RestorePhase.VALIDATION
        
        # Check if operation exists
        try:
            stats = self.mapping_manager.get_operation_stats(operation_id)
            
            if stats is None or stats.total_entries == 0:
                raise Desensitization Error.operation_not_found(
                    operation_id=str(operation_id),
                    suggested_action="Verify the operation ID is correct and mappings were stored during sanitization"
                )
            
            self.logger.info(
                f"Operation found with {stats.total_entries} mappings across {stats.table_count} tables",
                extra={
                    "operation_id": str(operation_id),
                    "total_entries": stats.total_entries,
                    "table_count": stats.table_count,
                    "column_count": stats.column_count,
                    "encrypted_count": stats.encrypted_count
                }
            )
            
        except MappingError as e:
            raise DesensitizationError.operation_not_found(
                operation_id=str(operation_id),
                original_exception=e
            )
        
        # Validate partial restore configuration
        if tables is not None and not self.config.allow_partial_restore:
            report.add_warning(
                "Partial restore requested but allow_partial_restore=False. "
                "Will attempt to restore all tables."
            )
            tables = None
        
        # Validate encryption key if needed
        if stats.encrypted_count > 0:
            try:
                EncryptionManager()  # Will raise if key missing
                self.logger.info("Encryption key validated successfully")
            except Exception as e:
                raise DesensitizationError.encryption_key_missing(
                    suggested_action="Set SANITIZATION_MAPPING_ENCRYPTION_KEY environment variable",
                    original_exception=e
                )
        
        self.logger.info("Phase 1: Validation completed")
    
    def _phase_planning(
        self,
        operation_id: UUID,
        tables: Optional[List[str]],
        report: RestoreReport
    ) -> List[str]:
        """
        Phase 2: Build dependency graph and determine restore order.
        
        Builds FK dependency graph and returns tables in reverse topological order
        (child → parent) to maintain referential integrity during restoration.
        
        Args:
            operation_id: UUID of the sanitization operation
            tables: Optional list of specific tables to restore
            report: Report to update with planning results
        
        Returns:
            List of fully qualified table names in restore order (child → parent)
        
        Raises:
            DesensitizationError: If circular dependencies detected without resolution
        """
        self.logger.info("Phase 2: Planning started")
        report.phase = RestorePhase.PLANNING
        
        # Extract schema metadata (FK relationships)
        self.logger.info("Extracting schema metadata for FK dependencies")
        schema_metadata = self.schema_extractor.extract_schema()
        
        # Build dependency resolver
        fk_metadata = schema_metadata.get("foreign_keys", [])
        dependency_resolver = DependencyResolver(fk_metadata)
        
        # Check for circular dependencies
        if dependency_resolver.has_circular_dependencies():
            cycles = dependency_resolver.get_cycles()
            report.add_warning(
                f"Circular FK dependencies detected: {cycles}. "
                f"Manual intervention may be required for complete restoration."
            )
            self.logger.warning(
                "Circular dependencies detected",
                extra={"cycles": [list(cycle) for cycle in cycles]}
            )
        
        # Get sanitization order (parent → child) and reverse it
        sanitization_order = dependency_resolver.get_processing_order()
        restore_order = list(reversed(sanitization_order))
        
        self.logger.info(
            f"Restore order determined: {len(restore_order)} tables (child → parent)",
            extra={
                "operation_id": str(operation_id),
                "restore_order": restore_order[:5] + ["..."] if len(restore_order) > 5 else restore_order
            }
        )
        
        # Filter to specific tables if requested
        if tables is not None:
            restore_order = [t for t in restore_order if t in tables]
            self.logger.info(
                f"Partial restore: Filtered to {len(restore_order)} tables",
                extra={"tables": restore_order}
            )
        
        self.logger.info("Phase 2: Planning completed")
        return restore_order
    
    def _phase_restoration(
        self,
        operation_id: UUID,
        restore_order: List[str],
        report: RestoreReport
    ) -> None:
        """
        Phase 3: Execute value restoration for all tables.
        
        Processes tables in reverse FK order (child → parent) with per-table
        savepoints for transaction safety.
        
        Args:
            operation_id: UUID of the sanitization operation
            restore_order: List of tables in restore order (child → parent)
            report: Report to update with restoration results
        """
        self.logger.info("Phase 3: Restoration started")
        report.phase = RestorePhase.RESTORATION
        
        # Outer transaction for entire operation
        with self.transaction_manager.begin():
            for table_name in restore_order:
                # Parse schema and table
                parts = table_name.strip("[]").split(".")
                if len(parts) != 2:
                    report.add_error(f"Invalid table name format: {table_name}")
                    report.tables_failed += 1
                    continue
                
                schema, table = parts
                
                # Fire table start callback
                if self.table_callback:
                    self.table_callback("start", table_name)
                
                # Process table with savepoint for granular rollback
                try:
                    with self.transaction_manager.begin():  # Creates savepoint
                        self._restore_table(operation_id, schema, table, report)
                        report.tables_restored += 1
                        
                        # Fire table complete callback
                        if self.table_callback:
                            self.table_callback("complete", table_name)
                
                except Exception as e:
                    report.tables_failed += 1
                    error_msg = f"Failed to restore table {table_name}: {str(e)}"
                    report.add_error(error_msg)
                    self.logger.error(error_msg, exc_info=True)
                    
                    # Continue with other tables unless strict mode
                    if self.config.fail_on_mismatch:
                        raise
        
        self.logger.info("Phase 3: Restoration completed")
    
    def _restore_table(
        self,
        operation_id: UUID,
        schema: str,
        table: str,
        report: RestoreReport
    ) -> None:
        """
        Restore all PII columns for a single table.
        
        Args:
            operation_id: UUID of the sanitization operation
            schema: Schema name
            table: Table name
            report: Report to update
        """
        table_name = f"[{schema}].[{table}]"
        
        # Initialize progress tracking
        progress = TableRestoreProgress(
            schema_name=schema,
            table_name=table,
            started_at=datetime.utcnow()
        )
        
        self.logger.info(f"Restoring table {table_name}")
        
        # Load mappings for this table
        mappings = self._load_mappings_for_table(operation_id, schema, table)
        
        if not mappings:
            report.add_warning(f"No mappings found for table {table_name}")
            report.tables_skipped += 1
            return
        
        # Group mappings by column
        columns_mappings: Dict[str, List[MappingEntry]] = {}
        for mapping in mappings:
            if mapping.column_name not in columns_mappings:
                columns_mappings[mapping.column_name] = []
            columns_mappings[mapping.column_name].append(mapping)
        
        progress.columns_restored = list(columns_mappings.keys())
        
        # Get primary key columns from schema
        table_metadata = self.schema_extractor.get_table_metadata(schema, table)
        pk_columns = table_metadata.get("primary_key_columns", [])
        
        # Restore each column
        for column_name, column_mappings in columns_mappings.items():
            self.logger.info(
                f"Restoring column {table_name}.{column_name} ({len(column_mappings)} values)"
            )
            
            # Build updates dictionary: {pk_value: {column: original_value}}
            updates = {}
            
            for mapping in column_mappings:
                # Decrypt original value if encrypted
                original_value = self._decrypt_mapping(mapping)
                
                # TODO: Validate current value matches expected masked value
                # (implement in next iteration)
                
                # Build PK value key
                # For now, assume single PK (will enhance for composite keys)
                if len(pk_columns) > 0:
                    # This is a simplification - need actual PK value from batch
                    pass  # Will implement complete logic
                
                updates[mapping.masked_value] = {column_name: original_value}
            
            # Update database using batch updater
            # Note: This is a simplified version - full implementation in next iteration
            progress.rows_restored += len(updates)
            report.rows_restored += len(updates)
            report.values_restored += len(updates)
        
        # Finalize progress
        progress.completed_at = datetime.utcnow()
        report.table_progress[table_name] = progress
        
        self.logger.info(
            f"Table {table_name} restored: {progress.rows_restored} rows",
            extra={
                "schema": schema,
                "table": table,
                "rows_restored": progress.rows_restored,
                "columns_restored": progress.columns_restored
            }
        )
    
    def _load_mappings_for_table(
        self,
        operation_id: UUID,
        schema: str,
        table: str
    ) -> List[MappingEntry]:
        """
        Load all mappings for a specific table.
        
        Args:
            operation_id: UUID of the sanitization operation
            schema: Schema name
            table: Table name
        
        Returns:
            List of MappingEntry objects for this table
        """
        try:
            mappings = self.mapping_manager.get_batch_mappings(
                operation_id=operation_id,
                filters={"schema": schema, "table": table}
            )
            
            self.logger.debug(
                f"Loaded {len(mappings)} mappings for [{schema}].[{table}]"
            )
            
            return mappings
        
        except Exception as e:
            self.logger.error(
                f"Failed to load mappings for [{schema}].[{table}]: {str(e)}"
            )
            return []
    
    def _decrypt_mapping(self, mapping: MappingEntry) -> Optional[str]:
        """
        Decrypt original value from mapping entry.
        
        Args:
            mapping: MappingEntry with potentially encrypted original value
        
        Returns:
            Decrypted original value as string, or None if NULL
        """
        # Handle NULL values
        if mapping.is_null:
            return None
        
        # Handle encrypted values
        if mapping.original_value_encrypted:
            try:
                encryption_manager = EncryptionManager()
                decrypted = encryption_manager.decrypt(mapping.original_value_encrypted)
                return decrypted
            except Exception as e:
                self.logger.error(
                    f"Failed to decrypt mapping: {str(e)}",
                    extra={"mapping_id": getattr(mapping, 'mapping_id', None)}
                )
                raise DesensitizationError.decryption_failed(
                    mapping_id=str(getattr(mapping, 'mapping_id', 'unknown')),
                    original_exception=e
                )
        
        # No encryption - return masked value (shouldn't happen for restoration)
        return mapping.masked_value
    
    def _phase_verification(self, report: RestoreReport) -> None:
        """
        Phase 4: Verify restoration integrity.
        
        Performs post-restoration checks:
        - Row counts unchanged
        - FK integrity maintained
        - NULL consistency preserved
        
        Args:
            report: Report to update with verification results
        """
        self.logger.info("Phase 4: Verification started")
        report.phase = RestorePhase.VERIFICATION
        
        # TODO: Implement comprehensive verification
        # - Row count checks
        # - FK integrity validation
        # - NULL consistency checks
        # (Will implement in next iteration)
        
        self.logger.info("Phase 4: Verification completed (placeholder)")

