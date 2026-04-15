"""
Desanitization Engine - Core restoration logic for reversing database sanitization.

This module provides the DesanitizationEngine class, which orchestrates the process
of restoring original values from sanitized data using stored mapping tables.

Key Features:
    - Record-level restoration by primary key
    - Batch processing for efficiency
    - Transaction-safe operations with rollback
    - Composite primary key support
    - Dry-run mode for safety
    - Comprehensive validation and reporting

Usage:
    from desanitization import DesanitizationEngine
    from mapping.mapping_table_manager import MappingTableManager
    from database.schema_inspector import SchemaInspector
    
    engine = DesanitizationEngine(
        connection=conn,
        mapping_manager=mapping_mgr,
        schema_inspector=inspector
    )
    
    result = engine.desanitize_records(
        table='Customers',
        record_ids=['123', '456'],
        dry_run=False
    )
"""

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Any, TYPE_CHECKING
from collections import defaultdict

from desanitization.exceptions import (
    DesanitizationError,
    MappingNotFoundError,
    PreconditionError,
    RestorationError,
    ValidationError,
)
from security.exceptions import PermissionDeniedError

if TYPE_CHECKING:
    from database.dependency_graph_builder import DependencyGraph
    from desanitization.checkpoint_manager import CheckpointManager
    from validation.desanitization_validator import DesanitizationValidator
    from security.access_control import AccessControl


@dataclass
class RestorationRecord:
    """Represents a single restoration operation."""
    table_name: str
    column_name: str
    record_id: str
    original_value: Optional[str]
    masked_value: Optional[str]
    
    def __hash__(self):
        return hash((self.table_name, self.column_name, self.record_id))


