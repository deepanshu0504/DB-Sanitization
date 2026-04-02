# Database Sanitization Framework - User Stories

## Overview
This document contains 28 user stories across 6 phases for building a domain-agnostic SQL Server database sanitization framework in Python.

**Status Legend**: ⬜ Not Started | 🟦 In Progress | ✅ Completed

---

## PHASE 1: Foundation & Infrastructure (5 Stories)

### Story 1.1: Database Connection Manager
**Status**: ✅ Completed  
**Priority**: CRITICAL  
**Estimated Effort**: 1-2 days

**User Story**:  
As a developer, I want a robust SQL Server connection manager so that I can reliably connect to databases with retry logic and connection pooling.

**Acceptance Criteria**:
- ✅ Supports both SQL Server Authentication and Windows Authentication
- ✅ Implements exponential backoff retry (3 attempts: 1s, 2s, 4s delays)
- ✅ Connection pooling to minimize overhead
- ✅ Graceful timeout handling (30s default, configurable)
- ✅ Health check before executing queries
- ✅ Context manager for automatic cleanup
- ✅ No credentials logged

**Technical Details**:
- **File**: `src/database/connection_manager.py`
- **Dependencies**: pyodbc
- **Key Methods**: `connect()`, `execute_query()`, `execute_batch()`, `health_check()`

**Edge Cases**:
- Network partitions during long-running operations
- SQL Server in single-user mode
- TLS/SSL certificate validation failures
- Connection pool exhaustion

---

### Story 1.2: Configuration Management System
**Status**: ✅ Completed  
**Priority**: CRITICAL  
**Estimated Effort**: 1 day

**User Story**:  
As a developer, I want a typed configuration system so that I can manage settings from files, environment variables, and user input.

**Acceptance Criteria**:
- ✅ Load from JSON files (schema config, PII config)
- ✅ Override with environment variables (DB credentials)
- ✅ Validate configuration with Pydantic models
- ✅ Clear error messages for missing/invalid config
- ✅ Support multiple environments (dev, staging, prod)

**Technical Details**:
- **Files**: `src/config/config_models.py`, `src/config/config_loader.py`
- **Dependencies**: pydantic, python-dotenv
- **Config Models**: `DatabaseConfig`, `PIIColumnConfig`, `PIIConfig`, `SanitizationConfig`

**Implementation Summary**:
- ✅ Pydantic-based models with comprehensive validation
- ✅ ConfigLoader with JSON parsing and env var overrides
- ✅ Thread-safe singleton pattern with caching
- ✅ 75 unit tests + 11 integration tests (97% coverage)
- ✅ Example config files and documentation
- ✅ Environment variable pattern: `SANITIZATION_{SECTION}_{KEY}`

**Sample Config Structure**:
```json
{
  "database": {
    "server": "localhost",
    "database": "SanitizationTest",
    "auth_type": "windows",
    "timeout": 30,
    "batch_size": 10000
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

### Story 1.3: Structured Logging Framework
**Status**: ✅ Completed  
**Priority**: HIGH  
**Estimated Effort**: 1 day

**User Story**:  
As a developer, I want a structured logging system so that I can debug issues without exposing PII.

**Acceptance Criteria**:
- ✅ JSON-formatted logs with timestamps, levels, correlation IDs
- ✅ Automatic PII redaction (no raw sensitive data)
- ✅ Configurable log levels (DEBUG, INFO, WARNING, ERROR)
- ✅ File and console output support
- ✅ Correlation IDs for tracing multi-step operations
- ✅ Log rotation (daily, max 10 files)

**Technical Details**:
- **Files**: 
  - `src/logging/log_config.py` - Pydantic configuration models
  - `src/logging/pii_patterns.py` - Compiled regex patterns for PII detection
  - `src/logging/formatters.py` - JSON and colored console formatters
  - `src/logging/filters.py` - PII redaction and correlation filters
  - `src/logging/correlation.py` - Context manager for correlation IDs
  - `src/logging/logger.py` - Singleton logger manager
  - `src/logging/adapter.py` - Convenience logging adapter with helper methods
  - `src/logging/__init__.py` - Module initialization
- **Key Features**: 
  - Thread-safe correlation ID tracking using contextvars
  - Automatic PII redaction for: email, phone, SSN, credit cards, API keys, IP addresses
  - Rotating file handler with size and time-based rotation
  - Colored console output for development
  - Integration with SanitizationConfig

**Implementation Summary**:
- ✅ Complete structured logging framework with 62 unit tests (100% pass rate)
- ✅ JSON formatter for machine-readable logs
- ✅ PII redaction filter with configurable patterns
- ✅ Correlation context manager using contextvars for thread safety
- ✅ Singleton logger manager with configuration support
- ✅ Context logger adapter with convenience methods (log_operation_start, log_operation_end, etc.)
- ✅ TimedOperation context manager for automatic operation timing
- ✅ Updated SanitizationConfig to include logging configuration
- ✅ Updated config example with logging section

**Test Coverage**:
- ✅ 14 tests for formatters (JSON and colored console)
- ✅ 17 tests for filters (PII redaction, correlation, level range)
- ✅ 21 tests for correlation context (including thread isolation)  
- ✅ 10 tests for logger manager (singleton, configuration, handlers)

**PII Redaction Patterns**:
- Emails: `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b` → `***@***`
- Phones: `\d{3}[-.]?\d{3}[-.]?\d{4}` → `***-***-****`
- SSN: `\d{3}-\d{2}-\d{4}` → `***-**-****`
- Credit Cards, API Keys, IP Addresses also supported

---

### Story 1.4: Exception Hierarchy & Error Handling
**Status**: ✅ Completed  
**Priority**: HIGH  
**Estimated Effort**: 0.5 days

**User Story**:  
As a developer, I want a custom exception hierarchy so that I can handle different failure scenarios appropriately.

**Acceptance Criteria**:
- ✅ Base `SanitizationError` exception
- ✅ Specific exceptions for each module
- ✅ Include context (table, column, operation) in exceptions
- ✅ Support error chaining (preserve original exception)
- ✅ Actionable error messages

**Technical Details**:
- **File**: `src/exceptions.py`
- **Exception Classes**:
  - `SanitizationError` (base)
  - `DatabaseConnectionError`
  - `SchemaExtractionError`
  - `AIServiceError`
  - `DataValidationError`
  - `MaskingGenerationError`
  - `ReferentialIntegrityError`
  - `MappingTableError`

**Implementation Summary**:
- ✅ Complete exception hierarchy with 9 exception classes
- ✅ Error codes in `src/error_codes.py` with domain grouping
- ✅ Factory methods for common error scenarios
- ✅ Context enrichment via `add_context()` method
- ✅ Exception chaining via `from_exception()` factory
- ✅ Exception serialization to dict for logging
- ✅ 34 unit tests covering all exception types
- ✅ Comprehensive docstrings and type hints

---

### Story 1.5: Project Structure & Packaging
**Status**: ✅ Completed  
**Priority**: CRITICAL  
**Estimated Effort**: 0.5 days

**User Story**:  
As a developer, I want a well-organized project structure so that code is maintainable and testable.

**Acceptance Criteria**:
- ✅ Standard Python package structure
- ✅ `requirements.txt` with pinned versions
- ✅ `.env.example` template
- ✅ README with setup instructions
- ✅ `.gitignore` for Python/SQL Server

**Implementation Summary**:
- ✅ Complete project structure with src/, tests/, config/, examples/, scripts/
- ✅ Comprehensive requirements.txt with pinned versions (pyodbc, pydantic, pytest, etc.)
- ✅ Environment template at config/.env.example with documentation
- ✅ Detailed README.md with setup instructions, usage examples, configuration guide
- ✅ Complete .gitignore for Python, SQL Server, IDEs, testing artifacts
- ✅ Package structure with __init__.py files and proper exports

**Project Structure**:
```
database-sanitization/
├── src/
│   ├── __init__.py
│   ├── database/
│   ├── config/
│   ├── masking/
│   ├── sanitization/
│   ├── mapping/
│   ├── ai/
│   ├── validation/
│   ├── logging/
│   └── exceptions.py
├── tests/
├── config/
├── scripts/
├── requirements.txt
└── README.md
```

---

## PHASE 2: Database Layer (5 Stories)

### Story 2.1: Schema Metadata Extraction
**Status**: ✅ Completed  
**Priority**: CRITICAL  
**Estimated Effort**: 2 days

**User Story**:  
As a developer, I want to extract complete schema metadata so that I can understand table structures, relationships, and constraints.

**Acceptance Criteria**:
- ✅ Extract all tables with schema names (`[schema].[table]`)
- ✅ Extract columns: data types, lengths, precision, scale, nullability
- ✅ Identify primary keys (including composite keys)
- ✅ Identify foreign keys with parent/child relationships
- ✅ Identify unique constraints and indexes
- ✅ Output as structured JSON
- ✅ Handle special characters in names (proper `[]` escaping)

**Technical Details**:
- **File**: `src/database/schema_extractor.py`
- **System Tables**: `sys.tables`, `sys.columns`, `sys.key_constraints`, `sys.foreign_keys`
- **Key Method**: `extract_schema(database_name) -> Dict`

**Edge Cases**:
- Tables without primary keys
- Composite primary/foreign keys
- Self-referencing foreign keys
- Circular foreign key dependencies
- Schema names with special characters
- Case-sensitive collations

**Implementation Summary**:
- ✅ Complete SchemaExtractor class with 6 extraction methods
- ✅ 46 unit tests covering all functionality and edge cases
- ✅ 10 integration tests with real database validation
- ✅ Comprehensive error handling with custom exceptions
- ✅ Metadata integrity validation with warnings
- ✅ Example script and documentation
- ✅ Handles NVARCHAR character length, VARCHAR(MAX), composite keys
- ✅ Preserves column order for composite PKs/FKs
- ✅ Detects self-referencing and circular dependencies
- ✅ ~900 LOC implementation + ~550 LOC tests
- ✅ Estimated coverage: 95%+

**Dependencies**: Story 1.1 (Connection Manager)

---

### Story 2.2: Foreign Key Dependency Graph Builder
**Status**: ✅ Completed  
**Priority**: CRITICAL  
**Estimated Effort**: 2 days

**User Story**:  
As a developer, I want to build a dependency graph of foreign key relationships so that I can sanitize tables in the correct order without breaking integrity.

**Acceptance Criteria**:
- ✅ Build directed graph of table dependencies
- ✅ Detect circular dependencies using cycle detection algorithm
- ✅ Perform topological sort for processing order
- ✅ Identify self-referencing tables
- ✅ Support composite foreign keys
- ✅ Return processing order and cycle information

**Technical Details**:
- **File**: `src/sanitization/dependency_resolver.py`
- **Graph Library**: networkx 3.2.1 (Johnson's algorithm for cycles, Kahn's for topological sort)
- **Algorithms**: `nx.simple_cycles()`, `nx.topological_sort()`, `nx.strongly_connected_components()`
- **Key Methods**: `get_processing_order()`, `get_cycles()`, `has_circular_dependencies()`, `get_dependencies(table)`, `is_self_referencing(table)`

**Edge Cases**:
- Circular dependencies (Order → OrderItem → Promotion → Order)
- Self-referencing hierarchies (Employee.ManagerID → Employee.EmployeeID)
- Multi-level dependencies (A → B → C → D)
- Orphaned tables (no FKs)
- Multiple FKs between same tables

**Implementation Summary**:
- ✅ Complete DependencyResolver class using networkx DiGraph
- ✅ Graph construction from FK metadata with composite FK support (groups by constraint_name)
- ✅ Cycle detection using Johnson's algorithm (O(V + E + C) complexity)
- ✅ Topological sort using Kahn's algorithm (O(V + E) complexity)
- ✅ Self-referencing table identification (separate from circular dependencies)
- ✅ Caching of cycle detection and processing order results for performance
- ✅ Comprehensive logging with correlation IDs and graph statistics
- ✅ 25 unit tests covering all scenarios (simple DAG, circular, self-ref, composite FK, deep chains, edge cases)
- ✅ 5 integration tests with real database schema creation and FK validation
- ✅ CircularDependencyError exception with detailed cycle information and mitigation suggestions
- ✅ Graph summary method with root/leaf tables, max depth, cycle count
- ✅ Dependency depth calculation for multi-level hierarchies
- ✅ Usage example demonstrating end-to-end workflow
- ✅ ~500 LOC implementation + ~450 LOC unit tests + ~250 LOC integration tests
- ✅ Added error codes: CIRCULAR_DEPENDENCY, INVALID_DEPENDENCY_GRAPH, TOPOLOGICAL_SORT_FAILED

**Strategy for Circular FKs**:
- Raise `CircularDependencyError` with full cycle path and suggested mitigations
- Let orchestrator (Story 5.2) decide: (1) disable constraints, (2) multi-stage processing, or (3) exclude tables
- Self-referencing tables flagged separately for special handling

**Dependencies**: Story 2.1 (Schema Extraction)

---

### Story 2.3: Batch Data Extractor
**Status**: ✅ Completed  
**Priority**: CRITICAL  
**Estimated Effort**: 2 days

**User Story**:  
As a developer, I want to extract data in batches so that I can process large tables without memory overflow.

**Acceptance Criteria**:
- ✅ Key-based pagination (O(log n) performance)
- ✅ Fallback to OFFSET/FETCH for tables without numeric PKs
- ✅ Configurable batch size (default 10,000 rows)
- ✅ Memory-efficient iterator pattern (yield)
- ✅ Extract only PII columns (not full rows)
- ✅ Progress tracking (rows processed / total)
- ✅ Handle composite primary keys

**Technical Details**:
- **File**: `src/database/batch_extractor.py`
- **Key Method**: `extract_batches(table, columns, batch_size) -> Iterator`

**Implementation Summary**:
- ✅ Complete BatchExtractor class with 3 pagination strategies (~800 LOC)
- ✅ PaginationStrategy enum (KEY_BASED, COMPOSITE_KEY, ROW_NUMBER)
- ✅ Batch dataclass with progress tracking and metadata
- ✅ Automatic strategy selection based on PK type
- ✅ 38 unit tests covering all scenarios and edge cases (~700 LOC)
- ✅ Comprehensive error handling with DataExtractionError
- ✅ Usage example demonstrating 6 common scenarios
- ✅ SQL identifier escaping for special characters
- ✅ Integration with existing ConnectionManager and SchemaExtractor
- ✅ Structured logging with correlation IDs
- ✅ NULL value handling in PII columns
- ✅ Non-dbo schema support with fully qualified names

**Pagination Strategy**:
```sql
-- Key-based (FAST - preferred)
SELECT pk, pii_col1, pii_col2
FROM [schema].[table]
WHERE pk > @last_pk
ORDER BY pk
OFFSET 0 ROWS FETCH NEXT @batch_size ROWS ONLY;

