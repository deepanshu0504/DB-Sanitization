"""
Desensitization Engine usage examples.

This module demonstrates various desensitization (reverse sanitization) scenarios:
- Example 1: Basic full restoration
- Example 2: Dry-run mode for safety testing
- Example 3: Partial restoration (specific tables)
- Example 4: Progress tracking with callbacks
- Example 5: Custom configuration
- Example 6: Error handling and recovery
- Example 7: Batch restoration workflow
- Example 8: Integration with orchestrator

Author: Database Sanitization Team
Date: 2026-03-27
"""

import os
from uuid import UUID, uuid4
from datetime import datetime

from src.database.connection_manager import DatabaseConnectionManager
from src.database.connection_config import DatabaseConnectionConfig
from src.mapping.mapping_manager import MappingManager
from src.mapping.mapping_config import MappingConfig
from src.sanitization.desensitizer import Desensitizer, DesensitizationConfig, RestorePhase
from src.exceptions import DesensitizationError


def create_connection_manager():
    """Helper to create database connection manager."""
    db_config = DatabaseConnectionConfig(
        server=os.getenv("DB_SERVER", "localhost"),
        database=os.getenv("DB_NAME", "ProductionDB"),
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        driver="{ODBC Driver 17 for SQL Server}"
    )
    return DatabaseConnectionManager(db_config)


def create_mapping_manager(conn_mgr):
    """Helper to create mapping manager."""
    mapping_config = MappingConfig(
        server=os.getenv("DB_SERVER", "localhost"),
        database=os.getenv("DB_NAME", "ProductionDB"),
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        table_name="dbo.PII_Mapping",
        enable_encryption=True,
        batch_size=1000
    )
    return MappingManager(conn_mgr, mapping_config)


# ---------------------------------------------------------
# Example 1: Basic Full Restoration
# ---------------------------------------------------------

def example_1_basic_full_restoration():
    """
    Restore all PII values from a sanitization operation.
    
    Use case: Restoring production data for debugging or auditing purposes.
    """
    print("=" * 80)
    print("Example 1: Basic Full Restoration")
    print("=" * 80)
    
    # Initialize components
    conn_mgr = create_connection_manager()
    mapping_mgr = create_mapping_manager(conn_mgr)
    
    desensitizer = Desensitizer(
        connection_manager=conn_mgr,
        mapping_manager=mapping_mgr
    )
    
    # Operation ID from previous sanitization
    operation_id = UUID("12345678-1234-5678-1234-567812345678")
    
    print(f"\nRestoring data for operation: {operation_id}")
    print("-" * 80)
    
    # Execute restoration
    report = desensitizer.restore(operation_id)
    
    # Display results
    print(f"\nRestoration completed!")
    print(f"  Phase: {report.phase.value}")
    print(f"  Tables restored: {report.tables_restored}")
    print(f"  Rows restored: {report.rows_restored:,}")
    print(f"  Values restored: {report.values_restored:,}")
    print(f"  Duration: {report.duration_ms:,} ms")
    print(f"  Success: {report.is_successful()}")
    
    if report.warnings:
        print(f"\nWarnings ({len(report.warnings)}):")
        for warning in report.warnings:
            print(f"  - {warning}")
    
    if report.errors:
        print(f"\nErrors ({len(report.errors)}):")
        for error in report.errors:
            print(f"  - {error}")
    
    # Display per-table progress
    print(f"\nPer-Table Progress:")
    print("-" * 80)
    for table_name, progress in report.table_progress.items():
        print(f"  {table_name}:")
        print(f"    Rows restored: {progress.rows_restored:,}")
        print(f"    Columns: {', '.join(progress.columns_restored)}")
        if progress.errors:
            print(f"    Errors: {len(progress.errors)}")


# ---------------------------------------------------------
# Example 2: Dry-Run Mode
# ---------------------------------------------------------

