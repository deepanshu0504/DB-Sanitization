"""
AI-Powered PII Detection - Standalone Version (No Framework Logger)

This version bypasses the hanging logging system and uses basic Python logging.
"""

import json
import logging
import os
import sys
from pathlib import Path

# Configure basic Python logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

logger.info("=" * 70)
logger.info("AI-Powered PII Detection Example (Standalone)")
logger.info("=" * 70)

# Check for API key
api_key = os.getenv("GITHUB_COPILOT_TOKEN") or os.getenv("GITHUB_COPILOT_API_KEY")
if not api_key:
    logger.error("\n❌ GITHUB_COPILOT_TOKEN environment variable not set")
    logger.info("\nTo enable AI detection:")
    logger.info("1. Check your .env file")
    logger.info("2. Ensure GITHUB_COPILOT_TOKEN=your_token_here")
    logger.info("3. Re-run this script")
    sys.exit(1)

# Import after environment setup
from src.config import ConfigLoader, AIConfig
from src.ai import CopilotClient
import pyodbc

logger.info("\n1. Loading configuration...")
config_path = Path("config/pii_config.example.json")

try:
    config_loader = ConfigLoader()
    config = config_loader.load(str(config_path))
    logger.info(f"   ✓ Configuration loaded from: {config_path}")
    logger.info(f"   ✓ Database: {config.database.server}/{config.database.database}")
except Exception as e:
    logger.error(f"   ✗ Failed to load configuration: {e}")
    sys.exit(1)

# Connect to database directly (bypass framework connection manager)
logger.info("\n2. Connecting to database...")

try:
    conn_str = config.database.get_connection_string()
    conn = pyodbc.connect(conn_str)
    logger.info(f"   ✓ Connected to: {config.database.server}")
