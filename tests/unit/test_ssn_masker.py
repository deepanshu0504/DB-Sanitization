"""
Unit tests for SSNMasker class.

Tests cover:
- Basic masking functionality (deterministic mapping)
- Format detection and handling (formatted vs plain)
- Valid SSN range compliance (001-665, 667-899)
- Invalid range exclusion (000, 666, 900-999)
- NULL handling strategies (PRESERVE, MASK)
- Data type validation (VARCHAR, NVARCHAR, TEXT, CHAR)
- Edge cases (whitespace, boundaries, format validation)
- Error handling (column too short, invalid types)

Test Organization:
- TestSSNMaskerBasic: Core deterministic mapping, seed behavior
- TestSSNMaskerFormats: Format detection, formatted vs plain outputs
- TestSSNMaskerValidRanges: Area/group/serial range validation
- TestSSNMaskerInvalidRanges: Exclusion of 000, 666, 900-999
- TestSSNMaskerDataTypes: VARCHAR vs NVARCHAR, fixed vs variable length
- TestSSNMaskerNullHandling: NULL strategies and NOT NULL columns
- TestSSNMaskerValidation: Format validation and error handling
- TestSSNMaskerEdgeCases: Whitespace, boundaries, determinism

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from unittest.mock import Mock

from src.masking import SSNMasker
from src.masking.base_masker import ColumnInfo, MaskingStrategy
from src.exceptions import MaskingError
from src.error_codes import ErrorCodes


class TestSSNMaskerBasic:
    """Test basic SSN masking functionality."""
    
    def test_initialization_default(self):
        """Test default initialization."""
        masker = SSNMasker()
        assert masker.seed == 42
        assert masker.null_strategy == MaskingStrategy.PRESERVE
        assert masker.logger is not None
    
    def test_initialization_custom_seed(self):
        """Test initialization with custom seed."""
        masker = SSNMasker(seed=12345)
        assert masker.seed == 12345
    
    def test_initialization_custom_null_strategy(self):
        """Test initialization with custom NULL strategy."""
        masker = SSNMasker(null_strategy=MaskingStrategy.MASK)
        assert masker.null_strategy == MaskingStrategy.MASK
    
    def test_deterministic_masking(self):
        """Test that same input produces same output."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        ssn1 = masker.mask("123-45-6789", col)
        ssn2 = masker.mask("123-45-6789", col)
        
        assert ssn1 == ssn2
        assert ssn1 is not None
        assert len(ssn1) <= 11
    
    def test_different_inputs_different_outputs(self):
        """Test that different inputs produce different outputs."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        ssn1 = masker.mask("123-45-6789", col)
        ssn2 = masker.mask("987-65-4321", col)
        
        assert ssn1 != ssn2
    
    def test_seed_independence(self):
        """Test that different seeds produce different outputs for same input."""
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        masker1 = SSNMasker(seed=42)
        masker2 = SSNMasker(seed=999)
        
        ssn1 = masker1.mask("123-45-6789", col)
        ssn2 = masker2.mask("123-45-6789", col)
        
        # Different seeds should produce different results
        assert ssn1 != ssn2


class TestSSNMaskerFormats:
    """Test SSN format detection and handling."""
    
    def test_formatted_input_formatted_output(self):
        """Test formatted input produces formatted output (11+ char column)."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        fake_ssn = masker.mask("123-45-6789", col)
        
        assert fake_ssn is not None
        assert len(fake_ssn) == 11
        assert fake_ssn[3] == '-'
        assert fake_ssn[6] == '-'
        assert fake_ssn.replace('-', '').isdigit()
    
    def test_plain_input_formatted_output(self):
        """Test plain input produces formatted output (11+ char column)."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        fake_ssn = masker.mask("123456789", col)
        
        assert fake_ssn is not None
        assert len(fake_ssn) == 11
        assert fake_ssn[3] == '-'
        assert fake_ssn[6] == '-'
    
    def test_formatted_input_plain_output(self):
        """Test formatted input produces plain output (9 char column)."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=9, nullable=True)
        
        fake_ssn = masker.mask("123-45-6789", col)
        
        assert fake_ssn is not None
        assert len(fake_ssn) == 9
        assert '-' not in fake_ssn
        assert fake_ssn.isdigit()
    
    def test_plain_input_plain_output(self):
        """Test plain input produces plain output (9 char column)."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=9, nullable=True)
        
        fake_ssn = masker.mask("123456789", col)
        
        assert fake_ssn is not None
        assert len(fake_ssn) == 9
        assert '-' not in fake_ssn
        assert fake_ssn.isdigit()
    
    def test_detect_formatted_format(self):
        """Test format detection for formatted SSN."""
        masker = SSNMasker()
        assert masker._detect_ssn_format("123-45-6789") == "formatted"
    
    def test_detect_plain_format(self):
        """Test format detection for plain SSN."""
        masker = SSNMasker()
        assert masker._detect_ssn_format("123456789") == "plain"
    
    def test_detect_unknown_format(self):
        """Test format detection for unknown format."""
        masker = SSNMasker()
        assert masker._detect_ssn_format("123 45 6789") == "unknown"
    
    def test_column_10_chars_uses_plain(self):
        """Test that 10-char column uses plain format."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=10, nullable=True)
        
        fake_ssn = masker.mask("123-45-6789", col)
        
        assert fake_ssn is not None
        assert len(fake_ssn) == 9
        assert '-' not in fake_ssn


