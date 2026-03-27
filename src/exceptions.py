"""
Custom exception hierarchy for database sanitization framework.

This module defines a comprehensive exception hierarchy with recovery metadata
to enable intelligent error handling, retry logic, and actionable error messages.
All exceptions include error codes, retry-ability flags, and contextual information.

Author: Database Sanitization Team
Date: 2026-03-26
"""

from typing import Any, Dict, Optional, Type, List
import traceback

from .error_codes import ErrorCodes


class SanitizationError(Exception):
    """
    Base exception for all database sanitization errors.
    
    This exception includes recovery metadata to enable intelligent error handling:
    - error_code: Standardized error code for identification
    - is_retryable: Whether the operation can be retried
    - suggested_action: Human-readable guidance for resolution
    - operation_context: Additional context about the failed operation
    
    Attributes:
        message: The error message
        error_code: Standardized error code from ErrorCodes
        is_retryable: Whether this error is transient and retryable
        suggested_action: Recommended action to resolve the error
        operation_context: Dict containing contextual information
    """

    def __init__(
        self,
        message: str,
        error_code: str,
        is_retryable: bool = False,
        suggested_action: str = "",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize a SanitizationError.
        
        Args:
            message: Human-readable error message
            error_code: Error code from ErrorCodes class
            is_retryable: Whether the operation can be retried
            suggested_action: Recommended action to resolve the error
            operation_context: Additional context (file_path, server, table, etc.)
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.is_retryable = is_retryable
        self.suggested_action = suggested_action or "Check logs for more details"
        self.operation_context = operation_context or {}
    
    def __str__(self) -> str:
        """
        Format the exception as a string with error code and context.
        
        Returns:
            Formatted error message including code and context
        """
        parts = [f"[{self.error_code}] {self.message}"]
        
        if self.operation_context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.operation_context.items())
            parts.append(f"Context: {context_str}")
        
        if self.suggested_action:
            parts.append(f"Suggested action: {self.suggested_action}")
        
        return " | ".join(parts)
    
    def __repr__(self) -> str:
        """Return detailed representation for debugging."""
        return (
            f"{self.__class__.__name__}(message={self.message!r}, "
            f"error_code={self.error_code!r}, is_retryable={self.is_retryable}, "
            f"context={self.operation_context})"
        )
    
    def add_context(self, **kwargs: Any) -> "SanitizationError":
        """
        Add additional context to the exception.
        
        This method is useful for enriching exceptions as they propagate up
        the call stack.
        
        Args:
            **kwargs: Key-value pairs to add to operation_context
            
        Returns:
            Self for method chaining
        """
        self.operation_context.update(kwargs)
        return self
    
    @classmethod
    def from_exception(
        cls,
        original_exception: Exception,
        error_code: str,
        is_retryable: bool = False,
        suggested_action: str = "",
        **context: Any
    ) -> "SanitizationError":
        """
        Create a SanitizationError from another exception.
        
        This factory method wraps third-party exceptions (pyodbc, Pydantic, etc.)
        with our custom exception type while preserving the original exception
        via chaining.
        
        Args:
            original_exception: The original exception to wrap
            error_code: Error code for the new exception
            is_retryable: Whether the error is retryable
            suggested_action: Suggested resolution action
            **context: Additional context to include
            
        Returns:
            New SanitizationError instance with chained original exception
        """
        message = str(original_exception)
        new_exception = cls(
            message=message,
            error_code=error_code,
            is_retryable=is_retryable,
            suggested_action=suggested_action,
            operation_context=context
        )
        # Chain the original exception
        return new_exception.with_traceback(original_exception.__traceback__)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert exception to a dictionary for logging or serialization.
        
        Returns:
            Dictionary representation of the exception
        """
        return {
            "error_class": self.__class__.__name__,
            "message": self.message,
            "error_code": self.error_code,
            "is_retryable": self.is_retryable,
            "suggested_action": self.suggested_action,
            "context": self.operation_context,
        }


# ==================== Configuration Exceptions ====================


class ConfigError(SanitizationError):
    """Base exception for all configuration-related errors."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        is_retryable: bool = False,
        suggested_action: str = "",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, is_retryable, suggested_action, operation_context)


class ConfigFileError(ConfigError):
    """
    Exception raised for configuration file access or parsing errors.
    
    This includes file not found, permission denied, and JSON parsing errors.
    """
    
    @classmethod
    def file_not_found(cls, file_path: str) -> "ConfigFileError":
        """Factory method for file not found errors."""
        return cls(
            message=f"Configuration file not found: {file_path}",
            error_code=ErrorCodes.FILE_NOT_FOUND,
            is_retryable=False,
            suggested_action=f"Ensure the file exists at: {file_path}",
            operation_context={"file_path": file_path}
        )
    
    @classmethod
    def file_not_readable(cls, file_path: str) -> "ConfigFileError":
        """Factory method for file permission errors."""
        return cls(
            message=f"Configuration file not readable: {file_path}",
            error_code=ErrorCodes.FILE_NOT_READABLE,
            is_retryable=False,
            suggested_action=f"Check file permissions for: {file_path}",
            operation_context={"file_path": file_path}
        )
    
    @classmethod
    def invalid_json(cls, file_path: str, line: int = 0, column: int = 0, detail: str = "") -> "ConfigFileError":
        """Factory method for JSON parsing errors."""
        message = f"Invalid JSON in configuration file: {file_path}"
        if line and column:
            message += f" at line {line}, column {column}"
        if detail:
            message += f" - {detail}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.INVALID_JSON,
            is_retryable=False,
            suggested_action="Validate JSON syntax using a JSON validator",
            operation_context={"file_path": file_path, "line": line, "column": column}
        )


class ConfigValidationError(ConfigError):
    """
    Exception raised for configuration validation errors.
    
    This includes invalid values, missing required fields, and type mismatches.
    """
    
    @classmethod
    def invalid_value(
        cls,
        field: str,
        value: Any,
        expected: str = "",
        **context: Any
    ) -> "ConfigValidationError":
        """Factory method for invalid value errors."""
        message = f"Invalid value for '{field}': {value}"
        if expected:
            message += f" (expected: {expected})"
        
        return cls(
            message=message,
            error_code=ErrorCodes.INVALID_VALUE,
            is_retryable=False,
            suggested_action=f"Provide a valid value for '{field}'",
            operation_context={"field": field, "value": str(value), **context}
        )
    
    @classmethod
    def missing_field(cls, field: str, **context: Any) -> "ConfigValidationError":
        """Factory method for missing field errors."""
        return cls(
            message=f"Missing required field: '{field}'",
            error_code=ErrorCodes.MISSING_FIELD,
            is_retryable=False,
            suggested_action=f"Provide a value for required field '{field}'",
            operation_context={"field": field, **context}
        )
    
    @classmethod
    def invalid_auth_credentials(cls, auth_type: str, **context: Any) -> "ConfigValidationError":
        """Factory method for authentication credential errors."""
        return cls(
            message=f"Invalid or missing credentials for auth_type '{auth_type}'",
            error_code=ErrorCodes.INVALID_AUTH_CREDENTIALS,
            is_retryable=False,
            suggested_action="Provide username and password for SQL auth, or ensure Windows auth is properly configured",
            operation_context={"auth_type": auth_type, **context}
        )


