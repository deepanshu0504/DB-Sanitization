"""
Basic orchestrator usage example.

Demonstrates how to use the Sanitization Orchestrator to coordinate
the complete database sanitization workflow.

This example shows:
1. Loading configuration
2. Creating the orchestrator
3. Running dry-run mode for validation
4. Running actual sanitization
5. Reviewing the report
6. Using mapping storage for traceability

Note: This is a demonstration example. In production, ensure you have:
- Valid database connection
- Properly configured PII columns
- Backup of the database before sanitization

Author: Database Sanitization Team
Date: 2026-03-27 (Updated with mapping support)
"""

from datetime import datetime
from src.sanitization.orchestrator import (
    SanitizationOrchestrator,
    SanitizationReport,
    ExecutionPhase
)
from src.config.config_models import (
    SanitizationConfig,
    DatabaseConfig,
    PIIColumnConfig,
    MaskingStrategy
)
from src.mapping.mapping_config import MappingConfig


def example_basic_orchestration():
    """
    Basic orchestration example.
    
    This example demonstrates the simplest use case: creating an orchestrator
    and running sanitization with a pre-defined configuration.
    """
    print("="*70)
    print("Example 1: Basic Orchestration")
    print("="*70)
    
    # Create configuration
    config = SanitizationConfig(
        database=DatabaseConfig(
            server="localhost",
            database="TestDB",
            auth_type="sql",
            username="sa",
            password="YourPassword123!",
            timeout=30,
            batch_size=1000
        ),
        pii_columns=[
            PIIColumnConfig(
                schema="dbo",
                table="Users",
                column="Email",
                masking_strategy=MaskingStrategy.EMAIL,
                is_nullable=False
            ),
            PIIColumnConfig(
                schema="dbo",
                table="Users",
                column="FirstName",
                masking_strategy=MaskingStrategy.FIRST_NAME,
                is_nullable=False
            )
        ],
        validate_before=True,
        validate_after=False
    )
    
    # Create orchestrator
    orchestrator = SanitizationOrchestrator()
    
    print(f"\n✓ Orchestrator created")
    print(f"  Checkpoint directory: {orchestrator.checkpoint_dir}")
    
    # Note: Actual execution would require a real database connection
    print(f"\nConfiguration ready:")
    print(f"  Database: {config.database.database}")
    print(f"  PII Columns: {len(config.pii_columns)}")
    print(f"  Batch Size: {config.database.batch_size}")


def example_dry_run():
    """
    Dry-run example.
    
    Dry-run mode validates configuration and shows what would be changed
    without actually modifying the database.
    """
    print("\n" + "="*70)
    print("Example 2: Dry-Run Mode")
    print("="*70)
    
    # Create simple config (same as example 1)
    config = SanitizationConfig(
        database=DatabaseConfig(
            server="localhost",
            database="TestDB",
            auth_type="sql",
            username="sa",
            password="YourPassword123!",
            batch_size=500
        ),
        pii_columns=[
            PIIColumnConfig(
                schema="dbo",
                table="Customers",
                column="SSN",
                masking_strategy=MaskingStrategy.SSN,
                is_nullable=False
            )
        ],
        validate_before=True
    )
    
    orchestrator = SanitizationOrchestrator()
    
    print(f"\n✓ Running dry-run mode (no database changes)")
    print(f"  This validates configuration and dependency order")
    print(f"  Database updates are skipped in dry-run mode")
    
    # In actual use:
    # report = orchestrator.run(config, dry_run=True)
    # print(f"\nDry-run report:")
    # print(f"  Tables to process: {report.total_tables}")
    # print(f"  Estimated rows: {report.rows_processed}")


