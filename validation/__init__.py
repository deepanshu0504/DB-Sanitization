"""
Validation Package - Pre-desanitization validation checks.

This package provides validation capabilities to ensure preconditions are met
before desanitization operations begin. Helps prevent partial failures and
data corruption by fail-fast validation.

Key Components:
    - DesanitizationValidator: Core validation engine
    - ValidationReport: Structured validation results
    - ValidationCheck: Individual check results
"""

from validation.desanitization_validator import (
    DesanitizationValidator,
    ValidationReport,
    ValidationCheck,
    ValidationStatus,
    ValidationError,
)

__all__ = [
    'DesanitizationValidator',
    'ValidationReport',
    'ValidationCheck',
    'ValidationStatus',
    'ValidationError',
]
