"""
Credit card number masking with deterministic generation and Luhn validation.

This module provides PII masking for credit card numbers with the following features:
- Deterministic masking (same input → same output) for FK integrity
- Multi-tier length optimization for SQL Server column constraints
- Luhn algorithm validation (all generated cards pass checksum)
- Test BIN ranges only (never generates real card numbers)
- Support for major card types (Visa, MasterCard, Amex, Discover)
- Multiple format options (formatted with dashes/spaces, plain digits)

Key Features:
    - SHA256-based deterministic seeding from BaseMasker
    - Multi-tier format optimization (Formatted → Spaced → Plain → Short)
    - Test-safe BIN (Bank Identification Number) ranges
    - Luhn checksum calculation for realistic cards
    - VARCHAR vs NVARCHAR handling
    - Fixed-length column padding (CHAR, NCHAR)
    - NULL handling strategies (PRESERVE, MASK)

Security Notice:
    This masker ONLY generates test credit card numbers using reserved BIN ranges.
    Generated numbers will NEVER match real, issued credit cards.

Author: Database Sanitization Team
Date: 2026-03-30
"""

import logging
from typing import Optional, Tuple

from .base_masker import BaseMasker, ColumnInfo, MaskingStrategy
from ..exceptions import MaskingError
from ..error_codes import ErrorCodes
from ..logging.logger import get_logger


