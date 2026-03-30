"""
Quick validation script for new maskers (address, credit_card, date_of_birth).

This script validates that the new maskers:
1. Can be instantiated correctly
2. Can be retrieved from MaskerFactory
3. Generate deterministic output
4. Respect column length constraints
5. Pass Luhn validation (credit cards)
6. Generate realistic data

Run: python test_new_maskers_quick.py
"""

from src.masking import (
    AddressMasker,
    CreditCardMasker,
    DateOfBirthMasker,
    MaskerFactory,
    ColumnInfo,
    MaskingStrategy
)
from datetime import date, datetime


def test_address_masker():
    """Test AddressMasker basic functionality."""
    print("Testing AddressMasker...")
    
    masker = AddressMasker(seed=42)
    col_info = ColumnInfo(
        data_type="VARCHAR",
        max_length=100,
        nullable=True
    )
    
    # Test determinism
    addr1 = masker.mask("123 Real St, City, CA 12345", col_info)
    addr2 = masker.mask("123 Real St, City, CA 12345", col_info)
    assert addr1 == addr2, "Address masking should be deterministic"
    
    # Test different inputs produce different outputs
    addr3 = masker.mask("456 Other Ave, Town, NY 67890", col_info)
    assert addr1 != addr3, "Different inputs should produce different addresses"
    
    # Test length constraints
    short_col = ColumnInfo(data_type="VARCHAR", max_length=15, nullable=True)
    short_addr = masker.mask("123 Main St", short_col)
    assert len(short_addr) <= 15, f"Address should fit in column: {len(short_addr)} > 15"
    
    print(f"  ✓ Sample full address: {addr1}")
    print(f"  ✓ Sample short address: {short_addr}")
    print(f"  ✓ Determinism: PASS")
    print(f"  ✓ Length constraints: PASS")
    print()


def test_credit_card_masker():
    """Test CreditCardMasker basic functionality."""
    print("Testing CreditCardMasker...")
    
    masker = CreditCardMasker(seed=42)
    col_info = ColumnInfo(
        data_type="VARCHAR",
        max_length=20,
        nullable=True
    )
    
    # Test determinism
    card1 = masker.mask("4111111111111111", col_info)
    card2 = masker.mask("4111111111111111", col_info)
    assert card1 == card2, "Credit card masking should be deterministic"
    
    # Test Luhn validation
    card_digits = card1.replace("-", "").replace(" ", "")
    assert masker._verify_luhn(card_digits), f"Card should pass Luhn check: {card1}"
    
    # Test different inputs produce different outputs
    card3 = masker.mask("5500000000000004", col_info)
    assert card1 != card3, "Different inputs should produce different cards"
    
    # Test length constraints
    short_col = ColumnInfo(data_type="VARCHAR", max_length=16, nullable=True)
    short_card = masker.mask("4111111111111111", short_col)
    assert len(short_card) <= 16, f"Card should fit in column: {len(short_card)} > 16"
    
    print(f"  ✓ Sample formatted card: {card1}")
    print(f"  ✓ Sample plain card: {short_card}")
    print(f"  ✓ Determinism: PASS")
    print(f"  ✓ Luhn validation: PASS")
    print(f"  ✓ Length constraints: PASS")
    print()


def test_date_of_birth_masker():
    """Test DateOfBirthMasker basic functionality."""
    print("Testing DateOfBirthMasker...")
    
    masker = DateOfBirthMasker(seed=42, min_age=18, max_age=80)
    
    # Test DATE type
    date_col = ColumnInfo(data_type="DATE", max_length=None, nullable=True)
    dob1 = masker.mask("1990-05-15", date_col)
    dob2 = masker.mask("1990-05-15", date_col)
    assert dob1 == dob2, "Date of birth masking should be deterministic"
    assert isinstance(dob1, date), f"DATE column should return date object, got {type(dob1)}"
    
    # Test DATETIME type
    datetime_col = ColumnInfo(data_type="DATETIME", max_length=None, nullable=True)
    dob_dt = masker.mask("1990-05-15", datetime_col)
    assert isinstance(dob_dt, datetime), f"DATETIME column should return datetime object"
    
    # Test VARCHAR type
    varchar_col = ColumnInfo(data_type="VARCHAR", max_length=10, nullable=True)
    dob_str = masker.mask("05/15/1990", varchar_col)
    assert isinstance(dob_str, str), f"VARCHAR column should return string"
    assert len(dob_str) <= 10, f"Date string should fit in column: {len(dob_str)} > 10"
    
    # Test age range
    today = date.today()
    age = today.year - dob1.year
    assert 18 <= age <= 80, f"Generated age should be in range 18-80, got {age}"
    
    print(f"  ✓ Sample DATE: {dob1}")
    print(f"  ✓ Sample DATETIME: {dob_dt}")
    print(f"  ✓ Sample VARCHAR: {dob_str}")
    print(f"  ✓ Determinism: PASS")
    print(f"  ✓ Type safety: PASS")
    print(f"  ✓ Age range: PASS ({age} years)")
    print()


def test_masker_factory():
    """Test MaskerFactory registration."""
    print("Testing MaskerFactory registration...")
    
    factory = MaskerFactory()
    
    # Test address masker retrieval
    addr_masker = factory.get_masker("address", seed=42)
    assert isinstance(addr_masker, AddressMasker), "Factory should return AddressMasker"
    
    # Test credit card masker retrieval
    cc_masker = factory.get_masker("credit_card", seed=42)
    assert isinstance(cc_masker, CreditCardMasker), "Factory should return CreditCardMasker"
    
    # Test date of birth masker retrieval with params
    dob_masker = factory.get_masker("date_of_birth", seed=42, masker_params={"min_age": 21, "max_age": 65})
    assert isinstance(dob_masker, DateOfBirthMasker), "Factory should return DateOfBirthMasker"
    assert dob_masker.min_age == 21, "Factory should pass min_age parameter"
    assert dob_masker.max_age == 65, "Factory should pass max_age parameter"
    
    # Test caching
    addr_masker2 = factory.get_masker("address", seed=42)
    assert addr_masker is addr_masker2, "Factory should cache masker instances"
    
    print(f"  ✓ AddressMasker registration: PASS")
    print(f"  ✓ CreditCardMasker registration: PASS")
    print(f"  ✓ DateOfBirthMasker registration: PASS")
    print(f"  ✓ Parameter passing: PASS")
    print(f"  ✓ Caching: PASS")
    print()


def main():
    """Run all validation tests."""
    print("=" * 60)
    print("Quick Validation: New Maskers (address, credit_card, DOB)")
    print("=" * 60)
    print()
    
    try:
        test_address_masker()
        test_credit_card_masker()
        test_date_of_birth_masker()
        test_masker_factory()
        
        print("=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        print()
        print("Next steps:")
        print("1. Run comprehensive unit tests (when created)")
        print("2. Run integration tests with database")
        print("3. Test with production data samples")
        
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}\n")
        raise
    except Exception as e:
        print(f"\n✗ ERROR: {e}\n")
        raise


if __name__ == "__main__":
    main()
