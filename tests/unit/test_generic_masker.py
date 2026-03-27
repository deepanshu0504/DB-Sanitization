"""
Unit tests for GenericMasker class.

Tests cover:
- Basic masking functionality (deterministic mapping)
- Character class support (alphanumeric, alpha, numeric)
- Length preservation and truncation
- NULL handling strategies (PRESERVE, MASK)
- Data type validation (VARCHAR, NVARCHAR, TEXT, CHAR)
- Edge cases (empty strings, single char, very long strings)
- Error handling (invalid character class, column too short)

Test Organization:
- TestGenericMaskerBasic: Core deterministic mapping, seed behavior
- TestGenericMaskerCharacterClasses: Alphanumeric, alpha, numeric outputs
- TestGenericMaskerLengthPreservation: Length matching and truncation
- TestGenericMaskerDataTypes: VARCHAR vs NVARCHAR, fixed vs variable length
- TestGenericMaskerNullHandling: NULL strategies and NOT NULL columns
- TestGenericMaskerValidation: Character class validation, error handling
- TestGenericMaskerEdgeCases: Whitespace, boundaries, very long strings

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from unittest.mock import Mock

from src.masking import GenericMasker
from src.masking.base_masker import ColumnInfo, MaskingStrategy
from src.exceptions import MaskingError
from src.error_codes import ErrorCodes


class TestGenericMaskerBasic:
    """Test basic generic masking functionality."""
    
    def test_initialization_default(self):
        """Test default initialization."""
        masker = GenericMasker()
        assert masker.seed == 42
        assert masker.null_strategy == MaskingStrategy.PRESERVE
        assert masker.character_class == "alphanumeric"
        assert masker.logger is not None
    
    def test_initialization_custom_seed(self):
        """Test initialization with custom seed."""
        masker = GenericMasker(seed=12345)
        assert masker.seed == 12345
    
    def test_initialization_custom_null_strategy(self):
        """Test initialization with custom NULL strategy."""
        masker = GenericMasker(null_strategy=MaskingStrategy.MASK)
        assert masker.null_strategy == MaskingStrategy.MASK
    
    def test_initialization_custom_character_class(self):
        """Test initialization with custom character class."""
        masker = GenericMasker(character_class="alpha")
        assert masker.character_class == "alpha"
    
    def test_deterministic_masking(self):
        """Test that same input produces same output."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
        
        text1 = masker.mask("CustomData123", col)
        text2 = masker.mask("CustomData123", col)
        
        assert text1 == text2
        assert text1 is not None
        assert len(text1) <= 20
    
    def test_different_inputs_different_outputs(self):
        """Test that different inputs produce different outputs."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
        
        text1 = masker.mask("CustomData123", col)
        text2 = masker.mask("OtherData456", col)
        
        assert text1 != text2
    
    def test_seed_independence(self):
        """Test that different seeds produce different outputs for same input."""
        col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
        
        masker1 = GenericMasker(seed=42)
        masker2 = GenericMasker(seed=999)
        
        text1 = masker1.mask("CustomData", col)
        text2 = masker2.mask("CustomData", col)
        
        # Different seeds should produce different results
        assert text1 != text2


class TestGenericMaskerCharacterClasses:
    """Test character class support."""
    
    def test_alphanumeric_output(self):
        """Test alphanumeric character class produces letters and digits."""
        masker = GenericMasker(seed=42, character_class="alphanumeric")
        col = ColumnInfo(data_type="VARCHAR", max_length=100, nullable=True)
        
        fake_text = masker.mask("CustomData" * 10, col)  # Long input
        
        assert fake_text is not None
        assert fake_text.isalnum()  # Only letters and digits
    
    def test_alpha_output(self):
        """Test alpha character class produces only letters."""
        masker = GenericMasker(seed=42, character_class="alpha")
        col = ColumnInfo(data_type="VARCHAR", max_length=100, nullable=True)
        
        fake_text = masker.mask("CustomData123" * 10, col)  # Long input
        
        assert fake_text is not None
        assert fake_text.isalpha()  # Only letters, no digits
    
    def test_numeric_output(self):
        """Test numeric character class produces only digits."""
        masker = GenericMasker(seed=42, character_class="numeric")
        col = ColumnInfo(data_type="VARCHAR", max_length=100, nullable=True)
        
        fake_text = masker.mask("CustomData123" * 10, col)  # Long input
        
        assert fake_text is not None
        assert fake_text.isdigit()  # Only digits
    
    def test_character_class_alphanumeric_set(self):
        """Test alphanumeric character set is correct."""
        masker = GenericMasker(character_class="alphanumeric")
        chars = masker._get_character_set()
        
        assert len(chars) == 62  # 26 + 26 + 10
        assert 'a' in chars
        assert 'Z' in chars
        assert '0' in chars
    
    def test_character_class_alpha_set(self):
        """Test alpha character set is correct."""
        masker = GenericMasker(character_class="alpha")
        chars = masker._get_character_set()
        
        assert len(chars) == 52  # 26 + 26
        assert 'a' in chars
        assert 'Z' in chars
        assert '0' not in chars
    
    def test_character_class_numeric_set(self):
        """Test numeric character set is correct."""
        masker = GenericMasker(character_class="numeric")
        chars = masker._get_character_set()
        
        assert len(chars) == 10
        assert '0' in chars
        assert '9' in chars
        assert 'a' not in chars
    
    def test_invalid_character_class_raises_error(self):
        """Test initialization with invalid character class raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            GenericMasker(character_class="invalid")
        
        assert "Invalid character_class" in str(exc_info.value)
        assert "alphanumeric" in str(exc_info.value)
    
    def test_validate_character_class_valid(self):
        """Test character class validation for valid classes."""
        masker = GenericMasker()
        assert masker._validate_character_class("alphanumeric") is True
        assert masker._validate_character_class("alpha") is True
        assert masker._validate_character_class("numeric") is True
    
    def test_validate_character_class_invalid(self):
        """Test character class validation for invalid classes."""
        masker = GenericMasker()
        assert masker._validate_character_class("invalid") is False
        assert masker._validate_character_class("special") is False


