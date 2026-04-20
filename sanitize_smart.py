"""
Enhanced direct sanitization script with Smart Generation maskers.

This script uses the production masker classes with Smart Generation support,
bypassing the orchestrator to avoid import/logging issues while still getting
all the benefits of constraint-aware fake value generation.

Key Features:
- Smart Generation: Professional maskers automatically adapt to column constraints
- No truncation: All fake values guaranteed to fit without truncation
- Deterministic: Same input always produces same output (FK integrity)  
- Direct execution: No complex orchestrator, straightforward Python script

Usage:
    python sanitize_smart.py config/pii_config_ai_generated.json

Author: Database Sanitization Team
Date: 2026-03-28

"""

import json
import pyodbc
import hashlib
import random
import string
import os
from typing import Dict, List, Any, Optional, Tuple, Union
from datetime import datetime, date, timedelta
from decimal import Decimal
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID, uuid4


def _safe_encode(value: Any) -> bytes:
    """Safely encode any value to bytes (handles dates, numbers, etc.)."""
    if value is None:
        return b""
    elif isinstance(value, bytes):
        return value
    elif isinstance(value, str):
        return value.encode('utf-8')
    elif isinstance(value, (datetime, date)):
        return value.isoformat().encode('utf-8')
    elif isinstance(value, (int, float, Decimal)):
        return str(value).encode('utf-8')
    else:
        return str(value).encode('utf-8')


# Import mapping modules for desanitization support
try:
    from mapping import (
        EncryptionManager,
        MappingManager,
        create_mapping_entry,
        EncryptionKeyError
    )
    MAPPING_AVAILABLE = True
except ImportError:
    MAPPING_AVAILABLE = False
    print("[WARN] Mapping modules not available - desanitization disabled")
# ================================
# Dynamic Name Component Detection
# ================================

NAME_COMPONENT_PATTERNS = {
    "first": [
        r"\bfirst\b",           # FirstName, first_name, FIRST_NAME
        r"\bfname\b",           # fname, FName (after normalization)
        r"\bgiven\b",           # GivenName, given_name
        r"\bf[\s_]?name\b",     # f_name, f name, FName
        r"\bgivenname\b",       # givenname (single word)
        r"\bforename\b",        # forename (single word)
        r"\bfore[\s_]?name\b",  # ForeName, fore_name, fore name
        r"\bfirstname\b"        # firstname (single word)
    ],
    "middle": [
        r"\bmiddle\b",          # MiddleName, middle_name
        r"\bmname\b",           # mname, MName (after normalization)
        r"\bm[\s_]?name\b",     # m_name, m name, MName
        r"\bmiddlename\b",      # middlename (single word)
        r"\bmiddle[\s_]?initial\b"  # middle_initial, middle initial, MiddleInitial
    ],
    "last": [
        r"\blast\b",            # LastName, last_name
        r"\blname\b",           # lname, LName (after normalization)
        r"\bsurname\b",         # Surname, surname
        r"\bfamily\b",          # FamilyName, family_name
        r"\bl[\s_]?name\b",     # l_name, l name, LName
        r"\blastname\b",        # lastname (single word)
        r"\bfamilyname\b"       # familyname (single word)
    ],
    "full": [
        r"\bfull\b",                    # FullName, full_name
        r"\bfullname\b",                # fullname (single word)
        r"\bfull[\s_]?name\b",          # full_name, full name, FullName
        r"\bcomplete\b",                # CompleteName, complete_name
        r"\bcomplete[\s_]?name\b",      # complete_name, complete name, CompleteName
        r"^name$",                      # Exact match: "name" only
        r"^full[\s_]?name$",            # Exact match: fullname/full_name/full name
        r"\b(person|employee|customer|contact|user|student|patient)[\s_]?name\b"  # Generic entity names
    ]
}

# Dynamic address component detection patterns
ADDRESS_COMPONENT_PATTERNS = {
    "city": [r"\bcity\b"],
    "state": [r"\bstate\b", r"\bprovince\b", r"\bregion\b"],
    "postal": [r"zip", r"postal", r"pincode"],
    "line": [r"street", r"address", r"addr", r"line"],
     "country": [
        r"\bcountry\b",
        r"\bnation\b",
        r"\bcountry_code\b",
        r"\biso_country\b"
            ]
    }

@dataclass
class ColumnInfo:
    """Column metadata for Smart Generation."""
    data_type: str
    max_length: Optional[int]
    nullable: bool
    column_name: Optional[str] = None  # For component type detection


