"""
Direct sanitization script for actual database modification.
Bypasses framework logger to avoid hanging issues.
Performs actual PII masking with mapping table support for FK relationships.
"""

import json
import pyodbc
import random
import string
import hashlib
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from collections import defaultdict


class SimpleMasker:
    """Simple masking logic for different PII types with consistent mapping."""
    
    def __init__(self, seed: Optional[int] = None):
        """Initialize with optional seed for reproducibility."""
        if seed:
            random.seed(seed)
        self._mapping_cache = {}  # Cache for consistent masking
    
    def mask_with_mapping(self, original: Any, pii_type: str, use_mapping: bool = True) -> str:
        """
        Mask value with optional mapping for consistency.
        If use_mapping=True, same original value always produces same masked value.
        """
        if original is None:
            return None
        
        # Create deterministic key for mapping
        if use_mapping:
            cache_key = f"{pii_type}:{str(original)}"
            if cache_key in self._mapping_cache:
                return self._mapping_cache[cache_key]
        
        # Generate masked value
        masking_methods = {
            'name': self.mask_name,
            'email': self.mask_email,
            'phone': self.mask_phone,
            'ssn': self.mask_ssn,
            'address': self.mask_address,
            'generic': self.mask_generic,
        }
        
        mask_func = masking_methods.get(pii_type, self.mask_generic)
        
        # Use hash of original value as seed for deterministic masking
        if use_mapping:
            seed_value = int(hashlib.md5(str(original).encode()).hexdigest()[:8], 16)
            random.seed(seed_value)
        
        masked = mask_func(original)
        
        # Cache the mapping
        if use_mapping:
            self._mapping_cache[cache_key] = masked
        
        return masked
    
    def mask_name(self, original: str) -> str:
        """Generate fake name."""
        first_names = ["John", "Jane", "Michael", "Sarah", "David", "Emily", "James", "Emma", "Robert", "Olivia",
                      "William", "Sophia", "Richard", "Isabella", "Joseph", "Mia", "Thomas", "Charlotte", "Charles", "Amelia"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
                     "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin"]
        return f"{random.choice(first_names)} {random.choice(last_names)}"
    
    def mask_email(self, original: str) -> str:
        """Generate fake email."""
        names = ["user", "contact", "info", "admin", "support", "hello", "team", "person", "john", "jane",
                "customer", "client", "mail", "email", "test", "demo", "sample", "account", "member", "data"]
        domains = ["example.com", "test.com", "domain.com", "email.com", "mail.com",
                  "sample.org", "demo.net", "company.com", "business.com", "service.com"]
        num = random.randint(100, 9999)
        return f"{random.choice(names)}{num}@{random.choice(domains)}"
    
    def mask_phone(self, original: str) -> str:
        """Generate fake phone number."""
        area = random.randint(200, 999)
        prefix = random.randint(200, 999)
        line = random.randint(1000, 9999)
        return f"({area}) {prefix}-{line}"
    
    def mask_ssn(self, original: str) -> str:
        """Generate fake SSN."""
        return f"{random.randint(100,999)}-{random.randint(10,99)}-{random.randint(1000,9999)}"
    
    def mask_address(self, original: str) -> str:
        """Generate fake address."""
        numbers = random.randint(100, 9999)
        streets = ["Main St", "Oak Ave", "Elm St", "Maple Dr", "Cedar Ln", "Pine Rd", "Washington Blvd",
                  "Park Ave", "First St", "Second Ave", "Broadway", "Market St", "Hill Rd", "Lake Dr"]
        cities = ["Springfield", "Franklin", "Clinton", "Madison", "Georgetown", "Arlington", "Bristol",
                 "Chester", "Fairview", "Highland", "Riverside", "Salem", "Oakland", "Greenville"]
        states = ["CA", "NY", "TX", "FL", "IL", "PA", "OH", "GA", "NC", "MI", "NJ", "VA", "WA", "AZ", "MA"]
        zip_code = random.randint(10000, 99999)
        return f"{numbers} {random.choice(streets)}, {random.choice(cities)}, {random.choice(states)} {zip_code}"
    
    def mask_generic(self, original: str) -> str:
        """Generate generic masked value."""
        if original is None:
            return None
        original_str = str(original)
        length = len(original_str)
        
        if length == 0:
            return ""
        elif length <= 2:
            return ''.join(random.choices(string.ascii_letters + string.digits, k=length))
        else:
            # Keep first and last char, mask middle
            chars = string.ascii_letters + string.digits
            middle = ''.join(random.choices(chars, k=length - 2))
            return f"{original_str[0]}{middle}{original_str[-1]}"


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


