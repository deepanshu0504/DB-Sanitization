"""
Complete Example: Sanitization and Desanitization Workflow

This example demonstrates the full cycle of sanitizing a database with
mapping capture and then restoring the original values.

Prerequisites:
    - Database with PII data
    - SANITIZATION_ENCRYPTION_KEY environment variable set
    - SQL Server connection configured

Author: Database Sanitization Team
Date: 2026-04-16
"""

import os
import sys
from uuid import UUID, uuid4
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapping import (
    EncryptionManager,
    MappingManager,
    create_mapping_entry,
    generate_encryption_key
)
from desanitization import (
    Desanitizer,
    DesanitizationConfig,
    create_safe_config,
    create_production_config
)


def example_1_generate_encryption_key():
    """
    Example 1: Generate encryption key for first-time setup.
    
    Run this once to generate an encryption key, then add it to your .env file.
    """
    print("=" * 80)
    print("Example 1: Generate Encryption Key")
    print("=" * 80)
    
    key = generate_encryption_key()
    
    print("\nGenerated encryption key:")
    print("=" * 80)
    print(f"SANITIZATION_ENCRYPTION_KEY={key}")
    print("=" * 80)
    
    print("\nAdd this to your .env file and NEVER commit it to version control!")
    print("Store a backup of this key in a secure location.")


def example_2_full_workflow():
    """
    Example 2: Complete sanitization → desanitization workflow.
    
    This demonstrates:
    1. Setting up encryption and mapping
    2. Running sanitization with mapping capture
    3. Running desanitization to restore original values
    """
    print("\n" + "=" * 80)
    print("Example 2: Full Sanitization → Desanitization Workflow")
    print("=" * 80)
    
    # Connection string (update with your details)
    connection_string = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=localhost;"
        "DATABASE=TestDB;"
        "Trusted_Connection=yes;"
    )
    
    # Initialize encryption manager
    try:
        encryption_mgr = EncryptionManager()
        print("\n✓ Encryption manager initialized")
    except Exception as e:
        print(f"\n✗ Failed to initialize encryption: {e}")
        print("Make sure SANITIZATION_ENCRYPTION_KEY is set in your environment")
        return
    
    # Initialize mapping manager
    mapping_mgr = MappingManager(
        connection_string=connection_string,
        encryption_manager=encryption_mgr
    )
    mapping_mgr.initialize()
    print("✓ Mapping manager initialized")
    
    # Generate operation ID
    operation_id = uuid4()
    print(f"✓ Operation ID: {operation_id}")
    
    # --- SANITIZATION PHASE ---
    print("\n" + "-" * 80)
    print("PHASE 1: SANITIZATION (with mapping capture)")
    print("-" * 80)
    
    print("\nNOTE: In practice, you would run:")
    print(f"  python sanitize_smart.py config/pii_config.json")
    print("\nThe sanitization script will automatically:")
    print("  1. Generate an operation_id")
    print("  2. Initialize encryption and mapping managers")
    print("  3. Capture original→masked mappings during sanitization")
    print("  4. Store encrypted mappings in pii_mappings table")
    print(f"\nFor this example, we'll simulate some mappings...")
    
    # Simulate capturing some mappings (in real use, sanitize_smart.py does this)
    sample_mappings = [
        create_mapping_entry(
            operation_id=operation_id,
            schema="dbo",
            table="Customers",
            column="Email",
            original_value="john.doe@company.com",
            masked_value="user_a1b2c3d4@example.com",
            data_type="NVARCHAR(100)",
            encrypted_original=encryption_mgr.encrypt("john.doe@company.com")
        ),
        create_mapping_entry(
            operation_id=operation_id,
            schema="dbo",
            table="Customers",
            column="Phone",
            original_value="(555) 123-4567",
            masked_value="(555) 555-1001",
            data_type="NVARCHAR(20)",
            encrypted_original=encryption_mgr.encrypt("(555) 123-4567")
        ),
        create_mapping_entry(
            operation_id=operation_id,
            schema="dbo",
            table="Customers",
            column="FullName",
            original_value="John Doe",
            masked_value="Michael Brown",
            data_type="NVARCHAR(100)",
            encrypted_original=encryption_mgr.encrypt("John Doe")
        ),
    ]
    
    # Store mappings
    stats = mapping_mgr.store_mappings(sample_mappings)
    print(f"\n✓ Stored {stats.total_mappings} mappings")
    print(f"  Tables: {stats.tables_affected}")
    print(f"  Columns: {stats.columns_affected}")
    print(f"  Encrypted: {stats.encrypted_count}")
    
    # --- DESANITIZATION PHASE ---
    print("\n" + "-" * 80)
    print("PHASE 2: DESANITIZATION (restore original values)")
    print("-" * 80)
    
    # Initialize desanitizer
    desanitizer = Desanitizer(
        connection_string=connection_string,
        encryption_manager=encryption_mgr,
        mapping_manager=mapping_mgr
    )
    print("\n✓ Desanitizer initialized")
    
    # Dry-run first (preview)
    print("\n--- Dry-Run (Preview) ---")
    dry_config = create_safe_config()
    dry_stats = desanitizer.restore(operation_id, dry_config)
    
    print(f"\nDry-run results:")
    print(f"  Would restore: {dry_stats.total_rows_restored} rows")
    print(f"  Tables: {dry_stats.tables_restored}/{dry_stats.total_tables}")
    print(f"  Successful: {dry_stats.is_successful}")
    
    # Execute restoration (in real use, you would do this)
    print("\n--- Execute Restoration ---")
    print("NOTE: In practice, you would run:")
    print(f"  python desanitize.py {operation_id} --execute")
    print("\nThis would:")
    print("  1. Retrieve mappings from pii_mappings table")
    print("  2. Decrypt original values")
    print("  3. Update database with original values")
    print("  4. Verify restoration success")
    
    # Simulate execution (commented out to avoid actual DB changes in example)
    # execute_config = create_production_config()
    # execute_stats = desanitizer.restore(operation_id, execute_config)
    # print(f"\nRestored {execute_stats.total_rows_restored} rows")


