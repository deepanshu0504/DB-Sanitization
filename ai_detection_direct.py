"""
Direct AI PII Detection - No Framework Dependencies

This version makes API calls directly without using the CopilotClient class.
"""

import json
import logging
import os
import sys
from pathlib import Path
import requests
import pyodbc

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

logger.info("=" * 70)
logger.info("Direct AI-Powered PII Detection (No Framework)")
logger.info("=" * 70)

# Check API key
api_key = os.getenv("GITHUB_COPILOT_TOKEN") or os.getenv("GITHUB_COPILOT_API_KEY")
if not api_key:
    logger.error("\nNo API key found in environment")
    sys.exit(1)

# Database config
server = "(localdb)\\MSSQLLocalDB"
database = "smartstore"
conn_str = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER={server};"
    f"DATABASE={database};"
    f"Trusted_Connection=yes;"
    f"Connection Timeout=30;"
)

logger.info("\n1. Connecting to database...")
conn = pyodbc.connect(conn_str)
logger.info(f"   + Connected to {server}/{database}")

logger.info("\n2. Extracting schema with filtering...")
cursor = conn.cursor()

# Tables to exclude (system and metadata tables)
TABLES_TO_EXCLUDE = [
    "sanitization_metadata", "sysdiagrams", "selective_token_mappings", 
    "encrypted_originals", "detokenization_audit", "backup_tracking", "batch_processing_log",
    "__RefactorLog", "dtproperties", "MSreplication_options", "token_mappings"
]

# Get tables with exclusion filtering
cursor.execute("""
    SELECT TABLE_SCHEMA, TABLE_NAME
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE = 'BASE TABLE'
    ORDER BY TABLE_SCHEMA, TABLE_NAME
""")

tables = []
excluded_count = 0
for row in cursor.fetchall():
    # Filter out excluded tables and backup/temp tables
    table_name = row.TABLE_NAME.lower()
    full_name = f"{row.TABLE_SCHEMA}.{row.TABLE_NAME}".lower()
    
    # Skip excluded tables
    if (table_name in [t.lower() for t in TABLES_TO_EXCLUDE] or
        full_name in [t.lower() for t in TABLES_TO_EXCLUDE] or
        table_name.startswith(('backup_', 'temp_', 'staging_')) or
        table_name.endswith(('_sanitized', '_backup', '_temp'))):
        excluded_count += 1
        continue
    
    table = {
        "schema": row.TABLE_SCHEMA,
        "name": row.TABLE_NAME,
        "columns": []
    }
    
    # Get columns
    cursor.execute("""
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
    """, table["schema"], table["name"])
    
    for col_row in cursor.fetchall():
        table["columns"].append({
            "name": col_row.COLUMN_NAME,
            "data_type": col_row.DATA_TYPE,
            "max_length": col_row.CHARACTER_MAXIMUM_LENGTH,
            "nullable": col_row.IS_NULLABLE == "YES"
        })
    
    tables.append(table)

conn.close()

logger.info(f"   + Found {len(tables)} tables (excluded {excluded_count} system/metadata tables):")
for table in tables[:5]:  # Show only first 5 to avoid log spam
    logger.info(f"     - {table['schema']}.{table['name']} ({len(table['columns'])} columns)")
if len(tables) > 5:
    logger.info(f"     ... and {len(tables) - 5} more tables")

# Build efficient prompt using markdown tables instead of verbose JSON
total_columns = sum(len(table['columns']) for table in tables)

system_prompt = """You are a database security expert specializing in identifying PII (Personally Identifiable Information) in database schemas.

Analyze the provided database schema and identify all columns that likely contain PII data.

For each PII column, determine the type:
- "email": Email addresses  
- "phone": Phone numbers
- "name": Person names (first, last, full)
- "ssn": Social Security Numbers
- "address": Physical addresses
- "generic": Other sensitive data

Return ONLY a JSON array of objects with this structure:
{"schema": "schema_name", "table": "table_name", "column": "column_name", "pii_type": "type", "reason": "brief explanation"}

Example:
[{"schema": "dbo", "table": "users", "column": "email", "pii_type": "email", "reason": "Contains email addresses"}]"""

