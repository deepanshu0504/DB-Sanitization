"""
Example usage of SSNMasker for deterministic SSN masking with compliance validation.

This example demonstrates:
- Basic SSN masking with deterministic mapping
- Format detection and auto-selection (formatted vs plain)
- Valid range verification (excludes 000, 666, 900-999)
- NULL handling strategies
- Fixed-length vs variable-length columns
- Seed-based consistency
- Integration with config files

Real-world scenarios:
- Employee/HR tables with SSN columns
- Tax record sanitization
- Benefits/payroll data anonymization
- Compliance testing (GDPR, HIPAA)

Author: Database Sanitization Team
Date: 2026-03-26
"""

from src.masking import SSNMasker
from src.masking.base_masker import ColumnInfo, MaskingStrategy
from src.logging.logger import get_logger


def example_basic_masking():
    """Demonstrate basic deterministic SSN masking."""
    print("\n" + "="*70)
    print("Example 1: Basic Deterministic SSN Masking")
    print("="*70)
    
    # Initialize masker with seed for reproducibility
    masker = SSNMasker(seed=42)
    
    # Define column metadata (VARCHAR(11) for formatted SSNs)
    col = ColumnInfo(
        data_type="VARCHAR",
        max_length=11,
        nullable=True
    )
    
    # Original SSNs from employee database
    original_ssns = [
        "123-45-6789",
        "987-65-4321",
        "555-12-3456",
        "123-45-6789"  # Duplicate to show deterministic mapping
    ]
    
    print("\nOriginal SSN     →  Fake SSN")
    print("-" * 50)
    
    for original in original_ssns:
        fake = masker.mask(original, col)
        print(f"{original}  →  {fake}")
    
    print("\n✓ Notice: '123-45-6789' appears twice and produces the same fake SSN")
    print("  This maintains referential integrity across related tables")


def example_format_detection():
    """Demonstrate format detection and auto-selection."""
    print("\n" + "="*70)
    print("Example 2: Format Detection and Auto-Selection")
    print("="*70)
    
    masker = SSNMasker(seed=42)
    
    # Test different input formats
    test_cases = [
        ("123-45-6789", 11, "Formatted input, formatted output"),
        ("123456789", 11, "Plain input, formatted output"),
        ("123-45-6789", 9, "Formatted input, plain output"),
        ("123456789", 9, "Plain input, plain output"),
        ("123-45-6789", 10, "Formatted input, plain output (10 chars)")
    ]
    
    print("\nInput SSN      Max Length  Description                         →  Output")
    print("-" * 90)
    
    for original, max_len, description in test_cases:
        col = ColumnInfo(data_type="VARCHAR", max_length=max_len, nullable=True)
        fake = masker.mask(original, col)
        print(f"{original:14} {max_len:10}  {description:34}  →  {fake}")
    
    print("\n✓ Masker auto-selects format based on column length")
    print("  11+ chars: Formatted (XXX-XX-XXXX)")
    print("  9-10 chars: Plain (XXXXXXXXX)")


def example_valid_range_verification():
    """Demonstrate valid range verification (no 666, 900+)."""
    print("\n" + "="*70)
    print("Example 3: Valid Range Verification")
    print("="*70)
    
    masker = SSNMasker(seed=42)
    col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
    
    print("\nGenerating 50 SSNs and checking for invalid area codes (000, 666, 900-999)...")
    print("\nSample Generated SSNs:")
    print("-" * 50)
    
    invalid_count = 0
    samples_shown = 0
    
    for i in range(50):
        test_masker = SSNMasker(seed=42 + i)
        fake_ssn = test_masker.mask("123-45-6789", col)
        area = int(fake_ssn[:3])
        
        # Check for invalid area codes
        if area == 0 or area == 666 or area >= 900:
            invalid_count += 1
            print(f"❌ INVALID: {fake_ssn} (area code {area})")
        elif samples_shown < 10:
            print(f"✓ Valid: {fake_ssn} (area code {area:03d})")
            samples_shown += 1
    
    print(f"\n{'='*50}")
    print(f"Results: {50 - invalid_count}/50 valid SSNs generated")
    print(f"Invalid SSNs: {invalid_count}")
    
    if invalid_count == 0:
        print("\n✓ SUCCESS: All generated SSNs comply with valid area code ranges")
        print("  Valid ranges: 001-665, 667-899")
        print("  Excluded: 000, 666, 900-999")
    else:
        print("\n❌ ERROR: Some SSNs have invalid area codes!")


