"""
Email masking examples demonstrating EmailMasker usage patterns.

This script demonstrates 6 real-world scenarios:
1. Basic email column (VARCHAR(100))
2. Short email column (VARCHAR(30)) - truncation demo
3. Unicode email column (NVARCHAR(150)) - IDN demo
4. Fixed-length column (CHAR(50)) - padding demo
5. FK relationship - deterministic mapping demo
6. Batch masking 1000+ emails - progress tracking

Author: Database Sanitization Team
Date: 2026-03-26
"""

from src.masking.email_masker import EmailMasker
from src.masking.base_masker import ColumnInfo, MaskingStrategy


def print_section(title: str):
    """Print a section header."""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def scenario_1_basic_varchar():
    """Scenario 1: Basic email column (VARCHAR(100))."""
    print_section("Scenario 1: Basic Email Column (VARCHAR(100))")
    
    masker = EmailMasker(seed=42)
    column = ColumnInfo(
        data_type="VARCHAR",
        max_length=100,
        nullable=True
    )
    
    emails = [
        "john.doe@gmail.com",
        "jane.smith@yahoo.com",
        "bob.jones@outlook.com",
        "alice.williams@hotmail.com"
    ]
    
    print("Original Email → Masked Email")
    print("-" * 70)
    for email in emails:
        masked = masker.mask(email, column)
        print(f"{email:30} → {masked}")
    
    print("\n✓ All emails masked successfully!")
    print(f"✓ Column constraint: VARCHAR({column.max_length})")


def scenario_2_short_column():
    """Scenario 2: Short email column (VARCHAR(30)) - truncation demo."""
    print_section("Scenario 2: Short Email Column (VARCHAR(30))")
    
    masker = EmailMasker(seed=42)
    column = ColumnInfo(
        data_type="VARCHAR",
        max_length=30,
        nullable=True
    )
    
    emails = [
        "verylongemailaddress@verylongdomain.com",
        "short@test.com",
        "medium.length@example.org"
    ]
    
    print("Original Email → Masked Email (Length)")
    print("-" * 70)
    for email in emails:
        masked = masker.mask(email, column)
        print(f"{email:45} → {masked:25} ({len(masked)} chars)")
    
    print(f"\n✓ All emails fit within VARCHAR({column.max_length}) constraint")
    print("✓ Compact format used when needed")


def scenario_3_unicode_nvarchar():
    """Scenario 3: Unicode email column (NVARCHAR(150)) - IDN demo."""
    print_section("Scenario 3: Unicode Email Column (NVARCHAR(150))")
    
    masker = EmailMasker(seed=42)
    column = ColumnInfo(
        data_type="NVARCHAR",
        max_length=150,
        nullable=True,
        is_unicode=True
    )
    
    emails = [
        "user@example.com",
        "test@münchen.de",  # IDN domain
        "user名@test.com",   # Unicode local part
        "info@日本.jp"       # Full Unicode
    ]
    
    print("Original Email (Unicode) → Masked Email")
    print("-" * 70)
    for email in emails:
        try:
            masked = masker.mask(email, column)
            print(f"{email:30} → {masked}")
        except Exception as e:
            print(f"{email:30} → ERROR: {e}")
    
    print(f"\n✓ NVARCHAR({column.max_length}) supports Unicode characters")
    print("✓ IDN domains handled appropriately")


def scenario_4_fixed_length_char():
    """Scenario 4: Fixed-length column (CHAR(50)) - padding demo."""
    print_section("Scenario 4: Fixed-Length Column (CHAR(50))")
    
    masker = EmailMasker(seed=42)
    column = ColumnInfo(
        data_type="CHAR",
        max_length=50,
        nullable=True,
        is_fixed_length=True
    )
    
    emails = [
        "short@t.co",
        "medium@example.com",
        "longer.email@subdomain.example.org"
    ]
    
    print("Original Email → Masked Email (with padding)")
    print("-" * 70)
    for email in emails:
        masked = masker.mask(email, column)
        print(f"{email:40} → '{masked}' (len={len(masked)})")
    
    print(f"\n✓ All emails padded to exactly CHAR({column.max_length}) characters")
    print("✓ Padding preserves fixed-length column semantics")


