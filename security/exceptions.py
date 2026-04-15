"""
Security-related exceptions for the database desanitization framework.

This module defines custom exception classes for security and permission
errors that may occur during desanitization operations.

Exception Hierarchy:
    SecurityError (base)
    ├── PermissionDeniedError
    └── RoleNotFoundError

Author: Database Sanitization Team
Date: April 13, 2026
"""


class SecurityError(Exception):
    """
    Base exception for all security-related errors.
    
    This is the parent class for all security exceptions in the framework.
    Catch this to handle any security-related error generically.
    """
    pass


class PermissionDeniedError(SecurityError):
    """
    Raised when a user attempts an operation without required permissions.
    
    This exception is raised when:
    - User is not a member of any allowed roles
    - Security is enabled but user has insufficient privileges
    - Role check is required but user lacks the necessary role membership
    
    Attributes:
        message: Detailed explanation of why permission was denied
        operation_type: Type of operation attempted (RECORD/COLUMN/TABLE/DATABASE)
        required_roles: List of roles that would grant permission
        user_roles: List of roles the current user belongs to
    
    Example:
        >>> raise PermissionDeniedError(
        ...     "User 'DOMAIN\\user' is not a member of any allowed roles. "
        ...     "Required: ['DataRestorer', 'db_owner']. "
        ...     "User has: ['db_datareader']"
        ... )
    """
    
    def __init__(
        self,
        message: str,
        operation_type: str = None,
        required_roles: list = None,
        user_roles: list = None
    ):
        super().__init__(message)
        self.operation_type = operation_type
        self.required_roles = required_roles or []
        self.user_roles = user_roles or []


class RoleNotFoundError(SecurityError):
    """
    Raised when a configured role does not exist in the database.
    
    This exception is raised during role validation when one or more
    roles specified in the configuration are not found in the database.
    
    Attributes:
        message: Detailed explanation with missing role names
        missing_roles: List of role names that don't exist
        existing_roles: List of valid roles found in database
    
    Example:
        >>> raise RoleNotFoundError(
        ...     "Role 'DataRestorer' not found in database. "
        ...     "Available roles: ['db_owner', 'db_datareader', 'db_datawriter']",
        ...     missing_roles=['DataRestorer'],
        ...     existing_roles=['db_owner', 'db_datareader', 'db_datawriter']
        ... )
    """
    
    def __init__(
        self,
        message: str,
        missing_roles: list = None,
        existing_roles: list = None
    ):
        super().__init__(message)
        self.missing_roles = missing_roles or []
        self.existing_roles = existing_roles or []
