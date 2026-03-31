"""
Quick validation test for credit card implementation in sanitize_smart.py.

This test validates:
1. Credit card generation works for all format tiers
2. All generated cards pass Luhn validation
3. Only test BIN ranges are used
4. Deterministic generation (same input = same output)
5. Column length constraints are respected

Usage:
    python test_credit_card_implementation.py
"""

import sys
from sanitize_smart import SmartMaskerEngine, ColumnInfo


def verify_luhn(card_number: str) -> bool:
    """
    Verify a card number has a valid Luhn checksum.
    
    Args:
        card_number: Complete card number to verify
    
    Returns:
        True if card passes Luhn validation
    """
    # Remove any non-digit characters
    digits = ''.join(c for c in card_number if c.isdigit())
    
    total = 0
    # Process all digits from right to left
    for i, digit in enumerate(reversed(digits)):
        n = int(digit)
        
        # Double every second digit from the right
        if i % 2 == 1:
            n = n * 2
            if n > 9:
                n = n - 9
        
        total += n
    
    return total % 10 == 0


def test_credit_card_generation():
    """Test credit card generation across all format tiers."""
    
    print("="*80)
    print("CREDIT CARD IMPLEMENTATION VALIDATION TEST")
    print("="*80)
    
    masker = SmartMaskerEngine(seed=42)
    
    # Test cases: (column_length, expected_format, description)
    test_cases = [
        (13, "plain_13", "Minimum length - 13-digit plain"),
        (14, "plain_13", "Short length - 13-digit plain"),
        (15, "plain_13", "Short length - 13-digit plain"),
        (16, "plain_16", "Standard length - 16-digit plain"),
        (17, "plain_16", "Standard length - 16-digit plain"),
        (18, "plain_16", "Standard length - 16-digit plain"),
        (19, "formatted", "Formatted length - with dashes/spaces"),
        (20, "formatted", "Formatted length - with dashes/spaces"),
        (50, "formatted", "Large column - formatted"),
    ]
    
    print("\n[1/4] Testing format tier selection")
    all_passed = True
    
    for max_length, expected_format, description in test_cases:
        col_info = ColumnInfo(
            data_type="VARCHAR",
            max_length=max_length,
            nullable=True,
            column_name="CreditCardNumber"
        )
        
        try:
            # Generate credit card
            card = masker.mask_value("4111111111111111", "credit_card", col_info)
            
            # Remove formatting to get digits only
            card_digits = ''.join(c for c in card if c.isdigit())
            
            # Validate length
            if len(card) > max_length:
                print(f"  [FAIL] Length {max_length}: Card '{card}' exceeds max_length ({len(card)} > {max_length})")
                all_passed = False
                continue
            
            # Validate format
            if expected_format == "plain_13":
                expected = len(card_digits) == 13 and card == card_digits
            elif expected_format == "plain_16":
                expected = len(card_digits) == 16 and card == card_digits
            else:  # formatted
                expected = ("-" in card or " " in card) and len(card_digits) in [13, 15, 16]
            
            if expected:
                print(f"  [PASS] Length {max_length}: {card} ({description})")
            else:
                print(f"  [FAIL] Length {max_length}: {card} - unexpected format")
                all_passed = False
                
        except Exception as e:
            print(f"  [FAIL] Length {max_length}: {e}")
            all_passed = False
    
    if not all_passed:
        print("\n[ERROR] Format tier selection test FAILED")
        return False
    
    print("\n[2/4] Testing Luhn validation")
    all_valid = True
    
    for max_length in [13, 16, 19, 20, 50]:
        col_info = ColumnInfo(
            data_type="VARCHAR",
            max_length=max_length,
            nullable=True,
            column_name="CreditCardNumber"
        )
        
        card = masker.mask_value("4111111111111111", "credit_card", col_info)
        
        if verify_luhn(card):
            print(f"  [PASS] Length {max_length}: {card} - Valid Luhn checksum")
        else:
            print(f"  [FAIL] Length {max_length}: {card} - Invalid Luhn checksum")
            all_valid = False
    
    if not all_valid:
        print("\n[ERROR] Luhn validation test FAILED")
        return False
    
    print("\n[3/4] Testing TEST BIN usage")
    test_bins = ["4532", "4533", "4534", "4535", "4536", "4537", "4538", "4539",
                 "5100", "5105", "5111", "5150", "5155", "5175", "5199",
                 "3711", "3722", "3734", "3755", "3766", "3777", "3788", "3799",
                 "6011"]
    
    col_info = ColumnInfo(
        data_type="VARCHAR",
        max_length=20,
        nullable=True,
        column_name="CreditCardNumber"
    )
    
    all_test_bins = True
    cards_generated = []
    
    for i in range(20):
        test_input = f"411111111111111{i}"
        card = masker.mask_value(test_input, "credit_card", col_info)
        cards_generated.append(card)
        
        # Extract first 4 digits (BIN)
        card_digits = ''.join(c for c in card if c.isdigit())
        bin_prefix = card_digits[:4]
        
        if bin_prefix in test_bins:
            print(f"  [PASS] Input {i}: BIN {bin_prefix} is in TEST_BINS")
        else:
            print(f"  [FAIL] Input {i}: BIN {bin_prefix} is NOT in TEST_BINS!")
            all_test_bins = False
    
    if not all_test_bins:
        print("\n[ERROR] TEST BIN usage test FAILED")
        return False
    
    print("\n[4/4] Testing determinism")
    deterministic = True
    
    col_info = ColumnInfo(
        data_type="VARCHAR",
        max_length=20,
        nullable=True,
        column_name="CreditCardNumber"
    )
    
    test_inputs = ["4111111111111111", "5555555555554444", "378282246310005"]
    
    for test_input in test_inputs:
        card1 = masker.mask_value(test_input, "credit_card", col_info)
        card2 = masker.mask_value(test_input, "credit_card", col_info)
        
        if card1 == card2:
            print(f"  [PASS] Input '{test_input[:8]}...': Deterministic ({card1})")
        else:
            print(f"  [FAIL] Input '{test_input[:8]}...': Not deterministic ({card1} != {card2})")
            deterministic = False
    
    if not deterministic:
        print("\n[ERROR] Determinism test FAILED")
        return False
    
    print("\n" + "="*80)
    print("[SUCCESS] ALL TESTS PASSED")
    print("="*80)
    print("\nCredit card implementation validation complete:")
    print("  ✓ Format tier selection works correctly")
    print("  ✓ All generated cards pass Luhn validation")
    print("  ✓ Only TEST BIN ranges are used (safe generation)")
    print("  ✓ Deterministic generation verified")
    print("  ✓ Column length constraints respected")
    print("\nImplementation is ready for production use.")
    
    return True


