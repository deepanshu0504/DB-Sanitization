"""
Name masking with deterministic generation using Faker library.

This module provides PII masking for personal names with the following features:
- Deterministic masking (same input → same output) for FK integrity
- Multi-tier length optimization for SQL Server column constraints
- Support for first names, last names, and full names
- Handles hyphenated names, prefixes, and suffixes
- Unicode support for international names
- Realistic fake name generation using Faker library

Key Features:
    - Faker library integration with deterministic seeding
    - Multi-tier length optimization (Full → First+Last → First → Initial)
    - Structure detection (prefixes, suffixes, hyphenation)
    - VARCHAR vs NVARCHAR handling (ASCII vs Unicode)
    - Fixed-length column padding (CHAR, NCHAR)
    - NULL handling strategies (PRESERVE, MASK)

Author: Database Sanitization Team
Date: 2026-03-26
"""

import re
import logging
from typing import Optional, Dict, Any
from faker import Faker

from .base_masker import BaseMasker, ColumnInfo, MaskingStrategy
from ..exceptions import MaskingError
from ..error_codes import ErrorCodes
from ..logging.logger import get_logger


class NameMasker(BaseMasker):
    """
    Deterministic name masker using Faker library for realistic name generation.
    
    This masker generates realistic fake names while preserving referential integrity
    through deterministic mapping. The same input name always produces the same fake
    name, which is critical for maintaining FK relationships across tables.
    
    Name Generation Strategy:
        Uses Faker library with deterministic seeding to generate names.
        The seed is derived from the input name's hash, ensuring consistency.
    
    Multi-Tier Length Optimization:
        - Full (20+ chars): "Dr. John Smith Jr." (with prefix/suffix when detected)
        - First+Last (10-19 chars): "John Smith"
        - First Only (4-9 chars): "John"
        - Initial (2-3 chars): "J" or "JS"
        - Error (<2 chars): Raise MaskingError
    
    Supported Name Formats:
        - First names: "John", "Mary"
        - Last names: "Smith", "Johnson"
        - Full names: "John Smith", "Mary Johnson"
        - With prefixes: "Dr. John Smith", "Mr. Robert Jones"
        - With suffixes: "John Smith Jr.", "Robert Jones III"
        - Hyphenated: "Mary-Jane", "Jean-Pierre"
        - Unicode: "José", "François", "李明", "田中"
    
    Attributes:
        seed: Global seed for deterministic random generation
        null_strategy: Strategy for handling NULL values
        logger: Logger instance with correlation ID support
        MIN_LENGTH: Minimum column length required (2 characters)
    
    Examples:
        >>> from src.masking import NameMasker, ColumnInfo
        >>> masker = NameMasker(seed=42)
        >>> 
        >>> # VARCHAR(50) column - uses full name format
        >>> col_info = ColumnInfo(
        ...     data_type="VARCHAR",
        ...     max_length=50,
        ...     nullable=True
        ... )
        >>> 
        >>> # Deterministic masking
        >>> name1 = masker.mask("John Doe", col_info)
        >>> name2 = masker.mask("John Doe", col_info)
        >>> assert name1 == name2  # Same input → same output
        >>> 
        >>> # Different inputs produce different outputs
        >>> name3 = masker.mask("Jane Smith", col_info)
        >>> assert name1 != name3
        >>> 
        >>> # Short column uses first name only
        >>> short_col = ColumnInfo(data_type="VARCHAR", max_length=10, nullable=True)
        >>> short_name = masker.mask("Jonathan", short_col)
        >>> # Returns: "John" (or similar short first name)
    """
    
    # Minimum column length required for name masking
    MIN_LENGTH = 2
    
    # Common name prefixes (titles)
    NAME_PREFIXES = {
        "dr", "dr.", "mr", "mr.", "ms", "ms.", "mrs", "mrs.",
        "miss", "prof", "prof.", "rev", "rev.", "sir", "dame"
    }
    
    # Common name suffixes
    NAME_SUFFIXES = {
        "jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v",
        "esq", "esq.", "phd", "ph.d", "md", "m.d.", "dds", "d.d.s."
    }
    
    # Pattern for detecting hyphenated names
    HYPHEN_PATTERN = re.compile(r'[A-Za-z\u00C0-\u017F]+-[A-Za-z\u00C0-\u017F]+')
    
    # Pattern for valid name characters (letters, spaces, hyphens, apostrophes, periods)
    VALID_NAME_PATTERN = re.compile(r'^[A-Za-z\u00C0-\u017F\s\-\'.]+$')
    
    def __init__(
        self,
        seed: int = 42,
        null_strategy: MaskingStrategy = MaskingStrategy.PRESERVE,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the name masker.
        
        Args:
            seed: Global seed for deterministic random generation (default: 42)
            null_strategy: Strategy for handling NULL values (default: PRESERVE)
            logger: Logger instance with correlation ID support (default: auto-created)
        
        Examples:
            >>> # Default initialization
            >>> masker = NameMasker()
            >>> 
            >>> # Custom seed for different organization
            >>> masker = NameMasker(seed=12345)
            >>> 
            >>> # Always mask NULLs
            >>> masker = NameMasker(null_strategy=MaskingStrategy.MASK)
        """
        super().__init__(seed=seed, null_strategy=null_strategy, logger=logger)
        self.logger.info(
            f"NameMasker initialized with seed={seed}, null_strategy={null_strategy.value}"
        )
    
    def mask(self, value: Optional[str], column_info: ColumnInfo) -> Optional[str]:
        """
        Mask a name deterministically.
        
        This method generates a fake name that:
        - Is deterministic (same input → same output)
        - Uses Faker library for realistic names
        - Respects column length constraints
        - Validates against column data type
        - Handles NULL values per configured strategy
        
        Args:
            value: Original name (or None if NULL)
            column_info: Column metadata from SchemaExtractor
        
        Returns:
            Fake name matching column constraints, or None if value is NULL
            and null_strategy is PRESERVE
        
        Raises:
            MaskingError: If column too short (<2 chars), invalid data type,
                          or NULL on NOT NULL column with PRESERVE strategy
        
        Examples:
            >>> masker = NameMasker(seed=42)
            >>> col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
            >>> 
            >>> # Full name format
            >>> masker.mask("John Doe", col)
            'Michael Smith'  # Deterministic
            >>> 
            >>> # NULL handling
            >>> masker.mask(None, col)
            None  # PRESERVE strategy
            >>> 
            >>> # Short column
            >>> short_col = ColumnInfo(data_type="VARCHAR", max_length=10, nullable=True)
            >>> masker.mask("Jonathan", short_col)
            'John'  # First name only
        """
        # Handle NULL values
        if value is None:
            return self._handle_null(value, column_info)
        
        # Strip whitespace
        value = value.strip()
        
        # Validate name format (log warning if invalid, but continue masking)
        if not self._validate_name_format(value):
            self.logger.warning(
                "Input does not match name format, masking anyway (AI may have false positives)",
                extra={
                    "value_hash": self._hash_value(value),
                    "column_type": column_info.data_type
                }
            )
        
        # Detect name structure
        name_structure = self._detect_name_type(value)
        
        # Generate deterministic seed from input
        seed = self._get_deterministic_seed(value)
        
        # Generate fake name based on length constraints
        fake_name = self._generate_name(seed, name_structure, column_info.effective_max_length)
        
        # Validate length constraints
        fake_name = self._validate_length(fake_name, column_info)
        
        # Validate data type
        self._validate_data_type(fake_name, column_info)
        
        # Log successful masking (PII-safe)
        self.logger.debug(
            "Masked name successfully",
            extra={
                "value_hash": self._hash_value(value),
                "fake_length": len(fake_name),
                "max_length": column_info.max_length,
                "data_type": column_info.data_type,
                "name_tier": self._get_name_tier(column_info.effective_max_length)
            }
        )
        
        return fake_name
    
    def _generate_name(self, seed: int, name_structure: Dict[str, Any], max_length: int) -> str:
        """
        Generate a fake name deterministically based on seed and length constraints.
        
        Uses Faker library with deterministic seeding for realistic name generation.
        Applies multi-tier strategy based on available column length.
        
        Multi-tier length strategy:
        - Full (20+ chars): "Dr. John Smith Jr." (with prefix/suffix)
        - First+Last (10-19 chars): "John Smith"
        - First Only (4-9 chars): "John"
        - Initial (2-3 chars): "J" or "JS"
        - Error (<2 chars): Raise MaskingError
        
        Args:
            seed: Deterministic seed from input name
            name_structure: Dict with name components (prefix, suffix, hyphenated, etc.)
            max_length: Maximum column length
        
        Returns:
            Formatted fake name string
        
        Raises:
            MaskingError: If max_length < 2 (minimum required)
        
        Examples:
            >>> masker = NameMasker(seed=42)
            >>> structure = {"has_prefix": False, "has_suffix": False, "is_hyphenated": False}
            >>> masker._generate_name(12345, structure, 50)
            'Michael Smith'  # Full name
            >>> 
            >>> masker._generate_name(12345, structure, 10)
            'Michael'  # First name only
            >>> 
            >>> masker._generate_name(12345, structure, 2)
            'M'  # Initial only
        """
        # Check minimum length requirement
        if max_length < self.MIN_LENGTH:
            raise MaskingError(
                message=f"Column too short for name masking (min {self.MIN_LENGTH} chars required, got {max_length})",
                error_code=ErrorCodes.MASKING_LENGTH_EXCEEDED,
                is_retryable=False,
                suggested_action=f"Increase column length to at least {self.MIN_LENGTH} characters",
                operation_context={
                    "column_type": "name",
                    "max_length": max_length,
                    "minimum_required": self.MIN_LENGTH
                }
            )
        
        # Initialize Faker with deterministic seed
        Faker.seed(seed)
        fake = Faker()
        
        # Generate based on available length
        if max_length >= 20:
            # Full format with potential prefix/suffix
            first_name = fake.first_name()
            last_name = fake.last_name()
            
            # Handle hyphenation if detected in original
            if name_structure.get("is_hyphenated"):
                # Generate hyphenated first name
                first_part = fake.first_name()
                second_part = fake.first_name()
                first_name = f"{first_part}-{second_part}"
            
            # Build full name
            full_name = f"{first_name} {last_name}"
            
            # Add prefix if detected and space allows
            if name_structure.get("has_prefix") and len(full_name) + 4 <= max_length:
                prefix = fake.prefix()
                full_name = f"{prefix} {full_name}"
            
            # Add suffix if detected and space allows
            if name_structure.get("has_suffix") and len(full_name) + 4 <= max_length:
                suffix = fake.suffix()
                full_name = f"{full_name} {suffix}"
            
            return full_name[:max_length]
        
        elif max_length >= 10:
            # First + Last name format
            first_name = fake.first_name()
            last_name = fake.last_name()
            full_name = f"{first_name} {last_name}"
            
            # If too long, try shorter names
            attempts = 0
            while len(full_name) > max_length and attempts < 5:
                first_name = fake.first_name()
                last_name = fake.last_name()
                full_name = f"{first_name} {last_name}"
                attempts += 1
            
            return full_name[:max_length]
        
        elif max_length >= 4:
            # First name only
            first_name = fake.first_name()
            
            # If too long, try shorter names
            attempts = 0
            while len(first_name) > max_length and attempts < 5:
                first_name = fake.first_name()
                attempts += 1
            
            return first_name[:max_length]
        
        else:
            # Initial(s) only - use first 1-2 chars of generated name
            name = fake.first_name()
            if max_length >= 3:
                # Try to get first + last initial
                last = fake.last_name()
                return f"{name[0]}{last[0]}"[:max_length]
            else:
                # Just first initial
                return name[0]
    
    def _detect_name_type(self, value: str) -> Dict[str, Any]:
        """
        Detect name structure and components from input.
        
        Analyzes the input to identify:
        - Prefixes (Dr., Mr., Ms., etc.)
        - Suffixes (Jr., Sr., II, III, etc.)
        - Hyphenated names (Mary-Jane, Jean-Pierre)
        - Multiple words (middle names or compound names)
        
        Args:
            value: Input name string
        
        Returns:
            Dict with detected components:
                - has_prefix: bool
                - has_suffix: bool
                - is_hyphenated: bool
                - word_count: int
        
        Examples:
            >>> masker = NameMasker()
            >>> masker._detect_name_type("Dr. John Smith Jr.")
            {'has_prefix': True, 'has_suffix': True, 'is_hyphenated': False, 'word_count': 4}
            >>> 
            >>> masker._detect_name_type("Mary-Jane")
            {'has_prefix': False, 'has_suffix': False, 'is_hyphenated': True, 'word_count': 1}
        """
        words = value.split()
        word_count = len(words)
        
        structure = {
            "has_prefix": False,
            "has_suffix": False,
            "is_hyphenated": False,
            "word_count": word_count
        }
        
        # Check for prefix (first word)
        if word_count > 1:
            first_word = words[0].lower().strip(".")
            if first_word in self.NAME_PREFIXES:
                structure["has_prefix"] = True
        
        # Check for suffix (last word)
        if word_count > 1:
            last_word = words[-1].lower().strip(".")
            if last_word in self.NAME_SUFFIXES:
                structure["has_suffix"] = True
        
        # Check for hyphenation anywhere in the name
        if self.HYPHEN_PATTERN.search(value):
            structure["is_hyphenated"] = True
        
        return structure
    
    def _validate_name_format(self, value: str) -> bool:
        """
        Validate if input matches a reasonable name format.
        
        Accepts:
        - Letters (including Unicode: José, François, 李明)
        - Spaces, hyphens, apostrophes, periods
        - Must have at least one letter
        
        Rejects:
        - Numbers
        - Most special characters (except - ' .)
        - Excessive whitespace
        - Empty strings
        
        Args:
            value: Input name to validate
        
        Returns:
            True if format matches, False otherwise
        
        Note:
            This is a soft validation - if format is invalid, we log a warning
            but still proceed with masking (AI may have false positives).
        
        Examples:
            >>> masker = NameMasker()
            >>> masker._validate_name_format("John Smith")
            True
            >>> masker._validate_name_format("Mary-Jane O'Brien")
            True
            >>> masker._validate_name_format("José García")
            True
            >>> masker._validate_name_format("123 Main St")
            False
        """
        if not value or not value.strip():
            return False
        
        # Check against valid name pattern
        if not self.VALID_NAME_PATTERN.match(value):
            return False
        
        # Must contain at least one letter
        if not any(c.isalpha() for c in value):
            return False
        
        # Check for excessive whitespace (more than 2 consecutive spaces)
        if "   " in value:
            return False
        
        return True
    
    def _get_name_tier(self, max_length: int) -> str:
        """
        Determine which name format tier will be used for given length.
        
        Args:
            max_length: Maximum column length
        
        Returns:
            Tier name: "full", "first_last", "first_only", "initial", or "error"
        
        Examples:
            >>> masker = NameMasker()
            >>> masker._get_name_tier(50)
            'full'
            >>> masker._get_name_tier(15)
            'first_last'
            >>> masker._get_name_tier(8)
            'first_only'
            >>> masker._get_name_tier(2)
            'initial'
            >>> masker._get_name_tier(1)
            'error'
        """
        if max_length >= 20:
            return "full"
        elif max_length >= 10:
            return "first_last"
        elif max_length >= 4:
            return "first_only"
        elif max_length >= self.MIN_LENGTH:
            return "initial"
        else:
            return "error"