-- For composite PKs or no PK
SELECT ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) as rn, *
FROM [schema].[table]
WHERE rn > @last_rn AND rn <= @last_rn + @batch_size;
```

**Edge Cases**:
- Tables without primary keys
- Composite primary keys (multi-column ordering)
- Non-sequential primary keys (GUIDs, strings)
- Tables with gaps in PK sequence
- Concurrent modifications during extraction

**Dependencies**: Story 1.1 (Connection Manager), Story 2.1 (Schema Extraction)

---

### Story 2.4: Batch Data Updater
**Status**: ✅ Completed  
**Priority**: CRITICAL  
**Estimated Effort**: 1.5 days

**User Story**:  
As a developer, I want to update PII values in batches so that I can efficiently sanitize large datasets.

**Acceptance Criteria**:
- ✅ Batch updates using `executemany` or bulk operations
- ✅ Transactional updates (commit/rollback per batch)
- ✅ Support updating multiple columns simultaneously
- ✅ Preserve data types during updates
- ✅ Handle deadlocks with retry logic (SQL error 1205)
- ✅ Parameterized queries (prevent SQL injection)

**Technical Details**:
- **File**: `src/database/batch_updater.py`
- **Key Method**: `update_batches(schema, table, pk_columns, updates) -> Iterator[UpdateBatch]`

**Implementation Summary**:
- ✅ Complete BatchUpdater class with 3 update strategies (~1025 LOC)
- ✅ UpdateStrategy enum (KEY_BASED, COMPOSITE_KEY, ROW_NUMBER)
- ✅ UpdateBatch dataclass with progress tracking and metadata
- ✅ Automatic strategy selection based on PK type
- ✅ 32 unit tests covering all scenarios and edge cases (~719 LOC)
- ✅ Deadlock retry decorator with exponential backoff
- ✅ Transaction safety with automatic commit/rollback per batch
- ✅ FK dependency ordering integration with DependencyResolver
- ✅ DataUpdateError exception with detailed context
- ✅ SQL identifier escaping for special characters
- ✅ Integration with existing ConnectionManager and SchemaExtractor
- ✅ Structured logging with correlation IDs
- ✅ Multi-column updates with parameterized queries
- ⚠️ Integration tests pending

**Update Strategy**:
```python
# Key-based (FAST - preferred for single numeric PK)
UPDATE [schema].[table]
SET [col1] = ?, [col2] = ?
WHERE [pk] = ?

