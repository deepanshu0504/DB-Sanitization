"""
AI detection example without complex logging (to bypass logger hang issue).
"""

import json
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv()

from src.config import ConfigLoader, AIConfig
from src.database import DatabaseConnectionManager, SchemaExtractor
from src.ai import CopilotClient, PIIColumn


def main():
    """Run AI-powered PII detection workflow."""
    print("=" * 70)
    print("AI-Powered PII Detection Example")
    print("=" * 70)
    
    # Check for API key
    api_key = os.getenv("GITHUB_COPILOT_TOKEN") or os.getenv("GITHUB_COPILOT_API_KEY")
    if not api_key:
        print("\n❌ GITHUB_COPILOT_TOKEN environment variable not set")
        print("\nTo enable AI detection:")
        print("1. Get a GitHub token from: https://github.com/settings/tokens")
        print("2. Add to .env file: GITHUB_COPILOT_TOKEN=your_token_here")
        print("3. Re-run this script")
        return
    
    # Load configuration
    print("\n1. Loading configuration...")
    config_path = Path("config/pii_config.example.json")
    
    try:
        config_loader = ConfigLoader()
        config = config_loader.load(str(config_path))
        print(f"   ✓ Configuration loaded from: {config_path}")
        print(f"   ✓ Database: {config.database.server}/{config.database.database}")
    except Exception as e:
        print(f"   ✗ Failed to load configuration: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Initialize database connection
    print("\n2. Connecting to database...")
    
    try:
        conn_manager = DatabaseConnectionManager(config.database)
        if not conn_manager.health_check():
            print("   ✗ Database health check failed")
            return
        print(f"   ✓ Connected to: {config.database.server}")
    except Exception as e:
        print(f"   ✗ Connection failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Extract schema metadata
    print("\n3. Extracting schema metadata...")
    
    try:
        schema_extractor = SchemaExtractor(conn_manager)
        schema_metadata = schema_extractor.extract_schema(config.database.database)
        
        table_count = len(schema_metadata.get("tables", []))
        print(f"   ✓ Extracted schema for {table_count} tables")
        
        # Show sample tables
        tables = schema_metadata.get("tables", [])[:5]
        print("   Sample tables:")
        for table in tables:
            schema_name = table.get("schema", "unknown")
            table_name = table.get("name", "unknown")
            column_count = len(table.get("columns", []))
            print(f"     - {schema_name}.{table_name} ({column_count} columns)")
        
        if table_count > 5:
            print(f"     ... and {table_count - 5} more")
    
    except Exception as e:
        print(f"   ✗ Schema extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Initialize AI client
    print("\n4. Initializing AI client...")
    
    try:
        # Use AI config from loaded configuration
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
        
        print(f"   ✓ AI client initialized")
        print(f"   ✓ API URL: {ai_config.api_url}")
        print(f"   ✓ Cache enabled: {ai_config.cache_enabled}")
    
    except Exception as e:
        print(f"   ✗ AI client initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Detect PII columns using AI
    print("\n5. Detecting PII columns with AI...")
    print("   (This may take 30-60 seconds depending on schema size)")
    
    try:
        pii_columns = client.detect_pii(schema_metadata)
        
        print(f"   ✓ AI detection complete: found {len(pii_columns)} PII columns")
        
        if pii_columns:
            print("\n   Detected PII columns:")
            
            # Group by table
            by_table = {}
            for col in pii_columns:
                table_key = f"{col.schema}.{col.table}"
                if table_key not in by_table:
                    by_table[table_key] = []
                by_table[table_key].append(col)
            
            for table_key, cols in sorted(by_table.items()):
                print(f"\n     {table_key}:")
                for col in cols:
                    confidence_str = f" (confidence: {col.confidence:.2f})" if col.confidence else ""
                    print(f"       - {col.column}: {col.pii_type}{confidence_str}")
                    if col.reason:
                        print(f"         Reason: {col.reason}")
        else:
            print("   No PII columns detected")
    
    except Exception as e:
        print(f"   ✗ PII detection failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Save results
    output_path = Path("config/pii_config_ai_generated.json")
    print(f"\n6. Saving results to {output_path}...")
    
    try:
        # Convert to configuration format
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
            "dry_run": True,
            "validate_before": True,
            "validate_after": True,
        }
        
        # Save to file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_config, f, indent=2, ensure_ascii=False)
        
        print(f"   ✓ Configuration saved to: {output_path}")
    
    except Exception as e:
        print(f"   ✗ Failed to save configuration: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Tables analyzed: {table_count}")
    print(f"PII columns detected: {len(pii_columns)}")
    print(f"Configuration file: {output_path}")
    print("\nNext steps:")
    print("1. Review the generated configuration file")
    print("2. Add or remove PII columns as needed")
    print("3. Set correct nullable flags based on schema")
    print("4. Update dry_run to False when ready to sanitize")
    print("\n" + "=" * 70)


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