class ConfigOverrideError(ConfigError):
    """
    Exception raised for configuration override errors.
    
    This includes invalid environment variables and override conflicts.
    """
    
    @classmethod
    def invalid_env_var(cls, var_name: str, value: str, reason: str = "") -> "ConfigOverrideError":
        """Factory method for invalid environment variable errors."""
        message = f"Invalid environment variable '{var_name}': {value}"
        if reason:
            message += f" - {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.ENV_VAR_INVALID,
            is_retryable=False,
            suggested_action=f"Check the value of environment variable '{var_name}'",
            operation_context={"var_name": var_name, "value": value}
        )


# ==================== Database Exceptions ====================


class DatabaseError(SanitizationError):
    """Base exception for all database-related errors."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        is_retryable: bool = False,
        suggested_action: str = "",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, is_retryable, suggested_action, operation_context)


class DatabaseConnectionError(DatabaseError):
    """
    Exception raised for database connection failures.
    
    This includes connection timeouts, authentication failures, and
    server unreachable errors.
    """
    
    @classmethod
    def connection_failed(cls, server: str, database: str, reason: str = "", **context: Any) -> "DatabaseConnectionError":
        """Factory method for general connection failures."""
        message = f"Failed to connect to database '{database}' on server '{server}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.CONN_FAILED,
            is_retryable=False,  # Assume non-retryable unless specified
            suggested_action="Check connection settings and ensure the database server is accessible",
            operation_context={"server": server, "database": database, **context}
        )
    
    @classmethod
    def connection_timeout(cls, server: str, database: str, timeout: int, **context: Any) -> "DatabaseConnectionError":
        """Factory method for connection timeout errors."""
        return cls(
            message=f"Connection timeout after {timeout}s connecting to '{database}' on '{server}'",
            error_code=ErrorCodes.CONN_TIMEOUT,
            is_retryable=True,  # Timeouts are retryable
            suggested_action="Check network connectivity or increase timeout setting",
            operation_context={"server": server, "database": database, "timeout": timeout, **context}
        )
    
    @classmethod
    def auth_failed(cls, server: str, database: str, auth_type: str, **context: Any) -> "DatabaseConnectionError":
        """Factory method for authentication failures."""
        return cls(
            message=f"Authentication failed for '{database}' on '{server}' using {auth_type}",
            error_code=ErrorCodes.AUTH_FAILED,
            is_retryable=False,  # Auth failures are not retryable
            suggested_action="Verify credentials and ensure the user has access to the database",
            operation_context={"server": server, "database": database, "auth_type": auth_type, **context}
        )
    
    @classmethod
    def server_unreachable(cls, server: str, **context: Any) -> "DatabaseConnectionError":
        """Factory method for server unreachable errors."""
        return cls(
            message=f"Database server unreachable: {server}",
            error_code=ErrorCodes.SERVER_UNREACHABLE,
            is_retryable=True,  # Network issues are retryable
            suggested_action="Check network connectivity and server availability",
            operation_context={"server": server, **context}
        )


class DatabaseQueryError(DatabaseError):
    """
    Exception raised for database query execution errors.
    
    This includes syntax errors, permission denied, and query failures.
    """
    
    @classmethod
    def query_failed(cls, query: str, reason: str = "", **context: Any) -> "DatabaseQueryError":
        """Factory method for general query failures."""
        # Truncate query for logging (avoid exposing too much)
        query_preview = query[:100] + "..." if len(query) > 100 else query
        
        message = f"Query execution failed: {reason}" if reason else "Query execution failed"
        
        return cls(
            message=message,
            error_code=ErrorCodes.QUERY_FAILED,
            is_retryable=False,
            suggested_action="Review the query and error details",
            operation_context={"query_preview": query_preview, **context}
        )
    
    @classmethod
    def invalid_syntax(cls, query: str, reason: str = "", **context: Any) -> "DatabaseQueryError":
        """Factory method for SQL syntax errors."""
        query_preview = query[:100] + "..." if len(query) > 100 else query
        
        return cls(
            message=f"Invalid SQL syntax: {reason}" if reason else "Invalid SQL syntax",
            error_code=ErrorCodes.INVALID_SYNTAX,
            is_retryable=False,
            suggested_action="Check SQL syntax and fix the query",
            operation_context={"query_preview": query_preview, **context}
        )
    
    @classmethod
    def permission_denied(cls, operation: str, **context: Any) -> "DatabaseQueryError":
        """Factory method for permission denied errors."""
        return cls(
            message=f"Permission denied for operation: {operation}",
            error_code=ErrorCodes.PERMISSION_DENIED,
            is_retryable=False,
            suggested_action="Ensure the database user has sufficient permissions",
            operation_context={"operation": operation, **context}
        )


class ConnectionPoolError(DatabaseError):
    """
    Exception raised for connection pool management errors.
    
    This includes pool exhaustion and invalid pool state errors.
    """
    
    @classmethod
    def pool_exhausted(cls, pool_size: int, **context: Any) -> "ConnectionPoolError":
        """Factory method for pool exhaustion errors."""
        return cls(
            message=f"Connection pool exhausted (max size: {pool_size})",
            error_code=ErrorCodes.POOL_EXHAUSTED,
            is_retryable=True,  # Can retry when connections are released
            suggested_action="Increase pool size or release connections more frequently",
            operation_context={"pool_size": pool_size, **context}
        )
    
    @classmethod
    def invalid_pool_state(cls, reason: str = "", **context: Any) -> "ConnectionPoolError":
        """Factory method for invalid pool state errors."""
        return cls(
            message=f"Connection pool in invalid state: {reason}" if reason else "Connection pool in invalid state",
            error_code=ErrorCodes.POOL_INVALID_STATE,
            is_retryable=True,
            suggested_action="Reset the connection pool or restart the application",
            operation_context={**context}
        )


class HealthCheckError(DatabaseError):
    """
    Exception raised for database health check failures.
    
    This includes dead connections and unresponsive connections.
    """
    
    @classmethod
    def connection_dead(cls, **context: Any) -> "HealthCheckError":
        """Factory method for dead connection errors."""
        return cls(
            message="Database connection is dead",
            error_code=ErrorCodes.CONN_DEAD,
            is_retryable=True,  # Can retry with a new connection
            suggested_action="Obtain a new connection from the pool",
            operation_context={**context}
        )
    
    @classmethod
    def connection_unresponsive(cls, timeout: int, **context: Any) -> "HealthCheckError":
        """Factory method for unresponsive connection errors."""
        return cls(
            message=f"Database connection unresponsive after {timeout}s",
            error_code=ErrorCodes.CONN_UNRESPONSIVE,
            is_retryable=True,  # Can retry with a new connection
            suggested_action="Obtain a new connection from the pool",
            operation_context={"timeout": timeout, **context}
        )


# ==================== Logging Exceptions ====================


class LoggingError(SanitizationError):
    """Base exception for all logging-related errors."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        is_retryable: bool = False,
        suggested_action: str = "",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, is_retryable, suggested_action, operation_context)


