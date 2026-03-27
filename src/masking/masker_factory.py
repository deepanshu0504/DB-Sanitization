"""
Masking Strategy Factory for dynamic masker instantiation.

This module provides a thread-safe singleton factory for creating masker instances
based on PII type configuration. The factory manages a registry of masker classes,
handles masker-specific parameters, and provides caching for performance optimization.

Key Features:
    - Registry pattern for masker class lookup
    - Thread-safe singleton with double-checked locking
    - Instance caching for performance (same params = same masker)
    - Support for custom masker registration
    - Masker-specific parameter extraction (e.g., character_class for GenericMasker)
    - Clear error handling with actionable messages

Usage Example:
    >>> from src.masking.masker_factory import MaskerFactory
    >>> from src.masking.base_masker import MaskingStrategy
    >>> 
    >>> # Get factory instance (singleton)
    >>> factory = MaskerFactory()
    >>> 
    >>> # Get email masker
    >>> email_masker = factory.get_masker("email", seed=42)
    >>> 
    >>> # Get generic masker with custom parameters
    >>> generic_masker = factory.get_masker(
    ...     "generic",
    ...     seed=42,
    ...     masker_params={"character_class": "alpha"}
    ... )
    >>> 
    >>> # Register custom masker
    >>> factory.register_masker("custom_pii", CustomMasker)

Thread Safety:
    The factory uses double-checked locking for singleton instantiation and
    separate locks for cache operations to ensure thread-safe concurrent access.

Author: Database Sanitization Team
Date: 2026-03-26
"""

import threading
import logging
from typing import Dict, Optional, Type, Any

from src.masking.base_masker import BaseMasker, MaskingStrategy
from src.masking.email_masker import EmailMasker
from src.masking.phone_masker import PhoneMasker
from src.masking.name_masker import NameMasker
from src.masking.ssn_masker import SSNMasker
from src.masking.generic_masker import GenericMasker
from src.exceptions import MaskingError
from src.logging.logger import get_logger


