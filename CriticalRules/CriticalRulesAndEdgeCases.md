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