class LoggerConfigurationError(LoggingError):
    """
    Exception raised for logger configuration errors.
    
    This includes invalid handlers, formatters, and log levels.
    """
    
    @classmethod
    def invalid_handler(cls, handler_name: str, reason: str = "", **context: Any) -> "LoggerConfigurationError":
        """Factory method for invalid handler errors."""
        message = f"Invalid logging handler '{handler_name}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.INVALID_HANDLER,
            is_retryable=False,
            suggested_action="Check logging configuration and handler settings",
            operation_context={"handler_name": handler_name, **context}
        )
    
    @classmethod
    def invalid_formatter(cls, formatter_name: str, reason: str = "", **context: Any) -> "LoggerConfigurationError":
        """Factory method for invalid formatter errors."""
        message = f"Invalid logging formatter '{formatter_name}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.INVALID_FORMATTER,
            is_retryable=False,
            suggested_action="Check logging configuration and formatter settings",
            operation_context={"formatter_name": formatter_name, **context}
        )
    
    @classmethod
    def invalid_log_level(cls, level: str, **context: Any) -> "LoggerConfigurationError":
        """Factory method for invalid log level errors."""
        return cls(
            message=f"Invalid log level: {level}",
            error_code=ErrorCodes.INVALID_LOG_LEVEL,
            is_retryable=False,
            suggested_action="Use a valid log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
            operation_context={"level": level, **context}
        )


# ==================== Schema Extraction Exceptions ====================


class SchemaExtractionError(DatabaseError):
    """
    Exception raised for schema metadata extraction errors.
    
    This includes database not found, extraction failures, and invalid metadata.
    """
    
    @classmethod
    def database_not_found(cls, database_name: str, **context: Any) -> "SchemaExtractionError":
        """Factory method for database not found errors."""
        return cls(
            message=f"Database not found: '{database_name}'",
            error_code=ErrorCodes.DB_NOT_FOUND,
            is_retryable=False,
            suggested_action=f"Verify that database '{database_name}' exists and is accessible",
            operation_context={"database_name": database_name, **context}
        )
    
    @classmethod
    def no_tables_found(cls, database_name: str, **context: Any) -> "SchemaExtractionError":
        """Factory method for no tables found warning/error."""
        return cls(
            message=f"No user tables found in database '{database_name}'",
            error_code=ErrorCodes.NO_TABLES_FOUND,
            is_retryable=False,
            suggested_action="Verify that the database contains user tables or check permissions",
            operation_context={"database_name": database_name, **context}
        )
    
    @classmethod
    def extraction_failed(cls, database_name: str, reason: str = "", **context: Any) -> "SchemaExtractionError":
        """Factory method for general schema extraction failures."""
        message = f"Failed to extract schema from database '{database_name}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.SCHEMA_EXTRACTION_FAILED,
            is_retryable=True,  # May be transient
            suggested_action="Check database connectivity and permissions, then retry",
            operation_context={"database_name": database_name, **context}
        )
    
    @classmethod
    def invalid_metadata(cls, reason: str, **context: Any) -> "SchemaExtractionError":
        """Factory method for invalid or malformed metadata errors."""
        return cls(
            message=f"Invalid schema metadata: {reason}",
            error_code=ErrorCodes.INVALID_METADATA,
            is_retryable=False,
            suggested_action="Verify database schema integrity and system table accessibility",
            operation_context={**context}
        )


# ==================== Data Extraction Exceptions ====================


class DataExtractionError(DatabaseError):
    """
    Exception raised for data extraction errors.
    
    This includes failures during batch extraction, pagination errors,
    and data retrieval failures.
    """
    
    @classmethod
    def extraction_failed(
        cls,
        table_name: str,
        reason: str = "",
        **context: Any
    ) -> "DataExtractionError":
        """Factory method for general extraction failures."""
        message = f"Failed to extract data from table '{table_name}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.DATA_EXTRACTION_FAILED,
            is_retryable=True,  # May be transient
            suggested_action="Check database connectivity, table existence, and permissions, then retry",
            operation_context={"table": table_name, **context}
        )
    
    @classmethod
    def table_not_found(cls, schema: str, table: str, **context: Any) -> "DataExtractionError":
        """Factory method for table not found errors."""
        full_name = f"{schema}.{table}"
        return cls(
            message=f"Table not found: '{full_name}'",
            error_code=ErrorCodes.TABLE_NOT_FOUND,
            is_retryable=False,
            suggested_action=f"Verify that table '{full_name}' exists and is accessible",
            operation_context={"schema": schema, "table": table, **context}
        )
    
    @classmethod
    def column_not_found(
        cls,
        schema: str,
        table: str,
        column: str,
        **context: Any
    ) -> "DataExtractionError":
        """Factory method for column not found errors."""
        full_name = f"{schema}.{table}.{column}"
        return cls(
            message=f"Column not found: '{full_name}'",
            error_code=ErrorCodes.COLUMN_NOT_FOUND,
            is_retryable=False,
            suggested_action=f"Verify that column '{column}' exists in table '{schema}.{table}'",
            operation_context={"schema": schema, "table": table, "column": column, **context}
        )
    
    @classmethod
    def invalid_batch_size(cls, batch_size: int, **context: Any) -> "DataExtractionError":
        """Factory method for invalid batch size errors."""
        return cls(
            message=f"Invalid batch size: {batch_size}. Must be between 1 and 100,000",
            error_code=ErrorCodes.INVALID_VALUE,
            is_retryable=False,
            suggested_action="Provide a batch size between 1 and 100,000",
            operation_context={"batch_size": batch_size, **context}
        )


