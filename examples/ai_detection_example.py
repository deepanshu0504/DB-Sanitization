"""
Example script demonstrating AI-powered PII detection using GitHub Copilot API.

This script shows the complete workflow:
1. Extract database schema metadata
2. Send to AI for PII detection
3. Review and save results to configuration file

Prerequisites:
- Database connection configured in config/pii_config.json
- GITHUB_COPILOT_API_KEY environment variable set
- Network access to GitHub API

Author: Database Sanitization Team
Date: 2026-03-26
"""

import json
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import ConfigLoader, AIConfig
from src.database import DatabaseConnectionManager, SchemaExtractor
from src.ai import CopilotClient, PIIColumn
from src.logging.logger import get_logger


def main():
    """
    Demonstrate AI-powered PII detection workflow.
    """
    # Setup logging
    logger = get_logger(__name__)
    logger.info("=" * 70)
    logger.info("AI-Powered PII Detection Example")
    logger.info("=" * 70)
    
    # Check for API key (check both possible env var names)
    api_key = os.getenv("GITHUB_COPILOT_TOKEN") or os.getenv("GITHUB_COPILOT_API_KEY")
    if not api_key:
        logger.warning(
            "GITHUB_COPILOT_API_KEY environment variable not set. "
            "AI detection will be skipped."
        )
        logger.info("\nTo enable AI detection:")
        logger.info("1. Get a GitHub Copilot API key from: https://github.com/settings/tokens")
        logger.info("2. Set environment variable: export GITHUB_COPILOT_API_KEY=your_key_here")
        logger.info("3. Re-run this script")
        return
    
    # Load configuration
    logger.info("\n1. Loading configuration...")
    config_path = Path("config/pii_config.example.json")
    
    try:
        config_loader = ConfigLoader()
        config = config_loader.load(str(config_path))
        logger.info(f"   ✓ Configuration loaded from: {config_path}")
        logger.info(f"   ✓ Database: {config.database.server}/{config.database.database}")
    except Exception as e:
        logger.error(f"   ✗ Failed to load configuration: {e}")
        return
    
    # Initialize database connection
    logger.info("\n2. Connecting to database...")
    
    try:
        conn_manager = DatabaseConnectionManager(config.database)
        if not conn_manager.health_check():
            logger.error("   ✗ Database health check failed")
            return
        logger.info(f"   ✓ Connected to: {config.database.server}")
    except Exception as e:
        logger.error(f"   ✗ Connection failed: {e}")
        return
    
    # Extract schema metadata
    logger.info("\n3. Extracting schema metadata...")
    
    try:
        schema_extractor = SchemaExtractor(conn_manager)
        schema_metadata = schema_extractor.extract_schema(config.database.database)
        
        table_count = len(schema_metadata.get("tables", []))
        logger.info(f"   ✓ Extracted schema for {table_count} tables")
        
        # Show sample tables
        tables = schema_metadata.get("tables", [])[:5]
        logger.info("   Sample tables:")
        for table in tables:
            schema_name = table.get("schema", "unknown")
            table_name = table.get("name", "unknown")
            column_count = len(table.get("columns", []))
            logger.info(f"     - {schema_name}.{table_name} ({column_count} columns)")
        
        if table_count > 5:
            logger.info(f"     ... and {table_count - 5} more")
    
    except Exception as e:
        logger.error(f"   ✗ Schema extraction failed: {e}")
        return
    
    # Initialize AI client
    logger.info("\n4. Initializing AI client...")
    
    try:
        # Use AI config from loaded configuration, or fall back to defaults
        ai_config = config.ai if config.ai else AIConfig()
        
        client = CopilotClient(
            api_url=ai_config.api_url,
            api_key_env_var=ai_config.api_key_env_var,
            timeout_seconds=ai_config.timeout_seconds,
            max_retries=ai_config.max_retries,
            backoff_factor=ai_config.retry_backoff_factor,
            cache_enabled=ai_config.cache_enabled,
            cache_ttl_hours=ai_config.cache_ttl_hours,
            max_tables_per_request=ai_config.max_tables_per_request,
            max_schema_size_chars=ai_config.max_schema_size_chars
        )
        
        logger.info(f"   ✓ AI client initialized")
        logger.info(f"   ✓ API URL: {ai_config.api_url}")
        logger.info(f"   ✓ Cache enabled: {ai_config.cache_enabled}")
    
    except Exception as e:
        logger.error(f"   ✗ AI client initialization failed: {e}")
        return
    
    # Detect PII columns using AI
    logger.info("\n5. Detecting PII columns with AI...")
    logger.info("   (This may take 30-60 seconds depending on schema size)")
    
    try:
        pii_columns = client.detect_pii(schema_metadata)
        
        logger.info(f"   ✓ AI detection complete: found {len(pii_columns)} PII columns")
        
        if pii_columns:
            logger.info("\n   Detected PII columns:")
            
            # Group by table for better readability
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
        logger.exception("Full error traceback:")
        return
    
    # Save results to configuration file
    output_path = Path("config/pii_config_ai_generated.json")
    logger.info(f"\n6. Saving results to {output_path}...")
    
    try:
        # Convert PIIColumn instances to configuration format
        pii_column_configs = []
        for col in pii_columns:
            pii_column_configs.append({
                "schema": col.schema,
                "table": col.table,
                "column": col.column,
                "pii_type": col.pii_type,
                "nullable": True,  # Default, user should review
            })
        
        # Build output configuration
        output_config = {
            "database": {
                "server": config.database.server,
                "database": config.database.database,
                "auth_type": config.database.auth_type,
                "timeout": config.database.timeout,
                "batch_size": config.database.batch_size,
                # Performance optimization settings (6-10x faster for large datasets)
                "log_batch_frequency": 10,
                "bulk_update_strategy": "auto",
                "enable_fast_executemany": True,
                "enable_parallel_processing": True,
                "max_parallel_tables": 4,
            },
            "pii_columns": pii_column_configs,
            "dry_run": True,  # Default to dry-run for safety
            "validate_before": True,
            "validate_after": True,
        }
        
        # Save to file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_config, f, indent=2, ensure_ascii=False)
        
        logger.info(f"   ✓ Configuration saved to: {output_path}")
    
    except Exception as e:
        logger.error(f"   ✗ Failed to save configuration: {e}")
        return
    
    # Summary
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


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
