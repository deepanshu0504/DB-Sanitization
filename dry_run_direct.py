"""
Direct dry-run script for database sanitization preview.
Bypasses framework logger to avoid hanging issues.
Shows what would be sanitized without making any database changes.
"""

import json
import pyodbc
import random
import string
from typing import Dict, List, Any
from datetime import datetime


class SimpleMasker:
    """Simple masking logic for different PII types."""
    
    @staticmethod
    def mask_name(original: str) -> str:
        """Generate fake name."""
        first_names = ["John", "Jane", "Michael", "Sarah", "David", "Emily", "James", "Emma", "Robert", "Olivia"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez"]
        return f"{random.choice(first_names)} {random.choice(last_names)}"
    
    @staticmethod
    def mask_email(original: str) -> str:
        """Generate fake email."""
        names = ["user", "contact", "info", "admin", "support", "hello", "team", "person", "john", "jane"]
        domains = ["example.com", "test.com", "domain.com", "email.com", "mail.com"]
        num = random.randint(100, 999)
        return f"{random.choice(names)}{num}@{random.choice(domains)}"
    
    @staticmethod
    def mask_phone(original: str) -> str:
        """Generate fake phone number."""
        area = random.randint(200, 999)
        prefix = random.randint(200, 999)
        line = random.randint(1000, 9999)
        return f"({area}) {prefix}-{line}"
    
    @staticmethod
    def mask_ssn(original: str) -> str:
        """Generate fake SSN."""
        return f"{random.randint(100,999)}-{random.randint(10,99)}-{random.randint(1000,9999)}"
    
    @staticmethod
    def mask_address(original: str) -> str:
        """Generate fake address."""
        numbers = random.randint(100, 9999)
        streets = ["Main St", "Oak Ave", "Elm St", "Maple Dr", "Cedar Ln", "Pine Rd", "Washington Blvd"]
        cities = ["Springfield", "Franklin", "Clinton", "Madison", "Georgetown"]
        states = ["CA", "NY", "TX", "FL", "IL", "PA", "OH"]
        zip_code = random.randint(10000, 99999)
        return f"{numbers} {random.choice(streets)}, {random.choice(cities)}, {random.choice(states)} {zip_code}"
    
    @staticmethod
    def mask_generic(original: str) -> str:
        """Generate generic masked value."""
        if original is None:
            return None
        length = len(str(original))
        if length <= 4:
            return ''.join(random.choices(string.ascii_letters + string.digits, k=length))
        else:
            # Keep first and last char, mask middle
            chars = string.ascii_letters + string.digits
            middle = ''.join(random.choices(chars, k=length - 2))
            return f"{original[0]}{middle}{original[-1]}"


def load_config(config_path: str) -> Dict[str, Any]:
    """Load PII configuration from JSON file."""
    with open(config_path, 'r') as f:
        return json.load(f)


def connect_to_database(server: str, database: str) -> pyodbc.Connection:
    """Connect to SQL Server database."""
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"Trusted_Connection=yes;"
        f"Connection Timeout=30;"
        f"Login Timeout=30;"
    )
    return pyodbc.connect(conn_str)


def get_sample_data(conn: pyodbc.Connection, schema: str, table: str, column: str, limit: int = 5) -> List[Any]:
    """Get sample data from a column."""
    query = f"""
    SELECT TOP {limit} [{column}]
    FROM [{schema}].[{table}]
    WHERE [{column}] IS NOT NULL
    ORDER BY NEWID()
    """
    cursor = conn.cursor()
    cursor.execute(query)
    return [row[0] for row in cursor.fetchall()]


def get_row_count(conn: pyodbc.Connection, schema: str, table: str, column: str) -> int:
    """Get count of non-null rows in a column."""
    query = f"""
    SELECT COUNT(*)
    FROM [{schema}].[{table}]
    WHERE [{column}] IS NOT NULL
    """
    cursor = conn.cursor()
    cursor.execute(query)
    return cursor.fetchone()[0]


def check_foreign_keys(conn: pyodbc.Connection, schema: str, table: str, column: str) -> List[Dict[str, str]]:
    """Check if column is involved in foreign key relationships."""
    query = """
    SELECT 
        fk.name AS FK_Name,
        OBJECT_NAME(fk.parent_object_id) AS Child_Table,
        COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS Child_Column,
        OBJECT_NAME(fk.referenced_object_id) AS Parent_Table,
        COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS Parent_Column
    FROM sys.foreign_keys fk
    INNER JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
    WHERE 
        (OBJECT_NAME(fk.parent_object_id) = ? AND COL_NAME(fkc.parent_object_id, fkc.parent_column_id) = ?)
        OR
        (OBJECT_NAME(fk.referenced_object_id) = ? AND COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) = ?)
    """
    cursor = conn.cursor()
    cursor.execute(query, (table, column, table, column))
    
    fks = []
    for row in cursor.fetchall():
        fks.append({
            'name': row.FK_Name,
            'child_table': row.Child_Table,
            'child_column': row.Child_Column,
            'parent_table': row.Parent_Table,
            'parent_column': row.Parent_Column
        })
    return fks


