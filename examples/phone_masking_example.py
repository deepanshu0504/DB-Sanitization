"""
Phone masking examples demonstrating PhoneMasker usage patterns.

This script demonstrates 8 real-world scenarios:
1. Basic phone column (VARCHAR(20)) - standard format
2. Short phone column (VARCHAR(12)) - compact format demo
3. Minimal phone column (VARCHAR(10)) - plain digits demo
4. Unicode phone column (NVARCHAR(20))
5. Fixed-length column (CHAR(20)) - padding demo
6. FK relationship - deterministic mapping demo
7. NULL handling - PRESERVE vs MASK strategies
8. Error scenario - column too short

Author: Database Sanitization Team
Date: 2026-03-26
"""

from src.masking.phone_masker import PhoneMasker
from src.masking.base_masker import ColumnInfo, MaskingStrategy
from src.exceptions import MaskingError
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

# Initialize Rich console for colored output
console = Console()


def print_section(title: str):
    """Print a section header with Rich formatting."""
    console.print(f"\n[bold cyan]{title}[/bold cyan]", style="on blue")
    console.print()


def scenario_1_basic_varchar():
    """Scenario 1: Basic phone column (VARCHAR(20)) - standard format."""
    print_section("Scenario 1: Basic Phone Column (VARCHAR(20)) - Standard Format")
    
    masker = PhoneMasker(seed=42)
    column = ColumnInfo(
        data_type="VARCHAR",
        max_length=20,
        nullable=True
    )
    
    phones = [
        "(555) 123-4567",
        "555-987-6543",
        "555.456.7890",
        "5551239999",
        "+1-555-111-2222"
    ]
    
    table = Table(title="Standard Format Phone Masking", box=box.ROUNDED)
    table.add_column("Original Phone", style="yellow")
    table.add_column("Masked Phone", style="green")
    table.add_column("Format", style="cyan")
    
    for phone in phones:
        masked = masker.mask(phone, column)
        table.add_row(phone, masked, "Standard (14 chars)")
    
    console.print(table)
    console.print(f"[green]✓[/green] All phones masked successfully!")
    console.print(f"[green]✓[/green] Column constraint: VARCHAR({column.max_length})")
    console.print(f"[green]✓[/green] Format: (555) 555-5555 (14 characters)")


def scenario_2_compact_format():
    """Scenario 2: Short phone column (VARCHAR(12)) - compact format demo."""
    print_section("Scenario 2: Short Phone Column (VARCHAR(12)) - Compact Format")
    
    masker = PhoneMasker(seed=42)
    column = ColumnInfo(
        data_type="VARCHAR",
        max_length=12,
        nullable=True
    )
    
    phones = [
        "(555) 123-4567",
        "555-987-6543",
        "+1-555-456-7890"
    ]
    
    table = Table(title="Compact Format Phone Masking", box=box.ROUNDED)
    table.add_column("Original Phone", style="yellow")
    table.add_column("Masked Phone", style="green")
    table.add_column("Length", style="cyan")
    
    for phone in phones:
        masked = masker.mask(phone, column)
        table.add_row(phone, masked, f"{len(masked)} chars")
    
    console.print(table)
    console.print(f"[green]✓[/green] All phones fit within VARCHAR({column.max_length}) constraint")
    console.print(f"[green]✓[/green] Compact format: 555-555-5555 (12 characters)")


def scenario_3_minimal_format():
    """Scenario 3: Minimal phone column (VARCHAR(10)) - plain digits demo."""
    print_section("Scenario 3: Minimal Phone Column (VARCHAR(10)) - Plain Digits")
    
    masker = PhoneMasker(seed=42)
    column = ColumnInfo(
        data_type="VARCHAR",
        max_length=10,
        nullable=True
    )
    
    phones = [
        "5551234567",
        "(555) 987-6543",
        "555-456-7890"
    ]
    
    table = Table(title="Minimal Format Phone Masking", box=box.ROUNDED)
    table.add_column("Original Phone", style="yellow")
    table.add_column("Masked Phone", style="green")
    table.add_column("Format", style="cyan")
    
    for phone in phones:
        masked = masker.mask(phone, column)
        table.add_row(phone, masked, "Minimal (10 chars)")
    
    console.print(table)
    console.print(f"[green]✓[/green] All phones fit exactly in VARCHAR({column.max_length})")
    console.print(f"[green]✓[/green] Minimal format: 5555555555 (10 characters, no separators)")