# Composite key (for multi-column PKs)
UPDATE [schema].[table]
SET [col1] = ?, [col2] = ?
WHERE [pk1] = ? AND [pk2] = ?
```

**Edge Cases**:
- Deadlocks during concurrent updates (retry with exponential backoff)
- Long-running transactions causing blocking
- FK constraint violations (must update parent first - auto-ordered)
- Triggers that modify data
- Computed columns (read-only)
- Indexed columns (update performance impact)
- Tables without primary keys (ROW_NUMBER fallback)
- Composite primary keys (tuple-based updates)

**Optimization**:
- Batch updates with configurable batch size (default: 10,000)
- FK-aware ordering to minimize constraint violations
- Parameterized queries for performance
- Progress tracking with yield-based iteration
- Memory-efficient (never loads full dataset)

**Dependencies**: Story 1.1 (Connection Manager), Story 2.1 (Schema Extraction), Story 2.2 (Dependency Resolver)

---

### Story 2.5: Transaction & Rollback Manager
**Status**: ✅ Completed  
**Priority**: HIGH  
**Estimated Effort**: 1 day

**User Story**:  
As a developer, I want transaction management with rollback capability so that I can recover from failures without data corruption.

**Acceptance Criteria**:
- ✅ Begin/commit/rollback transactions
- ✅ Savepoint support for nested operations
- ✅ Automatic rollback on exceptions
- ✅ Context manager pattern for clean syntax
- ✅ Audit trail of all transactions

**Technical Details**:
- **File**: `src/database/transaction_manager.py`
- **Key Methods**: `begin()`, `commit()`, `rollback()`, `begin_savepoint()`, `rollback_to_savepoint()`
- **Pattern**: Context manager (`with transaction_manager.begin()`)

**Implementation Summary**:
- ✅ Complete TransactionManager class with savepoint support (~647 LOC)
- ✅ IsolationLevel enum (READ_UNCOMMITTED, READ_COMMITTED, REPEATABLE_READ, SERIALIZABLE, SNAPSHOT)
- ✅ TransactionAudit dataclass for complete lifecycle tracking
- ✅ Context manager pattern for automatic commit/rollback
- ✅ Nested transaction support via SQL Server savepoints (up to 32 levels)
- ✅ Rollback hooks for compensation logic (LIFO execution)
- ✅ Configurable transaction timeout with automatic rollback
- ✅ Thread-safe state management with threading.Lock
- ✅ Audit history with configurable retention (default: 1000 transactions)
- ✅ TransactionError exception with detailed context
- ✅ Structured logging with correlation IDs
- ✅ Integration with ConnectionManager
- ✅ Savepoint name validation (alphanumeric + underscore only)
- ⚠️ Unit tests pending
- ⚠️ Integration tests pending

**Usage Example**:
```python
with transaction_manager.begin():
    # Operations auto-commit on success
    # Auto-rollback on exception
    updater.update_batch(table, data)

# Nested transactions with savepoints
with transaction_manager.begin():
    updater.update_batch(table1, data1)
    with transaction_manager.begin():  # Creates savepoint
        updater.update_batch(table2, data2)
        # Auto-rolls back to savepoint on exception
```

**Edge Cases**:
- Nested transactions (uses savepoints, max depth: 32)
- Distributed transactions (not supported - single DB only)
- Long-running transactions timing out (configurable timeout)
- Connection failures mid-transaction (automatic rollback)
- Invalid savepoint names (validated against pattern)
- Savepoint depth exceeded (raises TransactionError)
- Concurrent transaction state access (thread-safe with locks)

**Dependencies**: Story 1.1 (Connection Manager), Story 1.3 (Logging)

---

## PHASE 3: AI Integration & User Interaction (3 Stories)

### Story 3.1: GitHub Copilot API Client
**Status**: ✅ Completed  
**Priority**: HIGH  
**Estimated Effort**: 1.5 days

**User Story**:  
As a developer, I want to integrate with GitHub Copilot API so that I can automatically detect PII columns.

**Acceptance Criteria**:
- ✅ Send schema metadata JSON to Copilot API
- ✅ Parse AI response for PII recommendations
- ✅ Handle API failures gracefully (retry, fallback)
- ✅ Rate limiting and quota management
- ✅ Secure API authentication (env variables)
- ✅ Cache responses to avoid duplicate API calls

**Technical Details**:
- **File**: `src/ai/copilot_client.py`
- **API**: GitHub Copilot Model API
- **Key Method**: `detect_pii(schema_json) -> List[PIIColumn]`

**Implementation Summary**:
- ✅ Complete CopilotClient class with retry logic and caching (~700 LOC)
- ✅ Pydantic models for request/response validation (PIIColumn, PIIDetectionResponse)
- ✅ Prompt engineering templates with few-shot examples
- ✅ Exponential backoff retry decorator handling timeouts, network errors, rate limits
- ✅ Response caching with SHA256 key generation and TTL expiration
- ✅ Batch processing for large schemas (50 tables per request)
- ✅ AIConfig model integrated into SanitizationConfig
- ✅ Environment-based API key authentication (GITHUB_COPILOT_API_KEY)
- ✅ 40+ unit tests covering retry logic, caching, error handling, edge cases
- ✅ 10 integration tests with workflow validation
- ✅ Example script demonstrating end-to-end usage
- ✅ ~2000 LOC implementation + tests + examples
- ✅ Error codes: AI_API_REQUEST_FAILED, AI_API_TIMEOUT, AI_API_QUOTA_EXCEEDED, AI_AUTH_FAILED, AI_NETWORK_ERROR, AI_INVALID_RESPONSE
- ✅ Exception classes: AIServiceError, APIRequestError, APIResponseError

**Prompt Template**:
```
Analyze this database schema and identify columns that likely contain PII.
For each PII column, specify the type (email, phone, name, ssn, etc.).

Schema:
{schema_json}

Return JSON format:
{
  "pii_columns": [
    {"schema": "dbo", "table": "Customers", "column": "Email", "pii_type": "email"},
    ...
  ]
}
```

**Edge Cases**:
- API quota exceeded (429 error)
- Network timeouts
- Invalid JSON responses
- Ambiguous column names ("Data", "Info")
- False positives ("EmailTemplate" is not PII)

**Dependencies**: Story 2.1 (Schema Extraction)

---

### Story 3.2: User Review Interface (CLI)
**Status**: ✅ Completed  
**Priority**: HIGH  
**Estimated Effort**: 1 day

**User Story**:  
As a user, I want to review and modify AI-detected PII columns so that I can ensure accuracy before sanitization.

**Acceptance Criteria**:
- ✅ Display AI recommendations in formatted table
- ✅ Allow adding new PII columns
- ✅ Allow removing false positives
- ✅ Allow changing PII type (email → phone)
- ✅ Validate columns exist in schema
- ✅ Save finalized config to JSON

**Technical Details**:
- **File**: `src/ui/review_cli.py`
- **Library**: `rich` for formatted tables
- **Output**: `config/pii_config.json`

**Implementation Summary**:
- ✅ PIIReviewCLI class with interactive menu-driven interface
- ✅ Rich terminal formatting with tables, panels, and color coding
- ✅ Add, remove, modify operations with validation
- ✅ Undo functionality for all operations
- ✅ Schema validation with FK/PK warnings
- ✅ Configuration persistence to JSON
- ✅ 50+ unit tests + 15 integration tests
- ✅ Comprehensive example script (examples/review_cli_example.py)

**CLI Interface**:
```
AI Recommended PII Columns:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Schema.Table          Column        Type
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
dbo.Customers         Email         email
dbo.Customers         Phone         phone
dbo.Employees         SSN           ssn

Options:
[A]dd  [R]emove  [M]odify  [S]ave  [Q]uit
```

**Dependencies**: Story 3.1 (AI Client), Story 2.1 (Schema Extraction)

---

### Story 3.3: Configuration Schema Validator
**Status**: ✅ Completed  
**Priority**: MEDIUM  
**Estimated Effort**: 1 day

**User Story**:  
As a developer, I want to validate PII configuration files so that I catch errors before sanitization begins.

**Acceptance Criteria**:
- ✅ Validate JSON structure with Pydantic
- ✅ Check all columns exist in database
- ✅ Verify data types compatible with masking strategy
- ✅ Warn about missing nullable constraints
- ✅ Validate FK dependencies
- ✅ Clear error messages for validation failures

**Implementation Details**:
- **Files**: 
  - `src/validation/validation_result.py` (ValidationResult, ValidationIssue, IssueSeverity)
  - `src/validation/config_validator.py` (ConfigValidator with comprehensive validation logic)
  - `examples/validate_config_example.py` (Example usage with color-coded output)
  - `tests/unit/test_validation_result.py` (40+ unit tests)
  - `tests/unit/test_config_validator.py` (30+ unit tests)
  - `tests/integration/test_config_validator_integration.py` (Integration tests)
- **Key Methods**: 
  - `ConfigValidator.validate_config(config) -> ValidationResult`
  - `ConfigValidator.validate_single_column(pii_column) -> ValidationResult`
- **Validation Checks**:
  - Column existence (schema, table, column)
  - Data type compatibility (PII type → SQL type mapping)
  - Nullable constraints (config vs database)
  - Special columns (PKs, FKs, identity, computed, system tables, temp tables, views)
  - Column length sufficiency (prevent silent truncation)
- **Error Codes**: Added 16 validation error codes to `error_codes.py`
- **Edge Cases Handled**:
  - System schemas (sys, INFORMATION_SCHEMA)
  - Temp tables (# prefix)
  - Identity and computed columns
  - Insufficient column lengths
  - CHAR vs VARCHAR warnings

**Pydantic Model**:
```python
class PIIColumn(BaseModel):
    schema: str
    table: str
    column: str
    pii_type: Literal["email", "phone", "name", "ssn", "generic"]
    nullable: bool
    custom_format: Optional[str] = None
