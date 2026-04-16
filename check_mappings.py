"""Quick script to check what's in the mapping table."""
import pyodbc
import os
import sys

# Get operation_id from command line or use default
operation_id = sys.argv[1] if len(sys.argv) > 1 else "1a1db0b4-5dd8-4087-a406-7d820287ecaf"

# Database connection
server = "(localdb)\\MSSQLLocalDB"
database = "Testsanitization"
conn_string = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};Trusted_Connection=yes;"

try:
    conn = pyodbc.connect(conn_string)
    cursor = conn.cursor()
    
    # Check mappings for the operation
    
    cursor.execute("""
        SELECT TOP 5
            schema_name,
            table_name,
            column_name,
            masked_value,
            original_value_encrypted,
            is_null,
            LEN(original_value_encrypted) as encrypted_length
        FROM dbo.pii_mappings
        WHERE operation_id = ?
    """, operation_id)
    
    print(f"\nFirst 5 mappings for operation {operation_id}:")
    print("-" * 120)
    print(f"{'Table.Column':<30} {'Masked Value':<40} {'Encrypted?':<15} {'Length':<10} {'IsNull'}")
    print("-" * 120)
    
    for row in cursor.fetchall():
        table_col = f"{row.table_name}.{row.column_name}"
        masked = (row.masked_value or "NULL")[:38]
        encrypted = "YES" if row.original_value_encrypted else "NO"
        length = row.encrypted_length if row.encrypted_length else 0
        is_null = "YES" if row.is_null else "NO"
        print(f"{table_col:<30} {masked:<40} {encrypted:<15} {length:<10} {is_null}")
    
    # Get summary stats
    cursor.execute("""
        SELECT 
            COUNT(*) as total_mappings,
            SUM(CASE WHEN original_value_encrypted IS NOT NULL THEN 1 ELSE 0 END) as encrypted_count,
            SUM(CASE WHEN original_value_encrypted IS NULL AND is_null = 0 THEN 1 ELSE 0 END) as plaintext_count,
            SUM(CASE WHEN is_null = 1 THEN 1 ELSE 0 END) as null_count
        FROM dbo.pii_mappings
        WHERE operation_id = ?
    """, operation_id)
    
    stats = cursor.fetchone()
    print("\n" + "=" * 120)
    print(f"Total mappings: {stats.total_mappings}")
    print(f"Encrypted mappings: {stats.encrypted_count}")
    print(f"Plaintext mappings (NO original value stored): {stats.plaintext_count}")
    print(f"NULL mappings: {stats.null_count}")
    print("=" * 120)
    
    if stats.plaintext_count > 0:
        print("\n⚠️  WARNING: Original values were NOT stored for plaintext mappings!")
        print("   Desanitization is IMPOSSIBLE without the original values.")
        print("   You need to:")
        print("   1. Re-run sanitization with SANITIZATION_ENCRYPTION_KEY set")
        print("   2. Or modify the mapping capture code to store plaintext values")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
