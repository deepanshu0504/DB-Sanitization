"""Correlation ID management for request tracing across operations.

This module provides context managers and utilities for managing correlation IDs
throughout the sanitization workflow. Correlation IDs enable tracing related log
entries across multi-step operations.

Classes:
    CorrelationContext: Context manager for setting correlation IDs

Functions:
    get_correlation_id: Get current correlation ID
    set_correlation_id: Set correlation ID for current context
    clear_correlation_id: Clear correlation ID from current context
    new_correlation_id: Generate a new UUID correlation ID

Examples:
    >>> from src.logging.correlation import correlation_context, get_correlation_id
    >>> 
    >>> with correlation_context("operation-123"):
    ...     print(get_correlation_id())
    ...     # All logs in this block will have correlation_id="operation-123"
    operation-123

Thread Safety:
    Uses contextvars for thread-safe and async-compatible context isolation.
    Each thread/task maintains its own correlation ID.
"""

import uuid
import logging
from contextvars import ContextVar
from typing import Optional, Generator
from contextlib import contextmanager


# Context variable for storing correlation ID
# This is thread-safe and async-compatible
_correlation_id: ContextVar[Optional[str]] = ContextVar(
    'correlation_id',
    default=None
)

logger = logging.getLogger(__name__)


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID from context.
    
    Returns:
        Current correlation ID, or None if not set
        
    Examples:
        >>> from src.logging.correlation import set_correlation_id, get_correlation_id
        >>> set_correlation_id("test-123")
        >>> get_correlation_id()
        'test-123'
        >>> clear_correlation_id()
        >>> get_correlation_id() is None
        True
    """
    return _correlation_id.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID for the current context.
    
    Args:
        correlation_id: Correlation ID to set
        
    Examples:
        >>> set_correlation_id("request-456")
        >>> get_correlation_id()
        'request-456'
    """
    _correlation_id.set(correlation_id)


def clear_correlation_id() -> None:
    """Clear the correlation ID from the current context.
    
    Examples:
        >>> set_correlation_id("test-123")
        >>> clear_correlation_id()
        >>> get_correlation_id() is None
        True
    """
    _correlation_id.set(None)


def new_correlation_id() -> str:
    """Generate a new UUID-based correlation ID.
    
    Returns:
        New UUID correlation ID as string
        
    Examples:
        >>> correlation_id = new_correlation_id()
        >>> len(correlation_id) == 36  # UUID format: 8-4-4-4-12
        True
        >>> '-' in correlation_id
        True
    """
    return str(uuid.uuid4())


@contextmanager
def correlation_context(
    correlation_id: Optional[str] = None,
    auto_generate: bool = True
) -> Generator[str, None, None]:
    """Context manager for setting a correlation ID for a block of code.
    
    The correlation ID is automatically cleared when exiting the context,
    restoring the previous value if one existed.
    
    Args:
        correlation_id: Correlation ID to use (generates new if None and auto_generate=True)
        auto_generate: Whether to auto-generate ID if none provided
        
    Yields:
        The correlation ID being used in this context
        
    Examples:
        >>> with correlation_context("operation-123") as corr_id:
        ...     print(f"Using correlation ID: {corr_id}")
        ...     print(f"Current ID: {get_correlation_id()}")
        Using correlation ID: operation-123
        Current ID: operation-123
        
        >>> # Auto-generate ID
        >>> with correlation_context() as corr_id:
        ...     print(f"Generated: {corr_id}")
        ...     print(len(corr_id))
        Generated: ...
        36
        
        >>> # Nested contexts
        >>> with correlation_context("outer") as outer_id:
        ...     print(f"Outer: {get_correlation_id()}")
        ...     with correlation_context("inner") as inner_id:
        ...         print(f"Inner: {get_correlation_id()}")
        ...     print(f"Back to outer: {get_correlation_id()}")
        Outer: outer
        Inner: inner
        Back to outer: outer
    """
    # Save previous correlation ID (if any)
    previous_id = _correlation_id.get()
    
    # Determine correlation ID to use
    if correlation_id is None and auto_generate:
        correlation_id = new_correlation_id()
        logger.debug(f"Auto-generated correlation ID: {correlation_id}")
    elif correlation_id is None:
        # No ID provided and auto-generate is False
        correlation_id = previous_id or "NO_CORRELATION"
    
    # Set new correlation ID
    _correlation_id.set(correlation_id)
    
    try:
        yield correlation_id
    finally:
        # Restore previous correlation ID
        _correlation_id.set(previous_id)


