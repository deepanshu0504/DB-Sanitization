"""Unit tests for log formatters.

Tests the JSON formatter and colored console formatter to ensure proper
log record formatting, field inclusion, and error handling.
"""

import json
import logging
from datetime import datetime, timezone

import pytest

from src.logging.formatters import JSONFormatter, ColoredConsoleFormatter


class TestJSONFormatter:
    """Test suite for JSONFormatter class."""
    
    def test_basic_json_formatting(self):
        """Test that log records are formatted as valid JSON."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="/path/to/file.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        formatted = formatter.format(record)
        
        # Should be valid JSON
        log_entry = json.loads(formatted)
        
        # Check required fields
        assert "timestamp" in log_entry
        assert "level" in log_entry
        assert "logger" in log_entry
        assert "message" in log_entry
        
        assert log_entry["level"] == "INFO"
        assert log_entry["logger"] == "test.module"
        assert log_entry["message"] == "Test message"
    
    def test_timestamp_format(self):
        """Test that timestamp is in ISO 8601 format with timezone."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None
        )
        
        formatted = formatter.format(record)
        log_entry = json.loads(formatted)
        
        # Timestamp should end with 'Z' (UTC)
        assert log_entry["timestamp"].endswith("Z")
        
        # Should be parseable as ISO 8601
        timestamp_str = log_entry["timestamp"].replace("Z", "+00:00")
        parsed = datetime.fromisoformat(timestamp_str)
        assert parsed.tzinfo is not None
    
    def test_correlation_id_inclusion(self):
        """Test that correlation ID is included when present."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None
        )
        record.correlation_id = "test-correlation-123"
        
        formatted = formatter.format(record)
        log_entry = json.loads(formatted)
        
        assert "correlation_id" in log_entry
        assert log_entry["correlation_id"] == "test-correlation-123"
    
    def test_no_correlation_id_when_absent(self):
        """Test that correlation_id field is omitted when not present."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None
        )
        
        formatted = formatter.format(record)
        log_entry = json.loads(formatted)
        
        assert "correlation_id" not in log_entry
    
    def test_location_info_for_errors(self):
        """Test that file location is included for ERROR and above."""
        formatter = JSONFormatter()
        
        # ERROR level should include location
        error_record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="/path/to/error.py",
            lineno=100,
            msg="Error occurred",
            args=(),
            exc_info=None
        )
        error_record.funcName = "test_function"
        
        formatted = formatter.format(error_record)
        log_entry = json.loads(formatted)
        
        assert "location" in log_entry
        assert log_entry["location"]["file"] == "/path/to/error.py"
        assert log_entry["location"]["line"] == 100
        assert log_entry["location"]["function"] == "test_function"
    
    def test_no_location_info_for_info(self):
        """Test that location is not included for INFO level."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/path/to/file.py",
            lineno=50,
            msg="Info message",
            args=(),
            exc_info=None
        )
        
        formatted = formatter.format(record)
        log_entry = json.loads(formatted)
        
        assert "location" not in log_entry
    
    def test_exception_formatting(self):
        """Test that exceptions are properly formatted."""
        formatter = JSONFormatter()
        
        try:
            raise ValueError("Test error message")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Exception occurred",
            args=(),
            exc_info=exc_info
        )
        
        formatted = formatter.format(record)
        log_entry = json.loads(formatted)
        
        assert "exception" in log_entry
        assert log_entry["exception"]["type"] == "ValueError"
        assert log_entry["exception"]["message"] == "Test error message"
        assert "traceback" in log_entry["exception"]
        assert isinstance(log_entry["exception"]["traceback"], list)


    def test_extra_fields_extraction(self):
        """Test that extra fields are properly extracted."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None
        )
        record.custom_field = "custom_value"
        record.table_name = "Customers"
        record.row_count = 100
        
        formatted = formatter.format(record)
        log_entry = json.loads(formatted)
        
        assert "extra" in log_entry
        assert log_entry["extra"]["custom_field"] == "custom_value"
        assert log_entry["extra"]["table_name"] == "Customers"
        assert log_entry["extra"]["row_count"] == 100
    
    def test_unicode_handling(self):
        """Test that Unicode characters are handled properly."""
        formatter = JSONFormatter(ensure_ascii=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Unicode: café ñ 中文",
            args=(),
            exc_info=None
        )
        
        formatted = formatter.format(record)
        log_entry = json.loads(formatted)
        
        assert log_entry["message"] == "Unicode: café ñ 中文"
    
    def test_non_serializable_extra_fields(self):
        """Test that non-serializable extra fields are converted to string."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None
        )
        
        class CustomObject:
            def __str__(self):
                return "CustomObject representation"
        
        record.custom_object = CustomObject()
        
        formatted = formatter.format(record)
        log_entry = json.loads(formatted)
        
        assert "extra" in log_entry
        assert log_entry["extra"]["custom_object"] == "CustomObject representation"


class TestColoredConsoleFormatter:
    """Test suite for ColoredConsoleFormatter class."""
    
    def test_colored_output_contains_ansi_codes(self):
        """Test that colored formatter adds ANSI color codes."""
        formatter = ColoredConsoleFormatter(use_colors=True)
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Error message",
            args=(),
            exc_info=None
        )
        
        formatted = formatter.format(record)
        
        # Should contain ANSI codes (escape sequences)
        assert "\033[" in formatted
    
    def test_no_colors_when_disabled(self):
        """Test that color codes are not added when disabled."""
        formatter = ColoredConsoleFormatter(use_colors=False)
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Error message",
            args=(),
            exc_info=None
        )
        
        formatted = formatter.format(record)
        
        # Should not contain ANSI codes
        assert "\033[" not in formatted
    
    def test_different_colors_for_different_levels(self):
        """Test that different log levels get different colors."""
        formatter = ColoredConsoleFormatter(use_colors=True)
        
        debug_record = logging.LogRecord(
            name="test", level=logging.DEBUG, pathname="", lineno=0,
            msg="Debug", args=(), exc_info=None
        )
        error_record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="", lineno=0,
            msg="Error", args=(), exc_info=None
        )
        
        debug_formatted = formatter.format(debug_record)
        error_formatted = formatter.format(error_record)
        
        # Different levels should have different color codes
        # DEBUG is cyan (\033[36m), ERROR is red (\033[31m)
        assert "\033[36m" in debug_formatted
        assert "\033[31m" in error_formatted
    
    def test_custom_format_string(self):
        """Test that custom format string is respected."""
        custom_format = "%(levelname)s - %(message)s"
        formatter = ColoredConsoleFormatter(fmt=custom_format, use_colors=False)
        
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        formatted = formatter.format(record)
        
        # Should match custom format (without logger name or timestamp details)
        assert "INFO - Test message" in formatted
