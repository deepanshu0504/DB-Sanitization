"""Configuration management module for database sanitization framework.

This module provides comprehensive configuration management with:
- Pydantic-based models for type-safe configuration
- JSON file loading with validation
- Environment variable overrides
- Caching for performance
- Clear error messages

Main Components:
    ConfigLoader: Load and manage configurations
    SanitizationConfig: Root configuration model
    DatabaseConfig: Database connection settings
    PIIColumnConfig: Individual PII column specification
    PIIConfig: Collection of PII columns
    Environment: Deployment environment enum

Example:
    >>> from src.config import ConfigLoader, SanitizationConfig
    >>> loader = ConfigLoader()
    >>> config = loader.load("config/sanitization.json")
    >>> print(config.database.server)
    localhost

Environment Variables:
    Use SANITIZATION_{SECTION}_{KEY} pattern:
        SANITIZATION_DATABASE_SERVER=prod-server
        SANITIZATION_DATABASE_PASSWORD=secret123
        SANITIZATION_DATABASE_BATCH_SIZE=20000

See Also:
    - config_models.py: Model definitions and validation
    - config_loader.py: Loading and caching logic
"""

from .config_loader import ConfigLoader
from .config_models import (
    DatabaseConfig,
    Environment,
    PIIColumnConfig,
    PIIConfig,
    AIConfig,
    SanitizationConfig,
)

__all__ = [
    "ConfigLoader",
    "SanitizationConfig",
    "DatabaseConfig",
    "PIIColumnConfig",
    "PIIConfig",
    "AIConfig",
    "Environment",
]