class DataUpdateError(DatabaseError):
    """
    Exception raised for data update errors.
    
    This includes failures during batch updates, validation errors,
    deadlock conditions, and transaction failures.
    """
    
    @classmethod
    def update_failed(
        cls,
        table_name: str,
        reason: str = "",
        **context: Any
    ) -> "DataUpdateError":
        """Factory method for general update failures."""
        message = f"Failed to update data in table '{table_name}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.DATA_UPDATE_FAILED,
            is_retryable=True,  # May be transient
            suggested_action="Check database connectivity, table existence, and permissions, then retry",
            operation_context={"table": table_name, **context}
        )
    
    @classmethod
    def batch_update_failed(
        cls,
        table_name: str,
        batch_number: int,
        reason: str = "",
        **context: Any
    ) -> "DataUpdateError":
        """Factory method for batch update failures."""
        message = f"Batch {batch_number} failed to update table '{table_name}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.UPDATE_BATCH_FAILED,
            is_retryable=True,
            suggested_action="Review the batch data and error details, then retry",
            operation_context={"table": table_name, "batch_number": batch_number, **context}
        )
    
    @classmethod
    def invalid_update_data(
        cls,
        field: str,
        value: Any,
        reason: str = "",
        **context: Any
    ) -> "DataUpdateError":
        """Factory method for invalid update data."""
        message = f"Invalid update data for field '{field}': {value}"
        if reason:
            message += f" - {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.INVALID_UPDATE_DATA,
            is_retryable=False,
            suggested_action=f"Ensure update data for '{field}' matches column constraints",
            operation_context={"field": field, "value": str(value), **context}
        )
    
    @classmethod
    def deadlock_detected(
        cls,
        table_name: str,
        attempt: int,
        **context: Any
    ) -> "DataUpdateError":
        """Factory method for deadlock detection."""
        return cls(
            message=f"Deadlock detected while updating table '{table_name}' (attempt {attempt})",
            error_code=ErrorCodes.DEADLOCK_DETECTED,
            is_retryable=True,
            suggested_action="Operation will be retried automatically",
            operation_context={"table": table_name, "attempt": attempt, **context}
        )
    
    @classmethod
    def deadlock_retry_exhausted(
        cls,
        table_name: str,
        max_attempts: int,
        **context: Any
    ) -> "DataUpdateError":
        """Factory method for exhausted deadlock retries."""
        return cls(
            message=f"Deadlock retry exhausted for table '{table_name}' after {max_attempts} attempts",
            error_code=ErrorCodes.DEADLOCK_RETRY_EXHAUSTED,
            is_retryable=False,
            suggested_action="Reduce concurrent operations or increase retry attempts",
            operation_context={"table": table_name, "max_attempts": max_attempts, **context}
        )
    
    @classmethod
    def invalid_batch_size(cls, batch_size: int, **context: Any) -> "DataUpdateError":
        """Factory method for invalid batch size errors."""
        return cls(
            message=f"Invalid batch size: {batch_size}. Must be between 1 and 100,000",
            error_code=ErrorCodes.INVALID_VALUE,
            is_retryable=False,
            suggested_action="Provide a batch size between 1 and 100,000",
            operation_context={"batch_size": batch_size, **context}
        )


class TransactionError(DatabaseError):
    """
    Exception raised for database transaction errors.
    
    This includes failures during transaction begin, commit, or rollback operations.
    """
    
    @classmethod
    def begin_failed(cls, reason: str = "", **context: Any) -> "TransactionError":
        """Factory method for transaction begin failures."""
        message = "Failed to begin transaction"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.TRANSACTION_BEGIN_FAILED,
            is_retryable=True,
            suggested_action="Check database connection and retry",
            operation_context=context
        )
    
    @classmethod
    def commit_failed(cls, reason: str = "", **context: Any) -> "TransactionError":
        """Factory method for transaction commit failures."""
        message = "Failed to commit transaction"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.TRANSACTION_COMMIT_FAILED,
            is_retryable=False,
            suggested_action="Transaction was rolled back; review the error and retry the operation",
            operation_context=context
        )
    
    @classmethod
    def rollback_failed(cls, reason: str = "", **context: Any) -> "TransactionError":
        """Factory method for transaction rollback failures."""
        message = "Failed to rollback transaction"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.TRANSACTION_ROLLBACK_FAILED,
            is_retryable=False,
            suggested_action="Database may be in inconsistent state; manual intervention required",
            operation_context=context
        )
    
    @classmethod
    def nested_transaction_error(cls, **context: Any) -> "TransactionError":
        """Factory method for nested transaction errors."""
        return cls(
            message="Nested transactions are not supported",
            error_code=ErrorCodes.NESTED_TRANSACTION_ERROR,
            is_retryable=False,
            suggested_action="Ensure only one transaction context is active at a time",
            operation_context=context
        )
    
    @classmethod
    def timeout(cls, timeout_seconds: int, **context: Any) -> "TransactionError":
        """Factory method for transaction timeouts."""
        return cls(
            message=f"Transaction exceeded timeout of {timeout_seconds} seconds",
            error_code=ErrorCodes.TRANSACTION_TIMEOUT,
            is_retryable=False,
            suggested_action="Optimize transaction operations or increase timeout value",
            operation_context={"timeout_seconds": timeout_seconds, **context}
        )
    
    @classmethod
    def savepoint_not_found(cls, savepoint_name: str, **context: Any) -> "TransactionError":
        """Factory method for savepoint not found errors."""
        return cls(
            message=f"Savepoint '{savepoint_name}' not found or already rolled back",
            error_code=ErrorCodes.SAVEPOINT_NOT_FOUND,
            is_retryable=False,
            suggested_action=f"Verify savepoint '{savepoint_name}' exists and has not been rolled back",
            operation_context={"savepoint_name": savepoint_name, **context}
        )
    
    @classmethod
    def savepoint_create_failed(cls, savepoint_name: str, reason: str = "", **context: Any) -> "TransactionError":
        """Factory method for savepoint creation failures."""
        message = f"Failed to create savepoint '{savepoint_name}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.SAVEPOINT_CREATE_FAILED,
            is_retryable=True,
            suggested_action="Check transaction state and retry",
            operation_context={"savepoint_name": savepoint_name, **context}
        )
    
    @classmethod
    def savepoint_rollback_failed(cls, savepoint_name: str, reason: str = "", **context: Any) -> "TransactionError":
        """Factory method for savepoint rollback failures."""
        message = f"Failed to rollback to savepoint '{savepoint_name}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.SAVEPOINT_ROLLBACK_FAILED,
            is_retryable=False,
            suggested_action="Check transaction and savepoint state",
            operation_context={"savepoint_name": savepoint_name, **context}
        )
    
    @classmethod
    def max_nesting_exceeded(cls, max_depth: int = 32, **context: Any) -> "TransactionError":
        """Factory method for max nesting depth exceeded."""
        return cls(
            message=f"Maximum savepoint nesting depth of {max_depth} exceeded",
            error_code=ErrorCodes.MAX_NESTING_EXCEEDED,
            is_retryable=False,
            suggested_action=f"SQL Server supports up to {max_depth} nested savepoints; reduce nesting depth",
            operation_context={"max_depth": max_depth, **context}
        )
    
    @classmethod
    def invalid_savepoint_name(cls, savepoint_name: str, reason: str = "", **context: Any) -> "TransactionError":
        """Factory method for invalid savepoint names."""
        message = f"Invalid savepoint name '{savepoint_name}'"
        if reason:
            message += f": {reason}"
        else:
            message += ": must contain only alphanumeric characters and underscores"
        
        return cls(
            message=message,
            error_code=ErrorCodes.INVALID_SAVEPOINT_NAME,
            is_retryable=False,
            suggested_action="Use only alphanumeric characters and underscores in savepoint names",
            operation_context={"savepoint_name": savepoint_name, **context}
        )
    
    @classmethod
    def invalid_isolation_level(cls, isolation_level: str, **context: Any) -> "TransactionError":
        """Factory method for invalid isolation level."""
        return cls(
            message=f"Invalid transaction isolation level: '{isolation_level}'",
            error_code=ErrorCodes.INVALID_ISOLATION_LEVEL,
            is_retryable=False,
            suggested_action="Use valid isolation level: READ_UNCOMMITTED, READ_COMMITTED, REPEATABLE_READ, SERIALIZABLE, or SNAPSHOT",
            operation_context={"isolation_level": isolation_level, **context}
        )
    
    @classmethod
    def isolation_level_not_supported(cls, isolation_level: str, reason: str = "", **context: Any) -> "TransactionError":
        """Factory method for unsupported isolation levels."""
        message = f"Isolation level '{isolation_level}' not supported"
        if reason:
            message += f": {reason}"
        
        suggested_action = "Check database configuration"
        if isolation_level.upper() == "SNAPSHOT":
            suggested_action = "Enable SNAPSHOT isolation: ALTER DATABASE SET ALLOW_SNAPSHOT_ISOLATION ON"
        
        return cls(
            message=message,
            error_code=ErrorCodes.ISOLATION_LEVEL_NOT_SUPPORTED,
            is_retryable=False,
            suggested_action=suggested_action,
            operation_context={"isolation_level": isolation_level, **context}
        )


