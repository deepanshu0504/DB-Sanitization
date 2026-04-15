"""
Audit Module Exceptions

Custom exception classes for audit logging operations.
"""


class AuditError(Exception):
    """Base exception for audit-related errors."""
    pass


class AuditTableMissingError(AuditError):
    """Raised when desanitization_audit_log table doesn't exist."""
    
    def __init__(self, message: str = None):
        if message is None:
            message = (
                "Audit log table 'desanitization_audit_log' not found. "
                "Run scripts/create_audit_log_table.sql to create it."
            )
        super().__init__(message)


class AuditInsertError(AuditError):
    """Raised when audit log insert fails."""
    pass


class AuditQueryError(AuditError):
    """Raised when audit log query fails."""
    pass
