"""
Data masking module for PII anonymization.

This module provides abstract base classes and concrete implementations for
masking various types of Personally Identifiable Information (PII) in a
deterministic, type-safe, and constraint-aware manner.

Key Components:
    - BaseMasker: Abstract base class for all masking strategies
    - ColumnInfo: Metadata container for database column information
    - MaskingStrategy: Enum for NULL value handling strategies
    - Concrete maskers: EmailMasker, PhoneMasker, NameMasker, SSNMasker, GenericMasker

Author: Database Sanitization Team
Date: 2026-03-26
"""

from .base_masker import BaseMasker, ColumnInfo, MaskingStrategy
from .email_masker import EmailMasker
from .phone_masker import PhoneMasker
from .name_masker import NameMasker
from .ssn_masker import SSNMasker
from .generic_masker import GenericMasker
from .masker_factory import MaskerFactory

__all__ = [
    "BaseMasker",
    "ColumnInfo",
    "MaskingStrategy",
    "EmailMasker",
    "PhoneMasker",
    "NameMasker",
    "SSNMasker",
    "GenericMasker",
    "MaskerFactory",
]
