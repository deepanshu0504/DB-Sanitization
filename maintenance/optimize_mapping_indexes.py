"""
Automated index maintenance for token_mappings table.

This module provides a Python wrapper for the SQL Server index maintenance
script, enabling scheduled or on-demand optimization.

Story 5.3: Optimized Mapping Lookups

Usage:
    python -m maintenance.optimize_mapping_indexes --connection-string "..." --execute
    
    OR
    
    from maintenance import optimize_mapping_indexes
    optimize_mapping_indexes(connection_string, dry_run=False)
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

import pyodbc


def execute_sql_script(
    connection_string: str,
    script_path: str,
    print_output: bool = True
) -> Dict[str, Any]:
    """
    Execute SQL script and capture results.
    
    Args:
        connection_string: SQL Server connection string
        script_path: Path to SQL script file
        print_output: Print SQL output messages
        
    Returns:
        Dictionary with execution results
        
    Raises:
        FileNotFoundError: If script file not found
        pyodbc.Error: If execution fails
    """
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"SQL script not found: {script_path}")
    
    # Read script
    with open(script_path, 'r', encoding='utf-8') as f:
        script_content = f.read()
    
    # Parse batches (split by GO)
    batches = [
        batch.strip() 
        for batch in script_content.split('\nGO\n')
        if batch.strip() and not batch.strip().startswith('--')
    ]
    
    results = {
        "started_at": datetime.now(),
        "batches_executed": 0,
        "batches_failed": 0,
        "output_messages": [],
        "errors": []
    }
    
    try:
        # Create connection with PRINT message handling
        conn = pyodbc.connect(connection_string)
        conn.autocommit = True  # Required for ALTER INDEX operations
        cursor = conn.cursor()
        
        # Execute each batch
        for batch_num, batch in enumerate(batches, 1):
            try:
                # Execute batch
                cursor.execute(batch)
                
                # Capture PRINT messages (SQL Server info messages)
                while cursor.nextset():
                    pass
                
                results["batches_executed"] += 1
                
                # Check for messages
                if cursor.messages:
                    for msg in cursor.messages:
                        message_text = str(msg[1])
                        results["output_messages"].append(message_text)
                        if print_output:
                            print(message_text)
                
            except pyodbc.Error as e:
                # Capture error but continue
                error_msg = f"Batch {batch_num} failed: {str(e)}"
                results["errors"].append(error_msg)
                results["batches_failed"] += 1
                if print_output:
                    print(f"ERROR: {error_msg}", file=sys.stderr)
        
        cursor.close()
        conn.close()
        
        results["completed_at"] = datetime.now()
        results["duration_seconds"] = (
            results["completed_at"] - results["started_at"]
        ).total_seconds()
        
        return results
        
    except pyodbc.Error as e:
        results["completed_at"] = datetime.now()
        results["errors"].append(f"Connection or execution failed: {str(e)}")
        raise


def optimize_mapping_indexes(
    connection_string: str,
    table_name: str = "token_mappings",
    schema: str = "dbo",
    dry_run: bool = True,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Optimize indexes for mapping table.
    
    Args:
        connection_string: SQL Server connection string
        table_name: Name of mapping table (default: token_mappings)
        schema: Database schema (default: dbo)
        dry_run: If True, only analyze fragmentation without maintenance
        verbose: Print detailed output
        
    Returns:
        Dictionary with maintenance results
        
    Example:
        >>> result = optimize_mapping_indexes(
        ...     connection_string="...",
        ...     dry_run=False,
        ...     verbose=True
        ... )
        >>> print(f"Optimized {result['indexes_processed']} indexes")
    """
    # Locate SQL script
    script_dir = Path(__file__).parent.parent / "scripts"
    script_path = script_dir / "maintain_mapping_indexes.sql"
    
    if not script_path.exists():
        raise FileNotFoundError(
            f"Index maintenance script not found: {script_path}\n"
            f"Expected: scripts/maintain_mapping_indexes.sql"
        )
    
    if verbose:
        print("=" * 70)
        print("Index Maintenance Utility")
        print("=" * 70)
        print(f"Table: [{schema}].[{table_name}]")
        print(f"Mode: {'DRY RUN (Analysis Only)' if dry_run else 'EXECUTE (Maintenance)'}")
        print(f"Script: {script_path}")
        print("=" * 70)
        print()
    
    if dry_run:
        # Dry run: Only analyze fragmentation
        from database import QueryPerformanceAnalyzer
        
        analyzer = QueryPerformanceAnalyzer(connection_string, table_name, schema)
        
        if verbose:
            print("Analyzing index fragmentation...")
            print()
        
        fragmentation = analyzer.get_index_fragmentation(fragmentation_threshold=0)
        
        if verbose:
            print(f"{'Index Name':<40} {'Fragmentation %':<20} {'Recommendation':<15}")
            print("-" * 70)
            for idx in fragmentation:
                print(f"{idx.index_name:<40} {idx.fragmentation_percent:<20.2f} {idx.recommendation:<15}")
            print()
            
            high_frag = [idx for idx in fragmentation if idx.fragmentation_percent >= 30]
            med_frag = [idx for idx in fragmentation if 10 <= idx.fragmentation_percent < 30]
            
            print(f"Summary:")
            print(f"  Indexes needing REBUILD: {len(high_frag)}")
            print(f"  Indexes needing REORGANIZE: {len(med_frag)}")
            print(f"  Indexes OK: {len(fragmentation) - len(high_frag) - len(med_frag)}")
            print()
            print("To execute maintenance, run with --execute flag")
        
        return {
            "mode": "dry_run",
            "indexes_analyzed": len(fragmentation),
            "rebuild_needed": len([idx for idx in fragmentation if idx.fragmentation_percent >= 30]),
            "reorganize_needed": len([idx for idx in fragmentation if 10 <= idx.fragmentation_percent < 30]),
            "fragmentation_data": [idx.to_dict() for idx in fragmentation]
        }
    
    else:
        # Execute maintenance
        if verbose:
            print("Executing index maintenance...")
            print()
        
        results = execute_sql_script(
            connection_string,
            str(script_path),
            print_output=verbose
        )
        
        if verbose:
            print()
            print("=" * 70)
            print("Maintenance Complete")
            print("=" * 70)
            print(f"Duration: {results['duration_seconds']:.2f} seconds")
            print(f"Batches executed: {results['batches_executed']}")
            print(f"Batches failed: {results['batches_failed']}")
            if results['errors']:
                print(f"Errors: {len(results['errors'])}")
                for error in results['errors']:
                    print(f"  - {error}")
            print("=" * 70)
        
        return {
            "mode": "execute",
            "duration_seconds": results['duration_seconds'],
            "batches_executed": results['batches_executed'],
            "batches_failed": results['batches_failed'],
            "success": results['batches_failed'] == 0,
            "errors": results['errors']
        }


