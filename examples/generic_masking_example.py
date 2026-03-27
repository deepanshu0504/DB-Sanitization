"""
Example demonstrating generic string masking with character class support.

This example shows:
1. Basic generic string masking (alphanumeric default)
2. Alpha-only character class (letters only)
3. Numeric-only character class (digits only)
4. Length preservation and truncation
5. NULL handling strategies
6. Different seed values for different masking
7. Fixed-length column padding
8. Practical use cases (user codes, reference numbers, tags)

Generic masker is ideal for:
- Custom PII types not covered by specialized maskers
- Miscellaneous sensitive fields
- Reference codes, internal IDs, tags
- Any string data requiring simple character replacement

Author: Database Sanitization Team
Date: 2026-03-26
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.masking import GenericMasker
from src.masking.base_masker import ColumnInfo, MaskingStrategy


def example_1_basic_generic_masking():
    """Example 1: Basic generic string masking with alphanumeric characters."""
    print("\n" + "="*80)
    print("EXAMPLE 1: Basic Generic String Masking (Alphanumeric)")
    print("="*80)
    
    # Create generic masker with default alphanumeric character class
    masker = GenericMasker(seed=42, character_class="alphanumeric")
    
    # Column configuration
    col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
    
    # Sample custom data types
    custom_data = [
        "CustomField123",
        "InternalCode456",
        "ReferenceNum789",
        "TagValue_ABC",
        "MiscData_XYZ"
    ]
    
    print("\nMasking custom string data:")
    print(f"{'Original Value':<25} -> {'Masked Value':<25}")
    print("-" * 52)
    
    for value in custom_data:
        masked = masker.mask(value, col)
        print(f"{value:<25} -> {masked:<25}")
    
    print("\n✓ All values masked with alphanumeric characters (a-zA-Z0-9)")


def example_2_alpha_character_class():
    """Example 2: Alpha character class (letters only)."""
    print("\n" + "="*80)
    print("EXAMPLE 2: Alpha Character Class (Letters Only)")
    print("="*80)
    
    # Create generic masker with alpha-only character class
    masker = GenericMasker(seed=42, character_class="alpha")
    
    # Column configuration
    col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
    
    # Sample data - ideal for text-only fields
    text_data = [
        "UserCode",
        "DepartmentTag",
        "CategoryLabel",
        "StatusFlag",
        "TypeIndicator"
    ]
    
    print("\nMasking with alpha-only characters:")
    print(f"{'Original Value':<25} -> {'Masked Value':<25}")
    print("-" * 52)
    
    for value in text_data:
        masked = masker.mask(value, col)
        print(f"{value:<25} -> {masked:<25} (letters only)")
    
    print("\n✓ All values masked with letters only (a-zA-Z)")


def example_3_numeric_character_class():
    """Example 3: Numeric character class (digits only)."""
    print("\n" + "="*80)
    print("EXAMPLE 3: Numeric Character Class (Digits Only)")
    print("="*80)
    
    # Create generic masker with numeric-only character class
    masker = GenericMasker(seed=42, character_class="numeric")
    
    # Column configuration
    col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
    
    # Sample data - ideal for numeric codes stored as strings
    numeric_codes = [
        "123456",
        "7890123",
        "555444333",
        "1234567890",
        "999888777"
    ]
    
    print("\nMasking with numeric-only characters:")
    print(f"{'Original Value':<20} -> {'Masked Value':<20}")
    print("-" * 42)
    
    for code in numeric_codes:
        masked = masker.mask(code, col)
        print(f"{code:<20} -> {masked:<20} (digits only)")
    
    print("\n✓ All values masked with digits only (0-9)")


def example_4_length_preservation():
    """Example 4: Length preservation and truncation."""
    print("\n" + "="*80)
    print("EXAMPLE 4: Length Preservation and Truncation")
    print("="*80)
    
    masker = GenericMasker(seed=42)
    
    # Test different column sizes
    test_cases = [
        ("Short", 50, "Short value in long column"),
        ("MediumLengthValue", 30, "Medium value in medium column"),
        ("VeryLongValueThatExceedsColumnMaxLength", 20, "Long value truncated to max_length"),
        ("X", 1, "Single character column"),
        ("CustomData" * 10, 50, "Very long input truncated to 50")
    ]
    
    print("\nLength preservation examples:")
    print(f"{'Original':<30} {'Max':<5} {'Masked':<30} {'Len':<5} Description")
    print("-" * 95)
    
    for value, max_len, description in test_cases:
        col = ColumnInfo(data_type="VARCHAR", max_length=max_len, nullable=True)
        masked = masker.mask(value, col)
        print(f"{value[:28]:<30} {max_len:<5} {masked:<30} {len(masked):<5} {description}")
    
    print("\n✓ Output length matches min(input_length, max_length)")


def example_5_null_handling():
    """Example 5: NULL handling strategies."""
    print("\n" + "="*80)
    print("EXAMPLE 5: NULL Handling Strategies")
    print("="*80)
    
    # Column configuration
    col_nullable = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
    col_not_null = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=False)
    
    print("\nStrategy 1: PRESERVE (keep NULL as NULL)")
    print("-" * 50)
    masker_preserve = GenericMasker(
        seed=42,
        null_strategy=MaskingStrategy.PRESERVE
    )
    result = masker_preserve.mask(None, col_nullable)
    print(f"NULL input -> {result} (preserved)")
    
    print("\nStrategy 2: MASK (generate fake value for NULL)")
    print("-" * 50)
    masker_mask = GenericMasker(
        seed=42,
        null_strategy=MaskingStrategy.MASK
    )
    result = masker_mask.mask(None, col_not_null)
    print(f"NULL input -> '{result}' (generated fake value)")
    
    print("\n✓ PRESERVE keeps NULL, MASK generates value")


def example_6_deterministic_masking():
    """Example 6: Deterministic masking with different seeds."""
    print("\n" + "="*80)
    print("EXAMPLE 6: Deterministic Masking with Different Seeds")
    print("="*80)
    
    # Column configuration
    col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
    
    # Test value
    test_value = "CustomData123"
    
    print(f"\nOriginal value: {test_value}")
    print("\nDifferent seeds produce different masked values:")
    print(f"{'Seed':<10} {'Masked Value':<30}")
    print("-" * 42)
    
    seeds = [42, 100, 999, 12345, 99999]
    for seed in seeds:
        masker = GenericMasker(seed=seed)
        masked = masker.mask(test_value, col)
        print(f"{seed:<10} {masked:<30}")
    
    print("\nSame seed produces consistent results:")
    print(f"{'Attempt':<10} {'Masked Value':<30}")
    print("-" * 42)
    
    for i in range(1, 4):
        masker = GenericMasker(seed=42)  # Same seed each time
        masked = masker.mask(test_value, col)
        print(f"#{i:<9} {masked:<30}")
    
    print("\n✓ Same seed = consistent output (idempotent)")


def example_7_fixed_length_columns():
    """Example 7: Fixed-length column padding (CHAR/NCHAR)."""
    print("\n" + "="*80)
    print("EXAMPLE 7: Fixed-Length Column Padding (CHAR/NCHAR)")
    print("="*80)
    
    masker = GenericMasker(seed=42)
    
    # Fixed-length column (CHAR)
    col_fixed = ColumnInfo(
        data_type="CHAR",
        max_length=20,
        nullable=True,
        is_fixed_length=True
    )
    
    # Variable-length column (VARCHAR)
    col_variable = ColumnInfo(
        data_type="VARCHAR",
        max_length=20,
        nullable=True,
        is_fixed_length=False
    )
    
    test_value = "Short"
    
    print(f"\nOriginal value: '{test_value}' (length={len(test_value)})")
    
    masked_fixed = masker.mask(test_value, col_fixed)
    masked_variable = masker.mask(test_value, col_variable)
    
    print(f"\nCHAR(20) - Fixed Length:")
    print(f"  Masked: '{masked_fixed}'")
    print(f"  Length: {len(masked_fixed)} (padded to 20)")
    
    print(f"\nVARCHAR(20) - Variable Length:")
    print(f"  Masked: '{masked_variable}'")
    print(f"  Length: {len(masked_variable)} (preserves input length)")
    
    print("\n✓ CHAR columns padded to fixed length, VARCHAR preserves length")


def example_8_practical_use_cases():
    """Example 8: Practical use cases for generic masker."""
    print("\n" + "="*80)
    print("EXAMPLE 8: Practical Use Cases")
    print("="*80)
    
    print("\nUse Case 1: Internal Reference Codes")
    print("-" * 50)
    masker_alpha = GenericMasker(seed=42, character_class="alphanumeric")
    col_code = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
    
    codes = ["REF-12345", "CODE-ABCD", "TAG-XYZ99"]
    for code in codes:
        masked = masker_alpha.mask(code, col_code)
        print(f"  {code:<15} -> {masked}")
    
    print("\nUse Case 2: User-Generated Tags (alpha-only)")
    print("-" * 50)
    masker_alpha_only = GenericMasker(seed=42, character_class="alpha")
    col_tag = ColumnInfo(data_type="VARCHAR", max_length=30, nullable=True)
    
    tags = ["PersonalTag", "CategoryLabel", "UserDefinedKey"]
    for tag in tags:
        masked = masker_alpha_only.mask(tag, col_tag)
        print(f"  {tag:<20} -> {masked}")
    
    print("\nUse Case 3: Numeric Identifiers (numeric-only)")
    print("-" * 50)
    masker_numeric = GenericMasker(seed=42, character_class="numeric")
    col_id = ColumnInfo(data_type="VARCHAR", max_length=15, nullable=True)
    
    ids = ["1234567890", "555444333", "999888777"]
    for id_value in ids:
        masked = masker_numeric.mask(id_value, col_id)
        print(f"  {id_value:<15} -> {masked}")
    
    print("\nUse Case 4: Miscellaneous Sensitive Fields")
    print("-" * 50)
    masker_misc = GenericMasker(seed=42)
    col_misc = ColumnInfo(data_type="NVARCHAR", max_length=50, nullable=True)
    
    misc_fields = [
        ("customer_note", "Special handling required"),
        ("internal_comment", "VIP account"),
        ("custom_field_1", "Confidential data")
    ]
    
    for field_name, value in misc_fields:
        masked = masker_misc.mask(value, col_misc)
        print(f"  {field_name:<20}: {value[:30]:<30} -> {masked[:30]}")
    
    print("\n✓ Generic masker handles diverse custom PII types")


def main():
    """Run all generic masking examples."""
    print("\n" + "="*80)
    print("GENERIC STRING MASKING EXAMPLES")
    print("Demonstrating character class support and flexible masking")
    print("="*80)
    
    try:
        example_1_basic_generic_masking()
        example_2_alpha_character_class()
        example_3_numeric_character_class()
        example_4_length_preservation()
        example_5_null_handling()
        example_6_deterministic_masking()
        example_7_fixed_length_columns()
        example_8_practical_use_cases()
        
        print("\n" + "="*80)
        print("✓ All examples completed successfully!")
        print("="*80)
        
        print("\nKey Takeaways:")
        print("  • Generic masker supports alphanumeric, alpha, and numeric character classes")
        print("  • Length is preserved (or truncated to max_length)")
        print("  • Deterministic masking ensures consistent results")
        print("  • Flexible NULL handling (PRESERVE or MASK)")
        print("  • Ideal for custom PII types and miscellaneous sensitive fields")
        print("  • Different seeds produce different masked values")
        print("  • Fixed-length columns (CHAR) are padded to full length")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
