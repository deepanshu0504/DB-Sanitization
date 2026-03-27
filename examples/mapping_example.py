"""
Mapping Table Manager usage examples.

Demonstrates how to use the MappingManager for storing and retrieving
original→masked value mappings during database sanitization.

This example shows:
1. Basic mapping storage and retrieval
2. Batch operations with progress tracking
3. Encryption-enabled mapping storage
4. Querying operation statistics
5. Error handling and retry scenarios
6. Integration with batch updater workflow

Note: This is a demonstration example. In production, ensure you have:
- Valid database connection
- Properly configured mapping table
- Encryption key if encryption is enabled
- Adequate database permissions

Author: Database Sanitization Team
Date: 2026-03-27
"""

import os
import hashlib
from datetime import datetime
from uuid import uuid4
from typing import List

from src.database.connection_manager import DatabaseConnectionManager
from src.database.connection_config import ConnectionConfig, AuthType
from src.mapping.mapping_manager import MappingManager
from src.mapping.mapping_config import MappingConfig
from src.mapping.mapping_models import MappingEntry, MappingBatch
from src.mapping.encryption_utils import EncryptionManager
from src.exceptions import MappingError


def example_1_basic_storage_and_retrieval():
    """
    Example 1: Basic mapping storage and retrieval.
    
    Demonstrates the simplest use case: storing a few mappings and
    retrieving them by operation ID.
    """
    print("=" * 70)
    print("Example 1: Basic Storage and Retrieval")
    print("=" * 70)
    
    # Create connection configuration
    config = ConnectionConfig(
        server="localhost",
        database="TestDB",
        auth_type=AuthType.WINDOWS,
        timeout=30
    )
    
    # Create connection manager
    conn_mgr = DatabaseConnectionManager(config)
    
    # Create mapping configuration
    mapping_config = MappingConfig(
        enabled=True,
        schema_name="sanitization",
        table_name="pii_mappings",
        encryption_enabled=False,
        batch_size=1000,
        index_creation=True,
        transactional=True
    )
    
    # Create mapping manager
    mapping_mgr = MappingManager(conn_mgr, mapping_config)
    
    # Initialize (creates schema, table, indexes)
    print("\n✓ Initializing mapping manager...")
    mapping_mgr.initialize()
    print("  Schema and table created successfully")
    
    # Create operation ID
    operation_id = uuid4()
    print(f"\n✓ Operation ID: {operation_id}")
    
    # Create sample mapping entries
    entries = []
    for i in range(5):
        original_email = f"user{i}@company.com"
        masked_email = f"user_{i:08x}@masked.dev"
        
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="Customers",
            column_name="Email",
            original_value_hash=hashlib.sha256(original_email.encode()).digest(),
            original_value_encrypted=None,
            masked_value=masked_email,
            data_type="VARCHAR",
            is_null=False,
            created_at=datetime.utcnow()
        )
        entries.append(entry)
    
    # Store mappings
    print(f"\n✓ Storing {len(entries)} mapping entries...")
    mapping_mgr.store_mappings(entries)
    print("  Mappings stored successfully")
    
    # Retrieve mappings
    print(f"\n✓ Retrieving mappings for operation {operation_id}...")
    retrieved = mapping_mgr.get_entries_by_operation(operation_id)
    print(f"  Retrieved {len(retrieved)} entries")
    
    # Display sample
    if retrieved:
        print("\n  Sample mapping:")
        sample = retrieved[0]
        print(f"    Table: {sample.table_qualified_name}")
        print(f"    Column: {sample.column_name}")
        print(f"    Masked: {sample.masked_value}")
        print(f"    Data Type: {sample.data_type}")


