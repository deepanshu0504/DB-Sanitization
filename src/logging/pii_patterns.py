"""PII redaction patterns for log sanitization.

This module defines compiled regex patterns for detecting and redacting
Personally Identifiable Information (PII) in log messages. Patterns are
pre-compiled for performance.

Constants:
    DEFAULT_PATTERNS: Dictionary mapping PII types to (pattern, replacement) tuples
    EMAIL_PATTERN: Compiled regex for email addresses
    PHONE_PATTERN: Compiled regex for phone numbers
    SSN_PATTERN: Compiled regex for Social Security Numbers
    CREDIT_CARD_PATTERN: Compiled regex for credit card numbers

Examples:
    >>> import re
    >>> pattern, replacement = DEFAULT_PATTERNS["email"]
    >>> pattern.sub(replacement, "Contact: john@example.com")
    'Contact: ***@***'

Security:
    Patterns are designed to be conservative - prefer false positives over
    false negatives to ensure PII is not leaked in logs.

Thread Safety:
    All compiled patterns are thread-safe and can be shared across threads.
"""

import re
from typing import Dict, Tuple, Pattern

# Email pattern - matches most valid email formats
# Examples: user@example.com, first.last@company.co.uk
EMAIL_PATTERN: Pattern = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    re.IGNORECASE
)

# Phone number patterns - US and international formats
# Examples: 555-123-4567, (555) 123-4567, +1-555-123-4567, 5551234567
PHONE_PATTERN: Pattern = re.compile(
    r'''
    (?:
        # US format with optional country code
        (?:\+?1[-.\s]?)?                # Optional +1 country code
        (?:\([0-9]{3}\)|[0-9]{3})       # Area code with/without parens
        [-.\s]?                          # Optional separator
        [0-9]{3}                         # Exchange
        [-.\s]?                          # Optional separator
        [0-9]{4}                         # Subscriber number
        |
        # International format (basic)
        \+[0-9]{1,3}[-.\s]?[0-9]{1,14}  # +XX to +XXX followed by number
        |
        # UK format
        (?:\+?44[-.\s]?)?               # Optional +44 country code
        (?:\(0\)|0)?                    # Optional 0 or (0)
        [1-9][0-9]{9}                   # UK number
    )
    ''',
    re.VERBOSE
)

# SSN pattern - US Social Security Numbers
# Examples: 123-45-6789, 123456789
SSN_PATTERN: Pattern = re.compile(
    r'\b(?!000|666|9\d{2})\d{3}-?(?!00)\d{2}-?(?!0000)\d{4}\b'
)

# Credit card pattern - major card types (Visa, MasterCard, Amex, Discover)
# Matches 13-16 digit numbers with optional spaces/dashes
# Examples: 4111-1111-1111-1111, 5500 0000 0000 0004
CREDIT_CARD_PATTERN: Pattern = re.compile(
    r'''
    \b
    (?:
        # Visa: starts with 4, 16 digits
        4[0-9]{3}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}
        |
        # MasterCard: starts with 51-55 or 2221-2720, 16 digits
        (?:5[1-5][0-9]{2}|222[1-9]|22[3-9][0-9]|2[3-6][0-9]{2}|27[01][0-9]|2720)
        [-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}
        |
        # American Express: starts with 34 or 37, 15 digits
        3[47][0-9]{2}[-\s]?[0-9]{6}[-\s]?[0-9]{5}
        |
        # Discover: starts with 6011 or 65, 16 digits
        (?:6011|65[0-9]{2})[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}
    )
    \b
    ''',
    re.VERBOSE
)

# IBAN pattern - International Bank Account Numbers (basic validation)
# Examples: GB82 WEST 1234 5698 7654 32, DE89370400440532013000
IBAN_PATTERN: Pattern = re.compile(
    r'\b[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}\b'
)

# IPv4 address pattern - may contain sensitive server information
# Examples: 192.168.1.1, 10.0.0.1
IP_ADDRESS_PATTERN: Pattern = re.compile(
    r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
)

# API key/token pattern - generic patterns for common formats
# Examples: api_key_abc123def456, sk-1234567890abcdef
API_KEY_PATTERN: Pattern = re.compile(
    r'''
    (?i)                                # Case insensitive
    (?:
        # Common prefixes
        (?:api[_-]?key|token|secret|password|pwd)[_-]?
        [:=\s]+                         # Separator
        [A-Za-z0-9_\-]{16,}             # Key value (16+ chars)
        |
        # Stripe-style keys
        (?:sk|pk)_(?:test|live)_[A-Za-z0-9]{24,}
        |
        # AWS-style keys
        AKIA[A-Z0-9]{16}
        |
        # Generic bearer tokens
        Bearer\s+[A-Za-z0-9\-._~+/]+=*
    )
    ''',
    re.VERBOSE
)

