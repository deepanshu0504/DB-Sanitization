#!/usr/bin/env python
"""
Desanitization wrapper script - run from project root.

This wrapper ensures proper Python path resolution for the desanitization module
and loads database configuration from config/pii_config_ai_generated.json.

Usage:
    python desanitize.py <operation_id>
    python desanitize.py <operation_id> --execute
    python desanitize.py <operation_id> --execute --tables dbo.Customers
    python desanitize.py <operation_id> --config config/custom_config.json

Examples:
    # Dry-run (preview)
    python desanitize.py a1b2c3d4-5678-90ab-cdef-123456789abc
    
    # Execute full restore
    python desanitize.py a1b2c3d4-5678-90ab-cdef-123456789abc --execute
    
    # Selective table restore
    python desanitize.py a1b2c3d4-5678-90ab-cdef-123456789abc --execute --tables dbo.Customers dbo.Orders
    
    # Use custom config
    python desanitize.py a1b2c3d4-5678-90ab-cdef-123456789abc --config config/pii_config.production.json
"""

import sys
import os
import json

# Ensure project root is in Python path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = os.path.join(project_root, '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"[INFO] Loaded environment variables from .env")
except ImportError:
    print("[WARNING] python-dotenv not installed. Install with: pip install python-dotenv")
    print("[INFO] Falling back to system environment variables")

# Load database config and set environment variables
def load_config_and_set_env():
    """Load config file and set database environment variables."""
    import argparse
    
    # Parse only the config argument first
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--config', type=str, default='config/pii_config_ai_generated.json')
    args, _ = parser.parse_known_args()
    
    config_path = os.path.join(project_root, args.config)
    
    if not os.path.exists(config_path):
        print(f"[ERROR] Config file not found: {config_path}")
        print("Available options:")
        print("  1. Specify config with: --config path/to/config.json")
        print("  2. Create config/pii_config_ai_generated.json")
        print("  3. Set environment variables: SQLSERVER_HOST, SQLSERVER_DB")
        sys.exit(1)
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        # Extract database settings
        db_config = config.get('database', {})
        server = db_config.get('server', 'localhost')
        database = db_config.get('database')
        
        if not database:
            print(f"[ERROR] No database specified in config: {config_path}")
            print("Config must have: database.database field")
            sys.exit(1)
        
        # Set environment variables for desanitization script
        os.environ['SQLSERVER_HOST'] = server
        os.environ['SQLSERVER_DB'] = database
        
        print(f"[INFO] Loaded config: {config_path}")
        print(f"[INFO] Database: {database} on {server}")
        
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in config file: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Failed to load config: {e}")
        sys.exit(1)

# Load config before importing desanitization module
load_config_and_set_env()

# Check if encryption key is available (optional if mappings aren't encrypted)
if 'SANITIZATION_ENCRYPTION_KEY' not in os.environ:
    print("[WARNING] SANITIZATION_ENCRYPTION_KEY not set")
    print("[INFO] Proceeding with plaintext mappings (encryption was not used during sanitization)")
    print("[INFO] If your mappings ARE encrypted, set the key and retry")
    print()

# Import and run desanitization
from desanitization.desanitize import main

if __name__ == "__main__":
    main()