def main():
    """CLI entry point for index maintenance."""
    parser = argparse.ArgumentParser(
        description="Optimize indexes for token_mappings table",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze fragmentation only (dry run)
  python optimize_mapping_indexes.py --connection-string "..."
  
  # Execute maintenance
  python optimize_mapping_indexes.py --connection-string "..." --execute
  
  # Custom table name
  python optimize_mapping_indexes.py --connection-string "..." --table my_mappings --execute
  
  # Quiet mode
  python optimize_mapping_indexes.py --connection-string "..." --execute --quiet
"""
    )
    
    parser.add_argument(
        "--connection-string",
        required=True,
        help="SQL Server connection string"
    )
    
    parser.add_argument(
        "--table",
        default="token_mappings",
        help="Mapping table name (default: token_mappings)"
    )
    
    parser.add_argument(
        "--schema",
        default="dbo",
        help="Database schema (default: dbo)"
    )
    
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute maintenance (default is dry-run)"
    )
    
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose output"
    )
    
    args = parser.parse_args()
    
    try:
        result = optimize_mapping_indexes(
            connection_string=args.connection_string,
            table_name=args.table,
            schema=args.schema,
            dry_run=not args.execute,
            verbose=not args.quiet
        )
        
        # Exit code
        if result.get("mode") == "execute":
            sys.exit(0 if result.get("success") else 1)
        else:
            sys.exit(0)
            
    except Exception as e:
        print(f"ERROR: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
