"""
Production-ready sanitization script with Smart Generation.

This script uses the full framework with all maskers implementing
Smart Generation for constraint-aware fake value generation.

Key Features:
- Smart Generation: All fake values fit column constraints (no truncation)
- Professional maskers: Email, Phone, Name, SSN, Generic
- Foreign key handling: Preserves referential integrity
- Comprehensive error handling and reporting
- Checkpoint support: Resume from failures

Usage:
    # Dry-run (recommended first)
    python run_sanitization.py config/pii_config_ai_generated.json
    
    # Actual sanitization (after setting dry_run=false in config)
    python run_sanitization.py config/pii_config_ai_generated.json

Author: Database Sanitization Team
Date: 2026-03-28
"""

import sys
from pathlib import Path
from datetime import datetime

from src.config.config_loader import ConfigLoader
from src.sanitization.orchestrator import SanitizationOrchestrator
from src.exceptions import (
    ConfigValidationError,
    DatabaseError,
    ValidationError,
    CircularDependencyError
)


def print_header():
    """Print script header."""
    print("=" * 80)
    print("DATABASE SANITIZATION WITH SMART GENERATION")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


def load_configuration(config_path: str):
    """
    Load configuration from file.
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        SanitizationConfig object
        
    Raises:
        ConfigValidationError: If configuration is invalid
    """
    print(f"[1/6] Loading configuration")
    print(f"  File: {config_path}")
    
    if not Path(config_path).exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    config_loader = ConfigLoader()
    config = config_loader.load_from_file(config_path)
    
    print(f"  ✓ Server: {config.database.server}")
    print(f"  ✓ Database: {config.database.database}")
    print(f"  ✓ Auth Type: {config.database.auth_type}")
    print(f"  ✓ PII Columns: {len(config.pii_columns)}")
    print(f"  ✓ Batch Size: {config.database.batch_size}")
    print(f"  ✓ Dry Run: {config.dry_run}")
    
    return config


def confirm_execution(config):
    """
    Get user confirmation before execution.
    
    Args:
        config: SanitizationConfig object
        
    Returns:
        True if user confirms, False otherwise
    """
    print(f"\n[2/6] Execution confirmation")
    
    if config.dry_run:
        print(f"  ✓ Dry-run mode: No database changes will be made")
        print(f"    (Configuration validation and preview only)")
        return True
    
    print(f"  ⚠️  WARNING: DRY_RUN IS FALSE")
    print(f"  ⚠️  THIS WILL MODIFY YOUR DATABASE!")
    print(f"  ⚠️  All PII data will be replaced with fake data!")
    print()
    
    response = input("  Do you want to continue? (yes/no): ")
    if response.lower() != 'yes':
        print("\n  Aborted by user.")
        return False
    
    return True


def check_backup(config):
    """
    Verify user has database backup.
    
    Args:
        config: SanitizationConfig object
        
    Returns:
        True if backup confirmed or dry-run, False otherwise
    """
    print(f"\n[3/6] Backup verification")
    
    if config.dry_run:
        print(f"  ⊘ Skipped (dry-run mode)")
        return True
    
    print(f"  ⚠️  IMPORTANT: Ensure you have a recent database backup!")
    print(f"  ⚠️  Sanitization is irreversible without backup!")
    print()
    
    response = input("  Do you have a current backup? (yes/no): ")
    if response.lower() != 'yes':
        print("\n  Please create a backup first. Aborted.")
        return False
    
    print(f"  ✓ Backup confirmed")
    return True


def initialize_orchestrator():
    """
    Initialize the sanitization orchestrator.
    
    Returns:
        SanitizationOrchestrator instance
        
    Raises:
        Exception: If orchestrator initialization fails
    """
    print(f"\n[4/6] Initializing sanitization orchestrator")
    
    orchestrator = SanitizationOrchestrator()
    
    print(f"  ✓ Orchestrator created")
    print(f"  ✓ Checkpoint directory: {orchestrator.checkpoint_dir}")
    print(f"  ✓ Smart Generation: Enabled (all maskers)")
    
    return orchestrator


def run_sanitization(orchestrator, config):
    """
    Execute the sanitization process.
    
    Args:
        orchestrator: SanitizationOrchestrator instance
        config: SanitizationConfig object
        
    Returns:
        SanitizationReport object
        
    Raises:
        Various exceptions for different failure scenarios
    """
    print(f"\n[5/6] Running sanitization")
    print(f"  Mode: {'DRY-RUN (no changes)' if config.dry_run else 'ACTUAL EXECUTION'}")
    print(f"  This may take several minutes for large databases...")
    print()
    
    start_time = datetime.now()
    
    try:
        report = orchestrator.run(config)
    except KeyboardInterrupt:
        duration = (datetime.now() - start_time).total_seconds()
        print(f"\n\n⚠️  Sanitization interrupted by user after {duration:.1f}s")
        print(f"  A checkpoint may have been saved.")
        print(f"  Check orchestrator documentation for resume instructions.")
        raise
    
    return report


