"""
Example script demonstrating schema metadata extraction.

This script shows how to use the SchemaExtractor to extract complete
database schema information including tables, columns, keys, and constraints.

Usage:
    python examples/extract_schema_example.py

Requirements:
    - SQL Server must be running and accessible
    - Configuration file or environment variables must be set
    - Database connection credentials must be valid

Output:
    - Console output with summary statistics
    - JSON file with complete schema metadata (output/extracted_schema.json)
"""

import json
import os
from pathlib import Path
from datetime import datetime

from src.config import ConfigLoader
from src.database import DatabaseConnectionManager, SchemaExtractor
from src.exceptions import SchemaExtractionError, DatabaseConnectionError


def main():
    """Main function to demonstrate schema extraction."""
    print("=" * 70)
    print("Database Schema Extraction Example")
    print("=" * 70)
    print()
    
    try:
        # Load configuration
        print("Loading configuration...")
        config = ConfigLoader.load()
        database_name = config.database.database
        print(f"✓ Configuration loaded for database: {database_name}")
        print()
        
        # Create connection manager
        print("Establishing database connection...")
        connection_manager = DatabaseConnectionManager(config.database)
        
        # Test connection
        with connection_manager:
            result = connection_manager.execute_query("SELECT @@VERSION AS version")
            sql_version = result[0][0].split('\n')[0]
            print(f"✓ Connected to: {sql_version}")
        print()
        
        # Create schema extractor
        extractor = SchemaExtractor(connection_manager)
        
        # Extract schema
        print(f"Extracting schema from database '{database_name}'...")
        print("This may take a few moments for large databases...")
        print()
        
        schema = extractor.extract_schema(database_name)
        
        # Display summary statistics
        print("=" * 70)
        print("EXTRACTION SUMMARY")
        print("=" * 70)
        print(f"Database Name:           {schema['database_name']}")
        print(f"Extraction Time:         {schema['extraction_timestamp']}")
        print(f"Duration:                {schema['extraction_duration_ms']:.2f} ms")
        print()
        print(f"Tables Found:            {len(schema['tables'])}")
        print(f"Total Columns:           {sum(len(cols) for cols in schema['columns'].values())}")
        print(f"Primary Keys:            {sum(len(pks) for pks in schema['primary_keys'].values())}")
        print(f"Foreign Keys:            {len(schema['foreign_keys'])}")
        print(f"Unique Constraints:      {sum(len(ucs) for ucs in schema['unique_constraints'].values())}")
        print(f"Indexes:                 {sum(len(idxs) for idxs in schema['indexes'].values())}")
        print()
        
        # Display warnings if any
        if schema['warnings']:
            print("WARNINGS:")
            for warning in schema['warnings']:
                print(f"  ⚠ {warning}")
            print()
        
        # Display table details
        if schema['tables']:
            print("=" * 70)
            print("TABLE DETAILS")
            print("=" * 70)
            
            for table in schema['tables'][:10]:  # Show first 10 tables
                qualified_name = table['qualified_name']
                column_count = len(schema['columns'].get(qualified_name, []))
                pk_count = len(schema['primary_keys'].get(qualified_name, []))
                
                print(f"\nTable: {qualified_name}")
                print(f"  Columns: {column_count}")
                
                if pk_count > 0:
                    pk_cols = ', '.join(schema['primary_keys'][qualified_name])
                    print(f"  Primary Key: {pk_cols}")
                else:
                    print(f"  Primary Key: None")
                
                # Show column details
                if qualified_name in schema['columns']:
                    print(f"  Column Details:")
                    for col in schema['columns'][qualified_name][:5]:  # Show first 5 columns
                        nullable = "NULL" if col['is_nullable'] else "NOT NULL"
                        identity = " IDENTITY" if col['is_identity'] else ""
                        
                        if col['data_type'] in ('VARCHAR', 'NVARCHAR', 'CHAR', 'NCHAR'):
                            type_info = f"{col['data_type']}({col['max_length'] if col['max_length'] != -1 else 'MAX'})"
                        elif col['data_type'] in ('DECIMAL', 'NUMERIC'):
                            type_info = f"{col['data_type']}({col['precision']}, {col['scale']})"
                        else:
                            type_info = col['data_type']
                        
                        print(f"    - {col['name']:<30} {type_info:<20} {nullable}{identity}")
                    
                    if len(schema['columns'][qualified_name]) > 5:
                        remaining = len(schema['columns'][qualified_name]) - 5
                        print(f"    ... and {remaining} more columns")
            
            if len(schema['tables']) > 10:
                remaining = len(schema['tables']) - 10
                print(f"\n... and {remaining} more tables")
        
        # Display foreign key relationships
        if schema['foreign_keys']:
            print("\n" + "=" * 70)
            print("FOREIGN KEY RELATIONSHIPS")
            print("=" * 70)
            
            fk_groups = {}
            for fk in schema['foreign_keys']:
                key = fk['constraint_name']
                if key not in fk_groups:
                    fk_groups[key] = []
                fk_groups[key].append(fk)
            
            for constraint_name, fks in list(fk_groups.items())[:5]:  # Show first 5 FKs
                fk = fks[0]
                parent = f"[{fk['parent_schema']}].[{fk['parent_table']}]"
                child = f"[{fk['child_schema']}].[{fk['child_table']}]"
                
                if fk['is_self_referencing']:
                    print(f"\n{constraint_name} (Self-Referencing):")
                else:
                    print(f"\n{constraint_name}:")
                
                print(f"  {child}")
                for fk_col in fks:
                    print(f"    {fk_col['child_column']} → {parent}.{fk_col['parent_column']}")
            
            if len(fk_groups) > 5:
                remaining = len(fk_groups) - 5
                print(f"\n... and {remaining} more foreign keys")
        
        # Save to JSON file
        print("\n" + "=" * 70)
        print("SAVING TO FILE")
        print("=" * 70)
        
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        
        output_file = output_dir / "extracted_schema.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
        
        file_size = output_file.stat().st_size / 1024  # KB
        print(f"✓ Schema saved to: {output_file}")
        print(f"  File size: {file_size:.2f} KB")
        print()
        
        print("=" * 70)
        print("✓ Schema extraction completed successfully!")
        print("=" * 70)
        
    except SchemaExtractionError as e:
        print(f"\n❌ Schema Extraction Error: {e}")
        print(f"   Error Code: {e.error_code}")
        print(f"   Suggested Action: {e.suggested_action}")
        if e.operation_context:
            print(f"   Context: {e.operation_context}")
        return 1
    
    except DatabaseConnectionError as e:
        print(f"\n❌ Database Connection Error: {e}")
        print(f"   Error Code: {e.error_code}")
        print(f"   Suggested Action: {e.suggested_action}")
        return 1
    
    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")
        print("\nPlease check:")
        print("  1. SQL Server is running and accessible")
        print("  2. Configuration file exists (config/pii_config.json)")
        print("  3. Environment variables are set correctly")
        print("  4. Database credentials are valid")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