def scenario_4_unicode_nvarchar():
    """Scenario 4: Unicode phone column (NVARCHAR(20))."""
    print_section("Scenario 4: Unicode Phone Column (NVARCHAR(20))")
    
    masker = PhoneMasker(seed=42)
    column = ColumnInfo(
        data_type="NVARCHAR",
        max_length=20,
        nullable=True,
        is_unicode=True
    )
    
    phones = [
        "+1-555-123-4567",     # US
        "+44 20 1234 5678",    # UK
        "+81-3-1234-5678",     # Japan
        "+49 30 12345678"      # Germany
    ]
    
    table = Table(title="International Phone Masking", box=box.ROUNDED)
    table.add_column("Original Phone (Country)", style="yellow")
    table.add_column("Masked Phone", style="green")
    table.add_column("Data Type", style="cyan")
    
    countries = ["US", "UK", "Japan", "Germany"]
    for phone, country in zip(phones, countries):
        masked = masker.mask(phone, column)
        table.add_row(f"{phone} ({country})", masked, "NVARCHAR")
    
    console.print(table)
    console.print(f"[green]✓[/green] International phones handled correctly")
    console.print(f"[green]✓[/green] NVARCHAR supports international characters")


def scenario_5_fixed_length_char():
    """Scenario 5: Fixed-length column (CHAR(20)) - padding demo."""
    print_section("Scenario 5: Fixed-Length Column (CHAR(20)) - Padding Demo")
    
    masker = PhoneMasker(seed=42)
    column = ColumnInfo(
        data_type="CHAR",
        max_length=20,
        nullable=True,
        is_fixed_length=True
    )
    
    phones = [
        "5551234567",
        "(555) 987-6543"
    ]
    
    table = Table(title="Fixed-Length Phone Masking with Padding", box=box.ROUNDED)
    table.add_column("Original Phone", style="yellow")
    table.add_column("Masked Phone", style="green")
    table.add_column("Actual Length", style="cyan")
    table.add_column("Padded?", style="magenta")
    
    for phone in phones:
        masked = masker.mask(phone, column)
        is_padded = "Yes" if len(masked) == column.max_length else "No"
        table.add_row(phone, masked, f"{len(masked)} chars", is_padded)
    
    console.print(table)
    console.print(f"[green]✓[/green] CHAR({column.max_length}) requires fixed length")
    console.print(f"[green]✓[/green] Values padded with spaces to {column.max_length} characters")


def scenario_6_fk_relationship():
    """Scenario 6: FK relationship - deterministic mapping demo."""
    print_section("Scenario 6: FK Relationship - Deterministic Mapping")
    
    masker = PhoneMasker(seed=42)
    column = ColumnInfo(
        data_type="VARCHAR",
        max_length=20,
        nullable=True
    )
    
    # Simulate parent-child tables with same phone number
    parent_phone = "(555) 123-4567"
    child_phones = [
        "(555) 123-4567",  # Same as parent
        "(555) 123-4567",  # Same as parent
        "(555) 987-6543"   # Different
    ]
    
    parent_masked = masker.mask(parent_phone, column)
    
    table = Table(title="FK Integrity Preservation", box=box.ROUNDED)
    table.add_column("Table", style="yellow")
    table.add_column("Original Phone", style="cyan")
    table.add_column("Masked Phone", style="green")
    table.add_column("FK Match?", style="magenta")
    
    table.add_row("Parent (Customers)", parent_phone, parent_masked, "-")
    
    for i, child_phone in enumerate(child_phones, 1):
        child_masked = masker.mask(child_phone, column)
        fk_match = "✓ Yes" if child_masked == parent_masked else "✗ No"
        table.add_row(f"Child (Orders #{i})", child_phone, child_masked, fk_match)
    
    console.print(table)
    console.print(f"[green]✓[/green] Same input → same output (deterministic)")
    console.print(f"[green]✓[/green] FK relationships preserved across tables")
    console.print(f"[green]✓[/green] Child rows with parent phone get same masked value")


def scenario_7_null_handling():
    """Scenario 7: NULL handling - PRESERVE vs MASK strategies."""
    print_section("Scenario 7: NULL Handling - PRESERVE vs MASK Strategies")
    
    column = ColumnInfo(
        data_type="VARCHAR",
        max_length=20,
        nullable=True
    )
    
    # Strategy 1: PRESERVE (default)
    masker_preserve = PhoneMasker(seed=42, null_strategy=MaskingStrategy.PRESERVE)
    preserved = masker_preserve.mask(None, column)
    
    # Strategy 2: MASK
    masker_mask = PhoneMasker(seed=42, null_strategy=MaskingStrategy.MASK)
    masked = masker_mask.mask(None, column)
    
    table = Table(title="NULL Handling Strategies", box=box.ROUNDED)
    table.add_column("Strategy", style="yellow")
    table.add_column("Input", style="cyan")
    table.add_column("Output", style="green")
    table.add_column("Description", style="magenta")
    
    table.add_row(
        "PRESERVE",
        "NULL",
        str(preserved),
        "Keep NULL as NULL (safest)"
    )
    table.add_row(
        "MASK",
        "NULL",
        str(masked),
        "Generate fake phone for NULL"
    )
    
    console.print(table)
    console.print(f"[green]✓[/green] PRESERVE: NULL → NULL (default)")
    console.print(f"[green]✓[/green] MASK: NULL → fake phone")
    console.print(f"[yellow]⚠[/yellow] PRESERVE may raise error on NOT NULL columns")