# ==================== Dependency Resolution Exceptions ====================


class DependencyResolutionError(SanitizationError):
    """Base exception for all dependency resolution errors."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        is_retryable: bool = False,
        suggested_action: str = "",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, is_retryable, suggested_action, operation_context)


class CircularDependencyError(DependencyResolutionError):
    """
    Exception raised when circular foreign key dependencies are detected.
    
    This exception indicates that a cycle exists in the table dependency graph,
    preventing standard topological sort. The cycle information is included
    to help users understand which tables are involved and plan mitigation.
    """
    
    @classmethod
    def circular_dependency_detected(
        cls,
        cycles: list[list[str]],
        **context: Any
    ) -> "CircularDependencyError":
        """
        Factory method for circular dependency detection.
        
        Args:
            cycles: List of cycles, where each cycle is a list of table names
            **context: Additional context information
            
        Returns:
            CircularDependencyError instance with cycle details
        """
        # Format cycles for readable error message
        cycle_count = len(cycles)
        cycle_descriptions = []
        
        for i, cycle in enumerate(cycles[:3], 1):  # Show up to 3 cycles
            cycle_path = " → ".join(cycle + [cycle[0]])  # Add first table to complete cycle
            cycle_descriptions.append(f"  Cycle {i}: {cycle_path}")
        
        if cycle_count > 3:
            cycle_descriptions.append(f"  ... and {cycle_count - 3} more cycles")
        
        cycle_summary = "\n".join(cycle_descriptions)
        
        message = (
            f"Circular foreign key dependencies detected ({cycle_count} cycle(s)):\n"
            f"{cycle_summary}"
        )
        
        suggested_action = (
            "Options to resolve: "
            "(1) Temporarily disable FK constraints during sanitization, "
            "(2) Process tables in the cycle using multi-stage approach with mapping lookups, "
            "(3) Exclude circular tables from sanitization scope"
        )
        
        return cls(
            message=message,
            error_code=ErrorCodes.CIRCULAR_DEPENDENCY,
            is_retryable=False,
            suggested_action=suggested_action,
            operation_context={"cycles": cycles, "cycle_count": cycle_count, **context}
        )
    
    @classmethod
    def invalid_dependency_graph(
        cls,
        reason: str = "",
        **context: Any
    ) -> "CircularDependencyError":
        """
        Factory method for invalid dependency graph errors.
        
        Args:
            reason: Description of why the graph is invalid
            **context: Additional context information
            
        Returns:
            CircularDependencyError instance
        """
        message = "Invalid dependency graph"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.INVALID_DEPENDENCY_GRAPH,
            is_retryable=False,
            suggested_action="Verify foreign key relationships are consistent and valid",
            operation_context={**context}
        )


# ==================== AI Service Exceptions ====================


class AIServiceError(SanitizationError):
    """Base exception for all AI service-related errors."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        is_retryable: bool = False,
        suggested_action: str = "",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, is_retryable, suggested_action, operation_context)


class APIRequestError(AIServiceError):
    """
    Exception raised for AI API request failures.
    
    This includes network errors, timeouts, server errors, and authentication failures.
    """
    
    @classmethod
    def api_request_failed(
        cls,
        reason: str = "",
        status_code: Optional[int] = None,
        **context: Any
    ) -> "APIRequestError":
        """Factory method for general API request failures."""
        message = "AI API request failed"
        if status_code:
            message += f" (HTTP {status_code})"
        if reason:
            message += f": {reason}"
        
        # Determine if retryable based on status code
        is_retryable = status_code in [500, 502, 503, 504] if status_code else False
        
        return cls(
            message=message,
            error_code=ErrorCodes.AI_API_REQUEST_FAILED,
            is_retryable=is_retryable,
            suggested_action="Check API endpoint, network connectivity, and retry",
            operation_context={"status_code": status_code, "reason": reason, **context}
        )
    
    @classmethod
    def api_timeout(
        cls,
        timeout_seconds: int,
        **context: Any
    ) -> "APIRequestError":
        """Factory method for API timeout errors."""
        return cls(
            message=f"AI API request timed out after {timeout_seconds}s",
            error_code=ErrorCodes.AI_API_TIMEOUT,
            is_retryable=True,  # Timeouts are retryable
            suggested_action="Increase timeout setting or check API service status",
            operation_context={"timeout_seconds": timeout_seconds, **context}
        )
    
    @classmethod
    def api_quota_exceeded(
        cls,
        retry_after: Optional[int] = None,
        **context: Any
    ) -> "APIRequestError":
        """Factory method for API quota/rate limit exceeded errors."""
        message = "AI API quota exceeded (HTTP 429)"
        if retry_after:
            message += f", retry after {retry_after}s"
        
        suggested_action = "Wait for quota reset"
        if retry_after:
            suggested_action += f" (retry after {retry_after}s)"
        else:
            suggested_action += " or manually create PII configuration"
        
        return cls(
            message=message,
            error_code=ErrorCodes.AI_API_QUOTA_EXCEEDED,
            is_retryable=True,  # Can retry after waiting
            suggested_action=suggested_action,
            operation_context={"retry_after": retry_after, **context}
        )
    
    @classmethod
    def authentication_failed(
        cls,
        reason: str = "",
        **context: Any
    ) -> "APIRequestError":
        """Factory method for AI API authentication failures."""
        message = "AI API authentication failed"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.AI_AUTH_FAILED,
            is_retryable=False,  # Auth failures are not retryable
            suggested_action="Verify GITHUB_COPILOT_API_KEY environment variable is set correctly",
            operation_context={"reason": reason, **context}
        )
    
    @classmethod
    def network_error(
        cls,
        reason: str = "",
        **context: Any
    ) -> "APIRequestError":
        """Factory method for network/connectivity errors."""
        message = "Network error while connecting to AI API"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.AI_NETWORK_ERROR,
            is_retryable=True,  # Network errors are retryable
            suggested_action="Check internet connectivity and firewall settings",
            operation_context={"reason": reason, **context}
        )