class CorrelationContext:
    """Class-based correlation context manager.
    
    Alternative to the function-based correlation_context for cases where
    a class is preferred (e.g., for explicit start/stop control).
    
    Attributes:
        correlation_id: Current correlation ID
        previous_id: Previous correlation ID (restored on exit)
        
    Examples:
        >>> context = CorrelationContext("operation-789")
        >>> context.start()
        >>> print(get_correlation_id())
        operation-789
        >>> context.stop()
        >>> print(get_correlation_id())
        None
        
        >>> # Use as context manager
        >>> with CorrelationContext("test-context") as corr_id:
        ...     print(get_correlation_id())
        test-context
    """
    
    def __init__(
        self,
        correlation_id: Optional[str] = None,
        auto_generate: bool = True
    ):
        """Initialize correlation context.
        
        Args:
            correlation_id: Correlation ID to use
            auto_generate: Whether to auto-generate ID if none provided
            
        Examples:
            >>> context = CorrelationContext()
            >>> len(context.correlation_id) == 36  # Auto-generated UUID
            True
            
            >>> context = CorrelationContext("custom-id")
            >>> context.correlation_id
            'custom-id'
        """
        if correlation_id is None and auto_generate:
            self.correlation_id = new_correlation_id()
        elif correlation_id is None:
            self.correlation_id = "NO_CORRELATION"
        else:
            self.correlation_id = correlation_id
        
        self.previous_id: Optional[str] = None
    
    def start(self) -> str:
        """Start the correlation context.
        
        Returns:
            The correlation ID being used
            
        Examples:
            >>> context = CorrelationContext("test-123")
            >>> context.start()
            'test-123'
            >>> get_correlation_id()
            'test-123'
            >>> context.stop()
        """
        self.previous_id = _correlation_id.get()
        _correlation_id.set(self.correlation_id)
        return self.correlation_id
    
    def stop(self) -> None:
        """Stop the correlation context and restore previous ID.
        
        Examples:
            >>> set_correlation_id("outer")
            >>> context = CorrelationContext("inner")
            >>> context.start()
            'inner'
            >>> get_correlation_id()
            'inner'
            >>> context.stop()
            >>> get_correlation_id()
            'outer'
        """
        _correlation_id.set(self.previous_id)
        self.previous_id = None
    
    def __enter__(self) -> str:
        """Enter correlation context.
        
        Returns:
            The correlation ID being used
        """
        return self.start()
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit correlation context.
        
        Args:
            exc_type: Exception type if exception occurred
            exc_val: Exception value if exception occurred
            exc_tb: Exception traceback if exception occurred
        """
        self.stop()
    
    def __repr__(self) -> str:
        """String representation of correlation context.
        
        Returns:
            String representation
            
        Examples:
            >>> context = CorrelationContext("test-123")
            >>> repr(context)
            "CorrelationContext(correlation_id='test-123')"
        """
        return f"CorrelationContext(correlation_id='{self.correlation_id}')"


def inject_correlation_id(record: logging.LogRecord) -> logging.LogRecord:
    """Inject correlation ID into a log record.
    
    This is a utility function for manually adding correlation IDs to
    log records. Normally this is handled automatically by filters.
    
    Args:
        record: Log record to modify
        
    Returns:
        Modified log record (same object, modified in-place)
        
    Examples:
        >>> record = logging.LogRecord(
        ...     name="test", level=logging.INFO, pathname="", lineno=0,
        ...     msg="Test", args=(), exc_info=None
        ... )
        >>> set_correlation_id("test-123")
        >>> inject_correlation_id(record)
        <LogRecord: ...>
        >>> record.correlation_id
        'test-123'
    """
    correlation_id = get_correlation_id()
    if correlation_id:
        record.correlation_id = correlation_id
    return record
