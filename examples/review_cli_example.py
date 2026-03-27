"""
Example: Interactive PII Review CLI

This example demonstrates how to use the PIIReviewCLI for reviewing AI-detected
PII columns and creating a finalized sanitization configuration.

The workflow:
1. Connect to database
2. Extract schema
3. Use AI to detect PII columns
4. Launch interactive CLI for review
5. Save finalized configuration

Author: Database Sanitization Team
Date: 2026-03-26
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.connection_manager import ConnectionManager
from src.database.schema_extractor import SchemaExtractor
from src.ai.copilot_client import CopilotClient
from src.ui.review_cli import PIIReviewCLI
from src.config.config_loader import ConfigLoader
from src.logging.logger import setup_logging


def main():
    """
    Main function demonstrating PII review CLI workflow.
    """
    # Setup logging
    setup_logging("DEBUG")
    
    print("=" * 70)
    print("PII Review CLI Example")
    print("=" * 70)
    print()
    
    # Load configuration
    print("Loading configuration...")
    config_loader = ConfigLoader("config/pii_config.example.json")
    config = config_loader.load()
    
    # Initialize database connection
    print("Connecting to database...")
    connection_manager = ConnectionManager(config.database)
    
    try:
        # Test connection
        with connection_manager.get_connection() as conn:
            print(f"✓ Connected to: {config.database.server}/{config.database.database}")
        
        # Extract schema
        print("\nExtracting database schema...")
        schema_extractor = SchemaExtractor(connection_manager)
        
        schemas = schema_extractor.get_schemas()
        print(f"✓ Found {len(schemas)} schemas")
        
        # Extract tables for first schema (or prompt user to select)
        target_schema = schemas[0]["schema_name"] if schemas else "dbo"
        tables = schema_extractor.get_tables(target_schema)
        print(f"✓ Found {len(tables)} tables in schema '{target_schema}'")
        
        # Initialize AI client
        print("\nInitializing GitHub Copilot AI client...")
        ai_client = CopilotClient(config.ai)
        print("✓ AI client ready")
        
        # Detect PII columns using AI
        print("\nAnalyzing schema for PII columns using AI...")
        pii_columns = ai_client.detect_pii_batch([target_schema])
        print(f"✓ AI detected {len(pii_columns)} potential PII columns")
        
        # Launch interactive CLI for review
        print("\nLaunching interactive review interface...")
        print("=" * 70)
        print()
        
        cli = PIIReviewCLI(schema_extractor=schema_extractor)
        final_configs = cli.review_recommendations(pii_columns)
        
        # Save finalized configuration
        if final_configs:
            output_path = Path("pii_config_finalized.json")
            cli.save_to_file(output_path)
            
            print()
            print("=" * 70)
            print(f"✓ Configuration saved to: {output_path}")
            print(f"✓ Total PII columns: {len(final_configs)}")
            print()
            print("Next steps:")
            print("  1. Review the generated configuration file")
            print("  2. Use this config for database sanitization")
            print("  3. Run sanitization with dependency resolution")
            print("=" * 70)
        else:
            print()
            print("=" * 70)
            print("⚠ No configuration saved (session cancelled or empty)")
            print("=" * 70)
    
    except KeyboardInterrupt:
        print("\n\n⚠ Example cancelled by user")
        sys.exit(1)
    
    except Exception as e:
        print(f"\n\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    finally:
        # Cleanup
        connection_manager.close_all()
        print("\n✓ Database connections closed")


if __name__ == "__main__":
    main()
