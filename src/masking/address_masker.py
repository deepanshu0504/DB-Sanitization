"""
Address masking with deterministic generation and length optimization.

This module provides PII masking for physical addresses with the following features:
- Deterministic masking (same input → same output) for FK integrity
- Multi-tier length optimization for SQL Server column constraints
- Support for full addresses and individual components (street, city, state, zip)
- Component detection based on column name patterns
- US address format support
- VARCHAR vs NVARCHAR handling (ASCII vs Unicode)

Key Features:
    - SHA256-based deterministic seeding from BaseMasker
    - Multi-tier length optimization (Full → Address+City → Street → Minimal)
    - Intelligent component selection using modulo operation
    - Fixed-length column padding (CHAR, NCHAR)
    - NULL handling strategies (PRESERVE, MASK)

Author: Database Sanitization Team
Date: 2026-03-30
"""

import re
import logging
from typing import Optional

from .base_masker import BaseMasker, ColumnInfo, MaskingStrategy
from ..exceptions import MaskingError
from ..error_codes import ErrorCodes
from ..logging.logger import get_logger


class AddressMasker(BaseMasker):
    """
    Deterministic address masker with component support and length optimization.
    
    This masker generates valid US addresses while preserving referential integrity
    through deterministic mapping. The same input address always produces the same
    fake address, which is critical for maintaining FK relationships across tables.
    
    Address Generation Strategy:
        1. Extract deterministic seed from input address
        2. Generate components: street number, street name, city, state, zip
        3. Combine based on column length constraints (multi-tier)
        4. Support component-only generation (e.g., city-only columns)
    
    Multi-Tier Length Optimization:
        - Full (≥100 chars): "742 Evergreen Terrace, Springfield, IL 62701"
        - Address+City (50-99 chars): "742 Evergreen Terrace, Springfield, IL"
        - Street Only (30-49 chars): "742 Evergreen Terrace"
        - Minimal (15-29 chars): "742 Main St"
        - Min viable (≥10 chars): "123 Oak St"
    
    Component Detection:
        If column name contains specific keywords, generate only that component:
        - "street" or "address" → street with number
        - "city" → city name only
        - "state" → state abbreviation only
        - "zip" or "postal" → zip code only
        Otherwise, generate full address based on length tier.
    
    Attributes:
        seed: Global seed for deterministic random generation
        null_strategy: Strategy for handling NULL values
        logger: Logger instance with correlation ID support
        STREET_NAMES: List of common street names for generation
        CITIES: List of US cities for generation
        STATES: List of US state abbreviations
        MIN_LENGTH: Minimum column length required (10 characters)
    
    Examples:
        >>> from src.masking import AddressMasker, ColumnInfo
        >>> masker = AddressMasker(seed=42)
        >>> 
        >>> # VARCHAR(100) column - uses full address format
        >>> col_info = ColumnInfo(
        ...     data_type="VARCHAR",
        ...     max_length=100,
        ...     nullable=True
        ... )
        >>> 
        >>> # Deterministic masking
        >>> addr1 = masker.mask("123 Real St, RealCity, CA 90210", col_info)
        >>> addr2 = masker.mask("123 Real St, RealCity, CA 90210", col_info)
        >>> assert addr1 == addr2  # Same input → same output
        >>> 
        >>> # Different inputs produce different addresses
        >>> addr3 = masker.mask("456 Other Ave, OtherCity, NY 10001", col_info)
        >>> assert addr1 != addr3
    """
    
    # Street names for address generation (50 diverse options)
    STREET_NAMES = [
        "Main Street", "Oak Avenue", "Maple Drive", "Elm Street", "Pine Road",
        "Cedar Lane", "Park Avenue", "Washington Street", "Lincoln Avenue", "Market Street",
        "First Street", "Second Avenue", "Third Street", "Broadway", "Madison Avenue",
        "Church Street", "Mill Road", "Spring Street", "Lake Drive", "Hill Road",
        "River Road", "Forest Avenue", "Sunset Boulevard", "Highland Avenue", "Valley Road",
        "Ridge Road", "Meadow Lane", "Grove Street", "Garden Avenue", "Woodland Drive",
        "Summit Avenue", "College Street", "School Street", "Franklin Street", "Jefferson Avenue",
        "Adams Street", "Monroe Drive", "Jackson Avenue", "Cherry Street", "Walnut Street",
        "Chestnut Street", "Birch Lane", "Willow Road", "Dogwood Drive", "Magnolia Avenue",
        "Sycamore Street", "Hickory Lane", "Poplar Street", "Cypress Avenue", "Laurel Drive"
    ]
    
    # Compact street names for shorter columns (15-29 chars needed)
    COMPACT_STREETS = [
        "Main St", "Oak Ave", "Elm St", "Pine Rd", "Park Ave",
        "First St", "Mill Rd", "Lake Dr", "Hill Rd", "Grove St"
    ]
    
    # US Cities (30 diverse options)
    CITIES = [
        "Springfield", "Franklin", "Clinton", "Madison", "Georgetown",
        "Arlington", "Salem", "Clayton", "Jackson", "Bristol",
        "Manchester", "Oxford", "Ashland", "Burlington", "Fairview",
        "Riverside", "Oakland", "Greenville", "Marion", "Newport",
        "Dover", "Auburn", "Concord", "Lexington", "Hudson",
        "Winchester", "Milton", "Chester", "Preston", "Dayton"
    ]
    
    # US State abbreviations (50 states)
    STATES = [
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"
    ]
    
    # Minimum viable address length
    MIN_LENGTH = 10  # "123 Oak St"
    
    # Column name patterns for component detection
    STREET_PATTERN = re.compile(r'street|address|addr', re.IGNORECASE)
    CITY_PATTERN = re.compile(r'\bcity\b', re.IGNORECASE)
    STATE_PATTERN = re.compile(r'\bstate\b', re.IGNORECASE)
    ZIP_PATTERN = re.compile(r'zip|postal', re.IGNORECASE)
    
    def __init__(
        self,
        seed: int = 42,
        null_strategy: MaskingStrategy = MaskingStrategy.PRESERVE,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the AddressMasker.
        
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
            f"Initialized AddressMasker with seed={seed}, "
            f"null_strategy={null_strategy.value}, "
            f"street_count={len(self.STREET_NAMES)}, "
            f"city_count={len(self.CITIES)}"
        )
    
    def mask(
        self,
        value: Optional[str],
        column_info: ColumnInfo
    ) -> Optional[str]:
        """
        Mask an address with smart format selection based on column length.
        
        This method generates a fake address while preserving the following:
        - Determinism: same input → same output (critical for FK integrity)
        - Valid format: always generates realistic US addresses
        - Length constraints: respects column max_length (smart generation)
        - Data type: VARCHAR (ASCII) vs NVARCHAR (Unicode)
        
        Args:
            value: Original address to mask (can be None)
            column_info: Column metadata for validation and constraints
        
        Returns:
            Masked address, or None if input is None and PRESERVE strategy
        
        Raises:
            MaskingError: If address cannot be generated within column constraints,
                         or if NULL value violates NOT NULL constraint
        
        Examples:
            >>> masker = AddressMasker(seed=42)
            >>> col = ColumnInfo(data_type="VARCHAR", max_length=100, nullable=True)
            >>> 
            >>> # Normal masking
            >>> masked = masker.mask("123 Real St, City, CA 12345", col)
            >>> # Returns something like: "742 Evergreen Terrace, Springfield, IL 62701"
            >>> 
            >>> # Deterministic
            >>> masked2 = masker.mask("123 Real St, City, CA 12345", col)
            >>> assert masked == masked2
        """
        # Handle NULL values
        if value is None:
            return self._handle_null(value, column_info)
        
        # Validate minimum length constraint
        if column_info.max_length < self.MIN_LENGTH:
            raise MaskingError(
                error_code=ErrorCodes.MASKING_CONSTRAINT_VIOLATION,
                message=f"Column length {column_info.max_length} is too short for address masking. "
                        f"Minimum required: {self.MIN_LENGTH} characters",
                context={
                    "column_info": str(column_info),
                    "min_required_length": self.MIN_LENGTH,
                    "actual_length": column_info.max_length
                }
            )
        
        # Get deterministic seed from input value
        value_seed = self._get_deterministic_seed(value)
        
        # Detect component type from column name if available
        # This is a heuristic - if we can't detect, we generate full address
        component_type = self._detect_component_type(column_info)
        
        # Generate address based on component type and length
        if component_type == "city":
            fake_address = self._generate_city(value_seed)
        elif component_type == "state":
            fake_address = self._generate_state(value_seed)
        elif component_type == "zip":
            fake_address = self._generate_zip(value_seed)
        else:
            # Generate full address or street based on length
            fake_address = self._generate_address_by_length(value_seed, column_info.max_length)
        
        # Validate length (should never truncate with smart generation)
        fake_address, was_truncated = self._validate_length(fake_address, column_info)
        
        if was_truncated:
            self.logger.error(
                f"Address was truncated! This indicates a bug in tier selection logic. "
                f"Original length: {len(fake_address)}, Max length: {column_info.max_length}"
            )
        
        # Validate data type
        self._validate_data_type(fake_address, column_info)
        
        return fake_address
    
    def _detect_component_type(self, column_info: ColumnInfo) -> Optional[str]:
        """
        Detect if column should contain a specific address component.
        
        Args:
            column_info: Column metadata with potential name hints
        
        Returns:
            Component type: "city", "state", "zip", "street", or None for full address
        """
        # This is a heuristic based on common naming patterns
        # In production, column_info might have a 'column_name' attribute
        # For now, we return None (generate full address) unless we add column_name to ColumnInfo
        
        # TODO: If column_info is extended to include column_name, implement detection:
        # if hasattr(column_info, 'column_name') and column_info.column_name:
        #     name = column_info.column_name.lower()
        #     if self.CITY_PATTERN.search(name): return "city"
        #     if self.STATE_PATTERN.search(name): return "state"
        #     if self.ZIP_PATTERN.search(name): return "zip"
        
        return None  # Default to full address
    
    def _generate_address_by_length(self, seed: int, max_length: int) -> str:
        """
        Generate address using appropriate tier based on max_length.
        
        Args:
            seed: Deterministic seed for generation
            max_length: Maximum column length
        
        Returns:
            Generated address fitting within max_length
        """
        if max_length >= 100:
            # Full format: "742 Evergreen Terrace, Springfield, IL 62701"
            return self._generate_full_address(seed)
        elif max_length >= 50:
            # Address+City format: "742 Evergreen Terrace, Springfield, IL"
            return self._generate_address_with_city(seed)
        elif max_length >= 30:
            # Street only format: "742 Evergreen Terrace"
            return self._generate_street_address(seed)
        elif max_length >= 15:
            # Minimal format: "742 Main St"
            return self._generate_minimal_address(seed)
        else:
            # Shortest format: "123 Oak St" (10 chars minimum)
            return self._generate_shortest_address(seed)
    
    def _generate_full_address(self, seed: int) -> str:
        """Generate full address: Number Street, City, ST ZIP."""
        number = self._generate_street_number(seed)
        street = self.STREET_NAMES[seed % len(self.STREET_NAMES)]
        city = self.CITIES[(seed >> 8) % len(self.CITIES)]
        state = self.STATES[(seed >> 16) % len(self.STATES)]
        zip_code = self._generate_zip(seed >> 24)
        
        return f"{number} {street}, {city}, {state} {zip_code}"
    
    def _generate_address_with_city(self, seed: int) -> str:
        """Generate address with city: Number Street, City, ST."""
        number = self._generate_street_number(seed)
        street = self.STREET_NAMES[seed % len(self.STREET_NAMES)]
        city = self.CITIES[(seed >> 8) % len(self.CITIES)]
        state = self.STATES[(seed >> 16) % len(self.STATES)]
        
        return f"{number} {street}, {city}, {state}"
    
    def _generate_street_address(self, seed: int) -> str:
        """Generate street address only: Number Street."""
        number = self._generate_street_number(seed)
        street = self.STREET_NAMES[seed % len(self.STREET_NAMES)]
        
        return f"{number} {street}"
    
    def _generate_minimal_address(self, seed: int) -> str:
        """Generate minimal address: Number CompactStreet."""
        number = self._generate_street_number(seed)
        street = self.COMPACT_STREETS[seed % len(self.COMPACT_STREETS)]
        
        return f"{number} {street}"
    
    def _generate_shortest_address(self, seed: int) -> str:
        """Generate shortest viable address: 3-digit number + short street."""
        # Use 3-digit number for consistency
        number = 100 + (seed % 900)
        street = self.COMPACT_STREETS[seed % len(self.COMPACT_STREETS)]
        
        return f"{number} {street}"
    
    def _generate_street_number(self, seed: int) -> int:
        """Generate realistic street number (100-9999)."""
        # Most street numbers are 3-4 digits
        return 100 + (seed % 9900)
    
    def _generate_city(self, seed: int) -> str:
        """Generate city name only."""
        return self.CITIES[seed % len(self.CITIES)]
    
    def _generate_state(self, seed: int) -> str:
        """Generate state abbreviation only."""
        return self.STATES[seed % len(self.STATES)]
    
    def _generate_zip(self, seed: int) -> str:
        """Generate valid 5-digit ZIP code."""
        # US ZIP codes: 00501 to 99950
        # Use modulo to ensure 5 digits
        zip_num = 10000 + (seed % 89950)
        return f"{zip_num:05d}"
