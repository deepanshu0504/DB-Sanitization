# Database Sanitization Framework

A comprehensive, domain-agnostic Python framework for sanitizing Microsoft SQL Server databases by identifying, masking, and managing Personally Identifiable Information (PII).

## 📚 Documentation

- **[Quick Start Guide](docs/QUICK_START.md)** - Get started in 15 minutes (installation + first sanitization)
- **[Workflow Guide](docs/WORKFLOW_GUIDE.md)** - Complete documentation: prerequisites, usage, troubleshooting, best practices
- **[Cheat Sheet](docs/CHEAT_SHEET.md)** - Quick reference: commands, SQL queries, configurations
- **[Troubleshooting FAQ](docs/TROUBLESHOOTING.md)** - Common issues and solutions with detailed fixes
- **[User Stories](docs/USER_STORIES.md)** - Development phases and implementation status
- **[Requirements](docs/Requirement/requirement.md)** - Functional and non-functional requirements

## Features

- 🔒 **AI-Powered PII Detection** - Automatically identify PII columns using GitHub Copilot API
- 🎭 **Intelligent Data Masking** - Deterministic masking strategies for emails, phones, names, SSNs, and more
- 🎯 **Smart Generation** - Format-adaptive masking ensures all fake values fit within column constraints without truncation
- 🔄 **Reversible Sanitization** - Mapping tables enable data restoration when needed
- ⚡ **High Performance** - Batch processing with connection pooling handles millions of rows efficiently
- 🔗 **Referential Integrity** - Preserves foreign key relationships and handles circular dependencies
- 🌐 **Domain Agnostic** - Works across healthcare, retail, finance, e-commerce, and any other domain
- 🛡️ **Security First** - No PII logging, encrypted mappings, parameterized queries

## 🔄 Reversible Sanitization (NEW)

The framework now supports **reversible sanitization** through persistent mapping tables, enabling you to restore original data when authorized.

### Quick Setup

```bash
# 1. Create mapping table
sqlcmd -S YourServer -d YourDatabase -i scripts/create_mapping_table.sql

# 2. Enable mapping capture in your config
# Add to config/pii_config.production.json:
{
  "use_mapping_capture": true,
  "mapping_table_name": "token_mappings"
}

# 3. Run sanitization (mappings captured automatically)
python sanitize_smart.py config/pii_config.production.json
```

### Python API

```python
from mapping.mapping_table_manager import MappingTableManager, MappingRecord

# Initialize
manager = MappingTableManager(connection_string)
manager.create_table()

# Query mappings for desanitization
results = manager.get_mappings(
    table_name="Customers",
    column_name="Email",
    record_ids=["123", "456"]
)

# Composite primary key support
composite_pk = manager.serialize_composite_pk({
    "CustomerID": 123,
    "OrderID": 456
})
```

**Features:**
- ✅ Persistent mapping table with optimized indexes
- ✅ Composite primary key support via JSON serialization
- ✅ Bulk insert performance (<1 second for 10K mappings)
- ✅ Schema validation with actionable error messages
- ✅ Transaction-safe batch operations
- ✅ Encryption at rest (Story 1.3 - AES-256-GCM)
- ✅ Desanitization engine (Stories 2.1-2.4 - All levels complete)
- ✅ Incremental desanitization (Story 5.2 - Time-based filtering, rate limiting, ETA)
- 🚧 Parallel desanitization (Story 5.1)
- 🚧 Role-based access control (Story 7.1)

See **[docs/USER_STORIES_DESANITIZATION.md](docs/USER_STORIES_DESANITIZATION.md)** for complete implementation roadmap.

## Recent Updates (April 13, 2026)

**🚀 Story 5.2: Incremental Desanitization - Now Available**

- **Time-Based Filtering**: Restore only mappings from specific date ranges using `--date-range`
- **Rate Limiting**: Add delays between column restorations for production-safe operations with `--rate-limit`
- **Enhanced Progress Tracking**: ETA with estimated completion time displayed every 10 tables and hourly
- **Multi-Shift Workflows**: Resume capability supports incremental restoration across multiple work shifts
- **Optimized Performance**: New composite index (`IX_token_mappings_created_at`) provides 10-100x speedup for date-filtered queries

```bash
# Example: Restore last week's data with throttling
python desanitize_direct.py \
  --database \
  --date-range "2026-04-06:2026-04-13" \
  --rate-limit 1000 \
  --execute
```

