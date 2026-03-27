"""
Phone number masking with deterministic generation and multi-tier length optimization.

This module provides PII masking for phone numbers with the following features:
- Deterministic masking (same input → same output) for FK integrity
- Multi-tier length optimization for SQL Server column constraints
- Support for US and international phone formats
- Uses reserved 555 area code (fictional use in North America)
- Format validation with fallback to masking anyway (AI false positives)

Key Features:
    - SHA256-based deterministic seeding from BaseMasker
    - Multi-tier length optimization (Standard → Compact → Minimal)
    - Modulo arithmetic for digit generation (predictable, testable)
    - VARCHAR vs NVARCHAR handling (ASCII vs Unicode)
    - Fixed-length column padding (CHAR, NCHAR)
    - NULL handling strategies (PRESERVE, MASK)

Author: Database Sanitization Team
Date: 2026-03-26
"""

import re
import logging
from typing import Optional

from .base_masker import BaseMasker, ColumnInfo, MaskingStrategy
from ..exceptions import MaskingError
from ..error_codes import ErrorCodes
from ..logging.logger import get_logger


class PhoneMasker(BaseMasker):
    """
    Deterministic phone number masker with multi-tier length optimization.
    
    This masker generates valid phone numbers while preserving referential integrity
    through deterministic mapping. The same input phone always produces the same fake
    phone, which is critical for maintaining FK relationships across tables.
    
    Area Code Selection:
        Uses 555 (reserved for fictional use in North America) to avoid generating
        real phone numbers that could accidentally match actual numbers.
    
    Generation Strategy:
        1. Extract deterministic seed from input phone
        2. Generate exchange (middle 3 digits): ((seed // 10000) % 900) + 100
        3. Generate subscriber (last 4 digits): (seed % 9000) + 1000
        4. Combine with 555 area code
        5. Format based on length constraints
    
    Length Optimization Tiers:
        - Standard (14+ chars): (555) 555-5555 (parentheses + dashes)
        - Compact (12-13 chars): 555-555-5555 (dashes only)
        - Minimal (10-11 chars): 5555555555 (plain digits)
        - Error (<10 chars): Raise MaskingError
    
    Supported Input Formats:
        - US standard: (555) 123-4567, 555-123-4567, 555.123.4567
        - Plain digits: 5551234567
        - International: +1-555-123-4567, +44 20 1234 5678
        - With extensions: 555-123-4567 ext. 123 (extension ignored)
    
    Attributes:
        seed: Global seed for deterministic random generation
        null_strategy: Strategy for handling NULL values
        logger: Logger instance with correlation ID support
        AREA_CODE: Fixed area code (555) for all generated phones
        MIN_LENGTH: Minimum column length required (10 characters)
    
    Examples:
        >>> from src.masking import PhoneMasker, ColumnInfo
        >>> masker = PhoneMasker(seed=42)
        >>> 
        >>> # VARCHAR(20) column - uses standard format
        >>> col_info = ColumnInfo(
        ...     data_type="VARCHAR",
        ...     max_length=20,
        ...     nullable=True
        ... )
        >>> 
        >>> # Deterministic masking
        >>> phone1 = masker.mask("(555) 123-4567", col_info)
        >>> phone2 = masker.mask("(555) 123-4567", col_info)
        >>> assert phone1 == phone2  # Same input → same output
        >>> 
        >>> # Different inputs produce different outputs
        >>> phone3 = masker.mask("(555) 987-6543", col_info)
        >>> assert phone1 != phone3
        >>> 
        >>> # Compact format for shorter columns
        >>> short_col = ColumnInfo(data_type="VARCHAR", max_length=12, nullable=True)
        >>> compact_phone = masker.mask("5551234567", short_col)
        >>> # Returns: 555-555-5555 (12 chars)
    """
    
    # Fixed area code for all generated phone numbers (555 reserved for fictional use)
    AREA_CODE = 555
    
    # Minimum column length required for phone masking
    MIN_LENGTH = 10
    
    # Phone number format validation patterns
    # US formats: (555) 123-4567, 555-123-4567, 555.123.4567, 5551234567
    US_PHONE_PATTERN = re.compile(
        r'^(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}(?:\s*(?:ext|x|#)\.?\s*\d+)?$',
        re.IGNORECASE
    )
    
    # International format: +XX to +XXX followed by number
    INTL_PHONE_PATTERN = re.compile(
        r'^\+[0-9]{1,3}[-.\s]?[0-9]{1,14}$'
    )
    
    def __init__(
        self,
        seed: int = 42,
        null_strategy: MaskingStrategy = MaskingStrategy.PRESERVE,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the phone number masker.
        
        Args:
            seed: Global seed for deterministic random generation (default: 42)
            null_strategy: Strategy for handling NULL values (default: PRESERVE)
            logger: Logger instance with correlation ID support (default: auto-created)
        
        Examples:
            >>> # Default initialization
            >>> masker = PhoneMasker()
            >>> 
            >>> # Custom seed for different organization
            >>> masker = PhoneMasker(seed=12345)
            >>> 
            >>> # Always mask NULLs
            >>> masker = PhoneMasker(null_strategy=MaskingStrategy.MASK)
        """
        super().__init__(seed=seed, null_strategy=null_strategy, logger=logger)
        self.logger.info(
            f"PhoneMasker initialized with seed={seed}, null_strategy={null_strategy.value}"
        )
    
    def mask(self, value: Optional[str], column_info: ColumnInfo) -> Optional[str]:
        """
        Mask a phone number deterministically.
        
        This method generates a fake phone number that:
        - Is deterministic (same input → same output)
        - Uses reserved 555 area code
        - Respects column length constraints
        - Validates against column data type
        - Handles NULL values per configured strategy
        
        Args:
            value: Original phone number (or None if NULL)
            column_info: Column metadata from SchemaExtractor
        
        Returns:
            Fake phone number matching column constraints, or None if value is NULL
            and null_strategy is PRESERVE
        
        Raises:
            MaskingError: If column too short (<10 chars), invalid data type,
                          or NULL on NOT NULL column with PRESERVE strategy
        
        Examples:
            >>> masker = PhoneMasker(seed=42)
            >>> col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
            >>> 
            >>> # Standard format
            >>> masker.mask("(555) 123-4567", col)
            '(555) 555-1234'  # Deterministic
            >>> 
            >>> # NULL handling
            >>> masker.mask(None, col)
            None  # PRESERVE strategy
            >>> 
            >>> # Short column
            >>> short_col = ColumnInfo(data_type="VARCHAR", max_length=12, nullable=True)
            >>> masker.mask("5551234567", short_col)
            '555-555-1234'  # Compact format
        """
        # Handle NULL values
        if value is None:
            return self._handle_null(value, column_info)
        
        # Strip whitespace
        value = value.strip()
        
        # Validate phone format (log warning if invalid, but continue masking)
        if not self._validate_phone_format(value):
            self.logger.warning(
                "Input does not match phone format, masking anyway (AI may have false positives)",
                extra={
                    "value_hash": self._hash_value(value),
                    "column_type": column_info.data_type
                }
            )
        
        # Generate deterministic seed from input
        seed = self._get_deterministic_seed(value)
        
        # Generate fake phone number based on length constraints
        fake_phone = self._generate_phone(seed, column_info.effective_max_length)
        
        # Validate length constraints
        fake_phone = self._validate_length(fake_phone, column_info)
        
        # Validate data type
        self._validate_data_type(fake_phone, column_info)
        
        # Log successful masking (PII-safe)
        self.logger.debug(
            "Masked phone successfully",
            extra={
                "value_hash": self._hash_value(value),
                "fake_length": len(fake_phone),
                "max_length": column_info.max_length,
                "data_type": column_info.data_type,
                "format_tier": self._get_format_tier(column_info.effective_max_length)
            }
        )
        
        return fake_phone
    
    def _generate_phone(self, seed: int, max_length: int) -> str:
        """
        Generate a fake phone number deterministically based on seed and length constraints.
        
        Uses modulo arithmetic for deterministic digit generation:
        - Exchange (middle 3 digits): ((seed // 10000) % 900) + 100 (range 100-999)
        - Subscriber (last 4 digits): (seed % 9000) + 1000 (range 1000-9999)
        - Area code: Fixed 555 (reserved/fictional)
        
        Multi-tier length strategy:
        - Standard (14+ chars): (555) 555-5555
        - Compact (12-13 chars): 555-555-5555
        - Minimal (10-11 chars): 5555555555
        - Error (<10 chars): Raise MaskingError
        
        Args:
            seed: Deterministic seed from input phone
            max_length: Maximum column length
        
        Returns:
            Formatted fake phone number
        
        Raises:
            MaskingError: If max_length < 10 (minimum required)
        
        Examples:
            >>> masker = PhoneMasker(seed=42)
            >>> masker._generate_phone(12345, 20)
            '(555) 512-2345'  # Standard format
            >>> 
            >>> masker._generate_phone(12345, 12)
            '555-512-2345'  # Compact format
            >>> 
            >>> masker._generate_phone(12345, 10)
            '5555122345'  # Minimal format
        """
        # Check minimum length requirement
        if max_length < self.MIN_LENGTH:
            raise MaskingError(
                message=f"Column too short for phone masking (min {self.MIN_LENGTH} chars required, got {max_length})",
                error_code=ErrorCodes.MASKING_LENGTH_EXCEEDED,
                is_retryable=False,
                suggested_action=f"Increase column length to at least {self.MIN_LENGTH} characters",
                operation_context={
                    "column_type": "phone",
                    "max_length": max_length,
                    "minimum_required": self.MIN_LENGTH
                }
            )
        
        # Generate exchange (middle 3 digits): range 100-999
        exchange = ((seed // 10000) % 900) + 100
        
        # Generate subscriber (last 4 digits): range 1000-9999
        subscriber = (seed % 9000) + 1000
        
        # Format based on available length
        if max_length >= 14:
            # Standard format: (555) 555-5555 (14 chars)
            return f"({self.AREA_CODE}) {exchange:03d}-{subscriber:04d}"
        elif max_length >= 12:
            # Compact format: 555-555-5555 (12 chars)
            return f"{self.AREA_CODE}-{exchange:03d}-{subscriber:04d}"
        else:
            # Minimal format: 5555555555 (10 chars)
            return f"{self.AREA_CODE}{exchange:03d}{subscriber:04d}"
    
    def _validate_phone_format(self, value: str) -> bool:
        """
        Validate if input matches a known phone number format.
        
        Supports:
        - US formats: (555) 123-4567, 555-123-4567, 555.123.4567, 5551234567
        - International: +1-555-123-4567, +44 20 1234 5678
        - With extensions: 555-123-4567 ext. 123
        
        Args:
            value: Input phone number to validate
        
        Returns:
            True if format matches, False otherwise
        
        Note:
            This is a soft validation - if format is invalid, we log a warning
            but still proceed with masking (AI may have false positives).
        
        Examples:
            >>> masker = PhoneMasker()
            >>> masker._validate_phone_format("(555) 123-4567")
            True
            >>> masker._validate_phone_format("+1-555-123-4567")
            True
            >>> masker._validate_phone_format("not a phone")
            False
        """
        # Try US format first (most common)
        if self.US_PHONE_PATTERN.match(value):
            return True
        
        # Try international format
        if self.INTL_PHONE_PATTERN.match(value):
            return True
        
        # Check if it's just digits (10-15 digits is reasonable for phone)
        digits_only = re.sub(r'\D', '', value)
        if 10 <= len(digits_only) <= 15:
            return True
        
        return False
    
    def _get_format_tier(self, max_length: int) -> str:
        """
        Determine which format tier will be used for given length.
        
        Args:
            max_length: Maximum column length
        
        Returns:
            Format tier name: "standard", "compact", "minimal", or "error"
        
        Examples:
            >>> masker = PhoneMasker()
            >>> masker._get_format_tier(20)
            'standard'
            >>> masker._get_format_tier(12)
            'compact'
            >>> masker._get_format_tier(10)
            'minimal'
            >>> masker._get_format_tier(9)
            'error'
        """
        if max_length >= 14:
            return "standard"
        elif max_length >= 12:
            return "compact"
        elif max_length >= self.MIN_LENGTH:
            return "minimal"
        else:
            return "error"
