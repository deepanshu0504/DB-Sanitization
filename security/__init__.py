"""
Security Module - Role-Based Access Control for Desanitization

This module provides security features for the database desanitization framework,
including role-based access control (RBAC) to restrict restoration operations
to authorized users.

Components:
    AccessControl: Main class for permission checking and role validation
    SecurityError: Base exception for security-related errors
    PermissionDeniedError: Raised when user lacks required permissions
    RoleNotFoundError: Raised when configured role doesn't exist in database

Usage:
    from security import AccessControl, SecurityConfig
    from desanitization.config_models import SecurityConfig
    
    config = SecurityConfig(
        enabled=True,
        allowed_roles=['DataRestorer', 'db_owner']
    )
    
    access_control = AccessControl(connection, config)
    allowed, reason = access_control.check_permission('RECORD', dry_run=False)
    
    if not allowed:
        raise PermissionDeniedError(reason)

Related User Story: 7.1 - Role-Based Access Control
Created: April 13, 2026
"""

from security.exceptions import (
    SecurityError,
    PermissionDeniedError,
    RoleNotFoundError,
)

from security.access_control import AccessControl

__all__ = [
    'AccessControl',
    'SecurityError',
    'PermissionDeniedError',
    'RoleNotFoundError',
]
