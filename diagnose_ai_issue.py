"""
Minimal test to identify where AI detection is failing.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import os

print("=" * 70)
print("DIAGNOSTIC: AI Detection Issue")
print("=" * 70)

# Test 1: Environment
print("\n1. Environment Check:")
api_key = os.getenv("GITHUB_COPILOT_TOKEN") or os.getenv("GITHUB_COPILOT_API_KEY")
print(f"   API Key present: {bool(api_key)}")
print(f"   DB configured: {bool(os.getenv('SQLSERVER_DB'))}")

# Test 2: Config Loading
print("\n2. Config Loading:")
try:
    from src.config import ConfigLoader
    config_loader = ConfigLoader()
    config = config_loader.load("config/pii_config.example.json")
    print(f"   ✓ Config loaded")
    print(f"   Database: {config.database.server}/{config.database.database}")
except Exception as e:
    print(f"   ✗ Config failed: {e}")
    sys.exit(1)

# Test 3: Database Connection
print("\n3. Database Connection:")
try:
    from src.database import DatabaseConnectionManager
    conn_manager = DatabaseConnectionManager(config.database)
    print(f"   ✓ Connection manager created")
    
    # Try health check with timeout
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError("Health check timed out")
    
    # Note: signal.alarm doesn't work on Windows, use threading instead
    import threading
    
    health_result = [None]
    error_result = [None]
    
    def run_health_check():
        try:
            health_result[0] = conn_manager.health_check()
        except Exception as e:
            error_result[0] = e
    
    health_thread = threading.Thread(target=run_health_check)
    health_thread.daemon = True
    health_thread.start()
    health_thread.join(timeout=10)
    
    if health_thread.is_alive():
        print("   ✗ Health check timed out after 10s")
        sys.exit(1)
    elif error_result[0]:
        print(f"   ✗ Health check failed: {error_result[0]}")
        sys.exit(1)
    elif health_result[0]:
        print(f"   ✓ Health check passed")
    else:
        print(f"   ✗ Health check returned False")
        sys.exit(1)
except Exception as e:
    print(f"   ✗ Connection failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Schema Extraction (with timeout)
print("\n4. Schema Extraction:")
try:
    from src.database import SchemaExtractor
    
    schema_extractor = SchemaExtractor(conn_manager)
    print(f"   ✓ Schema extractor created")
    
    # Try extraction with timeout
    schema_result = [None]
    schema_error = [None]
    
    def run_schema_extraction():
        try:
            schema_result[0] = schema_extractor.extract_schema(config.database.database)
        except Exception as e:
            schema_error[0] = e
    
    print(f"   Extracting schema (max 30s)...")
    schema_thread = threading.Thread(target=run_schema_extraction)
    schema_thread.daemon = True
    schema_thread.start()
    schema_thread.join(timeout=30)
    
    if schema_thread.is_alive():
        print("   ✗ Schema extraction timed out after 30s")
        print("\n   DIAGNOSIS: Schema extraction is hanging!")
        print("   This could be due to:")
        print("   - Large database with many tables/columns")
        print("   - Slow database queries")
        print("   - Database permissions issues")
        print("   - Network latency to SQL Server")
        sys.exit(1)
    elif schema_error[0]:
        print(f"   ✗ Schema extraction failed: {schema_error[0]}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    elif schema_result[0]:
        table_count = len(schema_result[0].get("tables", []))
        print(f"   ✓ Schema extracted: {table_count} tables")
        
        # Show first few tables
        tables = schema_result[0].get("tables", [])[:3]
        for table in tables:
            print(f"     - {table.get('schema', '?')}.{table.get('name', '?')}")
    else:
        print(f"   ✗ Schema extraction returned None")
        sys.exit(1)
except Exception as e:
    print(f"   ✗ Schema extraction failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 70)
print("✅ ALL TESTS PASSED")
print("=" * 70)
print("\nThe issue is NOT in schema extraction.")
print("Problem must be in AI API call or response processing.")
