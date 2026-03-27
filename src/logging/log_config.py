"""Logging configuration models for the database sanitization framework.

This module defines Pydantic models for configuring the structured logging system,
including log levels, output handlers, file rotation settings, and PII redaction patterns.

Classes:
    LogLevel: Enum for valid logging levels
    HandlerType: Enum for supported handler types
    HandlerConfig: Configuration for individual log handlers
    PIIRedactionConfig: Configuration for PII pattern redaction
    LogConfig: Main logging configuration model

Examples:
    >>> config = LogConfig(
    ...     level="INFO",
    ...     handlers=[
    ...         HandlerConfig(type="console"),
    ...         HandlerConfig(type="file", file_path="logs/sanitization.log")
    ...     ]
    ... )
    >>> config.level
    'INFO'

Security:
    - No sensitive data should be logged directly
    - PII patterns are automatically applied to all log output
    - File paths should have restricted permissions in production

Thread Safety:
    Configuration models are immutable after creation and thread-safe.
"""

import re
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)


class LogLevel(str, Enum):
    """Valid logging levels following Python's logging module."""
    
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class HandlerType(str, Enum):
    """Supported log handler types."""
    
    CONSOLE = "console"
    FILE = "file"


class HandlerConfig(BaseModel):
    """Configuration for a single log handler.
    
    Attributes:
        type: Handler type (console or file)
        file_path: Path to log file (required for file handlers)
        max_bytes: Maximum size per log file in bytes (file handlers only)
        backup_count: Number of backup files to keep (file handlers only)
        rotation_interval: Time-based rotation interval ('daily', 'hourly', None)
        format_json: Whether to use JSON formatting (default: True)
    
    Examples:
        >>> console_handler = HandlerConfig(type="console")
        >>> file_handler = HandlerConfig(
        ...     type="file",
        ...     file_path="logs/app.log",
        ...     max_bytes=104857600,  # 100MB
        ...     backup_count=10
        ... )
    """
    
    type: HandlerType = Field(..., description="Handler type (console or file)")
    file_path: Optional[str] = Field(
        None, 
        description="Path to log file (required for file handlers)"
    )
    max_bytes: int = Field(
        104857600,  # 100MB default
        ge=1048576,  # Min 1MB
        le=1073741824,  # Max 1GB
        description="Maximum size per log file in bytes"
    )
    backup_count: int = Field(
        10,
        ge=1,
        le=100,
        description="Number of backup files to keep"
    )
    rotation_interval: Optional[str] = Field(
        "daily",
        description="Time-based rotation interval ('daily', 'hourly', None)"
    )
    format_json: bool = Field(
        True,
        description="Whether to use JSON formatting"
    )
    
    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, v: Optional[str], info) -> Optional[str]:
        """Validate file path for file handlers.
        
        Args:
            v: File path value
            info: Validation context
            
        Returns:
            Validated file path
            
        Raises:
            ValueError: If file handler missing file_path or path is invalid
        """
        # Get handler type from context
        handler_type = info.data.get("type")
        
        if handler_type == HandlerType.FILE:
            if not v:
                raise ValueError("file_path is required for file handlers")
            
            # Validate path is valid (not actual existence, just format)
            try:
                path = Path(v)
                # Ensure parent directory path is valid
                if not path.parent:
                    raise ValueError(f"Invalid file path: {v}")
            except Exception as e:
                raise ValueError(f"Invalid file path '{v}': {e}")
        
        return v
    
    @field_validator("rotation_interval")
    @classmethod
    def validate_rotation_interval(cls, v: Optional[str]) -> Optional[str]:
        """Validate rotation interval value.
        
        Args:
            v: Rotation interval value
            
        Returns:
            Validated rotation interval
            
        Raises:
            ValueError: If rotation interval is invalid
        """
        if v is not None and v not in ["daily", "hourly"]:
            raise ValueError(
                f"rotation_interval must be 'daily', 'hourly', or None, got '{v}'"
            )
        return v


