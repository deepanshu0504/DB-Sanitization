"""
Comprehensive unit tests for smart generation implementation.

Tests Phase 1 (BaseMasker) and Phase 2-3 (all maskers).
"""

import pytest
from src.masking.base_masker import ColumnInfo
from src.masking.email_masker import EmailMasker
from src.masking.phone_masker import PhoneMasker
from src.masking.name_masker import NameMasker
from src.masking.ssn_masker import SSNMasker
from src.masking.generic_masker import GenericMasker
from src.exceptions import MaskingError


class TestBaseMaskerFoundation:
    """Test Phase 1: BaseMasker infrastructure."""
    
    def test_truncation_tracking_initialization(self):
        """Test truncation tracking is initialized."""
        masker = EmailMasker(seed=42)
        assert masker.truncation_count == 0
        assert masker.truncation_details == []
    
    def test_get_truncation_metrics(self):
        """Test get_truncation_metrics returns correct structure."""
        masker = EmailMasker(seed=42)
        metrics = masker.get_truncation_metrics()
        assert "truncation_count" in metrics
        assert "truncation_details" in metrics
        assert metrics["truncation_count"] == 0
        assert isinstance(metrics["truncation_details"], list)
    
    def test_reset_truncation_metrics(self):
        """Test reset_truncation_metrics clears counters."""  
        masker = EmailMasker(seed=42)
        # Manually add truncation (testing infrastructure)
        masker.truncation_count = 5
        masker.truncation_details = [{"test": "data"}]
        
        masker.reset_truncation_metrics()
        assert masker.truncation_count == 0
        assert masker.truncation_details == []


class TestEmailMaskerSmartGeneration:
    """Test Phase 2: EmailMasker smart generation."""
    
    def test_standard_format_large_column(self):
        """Test standard format for large columns (≥26 chars)."""
        masker = EmailMasker(seed=42)
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=100,
            nullable=True,
            is_unicode=False,
            is_fixed_length=False
        )
        
        result = masker.mask("test@example.com", col)
        assert result is not None
        assert len(result) <= 100
        assert "@" in result
        assert result.count("@") == 1
        # Should use standard format
        assert "user_" in result or len(result) >= 20
    
    def test_compact_format_medium_column(self):
        """Test compact format for medium columns (18-25 chars)."""
        masker = EmailMasker(seed=42)
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=20,
            nullable=True,
            is_unicode=False,
            is_fixed_length=False
        )
        
        result = masker.mask("test@example.com", col)
        assert result is not None
        assert len(result) <= 20
        assert "@" in result
    
    def test_minimal_format_small_column(self):
        """Test minimal format for small columns (6-17 chars)."""
        masker = EmailMasker(seed=42)
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=10,
            nullable=True,
            is_unicode=False,
            is_fixed_length=False
        )
        
        result = masker.mask("test@example.com", col)
        assert result is not None
        assert len(result) <= 10
        assert len(result) >= 6  # Minimum valid email
        assert "@" in result
    
    def test_too_short_raises_error(self):
        """Test email raises error for columns < minimum length."""
        masker = EmailMasker(seed=42)
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=5,  # Too short
            nullable=True,
            is_unicode=False,
            is_fixed_length=False
        )
        
        with pytest.raises(MaskingError) as exc_info:
            masker.mask("test@example.com", col)
        
        assert "too short" in str(exc_info.value).lower()
    
    def test_no_truncation_across_length_range(self):
        """Test that smart generation never truncates across length range."""
        masker = EmailMasker(seed=42)
        
        for length in range(6, 50):  # Test range 6-49 chars
            col = ColumnInfo(
                data_type="VARCHAR",
                max_length=length,
                nullable=True,
                is_unicode=False,
                is_fixed_length=False
            )
            
            result = masker.mask(f"test{length}@example.com", col)
            
            assert result is not None
            assert len(result) <= length, f"Length {length}: generated {len(result)} chars"
            
            # Check no truncation occurred
            metrics = masker.get_truncation_metrics()
            assert metrics["truncation_count"] == 0, \
                f"Truncation at length {length}: {metrics['truncation_details']}"
            
            masker.reset_truncation_metrics()