def check_foreign_keys(conn: pyodbc.Connection) -> List[Dict[str, str]]:
    """Get all foreign key relationships in the database."""
    query = """
    SELECT 
        fk.name AS FK_Name,
        SCHEMA_NAME(parent_obj.schema_id) AS Child_Schema,
        OBJECT_NAME(fk.parent_object_id) AS Child_Table,
        COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS Child_Column,
        SCHEMA_NAME(ref_obj.schema_id) AS Parent_Schema,
        OBJECT_NAME(fk.referenced_object_id) AS Parent_Table,
        COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS Parent_Column
    FROM sys.foreign_keys fk
    INNER JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
    INNER JOIN sys.objects parent_obj ON fk.parent_object_id = parent_obj.object_id
    INNER JOIN sys.objects ref_obj ON fk.referenced_object_id = ref_obj.object_id
    """
    cursor = conn.cursor()
    cursor.execute(query)
    
    fks = []
    for row in cursor.fetchall():
        fks.append({
            'name': row.FK_Name,
            'child_schema': row.Child_Schema,
            'child_table': row.Child_Table,
            'child_column': row.Child_Column,
            'parent_schema': row.Parent_Schema,
            'parent_table': row.Parent_Table,
            'parent_column': row.Parent_Column
        })
    return fks


def identify_fk_columns(pii_columns: List[Dict], all_fks: List[Dict]) -> Tuple[List[str], Dict]:
    """
    Identify which PII columns are involved in FK relationships.
    Returns: (list of FK column identifiers, mapping of FK relationships)
    """
    fk_columns = []
    fk_mapping = defaultdict(list)
    
    for pii_col in pii_columns:
        schema = pii_col.get('schema', 'dbo')
        table = pii_col.get('table', '')
        column = pii_col.get('column', '')
        col_id = f"{schema}.{table}.{column}"
        
        # Check if this column is part of any FK
        for fk in all_fks:
            child_id = f"{fk['child_schema']}.{fk['child_table']}.{fk['child_column']}"
            parent_id = f"{fk['parent_schema']}.{fk['parent_table']}.{fk['parent_column']}"
            
            if col_id == child_id or col_id == parent_id:
                fk_columns.append(col_id)
                fk_mapping[col_id].append(fk)
    
    return list(set(fk_columns)), dict(fk_mapping)


def disable_foreign_keys(conn: pyodbc.Connection) -> List[Dict[str, str]]:
    """Disable all foreign key constraints and return list for re-enabling."""
    cursor = conn.cursor()
    
    # Get all FK constraints
    query = """
    SELECT 
        SCHEMA_NAME(parent_obj.schema_id) AS table_schema,
        OBJECT_NAME(fk.parent_object_id) AS table_name,
        fk.name AS constraint_name
    FROM sys.foreign_keys fk
    INNER JOIN sys.objects parent_obj ON fk.parent_object_id = parent_obj.object_id
    """
    cursor.execute(query)
    
    constraints = []
    for row in cursor.fetchall():
        constraint = {
            'schema': row.table_schema,
            'table': row.table_name,
            'name': row.constraint_name
        }
        constraints.append(constraint)
        
        # Disable the constraint
        disable_sql = f"ALTER TABLE [{constraint['schema']}].[{constraint['table']}] NOCHECK CONSTRAINT [{constraint['name']}]"
        cursor.execute(disable_sql)
    
    return constraints


def enable_foreign_keys(conn: pyodbc.Connection, constraints: List[Dict[str, str]]):
    """Re-enable foreign key constraints."""
    cursor = conn.cursor()
    
    for constraint in constraints:
        enable_sql = f"ALTER TABLE [{constraint['schema']}].[{constraint['table']}] CHECK CONSTRAINT [{constraint['name']}]"
        cursor.execute(enable_sql)


