"""Test schema extraction directly."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.config import ConfigLoader
from src.database import DatabaseConnectionManager, SchemaExtractor
import threading

print("="*70)
print("Testing schema extraction on Testsanitization (2 tables)")
print("="*70)

# Load config
config_loader = ConfigLoader()
config = config_loader.load("config/pii_config.example.json")

# Connect
conn_manager = DatabaseConnectionManager(config.database)
print(f"\n✓ Connected to: {config.database.server}/{config.database.database}")

# Create extractor
schema_extractor = SchemaExtractor(conn_manager)
print(f"✓ Schema extractor created")

# Extract schema with timeout
def extract_with_method():
    """Extract schema using the SchemaExtractor.extract_schema method."""
    try:
        result = schema_extractor.extract_schema(config.database.database)
        print(f"\n✓ SCHEMA EXTRACTION COMPLETED")
        print(f"   Tables: {len(result.get('tables', []))}")
        
        # Show tables
        for table in result.get('tables', []):
            print(f"   - {table.get('schema')}.{table.get('name')} ({len(table.get('columns', []))} columns)")
        
        return result
    except Exception as e:
        print(f"\n✗ Schema extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return None

print(f"\nStarting schema extraction (timeout: 60s)...")

result_container = [None]
error_container = [None]

def run_extraction():
    try:
        result_container[0] = extract_with_method()
    except Exception as e:
        error_container[0] = e

thread = threading.Thread(target=run_extraction)
thread.daemon = True
thread.start()
thread.join(timeout=60)

if thread.is_alive():
    print("\n❌ SCHEMA EXTRACTION TIMED OUT AFTER 60 SECONDS")
    print("\nThe SchemaExtractor.extract_schema() method is hanging!")
    print("This indicates a problem with one of the SQL queries.")
    print("\nPossible causes:")
    print("  - Query is waiting for locks on system tables")
    print("  - Query has poor performance on this database")
    print("  - Database metadata is corrupted")
    print("\nRecommendation: Check SchemaExtractor queries for performance issues")
    sys.exit(1)
elif error_container[0]:
    print(f"\n❌ ERROR: {error_container[0]}")
    sys.exit(1)
elif result_container[0]:
    print("\n" + "="*70)
    print("✅ SUCCESS: Schema extraction completed")
    print("="*70)
else:
    print("\n❌ Schema extraction returned None")
    sys.exit(1)