def example_2_dry_run_mode():
    """
    Test restoration without making changes (validation only).
    
    Use case: Verify feasibility before actual restoration.
    """
    print("\n\n" + "=" * 80)
    print("Example 2: Dry-Run Mode (Validation Only)")
    print("=" * 80)
    
    conn_mgr = create_connection_manager()
    mapping_mgr = create_mapping_manager(conn_mgr)
    
    desensitizer = Desensitizer(
        connection_manager=conn_mgr,
        mapping_manager=mapping_mgr
    )
    
    operation_id = UUID("12345678-1234-5678-1234-567812345678")
    
    print(f"\nRunning dry-run validation for operation: {operation_id}")
    print("-" * 80)
    
    # Execute dry-run
    report = desensitizer.restore(operation_id, dry_run=True)
    
    print(f"\nDry-run completed!")
    print(f"  Would restore {report.tables_restored} tables")
    print(f"  Would restore {report.rows_restored:,} rows")
    print(f"  Would restore {report.values_restored:,} values")
    print(f"  Validation: {'PASSED' if report.is_successful() else 'FAILED'}")
    
    if report.warnings:
        print(f"\n⚠ Warnings detected:")
        for warning in report.warnings:
            print(f"  - {warning}")
    
    if report.errors:
        print(f"\n❌ Errors detected:")
        for error in report.errors:
            print(f"  - {error}")
    else:
        print(f"\n✓ No errors detected. Safe to proceed with actual restoration.")


# ---------------------------------------------------------
# Example 3: Partial Restoration
# ---------------------------------------------------------

def example_3_partial_restoration():
    """
    Restore specific tables only (selective restoration).
    
    Use case: Restore only critical tables for targeted debugging.
    """
    print("\n\n" + "=" * 80)
    print("Example 3: Partial Restoration (Specific Tables)")
    print("=" * 80)
    
    conn_mgr = create_connection_manager()
    mapping_mgr = create_mapping_manager(conn_mgr)
    
    desensitizer = Desensitizer(
        connection_manager=conn_mgr,
        mapping_manager=mapping_mgr,
        config=DesensitizationConfig(allow_partial_restore=True)
    )
    
    operation_id = UUID("12345678-1234-5678-1234-567812345678")
    
    # Specify tables to restore
    tables_to_restore = [
        "dbo.Customers",
        "dbo.Orders"
    ]
    
    print(f"\nRestoring specific tables:")
    for table in tables_to_restore:
        print(f"  - {table}")
    print("-" * 80)
    
    # Execute partial restoration
    report = desensitizer.restore(
        operation_id=operation_id,
        tables=tables_to_restore
    )
    
    print(f"\nPartial restoration completed!")
    print(f"  Tables restored: {report.tables_restored}/{len(tables_to_restore)}")
    print(f"  Rows restored: {report.rows_restored:,}")
    print(f"  Success: {report.is_successful()}")
    
    # Show which tables were restored
    print(f"\nRestored tables:")
    for table_name in report.table_progress.keys():
        print(f"  ✓ {table_name}")


# ---------------------------------------------------------
# Example 4: Progress Tracking with Callbacks
# ---------------------------------------------------------

def example_4_progress_tracking():
    """
    Track restoration progress with real-time callbacks.
    
    Use case: Monitor large restoration operations.
    """
    print("\n\n" + "=" * 80)
    print("Example 4: Progress Tracking with Callbacks")
    print("=" * 80)
    
    conn_mgr = create_connection_manager()
    mapping_mgr = create_mapping_manager(conn_mgr)
    
    desensitizer = Desensitizer(
        connection_manager=conn_mgr,
        mapping_manager=mapping_mgr
    )
    
    # Define progress callbacks
    def batch_progress(table_name, rows_processed, total_rows, percentage):
        """Callback for batch-level progress."""
        print(f"  [{table_name}] Processed {rows_processed:,}/{total_rows:,} rows ({percentage:.1f}%)")
    
    def table_event(event_type, table_name):
        """Callback for table-level events."""
        if event_type == "start":
            print(f"\n→ Starting restoration: {table_name}")
        elif event_type == "complete":
            print(f"✓ Completed restoration: {table_name}")
    
    # Register callbacks
    desensitizer.set_progress_callback(batch_progress)
    desensitizer.set_table_callback(table_event)
    
    operation_id = UUID("12345678-1234-5678-1234-567812345678")
    
    print(f"\nRestoring with real-time progress tracking...")
    print("-" * 80)
    
    # Execute restoration with callbacks
    report = desensitizer.restore(operation_id)
    
    print(f"\n" + "=" * 80)
    print(f"Restoration summary:")
    print(f"  Total tables: {report.tables_restored}")
    print(f"  Total rows: {report.rows_restored:,}")
    print(f"  Duration: {report.duration_ms:,} ms")


# ---------------------------------------------------------
# Example 5: Custom Configuration
# ---------------------------------------------------------

