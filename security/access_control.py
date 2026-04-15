"""
AccessControl - Role-Based Access Control for Database Desanitization

This module implements permission checking for desanitization operations
using SQL Server database roles. It verifies that the current user is a
member of configured allowed roles before permitting restoration operations.

Key Features:
    - SQL Server role membership checking via IS_MEMBER()
    - Support for Windows Authentication and SQL Server Authentication
    - Configurable dry-run exemption for read-only users
    - Detailed permission denial reasons for troubleshooting
    - Role validation to catch configuration errors early

Usage:
    from security import AccessControl
    from desanitization.config_models import SecurityConfig
    
    config = SecurityConfig(
        enabled=True,
        allowed_roles=['DataRestorer', 'db_owner'],
        require_role_for_dry_run=False
    )
    
    access_control = AccessControl(connection, config)
    
    # Check permission before operation
    allowed, reason = access_control.check_permission('RECORD', dry_run=False)
    if not allowed:
        raise PermissionDeniedError(reason)

Related User Story: 7.1 - Role-Based Access Control
Author: Database Sanitization Team
Date: April 13, 2026
"""

import logging
from typing import List, Tuple, Optional, TYPE_CHECKING

from security.exceptions import (
    SecurityError,
    PermissionDeniedError,
    RoleNotFoundError,
)

if TYPE_CHECKING:
    from desanitization.config_models import SecurityConfig


logger = logging.getLogger(__name__)


