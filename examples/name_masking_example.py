"""
Example usage of NameMasker for deterministic name masking.

This example demonstrates:
- Basic name masking with deterministic mapping
- Multi-tier length optimization across different column sizes
- NULL handling strategies
- Name structure preservation (prefixes, suffixes)
- Unicode name support
- Integration with config files

Real-world scenarios:
- Customer/employee name tables with FK relationships
- Contact information sanitization
- User profile data masking
- HR system data anonymization

Author: Database Sanitization Team
Date: 2026-03-26
"""

from src.masking import NameMasker
from src.masking.base_masker import ColumnInfo, MaskingStrategy
from src.logging.logger import get_logger


def example_basic_masking():
    """Demonstrate basic deterministic name masking."""
    print("\n" + "="*70)
    print("Example 1: Basic Deterministic Name Masking")
    print("="*70)
    
    # Initialize masker with seed for reproducibility
    masker = NameMasker(seed=42)
    
    # Define column metadata (VARCHAR(50))
    col = ColumnInfo(
        data_type="VARCHAR",
        max_length=50,
        nullable=True
    )
    
    # Original names from customer database
    original_names = [
        "John Doe",
        "Jane Smith", 
        "Robert Johnson",
        "John Doe"  # Duplicate to show deterministic mapping
    ]
    
    print("\nOriginal Name       →  Fake Name")
    print("-" * 50)
    
    for original in original_names:
        fake = masker.mask(original, col)
        print(f"{original:<20} →  {fake}")
    
    print("\n✓ Notice: 'John Doe' appears twice and produces the same fake name")
    print("  This maintains referential integrity across related tables")


def example_length_tiers():
    """Demonstrate multi-tier length optimization."""
    print("\n" + "="*70)
    print("Example 2: Multi-Tier Length Optimization")
    print("="*70)
    
    masker = NameMasker(seed=42)
    original = "Jonathan Alexander Smith"
    
    # Different column lengths
    length_configs = [
        (50, "Full Name"),
        (20, "Full Name (boundary)"),
        (15, "First + Last"),
        (10, "First + Last (boundary)"),
        (8, "First Only"),
        (4, "First Only (boundary)"),
        (3, "Initial(s)"),
        (2, "Single Initial")
    ]
    
    print(f"\nOriginal: '{original}'")
    print("\nColumn Length  Tier              Result")
    print("-" * 60)
    
    for max_len, tier_name in length_configs:
        col = ColumnInfo(
            data_type="VARCHAR",
            max_length=max_len,
            nullable=True
        )
        fake = masker.mask(original, col)
        print(f"{max_len:>3} chars      {tier_name:<16}  '{fake}'")
    
    print("\n✓ Masker automatically selects appropriate format for each length")


def example_name_structures():
    """Demonstrate handling of different name structures."""
    print("\n" + "="*70)
    print("Example 3: Name Structure Detection and Handling")
    print("="*70)
    
    masker = NameMasker(seed=42)
    col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
    
    # Various name formats
    test_names = [
        ("John", "Simple first name"),
        ("Smith", "Simple last name"),
        ("John Smith", "Full name"),
        ("Dr. John Smith", "With prefix"),
        ("John Smith Jr.", "With suffix"),
        ("Dr. John Smith Jr.", "With prefix and suffix"),
        ("Mary-Jane", "Hyphenated first name"),
        ("Smith-Jones", "Hyphenated last name"),
        ("O'Brien", "Name with apostrophe"),
        ("Jean-Pierre Dubois", "Hyphenated first + last")
    ]
    
    print("\nOriginal Name              Structure            →  Fake Name")
    print("-" * 80)
    
    for original, description in test_names:
        fake = masker.mask(original, col)
        print(f"{original:<25}  {description:<18}  →  {fake}")
    
    print("\n✓ Masker detects and preserves name structure characteristics")


