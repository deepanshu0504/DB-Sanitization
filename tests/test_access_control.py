"""
Unit tests for AccessControl - Role-Based Access Control

This test suite validates the AccessControl class for permission checking,
role validation, and user detection in the database desanitization framework.

Test Coverage:
    - SecurityConfig validation
    - User detection (_get_current_user)
    - Role membership checking (_is_member_of_role)
    - Permission check logic (enabled/disabled, dry-run, role matching)
    - Role validation (_validate_roles_exist)
    - Error scenarios (connection failures, invalid roles, permission denied)

Related User Story: 7.1 - Role-Based Access Control
Created: April 13, 2026
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from typing import List, Optional

import pytest

from security import AccessControl, PermissionDeniedError, RoleNotFoundError, SecurityError
from desanitization.config_models import SecurityConfig


class TestSecurityConfig(unittest.TestCase):
    """Test SecurityConfig model validation."""
    
    def test_default_config(self):
        """Test default SecurityConfig values."""
        config = SecurityConfig()
        
        assert config.enabled is False
        assert config.allowed_roles == []
        assert config.require_role_for_dry_run is False
        assert config.deny_on_role_check_failure is True
    
    def test_enabled_without_roles_fails(self):
        """Test that enabling security without roles raises validation error."""
        with pytest.raises(ValueError) as exc_info:
            SecurityConfig(enabled=True, allowed_roles=[])
        
        assert "allowed_roles must not be empty when security is enabled" in str(exc_info.value)
    
    def test_enabled_with_roles_succeeds(self):
        """Test that enabling security with roles succeeds."""
        config = SecurityConfig(
            enabled=True,
            allowed_roles=['DataRestorer', 'db_owner']
        )
        
        assert config.enabled is True
        assert config.allowed_roles == ['DataRestorer', 'db_owner']
    
    def test_disabled_with_empty_roles_succeeds(self):
        """Test that disabled security with empty roles is valid."""
        config = SecurityConfig(enabled=False, allowed_roles=[])
        
        assert config.enabled is False
        assert config.allowed_roles == []
    
    def test_custom_configuration(self):
        """Test custom security configuration."""
        config = SecurityConfig(
            enabled=True,
            allowed_roles=['CustomRole'],
            require_role_for_dry_run=True,
            deny_on_role_check_failure=False
        )
        
        assert config.enabled is True
        assert config.allowed_roles == ['CustomRole']
        assert config.require_role_for_dry_run is True
        assert config.deny_on_role_check_failure is False


class TestAccessControlInitialization(unittest.TestCase):
    """Test AccessControl initialization and setup."""
    
    def test_init_with_none_connection_raises_error(self):
        """Test that initializing with None connection raises ValueError."""
        config = SecurityConfig(enabled=False)
        
        with pytest.raises(ValueError) as exc_info:
            AccessControl(None, config)
        
        assert "Database connection cannot be None" in str(exc_info.value)
    
    def test_init_with_valid_connection_succeeds(self):
        """Test initialization with valid connection."""
        mock_conn = Mock()
        config = SecurityConfig(enabled=False)
        
        ac = AccessControl(mock_conn, config)
        
        assert ac.connection == mock_conn
        assert ac.config == config
        assert ac._current_user is None
        assert ac._user_roles is None
    
    def test_init_with_security_disabled_skips_role_validation(self):
        """Test that disabled security skips role validation."""
        mock_conn = Mock()
        config = SecurityConfig(enabled=False, allowed_roles=[])
        
        # Should not raise error even though roles are empty
        ac = AccessControl(mock_conn, config)
        
        assert ac.config.enabled is False
    
    @patch.object(AccessControl, '_validate_roles_exist')
    def test_init_with_security_enabled_validates_roles(self, mock_validate):
        """Test that enabled security triggers role validation."""
        mock_conn = Mock()
        config = SecurityConfig(enabled=True, allowed_roles=['DataRestorer'])
        mock_validate.return_value = ['DataRestorer']
        
        ac = AccessControl(mock_conn, config)
        
        mock_validate.assert_called_once_with(['DataRestorer'])


class TestUserDetection(unittest.TestCase):
    """Test user detection functionality."""
    
    def test_get_current_user_windows_auth(self):
        """Test user detection for Windows Authentication."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = ('DOMAIN\\username',)
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        user = ac._get_current_user()
        
        assert user == 'DOMAIN\\username'
        mock_cursor.execute.assert_called_once_with("SELECT SYSTEM_USER")
        mock_cursor.close.assert_called_once()
    
    def test_get_current_user_sql_auth(self):
        """Test user detection for SQL Server Authentication."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = ('sa',)
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        user = ac._get_current_user()
        
        assert user == 'sa'
    
    def test_get_current_user_cached(self):
        """Test that user detection result is cached."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = ('testuser',)
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        # First call
        user1 = ac._get_current_user()
        # Second call (should use cache)
        user2 = ac._get_current_user()
        
        assert user1 == user2 == 'testuser'
        # Cursor should only be called once (cached)
        assert mock_conn.cursor.call_count == 1
    
    def test_get_current_user_fallback_to_suser_sname(self):
        """Test fallback to SUSER_SNAME() when SYSTEM_USER returns None."""
        mock_conn = Mock()
        mock_cursor1 = Mock()
        mock_cursor1.fetchone.return_value = None
        mock_cursor2 = Mock()
        mock_cursor2.fetchone.return_value = ('fallback_user',)
        mock_conn.cursor.side_effect = [mock_cursor1, mock_cursor2]
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        user = ac._get_current_user()
        
        assert user == 'fallback_user'
        assert mock_conn.cursor.call_count == 2
    
    def test_get_current_user_error_handling(self):
        """Test error handling when user detection fails."""
        mock_conn = Mock()
        mock_conn.cursor.side_effect = Exception("Database error")
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        user = ac._get_current_user()
        
        assert user == "UNKNOWN"


