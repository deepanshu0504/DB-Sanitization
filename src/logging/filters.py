"""Log filters for PII redaction and message processing.

This module provides logging filters that automatically redact PII from
log messages before they are written to handlers.

Classes:
    PIIRedactionFilter: Filter that redacts PII from log messages
    CorrelationFilter: Filter that ensures correlation IDs are present

Examples:
    >>> import logging
    >>> from src.logging.log_config import PIIRedactionConfig
    >>> 
    >>> logger = logging.getLogger(__name__)
    >>> pii_filter = PIIRedactionFilter(PIIRedactionConfig())
    >>> logger.addFilter(pii_filter)
    >>> logger.info("Email: user@example.com")
    # Logs: "Email: ***@***"

Security:
    This filter is critical for preventing PII leakage in logs.
    Always apply to all handlers in production.

Thread Safety:
    All filters are thread-safe and can be used across multiple threads.
"""

import logging
from typing import Dict, Tuple, Pattern

from src.logging.log_config import PIIRedactionConfig
from src.logging.pii_patterns import get_active_patterns, redact_message


class PIIRedactionFilter(logging.Filter):
    """Filter that automatically redacts PII from log messages.
    
    Scans log messages for common PII patterns (email, phone, SSN, etc.)
    and replaces them with safe placeholders before output.
    
    Attributes:
        config: PII redaction configuration
        patterns: Active compiled regex patterns
        
    Examples:
        >>> from src.logging.log_config import PIIRedactionConfig
        >>> config = PIIRedactionConfig(
        ...     enabled=True,
        ...     redact_emails=True,
        ...     redact_phones=True
        ... )
        >>> pii_filter = PIIRedactionFilter(config)
        >>> record = logging.LogRecord(
        ...     name="test", level=logging.INFO, pathname="", lineno=0,
        ...     msg="Contact: user@example.com or 555-123-4567",
        ...     args=(), exc_info=None
        ... )
        >>> pii_filter.filter(record)
        True
        >>> record.getMessage()
        'Contact: ***@*** or ***-***-****'
    """
    
    def __init__(self, config: PIIRedactionConfig):
        """Initialize PII redaction filter.
        
        Args:
            config: PII redaction configuration
            
        Examples:
            >>> config = PIIRedactionConfig(enabled=True)
            >>> pii_filter = PIIRedactionFilter(config)
        """
        super().__init__()
        self.config = config
        self.patterns: Dict[str, Tuple[Pattern, str]] = {}
        
        # Load active patterns based on configuration
        if config.enabled:
            self.patterns = get_active_patterns(
                redact_emails=config.redact_emails,
                redact_phones=config.redact_phones,
                redact_ssn=config.redact_ssn,
                redact_credit_cards=config.redact_credit_cards,
                custom_patterns=config.patterns
            )
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Filter log record and redact PII from message.
        
        Modifies the record's message in-place to redact PII.
        
        Args:
            record: Log record to filter
            
        Returns:
            True to allow the record to be logged (always returns True)
            
        Examples:
            >>> config = PIIRedactionConfig(enabled=True, redact_emails=True)
            >>> pii_filter = PIIRedactionFilter(config)
            >>> record = logging.LogRecord(
            ...     name="test", level=logging.INFO, pathname="", lineno=0,
            ...     msg="Email: john.doe@example.com", args=(), exc_info=None
            ... )
            >>> pii_filter.filter(record)
            True
            >>> "***@***" in record.getMessage()
            True
        """
        if not self.config.enabled or not self.patterns:
            return True
        
        # Get the formatted message
        try:
            original_message = record.getMessage()
        except Exception:
            # If getMessage() fails, work with the raw msg
            original_message = str(record.msg)
        
        # Redact PII from the message
        redacted_message = redact_message(original_message, self.patterns)
        
        # Update the record's message
        # We modify both msg and args to ensure the redacted message is used
        record.msg = redacted_message
        record.args = ()  # Clear args since message is already formatted
        
        # Also redact from exc_text if present
        if hasattr(record, 'exc_text') and record.exc_text:
            record.exc_text = redact_message(record.exc_text, self.patterns)
        
        # Redact from any string fields in extra dict
        self._redact_extra_fields(record)
        
        return True
    
    def _redact_extra_fields(self, record: logging.LogRecord) -> None:
        """Redact PII from extra fields in the log record.
        
        Args:
            record: Log record to process
            
        Examples:
            >>> config = PIIRedactionConfig(enabled=True, redact_emails=True)
            >>> pii_filter = PIIRedactionFilter(config)
            >>> record = logging.LogRecord(
            ...     name="test", level=logging.INFO, pathname="", lineno=0,
            ...     msg="Test", args=(), exc_info=None
            ... )
            >>> record.user_email = "john@example.com"
            >>> pii_filter._redact_extra_fields(record)
            >>> record.user_email
            '***@***'
        """
        # Standard LogRecord attributes to skip
        standard_attrs = {
            'name', 'msg', 'args', 'created', 'filename', 'funcName', 
            'levelname', 'levelno', 'lineno', 'module', 'msecs', 'message',
            'pathname', 'process', 'processName', 'relativeCreated', 'thread',
            'threadName', 'exc_info', 'exc_text', 'stack_info', 'asctime',
            'taskName', 'correlation_id'  # Don't redact correlation ID
        }
        
        for attr_name in dir(record):
            # Skip standard attributes, private attributes, and methods
            if (attr_name in standard_attrs or 
                attr_name.startswith('_') or 
                callable(getattr(record, attr_name))):
                continue
            
            try:
                attr_value = getattr(record, attr_name)
                
                # Redact string values
                if isinstance(attr_value, str):
                    redacted_value = redact_message(attr_value, self.patterns)
                    setattr(record, attr_name, redacted_value)
                
                # Redact values in dictionaries
                elif isinstance(attr_value, dict):
                    self._redact_dict(attr_value)
                
                # Redact values in lists
                elif isinstance(attr_value, list):
                    self._redact_list(attr_value)
                    
            except (AttributeError, TypeError):
                # Skip attributes that can't be accessed or modified
                continue
    
    def _redact_dict(self, data: dict) -> None:
        """Redact PII from dictionary values in-place.
        
        Args:
            data: Dictionary to redact
            
        Examples:
            >>> config = PIIRedactionConfig(enabled=True, redact_emails=True)
            >>> pii_filter = PIIRedactionFilter(config)
            >>> data = {"email": "user@example.com", "count": 5}
            >>> pii_filter._redact_dict(data)
            >>> data["email"]
            '***@***'
            >>> data["count"]
            5
        """
        for key, value in data.items():
            if isinstance(value, str):
                data[key] = redact_message(value, self.patterns)
            elif isinstance(value, dict):
                self._redact_dict(value)
            elif isinstance(value, list):
                self._redact_list(value)
    
    def _redact_list(self, data: list) -> None:
        """Redact PII from list items in-place.
        
        Args:
            data: List to redact
            
        Examples:
            >>> config = PIIRedactionConfig(enabled=True, redact_emails=True)
            >>> pii_filter = PIIRedactionFilter(config)
            >>> data = ["user@example.com", "plain text", 123]
            >>> pii_filter._redact_list(data)
            >>> data[0]
            '***@***'
            >>> data[1]
            'plain text'
        """
        for i, item in enumerate(data):
            if isinstance(item, str):
                data[i] = redact_message(item, self.patterns)
            elif isinstance(item, dict):
                self._redact_dict(item)
            elif isinstance(item, list):
                self._redact_list(item)


class CorrelationFilter(logging.Filter):
    """Filter that ensures correlation IDs are present in log records.
    
    If a correlation ID is not already present in the record, this filter
    can add a default value or retrieve one from thread-local context.
    
    Examples:
        >>> corr_filter = CorrelationFilter(default_id="NO_CORRELATION")
        >>> record = logging.LogRecord(
        ...     name="test", level=logging.INFO, pathname="", lineno=0,
        ...     msg="Test", args=(), exc_info=None
        ... )
        >>> corr_filter.filter(record)
        True
        >>> hasattr(record, "correlation_id")
        True
    """
    
    def __init__(self, default_id: str = "NO_CORRELATION"):
        """Initialize correlation filter.
        
        Args:
            default_id: Default correlation ID if none is present
            
        Examples:
            >>> corr_filter = CorrelationFilter(default_id="NONE")
        """
        super().__init__()
        self.default_id = default_id
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Add correlation ID to record if not present.
        
        Args:
            record: Log record to filter
            
        Returns:
            True to allow the record to be logged
            
        Examples:
            >>> corr_filter = CorrelationFilter()
            >>> record = logging.LogRecord(
            ...     name="test", level=logging.INFO, pathname="", lineno=0,
            ...     msg="Test", args=(), exc_info=None
            ... )
            >>> corr_filter.filter(record)
            True
            >>> record.correlation_id
            'NO_CORRELATION'
        """
        if not hasattr(record, 'correlation_id') or not record.correlation_id:
            # Try to get from context (will be implemented in correlation.py)
            try:
                from src.logging.correlation import get_correlation_id
                correlation_id = get_correlation_id()
                if correlation_id:
                    record.correlation_id = correlation_id
                else:
                    record.correlation_id = self.default_id
            except ImportError:
                # Fallback if correlation module not available yet
                record.correlation_id = self.default_id
        
        return True