class APIResponseError(AIServiceError):
    """
    Exception raised for AI API response validation errors.
    
    This includes malformed JSON, unexpected structure, and missing required fields.
    """
    
    @classmethod
    def invalid_response(
        cls,
        reason: str = "",
        response_preview: str = "",
        **context: Any
    ) -> "APIResponseError":
        """Factory method for invalid API response errors."""
        message = "AI API returned invalid response"
        if reason:
            message += f": {reason}"
        
        ctx = {**context}
        if response_preview:
            # Truncate preview to avoid exposing too much data
            ctx["response_preview"] = response_preview[:200]
        if reason:
            ctx["reason"] = reason
        
        return cls(
            message=message,
            error_code=ErrorCodes.AI_INVALID_RESPONSE,
            is_retryable=False,
            suggested_action="Check API documentation for expected response format",
            operation_context=ctx
        )
    
    @classmethod
    def parsing_failed(
        cls,
        reason: str = "",
        **context: Any
    ) -> "APIResponseError":
        """Factory method for response parsing errors."""
        message = "Failed to parse AI API response"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.AI_RESPONSE_PARSING_FAILED,
            is_retryable=False,
            suggested_action="Validate response JSON structure and field types",
            operation_context={"reason": reason, **context}
        )
    
    @classmethod
    def schema_too_large(
        cls,
        schema_size: int,
        max_size: int,
        **context: Any
    ) -> "APIResponseError":
        """Factory method for schema size limit errors."""
        return cls(
            message=f"Schema metadata too large ({schema_size} chars, max: {max_size})",
            error_code=ErrorCodes.AI_SCHEMA_TOO_LARGE,
            is_retryable=False,
            suggested_action="Process schema in batches or reduce schema complexity",
            operation_context={"schema_size": schema_size, "max_size": max_size, **context}
        )


# ==================== Data Masking Exceptions ====================


class MaskingError(SanitizationError):
    """
    Exception raised for errors during PII data masking.
    
    This includes type mismatches, length violations, NULL constraint violations,
    and failures in masking strategy implementation.
    """
    
    @classmethod
    def masking_failed(
        cls,
        column: str,
        pii_type: str,
        reason: str = "",
        **context: Any
    ) -> "MaskingError":
        """Factory method for general masking failures."""
        message = f"Failed to mask column '{column}' (type: {pii_type})"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.MASKING_FAILED,
            is_retryable=False,
            suggested_action="Check masking strategy implementation and column metadata",
            operation_context={"column": column, "pii_type": pii_type, "reason": reason, **context}
        )
    
    @classmethod
    def type_mismatch(
        cls,
        column: str,
        expected_type: str,
        actual_type: str,
        **context: Any
    ) -> "MaskingError":
        """Factory method for data type mismatch errors."""
        return cls(
            message=f"Type mismatch for column '{column}': expected {expected_type}, got {actual_type}",
            error_code=ErrorCodes.MASKING_TYPE_MISMATCH,
            is_retryable=False,
            suggested_action=f"Ensure masker returns {expected_type} values for {expected_type} columns",
            operation_context={
                "column": column,
                "expected_type": expected_type,
                "actual_type": actual_type,
                **context
            }
        )
    
    @classmethod
    def length_exceeded(
        cls,
        column: str,
        value_length: int,
        max_length: int,
        **context: Any
    ) -> "MaskingError":
        """Factory method for length constraint violations."""
        return cls(
            message=f"Masked value for column '{column}' exceeds max length ({value_length} > {max_length})",
            error_code=ErrorCodes.MASKING_LENGTH_EXCEEDED,
            is_retryable=False,
            suggested_action=f"Ensure masked values fit within column length ({max_length})",
            operation_context={
                "column": column,
                "value_length": value_length,
                "max_length": max_length,
                **context
            }
        )
    
    @classmethod
    def null_constraint_violation(
        cls,
        column: str,
        **context: Any
    ) -> "MaskingError":
        """Factory method for NULL constraint violations."""
        return cls(
            message=f"NULL value encountered for NOT NULL column '{column}'",
            error_code=ErrorCodes.MASKING_NULL_CONSTRAINT_VIOLATION,
            is_retryable=False,
            suggested_action="Ensure data doesn't contain NULLs or configure MASK strategy for NULL values",
            operation_context={"column": column, **context}
        )
    
    @classmethod
    def strategy_not_implemented(
        cls,
        masker_class: str,
        **context: Any
    ) -> "MaskingError":
        """Factory method for unimplemented masking strategy errors."""
        return cls(
            message=f"Masker '{masker_class}' does not implement required mask() method",
            error_code=ErrorCodes.MASKING_STRATEGY_NOT_IMPLEMENTED,
            is_retryable=False,
            suggested_action=f"Implement abstract mask() method in {masker_class} class",
            operation_context={"masker_class": masker_class, **context}
        )
    
    @classmethod
    def invalid_format(
        cls,
        column: str,
        value: str,
        expected_format: str,
        **context: Any
    ) -> "MaskingError":
        """Factory method for invalid format errors."""
        return cls(
            message=f"Invalid format for column '{column}': expected {expected_format}, got '{value}'",
            error_code=ErrorCodes.MASKING_INVALID_FORMAT,
            is_retryable=False,
            suggested_action=f"Ensure masked values match {expected_format} format",
            operation_context={
                "column": column,
                "value": value,
                "expected_format": expected_format,
                **context
            }
        )
    
    @classmethod
    def collision_detected(
        cls,
        column: str,
        original_value: str,
        masked_value: str,
        existing_mapping: str,
        **context: Any
    ) -> "MaskingError":
        """Factory method for masking collision errors."""
        return cls(
            message=f"Collision detected for column '{column}': multiple original values map to '{masked_value}'",
            error_code=ErrorCodes.MASKING_COLLISION_DETECTED,
            is_retryable=False,
            suggested_action="Use stronger hash or add uniqueness constraint to masked values",
            operation_context={
                "column": column,
                "original_value": original_value[:50],  # Truncate for logging
                "masked_value": masked_value,
                "existing_mapping": existing_mapping,
                **context
            }
        )
    
    @classmethod
    def invalid_masking_strategy(
        cls,
        strategy: str,
        **context: Any
    ) -> "MaskingError":
        """Factory method for invalid masking strategy configuration."""
        return cls(
            message=f"Invalid masking strategy: '{strategy}'",
            error_code=ErrorCodes.INVALID_MASKING_STRATEGY,
            is_retryable=False,
            suggested_action="Use valid masking strategy: PRESERVE, MASK, or RANDOMIZE",
            operation_context={"strategy": strategy, **context}
        )
    
    @classmethod
    def unsupported_pii_type(
        cls,
        pii_type: str,
        **context: Any
    ) -> "MaskingError":
        """Factory method for unsupported PII type errors."""
        return cls(
            message=f"Unsupported PII type: '{pii_type}'",
            error_code=ErrorCodes.UNSUPPORTED_PII_TYPE,
            is_retryable=False,
            suggested_action="Use supported PII types (email, phone, name, ssn, etc.) or implement custom masker",
            operation_context={"pii_type": pii_type, **context}
        )
    
    @classmethod
    def masker_not_found(
        cls,
        pii_type: str,
        **context: Any
    ) -> "MaskingError":
        """Factory method for masker not found errors."""
        return cls(
            message=f"No masker registered for PII type: '{pii_type}'",
            error_code=ErrorCodes.MASKER_NOT_FOUND,
            is_retryable=False,
            suggested_action=f"Register masker for PII type '{pii_type}' in masker factory",
            operation_context={"pii_type": pii_type, **context}
        )