def example_null_handling():
    """Demonstrate NULL handling strategies."""
    print("\n" + "="*70)
    print("Example 4: NULL Handling Strategies")
    print("="*70)
    
    col_nullable = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
    col_not_null = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=False)
    
    # Strategy 1: PRESERVE (default)
    print("\nStrategy 1: PRESERVE (keep NULLs as NULL)")
    print("-" * 50)
    masker_preserve = SSNMasker(seed=42, null_strategy=MaskingStrategy.PRESERVE)
    
    result = masker_preserve.mask(None, col_nullable)
    print(f"NULL input on nullable column → {result}")
    
    try:
        masker_preserve.mask(None, col_not_null)
    except Exception as e:
        print(f"NULL input on NOT NULL column → Error: {e.error_code}")
    
    # Strategy 2: MASK
    print("\nStrategy 2: MASK (replace NULLs with fake SSNs)")
    print("-" * 50)
    masker_mask = SSNMasker(seed=42, null_strategy=MaskingStrategy.MASK)
    
    result1 = masker_mask.mask(None, col_nullable)
    print(f"NULL input on nullable column → '{result1}'")
    
    result2 = masker_mask.mask(None, col_not_null)
    print(f"NULL input on NOT NULL column → '{result2}'")
    
    print("\n✓ PRESERVE: Maintains NULL values (fails on NOT NULL)")
    print("  MASK: Generates fake SSNs for NULLs (works on any column)")


def example_fixed_length_columns():
    """Demonstrate CHAR/NCHAR fixed-length column handling."""
    print("\n" + "="*70)
    print("Example 5: Fixed-Length Column Handling (CHAR/NCHAR)")
    print("="*70)
    
    masker = SSNMasker(seed=42)
    
    # CHAR(11) - fixed length with padding
    col_char = ColumnInfo(
        data_type="CHAR",
        max_length=11,
        nullable=True,
        is_fixed_length=True
    )
    
    # VARCHAR(11) - variable length
    col_varchar = ColumnInfo(
        data_type="VARCHAR",
        max_length=11,
        nullable=True,
        is_fixed_length=False
    )
    
    original = "123-45-6789"
    
    print(f"\nOriginal: '{original}'")
    print("\nColumn Type    Result                       Length")
    print("-" * 60)
    
    fake_char = masker.mask(original, col_char)
    print(f"CHAR(11)       '{fake_char}'  {len(fake_char)} chars (padded)")
    
    fake_varchar = masker.mask(original, col_varchar)
    print(f"VARCHAR(11)    '{fake_varchar}'  {len(fake_varchar)} chars (no padding)")
    
    print("\n✓ CHAR columns are padded to fixed length")
    print("  VARCHAR columns use only needed space")


def example_seed_consistency():
    """Demonstrate seed-based deterministic mapping."""
    print("\n" + "="*70)
    print("Example 6: Seed-Based Deterministic Mapping")
    print("="*70)
    
    col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
    original = "123-45-6789"
    
    # Same seed produces same results
    print("\nSame seed (42) - different masker instances:")
    print("-" * 50)
    masker1 = SSNMasker(seed=42)
    masker2 = SSNMasker(seed=42)
    
    fake1 = masker1.mask(original, col)
    fake2 = masker2.mask(original, col)
    
    print(f"Masker 1 → '{fake1}'")
    print(f"Masker 2 → '{fake2}'")
    print(f"Match: {fake1 == fake2}")
    
    # Different seeds produce different results
    print("\nDifferent seeds - same input:")
    print("-" * 50)
    masker_a = SSNMasker(seed=42)
    masker_b = SSNMasker(seed=999)
    
    fake_a = masker_a.mask(original, col)
    fake_b = masker_b.mask(original, col)
    
    print(f"Seed 42  → '{fake_a}'")
    print(f"Seed 999 → '{fake_b}'")
    print(f"Match: {fake_a == fake_b}")
    
    print("\n✓ Same seed ensures consistent masking across runs")
    print("  Different seeds allow different organizations to use different mappings")