user_prompt = f"""# Database PII Detection Analysis

**Database**: {database} (Microsoft SQL Server)
**Tables**: {len(tables)} | **Columns**: {total_columns}

## Schema Details
"""

# Add schema information using compact markdown format
for table in tables:
    user_prompt += f"\n**Table: {table['schema']}.{table['name']}**\n"
    user_prompt += "| Column | Type | Length | Nullable |\n|--------|------|--------|----------|\n"
    
    for col in table['columns']:
        data_type = col['data_type']
        max_length = col['max_length'] if col['max_length'] else 'N/A'
        nullable = 'Yes' if col['nullable'] else 'No'
        user_prompt += f"| {col['name']} | {data_type} | {max_length} | {nullable} |\n"
    
    user_prompt += "\n"

user_prompt += """
## Task
Identify PII columns based on:
- Column names (primary indicator)
- Data types and constraints  
- Regulatory compliance needs (GDPR, CCPA, HIPAA)

Focus on finding: emails, phones, names, addresses, SSNs, and other sensitive identifiers.

Respond with JSON array only, no additional text.
"""

logger.info("\n3. Calling AI API...")
logger.info(f"   + Endpoint: https://models.github.ai/inference/chat/completions")
logger.info(f"   + Model: gpt-4o")
logger.info(f"   + Prompt size: {len(user_prompt)} chars (reduced from JSON format)")

# Make API call
payload = {
    "model": "gpt-4o",
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    "temperature": 0.0,
    "max_tokens": 4000
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

logger.info("   + Sending request (60s timeout)...")
response = requests.post(
    "https://models.github.ai/inference/chat/completions",
    json=payload,
    headers=headers,
    timeout=60
)

logger.info(f"   + Response status: {response.status_code}")

if response.status_code != 200:
    logger.error(f"API Error: {response.text}")
    sys.exit(1)

# Parse response
data = response.json()
content = data['choices'][0]['message']['content']

logger.info(f"   + AI response received ({len(content)} chars)")

# Extract JSON from response (might be wrapped in markdown code blocks)
import re
json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', content, re.DOTALL)
if json_match:
    content = json_match.group(1)
elif not content.strip().startswith('['):
    # Try to find JSON array
    json_match = re.search(r'(\[.*\])', content, re.DOTALL)
    if json_match:
        content = json_match.group(1)

# Parse PII columns
try:
    pii_columns = json.loads(content)
    logger.info(f"\n4. PII Detection Results:")
    logger.info(f"   + Found {len(pii_columns)} PII columns")
    
    for col in pii_columns:
        logger.info(f"\n   - {col['schema']}.{col['table']}.{col['column']}")
        logger.info(f"     Type: {col['pii_type']}")
        logger.info(f"     Reason: {col['reason']}")
        
except json.JSONDecodeError as e:
    logger.error(f"\nFailed to parse AI response as JSON:")
    logger.error(f"Content: {content[:500]}")
    sys.exit(1)

# Save to config file
output_path = Path("config/pii_config_ai_generated.json")
logger.info(f"\n5. Saving configuration to {output_path}...")

# Convert to config format
pii_column_configs = []
for col in pii_columns:
    pii_column_configs.append({
        "schema": col["schema"],
        "table": col["table"],
        "column": col["column"],
        "pii_type": col["pii_type"],
        "nullable": True  # User should verify
    })

output_config = {
    "database": {
        "server": server,
        "database": database,
        "auth_type": "windows",
        "timeout": 60,
        "batch_size": 5000,
        # Performance optimization settings (6-10x faster for large datasets)
        "log_batch_frequency": 10,
        "bulk_update_strategy": "auto",
        "enable_fast_executemany": True,
        "enable_parallel_processing": True,
        "max_parallel_tables": 4
    },
    "pii_columns": pii_column_configs,
    "dry_run": True,
    "validate_before": True,
    "validate_after": True
}

with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(output_config, f, indent=2, ensure_ascii=False)

logger.info(f"   + Configuration saved!")

logger.info("\n" + "=" * 70)
logger.info(f"SUCCESS! Detected {len(pii_columns)} PII columns")
logger.info(f"Configuration file: {output_path}")
logger.info("=" * 70)
