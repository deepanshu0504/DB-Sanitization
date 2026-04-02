# Troubleshooting FAQ - Database Sanitization

## 🔍 Common Issues and Solutions

### Database Connection Issues

<details>
<summary><b>❌ Error: ODBC Driver not found</b></summary>

**Full Error:**
```
pyodbc.Error: ('01000', "[01000] [unixODBC][Driver Manager]Can't open lib 'ODBC Driver 17 for SQL Server'")
```

**Solution:**

**Windows:**
```bash
# Download and install ODBC Driver 17
# https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

# Verify installation
odbcinst -j
```

**Linux (Ubuntu/Debian):**
```bash
curl https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -
curl https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list
sudo apt-get update
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql17
```

**macOS:**
```bash
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew update
brew install msodbcsql17
```
</details>

<details>
<summary><b>❌ Error: Login failed for user / Connection timeout</b></summary>

**Full Error:**
```
pyodbc.Error: ('28000', "[28000] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]Login failed for user 'sa'.")
```

**Solutions:**

1. **Check SQL Server is running:**
   ```bash
   # Windows
   # Open services.msc
   # Look for "SQL Server (MSSQLSERVER)" - should be "Running"
   
   # Linux
   sudo systemctl status mssql-server
   ```

2. **Verify credentials in .env file:**
   ```bash
   SQLSERVER_HOST=localhost
   SQLSERVER_DB=TestDatabase
   # For SQL Server auth:
   SQLSERVER_USERNAME=sa
   SQLSERVER_PASSWORD=YourPassword123
   ```

3. **Test connection manually:**
   ```python
   import pyodbc
   conn_str = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=master;Trusted_Connection=yes"
   conn = pyodbc.connect(conn_str, timeout=5)
   print("Connection successful!")
   ```

4. **Check firewall:**
   - Windows: Allow TCP port 1433 through Windows Firewall
   - SQL Server Configuration Manager: Enable TCP/IP protocol
</details>

<details>
<summary><b>❌ Error: Database does not exist</b></summary>

**Full Error:**
```
pyodbc.ProgrammingError: ('42000', "[42000] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]Cannot open database \"TestDB\" requested by the login.")
```

**Solutions:**

1. **Verify database name:**
   ```sql
   -- Connect to master database
   USE master;
   GO
   
   -- List all databases
   SELECT name FROM sys.databases;
   ```

2. **Update .env file with correct database name:**
   ```bash
   SQLSERVER_DB=ActualDatabaseName
   ```

3. **Create test database if needed:**
   ```sql
   CREATE DATABASE TestDatabase;
   ```
</details>

---

### GitHub Copilot API Issues

<details>
<summary><b>❌ Error: 401 Unauthorized / No API key found</b></summary>

**Full Error:**
```
No API key found in environment
```
or
```
Error 401: Unauthorized
```

**Solutions:**

1. **Check environment variable is set:**
   ```bash
   # Windows
   echo %GITHUB_COPILOT_TOKEN%
   
   # Linux/macOS
   echo $GITHUB_COPILOT_TOKEN
   ```

2. **Verify .env file exists and is loaded:**
   ```bash
   # Check file exists
   ls -la .env
   
   # Test loading
   python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('Token:', os.getenv('GITHUB_COPILOT_TOKEN')[:10] + '...')"
   ```

3. **Generate new GitHub token:**
   - Go to https://github.com/settings/tokens
   - Click "Generate new token (classic)"
   - Select scopes: `copilot` (required)
   - Copy token and add to .env file

4. **Verify Copilot subscription is active:**
   - Go to https://github.com/settings/copilot
   - Ensure subscription is active
   - Business/Enterprise users: Check organization settings
</details>

<details>
<summary><b>❌ Error: Rate limit exceeded</b></summary>

**Full Error:**
```
Error 429: Too Many Requests
```

**Solutions:**

1. **Wait and retry:**
   - GitHub API has rate limits
   - Wait 60 seconds and retry detection

2. **Reduce batch size:**
   ```python
   # In ai_detection_direct.py
   # Process fewer tables at once
   ```

3. **Use caching:**
   - Framework automatically caches API responses
   - Re-running detection uses cached results
   - Clear cache if needed: Delete `.copilot_cache/` folder
</details>

---

### Configuration Validation Errors

<details>
<summary><b>❌ Error: Column does not exist in database</b></summary>

**Full Error (from validate_config_direct.py):**
```
✗ dbo.Users.SocialSecurityNumber
  ERROR: Column does not exist in database
```

**Solutions:**

1. **Re-run AI detection:**
   ```bash
   # Schema may have changed since last detection
   python ai_detection_direct.py
   ```

2. **Manually remove invalid column from config:**
   ```json
   // Remove this entry from pii_config_*.json
   {
     "schema": "dbo",
     "table": "Users",
     "column": "SocialSecurityNumber",  // <- Remove this column
     "pii_type": "ssn",
     "nullable": false
   }
   ```