# ==================== Mapping Exceptions ====================


class MappingError(SanitizationError):
    """
    Exception raised for mapping table operation errors.
    
    This includes storage failures, lookup errors, encryption errors,
    and schema/table creation failures.
    """
    
    def __init__(
        self,
        message: str,
        error_code: str,
        is_retryable: bool = False,
        suggested_action: str = "",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, is_retryable, suggested_action, operation_context)
    
    @classmethod
    def storage_failed(
        cls,
        table_name: str,
        reason: str = "",
        **context: Any
    ) -> "MappingError":
        """Factory method for mapping storage failures."""
        message = f"Failed to store mappings for table '{table_name}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.MAPPING_STORAGE_FAILED,
            is_retryable=True,  # Storage failures may be transient
            suggested_action="Check database connectivity, transaction log space, and disk space",
            operation_context={"table_name": table_name, "reason": reason, **context}
        )
    
    @classmethod
    def schema_creation_failed(
        cls,
        schema_name: str,
        reason: str = "",
        **context: Any
    ) -> "MappingError":
        """Factory method for schema creation failures."""
        message = f"Failed to create schema '{schema_name}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.MAPPING_SCHEMA_CREATION_FAILED,
            is_retryable=False,  # Likely a permissions issue
            suggested_action="Ensure the database user has CREATE SCHEMA permission",
            operation_context={"schema_name": schema_name, "reason": reason, **context}
        )
    
    @classmethod
    def table_creation_failed(
        cls,
        table_name: str,
        schema_name: str,
        reason: str = "",
        **context: Any
    ) -> "MappingError":
        """Factory method for table creation failures."""
        full_name = f"{schema_name}.{table_name}"
        message = f"Failed to create mapping table '{full_name}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.MAPPING_TABLE_CREATION_FAILED,
            is_retryable=False,
            suggested_action="Ensure the database user has CREATE TABLE permission and sufficient disk space",
            operation_context={
                "table_name": table_name,
                "schema_name": schema_name,
                "full_name": full_name,
                "reason": reason,
                **context
            }
        )
    
    @classmethod
    def index_creation_failed(
        cls,
        index_name: str,
        table_name: str,
        reason: str = "",
        **context: Any
    ) -> "MappingError":
        """Factory method for index creation failures."""
        message = f"Failed to create index '{index_name}' on table '{table_name}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.MAPPING_INDEX_CREATION_FAILED,
            is_retryable=False,
            suggested_action="Check index definition and ensure sufficient disk space",
            operation_context={
                "index_name": index_name,
                "table_name": table_name,
                "reason": reason,
                **context
            }
        )
    
    @classmethod
    def duplicate_entry(
        cls,
        operation_id: str,
        table_name: str,
        column_name: str,
        **context: Any
    ) -> "MappingError":
        """Factory method for duplicate mapping entry errors."""
        return cls(
            message=f"Duplicate mapping entry for {table_name}.{column_name} in operation {operation_id}",
            error_code=ErrorCodes.MAPPING_DUPLICATE_ENTRY,
            is_retryable=False,  # Duplicates should be skipped, not retried
            suggested_action="This is expected during idempotent re-runs; entry will be skipped",
            operation_context={
                "operation_id": operation_id,
                "table_name": table_name,
                "column_name": column_name,
                **context
            }
        )
    
    @classmethod
    def not_found(
        cls,
        operation_id: str,
        table_name: str = "",
        column_name: str = "",
        **context: Any
    ) -> "MappingError":
        """Factory method for mapping not found errors."""
        message = f"No mapping found for operation {operation_id}"
        if table_name and column_name:
            message += f" (table: {table_name}, column: {column_name})"
        elif table_name:
            message += f" (table: {table_name})"
        
        return cls(
            message=message,
            error_code=ErrorCodes.MAPPING_NOT_FOUND,
            is_retryable=False,
            suggested_action="Ensure the sanitization operation completed and mappings were stored",
            operation_context={
                "operation_id": operation_id,
                "table_name": table_name,
                "column_name": column_name,
                **context
            }
        )
    
    @classmethod
    def lookup_failed(
        cls,
        reason: str = "",
        **context: Any
    ) -> "MappingError":
        """Factory method for mapping lookup failures."""
        message = "Failed to lookup mapping"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.MAPPING_LOOKUP_FAILED,
            is_retryable=True,  # Lookup failures may be transient
            suggested_action="Check database connectivity and ensure mapping table exists",
            operation_context={"reason": reason, **context}
        )
    
    @classmethod
    def table_not_found(
        cls,
        table_name: str,
        schema_name: str,
        **context: Any
    ) -> "MappingError":
        """Factory method for mapping table not found errors."""
        full_name = f"{schema_name}.{table_name}"
        return cls(
            message=f"Mapping table '{full_name}' does not exist",
            error_code=ErrorCodes.MAPPING_TABLE_NOT_FOUND,
            is_retryable=False,
            suggested_action="Ensure the mapping table is created during MappingManager initialization",
            operation_context={
                "table_name": table_name,
                "schema_name": schema_name,
                "full_name": full_name,
                **context
            }
        )
    
    @classmethod
    def encryption_failed(
        cls,
        reason: str = "",
        **context: Any
    ) -> "MappingError":
        """Factory method for encryption failures."""
        message = "Failed to encrypt mapping value"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.MAPPING_ENCRYPTION_FAILED,
            is_retryable=False,  # Encryption failures are configuration issues
            suggested_action="Check encryption key configuration and ensure cryptography library is installed",
            operation_context={"reason": reason, **context}
        )
    
    @classmethod
    def decryption_failed(
        cls,
        reason: str = "",
        **context: Any
    ) -> "MappingError":
        """Factory method for decryption failures."""
        message = "Failed to decrypt mapping value"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.MAPPING_DECRYPTION_FAILED,
            is_retryable=False,
            suggested_action="Check encryption key matches the key used for encryption",
            operation_context={"reason": reason, **context}
        )
    
    @classmethod
    def encryption_key_missing(
        cls,
        **context: Any
    ) -> "MappingError":
        """Factory method for missing encryption key errors."""
        return cls(
            message="Encryption key not found in environment variables",
            error_code=ErrorCodes.MAPPING_ENCRYPTION_KEY_MISSING,
            is_retryable=False,
            suggested_action="Set SANITIZATION_MAPPING_ENCRYPTION_KEY environment variable with a valid Fernet key",
            operation_context={**context}
        )