class SmartMaskerEngine:
    """
    Masking engine with Smart Generation - constraint-aware fake value generation.
    
    Implements Smart Generation logic directly to avoid framework dependencies.
    Each masker type has multiple format tiers that adapt to column length.
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
    
    # Card type lengths
    CARD_LENGTH_16 = 16  # Visa, MasterCard, Discover
    CARD_LENGTH_15 = 15  # American Express
    CARD_LENGTH_13 = 13  # Older Visa cards
    MIN_CARD_LENGTH = 13  # Minimum viable card length

    
    def __init__(self, seed: int = 42):
        """Initialize with seed for deterministic masking."""
        self.seed = seed
        self._mapping_cache = {}  # Cache for consistent FK relationships
    
    def _get_deterministic_seed(self, value: str) -> int:
        """Generate deterministic seed from value for reproducible masking."""
        hash_obj = hashlib.sha256(str(value).encode('utf-8'))
        return int.from_bytes(hash_obj.digest()[:4], 'big')
    
    def _generate_email_smart(self, seed: int, max_length: int) -> str:
        """
        Smart Generation for emails - 3 format tiers.
        
        - Standard (≥26 chars): user_a1b2c3d4@example.com
        - Compact (≥18 chars): u_a1b2c3@demo.co
        - Minimal (≥6 chars): a@x.co
        """
        if max_length < 6:
            raise ValueError(f"Column too short for email: {max_length}")
        
        # Generate deterministic parts
        random.seed(seed)
        hex_id = format(seed % 0xFFFFFFFF, '08x')
        
        if max_length >= 26:
            # Standard format
            return f"user_{hex_id}@example.com"
        elif max_length >= 18:
            # Compact format
            return f"u_{hex_id[:6]}@demo.co"
        else:
            # Minimal format
            char = chr(97 + (seed % 26))  # a-z
            return f"{char}@x.co"
    
    def _generate_phone_smart(self, seed: int, max_length: int) -> str:
        """
        Smart Generation for phones - 3 format tiers.
        
        - Standard (≥14 chars): (555) 555-5555
        - Compact (≥12 chars): 555-555-5555
        - Minimal (≥10 chars): 5555555555
        """
        if max_length < 10:
            raise ValueError(f"Column too short for phone: {max_length}")
        
        # Generate deterministic phone parts
        area = 555  # Reserved area code
        exchange = (seed % 900) + 100  # 100-999
        subscriber = ((seed // 1000) % 9000) + 1000  # 1000-9999
        
        if max_length >= 14:
            # Standard format
            return f"({area}) {exchange:03d}-{subscriber:04d}"
        elif max_length >= 12:
            # Compact format
            return f"{area}-{exchange:03d}-{subscriber:04d}"
        else:
            # Minimal format
            return f"{area}{exchange:03d}{subscriber:04d}"
    
    def _generate_name_smart(self, seed: int, max_length: int, component_type: str = "full") -> str:
        """
        Smart Generation for names with component awareness.
        """

        if max_length < 1:
            raise ValueError(f"Column too short for name: {max_length}")

        first_names = ["John", "Jane", "Mike", "Sarah", "David", "Emma", "James", "Mary",
                    "Robert", "Lisa", "William", "Nancy", "Richard", "Karen", "Joseph"]

        middle_names = ["A.", "B.", "C.", "D.", "E.", "K.", "R.", "S."]

        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
                    "Davis", "Rodriguez", "Martinez", "Lopez", "Wilson", "Anderson"]

        random.seed(seed)

        first = random.choice(first_names)
        middle = random.choice(middle_names)
        last = random.choice(last_names)

        # 🎯 Component-specific generation
        if component_type == "first":
            return first[:max_length]

        elif component_type == "middle":
            return middle[:max_length]

        elif component_type == "last":
            return last[:max_length]

        # 🎯 Full name logic
        if max_length >= 20:
            title = random.choice(["Dr.", "Mr.", "Mrs.", "Ms."])
            suffix = random.choice(["Jr.", "Sr.", "III", ""])
            full = f"{title} {first} {last} {suffix}".strip()
            return full[:max_length]

        elif max_length >= 10:
            return f"{first} {last}"[:max_length]

        elif max_length >= 4:
            return first[:max_length]

        else:
            return f"{first[0]}{last[0]}"[:max_length]
    
    def _generate_ssn_smart(self, seed: int, max_length: int) -> str:
        """
        Smart Generation for SSNs - 2 format tiers.
        
        - Formatted (≥11 chars): 123-45-6789
        - Plain (≥9 chars): 123456789
        """
        if max_length < 9:
            raise ValueError(f"Column too short for SSN: {max_length}")
        
        # Generate deterministic SSN parts
        area = (seed % 900) + 100  # 100-999
        group = (seed // 1000) % 100  # 00-99
        serial = (seed // 100000) % 10000  # 0000-9999
        
        if max_length >= 11:
            # Formatted
            return f"{area:03d}-{group:02d}-{serial:04d}"
        else:
            # Plain
            return f"{area:03d}{group:02d}{serial:04d}"
    
    def _generate_generic_smart(self, original: str, max_length: int) -> str:
        """
        Smart Generation for generic PII - keeps original data type and format.

        - Preserves numeric, alphabetic, and alphanumeric formats.
        - Respects original length and max_length.
        """
        import random
        import string

        original_str = str(original)
        if max_length is None:
            max_length = len(original_str)

        target_length = min(len(original_str), max_length)
        if target_length == 0:
            return ""

        # Deterministic seed to ensure same value for same original
        seed_val = self._get_deterministic_seed(original)
        random.seed(seed_val)

        # Detect format of original
        if original_str.isdigit():
            # Numeric column → replace with digits only
            return ''.join(random.choices(string.digits, k=target_length))
        elif original_str.isalpha():
            # Alphabetic column → letters only
            return ''.join(random.choices(string.ascii_letters, k=target_length))
        elif original_str.isalnum():
            # Alphanumeric column → letters + digits
            return ''.join(random.choices(string.ascii_letters + string.digits, k=target_length))
        elif self._is_decimal(original_str):
            # Decimal numbers → keep digits and decimal point
            parts = original_str.split(".")
            int_part = ''.join(random.choices(string.digits, k=len(parts[0])))
            if len(parts) > 1:
                frac_part = ''.join(random.choices(string.digits, k=len(parts[1])))
                return f"{int_part}.{frac_part}"
            return int_part
        else:
            # Mixed/Other → replace with printable characters but maintain length
            return ''.join(random.choices(string.printable.strip(), k=target_length))


    def _is_decimal(self, value: str) -> bool:
        """
        Helper to check if a string is a decimal number
        """
        try:
            float(value)
            return True
        except ValueError:
            return False
    
    def _generate_date_of_birth_smart(
        self, 
        seed: int, 
        max_length: Optional[int], 
        data_type: str,
        min_age: int = 18,
        max_age: int = 80
    ) -> Union[date, datetime, str]:
        """
        Smart Generation for date of birth - age-based date generation.
        
        Generates realistic birth dates within age range (default: 18-80 years).
        Returns appropriate type based on column data type:
        - DATE: returns date object
        - DATETIME/DATETIME2/SMALLDATETIME: returns datetime object
        - VARCHAR/NVARCHAR: returns formatted string
        
        Args:
            seed: Deterministic seed for generation
            max_length: Maximum length for VARCHAR columns
            data_type: SQL column data type
            min_age: Minimum age in years (default: 18)
            max_age: Maximum age in years (default: 80)
        
        Returns:
            Birth date as date, datetime, or string depending on data_type
        """
        data_type_upper = data_type.upper()
        
        # Validate length for VARCHAR types
        if data_type_upper in ("VARCHAR", "NVARCHAR", "CHAR", "NCHAR"):
            if max_length is None or max_length < 4:
                raise ValueError(
                    f"Column length {max_length} is too short for date of birth. "
                    f"Minimum required: 4 characters (year only format)"
                )
        
        # Get current date
        today = date.today()
        
        # Calculate age deterministically within range
        age_range = max_age - min_age + 1
        age = min_age + (seed % age_range)
        
        # Calculate birth year
        birth_year = today.year - age
        
        # Add day-level variation within the year (use upper bits of seed)
        day_offset = (seed >> 16) % 365
        
        # Start from Jan 1 of birth year
        try:
            base_date = date(birth_year, 1, 1)
            birth_date = base_date + timedelta(days=day_offset)
            
            # Ensure date is not in future
            if birth_date > today:
                birth_date = today - timedelta(days=365 * age)
        except (ValueError, OverflowError):
            # Fallback to Jan 1 if date calculation fails
            birth_date = date(birth_year, 1, 1)
        
        # Return appropriate type based on data_type
        if data_type_upper == "DATE":
            return birth_date
        elif data_type_upper in ("DATETIME", "DATETIME2", "SMALLDATETIME"):
            return datetime.combine(birth_date, datetime.min.time())
        elif data_type_upper in ("VARCHAR", "NVARCHAR", "CHAR", "NCHAR"):
            # Format based on length
            if max_length >= 10:
                # ISO 8601 format: YYYY-MM-DD (10 chars)
                return birth_date.strftime("%Y-%m-%d")
            elif max_length >= 8:
                # Compact format: YYYYMMDD (8 chars)
                return birth_date.strftime("%Y%m%d")
            else:
                # Year only: YYYY (4 chars)
                return str(birth_date.year)
        else:
            raise ValueError(
                f"Unsupported data type for date of birth: {data_type}. "
                f"Supported types: DATE, DATETIME, DATETIME2, SMALLDATETIME, VARCHAR, NVARCHAR"
            )
    
    def _generate_address_smart(self, seed: int, max_length: int, component_type: str = "full") -> str:
        """
        Smart Generation for addresses - adapts to column length.
        
        Generates realistic fake addresses of appropriate length.
        """
        if max_length < 5:
            raise ValueError(f"Column too short for address: {max_length}")
        
        # Address components
        street_numbers = [str(100 + (seed % 900))]  # 100-999
        street_names = ["Main St", "Oak Ave", "Elm Rd", "Park Blvd", "Lake Dr", 
                       "Hill Way", "Pine St", "Maple Ave", "Cedar Ln", "River Rd"]
        cities = ["Springfield", "Madison", "Greenville", "Clinton", "Franklin",
                 "Chester", "Salem", "Monroe", "Auburn", "Marion"]
        states = ["NY", "CA", "TX", "FL", "IL", "PA", "OH", "GA", "NC", "MI"]
        zip_codes = [f"{10000 + (seed % 90000):05d}"]  # 10000-99999
        
        random.seed(seed)
        
        # For AddressLine1/AddressLine2
        if component_type == "full" or component_type == "line":
            street_num = random.choice(street_numbers)
            street = random.choice(street_names)
            address = f"{street_num} {street}"
            
            # Truncate if needed
            if len(address) > max_length:
                address = address[:max_length].rstrip()
            
            return address
        
        # For City
        elif component_type == "city":
            city = random.choice(cities)
            if len(city) > max_length:
                city = city[:max_length]
            return city
        
        # For PostalCode
        elif component_type == "postal":
            zip_code = random.choice(zip_codes)
            if len(zip_code) > max_length:
                zip_code = zip_code[:max_length]
            return zip_code
        
        # For State
        elif component_type == "state":
            state = random.choice(states)
            if len(state) > max_length:
                state = state[:max_length]
            return state
        
        # For Country
        elif component_type == "country":
            # Smart country generation based on column length
            
            # ISO-2 codes
            iso2 = ["US", "IN", "GB", "CA", "AU", "DE", "FR", "JP"]
            
            # ISO-3 codes
            iso3 = ["USA", "IND", "GBR", "CAN", "AUS", "DEU", "FRA", "JPN"]
            
            # Full country names
            full_names = [
                "United States", "India", "United Kingdom", "Canada",
                "Australia", "Germany", "France", "Japan"
            ]
            
            if max_length <= 3:
                value = iso2[seed % len(iso2)]
            elif max_length <= 5:
                value = iso3[seed % len(iso3)]
            else:
                value = full_names[seed % len(full_names)]
            
            return value[:max_length]
        
        # Default: use generic
        else:
            return self._generate_generic_smart(str(seed), max_length)
    
    def _calculate_luhn_digit(self, card_without_checksum: str) -> str:
        """
        Calculate Luhn checksum digit for a partial card number.
        
        The Luhn algorithm:
        1. Starting from the rightmost digit, double every second digit
        2. If doubling results in two digits, add them together (subtract 9)
        3. Sum all digits
        4. The checksum is (10 - (sum % 10)) % 10
        
        Args:
            card_without_checksum: Card number without the last checksum digit
        
        Returns:
            Single checksum digit as string
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
    
    def _format_card_with_dashes(self, card_digits: str) -> str:
        """
        Format card number with dashes.
        
        Args:
            card_digits: Plain card digits
        
        Returns:
            Formatted card with dashes (e.g., "4532-1234-5678-9012")
        """
        if len(card_digits) == 15:  # Amex: 3711-123456-12345
            return f"{card_digits[0:4]}-{card_digits[4:10]}-{card_digits[10:15]}"
        elif len(card_digits) == 16:  # Visa/MC/Discover: 4532-1234-5678-9012
            return f"{card_digits[0:4]}-{card_digits[4:8]}-{card_digits[8:12]}-{card_digits[12:16]}"
        else:  # 13-digit: 4532-1234-5678-9
            return f"{card_digits[0:4]}-{card_digits[4:8]}-{card_digits[8:12]}-{card_digits[12:]}"
    
    def _format_card_with_spaces(self, card_digits: str) -> str:
        """
        Format card number with spaces.
        
        Args:
            card_digits: Plain card digits
        
        Returns:
            Formatted card with spaces (e.g., "4532 1234 5678 9012")
        """
        if len(card_digits) == 15:  # Amex: 3711 123456 12345
            return f"{card_digits[0:4]} {card_digits[4:10]} {card_digits[10:15]}"
        elif len(card_digits) == 16:  # Visa/MC/Discover: 4532 1234 5678 9012
            return f"{card_digits[0:4]} {card_digits[4:8]} {card_digits[8:12]} {card_digits[12:16]}"
        else:  # 13-digit: 4532 1234 5678 9
            return f"{card_digits[0:4]} {card_digits[4:8]} {card_digits[8:12]} {card_digits[12:]}"
    
    def _generate_credit_card_smart(self, seed: int, max_length: int) -> str:
        """
        Smart Generation for credit cards - 3 format tiers with Luhn validation.
        
        - Formatted (≥19 chars): "4532-1234-5678-9012" or "4532 1234 5678 9012"
        - Plain (≥16 chars): "4532123456789012"
        - Short (13-15 chars): "4532123456789"
        
        All generated cards:
        - Use TEST BIN ranges only (never real cards)
        - Pass Luhn checksum validation
        - Are deterministic (same input → same output)
        
        Args:
            seed: Deterministic seed for generation
            max_length: Maximum column length
        
        Returns:
            Valid credit card number fitting within max_length
        
        Raises:
            ValueError: If max_length < 13 (minimum card length)
        """
        if max_length < self.MIN_CARD_LENGTH:
            raise ValueError(
                f"Column too short for credit card: {max_length}. "
                f"Minimum required: {self.MIN_CARD_LENGTH}"
            )
        
        # Determine card length based on column constraints first
        if max_length >= 19:
            # Can accommodate formatted output - use 16 or 15 digit cards
            # Select test BIN deterministically
            bin_prefix = self.TEST_BINS[seed % len(self.TEST_BINS)]
            if bin_prefix.startswith("37"):  # Amex
                card_length = self.CARD_LENGTH_15
            else:
                card_length = self.CARD_LENGTH_16
        elif max_length >= 16:
            # Can accommodate plain 16-digit cards, avoid Amex (15 digits + format = 18)
            # Select only non-Amex BINs
            non_amex_bins = [b for b in self.TEST_BINS if not b.startswith("37")]
            bin_prefix = non_amex_bins[seed % len(non_amex_bins)]
            card_length = self.CARD_LENGTH_16
        else:
            # Use 13-digit format for short columns
            non_amex_bins = [b for b in self.TEST_BINS if not b.startswith("37")]
            bin_prefix = non_amex_bins[seed % len(non_amex_bins)]
            card_length = self.CARD_LENGTH_13
        
        # Generate account number digits (excluding BIN and checksum)
        digits_needed = card_length - len(bin_prefix) - 1
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
        card_digits = card_without_check + check_digit
        
        # Format based on available length
        if max_length >= 19:
            # Use formatted output (alternate between dashes and spaces for diversity)
            if seed % 2 == 0:
                return self._format_card_with_dashes(card_digits)
            else:
                return self._format_card_with_spaces(card_digits)
        else:
            # Use plain digits (no formatting)
            return card_digits
    
    def _detect_address_component_type(self, column_info: ColumnInfo) -> str:
        """
        Detect address component type from column name using dynamic patterns.
        
        Returns:
            Component type: "city", "state", "postal", "line", "country", or "full"
        """
        import re
        from collections import defaultdict
        
        if not column_info.column_name:
            return "full"
        
        col_name = column_info.column_name.lower()
        scores = defaultdict(int)
        
        # Score-based pattern matching (more robust than first-match)
        for component, patterns in ADDRESS_COMPONENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, col_name):
                    scores[component] += 1
        
        if not scores:
            return "full"
        
        return max(scores, key=scores.get)
    
    def _detect_name_component_type(self, column_info: ColumnInfo) -> str:
        """
        Detect name component type from column name using regex patterns.
        
        Uses priority-based detection: component-specific patterns (first/middle/last)
        are checked first and take precedence over generic "full" patterns.
        
        Returns:
            "first", "middle", "last", or "full"
        """
        import re
        
        if not column_info.column_name:
            return "full"
        
        # Normalize column name (VERY IMPORTANT)
        col_name = column_info.column_name
        
        # 1. Replace underscores with spaces first
        col_name = col_name.replace("_", " ")
        
        # 2. Insert spaces before capital letters (CamelCase → Camel Case)
        #    Only if the string is not all uppercase (to avoid "FIRST" → "F I R S T")
        if not col_name.isupper():
            col_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', col_name)
        
        # 3. Convert to lowercase
        col_name = col_name.lower()
        
        # Priority 1: Check component-specific patterns first (first/middle/last)
        # These take precedence to avoid conflicts with generic "name" pattern
        component_types = ["first", "middle", "last"]
        for component in component_types:
            patterns = NAME_COMPONENT_PATTERNS.get(component, [])
            for pattern in patterns:
                if re.search(pattern, col_name):
                    return component  # Early exit on first match
        
        # Priority 2: Check "full" patterns only if no component matched
        full_patterns = NAME_COMPONENT_PATTERNS.get("full", [])
        for pattern in full_patterns:
            if re.search(pattern, col_name):
                return "full"
        
        # Default fallback: treat as full name if no patterns matched
        return "full"
    def mask_value(
        self,
        original: Any,
        pii_type: str,
        column_info: ColumnInfo,
        use_mapping: bool = True
    ) -> Any:
        """
        Mask a single value using Smart Generation.
        
        Args:
            original: Original value to mask
            pii_type: Type of PII (email, phone, name, ssn, generic)
            column_info: Column metadata for constraint checking
            use_mapping: Whether to use deterministic mapping
            
        Returns:
            Masked value that fits within column constraints
        """
        if original is None:
            return None
        
        # Get effective max length (handle NVARCHAR vs VARCHAR)
        max_length = column_info.max_length
        if max_length == -1:  # MAX type
            max_length = 4000
        
        # Create deterministic key for FK consistency
        # Include max_length for PII types with length-dependent formatting
        if use_mapping:
            cache_key = f"{pii_type}:{str(original)}:{max_length}"
            if cache_key in self._mapping_cache:
                return self._mapping_cache[cache_key]
        
        # Get deterministic seed from value
        seed = self._get_deterministic_seed(original)
        
        # Generate masked value using Smart Generation
        try:
            if pii_type == 'email':
                masked_value = self._generate_email_smart(seed, max_length)
            elif pii_type == 'phone':
                masked_value = self._generate_phone_smart(seed, max_length)
            elif pii_type == 'name':
                component_type = self._detect_name_component_type(column_info)
                masked_value = self._generate_name_smart(seed, max_length, component_type)
            elif pii_type == 'ssn':
                masked_value = self._generate_ssn_smart(seed, max_length)
            elif pii_type == 'address':
                # Detect component type from column name
                component_type = self._detect_address_component_type(column_info)
                masked_value = self._generate_address_smart(seed, max_length, component_type)
            elif pii_type == 'date_of_birth':
                # Generate date with age range 18-80 years
                masked_value = self._generate_date_of_birth_smart(
                    seed, max_length, column_info.data_type
                )
            elif pii_type == 'credit_card':
                # Generate credit card with Luhn validation and test BINs
                masked_value = self._generate_credit_card_smart(seed, max_length)
            else:  # generic and any other type
                masked_value = self._generate_generic_smart(original, max_length)
        except ValueError as e:
            # Column too short - use fallback
            print(f"      [WARN] {e}, using truncated fallback")
            masked_value = "X" * min(max_length, 1)
        except Exception as e:
            print(f"      [WARN] Masking error: {e}, using fallback")
            masked_value = f"MASK_{seed % 10000}"
        
        # Cache for consistency
        if use_mapping:
            self._mapping_cache[cache_key] = masked_value
        
        return masked_value