def example_unicode_support():
    """Demonstrate Unicode name support."""
    print("\n" + "="*70)
    print("Example 4: Unicode and International Name Support")
    print("="*70)
    
    masker = NameMasker(seed=42)
    
    # Use NVARCHAR for Unicode support
    col = ColumnInfo(
        data_type="NVARCHAR",
        max_length=50,
        nullable=True
    )
    
    # International names
    international_names = [
        ("José García", "Spanish"),
        ("François Côté", "French"),
        ("Müller", "German"),
        ("Søren Hansen", "Danish"),
        ("Łukasz Nowak", "Polish"),
        ("李明", "Chinese"),
        ("田中太郎", "Japanese"),
        ("김철수", "Korean")
    ]
    
    print("\nOriginal Name    Language   →  Fake Name")
    print("-" * 60)
    
    for original, language in international_names:
        fake = masker.mask(original, col)
        print(f"{original:<15}  {language:<9}  →  {fake}")
    
    print("\n✓ NVARCHAR columns support international Unicode characters")
    print("  (VARCHAR columns would need ASCII-safe names)")


def example_null_handling():
    """Demonstrate NULL handling strategies."""
    print("\n" + "="*70)
    print("Example 5: NULL Handling Strategies")
    print("="*70)
    
    col_nullable = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
    col_not_null = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=False)
    
    # Strategy 1: PRESERVE (default)
    print("\nStrategy 1: PRESERVE (keep NULLs as NULL)")
    print("-" * 50)
    masker_preserve = NameMasker(seed=42, null_strategy=MaskingStrategy.PRESERVE)
    
    result = masker_preserve.mask(None, col_nullable)
    print(f"NULL input on nullable column → {result}")
    
    try:
        masker_preserve.mask(None, col_not_null)
    except Exception as e:
        print(f"NULL input on NOT NULL column → Error: {e.error_code}")
    
    # Strategy 2: MASK
    print("\nStrategy 2: MASK (replace NULLs with fake names)")
    print("-" * 50)
    masker_mask = NameMasker(seed=42, null_strategy=MaskingStrategy.MASK)
    
    result1 = masker_mask.mask(None, col_nullable)
    print(f"NULL input on nullable column → '{result1}'")
    
    result2 = masker_mask.mask(None, col_not_null)
    print(f"NULL input on NOT NULL column → '{result2}'")
    
    print("\n✓ PRESERVE: Maintains NULL values (fails on NOT NULL)")
    print("  MASK: Generates fake names for NULLs (works on any column)")


def example_fixed_length_columns():
    """Demonstrate CHAR/NCHAR fixed-length column handling."""
    print("\n" + "="*70)
    print("Example 6: Fixed-Length Column Handling (CHAR/NCHAR)")
    print("="*70)
    
    masker = NameMasker(seed=42)
    
    # CHAR(20) - fixed length with padding
    col_char = ColumnInfo(
        data_type="CHAR",
        max_length=20,
        nullable=True,
        is_fixed_length=True
    )
    
    # VARCHAR(20) - variable length
    col_varchar = ColumnInfo(
        data_type="VARCHAR",
        max_length=20,
        nullable=True,
        is_fixed_length=False
    )
    
    original = "John"
    
    print(f"\nOriginal: '{original}'")
    print("\nColumn Type    Result                       Length")
    print("-" * 60)
    
    fake_char = masker.mask(original, col_char)
    print(f"CHAR(20)       '{fake_char}'  {len(fake_char)} chars (padded)")
    
    fake_varchar = masker.mask(original, col_varchar)
    print(f"VARCHAR(20)    '{fake_varchar}'  {len(fake_varchar)} chars (no padding)")
    
    print("\n✓ CHAR columns are padded to fixed length")
    print("  VARCHAR columns use only needed space")


