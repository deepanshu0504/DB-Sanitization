"""
Unit tests for BaseMasker abstract class and supporting components.

These tests validate:
- ColumnInfo dataclass validation
- MaskingStrategy enum
- BaseMasker abstract class methods
- Deterministic hashing and seed generation
- Length validation with Unicode support
- Type validation
- NULL handling strategies
- Error handling

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from unittest.mock import Mock, patch
from typing import Any

from src.masking.base_masker import BaseMasker, ColumnInfo, MaskingStrategy
from src.exceptions import MaskingError
from src.error_codes import ErrorCodes


# ==================== Test Fixtures ====================


class SimpleMasker(BaseMasker):
    """
    Concrete implementation of BaseMasker for testing.
    
    This simple masker just appends "_masked" to string values.
    """
    
    def mask(self, value: Any, column_info: ColumnInfo) -> Any:
        # Handle NULL
        if value is None:
            return self._handle_null(value, column_info)
        
        # Generate deterministic seed
        seed = self._get_deterministic_seed(value)
        
        # Create fake value
        fake_value = f"{value}_masked_{seed % 1000}"
        
        # Validate length
        fake_value = self._validate_length(fake_value, column_info)
        
        # Validate type
        self._validate_data_type(fake_value, column_info)
        
        return fake_value


@pytest.fixture
def simple_masker():
    """Create a simple masker for testing."""
    return SimpleMasker(seed=42)


@pytest.fixture
def varchar_column():
    """Create a VARCHAR(50) column info."""
    return ColumnInfo(
        data_type="VARCHAR",
        max_length=50,
        nullable=True,
        is_unicode=False,
        is_fixed_length=False
    )


@pytest.fixture
def nvarchar_column():
    """Create an NVARCHAR(100) column info."""
    return ColumnInfo(
        data_type="NVARCHAR",
        max_length=100,
        nullable=False,
        is_unicode=True,
        is_fixed_length=False
    )


@pytest.fixture
def char_column():
    """Create a CHAR(10) column info."""
    return ColumnInfo(
        data_type="CHAR",
        max_length=10,
        nullable=True,
        is_unicode=False,
        is_fixed_length=True
    )


# ==================== ColumnInfo Tests ====================


class TestColumnInfo:
    """Tests for ColumnInfo dataclass."""
    
    def test_create_column_info_minimal(self):
        """Test creating ColumnInfo with minimal required fields."""
        col_info = ColumnInfo(
            data_type="VARCHAR",
            max_length=255,
            nullable=True
        )
        
        assert col_info.data_type == "VARCHAR"
        assert col_info.max_length == 255
        assert col_info.nullable is True
        assert col_info.is_unicode is False
        assert col_info.is_fixed_length is False
    
    def test_create_column_info_full(self):
        """Test creating ColumnInfo with all fields."""
        col_info = ColumnInfo(
            data_type="NVARCHAR",
            max_length=100,
            nullable=False,
            precision=18,
            scale=2,
            is_max_type=False,
            is_unicode=True,
            is_fixed_length=False
        )
        
        assert col_info.data_type == "NVARCHAR"
        assert col_info.max_length == 100
        assert col_info.nullable is False
        assert col_info.precision == 18
        assert col_info.scale == 2
    
    def test_data_type_normalized_to_uppercase(self):
        """Test that data_type is normalized to uppercase."""
        col_info = ColumnInfo(
            data_type="varchar",
            max_length=50,
            nullable=True
        )
        
        assert col_info.data_type == "VARCHAR"
    
    def test_unicode_flag_set_for_nvarchar(self):
        """Test that is_unicode is set automatically for NVARCHAR."""
        col_info = ColumnInfo(
            data_type="NVARCHAR",
            max_length=100,
            nullable=True
        )
        
        assert col_info.is_unicode is True
    
    def test_unicode_flag_set_for_nchar(self):
        """Test that is_unicode is set automatically for NCHAR."""
        col_info = ColumnInfo(
            data_type="NCHAR",
            max_length=10,
            nullable=True
        )
        
        assert col_info.is_unicode is True
    
    def test_fixed_length_flag_set_for_char(self):
        """Test that is_fixed_length is set automatically for CHAR."""
        col_info = ColumnInfo(
            data_type="CHAR",
            max_length=10,
            nullable=True
        )
        
        assert col_info.is_fixed_length is True
    
    def test_fixed_length_flag_set_for_nchar(self):
        """Test that is_fixed_length is set automatically for NCHAR."""
        col_info = ColumnInfo(
            data_type="NCHAR",
            max_length=10,
            nullable=True
        )
        
        assert col_info.is_fixed_length is True
        assert col_info.is_unicode is True
    
    def test_max_length_validation_fails_for_zero(self):
        """Test that max_length <= 0 raises ValueError for string types."""
        with pytest.raises(ValueError, match="max_length must be positive"):
            ColumnInfo(
                data_type="VARCHAR",
                max_length=0,
                nullable=True
            )
    
    def test_max_length_validation_fails_for_negative(self):
        """Test that negative max_length raises ValueError."""
        with pytest.raises(ValueError, match="max_length must be positive"):
            ColumnInfo(
                data_type="VARCHAR",
                max_length=-1,
                nullable=True,
                is_max_type=False
            )
    
    def test_max_type_allows_negative_max_length(self):
        """Test that MAX types can have -1 max_length."""
        col_info = ColumnInfo(
            data_type="VARCHAR",
            max_length=-1,
            nullable=True,
            is_max_type=True
        )
        
        assert col_info.effective_max_length == 10000  # Default for MAX types
    
    def test_effective_max_length_for_normal_column(self):
        """Test effective_max_length returns actual length for normal columns."""
        col_info = ColumnInfo(
            data_type="VARCHAR",
            max_length=50,
            nullable=True
        )
        
        assert col_info.effective_max_length == 50
    
    def test_effective_max_length_for_max_type(self):
        """Test effective_max_length returns reasonable default for MAX types."""
        col_info = ColumnInfo(
            data_type="NVARCHAR",
            max_length=-1,
            nullable=True,
            is_max_type=True
        )
        
        assert col_info.effective_max_length == 10000


# ==================== MaskingStrategy Tests ====================


class TestMaskingStrategy:
    """Tests for MaskingStrategy enum."""
    
    def test_preserve_strategy_exists(self):
        """Test PRESERVE strategy exists."""
        assert MaskingStrategy.PRESERVE.value == "preserve"
    
    def test_mask_strategy_exists(self):
        """Test MASK strategy exists."""
        assert MaskingStrategy.MASK.value == "mask"
    
    def test_randomize_strategy_exists(self):
        """Test RANDOMIZE strategy exists."""
        assert MaskingStrategy.RANDOMIZE.value == "randomize"
    
    def test_strategy_comparison(self):
        """Test strategy comparisons."""
        assert MaskingStrategy.PRESERVE != MaskingStrategy.MASK
        assert MaskingStrategy.PRESERVE == MaskingStrategy.PRESERVE


# ==================== BaseMasker Initialization Tests ====================


class TestBaseMaskerInitialization:
    """Tests for BaseMasker initialization."""
    
    def test_cannot_instantiate_abstract_class(self):
        """Test that BaseMasker cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseMasker()
    
    def test_concrete_masker_initialization_defaults(self, simple_masker):
        """Test concrete masker initializes with default values."""
        assert simple_masker.seed == 42
        assert simple_masker.null_strategy == MaskingStrategy.PRESERVE
        assert simple_masker.logger is not None
    
    def test_concrete_masker_with_custom_seed(self):
        """Test concrete masker with custom seed."""
        masker = SimpleMasker(seed=12345)
        
        assert masker.seed == 12345
    
    def test_concrete_masker_with_custom_null_strategy(self):
        """Test concrete masker with custom NULL strategy."""
        masker = SimpleMasker(
            seed=42,
            null_strategy=MaskingStrategy.MASK
        )
        
        assert masker.null_strategy == MaskingStrategy.MASK
    
    def test_concrete_masker_with_custom_logger(self):
        """Test concrete masker with custom logger."""
        custom_logger = Mock()
        masker = SimpleMasker(seed=42, logger=custom_logger)
        
        assert masker.logger is custom_logger