class TestGenericMaskerLengthPreservation:
    """Test length preservation and truncation."""
    
    def test_exact_length_match(self):
        """Test output length matches input length."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=100, nullable=True)
        
        original = "CustomData"
        fake_text = masker.mask(original, col)
        
        assert len(fake_text) == len(original)
    
    def test_truncation_to_max_length(self):
        """Test truncation when input exceeds max_length."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=5, nullable=True)
        
        original = "VeryLongCustomData"
        fake_text = masker.mask(original, col)
        
        assert len(fake_text) == 5
    
    def test_single_character_column(self):
        """Test masking into 1-character column."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=1, nullable=True)
        
        fake_text = masker.mask("X", col)
        
        assert len(fake_text) == 1
        assert fake_text.isalnum()
    
    def test_very_long_string(self):
        """Test masking very long string (100+ chars)."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=200, nullable=True)
        
        original = "A" * 150
        fake_text = masker.mask(original, col)
        
        assert len(fake_text) == 150
    
    def test_short_string_long_column(self):
        """Test short string in long column preserves input length."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=100, nullable=True)
        
        original = "Short"
        fake_text = masker.mask(original, col)
        
        assert len(fake_text) == len(original)
    
    def test_length_boundary_1_char(self):
        """Test boundary at 1 character (minimum)."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=1, nullable=True)
        
        fake_text = masker.mask("A", col)
        
        assert len(fake_text) == 1
    
    def test_empty_string_after_trim(self):
        """Test whitespace-only string becomes empty after trim."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=10, nullable=True)
        
        # After trimming whitespace, becomes empty - should generate based on 0 length
        # This will raise MaskingError because target_length = 0
        with pytest.raises(MaskingError):
            masker.mask("   ", col)
    
    def test_column_too_short_zero(self):
        """Test error on column length < 1."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=0, nullable=True)
        
        with pytest.raises(MaskingError) as exc_info:
            masker.mask("Data", col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_LENGTH_EXCEEDED


class TestGenericMaskerDataTypes:
    """Test handling of different SQL Server data types."""
    
    def test_varchar_basic(self):
        """Test VARCHAR column masking."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        fake_text = masker.mask("CustomData", col)
        
        assert fake_text is not None
        assert len(fake_text) <= 50
        assert fake_text.isalnum()
    
    def test_nvarchar_basic(self):
        """Test NVARCHAR column masking."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="NVARCHAR", max_length=50, nullable=True)
        
        fake_text = masker.mask("CustomData", col)
        
        assert fake_text is not None
        assert len(fake_text) <= 50
    
    def test_char_fixed_length(self):
        """Test CHAR fixed-length column (should be padded)."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(
            data_type="CHAR",
            max_length=20,
            nullable=True,
            is_fixed_length=True
        )
        
        fake_text = masker.mask("Data", col)
        
        assert fake_text is not None
        # CHAR columns should be padded to fixed length
        assert len(fake_text) == 20
    
    def test_nchar_fixed_length(self):
        """Test NCHAR fixed-length column (should be padded)."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(
            data_type="NCHAR",
            max_length=20,
            nullable=True,
            is_fixed_length=True
        )
        
        fake_text = masker.mask("Data", col)
        
        assert fake_text is not None
        assert len(fake_text) == 20
    
    def test_text_type(self):
        """Test TEXT column masking."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="TEXT", max_length=None, nullable=True)
        
        fake_text = masker.mask("CustomData", col)
        
        assert fake_text is not None
        # TEXT has no explicit length limit (uses default max)
    
    def test_ntext_type(self):
        """Test NTEXT column masking."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="NTEXT", max_length=None, nullable=True)
        
        fake_text = masker.mask("CustomData", col)
        
        assert fake_text is not None


