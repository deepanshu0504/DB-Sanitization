"""Central logging manager for the sanitization framework.

This module provides a singleton logger manager that configures and maintains
the logging system with JSON formatting, PII redaction, and correlation tracking.

Classes:
    SanitizationLogger: Singleton logger manager

Functions:
    get_logger: Get a configured logger instance
    setup_logging: Initialize logging system from configuration

Examples:
    >>> from src.logging.logger import setup_logging, get_logger
    >>> from src.logging.log_config import LogConfig
    >>> 
    >>> config = LogConfig(level="INFO")
    >>> setup_logging(config)
    >>> logger = get_logger(__name__)
    >>> logger.info("Application started")

Thread Safety:
    The SanitizationLogger singleton uses double-checked locking for
    thread-safe initialization. All methods are thread-safe.
"""

import logging
import logging.handlers
import threading
from pathlib import Path
from typing import Optional, Dict, List

from src.logging.log_config import LogConfig, HandlerType, HandlerConfig
from src.logging.formatters import JSONFormatter, ColoredConsoleFormatter
from src.logging.filters import PIIRedactionFilter, CorrelationFilter


class SanitizationLogger:
    """Singleton logger manager for the sanitization framework.
    
    Configures and manages all loggers with structured logging, PII redaction,
    and correlation ID tracking. Implements thread-safe singleton pattern.
    
    Attributes:
        config: Logging configuration
        handlers: Dictionary of configured handlers by name
        pii_filter: Shared PII redaction filter instance
        correlation_filter: Shared correlation filter instance
        
    Examples:
        >>> from src.logging.log_config import LogConfig, HandlerConfig
        >>> config = LogConfig(
        ...     level="INFO",
        ...     handlers=[HandlerConfig(type="console")]
        ... )
        >>> logger_manager = SanitizationLogger()
        >>> logger_manager.configure(config)
        >>> logger = logger_manager.get_logger("test")
        >>> logger.info("Test message")
    
    Thread Safety:
        All public methods are thread-safe and can be called from multiple threads.
    """
    
    _instance: Optional["SanitizationLogger"] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> "SanitizationLogger":
        """Create or return singleton instance.
        
        Uses double-checked locking for thread-safe singleton creation.
        
        Returns:
            Singleton SanitizationLogger instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize logger manager (only runs once for singleton)."""
        if self._initialized:
            return
        
        self.config: Optional[LogConfig] = None
        self.handlers: Dict[str, logging.Handler] = {}
        self.pii_filter: Optional[PIIRedactionFilter] = None
        self.correlation_filter: Optional[CorrelationFilter] = None
        self._configured_loggers: Dict[str, logging.Logger] = {}
        self._handler_lock = threading.Lock()
        self._initialized = True
    
    def configure(self, config: LogConfig) -> None:
        """Configure the logging system.
        
        Sets up handlers, formatters, and filters based on configuration.
        Can be called multiple times to reconfigure.
        
        Args:
            config: Logging configuration
            
        Examples:
            >>> from src.logging.log_config import LogConfig
            >>> logger_manager = SanitizationLogger()
            >>> config = LogConfig(level="DEBUG")
            >>> logger_manager.configure(config)
        
        Thread Safety:
            Thread-safe. Reconfiguration will affect all existing loggers.
        """
        with self._handler_lock:
            # Shutdown existing handlers
            self.shutdown()
            
            # Store new configuration
            self.config = config
            
            # Create filters
            self.pii_filter = PIIRedactionFilter(config.pii_redaction)
            self.correlation_filter = CorrelationFilter()
            
            # Create handlers based on configuration
            for handler_config in config.handlers:
                handler = self._create_handler(handler_config)
                handler_name = f"{handler_config.type.value}_{id(handler)}"
                self.handlers[handler_name] = handler
            
            # Reconfigure existing loggers
            for logger_name, logger in self._configured_loggers.items():
                self._apply_configuration(logger)
    
    def _create_handler(self, config: HandlerConfig) -> logging.Handler:
        """Create a logging handler from configuration.
        
        Args:
            config: Handler configuration
            
        Returns:
            Configured logging handler
            
        Raises:
            ValueError: If handler configuration is invalid
            
        Examples:
            >>> from src.logging.log_config import HandlerConfig
            >>> logger_manager = SanitizationLogger()
            >>> handler_config = HandlerConfig(type="console")
            >>> handler = logger_manager._create_handler(handler_config)
            >>> isinstance(handler, logging.StreamHandler)
            True
        """
        if config.type == HandlerType.CONSOLE:
            handler = logging.StreamHandler()
            
            # Use colored formatter for console if not JSON
            if not config.format_json:
                formatter = ColoredConsoleFormatter()
            else:
                formatter = JSONFormatter()
                
        elif config.type == HandlerType.FILE:
            if not config.file_path:
                raise ValueError("file_path required for file handlers")
            
            # Ensure directory exists
            log_file = Path(config.file_path)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Create rotating file handler with both time and size rotation
            handler = logging.handlers.RotatingFileHandler(
                filename=str(log_file),
                maxBytes=config.max_bytes,
                backupCount=config.backup_count,
                encoding='utf-8'
            )
            
            # Use JSON formatter for file logs
            formatter = JSONFormatter()
        else:
            raise ValueError(f"Unsupported handler type: {config.type}")
        
        # Set formatter
        handler.setFormatter(formatter)
        
        # Add filters
        if self.pii_filter:
            handler.addFilter(self.pii_filter)
        if self.correlation_filter:
            handler.addFilter(self.correlation_filter)
        
        return handler
    
    def get_logger(self, name: str) -> logging.Logger:
        """Get a configured logger instance.
        
        Args:
            name: Logger name (typically __name__ of calling module)
            
        Returns:
            Configured logger instance
            
        Examples:
            >>> logger_manager = SanitizationLogger()
            >>> logger = logger_manager.get_logger("my_module")
            >>> logger.name
            'my_module'
        
        Thread Safety:
            Thread-safe. Can be called concurrently from multiple threads.
        """
        # Get or create logger
        logger = logging.getLogger(name)
        
        # Track configured loggers
        if name not in self._configured_loggers:
            with self._handler_lock:
                if name not in self._configured_loggers:
                    self._configured_loggers[name] = logger
                    
                    # Apply configuration if available
                    if self.config:
                        self._apply_configuration(logger)
        
        return logger
    
    def _apply_configuration(self, logger: logging.Logger) -> None:
        """Apply configuration to a logger.
        
        Args:
            logger: Logger to configure
            
        Examples:
            >>> logger_manager = SanitizationLogger()
            >>> logger = logging.getLogger("test")
            >>> logger_manager._apply_configuration(logger)
        """
        if not self.config:
            return
        
        # Set log level
        logger.setLevel(getattr(logging, self.config.level))
        
        # Remove existing handlers
        logger.handlers.clear()
        
        # Add configured handlers
        for handler in self.handlers.values():
            logger.addHandler(handler)
        
        # Don't propagate to root logger (avoid duplicate logs)
        logger.propagate = False
    
    def shutdown(self) -> None:
        """Shutdown all handlers and close log files.
        
        Should be called on application exit to ensure logs are flushed.
        
        Examples:
            >>> logger_manager = SanitizationLogger()
            >>> logger_manager.shutdown()
        
        Thread Safety:
            Thread-safe. Safe to call multiple times.
        """
        with self._handler_lock:
            for handler_name, handler in self.handlers.items():
                try:
                    handler.flush()
                    handler.close()
                except Exception as e:
                    # Use basic logging since our logging might be shutting down
                    print(f"Error closing handler {handler_name}: {e}")
            
            self.handlers.clear()
    
    def add_handler(self, handler: logging.Handler, name: Optional[str] = None) -> None:
        """Add a custom handler to all loggers.
        
        Args:
            handler: Handler to add
            name: Optional name for the handler
            
        Examples:
            >>> import logging
            >>> logger_manager = SanitizationLogger()
            >>> custom_handler = logging.StreamHandler()
            >>> logger_manager.add_handler(custom_handler, "custom")
        
        Thread Safety:
            Thread-safe.
        """
        with self._handler_lock:
            handler_name = name or f"custom_{id(handler)}"
            
            # Add filters to custom handler
            if self.pii_filter:
                handler.addFilter(self.pii_filter)
            if self.correlation_filter:
                handler.addFilter(self.correlation_filter)
            
            self.handlers[handler_name] = handler
            
            # Add to all existing loggers
            for logger in self._configured_loggers.values():
                logger.addHandler(handler)
    
    def remove_handler(self, name: str) -> None:
        """Remove a handler by name.
        
        Args:
            name: Name of handler to remove
            
        Examples:
            >>> logger_manager = SanitizationLogger()
            >>> logger_manager.remove_handler("console_123456")
        
        Thread Safety:
            Thread-safe.
        """
        with self._handler_lock:
            if name in self.handlers:
                handler = self.handlers[name]
                
                # Remove from all loggers
                for logger in self._configured_loggers.values():
                    logger.removeHandler(handler)
                
                # Close handler
                try:
                    handler.flush()
                    handler.close()
                except Exception:
                    pass
                
                # Remove from registry
                del self.handlers[name]
    
    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance.
        
        Primarily for testing purposes. Shuts down existing instance
        and allows a new one to be created.
        
        Examples:
            >>> SanitizationLogger.reset()
        
        Thread Safety:
            Thread-safe.
        """
        with cls._lock:
            if cls._instance:
                cls._instance.shutdown()
                cls._instance = None


# Module-level convenience functions

_logger_manager: Optional[SanitizationLogger] = None


def setup_logging(config: Optional[LogConfig] = None) -> None:
    """Initialize the logging system with configuration.
    
    Args:
        config: Logging configuration (uses defaults if None)
        
    Examples:
        >>> from src.logging.log_config import LogConfig
        >>> config = LogConfig(level="INFO")
        >>> setup_logging(config)
    
    Thread Safety:
        Thread-safe. Safe to call multiple times.
    """
    global _logger_manager
    
    _logger_manager = SanitizationLogger()
    
    if config is None:
        # Use default configuration
        config = LogConfig()
    
    _logger_manager.configure(config)


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance.
    
    Args:
        name: Logger name (typically __name__ of calling module)
        
    Returns:
        Configured logger instance
        
    Examples:
        >>> logger = get_logger(__name__)
        >>> logger.info("Application started")
    
    Thread Safety:
        Thread-safe.
    """
    global _logger_manager
    
    if _logger_manager is None:
        # Auto-initialize with defaults if not configured
        setup_logging()
    
    return _logger_manager.get_logger(name)


def shutdown_logging() -> None:
    """Shutdown the logging system.
    
    Closes all handlers and flushes logs. Should be called on application exit.
    
    Examples:
        >>> shutdown_logging()
    
    Thread Safety:
        Thread-safe.
    """
    global _logger_manager
    
    if _logger_manager:
        _logger_manager.shutdown()