except Exception as e:
    logger.error(f"   ✗ Connection failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Extract schema directly with SQL queries
logger.info("\n3. Extracting schema metadata...")

try:
    cursor = conn.cursor()
    
    # Get tables
    cursor.execute("""
        SELECT 
            TABLE_SCHEMA,
            TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_SCHEMA, TABLE_NAME
    """)
    
    tables = []
    for row in cursor.fetchall():
        tables.append({
            "schema": row.TABLE_SCHEMA,
            "name": row.TABLE_NAME,
            "columns": []
        })
    
    logger.info(f"   ✓ Found {len(tables)} tables")
    
    # Get columns for each table
    for table in tables:
        cursor.execute("""
            SELECT 
                COLUMN_NAME,
                DATA_TYPE,
                CHARACTER_MAXIMUM_LENGTH,
                IS_NULLABLE,
                COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
        """, table["schema"], table["name"])
        
        for col_row in cursor.fetchall():
            table["columns"].append({
                "name": col_row.COLUMN_NAME,
                "data_type": col_row.DATA_TYPE,
                "max_length": col_row.CHARACTER_MAXIMUM_LENGTH,
                "nullable": col_row.IS_NULLABLE == "YES",
                "default": col_row.COLUMN_DEFAULT
            })
    
    # Show sample
    logger.info("   Sample tables:")
    for table in tables[:5]:
        logger.info(f"     - {table['schema']}.{table['name']} ({len(table['columns'])} columns)")
    if len(tables) > 5:
        logger.info(f"     ... and {len(tables) - 5} more")
    
    # Build schema metadata structure
    schema_metadata = {
        "database_name": config.database.database,
        "tables": tables
    }
    
    conn.close()
    
except Exception as e:
    logger.error(f"   ✗ Schema extraction failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Initialize AI client
logger.info("\n4. Initializing AI client...")

try:
    ai_config = config.ai if config.ai else AIConfig()
    
    # Create a simple logger wrapper that the AI client can use
    class SimpleLoggerWrapper:
        def __init__(self, logger):
            self._logger = logger
        def debug(self, msg, **kwargs):
            self._logger.debug(msg)
        def info(self, msg, **kwargs):
            self._logger.info(msg)
        def warning(self, msg, **kwargs):
            self._logger.warning(msg)
        def error(self, msg, **kwargs):
            self._logger.error(msg)
        def with_context(self, **kwargs):
            return self  # Return self to avoid creating new logger
    
    simple_logger = SimpleLoggerWrapper(logger)
    
    client = CopilotClient(
        api_url=ai_config.api_url,
        api_key_env_var=ai_config.api_key_env_var,
        timeout_seconds=ai_config.timeout_seconds,
        max_retries=ai_config.max_retries,
        backoff_factor=ai_config.retry_backoff_factor,
        cache_enabled=ai_config.cache_enabled,
        cache_ttl_hours=ai_config.cache_ttl_hours,
        max_tables_per_request=ai_config.max_tables_per_request,
        max_schema_size_chars=ai_config.max_schema_size_chars,
        logger=simple_logger  # Pass our simple logger
    )
    
    logger.info(f"   + AI client initialized")
    logger.info(f"   + API URL: {ai_config.api_url}")
    logger.info(f"   + Model: gpt-4o")
    
except Exception as e:
    logger.error(f"   ✗ AI client initialization failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Detect PII columns using AI
logger.info("\n5. Detecting PII columns with AI...")
logger.info("   (This may take 30-60 seconds depending on schema size)")

try:
    pii_columns = client.detect_pii(schema_metadata)
    
    logger.info(f"   ✓ AI detection complete: found {len(pii_columns)} PII columns")
    
    if pii_columns:
        logger.info("\n   Detected PII columns:")
        
        # Group by table
        by_table = {}
        for col in pii_columns:
            table_key = f"{col.schema}.{col.table}"
            if table_key not in by_table:
                by_table[table_key] = []
            by_table[table_key].append(col)
        
        for table_key, cols in sorted(by_table.items()):
            logger.info(f"\n     {table_key}:")
            for col in cols:
                confidence_str = f" (confidence: {col.confidence:.2f})" if col.confidence else ""
                logger.info(f"       - {col.column}: {col.pii_type}{confidence_str}")
                if col.reason:
                    logger.info(f"         Reason: {col.reason}")
    else:
        logger.info("   No PII columns detected")

except Exception as e:
    logger.error(f"   ✗ PII detection failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Save results
output_path = Path("config/pii_config_ai_generated.json")
logger.info(f"\n6. Saving results to {output_path}...")

try:
    # Convert to configuration format
    pii_column_configs = []
    for col in pii_columns:
        pii_column_configs.append({
            "schema": col.schema,
            "table": col.table,
            "column": col.column,
            "pii_type": col.pii_type,
            "nullable": True,  # User should verify
        })
    
    # Build output configuration
    output_config = {
        "database": {
            "server": config.database.server,
            "database": config.database.database,
            "auth_type": config.database.auth_type,
            "timeout": config.database.timeout,
            "batch_size": config.database.batch_size,
        },
        "pii_columns": pii_column_configs,
        "dry_run": True,
        "validate_before": True,
        "validate_after": True,
    }
    
    # Save to file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_config, f, indent=2, ensure_ascii=False)
    
    logger.info(f"   ✓ Configuration saved to: {output_path}")

except Exception as e:
    logger.error(f"   ✗ Failed to save configuration: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Summary
table_count = len(tables)
logger.info("\n" + "=" * 70)
logger.info("Summary")
logger.info("=" * 70)
logger.info(f"Tables analyzed: {table_count}")
logger.info(f"PII columns detected: {len(pii_columns)}")
logger.info(f"Configuration file: {output_path}")
logger.info("\nNext steps:")
logger.info("1. Review the generated configuration file")
logger.info("2. Add or remove PII columns as needed")
logger.info("3. Set correct nullable flags based on schema")
logger.info("4. Update dry_run to False when ready to sanitize")
logger.info("\n" + "=" * 70)

logger.info("\n✅ AI-Powered PII Detection Completed Successfully!")