# ==================== Deterministic Hashing Tests ====================


class TestDeterministicHashing:
    """Tests for deterministic seed generation."""
    
    def test_same_value_produces_same_seed(self, simple_masker):
        """Test that same value always produces same seed."""
        seed1 = simple_masker._get_deterministic_seed("test@example.com")
        seed2 = simple_masker._get_deterministic_seed("test@example.com")
        
        assert seed1 == seed2
    
    def test_different_values_produce_different_seeds(self, simple_masker):
        """Test that different values produce different seeds."""
        seed1 = simple_masker._get_deterministic_seed("test1@example.com")
        seed2 = simple_masker._get_deterministic_seed("test2@example.com")
        
        assert seed1 != seed2
    
    def test_seed_is_integer(self, simple_masker):
        """Test that seed is an integer."""
        seed = simple_masker._get_deterministic_seed("test")
        
        assert isinstance(seed, int)
    
    def test_seed_in_valid_range(self, simple_masker):
        """Test that seed is in range [0, 2^32-1]."""
        seed = simple_masker._get_deterministic_seed("test")
        
        assert 0 <= seed < 2**32
    
    def test_very_long_value_hashed correctly(self, simple_masker):
        """Test that very long values (>10KB) are hashed correctly."""
        long_value = "a" * 20000  # 20KB string
        seed = simple_masker._get_deterministic_seed(long_value)
        
        assert isinstance(seed, int)
        assert 0 <= seed < 2**32
    
    def test_empty_string_produces_seed(self, simple_masker):
        """Test that empty string produces valid seed."""
        seed = simple_masker._get_deterministic_seed("")
        
        assert isinstance(seed, int)
    
    def test_unicode_value_produces_seed(self, simple_masker):
        """Test that Unicode values produce valid seeds."""
        seed = simple_masker._get_deterministic_seed("测试@example.com")
        
        assert isinstance(seed, int)
    
    def test_different_global_seeds_produce_different_results(self):
        """Test that different global seeds produce different results."""
        masker1 = SimpleMasker(seed=1)
        masker2 = SimpleMasker(seed=2)
        
        seed1 = masker1._get_deterministic_seed("test")
        seed2 = masker2._get_deterministic_seed("test")
        
        assert seed1 != seed2


