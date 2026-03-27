"""Configuration loader for database sanitization framework.

This module provides functionality to load configuration from JSON files
and environment variables, with support for validation, merging, and caching.

Classes:
    ConfigLoader: Main configuration loading and management class

Example:
    >>> from src.config.config_loader import ConfigLoader
    >>> loader = ConfigLoader()
    >>> config = loader.load("config/sanitization.json")
    >>> print(config.database.server)
    localhost

Environment Variables:
    Configuration can be overridden with environment variables using the pattern:
    SANITIZATION_{SECTION}_{KEY}
    
    Examples:
        SANITIZATION_DATABASE_SERVER=production-server
        SANITIZATION_DATABASE_USERNAME=admin
        SANITIZATION_DATABASE_PASSWORD=secret123
        SANITIZATION_DATABASE_BATCH_SIZE=20000

Thread Safety:
    ConfigLoader is thread-safe with singleton pattern for cached configuration.
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from pydantic import ValidationError

from .config_models import SanitizationConfig, DatabaseConfig, PIIColumnConfig
from ..exceptions import ConfigFileError, ConfigValidationError

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Load and manage sanitization configuration.
    
    Loads configuration from JSON files with optional environment variable
    overrides. Provides caching for performance and validates all input.
    
    Attributes:
        _cache: Thread-safe cache of loaded configurations
        _lock: Threading lock for cache access
    
    Example:
        >>> loader = ConfigLoader()
        >>> config = loader.load("config/sanitization.json")
        >>> config.database.server
        'localhost'
        
        # With environment overrides
        >>> os.environ["SANITIZATION_DATABASE_SERVER"] = "prod-server"
        >>> config = loader.load("config/sanitization.json", use_env_overrides=True)
        >>> config.database.server
        'prod-server'
    
    Thread Safety:
        Safe to use across multiple threads. Cache access is synchronized.
    """
    
    _instance: Optional["ConfigLoader"] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> "ConfigLoader":
        """Implement singleton pattern for ConfigLoader.
        
        Returns:
            Singleton instance of ConfigLoader
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._cache: Dict[str, SanitizationConfig] = {}
                    cls._instance._cache_lock = threading.Lock()
        return cls._instance
    
    def __init__(self):
        """Initialize ConfigLoader.
        
        Loads .env file if present in the current directory.
        """
        # Load .env file if it exists
        env_path = Path(".env")
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug(f"Loaded environment variables from {env_path}")
    
    def load(
        self,
        json_path: str,
        use_env_overrides: bool = True,
        use_cache: bool = True
    ) -> SanitizationConfig:
        """Load configuration from JSON file with optional env overrides.
        
        Args:
            json_path: Path to JSON configuration file
            use_env_overrides: Whether to apply environment variable overrides
            use_cache: Whether to use cached configuration
        
        Returns:
            Validated SanitizationConfig object
        
        Raises:
            FileNotFoundError: If JSON file doesn't exist
            PermissionError: If file cannot be read
            json.JSONDecodeError: If JSON syntax is invalid
            ValidationError: If configuration validation fails
        
        Example:
            >>> config = loader.load("config/sanitization.json")
            >>> config.database.database
            'SanitizationTest'
        
        Security:
            Always use environment variables for passwords, never store in JSON.
        """
        cache_key = f"{json_path}:{use_env_overrides}"
        
        # Check cache
        if use_cache:
            with self._cache_lock:
                if cache_key in self._cache:
                    logger.debug(f"Returning cached configuration for {json_path}")
                    return self._cache[cache_key]
        
        logger.info(f"Loading configuration from {json_path}")
        
        # Validate file exists
        self._validate_file_exists(json_path)
        
        # Load from JSON
        config_dict = self._load_from_json(json_path)
        
        # Apply environment overrides
        if use_env_overrides:
            env_overrides = self._load_from_env()
            config_dict = self._merge_configs(config_dict, env_overrides)
        
        # Validate and create config object
        try:
            config = SanitizationConfig(**config_dict)
            logger.info(
                f"Successfully loaded configuration: "
                f"{len(config.pii_columns)} PII columns, "
                f"database={config.database.database}, "
                f"environment={config.database.environment}"
            )
        except ValidationError as e:
            logger.error(f"Configuration validation failed: {e}")
            # Wrap Pydantic validation error with our custom exception
            raise ConfigValidationError(
                message=f"Configuration validation failed: {str(e)}",
                error_code="INVALID_VALUE",
                is_retryable=False,
                suggested_action="Check configuration values against schema requirements",
                operation_context={"file_path": json_path}
            ) from e
        
        # Cache result
        if use_cache:
            with self._cache_lock:
                self._cache[cache_key] = config
        
        return config
    
    def _validate_file_exists(self, file_path: str) -> None:
        """Validate that configuration file exists and is readable.
        
        Args:
            file_path: Path to configuration file
        
        Raises:
            FileNotFoundError: If file doesn't exist
            PermissionError: If file cannot be read
        """
        path = Path(file_path)
        
        if not path.exists():
            raise ConfigFileError.file_not_found(file_path)
        
        if not path.is_file():
            raise ValueError(
                f"Path is not a file: {file_path}\n"
                f"Please provide a path to a JSON configuration file."
            )
        
        # Try to open file to check permissions
        try:
            with open(path, 'r', encoding='utf-8') as f:
                pass
        except PermissionError as e:
            raise ConfigFileError.file_not_readable(file_path)
    
    def _load_from_json(self, file_path: str) -> Dict[str, Any]:
        """Load configuration dictionary from JSON file.
        
        Args:
            file_path: Path to JSON configuration file
        
        Returns:
            Dictionary representation of configuration
        
        Raises:
            json.JSONDecodeError: If JSON syntax is invalid
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config_dict = json.load(f)
            logger.debug(f"Successfully parsed JSON from {file_path}")
            return config_dict
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON syntax in {file_path}: {e}")
            raise ConfigFileError.invalid_json(
                file_path,
                line=e.lineno,
                column=e.colno,
                detail=e.msg
            ) from e
    
    def _load_from_env(self) -> Dict[str, Any]:
        """Load configuration overrides from environment variables.
        
        Looks for environment variables matching the pattern:
        SANITIZATION_{SECTION}_{KEY}
        
        Returns:
            Dictionary of configuration overrides
        
        Example:
            Environment variables:
                SANITIZATION_DATABASE_SERVER=prod-server
                SANITIZATION_DATABASE_BATCH_SIZE=20000
            
            Returns:
                {
                    "database": {
                        "server": "prod-server",
                        "batch_size": 20000
                    }
                }
        
        Notes:
            - Only overrides values that are explicitly set in environment
            - Attempts type coercion for numeric values
            - Case-insensitive for section and key names
        """
        prefix = "SANITIZATION_"
        overrides: Dict[str, Any] = {}
        
        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue
            
            # Remove prefix and split into section and key
            remainder = key[len(prefix):]
            parts = remainder.split("_", 1)
            
            if len(parts) != 2:
                logger.warning(
                    f"Ignoring invalid environment variable format: {key}\n"
                    f"Expected format: SANITIZATION_SECTION_KEY"
                )
                continue
            
            section, var_key = parts
            section = section.lower()
            var_key = var_key.lower()
            
            # Initialize section if needed
            if section not in overrides:
                overrides[section] = {}
            
            # Type coercion
            coerced_value = self._coerce_value(value)
            overrides[section][var_key] = coerced_value
            
            # Log override (but not passwords)
            if "password" not in var_key.lower():
                logger.debug(
                    f"Environment override: {section}.{var_key} = {coerced_value}"
                )
            else:
                logger.debug(f"Environment override: {section}.{var_key} = ***")
        
        return overrides
    
    def _coerce_value(self, value: str) -> Any:
        """Coerce string value to appropriate type.
        
        Args:
            value: String value from environment variable
        
        Returns:
            Coerced value (int, float, bool, or str)
        
        Example:
            >>> loader._coerce_value("123")
            123
            >>> loader._coerce_value("true")
            True
            >>> loader._coerce_value("3.14")
            3.14
            >>> loader._coerce_value("hello")
            'hello'
        """
        # Try boolean
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        
        # Try integer
        try:
            return int(value)
        except ValueError:
            pass
        
        # Try float
        try:
            return float(value)
        except ValueError:
            pass
        
        # Return as string
        return value
    
    def _merge_configs(
        self,
        base: Dict[str, Any],
        overrides: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Merge override configuration into base configuration.
        
        Args:
            base: Base configuration dictionary
            overrides: Override configuration dictionary
        
        Returns:
            Merged configuration dictionary
        
        Example:
            >>> base = {"database": {"server": "localhost", "timeout": 30}}
            >>> overrides = {"database": {"server": "prod-server"}}
            >>> loader._merge_configs(base, overrides)
            {"database": {"server": "prod-server", "timeout": 30}}
        
        Notes:
            - Shallow merge for top-level sections
            - Deep merge within each section
            - Overrides take precedence over base values
        """
        merged = base.copy()
        
        for section, values in overrides.items():
            if section not in merged:
                merged[section] = values
            elif isinstance(values, dict) and isinstance(merged[section], dict):
                # Deep merge for dict values
                merged[section] = {**merged[section], **values}
            else:
                # Direct override for non-dict values
                merged[section] = values
        
        return merged
    
    def clear_cache(self) -> None:
        """Clear the configuration cache.
        
        Example:
            >>> loader.clear_cache()
            >>> # Next load() will read from file again
        """
        with self._cache_lock:
            self._cache.clear()
            logger.debug("Configuration cache cleared")
    
    def get_cached_config(self, json_path: str) -> Optional[SanitizationConfig]:
        """Get cached configuration without loading.
        
        Args:
            json_path: Path to JSON configuration file
        
        Returns:
            Cached SanitizationConfig or None if not cached
        
        Example:
            >>> cached = loader.get_cached_config("config/sanitization.json")
            >>> if cached:
            ...     print("Using cached config")
        """
        cache_key = f"{json_path}:True"
        with self._cache_lock:
            return self._cache.get(cache_key)
    
    @staticmethod
    def validate_config(config_dict: Dict[str, Any]) -> SanitizationConfig:
        """Validate configuration dictionary without loading from file.
        
        Args:
            config_dict: Configuration dictionary to validate
        
        Returns:
            Validated SanitizationConfig object
        
        Raises:
            ValidationError: If configuration validation fails
        
        Example:
            >>> config_dict = {
            ...     "database": {
            ...         "server": "localhost",
            ...         "database": "TestDB",
            ...         "auth_type": "windows"
            ...     },
            ...     "pii_columns": []
            ... }
            >>> config = ConfigLoader.validate_config(config_dict)
        """
        try:
            return SanitizationConfig(**config_dict)
        except ValidationError as e:
            logger.error(f"Configuration validation failed: {e}")
            raise ConfigValidationError(
                message=f"Configuration validation failed: {str(e)}",
                error_code="INVALID_VALUE",
                is_retryable=False,
                suggested_action="Check configuration values against schema requirements"
            ) from e
    
    @staticmethod
    def save_config(config: SanitizationConfig, file_path: str) -> None:
        """Save configuration to JSON file.
        
        Args:
            config: SanitizationConfig to save
            file_path: Path where JSON should be saved
        
        Raises:
            PermissionError: If file cannot be written
        
        Example:
            >>> config = SanitizationConfig(...)
            >>> ConfigLoader.save_config(config, "config/output.json")
        
        Security:
            Passwords are excluded from saved configuration.
        """
        # Create parent directory if needed
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert to dict and save
        config_dict = config.model_dump(mode="json", exclude_none=True)
        
        # Remove password from saved config
        if "database" in config_dict and "password" in config_dict["database"]:
            config_dict["database"]["password"] = None
            logger.warning(
                "Password excluded from saved configuration. "
                "Set via SANITIZATION_DATABASE_PASSWORD environment variable."
            )
        
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=2, ensure_ascii=False)
            logger.info(f"Configuration saved to {file_path}")
        except PermissionError as e:
            logger.error(f"Cannot write configuration file: {file_path}")
            raise ConfigFileError.file_not_readable(file_path) from e