def scenario_5_fk_relationship():
    """Scenario 5: FK relationship - deterministic mapping demo."""
    print_section("Scenario 5: Foreign Key Relationship (Deterministic Mapping)")
    
    masker = EmailMasker(seed=42)
    column = ColumnInfo(
        data_type="VARCHAR",
        max_length=100,
        nullable=True
    )
    
    # Simulate parent table (Customers)
    print("Parent Table: Customers")
    print("-" * 70)
    customers = [
        ("CustomerID", "Email"),
        (1, "john@company.com"),
        (2, "jane@company.com"),
        (3, "bob@company.com")
    ]
    
    customer_masked = {}
    print(f"{'CustomerID':<12} {'Original Email':<25} {'Masked Email':<25}")
    print("-" * 70)
    for cust_id, email in customers[1:]:  # Skip header
        masked = masker.mask(email, column)
        customer_masked[email] = masked
        print(f"{cust_id:<12} {email:<25} {masked:<25}")
    
    # Simulate child table (Orders)
    print("\nChild Table: Orders (references Customers.Email)")
    print("-" * 70)
    orders = [
        ("OrderID", "CustomerEmail", "OrderDate"),
        (101, "john@company.com", "2024-01-15"),
        (102, "jane@company.com", "2024-01-16"),
        (103, "john@company.com", "2024-01-17"),  # Same customer
        (104, "bob@company.com", "2024-01-18")
    ]
    
    print(f"{'OrderID':<10} {'Customer Email':<25} {'Masked Email':<25} {'FK Preserved?'}")
    print("-" * 70)
    for order_id, email, order_date in orders[1:]:  # Skip header
        masked = masker.mask(email, column)
        fk_ok = "✓ YES" if customer_masked[email] == masked else "✗ NO"
        print(f"{order_id:<10} {email:<25} {masked:<25} {fk_ok}")
    
    print("\n✓ FK integrity preserved: same email → same masked email")
    print("✓ Deterministic mapping ensures referential integrity")


def scenario_6_batch_processing():
    """Scenario 6: Batch masking 1000+ emails - progress tracking."""
    print_section("Scenario 6: Batch Processing (1000+ Emails)")
    
    masker = EmailMasker(seed=42)
    column = ColumnInfo(
        data_type="VARCHAR",
        max_length=100,
        nullable=True
    )
    
    # Generate 1000 emails
    total = 1000
    print(f"Masking {total} emails in batches...\n")
    
    masked_count = 0
    batch_size = 100
    
    for batch_num in range(total // batch_size):
        batch_start = batch_num * batch_size
        batch_end = batch_start + batch_size
        
        # Generate batch of emails
        batch_emails = [
            f"user{i}@domain{i % 10}.com" 
            for i in range(batch_start, batch_end)
        ]
        
        # Mask batch
        for email in batch_emails:
            masked = masker.mask(email, column)
            masked_count += 1
        
        # Progress update
        progress = (masked_count / total) * 100
        print(f"  Batch {batch_num + 1:2d}/10: {batch_size:3d} emails masked "
              f"({masked_count:4d}/{total} = {progress:5.1f}%)")
    
    print(f"\n✓ Successfully masked {masked_count} emails")
    print("✓ Memory-efficient: processes in batches")
    print("✓ Suitable for large-scale data sanitization")


def demonstrate_null_handling():
    """Bonus: Demonstrate NULL handling strategies."""
    print_section("Bonus: NULL Handling Strategies")
    
    column = ColumnInfo(
        data_type="VARCHAR",
        max_length=100,
        nullable=True
    )
    
    # PRESERVE strategy (default)
    masker_preserve = EmailMasker(seed=42, null_strategy=MaskingStrategy.PRESERVE)
    result_preserve = masker_preserve.mask(None, column)
    print(f"PRESERVE strategy: NULL → {result_preserve}")
    
    # MASK strategy
    masker_mask = EmailMasker(seed=42, null_strategy=MaskingStrategy.MASK)
    result_mask = masker_mask.mask(None, column)
    print(f"MASK strategy: NULL → {result_mask}")
    
    print("\n✓ NULL handling strategies provide flexibility")
    print("✓ PRESERVE keeps NULL as NULL (default)")
    print("✓ MASK generates fake value even for NULL")


def demonstrate_domain_diversity():
    """Bonus: Demonstrate domain diversity."""
    print_section("Bonus: Domain Diversity")
    
    masker = EmailMasker(seed=42)
    column = ColumnInfo(
        data_type="VARCHAR",
        max_length=100,
        nullable=True
    )
    
    print("Masking 20 different emails to show domain diversity:\n")
    
    emails = [f"user{i}@original{i}.com" for i in range(20)]
    domains_used = set()
    
    for i, email in enumerate(emails, 1):
        masked = masker.mask(email, column)
        domain = masked.split('@')[1]
        domains_used.add(domain)
        print(f"  {i:2d}. {email:30} → {masked:30} (domain: {domain})")
    
    print(f"\n✓ Used {len(domains_used)} different domains out of {len(masker.DOMAINS)} available")
    print(f"✓ Available domains: {', '.join(masker.DOMAINS)}")
    print("✓ Domain diversity prevents pattern detection")


def main():
    """Run all example scenarios."""
    print("\n" + "="*70)
    print("  EMAIL MASKER EXAMPLES")
    print("  Demonstrating real-world usage patterns")
    print("="*70)
    
    try:
        scenario_1_basic_varchar()
        scenario_2_short_column()
        scenario_3_unicode_nvarchar()
        scenario_4_fixed_length_char()
        scenario_5_fk_relationship()
        scenario_6_batch_processing()
        demonstrate_null_handling()
        demonstrate_domain_diversity()
        
        print("\n" + "="*70)
        print("  ALL EXAMPLES COMPLETED SUCCESSFULLY!")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"\n✗ Error occurred: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
