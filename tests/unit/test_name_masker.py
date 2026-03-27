"""
Unit tests for NameMasker class.

Tests cover:
- Basic masking functionality (deterministic mapping)
- Multi-tier length optimization (Full → First+Last → First → Initial)
- Name structure detection (prefixes, suffixes, hyphenation)
- NULL handling strategies (PRESERVE, MASK)
- Data type validation (VARCHAR, NVARCHAR, TEXT, CHAR)
- Edge cases (Unicode, special characters, length constraints)
- Error handling (column too short, invalid types)

Test Organization:
- TestNameMaskerBasic: Core deterministic mapping, seed behavior
- TestNameMaskerLengthTiers: Multi-tier optimization across length ranges
- TestNameMaskerNameStructure: Prefix/suffix/hyphenation detection
- TestNameMaskerDataTypes: VARCHAR vs NVARCHAR, fixed vs variable length
- TestNameMaskerNullHandling: NULL strategies and NOT NULL columns 
- TestNameMaskerValidation: Format validation and error handling
- TestNameMaskerEdgeCases: Unicode, whitespace, special characters

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from unittest.mock import Mock, patch
from faker import Faker

from src.masking import NameMasker
from src.masking.base_masker import ColumnInfo, MaskingStrategy
from src.exceptions import MaskingError
from src.error_codes import ErrorCodes


class TestNameMaskerBasic:
    """Test basic name masking functionality."""
    
    def test_initialization_default(self):
        """Test default initialization."""
        masker = NameMasker()
        assert masker.seed == 42
        assert masker.null_strategy == MaskingStrategy.PRESERVE
        assert masker.logger is not None
    
    def test_initialization_custom_seed(self):
        """Test initialization with custom seed."""
        masker = NameMasker(seed=12345)
        assert masker.seed == 12345
    
    def test_initialization_custom_null_strategy(self):
        """Test initialization with custom NULL strategy."""
        masker = NameMasker(null_strategy=MaskingStrategy.MASK)
        assert masker.null_strategy == MaskingStrategy.MASK
    
    def test_deterministic_masking(self):
        """Test that same input produces same output."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        name1 = masker.mask("John Doe", col)
        name2 = masker.mask("John Doe", col)
        
        assert name1 == name2
        assert name1 is not None
        assert len(name1) <= 50
    
    def test_different_inputs_different_outputs(self):
        """Test that different inputs produce different outputs."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        name1 = masker.mask("John Doe", col)
        name2 = masker.mask("Jane Smith", col)
        
        assert name1 != name2
    
    def test_seed_independence(self):
        """Test that different seeds produce different outputs for same input."""
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        masker1 = NameMasker(seed=42)
        masker2 = NameMasker(seed=999)
        
        name1 = masker1.mask("John Doe", col)
        name2 = masker2.mask("John Doe", col)
        
        # Different seeds should produce different results
        assert name1 != name2


class TestNameMaskerLengthTiers:
    """Test multi-tier length optimization strategy."""
    
    def test_tier_full_name(self):
        """Test full name tier (20+ chars)."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        fake_name = masker.mask("John Doe", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 50
        # Full tier should have at least first + last name
        assert " " in fake_name
    
    def test_tier_first_last(self):
        """Test first + last name tier (10-19 chars)."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=15, nullable=True)
        
        fake_name = masker.mask("John Doe", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 15
        # Should have space between first and last if possible
        assert " " in fake_name or len(fake_name) == 15
    
    def test_tier_first_only(self):
        """Test first name only tier (4-9 chars)."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=8, nullable=True)
        
        fake_name = masker.mask("John", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 8
        # First name only - no spaces in typical case
        # (might have space if name is exactly 8 chars and truncated)
    
    def test_tier_initial(self):
        """Test initial tier (2-3 chars)."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=2, nullable=True)
        
        fake_name = masker.mask("John", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 2
        assert fake_name.isalpha()
    
    def test_tier_three_chars(self):
        """Test 3-character column (initial tier)."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=3, nullable=True)
        
        fake_name = masker.mask("John Doe", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 3
        assert fake_name.isalpha()
    
    def test_column_too_short(self):
        """Test error on column length < MIN_LENGTH (2)."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=1, nullable=True)
        
        with pytest.raises(MaskingError) as exc_info:
            masker.mask("John", col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_LENGTH_EXCEEDED
        assert "too short" in str(exc_info.value.message).lower()
    
    def test_length_boundary_20(self):
        """Test boundary between full and first+last tiers (20 chars)."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
        
        fake_name = masker.mask("John Doe", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 20
    
    def test_length_boundary_10(self):
        """Test boundary between first+last and first-only tiers (10 chars)."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=10, nullable=True)
        
        fake_name = masker.mask("John", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 10
    
    def test_length_boundary_4(self):
        """Test boundary between first-only and initial tiers (4 chars)."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=4, nullable=True)
        
        fake_name = masker.mask("John", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 4


class TestNameMaskerNameStructure:
    """Test detection and preservation of name structure."""
    
    def test_detect_simple_name(self):
        """Test detection of simple first or last name."""
        masker = NameMasker()
        structure = masker._detect_name_type("John")
        
        assert structure["has_prefix"] is False
        assert structure["has_suffix"] is False
        assert structure["is_hyphenated"] is False
        assert structure["word_count"] == 1
    
    def test_detect_full_name(self):
        """Test detection of full name (first + last)."""
        masker = NameMasker()
        structure = masker._detect_name_type("John Smith")
        
        assert structure["has_prefix"] is False
        assert structure["has_suffix"] is False
        assert structure["is_hyphenated"] is False
        assert structure["word_count"] == 2
    
    def test_detect_prefix_dr(self):
        """Test detection of 'Dr.' prefix."""
        masker = NameMasker()
        structure = masker._detect_name_type("Dr. John Smith")
        
        assert structure["has_prefix"] is True
        assert structure["has_suffix"] is False
        assert structure["word_count"] == 3
    
    def test_detect_prefix_mr(self):
        """Test detection of 'Mr.' prefix."""
        masker = NameMasker()
        structure = masker._detect_name_type("Mr. Robert Jones")
        
        assert structure["has_prefix"] is True
        assert structure["has_suffix"] is False
    
    def test_detect_prefix_mrs(self):
        """Test detection of 'Mrs.' prefix."""
        masker = NameMasker()
        structure = masker._detect_name_type("Mrs. Mary Johnson")
        
        assert structure["has_prefix"] is True
        assert structure["has_suffix"] is False
    
    def test_detect_suffix_jr(self):
        """Test detection of 'Jr.' suffix."""
        masker = NameMasker()
        structure = masker._detect_name_type("John Smith Jr.")
        
        assert structure["has_prefix"] is False
        assert structure["has_suffix"] is True
        assert structure["word_count"] == 3
    
    def test_detect_suffix_sr(self):
        """Test detection of 'Sr.' suffix."""
        masker = NameMasker()
        structure = masker._detect_name_type("Robert Johnson Sr.")
        
        assert structure["has_prefix"] is False
        assert structure["has_suffix"] is True
    
    def test_detect_suffix_roman_numeral(self):
        """Test detection of roman numeral suffix (II, III)."""
        masker = NameMasker()
        structure = masker._detect_name_type("William Smith III")
        
        assert structure["has_prefix"] is False
        assert structure["has_suffix"] is True
    
    def test_detect_prefix_and_suffix(self):
        """Test detection of both prefix and suffix."""
        masker = NameMasker()
        structure = masker._detect_name_type("Dr. John Smith Jr.")
        
        assert structure["has_prefix"] is True
        assert structure["has_suffix"] is True
        assert structure["word_count"] == 4
    
    def test_detect_hyphenated_first_name(self):
        """Test detection of hyphenated first name."""
        masker = NameMasker()
        structure = masker._detect_name_type("Mary-Jane")
        
        assert structure["has_prefix"] is False
        assert structure["has_suffix"] is False
        assert structure["is_hyphenated"] is True
        assert structure["word_count"] == 1
    
    def test_detect_hyphenated_last_name(self):
        """Test detection of hyphenated last name."""
        masker = NameMasker()
        structure = masker._detect_name_type("John Smith-Jones")
        
        assert structure["has_prefix"] is False
        assert structure["has_suffix"] is False
        assert structure["is_hyphenated"] is True
        assert structure["word_count"] == 2
    
    def test_format_validation_valid_simple(self):
        """Test format validation for simple name."""
        masker = NameMasker()
        assert masker._validate_name_format("John") is True
    
    def test_format_validation_valid_full(self):
        """Test format validation for full name."""
        masker = NameMasker()
        assert masker._validate_name_format("John Smith") is True
    
    def test_format_validation_valid_hyphenated(self):
        """Test format validation for hyphenated name."""
        masker = NameMasker()
        assert masker._validate_name_format("Mary-Jane") is True
    
    def test_format_validation_valid_apostrophe(self):
        """Test format validation for name with apostrophe."""
        masker = NameMasker()
        assert masker._validate_name_format("O'Brien") is True
    
    def test_format_validation_valid_unicode(self):
        """Test format validation for Unicode name."""
        masker = NameMasker()
        assert masker._validate_name_format("José García") is True
    
    def test_format_validation_invalid_numbers(self):
        """Test format validation rejects numbers."""
        masker = NameMasker()
        assert masker._validate_name_format("123 Main St") is False
    
    def test_format_validation_invalid_empty(self):
        """Test format validation rejects empty string."""
        masker = NameMasker()
        assert masker._validate_name_format("") is False
    
    def test_format_validation_invalid_whitespace_only(self):
        """Test format validation rejects whitespace-only string."""
        masker = NameMasker()
        assert masker._validate_name_format("   ") is False
    
    def test_format_validation_excessive_whitespace(self):
        """Test format validation rejects excessive whitespace."""
        masker = NameMasker()
        assert masker._validate_name_format("John   Smith") is False


class TestNameMaskerDataTypes:
    """Test handling of different SQL Server data types."""
    
    def test_varchar_basic(self):
        """Test VARCHAR column masking."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        fake_name = masker.mask("John Doe", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 50
        # VARCHAR should produce ASCII-safe names
        assert fake_name.isascii()
    
    def test_nvarchar_basic(self):
        """Test NVARCHAR column masking."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="NVARCHAR", max_length=50, nullable=True)
        
        fake_name = masker.mask("José García", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 50
    
    def test_text_type(self):
        """Test TEXT column masking."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="TEXT", max_length=None, nullable=True)
        
        fake_name = masker.mask("John Doe", col)
        
        assert fake_name is not None
        # TEXT has no explicit length limit (uses default max)
    
    def test_ntext_type(self):
        """Test NTEXT column masking."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="NTEXT", max_length=None, nullable=True)
        
        fake_name = masker.mask("José García", col)
        
        assert fake_name is not None
    
    def test_char_fixed_length(self):
        """Test CHAR fixed-length column (should be padded)."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(
            data_type="CHAR",
            max_length=20,
            nullable=True,
            is_fixed_length=True
        )
        
        fake_name = masker.mask("John", col)
        
        assert fake_name is not None
        # CHAR columns should be padded to fixed length
        assert len(fake_name) == 20
    
    def test_nchar_fixed_length(self):
        """Test NCHAR fixed-length column (should be padded)."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(
            data_type="NCHAR",
            max_length=20,
            nullable=True,
            is_fixed_length=True
        )
        
        fake_name = masker.mask("John", col)
        
        assert fake_name is not None
        assert len(fake_name) == 20


class TestNameMaskerNullHandling:
    """Test NULL value handling strategies."""
    
    def test_preserve_null(self):
        """Test PRESERVE strategy returns None for NULL input."""
        masker = NameMasker(null_strategy=MaskingStrategy.PRESERVE)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        result = masker.mask(None, col)
        
        assert result is None
    
    def test_mask_null(self):
        """Test MASK strategy generates fake name for NULL input."""
        masker = NameMasker(null_strategy=MaskingStrategy.MASK)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        result = masker.mask(None, col)
        
        assert result is not None
        assert isinstance(result, str)
        assert len(result) <= 50
    
    def test_null_on_not_null_column_preserve(self):
        """Test NULL input on NOT NULL column with PRESERVE strategy raises error."""
        masker = NameMasker(null_strategy=MaskingStrategy.PRESERVE)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=False)
        
        with pytest.raises(MaskingError) as exc_info:
            masker.mask(None, col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_NULL_CONSTRAINT_VIOLATION
    
    def test_null_on_not_null_column_mask(self):
        """Test NULL input on NOT NULL column with MASK strategy generates value."""
        masker = NameMasker(null_strategy=MaskingStrategy.MASK)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=False)
        
        result = masker.mask(None, col)
        
        assert result is not None
        assert isinstance(result, str)


class TestNameMaskerValidation:
    """Test validation and error handling."""
    
    def test_invalid_format_logs_warning(self):
        """Test that invalid format logs warning but still masks."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        # This should log warning but still return a masked value
        fake_name = masker.mask("123 Main St", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 50
    
    def test_whitespace_trimmed(self):
        """Test that leading/trailing whitespace is trimmed."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        name1 = masker.mask("  John Doe  ", col)
        name2 = masker.mask("John Doe", col)
        
        # Trimmed input should produce same result
        assert name1 == name2
    
    def test_get_name_tier_full(self):
        """Test tier detection for full tier (20+)."""
        masker = NameMasker()
        assert masker._get_name_tier(50) == "full"
        assert masker._get_name_tier(20) == "full"
    
    def test_get_name_tier_first_last(self):
        """Test tier detection for first+last tier (10-19)."""
        masker = NameMasker()
        assert masker._get_name_tier(19) == "first_last"
        assert masker._get_name_tier(10) == "first_last"
    
    def test_get_name_tier_first_only(self):
        """Test tier detection for first-only tier (4-9)."""
        masker = NameMasker()
        assert masker._get_name_tier(9) == "first_only"
        assert masker._get_name_tier(4) == "first_only"
    
    def test_get_name_tier_initial(self):
        """Test tier detection for initial tier (2-3)."""
        masker = NameMasker()
        assert masker._get_name_tier(3) == "initial"
        assert masker._get_name_tier(2) == "initial"
    
    def test_get_name_tier_error(self):
        """Test tier detection for error case (<2)."""
        masker = NameMasker()
        assert masker._get_name_tier(1) == "error"
        assert masker._get_name_tier(0) == "error"


class TestNameMaskerEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_unicode_spanish_name(self):
        """Test masking of Spanish name with accents."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="NVARCHAR", max_length=50, nullable=True)
        
        fake_name = masker.mask("José García", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 50
    
    def test_unicode_french_name(self):
        """Test masking of French name with accents."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="NVARCHAR", max_length=50, nullable=True)
        
        fake_name = masker.mask("François Côté", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 50
    
    def test_unicode_chinese_name(self):
        """Test masking of Chinese name."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="NVARCHAR", max_length=50, nullable=True)
        
        fake_name = masker.mask("李明", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 50
    
    def test_single_letter_name(self):
        """Test masking of single-letter name (edge case)."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=2, nullable=True)
        
        # Should still mask even though format might be unusual
        fake_name = masker.mask("X", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 2
    
    def test_very_long_name(self):
        """Test masking of very long name."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=200, nullable=True)
        
        long_name = "Dr. Alexander Bartholomew Christopher Davidson III"
        fake_name = masker.mask(long_name, col)
        
        assert fake_name is not None
        assert len(fake_name) <= 200
    
    def test_name_with_multiple_spaces(self):
        """Test masking handles names with extra spaces."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        # Extra spaces should be trimmed during validation
        name1 = masker.mask("John  Smith", col)
        name2 = masker.mask("John Smith", col)
        
        # Should produce same result after trimming
        assert name1 == name2
    
    def test_name_with_apostrophe(self):
        """Test masking of name with apostrophe (O'Brien)."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        fake_name = masker.mask("O'Brien", col)
        
        assert fake_name is not None
        assert len(fake_name) <= 50
    
    def test_deterministic_across_tiers(self):
        """Test that same name produces consistent results even with different lengths."""
        masker = NameMasker(seed=42)
        
        col_long = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        col_short = ColumnInfo(data_type="VARCHAR", max_length=8, nullable=True)
        
        name_long = masker.mask("John Doe", col_long)
        name_short = masker.mask("John Doe", col_short)
        
        # Both should be deterministic (same seed from same input)
        # but results differ due to length constraints
        assert name_long is not None
        assert name_short is not None
        
        # Verify results are consistent with their tier
        assert len(name_long) <= 50
        assert len(name_short) <= 8
    
    def test_faker_integration(self):
        """Test that Faker library is properly integrated."""
        masker = NameMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        fake_name = masker.mask("John Doe", col)
        
        # Should produce a realistic-looking name
        assert fake_name is not None
        assert isinstance(fake_name, str)
        assert len(fake_name) > 0