Learn more in the **[Incremental Desanitization Guide](docs/DESANITIZATION_GUIDE.md#incremental-desanitization-story-52)**.

---

## Current Status: Phase 1 - Foundation

✅ **Story 1.1: Database Connection Manager** (COMPLETED)
- Robust SQL Server connection management
- Connection pooling with automatic retry
- Support for Windows and SQL Server authentication
- Health checks and batch operations

✅ **Story 1.2: Configuration Management System** (COMPLETED)
- Pydantic-based typed configuration models
- JSON file loading with validation
- Environment variable overrides
- Configuration caching for performance

✅ **Story 1.3: Structured Logging Framework** (COMPLETED)
- JSON-formatted logs with correlation IDs
- Automatic PII redaction in logs
- Multi-handler support (file and console)
- Configurable log levels and rotation

✅ **Story 1.4: Exception Hierarchy & Error Handling** (COMPLETED)
- Custom exception classes with error codes
- Context enrichment and error chaining
- Factory methods for common scenarios
- Actionable error messages

✅ **Story 1.5: Project Structure & Packaging** (COMPLETED)
- Standard Python package structure
- Comprehensive requirements.txt
- Environment templates and documentation

✅ **Story 2.1: Schema Metadata Extraction** (COMPLETED)
- Extract complete database schema metadata
- Support for tables, columns, PKs, FKs, constraints, indexes
- Handle composite keys and self-referencing relationships
- Comprehensive edge case handling

✅ **Story 3.1: GitHub Copilot API Client** (COMPLETED)
- AI-powered PII detection using GitHub Copilot API
- Batch processing with retry logic and caching
- Confidence scoring and deduplication
- Comprehensive error handling

✅ **Story 3.2: User Review Interface CLI** (COMPLETED)
- Interactive terminal UI for reviewing AI recommendations
- Add, remove, and modify PII columns
- Schema validation with FK/PK warnings
- Undo functionality and configuration persistence

✅ **Story 3.3: Configuration Schema Validator** (COMPLETED)
- Validate PII configuration files against database schema
- Check column existence, data types, nullable constraints
- Warn about foreign keys, primary keys, and special columns
- Generate detailed validation reports with actionable suggestions
- Integration with configuration loading and review workflows

🚧 **In Progress**: Foreign key dependency graph and batch data extraction

## Quick Start

> **📖 For detailed instructions, see [QUICK_START.md](QUICK_START.md) or [WORKFLOW_GUIDE.md](WORKFLOW_GUIDE.md)**

### Prerequisites

- Python 3.10 or higher
- Microsoft SQL Server 2016+ (or Azure SQL Database)  
- ODBC Driver 17 for SQL Server
- GitHub Copilot API access

### Installation

```bash
# Clone and navigate
cd DB-Sanitization

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Configure environment (.env file)
SQLSERVER_HOST=localhost
SQLSERVER_DB=YourDatabase
GITHUB_COPILOT_TOKEN=ghp_your_token_here
```

### Complete Workflow (3 Steps)

```bash
# Step 1: AI-powered PII detection
python ai_detection_direct.py

# Step 2: Validate configuration
python validate_config_direct.py config/pii_config_ai_generated.json

# Step 3a: Test with dry-run (default - safe, no changes)
python sanitize_smart.py config/pii_config_ai_generated.json

# Step 3b: Edit config: Set "dry_run": false, then execute actual sanitization
python sanitize_smart.py config/pii_config_ai_generated.json

# Step 4: Verify results in database
# ⚠️ Note: Sanitization is irreversible without backup
```

**⚠️ CRITICAL:** Sanitization permanently replaces original data. Always backup before running with `dry_run: false`.

### Basic Usage (Legacy Example - For Framework Development)

```python
from src.database import DatabaseConnectionManager, ConnectionConfig, AuthType

# Configure connection
config = ConnectionConfig(
    server="localhost",
    database="TestDB",
    auth_type=AuthType.WINDOWS
)

# Create connection manager
with DatabaseConnectionManager(config) as manager:
    # Check database health
    if manager.health_check():
        print("✓ Database connection healthy")
    
    # Execute queries
    results = manager.execute_query(
        "SELECT * FROM Users WHERE age > ?",
        params=(18,)
    )
    
    # Batch operations
    data = [(1, "Alice"), (2, "Bob"), (3, "Charlie")]
    affected = manager.execute_batch(
        "INSERT INTO Users (id, name) VALUES (?, ?)",
        data
    )
```

### Configuration Management

The framework uses a flexible configuration system with JSON files and environment variable overrides.

#### Creating a Configuration File

```bash
# Copy the example configuration
cp config/pii_config.example.json config/pii_config.json

# Edit with your database and PII column settings
nano config/pii_config.json
```

#### Configuration Structure

```json
{
  "database": {
    "server": "localhost",
    "database": "SanitizationTest",
    "auth_type": "windows",
    "batch_size": 10000,
    "environment": "dev"
  },
  "pii_columns": [
    {
      "schema": "dbo",
      "table": "Customers",
      "column": "Email",
      "pii_type": "email",
      "nullable": false
    }
  ],
  "dry_run": false,
  "validate_before": true,
  "validate_after": true
}
```

#### Loading Configuration

```python
from src.config import ConfigLoader

# Load configuration from file
loader = ConfigLoader()
config = loader.load("config/pii_config.json")

# Access configuration values
print(f"Database: {config.database.database}")
print(f"Batch size: {config.database.batch_size}")
print(f"PII columns: {len(config.pii_columns)}")

# Get PII configuration
pii_config = config.get_pii_config()
tables = pii_config.get_unique_tables()
print(f"Tables to sanitize: {tables}")
```

#### Environment Variable Overrides

```bash
# Create .env file from example
cp config/.env.example .env

# Set environment variables
export SANITIZATION_DATABASE_SERVER=prod-server
export SANITIZATION_DATABASE_PASSWORD=SecurePassword123
export SANITIZATION_DATABASE_BATCH_SIZE=20000
```

Environment variables follow the pattern: `SANITIZATION_{SECTION}_{KEY}`

```python
# Load with environment overrides (default behavior)
config = loader.load("config/pii_config.json", use_env_overrides=True)

# Values from environment take precedence
print(config.database.server)  # "prod-server" (from env)
print(config.database.batch_size)  # 20000 (from env)
```

#### Configuration Validation

The framework validates all configuration values:

```python
from pydantic import ValidationError

try:
    config = loader.load("config/pii_config.json")
except ValidationError as e:
    # Clear error messages for missing/invalid values
    print(f"Configuration error: {e}")
```

Common validation errors:
- Missing required fields (server, database, auth_type)
- Out-of-range values (batch_size must be 100-1,000,000)
- Invalid auth credentials (SQL auth requires username and password)
- Duplicate PII column definitions
- Invalid PII types (must be: email, phone, name, ssn, generic)

### Schema Metadata Extraction

The framework includes a comprehensive schema extractor that queries SQL Server system tables to extract complete database structure information. This is a critical component for AI-based PII detection and FK-aware sanitization.

#### Extracting Schema Metadata

```python
from src.database import DatabaseConnectionManager, SchemaExtractor
from src.config import ConfigLoader

# Load configuration and create connection
config = ConfigLoader.load()
connection_manager = DatabaseConnectionManager(config.database)

# Create schema extractor
extractor = SchemaExtractor(connection_manager)

# Extract complete schema
schema = extractor.extract_schema("MyDatabase")

# Access extracted metadata
print(f"Found {len(schema['tables'])} tables")
print(f"Found {len(schema['foreign_keys'])} foreign key relationships")

# Browse tables
for table in schema['tables']:
    qualified_name = table['qualified_name']  # e.g., "[dbo].[Customers]"
    columns = schema['columns'][qualified_name]
    
    print(f"\n{qualified_name}:")
    print(f"  Columns: {len(columns)}")
    
    # Primary key
    if qualified_name in schema['primary_keys']:
        pk_cols = ', '.join(schema['primary_keys'][qualified_name])
        print(f"  Primary Key: {pk_cols}")
    
    # Show column details
    for col in columns[:3]:  # First 3 columns
        nullable = "NULL" if col['is_nullable'] else "NOT NULL"
        print(f"    - {col['name']}: {col['data_type']} {nullable}")
```

#### Schema Metadata Structure

The extracted schema includes:

- **Tables**: All user tables with schema names
  - `schema`: Schema name (e.g., "dbo", "sales")
  - `name`: Table name
  - `qualified_name`: Fully qualified name `[schema].[table]`

- **Columns**: Complete column metadata for all tables
  - `name`: Column name
  - `data_type`: SQL Server data type (normalized to uppercase)
  - `max_length`: Maximum length (characters for NVARCHAR, bytes for VARCHAR)
  - `precision`: Numeric precision
  - `scale`: Numeric scale
  - `is_nullable`: Whether column accepts NULL values
  - `is_identity`: Whether column is an IDENTITY column
  - `is_computed`: Whether column is computed
  - `is_max_type`: Whether column uses MAX length (VARCHAR(MAX), etc.)

- **Primary Keys**: Primary key columns (including composite keys)
  - Preserves column order for composite keys

- **Foreign Keys**: All FK relationships (including composite, self-referencing, circular)
  - `constraint_name`: FK constraint name
  - `parent_schema`, `parent_table`, `parent_column`: Referenced table/column
  - `child_schema`, `child_table`, `child_column`: Referencing table/column
  - `is_self_referencing`: Flag for self-referencing FKs
  - `ordinal_position`: Position in composite key

- **Unique Constraints**: Unique constraints with column lists

- **Indexes**: Index metadata (clustered, non-clustered, unique)

#### Running the Example Script

```bash
# Run the schema extraction example
python examples/extract_schema_example.py

# Output:
# - Console summary with statistics
# - JSON file: output/extracted_schema.json
```

#### Edge Cases Handled

The schema extractor properly handles:
- ✅ Multiple schemas (never assumes `dbo`)
- ✅ Special characters in object names (proper `[]` escaping)
- ✅ Composite primary and foreign keys (preserves column order)
- ✅ Self-referencing foreign keys (hierarchical data)
- ✅ Circular foreign key dependencies
- ✅ Tables without primary keys
- ✅ NVARCHAR vs VARCHAR (correct character vs byte lengths)
- ✅ VARCHAR(MAX) and NVARCHAR(MAX) types
- ✅ DECIMAL precision and scale
- ✅ Case-sensitive collations

### Configuration Validation

The framework includes a comprehensive configuration validator that checks your PII configuration file against the actual database schema. This prevents runtime errors and ensures that all specified columns exist and are compatible with sanitization operations.

#### Running Configuration Validation

```python
from src.validation import ConfigValidator
from src.database import ConnectionManager, SchemaExtractor
from src.config import ConfigLoader

# Load configuration
config = ConfigLoader().load("config/pii_config.json")

# Create connection and schema extractor
connection_manager = ConnectionManager(config.database)
schema_extractor = SchemaExtractor(connection_manager)

# Create validator
validator = ConfigValidator(schema_extractor)

# Validate configuration
result = validator.validate_config(config)

# Check results
if result.is_valid:
    print(f"✅ Configuration is valid!")
else:
    print(f"❌ Configuration has {result.error_count} errors:")
    for error in result.errors:
        print(f"  - {error.message}")
        if error.suggested_action:
            print(f"    Suggestion: {error.suggested_action}")

# Review warnings
if result.warning_count > 0:
    print(f"⚠️  {result.warning_count} warnings:")
    for warning in result.warnings:
        print(f"  - {warning.message}")
```

#### Validation Checks

The validator performs comprehensive checks:

**Column Existence**:
- ✅ Schema exists in database
- ✅ Table exists in schema
- ✅ Column exists in table
- ✅ Special handling for system schemas (sys, INFORMATION_SCHEMA)

**Data Type Compatibility**:
- ✅ Email: VARCHAR/NVARCHAR/CHAR/NCHAR
- ✅ Phone: VARCHAR/CHAR/NCHAR (numeric-compatible)
- ✅ Name: VARCHAR/NVARCHAR/CHAR/NCHAR
- ✅ SSN: VARCHAR/CHAR (11 chars min: "XXX-XX-XXXX")
- ✅ Date of Birth: DATE/DATETIME/DATETIME2/SMALLDATETIME
- ✅ Account Number: VARCHAR/CHAR/NVARCHAR/NCHAR/BIGINT/INT
- ⚠️  Warns if column length insufficient (email needs ≥7 chars, phone ≥10, etc.)

**Nullable Constraints**:
- ✅ Verifies nullable setting matches database column
- ✅ Warns if config says NOT NULL but column is nullable
- ✅ Errors if config allows NULL but column is NOT NULL

**Special Column Warnings**:
- ⚠️  Primary key columns (may affect referential integrity)
- ⚠️  Foreign key columns (requires dependency-aware sanitization)
- ⚠️  Unique constraints (may cause duplicate detection after masking)
- ❌ Identity columns (cannot be directly updated)
- ⚠️  Computed columns (cannot be modified)
- ⚠️  System tables (generally should not be sanitized)
- ⚠️  Views (sanitize underlying tables instead)
- ❌ Temp tables (# prefix - transient tables)

#### Running Validation from Command Line

```bash
# Run validation example
python examples/validate_config_example.py

# Output includes:
# - Validation summary (passed/failed)
# - Detailed error and warning list
# - Color-coded console output (green/yellow/red)
# - JSON report saved to output/validation_report.json
```

#### Validation Result Structure

```python
# Access validation results programmatically
result = validator.validate_config(config)

# Properties
print(f"Valid: {result.is_valid}")           # True if no errors
print(f"Errors: {result.error_count}")       # Count of blocking errors
print(f"Warnings: {result.warning_count}")   # Count of non-blocking warnings
print(f"Info: {result.info_count}")          # Count of informational messages

# Get all issues
all_issues = result.get_all_issues()

# Get issues by severity
errors = result.get_issues_by_severity("ERROR")
warnings = result.get_issues_by_severity("WARNING")

# Get issues for specific column
column_issues = result.get_issues_by_column("dbo", "Users", "Email")

# Generate formatted summary
summary = result.format_summary(show_issues=True)
print(summary)

# Export to JSON for reporting
report = result.to_dict()
with open("validation_report.json", "w") as f:
    json.dump(report, f, indent=2)
```

#### Validation Issue Details

Each validation issue includes:
- `severity`: ERROR (blocks sanitization), WARNING (non-blocking), or INFO
- `message`: Human-readable description
- `column`: Affected column (schema.table.column)
- `code`: Error code constant (e.g., `ErrorCodes.COLUMN_NOT_FOUND_IN_TABLE`)
- `suggested_action`: Actionable recommendation (e.g., "Remove from config or create column")
- `context`: Additional context (e.g., column data type, available alternatives)

#### Integration with Configuration Loading

```python
from src.config import ConfigLoader
from src.validation import ConfigValidator

# Load and validate in one step
def load_and_validate(config_path: str) -> tuple[SanitizationConfig, ValidationResult]:
    config = ConfigLoader().load(config_path)
    validator = ConfigValidator(schema_extractor)
    result = validator.validate_config(config)
    
    if not result.is_valid:
        raise ValueError(f"Invalid configuration: {result.error_count} errors")
    
    return config, result

# Use in production
try:
    config, validation_result = load_and_validate("config/pii_config.json")
    print(f"✅ Configuration validated with {validation_result.warning_count} warnings")
except ValueError as e:
    print(f"❌ Configuration validation failed: {e}")
    sys.exit(1)
```

#### Best Practices

1. **Always validate before sanitization**: Prevent runtime errors by catching configuration issues early
2. **Review warnings carefully**: Warnings indicate potential issues (FK columns, PKs, unique constraints)
3. **Use strict mode for production**: Consider treating warnings as errors in production environments
4. **Re-validate after schema changes**: Run validation whenever database schema is modified
5. **Automate validation**: Include validation in CI/CD pipelines and pre-deployment checks
6. **Save validation reports**: Keep JSON reports for auditing and troubleshooting

### Interactive PII Review CLI

The framework provides an interactive command-line interface for reviewing AI-detected PII columns and building finalized sanitization configurations. The UI uses the Rich library for beautiful terminal formatting with tables, panels, and color-coded output.

#### Launching the Review Interface

```python
from src.database import ConnectionManager, SchemaExtractor
from src.ai import CopilotClient
from src.ui import PIIReviewCLI
from src.config import ConfigLoader

# Load configuration
config = ConfigLoader().load("config/pii_config.json")

# Initialize components
connection_manager = ConnectionManager(config.database)
schema_extractor = SchemaExtractor(connection_manager)
ai_client = CopilotClient(config.ai)

# Detect PII using AI
pii_columns = ai_client.detect_pii_batch(["dbo", "sales"])

# Launch interactive review
cli = PIIReviewCLI(schema_extractor=schema_extractor)
final_configs = cli.review_recommendations(pii_columns)

# Save finalized configuration
if final_configs:
    cli.save_to_file("config/pii_config_final.json")
    print(f"✓ Saved {len(final_configs)} PII column configurations")
```

#### CLI Features

The review interface provides:

- **Visual Display**: AI recommendations shown in formatted tables with schema, table, column, PII type, and confidence
- **Add Columns**: Manually add PII columns with validation against database schema
- **Remove Columns**: Remove false positives from AI recommendations  
- **Modify Columns**: Change PII type or nullable flag for existing columns
- **Undo Operations**: Revert the last action (add, remove, or modify)
- **Schema Validation**: Verify columns exist with warnings for primary/foreign keys
- **Configuration Persistence**: Save finalized configurations to JSON

#### Interactive Commands

```
Commands: [A]dd | [R]emove | [M]odify | [U]ndo | [S]ave | [H]elp | [Q]uit
```

**[A]dd** - Add a new PII column:
- Prompts for schema, table, and column name
- Validates column exists in database (if SchemaExtractor provided)
- Warns if column is a primary key or foreign key
- Allows selection of PII type from supported types
- Sets nullable flag

**[R]emove** - Remove a column from configuration:
- Displays numbered list of current columns
- Removes selected column by index
- Can be undone

**[M]odify** - Modify an existing column:
- Change PII type (EMAIL → PHONE, etc.)
- Toggle nullable flag
- Preserves original values unless explicitly changed
- Can be undone

**[U]ndo** - Revert last operation:
- Restores state before last add/remove/modify
- Maintains full history during session
- Updates statistics accordingly

**[S]ave** - Accept changes and return finalized config:
- Returns list of PIIColumnConfig objects
- Can be saved to JSON file
- Ends review session

**[Q]uit** - Exit without saving:
- Prompts for confirmation if changes were made
- Returns empty list
- Discards all changes

#### Example Session

```
╭─────────────────────────────── Summary ───────────────────────────────────╮
│ Total PII Columns: 12                                                     │
│   • AI Detected: 10                                                       │
│   • Manually Added: 2                                                     │
│   • Removed: 1                                                            │
│   • Modified: 1                                                           │
╰───────────────────────────────────────────────────────────────────────────╯

                      Current PII Configuration
┏━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ #  ┃ Schema.Table  ┃ Column      ┃ PII Type     ┃ Nullable ┃
┡━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━┩
│ 1  │ dbo.Users     │ Email       │ EMAIL        │    ✓     │
│ 2  │ dbo.Users     │ PhoneNumber │ PHONE        │    ✓     │
│ 3  │ dbo.Users     │ SSN         │ SSN          │    ✗     │
│ 4  │ dbo.Orders    │ CreditCard  │ CREDIT_CARD  │    ✓     │
...
└────┴───────────────┴─────────────┴──────────────┴──────────┘

Commands: [A]dd | [R]emove | [M]odify | [U]ndo | [S]ave | [H]elp | [Q]uit
Choose action:
```

#### Schema Validation

When adding columns, the CLI validates against the database schema:

```python
# Validation checks:
# ✓ Table exists in target schema
# ✓ Column exists in table
# ⚠ Warning if column is primary key
# ⚠ Warning if column is foreign key
# ✗ Blocks addition if table/column not found
```

Example validation warnings:

```
╭─────────────────────── Validation Results ───────────────────────╮
│ WARNING  Column 'UserID' is a PRIMARY KEY - sanitizing may       │
│          break relationships                                      │
│ WARNING  Column 'CustomerID' is a FOREIGN KEY - sanitizing may   │
│          break referential integrity                              │
╰───────────────────────────────────────────────────────────────────╯
Add column anyway? [y/n]:
```

#### Supported PII Types

The CLI supports the following PII types:

1. **EMAIL** - Email addresses
2. **PHONE** - Phone numbers
3. **SSN** - Social Security Numbers
4. **CREDIT_CARD** - Credit card numbers
5. **NAME** - Personal names
6. **ADDRESS** - Physical addresses
7. **DATE_OF_BIRTH** - Birth dates
8. **IP_ADDRESS** - IP addresses
9. **ACCOUNT_NUMBER** - Account identifiers
10. **CUSTOM** - Custom PII types

#### Running the Example

```bash
# Run the interactive review example
python examples/review_cli_example.py

# Workflow:
# 1. Connects to database
# 2. Extracts schema metadata
# 3. Uses AI to detect PII columns
# 4. Launches interactive CLI
# 5. User reviews and modifies
# 6. Saves finalized configuration

# Output: pii_config_finalized.json
```

#### Configuration Output Format

The CLI saves configurations in JSON format compatible with the sanitization engine:

```json
[
  {
    "schema": "dbo",
    "table": "Users",
    "column": "Email",
    "pii_type": "EMAIL",
    "nullable": true
  },
  {
    "schema": "dbo",
    "table": "Users",
    "column": "SSN",
    "pii_type": "SSN",
    "nullable": false
  }
]
```

## Smart Generation: Constraint-Aware Fake Value Generation

The framework uses **Smart Generation** to ensure all generated fake values fit perfectly within database column constraints without truncation, eliminating data corruption.

### The Problem with Truncation

Traditional sanitization approaches generate fixed-format values and truncate them if they're too long:

```python
# ❌ OLD APPROACH: Generate-then-truncate
email = "user_a1b2c3d4@example.com"  # 27 characters
if len(email) > 15:
    email = email[:15]  # "user_a1b2c3d4@e" - INVALID!
```

This creates corrupt data:
- ❌ Broken emails: `john.doe@gmai` (missing TLD)
- ❌ Invalid phone numbers: `(555) 555-55` (incomplete)
- ❌ Application failures in downstream systems
- ❌ Failed data integrity validation

### The Smart Generation Solution

Smart Generation selects the appropriate format **BEFORE** generating the value, based on available column space:

```python
# ✅ NEW APPROACH: Smart Generation
def generate_email(max_length):
    if max_length < 6:
        raise MaskingError("Column too short")
    elif max_length >= 26:
        return "user_a1b2c3d4@example.com"  # Standard format
    elif max_length >= 18:
        return "u_a1b2c3@demo.co"           # Compact format
    else:
        return "a@x.co"                      # Minimal format (6 chars)
```

### Format Tiers by Masker Type

Each masker implements multiple format tiers that automatically adapt to column size:

#### EmailMasker (3 tiers)
- **Standard** (≥26 chars): `user_a1b2c3d4@example.com`
- **Compact** (18-25 chars): `u_a1b2c3@demo.co`
- **Minimal** (6-17 chars): `a@x.co`

#### PhoneMasker (3 tiers)
- **Standard** (≥14 chars): `(555) 555-5555`
- **Compact** (12-13 chars): `555-555-5555`
- **Minimal** (10-11 chars): `5555555555`

#### NameMasker (4 tiers)
- **Full** (≥20 chars): `Dr. John Smith Jr.`
- **First+Last** (10-19 chars): `John Smith`
- **First** (4-9 chars): `John`
- **Initial** (2-3 chars): `JS`

#### SSNMasker (2 tiers)
- **Formatted** (≥11 chars): `123-45-6789`
- **Plain** (9-10 chars): `123456789`

### Benefits

✅ **Zero Data Corruption** - All generated values are valid and complete
✅ **Better Performance** - 5-10% faster (no wasted generation + truncation cycles)  
✅ **Transparent Debugging** - Truncation becomes a bug indicator, not normal behavior  
✅ **Maintains Determinism** - Same input always produces same output for same length  
✅ **Graceful Degradation** - Adapts to small columns intelligently  
✅ **Clear Error Messages** - Fail-fast validation for impossible constraints  

### Truncation Tracking

The framework automatically tracks any truncations that occur (which indicate bugs):

```python
# After processing, check truncation metrics
truncation_count, details = masker.get_truncation_metrics()

# Sanitization report includes truncation status
print(f"Truncation Status:")
if report.total_truncations == 0:
    print(f"  ✅ No truncations detected (smart generation working correctly)")
else:
    print(f"  ⚠️ {report.total_truncations} truncations detected - BUG!")
```

The orchestrator automatically collects and reports truncation metrics for every table and column, making it easy to identify and fix any smart generation bugs.

### Example Usage

```python
from src.masking.email_masker import EmailMasker
from src.masking.base_masker import ColumnInfo

masker = EmailMasker(seed=42)

# Small column - automatically uses minimal format
column_small = ColumnInfo(data_type="VARCHAR", max_length=10, nullable=True)
email = masker.mask("john.doe@example.com", column_small)
print(email)  # "a@x.co" (6 chars, valid email)

# Large column - uses standard format
column_large = ColumnInfo(data_type="VARCHAR", max_length=100, nullable=True)
email = masker.mask("john.doe@example.com", column_large)
print(email)  # "user_a1b2c3d4@example.com" (27 chars, full format)

# Column too short - clear error message
column_tiny = ColumnInfo(data_type="VARCHAR", max_length=5, nullable=True)
try:
    masker.mask("john.doe@example.com", column_tiny)
except MaskingError as e:
    print(e.message)  # "Column too short for minimum email (6 chars)"
    print(e.suggested_action)  # "Increase column size to at least 6 characters"
```

### Complete Example

See [examples/smart_generation_example.py](examples/smart_generation_example.py) for comprehensive examples including:
- Format tier demonstrations for all masker types
- Edge case handling
- Performance comparisons
- Truncation tracking
- Integration with orchestrator

### Implementation Details

Smart Generation is implemented across all maskers:
- [src/masking/base_masker.py](src/masking/base_masker.py) - Foundation with truncation tracking
- [src/masking/email_masker.py](src/masking/email_masker.py) - 3 email format tiers
- [src/masking/phone_masker.py](src/masking/phone_masker.py) - 3 phone format tiers
- [src/masking/name_masker.py](src/masking/name_masker.py) - 4 name format tiers
- [src/masking/ssn_masker.py](src/masking/ssn_masker.py) - 2 SSN format tiers
- [src/masking/generic_masker.py](src/masking/generic_masker.py) - Exact length generation

The orchestrator ([src/sanitization/orchestrator.py](src/sanitization/orchestrator.py)) automatically integrates truncation tracking into sanitization reports.

## Project Structure

```
database-sanitization/
├── src/
│   ├── database/           # Database connection management (Story 1.1 ✅)
│   ├── config/             # Configuration management (Story 1.2 ✅)
│   ├── logging/            # Structured logging (Story 1.3 ✅)
│   ├── ai/                 # AI integration (Story 3.1 ✅)
│   ├── ui/                 # Interactive CLI (Story 3.2 ✅)
│   ├── masking/            # Data masking strategies (Phase 4)
│   ├── sanitization/       # Orchestration logic (Phase 5)
│   ├── mapping/            # Mapping table management (Phase 5)
│   └── validation/         # Data validation (Phase 5)
├── tests/
│   ├── unit/               # Unit tests
│   └── integration/        # Integration tests
├── config/                 # Configuration files
│   ├── .env.example        # Environment variable template
│   └── pii_config.example.json  # PII configuration template
├── examples/               # Example scripts
│   ├── review_cli_example.py    # Interactive PII review demo
│   ├── connection_example.py    # Database connection demo
│   └── extract_schema_example.py  # Schema extraction demo
├── CriticalRules/          # Edge case documentation
├── Requirement/            # Requirements specification
└── USER_STORIES.md         # Development roadmap

```

## Development Roadmap

### Phase 1: Foundation & Infrastructure (1 week)
- [x] Story 1.1: Database Connection Manager
- [x] Story 1.2: Configuration Management System
- [ ] Story 1.3: Structured Logging Framework
- [ ] Story 1.4: Exception Hierarchy
- [ ] Story 1.5: Project Structure & Packaging

### Phase 2: Database Layer (2 weeks)
- [ ] Story 2.1: Schema Metadata Extraction
- [ ] Story 2.2: Foreign Key Dependency Graph Builder
- [ ] Story 2.3: Batch Data Extractor
- [ ] Story 2.4: Batch Data Updater
- [ ] Story 2.5: Transaction & Rollback Manager

### Phase 3: AI Integration (1 week)
- [x] Story 3.1: GitHub Copilot API Client
- [x] Story 3.2: User Review Interface (CLI)
- [ ] Story 3.3: Configuration Schema Validator

### Phase 4: Data Masking Engine (1.5 weeks)
- [ ] Story 4.1: Base Masker Abstract Class
- [ ] Story 4.2-4.6: Specific maskers (Email, Phone, Name, SSN, Generic)

### Phase 5: Orchestration (2 weeks)
- [ ] Story 5.1: Masking Strategy Factory
- [ ] Story 5.2: Sanitization Orchestrator
- [ ] Story 5.3: Mapping Table Manager
- [ ] Story 5.4: Desensitization Engine
- [ ] Story 5.5: Pre/Post Validation

### Phase 6: Testing & Documentation (1.5 weeks)
- [ ] Story 6.1: Unit Tests
- [ ] Story 6.2: Integration Tests
- [ ] Story 6.3: Documentation

## Running Tests

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run with coverage
pytest tests/unit/ -v --cov=src.database --cov-report=html

# Run integration tests (requires SQL Server)
export SQLSERVER_HOST=localhost
export SQLSERVER_DB=master
export SQLSERVER_AUTH=windows
pytest tests/integration/ -v
```

## Critical Rules & Edge Cases

This framework strictly enforces critical rules for production-grade sanitization:

1. **Multi-Schema Support** - Never assume `dbo`, always use `[schema].[table]`
2. **Data Type Compliance** - Respect column lengths, types, precision, and constraints
3. **Referential Integrity** - Preserve foreign key relationships, handle circular dependencies
4. **Performance** - Batch processing, key-based pagination, set-based operations
5. **Security** - No PII logging, encrypted mappings, parameterized queries only

See [CriticalRules/CriticalRulesAndEdgeCases.md](CriticalRules/CriticalRulesAndEdgeCases.md) for complete details.

## Documentation

- [User Stories](USER_STORIES.md) - Development roadmap with 28 user stories
- [Requirements](Requirement/requirement.md) - Complete functional requirements
- [Critical Rules](CriticalRules/CriticalRulesAndEdgeCases.md) - Edge cases and constraints

## Contributing

This project follows strict code quality standards:
- Type hints on all public functions
- Comprehensive docstrings (Google style)
- PEP 8 compliance
- 80%+ test coverage
- Security-first mindset

See [.github/instructions/sanitization-standards.instructions.md](.github/instructions/sanitization-standards.instructions.md) for details.

## License

[License details to be added]

## Contact

[Contact information to be added]

---

**Version**: 0.1.0 (Phase 1 in progress)  
**Last Updated**: March 26, 2026