class TestRoleMembership(unittest.TestCase):
    """Test role membership checking."""
    
    def test_is_member_of_role_true(self):
        """Test role membership check when user is member."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = (1,)  # IS_MEMBER returns 1
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        is_member = ac._is_member_of_role('DataRestorer')
        
        assert is_member is True
        mock_cursor.execute.assert_called_once_with("SELECT IS_MEMBER(?)", ('DataRestorer',))
    
    def test_is_member_of_role_false(self):
        """Test role membership check when user is not member."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = (0,)  # IS_MEMBER returns 0
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        is_member = ac._is_member_of_role('DataRestorer')
        
        assert is_member is False
    
    def test_is_member_of_role_invalid_role_returns_null(self):
        """Test role membership check for invalid role (IS_MEMBER returns NULL)."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = (None,)  # IS_MEMBER returns NULL
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        is_member = ac._is_member_of_role('InvalidRole')
        
        assert is_member is False
    
    def test_is_member_of_role_error_handling(self):
        """Test error handling when role check fails."""
        mock_conn = Mock()
        mock_conn.cursor.side_effect = Exception("Database error")
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        is_member = ac._is_member_of_role('DataRestorer')
        
        assert is_member is False


class TestGetUserRoles(unittest.TestCase):
    """Test user role retrieval."""
    
    def test_get_user_roles_success(self):
        """Test retrieving user roles successfully."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [
            ('db_datareader',),
            ('db_datawriter',),
            ('DataRestorer',)
        ]
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        roles = ac._get_user_roles('testuser')
        
        assert roles == ['db_datareader', 'db_datawriter', 'DataRestorer']
        assert 'usr.name = ?' in mock_cursor.execute.call_args[0][0]
    
    def test_get_user_roles_no_roles(self):
        """Test user with no roles."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        roles = ac._get_user_roles('testuser')
        
        assert roles == []
    
    def test_get_user_roles_cached(self):
        """Test that user roles are cached."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [('DataRestorer',)]
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        # First call
        roles1 = ac._get_user_roles('testuser')
        # Second call (should use cache)
        roles2 = ac._get_user_roles('testuser')
        
        assert roles1 == roles2 == ['DataRestorer']
        # Cursor should only be called once (cached)
        assert mock_conn.cursor.call_count == 1
    
    def test_get_user_roles_error_handling(self):
        """Test error handling when role query fails."""
        mock_conn = Mock()
        mock_conn.cursor.side_effect = Exception("Database error")
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        roles = ac._get_user_roles('testuser')
        
        assert roles == []


class TestRoleValidation(unittest.TestCase):
    """Test role existence validation."""
    
    def test_validate_roles_exist_all_valid(self):
        """Test validation when all roles exist."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [
            ('db_owner',),
            ('db_datareader',),
            ('DataRestorer',)
        ]
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        result = ac._validate_roles_exist(['DataRestorer', 'db_owner'])
        
        assert result == ['DataRestorer', 'db_owner']
    
    def test_validate_roles_exist_missing_roles_raises_error(self):
        """Test validation when roles are missing."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [
            ('db_owner',),
            ('db_datareader',)
        ]
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(enabled=True, allowed_roles=['MissingRole', 'db_owner'])
        
        with pytest.raises(RoleNotFoundError) as exc_info:
            ac = AccessControl(mock_conn, config)
        
        error = exc_info.value
        assert 'MissingRole' in error.missing_roles
        assert 'db_owner' in error.existing_roles
        assert "not found in database" in str(error)
    
    def test_validate_roles_exist_database_error_with_deny_on_failure(self):
        """Test validation error with deny_on_role_check_failure=True."""
        mock_conn = Mock()
        mock_conn.cursor.side_effect = Exception("Database error")
        
        config = SecurityConfig(
            enabled=True,
            allowed_roles=['DataRestorer'],
            deny_on_role_check_failure=True
        )
        
        with pytest.raises(SecurityError) as exc_info:
            ac = AccessControl(mock_conn, config)
        
        assert "Role validation failed" in str(exc_info.value)
    
    def test_validate_roles_exist_database_error_with_allow_on_failure(self):
        """Test validation error with deny_on_role_check_failure=False."""
        mock_conn = Mock()
        mock_conn.cursor.side_effect = Exception("Database error")
        
        config = SecurityConfig(
            enabled=True,
            allowed_roles=['DataRestorer'],
            deny_on_role_check_failure=False
        )
        
        # Should not raise error, just log warning
        ac = AccessControl(mock_conn, config)
        
        assert ac.config.deny_on_role_check_failure is False