# Default PII patterns with their replacements
# Pattern -> Replacement mapping
DEFAULT_PATTERNS: Dict[str, Tuple[Pattern, str]] = {
    "email": (EMAIL_PATTERN, "***@***"),
    "phone": (PHONE_PATTERN, "***-***-****"),
    "ssn": (SSN_PATTERN, "***-**-****"),
    "credit_card": (CREDIT_CARD_PATTERN, "****-****-****-****"),
    "iban": (IBAN_PATTERN, "****"),
    "ip_address": (IP_ADDRESS_PATTERN, "***.***.***.***"),
    "api_key": (API_KEY_PATTERN, "***API_KEY***"),
}

# Additional patterns for specific use cases
# These are less common but may be enabled via configuration

# US Driver's License (varies by state, this is a generic pattern)
DRIVERS_LICENSE_PATTERN: Pattern = re.compile(
    r'\b[A-Z]{1,2}[0-9]{5,8}\b'
)

# Passport number (generic international pattern)
PASSPORT_PATTERN: Pattern = re.compile(
    r'\b[A-Z]{1,2}[0-9]{6,9}\b'
)

# Medical record number (generic pattern)
MEDICAL_RECORD_PATTERN: Pattern = re.compile(
    r'\b(?:MRN|Medical[_\s]?Record)[_\s]?(?:Number)?[:\s]+[A-Z0-9]{6,}\b',
    re.IGNORECASE
)

# Additional patterns (not enabled by default)
ADDITIONAL_PATTERNS: Dict[str, Tuple[Pattern, str]] = {
    "drivers_license": (DRIVERS_LICENSE_PATTERN, "***LICENSE***"),
    "passport": (PASSPORT_PATTERN, "***PASSPORT***"),
    "medical_record": (MEDICAL_RECORD_PATTERN, "***MRN***"),
}


def compile_custom_pattern(pattern: str) -> Pattern:
    """Compile a custom regex pattern for PII detection.
    
    Args:
        pattern: Regex pattern string
        
    Returns:
        Compiled regex pattern
        
    Raises:
        re.error: If pattern is invalid regex
        
    Examples:
        >>> pattern = compile_custom_pattern(r'ID-\d{5}')
        >>> pattern.sub('***ID***', 'User ID-12345')
        'User ***ID***'
    """
    return re.compile(pattern)


def get_active_patterns(
    redact_emails: bool = True,
    redact_phones: bool = True,
    redact_ssn: bool = True,
    redact_credit_cards: bool = True,
    custom_patterns: Dict[str, str] = None
) -> Dict[str, Tuple[Pattern, str]]:
    """Get active PII patterns based on configuration.
    
    Args:
        redact_emails: Whether to include email pattern
        redact_phones: Whether to include phone pattern
        redact_ssn: Whether to include SSN pattern
        redact_credit_cards: Whether to include credit card pattern
        custom_patterns: Custom patterns to add (name -> replacement)
        
    Returns:
        Dictionary of active patterns (name -> (pattern, replacement))
        
    Examples:
        >>> patterns = get_active_patterns(
        ...     redact_emails=True,
        ...     redact_phones=False,
        ...     custom_patterns={"custom_id": "***ID***"}
        ... )
        >>> "email" in patterns
        True
        >>> "phone" in patterns
        False
    """
    active: Dict[str, Tuple[Pattern, str]] = {}
    
    # Add default patterns based on flags
    if redact_emails:
        active["email"] = DEFAULT_PATTERNS["email"]
    if redact_phones:
        active["phone"] = DEFAULT_PATTERNS["phone"]
    if redact_ssn:
        active["ssn"] = DEFAULT_PATTERNS["ssn"]
    if redact_credit_cards:
        active["credit_card"] = DEFAULT_PATTERNS["credit_card"]
    
    # Always include API keys and IP addresses (high security risk)
    active["api_key"] = DEFAULT_PATTERNS["api_key"]
    active["ip_address"] = DEFAULT_PATTERNS["ip_address"]
    
    # Add custom patterns if provided
    if custom_patterns:
        for name, pattern_str in custom_patterns.items():
            try:
                pattern = compile_custom_pattern(pattern_str)
                # Use a generic replacement for custom patterns
                active[f"custom_{name}"] = (pattern, f"***{name.upper()}***")
            except re.error:
                # Skip invalid patterns (they should have been validated earlier)
                continue
    
    return active


def redact_message(
    message: str,
    patterns: Dict[str, Tuple[Pattern, str]]
) -> str:
    """Redact PII from a message using provided patterns.
    
    Args:
        message: Original message to redact
        patterns: Dictionary of patterns to apply (name -> (pattern, replacement))
        
    Returns:
        Message with PII redacted
        
    Examples:
        >>> patterns = DEFAULT_PATTERNS
        >>> redact_message("Email: user@example.com", {"email": patterns["email"]})
        'Email: ***@***'
    """
    redacted = message
    
    # Apply each pattern
    for name, (pattern, replacement) in patterns.items():
        redacted = pattern.sub(replacement, redacted)
    
    return redacted
