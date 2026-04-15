#!/usr/bin/env python3
"""
Mapping Discrepancy Diagnostic Tool
====================================

This script analyzes token_mappings to identify reasons why some mappings
might not be restored during desanitization.

Common Issues Detected:
    - Orphaned mappings (records deleted after sanitization)
    - Duplicate mappings (same record mapped multiple times)
    - Primary key format mismatches
    - Tables that no longer exist

Usage:
    python diagnose_mappings.py
    python diagnose_mappings.py --table HumanResources.Employee
    python diagnose_mappings.py --verbose
"""

import argparse
import os
import sys
import pyodbc
from datetime import datetime
from collections import defaultdict


class Colors:
    """ANSI color codes for terminal output."""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def get_connection_string():
    """Build connection string from environment variables."""
    server = os.getenv('SQLSERVER_HOST', '(localdb)\\MSSQLLocalDB')
    database = os.getenv('SQLSERVER_DB', 'AdventureWorks2016')
    auth_type = os.getenv('SQLSERVER_AUTH', 'windows')
    
    if auth_type.lower() == 'windows':
        return (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"Trusted_Connection=yes;"
        )
    else:
        username = os.getenv('SQLSERVER_USER')
        password = os.getenv('SQLSERVER_PASSWORD')
        return (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
        )


def check_duplicates(conn, table_filter=None):
    """Check for duplicate mappings (same record mapped multiple times)."""
    cursor = conn.cursor()
    
    query = """
        SELECT 
            table_name,
            column_name,
            record_id,
            COUNT(*) as duplicate_count
        FROM dbo.token_mappings
    """
    
    if table_filter:
        query += " WHERE table_name = ?"
        cursor.execute(query + " GROUP BY table_name, column_name, record_id HAVING COUNT(*) > 1", (table_filter,))
    else:
        cursor.execute(query + " GROUP BY table_name, column_name, record_id HAVING COUNT(*) > 1")
    
    duplicates = cursor.fetchall()
    
    if duplicates:
        print(f"\n{Colors.WARNING}⚠️ DUPLICATE MAPPINGS DETECTED{Colors.ENDC}")
        print(f"Found {len(duplicates)} record(s) with duplicate mappings:\n")
        
        total_excess = 0
        for table_name, column_name, record_id, count in duplicates[:10]:
            excess = count - 1
            total_excess += excess
            print(f"  • {table_name}.{column_name} | Record ID: {record_id[:50]}... | Count: {count} (+{excess} duplicate)")
        
        if len(duplicates) > 10:
            print(f"  ... and {len(duplicates) - 10} more")
        
        print(f"\n  {Colors.BOLD}Total excess mappings:{Colors.ENDC} {total_excess:,}")
        print(f"  {Colors.BOLD}Impact:{Colors.ENDC} These duplicates inflate the mappings_applied count")
        return total_excess
    else:
        print(f"\n{Colors.OKGREEN}✓ No duplicate mappings found{Colors.ENDC}")
        return 0


def check_orphaned_records(conn, table_filter=None, verbose=False):
    """Check for orphaned mappings (records that don't exist in actual tables)."""
    cursor = conn.cursor()
    
    # Get distinct tables from mappings
    if table_filter:
        cursor.execute("SELECT DISTINCT table_name FROM dbo.token_mappings WHERE table_name = ?", (table_filter,))
    else:
        cursor.execute("SELECT DISTINCT table_name FROM dbo.token_mappings")
    
    tables = [row[0] for row in cursor.fetchall()]
    
    print(f"\n{Colors.OKCYAN}Checking for orphaned records in {len(tables)} table(s)...{Colors.ENDC}\n")
    
    total_orphaned = 0
    orphaned_tables = []
    
    for table_name in tables:
        # Parse table name (format: "Schema.Table")
        if '.' in table_name:
            schema, table = table_name.split('.', 1)
        else:
            schema = 'dbo'
            table = table_name
        
        # Check if table exists
        cursor.execute("""
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        """, (schema, table))
        
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "SELECT COUNT(*) FROM dbo.token_mappings WHERE table_name = ?",
                (table_name,)
            )
            mapping_count = cursor.fetchone()[0]
            
            print(f"  {Colors.FAIL}✗ Table {table_name} does not exist!{Colors.ENDC}")
            print(f"    Orphaned mappings: {mapping_count:,}")
            total_orphaned += mapping_count
            orphaned_tables.append((table_name, mapping_count, "table_deleted"))
            continue
        
        # Get primary key columns
        cursor.execute("""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = ? 
            AND TABLE_NAME = ?
            AND CONSTRAINT_NAME LIKE 'PK_%'
            ORDER BY ORDINAL_POSITION
        """, (schema, table))
        
        pk_columns = [row[0] for row in cursor.fetchall()]
        
        if not pk_columns:
            if verbose:
                print(f"  {Colors.WARNING}⚠ {table_name}: No primary key found, skipping orphan check{Colors.ENDC}")
            continue
        
        # For simple PKs, check orphaned records
        if len(pk_columns) == 1:
            pk_col = pk_columns[0]
            
            # Count total mappings for this table
            cursor.execute(
                "SELECT COUNT(DISTINCT record_id) FROM dbo.token_mappings WHERE table_name = ?",
                (table_name,)
            )
            total_mappings = cursor.fetchone()[0]
            
            # Count orphaned mappings (exist in mappings but not in table)
            orphan_query = f"""
                SELECT COUNT(DISTINCT tm.record_id)
                FROM dbo.token_mappings tm
                WHERE tm.table_name = ?
                AND NOT EXISTS (
                    SELECT 1 
                    FROM [{schema}].[{table}] t
                    WHERE CAST(t.[{pk_col}] AS NVARCHAR(MAX)) = tm.record_id
                )
            """
            
            cursor.execute(orphan_query, (table_name,))
            orphaned_count = cursor.fetchone()[0]
            
            if orphaned_count > 0:
                orphaned_pct = (orphaned_count / total_mappings * 100) if total_mappings > 0 else 0
                print(f"  {Colors.WARNING}⚠ {table_name}:{Colors.ENDC}")
                print(f"    Total distinct records in mappings: {total_mappings:,}")
                print(f"    Orphaned records: {orphaned_count:,} ({orphaned_pct:.1f}%)")
                total_orphaned += orphaned_count
                orphaned_tables.append((table_name, orphaned_count, "records_deleted"))
            elif verbose:
                print(f"  {Colors.OKGREEN}✓ {table_name}: All {total_mappings:,} records exist{Colors.ENDC}")
        elif verbose:
            print(f"  {Colors.OKCYAN}ℹ {table_name}: Composite PK, skipping detailed check{Colors.ENDC}")
    
    if total_orphaned > 0:
        print(f"\n{Colors.WARNING}{Colors.BOLD}⚠️ ORPHANED MAPPINGS SUMMARY{Colors.ENDC}")
        print(f"  Total orphaned records: {total_orphaned:,}")
        print(f"  Affected tables: {len(orphaned_tables)}")
        print(f"\n  {Colors.BOLD}Impact:{Colors.ENDC} These mappings cannot be restored (records deleted post-sanitization)")
        return total_orphaned, orphaned_tables
    else:
        print(f"\n{Colors.OKGREEN}✓ No orphaned records found{Colors.ENDC}")
        return 0, []


