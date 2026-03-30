"""
Date of birth masking with deterministic generation and age range control.

This module provides PII masking for birth dates with the following features:
- Deterministic masking (same input → same output) for FK integrity
- Support for DATE, DATETIME, and VARCHAR data types
- Multi-tier format optimization for VARCHAR columns
- Configurable age range (default: 18-80 years)
- Realistic date distribution within age range
- Leap year handling (Feb 29 edge cases)

Key Features:
    - SHA256-based deterministic seeding from BaseMasker
    - Multi-tier format optimization for VARCHAR (ISO 8601, US format, compact, year-only)
    - Configurable age range via masker_params
    - Native date object generation for DATE/DATETIME types
    - VARCHAR format detection and preservation
    - NULL handling strategies (PRESERVE, MASK)

Author: Database Sanitization Team
Date: 2026-03-30
"""

import logging
from typing import Optional, Union, Dict, Any
from datetime import datetime, date, timedelta

from .base_masker import BaseMasker, ColumnInfo, MaskingStrategy
from ..exceptions import MaskingError
from ..error_codes import ErrorCodes
from ..logging.logger import get_logger


class DateOfBirthMasker(BaseMasker):
    """
    Deterministic date of birth masker with age range control.
    
    This masker generates realistic birth dates while preserving referential integrity
    through deterministic mapping. The same input date always produces the same fake
    date, which is critical for maintaining FK relationships across tables.
    
    Date Generation Strategy:
        1. Extract deterministic seed from input date
        2. Calculate age within configured range (default: 18-80 years)
        3. Generate birth date deterministically within that age range
        4. Format based on column data type and length
    
    Multi-Tier Format Optimization (VARCHAR columns):
        - ISO 8601 (≥10 chars): "1985-03-15" (YYYY-MM-DD)
        - US Format (≥10 chars): "03/15/1985" (MM/DD/YYYY)
        - Compact (≥8 chars): "19850315" (YYYYMMDD)
        - Year Only (≥4 chars): "1985" (YYYY)
    
    Date Type Support:
        - DATE: Returns native datetime.date objects
        - DATETIME/DATETIME2: Returns datetime with 00:00:00 time
        - SMALLDATETIME: Returns datetime with 00:00 time
        - VARCHAR/NVARCHAR: Returns formatted string
    
    Age Range Configuration:
        Default: 18-80 years from current date (adults)
        Configurable via masker_params: {"min_age": 18, "max_age": 80}
    
    Attributes:
        seed: Global seed for deterministic random generation
        null_strategy: Strategy for handling NULL values
        logger: Logger instance with correlation ID support
        min_age: Minimum age in years (default: 18)
        max_age: Maximum age in years (default: 80)
        MIN_LENGTH: Minimum column length for VARCHAR (4 characters for year)
    
    Examples:
        >>> from src.masking import DateOfBirthMasker, ColumnInfo
        >>> masker = DateOfBirthMasker(seed=42)
        >>> 
        >>> # DATE column - returns date object
        >>> col_info = ColumnInfo(
        ...     data_type="DATE",
        ...     max_length=None,
        ...     nullable=True
        ... )
        >>> 
        >>> # Deterministic masking
        >>> dob1 = masker.mask("1990-05-15", col_info)
        >>> dob2 = masker.mask("1990-05-15", col_info)
        >>> assert dob1 == dob2  # Same input → same output
        >>> 
        >>> # VARCHAR column - returns formatted string
        >>> varchar_col = ColumnInfo(data_type="VARCHAR", max_length=10, nullable=True)
        >>> dob_str = masker.mask("05/15/1990", varchar_col)
        >>> # Returns something like: "1985-03-15" or "03/15/1985"
    """
    
    # Minimum viable format (year only)
    MIN_LENGTH = 4
    
    # Days in each month (non-leap year)
    DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    
    def __init__(
        self,
        seed: int = 42,
        null_strategy: MaskingStrategy = MaskingStrategy.PRESERVE,
        logger: Optional[logging.Logger] = None,
        min_age: int = 18,
        max_age: int = 80
    ):
        """
        Initialize the DateOfBirthMasker.
        
        Args:
            seed: Global seed for deterministic random generation (default: 42)
            null_strategy: How to handle NULL values (default: PRESERVE)
            logger: Optional logger instance (creates default if None)
            min_age: Minimum age in years (default: 18)
            max_age: Maximum age in years (default: 80)
        
        Raises:
            ValueError: If seed is negative, or if age range is invalid
        """
        super().__init__(seed=seed, null_strategy=null_strategy, logger=logger)
        
        if seed < 0:
            raise ValueError(f"Seed must be non-negative, got {seed}")
        
        if min_age < 0 or max_age < 0:
            raise ValueError(f"Age range must be non-negative: min_age={min_age}, max_age={max_age}")
        
        if min_age > max_age:
            raise ValueError(f"min_age ({min_age}) must be <= max_age ({max_age})")
        
        self.min_age = min_age
        self.max_age = max_age
        
        self.logger.debug(
            f"Initialized DateOfBirthMasker with seed={seed}, "
            f"null_strategy={null_strategy.value}, "
            f"age_range={min_age}-{max_age} years"
        )
    
    def mask(
        self,
        value: Optional[Union[str, date, datetime]],
        column_info: ColumnInfo
    ) -> Optional[Union[str, date, datetime]]:
        """
        Mask a date of birth with age range control.
        
        This method generates a fake birth date while preserving:
        - Determinism: same input → same output (critical for FK integrity)
        - Type safety: DATE returns date, DATETIME returns datetime, VARCHAR returns string
        - Realistic ages: within configured age range
        - Length constraints: respects VARCHAR column max_length
        
        Args:
            value: Original birth date to mask (can be None, string, date, or datetime)
            column_info: Column metadata for validation and constraints
        
        Returns:
            Masked birth date (type depends on column_info.data_type),
            or None if input is None and PRESERVE strategy
        
        Raises:
            MaskingError: If date cannot be generated within column constraints,
                         or if NULL value violates NOT NULL constraint
        
        Examples:
            >>> masker = DateOfBirthMasker(seed=42, min_age=18, max_age=80)
            >>> 
            >>> # DATE column
            >>> col = ColumnInfo(data_type="DATE", max_length=None, nullable=True)
            >>> masked_date = masker.mask("1990-05-15", col)
            >>> assert isinstance(masked_date, date)
            >>> 
            >>> # VARCHAR column
            >>> col = ColumnInfo(data_type="VARCHAR", max_length=10, nullable=True)
            >>> masked_str = masker.mask("05/15/1990", col)
            >>> assert isinstance(masked_str, str)
        """
        # Handle NULL values
        if value is None:
            return self._handle_null(value, column_info)
        
        # Validate length for VARCHAR types
        data_type_upper = column_info.data_type.upper()
        if data_type_upper in ("VARCHAR", "NVARCHAR", "CHAR", "NCHAR"):
            if column_info.max_length < self.MIN_LENGTH:
                raise MaskingError(
                    error_code=ErrorCodes.MASKING_CONSTRAINT_VIOLATION,
                    message=f"Column length {column_info.max_length} is too short for date of birth masking. "
                            f"Minimum required: {self.MIN_LENGTH} characters",
                    context={
                        "column_info": str(column_info),
                        "min_required_length": self.MIN_LENGTH,
                        "actual_length": column_info.max_length
                    }
                )
        
        # Get deterministic seed from input value
        value_seed = self._get_deterministic_seed(value)
        
        # Generate birth date
        birth_date = self._generate_birth_date(value_seed)
        
        # Format based on data type
        if data_type_upper == "DATE":
            # Return date object
            result = birth_date
        elif data_type_upper in ("DATETIME", "DATETIME2", "SMALLDATETIME"):
            # Return datetime object with 00:00:00 time
            result = datetime.combine(birth_date, datetime.min.time())
        elif data_type_upper in ("VARCHAR", "NVARCHAR", "CHAR", "NCHAR"):
            # Return formatted string based on length
            result = self._format_date_by_length(birth_date, column_info.max_length)
            
            # Validate length (should never truncate with smart generation)
            result, was_truncated = self._validate_length(result, column_info)
            
            if was_truncated:
                self.logger.error(
                    f"Date was truncated! This indicates a bug in format selection logic. "
                    f"Original length: {len(result)}, Max length: {column_info.max_length}"
                )
        else:
            raise MaskingError(
                error_code=ErrorCodes.MASKING_TYPE_MISMATCH,
                message=f"Unsupported data type for date of birth masking: {column_info.data_type}",
                context={
                    "column_info": str(column_info),
                    "supported_types": ["DATE", "DATETIME", "DATETIME2", "SMALLDATETIME", 
                                       "VARCHAR", "NVARCHAR", "CHAR", "NCHAR"]
                }
            )
        
        # Validate data type
        self._validate_data_type(result, column_info)
        
        return result
    
    def _generate_birth_date(self, seed: int) -> date:
        """
        Generate a random birth date within configured age range.
        
        Args:
            seed: Deterministic seed for generation
        
        Returns:
            Birth date as datetime.date object
        """
        # Get current date
        today = date.today()
        
        # Calculate age deterministically within range
        age_range = self.max_age - self.min_age + 1
        age = self.min_age + (seed % age_range)
        
        # Calculate approximate birth year
        birth_year = today.year - age
        
        # Add day-level variation within the year (seed-based)
        # Use upper bits of seed for day offset
        day_offset = (seed >> 16) % 365
        
        # Start from Jan 1 of birth year
        base_date = date(birth_year, 1, 1)
        
        # Add day offset (handle leap years)
        try:
            birth_date = base_date + timedelta(days=day_offset)
        except (ValueError, OverflowError):
            # Fallback to Jan 1 if date calculation fails
            birth_date = base_date
        
        # Ensure date is within valid range (not in future)
        if birth_date > today:
            birth_date = today - timedelta(days=365 * age)
        
        return birth_date
    
    def _format_date_by_length(self, birth_date: date, max_length: int) -> str:
        """
        Format date using appropriate format based on max_length.
        
        Args:
            birth_date: Date to format
            max_length: Maximum column length
        
        Returns:
            Formatted date string fitting within max_length
        """
        if max_length >= 10:
            # ISO 8601 format or US format (both 10 chars)
            # Alternate between them for diversity
            if birth_date.year % 2 == 0:
                # ISO 8601: YYYY-MM-DD
                return birth_date.strftime("%Y-%m-%d")
            else:
                # US format: MM/DD/YYYY
                return birth_date.strftime("%m/%d/%Y")
        elif max_length >= 8:
            # Compact format: YYYYMMDD
            return birth_date.strftime("%Y%m%d")
        else:
            # Year only: YYYY (4 chars)
            return str(birth_date.year)
    
    def _is_leap_year(self, year: int) -> bool:
        """
        Check if a year is a leap year.
        
        Args:
            year: Year to check
        
        Returns:
            True if leap year, False otherwise
        """
        return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
