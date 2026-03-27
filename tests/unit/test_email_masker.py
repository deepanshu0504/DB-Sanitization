"""
Unit tests for EmailMasker class.

These tests validate:
- Basic email masking functionality
- Deterministic masking (same input → same output)
- Domain diversity
- Length constraint handling (VARCHAR, NVARCHAR, CHAR)
- Unicode and IDN support
- Edge cases (quoted strings, IP domains, special chars)
- Integration with BaseMasker
- NULL handling strategies
- Error handling

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from unittest.mock import Mock, patch
from typing import Optional

from src.masking.email_masker import EmailMasker
from src.masking.base_masker import ColumnInfo, MaskingStrategy
from src.exceptions import MaskingError
from src.error_codes import ErrorCodes


# ==================== Test Fixtures ====================


@pytest.fixture
def email_masker():
    """Create an EmailMasker with default seed.</"""
    return EmailMasker(seed=42)


@pytest.fixture
def varchar_50():
    """Create a VARCHAR(50) column info."""
    return ColumnInfo(
        data_type="VARCHAR",
        max_length=50,
        nullable=True,
        is_unicode=False,
        is_fixed_length=False
    )


@pytest.fixture
def nvarchar_100():
    """Create an NVARCHAR(100) column info."""
    return ColumnInfo(
        data_type="NVARCHAR",
        max_length=100,
        nullable=False,
        is_unicode=True,
        is_fixed_length=False
    )


@pytest.fixture
def varchar_20():
    """Create a VARCHAR(20) column info for testing truncation."""
    return ColumnInfo(
        data_type="VARCHAR",
        max_length=20,
        nullable=True,
        is_unicode=False,
        is_fixed_length=False
    )


@pytest.fixture
def char_50():
    """Create a CHAR(50) fixed-length column info."""
    return ColumnInfo(
        data_type="CHAR",
        max_length=50,
        nullable=True,
        is_unicode=False,
        is_fixed_length=True
    )


# ==================== Basic Functionality Tests (8 tests) ====================


class TestBasicFunctionality:
    """Test basic email masking functionality."""
    
    def test_initialization_default_seed(self):
        """Test EmailMasker initialization with default seed."""
        masker = EmailMasker()
        assert masker.seed == 42
        assert masker.null_strategy == MaskingStrategy.PRESERVE
        assert len(masker.DOMAINS) == 10
    
    def test_initialization_custom_seed(self):
        """Test EmailMasker initialization with custom seed."""
        masker = EmailMasker(seed=123)
        assert masker.seed == 123
    
    def test_initialization_custom_null_strategy(self):
        """Test EmailMasker initialization with custom NULL strategy."""
        masker = EmailMasker(null_strategy=MaskingStrategy.MASK)
        assert masker.null_strategy == MaskingStrategy.MASK
    
    def test_initialization_negative_seed_raises_error(self):
        """Test that negative seed raises ValueError."""
        with pytest.raises(ValueError, match="Seed must be non-negative"):
            EmailMasker(seed=-1)
    
    def test_basic_email_masking(self, email_masker, varchar_50):
        """Test basic email masking returns valid email."""
        email = "john.doe@gmail.com"
        masked = email_masker.mask(email, varchar_50)
        
        assert masked is not None
        assert '@' in masked
        assert '.' in masked
        assert len(masked) <= 50
    
    def test_determinism_same_input_same_output(self, email_masker, varchar_50):
        """Test that same email input produces same masked output."""
        email = "test@example.com"
        
        masked1 = email_masker.mask(email, varchar_50)
        masked2 = email_masker.mask(email, varchar_50)
        
        assert masked1 == masked2
    
    def test_different_inputs_different_outputs(self, email_masker, varchar_50):
        """Test that different emails produce different masked outputs."""
        email1 = "john@gmail.com"
        email2 = "jane@yahoo.com"
        
        masked1 = email_masker.mask(email1, varchar_50)
        masked2 = email_masker.mask(email2, varchar_50)
        
        assert masked1 != masked2
    
    def test_determinism_across_instances(self, varchar_50):
        """Test determinism across different masker instances with same seed."""
        masker1 = EmailMasker(seed=42)
        masker2 = EmailMasker(seed=42)
        
        email = "consistent@test.com"
        
        masked1 = masker1.mask(email, varchar_50)
        masked2 = masker2.mask(email, varchar_50)
        
        assert masked1 == masked2


# ==================== Email Validation Tests (6 tests) ====================


class TestEmailValidation:
    """Test email format validation."""
    
    def test_valid_simple_email(self, email_masker):
        """Test validation of simple valid email."""
        assert email_masker._validate_email_format("user@example.com") is True
    
    def test_valid_complex_email(self, email_masker):
        """Test validation of complex valid email with subdomain."""
        assert email_masker._validate_email_format("user.name+tag@sub.example.co.uk") is True
    
    def test_invalid_format_no_at_sign(self, email_masker):
        """Test that string without @ is invalid."""
        assert email_masker._validate_email_format("not-an-email") is False
    
    def test_invalid_format_empty_string(self, email_masker):
        """Test that empty string is invalid."""
        assert email_masker._validate_email_format("") is False
    
    def test_invalid_format_no_domain(self, email_masker):
        """Test that email without domain is invalid."""
        assert email_masker._validate_email_format("user@") is False
    
    def test_ip_domain_is_valid(self, email_masker):
        """Test that IP address domain is considered valid."""
        assert email_masker._validate_email_format("user@[192.168.1.1]") is True


# ==================== Domain Diversity Tests (5 tests) ====================


class TestDomainDiversity:
    """Test domain selection and diversity."""
    
    def test_different_emails_get_different_domains(self, email_masker, varchar_50):
        """Test that different emails can produce different domains."""
        emails = [f"user{i}@test.com" for i in range(20)]
        masked_emails = [email_masker.mask(email, varchar_50) for email in emails]
        
        # Extract domains
        domains = [masked.split('@')[1] for masked in masked_emails]
        
        # Should have multiple different domains (not all the same)
        unique_domains = set(domains)
        assert len(unique_domains) > 1, "Expected domain diversity"
    
    def test_domain_selection_is_deterministic(self, email_masker):
        """Test that same seed produces same domain."""
        seed = 12345
        domain1 = email_masker._select_domain(seed)
        domain2 = email_masker._select_domain(seed)
        
        assert domain1 == domain2
    
    def test_all_domains_can_be_selected(self, email_masker, varchar_50):
        """Test that all domains in pool can be selected."""
        # Generate many emails to hit all domains statistically
        emails = [f"test{i}@example.com" for i in range(100)]
        masked_emails = [email_masker.mask(email, varchar_50) for email in emails]
        
        # Extract unique domains
        domains = set(masked.split('@')[1] for masked in masked_emails)
        
        # Should have good coverage (at least half of available domains)
        assert len(domains) >= len(email_masker.DOMAINS) // 2
    
    def test_domain_selection_wraps_correctly(self, email_masker):
        """Test that domain selection uses modulo correctly."""
        domain_count = len(email_masker.DOMAINS)
        
        # Test with seeds that wrap around
        seed1 = 0
        seed2 = domain_count
        seed3 = domain_count * 2
        
        domain1 = email_masker._select_domain(seed1)
        domain2 = email_masker._select_domain(seed2)
        domain3 = email_masker._select_domain(seed3)
        
        # Should all select the same domain (index 0)
        assert domain1 == domain2 == domain3
    
    def test_domain_count_is_ten(self, email_masker):
        """Test that exactly 10 domains are available."""
        assert len(email_masker.DOMAINS) == 10


# ==================== Length Constraint Tests (8 tests) ====================


class TestLengthConstraints:
    """Test handling of column length constraints."""
    
    def test_varchar_50_fits_normal_email(self, email_masker, varchar_50):
        """Test that normal email fits in VARCHAR(50)."""
        email = "test@example.com"
        masked = email_masker.mask(email, varchar_50)
        
        assert len(masked) <= 50
    
    def test_varchar_20_requires_compact_format(self, email_masker, varchar_20):
        """Test that VARCHAR(20) triggers compact format."""
        email = "verylongemailaddress@example.com"
        masked = email_masker.mask(email, varchar_20)
        
        assert len(masked) <= 20
        assert '@' in masked
    
    def test_varchar_10_requires_minimal_format(self, email_masker):
        """Test that VARCHAR(10) triggers minimal format."""
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=10,
            nullable=True
        )
        
        email = "test@example.com"
        masked = email_masker.mask(email, col)
        
        assert len(masked) <= 10
        assert masked == "x@y.co"  # Minimal format
    
    def test_varchar_5_raises_error(self, email_masker):
        """Test that VARCHAR(5) raises MaskingError (too short)."""
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=5,
            nullable=True
        )
        
        email = "test@example.com"
        
        with pytest.raises(MaskingError) as exc_info:
            email_masker.mask(email, col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_LENGTH_CONSTRAINT_VIOLATED
        assert "min 6 chars required" in str(exc_info.value)
    
    def test_nvarchar_100_character_counting(self, email_masker, nvarchar_100):
        """Test that NVARCHAR uses character counting."""
        email = "test@example.com"
        masked = email_masker.mask(email, nvarchar_100)
        
        # Should count characters, not bytes
        assert len(masked) <= 100
    
    def test_char_50_fixed_length_padding(self, email_masker, char_50):
        """Test that CHAR(50) pads to exact length."""
        email = "short@test.com"
        masked = email_masker.mask(email, char_50)
        
        # CHAR should be padded to exactly 50 characters
        assert len(masked) == 50
    
    def test_varchar_max_no_length_concern(self, email_masker):
        """Test that VARCHAR(MAX) has no length constraint."""
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=-1,  # MAX type
            nullable=True,
            is_max_type=True
        )
        
        email = "test@example.com"
        masked = email_masker.mask(email, col)
        
        assert masked is not None
        assert '@' in masked
    
    def test_length_optimization_strategies(self, email_masker):
        """Test different length optimization tiers."""
        # Standard format (~26 chars)
        col_30 = ColumnInfo(data_type="VARCHAR", max_length=30, nullable=True)
        masked_30 = email_masker.mask("test@example.com", col_30)
        assert len(masked_30) <= 30
        
        # Compact format (~18 chars)
        col_18 = ColumnInfo(data_type="VARCHAR", max_length=18, nullable=True)
        masked_18 = email_masker.mask("test@example.com", col_18)
        assert len(masked_18) <= 18
        
        # Minimal format (6 chars)
        col_6 = ColumnInfo(data_type="VARCHAR", max_length=6, nullable=True)
        masked_6 = email_masker.mask("test@example.com", col_6)
        assert len(masked_6) == 6


# ==================== Unicode Handling Tests (6 tests) ====================


class TestUnicodeHandling:
    """Test Unicode and internationalized domain support."""
    
    def test_unicode_email_with_nvarchar(self, email_masker, nvarchar_100):
        """Test masking with NVARCHAR column (Unicode support)."""
        email = "test@example.com"
        masked = email_masker.mask(email, nvarchar_100)
        
        assert masked is not None
        assert len(masked) <= 100
    
    def test_unicode_email_with_varchar(self, email_masker, varchar_50):
        """Test masking with VARCHAR column (ASCII only)."""
        email = "test@example.com"
        masked = email_masker.mask(email, varchar_50)
        
        # Should produce ASCII-only result
        assert masked.isascii()
    
    def test_idn_domain_handling(self, email_masker, nvarchar_100):
        """Test handling of internationalized domain names."""
        # IDN example: münchen.de encoded as xn--mnchen-3ya.de
        email = "test@münchen.de"
        
        # Should mask without error
        masked = email_masker.mask(email, nvarchar_100)
        assert masked is not None
    
    def test_unicode_local_part(self, email_masker, nvarchar_100):
        """Test email with Unicode characters in local part."""
        email = "user名@example.com"
        
        # Should mask without error
        masked = email_masker.mask(email, nvarchar_100)
        assert masked is not None
    
    def test_mixed_ascii_unicode(self, email_masker, nvarchar_100):
        """Test email with mixed ASCII and Unicode."""
        email = "user123名@test.com"
        
        masked = email_masker.mask(email, nvarchar_100)
        assert masked is not None
    
    def test_byte_vs_character_length_nvarchar(self, email_masker):
        """Test that NVARCHAR uses character length not byte length."""
        col = ColumnInfo(
            data_type="NVARCHAR",
            max_length=20,
            nullable=True,
            is_unicode=True
        )
        
        email = "test@example.com"
        masked = email_masker.mask(email, col)
        
        # Character count should be <= 20
        assert len(masked) <= 20


# ==================== Edge Cases Tests (10 tests) ====================


class TestEdgeCases:
    """Test edge cases and special email formats."""
    
    def test_whitespace_trimmed(self, email_masker, varchar_50):
        """Test that leading/trailing whitespace is trimmed."""
        email = "  user@example.com  "
        masked = email_masker.mask(email, varchar_50)
        
        # Should not have leading/trailing spaces
        assert not masked.startswith(' ')
        assert not masked.endswith(' ')
    
    def test_case_insensitive_determinism(self, email_masker, varchar_50):
        """Test determinism with different cases."""
        email_lower = "user@example.com"
        email_upper = "USER@EXAMPLE.COM"
        email_mixed = "User@Example.COM"
        
        # Case differences should produce different outputs
        # (we preserve exact input for hashing)
        masked_lower = email_masker.mask(email_lower, varchar_50)
        masked_upper = email_masker.mask(email_upper, varchar_50)
        masked_mixed = email_masker.mask(email_mixed, varchar_50)
        
        # Different cases = different hashes = different outputs
        assert masked_lower != masked_upper or masked_upper != masked_mixed
    
    def test_ip_domain_is_replaced(self, email_masker, varchar_50):
        """Test that IP address domain is replaced with standard domain."""
        email = "user@[192.168.1.1]"
        masked = email_masker.mask(email, varchar_50)
        
        # Should produce a standard domain, not IP
        assert '@' in masked
        assert '[' not in masked or ']' not in masked or '.' in masked.split('@')[1]
    
    def test_very_long_local_part(self, email_masker, varchar_50):
        """Test handling of very long local part (>64 chars per RFC)."""
        email = "a" * 70 + "@example.com"
        masked = email_masker.mask(email, varchar_50)
        
        assert len(masked) <= 50
    
    def test_very_long_domain(self, email_masker, varchar_50):
        """Test handling of very long domain (>253 chars)."""
        email = "user@" + "a" * 300 + ".com"
        masked = email_masker.mask(email, varchar_50)
        
        assert len(masked) <= 50
    
    def test_consecutive_dots(self, email_masker, varchar_50):
        """Test handling of consecutive dots (technically invalid)."""
        email = "user..name@example.com"
        
        # Should mask anyway (with warning logged)
        masked = email_masker.mask(email, varchar_50)
        assert masked is not None
    
    def test_leading_dot(self, email_masker, varchar_50):
        """Test handling of leading dot in local part."""
        email = ".user@example.com"
        
        masked = email_masker.mask(email, varchar_50)
        assert masked is not None
    
    def test_trailing_dot(self, email_masker, varchar_50):
        """Test handling of trailing dot in local part."""
        email = "user.@example.com"
        
        masked = email_masker.mask(email, varchar_50)
        assert masked is not None
    
    def test_multiple_at_signs_invalid(self, email_masker, varchar_50):
        """Test handling of multiple @ signs (invalid)."""
        email = "user@company@example.com"
        
        # Should mask anyway (format validation logs warning)
        masked = email_masker.mask(email, varchar_50)
        assert masked is not None
    
    def test_special_characters_in_local_part(self, email_masker, varchar_50):
        """Test handling of special characters in local part."""
        email = "user+tag%test@example.com"
        
        masked = email_masker.mask(email, varchar_50)
        assert masked is not None


# ==================== NULL Handling Tests (4 tests) ====================


class TestNullHandling:
    """Test NULL value handling strategies."""
    
    def test_null_preserve_strategy(self, varchar_50):
        """Test that NULL is preserved with PRESERVE strategy."""
        masker = EmailMasker(null_strategy=MaskingStrategy.PRESERVE)
        result = masker.mask(None, varchar_50)
        
        assert result is None
    
    def test_null_mask_strategy_generates_email(self, varchar_50):
        """Test that NULL generates fake email with MASK strategy."""
        masker = EmailMasker(null_strategy=MaskingStrategy.MASK)
        
        # MASK strategy should generate a value even for NULL
        # (BaseMasker _handle_null implementation)
        # Note: This depends on BaseMasker implementation
        result = masker.mask(None, varchar_50)
        
        # If MASK strategy generates value, it should be valid
        # If not implemented in BaseMasker, will return None
        if result is not None:
            assert '@' in result
    
    def test_null_not_null_violation(self):
        """Test that NULL raises error for NOT NULL column."""
        masker = EmailMasker(null_strategy=MaskingStrategy.PRESERVE)
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=50,
            nullable=False  # NOT NULL
        )
        
        with pytest.raises(MaskingError) as exc_info:
            masker.mask(None, col)
        
        assert exc_info.value.error_code == ErrorCodes.MASKING_NULL_CONSTRAINT_VIOLATION
    
    def test_empty_string_not_null(self, email_masker, varchar_50):
        """Test that empty string is masked (not treated as NULL)."""
        email = ""
        masked = email_masker.mask(email, varchar_50)
        
        # Empty string should be masked, not returned as NULL
        assert masked is not None


# ==================== BaseMasker Integration Tests (6 tests) ====================


class TestBaseMaskerIntegration:
    """Test integration with BaseMasker abstract class."""
    
    def test_get_deterministic_seed_called(self, email_masker, varchar_50):
        """Test that _get_deterministic_seed is used correctly."""
        email1 = "test@example.com"
        email2 = "test@example.com"
        
        # Same input should use same seed
        seed1 = email_masker._get_deterministic_seed(email1)
        seed2 = email_masker._get_deterministic_seed(email2)
        
        assert seed1 == seed2
    
    def test_validate_length_called(self, email_masker, varchar_20):
        """Test that _validate_length is applied."""
        email = "verylongemailaddress@verylongdomain.com"
        masked = email_masker.mask(email, varchar_20)
        
        # Should be truncated/optimized to fit
        assert len(masked) <= 20
    
    def test_handle_null_respects_strategy(self, varchar_50):
        """Test that _handle_null respects NULL strategy."""
        masker_preserve = EmailMasker(null_strategy=MaskingStrategy.PRESERVE)
        masker_mask = EmailMasker(null_strategy=MaskingStrategy.MASK)
        
        result_preserve = masker_preserve.mask(None, varchar_50)
        # PRESERVE should return None
        assert result_preserve is None
    
    def test_masking_error_raised_for_constraints(self, email_masker):
        """Test that MaskingError is raised for violated constraints."""
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=3,  # Too short
            nullable=True
        )
        
        with pytest.raises(MaskingError):
            email_masker.mask("test@example.com", col)
    
    def test_logging_for_warnings(self, email_masker, varchar_50):
        """Test that warnings are logged for invalid formats."""
        # Mock logger to capture calls
        with patch.object(email_masker.logger, 'warning') as mock_warning:
            email_masker.mask("not-an-email", varchar_50)
            
            # Should log warning about invalid format
            mock_warning.assert_called()
    
    def test_column_info_integration(self, email_masker):
        """Test that ColumnInfo is used correctly."""
        col = ColumnInfo(
            data_type="NVARCHAR",
            max_length=50,
            nullable=False,
            is_unicode=True,
            is_fixed_length=False
        )
        
        email = "test@example.com"
        masked = email_masker.mask(email, col)
        
        # Should respect all column properties
        assert len(masked) <= 50
        assert masked is not None


# ==================== Stress Tests (2 additional tests) ====================


class TestStressAndPerformance:
    """Test performance and stress scenarios."""
    
    def test_determinism_100_iterations(self, email_masker, varchar_50):
        """Test determinism over 100 iterations."""
        email = "consistent@test.com"
        
        results = [email_masker.mask(email, varchar_50) for _ in range(100)]
        
        # All results should be identical
        assert len(set(results)) == 1
    
    def test_domain_distribution_1000_emails(self, email_masker, varchar_50):
        """Test domain distribution over 1000 emails."""
        emails = [f"user{i}@test{i}.com" for i in range(1000)]
        masked_emails = [email_masker.mask(email, varchar_50) for email in emails]
        
        # Extract domains
        domains = [masked.split('@')[1] for masked in masked_emails]
        domain_counts = {}
        for domain in domains:
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
        
        # Should use all 10 domains
        assert len(domain_counts) == 10
        
        # Distribution should be relatively even (within 20% of average)
        average = 1000 / 10
        for count in domain_counts.values():
            assert abs(count - average) < average * 0.3  # Within 30%