```

**Dependencies**: Story 1.2 (Config Management), Story 2.1 (Schema Extraction)

---

## PHASE 4: Data Masking Engine (6 Stories)

### Story 4.1: Base Masker Abstract Class
**Status**: ✅ Completed  
**Priority**: CRITICAL  
**Estimated Effort**: 1 day

**User Story**:  
As a developer, I want a base masker interface so that I can implement consistent masking strategies.

**Acceptance Criteria**:
- ✅ Abstract `mask()` method
- ✅ Deterministic masking (same input → same output)
- ✅ Type safety with data type validation
- ✅ Length constraint enforcement
- ✅ Null handling strategy (preserve/mask/randomize)

**Technical Details**:
- **File**: `src/masking/base_masker.py`
- **Pattern**: Abstract Base Class (ABC)
- **Key Methods**: `mask()`, `_get_deterministic_seed()`, `_validate_length()`, `_handle_null()`

**Implementation Summary**:
- ✅ Complete BaseMasker abstract base class (~440 LOC)
- ✅ MaskingStrategy enum (PRESERVE, MASK, RANDOMIZE)
- ✅ ColumnInfo dataclass with comprehensive SQL Server type metadata
- ✅ SHA256-based deterministic seed generation
- ✅ Intelligent length validation with Unicode awareness
- ✅ Data type validation before returning values
- ✅ NULL handling with configurable strategy
- ✅ Fixed-length column padding (CHAR, NCHAR)
- ✅ VARCHAR(MAX) support with reasonable defaults
- ✅ MaskingError exception with detailed context
- ✅ 54 unit tests covering all functionality
- ✅ Comprehensive logging with correlation IDs
- ✅ Integration with SchemaExtractor metadata
- ✅ Support for NVARCHAR character length vs byte length

**Interface**:
```python
class BaseMasker(ABC):
    def __init__(
        self, 
        seed: int = 42,
        null_strategy: MaskingStrategy = MaskingStrategy.PRESERVE,
        logger: Optional[logging.Logger] = None
    ):
        self.seed = seed
        self.null_strategy = null_strategy
        self.logger = logger or get_logger(self.__class__.__name__)
    
    @abstractmethod
    def mask(self, value: Any, column_info: ColumnInfo) -> Any:
        """Mask a single value deterministically."""
        pass
    
    def _get_deterministic_seed(self, value: Any) -> int:
        """Generate deterministic seed using SHA256 hash."""
        pass
    
    def _validate_length(self, value: str, column_info: ColumnInfo) -> str:
        """Validate and truncate to max_length with Unicode awareness."""
        pass
    
    def _handle_null(self, value: Any, column_info: ColumnInfo) -> Any:
        """Handle NULL values based on null_strategy."""
        pass
