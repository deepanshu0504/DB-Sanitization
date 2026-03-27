"""Unit tests for the central logger manager.

Tests the SanitizationLogger singleton, configuration, and logger retrieval.
"""

import logging
import tempfile
from pathlib import Path

import pytest

from src.logging.logger import (
    SanitizationLogger,
    setup_logging,
    get_logger,
    shutdown_logging,
)
from src.logging.log_config import LogConfig, HandlerConfig, PIIRedactionConfig


@pytest.fixture(autouse=True)
def reset_logger():
    """Reset logger singleton before and after each test."""
    SanitizationLogger.reset()
    yield
    SanitizationLogger.reset()


class TestSanitizationLogger:
    """Test suite for SanitizationLogger class."""
    
    def test_singleton_pattern(self):
        """Test that SanitizationLogger implements singleton pattern."""
        logger1 = SanitizationLogger()
        logger2 = SanitizationLogger()
        
        assert logger1 is logger2
    
    def test_configure_with_console_handler(self):
        """Test configuration with console handler."""
        config = LogConfig(
            level="INFO",
            handlers=[HandlerConfig(type="console")]
        )
        
        logger_manager = SanitizationLogger()
        logger_manager.configure(config)
        
        assert logger_manager.config == config
        assert len(logger_manager.handlers) > 0
    
    def test_configure_with_file_handler(self):
        """Test configuration with file handler."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "test.log"
            
            config = LogConfig(
                level="DEBUG",
                handlers=[
                    HandlerConfig(
                        type="file",
                        file_path=str(log_file)
                    )
                ]
            )
            
            logger_manager = SanitizationLogger()
            logger_manager.configure(config)
            
            assert logger_manager.config == config
            assert len(logger_manager.handlers) > 0
    
    def test_get_logger_returns_configured_logger(self):
        """Test that get_logger returns properly configured logger."""
        config = LogConfig(level="WARNING")
        
        logger_manager = SanitizationLogger()
        logger_manager.configure(config)
        
        logger = logger_manager.get_logger("test.module")
        
        assert logger.name == "test.module"
        assert logger.level == logging.WARNING
    
    def test_multiple_get_logger_calls_return_same_instance(self):
        """Test that repeated get_logger calls return the same logger instance."""
        logger_manager = SanitizationLogger()
        
        logger1 = logger_manager.get_logger("test.module")
        logger2 = logger_manager.get_logger("test.module")
        
        assert logger1 is logger2


    def test_shutdown_closes_handlers(self):
        """Test that shutdown closes all handlers."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "test.log"
            
            config = LogConfig(
                level="INFO",
                handlers=[
                    HandlerConfig(type="file", file_path=str(log_file))
                ]
            )
            
            logger_manager = SanitizationLogger()
            logger_manager.configure(config)
            
            assert len(logger_manager.handlers) > 0
            
            logger_manager.shutdown()
            
            # Handlers should be cleared
            assert len(logger_manager.handlers) == 0


class TestModuleLevelFunctions:
    """Test suite for module-level convenience functions."""
    
    def test_setup_logging_configures_system(self):
        """Test that setup_logging initializes the logging system."""
        config = LogConfig(level="DEBUG")
        
        setup_logging(config)
        
        logger = get_logger(__name__)
        
        assert logger is not None
        assert logger.level == logging.DEBUG
    
    def test_setup_logging_with_defaults(self):
        """Test that setup_logging works with default configuration."""
        setup_logging()
        
        logger = get_logger(__name__)
        
        assert logger is not None
        # Default level is INFO
        assert logger.level == logging.INFO
    
    def test_get_logger_auto_initializes(self):
        """Test that get_logger auto-initializes if not configured."""
        # Don't call setup_logging
        logger = get_logger("test.auto")
        
        assert logger is not None
        assert logger.name == "test.auto"
    
    def test_shutdown_logging(self):
        """Test shutdown_logging function."""
        setup_logging()
        
        # Should not raise any exceptions
        shutdown_logging()