def analyze_mapping_stats(conn, table_filter=None):
    """Show overall mapping statistics."""
    cursor = conn.cursor()
    
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}MAPPING TABLE STATISTICS{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}\n")
    
    # Total mappings
    if table_filter:
        cursor.execute("SELECT COUNT(*) FROM dbo.token_mappings WHERE table_name = ?", (table_filter,))
    else:
        cursor.execute("SELECT COUNT(*) FROM dbo.token_mappings")
    total_mappings = cursor.fetchone()[0]
    
    # Distinct records
    if table_filter:
        cursor.execute(
            "SELECT COUNT(DISTINCT record_id) FROM dbo.token_mappings WHERE table_name = ?",
            (table_filter,)
        )
    else:
        cursor.execute("SELECT COUNT(DISTINCT record_id) FROM dbo.token_mappings")
    distinct_records = cursor.fetchone()[0]
    
    # Tables and columns
    if table_filter:
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT table_name) as tables,
                COUNT(DISTINCT column_name) as columns
            FROM dbo.token_mappings
            WHERE table_name = ?
        """, (table_filter,))
    else:
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT table_name) as tables,
                COUNT(DISTINCT column_name) as columns
            FROM dbo.token_mappings
        """)
    tables, columns = cursor.fetchone()
    
    print(f"  Total Mappings:        {total_mappings:,}")
    print(f"  Distinct Records:      {distinct_records:,}")
    print(f"  Tables with Mappings:  {tables}")
    print(f"  Columns with Mappings: {columns}")
    
    if total_mappings > distinct_records:
        duplicate_count = total_mappings - distinct_records
        print(f"\n  {Colors.WARNING}Note: {duplicate_count:,} duplicate mapping(s) detected{Colors.ENDC}")


def main():
    parser = argparse.ArgumentParser(
        description='Diagnose mapping table discrepancies',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--table',
        help='Filter analysis to specific table (format: Schema.Table)',
        default=None
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed output for all tables'
    )
    
    args = parser.parse_args()
    
    try:
        # Connect to database
        conn_str = get_connection_string()
        conn = pyodbc.connect(conn_str)
        
        # Run diagnostics
        analyze_mapping_stats(conn, args.table)
        duplicate_count = check_duplicates(conn, args.table)
        orphaned_count, orphaned_tables = check_orphaned_records(conn, args.table, args.verbose)
        
        # Final summary
        print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}DIAGNOSTIC SUMMARY{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}\n")
        
        total_discrepancy = duplicate_count + orphaned_count
        
        if total_discrepancy > 0:
            print(f"  {Colors.WARNING}Expected discrepancy: {total_discrepancy:,}{Colors.ENDC}")
            print(f"    • Duplicate mappings: {duplicate_count:,}")
            print(f"    • Orphaned records: {orphaned_count:,}")
            print(f"\n  {Colors.BOLD}Explanation:{Colors.ENDC}")
            print(f"    When you run desanitization, you may see:")
            print(f"    - Mappings Applied: [higher number]")
            print(f"    - Records Restored: [lower number by ~{total_discrepancy:,}]")
            print(f"\n  {Colors.OKCYAN}This is expected and does not indicate a failure.{Colors.ENDC}")
        else:
            print(f"  {Colors.OKGREEN}✓ No discrepancies detected{Colors.ENDC}")
            print(f"  Mappings should restore 1:1 with records")
        
        print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}\n")
        
        conn.close()
        return 0
        
    except Exception as e:
        print(f"\n{Colors.FAIL}Error: {e}{Colors.ENDC}\n")
        return 1


if __name__ == '__main__':
    sys.exit(main())