def example_2_batch_operations():
    """
    Example 2: Batch operations with progress tracking.
    
    Demonstrates handling large numbers of mappings with automatic
    batching and progress monitoring.
    """
    print("\n" + "=" * 70)
    print("Example 2: Batch Operations")
    print("=" * 70)
    
    # Setup (reuse from Example 1)
    config = ConnectionConfig(
        server="localhost",
        database="TestDB",
        auth_type=AuthType.WINDOWS
    )
    conn_mgr = DatabaseConnectionManager(config)
    
    mapping_config = MappingConfig(
        enabled=True,
        schema_name="sanitization",
        table_name="pii_mappings",
        batch_size=100,  # Small batch for demonstration
        transactional=True
    )
    
    mapping_mgr = MappingManager(conn_mgr, mapping_config)
    mapping_mgr.initialize()
    
    # Generate large number of entries
    operation_id = uuid4()
    total_count = 1000
    
    print(f"\n✓ Generating {total_count} mapping entries...")
    entries = []
    for i in range(total_count):
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="Users",
            column_name="Phone",
            original_value_hash=hashlib.sha256(f"555-{i:04d}".encode()).digest(),
            original_value_encrypted=None,
            masked_value=f"555-{i+1000:04d}",
            data_type="VARCHAR",
            is_null=False,
            created_at=datetime.utcnow()
        )
        entries.append(entry)
    
    print(f"  Generated {len(entries)} entries")
    
    # Store with automatic batching
    print(f"\n✓ Storing entries in batches of {mapping_config.batch_size}...")
    mapping_mgr.store_mappings(entries)
    print(f"  All {total_count} entries stored successfully")
    
    # Get operation statistics
    print(f"\n✓ Retrieving operation statistics...")
    stats = mapping_mgr.get_operation_stats(operation_id)
    
    if stats:
        print(f"  Total entries: {stats.total_entries}")
        print(f"  Tables processed: {stats.table_count}")
        print(f"  Columns processed: {stats.column_count}")
        print(f"  Encrypted: {stats.encrypted_count}")
        print(f"  NULL values: {stats.null_count}")
        print(f"  Time range: {stats.earliest_timestamp} to {stats.latest_timestamp}")


def example_3_encryption_enabled():
    """
    Example 3: Encryption-enabled mapping storage.
    
    Demonstrates secure storage of original PII values using encryption.
    """
    print("\n" + "=" * 70)
    print("Example 3: Encryption-Enabled Storage")
    print("=" * 70)
    
    # Generate and set encryption key
    print("\n✓ Generating encryption key...")
    encryption_key = EncryptionManager.generate_key()
    os.environ['SANITIZATION_MAPPING_ENCRYPTION_KEY'] = encryption_key
    print("  Encryption key generated and set")
    
    # Setup with encryption enabled
    config = ConnectionConfig(
        server="localhost",
        database="TestDB",
        auth_type=AuthType.WINDOWS
    )
    conn_mgr = DatabaseConnectionManager(config)
    
    mapping_config = MappingConfig(
        enabled=True,
        schema_name="sanitization",
        table_name="pii_mappings_encrypted",
        encryption_enabled=True,  # Enable encryption
        batch_size=1000,
        transactional=True
    )
    
    mapping_mgr = MappingManager(conn_mgr, mapping_config)
    mapping_mgr.initialize()
    
    # Create sensitive data mappings
    operation_id = uuid4()
    
    sensitive_data = [
        ("SSN", "123-45-6789", "***-**-6789"),
        ("CreditCard", "4532-1234-5678-9010", "****-****-****-9010"),
        ("Email", "john.doe@company.com", "user_abc123@masked.dev")
    ]
    
    entries = []
    for column, original, masked in sensitive_data:
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="Employees",
            column_name=column,
            original_value_hash=hashlib.sha256(original.encode()).digest(),
            original_value_encrypted=original.encode(),  # Will be encrypted
            masked_value=masked,
            data_type="VARCHAR",
            is_null=False,
            created_at=datetime.utcnow()
        )
        entries.append(entry)
    
    print(f"\n✓ Storing {len(entries)} encrypted mappings...")
    mapping_mgr.store_mappings(entries)
    print("  Encrypted mappings stored successfully")
    
    # Retrieve and decrypt
    print(f"\n✓ Retrieving and decrypting mappings...")
    retrieved = mapping_mgr.get_entries_by_operation(operation_id)
    
    encryption_mgr = EncryptionManager()
    
    print("\n  Decrypted values:")
    for entry in retrieved:
        if entry.original_value_encrypted:
            decrypted = encryption_mgr.decrypt(entry.original_value_encrypted)
            print(f"    {entry.column_name}: {decrypted} → {entry.masked_value}")
    
    # Cleanup
    del os.environ['SANITIZATION_MAPPING_ENCRYPTION_KEY']


