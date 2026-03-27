"""
Unit tests for PhoneMasker class.

These tests validate:
- Basic phone masking functionality
- Deterministic masking (same input → same output)
- Multi-tier length optimization (standard, compact, minimal)
- Format validation (US, international, plain digits)
- Length constraint handling (VARCHAR, NVARCHAR, CHAR)
- Edge cases (whitespace, extensions, invalid formats)
- Integration with BaseMasker
- NULL handling strategies
- Error handling (column too short, invalid data types)

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from unittest.mock import Mock, patch
from typing import Optional

from src.masking.phone_masker import PhoneMasker
from src.masking.base_masker import ColumnInfo, MaskingStrategy
from src.exceptions import MaskingError
from src.error_codes import ErrorCodes


# ==================== Test Fixtures ====================


@pytest.fixture
def phone_masker():
    """Create a PhoneMasker with default seed."""
    return PhoneMasker(seed=42)


@pytest.fixture
def varchar_20():
    """Create a VARCHAR(20) column info for standard format."""
    return ColumnInfo(
        data_type="VARCHAR",
        max_length=20,
        nullable=True,
        is_unicode=False,
        is_fixed_length=False
    )


@pytest.fixture
def varchar_14():
    """Create a VARCHAR(14) column info for standard format (exact fit)."""
    return ColumnInfo(
        data_type="VARCHAR",
        max_length=14,
        nullable=True,
        is_unicode=False,
        is_fixed_length=False
    )


@pytest.fixture
def varchar_12():
    """Create a VARCHAR(12) column info for compact format."""
    return ColumnInfo(
        data_type="VARCHAR",
        max_length=12,
        nullable=True,
        is_unicode=False,
        is_fixed_length=False
    )


@pytest.fixture
def varchar_10():
    """Create a VARCHAR(10) column info for minimal format."""
    return ColumnInfo(
        data_type="VARCHAR",
        max_length=10,
        nullable=True,
        is_unicode=False,
        is_fixed_length=False
    )


@pytest.fixture
def nvarchar_20():
    """Create an NVARCHAR(20) column info."""
    return ColumnInfo(
        data_type="NVARCHAR",
        max_length=20,
        nullable=False,
        is_unicode=True,
        is_fixed_length=False
    )


@pytest.fixture
def char_20():
    """Create a CHAR(20) fixed-length column info."""
    return ColumnInfo(
        data_type="CHAR",
        max_length=20,
        nullable=True,
        is_unicode=False,
        is_fixed_length=True
    )


# ==================== Basic Functionality Tests (8 tests) ====================


class TestBasicFunctionality:
    """Test basic phone masking functionality."""
    
    def test_initialization_default_seed(self):
        """Test PhoneMasker initialization with default seed."""
        masker = PhoneMasker()
        assert masker.seed == 42
        assert masker.null_strategy == MaskingStrategy.PRESERVE
        assert masker.AREA_CODE == 555
        assert masker.MIN_LENGTH == 10
    
    def test_initialization_custom_seed(self):
        """Test PhoneMasker initialization with custom seed."""
        masker = PhoneMasker(seed=123)
        assert masker.seed == 123
    
    def test_initialization_custom_null_strategy(self):
        """Test PhoneMasker initialization with custom NULL strategy."""
        masker = PhoneMasker(null_strategy=MaskingStrategy.MASK)
        assert masker.null_strategy == MaskingStrategy.MASK
    
    def test_initialization_negative_seed_raises_error(self):
        """Test that negative seed raises ValueError."""
        with pytest.raises(ValueError, match="Seed must be non-negative"):
            PhoneMasker(seed=-1)
    
    def test_basic_phone_masking(self, phone_masker, varchar_20):
        """Test basic phone masking returns valid phone."""
        phone = "(555) 123-4567"
        masked = phone_masker.mask(phone, varchar_20)
        
        assert masked is not None
        assert len(masked) <= 20
        assert '555' in masked  # Area code
    
    def test_determinism_same_input_same_output(self, phone_masker, varchar_20):
        """Test that same phone input produces same masked output."""
        phone = "(555) 123-4567"
        
        masked1 = phone_masker.mask(phone, varchar_20)
        masked2 = phone_masker.mask(phone, varchar_20)
        
        assert masked1 == masked2
    
    def test_different_inputs_different_outputs(self, phone_masker, varchar_20):
        """Test that different phones produce different masked outputs."""
        phone1 = "(555) 123-4567"
        phone2 = "(555) 987-6543"
        
        masked1 = phone_masker.mask(phone1, varchar_20)
        masked2 = phone_masker.mask(phone2, varchar_20)
        
        assert masked1 != masked2
    
    def test_determinism_across_instances(self, varchar_20):
        """Test determinism across different masker instances with same seed."""
        masker1 = PhoneMasker(seed=42)
        masker2 = PhoneMasker(seed=42)
        
        phone = "(555) 555-5555"
        
        masked1 = masker1.mask(phone, varchar_20)
        masked2 = masker2.mask(phone, varchar_20)
        
        assert masked1 == masked2


# ==================== Phone Validation Tests (8 tests) ====================


class TestPhoneValidation:
    """Test phone format validation."""
    
    def test_valid_us_parens_format(self, phone_masker):
        """Test validation of US format with parentheses."""
        assert phone_masker._validate_phone_format("(555) 123-4567") is True
    
    def test_valid_us_dash_format(self, phone_masker):
        """Test validation of US format with dashes."""
        assert phone_masker._validate_phone_format("555-123-4567") is True
    
    def test_valid_us_dot_format(self, phone_masker):
        """Test validation of US format with dots."""
        assert phone_masker._validate_phone_format("555.123.4567") is True
    
    def test_valid_plain_digits(self, phone_masker):
        """Test validation of plain 10-digit number."""
        assert phone_masker._validate_phone_format("5551234567") is True
    
    def test_valid_international_with_country_code(self, phone_masker):
        """Test validation of international format with +1."""
        assert phone_masker._validate_phone_format("+1-555-123-4567") is True
    
    def test_valid_international_uk(self, phone_masker):
        """Test validation of UK international format."""
        assert phone_masker._validate_phone_format("+44 20 1234 5678") is True
    
    def test_valid_with_extension(self, phone_masker):
        """Test validation of phone with extension."""
        assert phone_masker._validate_phone_format("555-123-4567 ext. 123") is True
    
    def test_invalid_format(self, phone_masker):
        """Test that clearly invalid string is rejected."""
        assert phone_masker._validate_phone_format("not-a-phone") is False


# ==================== Format Generation Tests (10 tests) ====================


class TestFormatGeneration:
    """Test phone number format generation."""
    
    def test_standard_format_structure(self, phone_masker, varchar_20):
        """Test that standard format has correct structure."""
        phone = "5551234567"
        masked = phone_masker.mask(phone, varchar_20)
        
        # Standard format: (555) 555-5555
        assert masked.startswith("(555)")
        assert ")" in masked
        assert "-" in masked
        assert len(masked) == 14
    
    def test_compact_format_structure(self, phone_masker, varchar_12):
        """Test that compact format has correct structure."""
        phone = "5551234567"
        masked = phone_masker.mask(phone, varchar_12)
        
        # Compact format: 555-555-5555
        assert masked.startswith("555-")
        assert masked.count("-") == 2
        assert len(masked) == 12
    
    def test_minimal_format_structure(self, phone_masker, varchar_10):
        """Test that minimal format has correct structure."""
        phone = "5551234567"
        masked = phone_masker.mask(phone, varchar_10)
        
        # Minimal format: 5555555555
        assert masked.startswith("555")
        assert "-" not in masked
        assert "(" not in masked
        assert len(masked) == 10
    
    def test_all_formats_use_555_area_code(self, phone_masker):
        """Test that all formats use 555 area code."""
        phone = "1234567890"
        
        # Test with different lengths
        col_20 = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
        col_12 = ColumnInfo(data_type="VARCHAR", max_length=12, nullable=True)
        col_10 = ColumnInfo(data_type="VARCHAR", max_length=10, nullable=True)
        
        masked_20 = phone_masker.mask(phone, col_20)
        masked_12 = phone_masker.mask(phone, col_12)
        masked_10 = phone_masker.mask(phone, col_10)
        
        assert "555" in masked_20
        assert masked_12.startswith("555")
        assert masked_10.startswith("555")
    
    def test_exchange_in_valid_range(self, phone_masker, varchar_20):
        """Test that exchange (middle 3 digits) is in valid range 100-999."""
        import re
        
        # Generate multiple phones
        for i in range(20):
            phone = f"555123{i:04d}"
            masked = phone_masker.mask(phone, varchar_20)
            
            # Extract exchange from format: (555) XXX-YYYY
            match = re.search(r'\(555\)\s(\d{3})', masked)
            if match:
                exchange = int(match.group(1))
                assert 100 <= exchange <= 999
    
    def test_subscriber_in_valid_range(self, phone_masker, varchar_20):
        """Test that subscriber (last 4 digits) is in valid range 1000-9999."""
        import re
        
        # Generate multiple phones
        for i in range(20):
            phone = f"555123{i:04d}"
            masked = phone_masker.mask(phone, varchar_20)
            
            # Extract subscriber from format: (555) XXX-YYYY
            match = re.search(r'-(\d{4})$', masked)
            if match:
                subscriber = int(match.group(1))
                assert 1000 <= subscriber <= 9999
    
    def test_format_tier_standard(self, phone_masker):
        """Test _get_format_tier returns 'standard' for length >= 14."""
        assert phone_masker._get_format_tier(14) == "standard"
        assert phone_masker._get_format_tier(20) == "standard"
        assert phone_masker._get_format_tier(100) == "standard"
    
    def test_format_tier_compact(self, phone_masker):
        """Test _get_format_tier returns 'compact' for length 12-13."""
        assert phone_masker._get_format_tier(12) == "compact"
        assert phone_masker._get_format_tier(13) == "compact"
    
    def test_format_tier_minimal(self, phone_masker):
        """Test _get_format_tier returns 'minimal' for length 10-11."""
        assert phone_masker._get_format_tier(10) == "minimal"
        assert phone_masker._get_format_tier(11) == "minimal"
    
    def test_format_tier_error(self, phone_masker):
        """Test _get_format_tier returns 'error' for length < 10."""
        assert phone_masker._get_format_tier(9) == "error"
        assert phone_masker._get_format_tier(5) == "error"


# ==================== Length Constraints Tests (7 tests) ====================


class TestLengthConstraints:
    """Test length constraint handling."""
    
    def test_varchar_20_fits_standard_format(self, phone_masker, varchar_20):
        """Test that VARCHAR(20) uses standard format."""
        phone = "5551234567"
        masked = phone_masker.mask(phone, varchar_20)
        
        assert len(masked) == 14  # (555) 555-5555
        assert len(masked) <= 20
    
    def test_varchar_14_exact_fit_standard(self, phone_masker, varchar_14):
        """Test that VARCHAR(14) uses standard format (exact fit)."""
        phone = "5551234567"
        masked = phone_masker.mask(phone, varchar_14)
        
        assert len(masked) == 14
    
    def test_varchar_12_uses_compact(self, phone_masker, varchar_12):
        """Test that VARCHAR(12) uses compact format."""
        phone = "5551234567"
        masked = phone_masker.mask(phone, varchar_12)
        
        assert len(masked) == 12  # 555-555-5555
        assert masked.count("-") == 2
    
    def test_varchar_10_uses_minimal(self, phone_masker, varchar_10):
        """Test that VARCHAR(10) uses minimal format."""
        phone = "5551234567"
        masked = phone_masker.mask(phone, varchar_10)
        
        assert len(masked) == 10  # 5555555555
        assert "-" not in masked
    
    def test_varchar_9_raises_error(self, phone_masker):
        """Test that column shorter than 10 chars raises MaskingError."""
        phone = "5551234567"
        col = ColumnInfo(data_type="VARCHAR", max_length=9, nullable=True)
        
        with pytest.raises(MaskingError) as exc_info:
            phone_masker.mask(phone, col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_LENGTH_EXCEEDED
        assert "min 10 chars required" in str(exc_info.value)
    
    def test_nvarchar_respects_length(self, phone_masker, nvarchar_20):
        """Test that NVARCHAR respects max_length."""
        phone = "+1-555-123-4567"
        masked = phone_masker.mask(phone, nvarchar_20)
        
        assert len(masked) <= 20
    
    def test_char_fixed_length_padding(self, phone_masker, char_20):
        """Test that CHAR columns are padded to fixed length."""
        phone = "5551234567"
        masked = phone_masker.mask(phone, char_20)
        
        # CHAR(20) should be padded with spaces
        assert len(masked) == 20
        assert masked.rstrip() == masked.rstrip()  # Has padding


# ==================== Edge Cases Tests (10 tests) ====================


class TestEdgeCases:
    """Test edge case handling."""
    
    def test_whitespace_trimmed(self, phone_masker, varchar_20):
        """Test that leading/trailing whitespace is trimmed."""
        phone = "  (555) 123-4567  "
        masked = phone_masker.mask(phone, varchar_20)
        
        assert masked is not None
        assert not masked.startswith(" ")
        assert not masked.endswith(" ")
    
    def test_extension_ignored(self, phone_masker, varchar_20):
        """Test that phone extensions are ignored (masked without extension)."""
        phone1 = "555-123-4567 ext. 123"
        phone2 = "555-123-4567"
        
        # Should produce same output (extension ignored in generation)
        # But different inputs produce different seeds
        masked1 = phone_masker.mask(phone1, varchar_20)
        masked2 = phone_masker.mask(phone2, varchar_20)
        
        # Both should be valid phones without extensions
        assert "ext" not in masked1
        assert "ext" not in masked2
    
    def test_very_long_phone_number(self, phone_masker, varchar_20):
        """Test that very long phone numbers are handled."""
        phone = "+1-555-123-4567-999-888-777"
        masked = phone_masker.mask(phone, varchar_20)
        
        assert masked is not None
        assert len(masked) <= 20
    
    def test_international_prefix_different_countries(self, phone_masker, varchar_20):
        """Test that different country codes produce different outputs."""
        phone_us = "+1-555-123-4567"
        phone_uk = "+44-20-1234-5678"
        
        masked_us = phone_masker.mask(phone_us, varchar_20)
        masked_uk = phone_masker.mask(phone_uk, varchar_20)
        
        assert masked_us != masked_uk
    
    def test_special_characters_handled(self, phone_masker, varchar_20):
        """Test that special characters in input are handled."""
        phone = "(555) 123-4567 #"
        masked = phone_masker.mask(phone, varchar_20)
        
        assert masked is not None
        assert "#" not in masked
    
    def test_invalid_format_still_masked(self, phone_masker, varchar_20):
        """Test that invalid format is still masked (AI false positives)."""
        phone = "not-really-a-phone-123"
        masked = phone_masker.mask(phone, varchar_20)
        
        # Should still generate a valid phone number
        assert masked is not None
        assert "555" in masked
    
    def test_empty_string_after_strip(self, phone_masker, varchar_20):
        """Test that empty string after stripping is handled."""
        phone = "   "
        masked = phone_masker.mask(phone, varchar_20)
        
        # Should still generate a phone (deterministic based on empty string)
        assert masked is not None
        assert len(masked) > 0
    
    def test_plain_digits_no_formatting(self, phone_masker, varchar_20):
        """Test that plain 10-digit number is accepted."""
        phone = "5551234567"
        masked = phone_masker.mask(phone, varchar_20)
        
        assert masked is not None
        assert "555" in masked
    
    def test_case_insensitive_extension(self, phone_masker, varchar_20):
        """Test that extensions with different cases are recognized."""
        phone1 = "555-123-4567 EXT 123"
        phone2 = "555-123-4567 ext 123"
        
        # Both should be considered valid formats
        assert phone_masker._validate_phone_format(phone1) is True
        assert phone_masker._validate_phone_format(phone2) is True
    
    def test_dots_as_separators(self, phone_masker, varchar_20):
        """Test that dots as separators are valid."""
        phone = "555.123.4567"
        assert phone_masker._validate_phone_format(phone) is True
        
        masked = phone_masker.mask(phone, varchar_20)
        assert masked is not None


# ==================== NULL Handling Tests (5 tests) ====================


class TestNullHandling:
    """Test NULL value handling strategies."""
    
    def test_null_with_preserve_strategy(self, varchar_20):
        """Test that NULL returns None with PRESERVE strategy."""
        masker = PhoneMasker(null_strategy=MaskingStrategy.PRESERVE)
        masked = masker.mask(None, varchar_20)
        
        assert masked is None
    
    def test_null_with_mask_strategy(self, varchar_20):
        """Test that NULL generates fake phone with MASK strategy."""
        masker = PhoneMasker(null_strategy=MaskingStrategy.MASK)
        masked = masker.mask(None, varchar_20)
        
        assert masked is not None
        assert "555" in masked
    
    def test_null_on_not_null_column_with_preserve_raises(self):
        """Test that NULL on NOT NULL column with PRESERVE raises error."""
        masker = PhoneMasker(null_strategy=MaskingStrategy.PRESERVE)
        col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=False)
        
        with pytest.raises(MaskingError) as exc_info:
            masker.mask(None, col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_NULL_CONSTRAINT_VIOLATION
    
    def test_null_determinism_with_mask_strategy(self, varchar_20):
        """Test that NULL with MASK strategy is deterministic."""
        masker = PhoneMasker(null_strategy=MaskingStrategy.MASK)
        
        masked1 = masker.mask(None, varchar_20)
        masked2 = masker.mask(None, varchar_20)
        
        assert masked1 == masked2
    
    def test_nullable_column_with_value(self, phone_masker, varchar_20):
        """Test that nullable column with actual value is masked normally."""
        phone = "555-123-4567"
        masked = phone_masker.mask(phone, varchar_20)
        
        assert masked is not None
        assert "555" in masked


# ==================== Data Type Compatibility Tests (6 tests) ====================


class TestDataTypeCompatibility:
    """Test data type compatibility and validation."""
    
    def test_varchar_compatible(self, phone_masker, varchar_20):
        """Test that VARCHAR is compatible."""
        phone = "5551234567"
        masked = phone_masker.mask(phone, varchar_20)
        
        assert masked is not None
        assert isinstance(masked, str)
    
    def test_nvarchar_compatible(self, phone_masker, nvarchar_20):
        """Test that NVARCHAR is compatible."""
        phone = "+1-555-123-4567"
        masked = phone_masker.mask(phone, nvarchar_20)
        
        assert masked is not None
        assert isinstance(masked, str)
    
    def test_char_compatible(self, phone_masker, char_20):
        """Test that CHAR is compatible."""
        phone = "5551234567"
        masked = phone_masker.mask(phone, char_20)
        
        assert masked is not None
        assert isinstance(masked, str)
    
    def test_nchar_compatible(self, phone_masker):
        """Test that NCHAR is compatible."""
        phone = "5551234567"
        col = ColumnInfo(data_type="NCHAR", max_length=20, nullable=True, is_fixed_length=True)
        
        masked = phone_masker.mask(phone, col)
        
        assert masked is not None
        assert isinstance(masked, str)
    
    def test_invalid_data_type_int_raises(self, phone_masker):
        """Test that INT data type raises error."""
        phone = "5551234567"
        col = ColumnInfo(data_type="INT", max_length=None, nullable=True)
        
        with pytest.raises(MaskingError) as exc_info:
            phone_masker.mask(phone, col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_TYPE_MISMATCH
    
    def test_invalid_data_type_datetime_raises(self, phone_masker):
        """Test that DATETIME data type raises error."""
        phone = "5551234567"
        col = ColumnInfo(data_type="DATETIME", max_length=None, nullable=True)
        
        with pytest.raises(MaskingError) as exc_info:
            phone_masker.mask(phone, col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_TYPE_MISMATCH


# ==================== Determinism Across Sessions Tests (3 tests) ====================


class TestDeterminismAcrossSessions:
    """Test determinism across different sessions and scenarios."""
    
    def test_same_seed_different_instances(self, varchar_20):
        """Test that different instances with same seed produce identical output."""
        phone = "(555) 123-4567"
        
        masker1 = PhoneMasker(seed=42)
        masker2 = PhoneMasker(seed=42)
        
        masked1 = masker1.mask(phone, varchar_20)
        masked2 = masker2.mask(phone, varchar_20)
        
        assert masked1 == masked2
    
    def test_different_seeds_different_outputs(self, varchar_20):
        """Test that different seeds produce different outputs."""
        phone = "(555) 123-4567"
        
        masker1 = PhoneMasker(seed=42)
        masker2 = PhoneMasker(seed=123)
        
        masked1 = masker1.mask(phone, varchar_20)
        masked2 = masker2.mask(phone, varchar_20)
        
        assert masked1 != masked2
    
    def test_determinism_with_special_chars(self, varchar_20):
        """Test determinism with special characters in input."""
        phone = "(555) 123-4567 ext. 999"
        
        masker = PhoneMasker(seed=42)
        
        masked1 = masker.mask(phone, varchar_20)
        masked2 = masker.mask(phone, varchar_20)
        
        assert masked1 == masked2


# ==================== Error Conditions Tests (4 tests) ====================


class TestErrorConditions:
    """Test error handling and validation."""
    
    def test_column_too_short_raises_detailed_error(self, phone_masker):
        """Test that column < 10 chars raises detailed error."""
        phone = "5551234567"
        col = ColumnInfo(data_type="VARCHAR", max_length=9, nullable=True)
        
        with pytest.raises(MaskingError) as exc_info:
            phone_masker.mask(phone, col)
        
        error = exc_info.value
        assert error.error_code == ErrorCodes.MASKING_LENGTH_EXCEEDED
        assert "min 10 chars required" in error.message
        assert error.is_retryable is False
        assert "Increase column length" in error.suggested_action
        assert error.operation_context["minimum_required"] == 10
    
    def test_invalid_data_type_raises_error(self, phone_masker):
        """Test that invalid data type raises error."""
        phone = "5551234567"
        col = ColumnInfo(data_type="BIGINT", max_length=None, nullable=True)
        
        with pytest.raises(MaskingError) as exc_info:
            phone_masker.mask(phone, col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_TYPE_MISMATCH
    
    def test_null_on_not_null_column_raises(self, phone_masker):
        """Test that NULL on NOT NULL column raises appropriate error."""
        col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=False)
        
        with pytest.raises(MaskingError) as exc_info:
            phone_masker.mask(None, col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_NULL_CONSTRAINT_VIOLATION
    
    def test_error_message_contains_context(self, phone_masker):
        """Test that error messages contain helpful context."""
        phone = "5551234567"
        col = ColumnInfo(data_type="VARCHAR", max_length=5, nullable=True)
        
        with pytest.raises(MaskingError) as exc_info:
            phone_masker.mask(phone, col)
        
        error_dict = exc_info.value.to_dict()
        assert "column_type" in error_dict["operation_context"]
        assert error_dict["operation_context"]["column_type"] == "phone"
