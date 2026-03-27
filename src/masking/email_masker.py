"""
Email address masking with deterministic domain diversity and length optimization.

This module provides PII masking for email addresses with the following features:
- Deterministic masking (same input → same output) for FK integrity
- Domain diversity (10+ domains to avoid pattern detection)
- Length-aware optimization for SQL Server column constraints
- Unicode/IDN domain support for NVARCHAR columns
- RFC 5322 email format validation
- Special email format handling (quoted, IP domains, etc.)

Key Features:
    - SHA256-based deterministic seeding from BaseMasker
    - Multi-tier length optimization (Standard → Compact → Minimal)
    - Intelligent domain selection using modulo operation
    - VARCHAR vs NVARCHAR handling (ASCII vs Unicode)
    - Fixed-length column padding (CHAR, NCHAR)
    - NULL handling strategies (PRESERVE, MASK)

Author: Database Sanitization Team
Date: 2026-03-26
"""

import re
import logging
from typing import Optional
from email.utils import parseaddr

from .base_masker import BaseMasker, ColumnInfo, MaskingStrategy
from ..exceptions import MaskingError
from ..error_codes import ErrorCodes
from ..logging.logger import get_logger


class EmailMasker(BaseMasker):
    """
    Deterministic email address masker with domain diversity.
    
    This masker generates valid email addresses while preserving referential integrity
    through deterministic mapping. The same input email always produces the same fake
    email, which is critical for maintaining FK relationships across tables.
    
    Domain Pool:
        Ten diverse domains are used to avoid pattern detection:
        - example.com, test.org, demo.net, sample.io
        - fake.email, masked.dev, sanitized.app, placeholder.co
        - dummy.tech, anon.site
    
    Generation Strategy:
        1. Extract deterministic seed from input email
        2. Generate username: user_{hash8} (8-char hex from seed)
        3. Select domain deterministically: DOMAINS[seed % len(DOMAINS)]
        4. Combine: {username}@{domain}
        5. Optimize for length if needed (multi-tier fallback)
    
    Length Optimization Tiers:
        - Standard: user_a1b2c3d4@example.com (~26 chars)
        - Compact: u_a1b2c3@demo.co (~18 chars)
        - Minimal: x@y.co (6 chars minimum)
    
    Attributes:
        seed: Global seed for deterministic random generation
        null_strategy: Strategy for handling NULL values
        logger: Logger instance with correlation ID support
        DOMAINS: List of domain names for fake emails
        EMAIL_REGEX: Compiled regex for email format validation
    
    Examples:
        >>> from src.masking import EmailMasker, ColumnInfo
        >>> masker = EmailMasker(seed=42)
        >>> 
        >>> # VARCHAR(100) column
        >>> col_info = ColumnInfo(
        ...     data_type="VARCHAR",
        ...     max_length=100,
        ...     nullable=True
        ... )
        >>> 
        >>> # Deterministic masking
        >>> email1 = masker.mask("john.doe@gmail.com", col_info)
        >>> email2 = masker.mask("john.doe@gmail.com", col_info)
        >>> assert email1 == email2  # Same input → same output
        >>> 
        >>> # Domain diversity
        >>> email3 = masker.mask("jane.smith@yahoo.com", col_info)
        >>> assert email1 != email3  # Different inputs → different outputs
        >>> # email1 might be user_a1b2c3d4@example.com
        >>> # email3 might be user_e5f6g7h8@test.org
    """
    
    # Domain pool for fake email generation (10 domains for diversity)
    DOMAINS = [
        "example.com",    # Standard test domain
        "test.org",       # Alternative test domain
        "demo.net",       # Demo domain
        "sample.io",      # Sample domain
        "fake.email",     # Clearly fake
        "masked.dev",     # Developer-friendly
        "sanitized.app",  # Sanitization-themed
        "placeholder.co", # Placeholder domain
        "dummy.tech",     # Tech domain
        "anon.site",      # Anonymous domain
    ]
    
    # Shortest domain for extreme length constraints
    SHORTEST_DOMAIN = "y.co"  # 4 characters
    
    # RFC 5322 email format validation (simplified)
    EMAIL_REGEX = re.compile(
        r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$',
        re.IGNORECASE
    )
    
    # IP address domain pattern (e.g., user@[192.168.1.1])
    IP_DOMAIN_REGEX = re.compile(
        r'@\[\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\]$',
        re.IGNORECASE
    )
    
    def __init__(
        self,
        seed: int = 42,
        null_strategy: MaskingStrategy = MaskingStrategy.PRESERVE,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the EmailMasker.
        
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
            f"Initialized EmailMasker with seed={seed}, "
            f"null_strategy={null_strategy.value}, "
            f"domain_count={len(self.DOMAINS)}"
        )
    
    def mask(
        self,
        value: Optional[str],
        column_info: ColumnInfo
    ) -> Optional[str]:
        """
        Mask an email address deterministically.
        
        This method generates a fake email address while preserving the following:
        - Determinism: same input → same output (critical for FK integrity)
        - Valid format: always generates RFC 5322 compliant emails
        - Length constraints: respects column max_length
        - Data type: VARCHAR (ASCII) vs NVARCHAR (Unicode)
        
        Args:
            value: Original email address to mask (can be None)
            column_info: Column metadata for validation and constraints
        
        Returns:
            Masked email address, or None if input is None and PRESERVE strategy
        
        Raises:
            MaskingError: If email cannot be generated within column constraints,
                         or if NULL value violates NOT NULL constraint
        
        Examples:
            >>> masker = EmailMasker(seed=42)
            >>> col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
            >>> 
            >>> # Normal masking
            >>> masked = masker.mask("user@example.com", col)
            >>> # Returns something like: user_a1b2c3d4@example.com
            >>> 
            >>> # Deterministic
            >>> masked2 = masker.mask("user@example.com", col)
            >>> assert masked == masked2
            >>> 
            >>> # NULL handling
            >>> result = masker.mask(None, col)  # Returns None (PRESERVE)
        """
        # Handle NULL values
        if value is None:
            return self._handle_null(value, column_info)
        
        # Strip whitespace
        value = value.strip()
        
        # Validate input format (log warning if invalid)
        if not self._validate_email_format(value):
            self.logger.warning(
                "Input does not match email format, masking anyway",
                extra={
                    "value_hash": self._hash_value(value),
                    "column_type": column_info.data_type
                }
            )
        
        # Generate deterministic seed from input
        seed = self._get_deterministic_seed(value)
        
        # Generate fake email
        fake_email = self._generate_email(seed, column_info.effective_max_length)
        
        # Validate length
        fake_email = self._validate_length(fake_email, column_info)
        
        # Validate data type
        self._validate_data_type(fake_email, column_info)
        
        self.logger.debug(
            "Masked email successfully",
            extra={
                "value_hash": self._hash_value(value),
                "fake_length": len(fake_email),
                "max_length": column_info.max_length,
                "data_type": column_info.data_type
            }
        )
        
        return fake_email
    
    def _generate_email(self, seed: int, max_length: int) -> str:
        """
        Generate a fake email address from a deterministic seed.
        
        Uses multi-tier optimization to fit within column length constraints:
        1. Standard: user_{hash8}@{domain} (~26 chars)
        2. Compact: u_{hash6}@{short_domain} (~18 chars)
        3. Minimal: x@{shortest_domain} (6 chars)
        
        Args:
            seed: Deterministic seed for generation
            max_length: Maximum allowed length for the email
        
        Returns:
            Generated email address
        
        Raises:
            MaskingError: If max_length < 6 (minimum viable email)
        """
        # Select domain deterministically
        domain_index = seed % len(self.DOMAINS)
        domain = self.DOMAINS[domain_index]
        
        # Generate username from seed hash
        # Use first 8 hex characters from seed
        hash_hex = hex(seed)[2:]  # Remove '0x' prefix
        hash8 = hash_hex[:8].ljust(8, '0')  # Ensure 8 chars
        
        # Standard format: user_{hash8}@{domain}
        username_standard = f"user_{hash8}"
        email_standard = f"{username_standard}@{domain}"
        
        # If standard fits, use it
        if len(email_standard) <= max_length:
            return email_standard
        
        # Compact format: u_{hash6}@{domain}
        hash6 = hash_hex[:6].ljust(6, '0')
        username_compact = f"u_{hash6}"
        email_compact = f"{username_compact}@{domain}"
        
        if len(email_compact) <= max_length:
            self.logger.debug(
                f"Using compact email format for length {max_length}"
            )
            return email_compact
        
        # Try with shortest domain
        email_compact_short = f"{username_compact}@{self.SHORTEST_DOMAIN}"
        
        if len(email_compact_short) <= max_length:
            self.logger.debug(
                f"Using compact email with shortest domain for length {max_length}"
            )
            return email_compact_short
        
        # Minimal format: x@{shortest_domain}
        email_minimal = f"x@{self.SHORTEST_DOMAIN}"
        
        if len(email_minimal) <= max_length:
            self.logger.warning(
                f"Using minimal email format for very short column (length={max_length})"
            )
            return email_minimal
        
        # Cannot generate valid email for this column length
        raise MaskingError(
            message=f"Column too short for email masking (min 6 chars required, got {max_length})",
            error_code=ErrorCodes.MASKING_LENGTH_CONSTRAINT_VIOLATED,
            is_retryable=False,
            suggested_action="Increase column length to at least 6 characters or use generic masker",
            operation_context={
                "column_type": "email",
                "max_length": max_length,
                "minimum_required": 6,
                "minimal_email": email_minimal
            }
        )
    
    def _validate_email_format(self, email: str) -> bool:
        """
        Validate if a string matches email format using RFC 5322 simplified regex.
        
        This is a best-effort validation. It catches most common email formats
        but may not handle all edge cases from RFC 5322 (quoted strings, comments, etc.).
        
        Args:
            email: Email string to validate
        
        Returns:
            True if email matches format, False otherwise
        """
        if not email or '@' not in email:
            return False
        
        # Remove IP domain format if present (special case)
        if self.IP_DOMAIN_REGEX.search(email):
            # IP domains are valid, just unusual
            return True
        
        # Standard regex validation
        return bool(self.EMAIL_REGEX.match(email))
    
    def _select_domain(self, seed: int) -> str:
        """
        Select a domain deterministically from the domain pool.
        
        Uses modulo operation to ensure the same seed always selects the same domain.
        
        Args:
            seed: Deterministic seed
        
        Returns:
            Selected domain name
        """
        domain_index = seed % len(self.DOMAINS)
        return self.DOMAINS[domain_index]
    
    def _generate_username(self, seed: int, length: int = 8) -> str:
        """
        Generate a username from a seed with specified hash length.
        
        Args:
            seed: Deterministic seed
            length: Number of hex characters to use (default: 8)
        
        Returns:
            Username like "user_{hash}" or "u_{hash}"
        """
        hash_hex = hex(seed)[2:]  # Remove '0x' prefix
        hash_part = hash_hex[:length].ljust(length, '0')
        
        if length >= 8:
            return f"user_{hash_part}"
        else:
            return f"u_{hash_part}"