```

**Determinism**: SHA256 hash of original value combined with global seed ensures same input → same output

---

### Story 4.2: Email Masker
**Status**: ✅ Completed  
**Priority**: HIGH  
**Estimated Effort**: 0.5 days

**User Story**:  
As a developer, I want to mask email addresses so that I can anonymize contact information.

**Acceptance Criteria**:
- ✅ Generate valid email format
- ✅ Preserve domain diversity (not all @example.com)
- ✅ Deterministic (same email → same fake email)
- ✅ Respect max_length constraints
- ✅ Handle international domains

**Technical Details**:
- **File**: `src/masking/email_masker.py`
- **Key Methods**: `mask()`, `_generate_email()`, `_validate_email_format()`, `_select_domain()`
- **Strategy**: Hash email → `user_{hash8}@{domain}` with deterministic domain selection

**Implementation Summary**:
- ✅ Complete EmailMasker class extending BaseMasker (~350 LOC)
- ✅ 10-domain pool for diversity (example.com, test.org, demo.net, sample.io, fake.email, masked.dev, sanitized.app, placeholder.co, dummy.tech, anon.site)
- ✅ Multi-tier length optimization (Standard ~26 chars → Compact ~18 chars → Minimal 6 chars)
- ✅ SHA256-based deterministic seeding from BaseMasker
- ✅ RFC 5322 email format validation
- ✅ 55 unit tests covering all scenarios and edge cases (~560 LOC)
- ✅ Comprehensive example script with 8 scenarios (~280 LOC)
- ✅ Unicode/IDN domain support for NVARCHAR columns
- ✅ VARCHAR vs NVARCHAR handling (ASCII vs Unicode)
- ✅ Fixed-length column padding (CHAR, NCHAR)
- ✅ Special format handling (IP domains, quoted strings, whitespace)
- ✅ NULL handling strategies (PRESERVE, MASK)
- ✅ Integration with BaseMasker interface
- ✅ Deterministic mapping ensures FK integrity

**Domain Pool**:
```python
DOMAINS = [
    "example.com", "test.org", "demo.net", "sample.io",
    "fake.email", "masked.dev", "sanitized.app", "placeholder.co",
    "dummy.tech", "anon.site"
]
```

**Generation Algorithm**:
1. Get deterministic seed from input email
2. Generate username: `user_{hash8}` (8-char hex from seed)
3. Select domain: `DOMAINS[seed % len(DOMAINS)]`
4. Combine: `{username}@{domain}`
5. Optimize length if needed (multi-tier fallback)
6. Validate and return

**Length Optimization**:
- **Standard**: `user_a1b2c3d4@example.com` (~26 chars)
- **Compact**: `u_a1b2c3@demo.co` (~18 chars)
- **Minimal**: `x@y.co` (6 chars minimum)

**Edge Cases Handled**:
- IP address domains: `user@[192.168.1.1]` → replaced with standard domain
- Quoted local-parts: `"user@test"@example.com` → standard format
- Whitespace: Leading/trailing spaces trimmed
- Case sensitivity: Different cases → different hashes → different outputs
- Very long emails: Truncated while preserving `@domain` structure
- Consecutive dots: Masked with warning logged
- Invalid formats: Masked anyway (AI might false-positive detect)
- Unicode characters: Handled for NVARCHAR columns
- NULL values: PRESERVE (returns None) or MASK (generates fake email)

**Example**: 
```python
masker = EmailMasker(seed=42)
col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
masked = masker.mask("john.doe@gmail.com", col)
# Returns: user_a1b2c3d4@example.com (deterministic)
```

**Dependencies**: Story 4.1 (Base Masker)

---

### Story 4.3: Phone Number Masker
**Status**: ✅ Completed  
**Priority**: HIGH  
**Estimated Effort**: 1 day

**User Story**:  
As a developer, I want to mask phone numbers so that I can anonymize telecommunications data.

**Acceptance Criteria**:
- ✅ Generate valid phone formats
- ✅ Multi-tier length optimization (standard, compact, minimal)
- ✅ Deterministic masking
- ✅ Handle various formats (10-digit, +country code, extensions)
- ✅ Respect max_length

**Technical Details**:
- **File**: `src/masking/phone_masker.py`
- **Key Methods**: `mask()`, `_generate_phone()`, `_validate_phone_format()`, `_get_format_tier()`
- **Strategy**: Deterministic digit generation using modulo arithmetic with fixed 555 area code (reserved/fictional)

**Implementation Summary**:
- ✅ Complete PhoneMasker class extending BaseMasker (~470 LOC)
- ✅ Fixed 555 area code (reserved for fictional use in North America)
- ✅ Multi-tier length optimization (Standard 14 chars → Compact 12 → Minimal 10)
- ✅ SHA256-based deterministic seeding from BaseMasker
- ✅ Modulo arithmetic for digit generation (predictable, testable)
- ✅ 61 unit tests covering all scenarios and edge cases (~700 LOC)
- ✅ Comprehensive example script with 9 scenarios including batch masking (~400 LOC)
- ✅ US and international phone format validation
- ✅ VARCHAR vs NVARCHAR handling (ASCII vs Unicode)
- ✅ Fixed-length column padding (CHAR, NCHAR)
- ✅ Special format handling (extensions, international prefixes, invalid formats)
- ✅ NULL handling strategies (PRESERVE, MASK)
- ✅ Integration with BaseMasker interface
- ✅ Deterministic mapping ensures FK integrity

**Phone Format Tiers**:
```python
# Standard (14+ chars): (555) 555-5555
# Compact (12-13 chars): 555-555-5555
# Minimal (10-11 chars): 5555555555
# Error (<10 chars): Raise MaskingError
```

**Generation Algorithm**:
1. Extract deterministic seed from input phone
2. Generate exchange (middle 3 digits): `((seed // 10000) % 900) + 100` (range 100-999)
3. Generate subscriber (last 4 digits): `(seed % 9000) + 1000` (range 1000-9999)
4. Combine with fixed 555 area code
5. Format based on column length constraints
6. Validate and return

**Length Optimization**:
- **Standard**: `(555) 555-5555` (14 characters)
- **Compact**: `555-555-5555` (12 characters)
- **Minimal**: `5555555555` (10 characters)

**Edge Cases Handled**:
- Whitespace: Leading/trailing spaces trimmed
- Extensions: Ignored in masking (e.g., "ext. 123")
- Very long numbers: Truncated to fit column constraints
- International prefixes: Recognized but output uses US format
- Special characters: Stripped from generated output
- Invalid formats: Masked anyway (AI may have false positives)
- Plain digits: Accepted and masked
- NULL values: PRESERVE (returns None) or MASK (generates fake phone)
- Column too short (<10 chars): Raises MaskingError with actionable message

**Supported Input Formats**:
- US standard: `(555) 123-4567`, `555-123-4567`, `555.123.4567`
- Plain digits: `5551234567`
- International: `+1-555-123-4567`, `+44 20 1234 5678`
- With extensions: `555-123-4567 ext. 123` (extension ignored)

**Example**: 
```python
masker = PhoneMasker(seed=42)
col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
masked = masker.mask("(555) 123-4567", col)
# Returns: (555) 512-2345 (deterministic, 14 chars)

compact_col = ColumnInfo(data_type="VARCHAR", max_length=12, nullable=True)
masked_compact = masker.mask("5551234567", compact_col)
# Returns: 555-512-2345 (compact format, 12 chars)
```

**Dependencies**: Story 4.1 (Base Masker)

---

### Story 4.4: Name Masker
**Status**: ✅ Completed  
**Priority**: HIGH  
**Estimated Effort**: 0.5 days

**User Story**:  
As a developer, I want to mask personal names so that I can anonymize identity information.

**Acceptance Criteria**:
- ✅ Generate realistic fake names using Faker library
- ✅ Preserve gender consistency (optional)
- ✅ Deterministic mapping (same name → same fake name)
- ✅ Support first, last, and full names
- ✅ Handle Unicode names (internationalization)

**Technical Details**:
- **File**: `src/masking/name_masker.py`
- **Library**: `faker==19.12.0`
- **Strategy**: Seed Faker with hash of original name for deterministic generation
- **MIN_LENGTH**: 2 characters (supports single-letter names like "Li", "Wu")

**Implementation Summary**:
- ✅ Complete NameMasker class with Faker integration (~570 LOC)
- ✅ Multi-tier length optimization:
  - Full (20+ chars): "Dr. John Smith Jr." with prefix/suffix
  - First+Last (10-19 chars): "John Smith"
  - First Only (4-9 chars): "John"
  - Initial (2-3 chars): "J" or "JS"
- ✅ Name structure detection (prefixes, suffixes, hyphenation)
- ✅ Unicode support for international names (José, François, 李明)
- ✅ Format validation with warning logs for invalid inputs
- ✅ Deterministic seed generation from input hash
- ✅ 61 comprehensive unit tests (100% pass rate)
- ✅ Usage example with 8 practical scenarios
- ✅ MIN_LENGTH validator added to config_validator.py
- ✅ Exported from src/masking/__init__.py

**Test Coverage**:
- ✅ 6 tests for basic masking (deterministic, seed independence)
- ✅ 10 tests for length tiers and boundaries
- ✅ 16 tests for name structure (prefixes, suffixes, hyphenation)
- ✅ 6 tests for data types (VARCHAR, NVARCHAR, CHAR, TEXT)
- ✅ 4 tests for NULL handling strategies
- ✅ 9 tests for validation and error handling
- ✅ 10 tests for edge cases (Unicode, apostrophes, special characters)

**Edge Cases Handled**:
- Hyphenated names (Mary-Jane, Jean-Pierre)
- Prefixes/suffixes (Dr., Mr., Jr., III)
- Names with apostrophes (O'Brien)
- Unicode characters (José García, 李明, 田中)
- Very long names with multiple components
- Invalid formats (logs warning but continues masking)
- Single-letter names at minimum length (2 chars)
- Excessive whitespace trimming

**Dependencies**: Story 4.1 (Base Masker)

---

### Story 4.5: SSN Masker
**Status**: ✅ Completed  
**Priority**: MEDIUM  
**Estimated Effort**: 0.5 days

**User Story**:  
As a developer, I want to mask Social Security Numbers so that I can anonymize government identifiers.

**Acceptance Criteria**:
- ✅ Generate valid SSN format (`XXX-XX-XXXX`)
- ✅ Avoid real SSN ranges (exclude 666, 900+)
- ✅ Deterministic
- ✅ Support plain (9-digit) and formatted versions

**Technical Details**:
- **File**: `src/masking/ssn_masker.py`
- **Valid Ranges**: 001-665, 667-899 (excludes 000, 666, 900-999)
- **Format**: `f"{area:03d}-{group:02d}-{serial:04d}"` (formatted) or plain 9 digits
- **MIN_LENGTH**: 9 characters (plain format)

**Implementation Summary**:
- ✅ Complete SSNMasker class with compliance validation (~380 LOC)
- ✅ Multi-format support:
  - Formatted (11+ chars): "123-45-6789" (XXX-XX-XXXX)
  - Plain (9-10 chars): "123456789" (9 digits)
- ✅ Valid area code generation with gap handling (001-665, 667-899)
- ✅ Modulo arithmetic for deterministic generation
- ✅ Format detection and auto-selection
- ✅ 45 comprehensive unit tests (100% pass rate)
- ✅ Usage example with 8 practical scenarios
- ✅ MIN_LENGTH and data type validators verified in config_validator.py
- ✅ Exported from src/masking/__init__.py

**Test Coverage**:
- ✅ 6 tests for basic masking (deterministic, seed independence)
- ✅ 9 tests for format detection and handling
- ✅ 7 tests for valid SSN ranges (area/group/serial)
- ✅ 5 tests for invalid range exclusion (000, 666, 900-999)
- ✅ 6 tests for data types (VARCHAR, NVARCHAR, CHAR, TEXT)
- ✅ 4 tests for NULL handling strategies
- ✅ 9 tests for validation and error handling
- ✅ 6 tests for edge cases (whitespace, boundaries, distribution)

**Edge Cases Handled**:
- Invalid area codes excluded (000, 666, 900-999) via modulo with gap handling
- Both formatted (XXX-XX-XXXX) and plain (9 digits) input/output formats
- Column too short (<9 chars) raises clear MaskingError
- Invalid format logs warning but continues masking (AI false positives)
- Fixed-length columns (CHAR, NCHAR) padded appropriately
- Whitespace trimming before processing
- Deterministic mapping across both valid ranges (001-665, 667-899)

**Dependencies**: Story 4.1 (Base Masker)

---

### Story 4.6: Generic String Masker
**Status**: ✅ **COMPLETE**  
**Priority**: LOW  
**Estimated Effort**: 0.5 days  
**Actual Effort**: 0.5 days  
**Completed**: 2026-03-26

**User Story**:  
As a developer, I want a fallback masker for unknown PII types so that I can handle custom or miscellaneous fields.

**Acceptance Criteria**:
- ✅ Generate random alphanumeric strings
- ✅ Preserve original length (or respect max_length)
- ✅ Deterministic
- ✅ Support character classes (alpha, numeric, alphanumeric)

**Technical Details**:
- **File**: `src/masking/generic_masker.py` (330 LOC)
- **Tests**: `tests/unit/test_generic_masker.py` (44 tests)
- **Example**: `examples/generic_masking_example.py`
- **Strategy**: Modulo arithmetic for character-by-character generation
- **Character Classes**: alphanumeric (default), alpha, numeric
- **Minimum Length**: 1 (most permissive of all maskers)

**Implementation Notes**:
- Simple length preservation (no multi-tier formatting)
- Supports any string length >= 1
- Deterministic using `(seed + i) % len(charset)`
- Three character sets: ALPHANUMERIC_CHARS (62), ALPHA_CHARS (52), NUMERIC_CHARS (10)
- Ideal for custom PII types, miscellaneous fields, reference codes

**Dependencies**: Story 4.1 (Base Masker)

---

## PHASE 5: Orchestration & Execution (5 Stories)

### Story 5.1: Masking Strategy Factory
**Status**: ✅ **COMPLETE**  
**Priority**: MEDIUM  
**Estimated Effort**: 0.5 days  
**Actual Effort**: 0.5 days  
**Completed**: 2026-03-26

**User Story**:  
As a developer, I want a factory to instantiate maskers so that I can dynamically select strategies based on PII type.

**Acceptance Criteria**:
- ✅ Map PII types to masker classes
- ✅ Support custom maskers via configuration
- ✅ Raise clear errors for unknown types
- ✅ Singleton pattern for masker reuse

**Technical Details**:
- **File**: `src/masking/masker_factory.py` (450 LOC)
- **Tests**: `tests/unit/test_masker_factory.py` (43 tests)
- **Example**: `examples/masker_factory_example.py`
- **Pattern**: Registry + Factory with thread-safe singleton
- **Registry**: Maps 5 built-in PII types to masker classes
- **Caching**: Automatic caching for performance (same config = same instance)
- **Thread Safety**: Double-checked locking pattern for concurrent access

**Implementation Notes**:
- Thread-safe singleton following ConfigLoader pattern
- Cache key includes: pii_type, seed, null_strategy, masker_params
- Supports masker-specific parameters via PIIColumnConfig.custom_format
- GenericMasker character_class extraction: "alpha", "numeric", "alphanumeric"
- Custom masker registration via register_masker() method
- Clear error handling with MaskingError.unsupported_pii_type() and masker_not_found()
- Manual cache clearing for testing/cleanup via clear_cache()

**Registry**:
```python
_registry = {
    "email": EmailMasker,
    "phone": PhoneMasker,
    "name": NameMasker,
    "ssn": SSNMasker,
    "generic": GenericMasker,
}
```

**Dependencies**: Stories 4.1-4.6 (All Maskers)

---

### Story 5.2: Sanitization Orchestrator
**Status**: ✅ COMPLETE  
**Priority**: CRITICAL  
**Estimated Effort**: 3 days  
**Actual Effort**: 3 days

**User Story**:  
As a developer, I want a central orchestrator so that I can coordinate the entire sanitization workflow.

**Acceptance Criteria**:
- ✅ Execute workflow steps in correct order
- ✅ Handle FK dependencies (parent before child)
- ✅ Support dry-run mode (validation only)
- ✅ Progress reporting (tables/rows processed)
- ✅ Comprehensive error handling
- ✅ Resume from checkpoint on failure

**Technical Details**:
- **File**: `src/sanitization/orchestrator.py` (800 LOC)
- **Key Method**: `run(config, dry_run=False) -> SanitizationReport`
- **Tests**: `tests/unit/test_orchestrator.py` (82 tests)
- **Examples**: `examples/orchestrator_example.py` (8 examples)

**Workflow**:
1. Validate configuration
2. Build dependency graph
3. Topologically sort tables
4. For each table (parent → child):
   - Extract batch
   - Mask values
   - Store mapping
   - Update database
5. Validate integrity

**Implementation Notes**:
- 4 execution phases: Validation → Planning → Execution → Verification
- Batch processing with memory-efficient generators
- Per-table transactions for partial completion support
- Checkpoint/resume mechanism with JSON serialization
- Progress callbacks for table-level and batch-level tracking
- Dry-run mode validates without database modifications
- Comprehensive error handling with retryable errors
- Correlation ID tracking throughout execution
- SanitizationReport with detailed statistics and per-table progress

**Dependencies**: All previous stories

---

### Story 5.3: Mapping Table Manager
**Status**: ✅ Completed  
**Priority**: HIGH  
**Estimated Effort**: 2 days  
**Actual Effort**: 2 days  
**Completed**: 2026-03-27

**User Story**:  
As a developer, I want to store original→fake value mappings so that I can trace changes and support desensitization.

**Acceptance Criteria**:
- ✅ Create mapping table on first run
- ✅ Store schema, table, column, original, fake values
- ✅ Store timestamps and operation IDs
- ✅ Support encryption of original values (Fernet AES-128)
- ✅ Efficient lookup for desensitization
- ✅ Batch inserts for performance

**Technical Details**:
- **Files**: 
  - `src/mapping/mapping_manager.py` (✅ Complete - ~1025 LOC)
  - `src/mapping/mapping_models.py` (✅ Complete - MappingEntry, MappingBatch, MappingStats)
  - `src/mapping/mapping_config.py` (✅ Complete - MappingConfig Pydantic model)
  - `src/mapping/encryption_utils.py` (✅ Complete - EncryptionManager)
- **Table**: `sanitization.pii_mappings` (configurable schema/table name)

**Schema**:
```sql
CREATE TABLE [sanitization].[pii_mappings] (
    mapping_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    operation_id UNIQUEIDENTIFIER NOT NULL,
    schema_name NVARCHAR(128) NOT NULL,
    table_name NVARCHAR(128) NOT NULL,
    column_name NVARCHAR(128) NOT NULL,
    original_value_hash VARBINARY(32) NOT NULL,
    original_value_encrypted VARBINARY(MAX),
    masked_value NVARCHAR(MAX),
    data_type NVARCHAR(128) NOT NULL,
    is_null BIT NOT NULL DEFAULT 0,
    created_at DATETIME2 DEFAULT GETUTCDATE(),
    INDEX idx_lookup (schema_name, table_name, column_name, original_value_hash),
    INDEX idx_operation (operation_id)
);
```

**Implementation Summary**:
- ✅ MappingManager fully implemented with idempotent schema/table/index creation
- ✅ Batch storage with configurable batch sizes (100-100,000 rows)
- ✅ Deadlock retry with exponential backoff (`@retry_on_deadlock` decorator)
- ✅ Entry retrieval (by operation, table, column, filtered)
- ✅ Operation statistics aggregation (MappingStats)
- ✅ Encryption support using Fernet (AES-128-CBC + HMAC)
- ✅ Environment-based encryption key management
- ✅ Thread-safe operations with connection pooling
- ✅ Integrated into Orchestrator workflow (automatic mapping during sanitization)
- ✅ Comprehensive unit tests (~100% coverage with mocks)
- ✅ Integration tests with real SQL Server database
- ✅ Edge case validation (Unicode, NULL values, special characters, large batches)
- ✅ Example scripts demonstrating usage patterns
- ✅ Updated orchestrator_example.py with mapping storage example

**Testing**:
- ✅ Unit tests: `tests/unit/test_mapping_manager.py`
- ✅ Integration tests: `tests/integration/test_mapping_manager_integration.py`
- ✅ Orchestrator integration: `tests/integration/test_orchestrator_mapping_integration.py`
- ✅ Edge case tests: `tests/integration/test_mapping_edge_cases.py`
- ✅ Test helpers: `tests/integration/mapping_test_helpers.py`

**Examples**:
- ✅ Standalone usage: `examples/mapping_example.py` (6 examples)
- ✅ Orchestrator integration: `examples/orchestrator_example.py` (Example 9)

**Configuration**:
```python
mapping=MappingConfig(
    enabled=True,
    schema_name="sanitization",
    table_name="pii_mappings",
    encryption_enabled=False,  # Set True for production
    batch_size=10000,
    index_creation=True,
    transactional=True
)
```

**Encryption Setup**:
```python
from src.mapping.encryption_utils import EncryptionManager
import os

# Generate key
key = EncryptionManager.generate_key()
os.environ['SANITIZATION_MAPPING_ENCRYPTION_KEY'] = key
```

**Performance**:
- Batch storage: ~10,000+ entries/second (with indexing)
- Concurrent writes: Deadlock-safe with automatic retry
- Large batches: Successfully tested with 100,000+ rows

**Dependencies**: Story 1.1 (Connection Manager), Story 5.2 (Orchestrator)

---

### Story 5.4: Desensitization (Reverse) Engine
**Status**: ✅ Completed  
**Priority**: MEDIUM  
**Estimated Effort**: 1.5 days

**User Story**:  
As a developer, I want to restore original values so that I can reverse sanitization if needed.

**Acceptance Criteria**:
- ✅ Read mappings from mapping table
- ✅ Replace fake values with original values
- ✅ Support selective restore (specific tables/columns)
- ✅ Validate mappings exist before restoring
- ✅ Transactional restore

**Technical Details**:
- **File**: `src/sanitization/desensitizer.py`
- **Key Method**: `restore(operation_id, tables=None) -> RestoreReport`

**Implementation Summary**:
- ✅ Complete Desensitizer class with phased workflow (~900 LOC)
- ✅ RestorePhase enum (VALIDATION, PLANNING, RESTORATION, VERIFICATION, COMPLETED, FAILED)
- ✅ RestoreBatch, TableRestoreProgress, RestoreReport dataclasses
- ✅ DesensitizationConfig with validation (max_mismatch_percentage, sample_size_for_validation)
- ✅ Dependency injection pattern for all components
- ✅ Phase 1: Validation (operation exists, mappings complete, encryption key available)
- ✅ Phase 2: Planning (reverse FK dependency order: child → parent)
- ✅ Phase 3: Restoration (batch processing with per-table savepoints)
- ✅ Phase 4: Verification (integrity checks)
- ✅ Dry-run mode for safety testing
- ✅ Partial restore support (specific tables)
- ✅ Progress tracking callbacks (batch and table level)
- ✅ Encryption/decryption roundtrip
- ✅ Transaction safety with automatic rollback
- ✅ Comprehensive error handling
- ✅ Correlation IDs for audit trails
- ✅ Unit tests (~600 LOC, 40+ test cases)
- ✅ Integration tests (~750 LOC, test database setup, E2E workflows)
- ✅ Examples (~650 LOC, 8 usage scenarios)

**Usage Example**:
```python
# Basic full restoration
desensitizer = Desensitizer(
    connection_manager=conn_mgr,
    mapping_manager=mapping_mgr
)
report = desensitizer.restore(operation_id)
print(f"Restored {report.rows_restored} rows from {report.tables_restored} tables")

# Dry-run mode
report = desensitizer.restore(operation_id, dry_run=True)

# Partial restore
report = desensitizer.restore(
    operation_id,
    tables=["dbo.Customers", "dbo.Orders"]
)

# With progress tracking
def progress(table, rows, total, pct):
    print(f"[{table}] {pct:.1f}% complete")

desensitizer.set_progress_callback(progress)
report = desensitizer.restore(operation_id)
```

**Workflow** (Implemented):
1. **Phase 1 - Validation**: Verify operation exists, mappings complete, encryption key available
2. **Phase 2 - Planning**: Build reverse FK dependency graph (child → parent order)
3. **Phase 3 - Restoration**: Decrypt original values, update database in batches with savepoints
4. **Phase 4 - Verification**: Validate integrity (row counts, FK consistency)

**Edge Cases Handled**:
- Operation not found (DesensitizationError)
- Missing encryption key (DesensitizationError)
- Partial restore disabled (warning, falls back to full)
- Circular FK dependencies (warning, continues processing)
- Table restoration failures (per-table savepoints, continues with others)
- Decryption failures (DesensitizationError with context)
- NULL value handling
- Empty mapping sets (skips table with warning)

**Dependencies**: Story 5.3 (Mapping Manager), Story 2.4 (Batch Updater)

---

### Story 5.5: Pre/Post Sanitization Validator
**Status**: ✅ Completed  
**Priority**: HIGH  
**Estimated Effort**: 2 days

**User Story**:  
As a developer, I want to validate data integrity before and after sanitization so that I can ensure no data corruption occurs.

**Acceptance Criteria**:
- ✅ Pre-sanitization: row counts, NULL counts, FK integrity
- ✅ Post-sanitization: row counts unchanged, data types preserved
- ✅ Validate no PII remains (regex pattern matching)
- ✅ Validate FK relationships intact
- ✅ Generate validation report (JSON/HTML)

**Technical Details**:
- **File**: `src/validation/integrity_validator.py`
- **Methods**: `validate_pre()`, `validate_post()`, `compare_snapshots()`

**Implementation Summary**:
- ✅ ValidationPhase enum (PRE_SANITIZATION, POST_SANITIZATION, PRE_DESENSITIZATION, POST_DESENSITIZATION)
- ✅ ValidationConfig dataclass with configurable thresholds and PII whitelists (~100 LOC)
- ✅ Enhanced TableMetrics with column_max_lengths, identity_columns, computed_columns
- ✅ Enhanced IntegrityReport with row_count_deltas, null_count_deltas, data_type_mismatches, FK changes
- ✅ IntegrityReport.to_json() - JSON export with ISO timestamps
- ✅ IntegrityReport.to_html() - Styled HTML report with CSS, collapsible sections, charts (~300 LOC)
- ✅ IntegrityReport.export() - Unified export (JSON/HTML/both)
- ✅ IntegrityReport.has_critical_issues() - Critical error detection
- ✅ IntegrityReport.severity_summary() - Issue count by severity
- ✅ _validate_fk_constraint_existence() - FK constraint verification
- ✅ _validate_composite_fk_integrity() - Multi-column FK validation with NULL handling
- ✅ _validate_circular_fk_dependencies() - Cycle detection via DependencyResolver
- ✅ _validate_self_referencing_tables() - Hierarchical data validation
- ✅ _validate_row_count_with_sampling() - Large table sampling support
- ✅ _validate_column_length_preservation() - Truncation detection (MAX(LEN()) comparison)
- ✅ _validate_null_preservation_strategy() - Per-column NULL delta calculation
- ✅ _validate_data_type_precision() - NUMERIC_PRECISION/SCALE validation
- ✅ _validate_pii_patterns_with_whitelist() - Whitelist/exception handling for PII patterns
- ✅ _validate_masking_effectiveness() - Effectiveness score calculation (95% threshold)
- ✅ _compare_pii_patterns_pre_post() - Pre vs post PII pattern comparison

**Validation Checks**:
- ✅ Row count consistency (exact or sampled)
- ✅ NULL value preservation (per-column delta %)
- ✅ Data type preservation (schema integrity)
- ✅ FK relationship integrity (no orphans, composite FK support)
- ✅ PII pattern detection (EMAIL, PHONE, SSN, CREDIT_CARD with whitelist)
- ✅ Column length preservation (truncation detection)
- ✅ Numeric precision/scale preservation
- ✅ FK constraint existence (detect dropped constraints)
- ✅ Circular FK dependency detection
- ✅ Self-referencing table validation

**Report Generation**:
- ✅ JSON format: Machine-readable, automation-friendly, schema versioned
- ✅ HTML format: Human-readable with CSS styling, color-coded severity (red=error, yellow=warning, green=success)
- ✅ Collapsible sections with JavaScript for expand/collapse
- ✅ Row count comparison table with delta badges
- ✅ Execution metrics display (pre/post snapshot duration)
- ✅ Export to `./validation_reports/` directory with timestamp
- ✅ Correlation IDs for audit trail

**Edge Cases Handled**:
- ✅ Circular FK dependencies (detected via DependencyResolver, validated for orphans)
- ✅ Self-referencing tables (hierarchical data - employees→managers, categories→parent)
- ✅ Composite foreign keys (multi-column WHERE with AND logic)
- ✅ NULL-able FK columns (NULL in any column makes entire FK NULL, not orphan)
- ✅ Large table sampling (configurable threshold: 100k rows, uses sys.partitions stats)
- ✅ Column length truncation (MAX(LEN()) vs schema max)
- ✅ Identity columns (tracked but skipped for validation)
- ✅ Computed columns (tracked but skipped for validation)
- ✅ PII pattern whitelisting (test@example.com, 555-0100 test data)
- ✅ PII pattern exceptions (per-table.column configuration)
- ✅ Data type precision changes (NUMERIC_PRECISION, NUMERIC_SCALE, DATETIME_PRECISION)
- ✅ Dropped FK constraints (INFORMATION_SCHEMA query detects missing constraints)

**Configuration Options**:
- enable_row_count_check, enable_null_check, enable_fk_check (default: True)
- enable_pii_check, enable_data_type_check, enable_column_length_check (default: True)
- acceptable_orphan_percentage (default: 0.0%)
- acceptable_null_delta_percentage (default: 0.0%)
- pii_sample_size (default: 1000 rows)
- pii_pattern_whitelist (List[str] regex patterns)
- pii_pattern_exceptions (Dict[str, List[str]] - table.column → patterns)
- row_count_sampling_enabled (default: True for tables > 100k rows)
- row_count_sample_size (default: 100000)
- fail_on_warning (default: False)

**Usage Example**:
```python
# Configure validation
validation_config = ValidationConfig(
    enable_pii_check=True,
    pii_sample_size=5000,
    pii_pattern_whitelist=[r"test@example\\.com", r"555-0100"],
    pii_pattern_exceptions={
        "dbo.Customers.email": [r".*@testdomain\\.com"]
    },
    acceptable_orphan_percentage=0.1,
    row_count_sampling_enabled=True
)

# Initialize validator
validator = IntegrityValidator(conn_mgr, schema_extractor)

# Capture pre-sanitization baseline
pre_snapshot = validator.capture_pre_snapshot(
    operation_id=operation_id,
    tables=["dbo.Customers", "dbo.Orders"]
)

# ... perform sanitization ...

# Verify post-sanitization
post_snapshot = validator.capture_post_snapshot(
    operation_id=operation_id,
    tables=["dbo.Customers", "dbo.Orders"]
)

# Generate comparison report
report = validator.compare_snapshots(
    pre_snapshot,
    post_snapshot,
    config=validation_config
)

# Export report
files = report.export(format="both")  # JSON + HTML
print(f"Reports generated: {', '.join(files)}")

# Check for critical issues
if report.has_critical_issues():
    print(f"Validation FAILED: {report.critical_errors} errors")
    for error in report.validation_result.errors:
        print(f"  - {error}")
else:
    print(f"Validation PASSED: {report.overall_status}")
```

**Performance Optimizations**:
- Large table sampling (sys.partitions for row estimates)
- Batch FK orphan queries (EXISTS subquery pattern)
- Top N + NEWID() for random sampling
- Configurable PII sample size (balance accuracy vs speed)
- Query-based validation (no full data loads)

**Dependencies**: Story 1.1 (Connection Manager), Story 2.1 (Schema Extraction), Story 2.2 (Dependency Resolver)

---

## PHASE 6: Testing, Documentation & Polish (3 Stories)

### Story 6.1: Unit Tests for All Modules
**Status**: ✅ Completed  
**Priority**: HIGH  
**Estimated Effort**: 3 days  
**Actual Effort**: 3 days  
**Completed**: 2026-03-27

**User Story**:  
As a developer, I want comprehensive unit tests so that I can ensure code correctness and prevent regressions.

**Acceptance Criteria**:
- ✅ Test coverage > 80%
- ✅ Test all maskers with edge cases
- ✅ Test dependency graph builder (circular FKs)
- ✅ Test batch processing (pagination)
- ✅ Test configuration validation
- ✅ Mock external dependencies (database, AI API)

**Technical Details**:
- **Framework**: pytest 7.0+
- **Location**: `tests/unit/`, `tests/conftest.py`, `tests/test_helpers.py`
- **Mocking**: unittest.mock
- **Configuration**: `pytest.ini` with coverage settings

**Implementation Summary**:
- ✅ **Phase 1: Test Infrastructure** (~850 LOC)
  - `tests/conftest.py` - Shared pytest fixtures (mock_connection, mock_cursor, mock_connection_manager, faker_instance, etc.)
  - `pytest.ini` - Test configuration (coverage: 80%+, markers, logging, timeout settings)
  - `tests/test_helpers.py` - MockCursor class, mock builders, edge case generators, SQL assertion helpers

- ✅ **Phase 2: TIER 1 Critical Module Tests** (~2,330 LOC)
  - `test_transaction_manager.py` (~780 LOC) - 82 tests covering initialization, begin/commit/rollback, savepoints, isolation levels, timeout handling, rollback hooks, audit trail, thread safety, edge cases
  - `test_integrity_validator.py` (~960 LOC) - 73 tests covering ValidationConfig, ValidationPhase, TableMetrics, FKRelationshipStatus, IntegrityReport (to_dict/to_json/to_html/export), FK constraint validation, composite FK integrity, circular dependencies, self-referencing tables, row count sampling, column length preservation, NULL preservation, data type precision, PII pattern whitelist, masking effectiveness
  - `test_encryption_utils.py` (~590 LOC) - 78 tests covering EncryptionManager initialization, generate_key(), is_key_valid(), encrypt/decrypt, round-trip tests, NULL handling, Unicode/long strings/special characters, error handling

- ✅ **Phase 3: TIER 2 High Priority Module Tests** (~800 LOC)
  - `test_mapping_models.py` (~700 LOC) - 65 tests covering MappingEntry (creation, validation, to_dict, NULL values, edge cases), MappingBatch (creation, validation, properties, progress percent, to_dict), MappingStats (creation, validation, duration_seconds, avg_entries_per_table/column)
  - `test_error_codes.py` (~100 LOC) - 9 tests covering error code constants, uniqueness, naming conventions

**Test Coverage by Module**:
- TransactionManager: ~95% coverage (all methods, edge cases, concurrency)
- IntegrityValidator: ~90% coverage (all validation methods, report generation)
- EncryptionManager: ~95% coverage (encryption/decryption round-trips, key validation)
- MappingModels: ~100% coverage (all dataclasses, validation, properties)
- ErrorCodes: ~100% coverage (all constants, naming patterns)

**Test Organization**:
```
tests/
├── conftest.py              # Shared fixtures (~450 LOC)
├── test_helpers.py          # Test utilities (~400 LOC)
├── unit/
│   ├── test_transaction_manager.py          (~780 LOC, 82 tests)
│   ├── test_integrity_validator.py          (~960 LOC, 73 tests)
│   ├── test_encryption_utils.py            (~590 LOC, 78 tests)
│   ├── test_mapping_models.py              (~700 LOC, 65 tests)
│   ├── test_error_codes.py                 (~100 LOC, 9 tests)
│   ├── test_name_masker.py                  [existing]
│   ├── test_email_masker.py                 [existing]
│   ├── test_phone_masker.py                 [existing]
│   ├── test_ssn_masker.py                   [existing]
│   ├── test_generic_masker.py               [existing]
│   ├── test_masker_factory.py               [existing]
│   ├── test_orchestrator.py                 [existing]
│   ├── test_desensitizer.py                 [existing]
│   └── ... [22 more existing test files]
├── integration/
│   └── ... [13 existing integration test files]
└── pytest.ini               # Pytest configuration (~70 lines)
```

**Pytest Configuration**:
- Coverage threshold: `--cov-fail-under=80`
- Coverage reports: HTML, XML, terminal with missing lines
- Markers: `unit`, `integration`, `slow`, `smoke`, `regression`, `security`, `edge_case`
- Logging: CLI level INFO, file level DEBUG
- Timeout: 300 seconds (5 minutes)
- Test discovery: `test_*.py`, `Test*` classes, `test_*` functions

**Test Helpers & Fixtures**:
- **Database Mocks**: mock_cursor, mock_connection, mock_connection_manager
- **Configuration Mocks**: mock_database_config, mock_sanitization_config, mock_mapping_config
- **Test Data**: sample_table_data (PII samples), sample_fk_metadata (simple, composite, circular, self-referencing)
- **Edge Case Generators**: unicode_test_data (10 languages), long_string_test_data (255-64KB), edge_date_test_data
- **MockCursor Class**: Query tracking, result simulation, assertion helpers (assert_query_contains, assert_query_count)
- **SQL Assertion Helpers**: assert_sql_contains(), assert_sql_not_contains(), assert_parameterized_query()

**Edge Cases Covered**:
- **TransactionManager**: Nested transactions (savepoints), max depth exceeded, isolation levels, timeout, deadlocks, concurrent access, invalid savepoint names
- **IntegrityValidator**: Circular FK dependencies, self-referencing tables, composite FKs, NULL-able FKs, large table sampling, column truncation, zero rows, Unicode data
- **EncryptionUtils**: Wrong key decryption, corrupted ciphertext, empty strings, NULL values, Unicode strings, very long strings (1MB+), whitespace-only, repeated encryption
- **MappingModels**: Invalid UUIDs, empty names, wrong hash length, NULL conflicts, negative values, completed_at before started_at, zero tables/columns

**Test Statistics**:
- **New Test Files**: 5 files (~3,980 LOC)
- **Infrastructure Files**: 3 files (~850 LOC)
- **Total New Test Code**: ~4,830 LOC
- **Existing Test Files**: 27 unit + 13 integration = 40 files
- **Total Test Count**: 307+ new tests + 300+ existing = 600+ tests
- **Estimated Coverage**: 85%+ overall (exceeds 80% target)
- **Execution Time**: ~5-10 seconds for unit tests (fast, isolated)

**Dependencies**: All implementation stories

---

### Story 6.2: Integration Tests with Test Database
**Status**: ⬜ Not Started  
**Priority**: HIGH  
**Estimated Effort**: 2 days

**User Story**:  
As a developer, I want integration tests against a real SQL Server instance so that I can validate end-to-end workflows.

**Acceptance Criteria**:
- ✅ Test database setup script (DDL + sample data)
- ✅ Test complete sanitization workflow
- ✅ Test desensitization workflow
- ✅ Test FK integrity preservation
- ✅ Test circular FK handling
- ✅ Test self-referencing tables
- ✅ Cleanup test data after each run

**Technical Details**:
- **Location**: `tests/integration/`
- **Setup**: `scripts/setup_test_db.sql`
- **Test DB**: `SanitizationTest`

**Dependencies**: All implementation stories

---

### Story 6.3: Comprehensive Documentation
**Status**: ⬜ Not Started  
**Priority**: MEDIUM  
**Estimated Effort**: 2 days

**User Story**:  
As a user/developer, I want comprehensive documentation so that I can understand, use, and extend the system.

**Acceptance Criteria**:
- ✅ README with quickstart guide
- ✅ Installation instructions
- ✅ Configuration guide
- ✅ API reference documentation
- ✅ Architecture diagrams
- ✅ Edge case handling guide
- ✅ Performance tuning guide
- ✅ Security best practices

**Documentation Structure**:
```
docs/
├── README.md
├── quickstart.md
├── installation.md
├── configuration.md
├── architecture.md
├── api-reference.md
├── edge-cases.md
├── performance.md
└── security.md
```

**Dependencies**: All implementation stories

---

## Summary Statistics

- **Total Stories**: 28
- **Completed**: 23 stories (82.1%)
- **Remaining**: 5 stories (17.9%)
- **Total Estimated Duration**: 9-11 weeks
- **Critical Priority**: 11 stories (8 completed, 3 remaining)
- **High Priority**: 11 stories (10 completed, 1 remaining)
- **Medium Priority**: 4 stories (3 completed, 1 remaining)
- **Low Priority**: 1 story (1 completed, 0 remaining)

## Phase Completion Status

- **Phase 1 (Foundation)**: ✅ 5/5 stories complete (100%)
- **Phase 2 (Database Layer)**: ✅ 5/5 stories complete (100%)
- **Phase 3 (AI Integration)**: ✅ 3/3 stories complete (100%)
- **Phase 4 (Masking Engine)**: ✅ 6/6 stories complete (100%)
- **Phase 5 (Orchestration)**: ✅ 5/5 stories complete (100%)
- **Phase 6 (Testing & Documentation)**: 🟦 1/3 stories complete (33%) - IN PROGRESS

## Dependencies Overview

```
Phase 1 (Foundation) → Phase 2 (Database Layer) → Phase 3 (AI Integration)
        ✅                      ✅                        ✅
                    ↓
                 Phase 4 (Masking Engine) → Phase 5 (Orchestration) → Phase 6 (Testing)
                         ✅ (100%)                  ✅ (100%)             🟦 (33%)
```

## Next Steps

1. ✅ ~~Complete Phase 1 (Foundation)~~ - DONE
2. ✅ ~~Complete Phase 2 (Database Layer)~~ - DONE
3. ✅ ~~Complete Phase 3 (AI Integration)~~ - DONE
4. ✅ ~~Complete Phase 4 (Masking Engine)~~ - **DONE**
5. ✅ ~~Complete Phase 5 (Orchestration)~~ - **DONE**
6. ✅ **Story 6.1: Unit Tests for All Modules** - **DONE** (3 days)
7. 🔄 Story 6.2: Integration Tests with Test Database (2 days) - NEXT
8. ⬜ Story 6.3: Comprehensive Documentation (2 days)
   - ✅ Story 4.1 (Base Masker) - DONE
   - ✅ Story 4.2 (Email Masker) - DONE
   - ✅ Story 4.3 (Phone Number Masker) - DONE
   - ✅ Story 4.4 (Name Masker) - DONE
   - ✅ Story 4.5 (SSN Masker) - DONE
   - ✅ Story 4.6 (Generic String Masker) - DONE
5. **CURRENT**: Phase 5 (Orchestration)
   - ✅ Story 5.1 (Masking Strategy Factory) - **DONE**
   - **NEXT**: Story 5.2 (Sanitization Orchestrator)
6. Add missing tests:
   - Integration tests for Story 2.4 (Batch Updater)
   - Unit tests for Story 2.5 (Transaction Manager)
   - Integration tests for Story 2.5 (Transaction Manager)
7. Complete Phase 6 (Testing & Documentation) for production readiness

---

**Document Version**: 1.0  
**Last Updated**: 2026-03-26  
**Maintained By**: Development Team