# ==================== Hash Value Tests ====================


class TestHashValue:
    """Tests for _hash_value method."""
    
    def test_hash_value_produces_hex_string(self, simple_masker):
        """Test that _hash_value produces hexadecimal string."""
        hash_val = simple_masker._hash_value("test")
        
        assert isinstance(hash_val, str)
        assert len(hash_val) == 64  # SHA256 hex digest is 64 characters
        assert all(c in "0123456789abcdef" for c in hash_val)
    
    def test_same_value_produces_same_hash(self, simple_masker):
        """Test that same value produces same hash."""
        hash1 = simple_masker._hash_value("test@example.com")
        hash2 = simple_masker._hash_value("test@example.com")
        
        assert hash1 == hash2
    
    def test_different_values_produce_different_hashes(self, simple_masker):
        """Test that different values produce different hashes."""
        hash1 = simple_masker._hash_value("test1")
        hash2 = simple_masker._hash_value("test2")
        
        assert hash1 != hash2


# ==================== Length Validation Tests ====================


class TestLengthValidation:
    """Tests for length validation."""
    
    def test_value_within_length_not_truncated(self, simple_masker, varchar_column):
        """Test that values within length are not truncated."""
        value = "short"
        result = simple_masker._validate_length(value, varchar_column)
        
        assert result == "short"
    
    def test_value_exceeding_length_truncated(self, simple_masker):
        """Test that values exceeding length are truncated."""
        col_info = ColumnInfo(data_type="VARCHAR", max_length=10, nullable=True)
        value = "this_is_a_very_long_string"
        
        result = simple_masker._validate_length(value, col_info)
        
        assert len(result.encode('utf-8')) <= 10
    
    def test_nvarchar_truncates_by_characters(self, simple_masker, nvarchar_column):
        """Test that NVARCHAR truncates by character count."""
        value = "a" * 150
        result = simple_masker._validate_length(value, nvarchar_column)
        
        assert len(result) == 100  # Character count
    
    def test_varchar_truncates_by bytes(self, simple_masker):
        """Test that VARCHAR truncates by byte count."""
        col_info = ColumnInfo(data_type="VARCHAR", max_length=10, nullable=True)
        value = "test" * 5  # 20 bytes
        
        result = simple_masker._validate_length(value, col_info)
        
        assert len(result.encode('utf-8')) <= 10
    
    def test_unicode_character_boundary_respected(self, simple_masker):
        """Test that Unicode character boundaries are respected."""
        col_info = ColumnInfo(data_type="VARCHAR", max_length=5, nullable=True)
        value = "测试"  # 6 bytes in UTF-8 (3 bytes each)
        
        result = simple_masker._validate_length(value, col_info)
        
        # Should truncate to fit within 5 bytes without breaking UTF-8
        assert len(result.encode('utf-8')) <= 5
        # Should be valid UTF-8
        result.encode('utf-8').decode('utf-8')
    
    def test_char_column_padded_with_spaces(self, simple_masker, char_column):
        """Test that CHAR columns are padded with spaces."""
        value = "test"
        result = simple_masker._validate_length(value, char_column)
        
        assert len(result.encode('utf-8')) == 10  # Padded to fixed length
        assert result.startswith("test")
    
    def test_max_type_uses_reasonable_default(self, simple_masker):
        """Test that MAX types use reasonable default length."""
        col_info = ColumnInfo(
            data_type="VARCHAR",
            max_length=-1,
            nullable=True,
            is_max_type=True
        )
        value = "a" * 15000
        
        result = simple_masker._validate_length(value, col_info)
        
        # Should not truncate up to 10000 characters
        assert len(result.encode('utf-8')) <= 10000
    
    def test_non_string_value_passed_through(self, simple_masker, varchar_column):
        """Test that non-string values are passed through unchanged."""
        result = simple_masker._validate_length(123, varchar_column)
        
        assert result == 123


