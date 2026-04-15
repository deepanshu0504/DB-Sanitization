# Database Desanitization Guide

**Version**: 1.4.0  
**Date**: April 13, 2026  
**Status**: Stories 2.1-2.3, 4.1-4.3, 5.2, 7.1 Complete

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [CLI Usage - Record Level](#cli-usage)
4. [Programmatic Usage - Record Level](#programmatic-usage)
5. [Column-Level Restoration (Story 2.2)](#column-level-restoration-story-22)
6. [Table-Level Restoration (Story 2.3)](#table-level-restoration-story-23)
7. [Incremental Desanitization (Story 5.2)](#incremental-desanitization-story-52)
8. [Role-Based Access Control (Story 7.1)](#role-based-access-control-story-71)
9. [Configuration](#configuration)
10. [Best Practices](#best-practices)
11. [Troubleshooting](#troubleshooting)
12. [Examples](#examples)

---

## Overview

The Database Desanitization Framework provides a safe, auditable way to restore original values from sanitized data using stored mapping tables. This guide covers record-level (Story 2.1), column-level (Story 2.2), and table-level (Story 2.3) desanitization, enabling flexible selective restoration strategies.

### Key Features

- **Record-Level Restoration**: Restore original values for specific records by primary key
- **Column-Level Restoration**: Restore specific PII columns across ALL records
- **Table-Level Restoration**: Restore ALL columns with mappings automatically (auto-discovery)
- **Transaction Safety**: All operations are atomic with automatic rollback on failure
- **Dry-Run Mode**: Preview changes before committing (safe default)
- **Progress Tracking**: Monitor large operations with real-time feedback
- **Comprehensive Reporting**: Detailed reports with success/failure metrics
- **Composite Key Support**: Handles single and composite primary keys
- **Batch Filtering**: Restore only mappings from specific sanitization batches
- **NULL Preservation**: Correctly restores NULL values (not tokens)
- **Referential Integrity**: Validates FK constraints after table-level restoration
- **Flexible Error Handling**: Skip missing mappings or fail strictly

### Prerequisites

- Python 3.8+
- pyodbc library
- SQL Server with sanitized database and mapping table
- Appropriate database permissions (SELECT, UPDATE)
- Mapping table created during sanitization (Story 1.2)

---

## Quick Start

### Record-Level Quick Start

### Step 1: Verify Mapping Table Exists

```bash
# Check if mapping table was created during sanitization
python -c "
import pyodbc
conn = pyodbc.connect('your_connection_string')
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM token_mappings')
print(f'Mappings: {cursor.fetchone()[0]}')
"
```

### Step 2: Preview Restoration (Dry-Run)

```bash
# Safe preview - no changes committed
python desanitize_direct.py \
  --table Customers \
  --record-ids "123" "456" \
  --dry-run
```

### Step 3: Execute Restoration

```bash
# Apply changes
python desanitize_direct.py \
  --table Customers \
  --record-ids "123" "456" \
  --execute
```

### Column-Level Quick Start

### Step 1: Preview Column Restoration

```bash
# Preview restoring specific columns across ALL records
python desanitize_direct.py \
  --table Customers \
  --columns Email PhoneNumber \
  --dry-run
```

### Step 2: Execute Column Restoration

```bash
# Apply changes to specified columns only
python desanitize_direct.py \
  --table Customers \
  --columns Email PhoneNumber \
  --execute
```

---

## CLI Usage

### Basic Syntax

```bash
python desanitize_direct.py --table <TABLE> --record-ids <ID1> <ID2> ... [OPTIONS]
```

### Required Arguments

| Argument | Description | Example |
|----------|-------------|---------|
| `--table` | Name of table to restore | `--table Customers` |
| `--record-ids` | Space-separated list of record IDs | `--record-ids "123" "456" "789"` |

### Optional Arguments

| Argument | Description | Default | Example |
|----------|-------------|---------|---------|
| `--schema` | Database schema | `dbo` | `--schema sales` |
| `--batch-id` | Filter by sanitization batch | None | `--batch-id "BATCH-20260409"` |
| `--dry-run` | Preview without committing | `True` | `--dry-run` (default) |
| `--execute` | Execute restoration (disable dry-run) | `False` | `--execute` |
| `--skip-missing` | Skip records without mappings | `False` | `--skip-missing` |
| `--yes`, `-y` | Skip confirmation prompt | `False` | `--yes` |
| `--config` | Path to config file | `config/pii_config.example.json` | `--config myconfig.json` |
| `--json-output` | Save report as JSON | None | `--json-output report.json` |
| `--no-color` | Disable colored output | `False` | `--no-color` |
| `--verbose`, `-v` | Enable debug logging | `False` | `--verbose` |

### Common Usage Patterns

#### 1. Single Record Restoration

```bash
# Restore one customer record
python desanitize_direct.py --table Customers --record-ids "12345" --execute
```

#### 2. Multiple Records

```bash
# Restore multiple orders
python desanitize_direct.py \
  --table Orders \
  --record-ids "ORD-001" "ORD-002" "ORD-003" \
  --execute
```

#### 3. List Available Batches

```bash
# List all sanitization batches with metadata
python desanitize_direct.py --list-batches

# Example output:
# ═══ Available Sanitization Batches ═══
#
# Found 2 sanitization batch(es):
#
# 1. Batch ID: BATCH-20260413-a1b2c3d4
#    Mappings: 1,234 records
#    Tables: 3 (Customers, Orders, Products)
#    Columns: 8 unique columns
#    Created: 2026-04-13 10:30:00
#    Latest: 2026-04-13 10:35:00 (2h ago)
#
# 2. Batch ID: BATCH-20260412-e5f6g7h8
#    Mappings: 856 records
#    Tables: 2 (Customers, Addresses)
#    Columns: 5 unique columns
#    Created: 2026-04-12 14:20:00
#    Latest: 2026-04-12 14:22:00 (1d ago)
```

#### 4. Batch-Specific Restoration Workflow

```bash
# Step 1: List available batches to find the batch ID
python desanitize_direct.py --list-batches

# Step 2: Preview restoration from specific batch
python desanitize_direct.py \
  --table Users \
  --record-ids "U001" "U002" \
  --batch-id "BATCH-20260413-a1b2c3d4" \
  --dry-run

# Step 3: Execute restoration from that batch
python desanitize_direct.py \
  --table Users \
  --record-ids "U001" "U002" \
  --batch-id "BATCH-20260413-a1b2c3d4" \
  --execute

# Restore entire table from specific batch
python desanitize_direct.py \
  --table Customers \
  --table-only \
  --batch-id "BATCH-20260412-e5f6g7h8" \
  --execute
```

**Use Case**: When you run multiple sanitization operations over time and need to restore data from a specific sanitization run (e.g., restore only the data sanitized last week, not earlier runs).

#### 5. JSON Output for Automation

```bash
# List batches as JSON
python desanitize_direct.py --list-batches --json-output

# Example output:
{
  "batches": [
    {
      "batch_id": "BATCH-20260413-a1b2c3d4",
      "row_count": 1234,
      "earliest_timestamp": "2026-04-13T10:30:00",
      "latest_timestamp": "2026-04-13T10:35:00",
      "affected_tables": ["Customers", "Orders", "Products"],
      "affected_columns": ["Email", "Phone", "SSN", "OrderNumber", ...]
    },
    ...
  ]
}
```

#### 6. Skip Missing Mappings

```bash
# Continue even if some records have no mappings
python desanitize_direct.py \
  --table Products \
  --record-ids "P001" "P002" "P999" \
  --skip-missing \
  --execute
```

#### 7. Automated Workflow

```bash
# Non-interactive with JSON output for automation
python desanitize_direct.py \
  --table Customers \
  --record-ids "123" \
  --execute \
  --yes \
  --json-output restoration_report.json
```

#### 8. Preview Before Execute

```bash
# Step 1: Preview (safe default)
python desanitize_direct.py --table Orders --record-ids "456"

# Step 2: Review output, then execute
python desanitize_direct.py --table Orders --record-ids "456" --execute
```

---

## Programmatic Usage

### Basic Example

```python
import pyodbc
from desanitization import DesanitizationEngine
from mapping.mapping_table_manager import MappingTableManager
from database.schema_inspector import SchemaInspector

# Connect to database
conn_string = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=MyDB;Trusted_Connection=yes;"
conn = pyodbc.connect(conn_string)
conn.autocommit = False

# Initialize components
mapping_manager = MappingTableManager(conn_string)
schema_inspector = SchemaInspector(conn_string)

engine = DesanitizationEngine(
    connection=conn,
    mapping_manager=mapping_manager,
    schema_inspector=schema_inspector
)

# Restore records
report = engine.desanitize_records(
    table='Customers',
    record_ids=['123', '456'],
    dry_run=False
)

# Check results
print(f"Records restored: {report.records_restored}")
print(f"Mappings applied: {report.mappings_applied}")

if report.errors:
    print(f"Errors: {report.errors}")
else:
    print("✓ Restoration successful")

conn.close()
```

### Advanced Example with Error Handling

```python
from desanitization import DesanitizationEngine
from desanitization.exceptions import (
    MappingNotFoundError,
    PreconditionError,
    RestorationError
)

try:
    report = engine.desanitize_records(
        table='Orders',
        record_ids=['ORD-001', 'ORD-002'],
        schema='sales',
        batch_id='BATCH-20260409',
        skip_missing=True,
        dry_run=False
    )
    
    # Process report
    for table, columns in report.table_details.items():
        for column, rows in columns.items():
            print(f"  {table}.{column}: {rows} rows restored")
    
    # Save report
    import json
    with open('report.json', 'w') as f:
        json.dump(report.to_dict(), f, indent=2)

except MappingNotFoundError as e:
    print(f"Missing mappings: {e.missing_records}")
    # Handle missing mappings...

except PreconditionError as e:
    print(f"Setup error: {e}")
    print(f"Action: {e.suggested_action}")
    # Fix preconditions...

except RestorationError as e:
    print(f"Database error: {e}")
    # Handle restoration failure...
```

---

## Column-Level Restoration (Story 2.2)

Column-level desanitization restores specific PII columns across **ALL records** in a table, enabling selective restoration of certain data fields while keeping others sanitized.

### Use Cases

- **Selective Data Exposure**: Restore emails but keep phone numbers masked
- **Progressive Desanitization**: Restore columns incrementally as needed
- **Compliance Requirements**: Expose only specific PII types per regulation
- **Large Table Operations**: Restore specific columns without loading all PII into memory

### CLI Usage - Column Level

#### Basic Syntax

```bash
python desanitize_direct.py --table <TABLE> --columns <COL1> <COL2> ... [OPTIONS]
```

#### Required Arguments

| Argument | Description | Example |
|----------|-------------|---------|
| `--table` | Name of table to restore | `--table Customers` |
| `--columns` | Space-separated list of columns | `--columns Email PhoneNumber` |

**Note**: `--record-ids` and `--columns` are mutually exclusive. Use one or the other.

#### Common Usage Patterns

##### 1. Single Column Restoration

```bash
# Preview restoring Email column across all records
python desanitize_direct.py --table Customers --columns Email --dry-run

# Execute restoration
python desanitize_direct.py --table Customers --columns Email --execute
```

##### 2. Multiple Columns

```bash
# Restore several PII columns simultaneously
python desanitize_direct.py \
  --table Customers \
  --columns Email PhoneNumber SSN \
  --execute \
  --yes
```

##### 3. Batch-Specific Column Restoration

```bash
# Restore columns only from specific sanitization batch
python desanitize_direct.py \
  --table Users \
  --columns FirstName LastName \
  --batch-id "BATCH-20260409-123456" \
  --execute
```

##### 4. Large Table with Progress Tracking

```bash
# Restore columns with live progress updates (to stderr)
python desanitize_direct.py \
  --table Employees \
  --columns Salary BonusAmount \
  --execute \
  --verbose
```

##### 5. Automated Column Restoration

```bash
# Non-interactive with JSON output
python desanitize_direct.py \
  --table Orders \
  --columns CustomerEmail CustomerPhone \
  --execute \
  --yes \
  --json-output column_restoration.json
```

### Programmatic Usage - Column Level

#### Basic Example

```python
import pyodbc
from desanitization import DesanitizationEngine
from mapping.mapping_table_manager import MappingTableManager
from database.schema_inspector import SchemaInspector

# Setup (same as record-level)
conn_string = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=MyDB;Trusted_Connection=yes;"
conn = pyodbc.connect(conn_string)
conn.autocommit = False

mapping_manager = MappingTableManager(conn_string)
schema_inspector = SchemaInspector(conn_string)

engine = DesanitizationEngine(
    connection=conn,
    mapping_manager=mapping_manager,
    schema_inspector=schema_inspector
)

# Restore specific columns across all records
report = engine.desanitize_columns(
    table='Customers',
    column_names=['Email', 'PhoneNumber'],
    schema='dbo',
    dry_run=False
)

# Check results
print(f"Columns restored: {report.columns_affected}")
print(f"Records affected: {report.records_restored}")
print(f"Mappings applied: {report.mappings_applied}")

for table, columns in report.table_details.items():
    for column, rows in columns.items():
        print(f"  {column}: {rows} rows restored")

conn.close()
```

#### Advanced Example with Progress Callback

```python
from desanitization import DesanitizationEngine

def progress_handler(column, current, total, records):
    """Custom progress callback for large operations."""
    percentage = (current / total) * 100
    print(f"[{percentage:.1f}%] Processing column {current}/{total}: "
          f"{column} ({records:,} records)")

# Execute with progress tracking
report = engine.desanitize_columns(
    table='Customers',
    column_names=['Email', 'PhoneNumber', 'SSN', 'DateOfBirth'],
    batch_id='BATCH-20260409',
    dry_run=False,
    progress_callback=progress_handler
)

# Output:
# [25.0%] Processing column 1/4: Email (125,432 records)
# [50.0%] Processing column 2/4: PhoneNumber (125,432 records)
# [75.0%] Processing column 3/4: SSN (125,432 records)
# [100.0%] Processing column 4/4: DateOfBirth (125,432 records)
```

### Performance Characteristics

| Table Size | Columns | Avg Time | Memory Usage | Notes |
|------------|---------|----------|--------------|-------|
| 10K rows | 1 column | <5 sec | ~10 MB | Minimal overhead |
| 100K rows | 2 columns | <30 sec | ~50 MB | Efficient batch processing |
| 1M rows | 3 columns | 2-5 min | ~200 MB | Progress tracking recommended |

**Optimization Tips:**
- Mappings fetched per-column to enable progress tracking
- Temp table pattern ensures efficient UPDATE-JOIN operations
- Transaction safety maintained across all columns (all-or-nothing)
- Progress callbacks help monitor long-running operations

### Column-Level vs Record-Level Comparison

| Feature | Record-Level | Column-Level |
|---------|--------------|--------------|
| **Scope** | Specific records | All records |
| **Granularity** | By primary key | By column name |
| **Use Case** | Individual customer requests | Bulk policy changes |
| **Performance** | Fast for few records | Optimized for full columns |
| **Filtering** | Record IDs | Column names |
| **Progress Tracking** | Batch-based | Per-column |

### Best Practices for Column-Level Restoration

1. **Always Preview First**: Use `--dry-run` to validate scope
   ```bash
   python desanitize_direct.py --table Users --columns Email --dry-run
   ```

2. **Consider FK Dependencies**: Restore parent table columns before children
   ```bash
   # Restore Customer email first
   python desanitize_direct.py --table Customers --columns Email --execute
   
   # Then restore Orders customer email reference
   python desanitize_direct.py --table Orders --columns CustomerEmail --execute
   ```

3. **Use Batch Filtering for Selective Restoration**:
   ```bash
   # Only restore columns from recent sanitization run
   python desanitize_direct.py \
     --table Users \
     --columns SSN \
     --batch-id "BATCH-20260409" \
     --execute
   ```

4. **Monitor Progress on Large Tables**:
   ```bash
   # Enable verbose logging to see progress
   python desanitize_direct.py \
     --table LargeTable \
     --columns Email PhoneNumber \
     --execute \
     --verbose
   ```

5. **Validate Results After Restoration**:
   ```sql
   -- Sample check after restoration
   SELECT 
       COUNT(*) AS total_records,
       COUNT(Email) AS non_null_emails,
       COUNT(CASE WHEN Email LIKE 'user_%@example.com' THEN 1 END) AS still_masked
   FROM Customers
   WHERE Email IS NOT NULL;
   ```

### Error Handling

#### Invalid Column Name

```bash
$ python desanitize_direct.py --table Customers --columns InvalidColumn --dry-run

ERROR: Invalid columns: ['InvalidColumn'] not found in [dbo].[Customers]
Available columns: CustomerID, FirstName, LastName, Email, PhoneNumber
```

#### No Mappings Found

```bash
$ python desanitize_direct.py --table Customers --columns Email --execute

WARNING: No mappings found for columns: ['Email']
Operation completed with 0 records restored.
```

#### Progress Callback Errors

If a custom progress callback raises an exception, it will be logged but won't fail the restoration:

```python
def bad_callback(column, current, total, records):
    raise ValueError("Oops!")  # Won't stop restoration

report = engine.desanitize_columns(
    table='Customers',
    column_names=['Email'],
    progress_callback=bad_callback,
    dry_run=False
)
# Restoration continues despite callback error
```

---

## Table-Level Restoration (Story 2.3)

Table-level desanitization restores **ALL columns with mappings** in a table automatically. The engine auto-discovers which columns have stored mappings and restores them all in a single operation—eliminating the need to manually specify column lists.

### Use Cases

- **Complete Table Restoration**: Restore entire table to original state after testing/development
- **Simplified Workflow**: No need to remember which columns were sanitized
- **Batch Rollback**: Reverse entire sanitization batch at table level
- **Post-Audit Restoration**: Restore all PII after audit/compliance review complete
- **Emergency Recovery**: Quick full restoration when sanitized data causes issues

### CLI Usage - Table Level

#### Basic Syntax

```bash
python desanitize_direct.py --table <TABLE> --table-only [OPTIONS]
```

#### Required Arguments

| Argument | Description | Example |
|----------|-------------|---------|
| `--table` | Name of table to restore | `--table Customers` |
| `--table-only` | Flag to enable table-level mode | `--table-only` |

**Note**: `--table-only` is mutually exclusive with `--record-ids` and `--columns`.

#### Common Usage Patterns

##### 1. Full Table Restoration

```bash
# Preview restoring all columns with mappings (safe default)
python desanitize_direct.py --table Customers --table-only --dry-run

# Execute restoration
python desanitize_direct.py --table Customers --table-only --execute
```

##### 2. Non-Interactive Restoration

```bash
# Skip confirmation prompt for automated workflows
python desanitize_direct.py \
  --table Users \
  --table-only \
  --execute \
  --yes
```

##### 3. Batch-Specific Table Restoration

```bash
# Restore only columns from specific sanitization batch
python desanitize_direct.py \
  --table Orders \
  --table-only \
  --batch-id "BATCH-20260409-123456" \
  --execute
```

##### 4. Large Table with Progress Tracking

```bash
# Enable verbose logging to monitor column-by-column progress
python desanitize_direct.py \
  --table Employees \
  --table-only \
  --execute \
  --verbose
```

##### 5. Automated Table Restoration with Reporting

```bash
# Non-interactive with JSON output for CI/CD pipelines
python desanitize_direct.py \
  --table Customers \
  --table-only \
  --execute \
  --yes \
  --json-output table_restoration_report.json
```

### Programmatic Usage - Table Level

#### Basic Example

```python
import pyodbc
from desanitization import DesanitizationEngine
from mapping.mapping_table_manager import MappingTableManager
from database.schema_inspector import SchemaInspector

# Setup connection
conn_string = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=MyDB;Trusted_Connection=yes;"
conn = pyodbc.connect(conn_string)
conn.autocommit = False

mapping_manager = MappingTableManager(conn_string)
schema_inspector = SchemaInspector(conn_string)

engine = DesanitizationEngine(
    connection=conn,
    mapping_manager=mapping_manager,
    schema_inspector=schema_inspector
)

# Restore ALL columns with mappings in table
report = engine.desanitize_table(
    table='Customers',
    schema='dbo',
    dry_run=False
)

# Check results
print(f"Columns restored: {report.columns_affected}")
print(f"Records affected: {report.records_restored}")
print(f"Mappings applied: {report.mappings_applied}")

# View discovered columns
for table, columns in report.table_details.items():
    print(f"\nTable: {table}")
    for column, rows in columns.items():
        print(f"  {column}: {rows} rows restored")

# Check for FK violations
if report.warnings:
    print("\nWarnings:")
    for warning in report.warnings:
        print(f"  ⚠ {warning}")

conn.close()
```

#### Advanced Example with Batch Filtering

```python
from desanitization import DesanitizationEngine
from datetime import datetime

def progress_handler(column, current, total, records):
    """Track restoration progress."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] "
          f"Column {current}/{total}: {column} ({records:,} mappings)")

# Restore only mappings from specific batch
report = engine.desanitize_table(
    table='Customers',
    schema='dbo',
    batch_id='BATCH-20260409-123456',
    dry_run=False,
    progress_callback=progress_handler
)

print(f"\nRestoration complete!")
print(f"  Auto-discovered columns: {report.columns_affected}")
print(f"  Total mappings applied: {report.mappings_applied}")
print(f"  Duration: {report.end_time - report.start_time}")
```

#### Error Handling Example

```python
from desanitization.exceptions import PreconditionError

try:
    report = engine.desanitize_table(
        table='EmptyTable',
        schema='dbo',
        dry_run=False
    )
except PreconditionError as e:
    print(f"Cannot restore table: {e}")
    print(f"Suggested action: {e.suggested_action}")
    # Output:
    # Cannot restore table: No mappings found for table [dbo].[EmptyTable]
    # Suggested action: No columns have mappings in the mapping table...
```

### Auto-Discovery Workflow

The table-level restoration follows this workflow:

```
1. Query mapping table for DISTINCT column_name WHERE table_name = ?
   ├─ Returns: ['Email', 'PhoneNumber', 'SSN'] (alphabetically sorted)
   └─ Filters by batch_id if provided

2. Delegate to desanitize_columns() with discovered column list
   ├─ Reuses existing column-level restoration pipeline (70% code reuse)
   ├─ Batch processing per column for efficiency
   └─ Progress tracking per column

3. Validate referential integrity (if not dry-run)
   ├─ Check outgoing FK constraints
   ├─ Query for orphaned records
   └─ Add warnings to report (non-blocking)

4. Return comprehensive report
   ├─ Auto-discovered columns listed
   ├─ Restoration metrics per column
   └─ FK validation results
```

### Performance Characteristics

| Table Size | PII Columns | Avg Time | Memory Usage | Notes |
|------------|-------------|---------|--------------| ------|
| 10K rows | 3 columns | <10 sec | ~15 MB | Fast auto-discovery |
| 100K rows | 5 columns | 1-2 min | ~100 MB | Progress tracking recommended |
| 1M rows | 8 columns | 5-10 min | ~500 MB | Batch processing efficient |

**Optimization:**
- Column discovery query uses DISTINCT with indexed columns (fast)
- Restoration delegates to optimized column-level pipeline
- Temp table pattern ensures efficient UPDATE-JOIN per column
- FK validation runs in parallel (non-blocking warnings)

### Table vs Column vs Record Level Comparison

| Feature | Record-Level | Column-Level | Table-Level |
|---------|--------------|--------------|-------------|
| **Scope** | Specific records | Specific columns (all rows) | All columns with mappings |
| **Granularity** | By primary key | By column name | Entire table |
| **Discovery** | Manual record IDs | Manual column list | **Automatic** |
| **Use Case** | Individual requests | Selective exposure | Full rollback |
| **Performance** | Fast for few records | Optimized per column | Optimized for full table |
| **Progress** | Batch-based | Per column | Per column |
| **FK Validation** | Optional | Optional | **Included** |

### Best Practices for Table-Level Restoration

1. **Always Preview First**: Verify auto-discovered columns match expectations
   ```bash
   python desanitize_direct.py --table Customers --table-only --dry-run
   # Review output to see which columns will be restored
   ```

2. **Use Batch Filtering for Selective Rollback**:
   ```bash
   # Rollback only the most recent sanitization batch
   python desanitize_direct.py \
     --table Users \
     --table-only \
     --batch-id "BATCH-20260409-123456" \
     --execute
   ```

3. **Monitor FK Warnings**: Check for referential integrity issues after restoration
   ```python
   report = engine.desanitize_table(table='Orders', dry_run=False)
   
   if report.warnings:
       for warning in report.warnings:
           if 'FK violation' in warning or 'orphaned' in warning:
               print(f"⚠ CRITICAL: {warning}")
   ```

4. **Verify Column Discovery on First Run**:
   ```bash
   # First time restoring a table? Check what columns it finds
   python desanitize_direct.py --table NewTable --table-only --dry-run --verbose
   # Output will show: "Auto-discovered 3 column(s): ['Email', 'Phone', 'SSN']"
   ```

5. **Validate Results After Full Table Restoration**:
   ```sql
   -- Check for any remaining masked values
   SELECT 
       'Email' AS column_name,
       COUNT(*) AS masked_count
   FROM Customers
   WHERE Email LIKE '%@example.com' AND Email LIKE 'user_%'
   
   UNION ALL
   
   SELECT 
       'PhoneNumber',
       COUNT(*)
   FROM Customers
   WHERE PhoneNumber LIKE '555-%';
   ```

### Error Handling

#### No Mappings Found

```bash
$ python desanitize_direct.py --table EmptyTable --table-only --dry-run

✖ Error: No mappings found for table [dbo].[EmptyTable]
Suggested action: No columns have mappings in the mapping table. Possible causes:
  1. Table has not been sanitized yet
  2. Incorrect table name or schema
  3. Batch ID filter excluded all mappings
```

#### Batch Filter Excludes All Mappings

```bash
$ python desanitize_direct.py --table Customers --table-only --batch-id "INVALID-BATCH" --dry-run

✖ Error: No mappings found for table [dbo].[Customers]
Suggested action: Batch ID filter excluded all mappings. 
Try without --batch-id to see all available columns.
```

#### FK Violations Detected (Non-Blocking)

```python
report = engine.desanitize_table(table='Orders', dry_run=False)

# Warnings added but restoration succeeds
assert len(report.warnings) > 0
assert 'Referential integrity issue: FK_Orders_Customers - 3 orphaned record(s)' in report.warnings[0]

# Restoration still completed
assert report.records_restored > 0
```

### Troubleshooting Table-Level Restoration

#### Issue: "Table has no mappings" but table was sanitized

**Cause**: Table name mismatch or schema difference

**Solution**:
```python
# Check mapping table for exact table name
cursor.execute("""
    SELECT DISTINCT table_name 
    FROM token_mappings 
    WHERE table_name LIKE '%Customer%'
""")
print(cursor.fetchall())  # Shows actual table names with schema

# Use exact name from mapping table
report = engine.desanitize_table(table='dbo.Customers', schema='dbo', ...)
```

#### Issue: Only some columns restored, expected more

**Cause**: Batch ID filter or partial sanitization

**Solution**:
```bash
# Check which batches have mappings for this table
SELECT DISTINCT batch_id, COUNT(DISTINCT column_name) AS columns
FROM token_mappings
WHERE table_name = 'Customers'
GROUP BY batch_id;

# Restore without batch filter to get all columns
python desanitize_direct.py --table Customers --table-only --execute
```

#### Issue: Performance slow on large tables

**Cause**: Many columns or millions of rows

**Solution**:
```bash
# Use verbose mode to monitor progress
python desanitize_direct.py \
  --table LargeTable \
  --table-only \
  --execute \
  --verbose
  
# Consider column-level restoration for finer control
python desanitize_direct.py \
  --table LargeTable \
  --columns Email PhoneNumber \
  --execute  # Restore subset first
```

---

## Performance Tuning (Story 5.3)

**Optimization features added**: April 13, 2026

The desanitization framework provides several performance optimization tools for large-scale operations and repeated restorations:

### LRU Caching for Mapping Lookups

Reduce database load by caching frequently accessed mappings in memory.

**When to Use:**
- Repeated desanitizations of the same batch
- Development/testing with same dataset
- Large desanitization operations (>100K mappings)
- Database connection is slow or high-latency

**Configuration:**

```json
{
  "mapping_performance": {
    "cache_enabled": true,
    "cache_size": 10000,
    "cache_ttl_seconds": null
  }
}
```

**Programmatic Usage:**

```python
from mapping import MappingTableManager, MappingLRUCache

# Initialize cache
cache = MappingLRUCache(max_size=10000)

# Pass to manager
manager = MappingTableManager(
    connection_string=conn_str,
    cache=cache
)

# Use normally - caching is transparent
mappings = manager.get_mappings("Customers", "Email")

# Check cache performance
metrics = cache.get_metrics()
print(f"Cache hit rate: {metrics.hit_rate:.1f}%")
print(f"Hits: {metrics.hits}, Misses: {metrics.misses}")
print(f"Evictions: {metrics.evictions}")
```

**Performance Benefits:**
- **10-100x faster** lookups on cache hits (<1ms vs 10-100ms)
- **>80% hit rate** on repeated desanitizations
- **Minimal overhead** (<5%) on first pass (cache population)
- **Thread-safe** for concurrent operations

**Cache Sizing Guidance:**
- Default: 10,000 entries (good for most workloads)
- Small datasets (<10K mappings): cache_size = 5,000
- Large datasets (>100K mappings): cache_size = 50,000
- Rule of thumb: 10% of distinct masked values

**When NOT to Use:**
- One-time desanitization operations
- Memory-constrained environments
- Rapidly changing mapping data

### Query Performance Analysis

Diagnose slow queries and identify optimization opportunities.

**CLI Tool:**

```bash
# Analyze mapping table performance
python -m database.query_performance_analyzer \
  --connection-string "..." \
  --table token_mappings \
  --export-report performance_report.json
```

**Programmatic Usage:**

```python
from database import QueryPerformanceAnalyzer

analyzer = QueryPerformanceAnalyzer(connection_string, "token_mappings")

# Check index fragmentation
fragmentation = analyzer.get_index_fragmentation()
for idx in fragmentation:
    print(f"{idx.index_name}: {idx.fragmentation_percent:.1f}% - {idx.recommendation}")
    # Output:
    # IX_token_mappings_record_id: 35.4% - REBUILD
    # IX_token_mappings_table_name: 12.3% - REORGANIZE
    # IX_token_mappings_batch_id: 3.1% - OK

# Analyze index usage
usage = analyzer.get_index_usage_stats()
for idx in usage:
    if idx.total_reads == 0:
        print(f"⚠ Unused index: {idx.index_name} (consider removing)")
    elif idx.read_write_ratio < 1.0:
        print(f"⚠ Write-heavy index: {idx.index_name} (ratio: {idx.read_write_ratio:.2f})")

# Get missing index recommendations
missing = analyzer.get_missing_indexes()
for suggestion in missing:
    print(f"Suggested index: {suggestion['create_index_statement']}")

# Table size statistics
stats = analyzer.get_table_size_stats()
print(f"Table: {stats['row_count']:,} rows, {stats['total_size_mb']:.2f} MB")
```

### Index Maintenance

Optimize index performance through regular maintenance.

**Manual Execution (SQL Script):**

```sql
-- Run scripts/maintain_mapping_indexes.sql in SQL Server Management Studio
-- - Analyzes fragmentation for all indexes on token_mappings
-- - Executes REORGANIZE (10-30% fragmentation) or REBUILD (>30%)
-- - Updates statistics with FULLSCAN
-- - Displays comprehensive before/after report
```

**Python Wrapper:**

```bash
# Dry run - analyze fragmentation only
python maintenance/optimize_mapping_indexes.py \
  --connection-string "..." \
  --table token_mappings

# Execute maintenance
python maintenance/optimize_mapping_indexes.py \
  --connection-string "..." \
  --table token_mappings \
  --execute
```

**Output:**

```
=====================================================================
Index Maintenance for [dbo].[token_mappings]
=====================================================================

--- Current Index Fragmentation ---
IndexName                          Fragmentation %  PageCount  RecommendedAction
IX_token_mappings_record_id        35.42           12453      REBUILD
IX_token_mappings_table_name       12.87           8392       REORGANIZE
IX_token_mappings_batch_id         3.21            5421       OK

--- Executing Maintenance ---
Processing: IX_token_mappings_record_id (REBUILD) - Fragmentation: 35.42%
  ✓ Completed in 8 seconds

--- Maintenance Summary ---
Total Indexes Processed: 2
Successful: 2
Failed: 0
Total Duration: 15 seconds
```

**Programmatic Usage:**

```python
from maintenance import optimize_mapping_indexes

# Dry run
result = optimize_mapping_indexes(
    connection_string=conn_str,
    table_name="token_mappings",
    dry_run=True,
    verbose=True
)

print(f"Indexes needing REBUILD: {result['rebuild_needed']}")
print(f"Indexes needing REORGANIZE: {result['reorganize_needed']}")

# Execute
if result['rebuild_needed'] > 0:
    optimize_mapping_indexes(
        connection_string=conn_str,
        dry_run=False,
        verbose=True
    )
```

**Maintenance Schedule Recommendations:**
- High activity (>10K inserts/day): **Weekly**
- Medium activity (1K-10K inserts/day): **Bi-weekly**
- Low activity (<1K inserts/day): **Monthly**
- After large sanitization batches: **Immediate**

### Performance Benchmarking

Measure and validate performance improvements.

```bash
# Run performance benchmarks
pytest tests/test_mapping_performance_benchmark.py -v

# Run with database connection for real-world benchmarks
python tests/test_mapping_performance_benchmark.py "your_connection_string"
```

**Benchmark Results (Typical):**

| Operation | Without Cache | With Cache (Hit) | Speedup |
|-----------|---------------|------------------|---------|
| 100 lookups | 250ms | 2ms | 125x |
| 1K lookups | 2.1s | 15ms | 140x |
| 10K lookups | 18.5s | 120ms | 154x |

**Cache Performance Metrics:**
- Cache lookup: <0.01ms avg (100,000+ lookups/sec)
- Cache miss: <0.01ms avg (negligible overhead)
- LRU eviction: <0.05ms avg per insert
- Thread-safe overhead: <0.1ms avg

### Performance Best Practices

1. **Enable Caching for Repeated Operations:**
   ```python
   # Scenario: Multiple desanitization iterations during testing
   cache = MappingLRUCache(max_size=20000)
   manager = MappingTableManager(conn_str, cache=cache)
   
   # First iteration: Cache miss (slow)
   report1 = engine.desanitize_table(..., dry_run=False)
   
   # Second iteration: Cache hit (fast)
   report2 = engine.desanitize_table(..., dry_run=False)
   ```

2. **Monitor Index Fragmentation:**
   ```bash
   # Add to weekly maintenance scripts
   python -m database.query_performance_analyzer \
     --connection-string "..." \
     --alert-on-fragmentation 30
   ```

3. **Use Composite Index on created_at (Story 5.2):**
   ```sql
   -- Execute once if not already created
   CREATE NONCLUSTERED INDEX IX_token_mappings_created_at
   ON [dbo].[token_mappings] (created_at, table_name, batch_id)
   INCLUDE (column_name, record_id, original_value, masked_value)
   WITH (FILLFACTOR = 90);
   ```

4. **Clear Cache After Mapping Inserts:**
   ```python
   # After sanitization run that adds new mappings
   if cache:
       cache.invalidate()  # Clear all entries
       # OR invalidate specific table
       cache.invalidate_table("Customers")
   ```

5. **Profile Slow Operations:**
   ```python
   import time
   
   start = time.perf_counter()
   mappings = manager.get_mappings("LargeTable", "Column")
   elapsed_ms = (time.perf_counter() - start) * 1000
   
   if elapsed_ms > 1000:  # Slower than 1 second
       analyzer = QueryPerformanceAnalyzer(conn_str)
       fragmentation = analyzer.get_index_fragmentation()
       # Check for high fragmentation...
   ```

---

The desanitization engine uses the same configuration file as sanitization:

**config/pii_config.example.json**:
```json
{
  "database": {
    "server": "localhost",
    "database": "MyDatabase",
    "authentication": "windows",
    "timeout": 30
  },
  "mapping_capture": {
    "table_name": "token_mappings",
    "enabled": true
  }
}
```

### Environment Variables

Override config with environment variables:

```bash
export SQLSERVER_HOST="myserver.database.windows.net"
export SQLSERVER_DB="ProductionDB"
export SQLSERVER_AUTH="sql"
export SQLSERVER_USER="sa"
export SQLSERVER_PASSWORD="YourPassword"
```

---

## Best Practices

### 1. Always Preview First

```bash
# ALWAYS run with --dry-run first
python desanitize_direct.py --table Users --record-ids "123" --dry-run

# Review output, then execute
python desanitize_direct.py --table Users --record-ids "123" --execute
```

### 2. Use Batch IDs for Tracking

```bash
# Restore only from specific sanitization run
python desanitize_direct.py \
  --table Customers \
  --batch-id "BATCH-$(date +%Y%m%d)" \
  --record-ids "123" \
  --execute
```

### 3. Handle Missing Mappings Gracefully

```bash
# Skip records without mappings (for partial restoration)
python desanitize_direct.py \
  --table Orders \
  --record-ids "1" "2" "3" \
  --skip-missing \
  --execute
```

### 4. Automate with JSON Output

```bash
# Save detailed report for auditing
python desanitize_direct.py \
  --table Customers \
  --record-ids "123" \
  --execute \
  --json-output "reports/restore_$(date +%Y%m%d_%H%M%S).json"
```

### 5. Test on Non-Production First

```bash
# Test workflow on dev/test database
export SQLSERVER_DB="TestDB"
python desanitize_direct.py --table Customers --record-ids "123" --execute

# Then apply to production
export SQLSERVER_DB="ProductionDB"
python desanitize_direct.py --table Customers --record-ids "123" --execute
```

### 6. Verify After Restoration

```sql
-- Verify specific records restored correctly
SELECT CustomerID, Email, Phone
FROM Customers
WHERE CustomerID IN (123, 456)

-- Compare row counts before/after
SELECT COUNT(*) FROM Customers  -- Should be unchanged
```

---

## Troubleshooting

### Error: Mapping table 'token_mappings' does not exist

**Cause**: Sanitization was not run with mapping capture enabled, or mapping table was dropped.

**Solution**:
```bash
# 1. Check if table exists
python -c "
import pyodbc
conn = pyodbc.connect('your_conn_string')
cursor = conn.cursor()
cursor.execute(\"SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='token_mappings'\")
print('Found' if cursor.fetchone() else 'Not found')
"

# 2. Re-run sanitization with mapping capture
# Edit config/pii_config.example.json:
#   "mapping_capture": { "enabled": true }
python sanitize_smart.py config/pii_config.example.json
```

### Error: Mappings not found for record(s)

**Cause**: Records were never sanitized, or mappings were archived/purged.

**Solutions**:
```bash
# Option 1: Skip missing records
python desanitize_direct.py --table Users --record-ids "999" --skip-missing

# Option 2: Query mapping table to check availability
SELECT table_name, column_name, record_id, created_at
FROM token_mappings
WHERE table_name = 'Customers' AND record_id IN ('123', '456')
```

### Error: Target table does not exist

**Cause**: Table name or schema is incorrect.

**Solution**:
```bash
# Check table exists
SELECT TABLE_SCHEMA, TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE'

# Specify correct schema
python desanitize_direct.py --table MyTable --schema custom_schema --record-ids "123"
```

### Error: Database connection failed

**Cause**: Incorrect connection settings or permissions.

**Solution**:
```bash
# Test connection directly
python -c "
import pyodbc
conn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=TestDB;Trusted_Connection=yes;')
print('✓ Connected')
"

# Check environment variables
echo $SQLSERVER_HOST
echo $SQLSERVER_DB
```

### Desanitization Slow for Large Record Sets

**Cause**: Too many records without indexing.

**Solution**:
```sql
-- Add index on record_id for faster lookups
CREATE NONCLUSTERED INDEX IX_mapping_record_id
ON token_mappings(record_id)
INCLUDE (table_name, column_name, original_value)

-- Process in smaller batches
python desanitize_direct.py --table Users --record-ids {batch1} --execute
python desanitize_direct.py --table Users --record-ids {batch2} --execute
```

---

## Examples

### Example 1: E-commerce Order Restoration

```bash
# Scenario: Customer requests data restoration for their orders

# Step 1: Identify customer's order IDs
SELECT OrderID FROM Orders WHERE CustomerEmail = 'customer@example.com'
# Results: ORD-123, ORD-456

# Step 2: Preview restoration
python desanitize_direct.py \
  --table Orders \
  --record-ids "ORD-123" "ORD-456" \
  --dry-run

# Step 3: Execute after review
python desanitize_direct.py \
  --table Orders \
  --record-ids "ORD-123" "ORD-456" \
  --execute \
  --json-output reports/order_restoration_$(date +%Y%m%d).json
```

### Example 2: Multi-Table Customer Data

```bash
# Restore customer across multiple tables

# Customers table
python desanitize_direct.py --table Customers --record-ids "C123" --execute

# Orders table (same customer ID)
python desanitize_direct.py --table Orders --schema sales --record-ids "C123" --execute

# Payments table
python desanitize_direct.py --table Payments --schema billing --record-ids "C123" --execute
```

### Example 3: Composite Primary Key

```bash
# Table with composite PK: (CustomerID, OrderID)
# Record ID stored as JSON in mapping table: {"CustomerID": "123", "OrderID": "456"}

python desanitize_direct.py \
  --table OrderDetails \
  --record-ids '{"CustomerID": "C123", "OrderID": "O456"}' \
  --execute
```

### Example 4: Batch Scripting

```bash
#!/bin/bash
# restore_customers.sh - Restore multiple customers from list

CUSTOMER_IDS_FILE="customers_to_restore.txt"
REPORT_DIR="reports"

while IFS= read -r customer_id; do
    echo "Restoring customer: $customer_id"
    
    python desanitize_direct.py \
      --table Customers \
      --record-ids "$customer_id" \
      --execute \
      --yes \
      --json-output "$REPORT_DIR/restore_$customer_id.json"
    
    if [ $? -eq 0 ]; then
        echo "✓ Success: $customer_id"
    else
        echo "✖ Failed: $customer_id"
    fi
done < "$CUSTOMER_IDS_FILE"
```

### Example 5: Validation Script

```python
#!/usr/bin/env python3
"""
Validate restoration completed successfully.
"""
import pyodbc
import json

def validate_restoration(conn, table, record_ids, report_file):
    """Verify records were restored correctly."""
    cursor = conn.cursor()
    
    # Load restoration report
    with open(report_file) as f:
        report = json.load(f)
    
    print(f"Restoration Report: {report['operation_id']}")
    print(f"Records restored: {report['summary']['records_restored']}")
    
    # Verify no tokens remain
    placeholders = ','.join('?' * len(record_ids))
    cursor.execute(f"""
        SELECT * FROM {table}
        WHERE record_id IN ({placeholders})
        AND (
            Email LIKE '%@test.com' OR
            Email LIKE 'user_%@%' OR
            Phone LIKE '555-%'
        )
    """, record_ids)
    
    remaining_tokens = cursor.fetchall()
    if remaining_tokens:
        print(f"⚠ Warning: {len(remaining_tokens)} records still have masked values")
    else:
        print("✓ Validation passed: No masked values detected")

# Usage
conn = pyodbc.connect("your_connection_string")
validate_restoration(conn, 'Customers', ['123', '456'], 'report.json')
```

---

## Incremental Desanitization (Story 5.2)

**New in Version 1.3.0 (April 13, 2026)**

For large production databases, incremental desanitization enables controlled restoration over time with minimal system impact. Key features include time-based filtering, rate limiting, and progress checkpoints.

### Key Features

- **Time-Based Filtering**: Restore only mappings created within a date range
- **Rate Limiting**: Add delays between column restorations to reduce system load
- **ETA Display**: Real-time progress updates with estimated completion time
- **Checkpoint Resume**: Continue from interruption points (inherited from Story 2.4)
- **Production-Safe**: Designed for multi-shift workflows and maintenance windows

### Use Cases

1. **Multi-Shift Operations**: Restore 8 hours per shift, resume next day
2. **Partial Restoration**: Restore only last week's data
3. **Throttled Production**: Minimize impact during business hours
4. **Scheduled Maintenance**: Pause/resume across maintenance windows

### Time-Based Filtering

Filter mappings by creation date using `--date-range` flag.

#### Syntax

```bash
--date-range "START_DATE:END_DATE"
# Format: YYYY-MM-DD:YYYY-MM-DD (inclusive range)
```

#### Example: Restore Last Week Only

```bash
# Restore mappings created between April 6-13, 2026
python desanitize_direct.py \
  --database \
  --date-range "2026-04-06:2026-04-13" \
  --execute
```

#### Example: Restore Specific Month

```bash
# Restore all March 2026 data
python desanitize_direct.py \
  --table Customers \
  --table-only \
  --date-range "2026-03-01:2026-03-31" \
  --execute
```

#### Date Range Notes

- Range is **inclusive**: Both start and end dates are included
- Filters by `created_at` column in mapping table (sanitization timestamp)
- Applies to all desanitization levels (record, column, table, database)
- Works with batch filtering: `--batch-id` and `--date-range` can be combined
- Optimized by composite index `IX_token_mappings_created_at`

### Rate Limiting

Add configurable delays between column restorations to reduce database load.

#### Syntax

```bash
--rate-limit MILLISECONDS
# Default: 0 (no rate limiting)
# Typical production values: 100-5000ms
```

#### Example: Throttled Restoration (1 second delay)

```bash
# Restore with 1-second delay between columns
python desanitize_direct.py \
  --database \
  --rate-limit 1000 \
  --execute
```

#### Example: Conservative Production Restore (5 second delay)

```bash
# Very slow restoration for minimal impact
python desanitize_direct.py \
  --table Orders \
  --table-only \
  --rate-limit 5000 \
  --execute
```

#### Rate Limiting Notes

- Delay applied **after each column** restoration completes
- Does **not** delay on the last column (optimization)
- Warning displayed on every progress message when active
- Increases total execution time linearly with delay value
- Use `--dry-run` to estimate total time before committing

### Progress Tracking & ETA

Incremental operations display enhanced progress information.

#### Progress Update Frequency

- **Every 10 tables**: Brief progress update with ETA
- **Hourly**: Detailed summary with metrics
- **Per table**: Completion confirmation with row counts

#### Example Output

```
[DESAN-...] Progress: 10/50 tables (20.0%), ETA: 2026-04-13 18:45 (4.1h remaining)
[DESAN-...] ✓ [dbo].[Orders] completed: 12,543 record(s) restored
⚠️ Rate limiting active: Waiting 1.000s before next column

[DESAN-...] === HOURLY PROGRESS REPORT ===
  Tables processed: 15/50 (30.0%)
  Records restored: 1,234,567
  Elapsed time: 2.50 hours
  Estimated remaining: 5.83 hours
  Estimated completion: 2026-04-14 02:15 (5.8 hours remaining)
  Success: 15, Failed: 0
```

### Multi-Shift Workflow Example

Restore large database over 3 shifts using checkpoints and rate limiting.

#### Shift 1 (8am-4pm): Start Operation

```bash
# Start database restoration with rate limiting
python desanitize_direct.py \
  --database \
  --rate-limit 500 \
  --execute \
  --yes
  
# Run for 8 hours, then Ctrl+C to stop gracefully
# Operation ID logged: DESAN-20260413080000-abc12345
```

#### Shift 2 (8am next day): Resume Operation

```bash
# Resume from yesterday's checkpoint
python desanitize_direct.py \
  --database \
  --resume DESAN-20260413080000-abc12345 \
  --rate-limit 500 \
  --execute \
  --yes
  
# Continue for another 8 hours...
```

#### Shift 3: Complete Restoration

```bash
# Resume again if needed
python desanitize_direct.py \
  --database \
  --resume DESAN-20260413080000-abc12345 \
  --execute \
  --yes
  
# Completion message: "Database desanitization completed: 50/50 tables"
```

### Combining Features

Rate limiting, date ranges, batch filtering, and checkpoints work together.

#### Example: Incremental + Filtered + Throttled

```bash
# Restore last month's data for specific batch, throttled for production
python desanitize_direct.py \
  --database \
  --date-range "2026-03-01:2026-03-31" \
  --batch-id "BATCH-20260315-xyz" \
  --rate-limit 1000 \
  --schema-filter dbo \
  --execute
```

### Performance Considerations

#### Composite Index

Time-based filtering requires the `IX_token_mappings_created_at` index for optimal performance:

```bash
# Run this SQL script once to create the index
sqlcmd -S YourServer -d YourDatabase -i scripts/add_created_at_index.sql
```

**Performance Impact:**
- Index creation: ~1-2 seconds per 100K rows
- Query speedup: 10-100x for date range queries
- Storage overhead: ~5-10% of table size

#### Rate Limiting Impact

- **No rate limiting** (`--rate-limit 0`): Fastest restoration
- **100ms delay**: ~6 minute overhead per 1000 columns
- **1000ms delay**: ~16 minute overhead per 1000 columns
- **5000ms delay**: ~83 minute overhead per 1000 columns

**Recommendation:** Start with `--rate-limit 500` for production, adjust based on system load.

### Troubleshooting

#### "No mappings found for date range"

- **Cause**: Date range excludes all mappings for requested scope
- **Solution**: Verify date range with `--list-batches` to see available batches
- **Check**: `SELECT MIN(created_at), MAX(created_at) FROM token_mappings`

#### Rate limiting too slow / too fast

- **Too slow**: Reduce `--rate-limit` value or remove flag
- **Too fast**: Increase `--rate-limit` to reduce system impact
- **Monitor**: Check database CPU/IO metrics during restoration

#### Checkpoint resume with different date range

- **Not supported**: Date range is immutable for resumed operations
- **Workaround**: Clear old checkpoint and start fresh operation
- **Command**: `python desanitize_direct.py --clear-stale-checkpoints`

---

## Next Steps

- **Story 2.2**: Column-level batch desanitization (restore entire columns)
- **Story 2.3**: Table-level restoration (restore all PII in a table)
- **Story 2.4**: Database-level restoration (full database desanitization)

For more information, see:
- [User Stories](USER_STORIES_DESANITIZATION.md)
- [Requirements](Requirement/desanitization_requirement.md)
- [API Documentation](../desanitization/)