class TestSSNMaskerValidRanges:
    """Test valid SSN range generation and validation."""
    
    def test_valid_area_code_low_range(self):
        """Test valid area codes in low range (001-665)."""
        masker = SSNMasker()
        assert masker._is_valid_area_code(1) is True
        assert masker._is_valid_area_code(123) is True
        assert masker._is_valid_area_code(665) is True
    
    def test_valid_area_code_high_range(self):
        """Test valid area codes in high range (667-899)."""
        masker = SSNMasker()
        assert masker._is_valid_area_code(667) is True
        assert masker._is_valid_area_code(777) is True
        assert masker._is_valid_area_code(899) is True
    
    def test_generated_ssn_has_valid_area_code(self):
        """Test that generated SSNs have valid area codes."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        # Test multiple seeds to ensure consistency
        for i in range(100):
            test_masker = SSNMasker(seed=42 + i)
            fake_ssn = test_masker.mask("123-45-6789", col)
            area = int(fake_ssn[:3])
            assert masker._is_valid_area_code(area), f"Invalid area code: {area}"
    
    def test_area_code_boundaries(self):
        """Test area code boundaries (001, 665, 667, 899)."""
        masker = SSNMasker()
        assert masker._is_valid_area_code(1) is True    # Minimum valid
        assert masker._is_valid_area_code(665) is True  # Last before gap
        assert masker._is_valid_area_code(667) is True  # First after gap
        assert masker._is_valid_area_code(899) is True  # Maximum valid
    
    def test_formatted_ssn_pattern(self):
        """Test that formatted SSNs match expected pattern."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        fake_ssn = masker.mask("123-45-6789", col)
        
        # Check format: XXX-XX-XXXX
        parts = fake_ssn.split('-')
        assert len(parts) == 3
        assert len(parts[0]) == 3  # Area
        assert len(parts[1]) == 2  # Group
        assert len(parts[2]) == 4  # Serial
        assert all(part.isdigit() for part in parts)
    
    def test_plain_ssn_pattern(self):
        """Test that plain SSNs match expected pattern."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=9, nullable=True)
        
        fake_ssn = masker.mask("123456789", col)
        
        # Check format: 9 digits
        assert len(fake_ssn) == 9
        assert fake_ssn.isdigit()
    
    def test_group_code_range(self):
        """Test that generated group codes are in range 01-99."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        # Test multiple generations
        for i in range(50):
            test_masker = SSNMasker(seed=i)
            fake_ssn = test_masker.mask("123-45-6789", col)
            group = int(fake_ssn[4:6])
            assert 1 <= group <= 99, f"Invalid group code: {group}"


