# Desanitization Quick Reference

Complete guide to restoring original PII values from sanitized databases.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Command Reference](#command-reference)
4. [Workflow Examples](#workflow-examples)
5. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### 1. Encryption Key
The desanitization process requires the **same encryption key** used during sanitization.

```bash
# Generate encryption key (one-time setup)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Add to .env file
SANITIZATION_ENCRYPTION_KEY=<your-generated-key>
```

⚠️ **CRITICAL**: Store this key securely and never commit it to version control!

### 2. Operation ID
Every sanitization run generates a unique `operation_id` (UUID). You need this to identify which sanitization operation to reverse.

The operation_id is displayed at the end of sanitization:
```
Desanitization:
  [SUCCESS] Mappings captured: 15,432
  [INFO] Operation ID: a1b2c3d4-5678-90ab-cdef-123456789abc
```

### 3. Mapping Table
Ensure the `pii_mappings` table was created and populated during sanitization:

```sql
-- Check if mapping table exists
SELECT COUNT(*) FROM dbo.pii_mappings WHERE operation_id = '<your-operation-id>';
```

---

## Quick Start

### Step 1: Dry-Run (Preview)

Always start with a dry-run to preview what will be restored:

```bash
python desanitize.py a1b2c3d4-5678-90ab-cdef-123456789abc
```

Expected output:
```
================================================================================
DATABASE DESANITIZATION - RESTORE ORIGINAL VALUES
================================================================================
[1/4] Validating operation...
  [OK] Operation found
  [OK] Total mappings: 15,432
  [OK] Encryption key available

[2/4] Planning restoration...
  [OK] Planning complete: 3 tables to restore

[3/4] Restoring data...
  [1/3] Restoring dbo.Customers...
      [OK] Would restore 5,432 rows (DRY-RUN)

[DRY-RUN] DESANITIZATION PREVIEW
Tables:
  Restored: 3/3
Rows:
  Would restore: 15,432
```

### Step 2: Execute Restoration

After verifying the dry-run output, execute the restoration:

```bash
python desanitize.py a1b2c3d4-5678-90ab-cdef-123456789abc --execute
```

⚠️ **Warning**: This will **MODIFY** your database! Ensure you have a backup.

### Step 3: Verify Results

Check that original values have been restored:

```sql
-- Before desanitization (sanitized)
SELECT TOP 5 Email, FullName FROM dbo.Customers;
-- user_a1b2c3d4@example.com | Michael Brown

-- After desanitization (original)
SELECT TOP 5 Email, FullName FROM dbo.Customers;
-- john.doe@company.com | John Doe
```

---

## Command Reference

### Basic Commands

```bash
# Dry-run (preview only - safe)
python desanitize.py <operation_id>

# Execute full restore
python desanitize.py <operation_id> --execute

# Selective table restore
python desanitize.py <operation_id> --execute --tables dbo.Customers dbo.Orders

# Custom batch size
python desanitize.py <operation_id> --execute --batch-size 5000

# Custom connection string
python desanitize.py <operation_id> --execute --connection-string "DRIVER={...};SERVER=...;DATABASE=...;"
```

### Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `operation_id` | UUID of sanitization operation (required) | - |
| `--execute` | Execute restoration (without this flag, runs dry-run) | `False` (dry-run) |
| `--tables` | Space-separated list of tables to restore (schema.table) | All tables |
| `--batch-size` | Rows per batch for UPDATE operations | `10000` |
| `--connection-string` | Database connection string | From environment |

---

## Workflow Examples

### Example 1: Full Database Restore

Complete workflow from sanitization to desanitization:

```bash
# Step 1: Run sanitization with mapping capture
python sanitize_smart.py config/pii_config.json
# Output: Operation ID: a1b2c3d4-5678-90ab-cdef-123456789abc

# Step 2: Verify sanitization worked
# Check database - should show fake values

# Step 3: Dry-run desanitization
python desanitize.py a1b2c3d4-5678-90ab-cdef-123456789abc

# Step 4: Execute desanitization
python desanitize.py a1b2c3d4-5678-90ab-cdef-123456789abc --execute

# Step 5: Verify restoration
# Check database - should show original values
```

### Example 2: Selective Table Restore

Restore only specific tables (e.g., for debugging):

```bash
# Restore only Customers and Orders tables
python desanitize.py a1b2c3d4-5678-90ab-cdef-123456789abc --execute \
  --tables dbo.Customers dbo.Orders

# Other tables remain sanitized
```

### Example 3: Production Workflow with Backups

Recommended production workflow:

```bash
# 1. Create backup before sanitization
sqlcmd -S localhost -d MyDB -Q "BACKUP DATABASE MyDB TO DISK='C:\Backups\MyDB_before_sanitize.bak'"

# 2. Run sanitization
python sanitize_smart.py config/pii_config_production.json
# Note the operation_id

# 3. Test sanitized environment
# ... your testing ...

# 4. When ready to restore, dry-run first
python desanitize.py <operation_id>

# 5. Create backup before desanitization
sqlcmd -S localhost -d MyDB -Q "BACKUP DATABASE MyDB TO DISK='C:\Backups\MyDB_before_desanitize.bak'"

# 6. Execute desanitization
python desanitize.py <operation_id> --execute

# 7. Verify restoration
# ... verify original values ...
```

---

## Troubleshooting

### Error: "Operation not found in mapping table"

**Problem**: The operation_id doesn't exist in the `pii_mappings` table.

**Solutions**:
1. Verify the operation_id is correct (check sanitization output)
2. Ensure sanitization was run with mapping capture enabled (not in dry-run mode)
3. Check the mapping table:
   ```sql
   SELECT DISTINCT operation_id FROM dbo.pii_mappings;
   ```

### Error: "Encryption key not found"

**Problem**: `SANITIZATION_ENCRYPTION_KEY` environment variable is not set.

**Solutions**:
1. Set the environment variable:
   ```bash
   export SANITIZATION_ENCRYPTION_KEY=<your-key>
   ```
2. Or add to `.env` file
3. Ensure you're using the **same key** used during sanitization

### Error: "Decryption failed: Invalid token"

**Problem**: The encryption key is different from the one used during sanitization.

**Solutions**:
1. Verify you're using the correct encryption key
2. Check if the key was rotated between sanitization and desanitization
3. Restore from backup if key is lost (original data cannot be recovered)

### Slow Performance

**Problem**: Desanitization is taking too long for large datasets.

**Solutions**:
1. Increase batch size:
   ```bash
   python desanitize.py <operation_id> --execute --batch-size 50000
   ```
2. Use selective table restore for specific tables first
3. Check database indexes on the tables being restored

### Warning: "Mapping count mismatch"

**Problem**: Number of mappings applied doesn't match expected count.

**Possible Causes**:
1. Some masked values were manually changed after sanitization
2. Data was deleted/inserted after sanitization
3. Mapping table was modified

**Recommendation**: Review the specific tables/columns and verify data integrity.

---

## SQL Queries for Monitoring

### Check Mapping Table Stats

```sql
-- Overview of all operations
SELECT 
    operation_id,
    COUNT(*) as total_mappings,
    COUNT(DISTINCT CONCAT(schema_name, '.', table_name)) as tables_affected,
    MIN(created_at) as first_mapping,
    MAX(created_at) as last_mapping,
    SUM(CASE WHEN is_null = 1 THEN 1 ELSE 0 END) as null_count,
    SUM(CASE WHEN original_value_encrypted IS NOT NULL THEN 1 ELSE 0 END) as encrypted_count
FROM dbo.pii_mappings
GROUP BY operation_id
ORDER BY last_mapping DESC;
```

### Check Specific Operation

```sql
DECLARE @OperationID UNIQUEIDENTIFIER = 'a1b2c3d4-5678-90ab-cdef-123456789abc';

-- Table breakdown
SELECT 
    schema_name,
    table_name,
    COUNT(DISTINCT column_name) as columns,
    COUNT(*) as mappings,
    SUM(CASE WHEN is_null = 1 THEN 1 ELSE 0 END) as nulls
FROM dbo.pii_mappings
WHERE operation_id = @OperationID
GROUP BY schema_name, table_name
ORDER BY schema_name, table_name;
```

### Verify Restoration Success

```sql
-- Check if any sanitized values remain after desanitization
-- (This query assumes email format pattern)
SELECT 
    table_name,
    column_name,
    COUNT(*) as suspected_sanitized_values
FROM (
    SELECT 
        'dbo.Customers' as table_name,
        'Email' as column_name,
        Email as value
    FROM dbo.Customers
    WHERE Email LIKE 'user_%@example.com'
) subq
GROUP BY table_name, column_name;
```

---

## Best Practices

1. **Always Dry-Run First**
   - Never execute desanitization without reviewing dry-run output
   - Verify the number of tables and rows matches expectations

2. **Backup Before Operations**
   - Backup before sanitization
   - Backup before desanitization
   - Test restore procedures

3. **Secure Encryption Keys**
   - Store encryption keys in secure key management system
   - Never commit keys to version control
   - Document key location for disaster recovery

4. **Verify Restoration**
   - Sample check restored values
   - Verify row counts match
   - Check FK relationships are intact

5. **Monitor Performance**
   - Start with smaller batch sizes for testing
   - Increase batch size for production
   - Monitor transaction log growth

6. **Document Operations**
   - Record operation_ids and dates
   - Document which environments were sanitized/desanitized
   - Track encryption key versions

---

## Environment Variables

```bash
# Required
SANITIZATION_ENCRYPTION_KEY=<fernet-key>     # Same key used during sanitization

# Optional (can use --connection-string instead)
SQLSERVER_HOST=localhost
SQLSERVER_DB=MyDatabase
```

---

## FAQ

**Q: Can I restore data if I lost the encryption key?**
A: No. The encryption is not reversible without the original key. Always backup your encryption key.

**Q: Can I partially restore (only some rows)?**
A: Not in the current version. You can restore specific tables, but not specific rows within a table.

**Q: What happens if sanitization runs multiple times on the same database?**
A: Each sanitization gets a unique operation_id. You can restore to any previous state by using the corresponding operation_id.

**Q: Is desanitization transactional?**
A: Yes. All changes are wrapped in a transaction. If any error occurs, the entire operation rolls back (unless `--continue-on-table-failure` is configured).

**Q: How long are mappings stored?**
A: Indefinitely, unless you implement a retention policy and manually clean up old mappings.

---

## Related Documentation

- [Sanitization Workflow Guide](WORKFLOW_GUIDE.md)
- [Configuration Reference](CHEAT_SHEET.md)
- [Troubleshooting Guide](TROUBLESHOOTING.md)
- [Examples](../examples/desanitization_example.py)

---

**Last Updated**: 2026-04-16
**Version**: 1.0.0