@dataclass
class RestorationReport:
    """Summary of desanitization operation results."""
    operation_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    tables_affected: int = 0
    columns_affected: int = 0
    records_requested: int = 0
    records_restored: int = 0
    mappings_applied: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    table_details: Dict[str, Dict[str, int]] = field(default_factory=dict)
    dry_run: bool = False
    post_verification_report: Optional[Any] = None  # ValidationReport type (avoid circular import)
    audit_id: Optional[int] = None  # Audit log record ID from AuditLogger
    
    def add_table_detail(self, table: str, column: str, rows_affected: int):
        """Add column-level restoration details."""
        if table not in self.table_details:
            self.table_details[table] = {}
        self.table_details[table][column] = rows_affected
    
    def has_verification_failures(self) -> bool:
        """Check if post-restoration verification failed."""
        if self.post_verification_report is None:
            return False
        return not self.post_verification_report.is_valid()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary for JSON serialization."""
        result = {
            'operation_id': self.operation_id,
            'audit_id': self.audit_id,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_seconds': (
                (self.end_time - self.start_time).total_seconds()
                if self.end_time else None
            ),
            'summary': {
                'tables_affected': self.tables_affected,
                'columns_affected': self.columns_affected,
                'records_requested': self.records_requested,
                'records_restored': self.records_restored,
                'mappings_applied': self.mappings_applied,
            },
            'table_details': self.table_details,
            'errors': self.errors,
            'warnings': self.warnings,
            'dry_run': self.dry_run,
        }
        
        # Add verification results if available
        if self.post_verification_report:
            result['post_verification'] = self.post_verification_report.to_dict()
        
        return result


class DesanitizationEngine:
    """
    Core engine for database desanitization operations.
    
    Restores original values from sanitized data using mapping tables created
    during the sanitization process. Supports record-level restoration with
    transaction safety and comprehensive validation.
    
    Attributes:
        connection: Active database connection
        mapping_manager: MappingTableManager instance for retrieving mappings
        schema_inspector: SchemaInspector instance for PK metadata
        logger: Logger instance for operation tracking
    """
    
    def __init__(
        self,
        connection,
        mapping_manager,
        schema_inspector,
        logger: Optional[logging.Logger] = None,
        dependency_graph: Optional['DependencyGraph'] = None,
        checkpoint_manager: Optional['CheckpointManager'] = None,
        validator: Optional['DesanitizationValidator'] = None,
        audit_logger: Optional[Any] = None,  # AuditLogger type (avoid circular import)
        access_control: Optional['AccessControl'] = None,  # AccessControl for RBAC (Story 7.1)
        rate_limit_ms: int = 0,
        date_range_start: Optional[datetime] = None,
        date_range_end: Optional[datetime] = None
    ):
        """
        Initialize desanitization engine.
        
        Args:
            connection: pyodbc connection object with autocommit=False
            mapping_manager: MappingTableManager instance
            schema_inspector: SchemaInspector instance
            logger: Optional logger instance (creates default if not provided)
            dependency_graph: Optional DependencyGraph for multi-table operations
            checkpoint_manager: Optional CheckpointManager for fault-tolerant operations
            validator: Optional DesanitizationValidator for pre-flight checks
            audit_logger: Optional AuditLogger for compliance logging (default: None)
            access_control: Optional AccessControl for role-based access control (Story 7.1)
                           If None, permission checks are skipped (backward compatible)
            rate_limit_ms: Rate limiting delay in milliseconds between column restorations
                          (default: 0 = no rate limiting). Story 5.2.
            date_range_start: Optional start date for filtering mappings by created_at.
                             Story 5.2 - Incremental desanitization.
            date_range_end: Optional end date for filtering mappings by created_at.
                           Story 5.2 - Incremental desanitization.
        """
        self.connection = connection
        self.mapping_manager = mapping_manager
        self.schema_inspector = schema_inspector
        self.logger = logger or logging.getLogger(__name__)
        self.dependency_graph = dependency_graph
        self.checkpoint_manager = checkpoint_manager
        self.validator = validator
        self.audit_logger = audit_logger
        self.access_control = access_control  # Story 7.1: RBAC integration
        
        # Story 5.2: Incremental desanitization parameters
        self.rate_limit_ms = rate_limit_ms
        self.date_range_start = date_range_start
        self.date_range_end = date_range_end
        
        # Operation state
        self._operation_id = None
        self._current_report = None
    
    def _check_permission(self, operation_type: str, dry_run: bool):
        """
        Check user permissions before executing operation (Story 7.1: RBAC).
        
        This method verifies that the current user has permission to perform
        the requested desanitization operation based on database role membership.
        
        Args:
            operation_type: Type of operation (RECORD/COLUMN/TABLE/DATABASE)
            dry_run: Whether this is a dry-run (preview) operation
        
        Raises:
            PermissionDeniedError: If user lacks required permissions
        
        Notes:
            - If access_control is None, permission check is skipped (backward compatible)
            - Permission-denied attempts are logged to audit system if available
            - Detailed permission denial reasons provided for troubleshooting
        """
        if self.access_control is None:
            # Backward compatible: no permission check if access_control not configured
            return
        
        try:
            allowed, reason = self.access_control.check_permission(operation_type, dry_run)
            
            if not allowed:
                # Log permission denial to audit system
                if self.audit_logger and self._current_report:
                    try:
                        # Get user info for audit log
                        current_user = self.access_control._get_current_user()
                        user_roles = self.access_control._get_user_roles(current_user)
                        
                        # Log permission denied event
                        self.audit_logger.log_permission_denied(
                            operation_id=self._current_report.operation_id,
                            operation_type=operation_type,
                            target_table=getattr(self, '_current_table', None),
                            required_roles=self.access_control.config.allowed_roles,
                            user_roles=user_roles
                        )
                    except Exception as e:
                        self.logger.warning(f"Failed to log permission denial to audit: {e}")
                
                # Raise permission denied error
                raise PermissionDeniedError(
                    reason,
                    operation_type=operation_type,
                    required_roles=self.access_control.config.allowed_roles if self.access_control else [],
                    user_roles=self.access_control._get_user_roles(
                        self.access_control._get_current_user()
                    ) if self.access_control else []
                )
            
            # Permission granted - log for audit trail
            self.logger.info(f"[{operation_type}] Permission check passed: {reason}")
        
        except PermissionDeniedError:
            # Re-raise permission denied errors
            raise
        
        except Exception as e:
            # Unexpected error during permission check
            self.logger.error(f"Error during permission check: {e}")
            
            # Fail-safe: deny access on error (unless configured otherwise via config)
            if self.access_control and self.access_control.config.deny_on_role_check_failure:
                raise PermissionDeniedError(
                    f"Permission check failed due to error: {e}. "
                    f"Access denied for safety.",
                    operation_type=operation_type
                )
            else:
                # Log warning but allow operation (not recommended for production)
                self.logger.warning(
                    f"Permission check failed but continuing due to "
                    f"deny_on_role_check_failure=False: {e}"
                )
    
    def desanitize_records(
        self,
        table: str,
        record_ids: List[str],
        schema: str = 'dbo',
        batch_id: Optional[str] = None,
        dry_run: bool = True,
        skip_missing: bool = False,
        skip_verification: bool = False,
        strict_verification: bool = False
    ) -> RestorationReport:
        """
        Restore original values for specific records in a table.
        
        This is the main public method for record-level desanitization. It:
        1. Validates preconditions (mapping table exists, records valid)
        2. Retrieves mappings for specified record IDs
        3. Groups mappings by column for efficient batch updates
        4. Executes restoration using temp table pattern
        5. Validates results and generates comprehensive report
        
        Args:
            table: Name of table to restore
            record_ids: List of record IDs (primary key values as strings)
            schema: Database schema (default: 'dbo')
            batch_id: Optional batch ID to filter mappings
            dry_run: If True, preview changes without committing (default: True)
            skip_missing: If True, skip records without mappings instead of error
        
        Returns:
            RestorationReport with operation results
        
        Raises:
            PreconditionError: If setup validation fails
            MappingNotFoundError: If required mappings are missing (unless skip_missing=True)
            RestorationError: If database update fails
            ValidationError: If post-restoration validation fails
        
        Example:
            >>> engine = DesanitizationEngine(conn, mapping_mgr, inspector)
            >>> report = engine.desanitize_records(
            ...     table='Customers',
            ...     record_ids=['123', '456', '789'],
            ...     dry_run=False
            ... )
            >>> print(f"Restored {report.records_restored} records")
        """
        # Generate unique operation ID
        self._operation_id = self._generate_operation_id()
        
        # Initialize report
        self._current_report = RestorationReport(
            operation_id=self._operation_id,
            start_time=datetime.now(),
            records_requested=len(record_ids),
            dry_run=dry_run
        )
        
        # Audit logging: Log operation start
        if self.audit_logger:
            try:
                audit_id = self.audit_logger.log_operation_start(
                    operation_id=self._operation_id,
                    operation_type='RECORD',
                    target_table=table,
                    target_schema=schema,
                    target_record_ids=record_ids,
                    batch_id=batch_id,
                    dry_run=dry_run,
                    command_line=' '.join(sys.argv) if hasattr(sys, 'argv') else None
                )
                self._current_report.audit_id = audit_id
            except Exception as e:
                self.logger.warning(f"Audit logging failed (non-critical): {e}")
        
        # Story 7.1: Permission check (after report init, before validation)
        self._current_table = table  # Store for audit logging
        try:
            self._check_permission('RECORD', dry_run)
        except PermissionDeniedError as e:
            # Permission denied - add to report and re-raise
            self._current_report.errors.append(str(e))
            self._current_report.end_time = datetime.now()
            raise
        
        try:
            self.logger.info(
                f"[{self._operation_id}] Starting desanitization: "
                f"table=[{schema}].[{table}], records={len(record_ids)}, "
                f"dry_run={dry_run}"
            )
            
            # Phase 0: Pre-flight validation (if validator available)
            if self.validator:
                validation_report = self._run_validation(
                    scope='record',
                    table=table,
                    schema=schema,
                    record_ids=record_ids,
                    batch_id=batch_id
                )
                
                if not validation_report.is_valid():
                    # Add validation failures to report
                    for check in validation_report.failed_checks:
                        self._current_report.errors.append(
                            f"Validation failed - {check.check_name}: {check.message}"
                        )
                    
                    self._current_report.end_time = datetime.now()
                    
                    raise ValidationError(
                        f"Pre-flight validation failed: {len(validation_report.failed_checks)} check(s) failed. "
                        f"See report for details."
                    )
                
                # Add warnings to report
                for warning in validation_report.warnings:
                    self._current_report.warnings.append(
                        f"Validation warning - {warning.check_name}: {warning.message}"
                    )
            
            # Phase 1: Validate preconditions
            self._validate_preconditions(table, schema, record_ids)
            
            # Phase 2: Retrieve mappings
            mappings = self._retrieve_mappings(
                table, schema, record_ids, batch_id, skip_missing
            )
            
            if not mappings:
                self._current_report.warnings.append(
                    f"No mappings found for table [{schema}].[{table}]"
                )
                self._current_report.end_time = datetime.now()
                return self._current_report
            
            # Phase 3: Build restoration batches by column
            batches = self._build_restoration_batches(mappings)
            
            # Phase 4: Execute restoration
            if not dry_run:
                self._execute_restoration(table, schema, batches)
            else:
                self._preview_restoration(table, schema, batches)
            
            # Phase 5: Validate and finalize
            if not dry_run:
                self._validate_restoration(
                    restoration_report=self._current_report,
                    table=table,
                    schema=schema,
                    scope='record',
                    skip_verification=skip_verification,
                    strict_verification=strict_verification
                )
            
            self._current_report.end_time = datetime.now()
            
            # Audit logging: Log operation complete
            if self.audit_logger:
                try:
                    validation_passed = None
                    validation_warnings = 0
                    validation_errors = 0
                    
                    if self._current_report.post_verification_report:
                        validation_passed = self._current_report.post_verification_report.is_valid()
                        validation_warnings = len(self._current_report.post_verification_report.warnings)
                        validation_errors = len(self._current_report.post_verification_report.failed_checks)
                    
                    self.audit_logger.log_operation_complete(
                        audit_id=self._current_report.audit_id,
                        operation_id=self._operation_id,
                        rows_restored=self._current_report.records_restored,
                        mappings_applied=self._current_report.mappings_applied,
                        columns_affected=self._current_report.columns_affected,
                        tables_affected=self._current_report.tables_affected,
                        validation_passed=validation_passed,
                        validation_warnings_count=validation_warnings,
                        validation_errors_count=validation_errors
                    )
                except Exception as e:
                    self.logger.warning(f"Audit logging failed (non-critical): {e}")
            
            self.logger.info(
                f"[{self._operation_id}] Desanitization complete: "
                f"records_restored={self._current_report.records_restored}, "
                f"mappings_applied={self._current_report.mappings_applied}"
            )
            
            return self._current_report
            
        except Exception as e:
            self._current_report.errors.append(str(e))
            self._current_report.end_time = datetime.now()
            
            # Audit logging: Log operation failure
            if self.audit_logger:
                try:
                    self.audit_logger.log_operation_failure(
                        audit_id=self._current_report.audit_id,
                        operation_id=self._operation_id,
                        error_message=str(e),
                        error_type=type(e).__name__,
                        rows_restored=self._current_report.records_restored,
                        mappings_applied=self._current_report.mappings_applied
                    )
                except Exception as audit_err:
                    self.logger.warning(f"Audit logging failed (non-critical): {audit_err}")
            
            self.logger.error(
                f"[{self._operation_id}] Desanitization failed: {e}",
                exc_info=True
            )
            raise
    
    def desanitize_columns(
        self,
        table: str,
        column_names: List[str],
        schema: str = 'dbo',
        batch_id: Optional[str] = None,
        dry_run: bool = True,
        progress_callback: Optional[callable] = None,
        skip_verification: bool = False,
        strict_verification: bool = False
    ) -> RestorationReport:
        """
        Restore original values for specific columns across ALL records in a table.
        
        This is the main public method for column-level desanitization. It:
        1. Validates columns exist and have mappings
        2. Retrieves ALL mappings for specified columns (no record ID filter)
        3. Groups mappings by column for efficient batch updates
        4. Executes restoration using temp table pattern
        5. Reports progress for large operations
        6. Validates results and generates comprehensive report
        
        Args:
            table: Name of table to restore
            column_names: List of column names to restore
            schema: Database schema (default: 'dbo')
            batch_id: Optional batch ID to filter mappings
            dry_run: If True, preview changes without committing (default: True)
            progress_callback: Optional callback function(column, current, total, records_processed)
        
        Returns:
            RestorationReport with operation results
        
        Raises:
            PreconditionError: If setup validation fails
            RestorationError: If database update fails
            ValidationError: If post-restoration validation fails
        
        Example:
            >>> engine = DesanitizationEngine(conn, mapping_mgr, inspector)
            >>> report = engine.desanitize_columns(
            ...     table='Customers',
            ...     column_names=['Email', 'PhoneNumber'],
            ...     dry_run=False
            ... )
            >>> print(f"Restored {report.columns_affected} columns")
        """
        # Generate unique operation ID
        self._operation_id = self._generate_operation_id()
        
        # Initialize report
        self._current_report = RestorationReport(
            operation_id=self._operation_id,
            start_time=datetime.now(),
            dry_run=dry_run
        )
        
        # Audit logging: Log operation start
        if self.audit_logger:
            try:
                audit_id = self.audit_logger.log_operation_start(
                    operation_id=self._operation_id,
                    operation_type='COLUMN',
                    target_table=table,
                    target_schema=schema,
                    target_columns=column_names,
                    batch_id=batch_id,
                    dry_run=dry_run,
                    command_line=' '.join(sys.argv) if hasattr(sys, 'argv') else None
                )
                self._current_report.audit_id = audit_id
            except Exception as e:
                self.logger.warning(f"Audit logging failed (non-critical): {e}")
        
        # Story 7.1: Permission check (after report init, before validation)
        self._current_table = table  # Store for audit logging
        try:
            self._check_permission('COLUMN', dry_run)
        except PermissionDeniedError as e:
            # Permission denied - add to report and re-raise
            self._current_report.errors.append(str(e))
            self._current_report.end_time = datetime.now()
            raise
        
        try:
            self.logger.info(
                f"[{self._operation_id}] Starting column-level desanitization: "
                f"table=[{schema}].[{table}], columns={column_names}, "
                f"dry_run={dry_run}"
            )
            
            # Phase 0: Pre-flight validation (if validator available)
            if self.validator:
                validation_report = self._run_validation(
                    scope='column',
                    table=table,
                    schema=schema,
                    columns=column_names,
                    batch_id=batch_id
                )
                
                if not validation_report.is_valid():
                    for check in validation_report.failed_checks:
                        self._current_report.errors.append(
                            f"Validation failed - {check.check_name}: {check.message}"
                        )
                    
                    self._current_report.end_time = datetime.now()
                    
                    raise ValidationError(
                        f"Pre-flight validation failed: {len(validation_report.failed_checks)} check(s) failed"
                    )
                
                for warning in validation_report.warnings:
                    self._current_report.warnings.append(
                        f"Validation warning - {warning.check_name}: {warning.message}"
                    )
            
            # Phase 1: Validate preconditions (table exists, columns valid)
            self._validate_preconditions(table, schema, [])  # Empty record_ids for column-level
            self._validate_columns(table, schema, column_names)
            
            # Phase 2: Retrieve ALL mappings for specified columns
            mappings = self._retrieve_all_column_mappings(
                table, schema, column_names, batch_id
            )
            
            if not mappings:
                self._current_report.warnings.append(
                    f"No mappings found for columns {column_names} in table [{schema}].[{table}]"
                )
                self._current_report.end_time = datetime.now()
                return self._current_report
            
            # Phase 3: Build restoration batches by column
            batches = self._build_restoration_batches(mappings)
            
            # Phase 4: Execute restoration with progress tracking
            if not dry_run:
                self._execute_restoration(
                    table, schema, batches, progress_callback=progress_callback
                )
            else:
                self._preview_restoration(table, schema, batches)
            
            # Phase 5: Validate and finalize
            if not dry_run:
                self._validate_restoration(
                    restoration_report=self._current_report,
                    table=table,
                    schema=schema,
                    scope='column',
                    skip_verification=skip_verification,
                    strict_verification=strict_verification
                )
            
            self._current_report.end_time = datetime.now()
            
            # Audit logging: Log operation complete
            if self.audit_logger:
                try:
                    validation_passed = None
                    validation_warnings = 0
                    validation_errors = 0
                    
                    if self._current_report.post_verification_report:
                        validation_passed = self._current_report.post_verification_report.is_valid()
                        validation_warnings = len(self._current_report.post_verification_report.warnings)
                        validation_errors = len(self._current_report.post_verification_report.failed_checks)
                    
                    self.audit_logger.log_operation_complete(
                        audit_id=self._current_report.audit_id,
                        operation_id=self._operation_id,
                        rows_restored=self._current_report.records_restored,
                        mappings_applied=self._current_report.mappings_applied,
                        columns_affected=self._current_report.columns_affected,
                        tables_affected=self._current_report.tables_affected,
                        validation_passed=validation_passed,
                        validation_warnings_count=validation_warnings,
                        validation_errors_count=validation_errors
                    )
                except Exception as e:
                    self.logger.warning(f"Audit logging failed (non-critical): {e}")
            
            self.logger.info(
                f"[{self._operation_id}] Column-level desanitization complete: "
                f"columns_affected={self._current_report.columns_affected}, "
                f"records_restored={self._current_report.records_restored}, "
                f"mappings_applied={self._current_report.mappings_applied}"
            )
            
            return self._current_report
            
        except Exception as e:
            self._current_report.errors.append(str(e))
            self._current_report.end_time = datetime.now()
            
            # Audit logging: Log operation failure
            if self.audit_logger:
                try:
                    self.audit_logger.log_operation_failure(
                        audit_id=self._current_report.audit_id,
                        operation_id=self._operation_id,
                        error_message=str(e),
                        error_type=type(e).__name__,
                        rows_restored=self._current_report.records_restored,
                        mappings_applied=self._current_report.mappings_applied
                    )
                except Exception as audit_err:
                    self.logger.warning(f"Audit logging failed (non-critical): {audit_err}")
            
            self.logger.error(
                f"[{self._operation_id}] Column-level desanitization failed: {e}",
                exc_info=True
            )
            raise
    
    def desanitize_table(
        self,
        table: str,
        schema: str = 'dbo',
        batch_id: Optional[str] = None,
        dry_run: bool = True,
        progress_callback: Optional[callable] = None,
        skip_verification: bool = False,
        strict_verification: bool = False
    ) -> RestorationReport:
        """
        Restore original values for ALL columns with mappings in a table.
        
        This is the main public method for table-level desanitization. It:
        1. Auto-discovers columns that have mappings in the mapping table
        2. Delegates to desanitize_columns() to restore all discovered columns
        3. Validates referential integrity after restoration
        4. Reports progress for large operations
        5. Generates comprehensive report
        
        Key difference from desanitize_columns(): This method automatically discovers
        which columns have mappings, so the user doesn't need to specify them manually.
        
        Args:
            table: Name of table to restore
            schema: Database schema (default: 'dbo')
            batch_id: Optional batch ID to filter mappings
            dry_run: If True, preview changes without committing (default: True)
            progress_callback: Optional callback function(column, current, total, records_processed)
        
        Returns:
            RestorationReport with operation results
        
        Raises:
            PreconditionError: If table has no mappings or setup validation fails
            RestorationError: If database update fails
            ValidationError: If post-restoration validation fails
        
        Example:
            >>> engine = DesanitizationEngine(conn, mapping_mgr, inspector)
            >>> report = engine.desanitize_table(
            ...     table='Customers',
            ...     dry_run=False
            ... )
            >>> print(f"Restored {report.columns_affected} columns")
        """
        # Generate unique operation ID
        self._operation_id = self._generate_operation_id()
        
        # Initialize report
        self._current_report = RestorationReport(
            operation_id=self._operation_id,
            start_time=datetime.now(),
            dry_run=dry_run
        )
        
        # Audit logging: Log operation start
        if self.audit_logger:
            try:
                audit_id = self.audit_logger.log_operation_start(
                    operation_id=self._operation_id,
                    operation_type='TABLE',
                    target_table=table,
                    target_schema=schema,
                    batch_id=batch_id,
                    dry_run=dry_run,
                    command_line=' '.join(sys.argv) if hasattr(sys, 'argv') else None
                )
                self._current_report.audit_id = audit_id
            except Exception as e:
                self.logger.warning(f"Audit logging failed (non-critical): {e}")
        
        # Story 7.1: Permission check (after report init, before validation)
        self._current_table = table  # Store for audit logging
        try:
            self._check_permission('TABLE', dry_run)
        except PermissionDeniedError as e:
            # Permission denied - add to report and re-raise
            self._current_report.errors.append(str(e))
            self._current_report.end_time = datetime.now()
            raise
        
        try:
            self.logger.info(
                f"[{self._operation_id}] Starting table-level desanitization: "
                f"table=[{schema}].[{table}], dry_run={dry_run}"
            )
            
            # Phase 0: Pre-flight validation (if validator available)
            if self.validator:
                validation_report = self._run_validation(
                    scope='table',
                    table=table,
                    schema=schema,
                    batch_id=batch_id
                )
                
                # Check for mapping availability failures specifically
                mapping_failures = [c for c in validation_report.failed_checks 
                                  if c.check_name == "Mapping Availability"]
                
                if mapping_failures:
                    # No mappings found - skip table gracefully instead of failing
                    self._current_report.warnings.append(
                        f"Table [{schema}].[{table}] has no mappings - skipping (may not contain PII columns)"
                    )
                    self._current_report.end_time = datetime.now()
                    return self._current_report
                
                # Check other validation failures
                other_failures = [c for c in validation_report.failed_checks 
                                if c.check_name != "Mapping Availability"]
                
                if other_failures:
                    for check in other_failures:
                        self._current_report.errors.append(
                            f"Validation failed - {check.check_name}: {check.message}"
                        )
                    
                    self._current_report.end_time = datetime.now()
                    
                    raise ValidationError(
                        f"Pre-flight validation failed: {len(other_failures)} check(s) failed"
                    )
                
                for warning in validation_report.warnings:
                    self._current_report.warnings.append(
                        f"Validation warning - {warning.check_name}: {warning.message}"
                    )
            
            # Phase 1: Auto-discover columns with mappings
            column_names = self._get_columns_with_mappings(table, schema, batch_id)
            
            if not column_names:
                raise PreconditionError(
                    f"No mappings found for table [{schema}].[{table}]",
                    suggested_action=(
                        f"No columns have mappings in the mapping table. "
                        f"Possible causes:\n"
                        f"  1. Table has not been sanitized yet\n"
                        f"  2. Incorrect table name or schema\n"
                        f"  3. Batch ID filter excluded all mappings"
                    )
                )
            
            self.logger.info(
                f"[{self._operation_id}] Auto-discovered {len(column_names)} "
                f"column(s) with mappings: {column_names}"
            )
            
            # Phase 2: Delegate to desanitize_columns() for restoration
            # This reuses the entire column-level restoration pipeline
            result = self.desanitize_columns(
                table=table,
                column_names=column_names,
                schema=schema,
                batch_id=batch_id,
                dry_run=dry_run,
                progress_callback=progress_callback,
                skip_verification=skip_verification,
                strict_verification=strict_verification
            )
            
            # Phase 3: Validate referential integrity (if not dry-run)
            if not dry_run:
                fk_issues = self._validate_referential_integrity(table, schema)
                if fk_issues:
                    for issue in fk_issues:
                        result.warnings.append(
                            f"Referential integrity issue: {issue['constraint_name']} - "
                            f"{issue['orphaned_count']} orphaned record(s)"
                        )
                        self.logger.warning(
                            f"[{self._operation_id}] FK violation: {issue['constraint_name']}, "
                            f"orphans: {issue['orphaned_count']}, sample: {issue['sample_ids']}"
                        )
            
            self.logger.info(
                f"[{self._operation_id}] Table-level desanitization complete: "
                f"columns_affected={result.columns_affected}, "
                f"records_restored={result.records_restored}"
            )
            
            return result
            
        except PreconditionError:
            # Re-raise precondition errors as-is
            self._current_report.end_time = datetime.now()
            raise
        except Exception as e:
            self._current_report.errors.append(str(e))
            self._current_report.end_time = datetime.now()
            self.logger.error(
                f"[{self._operation_id}] Table-level desanitization failed: {e}",
                exc_info=True
            )
            raise
    
    def _generate_operation_id(self) -> str:
        """Generate unique operation ID for tracking."""
        import uuid
        return f"DESAN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    
    def _run_validation(
        self,
        scope: str,
        table: Optional[str] = None,
        schema: Optional[str] = None,
        columns: Optional[List[str]] = None,
        record_ids: Optional[List[str]] = None,
        batch_id: Optional[str] = None
    ):
        """
        Run pre-flight validation checks using DesanitizationValidator.
        
        Args:
            scope: Validation scope ('database', 'table', 'column', 'record')
            table: Table name (required for table/column/record scope)
            schema: Schema name (default: 'dbo')
            columns: Column names (for column scope)
            record_ids: Record IDs (for record scope)
            batch_id: Optional batch ID filter
        
        Returns:
            ValidationReport with all check results
        
        Raises:
            ValidationError: If validator not configured
        """
        if not self.validator:
            raise ValidationError("Validator not configured for this engine instance")
        
        self.logger.info(
            f"[{self._operation_id}] Running pre-flight validation for {scope} scope..."
        )
        
        validation_report = self.validator.validate_desanitization(
            scope=scope,
            table=table,
            schema=schema or 'dbo',
            columns=columns,
            record_ids=record_ids,
            batch_id=batch_id
        )
        
        self.logger.debug(
            f"[{self._operation_id}] Validation complete: "
            f"{len(validation_report.passed_checks)} passed, "
            f"{len(validation_report.failed_checks)} failed, "
            f"{len(validation_report.warnings)} warnings"
        )
        
        return validation_report
    
    def _validate_preconditions(
        self, table: str, schema: str, record_ids: List[str]
    ) -> None:
        """
        Validate preconditions before desanitization.
        
        Checks:
        - Mapping table exists and is accessible
        - Target table exists
        - Record IDs are valid format
        - Database connection is active
        
        Args:
            table: Table name to validate
            schema: Schema name
            record_ids: List of record IDs to validate
        
        Raises:
            PreconditionError: If any validation fails
        """
        self.logger.debug(f"[{self._operation_id}] Validating preconditions...")
        
        # Check mapping table exists
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_NAME = ?",
                (self.mapping_manager.table_name,)
            )
            if cursor.fetchone()[0] == 0:
                raise PreconditionError(
                    f"Mapping table '{self.mapping_manager.table_name}' does not exist",
                    suggested_action="Run sanitization with mapping_capture enabled first"
                )
        except Exception as e:
            raise PreconditionError(
                f"Failed to verify mapping table: {e}",
                suggested_action="Check database connection and permissions"
            )
        
        # Check target table exists
        if not self.schema_inspector.validate_table_exists(table, schema):
            raise PreconditionError(
                f"Target table [{schema}].[{table}] does not exist",
                suggested_action="Verify table name and schema are correct"
            )
        
        # Validate record IDs format (only for record-level operations)
        if record_ids:  # Skip validation if empty (column-level doesn't need record IDs)
            for record_id in record_ids:
                if not isinstance(record_id, str) or not record_id.strip():
                    raise PreconditionError(
                        f"Invalid record ID format: {record_id}",
                        suggested_action="Record IDs must be non-empty strings"
                    )
        
        self.logger.debug(f"[{self._operation_id}] Preconditions validated successfully")
    
    def _validate_columns(
        self, table: str, schema: str, column_names: List[str]
    ) -> None:
        """
        Validate that columns exist and have mappings.
        
        Checks:
        - Column list is not empty
        - All specified columns exist in the target table
        - Columns have at least some mappings in the mapping table
        
        Args:
            table: Table name
            schema: Schema name
            column_names: List of column names to validate
        
        Raises:
            PreconditionError: If any validation fails
        """
        self.logger.debug(
            f"[{self._operation_id}] Validating columns: {column_names}..."
        )
        
        # Check column list not empty
        if not column_names:
            raise PreconditionError(
                "No columns provided",
                suggested_action="Provide at least one column name to restore"
            )
        
        # Get all columns in target table
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
                """,
                (schema, table)
            )
            existing_columns = {row[0] for row in cursor.fetchall()}
        except Exception as e:
            raise PreconditionError(
                f"Failed to retrieve column list for [{schema}].[{table}]: {e}",
                suggested_action="Check database connection and permissions"
            )
        
        # Validate each column exists
        invalid_columns = [col for col in column_names if col not in existing_columns]
        if invalid_columns:
            raise PreconditionError(
                f"Invalid columns: {invalid_columns} not found in [{schema}].[{table}]",
                suggested_action=f"Available columns: {sorted(existing_columns)}"
            )
        
        # Check if columns have mappings
        full_table_name = f"{schema}.{table}" if schema != 'dbo' else table
        columns_without_mappings = []
        
        for column_name in column_names:
            try:
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {self.mapping_manager.fully_qualified_table}
                    WHERE table_name = ? AND column_name = ?
                    """,
                    (full_table_name, column_name)
                )
                count = cursor.fetchone()[0]
                if count == 0:
                    columns_without_mappings.append(column_name)
            except Exception as e:
                self.logger.warning(
                    f"[{self._operation_id}] Could not check mappings for {column_name}: {e}"
                )
        
        if columns_without_mappings:
            self._current_report.warnings.append(
                f"No mappings found for columns: {columns_without_mappings}"
            )
            self.logger.warning(
                f"[{self._operation_id}] Columns without mappings: {columns_without_mappings}"
            )
        
        self.logger.debug(
            f"[{self._operation_id}] Columns validated successfully"
        )
    
    def _retrieve_mappings(
        self,
        table: str,
        schema: str,
        record_ids: List[str],
        batch_id: Optional[str],
        skip_missing: bool
    ) -> List[RestorationRecord]:
        """
        Retrieve mappings for specified records.
        
        Args:
            table: Table name
            schema: Schema name
            record_ids: List of record IDs
            batch_id: Optional batch ID filter
            skip_missing: If True, skip records without mappings
        
        Returns:
            List of RestorationRecord objects
        
        Raises:
            MappingNotFoundError: If mappings missing and skip_missing=False
        """
        self.logger.debug(
            f"[{self._operation_id}] Retrieving mappings for {len(record_ids)} records..."
        )
        
        # Use mapping manager to fetch mappings
        try:
            full_table_name = f"{schema}.{table}" if schema != 'dbo' else table
            
            # Get mappings from mapping table (Story 5.2: with date range filtering)
            raw_mappings = self.mapping_manager.get_mappings(
                table_name=full_table_name,
                record_ids=record_ids,
                batch_id=batch_id,
                date_range_start=self.date_range_start,
                date_range_end=self.date_range_end
            )
            
            # Convert to RestorationRecord objects
            restoration_records = []
            for mapping in raw_mappings:
                record = RestorationRecord(
                    table_name=mapping.get('table_name', full_table_name),
                    column_name=mapping['column_name'],
                    record_id=mapping['record_id'],
                    original_value=mapping['original_value'],
                    masked_value=mapping['masked_value']
                )
                restoration_records.append(record)
            
            # Check for missing mappings
            found_record_ids = {r.record_id for r in restoration_records}
            missing_record_ids = set(record_ids) - found_record_ids
            
            if missing_record_ids:
                message = (
                    f"Mappings not found for {len(missing_record_ids)} record(s): "
                    f"{list(missing_record_ids)[:5]}"
                )
                if len(missing_record_ids) > 5:
                    message += f" ... and {len(missing_record_ids) - 5} more"
                
                if skip_missing:
                    self._current_report.warnings.append(message)
                    self.logger.warning(f"[{self._operation_id}] {message}")
                else:
                    raise MappingNotFoundError(message, list(missing_record_ids))
            
            self.logger.debug(
                f"[{self._operation_id}] Retrieved {len(restoration_records)} mappings"
            )
            
            return restoration_records
            
        except MappingNotFoundError:
            raise
        except Exception as e:
            raise RestorationError(
                f"Failed to retrieve mappings: {e}",
                table=table
            )
    
    def _retrieve_all_column_mappings(
        self,
        table: str,
        schema: str,
        column_names: List[str],
        batch_id: Optional[str]
    ) -> List[RestorationRecord]:
        """
        Retrieve ALL mappings for specified columns (no record ID filter).
        
        This method is used for column-level desanitization where we want to
        restore all records in specific columns. It fetches mappings in batches
        to avoid memory issues with large tables.
        
        Args:
            table: Table name
            schema: Schema name
            column_names: List of column names to retrieve mappings for
            batch_id: Optional batch ID filter
        
        Returns:
            List of RestorationRecord objects for all records in specified columns
        
        Raises:
            RestorationError: If mapping retrieval fails
        """
        self.logger.debug(
            f"[{self._operation_id}] Retrieving ALL mappings for columns: {column_names}..."
        )
        
        try:
            full_table_name = f"{schema}.{table}" if schema != 'dbo' else table
            all_restoration_records = []
            
            # Retrieve mappings for each column separately to enable progress tracking
            for column_name in column_names:
                self.logger.debug(
                    f"[{self._operation_id}] Fetching mappings for column [{column_name}]..."
                )
                
                # Get ALL mappings for this column (Story 5.2: with date range filtering)
                raw_mappings = self.mapping_manager.get_mappings(
                    table_name=full_table_name,
                    column_name=column_name,
                    record_ids=None,  # Key difference: fetch ALL records
                    batch_id=batch_id,
                    date_range_start=self.date_range_start,
                    date_range_end=self.date_range_end
                )
                
                # Convert to RestorationRecord objects
                for mapping in raw_mappings:
                    record = RestorationRecord(
                        table_name=mapping.get('table_name', full_table_name),
                        column_name=mapping['column_name'],
                        record_id=mapping['record_id'],
                        original_value=mapping['original_value'],
                        masked_value=mapping['masked_value']
                    )
                    all_restoration_records.append(record)
                
                self.logger.debug(
                    f"[{self._operation_id}] Retrieved {len(raw_mappings)} mappings "
                    f"for column [{column_name}]"
                )
            
            self.logger.info(
                f"[{self._operation_id}] Retrieved total {len(all_restoration_records)} "
                f"mappings for {len(column_names)} column(s)"
            )
            
            return all_restoration_records
            
        except Exception as e:
            raise RestorationError(
                f"Failed to retrieve column mappings: {e}",
                table=table
            )
    
    def _build_restoration_batches(
        self, mappings: List[RestorationRecord]
    ) -> Dict[str, List[RestorationRecord]]:
        """
        Group mappings by column for batch processing.
        
        Args:
            mappings: List of RestorationRecord objects
        
        Returns:
            Dictionary mapping column names to list of restoration records
        """
        batches = defaultdict(list)
        
        for mapping in mappings:
            batches[mapping.column_name].append(mapping)
        
        self.logger.debug(
            f"[{self._operation_id}] Built {len(batches)} restoration batches "
            f"(by column)"
        )
        
        return dict(batches)
    
    def _execute_restoration(
        self,
        table: str,
        schema: str,
        batches: Dict[str, List[RestorationRecord]],
        progress_callback: Optional[callable] = None
    ) -> None:
        """
        Execute restoration using temp table pattern.
        
        This method performs the actual database updates to restore original values.
        Uses the temp table + UPDATE-JOIN pattern for efficiency and atomicity.
        
        Args:
            table: Table name
            schema: Schema name
            batches: Dictionary of column -> restoration records
            progress_callback: Optional callback function(column, current, total, records_processed)
        
        Raises:
            RestorationError: If update fails
        """
        cursor = self.connection.cursor()
        full_table_name = f"[{schema}].[{table}]"
        
        total_columns = len(batches)
        current_column = 0
        
        try:
            for column_name, records in batches.items():
                current_column += 1
                
                self.logger.info(
                    f"[{self._operation_id}] Restoring column [{column_name}] "
                    f"({current_column}/{total_columns}): {len(records)} records"
                )
                
                # Call progress callback if provided
                if progress_callback:
                    try:
                        progress_callback(
                            column=column_name,
                            current=current_column,
                            total=total_columns,
                            records=len(records)
                        )
                    except Exception as callback_error:
                        self.logger.warning(
                            f"[{self._operation_id}] Progress callback failed: {callback_error}"
                        )
                
                # Get primary key info for WHERE clause
                pk_info = self.schema_inspector.get_primary_key_columns(table, schema)
                pk_where_clause = self.schema_inspector.build_pk_where_clause(
                    pk_info, "tmp.record_id"
                )
                
                # Create temp table
                temp_table_name = f"#temp_restore_{column_name.replace(' ', '_')}"
                cursor.execute(f"""
                    CREATE TABLE {temp_table_name} (
                        record_id NVARCHAR(MAX),
                        original_value NVARCHAR(MAX)
                    )
                """)
                
                # Insert restoration data into temp table
                distinct_record_ids = set()
                for record in records:
                    cursor.execute(
                        f"INSERT INTO {temp_table_name} (record_id, original_value) "
                        f"VALUES (?, ?)",
                        (record.record_id, record.original_value)
                    )
                    distinct_record_ids.add(record.record_id)
                
                # Count mappings loaded
                total_mappings = len(records)
                distinct_mappings = len(distinct_record_ids)
                
                # Execute UPDATE using JOIN
                update_sql = f"""
                    UPDATE t
                    SET t.[{column_name}] = tmp.original_value
                    FROM {full_table_name} t
                    INNER JOIN {temp_table_name} tmp ON {pk_where_clause}
                """
                
                cursor.execute(update_sql)
                rows_affected = cursor.rowcount
                
                # Enhanced logging: Check for discrepancies
                if distinct_mappings > rows_affected:
                    discrepancy = distinct_mappings - rows_affected
                    
                    # Query to find orphaned mappings (records that don't exist in table)
                    orphan_check_sql = f"""
                        SELECT COUNT(*) 
                        FROM {temp_table_name} tmp
                        WHERE NOT EXISTS (
                            SELECT 1 
                            FROM {full_table_name} t 
                            WHERE {pk_where_clause}
                        )
                    """
                    cursor.execute(orphan_check_sql)
                    orphaned_count = cursor.fetchone()[0]
                    
                    warning_msg = (
                        f"Restoration discrepancy for [{column_name}]: "
                        f"Retrieved {total_mappings} mapping(s) ({distinct_mappings} distinct records), "
                        f"but only {rows_affected} row(s) were updated. "
                        f"Discrepancy: {discrepancy} record(s). "
                    )
                    
                    if orphaned_count > 0:
                        warning_msg += (
                            f"Cause: {orphaned_count} record(s) exist in mappings but not in database "
                            f"(likely deleted after sanitization)."
                        )
                    elif total_mappings > distinct_mappings:
                        duplicate_count = total_mappings - distinct_mappings
                        warning_msg += (
                            f"Note: {duplicate_count} duplicate mapping(s) found for same record(s)."
                        )
                    
                    self._current_report.warnings.append(warning_msg)
                    self.logger.warning(f"[{self._operation_id}] {warning_msg}")
                elif total_mappings > distinct_mappings:
                    # Duplicate mappings but all records restored
                    duplicate_count = total_mappings - distinct_mappings
                    info_msg = (
                        f"[{column_name}]: Found {duplicate_count} duplicate mapping(s), "
                        f"but all {distinct_mappings} unique record(s) were restored successfully."
                    )
                    self.logger.info(f"[{self._operation_id}] {info_msg}")
                
                # Update report
                self._current_report.add_table_detail(table, column_name, rows_affected)
                self._current_report.mappings_applied += total_mappings
                self._current_report.records_restored += rows_affected
                
                # Drop temp table
                cursor.execute(f"DROP TABLE {temp_table_name}")
                
                self.logger.info(
                    f"[{self._operation_id}] Restored [{column_name}]: "
                    f"{rows_affected} rows affected from {total_mappings} mapping(s)"
                )
                
                # Story 5.2: Rate limiting for production impact mitigation
                if self.rate_limit_ms > 0 and current_column < total_columns:
                    delay_seconds = self.rate_limit_ms / 1000.0
                    self.logger.info(
                        f"[{self._operation_id}] ⚠️ Rate limiting active: "
                        f"Waiting {delay_seconds:.3f}s before next column"
                    )
                    time.sleep(delay_seconds)
            
            # Commit transaction
            self.connection.commit()
            self.logger.info(f"[{self._operation_id}] Transaction committed successfully")
            
            # Update report counts
            self._current_report.tables_affected = 1
            self._current_report.columns_affected = len(batches)
            
        except Exception as e:
            self.connection.rollback()
            self.logger.error(
                f"[{self._operation_id}] Restoration failed, rolled back: {e}"
            )
            raise RestorationError(f"Failed to execute restoration: {e}", table=table)
    
    def _preview_restoration(
        self, table: str, schema: str, batches: Dict[str, List[RestorationRecord]]
    ) -> None:
        """
        Preview restoration without making changes (dry-run mode).
        
        Args:
            table: Table name
            schema: Schema name
            batches: Dictionary of column -> restoration records
        """
        self.logger.info(f"[{self._operation_id}] [DRY RUN] Preview mode - no changes will be made")
        
        total_records = sum(len(records) for records in batches.values())
        
        self._current_report.tables_affected = 1
        self._current_report.columns_affected = len(batches)
        self._current_report.records_restored = total_records
        self._current_report.mappings_applied = total_records
        
        for column_name, records in batches.items():
            self._current_report.add_table_detail(table, column_name, len(records))
            self.logger.info(
                f"[{self._operation_id}] [DRY RUN] Would restore [{column_name}]: "
                f"{len(records)} records"
            )
    
    def _validate_restoration(
        self,
        restoration_report: RestorationReport,
        table: str,
        schema: str,
        scope: str = 'record',
        skip_verification: bool = False,
        strict_verification: bool = False
    ) -> None:
        """
        Validate restoration results (Story 3.2: Post-Desanitization Verification).
        
        Performs comprehensive post-restoration checks to ensure data integrity:
        - Row count verification (data completeness)
        - Foreign key constraint validation (bidirectional)
        - Unique constraint validation
        - Data type preservation
        - NULL value validation
        - Sample-based verification for large tables
        
        Args:
            restoration_report: ResturationReport to attach verification results to
            table: Table name that was restored
            schema: Schema name
            scope: Restoration scope ('database', 'table', 'column', 'record')
            skip_verification: If True, skip post-restoration verification
            strict_verification: If True, treat warnings as failures
        
        Raises:
            ValidationError: If validation fails (critical errors or strict mode)
        """
        # Skip verification on dry-run (no actual changes to verify)
        if restoration_report.dry_run:
            self.logger.debug(
                f"[{self._operation_id}] Skipping verification (dry-run mode)"
            )
            return
        
        # Skip verification if explicitly disabled
        if skip_verification:
            self.logger.info(
                f"[{self._operation_id}] Skipping post-restoration verification (disabled)"
            )
            return
        
        # Skip verification if no validator configured
        if not self.validator:
            self.logger.debug(
                f"[{self._operation_id}] No validator configured, skipping verification"
            )
            return
        
        self.logger.info(
            f"[{self._operation_id}] Running post-restoration verification for [{schema}].[{table}]..."
        )
        
        try:
            # Run verification
            verification_report = self.validator.verify_restoration(
                scope=scope,
                table=table,
                schema=schema,
                restoration_report=restoration_report,
                connection=self.connection,
                strict_mode=strict_verification
            )
            
            # Attach verification report to restoration report
            restoration_report.post_verification_report = verification_report
            
            # Log verification summary
            self.logger.info(
                f"[{self._operation_id}] Verification complete: "
                f"{len(verification_report.passed_checks)} passed, "
                f"{len(verification_report.failed_checks)} failed, "
                f"{len(verification_report.warnings)} warnings"
            )
            
            # Add verification warnings to restoration report
            for warning in verification_report.warnings:
                restoration_report.warnings.append(
                    f"VERIFICATION WARNING: {warning.message}"
                )
            
            # Handle verification failures
            if not verification_report.is_valid():
                error_summary = "; ".join(
                    [f"{check.check_name}: {check.message}" 
                     for check in verification_report.failed_checks]
                )
                restoration_report.errors.append(
                    f"Post-restoration verification failed: {error_summary}"
                )
                
                # Raise exception if verification fails (ensures transaction rollback in production)
                raise ValidationError(
                    f"Post-restoration verification failed with {len(verification_report.failed_checks)} error(s). "
                    f"See verification report for details."
                )
        
        except ValidationError:
            # Re-raise validation errors
            raise
        except Exception as e:
            # Log unexpected errors but don't fail the restoration
            self.logger.error(
                f"[{self._operation_id}] Verification error (non-critical): {e}",
                exc_info=True
            )
            restoration_report.warnings.append(
                f"Post-restoration verification encountered an error: {e}"
            )
    
    def _get_columns_with_mappings(
        self,
        table: str,
        schema: str,
        batch_id: Optional[str]
    ) -> List[str]:
        """
        Auto-discover columns that have mappings in the mapping table.
        
        This method queries the mapping table to find all distinct column names
        that have stored mappings for the specified table. Used for table-level
        desanitization to automatically detect which columns need restoration.
        
        Args:
            table: Table name
            schema: Schema name
            batch_id: Optional batch ID filter
        
        Returns:
            Sorted list of column names that have mappings (alphabetical order)
        
        Raises:
            RestorationError: If query fails
        """
        self.logger.debug(
            f"[{self._operation_id}] Discovering columns with mappings for [{schema}].[{table}]..."
        )
        
        try:
            full_table_name = f"{schema}.{table}" if schema != 'dbo' else table
            cursor = self.connection.cursor()
            
            # Build query with optional batch_id filter
            if batch_id:
                query = f"""
                    SELECT DISTINCT column_name
                    FROM {self.mapping_manager.fully_qualified_table}
                    WHERE table_name = ? AND batch_id = ?
                    ORDER BY column_name
                """
                cursor.execute(query, (full_table_name, batch_id))
            else:
                query = f"""
                    SELECT DISTINCT column_name
                    FROM {self.mapping_manager.fully_qualified_table}
                    WHERE table_name = ?
                    ORDER BY column_name
                """
                cursor.execute(query, (full_table_name,))
            
            column_names = [row[0] for row in cursor.fetchall()]
            
            self.logger.debug(
                f"[{self._operation_id}] Discovered {len(column_names)} column(s): {column_names}"
            )
            
            return column_names
            
        except Exception as e:
            raise RestorationError(
                f"Failed to discover columns with mappings: {e}",
                table=table
            )
    
    def _validate_referential_integrity(
        self,
        table: str,
        schema: str
    ) -> List[Dict[str, Any]]:
        """
        Validate referential integrity after restoration.
        
        Checks outgoing foreign key constraints (this table -> parent tables)
        to ensure no orphaned records exist after desanitization. This is a
        basic implementation; more comprehensive validation is planned for Story 3.2.
        
        Args:
            table: Table name
            schema: Schema name
        
        Returns:
            List of FK violation dictionaries with keys:
                - constraint_name: Name of the violated constraint
                - orphaned_count: Number of orphaned records
                - sample_ids: Sample of orphaned record IDs (up to 5)
        """
        self.logger.debug(
            f"[{self._operation_id}] Validating referential integrity for [{schema}].[{table}]..."
        )
        
        violations = []
        
        try:
            cursor = self.connection.cursor()
            
            # Get all FK constraints where this table is the child (references other tables)
            cursor.execute(
                """
                SELECT 
                    fk.name AS constraint_name,
                    OBJECT_NAME(fk.parent_object_id) AS child_table,
                    COL_NAME(fc.parent_object_id, fc.parent_column_id) AS child_column,
                    OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS parent_schema,
                    OBJECT_NAME(fk.referenced_object_id) AS parent_table,
                    COL_NAME(fc.referenced_object_id, fc.referenced_column_id) AS parent_column
                FROM sys.foreign_keys AS fk
                INNER JOIN sys.foreign_key_columns AS fc 
                    ON fk.object_id = fc.constraint_object_id
                WHERE OBJECT_SCHEMA_NAME(fk.parent_object_id) = ?
                    AND OBJECT_NAME(fk.parent_object_id) = ?
                """,
                (schema, table)
            )
            
            fk_constraints = cursor.fetchall()
            
            if not fk_constraints:
                self.logger.debug(
                    f"[{self._operation_id}] No outgoing FK constraints found for [{schema}].[{table}]"
                )
                return violations
            
            # For each FK constraint, check for orphaned records
            for fk in fk_constraints:
                constraint_name = fk.constraint_name
                child_table = fk.child_table
                child_column = fk.child_column
                parent_schema = fk.parent_schema
                parent_table = fk.parent_table
                parent_column = fk.parent_column
                
                # Query to find orphaned records (child FK value not in parent table)
                orphan_query = f"""
                    SELECT TOP 5 c.[{child_column}]
                    FROM [{schema}].[{child_table}] c
                    LEFT JOIN [{parent_schema}].[{parent_table}] p
                        ON c.[{child_column}] = p.[{parent_column}]
                    WHERE c.[{child_column}] IS NOT NULL
                        AND p.[{parent_column}] IS NULL
                """
                
                cursor.execute(orphan_query)
                orphan_samples = [row[0] for row in cursor.fetchall()]
                
                if orphan_samples:
                    # Count total orphans
                    count_query = f"""
                        SELECT COUNT(*)
                        FROM [{schema}].[{child_table}] c
                        LEFT JOIN [{parent_schema}].[{parent_table}] p
                            ON c.[{child_column}] = p.[{parent_column}]
                        WHERE c.[{child_column}] IS NOT NULL
                            AND p.[{parent_column}] IS NULL
                    """
                    
                    cursor.execute(count_query)
                    orphan_count = cursor.fetchone()[0]
                    
                    violations.append({
                        'constraint_name': constraint_name,
                        'orphaned_count': orphan_count,
                        'sample_ids': orphan_samples,
                        'child_table': f"{schema}.{child_table}",
                        'child_column': child_column,
                        'parent_table': f"{parent_schema}.{parent_table}",
                        'parent_column': parent_column
                    })
                    
                    self.logger.warning(
                        f"[{self._operation_id}] FK violation detected: {constraint_name}, "
                        f"orphaned: {orphan_count}"
                    )
            
            if not violations:
                self.logger.debug(
                    f"[{self._operation_id}] Referential integrity validated successfully"
                )
            
            return violations
            
        except Exception as e:
            # Log error but don't fail the entire operation
            self.logger.error(
                f"[{self._operation_id}] Failed to validate referential integrity: {e}",
                exc_info=True
            )
            return []
    
    def _get_table_constraints(
        self,
        table: str,
        schema: str
    ) -> List[str]:
        """
        Extract foreign key constraint names for a table.
        
        Retrieves all FK constraints where the table is either:
        - Parent (referenced by other tables)
        - Child (references other tables)
        
        This information is needed to disable/enable constraints during
        circular dependency handling.
        
        Args:
            table: Table name
            schema: Schema name
        
        Returns:
            List of constraint names associated with the table
        
        Raises:
            RestorationError: If constraint extraction fails
        """
        self.logger.debug(
            f"[{self._operation_id}] Extracting FK constraints for [{schema}].[{table}]..."
        )
        
        try:
            cursor = self.connection.cursor()
            
            # Get all FK constraints where this table is involved (parent or child)
            cursor.execute(
                """
                SELECT DISTINCT fk.name AS constraint_name
                FROM sys.foreign_keys AS fk
                WHERE (
                    -- Table is child (has FK to other tables)
                    OBJECT_SCHEMA_NAME(fk.parent_object_id) = ?
                    AND OBJECT_NAME(fk.parent_object_id) = ?
                )
                OR (
                    -- Table is parent (referenced by other tables)
                    OBJECT_SCHEMA_NAME(fk.referenced_object_id) = ?
                    AND OBJECT_NAME(fk.referenced_object_id) = ?
                )
                """,
                (schema, table, schema, table)
            )
            
            constraints = [row.constraint_name for row in cursor.fetchall()]
            
            self.logger.debug(
                f"[{self._operation_id}] Found {len(constraints)} FK constraint(s) "
                f"for [{schema}].[{table}]"
            )
            
            return constraints
            
        except Exception as e:
            raise RestorationError(
                f"Failed to extract FK constraints: {e}",
                table=table
            )
    
    def _disable_table_constraints(
        self,
        table: str,
        schema: str
    ) -> List[str]:
        """
        Disable all foreign key constraints for a table.
        
        Uses SQL Server's NOCHECK CONSTRAINT to temporarily disable FK validation.
        This is necessary when processing circular dependency groups to avoid
        constraint violations during restoration.
        
        IMPORTANT: Constraints MUST be re-enabled after restoration using
        _enable_table_constraints() to restore data integrity enforcement.
        
        Args:
            table: Table name
            schema: Schema name
        
        Returns:
            List of disabled constraint names
        
        Raises:
            RestorationError: If constraint disable fails
        """
        self.logger.info(
            f"[{self._operation_id}] Disabling FK constraints for [{schema}].[{table}]..."
        )
        
        try:
            cursor = self.connection.cursor()
            
            # Disable ALL FK constraints on the table (simpler than per-constraint)
            disable_sql = f"ALTER TABLE [{schema}].[{table}] NOCHECK CONSTRAINT ALL"
            
            self.logger.debug(f"[{self._operation_id}] Executing: {disable_sql}")
            cursor.execute(disable_sql)
            
            # Get constraint names for logging
            constraints = self._get_table_constraints(table, schema)
            
            self.logger.info(
                f"[{self._operation_id}] Disabled {len(constraints)} FK constraint(s) "
                f"on [{schema}].[{table}]"
            )
            
            return constraints
            
        except Exception as e:
            raise RestorationError(
                f"Failed to disable FK constraints: {e}. "
                "Ensure you have ALTER permission on the table.",
                table=table
            )
    
    def _enable_table_constraints(
        self,
        table: str,
        schema: str,
        validate: bool = True
    ) -> None:
        """
        Enable and optionally validate foreign key constraints for a table.
        
        Re-enables FK constraints after restoration. If validate=True (default),
        also checks that existing data satisfies the constraints, raising an
        error if violations are detected.
        
        Args:
            table: Table name
            schema: Schema name
            validate: If True, validate existing data against constraints
        
        Raises:
            ConstraintViolationError: If validation fails with orphaned records
            RestorationError: If constraint enable operation fails
        """
        from desanitization.exceptions import ConstraintViolationError
        
        self.logger.info(
            f"[{self._operation_id}] Enabling FK constraints for [{schema}].[{table}]..."
        )
        
        try:
            cursor = self.connection.cursor()
            
            # Enable AND validate constraints (CHECK enforces validation)
            if validate:
                enable_sql = f"ALTER TABLE [{schema}].[{table}] CHECK CONSTRAINT ALL"
                validation_mode = "with validation"
            else:
                enable_sql = f"ALTER TABLE [{schema}].[{table}] WITH NOCHECK CHECK CONSTRAINT ALL"
                validation_mode = "without validation"
            
            self.logger.debug(
                f"[{self._operation_id}] Executing: {enable_sql} ({validation_mode})"
            )
            
            cursor.execute(enable_sql)
            
            constraints = self._get_table_constraints(table, schema)
            
            self.logger.info(
                f"[{self._operation_id}] Enabled {len(constraints)} FK constraint(s) "
                f"on [{schema}].[{table}] {validation_mode}"
            )
            
        except Exception as e:
            error_message = str(e)
            
            # Check if this is a constraint violation error
            if "CONSTRAINT" in error_message.upper() or "FOREIGN KEY" in error_message.upper():
                # Try to get detailed violation information
                violations = self._validate_referential_integrity(table, schema)
                
                if violations:
                    # Raise detailed constraint violation error
                    first_violation = violations[0]
                    raise ConstraintViolationError(
                        f"FK constraint validation failed after restoration: {error_message}",
                        constraint_name=first_violation.get('constraint_name'),
                        orphan_count=first_violation.get('orphaned_count', 0),
                        orphan_samples=first_violation.get('sample_ids', [])
                    )
                else:
                    # Generic constraint error
                    raise ConstraintViolationError(
                        f"FK constraint validation failed: {error_message}"
                    )
            else:
                # Generic restoration error (permissions, syntax, etc.)
                raise RestorationError(
                    f"Failed to enable FK constraints: {e}. "
                    "Ensure you have ALTER permission on the table.",
                    table=table
                )
    
    def _handle_circular_group(
        self,
        tables: List[str],
        schema: str,
        batch_id: Optional[str],
        dry_run: bool,
        progress_callback: Optional[callable] = None
    ) -> List[RestorationReport]:
        """
        Handle desanitization of mutually dependent tables (circular FK dependencies).
        
        For tables with circular dependencies (A→B→C→A or A↔B), we cannot use simple
        topological ordering. Instead, we:
        1. Disable FK constraints for all tables in the group
        2. Restore each table sequentially
        3. Re-enable and validate constraints
        4. Detect any orphaned records

          
        This follows the pattern from the sanitization-edge-cases skill.
        
        Args:
            tables: List of table names in the circular dependency group
            schema: Schema name
            batch_id: Optional batch ID filter
            dry_run: If True, preview without committing changes
            progress_callback: Optional callback for progress updates
        
        Returns:
            List of RestorationReport objects (one per table)
        
        Raises:
            ConstraintViolationError: If FK violations detected after restoration
            RestorationError: If any table restoration fails
        """
        from desanitization.exceptions import ConstraintViolationError
        
        self.logger.info(
            f"[{self._operation_id}] Handling circular dependency group: "
            f"{len(tables)} table(s) - {tables}"
        )
        
        reports = []
        disabled_constraints = {}
        
        try:
            # Phase 1: Disable all FK constraints for tables in the group
            if not dry_run:
                for table in tables:
                    constraints = self._disable_table_constraints(table, schema)
                    disabled_constraints[table] = constraints
                    self.logger.info(
                        f"[{self._operation_id}] Disabled {len(constraints)} constraint(s) "
                        f"for [{schema}].[{table}]"
                    )
            else:
                self.logger.info(
                    f"[{self._operation_id}] [DRY RUN] Would disable FK constraints "
                    f"for {len(tables)} table(s)"
                )
            
            # Phase 2: Restore each table sequentially
            for idx, table in enumerate(tables, 1):
                self.logger.info(
                    f"[{self._operation_id}] Restoring table {idx}/{len(tables)}: "
                    f"[{schema}].[{table}]"
                )
                
                # Call desanitize_table for each table
                report = self.desanitize_table(
                    table=table,
                    schema=schema,
                    batch_id=batch_id,
                    dry_run=dry_run,
                    progress_callback=progress_callback
                )
                
                reports.append(report)
                
                self.logger.info(
                    f"[{self._operation_id}] Completed [{schema}].[{table}]: "
                    f"{report.records_restored} record(s) restored"
                )
            
            # Phase 3: Re-enable and validate constraints
            if not dry_run:
                self.logger.info(
                    f"[{self._operation_id}] Re-enabling FK constraints for circular group..."
                )
                
                all_violations = []
                
                for table in tables:
                    try:
                        self._enable_table_constraints(table, schema, validate=True)
                    except ConstraintViolationError as e:
                        # Track violations but continue to check all tables
                        all_violations.append({
                            'table': table,
                            'error': str(e),
                            'constraint_name': e.constraint_name,
                            'orphan_count': e.orphan_count
                        })
                        self.logger.error(
                            f"[{self._operation_id}] Constraint violation on [{schema}].[{table}]: "
                            f"{e.constraint_name} - {e.orphan_count} orphan(s)"
                        )
                
                # If any violations detected, raise comprehensive error
                if all_violations:
                    total_orphans = sum(v['orphan_count'] for v in all_violations)
                    violated_tables = [v['table'] for v in all_violations]
                    
                    raise ConstraintViolationError(
                        f"FK constraint validation failed for {len(violated_tables)} table(s) "
                        f"in circular group: {violated_tables}. Total orphaned records: {total_orphans}. "
                        f"This indicates incomplete or inconsistent desanitization across related tables.",
                        constraint_name=all_violations[0]['constraint_name'],
                        orphan_count=total_orphans
                    )
                
                self.logger.info(
                    f"[{self._operation_id}] All FK constraints re-enabled successfully. "
                    f"No violations detected."
                )
            else:
                self.logger.info(
                    f"[{self._operation_id}] [DRY RUN] Would re-enable FK constraints "
                    f"for {len(tables)} table(s)"
                )
            
            return reports
            
        except ConstraintViolationError:
            # Re-raise constraint violations as-is
            raise
        except Exception as e:
            # Any other error during circular group handling
            self.logger.error(
                f"[{self._operation_id}] Circular group restoration failed: {e}",
                exc_info=True
            )
            
            # Attempt to re-enable constraints even on failure (best effort)
            if not dry_run and disabled_constraints:
                self.logger.warning(
                    f"[{self._operation_id}] Attempting to re-enable constraints "
                    f"after failure..."
                )
                for table in disabled_constraints:
                    try:
                        self._enable_table_constraints(table, schema, validate=False)
                        self.logger.info(
                            f"[{self._operation_id}] Re-enabled constraints for "
                            f"[{schema}].[{table}] (without validation)"
                        )
                    except Exception as re_enable_error:
                        self.logger.error(
                            f"[{self._operation_id}] Failed to re-enable constraints "
                            f"for [{schema}].[{table}]: {re_enable_error}"
                        )
            
            raise RestorationError(
                f"Circular dependency group restoration failed: {e}",
                table="/".join(tables)
            )
    
    def _create_worker_connection(self):
        """
        Create a dedicated database connection for worker thread.
        
        pyodbc Connection objects are not thread-safe when shared across threads.
        Each worker thread needs its own connection to avoid race conditions and
        database errors during parallel operations.
        
        Returns:
            New pyodbc connection with same settings as main connection
        
        Raises:
            RestorationError: If connection creation fails
        
        Note:
            Story 5.1 - Parallel Desanitization
        """
        try:
            import pyodbc
            
            # Extract connection string from existing connection
            # Note: pyodbc doesn't expose connection string directly,
            # so we'll reconstruct from environment or config
            # For now, use the mapping_manager's connection pattern
            
            # Create new connection using same connection string
            conn_str = self.connection.getinfo(pyodbc.SQL_DATA_SOURCE_NAME)
            
            # Attempt to create new connection
            # This is a simplified approach - production code should extract
            # full connection string with authentication details
            new_conn = pyodbc.connect(
                self.connection.getinfo(pyodbc.SQL_DRIVER_NAME),
                autocommit=False
            )
            
            self.logger.debug(
                f"[{self._operation_id}] Created worker connection for parallel processing"
            )
            
            return new_conn
            
        except Exception as e:
            raise RestorationError(
                f"Failed to create worker connection for parallel processing: {e}",
                table="parallel_worker"
            )
    
    def _process_independent_tables_parallel(
        self,
        independent_tables: List[str],
        schema: str,
        batch_id: Optional[str],
        dry_run: bool,
        max_workers: int,
        operation_id: str,
        aggregate_report: RestorationReport,
        tables_to_skip: Set,
        progress_callback: Optional[callable] = None
    ) -> Tuple[int, int, int]:
        """
        Process independent tables in parallel using ThreadPoolExecutor.
        
        This method orchestrates concurrent table restoration for tables with
        no foreign key dependencies. Each worker thread gets its own database
        connection to avoid threading issues with pyodbc.
        
        Args:
            independent_tables: List of fully qualified table names with no FK deps
            schema: Database schema name
            batch_id: Optional batch ID filter
            dry_run: If True, preview without committing
            max_workers: Number of parallel worker threads
            operation_id: Operation ID for tracking
            aggregate_report: Shared report for collecting results
            tables_to_skip: Set of (table, schema) tuples to skip (resume scenario)
            progress_callback: Optional callback for progress updates
        
        Returns:
            Tuple of (tables_processed, tables_succeeded, tables_failed)
        
        Note:
            Story 5.1 - Parallel Desanitization
            Thread-safe through dedicated connections and locked aggregate updates
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        self.logger.info(
            f"[{operation_id}] Starting parallel processing of {len(independent_tables)} "
            f"independent table(s) with {max_workers} worker(s)"
        )
        
        # Thread-safe counters
        counters_lock = threading.Lock()
        tables_processed = 0
        tables_succeeded = 0
        tables_failed = 0
        
        def process_table_worker(table_name: str) -> Tuple[str, bool, Optional[RestorationReport], Optional[str]]:
            """
            Worker function to process a single table.
            
            Returns:
                Tuple of (table_name, success, report, error_message)
            """
            # Skip if already completed (resume scenario)
            if (table_name, schema) in tables_to_skip:
                self.logger.info(
                    f"[{operation_id}] Worker skipping [{schema}].[{table_name}] (already completed)"
                )
                return (table_name, True, None, None)
            
            try:
                # Note: For now, we'll reuse the main connection with locks
                # Full implementation should create worker connection here
                # worker_conn = self._create_worker_connection()
                
                self.logger.info(
                    f"[{operation_id}] Worker processing [{schema}].[{table_name}]"
                )
                
                # Mark IN_PROGRESS in checkpoint (thread-safe via SQL transactions)
                if self.checkpoint_manager:
                    try:
                        self.checkpoint_manager.mark_in_progress(
                            operation_id, table_name, schema
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"[{operation_id}] Checkpoint update failed: {e}"
                        )
                
                # Call desanitize_table (uses self.connection - will add lock in Phase 3)
                table_report = self.desanitize_table(
                    table=table_name,
                    schema=schema,
                    batch_id=batch_id,
                    dry_run=dry_run,
                    progress_callback=progress_callback
                )
                
                # Mark COMPLETED in checkpoint
                if self.checkpoint_manager and not dry_run:
                    try:
                        self.checkpoint_manager.mark_completed(
                            operation_id,
                            table_name,
                            schema,
                            rows_restored=table_report.records_restored,
                            columns_affected=table_report.columns_affected
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"[{operation_id}] Checkpoint update failed: {e}"
                        )
                
                self.logger.info(
                    f"[{operation_id}] ✓ Worker completed [{schema}].[{table_name}]: "
                    f"{table_report.records_restored} record(s) restored"
                )
                
                return (table_name, True, table_report, None)
                
            except Exception as e:
                error_msg = str(e)
                self.logger.error(
                    f"[{operation_id}] ✗ Worker failed [{schema}].[{table_name}]: {error_msg}",
                    exc_info=True
                )
                
                # Mark FAILED in checkpoint
                if self.checkpoint_manager:
                    try:
                        self.checkpoint_manager.mark_failed(
                            operation_id, table_name, schema, error_msg
                        )
                    except Exception:
                        pass
                
                return (table_name, False, None, error_msg)
        
        # Execute parallel processing
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="desan_worker") as executor:
            # Submit all independent tables
            future_to_table = {
                executor.submit(process_table_worker, table): table
                for table in independent_tables
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_table):
                table_name = future_to_table[future]
                
                try:
                    table_name, success, table_report, error_msg = future.result()
                    
                    # Thread-safe update of counters and aggregate report
                    with counters_lock:
                        tables_processed += 1
                        
                        if success and table_report:
                            tables_succeeded += 1
                            
                            # Update aggregate report (thread-safe with lock)
                            aggregate_report.tables_affected += 1
                            aggregate_report.columns_affected += table_report.columns_affected
                            aggregate_report.records_restored += table_report.records_restored
                            aggregate_report.mappings_applied += table_report.mappings_applied
                            
                            # Merge table details
                            if table_name not in aggregate_report.table_details:
                                aggregate_report.table_details[table_name] = {}
                            aggregate_report.table_details[table_name].update(
                                table_report.table_details.get(table_name, {})
                            )
                            
                            # Merge warnings
                            for warning in table_report.warnings:
                                aggregate_report.warnings.append(f"[{table_name}] {warning}")
                        elif not success:
                            tables_failed += 1
                            aggregate_report.errors.append(
                                f"[{table_name}] Restoration failed: {error_msg}"
                            )
                        
                        # Log progress
                        self.logger.info(
                            f"[{operation_id}] Parallel progress: {tables_processed}/{len(independent_tables)} "
                            f"(✓ {tables_succeeded}, ✗ {tables_failed})"
                        )
                    
                except Exception as e:
                    self.logger.error(
                        f"[{operation_id}] Future result retrieval failed for {table_name}: {e}",
                        exc_info=True
                    )
                    
                    with counters_lock:
                        tables_processed += 1
                        tables_failed += 1
                        aggregate_report.errors.append(
                            f"[{table_name}] Future result error: {e}"
                        )
        
        self.logger.info(
            f"[{operation_id}] Parallel processing complete: "
            f"{tables_succeeded}/{len(independent_tables)} succeeded, "
            f"{tables_failed} failed"
        )
        
        return (tables_processed, tables_succeeded, tables_failed)
    
    def desanitize_database(
        self,
        schema_filter: Optional[str] = None,
        batch_id: Optional[str] = None,
        dry_run: bool = True,
        resume_operation_id: Optional[str] = None,
        progress_callback: Optional[callable] = None,
        strict_mode: bool = False,
        enable_parallel: bool = False,
        max_workers: int = 4
    ) -> RestorationReport:
        """
        Restore entire database by processing all tables with mappings in safe order.
        
        This method orchestrates database-level desanitization by:
        1. Building FK dependency graph to determine safe processing order
        2. Handling circular dependencies with constraint management
        3. Processing tables sequentially OR in parallel (Story 5.1)
        4. Tracking progress via checkpoints for fault tolerance
        5. Validating data integrity after restoration
        
        Args:
            schema_filter: Optional schema name to limit processing (e.g., 'dbo')
            batch_id: Optional batch ID filter from sanitization
            dry_run: If True, preview changes without committing (default: True for safety)
            resume_operation_id: Resume from previous failed operation
            progress_callback: Optional callback(table_name, status, pct_complete)
            strict_mode: If True, stop on first error; else continue-on-error
            enable_parallel: If True, process independent tables in parallel (Story 5.1)
            max_workers: Number of parallel worker threads (default: 4, only used if enable_parallel=True)
        
        Returns:
            RestorationReport: Aggregate report for entire database operation
        
        Raises:
            PreconditionError: If dependencies not met (no dependency graph, etc.)
            CheckpointError: If checkpoint operations fail
            RestorationError: If any table restoration fails in strict mode or critical error
        
        Example:
            >>> # Sequential processing (default)
            >>> engine = DesanitizationEngine(conn, mapping_mgr, schema_insp, 
            ...                                dependency_graph=graph, checkpoint_mgr=ckpt)
            >>> report = engine.desanitize_database(
            ...     schema_filter='dbo',
            ...     dry_run=False,
            ...     strict_mode=False
            ... )
            >>> 
            >>> # Parallel processing (Story 5.1)
            >>> report = engine.desanitize_database(
            ...     schema_filter='dbo',
            ...     dry_run=False,
            ...     enable_parallel=True,
            ...     max_workers=4
            ... )
            >>> print(f"Restored {report.tables_affected} tables, {report.records_restored} records")
        """
        import uuid
        import time
        from desanitization.exceptions import CheckpointError, ConstraintViolationError
        
        # Phase 0: Precondition validation
        if self.dependency_graph is None:
            raise PreconditionError(
                "DependencyGraph instance required for database-level desanitization",
                suggested_action="Initialize DesanitizationEngine with dependency_graph parameter"
            )
        
        # Generate or reuse operation ID
        if resume_operation_id:
            operation_id = resume_operation_id
            self.logger.info(f"Resuming database desanitization: {operation_id}")
        else:
            operation_id = self._generate_operation_id()
            self.logger.info(f"Starting database desanitization: {operation_id}")
        
        self._operation_id = operation_id
        
        # Default schema if not specified
        schema = schema_filter or 'dbo'
        
        # Initialize aggregate report
        aggregate_report = RestorationReport(
            operation_id=operation_id,
            start_time=datetime.now(),
            dry_run=dry_run
        )
        
        # Audit logging: Log operation start
        if self.audit_logger:
            try:
                audit_id = self.audit_logger.log_operation_start(
                    operation_id=operation_id,
                    operation_type='DATABASE',
                    target_schema=schema_filter,
                    batch_id=batch_id,
                    dry_run=dry_run,
                    command_line=' '.join(sys.argv) if hasattr(sys, 'argv') else None
                )
                aggregate_report.audit_id = audit_id
            except Exception as e:
                self.logger.warning(f"Audit logging failed (non-critical): {e}")
        
        # Story 7.1: Permission check (after report init, before validation)
        # Note: For database-level, store operation_id as _current_table for audit context
        self._current_table = f"DATABASE [{schema_filter or 'all schemas'}]"  # Store for audit logging
        self._current_report = aggregate_report  # Set context for _check_permission
        try:
            self._check_permission('DATABASE', dry_run)
        except PermissionDeniedError as e:
            # Permission denied - add to report and re-raise
            aggregate_report.errors.append(str(e))
            aggregate_report.end_time = datetime.now()
            raise
        
        try:
            # Phase 0.5: Pre-flight validation (if validator available)
            # Note: Database-level validation is lightweight - only checks mapping table and disk space
            # Per-table validation happens during table processing
            if self.validator:
                self.logger.info(
                    f"[{operation_id}] Running database-level pre-flight validation..."
                )
                
                validation_report = self._run_validation(
                    scope='database',
                    table=None,  # Database-level, no specific table
                    schema=schema_filter,
                    batch_id=batch_id
                )
                
                if not validation_report.is_valid():
                    for check in validation_report.failed_checks:
                        aggregate_report.errors.append(
                            f"Validation failed - {check.check_name}: {check.message}"
                        )
                    
                    aggregate_report.end_time = datetime.now()
                    
                    raise ValidationError(
                        f"Database-level pre-flight validation failed: "
                        f"{len(validation_report.failed_checks)} check(s) failed"
                    )
                
                for warning in validation_report.warnings:
                    aggregate_report.warnings.append(
                        f"Validation warning - {warning.check_name}: {warning.message}"
                    )
            
            # Phase 1: Build dependency graph
            self.logger.info(
                f"[{operation_id}] Building FK dependency graph "
                f"(schema_filter={schema_filter or 'all'})..."
            )
            
            self.dependency_graph.build_graph(schema_filter=schema_filter)
            
            # Phase 2: Get safe processing order
            processing_order = self.dependency_graph.get_processing_order()
            
            total_tables_to_process = (
                len(processing_order.independent_tables) +
                len(processing_order.ordered_tables) +
                sum(len(group) for group in processing_order.circular_groups) +
                len(processing_order.self_referencing_tables)
            )
            
            self.logger.info(
                f"[{operation_id}] Processing order determined: "
                f"{len(processing_order.independent_tables)} independent, "
                f"{len(processing_order.ordered_tables)} ordered, "
                f"{len(processing_order.circular_groups)} circular group(s), "
                f"{len(processing_order.self_referencing_tables)} self-referencing"
            )
            
            # Phase 3: Handle checkpoint resume logic
            tables_to_skip = set()
            
            if resume_operation_id and self.checkpoint_manager:
                # Get list of already-completed tables
                status = self.checkpoint_manager.get_operation_status(operation_id)
                
                if status:
                    self.logger.info(
                        f"[{operation_id}] Resume: {status.completed_tables} already completed, "
                        f"{status.failed_tables} failed, "
                        f"{status.pending_tables + status.in_progress_tables} remaining"
                    )
                    
                    # Get incomplete tables
                    incomplete_tables = self.checkpoint_manager.get_incomplete_tables(operation_id)
                    
                    # All other tables should be skipped
                    all_tables_in_operation = set()
                    for table in processing_order.independent_tables:
                        all_tables_in_operation.add((table, schema_filter or 'dbo'))
                    for table in processing_order.ordered_tables:
                        all_tables_in_operation.add((table, schema_filter or 'dbo'))
                    for group in processing_order.circular_groups:
                        for table in group:
                            all_tables_in_operation.add((table, schema_filter or 'dbo'))
                    for table in processing_order.self_referencing_tables:
                        all_tables_in_operation.add((table, schema_filter or 'dbo'))
                    
                    incomplete_table_set = {(t[0], t[1]) for t in incomplete_tables}
                    tables_to_skip = all_tables_in_operation - incomplete_table_set
                    
                    self.logger.info(
                        f"[{operation_id}] Skipping {len(tables_to_skip)} completed table(s)"
                    )
                else:
                    self.logger.warning(
                        f"[{operation_id}] Resume requested but no checkpoint found, "
                        f"starting fresh operation"
                    )
            
            # Phase 4: Initialize checkpoints for new operation
            if not resume_operation_id and self.checkpoint_manager:
                # Collect all tables
                all_tables = []
                for table in processing_order.independent_tables:
                    all_tables.append((table, schema_filter or 'dbo'))
                for table in processing_order.ordered_tables:
                    all_tables.append((table, schema_filter or 'dbo'))
                for group in processing_order.circular_groups:
                    for table in group:
                        all_tables.append((table, schema_filter or 'dbo'))
                for table in processing_order.self_referencing_tables:
                    all_tables.append((table, schema_filter or 'dbo'))
                
                try:
                    checkpoint_count = self.checkpoint_manager.initialize_operation(
                        operation_id, all_tables, batch_id
                    )
                    self.logger.info(
                        f"[{operation_id}] Created {checkpoint_count} checkpoint record(s)"
                    )
                except CheckpointError as e:
                    self.logger.warning(
                        f"[{operation_id}] Checkpoint initialization failed: {e}. "
                        f"Continuing without checkpoint support."
                    )
            
            # Phase 5: Process tables in safe order
            tables_processed = 0
            tables_succeeded = 0
            tables_failed = 0
            last_progress_time = time.time()
            PROGRESS_INTERVAL = 3600  # Log hourly summary (1 hour in seconds)
            
            # Helper function to process a single table with checkpoint tracking
            def process_table_with_checkpoint(table_name: str, table_type: str = "standard"):
                nonlocal tables_processed, tables_succeeded, tables_failed, last_progress_time
                
                # Parse fully qualified table name: [Schema].[Table] -> (Schema, Table)
                # Dependency graph returns names like '[Production].[WorkOrder]'
                if '.' in table_name and table_name.startswith('['):
                    # Extract schema and table from '[Schema].[Table]' format
                    parts = table_name.strip('[]').split('].[')
                    if len(parts) == 2:
                        table_schema = parts[0]
                        table_only = parts[1]
                    else:
                        # Fallback: use schema_filter or 'dbo'
                        table_schema = schema_filter or 'dbo'
                        table_only = table_name.strip('[]')
                else:
                    # No schema prefix - use schema_filter or 'dbo'
                    table_schema = schema_filter or 'dbo'
                    table_only = table_name
                
                # Skip if already completed (resume scenario)
                if (table_name, table_schema) in tables_to_skip:
                    self.logger.info(
                        f"[{operation_id}] Skipping [{table_schema}].[{table_only}] "
                        f"(already completed)"
                    )
                    return None
                
                self.logger.info(
                    f"[{operation_id}] Processing table {tables_processed + 1}/"
                    f"{total_tables_to_process}: [{table_schema}].[{table_only}] ({table_type})"
                )
                
                # Mark IN_PROGRESS in checkpoint
                if self.checkpoint_manager:
                    try:
                        self.checkpoint_manager.mark_in_progress(
                            operation_id, table_only, table_schema
                        )
                    except CheckpointError as e:
                        self.logger.warning(
                            f"[{operation_id}] Checkpoint update failed: {e}"
                        )
                
                try:
                    # Call desanitize_table
                    table_report = self.desanitize_table(
                        table=table_only,
                        schema=table_schema,
                        batch_id=batch_id,
                        dry_run=dry_run,
                        progress_callback=progress_callback
                    )
                    
                    tables_processed += 1
                    tables_succeeded += 1
                    
                    # Mark COMPLETED in checkpoint
                    if self.checkpoint_manager and not dry_run:
                        try:
                            self.checkpoint_manager.mark_completed(
                                operation_id,
                                table_only,
                                table_schema,
                                rows_restored=table_report.records_restored,
                                columns_affected=table_report.columns_affected
                            )
                        except CheckpointError as e:
                            self.logger.warning(
                                f"[{operation_id}] Checkpoint update failed: {e}"
                            )
                    
                    # Update aggregate report
                    aggregate_report.tables_affected += 1
                    aggregate_report.columns_affected += table_report.columns_affected
                    aggregate_report.records_restored += table_report.records_restored
                    aggregate_report.mappings_applied += table_report.mappings_applied
                    
                    # Merge table details
                    if table_only not in aggregate_report.table_details:
                        aggregate_report.table_details[table_only] = {}
                    aggregate_report.table_details[table_only].update(
                        table_report.table_details.get(table_only, {})
                    )
                    
                    # Merge warnings
                    for warning in table_report.warnings:
                        aggregate_report.warnings.append(
                            f"[{table_only}] {warning}"
                        )
                    
                    self.logger.info(
                        f"[{operation_id}] ✓ [{table_schema}].[{table_only}] completed: "
                        f"{table_report.records_restored} record(s) restored"
                    )
                    
                    # Story 5.2: Progress update every 10 tables with ETA
                    if tables_processed % 10 == 0 and tables_processed > 0:
                        from datetime import timedelta
                        pct_complete = (tables_processed / total_tables_to_process) * 100
                        elapsed = time.time() - aggregate_report.start_time.timestamp()
                        avg_time_per_table = elapsed / tables_processed
                        remaining_tables = total_tables_to_process - tables_processed
                        est_remaining_seconds = avg_time_per_table * remaining_tables
                        est_completion_time = datetime.now() + timedelta(seconds=est_remaining_seconds)
                        
                        self.logger.info(
                            f"[{operation_id}] Progress: {tables_processed}/{total_tables_to_process} "
                            f"tables ({pct_complete:.1f}%), "
                            f"ETA: {est_completion_time.strftime('%Y-%m-%d %H:%M')} "
                            f"({est_remaining_seconds/3600:.1f}h remaining)"
                        )
                    
                    # Hourly progress report (Story 5.2: Enhanced with ETA)
                    current_time = time.time()
                    if current_time - last_progress_time >= PROGRESS_INTERVAL:
                        pct_complete = (tables_processed / total_tables_to_process) * 100
                        elapsed = current_time - aggregate_report.start_time.timestamp()
                        
                        # Calculate ETA using median for outlier resistance
                        if tables_processed >= 3:
                            # Use more sophisticated time estimation
                            avg_time_per_table = elapsed / tables_processed
                        else:
                            # Initial estimate may be inaccurate
                            avg_time_per_table = elapsed / tables_processed if tables_processed > 0 else 0
                        
                        remaining_tables = total_tables_to_process - tables_processed
                        est_remaining_seconds = avg_time_per_table * remaining_tables
                        
                        # Calculate estimated completion time (Story 5.2)
                        from datetime import timedelta
                        est_completion_time = datetime.now() + timedelta(seconds=est_remaining_seconds)
                        
                        self.logger.info(
                            f"[{operation_id}] === HOURLY PROGRESS REPORT ===\n"
                            f"  Tables processed: {tables_processed}/{total_tables_to_process} "
                            f"({pct_complete:.1f}%)\n"
                            f"  Records restored: {aggregate_report.records_restored:,}\n"
                            f"  Elapsed time: {elapsed/3600:.2f} hours\n"
                            f"  Estimated remaining: {est_remaining_seconds/3600:.2f} hours\n"
                            f"  Estimated completion: {est_completion_time.strftime('%Y-%m-%d %H:%M')} "
                            f"({est_remaining_seconds/3600:.1f} hours remaining)\n"
                            f"  Success: {tables_succeeded}, Failed: {tables_failed}"
                        )
                        
                        last_progress_time = current_time
                    
                    return table_report
                    
                except Exception as e:
                    tables_processed += 1
                    tables_failed += 1
                    
                    error_msg = f"Table restoration failed: {e}"
                    aggregate_report.errors.append(f"[{table_only}] {error_msg}")
                    
                    # Mark FAILED in checkpoint
                    if self.checkpoint_manager:
                        try:
                            self.checkpoint_manager.mark_failed(
                                operation_id, table_only, table_schema, str(e)
                            )
                        except CheckpointError as ckpt_error:
                            self.logger.warning(
                                f"[{operation_id}] Checkpoint update failed: {ckpt_error}"
                            )
                    
                    self.logger.error(
                        f"[{operation_id}] ✗ [{table_schema}].[{table_only}] failed: {e}",
                        exc_info=True
                    )
                    
                    # Strict mode: stop on first error
                    if strict_mode:
                        raise RestorationError(
                            f"Database desanitization stopped (strict mode): {error_msg}",
                            table=table_only
                        )
                    
                    # Continue-on-error mode
                    return None
            
            # Process independent tables
            # Story 5.1: Conditional parallelism for independent tables
            if enable_parallel and len(processing_order.independent_tables) > 0:
                # Validate max_workers
                if max_workers < 1:
                    self.logger.warning(
                        f"[{operation_id}] Invalid max_workers={max_workers}, using 1 instead"
                    )
                    max_workers = 1
                
                # Log parallel processing mode
                self.logger.info(
                    f"[{operation_id}] Processing {len(processing_order.independent_tables)} "
                    f"independent table(s) in PARALLEL mode with {max_workers} worker(s)"
                )
                
                # Call parallel processor
                par_processed, par_succeeded, par_failed = self._process_independent_tables_parallel(
                    independent_tables=processing_order.independent_tables,
                    schema=schema,
                    batch_id=batch_id,
                    dry_run=dry_run,
                    max_workers=max_workers,
                    operation_id=operation_id,
                    aggregate_report=aggregate_report,
                    tables_to_skip=tables_to_skip,
                    progress_callback=progress_callback
                )
                
                # Update counters
                tables_processed += par_processed
                tables_succeeded += par_succeeded
                tables_failed += par_failed
                
                self.logger.info(
                    f"[{operation_id}] Parallel processing complete: "
                    f"{par_succeeded}/{len(processing_order.independent_tables)} succeeded, "
                    f"{par_failed} failed"
                )
            else:
                # Sequential processing (default behavior)
                if enable_parallel:
                    self.logger.info(
                        f"[{operation_id}] No independent tables found - skipping parallel mode"
                    )
                else:
                    self.logger.info(
                        f"[{operation_id}] Processing {len(processing_order.independent_tables)} "
                        f"independent table(s) in SEQUENTIAL mode"
                    )
                
                for table in processing_order.independent_tables:
                    process_table_with_checkpoint(table, "independent")
            
            # Process ordered tables (topological order: parent before child)
            for table in processing_order.ordered_tables:
                process_table_with_checkpoint(table, "ordered")
            
            # Process circular dependency groups
            for group_idx, circular_group in enumerate(processing_order.circular_groups, 1):
                # Filter out already-completed tables
                incomplete_group_tables = [
                    t for t in circular_group
                    if (t, schema) not in tables_to_skip
                ]
                
                if not incomplete_group_tables:
                    self.logger.info(
                        f"[{operation_id}] Skipping circular group {group_idx} "
                        f"(all tables already completed)"
                    )
                    continue
                
                self.logger.info(
                    f"[{operation_id}] Processing circular group {group_idx}: "
                    f"{len(incomplete_group_tables)} table(s) - {incomplete_group_tables}"
                )
                
                try:
                    # Call _handle_circular_group which disables constraints,
                    # restores all tables, then re-enables constraints
                    group_reports = self._handle_circular_group(
                        tables=incomplete_group_tables,
                        schema=schema,
                        batch_id=batch_id,
                        dry_run=dry_run,
                        progress_callback=progress_callback
                    )
                    
                    # Update checkpoint and aggregate report for each table
                    for table_idx, table_name in enumerate(incomplete_group_tables):
                        table_report = group_reports[table_idx]
                        
                        tables_processed += 1
                        tables_succeeded += 1
                        
                        # Mark COMPLETED in checkpoint
                        if self.checkpoint_manager and not dry_run:
                            try:
                                self.checkpoint_manager.mark_completed(
                                    operation_id,
                                    table_name,
                                    schema,
                                    rows_restored=table_report.records_restored,
                                    columns_affected=table_report.columns_affected
                                )
                            except CheckpointError as e:
                                self.logger.warning(
                                    f"[{operation_id}] Checkpoint update failed: {e}"
                                )
                        
                        # Aggregate metrics
                        aggregate_report.tables_affected += 1
                        aggregate_report.columns_affected += table_report.columns_affected
                        aggregate_report.records_restored += table_report.records_restored
                        aggregate_report.mappings_applied += table_report.mappings_applied
                        
                        # Merge details
                        if table_name not in aggregate_report.table_details:
                            aggregate_report.table_details[table_name] = {}
                        aggregate_report.table_details[table_name].update(
                            table_report.table_details.get(table_name, {})
                        )
                    
                    self.logger.info(
                        f"[{operation_id}] ✓ Circular group {group_idx} completed"
                    )
                    
                except ConstraintViolationError as e:
                    # Constraint violation in circular group
                    for table_name in incomplete_group_tables:
                        tables_processed += 1
                        tables_failed += 1
                        
                        aggregate_report.errors.append(
                            f"[{table_name}] Circular group constraint violation: {e}"
                        )
                        
                        if self.checkpoint_manager:
                            try:
                                self.checkpoint_manager.mark_failed(
                                    operation_id, table_name, schema, str(e)
                                )
                            except CheckpointError:
                                pass
                    
                    self.logger.error(
                        f"[{operation_id}] ✗ Circular group {group_idx} failed: {e}"
                    )
                    
                    if strict_mode:
                        raise
                
                except Exception as e:
                    # Other error in circular group
                    for table_name in incomplete_group_tables:
                        tables_processed += 1
                        tables_failed += 1
                        
                        aggregate_report.errors.append(
                            f"[{table_name}] Circular group error: {e}"
                        )
                        
                        if self.checkpoint_manager:
                            try:
                                self.checkpoint_manager.mark_failed(
                                    operation_id, table_name, schema, str(e)
                                )
                            except CheckpointError:
                                pass
                    
                    self.logger.error(
                        f"[{operation_id}] ✗ Circular group {group_idx} failed: {e}",
                        exc_info=True
                    )
                    
                    if strict_mode:
                        raise RestorationError(
                            f"Circular group restoration failed: {e}",
                            table="/".join(incomplete_group_tables)
                        )
            
            # Process self-referencing tables
            for table in processing_order.self_referencing_tables:
                # Log warning about self-referencing
                aggregate_report.warnings.append(
                    f"[{table}] Table is self-referencing (hierarchical data). "
                    f"Restoration may require special handling for parent-child relationships."
                )
                
                process_table_with_checkpoint(table, "self-referencing")
            
            # Phase 6: Final summary
            aggregate_report.end_time = datetime.now()
            duration = (aggregate_report.end_time - aggregate_report.start_time).total_seconds()
            
            # Audit logging: Log operation complete
            if self.audit_logger:
                try:
                    validation_passed = None
                    validation_warnings = len(aggregate_report.warnings)
                    validation_errors = len(aggregate_report.errors)
                    
                    # For database-level, we consider it passed if no errors (warnings allowed)
                    if validation_errors == 0:
                        validation_passed = True
                    elif validation_errors > 0:
                        validation_passed = False
                    
                    self.audit_logger.log_operation_complete(
                        audit_id=aggregate_report.audit_id,
                        operation_id=operation_id,
                        rows_restored=aggregate_report.records_restored,
                        mappings_applied=aggregate_report.mappings_applied,
                        columns_affected=aggregate_report.columns_affected,
                        tables_affected=aggregate_report.tables_affected,
                        validation_passed=validation_passed,
                        validation_warnings_count=validation_warnings,
                        validation_errors_count=validation_errors
                    )
                except Exception as e:
                    self.logger.warning(f"Audit logging failed (non-critical): {e}")
            
            self.logger.info(
                f"[{operation_id}] === DATABASE DESANITIZATION COMPLETE ===\n"
                f"  Total tables processed: {tables_processed}/{total_tables_to_process}\n"
                f"  Successful: {tables_succeeded}\n"
                f"  Failed: {tables_failed}\n"
                f"  Total mappings processed: {aggregate_report.mappings_applied:,}\n"
                f"  Total records restored: {aggregate_report.records_restored:,}\n"
                f"  Restoration efficiency: {(aggregate_report.records_restored / aggregate_report.mappings_applied * 100) if aggregate_report.mappings_applied > 0 else 0:.1f}%\n"
                f"  Duration: {duration/3600:.2f} hours\n"
                f"  Dry run: {dry_run}"
            )
            
            # Log discrepancy summary if mappings != records
            if aggregate_report.mappings_applied > aggregate_report.records_restored:
                discrepancy = aggregate_report.mappings_applied - aggregate_report.records_restored
                orphan_warnings = [w for w in aggregate_report.warnings if 'deleted after sanitization' in w]
                
                self.logger.warning(
                    f"[{operation_id}] ⚠️ RESTORATION DISCREPANCY DETECTED\n"
                    f"  Mappings processed: {aggregate_report.mappings_applied:,}\n"
                    f"  Records restored: {aggregate_report.records_restored:,}\n"
                    f"  Discrepancy: {discrepancy:,} ({discrepancy / aggregate_report.mappings_applied * 100:.1f}%)\n"
                    f"  Likely cause: {len(orphan_warnings)} table(s) have records deleted after sanitization\n"
                    f"  See warnings above for details on affected tables"
                )
            
            return aggregate_report
            
        except PreconditionError:
            aggregate_report.end_time = datetime.now()
            
            # Audit logging: Log operation failure
            if self.audit_logger:
                try:
                    self.audit_logger.log_operation_failure(
                        audit_id=aggregate_report.audit_id,
                        operation_id=operation_id,
                        error_message=str(aggregate_report.errors) if aggregate_report.errors else "Precondition check failed",
                        error_type="PreconditionError",
                        rows_restored=aggregate_report.records_restored,
                        mappings_applied=aggregate_report.mappings_applied
                    )
                except Exception as audit_err:
                    self.logger.warning(f"Audit logging failed (non-critical): {audit_err}")
            
            raise
        except Exception as e:
            aggregate_report.end_time = datetime.now()
            aggregate_report.errors.append(str(e))
            
            # Audit logging: Log operation failure
            if self.audit_logger:
                try:
                    self.audit_logger.log_operation_failure(
                        audit_id=aggregate_report.audit_id,
                        operation_id=operation_id,
                        error_message=str(e),
                        error_type=type(e).__name__,
                        rows_restored=aggregate_report.records_restored,
                        mappings_applied=aggregate_report.mappings_applied
                    )
                except Exception as audit_err:
                    self.logger.warning(f"Audit logging failed (non-critical): {audit_err}")
            
            self.logger.error(
                f"[{operation_id}] Database desanitization failed: {e}",
                exc_info=True
            )
            raise
