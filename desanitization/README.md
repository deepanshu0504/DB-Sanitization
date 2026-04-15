# Desanitization Module

Python module for reversing database sanitization operations by restoring original values from masked data using stored mapping tables.

## Overview

The `desanitization` module provides a comprehensive framework for safely restoring sanitized database records to their original state. It integrates with the mapping infrastructure created during sanitization to enable selective, auditable data restoration.

## Installation

```python
# The module is part of the DB-Sanitization package
from desanitization import DesanitizationEngine
from desanitization.exceptions import DesanitizationError
```

## Quick Start

```python
import pyodbc
from desanitization import DesanitizationEngine
from mapping.mapping_table_manager import MappingTableManager
from database.schema_inspector import SchemaInspector

# Connect to database
conn_string = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=MyDB;Trusted_Connection=yes;"
conn = pyodbc.connect(conn_string)
conn.autocommit = False

# Initialize engine
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
    dry_run=False  # Set to True for preview
)

print(f"✓ Restored {report.records_restored} records")
conn.close()
```

## Core Classes

### DesanitizationEngine

Main engine for performing desanitization operations.

#### Constructor

```python
DesanitizationEngine(
    connection,              # pyodbc connection with autocommit=False
    mapping_manager,         # MappingTableManager instance
    schema_inspector,        # SchemaInspector instance
    logger=None             # Optional logger (creates default if not provided)
)
```

#### Methods

##### `desanitize_records()`

Restore original values for specific records in a table.

```python
report = engine.desanitize_records(
    table: str,                      # Table name (required)
    record_ids: List[str],           # List of record IDs (required)
    schema: str = 'dbo',             # Database schema
    batch_id: Optional[str] = None,  # Filter by batch ID
    dry_run: bool = True,            # Preview mode (safe default)
    skip_missing: bool = False       # Skip records without mappings
) -> RestorationReport
```

**Parameters:**
- `table`: Name of table to restore
- `record_ids`: List of primary key values as strings (for composite PKs, use JSON format)
- `schema`: Database schema (default: 'dbo')
- `batch_id`: Optional filter to restore only mappings from specific sanitization batch
- `dry_run`: If True, preview changes without committing (default: True for safety)
- `skip_missing`: If True, skip records without mappings instead of raising error

**Returns:** `RestorationReport` object with operation results