class TestSSNMaskerInvalidRanges:
    """Test exclusion of invalid SSN ranges."""
    
    def test_invalid_area_code_000(self):
        """Test that area code 000 is invalid."""
        masker = SSNMasker()
        assert masker._is_valid_area_code(0) is False
    
    def test_invalid_area_code_666(self):
        """Test that area code 666 is invalid."""
        masker = SSNMasker()
        assert masker._is_valid_area_code(666) is False
    
    def test_invalid_area_code_900_range(self):
        """Test that area codes 900-999 are invalid."""
        masker = SSNMasker()
        assert masker._is_valid_area_code(900) is False
        assert masker._is_valid_area_code(950) is False
        assert masker._is_valid_area_code(999) is False
    
    def test_no_generated_ssn_has_666(self):
        """Test that no generated SSN has area code 666."""
        masker = SSNMasker()
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        # Test many seeds to ensure 666 is never generated
        for i in range(200):
            test_masker = SSNMasker(seed=i)
            fake_ssn = test_masker.mask("123-45-6789", col)
            area = int(fake_ssn[:3])
            assert area != 666, "Generated SSN with forbidden area code 666"
    
    def test_no_generated_ssn_has_900_plus(self):
        """Test that no generated SSN has area code 900+."""
        masker = SSNMasker()
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        # Test many seeds to ensure 900+ is never generated
        for i in range(200):
            test_masker = SSNMasker(seed=i)
            fake_ssn = test_masker.mask("123-45-6789", col)
            area = int(fake_ssn[:3])
            assert area < 900, f"Generated SSN with forbidden area code {area}"


class TestSSNMaskerDataTypes:
    """Test handling of different SQL Server data types."""
    
    def test_varchar_basic(self):
        """Test VARCHAR column masking."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        fake_ssn = masker.mask("123-45-6789", col)
        
        assert fake_ssn is not None
        assert len(fake_ssn) <= 11
        # VARCHAR should produce ASCII-safe SSNs (digits and dashes)
        assert fake_ssn.replace('-', '').isdigit()
    
    def test_nvarchar_basic(self):
        """Test NVARCHAR column masking."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="NVARCHAR", max_length=11, nullable=True)
        
        fake_ssn = masker.mask("123-45-6789", col)
        
        assert fake_ssn is not None
        assert len(fake_ssn) <= 11
    
    def test_char_fixed_length(self):
        """Test CHAR fixed-length column (should be padded)."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(
            data_type="CHAR",
            max_length=11,
            nullable=True,
            is_fixed_length=True
        )
        
        fake_ssn = masker.mask("123-45-6789", col)
        
        assert fake_ssn is not None
        # CHAR columns should be padded to fixed length
        assert len(fake_ssn) == 11
    
    def test_nchar_fixed_length(self):
        """Test NCHAR fixed-length column (should be padded)."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(
            data_type="NCHAR",
            max_length=11,
            nullable=True,
            is_fixed_length=True
        )
        
        fake_ssn = masker.mask("123-45-6789", col)
        
        assert fake_ssn is not None
        assert len(fake_ssn) == 11
    
    def test_varchar_9_chars(self):
        """Test VARCHAR(9) uses plain format."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=9, nullable=True)
        
        fake_ssn = masker.mask("123456789", col)
        
        assert fake_ssn is not None
        assert len(fake_ssn) == 9
        assert '-' not in fake_ssn
    
    def test_text_type(self):
        """Test TEXT column masking."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="TEXT", max_length=None, nullable=True)
        
        fake_ssn = masker.mask("123-45-6789", col)
        
        assert fake_ssn is not None
        # TEXT has no explicit length limit (uses default max)


class TestSSNMaskerNullHandling:
    """Test NULL value handling strategies."""
    
    def test_preserve_null(self):
        """Test PRESERVE strategy returns None for NULL input."""
        masker = SSNMasker(null_strategy=MaskingStrategy.PRESERVE)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        result = masker.mask(None, col)
        
        assert result is None
    
    def test_mask_null(self):
        """Test MASK strategy generates fake SSN for NULL input."""
        masker = SSNMasker(null_strategy=MaskingStrategy.MASK)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        result = masker.mask(None, col)
        
        assert result is not None
        assert isinstance(result, str)
        assert len(result) <= 11
    
    def test_null_on_not_null_column_preserve(self):
        """Test NULL input on NOT NULL column with PRESERVE strategy raises error."""
        masker = SSNMasker(null_strategy=MaskingStrategy.PRESERVE)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=False)
        
        with pytest.raises(MaskingError) as exc_info:
            masker.mask(None, col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_NULL_CONSTRAINT_VIOLATION
    
    def test_null_on_not_null_column_mask(self):
        """Test NULL input on NOT NULL column with MASK strategy generates value."""
        masker = SSNMasker(null_strategy=MaskingStrategy.MASK)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=False)
        
        result = masker.mask(None, col)
        
        assert result is not None
        assert isinstance(result, str)