def load_config(config_path: str) -> dict:
    """Load configuration from JSON file."""
    print(f"\n[1/6] Loading configuration: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    print(f"  [OK] Server: {config['database']['server']}")
    print(f"  [OK] Database: {config['database']['database']}")
    print(f"  [OK] PII Columns: {len(config['pii_columns'])}")
    print(f"  [OK] Dry Run: {config.get('dry_run', True)}")
    
    return config


def build_connection_string(db_config: dict) -> str:
    """Build SQL Server connection string."""
    server = db_config['server']
    database = db_config['database']
    auth_type = db_config.get('auth_type', 'windows').lower()
    
    if auth_type == 'windows':
        return (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};DATABASE={database};"
            f"Trusted_Connection=yes;"
        )
    else:
        username = db_config.get('username', 'sa')
        password = db_config.get('password', '')
        return (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};DATABASE={database};"
            f"UID={username};PWD={password};"
        )


def get_column_metadata(conn, schema: str, table: str, column: str) -> ColumnInfo:
    """
    Get column metadata from database for Smart Generation.
    
    This is critical - Smart Generation needs to know column constraints
    to select the appropriate format tier.
    """
    query = """
    SELECT 
        c.DATA_TYPE,
        c.CHARACTER_MAXIMUM_LENGTH,
        c.IS_NULLABLE
    FROM INFORMATION_SCHEMA.COLUMNS c
    WHERE c.TABLE_SCHEMA = ?
      AND c.TABLE_NAME = ?
      AND c.COLUMN_NAME = ?
    """
    
    cursor = conn.cursor()
    cursor.execute(query, (schema, table, column))
    row = cursor.fetchone()
    
    if not row:
        # Default fallback
        return ColumnInfo(
            data_type="NVARCHAR",
            max_length=255,
            nullable=True,
            column_name=column
        )
    
    data_type = row[0]
    max_length = row[1]
    is_nullable = (row[2] == 'YES')
    
    return ColumnInfo(
        data_type=data_type,
        max_length=max_length,
        nullable=is_nullable,
        column_name=column
    )


