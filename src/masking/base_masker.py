"""
Abstract base class for deterministic data masking strategies.

This module provides the foundation for all PII masking implementations with:
- Deterministic masking (same input → same output) for FK integrity
- Type safety and validation
- Length constraint enforcement
- NULL handling strategies
- Unicode and multi-byte character support

Key Features:
    - SHA256-based deterministic seed generation
    - Column metadata integration with SchemaExtractor
    - Configurable NULL handling (PRESERVE, MASK, RANDOMIZE)
    - Intelligent length validation with Unicode awareness
    - Data type validation before returning masked values
    - Comprehensive logging with correlation IDs

Author: Database Sanitization Team
Date: 2026-03-26
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Union
import hashlib
import logging

from ..exceptions import MaskingError
from ..error_codes import ErrorCodes
from ..logging.logger import get_logger


class MaskingStrategy(Enum):
    """
    Strategy for handling NULL values during masking.
    
    Attributes:
        PRESERVE: Keep NULL values as NULL (default, safest option)
        MASK: Always generate a fake value, even for NULLs
        RANDOMIZE: Randomly decide to mask or preserve NULL (not recommended, breaks determinism)
    """
    
    PRESERVE = "preserve"  # NULL → NULL (default)
    MASK = "mask"          # NULL → fake value
    RANDOMIZE = "randomize"  # NULL → 50/50 chance (breaks determinism)


@dataclass
class ColumnInfo:
    """
    Container for database column metadata required for masking.
    
    This dataclass encapsulates all the information needed from SchemaExtractor
    to perform type-safe, constraint-aware masking.
    
    Attributes:
        data_type: SQL Server data type (e.g., 'VARCHAR', 'INT', 'DATE')
        max_length: Maximum column length (characters for NVARCHAR, bytes for VARCHAR)
        nullable: Whether the column allows NULL values
        precision: Numeric precision for DECIMAL/NUMERIC types (optional)
        scale: Numeric scale for DECIMAL/NUMERIC types (optional)
        is_max_type: Whether column uses MAX length (VARCHAR(MAX), etc.)
        is_unicode: Whether column is Unicode type (NVARCHAR, NCHAR)
        is_fixed_length: Whether column is fixed length (CHAR, NCHAR)
        
    Examples:
        >>> # VARCHAR(255) NOT NULL column
        >>> col_info = ColumnInfo(
        ...     data_type="VARCHAR",
        ...     max_length=255,
        ...     nullable=False,
        ...     is_unicode=False,
        ...     is_fixed_length=False
        ... )
        
        >>> # NVARCHAR(MAX) NULL column
        >>> col_info = ColumnInfo(
        ...     data_type="NVARCHAR",
        ...     max_length=-1,
        ...     nullable=True,
        ...     is_max_type=True,
        ...     is_unicode=True
        ... )
    """
    
    data_type: str
    max_length: int
    nullable: bool
    precision: Optional[int] = None
    scale: Optional[int] = None
    is_max_type: bool = False
    is_unicode: bool = False
    is_fixed_length: bool = False
    
    def __post_init__(self):
        """Validate column metadata after initialization."""
        # Normalize data type to uppercase
        self.data_type = self.data_type.upper()
        
        # Validate max_length for string types
        if self.data_type in {"VARCHAR", "NVARCHAR", "CHAR", "NCHAR"}:
            if self.max_length <= 0 and not self.is_max_type:
                raise ValueError(
                    f"max_length must be positive for {self.data_type}, got {self.max_length}"
                )
        
        # Set Unicode flag based on data type
        if self.data_type in {"NVARCHAR", "NCHAR", "NTEXT"}:
            self.is_unicode = True
        
        # Set fixed-length flag
        if self.data_type in {"CHAR", "NCHAR"}:
            self.is_fixed_length = True
    
    @property
    def effective_max_length(self) -> int:
        """
        Get effective maximum length for validation.
        
        Returns:
            Actual max length, or a reasonable default (10000) for MAX types
        """
        if self.is_max_type or self.max_length == -1:
            return 10000  # Reasonable default for MAX types
        return self.max_length


class BaseMasker(ABC):
    """
    Abstract base class for all PII masking strategies.
    
    This class enforces deterministic masking where the same input always produces
    the same output, which is critical for preserving foreign key relationships.
    
    All concrete masker implementations must:
    1. Override the abstract mask() method
    2. Use _get_deterministic_seed() for random generation
    3. Validate length with _validate_length()
    4. Handle NULLs with _handle_null()
    
    Attributes:
        seed: Global seed for deterministic random generation
        null_strategy: Strategy for handling NULL values
        logger: Logger instance with correlation ID support
        
    Examples:
        >>> class CustomMasker(BaseMasker):
        ...     def mask(self, value: Any, column_info: ColumnInfo) -> Any:
        ...         # Handle NULL values first
        ...         if value is None:
        ...             return self._handle_null(value, column_info)
        ...         
        ...         # Generate deterministic seed
        ...         seed = self._get_deterministic_seed(value)
        ...         
        ...         # Generate fake value (your logic here)
        ...         fake_value = f"masked_{seed}"
        ...         
        ...         # Validate length
        ...         fake_value = self._validate_length(fake_value, column_info)
        ...         
        ...         return fake_value
    """
    
    def __init__(
        self,
        seed: int = 42,
        null_strategy: MaskingStrategy = MaskingStrategy.PRESERVE,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the base masker.
        
        Args:
            seed: Global seed for deterministic random generation (default: 42)
            null_strategy: How to handle NULL values (default: PRESERVE)
            logger: Optional logger instance (creates default if None)
        """
        self.seed = seed
        self.null_strategy = null_strategy
        self.logger = logger or get_logger(self.__class__.__name__)
        
        # Track truncation events (should be zero with smart generation)
        self.truncation_count = 0
        self.truncation_details = []  # List of {original_length, truncated_length, data_type}
    
    @abstractmethod
    def mask(self, value: Any, column_info: ColumnInfo) -> Any:
        """
        Mask a single value deterministically.
        
        This method must be overridden by all concrete masker implementations.
        The implementation should:
        1. Check for NULL and handle with _handle_null()
        2. Generate deterministic seed with _get_deterministic_seed()
        3. Create fake value using seeded random generation
        4. Validate length with _validate_length()
        5. Return masked value
        
        Args:
            value: Original value to mask (can be None)
            column_info: Column metadata for validation
            
        Returns:
            Masked value of appropriate type
            
        Raises:
            MaskingError: If masking fails or constraints violated
        """
        pass
    
    def _get_deterministic_seed(self, value: Any) -> int:
        """
        Generate a deterministic integer seed from a value.
        
        Uses SHA256 hashing to create a consistent seed from the input value.
        The seed is used to initialize random generators for deterministic masking.
        
        Args:
            value: Value to hash (any type that can be converted to string)
            
        Returns:
            Integer seed in range [0, 2^32-1]
            
        Examples:
            >>> masker = CustomMasker()
            >>> seed1 = masker._get_deterministic_seed("test@example.com")
            >>> seed2 = masker._get_deterministic_seed("test@example.com")
            >>> assert seed1 == seed2  # Same input → same seed
        """
        # Convert value to string for hashing
        value_str = str(value)
        
        # Handle very long values (>10KB) - hash first 1KB + length
        if len(value_str) > 10240:
            value_str = value_str[:1024] + f"_len_{len(value_str)}"
        
        # Create hash with global seed for additional entropy
        hash_input = f"{self.seed}_{value_str}"
        hash_bytes = hashlib.sha256(hash_input.encode('utf-8')).digest()
        
        # Convert first 4 bytes to integer
        seed = int.from_bytes(hash_bytes[:4], byteorder='big')
        
        return seed
    
    def _hash_value(self, value: Any) -> str:
        """
        Generate a SHA256 hash of a value.
        
        This is useful for logging and debugging without exposing PII.
        
        Args:
            value: Value to hash
            
        Returns:
            Hexadecimal hash string (64 characters)
        """
        value_str = str(value)
        return hashlib.sha256(value_str.encode('utf-8')).hexdigest()
    
    def _validate_length(
        self,
        value: str,
        column_info: ColumnInfo
    ) -> tuple[str, bool]:
        """
        Validate and truncate value to fit within column length constraints.
        
        Handles:
        - Unicode character boundaries (don't split multi-byte characters)
        - Fixed-length columns (CHAR) - pads with spaces
        - Variable-length columns (VARCHAR) - truncates if needed
        - NVARCHAR (character count) vs VARCHAR (byte count)
        
        Note: With smart generation, truncation should NEVER occur.
              If it does, this indicates a bug in generation logic.
        
        Args:
            value: String value to validate
            column_info: Column metadata with length constraints
            
        Returns:
            Tuple of (validated_value, was_truncated)
            
        Raises:
            MaskingError: If column has insufficient length for any valid value
        """
        if not isinstance(value, str):
            return value, False  # Non-string values don't need length validation
        
        max_length = column_info.effective_max_length
        was_truncated = False
        original_length = 0
        
        # For NVARCHAR/NCHAR, count characters
        if column_info.is_unicode:
            if len(value) > max_length:
                was_truncated = True
                original_length = len(value)
                # Truncate at character boundary
                truncated = value[:max_length]
                
                # Log as ERROR - this should not happen with smart generation
                self.logger.error(
                    f"GENERATION BUG: Value truncated from {len(value)} to {max_length} characters. "
                    f"Smart generation should have prevented this.",
                    extra={
                        "masker": self.__class__.__name__,
                        "original_length": len(value),
                        "max_length": max_length,
                        "data_type": column_info.data_type,
                        "value_hash": self._hash_value(value)[:16]
                    }
                )
                value = truncated
        else:
            # For VARCHAR/CHAR, count bytes
            value_bytes = value.encode('utf-8')
            if len(value_bytes) > max_length:
                was_truncated = True
                original_length = len(value_bytes)
                # Truncate at byte boundary without breaking UTF-8
                truncated_bytes = value_bytes[:max_length]
                # Decode and handle potential broken UTF-8 at end
                try:
                    value = truncated_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    # Find last valid character boundary
                    for i in range(len(truncated_bytes) - 1, max(0, len(truncated_bytes) - 4), -1):
                        try:
                            value = truncated_bytes[:i].decode('utf-8')
                            break
                        except UnicodeDecodeError:
                            continue
                
                # Log as ERROR - this should not happen with smart generation
                self.logger.error(
                    f"GENERATION BUG: Value truncated from {len(value_bytes)} to {len(value.encode('utf-8'))} bytes",
                    extra={
                        "masker": self.__class__.__name__,
                        "original_bytes": len(value_bytes),
                        "max_length": max_length,
                        "data_type": column_info.data_type
                    }
                )
        
        # Track truncation if it occurred
        if was_truncated:
            self.truncation_count += 1
            self.truncation_details.append({
                "original_length": original_length,
                "truncated_length": max_length,
                "data_type": column_info.data_type
            })
        
        # For fixed-length columns (CHAR, NCHAR), pad with spaces
        if column_info.is_fixed_length:
            if column_info.is_unicode:
                # Pad to character length
                value = value.ljust(max_length)
            else:
                # Pad to byte length
                value_bytes = value.encode('utf-8')
                if len(value_bytes) < max_length:
                    padding = b' ' * (max_length - len(value_bytes))
                    value = (value_bytes + padding).decode('utf-8')
        
        return value, was_truncated
    
    def _validate_data_type(
        self,
        value: Any,
        column_info: ColumnInfo
    ) -> None:
        """
        Validate that the masked value matches the expected SQL Server data type.
        
        Args:
            value: Masked value to validate
            column_info: Column metadata with expected type
            
        Raises:
            MaskingError: If value type doesn't match column data type
        """
        if value is None:
            return  # NULL values are always valid if column is nullable
        
        data_type = column_info.data_type
        
        # String types
        if data_type in {"VARCHAR", "NVARCHAR", "CHAR", "NCHAR", "TEXT", "NTEXT"}:
            if not isinstance(value, str):
                raise MaskingError(
                    message=f"Expected string value for {data_type}, got {type(value).__name__}",
                    error_code=ErrorCodes.MASKING_TYPE_MISMATCH,
                    is_retryable=False,
                    suggested_action="Ensure masker returns string values for string columns",
                    operation_context={
                        "column_type": data_type,
                        "value_type": type(value).__name__
                    }
                )
        
        # Integer types
        elif data_type in {"INT", "BIGINT", "SMALLINT", "TINYINT"}:
            if not isinstance(value, int):
                raise MaskingError(
                    message=f"Expected integer value for {data_type}, got {type(value).__name__}",
                    error_code=ErrorCodes.MASKING_TYPE_MISMATCH,
                    is_retryable=False,
                    suggested_action="Ensure masker returns integer values for integer columns",
                    operation_context={
                        "column_type": data_type,
                        "value_type": type(value).__name__
                    }
                )
        
        # Date/time types
        elif data_type in {"DATE", "DATETIME", "DATETIME2", "SMALLDATETIME", "TIME"}:
            from datetime import datetime, date, time
            if not isinstance(value, (datetime, date, time, str)):
                raise MaskingError(
                    message=f"Expected date/time value for {data_type}, got {type(value).__name__}",
                    error_code=ErrorCodes.MASKING_TYPE_MISMATCH,
                    is_retryable=False,
                    suggested_action="Ensure masker returns date/time objects or ISO-formatted strings",
                    operation_context={
                        "column_type": data_type,
                        "value_type": type(value).__name__}
                )
    
    def _handle_null(
        self,
        value: Any,
        column_info: ColumnInfo
    ) -> Optional[Any]:
        """
        Handle NULL values according to the configured strategy.
        
        Args:
            value: Value to check (might be None)
            column_info: Column metadata with nullable constraint
            
        Returns:
            None if preserving NULL, or raises if NULL not allowed
            
        Raises:
            MaskingError: If NULL value violates NOT NULL constraint
        """
        if value is not None:
            return value  # Not a NULL, return as-is
        
        # Check nullable constraint
        if not column_info.nullable:
            raise MaskingError(
                message="NULL value encountered for NOT NULL column",
                error_code=ErrorCodes.MASKING_NULL_CONSTRAINT_VIOLATION,
                is_retryable=False,
                suggested_action="Ensure data doesn't contain NULLs before masking NOT NULL columns",
                operation_context={
                    "column_type": column_info.data_type,
                    "nullable": False
                }
            )
        
        # Apply NULL handling strategy
        if self.null_strategy == MaskingStrategy.PRESERVE:
            return None  # Keep NULL as NULL
        elif self.null_strategy == MaskingStrategy.MASK:
            # Subclass should generate fake value
            # This is signaled by returning the original None
            # and letting subclass handle it
            return None
        else:  # RANDOMIZE
            import random
            random.seed(self.seed)
            return None if random.random() < 0.5 else None  # 50/50, but still None for now
    
    def _pre_validate_constraints(
        self,
        column_info: ColumnInfo,
        min_length_required: int
    ) -> None:
        """
        Validate column constraints BEFORE generation.
        
        Checks that it's possible to generate a valid value given constraints.
        Fails fast if constraints cannot be satisfied.
        
        Args:
            column_info: Column metadata with constraints
            min_length_required: Minimum length needed for this masker type
            
        Raises:
            MaskingError: If constraints cannot be satisfied
            
        Example:
            >>> # Email masker needs minimum 6 chars
            >>> self._pre_validate_constraints(column_info, min_length_required=6)
            >>> # Raises if column is VARCHAR(5)
        """
        max_length = column_info.effective_max_length
        
        # Check minimum length requirement
        if max_length < min_length_required:
            raise MaskingError(
                message=f"Column too short for {self.__class__.__name__} "
                        f"(need {min_length_required}, have {max_length})",
                error_code=ErrorCodes.INSUFFICIENT_COLUMN_LENGTH,
                is_retryable=False,
                suggested_action=(
                    f"Increase column length to at least {min_length_required} "
                    f"or use GenericMasker for short columns"
                ),
                operation_context={
                    "masker": self.__class__.__name__,
                    "min_required": min_length_required,
                    "column_length": max_length,
                    "data_type": column_info.data_type
                }
            )
        
        # Check data type compatibility (string types only for most maskers)
        if column_info.data_type not in {
            "VARCHAR", "NVARCHAR", "CHAR", "NCHAR", "TEXT", "NTEXT"
        }:
            raise MaskingError(
                message=f"Data type {column_info.data_type} incompatible with {self.__class__.__name__}",
                error_code=ErrorCodes.INCOMPATIBLE_DATA_TYPE,
                is_retryable=False,
                suggested_action="Use appropriate masker for data type",
                operation_context={
                    "masker": self.__class__.__name__,
                    "data_type": column_info.data_type
                }
            )
        
        self.logger.debug(
            f"Pre-validation passed for {self.__class__.__name__}",
            extra={
                "min_required": min_length_required,
                "available": max_length,
                "data_type": column_info.data_type
            }
        )
    
    def get_truncation_metrics(self) -> dict[str, Any]:
        """
        Get truncation metrics for this masker instance.
        
        Returns:
            Dict with truncation count and details
            
        Example:
            >>> masker = EmailMasker()
            >>> masker.mask("test@example.com", column_info)
            >>> metrics = masker.get_truncation_metrics()
            >>> print(metrics['truncation_count'])  # Should be 0 with smart generation
        """
        return {
            "truncation_count": self.truncation_count,
            "truncation_details": self.truncation_details
        }
    
    def reset_truncation_metrics(self) -> None:
        """
        Reset truncation tracking counters.
        
        Should be called after retrieving metrics for each table/batch
        to prevent accumulation across different operations.
        
        Example:
            >>> masker = EmailMasker()
            >>> # Process table 1
            >>> metrics = masker.get_truncation_metrics()
            >>> masker.reset_truncation_metrics()
            >>> # Process table 2 with clean metrics
        """
        self.truncation_count = 0
        self.truncation_details = []
