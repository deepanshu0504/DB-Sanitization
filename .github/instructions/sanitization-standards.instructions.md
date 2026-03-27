---
description: "Database sanitization project standards. Use when writing database sanitization scripts, PII masking logic, SQL Server integration, data extraction, fake data generation, or mapping table operations. Applies to all Python development in this workspace focusing on code quality, performance optimization, security, and data integrity."
applyTo: "**/*.py"
---

# Database Sanitization Standards - Quick Reference Checklist

## 1. Codebase Understanding

- Thoroughly review the existing workflow and codebase before making changes
- Identify dependencies, database connections, and key modules prior to implementation
- Understand the impact of changes on related components (tables, functions, APIs)

## 2. File & Resource Management

- Remove any temporary or test files immediately after use
- Ensure no leftover scripts, logs, or data that may affect production

## 3. Change Management

- Avoid making changes without fully understanding the logic and dependencies
- Document the purpose and rationale behind each modification
- Prepare a single consolidated document for each file detailing all changes, improvements, and reasoning

## 4. Code Quality & Readability

- Write clean, readable, and modular code following industry standards
- Prioritize dynamic, scalable, and reusable solutions rather than static implementations
- Include meaningful comments and docstrings for all functions and modules
- Ensure naming conventions are consistent and descriptive

## 5. Optimization & Performance

- Implement optimized queries and batch processing where applicable
- Avoid row-by-row operations; use set-based or bulk operations for large datasets
- Validate that generated data respects all constraints (length, data type, FK/PK relationships)

## 6. Error Handling & Reliability

- Implement robust error handling with informative logging
- Include retry logic for transient failures (DB connections, API calls)
- Validate output at each step to ensure data integrity

## 7. Security & Compliance

- Avoid logging or exposing sensitive data
- Encrypt or securely store mapping tables and temporary data
- Ensure any external API calls (e.g., Copilot) are secure and authenticated

## 8. Testing & Validation

- Perform thorough sample testing on representative data before full deployment
- Validate:
  - Row counts remain consistent
  - Data types and constraints are preserved
  - Referential integrity is maintained
- Document test cases and results clearly

## 9. Tools & Best Practices

- Utilize existing skills, libraries, and tools efficiently
- Follow best practices for Python and SQL development
- Ensure the workflow is generic and domain-agnostic, capable of handling any database schema

## 10. Documentation

Maintain detailed records of:
- Code changes
- Optimizations
- Configuration updates
- Mapping table structure and usage

Ensure documentation is understandable by other developers and stakeholders.

## 11. Continuous Improvement

- Review and refactor code regularly for efficiency, readability, and maintainability
- Incorporate feedback from testing and peer reviews
- Keep the solution adaptable for future enhancements and additional domains

---
## 12. Ensure temporary files created for testing are removed
- After testing, verify that no temporary files, logs, or test data remain in the codebase or database
## References

- [Requirements Document](../Requirement/requirement.md)
- [Critical Rules & Edge Cases](../CriticalRules/CriticalRulesAndEdgeCases.md)
- Skills: `/mssql-expert`, `/python-expert`, `/db-sanitization`, `/sanitization-edge-cases`
