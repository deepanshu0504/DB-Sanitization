"""
Generic string masking with deterministic generation and configurable character classes.

This module provides PII masking for unknown/custom field types with the following features:
- Deterministic masking (same input → same output) for FK integrity
- Configurable character classes (alphanumeric, alpha, numeric)
- Length preservation (matches original within column constraints)
- Fallback masker for fields without dedicated maskers
- Domain-agnostic design for maximum flexibility

Key Features:
    - SHA256-based deterministic seeding from BaseMasker
    - Modulo arithmetic for character-by-character generation
    - Multiple character class support (alphanumeric default, alpha, numeric)
    - Simple length preservation (no formatting tiers)
    - VARCHAR vs NVARCHAR handling (ASCII vs Unicode)
    - Fixed-length column padding (CHAR, NCHAR)
    - NULL handling strategies (PRESERVE, MASK)

Use Cases:
    - Custom/domain-specific fields without dedicated maskers
    - Fields marked as "generic" by AI detection
    - Comments, notes, or description fields
    - Metadata or configuration text
    - Test/placeholder data columns
    - Future extensibility for unsupported PII types

Author: Database Sanitization Team
Date: 2026-03-26
"""

import logging
from typing import Optional

from .base_masker import BaseMasker, ColumnInfo, MaskingStrategy
from ..exceptions import MaskingError
from ..error_codes import ErrorCodes
from ..logging.logger import get_logger