3. **Check for case sensitivity:**
   ```sql
   -- SQL Server column names are case-insensitive
   SELECT COLUMN_NAME 
   FROM INFORMATION_SCHEMA.COLUMNS 
   WHERE TABLE_NAME = 'Users';
   ```
</details>

<details>
<summary><b>⚠ Warning: Primary key column detected</b></summary>

**Warning:**
```
⚠ dbo.Customers.CustomerID
  WARNING: Primary key column - sanitizing may break references
```

**Solutions:**

1. **Remove PK from sanitization config:**
   - Primary keys should generally NOT be sanitized
   - Can break foreign key relationships
   - Use surrogate keys instead if PII

2. **If PK must be sanitized:**
   - Use deterministic masking (enabled by default)
   - Sanitize BEFORE any child tables
   - Verify FK integrity after sanitization

3. **Alternative approach:**
   - Create new surrogate PK (non-PII)
   - Sanitize old PK column
   - Migrate references to new PK
</details>

<details>
<summary><b>⚠ Warning: Foreign key column detected</b></summary>

**Warning:**
```
⚠ dbo.Orders.CustomerID
  WARNING: Foreign key column - ensure referential integrity
```

**Solutions:**

1. **Ensure deterministic masking:**
   - `sanitize_smart.py` uses deterministic hashing by default
   - Same input value → same output value
   - FK relationships preserved automatically

2. **Verify parent table sanitized first:**
   - Sanitize `Customers.CustomerID` before `Orders.CustomerID`
   - Both must use same masking strategy

3. **Test FK integrity after sanitization:**
   ```sql
   -- Check for orphaned records
   SELECT COUNT(*) 
   FROM Orders o
   LEFT JOIN Customers c ON o.CustomerID = c.CustomerID
   WHERE c.CustomerID IS NULL;
   
   -- Should return 0
   ```
</details>

---

### Sanitization Issues

<details>
<summary><b>❌ Error: Database not being updated (still shows original data)</b></summary>

**Problem:**
You ran `sanitize_smart.py` but the database still contains original data.

**Cause:**
Default configuration has `"dry_run": true` for safety.

**Solutions:**

1. **Edit config file and set dry_run to false:**
   ```json
   {
     "database": {...},
     "pii_columns": [...],
     "dry_run": false  // ← Change this from true to false
   }
   ```

2. **Run sanitization again:**
   ```bash
   python sanitize_smart.py config/pii_config_ai_generated.json
   ```

3. **Verify the prompts:**
   - Script will ask for backup confirmation
   - Type "yes" to proceed with actual updates

4. **Check output:**
   ```
   [OK] Dry-run mode: No database changes will be made  # ← This means dry_run is still true
   
   OR
   
   [WARN] WARNING: This will MODIFY your database!  # ← This means dry_run is false
   ```
</details>

<details>
<summary><b>❌ Error: Data truncation / String or binary data would be truncated</b></summary>

**Full Error:**
```
pyodbc.DataError: ('22001', '[22001] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]String or binary data would be truncated.')
```

**Solutions:**

1. **Use Smart Generation (sanitize_smart.py):**
   - Smart maskers automatically respect `max_length` constraints
   - No truncation warnings or errors
   - All fake values guaranteed to fit

2. **Verify you're using sanitize_smart.py:**
   ```bash
   # Correct (with Smart Generation)
   python sanitize_smart.py config/pii_config_production.json
   
   # Legacy (may truncate)
   # python sanitize_basic.py config/pii_config_production.json
   ```

3. **Check column constraints in config:**
   ```json
   {
     "column": "Email",
     "pii_type": "email",
     "max_length": 100  // Smart masker uses this
   }
   ```
</details>

<details>
<summary><b>❌ Error: NULL value in non-nullable column</b></summary>

**Full Error:**
```
pyodbc.IntegrityError: ('23000', '[23000] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]Cannot insert the value NULL into column 'Email'')
```

**Solutions:**

1. **Verify nullable flag in config:**
   ```json
   {
     "column": "Email",
     "pii_type": "email",
     "nullable": false  // Must match database constraint
   }
   ```

2. **Check database schema:**
   ```sql
   SELECT COLUMN_NAME, IS_NULLABLE 
   FROM INFORMATION_SCHEMA.COLUMNS 
   WHERE TABLE_NAME = 'Customers' AND COLUMN_NAME = 'Email';
   ```

3. **Update config to match database:**
   - Re-run `ai_detection_direct.py` to get accurate nullable flags
   - Or manually edit config JSON
</details>

<details>
<summary><b>❌ Error: Foreign key constraint violation</b></summary>

**Full Error:**
```
pyodbc.IntegrityError: ('23000', '[23000] The UPDATE statement conflicted with the FOREIGN KEY constraint "FK_Orders_Customers"')
```

