"""
Social Security Number (SSN) masking with deterministic generation and compliance validation.

This module provides PII masking for Social Security Numbers with the following features:
- Deterministic masking (same input → same output) for FK integrity
- Compliant SSN generation excluding invalid ranges (000, 666, 900-999)
- Support for both formatted (XXX-XX-XXXX) and plain (9-digit) formats
- Format detection and auto-selection based on column length
- Modulo arithmetic for predictable, testable generation

Key Features:
    - SHA256-based deterministic seeding from BaseMasker
    - Valid area code generation (001-665, 667-899) with gap handling
    - Multi-format support (formatted vs plain)
    - VARCHAR vs NVARCHAR handling (ASCII vs Unicode)
    - Fixed-length column padding (CHAR, NCHAR)
    - NULL handling strategies (PRESERVE, MASK)

Valid SSN Ranges:
    - Area codes: 001-665, 667-899 (excludes 000, 666, 900-999)
    - Group codes: 01-99 (after 2011 randomization)
    - Serial numbers: 0001-9999 (after 2011 randomization)

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


class SSNMasker(BaseMasker):
    """
    Deterministic SSN masker with compliance validation and multi-format support.
    
    This masker generates valid Social Security Numbers while preserving referential 
    integrity through deterministic mapping. The same input SSN always produces the 
    same fake SSN, which is critical for maintaining FK relationships across tables.
    
    SSN Format:
        - Formatted: XXX-XX-XXXX (11 characters with dashes)
        - Plain: XXXXXXXXX (9 digits without formatting)
    
    Generation Strategy:
        1. Extract deterministic seed from input SSN
        2. Generate valid area code (001-665, 667-899) using modulo with gap handling
        3. Generate group code (01-99) using modulo arithmetic
        4. Generate serial number (0001-9999) using modulo arithmetic
        5. Format based on column length constraints
    
    Compliance (IRS/SSA Rules):
        - Area code 000: Not assigned
        - Area code 666: Never assigned (reserved)
        - Area codes 900-999: Reserved for ITINs (Individual Taxpayer ID Numbers)
        - Historical exclusions (pre-2011): Group 00, Serial 0000 (now valid after randomization)
    
    Multi-Tier Length Optimization:
        - Formatted (11+ chars): "123-45-6789" (standard format with dashes)
        - Plain (9-10 chars): "123456789" (no dashes)
        - Error (<9 chars): Raise MaskingError (minimum required)
    
    Attributes:
        seed: Global seed for deterministic random generation
        null_strategy: Strategy for handling NULL values
        logger: Logger instance with correlation ID support
        MIN_LENGTH: Minimum column length required (9 characters for plain format)
    
    Examples:
        >>> from src.masking import SSNMasker, ColumnInfo
        >>> masker = SSNMasker(seed=42)
        >>> 
        >>> # VARCHAR(11) column - uses formatted output
        >>> col_info = ColumnInfo(
        ...     data_type="VARCHAR",
        ...     max_length=11,
        ...     nullable=True
        ... )
        >>> 
        >>> # Deterministic masking
        >>> ssn1 = masker.mask("123-45-6789", col_info)
        >>> ssn2 = masker.mask("123-45-6789", col_info)
        >>> assert ssn1 == ssn2  # Same input → same output
        >>> 
        >>> # Different inputs produce different outputs
        >>> ssn3 = masker.mask("987-65-4321", col_info)
        >>> assert ssn1 != ssn3
        >>> 
        >>> # Plain format for shorter columns
        >>> short_col = ColumnInfo(data_type="VARCHAR", max_length=9, nullable=True)
        >>> plain_ssn = masker.mask("123456789", short_col)
        >>> # Returns: "234567890" (9 digits, no dashes)
    """
    
    # Minimum column length required for SSN masking (plain format)
    MIN_LENGTH = 9
    
    # SSN format validation patterns
    # Formatted: XXX-XX-XXXX (validates structure and excludes invalid ranges)
    FORMATTED_SSN_PATTERN = re.compile(
        r'^(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}$'
    )
    
    # Plain: 9 digits (validates structure and excludes invalid ranges)
    PLAIN_SSN_PATTERN = re.compile(
        r'^(?!000|666|9\d{2})\d{3}(?!00)\d{2}(?!0000)\d{4}$'
    )
    
    # Simple format detection (with or without dashes)
    SIMPLE_FORMATTED_PATTERN = re.compile(r'^\d{3}-\d{2}-\d{4}$')
    SIMPLE_PLAIN_PATTERN = re.compile(r'^\d{9}$')
    
    # Valid area code ranges (001-665, 667-899)
    # Total: 665 + 233 = 898 valid area codes
    VALID_AREA_COUNT = 898
    
    def __init__(
        self,
        seed: int = 42,
        null_strategy: MaskingStrategy = MaskingStrategy.PRESERVE,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the SSN masker.
        
        Args:
            seed: Global seed for deterministic random generation (default: 42)
            null_strategy: Strategy for handling NULL values (default: PRESERVE)
            logger: Logger instance with correlation ID support (default: auto-created)
        
        Examples:
            >>> # Default initialization
            >>> masker = SSNMasker()
            >>> 
            >>> # Custom seed for different organization
            >>> masker = SSNMasker(seed=12345)
            >>> 
            >>> # Always mask NULLs
            >>> masker = SSNMasker(null_strategy=MaskingStrategy.MASK)
        """
        super().__init__(seed=seed, null_strategy=null_strategy, logger=logger)
        self.logger.info(
            f"SSNMasker initialized with seed={seed}, null_strategy={null_strategy.value}"
        )
    
    def mask(self, value: Optional[str], column_info: ColumnInfo) -> Optional[str]:
        """
        Mask an SSN deterministically.
        
        This method generates a fake SSN that:
        - Is deterministic (same input → same output)
        - Uses compliant area codes (excludes 000, 666, 900-999)
        - Respects column length constraints
        - Validates against column data type
        - Handles NULL values per configured strategy
        
        Args:
            value: Original SSN (or None if NULL)
            column_info: Column metadata from SchemaExtractor
        
        Returns:
            Fake SSN matching column constraints, or None if value is NULL
            and null_strategy is PRESERVE
        
        Raises:
            MaskingError: If column too short (<9 chars), invalid data type,
                          or NULL on NOT NULL column with PRESERVE strategy
        
        Examples:
            >>> masker = SSNMasker(seed=42)
            >>> col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
            >>> 
            >>> # Formatted output
            >>> masker.mask("123-45-6789", col)
            '234-56-7890'  # Deterministic
            >>> 
            >>> # NULL handling
            >>> masker.mask(None, col)
            None  # PRESERVE strategy
            >>> 
            >>> # Plain format for shorter column
            >>> short_col = ColumnInfo(data_type="VARCHAR", max_length=9, nullable=True)
            >>> masker.mask("123456789", short_col)
            '234567890'  # Plain format (no dashes)
        """
        # Handle NULL values
        if value is None:
            return self._handle_null(value, column_info)
        
        # Strip whitespace
        value = value.strip()
        
        # Validate SSN format (log warning if invalid, but continue masking)
        if not self._validate_ssn_format(value):
            self.logger.warning(
                "Input does not match SSN format, masking anyway (AI may have false positives)",
                extra={
                    "value_hash": self._hash_value(value),
                    "column_type": column_info.data_type
                }
            )
        
        # Detect input format
        input_format = self._detect_ssn_format(value)
        
        # Generate deterministic seed from input
        seed = self._get_deterministic_seed(value)
        
        # Generate fake SSN based on length constraints
        fake_ssn = self._generate_ssn(seed, column_info.effective_max_length)
        
        # Validate length constraints
        fake_ssn = self._validate_length(fake_ssn, column_info)
        
        # Validate data type
        self._validate_data_type(fake_ssn, column_info)
        
        # Log successful masking (PII-safe)
        self.logger.debug(
            "Masked SSN successfully",
            extra={
                "value_hash": self._hash_value(value),
                "fake_length": len(fake_ssn),
                "max_length": column_info.max_length,
                "data_type": column_info.data_type,
                "format_tier": self._get_format_tier(column_info.effective_max_length),
                "input_format": input_format
            }
        )
        
        return fake_ssn
    
    def _generate_ssn(self, seed: int, max_length: int) -> str:
        """
        Generate a fake SSN deterministically based on seed and length constraints.
        
        Uses modulo arithmetic with gap handling to generate compliant SSNs that
        exclude invalid area codes (000, 666, 900-999).
        
        Multi-format strategy:
        - Formatted (11+ chars): "123-45-6789" (XXX-XX-XXXX with dashes)
        - Plain (9-10 chars): "123456789" (9 digits, no dashes)
        - Error (<9 chars): Raise MaskingError
        
        Args:
            seed: Deterministic seed from input SSN
            max_length: Maximum column length
        
        Returns:
            Formatted or plain SSN string
        
        Raises:
            MaskingError: If max_length < 9 (minimum required)
        
        Examples:
            >>> masker = SSNMasker(seed=42)
            >>> masker._generate_ssn(12345, 11)
            '123-45-6789'  # Formatted
            >>> 
            >>> masker._generate_ssn(12345, 9)
            '123456789'  # Plain
        """
        # Check minimum length requirement
        if max_length < self.MIN_LENGTH:
            raise MaskingError(
                message=f"Column too short for SSN masking (min {self.MIN_LENGTH} chars required, got {max_length})",
                error_code=ErrorCodes.MASKING_LENGTH_EXCEEDED,
                is_retryable=False,
                suggested_action=f"Increase column length to at least {self.MIN_LENGTH} characters (9 for plain, 11 for formatted)",
                operation_context={
                    "column_type": "ssn",
                    "max_length": max_length,
                    "minimum_required": self.MIN_LENGTH
                }
            )
        
        # Generate valid area code (001-665, 667-899)
        # Using modulo with offset mapping to skip the 666 gap
        area_offset = seed % self.VALID_AREA_COUNT
        
        # Map offset to valid area code:
        # 0-664 → 001-665
        # 665-897 → 667-899
        if area_offset < 665:
            area = area_offset + 1  # 0→001, 664→665
        else:
            area = area_offset + 2  # 665→667, 897→899
        
        # Generate group code (01-99)
        group = ((seed // self.VALID_AREA_COUNT) % 99) + 1
        
        # Generate serial number (0001-9999)
        serial = ((seed // (self.VALID_AREA_COUNT * 99)) % 9999) + 1
        
        # Format based on available length
        if max_length >= 11:
            # Formatted: XXX-XX-XXXX
            return f"{area:03d}-{group:02d}-{serial:04d}"
        else:
            # Plain: XXXXXXXXX (9 digits)
            return f"{area:03d}{group:02d}{serial:04d}"
    
    def _detect_ssn_format(self, value: str) -> str:
        """
        Detect the format of an input SSN.
        
        Args:
            value: Input SSN string
        
        Returns:
            "formatted" (XXX-XX-XXXX), "plain" (9 digits), or "unknown"
        
        Examples:
            >>> masker = SSNMasker()
            >>> masker._detect_ssn_format("123-45-6789")
            'formatted'
            >>> masker._detect_ssn_format("123456789")
            'plain'
            >>> masker._detect_ssn_format("123 45 6789")
            'unknown'
        """
        if self.SIMPLE_FORMATTED_PATTERN.match(value):
            return "formatted"
        elif self.SIMPLE_PLAIN_PATTERN.match(value):
            return "plain"
        else:
            return "unknown"
    
    def _validate_ssn_format(self, value: str) -> bool:
        """
        Validate if input matches a reasonable SSN format.
        
        Accepts both formatted (XXX-XX-XXXX) and plain (9 digits) formats.
        Validates against excluded area codes (000, 666, 900-999).
        
        Args:
            value: Input SSN to validate
        
        Returns:
            True if format matches, False otherwise
        
        Note:
            This is a soft validation - if format is invalid, we log a warning
            but still proceed with masking (AI may have false positives).
        
        Examples:
            >>> masker = SSNMasker()
            >>> masker._validate_ssn_format("123-45-6789")
            True
            >>> masker._validate_ssn_format("123456789")
            True
            >>> masker._validate_ssn_format("666-45-6789")
            False
            >>> masker._validate_ssn_format("900-45-6789")
            False
        """
        if not value or not value.strip():
            return False
        
        # Check against formatted pattern
        if self.FORMATTED_SSN_PATTERN.match(value):
            return True
        
        # Check against plain pattern
        if self.PLAIN_SSN_PATTERN.match(value):
            return True
        
        return False
    
    def _is_valid_area_code(self, area: int) -> bool:
        """
        Check if an area code is in the valid range.
        
        Valid ranges: 001-665, 667-899
        Invalid: 000, 666, 900-999
        
        Args:
            area: Area code (first 3 digits of SSN)
        
        Returns:
            True if valid, False otherwise
        
        Examples:
            >>> masker = SSNMasker()
            >>> masker._is_valid_area_code(123)
            True
            >>> masker._is_valid_area_code(665)
            True
            >>> masker._is_valid_area_code(666)
            False
            >>> masker._is_valid_area_code(900)
            False
        """
        if area < 1 or area > 899:
            return False
        if area == 666:
            return False
        if area >= 900:
            return False
        return True
    
    def _get_format_tier(self, max_length: int) -> str:
        """
        Determine which SSN format tier will be used for given length.
        
        Args:
            max_length: Maximum column length
        
        Returns:
            Tier name: "formatted", "plain", or "error"
        
        Examples:
            >>> masker = SSNMasker()
            >>> masker._get_format_tier(11)
            'formatted'
            >>> masker._get_format_tier(9)
            'plain'
            >>> masker._get_format_tier(8)
            'error'
        """
        if max_length >= 11:
            return "formatted"
        elif max_length >= self.MIN_LENGTH:
            return "plain"
        else:
            return "error"