class TestCheckPermission(unittest.TestCase):
    """Test permission checking logic."""
    
    def test_check_permission_security_disabled_allows_all(self):
        """Test that disabled security allows all operations."""
        mock_conn = Mock()
        config = SecurityConfig(enabled=False)
        ac = AccessControl(mock_conn, config)
        
        allowed, reason = ac.check_permission('RECORD', dry_run=False)
        
        assert allowed is True
        assert "Security checks disabled" in reason
    
    def test_check_permission_dryrun_exemption(self):
        """Test dry-run exemption when require_role_for_dry_run=False."""
        mock_conn = Mock()
        config = SecurityConfig(
            enabled=True,
            allowed_roles=['DataRestorer'],
            require_role_for_dry_run=False
        )
        
        with patch.object(AccessControl, '_validate_roles_exist', return_value=['DataRestorer']):
            ac = AccessControl(mock_conn, config)
        
        allowed, reason = ac.check_permission('RECORD', dry_run=True)
        
        assert allowed is True
        assert "Dry-run exemption" in reason
    
    def test_check_permission_dryrun_requires_role(self):
        """Test dry-run requires role when require_role_for_dry_run=True."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.side_effect = [
            ('testuser',),  # SYSTEM_USER
            (0,)  # IS_MEMBER returns 0 (not member)
        ]
        mock_cursor.fetchall.return_value = []  # No roles
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(
            enabled=True,
            allowed_roles=['DataRestorer'],
            require_role_for_dry_run=True
        )
        
        with patch.object(AccessControl, '_validate_roles_exist', return_value=['DataRestorer']):
            ac = AccessControl(mock_conn, config)
        
        allowed, reason = ac.check_permission('RECORD', dry_run=True)
        
        assert allowed is False
        assert "Permission denied" in reason
    
    def test_check_permission_user_has_role_granted(self):
        """Test permission granted when user has required role."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.side_effect = [
            ('testuser',),  # SYSTEM_USER
            (1,)  # IS_MEMBER returns 1 (is member)
        ]
        mock_cursor.fetchall.return_value = [('DataRestorer',)]
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(
            enabled=True,
            allowed_roles=['DataRestorer']
        )
        
        with patch.object(AccessControl, '_validate_roles_exist', return_value=['DataRestorer']):
            ac = AccessControl(mock_conn, config)
        
        allowed, reason = ac.check_permission('TABLE', dry_run=False)
        
        assert allowed is True
        assert "Permission granted" in reason
        assert "DataRestorer" in reason
    
    def test_check_permission_user_lacks_role_denied(self):
        """Test permission denied when user lacks required role."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.side_effect = [
            ('testuser',),  # SYSTEM_USER
            (0,)  # IS_MEMBER returns 0 (not member)
        ]
        mock_cursor.fetchall.return_value = [('db_datareader',)]
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(
            enabled=True,
            allowed_roles=['DataRestorer']
        )
        
        with patch.object(AccessControl, '_validate_roles_exist', return_value=['DataRestorer']):
            ac = AccessControl(mock_conn, config)
        
        allowed, reason = ac.check_permission('DATABASE', dry_run=False)
        
        assert allowed is False
        assert "Permission denied" in reason
        assert "not a member of any allowed roles" in reason
        assert "DataRestorer" in reason
    
    def test_check_permission_multiple_roles_any_match_succeeds(self):
        """Test that user needs ANY of the allowed roles (not all)."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.side_effect = [
            ('testuser',),  # SYSTEM_USER
            (0,),  # IS_MEMBER('db_owner') returns 0
            (1,)   # IS_MEMBER('DataRestorer') returns 1
        ]
        mock_cursor.fetchall.return_value = [('DataRestorer',)]
        mock_conn.cursor.return_value = mock_cursor
        
        config = SecurityConfig(
            enabled=True,
            allowed_roles=['db_owner', 'DataRestorer']
        )
        
        with patch.object(AccessControl, '_validate_roles_exist', return_value=['db_owner', 'DataRestorer']):
            ac = AccessControl(mock_conn, config)
        
        allowed, reason = ac.check_permission('COLUMN', dry_run=False)
        
        assert allowed is True
        assert "DataRestorer" in reason


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
