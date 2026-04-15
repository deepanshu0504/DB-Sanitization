"""
AuditLogger - Database Desanitization Audit Logging

Provides comprehensive audit logging for all desanitization operations to meet
compliance requirements (GDPR, HIPAA). Tracks who, what, when, and why for 
every restoration operation.

Features:
- Persistent audit trail in desanitization_audit_log table
- User detection via SQL SYSTEM_USER function
- Graceful degradation (logs to file if DB insert fails)
- JSON serialization for complex fields
- Never fails parent operation due to audit failure

Usage:
    from audit import AuditLogger
    
    audit_logger = AuditLogger(connection)
    audit_id = audit_logger.log_operation_start(
        operation_id='DESAN-20260413123456-a1b2c3d4',
        operation_type='RECORD',
        target_table='Customers',
        target_record_ids=['123', '456'],
        dry_run=False
    )
    
    # ... perform desanitization ...
    
    audit_logger.log_operation_complete(
        audit_id=audit_id,
        operation_id='DESAN-20260413123456-a1b2c3d4',
        rows_restored=2,
        mappings_applied=4
    )

Related: User Story 4.1 - Audit Logging for Desanitization
Created: April 13, 2026
"""

import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field

from .exceptions import AuditError, AuditTableMissingError, AuditInsertError, AuditQueryError


# Configure module logger
logger = logging.getLogger(__name__)


