"""Structured logging module for database sanitization framework.

This module provides comprehensive logging capabilities with JSON formatting,
automatic PII redaction, correlation ID tracking, and multiple output handlers.

Main Components:
    - LogConfig: Configuration models for logging setup
    - SanitizationLogger: Central logger manager (singleton)
    - PIIRedactionFilter: Automatic PII removal from logs
    - JSONFormatter: Structured JSON log formatting
    - CorrelationContext: Context manager for operation tracking
    - ContextLoggerAdapter: Logger with convenience methods

Quick Start:
    >>> from src.logging import setup_logging, get_logger, correlation_context
    >>> from src.logging.log_config import LogConfig, HandlerConfig
    >>> 
    >>> # Setup logging
    >>> config = LogConfig(
    ...     level="INFO",
    ...     handlers=[
    ...         HandlerConfig(type="console"),
    ...         HandlerConfig(type="file", file_path="logs/app.log")
    ...     ]
    ... )
    >>> setup_logging(config)
    >>> 
    >>> # Use logging with correlation
    >>> with correlation_context("operation-123"):
    ...     logger = get_logger(__name__)
    ...     logger.info("Processing data", extra={"table": "Customers"})

Features:
    - JSON-formatted structured logs
    - Automatic PII redaction (email, phone, SSN, credit cards)
    - Correlation ID tracking for multi-step operations
    - Console and rotating file handlers
    - Thread-safe operation
    - Configurable via Pydantic models or JSON files

Security:
    All logs are automatically scanned for PII patterns and redacted
    before output. Patterns match: email, phone, SSN, credit cards,
    API keys, and IP addresses.

Thread Safety:
    All components are thread-safe and can be used across multiple threads.

Examples:
    Basic usage:
        >>> logger = get_logger(__name__)
        >>> logger.info("Application started")
        >>> logger.error("Failed to connect", exc_info=True)
    
    With correlation IDs:
        >>> from src.logging import correlation_context
        >>> with correlation_context("request-123"):
        ...     logger.info("Processing request")
        ...     # All logs will include correlation_id="request-123"
    
    With context adapter:
        >>> from src.logging import get_context_logger
        >>> logger = get_context_logger(__name__, operation="sanitize")
        >>> logger.log_operation_start(table="Customers")
        >>> # Perform operation
        >>> logger.log_operation_success(rows_processed=1000)
    
    Timed operations:
        >>> from src.logging import get_context_logger, TimedOperation
        >>> logger = get_context_logger(__name__)
        >>> with TimedOperation(logger, "sanitize_table", table="Users"):
        ...     # Perform operation
        ...     pass
        # Logs: "Starting operation: sanitize_table [table=Users]"
        # Logs: "Completed operation: sanitize_table (duration: 123.45ms) [table=Users]"
"""

# Core logging setup
from src.logging.logger import (
    SanitizationLogger,
    setup_logging,
    get_logger,
    shutdown_logging,
)

# Configuration models
from src.logging.log_config import (
    LogConfig,
    HandlerConfig,
    PIIRedactionConfig,
    LogLevel,
    HandlerType,
)

# Correlation tracking
from src.logging.correlation import (
    correlation_context,
    CorrelationContext,
    get_correlation_id,
    set_correlation_id,
    clear_correlation_id,
    new_correlation_id,
)

# Context logger and utilities
from src.logging.adapter import (
    ContextLoggerAdapter,
    TimedOperation,
    get_context_logger,
)

# Formatters (advanced usage)
from src.logging.formatters import (
    JSONFormatter,
    ColoredConsoleFormatter,
)

# Filters (advanced usage)
from src.logging.filters import (
    PIIRedactionFilter,
    CorrelationFilter,
    LevelRangeFilter,
)

# PII patterns (advanced usage)
from src.logging.pii_patterns import (
    DEFAULT_PATTERNS,
    get_active_patterns,
    redact_message,
)


__all__ = [
    # Core functions
    "setup_logging",
    "get_logger",
    "shutdown_logging",
    "get_context_logger",
    
    # Configuration
    "LogConfig",
    "HandlerConfig",
    "PIIRedactionConfig",
    "LogLevel",
    "HandlerType",
    
    # Correlation
    "correlation_context",
    "CorrelationContext",
    "get_correlation_id",
    "set_correlation_id",
    "clear_correlation_id",
    "new_correlation_id",
    
    # Adapters and utilities
    "ContextLoggerAdapter",
    "TimedOperation",
    
    # Advanced: Formatters
    "JSONFormatter",
    "ColoredConsoleFormatter",
    
    # Advanced: Filters
    "PIIRedactionFilter",
    "CorrelationFilter",
    "LevelRangeFilter",
    
    # Advanced: PII patterns
    "DEFAULT_PATTERNS",
    "get_active_patterns",
    "redact_message",
    
    # Advanced: Manager
    "SanitizationLogger",
]


# Version
__version__ = "1.0.0"