class TestSSNMaskerValidation:
    """Test validation and error handling."""
    
    def test_validate_formatted_ssn(self):
        """Test validation of formatted SSN."""
        masker = SSNMasker()
        assert masker._validate_ssn_format("123-45-6789") is True
    
    def test_validate_plain_ssn(self):
        """Test validation of plain SSN."""
        masker = SSNMasker()
        assert masker._validate_ssn_format("123456789") is True
    
    def test_validate_invalid_format(self):
        """Test validation rejects invalid format."""
        masker = SSNMasker()
        assert masker._validate_ssn_format("123 45 6789") is False
    
    def test_validate_invalid_area_666(self):
        """Test validation rejects area code 666."""
        masker = SSNMasker()
        assert masker._validate_ssn_format("666-45-6789") is False
    
    def test_validate_invalid_area_900(self):
        """Test validation rejects area code 900+."""
        masker = SSNMasker()
        assert masker._validate_ssn_format("900-45-6789") is False
    
    def test_column_too_short(self):
        """Test error on column length < MIN_LENGTH (9)."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=8, nullable=True)
        
        with pytest.raises(MaskingError) as exc_info:
            masker.mask("123-45-6789", col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_LENGTH_EXCEEDED
        assert "too short" in str(exc_info.value.message).lower()
    
    def test_get_format_tier_formatted(self):
        """Test tier detection for formatted tier (11+)."""
        masker = SSNMasker()
        assert masker._get_format_tier(11) == "formatted"
        assert masker._get_format_tier(15) == "formatted"
    
    def test_get_format_tier_plain(self):
        """Test tier detection for plain tier (9-10)."""
        masker = SSNMasker()
        assert masker._get_format_tier(9) == "plain"
        assert masker._get_format_tier(10) == "plain"
    
    def test_get_format_tier_error(self):
        """Test tier detection for error case (<9)."""
        masker = SSNMasker()
        assert masker._get_format_tier(8) == "error"
        assert masker._get_format_tier(5) == "error"


class TestSSNMaskerEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_whitespace_trimmed(self):
        """Test that leading/trailing whitespace is trimmed."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        ssn1 = masker.mask("  123-45-6789  ", col)
        ssn2 = masker.mask("123-45-6789", col)
        
        # Trimmed input should produce same result
        assert ssn1 == ssn2
    
    def test_deterministic_across_runs(self):
        """Test that same SSN produces consistent results."""
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        # Multiple masker instances with same seed
        ssns = []
        for _ in range(5):
            masker = SSNMasker(seed=42)
            ssn = masker.mask("123-45-6789", col)
            ssns.append(ssn)
        
        # All should be identical
        assert len(set(ssns)) == 1
    
    def test_invalid_format_logs_warning(self):
        """Test that invalid format logs warning but still masks."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        # This should log warning but still return a masked value
        fake_ssn = masker.mask("abc-de-fghi", col)
        
        assert fake_ssn is not None
        assert len(fake_ssn) <= 11
    
    def test_length_boundary_11(self):
        """Test boundary at 11 chars (formatted vs plain)."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        fake_ssn = masker.mask("123-45-6789", col)
        
        assert fake_ssn is not None
        assert len(fake_ssn) == 11
        assert '-' in fake_ssn
    
    def test_length_boundary_9(self):
        """Test boundary at 9 chars (minimum)."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(data_type="VARCHAR", max_length=9, nullable=True)
        
        fake_ssn = masker.mask("123456789", col)
        
        assert fake_ssn is not None
        assert len(fake_ssn) == 9
        assert '-' not in fake_ssn
    
    def test_area_code_distribution(self):
        """Test that generated area codes cover both valid ranges."""
        masker = SSNMasker()
        col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
        
        low_range_found = False  # 001-665
        high_range_found = False  # 667-899
        
        # Generate many SSNs to test distribution
        for i in range(300):
            test_masker = SSNMasker(seed=i)
            fake_ssn = test_masker.mask("123-45-6789", col)
            area = int(fake_ssn[:3])
            
            if 1 <= area <= 665:
                low_range_found = True
            if 667 <= area <= 899:
                high_range_found = True
            
            if low_range_found and high_range_found:
                break
        
        # Should find SSNs in both ranges
        assert low_range_found, "No SSNs generated in low range (001-665)"
        assert high_range_found, "No SSNs generated in high range (667-899)"