@dataclass
class AuditRecord:
    """
    Immutable audit record representing a desanitization operation.
    
    This dataclass mirrors the desanitization_audit_log table schema.
    """
    # Operation Identification
    operation_id: str
    operation_type: str  # RECORD, COLUMN, TABLE, DATABASE
    
    # Target Identification
    target_schema: Optional[str] = None
    target_table: Optional[str] = None
    target_columns: Optional[List[str]] = None
    target_record_ids: Optional[List[str]] = None
    
    # User & Authorization
    initiated_by: str = ""
    command_line: Optional[str] = None
    
    # Batch Correlation
    batch_id: Optional[str] = None
    sanitization_run_id: Optional[str] = None
    
    # Operation Mode
    dry_run: bool = False
    
    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Status & Results
    status: str = "PENDING"
    rows_restored: int = 0
    mappings_applied: int = 0
    columns_affected: int = 0
    tables_affected: int = 0
    
    # Validation Results
    validation_passed: Optional[bool] = None
    validation_warnings_count: int = 0
    validation_errors_count: int = 0
    
    # Error Details
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    
    # Metadata
    audit_id: Optional[int] = None
    created_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert audit record to dictionary for JSON serialization.
        
        Returns:
            Dictionary representation of audit record
        """
        return {
            'audit_id': self.audit_id,
            'operation_id': self.operation_id,
            'operation_type': self.operation_type,
            'target_schema': self.target_schema,
            'target_table': self.target_table,
            'target_columns': self.target_columns,
            'target_record_ids': self.target_record_ids,
            'initiated_by': self.initiated_by,
            'command_line': self.command_line,
            'batch_id': self.batch_id,
            'sanitization_run_id': self.sanitization_run_id,
            'dry_run': self.dry_run,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'status': self.status,
            'rows_restored': self.rows_restored,
            'mappings_applied': self.mappings_applied,
            'columns_affected': self.columns_affected,
            'tables_affected': self.tables_affected,
            'validation_passed': self.validation_passed,
            'validation_warnings_count': self.validation_warnings_count,
            'validation_errors_count': self.validation_errors_count,
            'error_message': self.error_message,
            'error_type': self.error_type,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AuditLogger:
    """
    Manages audit logging for desanitization operations.
    
    Persists operation metadata to desanitization_audit_log table for compliance
    and security monitoring. Implements graceful degradation pattern - audit
    failures are logged but never fail the parent desanitization operation.
    """
    
    AUDIT_TABLE = "desanitization_audit_log"
    VALID_OPERATION_TYPES = {'RECORD', 'COLUMN', 'TABLE', 'DATABASE'}
    VALID_STATUSES = {'PENDING', 'COMPLETED', 'FAILED', 'ROLLED_BACK', 'PERMISSION_DENIED'}  # Story 7.1: RBAC
    
    def __init__(self, connection, fallback_to_file: bool = True):
        """
        Initialize AuditLogger with database connection.
        
        Args:
            connection: pyodbc connection object
            fallback_to_file: If True, log to file on DB failure (default: True)
        """
        self.connection = connection
        self.fallback_to_file = fallback_to_file
        self._current_user: Optional[str] = None
        
        # Verify audit table exists
        self._verify_audit_table()
    
    def _verify_audit_table(self) -> bool:
        """
        Verify desanitization_audit_log table exists.
        
        Returns:
            True if table exists, raises AuditTableMissingError otherwise
        
        Raises:
            AuditTableMissingError: If audit table doesn't exist
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute(f"""
                SELECT 1 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_NAME = '{self.AUDIT_TABLE}'
            """)
            
            if cursor.fetchone() is None:
                raise AuditTableMissingError()
            
            cursor.close()
            return True
            
        except AuditTableMissingError:
            raise
        except Exception as e:
            logger.warning(
                f"Could not verify audit table existence: {e}. "
                "Audit logging will fallback to file if enabled."
            )
            return False
    
    def _get_current_user(self) -> str:
        """
        Get current database user via SQL SYSTEM_USER function.
        
        Returns:
            Database username (e.g., 'DOMAIN\\username' for Windows Auth,
            'sa' for SQL Server Auth)
        """
        if self._current_user is not None:
            return self._current_user
        
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT SYSTEM_USER")
            row = cursor.fetchone()
            cursor.close()
            
            if row:
                self._current_user = row[0]
                return self._current_user
            else:
                # Fallback to SUSER_SNAME()
                cursor = self.connection.cursor()
                cursor.execute("SELECT SUSER_SNAME()")
                row = cursor.fetchone()
                cursor.close()
                
                self._current_user = row[0] if row else "UNKNOWN"
                return self._current_user
                
        except Exception as e:
            logger.warning(f"Could not detect database user: {e}")
            return "UNKNOWN"
    
    def _serialize_json_field(self, value: Optional[Union[List, Dict]]) -> Optional[str]:
        """
        Serialize list or dict to JSON string for database storage.
        
        Args:
            value: List or dict to serialize
        
        Returns:
            JSON string or None
        """
        if value is None:
            return None
        
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.warning(f"Could not serialize JSON field: {e}")
            return str(value)
    
    def _log_to_file_fallback(self, audit_record: AuditRecord) -> None:
        """
        Fallback logging to file when database insert fails.
        
        Args:
            audit_record: AuditRecord to log
        """
        if not self.fallback_to_file:
            return
        
        try:
            log_entry = (
                f"AUDIT_FALLBACK | {audit_record.operation_id} | "
                f"{audit_record.operation_type} | {audit_record.target_table} | "
                f"{audit_record.status} | {audit_record.initiated_by} | "
                f"{audit_record.started_at}"
            )
            logger.warning(f"Audit DB insert failed, logging to file: {log_entry}")
        except Exception as e:
            logger.error(f"File fallback logging also failed: {e}")
    
    def log_operation_start(
        self,
        operation_id: str,
        operation_type: str,
        target_table: Optional[str] = None,
        target_schema: Optional[str] = None,
        target_columns: Optional[List[str]] = None,
        target_record_ids: Optional[List[str]] = None,
        batch_id: Optional[str] = None,
        sanitization_run_id: Optional[str] = None,
        dry_run: bool = False,
        command_line: Optional[str] = None
    ) -> Optional[int]:
        """
        Log the start of a desanitization operation.
        
        Args:
            operation_id: Unique operation identifier (e.g., DESAN-20260413...)
            operation_type: RECORD, COLUMN, TABLE, or DATABASE
            target_table: Table name (if applicable)
            target_schema: Schema name (default: dbo)
            target_columns: List of column names (for COLUMN operations)
            target_record_ids: List of record IDs (for RECORD operations)
            batch_id: Batch ID from original sanitization
            sanitization_run_id: Sanitization run ID
            dry_run: True if preview mode (no actual changes)
            command_line: Full CLI command for traceability
        
        Returns:
            audit_id (BIGINT) if insert successful, None on failure
        """
        # Validate operation_type
        if operation_type not in self.VALID_OPERATION_TYPES:
            logger.warning(
                f"Invalid operation_type '{operation_type}'. "
                f"Must be one of: {self.VALID_OPERATION_TYPES}"
            )
            return None
        
        # Get current user
        initiated_by = self._get_current_user()
        
        # Create audit record
        audit_record = AuditRecord(
            operation_id=operation_id,
            operation_type=operation_type,
            target_schema=target_schema,
            target_table=target_table,
            target_columns=target_columns,
            target_record_ids=target_record_ids,
            initiated_by=initiated_by,
            command_line=command_line,
            batch_id=batch_id,
            sanitization_run_id=sanitization_run_id,
            dry_run=dry_run,
            started_at=datetime.now(),
            status='PENDING'
        )
        
        # Insert into database
        try:
            cursor = self.connection.cursor()
            
            insert_query = f"""
                INSERT INTO {self.AUDIT_TABLE} (
                    operation_id, operation_type, target_schema, target_table,
                    target_columns, target_record_ids, initiated_by, command_line,
                    batch_id, sanitization_run_id, dry_run, started_at, status
                )
                OUTPUT INSERTED.audit_id
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """
            
            cursor.execute(
                insert_query,
                operation_id,
                operation_type,
                target_schema,
                target_table,
                self._serialize_json_field(target_columns),
                self._serialize_json_field(target_record_ids),
                initiated_by,
                command_line,
                batch_id,
                sanitization_run_id,
                1 if dry_run else 0,
                audit_record.started_at,
                'PENDING'
            )
            
            # Get audit_id from OUTPUT clause
            row = cursor.fetchone()
            audit_id = row[0] if row else None
            
            # Commit immediately for audit independence
            self.connection.commit()
            cursor.close()
            
            logger.debug(f"Audit log created: audit_id={audit_id}, operation_id={operation_id}")
            return audit_id
            
        except Exception as e:
            logger.warning(f"Failed to insert audit log start record: {e}", exc_info=True)
            self._log_to_file_fallback(audit_record)
            return None
    
    def log_operation_complete(
        self,
        audit_id: Optional[int],
        operation_id: str,
        rows_restored: int = 0,
        mappings_applied: int = 0,
        columns_affected: int = 0,
        tables_affected: int = 0,
        validation_passed: Optional[bool] = None,
        validation_warnings_count: int = 0,
        validation_errors_count: int = 0
    ) -> bool:
        """
        Log the successful completion of a desanitization operation.
        
        Args:
            audit_id: Audit ID from log_operation_start (None if start failed)
            operation_id: Operation identifier for fallback lookup
            rows_restored: Total rows affected
            mappings_applied: Total mappings used
            columns_affected: Number of columns restored
            tables_affected: Number of tables restored (DATABASE operations)
            validation_passed: Post-restoration validation result
            validation_warnings_count: Number of validation warnings
            validation_errors_count: Number of validation errors
        
        Returns:
            True if update successful, False otherwise
        """
        if audit_id is None:
            logger.debug(f"Skipping audit log complete (audit_id=None, operation_id={operation_id})")
            return False
        
        try:
            cursor = self.connection.cursor()
            
            update_query = f"""
                UPDATE {self.AUDIT_TABLE}
                SET 
                    status = 'COMPLETED',
                    completed_at = ?,
                    rows_restored = ?,
                    mappings_applied = ?,
                    columns_affected = ?,
                    tables_affected = ?,
                    validation_passed = ?,
                    validation_warnings_count = ?,
                    validation_errors_count = ?
                WHERE audit_id = ?;
            """
            
            cursor.execute(
                update_query,
                datetime.now(),
                rows_restored,
                mappings_applied,
                columns_affected,
                tables_affected,
                validation_passed,
                validation_warnings_count,
                validation_errors_count,
                audit_id
            )
            
            # Commit immediately
            self.connection.commit()
            cursor.close()
            
            logger.debug(f"Audit log completed: audit_id={audit_id}, rows_restored={rows_restored}")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to update audit log completion: {e}", exc_info=True)
            return False
    
    def log_operation_failure(
        self,
        audit_id: Optional[int],
        operation_id: str,
        error_message: str,
        error_type: Optional[str] = None,
        rows_restored: int = 0,
        mappings_applied: int = 0
    ) -> bool:
        """
        Log the failure of a desanitization operation.
        
        Args:
            audit_id: Audit ID from log_operation_start (None if start failed)
            operation_id: Operation identifier for fallback lookup
            error_message: Error description
            error_type: Exception class name (e.g., 'MappingNotFoundError')
            rows_restored: Partial rows affected before failure
            mappings_applied: Partial mappings used before failure
        
        Returns:
            True if update successful, False otherwise
        """
        if audit_id is None:
            logger.debug(f"Skipping audit log failure (audit_id=None, operation_id={operation_id})")
            return False
        
        try:
            cursor = self.connection.cursor()
            
            update_query = f"""
                UPDATE {self.AUDIT_TABLE}
                SET 
                    status = 'FAILED',
                    completed_at = ?,
                    error_message = ?,
                    error_type = ?,
                    rows_restored = ?,
                    mappings_applied = ?
                WHERE audit_id = ?;
            """
            
            cursor.execute(
                update_query,
                datetime.now(),
                error_message[:4000] if error_message else None,  # Truncate if too long
                error_type[:128] if error_type else None,
                rows_restored,
                mappings_applied,
                audit_id
            )
            
            # Commit immediately
            self.connection.commit()
            cursor.close()
            
            logger.debug(f"Audit log failed: audit_id={audit_id}, error_type={error_type}")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to update audit log failure: {e}", exc_info=True)
            return False
    
    def log_permission_denied(
        self,
        operation_id: str,
        operation_type: str,
        target_table: Optional[str] = None,
        required_roles: Optional[List[str]] = None,
        user_roles: Optional[List[str]] = None
    ) -> Optional[int]:
        """
        Log a permission-denied event for security audit trail (Story 7.1).
        
        This method creates an audit record for failed authorization attempts,
        capturing which roles were required and which roles the user actually had.
        
        Args:
            operation_id: Unique operation identifier
            operation_type: RECORD, COLUMN, TABLE, or DATABASE
            target_table: Table user attempted to access (if applicable)
            required_roles: List of roles that would have granted permission
            user_roles: List of roles the current user actually has
        
        Returns:
            audit_id (BIGINT) if insert successful, None on failure
        
        Example:
            >>> audit_logger.log_permission_denied(
            ...     operation_id='DESAN-20260413...',
            ...     operation_type='TABLE',
            ...     target_table='Customers',
            ...     required_roles=['DataRestorer', 'db_owner'],
            ...     user_roles=['db_datareader']
            ... )
        """
        # Get current user
        initiated_by = self._get_current_user()
        
        # Create audit record with PERMISSION_DENIED status
        audit_record = AuditRecord(
            operation_id=operation_id,
            operation_type=operation_type,
            target_table=target_table,
            initiated_by=initiated_by,
            status='PERMISSION_DENIED',
            started_at=datetime.now(),
            completed_at=datetime.now(),  # Immediate denial
            dry_run=False,  # Permission checks apply to both dry-run and execute
            command_line=' '.join(sys.argv) if hasattr(sys, 'argv') else None
        )
        
        try:
            cursor = self.connection.cursor()
            
            insert_query = f"""
                INSERT INTO {self.AUDIT_TABLE} (
                    operation_id, operation_type, target_schema, target_table,
                    target_columns, target_record_ids, initiated_by, command_line,
                    batch_id, sanitization_run_id, dry_run, started_at, completed_at,
                    status, rows_restored, mappings_applied, columns_affected, tables_affected,
                    validation_passed, validation_warnings_count, validation_errors_count,
                    error_message, error_type, required_roles, user_roles
                )
                OUTPUT INSERTED.audit_id
                VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?
                );
            """
            
            # Serialize role lists to JSON for storage
            required_roles_json = self._serialize_json_field(required_roles)
            user_roles_json = self._serialize_json_field(user_roles)
            
            cursor.execute(
                insert_query,
                audit_record.operation_id,
                audit_record.operation_type,
                audit_record.target_schema,
                audit_record.target_table,
                self._serialize_json_field(audit_record.target_columns),
                self._serialize_json_field(audit_record.target_record_ids),
                audit_record.initiated_by,
                audit_record.command_line,
                audit_record.batch_id,
                audit_record.sanitization_run_id,
                audit_record.dry_run,
                audit_record.started_at,
                audit_record.completed_at,
                audit_record.status,
                0,  # rows_restored
                0,  # mappings_applied
                0,  # columns_affected
                0,  # tables_affected
                None,  # validation_passed
                0,  # validation_warnings_count
                0,  # validation_errors_count
                "Permission denied - user lacks required database roles",
                "PermissionDeniedError",
                required_roles_json,
                user_roles_json
            )
            
            # Get the inserted audit_id
            row = cursor.fetchone()
            audit_id = row[0] if row else None
            
            # Commit immediately (permission denied events are critical for security audit)
            self.connection.commit()
            cursor.close()
            
            logger.info(
                f"Permission denied logged to audit: audit_id={audit_id}, "
                f"user={initiated_by}, operation={operation_type}, "
                f"required_roles={required_roles}, user_roles={user_roles}"
            )
            
            return audit_id
            
        except Exception as e:
            logger.warning(f"Failed to log permission denied to audit: {e}", exc_info=True)
            # Graceful degradation - don't fail the application
            return None
    
    def get_audit_history(
        self,
        operation_type: Optional[str] = None,
        target_table: Optional[str] = None,
        initiated_by: Optional[str] = None,
        status: Optional[str] = None,
        days: int = 7,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Query audit log history with filters.
        
        Args:
            operation_type: Filter by operation type (RECORD, COLUMN, TABLE, DATABASE)
            target_table: Filter by table name
            initiated_by: Filter by username
            status: Filter by status (PENDING, COMPLETED, FAILED, ROLLED_BACK)
            days: Number of days to look back (default: 7)
            limit: Maximum records to return (default: 100)
        
        Returns:
            List of audit records as dictionaries
        """
        try:
            cursor = self.connection.cursor()
            
            # Build query with filters
            where_clauses = ["started_at >= DATEADD(DAY, ?, GETDATE())"]
            params = [-days]
            
            if operation_type:
                where_clauses.append("operation_type = ?")
                params.append(operation_type)
            
            if target_table:
                where_clauses.append("target_table = ?")
                params.append(target_table)
            
            if initiated_by:
                where_clauses.append("initiated_by = ?")
                params.append(initiated_by)
            
            if status:
                where_clauses.append("status = ?")
                params.append(status)
            
            where_clause = " AND ".join(where_clauses)
            
            query = f"""
                SELECT TOP (?)
                    audit_id, operation_id, operation_type, target_schema, target_table,
                    target_columns, target_record_ids, initiated_by, command_line,
                    batch_id, sanitization_run_id, dry_run, started_at, completed_at,
                    status, rows_restored, mappings_applied, columns_affected, 
                    tables_affected, validation_passed, validation_warnings_count,
                    validation_errors_count, error_message, error_type, created_at
                FROM {self.AUDIT_TABLE}
                WHERE {where_clause}
                ORDER BY started_at DESC;
            """
            
            params.insert(0, limit)
            cursor.execute(query, *params)
            
            # Fetch results
            columns = [column[0] for column in cursor.description]
            results = []
            
            for row in cursor.fetchall():
                record = dict(zip(columns, row))
                
                # Deserialize JSON fields
                if record.get('target_columns'):
                    try:
                        record['target_columns'] = json.loads(record['target_columns'])
                    except:
                        pass
                
                if record.get('target_record_ids'):
                    try:
                        record['target_record_ids'] = json.loads(record['target_record_ids'])
                    except:
                        pass
                
                results.append(record)
            
            cursor.close()
            return results
            
        except Exception as e:
            logger.error(f"Failed to query audit history: {e}", exc_info=True)
            raise AuditQueryError(f"Audit history query failed: {e}")
    
    def export_audit_logs(
        self,
        output_file: str,
        format: str = 'json',
        **filters
    ) -> int:
        """
        Export audit logs to file.
        
        Args:
            output_file: Path to output file
            format: Output format ('json' or 'csv')
            **filters: Filters to pass to get_audit_history()
        
        Returns:
            Number of records exported
        """
        records = self.get_audit_history(**filters)
        
        if format.lower() == 'json':
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(records, f, indent=2, default=str)
        elif format.lower() == 'csv':
            import csv
            if records:
                with open(output_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=records[0].keys())
                    writer.writeheader()
                    writer.writerows(records)
        else:
            raise ValueError(f"Unsupported format: {format}. Use 'json' or 'csv'.")
        
        logger.info(f"Exported {len(records)} audit records to {output_file}")
        return len(records)
