"""Unit tests for custom exception hierarchy.

This module tests the custom exception classes, their attributes,
factory methods, context enrichment, and exception chaining.

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from typing import Dict, Any

from src.exceptions import (
    SanitizationError,
    ConfigError,
    ConfigFileError,
    ConfigValidationError,
    ConfigOverrideError,
    DatabaseError,
    DatabaseConnectionError,
    DatabaseQueryError,
    ConnectionPoolError,
    HealthCheckError,
    LoggingError,
    LoggerConfigurationError,
)
from src.error_codes import ErrorCodes


class TestSanitizationError:
    """Test the base SanitizationError class."""
    
    def test_basic_initialization(self):
        """Test basic exception initialization with all attributes."""
        error = SanitizationError(
            message="Test error",
            error_code="TEST_CODE",
            is_retryable=True,
            suggested_action="Do something",
            operation_context={"key": "value"}
        )
        
        # __str__ includes error code, message, context, and suggested action
        error_str = str(error)
        assert "[TEST_CODE]" in error_str
        assert "Test error" in error_str
        assert "Context: key=value" in error_str
        assert "Suggested action: Do something" in error_str
        
        assert error.message == "Test error"
        assert error.error_code == "TEST_CODE"
        assert error.is_retryable is True
        assert error.suggested_action == "Do something"
        assert error.operation_context == {"key": "value"}
    
    def test_default_values(self):
        """Test default values for optional parameters."""
        error = SanitizationError(
            message="Simple error",
            error_code="SIMPLE"
        )
        
        assert error.is_retryable is False
        assert error.suggested_action == "Check logs for more details"
        assert error.operation_context == {}
    
    def test_string_formatting(self):
        """Test __str__ formatting includes code and context."""
        error = SanitizationError(
            message="Error occurred",
            error_code="ERR_001",
            suggested_action="Fix the issue",
            operation_context={"file": "test.json", "line": 42}
        )
        
        error_str = str(error)
        assert "[ERR_001]" in error_str
        assert "Error occurred" in error_str
        assert "Context:" in error_str
        assert "file=test.json" in error_str
        assert "line=42" in error_str
        assert "Suggested action: Fix the issue" in error_str
    
    def test_repr_format(self):
        """Test __repr__ provides detailed representation."""
        error = SanitizationError(
            message="Test",
            error_code="CODE",
            is_retryable=True
        )
        
        repr_str = repr(error)
        assert "SanitizationError" in repr_str
        assert "message='Test'" in repr_str
        assert "error_code='CODE'" in repr_str
        assert "is_retryable=True" in repr_str
    
    def test_add_context(self):
        """Test adding context to an existing exception."""
        error = SanitizationError(
            message="Error",
            error_code="CODE",
            operation_context={"initial": "value"}
        )
        
        result = error.add_context(additional="data", more="info")
        
        assert result is error  # Returns self
        assert error.operation_context == {
            "initial": "value",
            "additional": "data",
            "more": "info"
        }
    
    def test_from_exception(self):
        """Test creating exception from another exception."""
        original = ValueError("Original error message")
        
        sanitization_error = SanitizationError.from_exception(
            original_exception=original,
            error_code="WRAPPED",
            is_retryable=True,
            suggested_action="Check input",
            file="test.py"
        )
        
        assert sanitization_error.message == "Original error message"
        assert sanitization_error.error_code == "WRAPPED"
        assert sanitization_error.is_retryable is True
        assert sanitization_error.suggested_action == "Check input"
        assert sanitization_error.operation_context == {"file": "test.py"}
    
    def test_to_dict(self):
        """Test converting exception to dictionary."""
        error = SanitizationError(
            message="Test error",
            error_code="TEST",
            is_retryable=True,
            suggested_action="Do this",
            operation_context={"key": "value"}
        )
        
        error_dict = error.to_dict()
        
        assert error_dict["error_class"] == "SanitizationError"
        assert error_dict["message"] == "Test error"
        assert error_dict["error_code"] == "TEST"
        assert error_dict["is_retryable"] is True
        assert error_dict["suggested_action"] == "Do this"
        assert error_dict["context"] == {"key": "value"}


class TestConfigFileError:
    """Test ConfigFileError and its factory methods."""
    
    def test_file_not_found(self):
        """Test file_not_found factory method."""
        error = ConfigFileError.file_not_found("/path/to/config.json")
        
        assert error.error_code == ErrorCodes.FILE_NOT_FOUND
        assert error.is_retryable is False
        assert "/path/to/config.json" in error.message
        assert error.operation_context["file_path"] == "/path/to/config.json"
        assert "Ensure the file exists" in error.suggested_action
    
    def test_file_not_readable(self):
        """Test file_not_readable factory method."""
        error = ConfigFileError.file_not_readable("/path/to/config.json")
        
        assert error.error_code == ErrorCodes.FILE_NOT_READABLE
        assert error.is_retryable is False
        assert "/path/to/config.json" in error.message
        assert "Check file permissions" in error.suggested_action
    
    def test_invalid_json(self):
        """Test invalid_json factory method."""
        error = ConfigFileError.invalid_json(
            file_path="/path/to/bad.json",
            line=10,
            column=5,
            detail="Unexpected token"
        )
        
        assert error.error_code == ErrorCodes.INVALID_JSON
        assert error.is_retryable is False
        assert "/path/to/bad.json" in error.message
        assert "line 10" in error.message
        assert "column 5" in error.message
        assert "Unexpected token" in error.message
        assert error.operation_context["line"] == 10
        assert error.operation_context["column"] == 5


class TestConfigValidationError:
    """Test ConfigValidationError and its factory methods."""
    
    def test_invalid_value(self):
        """Test invalid_value factory method."""
        error = ConfigValidationError.invalid_value(
            field="batch_size",
            value=-1000,
            expected="positive integer"
        )
        
        assert error.error_code == ErrorCodes.INVALID_VALUE
        assert error.is_retryable is False
        assert "batch_size" in error.message
        assert "-1000" in error.message
        assert "positive integer" in error.message
        assert error.operation_context["field"] == "batch_size"
    
    def test_missing_field(self):
        """Test missing_field factory method."""
        error = ConfigValidationError.missing_field("username", auth_type="sql")
        
        assert error.error_code == ErrorCodes.MISSING_FIELD
        assert error.is_retryable is False
        assert "username" in error.message
        assert error.operation_context["field"] == "username"
        assert error.operation_context["auth_type"] == "sql"
    
    def test_invalid_auth_credentials(self):
        """Test invalid_auth_credentials factory method."""
        error = ConfigValidationError.invalid_auth_credentials(
            auth_type="sql",
            has_username=True,
            has_password=False
        )
        
        assert error.error_code == ErrorCodes.INVALID_AUTH_CREDENTIALS
        assert error.is_retryable is False
        assert "sql" in error.message
        assert "credentials" in error.message.lower()


class TestDatabaseConnectionError:
    """Test DatabaseConnectionError and its factory methods."""
    
    def test_connection_failed(self):
        """Test connection_failed factory method."""
        error = DatabaseConnectionError.connection_failed(
            server="localhost",
            database="TestDB",
            reason="Network unreachable"
        )
        
        assert error.error_code == ErrorCodes.CONN_FAILED
        assert error.is_retryable is False
        assert "localhost" in error.message
        assert "TestDB" in error.message
        assert "Network unreachable" in error.message
        assert error.operation_context["server"] == "localhost"
        assert error.operation_context["database"] == "TestDB"
    
    def test_connection_timeout(self):
        """Test connection_timeout factory method."""
        error = DatabaseConnectionError.connection_timeout(
            server="prod-server",
            database="ProdDB",
            timeout=30
        )
        
        assert error.error_code == ErrorCodes.CONN_TIMEOUT
        assert error.is_retryable is True  # Timeouts are retryable
        assert "30s" in error.message
        assert "prod-server" in error.message
        assert error.operation_context["timeout"] == 30
    
    def test_auth_failed(self):
        """Test auth_failed factory method."""
        error = DatabaseConnectionError.auth_failed(
            server="localhost",
            database="TestDB",
            auth_type="sql"
        )
        
        assert error.error_code == ErrorCodes.AUTH_FAILED
        assert error.is_retryable is False  # Auth failures not retryable
        assert "Authentication failed" in error.message
        assert "sql" in error.message
    
    def test_server_unreachable(self):
        """Test server_unreachable factory method."""
        error = DatabaseConnectionError.server_unreachable("remote-server")
        
        assert error.error_code == ErrorCodes.SERVER_UNREACHABLE
        assert error.is_retryable is True  # Network issues are retryable
        assert "remote-server" in error.message


class TestDatabaseQueryError:
    """Test DatabaseQueryError and its factory methods."""
    
    def test_query_failed(self):
        """Test query_failed factory method."""
        long_query = "SELECT * FROM users " * 100
        error = DatabaseQueryError.query_failed(
            query=long_query,
            reason="Syntax error"
        )
        
        assert error.error_code == ErrorCodes.QUERY_FAILED
        assert error.is_retryable is False
        assert "Syntax error" in error.message
        # Should truncate long queries
        assert len(error.operation_context["query_preview"]) <= 103
    
    def test_invalid_syntax(self):
        """Test invalid_syntax factory method."""
        error = DatabaseQueryError.invalid_syntax(
            query="SELECT * FORM users",
            reason="Incorrect syntax near 'FORM'"
        )
        
        assert error.error_code == ErrorCodes.INVALID_SYNTAX
        assert error.is_retryable is False
        assert "Invalid SQL syntax" in error.message
        assert "FORM" in error.message
    
    def test_permission_denied(self):
        """Test permission_denied factory method."""
        error = DatabaseQueryError.permission_denied(
            operation="DROP TABLE",
            table="users"
        )
        
        assert error.error_code == ErrorCodes.PERMISSION_DENIED
        assert error.is_retryable is False
        assert "Permission denied" in error.message
        assert "DROP TABLE" in error.message


class TestConnectionPoolError:
    """Test ConnectionPoolError and its factory methods."""
    
    def test_pool_exhausted(self):
        """Test pool_exhausted factory method."""
        error = ConnectionPoolError.pool_exhausted(pool_size=5, active=5)
        
        assert error.error_code == ErrorCodes.POOL_EXHAUSTED
        assert error.is_retryable is True
        assert "exhausted" in error.message.lower()
        assert "5" in error.message
        assert error.operation_context["pool_size"] == 5
    
    def test_invalid_pool_state(self):
        """Test invalid_pool_state factory method."""
        error = ConnectionPoolError.invalid_pool_state(
            reason="Negative connection count"
        )
        
        assert error.error_code == ErrorCodes.POOL_INVALID_STATE
        assert error.is_retryable is True
        assert "invalid state" in error.message.lower()
        assert "Negative connection count" in error.message


class TestHealthCheckError:
    """Test HealthCheckError and its factory methods."""
    
    def test_connection_dead(self):
        """Test connection_dead factory method."""
        error = HealthCheckError.connection_dead(connection_id=123)
        
        assert error.error_code == ErrorCodes.CONN_DEAD
        assert error.is_retryable is True
        assert "dead" in error.message.lower()
    
    def test_connection_unresponsive(self):
        """Test connection_unresponsive factory method."""
        error = HealthCheckError.connection_unresponsive(timeout=5)
        
        assert error.error_code == ErrorCodes.CONN_UNRESPONSIVE
        assert error.is_retryable is True
        assert "unresponsive" in error.message.lower()
        assert "5s" in error.message
        assert error.operation_context["timeout"] == 5


class TestLoggerConfigurationError:
    """Test LoggerConfigurationError and its factory methods."""
    
    def test_invalid_handler(self):
        """Test invalid_handler factory method."""
        error = LoggerConfigurationError.invalid_handler(
            handler_name="FileHandler",
            reason="File path does not exist"
        )
        
        assert error.error_code == ErrorCodes.INVALID_HANDLER
        assert error.is_retryable is False
        assert "FileHandler" in error.message
        assert "File path does not exist" in error.message
    
    def test_invalid_formatter(self):
        """Test invalid_formatter factory method."""
        error = LoggerConfigurationError.invalid_formatter(
            formatter_name="JSONFormatter",
            reason="Invalid format string"
        )
        
        assert error.error_code == ErrorCodes.INVALID_FORMATTER
        assert error.is_retryable is False
        assert "JSONFormatter" in error.message
    
    def test_invalid_log_level(self):
        """Test invalid_log_level factory method."""
        error = LoggerConfigurationError.invalid_log_level(level="TRACE")
        
        assert error.error_code == ErrorCodes.INVALID_LOG_LEVEL
        assert error.is_retryable is False
        assert "TRACE" in error.message
        assert "valid log level" in error.suggested_action.lower()


class TestExceptionChaining:
    """Test exception chaining and context preservation."""
    
    def test_exception_chaining_with_from_exception(self):
        """Test that original exception is chained properly."""
        original = ValueError("Original problem")
        
        try:
            raise original
        except ValueError as e:
            wrapped = SanitizationError.from_exception(
                original_exception=e,
                error_code="WRAPPED",
                is_retryable=False
            )
            
            assert wrapped.__traceback__ is not None
            # The message should be from the original exception
            assert wrapped.message == "Original problem"
    
    def test_raising_custom_exception_preserves_context(self):
        """Test that raising custom exceptions preserves context."""
        error = ConfigFileError.file_not_found("/missing/file.json")
        
        with pytest.raises(ConfigFileError) as exc_info:
            raise error
        
        caught = exc_info.value
        assert caught.error_code == ErrorCodes.FILE_NOT_FOUND
        assert caught.operation_context["file_path"] == "/missing/file.json"
    
    def test_context_enrichment_during_propagation(self):
        """Test adding context as exception propagates up the call stack."""
        def inner_function():
            raise ConfigValidationError.invalid_value(
                field="port",
                value=-1,
                expected="1-65535"
            )
        
        def middle_function():
            try:
                inner_function()
            except ConfigValidationError as e:
                e.add_context(function="middle_function", layer="validation")
                raise
        
        def outer_function():
            try:
                middle_function()
            except ConfigValidationError as e:
                e.add_context(function="outer_function", layer="orchestration")
                raise
        
        with pytest.raises(ConfigValidationError) as exc_info:
            outer_function()
        
        error = exc_info.value
        assert error.operation_context["field"] == "port"
        assert error.operation_context["function"] == "outer_function"
        assert error.operation_context["layer"] == "orchestration"


class TestInheritanceHierarchy:
    """Test that exception inheritance works correctly."""
    
    def test_config_error_is_sanitization_error(self):
        """Test ConfigError inherits from SanitizationError."""
        error = ConfigError(
            message="Config error",
            error_code="TEST"
        )
        
        assert isinstance(error, SanitizationError)
        assert isinstance(error, ConfigError)
    
    def test_config_file_error_is_config_error(self):
        """Test ConfigFileError inherits from ConfigError."""
        error = ConfigFileError.file_not_found("/test.json")
        
        assert isinstance(error, SanitizationError)
        assert isinstance(error, ConfigError)
        assert isinstance(error, ConfigFileError)
    
    def test_database_error_hierarchy(self):
        """Test database error inheritance."""
        error = DatabaseConnectionError.connection_timeout(
            server="localhost",
            database="test",
            timeout=30
        )
        
        assert isinstance(error, SanitizationError)
        assert isinstance(error, DatabaseError)
        assert isinstance(error, DatabaseConnectionError)
    
    def test_catch_base_class(self):
        """Test that we can catch exceptions by base class."""
        with pytest.raises(SanitizationError):
            raise ConfigFileError.file_not_found("/test.json")
        
        with pytest.raises(ConfigError):
            raise ConfigValidationError.invalid_value("field", "value")
        
        with pytest.raises(DatabaseError):
            raise ConnectionPoolError.pool_exhausted(pool_size=5)
