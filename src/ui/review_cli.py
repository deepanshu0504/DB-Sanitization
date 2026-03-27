"""
Interactive CLI for reviewing and managing PII column configurations.

This module provides the PIIReviewCLI class for an interactive terminal interface
that allows users to review AI-detected PII columns, manually add/remove columns,
modify configurations, and save finalized sanitization configs.

Author: Database Sanitization Team
Date: 2026-03-26
"""

import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from copy import deepcopy

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.text import Text

from ..ai.models import PIIColumn
from ..config.config_models import PIIColumnConfig
from ..database.schema_extractor import SchemaExtractor
from ..logging.logger import get_logger
from .formatters import (
    format_pii_table,
    format_config_table,
    format_summary_panel,
    format_validation_results,
    format_help_panel,
    format_column_detail
)

logger = get_logger(__name__)


class PIIReviewCLI:
    """
    Interactive command-line interface for reviewing PII column configurations.
    
    This class provides a menu-driven interface for:
    - Reviewing AI-detected PII columns
    - Adding new PII columns manually
    - Removing columns from the configuration
    - Modifying PII types and nullable flags
    - Validating columns against database schema
    - Saving finalized configurations to JSON
    
    Attributes:
        console (Console): Rich console for terminal output
        schema_extractor (Optional[SchemaExtractor]): For schema validation
        pii_configs (List[PIIColumnConfig]): Current PII configurations
        original_configs (List[PIIColumnConfig]): Backup for undo functionality
        history (List[Tuple[str, Any]]): Action history for undo
        stats (Dict[str, int]): Statistics for summary display
    
    Example:
        >>> cli = PIIReviewCLI(schema_extractor=extractor)
        >>> final_configs = cli.review_recommendations(ai_detected_pii)
        >>> # User interacts with menu, returns finalized list
    """
    
    # Supported PII types (aligned with AI model and sanitization logic)
    SUPPORTED_PII_TYPES = [
        "EMAIL",
        "PHONE",
        "SSN",
        "CREDIT_CARD",
        "NAME",
        "ADDRESS",
        "DATE_OF_BIRTH",
        "IP_ADDRESS",
        "ACCOUNT_NUMBER",
        "CUSTOM"
    ]
    
    def __init__(
        self,
        schema_extractor: Optional[SchemaExtractor] = None,
        console: Optional[Console] = None
    ):
        """
        Initialize PIIReviewCLI.
        
        Args:
            schema_extractor: Optional SchemaExtractor for validation
            console: Optional Rich Console (creates new if None)
        """
        self.console = console or Console()
        self.schema_extractor = schema_extractor
        self.pii_configs: List[PIIColumnConfig] = []
        self.original_configs: List[PIIColumnConfig] = []
        self.history: List[Tuple[str, Any]] = []
        self.stats = {
            "ai_detected": 0,
            "manually_added": 0,
            "removed": 0,
            "modified": 0
        }
        
        logger.info("PIIReviewCLI initialized")
    
    def review_recommendations(
        self,
        pii_columns: List[PIIColumn],
        existing_config: Optional[List[PIIColumnConfig]] = None
    ) -> List[PIIColumnConfig]:
        """
        Main entry point for interactive PII review session.
        
        Args:
            pii_columns: AI-detected PII columns to review
            existing_config: Optional existing configuration to merge with
        
        Returns:
            Finalized list of PIIColumnConfig objects
        
        Raises:
            KeyboardInterrupt: If user cancels with Ctrl+C
        
        Example:
            >>> final_configs = cli.review_recommendations(ai_pii_columns)
            >>> # Interactive session begins
        """
        logger.info(f"Starting PII review session with {len(pii_columns)} AI recommendations")
        
        # Convert PII columns to configs (deduplication handled in AIClient)
        self.pii_configs = self._convert_to_configs(pii_columns)
        self.stats["ai_detected"] = len(self.pii_configs)
        
        # Merge with existing config if provided
        if existing_config:
            self._merge_existing_config(existing_config)
        
        # Backup for undo
        self.original_configs = deepcopy(self.pii_configs)
        
        # Display welcome banner
        self._display_welcome()
        
        # Main interaction loop
        try:
            while True:
                self._display_current_state()
                action = self._show_menu()
                
                if action == "quit":
                    if self._confirm_quit():
                        logger.info("User quit without saving")
                        return []
                elif action == "save":
                    logger.info(f"User saved {len(self.pii_configs)} PII configs")
                    return self.pii_configs
                elif action == "add":
                    self._handle_add()
                elif action == "remove":
                    self._handle_remove()
                elif action == "modify":
                    self._handle_modify()
                elif action == "undo":
                    self._handle_undo()
                elif action == "help":
                    self._display_help()
                else:
                    self.console.print(f"[red]Unknown action: {action}[/red]")
                
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Session cancelled by user[/yellow]")
            logger.warning("PII review session cancelled via KeyboardInterrupt")
            return []
    
    def _convert_to_configs(self, pii_columns: List[PIIColumn]) -> List[PIIColumnConfig]:
        """
        Convert PIIColumn objects to PIIColumnConfig objects.
        
        Args:
            pii_columns: List of AI-detected PII columns
        
        Returns:
            List of PIIColumnConfig objects
        """
        configs = []
        for col in pii_columns:
            config = PIIColumnConfig(
                schema=col.schema,
                table=col.table,
                column=col.column,
                pii_type=col.pii_type,
                nullable=True  # Default to True, user can modify
            )
            configs.append(config)
        
        return configs
    
    def _merge_existing_config(self, existing: List[PIIColumnConfig]) -> None:
        """
        Merge existing configuration with AI recommendations.
        
        Args:
            existing: Existing PII column configurations
        """
        existing_keys = {
            (cfg.schema, cfg.table, cfg.column) for cfg in self.pii_configs
        }
        
        for cfg in existing:
            key = (cfg.schema, cfg.table, cfg.column)
            if key not in existing_keys:
                self.pii_configs.append(cfg)
                self.stats["manually_added"] += 1
        
        logger.info(f"Merged {len(existing)} existing configs")
    
    def _display_welcome(self) -> None:
        """Display welcome banner."""
        banner = Panel(
            Text(
                "Welcome to PII Configuration Review\n\n"
                "Review AI-detected PII columns and customize your sanitization configuration.\n"
                "Use the menu commands to add, remove, or modify columns.",
                justify="center"
            ),
            title="[bold magenta]PII Review Interface[/bold magenta]",
            border_style="magenta"
        )
        self.console.print(banner)
        self.console.print()
    
    def _display_current_state(self) -> None:
        """Display current PII configuration state."""
        self.console.clear()
        
        # Display summary
        summary = format_summary_panel(
            total_columns=len(self.pii_configs),
            ai_detected=self.stats["ai_detected"],
            manually_added=self.stats["manually_added"],
            removed=self.stats["removed"],
            modified=self.stats["modified"]
        )
        self.console.print(summary)
        self.console.print()
        
        # Display configuration table
        if self.pii_configs:
            table = format_config_table(self.pii_configs, "Current PII Configuration")
            self.console.print(table)
        else:
            self.console.print("[yellow]No PII columns configured[/yellow]")
        
        self.console.print()
    
    def _show_menu(self) -> str:
        """
        Display menu and get user choice.
        
        Returns:
            Action string: "add", "remove", "modify", "undo", "save", "help", "quit"
        """
        self.console.print("[bold]Commands:[/bold] [cyan][A]dd[/cyan] | [red][R]emove[/red] | "
                          "[yellow][M]odify[/yellow] | [magenta][U]ndo[/magenta] | "
                          "[green][S]ave[/green] | [blue][H]elp[/blue] | [dim][Q]uit[/dim]")
        
        choice = Prompt.ask(
            "Choose action",
            choices=["a", "r", "m", "u", "s", "h", "q"],
            default="s",
            show_choices=False
        ).lower()
        
        action_map = {
            "a": "add",
            "r": "remove",
            "m": "modify",
            "u": "undo",
            "s": "save",
            "h": "help",
            "q": "quit"
        }
        
        return action_map.get(choice, "help")
    
    def _handle_add(self) -> None:
        """Handle adding a new PII column."""
        self.console.print("\n[bold cyan]Add New PII Column[/bold cyan]")
        
        # Get schema, table, column
        schema = Prompt.ask("Schema name", default="dbo")
        table = Prompt.ask("Table name")
        column = Prompt.ask("Column name")
        
        # Validate column exists (if schema extractor available)
        if self.schema_extractor:
            validation_errors, validation_warnings = self._validate_column(schema, table, column)
            
            if validation_errors:
                validation_table = format_validation_results(validation_errors, [])
                self.console.print(validation_table)
                self.console.print("[red]Cannot add column with errors[/red]")
                Prompt.ask("Press Enter to continue")
                return
            
            if validation_warnings:
                validation_table = format_validation_results([], validation_warnings)
                self.console.print(validation_table)
                if not Confirm.ask("Add column anyway?", default=False):
                    return
        
        # Get PII type
        self.console.print("\n[bold]Available PII Types:[/bold]")
        for idx, pii_type in enumerate(self.SUPPORTED_PII_TYPES, 1):
            self.console.print(f"  {idx}. {pii_type}")
        
        pii_type_choice = Prompt.ask(
            "Select PII type",
            choices=[str(i) for i in range(1, len(self.SUPPORTED_PII_TYPES) + 1)],
            default="1"
        )
        pii_type = self.SUPPORTED_PII_TYPES[int(pii_type_choice) - 1]
        
        # Get nullable flag
        nullable = Confirm.ask("Is column nullable?", default=True)
        
        # Create config
        new_config = PIIColumnConfig(
            schema=schema,
            table=table,
            column=column,
            pii_type=pii_type,
            nullable=nullable
        )
        
        # Check for duplicates
        if self._is_duplicate(new_config):
            self.console.print("[red]Column already exists in configuration[/red]")
            Prompt.ask("Press Enter to continue")
            return
        
        # Add to configs
        self.pii_configs.append(new_config)
        self.stats["manually_added"] += 1
        self.history.append(("add", new_config))
        
        self.console.print(f"[green]✓ Added {schema}.{table}.{column} ({pii_type})[/green]")
        logger.info(f"User added PII column: {schema}.{table}.{column}")
        Prompt.ask("Press Enter to continue")
    
    def _handle_remove(self) -> None:
        """Handle removing a PII column."""
        if not self.pii_configs:
            self.console.print("[yellow]No columns to remove[/yellow]")
            Prompt.ask("Press Enter to continue")
            return
        
        self.console.print("\n[bold red]Remove PII Column[/bold red]")
        
        # Display numbered list
        for idx, cfg in enumerate(self.pii_configs, 1):
            self.console.print(f"  {idx}. {cfg.schema}.{cfg.table}.{cfg.column} ({cfg.pii_type})")
        
        choice = Prompt.ask(
            "Select column to remove",
            choices=[str(i) for i in range(1, len(self.pii_configs) + 1)] + ["cancel"],
            default="cancel"
        )
        
        if choice == "cancel":
            return
        
        idx = int(choice) - 1
        removed_config = self.pii_configs.pop(idx)
        self.stats["removed"] += 1
        self.history.append(("remove", (idx, removed_config)))
        
        self.console.print(f"[green]✓ Removed {removed_config.schema}.{removed_config.table}.{removed_config.column}[/green]")
        logger.info(f"User removed PII column: {removed_config.schema}.{removed_config.table}.{removed_config.column}")
        Prompt.ask("Press Enter to continue")
    
    def _handle_modify(self) -> None:
        """Handle modifying a PII column."""
        if not self.pii_configs:
            self.console.print("[yellow]No columns to modify[/yellow]")
            Prompt.ask("Press Enter to continue")
            return
        
        self.console.print("\n[bold yellow]Modify PII Column[/bold yellow]")
        
        # Display numbered list
        for idx, cfg in enumerate(self.pii_configs, 1):
            nullable_str = "✓" if cfg.nullable else "✗"
            self.console.print(f"  {idx}. {cfg.schema}.{cfg.table}.{cfg.column} ({cfg.pii_type}, Nullable: {nullable_str})")
        
        choice = Prompt.ask(
            "Select column to modify",
            choices=[str(i) for i in range(1, len(self.pii_configs) + 1)] + ["cancel"],
            default="cancel"
        )
        
        if choice == "cancel":
            return
        
        idx = int(choice) - 1
        original_config = deepcopy(self.pii_configs[idx])
        
        # Modify PII type
        if Confirm.ask("Change PII type?", default=False):
            self.console.print("\n[bold]Available PII Types:[/bold]")
            for type_idx, pii_type in enumerate(self.SUPPORTED_PII_TYPES, 1):
                marker = "→" if pii_type == original_config.pii_type else " "
                self.console.print(f"  {marker} {type_idx}. {pii_type}")
            
            pii_type_choice = Prompt.ask(
                "Select new PII type",
                choices=[str(i) for i in range(1, len(self.SUPPORTED_PII_TYPES) + 1)],
                default=str(self.SUPPORTED_PII_TYPES.index(original_config.pii_type) + 1)
            )
            self.pii_configs[idx].pii_type = self.SUPPORTED_PII_TYPES[int(pii_type_choice) - 1]
        
        # Modify nullable flag
        if Confirm.ask("Change nullable flag?", default=False):
            self.pii_configs[idx].nullable = Confirm.ask(
                "Is column nullable?",
                default=original_config.nullable
            )
        
        # Track modification
        if self.pii_configs[idx] != original_config:
            self.stats["modified"] += 1
            self.history.append(("modify", (idx, original_config)))
            
            self.console.print(f"[green]✓ Modified {self.pii_configs[idx].schema}.{self.pii_configs[idx].table}.{self.pii_configs[idx].column}[/green]")
            logger.info(f"User modified PII column: {self.pii_configs[idx].schema}.{self.pii_configs[idx].table}.{self.pii_configs[idx].column}")
        else:
            self.console.print("[dim]No changes made[/dim]")
        
        Prompt.ask("Press Enter to continue")
    
    def _handle_undo(self) -> None:
        """Handle undoing the last action."""
        if not self.history:
            self.console.print("[yellow]No actions to undo[/yellow]")
            Prompt.ask("Press Enter to continue")
            return
        
        action, data = self.history.pop()
        
        if action == "add":
            # Undo add: remove the added config
            self.pii_configs.remove(data)
            self.stats["manually_added"] = max(0, self.stats["manually_added"] - 1)
            self.console.print("[green]✓ Undid add operation[/green]")
        
        elif action == "remove":
            # Undo remove: restore the removed config
            idx, config = data
            self.pii_configs.insert(idx, config)
            self.stats["removed"] = max(0, self.stats["removed"] - 1)
            self.console.print("[green]✓ Undid remove operation[/green]")
        
        elif action == "modify":
            # Undo modify: restore original config
            idx, original_config = data
            self.pii_configs[idx] = original_config
            self.stats["modified"] = max(0, self.stats["modified"] - 1)
            self.console.print("[green]✓ Undid modify operation[/green]")
        
        logger.info(f"User undid {action} operation")
        Prompt.ask("Press Enter to continue")
    
    def _display_help(self) -> None:
        """Display help panel."""
        help_panel = format_help_panel()
        self.console.print(help_panel)
        Prompt.ask("Press Enter to continue")
    
    def _validate_column(
        self,
        schema: str,
        table: str,
        column: str
    ) -> Tuple[List[str], List[str]]:
        """
        Validate that a column exists in the database schema.
        
        Args:
            schema: Schema name
            table: Table name
            column: Column name
        
        Returns:
            Tuple of (errors, warnings) as lists of strings
        """
        errors = []
        warnings = []
        
        if not self.schema_extractor:
            return errors, warnings
        
        try:
            # Check if table exists
            tables = self.schema_extractor.get_tables(schema)
            if table not in [t["table_name"] for t in tables]:
                errors.append(f"Table '{schema}.{table}' not found in database")
                return errors, warnings
            
            # Check if column exists
            columns = self.schema_extractor.get_columns(schema, table)
            column_info = next((c for c in columns if c["column_name"].lower() == column.lower()), None)
            
            if not column_info:
                errors.append(f"Column '{column}' not found in table '{schema}.{table}'")
                return errors, warnings
            
            # Generate warnings for special columns
            if column_info.get("is_primary_key"):
                warnings.append(f"Column '{column}' is a PRIMARY KEY - sanitizing may break relationships")
            
            if column_info.get("is_foreign_key"):
                warnings.append(f"Column '{column}' is a FOREIGN KEY - sanitizing may break referential integrity")
            
        except Exception as e:
            logger.error(f"Schema validation failed: {e}")
            warnings.append(f"Schema validation error: {str(e)}")
        
        return errors, warnings
    
    def _is_duplicate(self, config: PIIColumnConfig) -> bool:
        """
        Check if a configuration already exists.
        
        Args:
            config: PIIColumnConfig to check
        
        Returns:
            True if duplicate exists, False otherwise
        """
        for existing in self.pii_configs:
            if (existing.schema == config.schema and
                existing.table == config.table and
                existing.column == config.column):
                return True
        return False
    
    def _confirm_quit(self) -> bool:
        """
        Confirm user wants to quit without saving.
        
        Returns:
            True if user confirms quit, False otherwise
        """
        if not self.history:
            # No changes made, safe to quit
            return True
        
        return Confirm.ask(
            "[yellow]You have unsaved changes. Quit anyway?[/yellow]",
            default=False
        )
    
    def save_to_file(self, output_path: Path) -> None:
        """
        Save current configuration to JSON file.
        
        Args:
            output_path: Path to output JSON file
        
        Raises:
            IOError: If file write fails
        
        Example:
            >>> cli.save_to_file(Path("pii_config.json"))
        """
        try:
            # Convert configs to dict format
            config_dicts = [
                {
                    "schema": cfg.schema,
                    "table": cfg.table,
                    "column": cfg.column,
                    "pii_type": cfg.pii_type,
                    "nullable": cfg.nullable
                }
                for cfg in self.pii_configs
            ]
            
            # Write to file
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(config_dicts, f, indent=2)
            
            logger.info(f"Saved {len(self.pii_configs)} PII configs to {output_path}")
            self.console.print(f"[green]✓ Configuration saved to {output_path}[/green]")
        
        except Exception as e:
            logger.error(f"Failed to save config to {output_path}: {e}")
            raise IOError(f"Failed to save configuration: {e}") from e
