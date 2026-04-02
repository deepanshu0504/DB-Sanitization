# 🚀 Quick Start Guide - Database Sanitization

## 30-Second Overview

**What**: AI-powered database sanitization framework that masks PII in SQL Server databases  
**How**: Detect → Validate → Sanitize → Verify  
**Why**: Compliance, security, and safe data sharing

---

## Prerequisites Checklist

- [ ] Python 3.10+
- [ ] SQL Server 2016+ with ODBC Driver 17
- [ ] GitHub Copilot API access
- [ ] Database credentials with SELECT/UPDATE permissions

---

## Installation (5 minutes)

```bash
# 1. Clone and navigate
cd DB-Sanitization

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
# Create .env file with:
SQLSERVER_HOST=localhost
SQLSERVER_DB=YourDatabase
GITHUB_COPILOT_TOKEN=ghp_your_token_here
```

---

## Complete Workflow (3 Steps + Optional Config Edit)

### Step 1: AI Detection (2-5 minutes)
```bash
python ai_detection_direct.py
```
**Output**: `config/pii_config_ai_generated.json` (with `dry_run: true`)

### Step 2: Validation (30 seconds)
```bash
python validate_config_direct.py config/pii_config_ai_generated.json
```
**Checks**: Column exists, data types, FK/PK warnings

### Step 3: Configure Dry Run (CRITICAL)
**Edit config file and set `"dry_run": false` to actually update database**
```json
{
  "database": {...},
  "pii_columns": [...],
  "dry_run": false  // ← Change this from true to false
}
```

### Step 4: Sanitization (varies by database size)
```bash
# First run in dry-run mode (safe)
python sanitize_smart.py config/pii_config_ai_generated.json

# Then set dry_run: false and run again to actually update
python sanitize_smart.py config/pii_config_ai_generated.json
```
**Result**: Masked data (in-place updates, irreversible)

### Step 5: Verification (manual)
```sql
-- Check masked data
SELECT TOP 10 * FROM YourTable;

-- Verify deterministic masking (same original → same masked)
SELECT Email, COUNT(*) as Count
FROM Customers
GROUP BY Email
HAVING COUNT(*) > 1;
```

---

## Essential Commands

| Task | Command |
|------|---------|
| **Detect PII** | `python ai_detection_direct.py` |
| **Validate Config** | `python validate_config_direct.py <config_file>` |
| **Sanitize** | `python sanitize_smart.py <config_file>` |
| **Test Connection** | `python -c "import pyodbc; print('OK')"` |
| **Check Env Vars** | `python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('SQLSERVER_DB'))"` |

---

## Configuration Template

**config/pii_config_production.json:**
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
  ]
}
```

---

## Supported PII Types

| Type | Example Output | Notes |
|------|----------------|-------|
| `email` | `user_a1b2c3d4@example.com` | 3 format tiers (6-26 chars) |
| `phone` | `(555) 555-5555` | 3 format tiers (10-14 chars) |
| `ssn` | `123-45-6789` | 2 format tiers (9-11 chars) |
| `name` | `John Smith` or `Michael` | Auto-detects first/middle/last/full |
| `address` | `123 Main St` or `Springfield` | Auto-detects line/city/state/postal/country |
| `credit_card` | `4532-1234-5678-9010` | Luhn validated, test BINs (13-19 chars) |
| `date_of_birth` | `1985-07-15` | Age range 18-80 years, 4 formats |
| `generic` | Deterministic random | Preserves format (numeric/alpha/mixed) |

---

## Common Issues & Fixes

### ❌ Database Connection Failed
```bash
# Test ODBC driver installed
odbcinst -j

# Verify .env file loaded
echo $SQLSERVER_HOST
```

### ❌ API 401 Unauthorized
```bash
# Check GitHub token
echo $GITHUB_COPILOT_TOKEN

# Regenerate at: https://github.com/settings/tokens
```

### ❌ Validation Errors
```bash
# Re-run detection for fresh schema
python ai_detection_direct.py

# Manually remove invalid columns from config
```

### ❌ Import Errors
```bash
# Reinstall dependencies
pip install --upgrade -r requirements.txt
```

---

## Safety Checklist

**⚠️ CRITICAL: Sanitization is IRREVERSIBLE – Original data is permanently replaced**

Before sanitization:
- [ ] **BACKUP DATABASE** (critical! No undo without backup)
  ```sql
  BACKUP DATABASE TestDB TO DISK = 'C:\Backups\PreSanitization.bak';
  ```
- [ ] Test on database copy first (highly recommended)
- [ ] Review AI-detected columns manually
- [ ] Run validation (Step 2)
- [ ] Run with `dry_run: true` first (default)
- [ ] Verify dry-run output before setting `dry_run: false`
- [ ] Schedule during maintenance window

After sanitization:
- [ ] Verify no real PII remains
- [ ] Check deterministic masking (same value → same mask)
- [ ] Test foreign key relationships still work
- [ ] Verify NULL values preserved where appropriate
- [ ] Test application functionality with masked data

---

## File Structure

```
DB-Sanitization/
├── ai_detection_direct.py          # Step 1: AI PII detection
├── validate_config_direct.py       # Step 2: Config validation
├── sanitize_smart.py               # Step 3: Smart sanitization
├── requirements.txt                # Dependencies
├── .env                            # Your credentials (create this)
├── config/
│   ├── pii_config.example.json    # Template
│   ├── pii_config_ai_generated.json  # AI output
│   └── pii_config_production.json # Your final config
└── scripts/
    ├── setup_test_db.sql          # Test database
    └── teardown_test_db.sql       # Cleanup
```

---

## Next Steps

1. ✅ Complete installation
2. ✅ Run Step 1 (AI Detection)
3. ✅ Run Step 2 (Validation)
4. ✅ Review and edit configuration if needed
5. ✅ Run Step 4 with `dry_run: true` (test mode)
6. ✅ Review dry-run output
7. ✅ Set `dry_run: false` and run again (actual sanitization)
8. ✅ Verify results
9. 📖 Read [WORKFLOW_GUIDE.md](WORKFLOW_GUIDE.md) for detailed documentation

---

**Need Help?**  
- 📖 Full documentation: [WORKFLOW_GUIDE.md](WORKFLOW_GUIDE.md)  
- 📋 Requirements: [Requirement/requirement.md](Requirement/requirement.md)  
- 📝 User stories: [USER_STORIES.md](USER_STORIES.md)  
- ⚙️ Edge cases: [CriticalRules/CriticalRulesAndEdgeCases.md](CriticalRules/CriticalRulesAndEdgeCases.md)

---

**Last Updated**: April 2, 2026  
**Estimated Time to First Sanitization**: 15-30 minutes