class GenericMasker(BaseMasker):
    """
    Deterministic generic string masker with configurable character classes.
    
    This masker generates random character strings while preserving referential 
    integrity through deterministic mapping. The same input string always produces 
    the same fake string, which is critical for maintaining FK relationships across tables.
    
    Unlike domain-specific maskers (email, phone, SSN, name), this masker is intentionally
    simple and flexible, designed to handle any unknown or custom field type.
    
    Character Classes:
        - alphanumeric: a-z, A-Z, 0-9 (default)
        - alpha: a-z, A-Z only
        - numeric: 0-9 only
    
    Generation Strategy:
        1. Extract deterministic seed from input string
        2. Determine target length (min of original length and max_length)
        3. Generate characters using modulo arithmetic: chars[(seed + i) % len(chars)]
        4. Validate and pad for fixed-length columns
    
    Length Preservation:
        - Output length matches input length (within column constraints)
        - No multi-tier formatting (unlike email, phone, SSN maskers)
        - Simple truncation if input exceeds max_length
        - Minimum length: 1 character
    
    Attributes:
        seed: Global seed for deterministic random generation
        null_strategy: Strategy for handling NULL values
        character_class: Character set to use ("alphanumeric", "alpha", "numeric")
        logger: Logger instance with correlation ID support
        MIN_LENGTH: Minimum column length required (1 character)
    
    Examples:
        >>> from src.masking import GenericMasker, ColumnInfo
        >>> masker = GenericMasker(seed=42)
        >>> 
        >>> # VARCHAR(50) column - alphanumeric default
        >>> col_info = ColumnInfo(
        ...     data_type="VARCHAR",
        ...     max_length=50,
        ...     nullable=True
        ... )
        >>> 
        >>> # Deterministic masking
        >>> text1 = masker.mask("CustomData123", col_info)
        >>> text2 = masker.mask("CustomData123", col_info)
        >>> assert text1 == text2  # Same input → same output
        >>> 
        >>> # Different inputs produce different outputs
        >>> text3 = masker.mask("OtherData456", col_info)
        >>> assert text1 != text3
        >>> 
        >>> # Alpha-only character class
        >>> masker_alpha = GenericMasker(seed=42, character_class="alpha")
        >>> alpha_text = masker_alpha.mask("CustomData", col_info)
        >>> # Returns: "AbCdEfGhIj" (only letters, no digits)
    """
    
    # Minimum column length required for generic masking
    MIN_LENGTH = 1
    
    # Character class definitions
    ALPHANUMERIC_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    ALPHA_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    NUMERIC_CHARS = "0123456789"
    
    # Valid character class names
    VALID_CHARACTER_CLASSES = {"alphanumeric", "alpha", "numeric"}
    
    def __init__(
        self,
        seed: int = 42,
        null_strategy: MaskingStrategy = MaskingStrategy.PRESERVE,
        character_class: str = "alphanumeric",
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the generic string masker.
        
        Args:
            seed: Global seed for deterministic random generation (default: 42)
            null_strategy: Strategy for handling NULL values (default: PRESERVE)
            character_class: Character set to use - "alphanumeric", "alpha", or "numeric" (default: "alphanumeric")
            logger: Logger instance with correlation ID support (default: auto-created)
        
        Raises:
            ValueError: If character_class is not valid
        
        Examples:
            >>> # Default initialization (alphanumeric)
            >>> masker = GenericMasker()
            >>> 
            >>> # Custom seed for different organization
            >>> masker = GenericMasker(seed=12345)
            >>> 
            >>> # Alpha-only characters
            >>> masker = GenericMasker(character_class="alpha")
            >>> 
            >>> # Numeric-only characters
            >>> masker = GenericMasker(character_class="numeric")
            >>> 
            >>> # Always mask NULLs
            >>> masker = GenericMasker(null_strategy=MaskingStrategy.MASK)
        """
        super().__init__(seed=seed, null_strategy=null_strategy, logger=logger)
        
        # Validate character class
        if not self._validate_character_class(character_class):
            raise ValueError(
                f"Invalid character_class '{character_class}'. "
                f"Must be one of: {', '.join(sorted(self.VALID_CHARACTER_CLASSES))}"
            )
        
        self.character_class = character_class
        self.logger.info(
            f"GenericMasker initialized with seed={seed}, "
            f"null_strategy={null_strategy.value}, character_class={character_class}"
        )
    
    def mask(self, value: Optional[str], column_info: ColumnInfo) -> Optional[str]:
        """
        Mask a string deterministically.
        
        This method generates a fake string that:
        - Is deterministic (same input → same output)
        - Preserves original length (within column constraints)
        - Uses configured character class
        - Respects column length constraints
        - Validates against column data type
        - Handles NULL values per configured strategy
        
        Args:
            value: Original string (or None if NULL)
            column_info: Column metadata from SchemaExtractor
        
        Returns:
            Fake string matching column constraints, or None if value is NULL
            and null_strategy is PRESERVE
        
        Raises:
            MaskingError: If column too short (<1 char), invalid data type,
                          or NULL on NOT NULL column with PRESERVE strategy
        
        Examples:
            >>> masker = GenericMasker(seed=42)
            >>> col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
            >>> 
            >>> # Length preservation
            >>> masker.mask("CustomData", col)
            'aBcDeFgHiJ'  # 10 chars in, 10 chars out (deterministic)
            >>> 
            >>> # NULL handling
            >>> masker.mask(None, col)
            None  # PRESERVE strategy
            >>> 
            >>> # Truncation for shorter column
            >>> short_col = ColumnInfo(data_type="VARCHAR", max_length=5, nullable=True)
            >>> masker.mask("LongCustomData", short_col)
            'aBcDe'  # Truncated to 5 chars
        """
        # Handle NULL values
        if value is None:
            return self._handle_null(value, column_info)
        
        # Strip whitespace
        value = value.strip()
        
        # Determine target length (preserve original up to max_length)
        original_length = len(value)
        target_length = min(original_length, column_info.effective_max_length)
        
        # Generate deterministic seed from input
        seed = self._get_deterministic_seed(value)
        
        # Generate fake string based on target length
        fake_string = self._generate_string(seed, target_length)
        
        # Validate length constraints
        fake_string = self._validate_length(fake_string, column_info)
        
        # Validate data type
        self._validate_data_type(fake_string, column_info)
        
        # Log successful masking (PII-safe)
        self.logger.debug(
            "Masked generic string successfully",
            extra={
                "value_hash": self._hash_value(value),
                "original_length": original_length,
                "fake_length": len(fake_string),
                "target_length": target_length,
                "max_length": column_info.max_length,
                "data_type": column_info.data_type,
                "character_class": self.character_class
            }
        )
        
        return fake_string
    
    def _generate_string(self, seed: int, target_length: int) -> str:
        """
        Generate a fake string deterministically based on seed and length.
        
        Uses modulo arithmetic to select characters deterministically from the
        configured character class. Each character position is determined by
        (seed + position) % len(character_set).
        
        Args:
            seed: Deterministic seed from input string
            target_length: Desired output length
        
        Returns:
            Generated string of exactly target_length characters
        
        Raises:
            MaskingError: If target_length < 1 (cannot generate empty string)
        
        Examples:
            >>> masker = GenericMasker(seed=42, character_class="alphanumeric")
            >>> masker._generate_string(12345, 10)
            'aBcDeFgHiJ'  # 10 alphanumeric characters
            >>> 
            >>> masker_alpha = GenericMasker(seed=42, character_class="alpha")
            >>> masker_alpha._generate_string(12345, 10)
            'AbCdEfGhIj'  # 10 alphabetic characters only
        """
        # Check minimum length requirement
        if target_length < self.MIN_LENGTH:
            raise MaskingError(
                message=f"Column too short for generic masking (min {self.MIN_LENGTH} char required, got {target_length})",
                error_code=ErrorCodes.MASKING_LENGTH_EXCEEDED,
                is_retryable=False,
                suggested_action=f"Increase column length to at least {self.MIN_LENGTH} character",
                operation_context={
                    "column_type": "generic",
                    "target_length": target_length,
                    "minimum_required": self.MIN_LENGTH
                }
            )
        
        # Get character set for current character class
        chars = self._get_character_set()
        
        # Generate string character by character using modulo arithmetic
        result = []
        for i in range(target_length):
            char_index = (seed + i) % len(chars)
            result.append(chars[char_index])
        
        return ''.join(result)
    
    def _get_character_set(self) -> str:
        """
        Get character set string based on configured character class.
        
        Returns:
            String containing all valid characters for the current character class
        
        Raises:
            ValueError: If character_class is invalid (should not happen if __init__ validated)
        
        Examples:
            >>> masker = GenericMasker(character_class="alphanumeric")
            >>> masker._get_character_set()
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            >>> 
            >>> masker = GenericMasker(character_class="alpha")
            >>> masker._get_character_set()
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
            >>> 
            >>> masker = GenericMasker(character_class="numeric")
            >>> masker._get_character_set()
            '0123456789'
        """
        if self.character_class == "alphanumeric":
            return self.ALPHANUMERIC_CHARS
        elif self.character_class == "alpha":
            return self.ALPHA_CHARS
        elif self.character_class == "numeric":
            return self.NUMERIC_CHARS
        else:
            # Should not reach here if __init__ validated properly
            raise ValueError(
                f"Invalid character_class '{self.character_class}'. "
                f"Must be one of: {', '.join(sorted(self.VALID_CHARACTER_CLASSES))}"
            )
    
    def _validate_character_class(self, character_class: str) -> bool:
        """
        Validate if character class name is supported.
        
        Args:
            character_class: Character class name to validate
        
        Returns:
            True if valid, False otherwise
        
        Examples:
            >>> masker = GenericMasker()
            >>> masker._validate_character_class("alphanumeric")
            True
            >>> masker._validate_character_class("alpha")
            True
            >>> masker._validate_character_class("numeric")
            True
            >>> masker._validate_character_class("invalid")
            False
        """
        return character_class in self.VALID_CHARACTER_CLASSES