def example_4_query_by_table():
    """
    Example 4: Querying mappings by table.
    
    Demonstrates retrieving mappings for a specific table and column.
    """
    print("\n" + "=" * 70)
    print("Example 4: Query by Table and Column")
    print("=" * 70)
    
    # Setup
    config = ConnectionConfig(
        server="localhost",
        database="TestDB",
        auth_type=AuthType.WINDOWS
    )
    conn_mgr = DatabaseConnectionManager(config)
    
    mapping_config = MappingConfig(
        enabled=True,
        schema_name="sanitization",
        table_name="pii_mappings"
    )
    
    mapping_mgr = MappingManager(conn_mgr, mapping_config)
    mapping_mgr.initialize()
    
    operation_id = uuid4()
    
    # Create mappings for multiple tables
    tables = [
        ("Customers", "Email", 10),
        ("Customers", "Phone", 10),
        ("Orders", "ShipToAddress", 5),
        ("Employees", "SSN", 3)
    ]
    
    print("\n✓ Creating mappings across multiple tables...")
    all_entries = []
    
    for table, column, count in tables:
        for i in range(count):
            entry = MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name=table,
                column_name=column,
                original_value_hash=hashlib.sha256(f"{table}_{column}_{i}".encode()).digest(),
                original_value_encrypted=None,
                masked_value=f"masked_{table}_{column}_{i}",
                data_type="VARCHAR",
                is_null=False,
                created_at=datetime.utcnow()
            )
            all_entries.append(entry)
    
    mapping_mgr.store_mappings(all_entries)
    print(f"  Stored {len(all_entries)} mappings across {len(tables)} table/column combinations")
    
    # Query specific table
    print("\n✓ Querying mappings for Customers.Email...")
    customer_emails = mapping_mgr.get_entries_by_table(
        operation_id=operation_id,
        schema="dbo",
        table="Customers",
        column="Email"
    )
    
    print(f"  Found {len(customer_emails)} Email mappings for Customers table")
    
    # Query different column
    print("\n✓ Querying mappings for Employees.SSN...")
    employee_ssn = mapping_mgr.get_entries_by_table(
        operation_id=operation_id,
        schema="dbo",
        table="Employees",
        column="SSN"
    )
    
    print(f"  Found {len(employee_ssn)} SSN mappings for Employees table")


def example_5_error_handling():
    """
    Example 5: Error handling and retry scenarios.
    
    Demonstrates proper error handling when working with mappings.
    """
    print("\n" + "=" * 70)
    print("Example 5: Error Handling")
    print("=" * 70)
    
    # Setup
    config = ConnectionConfig(
        server="localhost",
        database="TestDB",
        auth_type=AuthType.WINDOWS
    )
    conn_mgr = DatabaseConnectionManager(config)
    
    mapping_config = MappingConfig(
        enabled=True,
        schema_name="sanitization",
        table_name="pii_mappings"
    )
    
    mapping_mgr = MappingManager(conn_mgr, mapping_config)
    
    # Test 1: Initialize handles existing schema/table
    print("\n✓ Testing idempotent initialization...")
    try:
        mapping_mgr.initialize()
        mapping_mgr.initialize()  # Second call should be safe
        print("  ✓ Multiple initializations handled correctly")
    except Exception as e:
        print(f"  ✗ Error: {e}")
    
    # Test 2: Handle empty batch
    print("\n✓ Testing empty batch handling...")
    try:
        mapping_mgr.store_mappings([])
        print("  ✓ Empty batch handled gracefully")
    except Exception as e:
        print(f"  ✗ Error: {e}")
    
    # Test 3: Invalid encryption key
    print("\n✓ Testing missing encryption key...")
    try:
        # Remove encryption key if set
        if 'SANITIZATION_MAPPING_ENCRYPTION_KEY' in os.environ:
            del os.environ['SANITIZATION_MAPPING_ENCRYPTION_KEY']
        
        # Try to create manager with encryption enabled
        bad_config = MappingConfig(
            enabled=True,
            schema_name="sanitization",
            table_name="pii_mappings",
            encryption_enabled=True
        )
        
        bad_mgr = MappingManager(conn_mgr, bad_config)
        
        # This should work (manager created), but encryption will fail on use
        print("  ✓ Manager created (encryption will fail on actual use)")
        
    except MappingError as e:
        print(f"  ✓ Expected error caught: {e.error_code}")
    except Exception as e:
        print(f"  ✗ Unexpected error: {e}")
    
    # Test 4: Query non-existent operation
    print("\n✓ Testing query for non-existent operation...")
    try:
        fake_operation_id = uuid4()
        entries = mapping_mgr.get_entries_by_operation(fake_operation_id)
        print(f"  ✓ Query returned {len(entries)} entries (expected: 0)")
    except Exception as e:
        print(f"  ✗ Error: {e}")


