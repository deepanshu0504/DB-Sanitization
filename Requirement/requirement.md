# Database Sanitization Framework – Requirements Document

## 1. Overview

The purpose of this system is to identify, mask, and manage Personally Identifiable Information (PII) in a Microsoft SQL Server database using Python. The solution will support automated detection, manual override, secure sanitization, and reversible desensitization.

## 2. Technology Stack

- **Programming Language:** Python
- **Database:** Microsoft SQL Server
- **AI Integration:** GitHub Copilot Model API (for PII detection)

## 3. Functional Requirements

### 3.1 Database Connectivity

The system shall establish a secure connection to the SQL Server database.

It shall support both:
- SQL Server Authentication
- Windows Authentication

The system shall handle connection failures with retry mechanisms.

### 3.2 Schema Extraction

The system shall retrieve database schema metadata including:
- Table names
- Column names
- Data types
- Column lengths

The schema information shall be structured in JSON format.

### 3.3 PII Detection Using AI

- The system shall send extracted schema metadata to the AI service (Copilot API)
- The AI service shall analyze schema and identify potential PII columns
- The system shall receive a JSON response containing:
  - Table names
  - Column names suspected to contain PII data

### 3.4 User Review and Configuration

The system shall allow users to:
- Add additional tables/columns containing PII
- Remove incorrectly identified tables/columns

The finalized configuration shall be stored as a JSON file. This JSON shall act as the source of truth for sanitization.

### 3.5 Sanitization Input Configuration

The system shall accept the finalized JSON configuration as input.

The configuration shall define:
- Tables to process
- Columns to sanitize
- Type of data (e.g., email, phone, name)

### 3.6 Data Extraction (Batch Processing)

The system shall fetch data only for:
- Tables specified in the JSON
- Columns marked as PII

Data retrieval shall be performed in batches to:
- Optimize performance
- Prevent memory overflow

Pagination techniques (e.g., OFFSET/FETCH or key-based pagination) shall be used.

### 3.7 Fake Data Generation

The system shall generate fake data based on:
- Column data type
- Column length
- Identified PII category

**Examples:**
- Email → valid email format
- Phone → valid phone number format
- Name → realistic names

Generated data shall:
- Match original data format
- Respect length constraints

### 3.8 Data Replacement

- The system shall replace original PII values with generated fake values
- Replacement shall be executed efficiently using batch updates
- Data integrity must be maintained during updates

### 3.9 Mapping Table Management

The system shall maintain a mapping table to store:
- Table name
- Column name
- Original value
- Masked (fake) value
- Timestamp

The mapping table shall:
- Enable traceability
- Support reverse operations

### 3.10 Desensitization (Reverse Operation)

The system shall allow restoration of original data using the mapping table.

The process shall:
- Replace fake values with original values
- Ensure data consistency and completeness

## 4. Non-Functional Requirements

### 4.1 Performance

- The system shall support large datasets using batch processing
- It shall minimize database load and execution time

### 4.2 Security

- Sensitive data in the mapping table should be encrypted
- API communication shall be secured (HTTPS)
- Access to configuration and mapping data shall be restricted

### 4.3 Scalability

The system shall support:
- Multiple databases
- Large-scale data processing

It should allow parallel execution where applicable.

### 4.4 Reliability

The system shall include:
- Error handling mechanisms
- Logging and monitoring

Failures shall not result in data corruption.

### 4.5 Auditability

The system shall maintain logs for:
- Sanitization operations
- Data changes
- User modifications

## 5. Assumptions

- The database schema is accessible with required permissions
- AI API responses are reliable and available
- Users have sufficient knowledge to review and adjust PII configurations

## 6. Constraints

- The system depends on external AI service availability
- Performance may vary based on database size and infrastructure