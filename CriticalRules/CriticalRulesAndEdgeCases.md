# Critical Rules & Edge Case Handling

The following rules must be strictly enforced to ensure correctness, performance, and scalability of the database sanitization framework.

## 1. Schema & Object Name Handling

The system shall not assume that all database objects belong to the default `dbo` schema.

It must dynamically resolve fully qualified object names in the format:
```
[schema_name].[table_name]
```

**The system shall:**
- Handle multiple schemas within the same database
- Support special characters and reserved keywords in object names (using proper escaping, e.g., brackets `[]`)
- Ensure compatibility with case-sensitive collations

**Edge Cases to Handle:**
- Tables with identical names across different schemas
- Views or synonyms (if included in scope)
- Temporary tables (optional exclusion or controlled handling)

## 2. Data Type & Length Constraints for Fake Data

Generated fake values must strictly comply with:
- Column data type
- Maximum defined length
- Precision and scale (for numeric types)

**Rules:**
- Fake values shall never exceed column size limits
- Data type integrity must be preserved:
  - `VARCHAR`/`NVARCHAR` → string values within length
  - `INT`/`BIGINT` → numeric values only
  - `DATE`/`DATETIME` → valid date formats
- For constrained columns:
  - Respect `NOT NULL` constraints
  - Handle default values where applicable

**Edge Cases to Handle:**
- Truncation risks
- Unicode vs non-Unicode columns
- Fixed-length columns (`CHAR`, `NCHAR`)
- Enum-like or lookup-based fields

## 2A. Smart Generation - Constraint-Aware Value Generation

**CRITICAL RULE:** Generated fake values MUST fit within column constraints WITHOUT truncation.

The framework implements **Smart Generation** to eliminate data corruption from truncated values.

### The Problem: Generate-Then-Truncate

**❌ PROHIBITED APPROACH:**
```python
# Generate fixed format
email = "user_a1b2c3d4@example.com"  # 27 chars

# Truncate if too long
if len(email) > 15:
    email = email[:15]  # "user_a1b2c3d4@e" - INVALID!
```

**Issues:**
- Creates corrupt data (broken emails, incomplete phone numbers)
- Violates data integrity constraints
- Causes application failures in downstream systems
- Loses determinism (same input → different invalid outputs)

### The Solution: Select Format Before Generation

**✅ REQUIRED APPROACH:**
```python
# Check constraint BEFORE generation
if max_length < MIN_LENGTH:
    raise MaskingError("Column too short for minimum valid value")

# Select appropriate format tier based on available space
if max_length >= STANDARD_MIN:
    return generate_standard_format()  # Full format
elif max_length >= COMPACT_MIN:
    return generate_compact_format()   # Abbreviated format
else:
    return generate_minimal_format()   # Shortest valid format
```

### Format Tier Requirements

Each masker MUST implement multiple format tiers:

**EmailMasker:**
- Standard (≥26 chars): `user_a1b2c3d4@example.com`
- Compact (18-25 chars): `u_a1b2c3@demo.co`
- Minimal (6-17 chars): `a@x.co`

**PhoneMasker:**
- Standard (≥14 chars): `(555) 555-5555`
- Compact (12-13 chars): `555-555-5555`
- Minimal (10-11 chars): `5555555555`

**NameMasker:**
- Full (≥20 chars): `Dr. John Smith Jr.`
- First+Last (10-19 chars): `John Smith`
- First (4-9 chars): `John`
- Initial (2-3 chars): `JS`

**SSNMasker:**
- Formatted (≥11 chars): `123-45-6789`
- Plain (9-10 chars): `123456789`

### Truncation Tracking (Bug Detection)

Truncation MUST be tracked and reported as a BUG indicator, not normal behavior:

**Requirements:**
- BaseMasker tracks `truncation_count` and `truncation_details`
- Maskers log ERROR (not WARNING) when truncation occurs
- Orchestrator collects metrics after each table via `get_truncation_metrics()`
- SanitizationReport includes:
  - `total_truncations: int`
  - `truncation_details: Dict[str, List[Dict]]`
- Report displays "✅ No truncations detected" when zero
- Report displays "⚠️ X truncations detected - BUG!" when non-zero

### Pre-Validation (Fail-Fast)

All maskers MUST pre-validate constraints before attempting generation:

```python
def _pre_validate_constraints(self, column: ColumnInfo, min_length: int) -> None:
    """Validate column can accommodate minimum value length."""
    if column.max_length < min_length:
        raise MaskingError(
            f"Column too short for minimum {self.__class__.__name__} ({min_length} chars)",
            suggested_action=f"Increase column size to at least {min_length} characters"
        )
```

### Implementation Requirements

**BaseMasker:**
- Provide `truncation_count` and `truncation_details` instance variables
- Implement `_pre_validate_constraints()` method
- Change `_validate_length()` return type from `str` to `tuple[str, bool]` (value, was_truncated)
- Implement `get_truncation_metrics()` method
- Implement `reset_truncation_metrics()` method
- Log ERROR level when truncation occurs

