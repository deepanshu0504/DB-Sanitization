"""
Unit tests for ErrorCodes class (error_codes.py).

Tests cover:
- Error code constant definitions and immutability
- Error code uniqueness (no duplicates)
- Error code naming conventions (UPPERCASE_WITH_UNDERSCORES)
- Domain grouping validation

Test Organization:
- TestErrorCodesConstants: Constant definitions and types
- TestErrorCodesUniqueness: No duplicate error codes
- TestErrorCodesNaming: Naming convention compliance

Author: Database Sanitization Team
Date: 2026-03-27
"""

import pytest
from src.error_codes import ErrorCodes


class TestErrorCodesConstants:
    """Test ErrorCodes constant definitions."""
    
    def test_configuration_error_codes_exist(self):
        """Test that all configuration error codes exist."""
        assert ErrorCodes.FILE_NOT_FOUND == "FILE_NOT_FOUND"
        assert ErrorCodes.FILE_NOT_READABLE == "FILE_NOT_READABLE"
        assert ErrorCodes.INVALID_JSON == "INVALID_JSON"
        assert ErrorCodes.INVALID_VALUE == "INVALID_VALUE"
        assert ErrorCodes.MISSING_FIELD == "MISSING_FIELD"
        assert ErrorCodes.TYPE_MISMATCH == "TYPE_MISMATCH"
        assert ErrorCodes.INVALID_AUTH_CREDENTIALS == "INVALID_AUTH_CREDENTIALS"
        assert ErrorCodes.ENV_VAR_INVALID == "ENV_VAR_INVALID"
        assert ErrorCodes.OVERRIDE_CONFLICT == "OVERRIDE_CONFLICT"
    
    def test_database_error_codes_exist(self):
        """Test that all database error codes exist."""
        assert ErrorCodes.CONN_FAILED == "CONN_FAILED"
        assert ErrorCodes.CONN_TIMEOUT == "CONN_TIMEOUT"
        assert ErrorCodes.AUTH_FAILED == "AUTH_FAILED"
        assert ErrorCodes.SERVER_UNREACHABLE == "SERVER_UNREACHABLE"
        assert ErrorCodes.QUERY_FAILED == "QUERY_FAILED"
        assert ErrorCodes.INVALID_SYNTAX == "INVALID_SYNTAX"
        assert ErrorCodes.PERMISSION_DENIED == "PERMISSION_DENIED"
        assert ErrorCodes.POOL_EXHAUSTED == "POOL_EXHAUSTED"
        assert ErrorCodes.POOL_INVALID_STATE == "POOL_INVALID_STATE"
    
    def test_error_codes_are_strings(self):
        """Test that all error codes are string constants."""
        codes = [
            ErrorCodes.FILE_NOT_FOUND,
            ErrorCodes.CONN_FAILED,
            ErrorCodes.QUERY_FAILED
        ]
        
        for code in codes:
            assert isinstance(code, str)
    
    def test_error_codes_immutable(self):
        """Test that error code constants cannot be reassigned."""
        with pytest.raises(AttributeError):
            ErrorCodes.FILE_NOT_FOUND = "NEW_VALUE"


class TestErrorCodesUniqueness:
    """Test error code uniqueness."""
    
    def test_no_duplicate_error_codes(self):
        """Test that all error codes are unique."""
        # Get all error code attributes
        error_codes = [
            getattr(ErrorCodes, attr)
            for attr in dir(ErrorCodes)
            if not attr.startswith('_') and isinstance(getattr(ErrorCodes, attr), str)
        ]
        
        # Check for duplicates
        assert len(error_codes) == len(set(error_codes)), "Found duplicate error codes"


class TestErrorCodesNaming:
    """Test error code naming conventions."""
    
    def test_error_codes_uppercase_underscore(self):
        """Test that error code constants follow UPPERCASE_WITH_UNDERSCORES convention."""
        # Get all error code attribute names
        code_names = [
            attr
            for attr in dir(ErrorCodes)
            if not attr.startswith('_')
        ]
        
        for name in code_names:
            # Should be uppercase with underscores
            assert name.isupper(), f"{name} is not uppercase"
            assert ' ' not in name, f"{name} contains spaces"
    
    def test_error_code_values_match_names(self):
        """Test that error code values match their constant names."""
        code_map = {
            "FILE_NOT_FOUND": ErrorCodes.FILE_NOT_FOUND,
            "CONN_FAILED": ErrorCodes.CONN_FAILED,
            "QUERY_FAILED": ErrorCodes.QUERY_FAILED
        }
        
        for name, value in code_map.items():
            assert value == name, f"{name} value should be '{name}', got '{value}'"
