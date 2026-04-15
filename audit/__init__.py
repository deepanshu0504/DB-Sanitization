"""
Audit Package - Database Desanitization Audit Logging

This package provides comprehensive audit logging for all desanitization 
operations to meet compliance requirements (GDPR, HIPAA).

Key Components:
- AuditLogger: Main class for logging operations to database
- AuditRecord: Dataclass representing an audit log entry
- Exceptions: Custom exception classes for audit errors

Usage:
    from audit import AuditLogger, AuditRecord
    
    # Initialize logger with database connection
    audit_logger = AuditLogger(connection)
    
    # Log operation start
    audit_id = audit_logger.log_operation_start(
        operation_id='DESAN-20260413...',
        operation_type='RECORD',
        target_table='Customers'
    )
    
    # Log operation completion
    audit_logger.log_operation_complete(
        audit_id=audit_id,
        operation_id='DESAN-20260413...',
        rows_restored=100
    )

Related: User Story 4.1 - Audit Logging for Desanitization
Created: April 13, 2026
"""

from .audit_logger import AuditLogger, AuditRecord
from .exceptions import (
    AuditError,
    AuditTableMissingError,
    AuditInsertError,
    AuditQueryError
)

__all__ = [
    'AuditLogger',
    'AuditRecord',
    'AuditError',
    'AuditTableMissingError',
    'AuditInsertError',
    'AuditQueryError',
]

__version__ = '1.0.0'
