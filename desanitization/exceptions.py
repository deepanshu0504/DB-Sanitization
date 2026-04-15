"""
Custom exceptions for desanitization operations.

This module defines a hierarchy of exceptions used throughout the desanitization
framework to provide clear, actionable error messages.

Exception Hierarchy:
    DesanitizationError (base)
    ├── PreconditionError (setup/validation failures)
    ├── MappingNotFoundError (missing mapping data)
    ├── ValidationError (data validation failures)
    ├── RestorationError (update execution failures)
    └── CircularDependencyError (circular FK dependencies detected)
"""


class DesanitizationError(Exception):
    """Base exception for all desanitization-related errors."""
    
    def __init__(self, message: str, suggested_action: str = None):
        """
        Initialize desanitization error.
        
        Args:
            message: Error description
            suggested_action: Optional remediation guidance
        """
        self.message = message
        self.suggested_action = suggested_action
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        """Format error message with optional suggested action."""
        if self.suggested_action:
            return f"{self.message}\nSuggested Action: {self.suggested_action}"
        return self.message


class PreconditionError(DesanitizationError):
    """
    Raised when preconditions for desanitization are not met.
    
    Examples:
        - Mapping table doesn't exist
        - Database connection failed
        - Invalid configuration parameters
    """
    pass


class MappingNotFoundError(DesanitizationError):
    """
    Raised when required mappings are not found in the mapping table.
    
    Examples:
        - Record ID has no mapping (was never sanitized)
        - Mapping data expired or archived
        - Batch ID not found
    """
    
    def __init__(self, message: str, missing_records: list = None):
        """
        Initialize mapping not found error.
        
        Args:
            message: Error description
            missing_records: List of record IDs with no mappings
        """
        self.missing_records = missing_records or []
        suggested_action = (
            "Verify the records were sanitized and mappings captured. "
            "Check if mappings were archived or purged."
        )
        super().__init__(message, suggested_action)


class ValidationError(DesanitizationError):
    """
    Raised when data validation fails during desanitization.
    
    Examples:
        - Row count mismatch after restoration
        - Data type inconsistency
        - Foreign key constraint violation
        - Unexpected NULL values
    """
    pass


class RestorationError(DesanitizationError):
    """
    Raised when database restoration operations fail.
    
    Examples:
        - UPDATE query failed
        - Transaction rollback triggered
        - Insufficient permissions
        - Deadlock detected
    """
    
    def __init__(self, message: str, table: str = None, column: str = None):
        """
        Initialize restoration error.
        
        Args:
            message: Error description
            table: Table name where error occurred
            column: Column name where error occurred
        """
        self.table = table
        self.column = column
        location = f" in [{table}].[{column}]" if table and column else ""
        super().__init__(f"{message}{location}")


class CircularDependencyError(DesanitizationError):
    """
    Raised when circular foreign key dependencies are detected.
    
    Circular dependencies prevent simple topological sorting and require
    special handling (e.g., temporarily disabling constraints during restoration).
    
    Examples:
        - Table A references B, B references C, C references A
        - Self-referencing tables (Employee.ManagerID -> Employee.EmployeeID)
        - Mutual references between two tables
    """
    
    def __init__(self, message: str, cycles: list = None):
        """
        Initialize circular dependency error.
        
        Args:
            message: Error description
            cycles: List of circular dependency chains (e.g., [['A', 'B', 'C', 'A']])
        """
        self.cycles = cycles or []
        
        # Format suggested action based on cycle information
        if self.cycles:
            cycle_str = ", ".join([" → ".join(cycle) for cycle in self.cycles])
            suggested_action = (
                f"Circular dependencies detected: {cycle_str}. "
                "Consider using constraint-aware restoration mode or processing "
                "these tables with temporarily disabled FK constraints."
            )
        else:
            suggested_action = (
                "Circular dependencies detected in the database schema. "
                "Use dependency graph analysis to identify the cycles."
            )
        
        super().__init__(message, suggested_action)


class ConstraintViolationError(DesanitizationError):
    """
    Raised when foreign key or other constraints are violated after restoration.
    
    This typically indicates that the restored data breaks referential integrity,
    which can happen if:
    - Parent records were not sanitized/desanitized properly
    - Orphaned child records exist in the sanitized data
    - Mapping data is inconsistent across related tables
    
    Examples:
        - Child record references non-existent parent after restoration
        - Unique constraint violated by restored values
        - Check constraint failed after value restoration
    """
    
    def __init__(
        self,
        message: str,
        constraint_name: str = None,
        orphan_count: int = 0,
        orphan_samples: list = None
    ):
        """
        Initialize constraint violation error.
        
        Args:
            message: Error description
            constraint_name: Name of the violated constraint
            orphan_count: Number of orphaned records (for FK violations)
            orphan_samples: Sample orphaned record IDs
        """
        self.constraint_name = constraint_name
        self.orphan_count = orphan_count
        self.orphan_samples = orphan_samples or []
        
        # Build detailed suggested action
        if constraint_name and orphan_count > 0:
            suggested_action = (
                f"Constraint '{constraint_name}' violated with {orphan_count} orphaned record(s). "
                f"Sample orphaned IDs: {self.orphan_samples[:5]}. "
                "Ensure parent tables are desanitized before child tables, "
                "or use database-level desanitization with dependency ordering."
            )
        else:
            suggested_action = (
                "Check that all related tables are desanitized in the correct order. "
                "Use dependency graph analysis to determine safe restoration sequence."
            )
        
        super().__init__(message, suggested_action)


class CheckpointError(DesanitizationError):
    """
    Raised when checkpoint operations fail during database-level desanitization.
    
    Checkpoints track progress during long-running desanitization operations
    to enable resumption after failures. Checkpoint errors typically indicate:
    - Checkpoint table doesn't exist or is inaccessible
    - Concurrent modification of checkpoint data
    - Invalid operation_id for resume
    
    Examples:
        - Resume requested but operation_id not found
        - Checkpoint table corrupted or manually modified
        - Permissions insufficient to write checkpoint data
    """
    
    def __init__(self, message: str, operation_id: str = None):
        """
        Initialize checkpoint error.
        
        Args:
            message: Error description
            operation_id: Operation ID that failed (if applicable)
        """
        self.operation_id = operation_id
        
        if operation_id:
            suggested_action = (
                f"Check checkpoint table for operation_id '{operation_id}'. "
                "Use --list-checkpoints to see available operations. "
                "If checkpoint data is corrupted, start a new operation without --resume."
            )
        else:
            suggested_action = (
                "Ensure checkpoint table exists and is accessible. "
                "Check database permissions for checkpoint operations."
            )
        
        super().__init__(message, suggested_action)