**Solutions:**

1. **Sanitize parent table first:**
   ```bash
   # Correct order
   # 1. Sanitize Customers.CustomerID
   # 2. Sanitize Orders.CustomerID (references Customers)
   ```

2. **Use deterministic masking:**
   - Enabled by default in `sanitize_smart.py`
   - Same original value → same masked value
   - FK relationships preserved

3. **Verify same PII type for FK columns:**
   ```json
   // Parent
   {"table": "Customers", "column": "CustomerID", "pii_type": "generic"}
   
   // Child (must use SAME pii_type)
   {"table": "Orders", "column": "CustomerID", "pii_type": "generic"}
   ```

4. **Disable FK constraints temporarily (last resort):**
   ```sql
   -- Disable constraints
   ALTER TABLE Orders NOCHECK CONSTRAINT FK_Orders_Customers;
   
   -- Run sanitization
   
   -- Re-enable constraints
   ALTER TABLE Orders CHECK CONSTRAINT FK_Orders_Customers;
   ```
</details>

---

### Import and Module Errors

<details>
<summary><b>❌ Error: ModuleNotFoundError: No module named 'pyodbc'</b></summary>

**Full Error:**
```
ModuleNotFoundError: No module named 'pyodbc'
```

**Solutions:**

1. **Verify virtual environment is activated:**
   ```bash
   # Windows
   venv\Scripts\activate
   
   # Linux/macOS
   source venv/bin/activate
   
   # Check (should show venv path)
   which python
   ```

2. **Reinstall dependencies:**
   ```bash
   pip install --upgrade -r requirements.txt
   ```

3. **Check Python version:**
   ```bash
   python --version  # Should be 3.10+
   ```
</details>

<details>
<summary><b>❌ Error: ImportError: DLL load failed (Windows)</b></summary>

**Full Error:**
```
ImportError: DLL load failed while importing _odbc: The specified module could not be found.
```

**Solutions:**

1. **Install Visual C++ Redistributable:**
   - Download from: https://aka.ms/vs/17/release/vc_redist.x64.exe
   - Install and restart

2. **Reinstall pyodbc:**
   ```bash
   pip uninstall pyodbc
   pip install pyodbc --no-cache-dir
   ```

3. **Verify ODBC Driver installed:**
   ```bash
   odbcinst -j
   ```
</details>

---

### Performance Issues

<details>
<summary><b>⚠ Sanitization is too slow</b></summary>

**Symptoms:**
- Processing takes hours for large database
- High CPU/memory usage

**Solutions:**

1. **Increase batch size:**
   ```bash
   # Set in .env file
   BATCH_SIZE=50000  # Default is 10000
   ```

2. **Run during off-peak hours:**
   - Reduces contention with production workload

3. **Create indexes on sanitized columns:**
   ```sql
   -- Before sanitization
   CREATE INDEX IX_Customers_Email ON Customers(Email);
   ```

4. **Monitor SQL Server resources:**
   ```sql
   -- Check current connections and activity
   SELECT * FROM sys.dm_exec_sessions WHERE is_user_process = 1;
   
   -- Check long-running queries
   SELECT * FROM sys.dm_exec_requests WHERE status = 'running';
   ```

5. **Process tables in parallel (manual):**
   ```bash
   # Split config into multiple files
   # Run separate processes for independent tables
   python sanitize_smart.py config/customers_only.json &
   python sanitize_smart.py config/orders_only.json &
   ```
</details>

---

## 🆘 Still Having Issues?

### Debugging Steps

1. **Enable debug logging:**
   ```json
   // In config file
   "logging": {
     "level": "DEBUG",
     "log_file": "sanitization_debug.log"
   }
   ```

2. **Check log files:**
   ```bash
   # View recent errors
   tail -n 100 sanitization.log
   
   # Search for specific error
   grep -i "error" sanitization.log
   ```

3. **Test components individually:**
   ```bash
   # Test database connection only
   python -c "import pyodbc; conn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=master;Trusted_Connection=yes'); print('OK')"
   
   # Test API key only
   python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('Key:', os.getenv('GITHUB_COPILOT_TOKEN')[:10] if os.getenv('GITHUB_COPILOT_TOKEN') else 'NOT SET')"
   ```

4. **Review existing documentation:**
   - [WORKFLOW_GUIDE.md](WORKFLOW_GUIDE.md) - Comprehensive guide
   - [QUICK_START.md](QUICK_START.md) - Quick reference
   - [CriticalRules/CriticalRulesAndEdgeCases.md](CriticalRules/CriticalRulesAndEdgeCases.md) - Edge cases

### Contact Information

- Check user memory notes in `/memories/` for known issues
- Review critical rules in `CriticalRules/CriticalRulesAndEdgeCases.md`
- Examine test database setup in `scripts/setup_test_db.sql`

---

**Last Updated**: April 2, 2026
