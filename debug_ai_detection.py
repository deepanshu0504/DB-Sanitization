"""Debug version of AI detection to see where it hangs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

print("=" * 70)
print("DEBUG: Starting AI detection...")
print("=" * 70)

print("\nDEBUG: Step 1 - Importing modules...")
try:
    from src.config import ConfigLoader
    print("  ✓ ConfigLoader imported")
    from src.database import DatabaseConnectionManager, SchemaExtractor
    print("  ✓ Database modules imported")
    from src.ai import CopilotClient
    print("  ✓ AI modules imported")
    from src.logging.logger import get_logger
    print("  ✓ Logger imported")
except Exception as e:
    print(f"  ✗ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nDEBUG: Step 2 - Getting logger...")
try:
    logger = get_logger(__name__)
    print("  ✓ Logger created")
except Exception as e:
    print(f"  ✗ Logger creation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nDEBUG: Step 3 - Checking environment...")
import os
api_key = os.getenv("GITHUB_COPILOT_TOKEN") or os.getenv("GITHUB_COPILOT_API_KEY")
print(f"  API key exists: {bool(api_key)}")

print("\nDEBUG: Step 4 - Loading config...")
try:
    from pathlib import Path
    config_path = Path("config/pii_config.example.json")
    config_loader = ConfigLoader()
    print(f"  ✓ ConfigLoader created")
    
    config = config_loader.load(str(config_path))
    print(f"  ✓ Config loaded: {config_path}")
    print(f"  Database: {config.database.server}/{config.database.database}")
except Exception as e:
    print(f"  ✗ Config load failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nDEBUG: Step 5 - Testing database connection...")
try:
    conn_manager = DatabaseConnectionManager(config.database)
    print("  ✓ DatabaseConnectionManager created")
    
    print("  Testing health check (this might take a moment)...")
    health = conn_manager.health_check()
    print(f"  ✓ Health check result: {health}")
except Exception as e:
    print(f"  ✗ Database connection failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nDEBUG: All basic steps completed successfully!")
print("=" * 70)
