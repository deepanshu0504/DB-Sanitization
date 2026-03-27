"""
Example demonstrating batch data extraction from SQL Server tables.

This example shows how to use the BatchExtractor class to efficiently
extract PII data from large tables using different pagination strategies.

Usage:
    python examples/batch_extraction_example.py

Requirements:
    - SQL Server database accessible
    - Configuration file at config/sanitization_config.json
    - Install dependencies: pip install -r requirements.txt

Author: Database Sanitization Team
Date: 2026-03-26
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import ConfigLoader
from src.database import (
    DatabaseConnectionManager,
    SchemaExtractor,
    BatchExtractor,
    PaginationStrategy,
)
from src.logging.logger import get_logger
from src.logging.correlation import CorrelationContext


def example_basic_extraction():
    """Example 1: Basic batch extraction from a table."""
    print("\n" + "="*70)
    print("EXAMPLE 1: Basic Batch Extraction")
    print("="*70)
    
    # Load configuration
    config = ConfigLoader.load_config("config/pii_config.example.json")
    
    # Initialize components
    conn_mgr = DatabaseConnectionManager(config.database)
    schema_ext = SchemaExtractor(conn_mgr)
    extractor = BatchExtractor(conn_mgr, schema_ext, batch_size=10000)
    
    # Extract data from a table
    schema_name = "dbo"
    table_name = "Customers"
    columns = ["Email", "Phone", "FirstName", "LastName"]
    
    print(f"\nExtracting PII columns from [{schema_name}].[{table_name}]")
    print(f"Columns: {', '.join(columns)}")
    print(f"Batch size: {extractor.batch_size:,}\n")
    
    try:
        with CorrelationContext() as correlation_id:
            print(f"Correlation ID: {correlation_id}\n")
            
            for batch in extractor.extract_batches(schema_name, table_name, columns):
                print(f"Batch {batch.batch_number}:")
                print(f"  - Rows in batch: {batch.total_rows_in_batch:,}")
                print(f"  - Progress: {batch.rows_processed:,} / {batch.total_rows:,} "
                      f"({batch.progress_percentage:.1f}%)")
                print(f"  - Strategy: {batch.strategy.value}")
                print(f"  - Sample row: {batch.rows[0] if batch.rows else 'N/A'}")
                
                # Process each row (placeholder - in real sanitization, you would mask data here)
                for row in batch.rows:
                    # Example: Access PII values
                    email = row.get("Email")
                    phone = row.get("Phone")
                    # In real implementation, mask these values here
                    pass
                
                print()
        
        print("✓ Extraction completed successfully!")
    
    except Exception as e:
        print(f"✗ Error during extraction: {e}")
        raise


def example_empty_table():
    """Example 2: Handling empty tables."""
    print("\n" + "="*70)
    print("EXAMPLE 2: Extracting from Empty Table")
    print("="*70)
    
    config = ConfigLoader.load_config("config/pii_config.example.json")
    conn_mgr = DatabaseConnectionManager(config.database)
    schema_ext = SchemaExtractor(conn_mgr)
    extractor = BatchExtractor(conn_mgr, schema_ext, batch_size=5000)
    
    # Try to extract from an empty table
    schema_name = "dbo"
    table_name = "EmptyTable"  # Assume this table exists but is empty
    columns = ["Column1"]
    
    print(f"\nExtracting from [{schema_name}].[{table_name}]")
    
    try:
        batch_count = 0
        for batch in extractor.extract_batches(schema_name, table_name, columns):
            batch_count += 1
        
        if batch_count == 0:
            print("✓ No batches extracted (table is empty)")
        else:
            print(f"✓ Extracted {batch_count} batch(es)")
    
    except Exception as e:
        print(f"Note: {e}")


def example_progress_tracking():
    """Example 3: Progress tracking for large tables."""
    print("\n" + "="*70)
    print("EXAMPLE 3: Progress Tracking")
    print("="*70)
    
    config = ConfigLoader.load_config("config/pii_config.example.json")
    conn_mgr = DatabaseConnectionManager(config.database)
    schema_ext = SchemaExtractor(conn_mgr)
    
    # Use smaller batch size to demonstrate multiple batches
    extractor = BatchExtractor(conn_mgr, schema_ext, batch_size=1000)
    
    schema_name = "dbo"
    table_name = "LargeTable"  # Assume a table with many rows
    columns = ["PII_Column"]
    
    print(f"\nExtracting from [{schema_name}].[{table_name}] with progress tracking")
    print(f"Batch size: {extractor.batch_size:,}\n")
    
    try:
        start_time = __import__('time').time()
        total_batches = 0
        total_rows = 0
        
        for batch in extractor.extract_batches(schema_name, table_name, columns):
            total_batches += 1
            total_rows += batch.total_rows_in_batch
            
            # Display progress bar
            progress = batch.progress_percentage
            bar_length = 50
            filled = int(bar_length * progress / 100)
            bar = '█' * filled + '░' * (bar_length - filled)
            
            print(f"\rBatch {batch.batch_number}: [{bar}] {progress:.1f}% "
                  f"({batch.rows_processed:,}/{batch.total_rows:,} rows)", end='')
            
            # In real implementation, process the batch here
        
        elapsed = __import__('time').time() - start_time
        
        print(f"\n\n✓ Extraction completed!")
        print(f"  - Total batches: {total_batches}")
        print(f"  - Total rows extracted: {total_rows:,}")
        print(f"  - Time elapsed: {elapsed:.2f} seconds")
        print(f"  - Throughput: {total_rows / elapsed:.0f} rows/second")
    
    except Exception as e:
        print(f"\n✗ Error: {e}")


def example_composite_key_table():
    """Example 4: Extracting from table with composite primary key."""
    print("\n" + "="*70)
    print("EXAMPLE 4: Composite Primary Key Table")
    print("="*70)
    
    config = ConfigLoader.load_config("config/pii_config.example.json")
    conn_mgr = DatabaseConnectionManager(config.database)
    schema_ext = SchemaExtractor(conn_mgr)
    extractor = BatchExtractor(conn_mgr, schema_ext, batch_size=5000)
    
    # OrderDetails typically has composite PK: OrderID + ProductID
    schema_name = "dbo"
    table_name = "OrderDetails"
    columns = ["Quantity", "Price"]
    
    print(f"\nExtracting from [{schema_name}].[{table_name}]")
    print("(This table has a composite primary key)\n")
    
    try:
        for batch in extractor.extract_batches(schema_name, table_name, columns):
            print(f"Batch {batch.batch_number}:")
            print(f"  - Strategy: {batch.strategy.value}")
            print(f"  - Rows: {batch.total_rows_in_batch:,}")
            
            if batch.strategy == PaginationStrategy.COMPOSITE_KEY:
                print(f"  - Using tuple comparison for composite PK pagination")
            
            if batch.rows:
                print(f"  - Sample: {list(batch.rows[0].keys())}")
            print()
        
        print("✓ Extraction completed!")
    
    except Exception as e:
        print(f"✗ Error: {e}")


def example_non_dbo_schema():
    """Example 5: Extracting from non-dbo schema."""
    print("\n" + "="*70)
    print("EXAMPLE 5: Non-dbo Schema")
    print("="*70)
    
    config = ConfigLoader.load_config("config/pii_config.example.json")
    conn_mgr = DatabaseConnectionManager(config.database)
    schema_ext = SchemaExtractor(conn_mgr)
    extractor = BatchExtractor(conn_mgr, schema_ext, batch_size=10000)
    
    # Extract from custom schema
    schema_name = "custom_schema"
    table_name = "Users"
    columns = ["Email"]
    
    print(f"\nExtracting from [{schema_name}].[{table_name}]")
    
    try:
        for batch in extractor.extract_batches(schema_name, table_name, columns):
            print(f"Batch {batch.batch_number}: {batch.total_rows_in_batch:,} rows")
            print(f"  Schema: {batch.schema_name}")
            print(f"  Table: {batch.table_name}")
            print(f"  Full name: {batch.full_table_name}")
        
        print("\n✓ Successfully extracted from non-dbo schema!")
    
    except Exception as e:
        print(f"✗ Error: {e}")


def example_error_handling():
    """Example 6: Error handling for invalid inputs."""
    print("\n" + "="*70)
    print("EXAMPLE 6: Error Handling")
    print("="*70)
    
    config = ConfigLoader.load_config("config/pii_config.example.json")
    conn_mgr = DatabaseConnectionManager(config.database)
    schema_ext = SchemaExtractor(conn_mgr)
    extractor = BatchExtractor(conn_mgr, schema_ext)
    
    # Test 1: Non-existent table
    print("\n1. Attempting to extract from non-existent table...")
    try:
        list(extractor.extract_batches("dbo", "NonExistentTable", ["Col1"]))
        print("✗ Should have raised an error!")
    except Exception as e:
        print(f"✓ Caught expected error: {type(e).__name__}")
        print(f"   Message: {str(e)[:100]}...")
    
    # Test 2: Non-existent column
    print("\n2. Attempting to extract non-existent column...")
    try:
        list(extractor.extract_batches("dbo", "Customers", ["NonExistentColumn"]))
        print("✗ Should have raised an error!")
    except Exception as e:
        print(f"✓ Caught expected error: {type(e).__name__}")
        print(f"   Message: {str(e)[:100]}...")
    
    # Test 3: Invalid batch size
    print("\n3. Attempting to create extractor with invalid batch size...")
    try:
        invalid_extractor = BatchExtractor(conn_mgr, schema_ext, batch_size=0)
        print("✗ Should have raised an error!")
    except Exception as e:
        print(f"✓ Caught expected error: {type(e).__name__}")
        print(f"   Message: {str(e)[:100]}...")


def main():
    """Run all examples."""
    print("\n" + "="*70)
    print("BATCH DATA EXTRACTION EXAMPLES")
    print("="*70)
    print("\nThis example demonstrates various batch extraction scenarios:")
    print("  1. Basic extraction")
    print("  2. Empty table handling")
    print("  3. Progress tracking")
    print("  4. Composite primary key tables")
    print("  5. Non-dbo schema")
    print("  6. Error handling")
    
    try:
        # Run each example (comment out examples that require specific tables)
        example_basic_extraction()
        # example_empty_table()  # Uncomment if EmptyTable exists
        # example_progress_tracking()  # Uncomment if LargeTable exists
        # example_composite_key_table()  # Uncomment if OrderDetails exists
        # example_non_dbo_schema()  # Uncomment if custom_schema exists
        example_error_handling()
        
        print("\n" + "="*70)
        print("ALL EXAMPLES COMPLETED")
        print("="*70)
    
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