class TestGenericMaskerNullHandling:
    """Test NULL value handling strategies."""
    
    def test_preserve_null(self):
        """Test PRESERVE strategy returns None for NULL input."""
        masker = GenericMasker(null_strategy=MaskingStrategy.PRESERVE)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        result = masker.mask(None, col)
        
        assert result is None
    
    def test_mask_null(self):
        """Test MASK strategy generates fake string for NULL input."""
        masker = GenericMasker(null_strategy=MaskingStrategy.MASK)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
        
        result = masker.mask(None, col)
        
        assert result is not None
        assert isinstance(result, str)
        assert len(result) <= 50
    
    def test_null_on_not_null_column_preserve(self):
        """Test NULL input on NOT NULL column with PRESERVE strategy raises error."""
        masker = GenericMasker(null_strategy=MaskingStrategy.PRESERVE)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=False)
        
        with pytest.raises(MaskingError) as exc_info:
            masker.mask(None, col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_NULL_CONSTRAINT_VIOLATION
    
    def test_null_on_not_null_column_mask(self):
        """Test NULL input on NOT NULL column with MASK strategy generates value."""
        masker = GenericMasker(null_strategy=MaskingStrategy.MASK)
        col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=False)
        
        result = masker.mask(None, col)
        
        assert result is not None
        assert isinstance(result, str)


class TestGenericMaskerValidation:
    """Test validation and error handling."""
    
    def test_whitespace_trimmed(self):
        """Test that leading/trailing whitespace is trimmed."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
        
        text1 = masker.mask("  CustomData  ", col)
        text2 = masker.mask("CustomData", col)
        
        # Trimmed input should produce same result
        assert text1 == text2
    
    def test_deterministic_across_runs(self):
        """Test that same input produces consistent results."""
        col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
        
        # Multiple masker instances with same seed
        texts = []
        for _ in range(5):
            masker = GenericMasker(seed=42)
            text = masker.mask("CustomData", col)
            texts.append(text)
        
        # All should be identical
        assert len(set(texts)) == 1
    
    def test_different_character_classes_different_outputs(self):
        """Test that different character classes produce different outputs."""
        col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
        
        masker_alpha = GenericMasker(seed=42, character_class="alpha")
        masker_numeric = GenericMasker(seed=42, character_class="numeric")
        
        text_alpha = masker_alpha.mask("CustomData", col)
        text_numeric = masker_numeric.mask("CustomData", col)
        
        # Different character classes should produce different outputs
        assert text_alpha != text_numeric
        assert text_alpha.isalpha()
        assert text_numeric.isdigit()
    
    def test_generate_string_minimum_length(self):
        """Test _generate_string with minimum length (1)."""
        masker = GenericMasker(seed=42)
        
        result = masker._generate_string(12345, 1)
        
        assert len(result) == 1
        assert result.isalnum()
    
    def test_generate_string_zero_length_error(self):
        """Test _generate_string with zero length raises error."""
        masker = GenericMasker(seed=42)
        
        with pytest.raises(MaskingError) as exc_info:
            masker._generate_string(12345, 0)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_LENGTH_EXCEEDED


class TestGenericMaskerEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_unicode_column_support(self):
        """Test Unicode column (NVARCHAR) works correctly."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="NVARCHAR", max_length=50, nullable=True)
        
        fake_text = masker.mask("CustomData", col)
        
        assert fake_text is not None
        assert len(fake_text) <= 50
    
    def test_fixed_length_padding(self):
        """Test fixed-length column padding."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(
            data_type="CHAR",
            max_length=20,
            nullable=True,
            is_fixed_length=True
        )
        
        fake_text = masker.mask("Short", col)
        
        # Should be padded to 20 chars
        assert len(fake_text) == 20
    
    def test_very_short_value(self):
        """Test masking very short value (1 char)."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=1, nullable=True)
        
        fake_text = masker.mask("X", col)
        
        assert len(fake_text) == 1
    
    def test_very_long_value(self):
        """Test masking very long value (100+ chars)."""
        masker = GenericMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=150, nullable=True)
        
        original = "A" * 100
        fake_text = masker.mask(original, col)
        
        assert len(fake_text) == 100
    
    def test_determinism_with_different_lengths(self):
        """Test determinism works across different target lengths."""
        masker = GenericMasker(seed=42)
        
        col_short = ColumnInfo(data_type="VARCHAR", max_length=5, nullable=True)
        col_long = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
        
        # Same input, different column lengths
        text_short = masker.mask("CustomData", col_short)
        text_long = masker.mask("CustomData", col_long)
        
        # Both should be deterministic and different lengths
        assert len(text_short) == 5
        assert len(text_long) == 10  # Length of "CustomData"
        
        # Short should be prefix of long (deterministic character selection)
        assert text_long.startswith(text_short)
    
    def test_character_distribution(self):
        """Test that generated strings use characters from correct set."""
        masker_alpha = GenericMasker(seed=42, character_class="alpha")
        masker_numeric = GenericMasker(seed=42, character_class="numeric")
        
        col = ColumnInfo(data_type="VARCHAR", max_length=100, nullable=True)
        
        # Generate long strings to verify character distribution
        text_alpha = masker_alpha.mask("X" * 100, col)
        text_numeric = masker_numeric.mask("X" * 100, col)
        
        # Alpha should only have letters
        assert text_alpha.isalpha()
        
        # Numeric should only have digits
        assert text_numeric.isdigit()