class PIIRedactionConfig(BaseModel):
    """Configuration for PII redaction in log messages.
    
    Attributes:
        enabled: Whether PII redaction is enabled
        patterns: Custom PII patterns to redact (pattern -> replacement)
        redact_emails: Whether to redact email addresses
        redact_phones: Whether to redact phone numbers
        redact_ssn: Whether to redact SSNs
        redact_credit_cards: Whether to redact credit card numbers
    
    Examples:
        >>> config = PIIRedactionConfig(
        ...     enabled=True,
        ...     redact_emails=True,
        ...     patterns={"custom_id": r"ID-\d{5}"}
        ... )
    """
    
    enabled: bool = Field(
        True,
        description="Whether PII redaction is enabled"
    )
    patterns: Dict[str, str] = Field(
        default_factory=dict,
        description="Custom PII patterns to redact (name -> regex pattern)"
    )
    redact_emails: bool = Field(
        True,
        description="Whether to redact email addresses"
    )
    redact_phones: bool = Field(
        True,
        description="Whether to redact phone numbers"
    )
    redact_ssn: bool = Field(
        True,
        description="Whether to redact Social Security Numbers"
    )
    redact_credit_cards: bool = Field(
        True,
        description="Whether to redact credit card numbers"
    )
    
    @field_validator("patterns")
    @classmethod
    def validate_patterns(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Validate custom PII patterns are valid regex.
        
        Args:
            v: Dictionary of pattern name to regex
            
        Returns:
            Validated patterns
            
        Raises:
            ValueError: If any pattern is invalid regex
        """
        for name, pattern in v.items():
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(
                    f"Invalid regex pattern for '{name}': {pattern} - {e}"
                )
        return v


class LogConfig(BaseModel):
    """Main logging configuration model.
    
    Attributes:
        level: Minimum log level to record
        handlers: List of handler configurations
        pii_redaction: PII redaction configuration
        include_correlation_id: Whether to include correlation IDs in logs
        log_format: Custom log format string (for non-JSON handlers)
    
    Examples:
        >>> config = LogConfig(
        ...     level="INFO",
        ...     handlers=[
        ...         HandlerConfig(type="console"),
        ...         HandlerConfig(type="file", file_path="logs/app.log")
        ...     ],
        ...     pii_redaction=PIIRedactionConfig(enabled=True)
        ... )
        >>> config.level
        LogLevel.INFO
    """
    
    level: LogLevel = Field(
        LogLevel.INFO,
        description="Minimum log level to record"
    )
    handlers: List[HandlerConfig] = Field(
        default_factory=lambda: [HandlerConfig(type=HandlerType.CONSOLE)],
        min_length=1,
        description="List of handler configurations"
    )
    pii_redaction: PIIRedactionConfig = Field(
        default_factory=PIIRedactionConfig,
        description="PII redaction configuration"
    )
    include_correlation_id: bool = Field(
        True,
        description="Whether to include correlation IDs in logs"
    )
    log_format: str = Field(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        min_length=1,
        description="Custom log format string (for non-JSON handlers)"
    )
    
    @model_validator(mode="after")
    def validate_handlers(self) -> "LogConfig":
        """Validate handler configurations.
        
        Returns:
            Validated config
            
        Raises:
            ValueError: If handlers configuration is invalid
        """
        if not self.handlers:
            raise ValueError("At least one handler must be configured")
        
        # Validate file paths for file handlers
        file_handlers = [h for h in self.handlers if h.type == HandlerType.FILE]
        file_paths = [h.file_path for h in file_handlers]
        
        # Check for duplicate file paths
        if len(file_paths) != len(set(file_paths)):
            raise ValueError("Duplicate file paths found in handlers")
        
        return self
    
    class Config:
        """Pydantic configuration."""
        
        use_enum_values = True
        validate_assignment = True