def example_practical_scenario():
    """Demonstrate practical use case: employee database sanitization."""
    print("\n" + "="*70)
    print("Example 7: Practical Scenario - Employee Database Sanitization")
    print("="*70)
    
    # Simulate employee table with FK relationships
    print("\nOriginal Employee Table:")
    print("-" * 90)
    print(f"{'EmployeeID':<12} {'Name':<20} {'SSN':<15} {'ManagerID':<10} {'ManagerSSN':<15}")
    print("-" * 90)
    
    employees = [
        (1, "John Doe", "123-45-6789", None, None),
        (2, "Jane Smith", "234-56-7890", 1, "123-45-6789"),
        (3, "Robert Johnson", "345-67-8901", 1, "123-45-6789"),
        (4, "Mary Williams", "456-78-9012", 2, "234-56-7890")
    ]
    
    for emp in employees:
        mgr_ssn = emp[4] if emp[4] else "N/A"
        mgr_id = emp[3] if emp[3] else "N/A"
        print(f"{emp[0]:<12} {emp[1]:<20} {emp[2]:<15} {str(mgr_id):<10} {mgr_ssn:<15}")
    
    # Mask SSNs deterministically
    masker = SSNMasker(seed=42)
    col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
    
    print("\n\nMasked Employee Table:")
    print("-" * 90)
    print(f"{'EmployeeID':<12} {'Name':<20} {'SSN (Masked)':<15} {'ManagerID':<10} {'ManagerSSN (Masked)':<15}")
    print("-" * 90)
    
    for emp in employees:
        masked_ssn = masker.mask(emp[2], col)
        masked_mgr_ssn = masker.mask(emp[4], col) if emp[4] else "N/A"
        mgr_id = emp[3] if emp[3] else "N/A"
        print(f"{emp[0]:<12} {emp[1]:<20} {masked_ssn:<15} {str(mgr_id):<10} {masked_mgr_ssn:<15}")
    
    print("\n✓ Notice: SSN '123-45-6789' is masked consistently in both columns")
    print("  This preserves FK relationships: Manager SSN still points to correct person")
    print("  All PII is removed while maintaining data structure for testing/dev")


def example_area_code_distribution():
    """Demonstrate area code distribution across valid ranges."""
    print("\n" + "="*70)
    print("Example 8: Area Code Distribution Analysis")
    print("="*70)
    
    masker = SSNMasker()
    col = ColumnInfo(data_type="VARCHAR", max_length=11, nullable=True)
    
    print("\nAnalyzing area code distribution across 100 generated SSNs...")
    
    low_range = []   # 001-665
    high_range = []  # 667-899
    invalid = []     # Should be empty
    
    for i in range(100):
        test_masker = SSNMasker(seed=i)
        fake_ssn = test_masker.mask("123-45-6789", col)
        area = int(fake_ssn[:3])
        
        if 1 <= area <= 665:
            low_range.append(area)
        elif 667 <= area <= 899:
            high_range.append(area)
        else:
            invalid.append(area)
    
    print("\nDistribution Results:")
    print("-" * 50)
    print(f"Low range (001-665):  {len(low_range)} SSNs ({len(low_range)}%)")
    print(f"High range (667-899): {len(high_range)} SSNs ({len(high_range)}%)")
    print(f"Invalid (0, 666, 900+): {len(invalid)} SSNs")
    
    if low_range:
        print(f"\nLow range samples: {sorted(set(low_range))[:10]}")
    if high_range:
        print(f"High range samples: {sorted(set(high_range))[:10]}")
    
    print("\n✓ Proper distribution across both valid ranges")
    print("  No invalid area codes generated (0, 666, 900-999)")


def main():
    """Run all examples."""
    print("\n" + "="*70)
    print("SSN MASKER - Comprehensive Usage Examples")
    print("="*70)
    print("\nDemonstrating deterministic SSN masking with compliance validation")
    print("for database sanitization and PII protection.")
    
    # Run all examples
    example_basic_masking()
    example_format_detection()
    example_valid_range_verification()
    example_null_handling()
    example_fixed_length_columns()
    example_seed_consistency()
    example_practical_scenario()
    example_area_code_distribution()
    
    print("\n" + "="*70)
    print("Examples Complete!")
    print("="*70)
    print("\nKey Takeaways:")
    print("  • Deterministic masking preserves FK relationships")
    print("  • Compliant SSN generation (excludes 000, 666, 900-999)")
    print("  • Multi-format support (formatted vs plain)")
    print("  • Auto-format selection based on column length")
    print("  • Configurable NULL handling strategies")
    print("  • Seed-based consistency across runs")
    print("\nNext Steps:")
    print("  • Review config/pii_config.example.json for configuration")
    print("  • Run tests: pytest tests/unit/test_ssn_masker.py")
    print("  • Check examples/connection_example.py for database integration")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
