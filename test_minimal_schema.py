"""Minimal schema test with output flushing."""
import sys

def log(msg):
    print(msg, flush=True)

log("Step 1: Imports...")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

log("Step 2: Load dotenv...")
from dotenv import load_dotenv
load_dotenv()

log("Step 3: Import config...")
from src.config import ConfigLoader

log("Step 4: Load config...")
config_loader = ConfigLoader()
config = config_loader.load("config/pii_config.example.json")
log(f"  Database: {config.database.database}")

log("Step 5: Import database modules...")
from src.database import DatabaseConnectionManager, SchemaExtractor

log("Step 6: Create connection manager...")
conn_manager = DatabaseConnectionManager(config.database)

log(f"Step 7: Create schema extractor...")
schema_extractor = SchemaExtractor(conn_manager)

log(f"Step 8: Call extract_schema()...")
sys.stdout.flush()
result = schema_extractor.extract_schema(config.database.database)

log(f"Step 9: SUCCESS!")
log(f"  Tables: {len(result.get('tables', []))}")
