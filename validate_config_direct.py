"""
Direct Configuration Validator - No Framework Logger

Validates PII configuration against actual database schema.
"""

import json
import sys
from pathlib import Path
import pyodbc

print("=" * 70)
print("Configuration Validator (Direct)")
print("=" * 70)

# Check arguments
if len(sys.argv) < 2:
    print("\nUsage: python validate_config_direct.py <config_file>")
    print("Example: python validate_config_direct.py config/pii_config_ai_generated.json")
    sys.exit(1)

config_file = Path(sys.argv[1])

if not config_file.exists():
    print(f"\nError: Config file not found: {config_file}")
    sys.exit(1)

print(f"\n1. Loading configuration: {config_file}")

# Load config
with open(config_file, 'r') as f:
    config = json.load(f)

db_config = config['database']
pii_columns = config.get('pii_columns', [])

print(f"   + Database: {db_config['server']}/{db_config['database']}")
print(f"   + PII Columns to validate: {len(pii_columns)}")

# Connect to database
print("\n2. Connecting to database...")

conn_str = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER={db_config['server']};"
    f"DATABASE={db_config['database']};"
    f"Trusted_Connection=yes;"
    f"Connection Timeout=30;"
)

try:
    conn = pyodbc.connect(conn_str)
    print(f"   + Connected successfully")
except Exception as e:
    print(f"   X Connection failed: {e}")
    sys.exit(1)

cursor = conn.cursor()

# Extract actual database schema
print("\n3. Extracting database schema...")

# Get all columns from database
cursor.execute("""
    SELECT 
        c.TABLE_SCHEMA,
        c.TABLE_NAME,
        c.COLUMN_NAME,
        c.DATA_TYPE,
        c.CHARACTER_MAXIMUM_LENGTH,
        c.IS_NULLABLE,
        CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END AS IS_PRIMARY_KEY,
        CASE WHEN fk.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END AS IS_FOREIGN_KEY
    FROM INFORMATION_SCHEMA.COLUMNS c
    LEFT JOIN (
        SELECT ku.TABLE_SCHEMA, ku.TABLE_NAME, ku.COLUMN_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
            ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
            AND tc.TABLE_SCHEMA = ku.TABLE_SCHEMA
        WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
    ) pk ON c.TABLE_SCHEMA = pk.TABLE_SCHEMA 
        AND c.TABLE_NAME = pk.TABLE_NAME 
        AND c.COLUMN_NAME = pk.COLUMN_NAME
    LEFT JOIN (
        SELECT ku.TABLE_SCHEMA, ku.TABLE_NAME, ku.COLUMN_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
            ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
            AND tc.TABLE_SCHEMA = ku.TABLE_SCHEMA
        WHERE tc.CONSTRAINT_TYPE = 'FOREIGN KEY'
    ) fk ON c.TABLE_SCHEMA = fk.TABLE_SCHEMA 
        AND c.TABLE_NAME = fk.TABLE_NAME 
        AND c.COLUMN_NAME = fk.COLUMN_NAME
    ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
""")

db_columns = {}
for row in cursor.fetchall():
    # Use lowercase keys for case-insensitive comparison
    key = f"{row.TABLE_SCHEMA}.{row.TABLE_NAME}.{row.COLUMN_NAME}".lower()
    db_columns[key] = {
        "schema": row.TABLE_SCHEMA,  # Preserve original case for display
        "table": row.TABLE_NAME,
        "column": row.COLUMN_NAME,
        "data_type": row.DATA_TYPE,
        "max_length": row.CHARACTER_MAXIMUM_LENGTH,
        "nullable": row.IS_NULLABLE == "YES",
        "is_pk": bool(row.IS_PRIMARY_KEY),
        "is_fk": bool(row.IS_FOREIGN_KEY)
    }

conn.close()
print(f"   + Found {len(db_columns)} columns in database")

# Validate PII columns
print("\n4. Validating PII column configuration...")

errors = []
warnings = []
info = []

for pii_col in pii_columns:
    schema = pii_col['schema']
    table = pii_col['table']
    column = pii_col['column']
    pii_type = pii_col['pii_type']
    nullable = pii_col.get('nullable', True)
    
    # Use lowercase key for case-insensitive lookup
    key = f"{schema}.{table}.{column}".lower()
    display_key = f"{schema}.{table}.{column}"  # Preserve case for display
    
    # Check if column exists (case-insensitive)
    if key not in db_columns:
        errors.append(f"Column not found in database: {display_key}")
        continue
    
    db_col = db_columns[key]
    
    # Check data type compatibility
    data_type = db_col['data_type'].lower()
    
    type_compatibility = {
        'email': ['varchar', 'nvarchar', 'char', 'nchar', 'text', 'ntext'],
        'phone': ['varchar', 'nvarchar', 'char', 'nchar', 'text', 'ntext'],
        'name': ['varchar', 'nvarchar', 'char', 'nchar', 'text', 'ntext'],
        'ssn': ['varchar', 'nvarchar', 'char', 'nchar'],
        'address': ['varchar', 'nvarchar', 'text', 'ntext'],
        'date_of_birth': ['date', 'datetime', 'datetime2', 'smalldatetime', 'varchar', 'nvarchar'],
        'generic': ['varchar', 'nvarchar', 'char', 'nchar', 'text', 'ntext']
    }
    
    compatible_types = type_compatibility.get(pii_type, [])
    if data_type not in compatible_types:
        errors.append(
            f"{display_key}: Data type '{data_type}' incompatible with PII type '{pii_type}'. "
            f"Expected one of: {', '.join(compatible_types)}"
        )
    
    # Check nullable mismatch
    if nullable != db_col['nullable']:
        warnings.append(
            f"{display_key}: Config nullable={nullable} but database IS_NULLABLE={db_col['nullable']}"
        )
    
    # Warn if PII column is a primary key
    if db_col['is_pk']:
        warnings.append(
            f"{display_key}: Column is part of PRIMARY KEY - sanitizing may break referential integrity!"
        )
    
    # Warn if PII column is a foreign key
    if db_col['is_fk']:
        warnings.append(
            f"{display_key}: Column is part of FOREIGN KEY - sanitizing may break relationships!"
        )
    
    # Info: column validated successfully
    if key in db_columns and data_type in compatible_types:
        info.append(f"{display_key}: OK ({data_type}, nullable={db_col['nullable']})")

# Display results
print("\n" + "=" * 70)
print("VALIDATION RESULTS")
print("=" * 70)

if errors:
    print(f"\n[ERRORS] ({len(errors)}):")
    for error in errors:
        print(f"  X {error}")

if warnings:
    print(f"\n[WARNINGS] ({len(warnings)}):")
    for warning in warnings:
        print(f"  ! {warning}")

if info and not errors:
    print(f"\n[VALIDATED COLUMNS] ({len(info)}):")
    for item in info[:10]:  # Show first 10
        print(f"  + {item}")
    if len(info) > 10:
        print(f"  ... and {len(info) - 10} more")

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"Total PII Columns: {len(pii_columns)}")
print(f"Errors: {len(errors)}")
print(f"Warnings: {len(warnings)}")
print(f"Validated: {len(info)}")

if errors:
    print("\n[RESULT] VALIDATION FAILED - Fix errors before proceeding!")
    sys.exit(1)
elif warnings:
    print("\n[RESULT] VALIDATION PASSED WITH WARNINGS")
    print("Review warnings and proceed with caution.")
    sys.exit(0)
else:
    print("\n[RESULT] VALIDATION PASSED - Configuration is valid!")
    sys.exit(0)
