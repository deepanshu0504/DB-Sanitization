"""
Rich terminal formatting utilities for PII review interface.

This module provides functions to format PII column data, validation results,
and summaries using the Rich library for beautiful terminal output.

Author: Database Sanitization Team
Date: 2026-03-26
"""

from typing import Dict, List, Any, Optional

from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from ..ai.models import PIIColumn
from ..config.config_models import PIIColumnConfig


def format_pii_table(
    pii_columns: List[PIIColumn],
    title: str = "PII Columns"
) -> Table:
    """
    Format PII columns as a Rich table.
    
    Args:
        pii_columns: List of PIIColumn instances to display
        title: Table title (default: "PII Columns")
    
    Returns:
        Rich Table object ready for display
    
    Example:
        >>> table = format_pii_table(pii_columns, "AI Detected PII")
        >>> console.print(table)
    """
    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title_style="bold magenta",
        expand=True
    )
    
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Schema.Table", style="cyan", no_wrap=True)
    table.add_column("Column", style="green")
    table.add_column("PII Type", style="yellow")
    table.add_column("Confidence", justify="right", style="blue")
    
    for idx, col in enumerate(pii_columns, 1):
        table_name = f"{col.schema}.{col.table}"
        confidence_str = f"{col.confidence:.0%}" if col.confidence else "—"
        
        table.add_row(
            str(idx),
            table_name,
            col.column,
            col.pii_type,
            confidence_str
        )
    
    return table


def format_config_table(
    pii_configs: List[PIIColumnConfig],
    title: str = "Configuration"
) -> Table:
    """
    Format PII column configurations as a Rich table.
    
    Args:
        pii_configs: List of PIIColumnConfig instances to display
        title: Table title (default: "Configuration")
    
    Returns:
        Rich Table object ready for display
    
    Example:
        >>> table = format_config_table(configs, "Current Configuration")
        >>> console.print(table)
    """
    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title_style="bold magenta",
        expand=True
    )
    
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Schema.Table", style="cyan", no_wrap=True)
    table.add_column("Column", style="green")
    table.add_column("PII Type", style="yellow")
    table.add_column("Nullable", justify="center", style="blue")
    
    for idx, config in enumerate(pii_configs, 1):
        table_name = f"{config.schema}.{config.table}"
        nullable_str = "✓" if config.nullable else "✗"
        
        table.add_row(
            str(idx),
            table_name,
            config.column,
            config.pii_type,
            nullable_str
        )
    
    return table


def format_summary_panel(
    total_columns: int,
    ai_detected: int,
    manually_added: int,
    removed: int,
    modified: int
) -> Panel:
    """
    Format summary statistics as a Rich panel.
    
    Args:
        total_columns: Total number of PII columns in current config
        ai_detected: Number of AI-detected columns
        manually_added: Number of manually added columns
        removed: Number of removed columns
        modified: Number of modified columns
    
    Returns:
        Rich Panel object with formatted summary
    
    Example:
        >>> panel = format_summary_panel(10, 8, 2, 1, 3)
        >>> console.print(panel)
    """
    summary_text = Text()
    summary_text.append("Total PII Columns: ", style="bold")
    summary_text.append(f"{total_columns}\n", style="bold green")
    
    summary_text.append("  • AI Detected: ", style="dim")
    summary_text.append(f"{ai_detected}\n", style="cyan")
    
    if manually_added > 0:
        summary_text.append("  • Manually Added: ", style="dim")
        summary_text.append(f"{manually_added}\n", style="green")
    
    if removed > 0:
        summary_text.append("  • Removed: ", style="dim")
        summary_text.append(f"{removed}\n", style="red")
    
    if modified > 0:
        summary_text.append("  • Modified: ", style="dim")
        summary_text.append(f"{modified}\n", style="yellow")
    
    panel = Panel(
        summary_text,
        title="[bold]Summary[/bold]",
        border_style="blue",
        padding=(1, 2)
    )
    
    return panel