def example_progress_callbacks():
    """
    Progress tracking example.
    
    Shows how to monitor sanitization progress with callbacks.
    """
    print("\n" + "="*70)
    print("Example 3: Progress Tracking")
    print("="*70)
    
    def on_table_event(event: str, table_name: str):
        """Called when table processing starts or completes."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] Table {table_name}: {event.upper()}")
    
    def on_batch_progress(
        table_name: str,
        rows_processed: int,
        total_rows: int,
        percentage: float
    ):
        """Called after each batch is processed."""
        print(f"  {table_name}: {rows_processed}/{total_rows} ({percentage:.1f}%)")
    
    orchestrator = SanitizationOrchestrator()
    
    # Set callbacks
    orchestrator.set_table_callback(on_table_event)
    orchestrator.set_progress_callback(on_batch_progress)
    
    print(f"\n✓ Progress callbacks configured")
    print(f"  Table callback: on_table_event")
    print(f"  Batch callback: on_batch_progress")
    print(f"\nDuring execution, you would see output like:")
    print(f"  [12:34:56] Table [dbo].[Users]: START")
    print(f"    [dbo].[Users]: 1000/5000 (20.0%)")
    print(f"    [dbo].[Users]: 2000/5000 (40.0%)")
    print(f"  [12:35:12] Table [dbo].[Users]: COMPLETE")


def example_checkpoint_resume():
    """
    Checkpoint and resume example.
    
    Shows how to resume sanitization after a failure using checkpoints.
    """
    print("\n" + "="*70)
    print("Example 4: Checkpoint & Resume")
    print("="*70)
    
    from pathlib import Path
    
    checkpoint_dir = Path("./checkpoints")
    orchestrator = SanitizationOrchestrator(checkpoint_dir=checkpoint_dir)
    
    print(f"\n✓ Orchestrator with checkpoint support")
    print(f"  Checkpoint directory: {checkpoint_dir}")
    print(f"\nFirst run (will fail mid-way):")
    print(f"  report = orchestrator.run(config, dry_run=False)")
    print(f"  # If this fails, checkpoint is saved automatically")
    print(f"\nResume from checkpoint:")
    print(f"  report = orchestrator.run(config, resume_from_checkpoint=True)")
    print(f"  # Skips already-processed tables, continues from where it left off")
    
    # Show checkpoint structure
    print(f"\nCheckpoint file structure:")
    print(f"  {{")
    print(f'    "operation_id": "uuid-here",')
    print(f'    "config_hash": "abc123",')
    print(f'    "tables_completed": ["[dbo].[Users]", "[dbo].[Orders]"],')
    print(f'    "current_table": null,')
    print(f'    "rows_processed": 15000')
    print(f"  }}")


def example_report_analysis():
    """
    Report analysis example.
    
    Shows how to analyze the sanitization report after execution.
    """
    print("\n" + "="*70)
    print("Example 5: Report Analysis")
    print("="*70)
    
    # Create sample report (in real use, this comes from orchestrator.run())
    report = SanitizationReport(
        operation_id="demo-001",
        phase=ExecutionPhase.COMPLETED,
        started_at=datetime.now(),
        completed_at=datetime.now()
    )
    
    # Simulate some results
    report.tables_processed = 5
    report.tables_failed = 0
    report.tables_skipped = 1
    report.rows_processed = 12500
    report.rows_masked = 37500  # 3 PII columns per row
    report.duration_ms = 45000  # 45 seconds
    
    print(f"\n✓ Sanitization Report:")
    print(f"  Operation ID: {report.operation_id}")
    print(f"  Phase: {report.phase.value}")
    print(f"  Success: {report.is_successful}")
    print(f"\nStatistics:")
    print(f"  Tables processed: {report.tables_processed}")
    print(f"  Tables failed: {report.tables_failed}")
    print(f"  Tables skipped: {report.tables_skipped}")
    print(f"  Total tables: {report.total_tables}")
    print(f"\nData Processing:")
    print(f"  Rows processed: {report.rows_processed:,}")
    print(f"  Values masked: {report.rows_masked:,}")
    print(f"  Duration: {report.duration_ms / 1000:.1f} seconds")
    
    # Serialize to dict for logging/storage
    report_dict = report.to_dict()
    print(f"\n✓ Report can be serialized to JSON:")
    print(f"  Keys: {list(report_dict.keys())[:5]}...")


def example_error_handling():
    """
    Error handling example.
    
    Shows how to handle errors during sanitization.
    """
    print("\n" + "="*70)
    print("Example 6: Error Handling")
    print("="*70)
    
    from src.exceptions import ValidationError, CircularDependencyError, DatabaseError
    
    print(f"\n✓ Orchestrator handles multiple error types:")
    print(f"\n1. ValidationError:")
    print(f"   - Raised when configuration is invalid")
    print(f"   - Contains field names and suggested actions")
    print(f"   - Example: Missing column, incorrect data type")
    
    print(f"\n2. CircularDependencyError:")
    print(f"   - Raised when circular FK dependencies detected")
    print(f"   - Lists tables involved in the cycle")
    print(f"   - Suggested action: Disable FKs, sanitize, re-enable")
    
    print(f"\n3. DatabaseError:")
    print(f"   - Raised for connection/query failures")
    print(f"   - Includes error code and suggested action")
    print(f"   - Example: Connection timeout, query timeout")
    
    print(f"\n4. Retryable errors:")
    print(f"   - Some errors have is_retryable=True")
    print(f"   - Automatically retried with exponential backoff")
    print(f"   - Example: Deadlock, temporary network issue")
    
    print(f"\nError handling pattern:")
    print(f"  try:")
    print(f"      report = orchestrator.run(config)")
    print(f"  except ValidationError as e:")
    print(f"      print(f'Config error: {{e.message}}')")
    print(f"      print(f'Fix: {{e.suggested_action}}')")
    print(f"  except CircularDependencyError as e:")
    print(f"      print(f'Circular FKs: {{e.tables_in_cycle}}')")
    print(f"  except DatabaseError as e:")
    print(f"      if e.is_retryable:")
    print(f"          # Retry logic")


def example_custom_checkpoint_directory():
    """
    Custom checkpoint directory example.
    
    Shows how to use a custom directory for checkpoints.
    """
    print("\n" + "="*70)
    print("Example 7: Custom Checkpoint Directory")
    print("="*70)
    
    from pathlib import Path
    
    # Use custom checkpoint directory (e.g., network share for distributed processing)
    checkpoint_dir = Path("/data/sanitization/checkpoints")
    
    orchestrator = SanitizationOrchestrator(checkpoint_dir=checkpoint_dir)
    
    print(f"\n✓ Custom checkpoint directory configured:")
    print(f"  Path: {checkpoint_dir}")
    print(f"\nUse cases:")
    print(f"  - Network share for distributed systems")
    print(f"  - Persistent storage in Docker containers")
    print(f"  - Compliance requirements (audit trail)")
    print(f"  - Separate disk for I/O performance")


def example_batch_size_tuning():
    """
    Batch size tuning example.
    
    Shows how to configure batch size for performance optimization.
    """
    print("\n" + "="*70)
    print("Example 8: Batch Size Tuning")
    print("="*70)
    
    # Small tables: smaller batch size
    small_table_config = DatabaseConfig(
        server="localhost",
        database="TestDB",
        auth_type="sql",
        batch_size=500  # Smaller batches for quick commits
    )
    
    # Large tables: larger batch size
    large_table_config = DatabaseConfig(
        server="localhost",
        database="LargeDB",
        auth_type="sql",
        batch_size=10000  # Larger batches for efficiency
    )
    
    print(f"\n✓ Batch size recommendations:")
    print(f"\nSmall tables (<10K rows):")
    print(f"  Batch size: 500-1,000")
    print(f"  Benefit: Quick commits, less memory")
    
    print(f"\nMedium tables (10K-1M rows):")
    print(f"  Batch size: 1,000-5,000")
    print(f"  Benefit: Balanced performance")
    
    print(f"\nLarge tables (>1M rows):")
    print(f"  Batch size: 5,000-10,000")
    print(f"  Benefit: Maximum throughput")
    
    print(f"\nFactors to consider:")
    print(f"  - Available memory")
    print(f"  - Network latency")
    print(f"  - Transaction log size")
    print(f"  - Number of PII columns")


def example_mapping_storage():
    """
    Example 9: Mapping Storage for Traceability.
    
    Demonstrates how to enable mapping storage to track original→masked
    value mappings for audit trails and desensitization support.
    """
    print("\n" + "="*70)
    print("Example 9: Mapping Storage")
    print("="*70)
    
    # Create config with mapping enabled
    config = SanitizationConfig(
        database=DatabaseConfig(
            server="localhost",
            database="TestDB",
            auth_type="sql",
            username="sa",
            password="YourPassword123!",
            batch_size=1000
        ),
        pii_columns=[
            PIIColumnConfig(
                schema="dbo",
                table="Customers",
                column="Email",
                masking_strategy=MaskingStrategy.EMAIL,
                is_nullable=False
            ),
            PIIColumnConfig(
                schema="dbo",
                table="Customers",
                column="SSN",
                masking_strategy=MaskingStrategy.SSN,
                is_nullable=False
            )
        ],
        # Enable mapping storage
        mapping=MappingConfig(
            enabled=True,
            schema_name="sanitization",
            table_name="pii_mappings",
            encryption_enabled=False,  # Set to True for production
            batch_size=1000,
            index_creation=True,
            transactional=True
        ),
        validate_before=True
    )
    
    print(f"\n✓ Configuration with mapping storage:")
    print(f"  Mapping Table: [{config.mapping.schema_name}].[{config.mapping.table_name}]")
    print(f"  Encryption: {config.mapping.encryption_enabled}")
    print(f"  Batch Size: {config.mapping.batch_size}")
    
    # Create orchestrator
    orchestrator = SanitizationOrchestrator()
    
    # Note: Actual execution would require real database
    print(f"\n✓ Orchestrator created with mapping support")
    print(f"  When run() executes:")
    print(f"    1. Mapping schema and table will be created")
    print(f"    2. For each masked value, a mapping entry is stored:")
    print(f"       - operation_id (UUID)")
    print(f"       - schema/table/column names")
    print(f"       - original_value_hash (SHA256)")
    print(f"       - masked_value")
    print(f"       - encryption (if enabled)")
    print(f"    3. Mappings enable desensitization (reverse operation)")
    
    print(f"\n✓ Encryption setup (production):")
    print(f"  # Generate key")
    print(f"  from src.mapping.encryption_utils import EncryptionManager")
    print(f"  key = EncryptionManager.generate_key()")
    print(f"  ")
    print(f"  # Set environment variable")
    print(f"  import os")
    print(f"  os.environ['SANITIZATION_MAPPING_ENCRYPTION_KEY'] = key")
    print(f"  ")
    print(f"  # Then run with encryption_enabled=True")
    
    print(f"\n✓ Querying mappings after sanitization:")
    print(f"  from src.mapping.mapping_manager import MappingManager")
    print(f"  from src.database.connection_manager import DatabaseConnectionManager")
    print(f"  ")
    print(f"  conn_mgr = DatabaseConnectionManager(config.database)")
    print(f"  mapping_mgr = MappingManager(conn_mgr, config.mapping)")
    print(f"  ")
    print(f"  # Get all mappings for an operation")
    print(f"  entries = mapping_mgr.get_entries_by_operation(operation_id)")
    print(f"  ")
    print(f"  # Get mappings for specific table")
    print(f"  entries = mapping_mgr.get_entries_by_table(")
    print(f"      operation_id, 'dbo', 'Customers', 'Email'")
    print(f"  )")
    print(f"  ")
    print(f"  # Get operation statistics")
    print(f"  stats = mapping_mgr.get_operation_stats(operation_id)")
    print(f"  print(f'Total mappings: {{stats.total_entries}}')")
    
    print(f"\n✓ Using mappings for desensitization:")
    print(f"  # Story 5.4 (future): Restore original values")
    print(f"  # from src.sanitization.desensitizer import Desensitizer")
    print(f"  # ")
    print(f"  # desensitizer = Desensitizer(conn_mgr, mapping_mgr)")
    print(f"  # restore_report = desensitizer.restore(operation_id)")
    
    print(f"\n✓ Report includes mapping statistics:")
    print(f"  report.mappings_stored  # Number of mappings created")
    print(f"  report.mapping_errors   # Any mapping storage errors")


def main():
    """Run all examples."""
    print("\n" + "="*70)
    print("SANITIZATION ORCHESTRATOR - USAGE EXAMPLES")
    print("="*70)
    print(f"\nThese examples demonstrate the Sanitization Orchestrator")
    print(f"for coordinating database sanitization workflows.")
    print(f"\nNote: Examples show API usage. Actual database operations")
    print(f"require valid connection and properly configured environment.")
    
    # Run all examples
    example_basic_orchestration()
    example_dry_run()
    example_progress_callbacks()
    example_checkpoint_resume()
    example_report_analysis()
    example_error_handling()
    example_custom_checkpoint_directory()
    example_batch_size_tuning()
    example_mapping_storage()
    
    print("\n" + "="*70)
    print("All examples completed successfully!")
    print("="*70)
    print(f"\nFor more information, see:")
    print(f"  - src/sanitization/orchestrator.py (implementation)")
    print(f"  - src/mapping/mapping_manager.py (mapping storage)")
    print(f"  - examples/mapping_example.py (mapping usage)")
    print(f"  - tests/unit/test_orchestrator.py (unit tests)")
    print(f"  - tests/integration/test_orchestrator_integration.py (integration tests)")
    print(f"  - USER_STORIES.md (requirements)")


if __name__ == "__main__":
    main()