def display_results(report, config):
    """
    Display sanitization results.
    
    Args:
        report: SanitizationReport object
        config: SanitizationConfig object
    """
    print(f"\n[6/6] Results")
    print("=" * 80)
    
    # Status header
    status_icon = "✅" if report.is_successful else "❌"
    status_text = "COMPLETED SUCCESSFULLY" if report.is_successful else "FAILED"
    print(f"{status_icon} SANITIZATION {status_text}")
    print("=" * 80)
    
    # Basic info
    print(f"\nOperation Details:")
    print(f"  Status: {report.phase.value if hasattr(report.phase, 'value') else report.phase}")
    print(f"  Operation ID: {report.operation_id}")
    print(f"  Duration: {report.duration_seconds:.2f}s")
    if config.dry_run:
        print(f"  Mode: DRY-RUN (no actual changes made)")
    
    # Table statistics
    print(f"\nTables:")
    print(f"  ✓ Completed: {report.tables_completed}")
    if report.tables_failed > 0:
        print(f"  ✗ Failed: {report.tables_failed}")
    if report.tables_skipped > 0:
        print(f"  ⊘ Skipped: {report.tables_skipped}")
    print(f"  Total: {report.total_tables}")
    
    # Data statistics
    print(f"\nData Processing:")
    print(f"  Rows processed: {report.rows_processed:,}")
    if hasattr(report, 'rows_masked') and report.rows_masked:
        print(f"  Values masked: {report.rows_masked:,}")
    
    # Smart Generation metrics (KEY FEATURE!)
    print(f"\nSmart Generation Status:")
    truncations = getattr(report, 'total_truncations', 0)
    if truncations == 0:
        print(f"  ✅ ZERO truncations detected!")
        print(f"     All fake values fit perfectly within column constraints")
        print(f"     Smart Generation working correctly")
    else:
        print(f"  ⚠️  {truncations} truncations detected")
        print(f"     This indicates a potential Smart Generation bug")
        print(f"     Please review truncation details below")
        
        # Show truncation details if available
        if hasattr(report, 'truncation_details') and report.truncation_details:
            print(f"\n  Truncation Details:")
            for table_name, details in list(report.truncation_details.items())[:5]:
                print(f"    Table: {table_name}")
                if isinstance(details, list):
                    for detail in details[:3]:
                        if isinstance(detail, dict):
                            col = detail.get('column', 'unknown')
                            count = detail.get('count', 0)
                            print(f"      Column: {col}, Count: {count}")
    
    # Errors
    if report.errors:
        print(f"\n❌ Errors ({len(report.errors)}):")
        for error in report.errors[:10]:  # Show first 10
            print(f"   - {error}")
        if len(report.errors) > 10:
            print(f"   ... and {len(report.errors) - 10} more errors")
    
    # Warnings
    if report.warnings:
        print(f"\n⚠️  Warnings ({len(report.warnings)}):")
        for warning in report.warnings[:10]:  # Show first 10
            print(f"   - {warning}")
        if len(report.warnings) > 10:
            print(f"   ... and {len(report.warnings) - 10} more warnings")
    
    # Final summary
    print()
    print("=" * 80)
    if report.is_successful:
        if config.dry_run:
            print("✅ Dry-run completed successfully!")
            print("   Review the results above, then set dry_run=false to execute.")
        else:
            print("✅ Sanitization completed successfully!")
            print("   All PII data has been replaced with fake data.")
    else:
        print("❌ Sanitization failed!")
        print(f"   Review the error messages above for details.")
    print("=" * 80)


def main():
    """Main entry point."""
    # Check arguments
    if len(sys.argv) < 2:
        print("Usage: python run_sanitization.py <config_file>")
        print()
        print("Examples:")
        print("  python run_sanitization.py config/pii_config_ai_generated.json")
        print("  python run_sanitization.py config/pii_config.production.json")
        print()
        sys.exit(1)
    
    config_path = sys.argv[1]
    
    try:
        # Print header
        print_header()
        
        # Load configuration
        config = load_configuration(config_path)
        
        # Confirm execution
        if not confirm_execution(config):
            sys.exit(0)
        
        # Check backup
        if not check_backup(config):
            sys.exit(0)
        
        # Initialize orchestrator
        orchestrator = initialize_orchestrator()
        
        # Run sanitization
        report = run_sanitization(orchestrator, config)
        
        # Display results
        display_results(report, config)
        
        # Exit with appropriate code
        sys.exit(0 if report.is_successful else 1)
        
    except FileNotFoundError as e:
        print(f"\n❌ File Error: {e}")
        sys.exit(1)
        
    except ConfigValidationError as e:
        print(f"\n❌ Configuration Error: {e.message}")
        if hasattr(e, 'suggested_action') and e.suggested_action:
            print(f"   Suggested Action: {e.suggested_action}")
        sys.exit(1)
        
    except ValidationError as e:
        print(f"\n❌ Validation Error: {e.message}")
        if hasattr(e, 'suggested_action') and e.suggested_action:
            print(f"   Suggested Action: {e.suggested_action}")
        sys.exit(1)
        
    except CircularDependencyError as e:
        print(f"\n❌ Circular Dependency Error: {e.message}")
        if hasattr(e, 'tables_in_cycle'):
            print(f"   Tables in cycle: {', '.join(e.tables_in_cycle)}")
        if hasattr(e, 'suggested_action') and e.suggested_action:
            print(f"   Suggested Action: {e.suggested_action}")
        sys.exit(1)
        
    except DatabaseError as e:
        print(f"\n❌ Database Error: {e.message}")
        if hasattr(e, 'error_code'):
            print(f"   Error Code: {e.error_code.name if hasattr(e.error_code, 'name') else e.error_code}")
        if hasattr(e, 'suggested_action') and e.suggested_action:
            print(f"   Suggested Action: {e.suggested_action}")
        sys.exit(1)
        
    except KeyboardInterrupt:
        print(f"\n\nInterrupted by user.")
        sys.exit(130)  # Standard exit code for SIGINT
        
    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")
        print(f"\nStack trace:")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