def example_seed_consistency():
    """Demonstrate seed-based deterministic mapping."""
    print("\n" + "="*70)
    print("Example 7: Seed-Based Deterministic Mapping")
    print("="*70)
    
    col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
    original = "John Doe"
    
    # Same seed produces same results
    print("\nSame seed (42) - different masker instances:")
    print("-" * 50)
    masker1 = NameMasker(seed=42)
    masker2 = NameMasker(seed=42)
    
    fake1 = masker1.mask(original, col)
    fake2 = masker2.mask(original, col)
    
    print(f"Masker 1 → '{fake1}'")
    print(f"Masker 2 → '{fake2}'")
    print(f"Match: {fake1 == fake2}")
    
    # Different seeds produce different results
    print("\nDifferent seeds - same input:")
    print("-" * 50)
    masker_a = NameMasker(seed=42)
    masker_b = NameMasker(seed=999)
    
    fake_a = masker_a.mask(original, col)
    fake_b = masker_b.mask(original, col)
    
    print(f"Seed 42  → '{fake_a}'")
    print(f"Seed 999 → '{fake_b}'")
    print(f"Match: {fake_a == fake_b}")
    
    print("\n✓ Same seed ensures consistent masking across runs")
    print("  Different seeds allow different organizations to use different mappings")


def example_practical_scenario():
    """Demonstrate practical use case: customer database sanitization."""
    print("\n" + "="*70)
    print("Example 8: Practical Scenario - Customer Database Sanitization")
    print("="*70)
    
    # Simulate customer table with FK relationships
    print("\nOriginal Customer Table:")
    print("-" * 80)
    print(f"{'CustomerID':<12} {'Name':<20} {'ContactName':<20} {'ManagerID':<10}")
    print("-" * 80)
    
    customers = [
        (1, "John Doe", "John Doe", None),
        (2, "Jane Smith", "Jane Smith", 1),
        (3, "Robert Johnson", "Robert Johnson", 1),
        (4, "Mary Williams", "John Doe", 2)  # FK: Manager is John Doe (ID=1)
    ]
    
    for cust in customers:
        print(f"{cust[0]:<12} {cust[1]:<20} {cust[2]:<20} {str(cust[3]):<10}")
    
    # Mask names deterministically
    masker = NameMasker(seed=42)
    col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
    
    print("\n\nMasked Customer Table:")
    print("-" * 80)
    print(f"{'CustomerID':<12} {'Name (Masked)':<20} {'ContactName (Masked)':<20} {'ManagerID':<10}")
    print("-" * 80)
    
    for cust in customers:
        masked_name = masker.mask(cust[1], col)
        masked_contact = masker.mask(cust[2], col)
        print(f"{cust[0]:<12} {masked_name:<20} {masked_contact:<20} {str(cust[3]):<10}")
    
    print("\n✓ Notice: 'John Doe' is masked consistently in Name and ContactName columns")
    print("  This preserves FK relationships: Manager ID still points to correct person")
    print("  All PII is removed while maintaining data structure for testing/dev")


def main():
    """Run all examples."""
    print("\n" + "="*70)
    print("NAME MASKER - Comprehensive Usage Examples")
    print("="*70)
    print("\nDemonstrating deterministic name masking with Faker library")
    print("for database sanitization and PII protection.")
    
    # Run all examples
    example_basic_masking()
    example_length_tiers()
    example_name_structures()
    example_unicode_support()
    example_null_handling()
    example_fixed_length_columns()
    example_seed_consistency()
    example_practical_scenario()
    
    print("\n" + "="*70)
    print("Examples Complete!")
    print("="*70)
    print("\nKey Takeaways:")
    print("  • Deterministic masking preserves FK relationships")
    print("  • Multi-tier strategy optimizes for any column length")
    print("  • Faker library provides realistic fake names")
    print("  • Unicode support via NVARCHAR columns")
    print("  • Configurable NULL handling strategies")
    print("  • Seed-based consistency across runs")
    print("\nNext Steps:")
    print("  • Review config/pii_config.example.json for configuration")
    print("  • Run tests: pytest tests/unit/test_name_masker.py")
    print("  • Check examples/connection_example.py for database integration")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