def example_3_selective_restore():
    """
    Example 3: Selective table restoration.
    
    Demonstrates how to restore only specific tables instead of the entire database.
    """
    print("\n" + "=" * 80)
    print("Example 3: Selective Table Restoration")
    print("=" * 80)
    
    connection_string = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=localhost;"
        "DATABASE=TestDB;"
        "Trusted_Connection=yes;"
    )
    
    # Initialize
    encryption_mgr = EncryptionManager()
    desanitizer = Desanitizer(
        connection_string=connection_string,
        encryption_manager=encryption_mgr
    )
    
    # Restore only specific tables
    operation_id = UUID("12345678-1234-1234-1234-123456789abc")  # Example UUID
    
    config = create_production_config(
        tables=["dbo.Customers", "dbo.Orders"]  # Only these tables
    )
    
    print(f"\nRestoring only: {config.tables}")
    print("Other tables will remain sanitized")
    
    # Execute (commented for example)
    # stats = desanitizer.restore(operation_id, config)


def example_4_command_line_usage():
    """
    Example 4: Command-line usage examples.
    
    Shows various ways to use the desanitize.py script from command line.
    """
    print("\n" + "=" * 80)
    print("Example 4: Command-Line Usage")
    print("=" * 80)
    
    operation_id = "a1b2c3d4-5678-90ab-cdef-123456789abc"
    
    examples = [
        {
            "description": "Dry-run (preview only)",
            "command": f"python desanitize.py {operation_id}"
        },
        {
            "description": "Full database restore",
            "command": f"python desanitize.py {operation_id} --execute"
        },
        {
            "description": "Selective table restore",
            "command": f"python desanitize.py {operation_id} --execute --tables dbo.Customers dbo.Orders"
        },
        {
            "description": "Custom batch size",
            "command": f"python desanitize.py {operation_id} --execute --batch-size 5000"
        },
        {
            "description": "With custom connection string",
            "command": (
                f"python desanitize.py {operation_id} --execute "
                f"--connection-string 'DRIVER={{...}};SERVER=...;DATABASE=...;UID=...;PWD=...;'"
            )
        }
    ]
    
    for i, example in enumerate(examples, 1):
        print(f"\n{i}. {example['description']}:")
        print(f"   {example['command']}")


def main():
    """Run all examples."""
    print("=" * 80)
    print("DESANITIZATION EXAMPLES")
    print("=" * 80)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    # Check if encryption key is set
    if not os.getenv('SANITIZATION_ENCRYPTION_KEY'):
        print("\n⚠ WARNING: SANITIZATION_ENCRYPTION_KEY not set in environment")
        print("\nWould you like to generate one? (yes/no): ", end="")
        
        # For automated example, we'll skip interactive input
        # In real use, uncomment the following:
        # response = input()
        # if response.lower() == 'yes':
        #     example_1_generate_encryption_key()
        
        print("\nSkipping encryption key generation for automated example.")
        print("Run: python examples/desanitization_example.py")
        print("Then follow the prompts to generate a key.")
    
    # Run examples
    # example_2_full_workflow()
    # example_3_selective_restore()
    example_4_command_line_usage()
    
    print("\n" + "=" * 80)
    print("Examples complete!")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Set SANITIZATION_ENCRYPTION_KEY in your environment")
    print("2. Run sanitization with: python sanitize_smart.py config/pii_config.json")
    print("3. Note the operation_id from the output")
    print("4. Run desanitization with: python desanitize.py <operation_id> --execute")
    print("=" * 80)


if __name__ == "__main__":
    main()