class MaskerFactory:
    """
    Thread-safe singleton factory for creating and caching masker instances.
    
    The factory maintains a registry of PII types mapped to masker classes,
    handles masker-specific parameters, and caches masker instances for reuse
    when the same configuration is requested multiple times.
    
    Architecture:
        - Singleton pattern ensures one factory instance per application
        - Registry pattern maps PII types to masker classes
        - Cache pattern reuses masker instances for identical configurations
        - Factory method pattern for object creation
    
    Attributes:
        _instance: Singleton instance of the factory
        _lock: Thread lock for singleton instantiation
        _cache: Cache of masker instances keyed by configuration
        _cache_lock: Thread lock for cache operations
        _registry: Mapping of PII types to masker classes
    
    Example:
        >>> factory = MaskerFactory()
        >>> masker = factory.get_masker("email", seed=42)
        >>> # Same configuration returns cached instance
        >>> masker2 = factory.get_masker("email", seed=42)
        >>> assert masker is masker2
    """
    
    # Class-level singleton state
    _instance: Optional["MaskerFactory"] = None
    _lock: threading.Lock = threading.Lock()
    
    # Built-in masker registry
    _registry: Dict[str, Type[BaseMasker]] = {
        "email": EmailMasker,
        "phone": PhoneMasker,
        "name": NameMasker,
        "ssn": SSNMasker,
        "generic": GenericMasker,
    }
    
    def __new__(cls) -> "MaskerFactory":
        """
        Create or return the singleton factory instance.
        
        Uses double-checked locking pattern for thread-safe singleton creation:
        1. Check if instance exists (fast path, no lock)
        2. Acquire lock
        3. Check again if instance exists (another thread might have created it)
        4. Create instance if still None
        
        Returns:
            MaskerFactory: The singleton factory instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._cache: Dict[str, BaseMasker] = {}
                    instance._cache_lock = threading.Lock()
                    instance._logger = get_logger(__name__)
                    cls._instance = instance
        return cls._instance
    
    def get_masker(
        self,
        pii_type: str,
        seed: int = 42,
        null_strategy: MaskingStrategy = MaskingStrategy.PRESERVE,
        masker_params: Optional[Dict[str, Any]] = None,
        logger: Optional[logging.Logger] = None
    ) -> BaseMasker:
        """
        Get or create a masker instance for the specified PII type.
        
        This method implements the factory pattern with caching. It:
        1. Validates the PII type exists in the registry
        2. Creates a cache key from all parameters
        3. Returns cached masker if available
        4. Creates new masker instance if not cached
        5. Stores new instance in cache before returning
        
        Args:
            pii_type: Type of PII data (email, phone, name, ssn, generic)
            seed: Seed value for deterministic masking (default: 42)
            null_strategy: Strategy for handling NULL values (default: PRESERVE)
            masker_params: Dictionary of masker-specific parameters:
                - For GenericMasker: {"character_class": "alphanumeric"|"alpha"|"numeric"}
                - For future maskers: additional parameters as needed
            logger: Optional logger instance for correlation tracking
        
        Returns:
            BaseMasker: Configured masker instance ready for use
        
        Raises:
            MaskingError: If PII type is not registered or masker creation fails
        
        Example:
            >>> factory = MaskerFactory()
            >>> 
            >>> # Get email masker with default parameters
            >>> email_masker = factory.get_masker("email")
            >>> 
            >>> # Get generic masker with custom character class
            >>> alpha_masker = factory.get_masker(
            ...     "generic",
            ...     seed=42,
            ...     masker_params={"character_class": "alpha"}
            ... )
            >>> 
            >>> # Get phone masker with custom null strategy
            >>> phone_masker = factory.get_masker(
            ...     "phone",
            ...     seed=100,
            ...     null_strategy=MaskingStrategy.MASK
            ... )
        """
        # Validate PII type is registered
        if pii_type not in self._registry:
            valid_types = list(self._registry.keys())
            raise MaskingError.unsupported_pii_type(
                pii_type=pii_type,
                valid_types=valid_types
            )
        
        # Create cache key from all parameters
        cache_key = self._create_cache_key(
            pii_type=pii_type,
            seed=seed,
            null_strategy=null_strategy,
            masker_params=masker_params
        )
        
        # Check cache first (thread-safe)
        with self._cache_lock:
            if cache_key in self._cache:
                self._logger.debug(
                    f"Cache hit for masker: {pii_type}",
                    extra={"cache_key": cache_key}
                )
                return self._cache[cache_key]
        
        # Cache miss - create new masker instance
        self._logger.debug(
            f"Cache miss for masker: {pii_type}, creating new instance",
            extra={"cache_key": cache_key}
        )
        
        masker = self._create_masker(
            pii_type=pii_type,
            seed=seed,
            null_strategy=null_strategy,
            masker_params=masker_params,
            logger=logger
        )
        
        # Store in cache (thread-safe)
        with self._cache_lock:
            # Double-check cache in case another thread created it
            if cache_key not in self._cache:
                self._cache[cache_key] = masker
                self._logger.debug(
                    f"Cached masker instance: {pii_type}",
                    extra={"cache_key": cache_key, "cache_size": len(self._cache)}
                )
        
        return masker
    
    def _create_masker(
        self,
        pii_type: str,
        seed: int,
        null_strategy: MaskingStrategy,
        masker_params: Optional[Dict[str, Any]],
        logger: Optional[logging.Logger]
    ) -> BaseMasker:
        """
        Create a new masker instance with the specified configuration.
        
        This method handles:
        1. Extracting masker-specific parameters
        2. Instantiating the appropriate masker class
        3. Passing common parameters (seed, null_strategy, logger)
        4. Passing masker-specific parameters (e.g., character_class)
        
        Args:
            pii_type: Type of PII data
            seed: Seed value for deterministic masking
            null_strategy: Strategy for handling NULL values
            masker_params: Dictionary of masker-specific parameters
            logger: Optional logger instance
        
        Returns:
            BaseMasker: Newly created masker instance
        
        Raises:
            MaskingError: If masker class cannot be instantiated
        """
        masker_class = self._registry[pii_type]
        
        # Extract masker-specific parameters
        masker_kwargs = {
            "seed": seed,
            "null_strategy": null_strategy,
            "logger": logger
        }
        
        # Handle GenericMasker's character_class parameter
        if pii_type == "generic" and masker_params:
            if isinstance(masker_params, dict):
                character_class = masker_params.get("character_class", "alphanumeric")
                masker_kwargs["character_class"] = character_class
            # If masker_params is not a dict (e.g., legacy string format), ignore it
        
        # Future maskers can add their specific parameters here
        # if pii_type == "custom_type" and masker_params:
        #     custom_param = masker_params.get("custom_param", default_value)
        #     masker_kwargs["custom_param"] = custom_param
        
        try:
            masker = masker_class(**masker_kwargs)
            self._logger.info(
                f"Created masker instance: {pii_type}",
                extra={
                    "pii_type": pii_type,
                    "seed": seed,
                    "null_strategy": null_strategy.value,
                    "masker_params": masker_params
                }
            )
            return masker
        except Exception as e:
            # Convert any instantiation error to MaskingError
            raise MaskingError.masker_not_found(
                pii_type=pii_type,
                reason=str(e)
            )
    
    def _create_cache_key(
        self,
        pii_type: str,
        seed: int,
        null_strategy: MaskingStrategy,
        masker_params: Optional[Dict[str, Any]]
    ) -> str:
        """
        Create a unique cache key from masker configuration.
        
        The cache key combines all parameters that affect masker behavior:
        - PII type
        - Seed value
        - NULL strategy
        - Masker-specific parameters (sorted for consistency)
        
        Args:
            pii_type: Type of PII data
            seed: Seed value for deterministic masking
            null_strategy: Strategy for handling NULL values
            masker_params: Dictionary of masker-specific parameters
        
        Returns:
            str: Unique cache key for the configuration
        
        Example:
            >>> key1 = factory._create_cache_key("email", 42, MaskingStrategy.PRESERVE, None)
            >>> # "email_42_PRESERVE_None"
            >>> 
            >>> key2 = factory._create_cache_key(
            ...     "generic", 42, MaskingStrategy.PRESERVE,
            ...     {"character_class": "alpha"}
            ... )
            >>> # "generic_42_PRESERVE_character_class=alpha"
        """
        # Base key components
        key_parts = [
            pii_type,
            str(seed),
            null_strategy.value
        ]
        
        # Add masker-specific parameters (sorted for consistency)
        if masker_params and isinstance(masker_params, dict):
            # Sort parameters to ensure consistent cache keys
            sorted_params = sorted(masker_params.items())
            param_str = ",".join(f"{k}={v}" for k, v in sorted_params)
            key_parts.append(param_str)
        else:
            key_parts.append("None")
        
        return "_".join(key_parts)
    
    def register_masker(
        self,
        pii_type: str,
        masker_class: Type[BaseMasker]
    ) -> None:
        """
        Register a custom masker class for a PII type.
        
        This method allows extending the factory with custom masker implementations.
        It can also override built-in maskers if needed (with a warning).
        
        Args:
            pii_type: PII type identifier (e.g., "custom_pii", "address")
            masker_class: Masker class that inherits from BaseMasker
        
        Raises:
            ValueError: If masker_class is not a subclass of BaseMasker
        
        Example:
            >>> from src.masking.base_masker import BaseMasker
            >>> 
            >>> class CustomMasker(BaseMasker):
            ...     def mask(self, value, column_info):
            ...         # Custom masking logic
            ...         return "masked"
            >>> 
            >>> factory = MaskerFactory()
            >>> factory.register_masker("custom_pii", CustomMasker)
            >>> custom_masker = factory.get_masker("custom_pii")
        """
        # Validate masker class
        if not isinstance(masker_class, type) or not issubclass(masker_class, BaseMasker):
            raise ValueError(
                f"Masker class must be a subclass of BaseMasker, got: {masker_class}"
            )
        
        # Warn if overriding existing masker
        if pii_type in self._registry:
            self._logger.warning(
                f"Overriding existing masker for PII type: {pii_type}",
                extra={
                    "pii_type": pii_type,
                    "old_class": self._registry[pii_type].__name__,
                    "new_class": masker_class.__name__
                }
            )
        
        # Register the masker
        self._registry[pii_type] = masker_class
        self._logger.info(
            f"Registered masker: {pii_type} -> {masker_class.__name__}",
            extra={"pii_type": pii_type, "masker_class": masker_class.__name__}
        )
    
    def get_registered_types(self) -> list[str]:
        """
        Get list of all registered PII types.
        
        Returns:
            list[str]: Sorted list of registered PII type identifiers
        
        Example:
            >>> factory = MaskerFactory()
            >>> types = factory.get_registered_types()
            >>> print(types)
            ['email', 'generic', 'name', 'phone', 'ssn']
        """
        return sorted(self._registry.keys())
    
    def clear_cache(self) -> int:
        """
        Clear all cached masker instances.
        
        This method is primarily for testing and cleanup. It removes all
        cached masker instances, forcing new instances to be created on
        the next get_masker() call.
        
        Returns:
            int: Number of cached instances that were cleared
        
        Example:
            >>> factory = MaskerFactory()
            >>> masker = factory.get_masker("email")
            >>> cleared = factory.clear_cache()
            >>> print(f"Cleared {cleared} cached maskers")
            Cleared 1 cached maskers
        """
        with self._cache_lock:
            cache_size = len(self._cache)
            self._cache.clear()
            self._logger.info(
                f"Cleared masker cache: {cache_size} instances removed",
                extra={"cache_size": cache_size}
            )
            return cache_size
    
    @classmethod
    def _reset_instance(cls) -> None:
        """
        Reset the singleton instance.
        
        WARNING: This method is for TESTING ONLY. It should NEVER be used
        in production code. It allows tests to get a fresh factory instance
        with a clean cache.
        
        Example (testing only):
            >>> MaskerFactory._reset_instance()
            >>> factory = MaskerFactory()  # Fresh instance
        """
        with cls._lock:
            cls._instance = None
