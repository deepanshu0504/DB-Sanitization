"""Test direct database connection."""
import pyodbc
import sys

print("Testing pyodbc connection to Testsanitization...")
print("=" * 70)

# Test 1: List ODBC drivers
print("\n1. Available ODBC drivers:")
drivers = [driver for driver in pyodbc.drivers()]
for driver in drivers:
    if 'SQL Server' in driver:
        print(f"   - {driver}")

# Test 2: Try master database first
print("\n2. Testing connection to master database...")
try:
    conn_str_master = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=(localdb)\\MSSQLLocalDB;"
        "DATABASE=master;"
        "Trusted_Connection=yes;"
        "Connection Timeout=10;"
    )
    
    print(f"   Connecting...")
    conn = pyodbc.connect(conn_str_master)
    print(f"   ✓ Connected to master")
    
    cursor = conn.cursor()
    cursor.execute("SELECT DB_NAME()")
    print(f"   ✓ Current DB: {cursor.fetchone()[0]}")
    
    # Check if Testsanitization exists
    cursor.execute("SELECT name FROM sys.databases WHERE name = 'Testsanitization'")
    row = cursor.fetchone()
    if row:
        print(f"   ✓ Testsanitization database EXISTS")
    else:
        print(f"   ✗ Testsanitization database NOT FOUND")
        sys.exit(1)
    
    conn.close()
    
except Exception as e:
    print(f"   ✗ Failed: {e}")
    sys.exit(1)

# Test 3: Try Testsanitization database
print("\n3. Testing connection to Testsanitization database...")
try:
    conn_str_test = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=(localdb)\\MSSQLLocalDB;"
        "DATABASE=Testsanitization;"
        "Trusted_Connection=yes;"
        "Connection Timeout=30;"
        "Login Timeout=30;"
    )
    
    print(f"   Connecting (30s timeout)...")
    conn = pyodbc.connect(conn_str_test)
    print(f"   ✓ Connected successfully!")
    
    cursor = conn.cursor()
    cursor.execute("SELECT DB_NAME(), COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'")
    row = cursor.fetchone()
    
    print(f"   ✓ Database: {row[0]}")
    print(f"   ✓ Tables: {row[1]}")
    
    conn.close()
    print("\n✅ All tests PASSED")
    
except pyodbc.Error as e:
    print(f"   ✗ Connection failed:")
    print(f"      {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