def sanitize_column(conn: pyodbc.Connection, schema: str, table: str, column: str, 
                   pii_type: str, masker: SimpleMasker, use_mapping: bool = True) -> int:
    """
    Sanitize a single column.
    Returns count of rows updated.
    """
    cursor = conn.cursor()
    
    # Get all non-null values
    select_query = f"""
    SELECT [{column}]
    FROM [{schema}].[{table}]
    WHERE [{column}] IS NOT NULL
    """
    
    cursor.execute(select_query)
    rows = cursor.fetchall()
    
    if not rows:
        return 0
    
    # Update each row
    update_query = f"""
    UPDATE [{schema}].[{table}]
    SET [{column}] = ?
    WHERE [{column}] = ?
    """
    
    updates = []
    for row in rows:
        original_value = row[0]
        masked_value = masker.mask_with_mapping(original_value, pii_type, use_mapping)
        updates.append((masked_value, original_value))
    
    # Execute batch update
    cursor.executemany(update_query, updates)
    
    return len(updates)


def run_sanitization(config_path: str, backup_first: bool = False):
    """Execute actual database sanitization."""
    print("=" * 80)
    print("DATABASE SANITIZATION - ACTUAL EXECUTION")
    print("=" * 80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Config: {config_path}")
    print()
    
    # Load configuration
    print("[1/6] Loading configuration...")
    config = load_config(config_path)
    
    db_config = config.get('database', {})
    server = db_config.get('server', '')
    database = db_config.get('database', '')
    pii_columns = config.get('pii_columns', [])
    
    print(f"  Server: {server}")
    print(f"  Database: {database}")
    print(f"  PII Columns: {len(pii_columns)}")
    print()
    
    # Check dry_run flag
    dry_run = config.get('dry_run', True)
    if dry_run:
        print("⚠️  WARNING: Config has dry_run=true")
        print("   This script will still make changes. Set dry_run=false to confirm.")
        response = input("   Continue anyway? (yes/no): ")
        if response.lower() != 'yes':
            print("   Aborted by user.")
            return
        print()
    
    # Connect to database
    print("[2/6] Connecting to database...")
    try:
        conn = connect_to_database(server, database)
        conn.autocommit = False  # Enable transaction mode
        print("  ✓ Connection successful (transaction mode enabled)")
        print()
    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        return
    
    # Analyze FK relationships
    print("[3/6] Analyzing foreign key relationships...")
    all_fks = check_foreign_keys(conn)
    fk_columns, fk_mapping = identify_fk_columns(pii_columns, all_fks)
    
    if fk_columns:
        print(f"  Found {len(fk_columns)} PII column(s) involved in FK relationships:")
        for fk_col in fk_columns:
            print(f"    • {fk_col}")
        print("  → Will use consistent mapping to preserve referential integrity")
    else:
        print("  No FK relationships detected")
    print()
    
    # Backup warning
    if backup_first:
        print("[4/6] Database backup...")
        print("  ⚠️  Backup recommended but not implemented in this script")
        print("  ⚠️  Please ensure you have a recent backup!")
        response = input("  Do you have a backup? (yes/no): ")
        if response.lower() != 'yes':
            print("  Please create a backup first. Aborting.")
            conn.close()
            return
        print()
    else:
        print("[4/6] Skipping backup check...")
        print()
    
    # Initialize masker
    masker = SimpleMasker(seed=42)  # Deterministic seed for reproducibility
    
    # Disable FK constraints if needed
    disabled_constraints = []
    if fk_columns:
        print(f"  → Temporarily disabling {len(all_fks)} FK constraint(s) for safe update...")
        try:
            disabled_constraints = disable_foreign_keys(conn)
            print(f"  ✓ Disabled {len(disabled_constraints)} FK constraint(s)")
        except Exception as e:
            print(f"  ✗ Failed to disable FK constraints: {e}")
            conn.close()
            return
        print()
    
    # Sanitize columns
    print("[5/6] Sanitizing PII columns...")
    print()
    
    total_rows_updated = 0
    success_count = 0
    error_count = 0
    results = []
    
    try:
        for idx, pii_col in enumerate(pii_columns, 1):
            schema = pii_col.get('schema', 'dbo')
            table = pii_col.get('table', '')
            column = pii_col.get('column', '')
            pii_type = pii_col.get('pii_type', 'generic')
            col_id = f"{schema}.{table}.{column}"
            
            print(f"[{idx}/{len(pii_columns)}] Sanitizing {col_id}")
            print(f"     Type: {pii_type}")
            
            try:
                # Use mapping for FK columns to ensure consistency
                use_mapping = col_id in fk_columns
                
                rows_updated = sanitize_column(conn, schema, table, column, pii_type, masker, use_mapping)
                total_rows_updated += rows_updated
                success_count += 1
                
                print(f"     ✓ Updated {rows_updated:,} rows")
                results.append({
                    'column': col_id,
                    'status': 'success',
                    'rows': rows_updated,
                    'type': pii_type
                })
                
            except Exception as e:
                error_count += 1
                print(f"     ✗ Error: {e}")
                results.append({
                    'column': col_id,
                    'status': 'error',
                    'error': str(e),
                    'type': pii_type
                })
            
            print()
        
        # Commit or rollback
        if error_count == 0:
            print("  All columns sanitized successfully.")
            
            # Re-enable FK constraints before committing
            if disabled_constraints:
                print("  Re-enabling FK constraints...")
                try:
                    enable_foreign_keys(conn, disabled_constraints)
                    print(f"  ✓ Re-enabled {len(disabled_constraints)} FK constraint(s)")
                except Exception as e:
                    print(f"  ✗ Failed to re-enable FK constraints: {e}")
                    print("  Rolling back transaction...")
                    conn.rollback()
                    print("  ✓ Transaction rolled back - NO CHANGES MADE")
                    error_count += 1
                    conn.close()
                    return
            
            print("  Committing transaction...")
            conn.commit()
            print("  ✓ Transaction committed")
        else:
            print(f"  ⚠️  {error_count} error(s) occurred.")
            
            # Re-enable FK constraints before rollback
            if disabled_constraints:
                print("  Re-enabling FK constraints...")
                try:
                    enable_foreign_keys(conn, disabled_constraints)
                    print(f"  ✓ Re-enabled {len(disabled_constraints)} FK constraint(s)")
                except Exception as e:
                    print(f"  ⚠️  Warning: Failed to re-enable FK constraints: {e}")
            
            print("  Rolling back transaction...")
            conn.rollback()
            print("  ✓ Transaction rolled back - NO CHANGES MADE")
        
    except Exception as e:
        print(f"  ✗ Critical error: {e}")
        
        # Re-enable FK constraints before rollback
        if disabled_constraints:
            print("  Re-enabling FK constraints...")
            try:
                enable_foreign_keys(conn, disabled_constraints)
                print(f"  ✓ Re-enabled {len(disabled_constraints)} FK constraint(s)")
            except Exception as e2:
                print(f"  ⚠️  Warning: Failed to re-enable FK constraints: {e2}")
        
        print("  Rolling back transaction...")
        conn.rollback()
        print("  ✓ Transaction rolled back - NO CHANGES MADE")
        error_count += 1
    
    print()
    
    # Summary
    print("[6/6] Summary")
    print("-" * 80)
    print(f"Total PII columns processed: {len(pii_columns)}")
    print(f"Successful: {success_count}")
    print(f"Errors: {error_count}")
    print(f"Total rows updated: {total_rows_updated:,}")
    print()
    
    if error_count == 0:
        print("✓ SANITIZATION COMPLETED SUCCESSFULLY")
        print()
        print("Next steps:")
        print("  1. Verify the sanitized data in the database")
        print("  2. Run integrity checks")
        print("  3. Test application functionality with sanitized data")
    else:
        print("✗ SANITIZATION FAILED - NO CHANGES MADE")
        print()
        print("Please review the errors above and retry.")
    
    print("=" * 80)
    print()
    
    conn.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    else:
        config_file = "config/pii_config_ai_generated.json"
    
    try:
        # Ask for backup confirmation
        print()
        print("⚠️  WARNING: This will MODIFY your database!")
        print("⚠️  All PII data will be replaced with fake data!")
        print()
        
        backup_needed = input("Do you want to be prompted for backup confirmation? (yes/no): ")
        backup_first = backup_needed.lower() == 'yes'
        
        print()
        run_sanitization(config_file, backup_first)
        
    except KeyboardInterrupt:
        print("\n\nAborted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