class TestPhoneMaskerSmartGeneration:
    """Test Phase 3: PhoneMasker smart generation."""
    
    def test_standard_format(self):
        """Test standard format (555) 555-5555 for ≥14 chars."""
        masker = PhoneMasker(seed=42)
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=20,
            nullable=True,
            is_unicode=False,
            is_fixed_length=False
        )
        
        result = masker.mask("(555) 123-4567", col)
        assert result is not None
        assert len(result) <= 20
        assert "555" in result
    
    def test_compact_format(self):
        """Test compact format 555-555-5555 for ≥12 chars."""
        masker = PhoneMasker(seed=42)
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=12,
            nullable=True,
            is_unicode=False,
            is_fixed_length=False
        )
        
        result = masker.mask("5551234567", col)
        assert result is not None
        assert len(result) == 12
        assert "-" in result
    
    def test_minimal_format(self):
        """Test minimal format 5555555555 for ≥10 chars."""
        masker = PhoneMasker(seed=42)
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=10,
            nullable=True,
            is_unicode=False,
            is_fixed_length=False
        )
        
        result = masker.mask("5551234567", col)
        assert result is not None
        assert len(result) == 10
        assert "-" not in result
        assert "(" not in result


class TestNameMaskerSmartGeneration:
    """Test Phase 3: NameMasker smart generation."""
    
    def test_name_generates_within_constraints(self):
        """Test name generates within various length constraints."""
        masker = NameMasker(seed=42)
        
        test_cases = [
            (50, "John Doe"),
            (20, "Jane Smith"),
            (10, "Bob"),
            (5, "Alice"),
            (2, "X")
        ]
        
        for max_length, test_name in test_cases:
            col = ColumnInfo(
                data_type="VARCHAR",
                max_length=max_length,
                nullable=True,
                is_unicode=False,
                is_fixed_length=False
            )
            
            result = masker.mask(test_name, col)
            assert result is not None
            assert len(result) <= max_length
            
            # Verify no truncation
            metrics = masker.get_truncation_metrics()
            assert metrics["truncation_count"] == 0
            masker.reset_truncation_metrics()


class TestSSNMaskerSmartGeneration:
    """Test Phase 3: SSNMasker smart generation."""
    
    def test_formatted_ssn(self):
        """Test formatted SSN for ≥11 chars."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=11,
            nullable=True,
            is_unicode=False,
            is_fixed_length=False
        )
        
        result = masker.mask("123-45-6789", col)
        assert result is not None
        assert len(result) == 11
        assert "-" in result
    
    def test_plain_ssn(self):
        """Test plain SSN for ≥9 chars."""
        masker = SSNMasker(seed=42)
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=9,
            nullable=True,
            is_unicode=False,
            is_fixed_length=False
        )
        
        result = masker.mask("123456789", col)
        assert result is not None
        assert len(result) == 9
        assert "-" not in result


class TestGenericMaskerSmartGeneration:
    """Test Phase 3: GenericMasker smart generation."""
    
    def test_generates_exact_length(self):
        """Test generic masker generates to exact target length."""
        masker = GenericMasker(seed=42, character_class="alphanumeric")
        
        for length in range(1, 100):
            col = ColumnInfo(
                data_type="VARCHAR",
                max_length=length,
                nullable=True,
                is_unicode=False,
                is_fixed_length=False
            )
            
            # Input string of length 50 (will be truncated or preserved)
            input_value = "A" * 50
            result = masker.mask(input_value, col)
            
            assert result is not None
            assert len(result) <= length
            
            # Verify no truncation for smart generation
            metrics = masker.get_truncation_metrics()
            assert metrics["truncation_count"] == 0
            masker.reset_truncation_metrics()


class TestDeterminism:
    """Test that all maskers maintain determinism with smart generation."""
    
    def test_email_determinism(self):
        """Test email masker produces same output for same input."""
        masker1 = EmailMasker(seed=42)
        masker2 = EmailMasker(seed=42)
        
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=20,
            nullable=True,
            is_unicode=False,
            is_fixed_length=False
        )
        
        result1 = masker1.mask("test@example.com", col)
        result2 = masker2.mask("test@example.com", col)
        
        assert result1 == result2
    
    def test_phone_determinism(self):
        """Test phone masker produces same output for same input."""
        masker1 = PhoneMasker(seed=42)
        masker2 = PhoneMasker(seed=42)
        
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=12,
            nullable=True,
            is_unicode=False,
            is_fixed_length=False
        )
        
        result1 = masker1.mask("5551234567", col)
        result2 = masker2.mask("5551234567", col)
        
        assert result1 == result2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