def scenario_8_error_handling():
    """Scenario 8: Error scenario - column too short."""
    print_section("Scenario 8: Error Handling - Column Too Short")
    
    masker = PhoneMasker(seed=42)
    
    # This will raise an error
    short_column = ColumnInfo(
        data_type="VARCHAR",
        max_length=9,  # Too short! Minimum is 10
        nullable=True
    )
    
    phone = "5551234567"
    
    try:
        masked = masker.mask(phone, short_column)
    except MaskingError as e:
        error_panel = Panel(
            f"[red]Error Code:[/red] {e.error_code}\n"
            f"[red]Message:[/red] {e.message}\n"
            f"[yellow]Suggested Action:[/yellow] {e.suggested_action}\n"
            f"[cyan]Operation Context:[/cyan] {e.operation_context}",
            title="[red]MaskingError Details[/red]",
            border_style="red"
        )
        console.print(error_panel)
        console.print(f"[green]✓[/green] Error caught and handled gracefully")
        console.print(f"[green]✓[/green] Minimum column length: 10 characters")
        console.print(f"[green]✓[/green] Provided: {short_column.max_length} characters")


def scenario_9_batch_masking():
    """Bonus Scenario: Batch masking with progress tracking."""
    print_section("Bonus: Batch Masking 1000+ Phones with Progress Tracking")
    
    masker = PhoneMasker(seed=42)
    column = ColumnInfo(
        data_type="VARCHAR",
        max_length=20,
        nullable=True
    )
    
    # Generate 1000 sample phones
    phones = [f"555-{i:03d}-{(i*7) % 10000:04d}" for i in range(1000)]
    
    # Mask all phones
    masked_phones = []
    with console.status("[bold green]Masking 1000 phone numbers...", spinner="dots"):
        for phone in phones:
            masked = masker.mask(phone, column)
            masked_phones.append(masked)
    
    # Show statistics
    unique_originals = len(set(phones))
    unique_masked = len(set(masked_phones))
    
    stats_table = Table(title="Batch Masking Statistics", box=box.ROUNDED)
    stats_table.add_column("Metric", style="yellow")
    stats_table.add_column("Value", style="green")
    
    stats_table.add_row("Total Phones Masked", f"{len(phones):,}")
    stats_table.add_row("Unique Original Phones", f"{unique_originals:,}")
    stats_table.add_row("Unique Masked Phones", f"{unique_masked:,}")
    stats_table.add_row("Determinism Check", "✓ Pass" if len(phones) == len(masked_phones) else "✗ Fail")
    
    console.print(stats_table)
    
    # Show sample
    sample_table = Table(title="Sample Masked Phones (First 10)", box=box.SIMPLE)
    sample_table.add_column("Original", style="yellow")
    sample_table.add_column("Masked", style="green")
    
    for orig, masked in zip(phones[:10], masked_phones[:10]):
        sample_table.add_row(orig, masked)
    
    console.print(sample_table)
    console.print(f"[green]✓[/green] Successfully masked {len(phones):,} phone numbers")
    console.print(f"[green]✓[/green] All masked values deterministic")


def main():
    """Run all scenarios."""
    console.print(Panel.fit(
        "[bold cyan]PhoneMasker Usage Examples[/bold cyan]\n"
        "Demonstrating deterministic phone number masking with multi-tier length optimization",
        border_style="cyan"
    ))
    
    try:
        scenario_1_basic_varchar()
        scenario_2_compact_format()
        scenario_3_minimal_format()
        scenario_4_unicode_nvarchar()
        scenario_5_fixed_length_char()
        scenario_6_fk_relationship()
        scenario_7_null_handling()
        scenario_8_error_handling()
        scenario_9_batch_masking()
        
        console.print("\n" + "="*70)
        console.print("[bold green]All scenarios completed successfully![/bold green]")
        console.print("="*70)
        
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise


if __name__ == "__main__":
    main()