# ==================== Type Validation Tests ====================


class TestDataTypeValidation:
    """Tests for data type validation."""
    
    def test_string_validates_for_varchar(self, simple_masker, varchar_column):
        """Test that string values validate for VARCHAR columns."""
        # Should not raise
        simple_masker._validate_data_type("test", varchar_column)
    
    def test_non_string_fails_for_varchar(self, simple_masker, varchar_column):
        """Test that non-string values fail for VARCHAR columns."""
        with pytest.raises(MaskingError) as exc_info:
            simple_masker._validate_data_type(123, varchar_column)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_TYPE_MISMATCH
    
    def test_integer_validates_for_int_column(self, simple_masker):
        """Test that integer values validate for INT columns."""
        col_info = ColumnInfo(data_type="INT", max_length=4, nullable=True)
        
        # Should not raise
        simple_masker._validate_data_type(123, col_info)
    
    def test_non_integer_fails_for_int_column(self, simple_masker):
        """Test that non-integer values fail for INT columns."""
        col_info = ColumnInfo(data_type="INT", max_length=4, nullable=True)
        
        with pytest.raises(MaskingError) as exc_info:
            simple_masker._validate_data_type("123", col_info)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_TYPE_MISMATCH
    
    def test_null_value_always_validates(self, simple_masker, varchar_column):
        """Test that NULL values always validate regardless of type."""
        # Should not raise for any type
        simple_masker._validate_data_type(None, varchar_column)


# ==================== NULL Handling Tests ====================


class TestNullHandling:
    """Tests for NULL value handling."""
    
    def test_non_null_value_returned_unchanged(self, simple_masker, varchar_column):
        """Test that non-NULL values are returned unchanged."""
        result = simple_masker._handle_null("test", varchar_column)
        
        assert result == "test"
    
    def test_null_preserved_for_nullable_column(self, simple_masker, varchar_column):
        """Test that NULL is preserved for nullable columns with PRESERVE strategy."""
        result = simple_masker._handle_null(None, varchar_column)
        
        assert result is None
    
    def test_null_raises_error_for_not_null_column(self, simple_masker, nvarchar_column):
        """Test that NULL raises error for NOT NULL columns."""
        with pytest.raises(MaskingError) as exc_info:
            simple_masker._handle_null(None, nvarchar_column)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_NULL_CONSTRAINT_VIOLATION
        assert "NOT NULL" in str(exc_info.value)
    
    def test_mask_strategy_with_null(self, varchar_column):
        """Test MASK strategy with NULL value."""
        masker = SimpleMasker(seed=42, null_strategy=MaskingStrategy.MASK)
        result = masker._handle_null(None, varchar_column)
        
        # MASK strategy returns None to signal subclass should mask
        assert result is None


# ==================== Integration Tests ====================


class TestBaseMaskerIntegration:
    """Integration tests for complete masking workflow."""
    
    def test_complete_masking_workflow(self, simple_masker, varchar_column):
        """Test complete masking workflow from input to output."""
        result = simple_masker.mask("test@example.com", varchar_column)
        
        assert isinstance(result, str)
        assert "masked" in result
        assert len(result.encode('utf-8')) <= 50
    
    def test_determinism_across_multiple_calls(self, simple_masker, varchar_column):
        """Test that masking is deterministic across multiple calls."""
        value = "test@example.com"
        
        result1 = simple_masker.mask(value, varchar_column)
        result2 = simple_masker.mask(value, varchar_column)
        
        assert result1 == result2
    
    def test_different_values_produce_different_outputs(self, simple_masker, varchar_column):
        """Test that different inputs produce different outputs."""
        result1 = simple_masker.mask("test1@example.com", varchar_column)
        result2 = simple_masker.mask("test2@example.com", varchar_column)
        
        assert result1 != result2
    
    def test_null_handling_in_mask_workflow(self, simple_masker, varchar_column):
        """Test NULL handling in complete mask workflow."""
        result = simple_masker.mask(None, varchar_column)
        
        assert result is None  # PRESERVE strategy
    
    def test_masking_with_short_column(self, simple_masker):
        """Test masking with very short column length."""
        col_info = ColumnInfo(data_type="VARCHAR", max_length=5, nullable=True)
        result = simple_masker.mask("test", col_info)
        
        assert len(result.encode('utf-8')) <= 5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=src/masking", "--cov-report=term-missing"])