def example_6_integration_with_batch_updater():
    """
    Example 6: Integration with batch updater workflow.
    
    Demonstrates how mapping storage fits into the sanitization workflow.
    """
    print("\n" + "=" * 70)
    print("Example 6: Integration with Batch Updater Workflow")
    print("=" * 70)
    
    # Setup
    config = ConnectionConfig(
        server="localhost",
        database="TestDB",
        auth_type=AuthType.WINDOWS
    )
    conn_mgr = DatabaseConnectionManager(config)
    
    mapping_config = MappingConfig(
        enabled=True,
        schema_name="sanitization",
        table_name="pii_mappings"
    )
    
    mapping_mgr = MappingManager(conn_mgr, mapping_config)
    mapping_mgr.initialize()
    
    operation_id = uuid4()
    
    # Simulate batch update workflow
    print("\n✓ Simulating sanitization workflow...")
    
    # Step 1: Extract data (simulated)
    print("\n  Step 1: Extract PII data from database")
    simulated_batch = [
        {"id": 1, "email": "alice@company.com"},
        {"id": 2, "email": "bob@company.com"},
        {"id": 3, "email": "charlie@company.com"}
    ]
    print(f"    Extracted {len(simulated_batch)} rows")
    
    # Step 2: Mask data and create mappings
    print("\n  Step 2: Mask PII values and create mappings")
    mapping_entries = []
    
    for row in simulated_batch:
        original_email = row["email"]
        masked_email = f"user_{row['id']:08x}@masked.dev"
        
        # Update row (simulated)
        row["email"] = masked_email
        
        # Create mapping entry
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="Users",
            column_name="Email",
            original_value_hash=hashlib.sha256(original_email.encode()).digest(),
            original_value_encrypted=None,
            masked_value=masked_email,
            data_type="VARCHAR",
            is_null=False,
            created_at=datetime.utcnow()
        )
        mapping_entries.append(entry)
    
    print(f"    Masked {len(mapping_entries)} values")
    
    # Step 3: Update database (simulated)
    print("\n  Step 3: Update database with masked values")
    print("    [Database update would happen here]")
    
    # Step 4: Store mappings
    print("\n  Step 4: Store mappings for traceability")
    mapping_mgr.store_mappings(mapping_entries)
    print(f"    Stored {len(mapping_entries)} mappings")
    
    # Step 5: Verify
    print("\n  Step 5: Verify mappings stored correctly")
    stats = mapping_mgr.get_operation_stats(operation_id)
    print(f"    Operation {operation_id}")
    print(f"    Total entries: {stats.total_entries}")
    print(f"    Tables: {stats.table_count}")
    
    print("\n  ✓ Workflow complete!")


def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("MAPPING TABLE MANAGER EXAMPLES")
    print("=" * 70)
    print("\nNote: These examples require a running SQL Server instance.")
    print("Set environment variables: SQLSERVER_HOST, SQLSERVER_DB, SQLSERVER_AUTH")
    print("\nPress Ctrl+C to skip any example.\n")
    
    examples = [
        ("Basic Storage and Retrieval", example_1_basic_storage_and_retrieval),
        ("Batch Operations", example_2_batch_operations),
        ("Encryption Enabled", example_3_encryption_enabled),
        ("Query by Table", example_4_query_by_table),
        ("Error Handling", example_5_error_handling),
        ("Integration with Batch Updater", example_6_integration_with_batch_updater)
    ]
    
    for i, (name, func) in enumerate(examples, 1):
        try:
            print(f"\n{'=' * 70}")
            print(f"Running Example {i}: {name}")
            print(f"{'=' * 70}")
            func()
            print(f"\n✓ Example {i} completed successfully!")
        except KeyboardInterrupt:
            print(f"\n⊗ Example {i} skipped by user")
            continue
        except Exception as e:
            print(f"\n✗ Example {i} failed: {e}")
            print("  (This may be expected if database is not available)")
            continue
    
    print("\n" + "=" * 70)
    print("All examples completed!")
    print("=" * 70)


if __name__ == "__main__":
    main()