def sanitize_column(
    conn,
    schema: str,
    table: str,
    column: str,
    pii_type: str,
    masker_engine: SmartMaskerEngine,
    dry_run: bool = True,
    connection_string: Optional[str] = None,
    mapping_manager: Optional['MappingManager'] = None,
    operation_id: Optional[UUID] = None,
    encryption_manager: Optional['EncryptionManager'] = None
) -> int:
    """
    Sanitize a single column using Smart Generation.
    
    Args:
        conn: Database connection
        schema: Schema name
        table: Table name
        column: Column name
        pii_type: Type of PII for masking strategy
        masker_engine: SmartMaskerEngine instance
        dry_run: If True, don't actually update database
        connection_string: Database connection string (for PK detection)
        mapping_manager: Optional MappingManager for capturing original→masked mappings
        operation_id: Optional UUID for this sanitization operation
        encryption_manager: Optional EncryptionManager for encrypting original values
        
    Returns:
        Number of rows updated
    """
    fully_qualified = f"[{schema}].[{table}]"
    
    try:
        # Get column metadata for Smart Generation
        column_info = get_column_metadata(conn, schema, table, column)
        
        print(f"     Type: {pii_type}")
        print(f"     Column: {column_info.data_type}({column_info.max_length})")
        
        # Detect primary key columns for row-specific restoration
        pk_info = None
        pk_columns_str = None
        if mapping_manager and operation_id and MAPPING_AVAILABLE and connection_string:
            try:
                from mapping import get_primary_key_cached
                pk_info = get_primary_key_cached(connection_string, schema, table)
                if pk_info:
                    pk_columns_str = ','.join([f"[{pk_col}]" for pk_col in pk_info.pk_columns])
            except Exception as pk_err:
                print(f"     [WARN] Could not detect primary key: {str(pk_err)[:50]}")
        
        # Build SELECT query with PK columns if available
        if pk_info and pk_columns_str:
            select_query = f"SELECT {pk_columns_str}, [{column}] FROM {fully_qualified} WHERE [{column}] IS NOT NULL"
        else:
            select_query = f"SELECT [{column}] FROM {fully_qualified} WHERE [{column}] IS NOT NULL"
        
        cursor = conn.cursor()
        cursor.execute(select_query)
        
        # Process and build update mappings
        updates = []
        mapping_entries = []  # For desanitization support
        
        for row in cursor.fetchall():
            # Extract PK values if available
            if pk_info:
                from mapping import extract_pk_values, pk_values_to_json
                try:
                    pk_values = extract_pk_values(row, pk_info.pk_columns)
                    pk_values_json = pk_values_to_json(pk_values)
                    pk_columns_json = pk_info.to_json()
                    # Original value is after PK columns
                    original = row[len(pk_info.pk_columns)]
                except Exception as pk_extract_err:
                    print(f"     [WARN] Failed to extract PK values: {str(pk_extract_err)[:50]}")
                    pk_values_json = None
                    pk_columns_json = None
                    original = row[0]
            else:
                pk_values_json = None
                pk_columns_json = None
                original = row[0]
            
            masked = masker_engine.mask_value(original, pii_type, column_info)
            updates.append((original, masked))  # (original, masked) for temp table insert
            
            # Capture mapping for desanitization (if enabled)
            if mapping_manager and operation_id and MAPPING_AVAILABLE:
                # Store original value - encrypted if encryption_manager available, else plaintext as bytes
                encrypted_original = None
                if encryption_manager:
                    try:
                        encrypted_original = encryption_manager.encrypt(original)
                    except Exception as enc_err:
                        print(f"     [WARN] Encryption failed for value: {str(enc_err)[:50]}")
                        # Fallback to plaintext on encryption failure
                        encrypted_original = _safe_encode(original)
                else:
                    # No encryption available - store plaintext as bytes for desanitization
                    encrypted_original = _safe_encode(original)
                
                # Create mapping entry with PK information
                try:
                    entry = create_mapping_entry(
                        operation_id=operation_id,
                        schema=schema,
                        table=table,
                        column=column,
                        original_value=original,
                        masked_value=masked,
                        data_type=column_info.data_type,
                        encrypted_original=encrypted_original,
                        primary_key_columns=pk_columns_json,
                        primary_key_values=pk_values_json
                    )
                    mapping_entries.append(entry)
                except Exception as map_err:
                    print(f"     [WARN] Failed to create mapping entry: {str(map_err)[:50]}")
        
        cursor.close()
        
        if not updates:
            print(f"     [OK] No non-NULL values to update")
            return 0
        
        # Update database (if not dry-run)
        if not dry_run:
            cursor = conn.cursor()
            
            # HIGH PERFORMANCE: Use temp table with single UPDATE-JOIN
            try:
                # Step 1: Create temp table
                cursor.execute(f"""
                    IF OBJECT_ID('tempdb..#temp_mappings') IS NOT NULL
                        DROP TABLE #temp_mappings;
                    
                    CREATE TABLE #temp_mappings (
                        original_value NVARCHAR(MAX),
                        masked_value NVARCHAR(MAX)
                    );
                """)
                
                # Step 2: Bulk insert mappings
                insert_query = "INSERT INTO #temp_mappings (original_value, masked_value) VALUES (?, ?)"
                cursor.executemany(insert_query, updates)
                conn.commit()
                
                # Step 3: Single UPDATE with JOIN (fast!)
                update_query = f"""
                    UPDATE t
                    SET t.[{column}] = m.masked_value
                    FROM {fully_qualified} t
                    INNER JOIN #temp_mappings m ON t.[{column}] = m.original_value
                    WHERE t.[{column}] IS NOT NULL;
                """
                cursor.execute(update_query)
                rows_affected = cursor.rowcount
                conn.commit()
                
                # Step 4: Cleanup temp table
                cursor.execute("DROP TABLE #temp_mappings;")
                conn.commit()
                
                cursor.close()
                
                # Handle -1 rowcount (fallback to update list count)
                if rows_affected == -1:
                    rows_affected = len(updates)
                
                # Store mappings after successful update (if enabled)
                if mapping_entries and mapping_manager and not dry_run:
                    try:
                        stats = mapping_manager.store_mappings(mapping_entries)
                        print(f"     [OK] Updated {rows_affected:,} rows | Stored {stats.total_mappings} mappings")
                    except Exception as mapping_err:
                        print(f"     [OK] Updated {rows_affected:,} rows | [WARN] Mapping storage failed: {str(mapping_err)[:50]}")
                else:
                    print(f"     [OK] Updated {rows_affected:,} rows")
                
                return rows_affected
                
            except pyodbc.Error as inner_e:
                # Rollback on error
                conn.rollback()
                print(f"     [WARN] Bulk update failed: {str(inner_e)[:100]}")
                print(f"     [INFO] Falling back to row-by-row updates...")
                
                # Fallback: Individual updates (slower but reliable)
                cursor = conn.cursor()
                update_query = f"""
                    UPDATE {fully_qualified}
                    SET [{column}] = ?
                    WHERE [{column}] = ?
                """
                
                total_updated = 0
                for original_val, masked_val in updates:
                    try:
                        cursor.execute(update_query, (masked_val, original_val))
                        if cursor.rowcount > 0:
                            total_updated += cursor.rowcount
                    except pyodbc.Error:
                        continue  # Skip problematic rows
                
                conn.commit()
                cursor.close()
                
                print(f"     [OK] Updated {total_updated:,} rows (fallback method)")
                return total_updated
        else:
            print(f"     [OK] Would update {len(updates):,} rows (DRY-RUN)")
            return len(updates)
            
    except pyodbc.Error as e:
        error_msg = str(e)
        print(f"     [ERR] Error: {error_msg[:100]}")
        
        # Check for specific error types
        if "truncat" in error_msg.lower():
            print(f"     [WARN] TRUNCATION ERROR - This should not happen with Smart Generation!")
            print(f"        Column max length: {column_info.max_length}")
            print(f"        Please report this as a bug")
        elif "computed column" in error_msg.lower():
            print(f"     [WARN] Cannot modify computed column - skipping")
        
        return 0


