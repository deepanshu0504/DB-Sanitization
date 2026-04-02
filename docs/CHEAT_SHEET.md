# Database Sanitization - Cheat Sheet

## Essential Commands

```bash
# 1. AI Detection
python ai_detection_direct.py

# 2. Validation
python validate_config_direct.py config/pii_config_ai_generated.json

# 3. Sanitization (Dry-Run First - Default)
python sanitize_smart.py config/pii_config_ai_generated.json

# 4. Edit config: Set "dry_run": false
# Then run again to actually update database
python sanitize_smart.py config/pii_config_ai_generated.json
```

---

## Environment Variables (.env)

```bash
# Required
SQLSERVER_HOST=localhost
SQLSERVER_DB=YourDatabase
GITHUB_COPILOT_TOKEN=ghp_your_token_here

# Optional (SQL Server auth)
SQLSERVER_USERNAME=sa
SQLSERVER_PASSWORD=YourPassword123

# Optional (overrides)
TOKEN_MAPPING_TABLE=token_mappings  # Not used in current version
AUDIT_LOG_TABLE=sanitization_audit_log  # Not used in current version
BATCH_SIZE=5000
```

---

## Configuration Template

```json
{
  "database": {
    "server": "localhost",
    "database": "TestDB"
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
  "dry_run": true,
  "validate_before": true,
  "validate_after": true
}
```

---

## PII Types

| Type | Example | Notes |
|------|---------|-------|
| `email` | `user_a1b2c3d4@example.com` | 3 format tiers (6-26 chars) |
| `phone` | `(555) 555-5555` | 3 format tiers (10-14 chars) |
| `ssn` | `123-45-6789` | 2 format tiers (9-11 chars) |
| `name` | `John Smith` | Auto-detects first/middle/last/full |
| `address` | `123 Main St` | Auto-detects line/city/state/postal/country |
| `credit_card` | `4532-1234-5678-9010` | Luhn validated (13-19 chars) |
| `date_of_birth` | `1985-07-15` | Age 18-80, 4 format tiers |
| `generic` | Deterministic random | Preserves format |

---

## SQL Queries

### Verification

```sql
-- Check masked data
SELECT TOP 10 * FROM dbo.Customers;

-- Verify deterministic masking (same original → same masked)
SELECT Email, COUNT(*) as DuplicateCount
FROM dbo.Customers
GROUP BY Email
HAVING COUNT(*) > 1
ORDER BY DuplicateCount DESC;

-- Check NULL preservation
SELECT 
    COUNT(*) as TotalRows,
    COUNT(Email) as NonNullEmails,
    SUM(CASE WHEN Email IS NULL THEN 1 ELSE 0 END) as NullEmails
FROM dbo.Customers;

-- Check FK integrity
SELECT o.OrderID, o.CustomerID, c.CustomerID
FROM dbo.Orders o
LEFT JOIN dbo.Customers c ON o.CustomerID = c.CustomerID
WHERE c.CustomerID IS NULL;  -- Should return 0

-- Audit log
SELECT operation, table_name, column_name, rows_affected, timestamp
FROM sanitization_audit_log ORDER BY timestamp DESC;
```

### Database Schema

```sql
-- List all databases
SELECT name FROM sys.databases;

-- List all tables
SELECT TABLE_SCHEMA, TABLE_NAME 
FROM INFORMATION_SCHEMA.TABLES 
WHERE TABLE_TYPE = 'BASE TABLE';

-- Column info
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS 
WHERE TABLE_NAME = 'Customers';

-- Primary keys
SELECT ku.TABLE_NAME, ku.COLUMN_NAME
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
  ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY';

-- Foreign keys
SELECT 
    fk.name AS FK_Name,
    tp.name AS Parent_Table,
    cp.name AS Parent_Column,
    tr.name AS Referenced_Table,
    cr.name AS Referenced_Column
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
JOIN sys.tables tp ON fkc.parent_object_id = tp.object_id
JOIN sys.columns cp ON fkc.parent_object_id = cp.object_id AND fkc.parent_column_id = cp.column_id
JOIN sys.tables tr ON fkc.referenced_object_id = tr.object_id
JOIN sys.columns cr ON fkc.referenced_object_id = cr.object_id AND fkc.referenced_column_id = cr.column_id;
```

