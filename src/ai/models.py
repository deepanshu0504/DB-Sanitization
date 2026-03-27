"""
Pydantic models for AI API requests and responses.

This module defines structured data models for validating API responses
from the GitHub Copilot Model API, ensuring type safety and data integrity.

Author: Database Sanitization Team
Date: 2026-03-26
"""

import warnings
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Suppress Pydantic warning about 'schema' field shadowing BaseModel.schema()
# This is intentional as we need 'schema' for database schema names
warnings.filterwarnings('ignore', message=r'.*Field name "schema" shadows an attribute.*')


class PIIColumn(BaseModel):
    """
    Represents a single PII column recommendation from the AI service.
    
    Attributes:
        schema: Database schema name (e.g., "dbo")
        table: Table name (e.g., "Customers")
        column: Column name (e.g., "Email")
        pii_type: Type of PII (email, phone, name, ssn, address, generic)
        confidence: Optional confidence score (0.0 to 1.0) for future use
        reason: Optional explanation for the PII classification
    
    Example:
        >>> col = PIIColumn(
        ...     schema="dbo",
        ...     table="Customers",
        ...     column="Email",
        ...     pii_type="email",
        ...     confidence=0.95
        ... )
    """
    
    model_config = ConfigDict(protected_namespaces=())
    
    schema: str = Field(..., min_length=1, description="Database schema name")
    table: str = Field(..., min_length=1, description="Table name")
    column: str = Field(..., min_length=1, description="Column name")
    pii_type: str = Field(
        ...,
        pattern="^(email|phone|name|ssn|address|credit_card|date_of_birth|generic)$",
        description="Type of PII detected"
    )
    confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0 to 1.0)"
    )
    reason: Optional[str] = Field(
        None,
        max_length=500,
        description="Explanation for PII classification"
    )
    
    @field_validator("schema", "table", "column")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Strip leading/trailing whitespace from identifiers."""
        return v.strip()
    
    @field_validator("pii_type")
    @classmethod
    def lowercase_pii_type(cls, v: str) -> str:
        """Normalize PII type to lowercase."""
        return v.lower()
    
    def __hash__(self) -> int:
        """
        Make PIIColumn hashable for deduplication.
        
        Returns:
            Hash based on schema, table, and column
        """
        return hash((self.schema, self.table, self.column))
    
    def __eq__(self, other: object) -> bool:
        """
        Check equality based on schema, table, and column.
        
        Args:
            other: Another PIIColumn instance
        
        Returns:
            True if schema, table, and column match
        """
        if not isinstance(other, PIIColumn):
            return False
        return (
            self.schema == other.schema
            and self.table == other.table
            and self.column == other.column
        )


class PIIDetectionResponse(BaseModel):
    """
    Structured response from the AI service for PII detection.
    
    Attributes:
        pii_columns: List of detected PII columns
        metadata: Optional metadata about the detection (e.g., model version)
        total_columns_analyzed: Optional count of columns processed
    
    Example:
        >>> response = PIIDetectionResponse(
        ...     pii_columns=[
        ...         PIIColumn(schema="dbo", table="Users", column="Email", pii_type="email")
        ...     ],
        ...     metadata={"model": "copilot-gpt-4", "version": "2026-03"}
        ... )
    """
    
    pii_columns: List[PIIColumn] = Field(
        default_factory=list,
        description="List of detected PII columns"
    )
    metadata: Optional[Dict[str, str]] = Field(
        None,
        description="Optional metadata about the detection"
    )
    total_columns_analyzed: Optional[int] = Field(
        None,
        ge=0,
        description="Total number of columns analyzed"
    )
    
    @field_validator("pii_columns")
    @classmethod
    def deduplicate_columns(cls, v: List[PIIColumn]) -> List[PIIColumn]:
        """
        Remove duplicate PII column recommendations.
        
        Args:
            v: List of PIIColumn instances
        
        Returns:
            Deduplicated list (keeps first occurrence)
        """
        seen = set()
        deduplicated = []
        for col in v:
            if col not in seen:
                seen.add(col)
                deduplicated.append(col)
        return deduplicated