class AccessControl:
    """
    Manages role-based access control for desanitization operations.
    
    This class checks user permissions based on SQL Server database role
    membership. It supports both Windows Authentication and SQL Server
    Authentication, and can optionally allow dry-run operations without
    role requirements.
    
    Attributes:
        connection: Active pyodbc database connection
        config: SecurityConfig with enabled flag and allowed_roles list
        _current_user: Cached current database user (SYSTEM_USER)
        _user_roles: Cached list of roles for current user
    
    Example:
        >>> config = SecurityConfig(enabled=True, allowed_roles=['DataRestorer'])
        >>> ac = AccessControl(conn, config)
        >>> allowed, reason = ac.check_permission('TABLE', dry_run=False)
        >>> if not allowed:
        ...     print(f"Access denied: {reason}")
    """
    
    def __init__(
        self,
        connection,
        config: 'SecurityConfig'
    ):
        """
        Initialize AccessControl with database connection and configuration.
        
        Args:
            connection: Active pyodbc connection object
            config: SecurityConfig instance with security settings
        
        Raises:
            ValueError: If connection is None
            RoleNotFoundError: If configured roles don't exist (validation performed)
        """
        if connection is None:
            raise ValueError("Database connection cannot be None")
        
        self.connection = connection
        self.config = config
        self._current_user: Optional[str] = None
        self._user_roles: Optional[List[str]] = None
        
        # Validate configured roles exist if security is enabled
        if self.config.enabled and self.config.allowed_roles:
            self._validate_roles_exist(self.config.allowed_roles)
    
    def check_permission(
        self,
        operation_type: str,
        dry_run: bool = True
    ) -> Tuple[bool, str]:
        """
        Check if current user has permission to perform operation.
        
        This is the main permission checking method. It applies the following logic:
        1. If security disabled → GRANTED (backward compatible)
        2. If dry_run AND require_role_for_dry_run=False → GRANTED (read-only)
        3. If security enabled → Check role membership against allowed_roles
        4. Return (allowed, reason) tuple
        
        Args:
            operation_type: Type of operation (RECORD/COLUMN/TABLE/DATABASE)
            dry_run: Whether this is a dry-run (preview) operation
        
        Returns:
            Tuple of (allowed: bool, reason: str)
            - allowed: True if permission granted, False if denied
            - reason: Detailed explanation for logging/audit
        
        Example:
            >>> allowed, reason = ac.check_permission('DATABASE', dry_run=False)
            >>> if not allowed:
            ...     logger.error(f"Permission denied: {reason}")
            ...     raise PermissionDeniedError(reason)
        """
        # Rule 1: Security disabled → always allow (backward compatible)
        if not self.config.enabled:
            return (
                True,
                f"Security checks disabled - {operation_type} operation allowed"
            )
        
        # Rule 2: Dry-run exemption (read-only users can preview)
        if dry_run and not self.config.require_role_for_dry_run:
            return (
                True,
                f"Dry-run exemption - {operation_type} preview allowed without role check"
            )
        
        # Rule 3: Security enabled → check role membership
        current_user = self._get_current_user()
        user_roles = self._get_user_roles(current_user)
        
        # Check if user is member of ANY allowed role
        for role in self.config.allowed_roles:
            if self._is_member_of_role(role):
                return (
                    True,
                    f"Permission granted - User '{current_user}' is member of role '{role}'"
                )
        
        # Permission denied - provide detailed reason
        reason = (
            f"Permission denied for {operation_type} operation. "
            f"User '{current_user}' is not a member of any allowed roles. "
            f"Required roles: {self.config.allowed_roles}. "
            f"User's roles: {user_roles if user_roles else ['(none)']}. "
            f"Contact database administrator to grant appropriate role membership."
        )
        
        return (False, reason)
    
    def _get_current_user(self) -> str:
        """
        Get current database user via SQL SYSTEM_USER function.
        
        This method queries the database to determine the current user's identity.
        It supports both Windows Authentication (returns 'DOMAIN\\username') and
        SQL Server Authentication (returns 'username').
        
        The result is cached to avoid repeated queries.
        
        Returns:
            Database username string
            - Windows Auth: 'DOMAIN\\username'
            - SQL Server Auth: 'sa', 'username', etc.
        
        Example:
            >>> user = ac._get_current_user()
            >>> print(user)
            'MYCOMPANY\\john.doe'
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
    
    def _get_user_roles(self, user: str) -> List[str]:
        """
        Get list of database roles for specified user.
        
        Queries sys.database_principals and sys.database_role_members to find
        all database roles the user belongs to.
        
        Args:
            user: Username to query (from SYSTEM_USER)
        
        Returns:
            List of role names (e.g., ['db_datareader', 'DataRestorer'])
        
        Example:
            >>> roles = ac._get_user_roles('DOMAIN\\john.doe')
            >>> print(roles)
            ['db_datareader', 'db_datawriter', 'DataRestorer']
        """
        if self._user_roles is not None:
            return self._user_roles
        
        try:
            cursor = self.connection.cursor()
            
            query = """
                SELECT dp.name
                FROM sys.database_principals dp
                JOIN sys.database_role_members drm
                    ON dp.principal_id = drm.role_principal_id
                JOIN sys.database_principals usr
                    ON drm.member_principal_id = usr.principal_id
                WHERE usr.name = ?
                ORDER BY dp.name
            """
            
            cursor.execute(query, (user,))
            roles = [row[0] for row in cursor.fetchall()]
            cursor.close()
            
            self._user_roles = roles
            return roles
        
        except Exception as e:
            logger.warning(f"Could not query user roles for '{user}': {e}")
            return []
    
    def _is_member_of_role(self, role: str) -> bool:
        """
        Check if current user is member of specified role using IS_MEMBER().
        
        Uses SQL Server's native IS_MEMBER() function for accurate role checking.
        This is more reliable than querying system tables as it accounts for
        nested role memberships and special permissions.
        
        Args:
            role: Database role name to check
        
        Returns:
            True if current user is member of role, False otherwise
        
        Example:
            >>> if ac._is_member_of_role('DataRestorer'):
            ...     print("User has DataRestorer role")
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT IS_MEMBER(?)", (role,))
            row = cursor.fetchone()
            cursor.close()
            
            # IS_MEMBER returns 1 (member), 0 (not member), or NULL (invalid role)
            if row and row[0] is not None:
                return bool(row[0])
            
            return False
        
        except Exception as e:
            logger.warning(f"Error checking role membership for '{role}': {e}")
            return False
    
    def _validate_roles_exist(self, roles: List[str]) -> List[str]:
        """
        Validate that configured roles exist in the database.
        
        Queries sys.database_principals to verify each role exists.
        This is called during initialization to catch configuration errors early.
        
        Args:
            roles: List of role names to validate
        
        Returns:
            List of role names that were found (validated)
        
        Raises:
            RoleNotFoundError: If any configured role doesn't exist
        
        Example:
            >>> ac._validate_roles_exist(['DataRestorer', 'db_owner'])
            ['DataRestorer', 'db_owner']
        """
        try:
            cursor = self.connection.cursor()
            
            # Query all database roles
            query = """
                SELECT name
                FROM sys.database_principals
                WHERE type = 'R'
                ORDER BY name
            """
            
            cursor.execute(query)
            existing_roles = [row[0] for row in cursor.fetchall()]
            cursor.close()
            
            # Check each configured role
            missing_roles = []
            for role in roles:
                if role not in existing_roles:
                    missing_roles.append(role)
            
            # Raise error if any roles are missing
            if missing_roles:
                error_msg = (
                    f"Configuration error: {len(missing_roles)} role(s) not found in database. "
                    f"Missing roles: {missing_roles}. "
                    f"Available roles: {existing_roles}. "
                    f"Please create missing roles or update configuration."
                )
                
                raise RoleNotFoundError(
                    error_msg,
                    missing_roles=missing_roles,
                    existing_roles=existing_roles
                )
            
            logger.info(f"Role validation passed: {len(roles)} role(s) verified")
            return roles
        
        except RoleNotFoundError:
            # Re-raise role not found errors
            raise
        
        except Exception as e:
            logger.error(f"Error validating roles: {e}")
            
            # Optionally fail based on configuration
            if self.config.deny_on_role_check_failure:
                raise SecurityError(
                    f"Role validation failed: {e}. "
                    f"Cannot verify role configuration."
                )
            
            # Log warning but continue if deny_on_role_check_failure=False
            logger.warning(
                f"Role validation failed but continuing due to "
                f"deny_on_role_check_failure=False: {e}"
            )
            return []
