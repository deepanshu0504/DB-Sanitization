"""
Quick test for verifying production configuration setup.
"""
import os
from dotenv import load_dotenv
from src.config import ConfigLoader

# Load environment variables
load_dotenv()

print("=" * 70)
print("Configuration Verification")
print("=" * 70)

# Check environment variables
print("\n1. Environment Variables:")
print(f"   ✓ GITHUB_COPILOT_TOKEN: {'***' + os.getenv('GITHUB_COPILOT_TOKEN', '')[-4:] if os.getenv('GITHUB_COPILOT_TOKEN') else 'NOT SET'}")
print(f"   ✓ SQLSERVER_HOST: {os.getenv('SQLSERVER_HOST', 'NOT SET')}")
print(f"   ✓ SQLSERVER_DB: {os.getenv('SQLSERVER_DB', 'NOT SET')}")
print(f"   ✓ SQLSERVER_AUTH: {os.getenv('SQLSERVER_AUTH', 'NOT SET')}")

# Load production config
print("\n2. Loading Production Config:")
try:
    config_loader = ConfigLoader()
    config = config_loader.load_from_files(["config/pii_config.production.json"])
    print(f"   ✓ Database: {config.database.server} / {config.database.database}")
    print(f"   ✓ Auth Type: {config.database.auth_type}")
    print(f"   ✓ Batch Size: {config.database.batch_size}")
    print(f"   ✓ AI Enabled: {config.ai.enabled}")
    print(f"   ✓ AI URL: {config.ai.api_url}")
    print(f"   ✓ AI Model: {config.ai.model if hasattr(config.ai, 'model') else 'default'}")
    print(f"   ✓ Dry Run: {config.dry_run}")
except Exception as e:
    print(f"   ✗ Error: {e}")

print("\n" + "=" * 70)
print("Ready for Real Data Testing!")
print("=" * 70)
print("\nNext Steps:")
print("1. Test database connection: python examples/connection_example.py")
print("2. Run AI detection: python examples/ai_detection_example.py")
print("3. Validate config: python examples/validate_config_example.py")
print("=" * 70)