### Backup & Restore

```sql
-- Backup database
BACKUP DATABASE TestDB 
TO DISK = 'C:\Backups\TestDB_PreSanitization.bak';

-- Restore database
RESTORE DATABASE TestDB_Copy 
FROM DISK = 'C:\Backups\TestDB_PreSanitization.bak';

-- ⚠️ NOTE: No built-in detokenization/undo capability
-- Sanitization is irreversible without backup
```

---

## Installation

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Verify ODBC Driver
odbcinst -j

# Test connection
python -c "import pyodbc; print('ODBC OK')"

# Test environment
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('DB:', os.getenv('SQLSERVER_DB'))"
```

---

## Troubleshooting

```bash
# Check Python version
python --version  # Must be 3.10+

# Reinstall dependencies
pip install --upgrade -r requirements.txt

# Clear cache
rm -rf .copilot_cache/  # Linux/macOS
rmdir /s .copilot_cache  # Windows

# View logs
tail -n 100 sanitization.log  # Linux/macOS
Get-Content sanitization.log -Tail 100  # PowerShell

# Search logs for errors
grep -i "error" sanitization.log  # Linux/macOS
Select-String -Path sanitization.log -Pattern "error"  # PowerShell
```

---

## Performance Tuning

```bash
# Increase batch size (in .env)
BATCH_SIZE=50000

# Create indexes (before sanitization)
CREATE INDEX IX_Customers_Email ON Customers(Email);
CREATE INDEX IX_TokenMappings_Hash ON token_mappings(original_hash);

# Monitor SQL Server
SELECT * FROM sys.dm_exec_sessions WHERE is_user_process = 1;
SELECT * FROM sys.dm_exec_requests WHERE status = 'running';
```

---

## Security

```sql
-- Restrict mapping table access
REVOKE SELECT ON token_mappings FROM PUBLIC;
GRANT SELECT ON token_mappings TO SanitizationAdmins;

-- Enable TDE (Transparent Data Encryption)
CREATE DATABASE ENCRYPTION KEY
WITH ALGORITHM = AES_256
ENCRYPTION BY SERVER CERTIFICATE MyCertificate;

ALTER DATABASE TestDB SET ENCRYPTION ON;

-- Check encryption status
SELECT DB_NAME(database_id), encryption_state 
FROM sys.dm_database_encryption_keys;
```

---

## Quick Diagnostics

```python
# Test database connection
import pyodbc
conn_str = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=master;Trusted_Connection=yes"
conn = pyodbc.connect(conn_str, timeout=5)
print("✓ Database connection OK")

# Test API key
from dotenv import load_dotenv
import os
load_dotenv()
api_key = os.getenv("GITHUB_COPILOT_TOKEN")
print(f"✓ API key: {api_key[:10]}..." if api_key else "✗ No API key found")

# Test configuration loading
import json
with open('config/pii_config_ai_generated.json') as f:
    config = json.load(f)
print(f"✓ Config loaded: {len(config.get('pii_columns', []))} PII columns")
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success (may have warnings) |
| `1` | Validation errors / Failures |
| `2` | Configuration errors |
| `3` | Database connection errors |

---

## File Locations

```
DB-Sanitization/
├── ai_detection_direct.py          # Step 1
├── validate_config_direct.py       # Step 2
├── sanitize_smart.py               # Step 3
├── detokenize.py                   # Step 4 (optional)
├── .env                            # Your credentials
├── config/
│   ├── pii_config_ai_generated.json    # AI output
│   └── pii_config_production.json      # Final config
└── sanitization.log                # Logs
```

---

## Documentation Links

- [QUICK_START.md](QUICK_START.md) - 15-minute setup guide
- [WORKFLOW_GUIDE.md](WORKFLOW_GUIDE.md) - Complete documentation
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Detailed FAQ
- [README.md](../README.md) - Project overview

---

**Last Updated**: April 2, 2026