class LevelRangeFilter(logging.Filter):
    """Filter that only allows log records within a level range.
    
    Useful for sending different log levels to different handlers
    (e.g., INFO to console, ERROR to file).
    
    Examples:
        >>> # Only allow WARNING and ERROR (not CRITICAL)
        >>> level_filter = LevelRangeFilter(
        ...     min_level=logging.WARNING,
        ...     max_level=logging.ERROR
        ... )
    """
    
    def __init__(
        self,
        min_level: int = logging.DEBUG,
        max_level: int = logging.CRITICAL
    ):
        """Initialize level range filter.
        
        Args:
            min_level: Minimum log level to allow (inclusive)
            max_level: Maximum log level to allow (inclusive)
            
        Examples:
            >>> # Only INFO and WARNING
            >>> level_filter = LevelRangeFilter(
            ...     min_level=logging.INFO,
            ...     max_level=logging.WARNING
            ... )
        """
        super().__init__()
        self.min_level = min_level
        self.max_level = max_level
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Check if record's level is within the allowed range.
        
        Args:
            record: Log record to filter
            
        Returns:
            True if record level is within range, False otherwise
            
        Examples:
            >>> level_filter = LevelRangeFilter(
            ...     min_level=logging.INFO,
            ...     max_level=logging.WARNING
            ... )
            >>> debug_record = logging.LogRecord(
            ...     name="test", level=logging.DEBUG, pathname="", lineno=0,
            ...     msg="Debug", args=(), exc_info=None
            ... )
            >>> level_filter.filter(debug_record)
            False
            >>> info_record = logging.LogRecord(
            ...     name="test", level=logging.INFO, pathname="", lineno=0,
            ...     msg="Info", args=(), exc_info=None
            ... )
            >>> level_filter.filter(info_record)
            True
        """
        return self.min_level <= record.levelno <= self.max_level
