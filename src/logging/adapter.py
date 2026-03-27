"""Logging adapters with convenience methods for common patterns.

This module provides LoggerAdapter subclasses that add contextual information
and convenience methods for structured logging.

Classes:
    ContextLoggerAdapter: Adapter with operation context and convenience methods
    
Examples:
    >>> from src.logging.adapter import get_context_logger
    >>> from src.logging.correlation import correlation_context
    >>> 
    >>> with correlation_context("operation-123"):
    ...     logger = get_context_logger(__name__, operation="sanitize_table")
    ...     logger.log_operation_start(table="Customers")
    ...     # Perform operation
    ...     logger.log_operation_success(rows_processed=1000)

Thread Safety:
    All adapters are thread-safe when used with thread-safe loggers."""

import logging
import time
from typing import Any, Dict, MutableMapping, Optional, Tuple

from src.logging.correlation import get_correlation_id


class ContextLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that adds contextual information to log records.
    
    Automatically includes correlation ID and operation context in all logs.
    Provides convenience methods for common logging patterns.
    
    Attributes:
        extra: Dictionary of extra fields to include in all log records
        
    Examples:
        >>> logger = logging.getLogger(__name__)
        >>> adapter = ContextLoggerAdapter(
        ...     logger,
        ...     extra={"operation": "sanitize", "table": "Customers"}
        ... )
        >>> adapter.info("Processing data")
        # Logs include operation and table fields
    """
    
    def __init__(
        self,
        logger: logging.Logger,
        extra: Optional[Dict[str, Any]] = None
    ):
        """Initialize context logger adapter.
        
        Args:
            logger: Underlying logger instance
            extra: Extra fields to include in all logs
            
        Examples:
            >>> import logging
            >>> logger = logging.getLogger("test")
            >>> adapter = ContextLoggerAdapter(logger, {"service": "sanitization"})
        """
        super().__init__(logger, extra or {})
    
    def process(
        self,
        msg: str,
        kwargs: MutableMapping[str, Any]
    ) -> Tuple[str, MutableMapping[str, Any]]:
        """Process log record to add contextual information.
        
        Args:
            msg: Log message
            kwargs: Keyword arguments from log call
            
        Returns:
            Tuple of (message, updated kwargs)
            
        Examples:
            >>> adapter = ContextLoggerAdapter(logging.getLogger("test"))
            >>> msg, kwargs = adapter.process("Test", {})
            >>> "extra" in kwargs
            True
        """
        # Ensure 'extra' exists in kwargs
        if 'extra' not in kwargs:
            kwargs['extra'] = {}
        
        # Add correlation ID from context
        correlation_id = get_correlation_id()
        if correlation_id:
            kwargs['extra']['correlation_id'] = correlation_id
        
        # Merge adapter's extra fields
        kwargs['extra'].update(self.extra)
        
        return msg, kwargs
    
    def log_operation_start(
        self,
        operation: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """Log the start of an operation.
        
        Args:
            operation: Operation name (defaults to adapter's operation if set)
            **kwargs: Additional context fields
            
        Examples:
            >>> adapter = ContextLoggerAdapter(
            ...     logging.getLogger("test"),
            ...     extra={"operation": "sanitize"}
            ... )
            >>> adapter.log_operation_start(table="Customers", rows=1000)
        """
        op_name = operation or self.extra.get('operation', 'unknown')
        context = self._format_context(kwargs)
        self.info(f"Starting operation: {op_name}{context}")
    
    def log_operation_end(
        self,
        operation: Optional[str] = None,
        duration_ms: Optional[float] = None,
        **kwargs: Any
    ) -> None:
        """Log the successful completion of an operation.
        
        Args:
            operation: Operation name
            duration_ms: Duration in milliseconds
            **kwargs: Additional context fields (e.g., rows_processed)
            
        Examples:
            >>> adapter = ContextLoggerAdapter(logging.getLogger("test"))
            >>> adapter.log_operation_end(
            ...     operation="sanitize",
            ...     duration_ms=1234.5,
            ...     rows_processed=1000
            ... )
        """
        op_name = operation or self.extra.get('operation', 'unknown')
        context = self._format_context(kwargs)
        
        if duration_ms is not None:
            self.info(
                f"Completed operation: {op_name} "
                f"(duration: {duration_ms:.2f}ms){context}"
            )
        else:
            self.info(f"Completed operation: {op_name}{context}")
    
    def log_operation_success(
        self,
        operation: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """Log successful operation completion.
        
        Alias for log_operation_end for semantic clarity.
        
        Args:
            operation: Operation name
            **kwargs: Additional context fields
            
        Examples:
            >>> adapter = ContextLoggerAdapter(logging.getLogger("test"))
            >>> adapter.log_operation_success(rows_updated=500)
        """
        self.log_operation_end(operation=operation, **kwargs)
    
    def log_operation_failure(
        self,
        operation: Optional[str] = None,
        error: Optional[Exception] = None,
        **kwargs: Any
    ) -> None:
        """Log operation failure.
        
        Args:
            operation: Operation name
            error: Exception that caused the failure
            **kwargs: Additional context fields
            
        Examples:
            >>> adapter = ContextLoggerAdapter(logging.getLogger("test"))
            >>> try:
            ...     raise ValueError("Test error")
            ... except ValueError as e:
            ...     adapter.log_operation_failure(error=e, table="Customers")
        """
        op_name = operation or self.extra.get('operation', 'unknown')
        context = self._format_context(kwargs)
        
        if error:
            self.error(
                f"Operation failed: {op_name} - {type(error).__name__}: {error}{context}",
                exc_info=True
            )
        else:
            self.error(f"Operation failed: {op_name}{context}")
    
    def log_progress(
        self,
        current: int,
        total: int,
        operation: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """Log operation progress.
        
        Args:
            current: Current progress count
            total: Total count
            operation: Operation name
            **kwargs: Additional context fields
            
        Examples:
            >>> adapter = ContextLoggerAdapter(logging.getLogger("test"))
            >>> adapter.log_progress(500, 1000, table="Customers")
        """
        op_name = operation or self.extra.get('operation', 'unknown')
        percentage = (current / total * 100) if total > 0 else 0
        context = self._format_context(kwargs)
        
        self.info(
            f"Progress {op_name}: {current}/{total} ({percentage:.1f}%){context}"
        )
    
    def log_metric(
        self,
        metric_name: str,
        value: Any,
        unit: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """Log a metric value.
        
        Args:
            metric_name: Name of the metric
            value: Metric value
            unit: Optional unit (e.g., "ms", "rows", "bytes")
            **kwargs: Additional context fields
            
        Examples:
            >>> adapter = ContextLoggerAdapter(logging.getLogger("test"))
            >>> adapter.log_metric("rows_processed", 1000, unit="rows")
            >>> adapter.log_metric("duration", 1234.5, unit="ms")
        """
        context = self._format_context(kwargs)
        unit_str = f" {unit}" if unit else ""
        self.info(f"Metric {metric_name}: {value}{unit_str}{context}")
    
    def log_error_with_context(
        self,
        message: str,
        error: Optional[Exception] = None,
        **kwargs: Any
    ) -> None:
        """Log an error with additional context.
        
        Args:
            message: Error message
            error: Optional exception
            **kwargs: Additional context fields
            
        Examples:
            >>> adapter = ContextLoggerAdapter(logging.getLogger("test"))
            >>> try:
            ...     raise ValueError("Test error")
            ... except ValueError as e:
            ...     adapter.log_error_with_context(
            ...         "Failed to process record",
            ...         error=e,
            ...         table="Customers",
            ...         row_id=123
            ...     )
        """
        context = self._format_context(kwargs)
        
        if error:
            self.error(
                f"{message} - {type(error).__name__}: {error}{context}",
                exc_info=True
            )
        else:
            self.error(f"{message}{context}")
    
    def log_warning_with_context(
        self,
        message: str,
        **kwargs: Any
    ) -> None:
        """Log a warning with additional context.
        
        Args:
            message: Warning message
            **kwargs: Additional context fields
            
        Examples:
            >>> adapter = ContextLoggerAdapter(logging.getLogger("test"))
            >>> adapter.log_warning_with_context(
            ...     "Skipping invalid record",
            ...     row_id=456,
            ...     reason="missing required field"
            ... )
        """
        context = self._format_context(kwargs)
        self.warning(f"{message}{context}")
    
    def _format_context(self, context: Dict[str, Any]) -> str:
        """Format context dictionary for inclusion in log message.
        
        Args:
            context: Dictionary of context fields
            
        Returns:
            Formatted context string
            
        Examples:
            >>> adapter = ContextLoggerAdapter(logging.getLogger("test"))
            >>> adapter._format_context({"table": "Customers", "rows": 100})
            ' [table=Customers, rows=100]'
            >>> adapter._format_context({})
            ''
        """
        if not context:
            return ""
        
        items = [f"{k}={v}" for k, v in context.items()]
        return f" [{', '.join(items)}]"


class TimedOperation:
    """Context manager for timing operations with automatic logging.
    
    Records operation duration and logs start/end with a ContextLoggerAdapter.
    
    Attributes:
        logger: Logger adapter to use
        operation: Operation name
        context: Additional context fields
        start_time: Operation start timestamp
        
    Examples:
        >>> logger = get_context_logger(__name__)
        >>> with TimedOperation(logger, "sanitize_table", table="Customers"):
        ...     # Perform operation
        ...     pass
        # Logs: "Starting operation: sanitize_table [table=Customers]"
        # Logs: "Completed operation: sanitize_table (duration: 123.45ms) [table=Customers]"
    """
    
    def __init__(
        self,
        logger: ContextLoggerAdapter,
        operation: str,
        **context: Any
    ):
        """Initialize timed operation.
        
        Args:
            logger: Logger adapter to use
            operation: Operation name
            **context: Additional context fields
            
        Examples:
            >>> adapter = ContextLoggerAdapter(logging.getLogger("test"))
            >>> timer = TimedOperation(adapter, "sanitize", table="Users")
        """
        self.logger = logger
        self.operation = operation
        self.context = context
        self.start_time: Optional[float] = None
    
    def __enter__(self) -> "TimedOperation":
        """Enter context and log operation start.
        
        Returns:
            Self for context manager protocol
        """
        self.start_time = time.perf_counter()
        self.logger.log_operation_start(self.operation, **self.context)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context and log operation end/failure.
        
        Args:
            exc_type: Exception type if exception occurred
            exc_val: Exception value if exception occurred
            exc_tb: Exception traceback if exception occurred
        """
        duration_ms = (time.perf_counter() - self.start_time) * 1000
        
        if exc_type is None:
            # Successful completion
            self.logger.log_operation_end(
                self.operation,
                duration_ms=duration_ms,
                **self.context
            )
        else:
            # Operation failed
            self.logger.log_operation_failure(
                self.operation,
                error=exc_val,
                duration_ms=duration_ms,
                **self.context
            )


def get_context_logger(
    name: str,
    **extra: Any
) -> ContextLoggerAdapter:
    """Get a context logger adapter.
    
    Convenience function to create ContextLoggerAdapter instances.
    
    Args:
        name: Logger name (typically __name__)
        **extra: Extra fields to include in all logs
        
    Returns:
        ContextLoggerAdapter instance
        
    Examples:
        >>> logger = get_context_logger(__name__, operation="sanitize")
        >>> logger.info("Operation started")
        
        >>> with correlation_context("op-123"):
        ...     logger = get_context_logger(__name__, table="Customers")
        ...     logger.log_operation_start()
    
    Thread Safety:
        Thread-safe.
    """
    from src.logging.logger import get_logger
    
    base_logger = get_logger(name)
    return ContextLoggerAdapter(base_logger, extra=extra)