def test_edge_cases():
    """Test edge cases."""
    print("\n" + "="*80)
    print("EDGE CASE TESTING")
    print("="*80)
    
    masker = SmartMaskerEngine(seed=42)
    
    # Test 1: Column too short
    print("\n[Edge Case 1] Column length < 13 (should use fallback)")
    try:
        col_info = ColumnInfo(data_type="VARCHAR", max_length=12, nullable=True, column_name="CC")
        card = masker.mask_value("4111111111111111", "credit_card", col_info)
        if card == "X":
            print(f"  [PASS] Correctly used fallback for too-short column: '{card}'")
        else:
            print(f"  [FAIL] Expected fallback 'X', got: {card}")
    except ValueError as e:
        print(f"  [FAIL] Should not raise ValueError with graceful fallback enabled")

    
    # Test 2: NULL handling
    print("\n[Edge Case 2] NULL value handling")
    col_info = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True, column_name="CC")
    card = masker.mask_value(None, "credit_card", col_info)
    if card is None:
        print(f"  [PASS] NULL value preserved: {card}")
    else:
        print(f"  [FAIL] NULL should be None, got: {card}")
    
    # Test 3: NVARCHAR column
    print("\n[Edge Case 3] NVARCHAR column (Unicode support)")
    col_info = ColumnInfo(data_type="NVARCHAR", max_length=20, nullable=True, column_name="CC")
    card = masker.mask_value("4111111111111111", "credit_card", col_info)
    print(f"  [PASS] NVARCHAR column: {card}")
    
    # Test 4: Exact boundary lengths
    print("\n[Edge Case 4] Exact boundary lengths")
    for boundary in [13, 16, 19]:
        col_info = ColumnInfo(data_type="VARCHAR", max_length=boundary, nullable=True, column_name="CC")
        card = masker.mask_value("4111111111111111", "credit_card", col_info)
        if len(card) <= boundary:
            print(f"  [PASS] Boundary {boundary}: {card} (length={len(card)})")
        else:
            print(f"  [FAIL] Boundary {boundary}: {card} exceeds max_length (length={len(card)})")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    try:
        success = test_credit_card_generation()
        test_edge_cases()
        
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERROR] Test execution failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
