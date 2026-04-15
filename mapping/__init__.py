"""
Mapping infrastructure for reversible database sanitization.

This module provides utilities for capturing and managing mappings between
original and sanitized values, enabling selective data restoration.
"""

from .mapping_table_manager import MappingTableManager, MappingRecord, BatchMetadata
from .exceptions import (
    MappingTableError,
    MappingInsertError,
    SchemaValidationError,
    EncryptionError,
    KeyManagementError,
    DecryptionError
)
from .encryption_utils import MappingEncryptor, generate_encryption_key, validate_encryption_key
from .mapping_cache import MappingLRUCache, CacheMetrics

__all__ = [
    "MappingTableManager",
    "MappingRecord",
    "BatchMetadata",
    "MappingTableError",
    "MappingInsertError",
    "SchemaValidationError",
    "EncryptionError",
    "KeyManagementError",
    "DecryptionError",
    "MappingEncryptor",
    "generate_encryption_key",
    "validate_encryption_key",
    "MappingLRUCache",
    "CacheMetrics",
]

__version__ = "1.1.0"