def example_5_custom_configuration():
    """
    Use custom configuration for specialized restoration scenarios.
    
    Use case: Fine-tune restoration behavior for specific requirements.
    """
    print("\n\n" + "=" * 80)
    print("Example 5: Custom Configuration")
    print("=" * 80)
    
    conn_mgr = create_connection_manager()
    mapping_mgr = create_mapping_manager(conn_mgr)
    
    # Custom configuration
    custom_config = DesensitizationConfig(
        allow_partial_restore=True,
        verify_before_restore=True,          # Enable verification
        fail_on_mismatch=True,                # Strict mode - fail on any mismatch
        checkpoint_enabled=True,              # Per-table savepoints
        max_mismatch_percentage=5.0,          # Allow up to 5% mismatches
        sample_size_for_validation=1000       # Validate 1000 rows
    )
    
    print("\nCustom configuration:")
    print(f"  Allow partial restore: {custom_config.allow_partial_restore}")
    print(f"  Verify before restore: {custom_config.verify_before_restore}")
    print(f"  Fail on mismatch: {custom_config.fail_on_mismatch}")
    print(f"  Checkpoint enabled: {custom_config.checkpoint_enabled}")
    print(f"  Max mismatch %: {custom_config.max_mismatch_percentage}%")
    print(f"  Sample size: {custom_config.sample_size_for_validation}")
    
    desensitizer = Desensitizer(
        connection_manager=conn_mgr,
        mapping_manager=mapping_mgr,
        config=custom_config
    )
    
    operation_id = UUID("12345678-1234-5678-1234-567812345678")
    
    print(f"\nRestoring with custom configuration...")
    print("-" * 80)
    
    # Execute restoration
    report = desensitizer.restore(operation_id)
    
    print(f"\nRestoration completed!")
    print(f"  Success: {report.is_successful()}")
    print(f"  Tables restored: {report.tables_restored}")
    print(f"  Rows restored: {report.rows_restored:,}")


# ---------------------------------------------------------
# Example 6: Error Handling and Recovery
# ---------------------------------------------------------

def example_6_error_handling():
    """
    Demonstrate error handling and graceful recovery.
    
    Use case: Handle failures during restoration operations.
    """
    print("\n\n" + "=" * 80)
    print("Example 6: Error Handling and Recovery")
    print("=" * 80)
    
    conn_mgr = create_connection_manager()
    mapping_mgr = create_mapping_manager(conn_mgr)
    
    desensitizer = Desensitizer(
        connection_manager=conn_mgr,
        mapping_manager=mapping_mgr,
        config=DesensitizationConfig(fail_on_mismatch=False)  # Graceful handling
    )
    
    operation_id = UUID("12345678-1234-5678-1234-567812345678")
    
    print(f"\nAttempting restoration with error handling...")
    print("-" * 80)
    
    try:
        report = desensitizer.restore(operation_id)
        
        if report.is_successful():
            print(f"\n✓ Restoration successful!")
            print(f"  Tables restored: {report.tables_restored}")
            print(f"  Rows restored: {report.rows_restored:,}")
        else:
            print(f"\n⚠ Restoration completed with errors:")
            print(f"  Tables restored: {report.tables_restored}")
            print(f"  Tables failed: {report.tables_failed}")
            print(f"  Tables skipped: {report.tables_skipped}")
            
            if report.errors:
                print(f"\nErrors encountered:")
                for error in report.errors:
                    print(f"  - {error}")
            
            if report.warnings:
                print(f"\nWarnings:")
                for warning in report.warnings:
                    print(f"  - {warning}")
    
    except DesensitizationError as e:
        print(f"\n❌ Desensitization error: {e}")
        print(f"  Error code: {e.error_code}")
        print(f"  Suggested action: {e.suggested_action}")
    
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")


# ---------------------------------------------------------
# Example 7: Batch Restoration Workflow
# ---------------------------------------------------------

