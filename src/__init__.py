"""Database Sanitization Framework.

A comprehensive framework for sanitizing SQL Server databases by identifying,
masking, and managing Personally Identifiable Information (PII).
"""

from .config import (
    ConfigLoader,
    DatabaseConfig,
    Environment,
    PIIColumnConfig,
    PIIConfig,
    SanitizationConfig,
)
from .database import (
    AuthType,
    ConnectionConfig,
    ConnectionPool,
    DatabaseConnectionManager,
)

__version__ = "0.1.0"
__author__ = "Database Sanitization Team"

__all__ = [
    # Configuration module
    "ConfigLoader",
    "SanitizationConfig",
    "DatabaseConfig",
    "PIIColumnConfig",
    "PIIConfig",
    "Environment",
    # Database module
    "DatabaseConnectionManager",
    "ConnectionConfig",
    "ConnectionPool",
    "AuthType",
]