def format_validation_results(
    errors: List[str],
    warnings: List[str]
) -> Table:
    """
    Format validation errors and warnings as a Rich table.
    
    Args:
        errors: List of error messages
        warnings: List of warning messages
    
    Returns:
        Rich Table object with validation results
    
    Example:
        >>> table = format_validation_results(
        ...     errors=["Column 'email' not found"],
        ...     warnings=["Column 'ID' is a primary key"]
        ... )
        >>> console.print(table)
    """
    table = Table(
        title="Validation Results",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
        expand=True
    )
    
    table.add_column("Type", width=10)
    table.add_column("Message")
    
    for error in errors:
        table.add_row("ERROR", error, style="bold red")
    
    for warning in warnings:
        table.add_row("WARNING", warning, style="bold yellow")
    
    if not errors and not warnings:
        table.add_row("SUCCESS", "All validations passed", style="bold green")
    
    return table


def format_help_panel() -> Panel:
    """
    Format help text as a Rich panel.
    
    Returns:
        Rich Panel object with command help
    
    Example:
        >>> panel = format_help_panel()
        >>> console.print(panel)
    """
    help_text = Text()
    
    help_text.append("Commands:\n\n", style="bold underline")
    
    help_text.append("  [A]dd     ", style="bold cyan")
    help_text.append("— Add a new PII column\n")
    
    help_text.append("  [R]emove  ", style="bold red")
    help_text.append("— Remove a PII column from the list\n")
    
    help_text.append("  [M]odify  ", style="bold yellow")
    help_text.append("— Modify PII type or nullable flag\n")
    
    help_text.append("  [U]ndo    ", style="bold magenta")
    help_text.append("— Undo last action\n")
    
    help_text.append("  [S]ave    ", style="bold green")
    help_text.append("— Save configuration to file\n")
    
    help_text.append("  [H]elp    ", style="bold blue")
    help_text.append("— Show this help message\n")
    
    help_text.append("  [Q]uit    ", style="bold dim")
    help_text.append("— Exit without saving\n")
    
    panel = Panel(
        help_text,
        title="[bold]Help[/bold]",
        border_style="blue",
        padding=(1, 2)
    )
    
    return panel


def format_column_detail(
    schema: str,
    table: str,
    column: str,
    data_type: str,
    nullable: bool,
    is_pk: bool = False,
    is_fk: bool = False,
    fk_reference: Optional[str] = None
) -> Panel:
    """
    Format detailed column information as a Rich panel.
    
    Args:
        schema: Schema name
        table: Table name
        column: Column name
        data_type: SQL Server data type
        nullable: Whether column allows NULL
        is_pk: Whether column is a primary key
        is_fk: Whether column is a foreign key
        fk_reference: Foreign key reference (e.g., "Users.UserID")
    
    Returns:
        Rich Panel object with column details
    
    Example:
        >>> panel = format_column_detail(
        ...     "dbo", "Orders", "CustomerID", "INT", False,
        ...     is_fk=True, fk_reference="Customers.CustomerID"
        ... )
        >>> console.print(panel)
    """
    detail_text = Text()
    
    detail_text.append(f"{schema}.{table}.{column}\n\n", style="bold cyan")
    
    detail_text.append("Data Type: ", style="dim")
    detail_text.append(f"{data_type}\n", style="yellow")
    
    detail_text.append("Nullable: ", style="dim")
    nullable_str = "Yes ✓" if nullable else "No ✗"
    detail_text.append(f"{nullable_str}\n", style="green" if nullable else "red")
    
    if is_pk:
        detail_text.append("\n⚠ ", style="bold yellow")
        detail_text.append("This column is a PRIMARY KEY\n", style="bold yellow")
    
    if is_fk:
        detail_text.append("\n⚠ ", style="bold yellow")
        detail_text.append("This column is a FOREIGN KEY\n", style="bold yellow")
        if fk_reference:
            detail_text.append(f"   References: {fk_reference}\n", style="dim")
    
    panel = Panel(
        detail_text,
        title="[bold]Column Details[/bold]",
        border_style="cyan",
        padding=(1, 2)
    )
    
    return panel
