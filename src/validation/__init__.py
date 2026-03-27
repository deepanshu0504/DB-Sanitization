"""
Validation module for PII configuration and data integrity validation.

This module provides comprehensive validation of PII configuration files against
actual database schema, and validates data integrity before/after sanitization
operations.

Key Components:
    - ConfigValidator: Main validation class that checks configuration against schema
    - IntegrityValidator: Pre/post sanitization integrity validator
    - ValidationResult: Container for validation errors, warnings, and info messages
    - ValidationIssue: Individual validation issue with severity and details
    - IssueSeverity: Enum for issue severity levels (ERROR, WARNING, INFO)
    - Data Models: PreSanitizationSnapshot, PostSanitizationSnapshot, IntegrityReport

Author: Database Sanitization Team
Date: 2026-03-27
"""

from .validation_result import ValidationResult, ValidationIssue, IssueSeverity
from .config_validator import ConfigValidator
from .integrity_validator import (
    IntegrityValidator,
    PreSanitizationSnapshot,
    PostSanitizationSnapshot,
    IntegrityReport,
    TableMetrics,
    FKRelationshipStatus
)

__all__ = [
    "ConfigValidator",
    "ValidationResult",
    "ValidationIssue",
    "IssueSeverity",
    "IntegrityValidator",
    "PreSanitizationSnapshot",
    "PostSanitizationSnapshot",
    "IntegrityReport",
    "TableMetrics",
    "FKRelationshipStatus",
]
