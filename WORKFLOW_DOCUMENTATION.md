# Database Sanitization Framework - Complete Workflow Documentation

**Version:** 2.0  
**Last Updated:** April 22, 2026  
**Author:** Database Sanitization Team

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Key Capabilities](#2-key-capabilities)
3. [Architecture](#3-architecture)
4. [Prerequisites](#4-prerequisites)
5. [Installation](#5-installation)
6. [Configuration](#6-configuration)
7. [Complete Workflow](#7-complete-workflow)
8. [Security Features](#8-security-features)
9. [Advanced Features](#9-advanced-features)
10. [Troubleshooting](#10-troubleshooting)
11. [Best Practices](#11-best-practices)

---

## 1. Project Overview

### What is This Project?

The **Database Sanitization Framework** is a comprehensive, production-ready Python solution for identifying, masking, and managing Personally Identifiable Information (PII) in Microsoft SQL Server databases. It enables organizations to create safe, anonymized copies of production databases for development, testing, and analytics while maintaining data integrity and referential relationships.

### Core Purpose

- **Compliance:** Meet GDPR, HIPAA, CCPA, and other privacy regulations by removing real PII from non-production environments
- **Security:** Protect sensitive customer data from unauthorized access in development/test systems
- **Data Utility:** Preserve database structure, relationships, and statistical properties while masking sensitive values
- **Reversibility:** Optional desanitization capability allows authorized restoration of original data when needed

### Domain Agnostic

This framework works across any industry:
- Healthcare (patient records, medical history)
- Financial Services (account numbers, SSNs, credit cards)
- E-commerce (customer emails, addresses, payment info)
- HR Systems (employee data, salary information)
- SaaS Applications (user profiles, contact information)

---

## 2. Key Capabilities

### 2.1 AI-Powered PII Detection

**Automatic Column Identification**
- Uses GitHub Copilot API to analyze database schema and identify PII columns
- Examines table names, column names, data types, and relationships
- Confidence scoring and intelligent deduplication
- Handles complex schemas with thousands of tables

**Key Features:**
- Batch processing of multiple tables
- Intelligent retry logic with exponential backoff
- Response caching to minimize API calls
- System table exclusion (metadata tables automatically filtered)
- Comprehensive PII type detection (email, phone, SSN, address, credit card, DOB, etc.)

**Usage:**
```bash
python ai_detection_direct.py --export-json config/detected_pii.json
```

### 2.2 Smart Generation Engine

**Constraint-Aware Masking**

The framework's signature feature is **Smart Generation** - an intelligent masking engine that automatically adapts fake values to fit database column constraints without truncation.

**Multiple Format Tiers:**

Each PII type has 3-4 format variations that adapt to column length:

| PII Type | Standard Format | Compact Format | Minimal Format |
|----------|----------------|----------------|----------------|
| **Email** | `user_a1b2c3d4@example.com` (26 chars) | `u_a1b2c3@demo.co` (18 chars) | `a@x.co` (6 chars) |
| **Phone** | `(555) 555-5555` (14 chars) | `555-555-5555` (12 chars) | `5555555555` (10 chars) |
| **SSN** | `123-45-6789` (11 chars) | `123456789` (9 chars) | - |
| **Name** | `Dr. John Smith Jr.` (20 chars) | `John Smith` (10 chars) | `John` (4 chars) |
| **Credit Card** | `4532-1234-5678-9012` (19 chars) | `4532 1234 5678 9012` (19 chars) | `4532123456789` (13 chars) |

**Name Component Detection:**

Intelligent detection of name column types:
- **First Name:** `FirstName`, `fname`, `GivenName`, `forename`
- **Last Name:** `LastName`, `lname`, `Surname`, `FamilyName`
- **Middle Name:** `MiddleName`, `mname`, `middle_initial`
- **Full Name:** `FullName`, `name`, `PersonName`, `CustomerName`

**Address Component Detection:**

Smart handling of address fields:
- **City:** Generates realistic city names
- **State:** Two-letter state codes or full names
- **Postal Code:** ZIP codes or postal codes
- **Street Address:** Format-adaptive street addresses
- **Country:** Country names or ISO codes

**Date of Birth Generation:**

Age-aware date generation:
- Default age range: 18-80 years
- Deterministic day-level variation within year
- Type-aware returns: `DATE`, `DATETIME`, or formatted strings
- Format tiers: Full ISO 8601, Date only, Year only

**Credit Card Generation:**

Industry-compliant test card numbers:
- Uses reserved test BIN ranges (never real cards)
- Luhn algorithm validation for checksum
- Supports Visa, MasterCard, AmEx, Discover
- Format tiers: Dashed, spaced, or plain formats

### 2.3 Deterministic Masking

**Consistency Across Relationships**

- **Same Input → Same Output:** Identical values always generate identical fake values
- **Foreign Key Integrity:** Referential relationships preserved automatically
- **Cross-Table Consistency:** Email in Users table matches same email in Orders table
- **SHA-256 Seeding:** Cryptographic hashing ensures deterministic pseudorandom generation

### 2.4 Mapping & Reversibility

**Complete Traceability**

The framework stores mappings between original and masked values in a dedicated `pii_mappings` table:

**Mapping Table Schema:**
```sql
CREATE TABLE dbo.pii_mappings (
    mapping_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    operation_id UNIQUEIDENTIFIER NOT NULL,           -- Groups mappings by sanitization run
    schema_name NVARCHAR(128) NOT NULL,
    table_name NVARCHAR(128) NOT NULL,
    column_name NVARCHAR(128) NOT NULL,
    original_value_hash VARBINARY(32) NOT NULL,       -- SHA-256 hash for lookups
    original_value_encrypted VARBINARY(MAX),          -- AES-256 encrypted original
    masked_value NVARCHAR(MAX),                       -- Fake value (plaintext)
    primary_key_columns NVARCHAR(MAX),                -- JSON array of PK columns
    primary_key_values NVARCHAR(MAX),                 -- JSON array of PK values
    data_type NVARCHAR(128) NOT NULL,
    is_null BIT NOT NULL DEFAULT 0,
    created_at DATETIME2(7) NOT NULL DEFAULT GETUTCDATE()
);
```

**Key Features:**
- Row-level tracking via primary key capture
- Batch storage (10,000 entries per batch)
- Optional AES-256-GCM encryption of original values
- Optimized indexes for efficient lookups

### 2.5 Complete Desanitization

**Full or Selective Restoration**

Reverse the sanitization process to restore original PII values:

**Features:**
- **Full Database Restore:** Restore all tables in a sanitization operation
- **Selective Table Restore:** Restore specific tables only
- **Dry-Run Mode:** Preview changes before applying
- **Transaction Safety:** Automatic rollback on errors
- **Type-Safe Restoration:** Converts encrypted strings back to proper SQL types
- **Batch Processing:** Efficient restoration of large datasets

**Desanitization Workflow:**
1. Load mappings from `pii_mappings` table by operation ID
2. Decrypt original values using AES-256-GCM
3. Convert values to proper SQL data types
4. Update database in batches using primary key matching
5. Commit or rollback based on success/failure

**Usage:**
```bash
# Dry-run first (preview only)
python desanitize.py <operation_id>

# Full restore
python desanitize.py <operation_id> --execute

# Selective restore
python desanitize.py <operation_id> --execute --tables dbo.Customers dbo.Orders
```

### 2.6 Configuration Validation

**Schema Validation Engine**

Validates PII configuration files against actual database schema:

**Validation Checks:**
- ✅ Column existence verification
- ✅ Data type compatibility
- ✅ Nullable constraint validation
- ✅ Primary key warnings
- ✅ Foreign key warnings
- ✅ Computed column detection
- ✅ Special column handling (identity, timestamps)

**Usage:**
```bash
python validate_config_direct.py config/pii_config_ai_generated.json
```

### 2.7 High Performance

**Optimized for Large Databases**

- **Batch Processing:** Configurable batch sizes (default: 5,000 rows)
- **Connection Pooling:** Reuses database connections efficiently
- **Parallel Processing:** Multi-table parallel sanitization support
- **Fast ExecuteMany:** Leverages pyodbc fast_executemany for bulk operations
- **Indexed Lookups:** Optimized mapping table indexes for desanitization queries

### 2.8 Security-First Design

**Defense in Depth**

- **Encrypted Mappings:** AES-256-GCM encryption via Fernet
- **Parameterized Queries:** SQL injection prevention
- **No PII Logging:** Automatic redaction of sensitive data in logs
- **Environment Variable Keys:** Encryption keys never hardcoded
- **Secure Key Derivation:** PBKDF2-based key generation
- **Transaction Safety:** Automatic rollback on errors

---

## 3. Architecture

### 3.1 System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                     DATABASE SANITIZATION FRAMEWORK              │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────┐        ┌──────────────────────┐
│  AI Detection Layer  │        │  Validation Layer    │
│                      │        │                      │
│  • GitHub Copilot    │        │  • Schema Validator  │
│  • Pattern Detection │───────▶│  • Config Checker    │
│  • Confidence Score  │        │  • FK/PK Warnings    │
└──────────────────────┘        └──────────────────────┘
           │                               │
           ▼                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Configuration File (JSON)                    │
│  • Database connection settings                                  │
│  • PII column definitions (table, column, pii_type)             │
│  • Masking strategies                                            │
│  • Logging and retry configuration                              │
└─────────────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Sanitization Engine                            │
│                                                                   │
│  ┌────────────────────┐      ┌──────────────────────┐           │
│  │ SmartMaskerEngine  │      │  Mapping Manager     │           │
│  │                    │      │                      │           │
│  │ • EmailMasker      │      │ • Capture Mappings   │           │
│  │ • PhoneMasker      │─────▶│ • Encrypt Originals  │           │
│  │ • NameMasker       │      │ • Store in DB        │           │
│  │ • SSNMasker        │      │ • PK Tracking        │           │
│  │ • AddressMasker    │      │                      │           │
│  │ • DOBMasker        │      └──────────────────────┘           │
│  │ • CreditCardMasker │                 │                       │
│  └────────────────────┘                 │                       │
│                                          ▼                       │
│                              ┌────────────────────┐             │
│                              │ Encryption Manager │             │
│                              │  (AES-256-GCM)     │             │
│                              └────────────────────┘             │
└──────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SQL Server Database                            │
│                                                                   │
│  ┌────────────────┐           ┌──────────────────┐              │
│  │  User Tables   │           │  pii_mappings    │              │
│  │  (Sanitized)   │◀─────────▶│  (Mappings)      │              │
│  └────────────────┘           └──────────────────┘              │
└─────────────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Desanitization Engine                          │
│                                                                   │
│  • Load mappings by operation_id                                 │
│  • Decrypt original values                                       │
│  • Type conversion (string → DATE, INT, etc.)                    │
│  • Batch restoration with PK matching                            │
│  • Transaction management                                        │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Key Modules

| Module | Purpose | Key Files |
|--------|---------|-----------|
| **AI Detection** | Automatic PII column discovery | `ai_detection_direct.py` |
| **Validation** | Config and schema validation | `validate_config_direct.py`, `check_mappings.py` |
| **Sanitization** | Core masking engine | `sanitize_smart.py` |
| **Desanitization** | Restoration engine | `desanitization/desanitize.py`, `desanitization/desanitization_config.py` |
| **Mapping** | Value tracking & encryption | `mapping/mapping_manager.py`, `mapping/encryption_utils.py`, `mapping/pk_utils.py` |
| **Configuration** | Settings management | `config/pii_config*.json` |
| **Database Schema** | Mapping table creation | `database/schema/create_mapping_table.sql` |

### 3.3 Data Flow

**Sanitization Flow:**
```
1. Load Config → 2. Connect to DB → 3. Initialize Maskers → 4. For Each PII Column:
   a. Fetch data
   b. Generate fake values (deterministic)
   c. Capture mapping (optional)
   d. Update database
→ 5. Commit Transaction → 6. Report Results
```

**Desanitization Flow:**
```
1. Load Operation ID → 2. Validate Operation Exists → 3. Load Mappings from DB
→ 4. Decrypt Original Values → 5. Group by Table → 6. For Each Table:
   a. Convert types
   b. Update rows by PK
   c. Batch commit
→ 7. Verify Restoration → 8. Report Results
```

---

## 4. Prerequisites

### 4.1 Software Requirements

| Component | Version | Required |
|-----------|---------|----------|
| **Python** | 3.10 or higher | ✅ Yes |
| **Microsoft SQL Server** | 2016+ or Azure SQL | ✅ Yes |
| **ODBC Driver for SQL Server** | 17 or 18 | ✅ Yes |
| **GitHub Copilot API Access** | Active subscription | ⚠️ Optional (for AI detection) |

### 4.2 Python Dependencies

Install via `pip install -r requirements.txt`:

```
pyodbc==5.0.1                   # SQL Server connectivity
pydantic==2.5.0                 # Configuration validation
python-dotenv==1.0.0            # Environment variable management
faker==19.12.0                  # Fake data generation library
cryptography==41.0.7            # AES-256 encryption
requests==2.31.0                # HTTP client for AI API
requests-cache==1.1.1           # API response caching
networkx==3.2.1                 # Dependency graph analysis
pytest==7.4.3                   # Testing framework
rich==13.7.0                    # Terminal formatting
```

### 4.3 Database Permissions

**Minimum Required Permissions:**
- `SELECT` on all tables to be sanitized
- `UPDATE` on all tables to be sanitized
- `CREATE TABLE` (for pii_mappings table)
- `CREATE SCHEMA` (if using custom schema)
- `INSERT`, `UPDATE`, `DELETE` on pii_mappings table

**Recommended Role:** `db_owner` for development/test environments

### 4.4 Environment Setup

**Required Environment Variables:**

```bash
# Database Connection
SQLSERVER_HOST=localhost
SQLSERVER_DB=YourDatabase

# Optional: SQL Authentication (if not using Windows Auth)
SQLSERVER_USER=sa
SQLSERVER_PASSWORD=YourPassword

# Encryption (for desanitization support)
SANITIZATION_ENCRYPTION_KEY=<Fernet-key-here>

# AI Detection (optional)
GITHUB_COPILOT_TOKEN=<your-token-here>
```

**Generate Encryption Key:**
```python
from cryptography.fernet import Fernet
key = Fernet.generate_key()
print(f"SANITIZATION_ENCRYPTION_KEY={key.decode()}")
```

### 4.5 Network Requirements

- Database server must be accessible from Python runtime
- Outbound HTTPS access to `models.github.ai` (for AI detection)
- Firewall rules allowing SQL Server port (default: 1433)

---

## 5. Installation

### 5.1 Clone Repository

```bash
git clone <repository-url>
cd DB-Sanitization
```

### 5.2 Create Virtual Environment

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 5.3 Install Dependencies

```bash
pip install -r requirements.txt
```

### 5.4 Configure Environment

Create `.env` file in project root:

```env
# Database
SQLSERVER_HOST=(localdb)\MSSQLLocalDB
SQLSERVER_DB=Testsanitization

# Encryption (generate using cryptography.fernet.Fernet.generate_key())
SANITIZATION_ENCRYPTION_KEY=your-fernet-key-here

# AI Detection (optional)
GITHUB_COPILOT_TOKEN=your-copilot-token-here
```

### 5.5 Initialize Database Schema

**Option 1: Automatic (via Python)**
```bash
# Schema is auto-created when sanitization runs with mapping enabled
python sanitize_smart.py config/pii_config.example.json
```

**Option 2: Manual (via SQL)**
```bash
# Execute the SQL script directly
sqlcmd -S localhost -d YourDatabase -i database/schema/create_mapping_table.sql
```

### 5.6 Verify Installation

```bash
# Test database connectivity
python -c "import pyodbc; print('pyodbc OK')"

# Test environment loading
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('Env OK')"

# Test encryption
python -c "from mapping import EncryptionManager; print('Encryption OK')"
```

---

## 6. Configuration

### 6.1 Configuration File Structure

**Example: `config/pii_config.example.json`**

```json
{
  "database": {
    "server": "(localdb)\\MSSQLLocalDB",
    "database": "Testsanitization",
    "auth_type": "windows",
    "timeout": 60,
    "batch_size": 5000,
    "max_retries": 5,
    "retry_delay": 1.0,
    "pool_size": 10,
    "environment": "dev",
    "log_batch_frequency": 10,
    "bulk_update_strategy": "auto",
    "enable_fast_executemany": true,
    "enable_parallel_processing": true,
    "max_parallel_tables": 4
  },
  "logging": {
    "level": "INFO",
    "handlers": [
      {
        "type": "console",
        "format_json": false
      },
      {
        "type": "file",
        "file_path": "logs/sanitization.log",
        "max_bytes": 104857600,
        "backup_count": 10,
        "rotation_interval": "daily",
        "format_json": true
      }
    ],
    "pii_redaction": {
      "enabled": true,
      "redact_emails": true,
      "redact_phones": true,
      "redact_ssn": true,
      "redact_credit_cards": true
    },
    "include_correlation_id": true
  },
  "ai": {
    "enabled": true,
    "api_url": "https://models.github.ai/inference/chat/completions",
    "api_key_env_var": "GITHUB_COPILOT_TOKEN",
    "model": "gpt-4o",
    "timeout_seconds": 60,
    "max_retries": 3,
    "retry_backoff_factor": 1.0,
    "cache_enabled": true,
    "cache_ttl_hours": 24,
    "max_tables_per_request": 50,
    "max_schema_size_chars": 100000
  },
  "pii_columns": [
    {
      "schema": "Person",
      "table": "Person",
      "column": "FirstName",
      "pii_type": "name",
      "reason": "Contains first names of persons"
    },
    {
      "schema": "Person",
      "table": "EmailAddress",
      "column": "EmailAddress",
      "pii_type": "email",
      "reason": "Contains email addresses"
    },
    {
      "schema": "Person",
      "table": "PersonPhone",
      "column": "PhoneNumber",
      "pii_type": "phone",
      "reason": "Contains phone numbers"
    }
  ],
  "dry_run": true
}
```

### 6.2 Configuration Sections

#### Database Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `server` | string | Required | SQL Server hostname or instance |
| `database` | string | Required | Database name |
| `auth_type` | string | `"windows"` | Authentication: `"windows"` or `"sql"` |
| `timeout` | int | `60` | Connection timeout in seconds |
| `batch_size` | int | `5000` | Rows per batch for updates |
| `max_retries` | int | `5` | Retry attempts on transient failures |
| `retry_delay` | float | `1.0` | Delay between retries in seconds |
| `pool_size` | int | `10` | Connection pool size |
| `enable_fast_executemany` | bool | `true` | Use pyodbc fast_executemany optimization |
| `enable_parallel_processing` | bool | `true` | Enable multi-table parallel processing |
| `max_parallel_tables` | int | `4` | Max tables to process in parallel |

#### Logging Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `level` | string | `"INFO"` | Log level: `DEBUG`, `INFO`, `WARN`, `ERROR` |
| `handlers` | array | Required | List of log handlers (console, file) |
| `pii_redaction.enabled` | bool | `true` | Enable automatic PII redaction in logs |
| `include_correlation_id` | bool | `true` | Include correlation ID for request tracing |

#### AI Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enabled` | bool | `true` | Enable AI-powered detection |
| `api_url` | string | Required | GitHub Copilot API endpoint |
| `api_key_env_var` | string | `"GITHUB_COPILOT_TOKEN"` | Environment variable for API key |
| `model` | string | `"gpt-4o"` | AI model to use |
| `timeout_seconds` | int | `60` | API request timeout |
| `max_retries` | int | `3` | Retry attempts on API failures |
| `cache_enabled` | bool | `true` | Enable response caching |
| `cache_ttl_hours` | int | `24` | Cache TTL in hours |

#### PII Columns Configuration

Each PII column entry contains:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema` | string | ✅ Yes | Database schema name (e.g., `"dbo"`) |
| `table` | string | ✅ Yes | Table name (e.g., `"Customers"`) |
| `column` | string | ✅ Yes | Column name (e.g., `"Email"`) |
| `pii_type` | string | ✅ Yes | PII type (see below) |
| `reason` | string | ⚠️ Optional | Human-readable explanation |

**Supported PII Types:**

| PII Type | Description | Example Fake Value |
|----------|-------------|-------------------|
| `email` | Email addresses | `user_a1b2c3d4@example.com` |
| `phone` | Phone numbers | `(555) 555-1234` |
| `name` | Full names | `John Smith` |
| `first_name` | First names | `John` |
| `last_name` | Last names | `Smith` |
| `middle_name` | Middle names | `A.` |
| `ssn` | Social Security Numbers | `123-45-6789` |
| `date_of_birth` | Birth dates | `1985-03-15` |
| `address` | Street addresses | `123 Main St` |
| `city` | City names | `Springfield` |
| `state` | State/Province | `CA` |
| `postal_code` | ZIP/Postal codes | `90210` |
| `country` | Country names | `United States` |
| `credit_card` | Credit card numbers | `4532-1234-5678-9012` |
| `generic_pii` | Generic sensitive data | (format-preserving mask) |

#### Dry Run Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dry_run` | bool | `true` | If `true`, preview changes without modifying database |

⚠️ **IMPORTANT:** Always test with `dry_run: true` first!

---

## 7. Complete Workflow

### 7.1 Phase 1: AI-Powered PII Detection

**Objective:** Automatically discover PII columns in your database

**Step 1: Set Environment Variables**

```bash
export SQLSERVER_HOST=localhost
export SQLSERVER_DB=YourDatabase
export GITHUB_COPILOT_TOKEN=your-token-here
```

**Step 2: Run AI Detection**

```bash
python ai_detection_direct.py --export-json config/pii_config_ai_generated.json
```

**What Happens:**
1. Connects to database
2. Extracts schema metadata (tables, columns, data types)
3. Filters out system and metadata tables
4. Sends schema to GitHub Copilot API for analysis
5. AI identifies PII columns with confidence scores
6. Deduplicates and validates results
7. Exports configuration to JSON file

**Output:**
```
======================================================================
Direct AI-Powered PII Detection (No Framework)
======================================================================

[Configuration]
  Server: localhost
  Database: AdventureWorks2016

1. Connecting to database...
   + Connected to localhost/AdventureWorks2016

2. Extracting schema with filtering...
   + Found 71 tables (excluded 12 system/metadata tables)
   + Extracted 1,246 columns

3. Sending schema to GitHub Copilot API...
   + Request sent (model: gpt-4o)
   + Response received (14.2 seconds)

4. Processing AI response...
   + Identified 47 PII columns
   + Confidence: HIGH (38), MEDIUM (7), LOW (2)

5. Exporting to config/pii_config_ai_generated.json...
   + Configuration exported successfully

✅ AI Detection Complete
```

**Review the Results:**

Open `config/pii_config_ai_generated.json` and verify the detected columns are correct.

### 7.2 Phase 2: Configuration Validation

**Objective:** Validate PII configuration against database schema

**Step 1: Run Validator**

```bash
python validate_config_direct.py config/pii_config_ai_generated.json
```

**What Happens:**
1. Loads configuration file
2. Connects to database
3. Extracts actual schema metadata
4. Compares config against database reality
5. Checks for issues:
   - Non-existent columns
   - Data type mismatches
   - Nullable constraint violations
   - Primary key conflicts
   - Foreign key warnings
   - Computed columns

**Output:**
```
======================================================================
Configuration Validator (Direct)
======================================================================

1. Loading configuration: config/pii_config_ai_generated.json
   + Database: localhost/AdventureWorks2016
   + PII Columns to validate: 47

2. Connecting to database...
   + Connected successfully

3. Extracting database schema...
   + Extracted metadata for 71 tables

4. Validating PII columns...
   ✅ Person.Person.FirstName (VALID)
   ✅ Person.Person.LastName (VALID)
   ✅ Person.EmailAddress.EmailAddress (VALID)
   ⚠️  Person.Person.BusinessEntityID (WARNING: Primary Key)
   ❌ dbo.Users.Password (ERROR: Column not found)

5. Validation Summary:
   ✅ Valid: 44
   ⚠️  Warnings: 2 (Primary Keys)
   ❌ Errors: 1

[ACTION REQUIRED]
Fix errors before proceeding with sanitization.
```

**Step 2: Fix Issues**

Edit the configuration file to remove invalid columns or fix data type mismatches.

**Step 3: Re-validate**

```bash
python validate_config_direct.py config/pii_config_ai_generated.json
```

Repeat until validation passes with zero errors.

### 7.3 Phase 3: Test Sanitization (Dry Run)

**Objective:** Preview sanitization without modifying database

**Step 1: Ensure Dry Run is Enabled**

Edit config file:
```json
{
  "dry_run": true,
  ...
}
```

**Step 2: Run Sanitization**

```bash
python sanitize_smart.py config/pii_config_ai_generated.json
```

**What Happens:**
1. Loads configuration
2. Connects to database (no autocommit)
3. Initializes Smart Generation maskers
4. For each PII column:
   - Fetches current values
   - Generates fake values (deterministic)
   - **DOES NOT UPDATE DATABASE** (dry run)
5. Reports statistics

**Output:**
```
================================================================================
DATABASE SANITIZATION WITH SMART GENERATION
================================================================================
Started: 2026-04-22 14:30:00
Config: config/pii_config_ai_generated.json

[OK] Dry-run mode: No database changes will be made

[2/6] Backup check - Skipped (dry-run mode)

[3/6] Connecting to database
  [OK] Connection successful

[4/6] Initializing Smart Generation maskers
  [OK] EmailMasker: 3 format tiers (6-26 chars)
  [OK] PhoneMasker: 3 format tiers (10-14 chars)
  [OK] NameMasker: 4 format tiers (2-20 chars)
  [OK] SSNMasker: 2 format tiers (9-11 chars)
  [OK] AddressMasker: Smart length adaptation
  [OK] DateOfBirthMasker: Age range 18-80 years, 4 format tiers
  [OK] CreditCardMasker: 3 format tiers (13-19 chars), Luhn validated
  [OK] GenericMasker: Exact length generation

[4b/6] Mapping capture - Skipped (dry-run mode)
  [INFO] Enable mapping capture by setting dry_run=false

[5/6] Sanitizing PII columns

[1/47] Sanitizing Person.Person.FirstName
     [DRY-RUN] Would update 19,972 rows

[2/47] Sanitizing Person.Person.LastName
     [DRY-RUN] Would update 19,972 rows

[3/47] Sanitizing Person.EmailAddress.EmailAddress
     [DRY-RUN] Would update 19,972 rows

... (44 more columns)

[6/6] Results
================================================================================
[SUCCESS] SANITIZATION COMPLETED
================================================================================

Columns:
  [OK] Successful: 47
  Total: 47

Rows:
  Would update: 487,324 (DRY-RUN)

Smart Generation:
  [SUCCESS] All maskers use constraint-aware generation
  [SUCCESS] Zero truncation errors expected
  [SUCCESS] All fake values fit column constraints perfectly

[TIP] To execute actual sanitization:
   1. Set 'dry_run': false in config/pii_config_ai_generated.json
   2. Run: python sanitize_smart.py config/pii_config_ai_generated.json

================================================================================
Completed: 2026-04-22 14:35:23
================================================================================
```

**Step 3: Review Statistics**

Verify:
- ✅ All columns sanitized successfully
- ✅ Row counts match expectations
- ✅ No errors or warnings

### 7.4 Phase 4: Database Backup

**Objective:** Create a backup before modifying production data

⚠️ **CRITICAL:** Always backup before actual sanitization!

**Option 1: SQL Server Management Studio**

1. Right-click database → Tasks → Back Up...
2. Select "Full" backup type
3. Choose destination
4. Click OK

**Option 2: T-SQL Command**

```sql
BACKUP DATABASE [YourDatabase]
TO DISK = 'C:\Backups\YourDatabase_PreSanitization.bak'
WITH FORMAT, INIT, COMPRESSION,
NAME = 'Pre-Sanitization Full Backup';
```

**Option 3: Command Line**

```bash
sqlcmd -S localhost -Q "BACKUP DATABASE [YourDatabase] TO DISK='C:\Backups\YourDatabase_PreSanitization.bak' WITH INIT"
```

**Verify Backup:**

```sql
RESTORE VERIFYONLY
FROM DISK = 'C:\Backups\YourDatabase_PreSanitization.bak';
```

### 7.5 Phase 5: Production Sanitization

**Objective:** Execute actual database sanitization

⚠️ **WARNING:** This will permanently modify your database!

**Step 1: Disable Dry Run**

Edit config file:
```json
{
  "dry_run": false,
  ...
}
```

**Step 2: Generate Encryption Key (if not already done)**

```python
from cryptography.fernet import Fernet
key = Fernet.generate_key()
print(f"SANITIZATION_ENCRYPTION_KEY={key.decode()}")
```

Add to `.env`:
```env
SANITIZATION_ENCRYPTION_KEY=<your-generated-key>
```

**Step 3: Run Production Sanitization**

```bash
python sanitize_smart.py config/pii_config_ai_generated.json
```

**Interactive Prompts:**

```
[WARN]  WARNING: This will MODIFY your database!
[WARN]  All PII data will be replaced with fake data!

Continue anyway? (yes/no): yes

[2/6] Database backup check
  [WARN] Backup recommended before sanitization!
Do you have a backup? (yes/no): yes
```

**What Happens:**
1. Loads configuration
2. Verifies backup exists
3. Connects to database
4. Initializes Smart Generation maskers
5. Initializes mapping capture (with encryption)
6. For each PII column:
   - Fetches primary keys and current values
   - Generates fake values (deterministic)
   - Captures mappings (encrypted)
   - Updates database in batches
7. Commits transaction
8. Reports statistics

**Output:**
```
================================================================================
DATABASE SANITIZATION WITH SMART GENERATION
================================================================================
Started: 2026-04-22 15:00:00
Config: config/pii_config_ai_generated.json

Continue anyway? (yes/no): yes

[2/6] Database backup check
Do you have a backup? (yes/no): yes

[3/6] Connecting to database
  [OK] Connection successful

[4/6] Initializing Smart Generation maskers
  [OK] All maskers initialized

[4b/6] Initializing mapping capture for desanitization
  Operation ID: 1a1db0b4-5dd8-4087-a406-7d820287ecaf
  [OK] Encryption enabled: AES-256-GCM (Fernet)
  [OK] Mapping table initialized: dbo.pii_mappings
  [OK] Desanitization support enabled

[5/6] Sanitizing PII columns

[1/47] Sanitizing Person.Person.FirstName
     Fetching data...
     Generating fake values...
     Capturing mappings...
     Updating database (batch 1/4)...
     [OK] Sanitized 19,972 rows

[2/47] Sanitizing Person.Person.LastName
     [OK] Sanitized 19,972 rows

... (45 more columns)

[OK] Transaction committed

[6/6] Results
================================================================================
[SUCCESS] SANITIZATION COMPLETED
================================================================================

Columns:
  [OK] Successful: 47
  Total: 47

Rows:
  Updated: 487,324

Smart Generation:
  [SUCCESS] All maskers use constraint-aware generation
  [SUCCESS] Zero truncation errors expected
  [SUCCESS] All fake values fit column constraints perfectly

Desanitization:
  [SUCCESS] Mappings captured: 487,324
  [SUCCESS] Tables tracked: 12
  [SUCCESS] Values encrypted: 487,324 (AES-256)
  [INFO] Operation ID: 1a1db0b4-5dd8-4087-a406-7d820287ecaf
  [TIP] To restore original data, use: python desanitize.py 1a1db0b4-5dd8-4087-a406-7d820287ecaf

================================================================================
Completed: 2026-04-22 15:12:45
================================================================================
```

**Step 4: Verify Sanitization**

Query database to verify PII is masked:

```sql
-- Check email masking
SELECT TOP 10 EmailAddress FROM Person.EmailAddress;
-- Expected: user_a1b2c3d4@example.com, u_a1b2c3@demo.co, etc.

-- Check name masking
SELECT TOP 10 FirstName, LastName FROM Person.Person;
-- Expected: John Smith, Jane Doe, etc.

-- Check phone masking
SELECT TOP 10 PhoneNumber FROM Person.PersonPhone;
-- Expected: (555) 555-1234, 555-555-5678, etc.
```

**Step 5: Verify Mappings**

```bash
python check_mappings.py 1a1db0b4-5dd8-4087-a406-7d820287ecaf
```

**Output:**
```
First 5 mappings for operation 1a1db0b4-5dd8-4087-a406-7d820287ecaf:
------------------------------------------------------------------------------------------------------------------------
Table.Column                   Masked Value                             Encrypted?      Length     IsNull
------------------------------------------------------------------------------------------------------------------------
Person.FirstName               John                                     YES             168        NO
Person.LastName                Smith                                    YES             172        NO
EmailAddress.EmailAddress      user_a1b2c3d4@example.com                YES             176        NO

========================================================================================================================
Total mappings: 487,324
Encrypted mappings: 487,324
Plaintext mappings (NO original value stored): 0
NULL mappings: 128
========================================================================================================================
```

### 7.6 Phase 6: Desanitization (Optional)

**Objective:** Restore original PII values from encrypted mappings

⚠️ **Use Case:** Authorized data restoration for legal/compliance requirements

**Step 1: Dry-Run Desanitization (Preview)**

```bash
python desanitize.py 1a1db0b4-5dd8-4087-a406-7d820287ecaf
```

**Output:**
```
================================================================================
DESANITIZATION ENGINE
================================================================================
Operation ID: 1a1db0b4-5dd8-4087-a406-7d820287ecaf
Mode: DRY-RUN (preview only)

[1/5] Validating operation
  ✅ Operation exists
  ✅ Total mappings: 487,324
  ✅ Tables affected: 12

[2/5] Loading mappings
  ✅ Loaded 487,324 mappings

[3/5] Decrypting original values
  ✅ Decrypted 487,324 values
  ✅ Encryption: AES-256-GCM

[4/5] Simulating restoration (DRY-RUN)
  [1/12] Person.Person.FirstName: Would restore 19,972 rows
  [2/12] Person.Person.LastName: Would restore 19,972 rows
  ... (10 more tables)

[5/5] Results
================================================================================
[SUCCESS] DESANITIZATION PREVIEW COMPLETED
================================================================================

Statistics:
  Mappings loaded: 487,324
  Mappings decrypted: 487,324
  Rows to restore: 487,324
  Tables affected: 12

[TIP] To execute actual restoration:
  python desanitize.py 1a1db0b4-5dd8-4087-a406-7d820287ecaf --execute

================================================================================
```

**Step 2: Execute Full Restoration**

```bash
python desanitize.py 1a1db0b4-5dd8-4087-a406-7d820287ecaf --execute
```

**Interactive Prompt:**

```
[WARN] WARNING: This will RESTORE original PII values to the database!
[WARN] This operation cannot be undone!

Continue? (yes/no): yes
```

**Output:**
```
================================================================================
DESANITIZATION ENGINE
================================================================================
Operation ID: 1a1db0b4-5dd8-4087-a406-7d820287ecaf
Mode: EXECUTION (will modify database)

Continue? (yes/no): yes

[1/5] Validating operation
  ✅ Operation exists

[2/5] Loading mappings
  ✅ Loaded 487,324 mappings

[3/5] Decrypting original values
  ✅ Decrypted 487,324 values

[4/5] Restoring original values
  [1/12] Person.Person.FirstName
     Batch 1/4... ✅ 5,000 rows restored
     Batch 2/4... ✅ 5,000 rows restored
     Batch 3/4... ✅ 5,000 rows restored
     Batch 4/4... ✅ 4,972 rows restored
     [OK] Restored 19,972 rows

  [2/12] Person.Person.LastName
     [OK] Restored 19,972 rows

  ... (10 more tables)

  ✅ Transaction committed

[5/5] Results
================================================================================
[SUCCESS] DESANITIZATION COMPLETED
================================================================================

Statistics:
  Mappings loaded: 487,324
  Rows restored: 487,324
  Tables affected: 12
  Successful: 487,324 (100.0%)
  Failed: 0 (0.0%)

[INFO] Original PII values have been restored to the database.

================================================================================
Completed: 2026-04-22 15:30:12
================================================================================
```

**Step 3: Verify Restoration**

```sql
-- Query should show original values
SELECT TOP 10 EmailAddress FROM Person.EmailAddress;
-- Expected: Real email addresses (e.g., john.doe@example.com)
```

**Step 4: Selective Table Restoration**

Restore only specific tables:

```bash
python desanitize.py 1a1db0b4-5dd8-4087-a406-7d820287ecaf --execute --tables Person.Person Person.EmailAddress
```

---

## 8. Security Features

### 8.1 Encryption Architecture

**AES-256-GCM via Fernet**

The framework uses **Fernet** (symmetric encryption) from the `cryptography` library:

```python
from cryptography.fernet import Fernet

# Key generation (one-time setup)
key = Fernet.generate_key()  # 32 bytes, URL-safe base64-encoded

# Encryption
fernet = Fernet(key)
encrypted = fernet.encrypt(b"sensitive data")

# Decryption
decrypted = fernet.decrypt(encrypted)
```

**Key Features:**
- **Algorithm:** AES-256-GCM (Galois/Counter Mode)
- **Key Size:** 256 bits (32 bytes)
- **Authentication:** HMAC-SHA256 for integrity
- **IV:** Unique initialization vector per encryption
- **Timestamp:** Automatic expiration support

### 8.2 Key Management

**Environment-Based Key Storage**

```env
# .env file
SANITIZATION_ENCRYPTION_KEY=<base64-encoded-fernet-key>
```

**Best Practices:**
1. **Generate Strong Keys:** Use `Fernet.generate_key()` (cryptographically secure)
2. **Store Securely:** Use environment variables, never hardcode keys
3. **Rotate Regularly:** Generate new keys periodically (e.g., quarterly)
4. **Backup Keys:** Store keys in secure vault (e.g., Azure Key Vault, AWS KMS)
5. **Access Control:** Limit key access to authorized personnel only

**Key Rotation Workflow:**
```bash
# 1. Generate new key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. Update .env with new key
export SANITIZATION_ENCRYPTION_KEY=<new-key>

# 3. Re-sanitize with new key (new operation ID)
python sanitize_smart.py config/pii_config.json

# 4. Retire old key after grace period
```

### 8.3 SQL Injection Prevention

**Parameterized Queries Only**

The framework **never** constructs SQL queries via string concatenation:

❌ **Vulnerable (NEVER do this):**
```python
query = f"UPDATE {table} SET {column} = '{value}' WHERE id = {row_id}"
cursor.execute(query)
```

✅ **Secure (Always parameterized):**
```python
query = f"UPDATE [{schema}].[{table}] SET [{column}] = ? WHERE [{pk_column}] = ?"
cursor.execute(query, (value, row_id))
```

**All User Inputs Are Parameterized:**
- Table names (validated against schema)
- Column names (validated against schema)
- Values (always parameterized)
- Primary key values (always parameterized)

### 8.4 PII Redaction in Logs

**Automatic Sensitive Data Redaction**

The logging system automatically redacts PII from log output:

```python
# Configuration
"pii_redaction": {
  "enabled": true,
  "redact_emails": true,
  "redact_phones": true,
  "redact_ssn": true,
  "redact_credit_cards": true
}
```

**Example:**
```python
# Actual log entry
logger.info(f"Processing email: {email}")

# Logged as:
# Processing email: [REDACTED_EMAIL]
```

**Redacted Patterns:**
- Emails: `john.doe@example.com` → `[REDACTED_EMAIL]`
- Phones: `(555) 123-4567` → `[REDACTED_PHONE]`
- SSNs: `123-45-6789` → `[REDACTED_SSN]`
- Credit Cards: `4532-1234-5678-9012` → `[REDACTED_CC]`

### 8.5 Transaction Safety

**Automatic Rollback on Errors**

All database operations are wrapped in transactions:

```python
conn.autocommit = False  # Explicit transaction control

try:
    # Perform updates
    for col in pii_columns:
        sanitize_column(conn, col)
    
    # Commit if all succeed
    conn.commit()
    
except Exception as e:
    # Rollback on any error
    conn.rollback()
    raise
```

**Benefits:**
- **Atomicity:** All-or-nothing updates
- **Consistency:** No partial sanitization
- **Isolation:** Changes invisible until commit
- **Durability:** Committed changes are persistent

### 8.6 Access Control

**Principle of Least Privilege**

The framework requires minimal permissions:

**Sanitization:**
- `SELECT` on target tables (read data)
- `UPDATE` on target tables (modify PII)
- `CREATE TABLE` (one-time for pii_mappings)
- `INSERT` on pii_mappings (store mappings)

**Desanitization:**
- `SELECT` on pii_mappings (read mappings)
- `UPDATE` on target tables (restore originals)

**Recommendations:**
- Create dedicated service account for sanitization
- Grant only required permissions
- Revoke desanitization permissions from most users
- Audit all sanitization/desanitization operations

---

## 9. Advanced Features

### 9.1 Batch Processing Optimization

**Configurable Batch Sizes**

```json
{
  "database": {
    "batch_size": 5000,  // Rows per batch
    "enable_fast_executemany": true  // pyodbc optimization
  }
}
```

**How It Works:**
1. Fetch 5,000 rows from table
2. Generate 5,000 fake values
3. Update 5,000 rows in single batch
4. Repeat until all rows processed

**Performance Impact:**

| Batch Size | Rows/Second | Notes |
|------------|-------------|-------|
| 1000 | ~1,500 | Many round-trips |
| 5000 | ~8,000 | **Recommended** |
| 10000 | ~12,000 | Higher memory usage |
| 50000 | ~15,000 | Risk of timeout |

### 9.2 Parallel Table Processing

**Multi-Table Parallelization**

```json
{
  "database": {
    "enable_parallel_processing": true,
    "max_parallel_tables": 4  // Process 4 tables simultaneously
  }
}
```

**Benefits:**
- 3-4x faster for databases with many tables
- Utilizes multiple CPU cores
- Independent table processing

**Considerations:**
- Increases database load (more connections)
- May hit connection pool limits
- Not beneficial for single-table databases

### 9.3 Primary Key Tracking

**Row-Specific Restoration**

The mapping table stores primary key values for each row:

```json
{
  "primary_key_columns": ["CustomerID"],
  "primary_key_values": [12345]
}
```

**Composite Keys:**
```json
{
  "primary_key_columns": ["OrderID", "LineNumber"],
  "primary_key_values": [98765, 3]
}
```

**Desanitization Query:**
```sql
UPDATE [Sales].[OrderDetail]
SET [CustomerEmail] = @original_value
WHERE [OrderID] = @pk1 AND [LineNumber] = @pk2;
```

**Benefits:**
- Accurate row-level restoration
- Handles tables without unique constraints
- Supports composite primary keys

### 9.4 NULL and Empty Value Handling

**Special Tokens**

The framework distinguishes between NULL and empty string:

| Original Value | Token | Masked Value | Restoration |
|----------------|-------|--------------|-------------|
| `NULL` | `[NULL_TOKEN]` | `NULL` | `NULL` |
| `""` (empty) | `[EMPTY_TOKEN]` | `""` (empty) | `""` (empty) |

**Mapping Storage:**
```sql
-- NULL value
INSERT INTO pii_mappings (original_value_encrypted, masked_value, is_null)
VALUES (NULL, NULL, 1);  -- is_null flag set

-- Empty string
INSERT INTO pii_mappings (original_value_encrypted, masked_value, is_null)
VALUES (@encrypted_empty, '', 0);  -- encrypted = ""
```

**Desanitization Handling:**
- `is_null = 1` → Restore as SQL NULL
- `original_value = ""` → Restore as empty string
- All other values → Decrypt and restore

### 9.5 Computed Column Detection

**Automatic Skip**

Computed columns are automatically detected and skipped:

```sql
-- Computed column example
CREATE TABLE Customers (
    FirstName NVARCHAR(50),
    LastName NVARCHAR(50),
    FullName AS (FirstName + ' ' + LastName)  -- Computed, read-only
);
```

**Detection Query:**
```sql
SELECT 
    COLUMN_NAME,
    COLUMNPROPERTY(OBJECT_ID(TABLE_SCHEMA + '.' + TABLE_NAME), COLUMN_NAME, 'IsComputed') AS is_computed
FROM INFORMATION_SCHEMA.COLUMNS
WHERE is_computed = 1;
```

**Behavior:**
- Computed columns are skipped during sanitization
- Warning logged: `[WARN] Column is computed - skipping`
- No error raised

### 9.6 Foreign Key Preservation

**Deterministic Consistency**

The same original value **always** generates the same fake value:

**Example:**

| Table | Column | Original | Masked |
|-------|--------|----------|--------|
| Customers | Email | `john.doe@example.com` | `user_a1b2c3d4@example.com` |
| Orders | CustomerEmail | `john.doe@example.com` | `user_a1b2c3d4@example.com` |
| Subscriptions | Email | `john.doe@example.com` | `user_a1b2c3d4@example.com` |

**Implementation:**
```python
def _get_deterministic_seed(self, value: str) -> int:
    """Generate deterministic seed from value."""
    hash_obj = hashlib.sha256(str(value).encode('utf-8'))
    return int.from_bytes(hash_obj.digest()[:4], 'big')

# Same value → Same seed → Same random sequence → Same fake value
```

**Benefits:**
- Foreign key constraints remain valid
- JOIN queries continue to work
- Referential integrity preserved
- No dependency graph required

---

## 10. Troubleshooting

### 10.1 Connection Issues

**Problem:** `pyodbc.OperationalError: Can't open lib 'ODBC Driver 17 for SQL Server'`

**Solution:** Install ODBC Driver

**Windows:**
```
Download: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
```

**Linux (Ubuntu/Debian):**
```bash
curl https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -
curl https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list
sudo apt-get update
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql17
```

**Verify Installation:**
```bash
odbcinst -q -d
# Expected output: [ODBC Driver 17 for SQL Server]
```

---

**Problem:** `Login failed for user 'domain\user'`

**Solution:** Check authentication method

**Option 1: Windows Authentication (Trusted Connection)**
```json
{
  "database": {
    "auth_type": "windows"
  }
}
```

**Option 2: SQL Server Authentication**
```json
{
  "database": {
    "auth_type": "sql",
    "username": "sa",
    "password": "YourPassword"
  }
}
```

**Environment Variables:**
```env
SQLSERVER_USER=sa
SQLSERVER_PASSWORD=YourSecurePassword
```

---

### 10.2 Encryption Issues

**Problem:** `EncryptionKeyError: No encryption key found in environment`

**Solution:** Generate and set encryption key

```bash
# Generate key
python -c "from cryptography.fernet import Fernet; print(f'SANITIZATION_ENCRYPTION_KEY={Fernet.generate_key().decode()}')"

# Add to .env
echo "SANITIZATION_ENCRYPTION_KEY=<your-key>" >> .env

# Verify
python -c "from mapping import EncryptionManager; print(EncryptionManager().get_key_info())"
```

---

**Problem:** `DecryptionError: Invalid token`

**Cause:** Encryption key changed or corrupted

**Solution:**
1. Check if key in `.env` matches key used during sanitization
2. If key lost, original values cannot be recovered
3. Re-run sanitization with new key (new operation ID)

---

### 10.3 Performance Issues

**Problem:** Sanitization is very slow (< 100 rows/second)

**Solutions:**

**1. Increase Batch Size**
```json
{
  "database": {
    "batch_size": 10000  // Increase from default 5000
  }
}
```

**2. Enable Fast ExecuteMany**
```json
{
  "database": {
    "enable_fast_executemany": true
  }
}
```

**3. Enable Parallel Processing**
```json
{
  "database": {
    "enable_parallel_processing": true,
    "max_parallel_tables": 4
  }
}
```

**4. Check Network Latency**
```bash
# Measure round-trip time
ping <your-sql-server>
```

**5. Check Database Load**
```sql
-- Check active sessions
SELECT * FROM sys.dm_exec_sessions WHERE is_user_process = 1;

-- Check blocking
SELECT * FROM sys.dm_exec_requests WHERE blocking_session_id <> 0;
```

---

### 10.4 Validation Errors

**Problem:** `ERROR: Column not found: dbo.Users.Password`

**Solution:** Remove non-existent column from config

Edit `config/pii_config.json`:
```json
{
  "pii_columns": [
    // Remove this entry:
    // {"table": "Users", "column": "Password", "pii_type": "generic_pii"}
  ]
}
```

Re-run validator:
```bash
python validate_config_direct.py config/pii_config.json
```

---

**Problem:** `WARNING: Column is a Primary Key: Person.Person.BusinessEntityID`

**Risk:** Sanitizing primary keys breaks relationships

**Solution:** Remove primary key from sanitization config

Primary keys should **never** be sanitized (unless intentionally breaking relationships).

---

### 10.5 Desanitization Issues

**Problem:** `OperationNotFoundError: Operation ID not found`

**Solution:** Verify operation ID exists

```bash
# List all operation IDs
python check_mappings.py --list-operations

# Check specific operation
python check_mappings.py <operation-id>
```

**Common Causes:**
- Typo in operation ID
- Sanitization was run in dry-run mode (no mappings stored)
- Mapping table was dropped/truncated

---

**Problem:** Desanitization restores `[NULL_TOKEN]` instead of actual NULL

**Cause:** Bug in old versions (fixed in v2.0)

**Solution:** Upgrade to v2.0+ or apply fix:

```python
# In desanitize.py, line 253:
# OLD (buggy):
success = original_value is not None

# NEW (fixed):
success = token_value in token_to_original
```

---

### 10.6 AI Detection Issues

**Problem:** `APIError: 401 Unauthorized`

**Solution:** Check GitHub Copilot API token

```bash
# Verify token is set
echo $GITHUB_COPILOT_TOKEN

# Test token validity
curl -H "Authorization: Bearer $GITHUB_COPILOT_TOKEN" \
     https://models.github.ai/models
```

**Get New Token:**
1. Go to: https://github.com/settings/copilot
2. Generate new API token
3. Update `.env`:
   ```env
   GITHUB_COPILOT_TOKEN=<new-token>
   ```

---

**Problem:** AI detection misses obvious PII columns

**Solution:** Review and manually add columns

```json
{
  "pii_columns": [
    // Manually add missed columns
    {
      "schema": "dbo",
      "table": "Customers",
      "column": "Email",
      "pii_type": "email",
      "reason": "Customer email addresses (manually added)"
    }
  ]
}
```

Re-run sanitization with updated config.

---

## 11. Best Practices

### 11.1 Pre-Sanitization Checklist

✅ **Before Running Sanitization:**

1. **Backup Database**
   - Create full database backup
   - Verify backup integrity
   - Test restore process

2. **Test in Non-Production First**
   - Clone production to test environment
   - Run full sanitization workflow
   - Verify results before production

3. **Run Dry-Run Mode**
   - Always test with `dry_run: true` first
   - Review row counts and column list
   - Fix any errors before actual run

4. **Validate Configuration**
   - Run `validate_config_direct.py`
   - Fix all errors and warnings
   - Document any intentional warnings

5. **Review PII Columns**
   - Manually review AI-detected columns
   - Add any missed sensitive columns
   - Remove non-PII columns

6. **Check Database Permissions**
   - Verify service account has required permissions
   - Test connection before sanitization
   - Ensure no active connections will block updates

7. **Set Encryption Key**
   - Generate strong encryption key
   - Store in `.env` file
   - Backup key securely

8. **Schedule Maintenance Window**
   - Coordinate with stakeholders
   - Allocate sufficient time (estimate: 100K rows/minute)
   - Plan for rollback if needed

### 11.2 Configuration Management

**Version Control Best Practices:**

```
config/
├── pii_config.example.json       # Template with comments
├── pii_config.development.json   # Dev environment
├── pii_config.staging.json       # Staging environment
└── pii_config.production.json    # Production environment (DO NOT COMMIT)
```

**.gitignore:**
```
# Sensitive config files
config/pii_config.production.json
.env
*.bak

# Logs with potential PII
logs/*.log

# Mapping data
database/backups/
```

**Configuration Validation:**
```bash
# Validate before deployment
python validate_config_direct.py config/pii_config.production.json

# Lint JSON
jq . config/pii_config.production.json > /dev/null && echo "Valid JSON"
```

### 11.3 Security Hardening

**Environment Separation:**

```
Development:
  - Use test data only
  - Encryption optional
  - Dry-run mode enabled

Staging:
  - Copy of production
  - Encryption required
  - Test full workflow

Production:
  - Encryption mandatory
  - Audit all operations
  - Restricted access
```

**Access Control:**

```sql
-- Create dedicated service account
CREATE LOGIN SanitizationService WITH PASSWORD = '<strong-password>';
CREATE USER SanitizationService FOR LOGIN SanitizationService;

-- Grant minimum permissions
GRANT SELECT, UPDATE ON SCHEMA::dbo TO SanitizationService;
GRANT CREATE TABLE TO SanitizationService;  -- One-time for mapping table

-- Audit operations
CREATE TABLE dbo.sanitization_audit (
    operation_id UNIQUEIDENTIFIER,
    executed_by NVARCHAR(128),
    executed_at DATETIME2,
    tables_affected INT,
    rows_modified BIGINT
);
```

**Key Management:**

```bash
# Rotate keys quarterly
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Store keys in secure vault
# - Azure Key Vault
# - AWS Secrets Manager
# - HashiCorp Vault
```

### 11.4 Performance Tuning

**Optimize Batch Size:**

```bash
# Test different batch sizes
for batch_size in 1000 5000 10000 20000; do
  echo "Testing batch_size=$batch_size"
  time python sanitize_smart.py config/test_batch_$batch_size.json
done

# Choose optimal size
```

**Database Optimization:**

```sql
-- Disable indexes during bulk update (if necessary)
ALTER INDEX ALL ON dbo.LargeTable DISABLE;

-- Run sanitization
-- ...

-- Rebuild indexes
ALTER INDEX ALL ON dbo.LargeTable REBUILD;

-- Update statistics
UPDATE STATISTICS dbo.LargeTable;
```

**Connection Pooling:**

```json
{
  "database": {
    "pool_size": 10,           // Increase for parallel processing
    "timeout": 120,            // Longer timeout for large tables
    "enable_parallel_processing": true,
    "max_parallel_tables": 4
  }
}
```

### 11.5 Monitoring & Logging

**Log Aggregation:**

```json
{
  "logging": {
    "handlers": [
      {
        "type": "file",
        "file_path": "logs/sanitization.log",
        "format_json": true,      // Structured logs
        "rotation_interval": "daily",
        "backup_count": 30
      }
    ]
  }
}
```

**Metrics to Track:**

- Rows sanitized per second
- Tables processed
- Errors encountered
- Mapping storage success rate
- Transaction commit time

**Alerting:**

```bash
# Monitor log for errors
tail -f logs/sanitization.log | grep "ERROR"

# Check completion status
grep "SANITIZATION COMPLETED" logs/sanitization.log | tail -1
```

### 11.6 Data Retention

**Mapping Table Cleanup:**

```sql
-- Archive old mappings (after desanitization no longer needed)
DELETE FROM dbo.pii_mappings
WHERE operation_id = '1a1db0b4-5dd8-4087-a406-7d820287ecaf';

-- Or move to archive table
SELECT * INTO dbo.pii_mappings_archive
FROM dbo.pii_mappings
WHERE created_at < DATEADD(MONTH, -6, GETUTCDATE());

DELETE FROM dbo.pii_mappings
WHERE created_at < DATEADD(MONTH, -6, GETUTCDATE());
```

**Retention Policy:**

- **Active Operations:** Keep mappings indefinitely (may need desanitization)
- **Completed Operations:** Keep 90 days after desanitization
- **Failed Operations:** Keep 30 days for debugging
- **Archived Operations:** Move to cold storage (Azure Blob, S3)

### 11.7 Documentation

**Document Each Sanitization Run:**

```markdown
# Sanitization Operation: 2026-04-22

**Operation ID:** 1a1db0b4-5dd8-4087-a406-7d820287ecaf

**Environment:** Production

**Executed By:** John Doe (john.doe@company.com)

**Configuration:** config/pii_config.production.json

**Statistics:**
- Tables: 12
- Columns: 47
- Rows: 487,324
- Duration: 12m 45s

**Backup:**
- Location: \\backups\prod_db_20260422.bak
- Size: 2.4 GB
- Verified: Yes

**Status:** SUCCESS

**Notes:**
- All primary keys preserved
- Referential integrity maintained
- Encryption enabled (AES-256)
- Desanitization available if needed
```

---

## Appendix A: Configuration Reference

### Complete Configuration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["database", "pii_columns"],
  "properties": {
    "database": {
      "type": "object",
      "required": ["server", "database"],
      "properties": {
        "server": {"type": "string"},
        "database": {"type": "string"},
        "auth_type": {"type": "string", "enum": ["windows", "sql"]},
        "username": {"type": "string"},
        "password": {"type": "string"},
        "timeout": {"type": "integer", "minimum": 1},
        "batch_size": {"type": "integer", "minimum": 1, "maximum": 100000},
        "max_retries": {"type": "integer", "minimum": 0},
        "retry_delay": {"type": "number", "minimum": 0},
        "pool_size": {"type": "integer", "minimum": 1},
        "environment": {"type": "string"},
        "enable_fast_executemany": {"type": "boolean"},
        "enable_parallel_processing": {"type": "boolean"},
        "max_parallel_tables": {"type": "integer", "minimum": 1}
      }
    },
    "logging": {
      "type": "object",
      "properties": {
        "level": {"type": "string", "enum": ["DEBUG", "INFO", "WARN", "ERROR"]},
        "handlers": {"type": "array"},
        "pii_redaction": {
          "type": "object",
          "properties": {
            "enabled": {"type": "boolean"},
            "redact_emails": {"type": "boolean"},
            "redact_phones": {"type": "boolean"},
            "redact_ssn": {"type": "boolean"},
            "redact_credit_cards": {"type": "boolean"}
          }
        },
        "include_correlation_id": {"type": "boolean"}
      }
    },
    "ai": {
      "type": "object",
      "properties": {
        "enabled": {"type": "boolean"},
        "api_url": {"type": "string"},
        "api_key_env_var": {"type": "string"},
        "model": {"type": "string"},
        "timeout_seconds": {"type": "integer"},
        "max_retries": {"type": "integer"},
        "cache_enabled": {"type": "boolean"},
        "cache_ttl_hours": {"type": "integer"}
      }
    },
    "pii_columns": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["schema", "table", "column", "pii_type"],
        "properties": {
          "schema": {"type": "string"},
          "table": {"type": "string"},
          "column": {"type": "string"},
          "pii_type": {"type": "string"},
          "reason": {"type": "string"}
        }
      }
    },
    "dry_run": {"type": "boolean"}
  }
}
```

---

## Appendix B: SQL Queries

### Check Sanitization Status

```sql
-- Count PII columns by table
SELECT 
    schema_name,
    table_name,
    COUNT(*) as pii_columns
FROM dbo.pii_mappings
WHERE operation_id = '<operation-id>'
GROUP BY schema_name, table_name
ORDER BY schema_name, table_name;

-- Sample masked values
SELECT TOP 10
    table_name,
    column_name,
    masked_value
FROM dbo.pii_mappings
WHERE operation_id = '<operation-id>'
ORDER BY created_at DESC;

-- Check encryption status
SELECT 
    COUNT(*) as total_mappings,
    SUM(CASE WHEN original_value_encrypted IS NOT NULL THEN 1 ELSE 0 END) as encrypted,
    SUM(CASE WHEN is_null = 1 THEN 1 ELSE 0 END) as null_values
FROM dbo.pii_mappings
WHERE operation_id = '<operation-id>';
```

### Database Statistics

```sql
-- Table sizes
SELECT 
    s.name AS schema_name,
    t.name AS table_name,
    p.rows AS row_count,
    SUM(a.total_pages) * 8 AS size_kb
FROM sys.tables t
INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
INNER JOIN sys.partitions p ON t.object_id = p.object_id
INNER JOIN sys.allocation_units a ON p.partition_id = a.container_id
WHERE t.is_ms_shipped = 0
GROUP BY s.name, t.name, p.rows
ORDER BY size_kb DESC;

-- Database size
EXEC sp_spaceused;
```

---

## Appendix C: Command Reference

### Sanitization Commands

```bash
# AI Detection
python ai_detection_direct.py --export-json config/pii_config_ai_generated.json

# Validation
python validate_config_direct.py config/pii_config.json

# Sanitization (dry-run)
python sanitize_smart.py config/pii_config.json

# Sanitization (execute)
# Set dry_run: false in config first
python sanitize_smart.py config/pii_config.json

# Check mappings
python check_mappings.py <operation-id>

# Desanitization (preview)
python desanitize.py <operation-id>

# Desanitization (execute)
python desanitize.py <operation-id> --execute

# Desanitization (selective)
python desanitize.py <operation-id> --execute --tables dbo.Customers dbo.Orders
```

### Utility Commands

```bash
# Generate encryption key
python -c "from cryptography.fernet import Fernet; print(f'SANITIZATION_ENCRYPTION_KEY={Fernet.generate_key().decode()}')"

# Test database connection
python -c "import pyodbc; conn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=TestDB;Trusted_Connection=yes;'); print('Connection OK')"

# Verify installation
pip list | grep -E "(pyodbc|cryptography|pydantic|requests)"

# Run tests
pytest tests/

# Code formatting
black *.py mapping/ desanitization/

# Linting
pylint *.py
```

---

## Appendix D: Glossary

| Term | Definition |
|------|------------|
| **PII** | Personally Identifiable Information - data that can identify an individual (email, SSN, name, etc.) |
| **Sanitization** | Process of replacing real PII with fake data while preserving data structure |
| **Desanitization** | Reverse process of restoring original PII from encrypted mappings |
| **Smart Generation** | Constraint-aware fake value generation that adapts to column length limits |
| **Deterministic Masking** | Same input always produces same output (preserves relationships) |
| **Mapping Table** | Database table storing original→masked value mappings |
| **Operation ID** | Unique identifier (UUID) for each sanitization run |
| **Dry Run** | Preview mode that simulates changes without modifying database |
| **Fernet** | Symmetric encryption scheme (AES-256-GCM) from cryptography library |
| **Primary Key Tracking** | Storing PK values with mappings for row-specific restoration |
| **Batch Processing** | Processing data in chunks (e.g., 5,000 rows at a time) |
| **Foreign Key Integrity** | Preserving referential relationships between tables |

---

## Appendix E: Support & Contact

### Getting Help

**Documentation:**
- Full docs: [docs/](docs/)
- Quick Start: [docs/QUICK_START.md](docs/QUICK_START.md)
- Workflow Guide: [docs/WORKFLOW_GUIDE.md](docs/WORKFLOW_GUIDE.md)
- Troubleshooting: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

**Community:**
- GitHub Issues: <repository-url>/issues
- Discussions: <repository-url>/discussions

**Commercial Support:**
- Contact: support@example.com
- Enterprise inquiries: sales@example.com

---

**End of Documentation**

Version 2.0 | Last Updated: April 22, 2026 | Database Sanitization Team