def preview_masking(pii_type: str, samples: List[Any]) -> List[str]:
    """Generate preview of masked values."""
    masker = SimpleMasker()
    
    masking_methods = {
        'name': masker.mask_name,
        'email': masker.mask_email,
        'phone': masker.mask_phone,
        'ssn': masker.mask_ssn,
        'address': masker.mask_address,
        'generic': masker.mask_generic,
    }
    
    mask_func = masking_methods.get(pii_type, masker.mask_generic)
    return [mask_func(sample) for sample in samples]


def run_dry_run(config_path: str):
    """Execute dry-run preview of sanitization."""
    print("=" * 80)
    print("DATABASE SANITIZATION - DRY RUN PREVIEW")
    print("=" * 80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Config: {config_path}")
    print()
    
    # Load configuration
    print("[1/4] Loading configuration...")
    config = load_config(config_path)
    
    db_config = config.get('database', {})
    server = db_config.get('server', '')
    database = db_config.get('database', '')
    pii_columns = config.get('pii_columns', [])
    
    print(f"  Server: {server}")
    print(f"  Database: {database}")
    print(f"  PII Columns: {len(pii_columns)}")
    print()
    
    # Connect to database
    print("[2/4] Connecting to database...")
    try:
        conn = connect_to_database(server, database)
        print("  ✓ Connection successful")
        print()
    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        return
    
    # Analyze each PII column
    print("[3/4] Analyzing PII columns...")
    print()
    
    total_rows_affected = 0
    fk_columns = []
    
    for idx, pii_col in enumerate(pii_columns, 1):
        schema = pii_col.get('schema', 'dbo')
        table = pii_col.get('table', '')
        column = pii_col.get('column', '')
        pii_type = pii_col.get('pii_type', 'generic')
        
        print(f"[{idx}/{len(pii_columns)}] {schema}.{table}.{column}")
        print(f"     Type: {pii_type}")
        
        try:
            # Get row count
            row_count = get_row_count(conn, schema, table, column)
            total_rows_affected += row_count
            print(f"     Rows to sanitize: {row_count:,}")
            
            # Check for foreign keys
            fks = check_foreign_keys(conn, schema, table, column)
            if fks:
                fk_columns.append({
                    'column': f"{schema}.{table}.{column}",
                    'fks': fks
                })
                print(f"     ⚠️  Foreign Key Detected: {len(fks)} relationship(s)")
                for fk in fks:
                    if fk['child_table'] == table and fk['child_column'] == column:
                        print(f"         → References {fk['parent_table']}.{fk['parent_column']}")
                    else:
                        print(f"         → Referenced by {fk['child_table']}.{fk['child_column']}")
            
            # Get sample data
            samples = get_sample_data(conn, schema, table, column, limit=3)
            
            if samples:
                print(f"     Sample transformations:")
                masked_samples = preview_masking(pii_type, samples)
                
                for i, (original, masked) in enumerate(zip(samples, masked_samples), 1):
                    # Truncate long values for display
                    orig_display = str(original)[:50] + "..." if len(str(original)) > 50 else str(original)
                    masked_display = str(masked)[:50] + "..." if len(str(masked)) > 50 else str(masked)
                    print(f"       {i}. '{orig_display}' → '{masked_display}'")
            else:
                print(f"     No data to preview (all NULL)")
            
            print()
            
        except Exception as e:
            print(f"     ✗ Error: {e}")
            print()
    
    # Generate summary
    print("[4/4] Summary")
    print("-" * 80)
    print(f"Total PII columns: {len(pii_columns)}")
    print(f"Total rows affected: {total_rows_affected:,}")
    print()
    
    if fk_columns:
        print("⚠️  FOREIGN KEY HANDLING:")
        print("The following columns are part of foreign key relationships.")
        print("The framework will use mapping tables to maintain referential integrity:")
        print()
        for fk_info in fk_columns:
            print(f"  • {fk_info['column']}")
            for fk in fk_info['fks']:
                if fk['child_column'] in fk_info['column']:
                    print(f"      → Child of {fk['parent_table']}.{fk['parent_column']}")
                else:
                    print(f"      → Parent of {fk['child_table']}.{fk['child_column']}")
        print()
    
    print("=" * 80)
    print("DRY RUN COMPLETE - NO CHANGES MADE TO DATABASE")
    print("=" * 80)
    print()
    print("Next steps:")
    print("  1. Review the sample transformations above")
    print("  2. Verify foreign key relationships are acceptable")
    print("  3. If satisfied, set dry_run=false in config and run actual sanitization")
    print("  4. IMPORTANT: Back up your database before actual sanitization!")
    print()
    
    conn.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    else:
        config_file = "config/pii_config_ai_generated.json"
    
    try:
        run_dry_run(config_file)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
