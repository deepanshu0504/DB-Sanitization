"""Log formatters for structured output.

This module provides custom log formatters including JSON formatting
for machine-readable structured logs.

Classes:
    JSONFormatter: Formats log records as JSON

Examples:
    >>> import logging
    >>> from logging import StreamHandler
    >>> handler = StreamHandler()
    >>> handler.setFormatter(JSONFormatter())
    >>> logger = logging.getLogger(__name__)
    >>> logger.addHandler(handler)

Thread Safety:
    All formatters are thread-safe and can be used across multiple threads.
"""

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """Formatter that outputs log records as JSON.
    
    Produces structured JSON logs with consistent fields:
    - timestamp: ISO 8601 formatted UTC timestamp
    - level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - logger: Logger name (module path)
    - message: Formatted log message
    - correlation_id: Correlation ID if present in extra fields
    - extra: Any additional fields from log record's extra dict
    - exception: Exception information if present (type, message, traceback)
    
    Attributes:
        include_fields: Set of additional LogRecord fields to include
        
    Examples:
        >>> formatter = JSONFormatter()
        >>> handler = logging.StreamHandler()
        >>> handler.setFormatter(formatter)
        >>> logger = logging.getLogger("test")
        >>> logger.addHandler(handler)
        >>> logger.info("Test message", extra={"correlation_id": "123"})
        # Outputs: {"timestamp":"2026-03-26T10:00:00.000Z","level":"INFO",...}
    """
    
    # Standard LogRecord attributes to exclude from extra fields
    EXCLUDE_FIELDS = {
        'name', 'msg', 'args', 'created', 'filename', 'funcName', 'levelname',
        'levelno', 'lineno', 'module', 'msecs', 'message', 'pathname',
        'process', 'processName', 'relativeCreated', 'thread', 'threadName',
        'exc_info', 'exc_text', 'stack_info', 'asctime', 'taskName'
    }
    
    def __init__(
        self,
        include_fields: Optional[set] = None,
        ensure_ascii: bool = False
    ):
        """Initialize JSON formatter.
        
        Args:
            include_fields: Additional LogRecord fields to include
            ensure_ascii: Whether to ensure ASCII output (escape Unicode)
            
        Examples:
            >>> formatter = JSONFormatter(include_fields={'process', 'thread'})
        """
        super().__init__()
        self.include_fields = include_fields or set()
        self.ensure_ascii = ensure_ascii
    
    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as JSON.
        
        Args:
            record: Log record to format
            
        Returns:
            JSON-formatted log string
            
        Examples:
            >>> record = logging.LogRecord(
            ...     name="test", level=logging.INFO, pathname="", lineno=0,
            ...     msg="Test", args=(), exc_info=None
            ... )
            >>> formatter = JSONFormatter()
            >>> output = formatter.format(record)
            >>> "timestamp" in output and "level" in output
            True
        """
        # Build base log entry
        log_entry: Dict[str, Any] = {
            "timestamp": self._format_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add correlation ID if present
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id:
            log_entry["correlation_id"] = correlation_id
        
        # Add file location information for ERROR and above
        if record.levelno >= logging.ERROR:
            log_entry["location"] = {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            }
        
        # Add exception information if present
        if record.exc_info:
            log_entry["exception"] = self._format_exception(record)
        
        # Add any extra fields from the log record
        extra_fields = self._extract_extra_fields(record)
        if extra_fields:
            log_entry["extra"] = extra_fields
        
        # Add requested additional fields
        for field in self.include_fields:
            if hasattr(record, field) and field not in log_entry:
                log_entry[field] = getattr(record, field)
        
        # Convert to JSON
        try:
            return json.dumps(
                log_entry,
                ensure_ascii=self.ensure_ascii,
                default=str  # Convert non-serializable objects to string
            )
        except (TypeError, ValueError) as e:
            # Fallback if JSON serialization fails
            return json.dumps({
                "timestamp": self._format_timestamp(record.created),
                "level": "ERROR",
                "logger": __name__,
                "message": f"Failed to format log record: {e}",
                "original_message": str(record.getMessage()),
            })
    
    def _format_timestamp(self, created: float) -> str:
        """Format timestamp as ISO 8601 UTC.
        
        Args:
            created: Unix timestamp from log record
            
        Returns:
            ISO 8601 formatted timestamp string
            
        Examples:
            >>> formatter = JSONFormatter()
            >>> timestamp = formatter._format_timestamp(1711447200.123)
            >>> timestamp.endswith('Z')
            True
        """
        dt = datetime.fromtimestamp(created, tz=timezone.utc)
        # Format: 2026-03-26T10:30:45.123Z
        return dt.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    
    def _format_exception(self, record: logging.LogRecord) -> Dict[str, Any]:
        """Format exception information.
        
        Args:
            record: Log record containing exception info
            
        Returns:
            Dictionary with exception details
            
        Examples:
            >>> try:
            ...     raise ValueError("Test error")
            ... except ValueError:
            ...     import sys
            ...     exc_info = sys.exc_info()
            >>> record = logging.LogRecord(
            ...     name="test", level=logging.ERROR, pathname="", lineno=0,
            ...     msg="Error occurred", args=(), exc_info=exc_info
            ... )
            >>> formatter = JSONFormatter()
            >>> exc_dict = formatter._format_exception(record)
            >>> "type" in exc_dict and "message" in exc_dict
            True
        """
        exc_type, exc_value, exc_tb = record.exc_info
        
        exception_info = {
            "type": exc_type.__name__ if exc_type else "Unknown",
            "message": str(exc_value) if exc_value else "",
        }
        
        # Add traceback for ERROR and above
        if record.levelno >= logging.ERROR and exc_tb:
            exception_info["traceback"] = [
                line.strip() 
                for line in traceback.format_tb(exc_tb)
            ]
        
        return exception_info
    
    def _extract_extra_fields(self, record: logging.LogRecord) -> Dict[str, Any]:
        """Extract extra fields from log record.
        
        Args:
            record: Log record
            
        Returns:
            Dictionary of extra fields not part of standard LogRecord
            
        Examples:
            >>> record = logging.LogRecord(
            ...     name="test", level=logging.INFO, pathname="", lineno=0,
            ...     msg="Test", args=(), exc_info=None
            ... )
            >>> record.custom_field = "custom_value"
            >>> formatter = JSONFormatter()
            >>> extra = formatter._extract_extra_fields(record)
            >>> extra.get("custom_field")
            'custom_value'
        """
        extra = {}
        
        for key, value in record.__dict__.items():
            # Skip standard fields, private fields, and correlation_id (handled separately)
            if (key not in self.EXCLUDE_FIELDS and 
                not key.startswith('_') and 
                key != 'correlation_id'):
                
                # Only include serializable values
                try:
                    json.dumps(value)
                    extra[key] = value
                except (TypeError, ValueError):
                    # Convert non-serializable to string
                    extra[key] = str(value)
        
        return extra


class ColoredConsoleFormatter(logging.Formatter):
    """Formatter with color coding for console output.
    
    Adds ANSI color codes to console output for better readability.
    Only use for console/terminal output, not for file logs.
    
    Examples:
        >>> formatter = ColoredConsoleFormatter()
        >>> handler = logging.StreamHandler()
        >>> handler.setFormatter(formatter)
    """
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'
    
    def __init__(self, fmt: Optional[str] = None, use_colors: bool = True):
        """Initialize colored formatter.
        
        Args:
            fmt: Format string (uses default if None)
            use_colors: Whether to use color codes
        """
        super().__init__(
            fmt or '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.use_colors = use_colors
    
    def format(self, record: logging.LogRecord) -> str:
        """Format record with color codes.
        
        Args:
            record: Log record to format
            
        Returns:
            Formatted log string with color codes
        """
        if self.use_colors and record.levelname in self.COLORS:
            # Add color to level name
            record.levelname = (
                f"{self.COLORS[record.levelname]}"
                f"{record.levelname}{self.RESET}"
            )
        
        return super().format(record)
