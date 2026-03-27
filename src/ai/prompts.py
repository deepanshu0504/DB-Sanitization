"""
Prompt engineering templates for AI-powered PII detection.

This module contains carefully crafted prompts for the GitHub Copilot Model API
to maximize accuracy and consistency in PII detection across diverse database schemas.

Author: Database Sanitization Team
Date: 2026-03-26
"""

from typing import Dict, Any
import json


SYSTEM_PROMPT = """You are a database security expert specializing in identifying Personally Identifiable Information (PII) in database schemas.

Your task is to analyze database schema metadata and identify columns that likely contain PII or sensitive data that should be sanitized before data sharing or testing.

Important guidelines:
- Consider column names, data types, constraints, and context
- Foreign key columns are relationships, NOT PII (unless the referenced column is PII)
- Columns like "EmailTemplateID", "PhoneTypeID" are NOT PII (they are IDs/enums)
- Ambiguous columns like "Data", "Value" require context from nearby columns
- International schemas may use non-English column names
- Return ONLY columns with high confidence of containing actual PII data values

Output MUST be valid JSON in this exact format:
{
  "pii_columns": [
    {
      "schema": "dbo",
      "table": "TableName",
      "column": "ColumnName",
      "pii_type": "email|phone|name|ssn|address|credit_card|date_of_birth|generic",
      "confidence": 0.95,
      "reason": "Brief explanation"
    }
  ]
}
"""


USER_PROMPT_TEMPLATE = """Analyze the following database schema and identify all columns that likely contain PII:

# Schema Metadata
{schema_json}

# PII Types Reference
- **email**: Email addresses (e.g., user@example.com)
- **phone**: Phone numbers (any format)
- **name**: Person names (first, last, full names)
- **ssn**: Social Security Numbers or national IDs
- **address**: Physical addresses (street, city, zip)
- **credit_card**: Credit card numbers
- **date_of_birth**: Birth dates
- **generic**: Other sensitive data not fitting above categories

# Examples of PII Columns (include these if found):
✓ Email, EmailAddress, ContactEmail, UserEmail
✓ Phone, PhoneNumber, ContactPhone, MobileNumber
✓ FirstName, LastName, FullName, PatientName
✓ SSN, SocialSecurityNumber, NationalID, TaxID
✓ Address, StreetAddress, City, ZipCode, PostalCode
✓ CreditCardNumber, CardNumber, CCNumber
✓ DateOfBirth, BirthDate, DOB

# Examples of NON-PII Columns (exclude these):
✗ EmailTemplateID, PhoneTypeID (IDs/enums, not actual data)
✗ CustomerID, OrderID, ProductID (surrogate keys)
✗ CreatedBy, ModifiedBy (audit columns unless they store actual names)
✗ Foreign key columns (unless referencing PII)
✗ Computed columns, timestamps, status flags

Return ONLY the JSON response. Do not include explanations outside the JSON structure.
"""


EXAMPLES_FEW_SHOT = """
# Example 1: Clear PII Column
Schema: dbo, Table: Customers, Column: Email, Type: NVARCHAR(100)
→ PII Type: email, Confidence: 0.99, Reason: "Column name 'Email' and VARCHAR type strongly indicate email addresses"

# Example 2: Ambiguous Column with Context
Schema: dbo, Table: Users, Column: Data, Type: NVARCHAR(50)
Context: Nearby columns include FirstName, LastName
→ PII Type: generic, Confidence: 0.70, Reason: "Ambiguous name but context suggests user data"

# Example 3: False Positive (Foreign Key)
Schema: dbo, Table: Orders, Column: CustomerID, Type: INT
Foreign Key: References Customers(CustomerID)
→ NOT PII, Reason: "Foreign key relationship, not actual customer data"

# Example 4: False Positive (Enum/Lookup)
Schema: dbo, Table: Products, Column: EmailTemplateID, Type: INT
→ NOT PII, Reason: "Suffix 'ID' indicates lookup/enum, not actual email"
"""


def build_pii_detection_prompt(
    schema_metadata: Dict[str, Any],
    include_examples: bool = True
) -> Dict[str, str]:
    """
    Build a structured prompt for PII detection from schema metadata.
    
    Args:
        schema_metadata: Schema information from SchemaExtractor
                        Expected keys: "tables", each with "columns", "foreign_keys"
        include_examples: Whether to include few-shot examples (default: True)
    
    Returns:
        Dictionary with "system" and "user" prompt strings
    
    Example:
        >>> schema = {"tables": [...]}
        >>> prompts = build_pii_detection_prompt(schema)
        >>> api_request = {
        ...     "messages": [
        ...         {"role": "system", "content": prompts["system"]},
        ...         {"role": "user", "content": prompts["user"]}
        ...     ]
        ... }
    """
    # Format schema metadata as readable JSON
    schema_json = json.dumps(schema_metadata, indent=2, ensure_ascii=False)
    
    # Build user prompt
    user_prompt = USER_PROMPT_TEMPLATE.format(schema_json=schema_json)
    
    # Optionally append few-shot examples
    if include_examples:
        user_prompt += f"\n\n# Few-Shot Examples\n{EXAMPLES_FEW_SHOT}"
    
    return {
        "system": SYSTEM_PROMPT,
        "user": user_prompt
    }


def build_large_schema_prompt(
    table_batch: Dict[str, Any],
    batch_number: int,
    total_batches: int
) -> Dict[str, str]:
    """
    Build a prompt for processing large schemas in batches.
    
    For schemas with 500+ tables, we split processing into smaller chunks
    to avoid exceeding API token limits.
    
    Args:
        table_batch: Subset of schema metadata (50 tables max)
        batch_number: Current batch number (1-indexed)
        total_batches: Total number of batches
    
    Returns:
        Dictionary with "system" and "user" prompt strings
    
    Example:
        >>> batch = {"tables": tables[0:50]}
        >>> prompts = build_large_schema_prompt(batch, 1, 10)
    """
    schema_json = json.dumps(table_batch, indent=2, ensure_ascii=False)
    
    system_prompt = f"""{SYSTEM_PROMPT}

NOTE: This is batch {batch_number} of {total_batches} for a large schema.
Process only the tables in this batch and return PII columns found.
"""
    
    user_prompt = USER_PROMPT_TEMPLATE.format(schema_json=schema_json)
    
    return {
        "system": system_prompt,
        "user": user_prompt
    }
