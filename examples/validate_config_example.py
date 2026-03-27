"""
Example: Configuration Schema Validation

This example demonstrates how to use the ConfigValidator to validate PII
configuration files against actual database schema before sanitization begins.

The workflow:
1. Load configuration from JSON
2. Connect to database
3. Extract schema metadata
4. Validate configuration
5. Display results with color-coded output
6. Save validation report

Author: Database Sanitization Team
Date: 2026-03-26
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.connection_manager import DatabaseConnectionManager
from src.database.schema_extractor import SchemaExtractor
from src.validation import ConfigValidator, ValidationResult, IssueSeverity
from src.config.config_loader import ConfigLoader
from src.logging.logger import setup_logging


def print_colored(text: str, color: str = "white") -> None:
    """Print colored text to console."""
    colors = {
        "red": "\033[91m",
        "yellow": "\033[93m",
        "green": "\033[92m",
        "cyan": "\033[96m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "white": "\033[97m",
        "reset": "\033[0m"
    }
    print(f"{colors.get(color, colors['white'])}{text}{colors['reset']}")


def display_validation_results(result: ValidationResult) -> None:
    """
    Display validation results with color-coded output.
    
    Args:
        result: ValidationResult to display
    """
    print("\n" + "=" * 70)
    
    if result.is_valid:
        print_colored("✓ VALIDATION PASSED", "green")
    else:
        print_colored("✗ VALIDATION FAILED", "red")
    
    print("=" * 70)
    
    print(f"\nSummary:")
    print(f"  Total Issues: {result.total_issue_count}")
    
    if result.error_count > 0:
        print_colored(f"  Errors:   {result.error_count}", "red")
    else:
        print(f"  Errors:   {result.error_count}")
    
    if result.warning_count > 0:
        print_colored(f"  Warnings: {result.warning_count}", "yellow")
    else:
        print(f"  Warnings: {result.warning_count}")
    
    if result.info_count > 0:
        print_colored(f"  Info:     {result.info_count}", "cyan")
    else:
        print(f"  Info:     {result.info_count}")
    
    # Display errors
    if result.errors:
        print("\n" + "-" * 70)
        print_colored("ERRORS:", "red")
        print("-" * 70)
        for error in result.errors:
            print_colored(f"  • {error}", "red")
    
    # Display warnings
    if result.warnings:
        print("\n" + "-" * 70)
        print_colored("WARNINGS:", "yellow")
        print("-" * 70)
        for warning in result.warnings:
            print_colored(f"  • {warning}", "yellow")
    
    # Display info messages
    if result.infos:
        print("\n" + "-" * 70)
        print_colored("INFO:", "cyan")
        print("-" * 70)
        for info in result.infos:
            print_colored(f"  • {info}", "cyan")
    
    print("\n" + "=" * 70)


def save_validation_report(
    result: ValidationResult,
    output_path: Path,
    config_path: str
) -> None:
    """
    Save validation report to JSON file.
    
    Args:
        result: ValidationResult to save
        output_path: Path to output JSON file
        config_path: Path to validated configuration file
    """
    report = {
        "timestamp": datetime.now().isoformat(),
        "config_file": str(config_path),
        "validation_status": "PASSED" if result.is_valid else "FAILED",
        "summary": {
            "total_issues": result.total_issue_count,
            "errors": result.error_count,
            "warnings": result.warning_count,
            "infos": result.info_count
        },
        "results": result.to_dict()
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    
    print_colored(f"\n✓ Validation report saved to: {output_path}", "green")


def main():
    """
    Main function demonstrating configuration validation workflow.
    """
    # Setup logging
    setup_logging("INFO")
    
    print_colored("=" * 70, "magenta")
    print_colored("Configuration Schema Validation Example", "magenta")
    print_colored("=" * 70, "magenta")
    print()
    
    # Configuration file to validate
    config_file = "config/pii_config.example.json"
    
    # Check if config file exists
    if not Path(config_file).exists():
        print_colored(f"✗ Configuration file not found: {config_file}", "red")
        print_colored("  Create a configuration file first", "yellow")
        sys.exit(1)
    
    try:
        # Load configuration
        print(f"Loading configuration from: {config_file}")
        config_loader = ConfigLoader(config_file)
        config = config_loader.load()
        print_colored(f"✓ Loaded configuration with {len(config.pii_columns)} PII columns", "green")
        
        # Initialize database connection
        print("\nConnecting to database...")
        connection_manager = ConnectionManager(config.database)
        
        # Test connection
        with connection_manager.get_connection() as conn:
            print_colored(f"✓ Connected to: {config.database.server}/{config.database.database}", "green")
        
        # Extract schema metadata
        print("\nExtracting database schema...")
        schema_extractor = SchemaExtractor(connection_manager)
        
        schemas = schema_extractor.get_schemas()
        print_colored(f"✓ Found {len(schemas)} schemas in database", "green")
        
        # Initialize validator
        print("\nInitializing configuration validator...")
        validator = ConfigValidator(schema_extractor, strict_mode=False)
        print_colored("✓ Validator ready", "green")
        
        # Validate configuration
        print("\n" + "=" * 70)
        print_colored("VALIDATING CONFIGURATION...", "cyan")
        print("=" * 70)
        
        result = validator.validate_config(config)
        
        # Display results
        display_validation_results(result)
        
        # Save validation report
        report_path = Path("output/validation_report.json")
        save_validation_report(result, report_path, config_file)
        
        # Exit with appropriate code
        if result.is_valid:
            print_colored("\n✓ Configuration is valid and ready for sanitization", "green")
            sys.exit(0)
        else:
            print_colored("\n✗ Fix validation errors before proceeding with sanitization", "red")
            sys.exit(1)
    
    except KeyboardInterrupt:
        print_colored("\n\n⚠ Validation cancelled by user", "yellow")
        sys.exit(1)
    
    except Exception as e:
        print_colored("\n\n✗ Validation failed with error:", "red")
        print_colored(f"   {str(e)}", "red")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    finally:
        # Cleanup
        if 'connection_manager' in locals():
            connection_manager.close_all()
            print("\n✓ Database connections closed")


if __name__ == "__main__":
    main()