# ==================== Desensitization Exceptions ====================


class DesensitizationError(SanitizationError):
    """
    Exception raised for desensitization (reverse sanitization) errors.
    
    This includes mapping not found, decryption failures, value mismatches,
    restore failures, and validation errors.
    """
    
    def __init__(
        self,
        message: str,
        error_code: str,
        is_retryable: bool = False,
        suggested_action: str = "",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, is_retryable, suggested_action, operation_context)
    
    @classmethod
    def mapping_not_found(
        cls,
        operation_id: str,
        table_name: str = "",
        column_name: str = "",
        **context: Any
    ) -> "DesensitizationError":
        """Factory method for mapping not found errors."""
        message = f"No mappings found for operation {operation_id}"
        if table_name and column_name:
            message += f" (table: {table_name}, column: {column_name})"
        elif table_name:
            message += f" (table: {table_name})"
        
        return cls(
            message=message,
            error_code=ErrorCodes.DESENSITIZATION_MAPPING_NOT_FOUND,
            is_retryable=False,
            suggested_action="Verify operation_id and ensure sanitization completed successfully with mappings stored",
            operation_context={
                "operation_id": operation_id,
                "table_name": table_name,
                "column_name": column_name,
                **context
            }
        )
    
    @classmethod
    def decryption_failed(
        cls,
        table_name: str,
        column_name: str,
        reason: str = "",
        **context: Any
    ) -> "DesensitizationError":
        """Factory method for decryption failures during desensitization."""
        message = f"Failed to decrypt original value for {table_name}.{column_name}"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.DESENSITIZATION_DECRYPTION_FAILED,
            is_retryable=False,
            suggested_action="Verify encryption key matches the key used during sanitization",
            operation_context={
                "table_name": table_name,
                "column_name": column_name,
                "reason": reason,
                **context
            }
        )
    
    @classmethod
    def value_mismatch(
        cls,
        table_name: str,
        column_name: str,
        pk_value: Any,
        expected_masked: str,
        actual_current: str,
        **context: Any
    ) -> "DesensitizationError":
        """Factory method for value mismatch errors (database modified since sanitization)."""
        return cls(
            message=(
                f"Value mismatch in {table_name}.{column_name} for PK={pk_value}: "
                f"expected masked value '{expected_masked[:50]}...', found '{actual_current[:50]}...'"
            ),
            error_code=ErrorCodes.DESENSITIZATION_VALUE_MISMATCH,
            is_retryable=False,
            suggested_action="Database may have been modified since sanitization. Consider re-sanitizing or use --force option.",
            operation_context={
                "table_name": table_name,
                "column_name": column_name,
                "pk_value": str(pk_value),
                "expected_masked_preview": expected_masked[:50],
                "actual_current_preview": actual_current[:50],
                **context
            }
        )
    
    @classmethod
    def restore_failed(
        cls,
        table_name: str,
        reason: str = "",
        **context: Any
    ) -> "DesensitizationError":
        """Factory method for table restoration failures."""
        message = f"Failed to restore original values for table '{table_name}'"
        if reason:
            message += f": {reason}"
        
        return cls(
            message=message,
            error_code=ErrorCodes.DESENSITIZATION_RESTORE_FAILED,
            is_retryable=True,  # May be transient (deadlock, network)
            suggested_action="Check database connectivity, transaction log space, and review error details",
            operation_context={"table_name": table_name, "reason": reason, **context}
        )
    
    @classmethod
    def validation_failed(
        cls,
        reason: str,
        **context: Any
    ) -> "DesensitizationError":
        """Factory method for validation failures before desensitization."""
        return cls(
            message=f"Desensitization validation failed: {reason}",
            error_code=ErrorCodes.DESENSITIZATION_VALIDATION_FAILED,
            is_retryable=False,
            suggested_action="Review validation errors and resolve issues before attempting desensitization",
            operation_context={"reason": reason, **context}
        )
    
    @classmethod
    def incomplete_mappings(
        cls,
        operation_id: str,
        missing_tables: Dict[str, List[str]],
        **context: Any
    ) -> "DesensitizationError":
        """Factory method for incomplete mapping coverage."""
        missing_summary = ", ".join(
            f"{table}({', '.join(cols)})" for table, cols in missing_tables.items()
        )
        return cls(
            message=f"Incomplete mappings for operation {operation_id}: {missing_summary}",
            error_code=ErrorCodes.DESENSITIZATION_INCOMPLETE_MAPPINGS,
            is_retryable=False,
            suggested_action="Ensure sanitization completed for all requested tables or use selective restore",
            operation_context={
                "operation_id": operation_id,
                "missing_tables": missing_tables,
                **context
            }
        )
    
    @classmethod
    def operation_not_found(
        cls,
        operation_id: str,
        **context: Any
    ) -> "DesensitizationError":
        """Factory method for operation ID not found in mapping table."""
        return cls(
            message=f"Operation ID {operation_id} not found in mapping table",
            error_code=ErrorCodes.DESENSITIZATION_OPERATION_NOT_FOUND,
            is_retryable=False,
            suggested_action="Verify operation_id is correct and sanitization completed successfully",
            operation_context={"operation_id": operation_id, **context}
        )