def example_7_batch_restoration_workflow():
    """
    Restore multiple operations in batch.
    
    Use case: Bulk restoration of multiple sanitization operations.
    """
    print("\n\n" + "=" * 80)
    print("Example 7: Batch Restoration Workflow")
    print("=" * 80)
    
    conn_mgr = create_connection_manager()
    mapping_mgr = create_mapping_manager(conn_mgr)
    
    desensitizer = Desensitizer(
        connection_manager=conn_mgr,
        mapping_manager=mapping_mgr
    )
    
    # Multiple operations to restore
    operation_ids = [
        UUID("12345678-1234-5678-1234-567812345671"),
        UUID("12345678-1234-5678-1234-567812345672"),
        UUID("12345678-1234-5678-1234-567812345673")
    ]
    
    print(f"\nRestoring {len(operation_ids)} operations in batch...")
    print("-" * 80)
    
    results = []
    
    for i, operation_id in enumerate(operation_ids, 1):
        print(f"\n[{i}/{len(operation_ids)}] Restoring operation: {operation_id}")
        
        try:
            report = desensitizer.restore(operation_id)
            results.append((operation_id, report, None))
            
            print(f"  ✓ Success: {report.tables_restored} tables, {report.rows_restored:,} rows")
        
        except Exception as e:
            results.append((operation_id, None, str(e)))
            print(f"  ❌ Failed: {e}")
    
    # Summary
    print(f"\n" + "=" * 80)
    print(f"Batch restoration summary:")
    print(f"  Total operations: {len(operation_ids)}")
    print(f"  Successful: {sum(1 for _, report, _ in results if report is not None)}")
    print(f"  Failed: {sum(1 for _, _, error in results if error is not None)}")
    
    total_rows = sum(report.rows_restored for _, report, _ in results if report is not None)
    print(f"  Total rows restored: {total_rows:,}")


# ---------------------------------------------------------
# Example 8: Integration with Orchestrator
# ---------------------------------------------------------

def example_8_orchestrator_integration():
    """
    Integrate desensitization with the sanitization orchestrator.
    
    Use case: Round-trip workflow (sanitize → store mappings → desensitize).
    """
    print("\n\n" + "=" * 80)
    print("Example 8: Integration with Orchestrator")
    print("=" * 80)
    
    from src.sanitization.orchestrator import SanitizationOrchestrator
    from src.config.config_loader import ConfigLoader
    
    # Load configuration
    config_loader = ConfigLoader()
    pii_config = config_loader.load_from_file("config/pii_config.json")
    
    # Initialize components
    conn_mgr = create_connection_manager()
    mapping_mgr = create_mapping_manager(conn_mgr)
    
    orchestrator = SanitizationOrchestrator(
        connection_manager=conn_mgr,
        mapping_manager=mapping_mgr,
        config=pii_config
    )
    
    desensitizer = Desensitizer(
        connection_manager=conn_mgr,
        mapping_manager=mapping_mgr
    )
    
    print("\nStep 1: Sanitize production data")
    print("-" * 80)
    
    # Sanitize data
    sanitize_report = orchestrator.sanitize()
    
    print(f"Sanitization completed:")
    print(f"  Operation ID: {sanitize_report.operation_id}")
    print(f"  Tables processed: {sanitize_report.tables_processed}")
    print(f"  Rows processed: {sanitize_report.rows_processed:,}")
    print(f"  Mappings stored: {sanitize_report.mappings_stored:,}")
    
    print("\n\nStep 2: Desensitize (restore) original data")
    print("-" * 80)
    
    # Restore original data
    restore_report = desensitizer.restore(sanitize_report.operation_id)
    
    print(f"Restoration completed:")
    print(f"  Tables restored: {restore_report.tables_restored}")
    print(f"  Rows restored: {restore_report.rows_restored:,}")
    print(f"  Values restored: {restore_report.values_restored:,}")
    print(f"  Success: {restore_report.is_successful()}")
    
    print("\n" + "=" * 80)
    print("Round-trip workflow completed successfully!")


# ---------------------------------------------------------
# Main execution
# ---------------------------------------------------------

if __name__ == "__main__":
    print("Desensitization Engine - Usage Examples")
    print("=" * 80)
    
    # Run all examples
    examples = [
        ("Basic Full Restoration", example_1_basic_full_restoration),
        ("Dry-Run Mode", example_2_dry_run_mode),
        ("Partial Restoration", example_3_partial_restoration),
        ("Progress Tracking", example_4_progress_tracking),
        ("Custom Configuration", example_5_custom_configuration),
        ("Error Handling", example_6_error_handling),
        ("Batch Restoration", example_7_batch_restoration_workflow),
        ("Orchestrator Integration", example_8_orchestrator_integration)
    ]
    
    print("\nAvailable examples:")
    for i, (name, _) in enumerate(examples, 1):
        print(f"  {i}. {name}")
    
    print("\nRun individual examples or modify this script to execute specific scenarios.")
    print("-" * 80)
    
    # Uncomment to run specific examples:
    # example_1_basic_full_restoration()
    # example_2_dry_run_mode()
    # example_3_partial_restoration()
    # example_4_progress_tracking()
    # example_5_custom_configuration()
    # example_6_error_handling()
    # example_7_batch_restoration_workflow()
    # example_8_orchestrator_integration()