**Raises:**
- `PreconditionError`: Setup validation failed (mapping table missing, table doesn't exist, etc.)
- `MappingNotFoundError`: Required mappings not found (unless skip_missing=True)
- `RestorationError`: Database update operation failed
- `ValidationError`: Post-restoration validation failed

**Example:**
```python
# Basic usage
report = engine.desanitize_records(
    table='Users',
    record_ids=['U001', 'U002'],
    dry_run=False
)

# With batch filtering
report = engine.desanitize_records(
    table='Orders',
    record_ids=['ORD-123'],
    batch_id='BATCH-20260409-ABC123',
    dry_run=False
)

# Skip missing mappings
report = engine.desanitize_records(
    table='Products',
    record_ids=['P001', 'P002', 'P999'],  # P999 might not exist
    skip_missing=True,
    dry_run=False
)
```

### RestorationReport

Data class containing desanitization operation results.

#### Attributes

```python
operation_id: str           # Unique operation identifier
start_time: datetime        # Operation start timestamp
end_time: datetime         # Operation end timestamp
tables_affected: int       # Number of tables processed
columns_affected: int      # Number of columns restored
records_requested: int     # Number of records requested
records_restored: int      # Number of records actually restored
mappings_applied: int      # Total mappings applied
errors: List[str]          # List of error messages
warnings: List[str]        # List of warning messages
table_details: Dict        # Per-table, per-column restoration counts
dry_run: bool             # Whether this was a dry-run
```

#### Methods

```python
# Convert report to dictionary (for JSON serialization)
report_dict = report.to_dict()

# Add table-level details
report.add_table_detail(table='Users', column='Email', rows_affected=5)
```

**Example:**
```python
# Access report data
print(f"Operation: {report.operation_id}")
print(f"Duration: {(report.end_time - report.start_time).total_seconds():.2f}s")
print(f"Records restored: {report.records_restored}/{report.records_requested}")

# Check for issues
if report.errors:
    print(f"Errors: {', '.join(report.errors)}")
if report.warnings:
    print(f"Warnings: {', '.join(report.warnings)}")

# Table-level details
for table, columns in report.table_details.items():
    for column, count in columns.items():
        print(f"  {table}.{column}: {count} rows")

# Export to JSON
import json
with open('report.json', 'w') as f:
    json.dump(report.to_dict(), f, indent=2)
```

### RestorationRecord

Internal data class representing a single restoration operation.

```python
@dataclass
class RestorationRecord:
    table_name: str
    column_name: str
    record_id: str
    original_value: Optional[str]
    masked_value: Optional[str]
```

## Exception Hierarchy

```
DesanitizationError (base)
├── PreconditionError          # Setup/validation failures
├── MappingNotFoundError       # Missing mapping data
├── ValidationError            # Data validation failures
└── RestorationError           # Update execution failures
```

### Exception Usage

```python
from desanitization.exceptions import (
    DesanitizationError,
    MappingNotFoundError,
    PreconditionError,
    RestorationError,
    ValidationError
)

try:
    report = engine.desanitize_records(...)
    
except MappingNotFoundError as e:
    print(f"Missing mappings for: {e.missing_records}")
    print(f"Suggestion: {e.suggested_action}")

except PreconditionError as e:
    print(f"Setup error: {e.message}")
    print(f"Action: {e.suggested_action}")

except RestorationError as e:
    print(f"Database error: {e}")
    if e.table and e.column:
        print(f"Location: {e.table}.{e.column}")

except DesanitizationError as e:
    print(f"General error: {e}")
```

## Advanced Usage

### Composite Primary Keys

For tables with composite primary keys, use JSON format for record IDs:

```python
# Table: OrderDetails with PK (CustomerID, OrderID)
report = engine.desanitize_records(
    table='OrderDetails',
    record_ids=[
        '{"CustomerID": "C123", "OrderID": "O456"}',
        '{"CustomerID": "C124", "OrderID": "O457"}'
    ],
    dry_run=False
)
```

The engine automatically handles JSON deserialization and builds appropriate WHERE clauses.

### NULL Value Restoration

NULL values are correctly restored (not as string tokens):

```python
# Original: NULL → Sanitized: '[NULL_TOKEN]' → Restored: NULL
report = engine.desanitize_records(
    table='Users',
    record_ids=['U001'],  # Has NULL middle name
    dry_run=False
)
# Result: MiddleName column contains database NULL, not '[NULL_TOKEN]' string
```

### Custom Logging

```python
import logging

# Create custom logger
logger = logging.getLogger('my_app.desanitization')
logger.setLevel(logging.DEBUG)

handler = logging.FileHandler('desanitization.log')
handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
logger.addHandler(handler)

# Pass to engine
engine = DesanitizationEngine(
    connection=conn,
    mapping_manager=mapping_manager,
    schema_inspector=schema_inspector,
    logger=logger
)
```

### Transaction Control

The engine requires explicit transaction control:

```python
# CORRECT: Manual transaction control
conn = pyodbc.connect(conn_string)
conn.autocommit = False  # Required!

try:
    report = engine.desanitize_records(...)
    # Engine commits internally if dry_run=False
    # Or handle commit externally if needed
except Exception as e:
    conn.rollback()  # Engine also rolls back internally
    raise
finally:
    conn.close()
```

## Performance Considerations

- **Batch Processing**: Operations are batched by column for efficiency
- **Temp Tables**: Uses SQL Server temp tables with UPDATE-JOIN pattern
- **Indexing**: Ensure mapping table has index on `record_id` for fast lookups
- **Connection Pooling**: Reuse connections when processing multiple batches

## Best Practices

1. **Always Preview First**: Use `dry_run=True` (default) to preview changes before committing
2. **Batch Records**: Group related record IDs into single operation for efficiency
3. **Handle Missing Mappings**: Use `skip_missing=True` for graceful partial restoration
4. **Filter by Batch**: Use `batch_id` parameter to restore only specific sanitization runs
5. **Save Reports**: Export reports to JSON for audit trails and compliance
6. **Test on Non-Prod**: Validate workflow on test database before production use

## Testing

```bash
# Run unit tests
pytest tests/test_desanitization_engine.py -v

# Run integration tests (requires test database)
pytest tests/test_record_desanitization_integration.py -v

# Run specific test
pytest tests/test_desanitization_engine.py::TestDesanitizationEngine::test_validate_preconditions -v
```

## CLI Usage

For command-line usage, see:
```bash
python desanitize_direct.py --help
```

Or refer to the [Desanitization Guide](../docs/DESANITIZATION_GUIDE.md).

## Documentation

- **User Guide**: [docs/DESANITIZATION_GUIDE.md](../docs/DESANITIZATION_GUIDE.md)
- **User Stories**: [docs/USER_STORIES_DESANITIZATION.md](../docs/USER_STORIES_DESANITIZATION.md)
- **Requirements**: [docs/Requirement/desanitization_requirement.md](../docs/Requirement/desanitization_requirement.md)

## Version History

- **1.0.0** (2026-04-09): Initial release with record-level desanitization (Story 2.1)

## License

Part of the Database Sanitization Framework.

## Support

For issues, questions, or contributions, see project documentation.