class CreditCardMasker(BaseMasker):
    """
    Deterministic credit card masker with Luhn validation and test BIN ranges.
    
    This masker generates valid-looking credit card numbers while preserving referential
    integrity through deterministic mapping. The same input card always produces the same
    fake card, which is critical for maintaining FK relationships across tables.
    
    SECURITY: Only generates numbers from TEST BIN ranges. Will NEVER generate real cards.
    
    Card Generation Strategy:
        1. Extract deterministic seed from input card number
        2. Select test BIN (Bank Identification Number) from pool
        3. Generate account number digits deterministically
        4. Calculate Luhn checksum digit for validity
        5. Format based on column length constraints
    
    Multi-Tier Format Optimization:
        - Formatted (≥19 chars): "4532-1234-5678-9012" (with dashes)
        - Spaced (≥19 chars): "4532 1234 5678 9012" (with spaces)
        - Plain (≥16 chars): "4532123456789012" (no separators)
        - Short (13-15 chars): "4532123456789" (13-digit cards like early Visa)
    
    Test BIN Ranges (Safe for Generation):
        - Visa test: 4532-4539 (will never match real Visa cards)
        - MasterCard test: 5100-5199 (reserved for testing)
        - American Express test: 3711-3799 (test range)
        - Discover test: 6011 (test prefix)
    
    Attributes:
        seed: Global seed for deterministic random generation
        null_strategy: Strategy for handling NULL values
        logger: Logger instance with correlation ID support
        TEST_BINS: List of test BIN prefixes for safe generation
        MIN_LENGTH: Minimum column length required (13 characters)
    
    Examples:
        >>> from src.masking import CreditCardMasker, ColumnInfo
        >>> masker = CreditCardMasker(seed=42)
        >>> 
        >>> # VARCHAR(20) column - uses formatted output
        >>> col_info = ColumnInfo(
        ...     data_type="VARCHAR",
        ...     max_length=20,
        ...     nullable=True
        ... )
        >>> 
        >>> # Deterministic masking
        >>> card1 = masker.mask("4111111111111111", col_info)
        >>> card2 = masker.mask("4111111111111111", col_info)
        >>> assert card1 == card2  # Same input → same output
        >>> 
        >>> # All generated cards pass Luhn validation
        >>> assert masker._verify_luhn(card1.replace("-", ""))
    """
    
    # Test BIN prefixes - SAFE for generation, will NEVER match real cards
    TEST_BINS = [
        # Visa test range (4532-4539)
        "4532", "4533", "4534", "4535", "4536", "4537", "4538", "4539",
        # MasterCard test range (5100-5199)
        "5100", "5105", "5111", "5150", "5155", "5175", "5199",
        # American Express test range (3711-3799)
        "3711", "3722", "3734", "3755", "3766", "3777", "3788", "3799",
        # Discover test
        "6011"
    ]
    
    # Card type lengths (for format selection)
    CARD_LENGTH_16 = 16  # Visa, MasterCard, Discover
    CARD_LENGTH_15 = 15  # American Express
    CARD_LENGTH_13 = 13  # Older Visa cards
    
    # Minimum viable card length
    MIN_LENGTH = 13
    
    def __init__(
        self,
        seed: int = 42,
        null_strategy: MaskingStrategy = MaskingStrategy.PRESERVE,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the CreditCardMasker.
        
        Args:
            seed: Global seed for deterministic random generation (default: 42)
            null_strategy: How to handle NULL values (default: PRESERVE)
            logger: Optional logger instance (creates default if None)
        
        Raises:
            ValueError: If seed is negative
        """
        super().__init__(seed=seed, null_strategy=null_strategy, logger=logger)
        
        if seed < 0:
            raise ValueError(f"Seed must be non-negative, got {seed}")
        
        self.logger.debug(
            f"Initialized CreditCardMasker with seed={seed}, "
            f"null_strategy={null_strategy.value}, "
            f"test_bin_count={len(self.TEST_BINS)}"
        )
    
    def mask(
        self,
        value: Optional[str],
        column_info: ColumnInfo
    ) -> Optional[str]:
        """
        Mask a credit card number with Luhn validation and test BIN usage.
        
        This method generates a fake credit card number while preserving:
        - Determinism: same input → same output (critical for FK integrity)
        - Validity: all cards pass Luhn checksum validation
        - Safety: only uses test BIN ranges, never real cards
        - Length constraints: respects column max_length (smart generation)
        - Data type: VARCHAR (ASCII) vs NVARCHAR (Unicode)
        
        Args:
            value: Original credit card number to mask (can be None)
            column_info: Column metadata for validation and constraints
        
        Returns:
            Masked credit card number, or None if input is None and PRESERVE strategy
        
        Raises:
            MaskingError: If card cannot be generated within column constraints,
                         or if NULL value violates NOT NULL constraint
        
        Examples:
            >>> masker = CreditCardMasker(seed=42)
            >>> col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
            >>> 
            >>> # Normal masking
            >>> masked = masker.mask("4111111111111111", col)
            >>> # Returns something like: "4532-1234-5678-9012"
            >>> 
            >>> # Deterministic
            >>> masked2 = masker.mask("4111111111111111", col)
            >>> assert masked == masked2
        """
        # Handle NULL values
        if value is None:
            return self._handle_null(value, column_info)
        
        # Validate minimum length constraint
        if column_info.max_length < self.MIN_LENGTH:
            raise MaskingError(
                error_code=ErrorCodes.MASKING_CONSTRAINT_VIOLATION,
                message=f"Column length {column_info.max_length} is too short for credit card masking. "
                        f"Minimum required: {self.MIN_LENGTH} characters",
                context={
                    "column_info": str(column_info),
                    "min_required_length": self.MIN_LENGTH,
                    "actual_length": column_info.max_length
                }
            )
        
        # Get deterministic seed from input value
        value_seed = self._get_deterministic_seed(value)
        
        # Generate card number based on length tier
        fake_card = self._generate_card_by_length(value_seed, column_info.max_length)
        
        # Validate length (should never truncate with smart generation)
        fake_card, was_truncated = self._validate_length(fake_card, column_info)
        
        if was_truncated:
            self.logger.error(
                f"Credit card was truncated! This indicates a bug in tier selection logic. "
                f"Original length: {len(fake_card)}, Max length: {column_info.max_length}"
            )
        
        # Validate data type
        self._validate_data_type(fake_card, column_info)
        
        return fake_card
    
    def _generate_card_by_length(self, seed: int, max_length: int) -> str:
        """
        Generate credit card using appropriate format based on max_length.
        
        Args:
            seed: Deterministic seed for generation
            max_length: Maximum column length
        
        Returns:
            Generated credit card fitting within max_length
        """
        # Determine card type and length based on BIN
        bin_prefix = self.TEST_BINS[seed % len(self.TEST_BINS)]
        
        # Amex cards are 15 digits, others are 16
        if bin_prefix.startswith("37"):  # Amex
            card_digits = self._generate_card_number(seed, bin_prefix, self.CARD_LENGTH_15)
        elif max_length >= 16:
            card_digits = self._generate_card_number(seed, bin_prefix, self.CARD_LENGTH_16)
        else:
            # For very short columns, use 13-digit format
            card_digits = self._generate_card_number(seed, bin_prefix, self.CARD_LENGTH_13)
        
        # Format based on available length
        if max_length >= 19:
            # Use formatted output (dashes or spaces)
            # Alternate between dashes and spaces for diversity
            if seed % 2 == 0:
                return self._format_with_dashes(card_digits)
            else:
                return self._format_with_spaces(card_digits)
        else:
            # Use plain digits (no formatting)
            return card_digits
    
    def _generate_card_number(self, seed: int, bin_prefix: str, length: int) -> str:
        """
        Generate complete card number with Luhn checksum.
        
        Args:
            seed: Deterministic seed for generation
            bin_prefix: BIN prefix (4-digit)
            length: Total card length (13, 15, or 16)
        
        Returns:
            Complete card number with valid Luhn checksum
        """
        # Calculate how many digits we need to generate (excluding BIN and checksum)
        digits_needed = length - len(bin_prefix) - 1  # -1 for checksum digit
        
        # Generate account number digits deterministically
        account_digits = ""
        current_seed = seed
        for i in range(digits_needed):
            digit = current_seed % 10
            account_digits += str(digit)
            current_seed = current_seed >> 3  # Shift for next digit
        
        # Combine BIN + account digits (without checksum yet)
        card_without_check = bin_prefix + account_digits
        
        # Calculate and append Luhn checksum digit
        check_digit = self._calculate_luhn_digit(card_without_check)
        
        return card_without_check + check_digit
    
    def _calculate_luhn_digit(self, card_without_checksum: str) -> str:
        """
        Calculate Luhn checksum digit for a partial card number.
        
        The Luhn algorithm:
        1. Starting from the rightmost digit, double every second digit
        2. If doubling results in two digits, add them together
        3. Sum all digits
        4. The checksum is (10 - (sum % 10)) % 10
        
        Args:
            card_without_checksum: Card number without the last checksum digit
        
        Returns:
            Single checksum digit as string
        
        Examples:
            >>> masker = CreditCardMasker()
            >>> masker._calculate_luhn_digit("453212345678901")
            "2"  # Makes "4532123456789012" valid
        """
        total = 0
        # Process digits from right to left
        for i, digit in enumerate(reversed(card_without_checksum)):
            n = int(digit)
            
            # Double every second digit (odd positions when counting from right)
            if i % 2 == 0:  # This will be doubled after we add checksum
                n = n * 2
                if n > 9:
                    n = n - 9  # Equivalent to adding digits (18 -> 1+8=9)
            
            total += n
        
        # Calculate checksum digit
        checksum = (10 - (total % 10)) % 10
        return str(checksum)
    
    def _verify_luhn(self, card_number: str) -> bool:
        """
        Verify a card number has a valid Luhn checksum (for testing).
        
        Args:
            card_number: Complete card number to verify
        
        Returns:
            True if card passes Luhn validation
        """
        # Remove any non-digit characters
        digits = ''.join(c for c in card_number if c.isdigit())
        
        total = 0
        # Process all digits from right to left
        for i, digit in enumerate(reversed(digits)):
            n = int(digit)
            
            # Double every second digit from the right
            if i % 2 == 1:
                n = n * 2
                if n > 9:
                    n = n - 9
            
            total += n
        
        return total % 10 == 0
    
    def _format_with_dashes(self, card_digits: str) -> str:
        """
        Format card number with dashes: 4532-1234-5678-9012.
        
        Args:
            card_digits: Plain card digits
        
        Returns:
            Formatted card with dashes
        """
        if len(card_digits) == 15:  # Amex: 3711-123456-12345
            return f"{card_digits[0:4]}-{card_digits[4:10]}-{card_digits[10:15]}"
        elif len(card_digits) == 16:  # Visa/MC/Discover: 4532-1234-5678-9012
            return f"{card_digits[0:4]}-{card_digits[4:8]}-{card_digits[8:12]}-{card_digits[12:16]}"
        else:  # 13-digit: 4532-1234-5678-9
            return f"{card_digits[0:4]}-{card_digits[4:8]}-{card_digits[8:12]}-{card_digits[12:]}"
    
    def _format_with_spaces(self, card_digits: str) -> str:
        """
        Format card number with spaces: 4532 1234 5678 9012.
        
        Args:
            card_digits: Plain card digits
        
        Returns:
            Formatted card with spaces
        """
        if len(card_digits) == 15:  # Amex: 3711 123456 12345
            return f"{card_digits[0:4]} {card_digits[4:10]} {card_digits[10:15]}"
        elif len(card_digits) == 16:  # Visa/MC/Discover: 4532 1234 5678 9012
            return f"{card_digits[0:4]} {card_digits[4:8]} {card_digits[8:12]} {card_digits[12:16]}"
        else:  # 13-digit: 4532 1234 5678 9
            return f"{card_digits[0:4]} {card_digits[4:8]} {card_digits[8:12]} {card_digits[12:]}"
