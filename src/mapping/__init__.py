"""
Mapping module for storing and retrieving PII value mappings.

This module provides functionality to:
- Store original→masked value mappings for traceability
- Support reversible sanitization (desensitization)
- Enable audit trails of sanitization operations
- Maintain referential integrity through deterministic mapping lookups
"""

from src.mapping.mapping_models import MappingEntry, MappingBatch, MappingStats
from src.mapping.encryption_utils import EncryptionManager
from src.mapping.mapping_config import MappingConfig
from src.mapping.mapping_manager import MappingManager

__all__ = [
    "MappingEntry",
    "MappingBatch",
    "MappingStats",
    "EncryptionManager",
    "MappingConfig",
    "MappingManager",
]