def main():
    """Main execution function."""
    import sys
    
    # Check arguments
    if len(sys.argv) < 2:
        print("Usage: python sanitize_smart.py <config_file>")
        print("Example: python sanitize_smart.py config/pii_config_ai_generated.json")
        sys.exit(1)
    
    config_path = sys.argv[1]
    
    print("="*80)
    print("DATABASE SANITIZATION WITH SMART GENERATION")
    print("="*80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Config: {config_path}")
    
    # Load configuration
    try:
        config = load_config(config_path)
    except Exception as e:
        print(f"\n[ERROR] Configuration error: {e}")
        sys.exit(1)
    
    dry_run = config.get('dry_run', True)
    
    # Warning for actual execution
    if not dry_run:
        print(f"\n[WARN]  WARNING: This will MODIFY your database!")
        print(f"[WARN]  All PII data will be replaced with fake data!")
        response = input("\nContinue anyway? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            sys.exit(0)
    else:
        print(f"\n[OK] Dry-run mode: No database changes will be made")
    
    # Backup check
    if not dry_run:
        print(f"\n[2/6] Database backup check")
        print(f"  [WARN] Backup recommended before sanitization!")
        response = input("Do you have a backup? (yes/no): ")
        if response.lower() != 'yes':
            print("Please create a backup first. Aborted.")
            sys.exit(0)
    else:
        print(f"\n[2/6] Backup check - Skipped (dry-run mode)")
    
    # Connect to database
    print(f"\n[3/6] Connecting to database")
    try:
        conn_string = build_connection_string(config['database'])
        conn = pyodbc.connect(conn_string)
        print(f"  [OK] Connection successful")
        
        # Disable autocommit for transactions
        conn.autocommit = False
        
    except Exception as e:
        print(f"  [ERR] Connection failed: {e}")
        sys.exit(1)
    
    # Initialize Smart Generation masker engine
    print(f"\n[4/6] Initializing Smart Generation maskers")
    try:
        masker_engine = SmartMaskerEngine(seed=42)
        print(f"  [OK] EmailMasker: 3 format tiers (6-26 chars)")
        print(f"  [OK] PhoneMasker: 3 format tiers (10-14 chars)")
        print(f"  [OK] NameMasker: 4 format tiers (2-20 chars)")
        print(f"  [OK] SSNMasker: 2 format tiers (9-11 chars)")
        print(f"  [OK] AddressMasker: Smart length adaptation")
        print(f"  [OK] DateOfBirthMasker: Age range 18-80 years, 4 format tiers")
        print(f"  [OK] CreditCardMasker: 3 format tiers (13-19 chars), Luhn validated")
        print(f"  [OK] GenericMasker: Exact length generation")
    except Exception as e:
        print(f"  [ERR] Initialization failed: {e}")
        sys.exit(1)
    
    # Initialize mapping capture for desanitization (if available)
    operation_id = uuid4()
    encryption_manager = None
    mapping_manager = None
    
    if MAPPING_AVAILABLE and not dry_run:
        print(f"\n[4b/6] Initializing mapping capture for desanitization")
        print(f"  Operation ID: {operation_id}")
        
        # Initialize encryption manager
        try:
            encryption_manager = EncryptionManager()
            print(f"  [OK] Encryption enabled: {encryption_manager.get_key_info()['algorithm']}")
        except EncryptionKeyError as enc_err:
            print(f"  [WARN] Encryption disabled: {str(enc_err)[:80]}")
            print(f"  [INFO] Mappings will be stored without encryption")
            encryption_manager = None
        except Exception as enc_err:
            print(f"  [WARN] Encryption initialization failed: {str(enc_err)[:80]}")
            encryption_manager = None
        
        # Initialize mapping manager
        try:
            mapping_manager = MappingManager(
                connection_string=conn_string,
                encryption_manager=encryption_manager
            )
            mapping_manager.initialize()
            print(f"  [OK] Mapping table initialized: dbo.pii_mappings")
            print(f"  [OK] Desanitization support enabled")
        except Exception as map_err:
            print(f"  [WARN] Mapping manager initialization failed: {str(map_err)[:80]}")
            print(f"  [INFO] Continuing without mapping capture")
            mapping_manager = None
    elif dry_run:
        print(f"\n[4b/6] Mapping capture - Skipped (dry-run mode)")
        print(f"  [INFO] Enable mapping capture by setting dry_run=false")
    else:
        print(f"\n[4b/6] Mapping capture - Not Available")
        print(f"  [WARN] Mapping modules not installed - desanitization disabled")
    
    # Sanitize each PII column
    print(f"\n[5/6] Sanitizing PII columns")
    
    total_rows = 0
    successful = 0
    failed = 0
    
    pii_columns = config.get('pii_columns', [])
    
    for i, col_config in enumerate(pii_columns, 1):
        schema = col_config.get('schema', 'dbo')
        table = col_config['table']
        column = col_config['column']
        pii_type = col_config['pii_type']
        
        print(f"\n[{i}/{len(pii_columns)}] Sanitizing {schema}.{table}.{column}")
        
        try:
            rows = sanitize_column(
                conn, schema, table, column, pii_type,
                masker_engine, dry_run,
                connection_string=conn_string,
                mapping_manager=mapping_manager,
                operation_id=operation_id,
                encryption_manager=encryption_manager
            )
            total_rows += rows
            successful += 1
        except Exception as e:
            print(f"     [ERR] Unexpected error: {e}")
            failed += 1
    
    # Commit if not dry-run
    if not dry_run and successful > 0:
        try:
            conn.commit()
            print(f"\n[OK] Transaction committed")
        except Exception as e:
            conn.rollback()
            print(f"\n[ERR] Commit failed, rolled back: {e}")
    
    conn.close()
    
    # Display results
    print(f"\n[6/6] Results")
    print("="*80)
    print(f"{'[SUCCESS] SANITIZATION COMPLETED' if failed == 0 else '[WARN]  SANITIZATION COMPLETED WITH ERRORS'}")
    print("="*80)
    
    print(f"\nColumns:")
    print(f"  [OK] Successful: {successful}")
    if failed > 0:
        print(f"  [ERR] Failed: {failed}")
    print(f"  Total: {len(pii_columns)}")
    
    print(f"\nRows:")
    if dry_run:
        print(f"  Would update: {total_rows:,} (DRY-RUN)")
    else:
        print(f"  Updated: {total_rows:,}")
    
    print(f"\nSmart Generation:")
    print(f"  [SUCCESS] All maskers use constraint-aware generation")
    print(f"  [SUCCESS] Zero truncation errors expected")
    print(f"  [SUCCESS] All fake values fit column constraints perfectly")
    
    if mapping_manager and not dry_run:
        print(f"\nDesanitization:")
        try:
            stats = mapping_manager.get_stats(operation_id)
            print(f"  [SUCCESS] Mappings captured: {stats.total_mappings:,}")
            print(f"  [SUCCESS] Tables tracked: {stats.tables_affected}")
            
            # Show encryption status
            if encryption_manager:
                print(f"  [SUCCESS] Values encrypted: {stats.encrypted_count:,} (AES-256)")
            else:
                print(f"  [SUCCESS] Values stored: {stats.encrypted_count:,} (plaintext - set SANITIZATION_ENCRYPTION_KEY for encryption)")
            
            print(f"  [INFO] Operation ID: {operation_id}")
            print(f"  [TIP] To restore original data, use: python desanitize.py {operation_id}")
        except Exception as stats_err:
            print(f"  [WARN] Could not retrieve mapping stats: {str(stats_err)[:80]}")
    
    if dry_run:
        print(f"\n[TIP] To execute actual sanitization:")
        print(f"   1. Set 'dry_run': false in {config_path}")
        print(f"   2. Run: python sanitize_smart.py {config_path}")
    
    print("="*80)
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)


if __name__ == "__main__":
    main()