**Concrete Maskers:**
- Implement `_generate_<type>_smart()` method with tier selection logic
- Call `_pre_validate_constraints()` in `mask()` before generation
- Handle tuple return from `_validate_length()`
- Mark old generate methods as DEPRECATED (keep for backwards compatibility)

**Orchestrator:**
- Collect truncation metrics after `_process_batches()` completes
- Call `get_truncation_metrics()` on each masker
- Add to report via `report.add_truncation()` if count > 0
- Log ERROR warning if truncations detected
- Call `reset_truncation_metrics()` before next table

### Performance Benefits

Smart Generation provides measurable performance improvements:

- **5-10% throughput increase** - No wasted generation + truncation cycles
- **5-8% memory reduction** - Direct allocation of correct size
- **Better cache utilization** - Consistent lengths improve deterministic lookups
- **Zero retry overhead** - No revision loops for invalid values

### Validation

All implementations MUST:
- Generate zero truncations for valid column sizes
- Raise clear MaskingError for impossible constraints (column too short)
- Maintain determinism (same input + same max_length → same output)
- Preserve backward compatibility (old methods deprecated but functional)

**Edge Cases to Handle:**
- Exact boundary lengths (max_length == minimum for tier)
- NULL value handling (preserve or mask based on strategy)
- Empty string handling (generate or preserve)
- Unicode columns requiring different length calculations
- CHAR vs VARCHAR (padding vs truncation behavior)

## 3. Query Optimization & Performance

All database operations must be optimized for high performance and minimal resource consumption.

**Requirements:**
- Use batch processing for both:
  - Data extraction
  - Data updates
- Prefer set-based operations over row-by-row processing
- Use efficient pagination techniques:
  - Key-based pagination (preferred over `OFFSET` for large datasets)
- Avoid full table scans wherever possible (use indexes)

**Update Optimization:**
- Use bulk operations (`executemany`, bulk update strategies)
- Minimize transaction size to reduce locking and blocking

**Edge Cases to Handle:**
- Very large tables (millions+ rows)
- Deadlocks and long-running transactions
- Network latency between application and database

## 4. Generic & Domain-Agnostic Design

The solution must be fully generic and reusable across domains, including but not limited to:
- Healthcare
- Retail
- E-commerce
- Finance

**Requirements:**
- No hardcoded table names, column names, or domain-specific logic
- PII detection must be driven by:
  - AI-based identification (e.g., GitHub Copilot)
  - Configurable JSON input
- Masking strategies must be configurable and extensible

**Edge Cases to Handle:**
- Domain-specific PII fields (e.g., medical record numbers, loyalty IDs)
- Multi-tenant database structures
- Dynamic or evolving schemas

## 5. Code Quality & Maintainability

The system shall enforce high standards for code quality.

**Requirements:**

Code must be:
- Modular
- Reusable
- Well-structured (layered architecture)

Follow best practices:
- Separation of concerns
- Dependency injection where applicable

Include:
- Proper error handling
- Logging mechanisms
- Inline documentation and docstrings

## 6. Reliability & Data Integrity

The system must ensure that data integrity is never compromised.

**Requirements:**
- All updates must be transactional where applicable
- Rollback mechanisms must be available in case of failure
- Ensure referential integrity is maintained across related tables

**Edge Cases to Handle:**
- Foreign key dependencies
- Partial updates due to failures
- Duplicate values where uniqueness is required

## 7. Idempotency & Re-runnability

The process must be safe to execute multiple times without causing inconsistent data states.

**Requirements:**
- Detect already sanitized data
- Avoid duplicate mappings
- Ensure consistent results across repeated runs

## 8. Security Considerations

Sensitive data handling must follow strict security practices.

**Requirements:**
- Avoid logging raw PII data
- Secure mapping tables (encryption recommended)
- Ensure secure API communication

## 9. Validation & Verification

The system must validate data before and after sanitization.

**Checks:**
- Row counts remain unchanged
- Data types remain consistent
- No unintended NULL or corrupted values

## 10. Handling Foreign Keys, Composite Keys, and Constraints

The system shall support and correctly handle:
- Foreign key relationships
- Primary keys (including composite keys)
- Unique constraints and indexes

### Requirements

The sanitization process must preserve referential integrity across related tables.

**When masking data:**
- Changes in parent tables must be consistently reflected in child tables
- Related columns across tables must maintain valid relationships

**For composite keys:**
- The system shall treat the combination of columns as a single logical identifier
- Updates must not break uniqueness or relationships defined by composite keys

### Strategy Guidelines

**Perform sanitization in a dependency-aware sequence:**
- Parent tables first, followed by child tables
- OR temporarily disable constraints (if safe) and re-enable after processing

**Maintain consistent mapping:**
- Same original value → same fake value across all tables
- Use mapping tables to ensure cross-table consistency

### Edge Cases to Handle

- Circular foreign key dependencies
- Self-referencing tables (hierarchical data)
- Composite foreign keys referencing multiple columns
- Cascading rules (`ON DELETE`, `ON UPDATE`)
- Unique constraints that may break due to fake data collisions
- Indexed columns affecting update performance
- Nullable foreign keys

### Data Integrity Safeguards

- Validate referential integrity after sanitization
- Ensure no orphan records are created
- Rebuild or validate indexes if required after bulk updates