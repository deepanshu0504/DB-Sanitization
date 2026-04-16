"""
Mapping module for PII value storage and retrieval.

This module provides comprehensive mapping management for database sanitization,
enabling reversible sanitization through secure storage of original→masked value mappings.

Modules:
    - encryption_utils: AES-256-GCM encryption/decryption
    - mapping_models: Data models for mappings, batches, and statistics
    - mapping_manager: Core storage and retrieval logic

Example:
    ```python
    from mapping import (
        EncryptionManager,
        MappingManager,
        create_mapping_entry
    )
    from uuid import uuid4
    
    # Setup
    encryption_mgr = EncryptionManager()
    mapping_mgr = MappingManager(
        connection_string="...",
        encryption_manager=encryption_mgr
    )
    mapping_mgr.initialize()
    
    # Create and store mapping
    operation_id = uuid4()
    entry = create_mapping_entry(
        operation_id=operation_id,
        schema="dbo",
        table="Customers",
        column="Email",
        original_value="john@example.com",
        masked_value="user_a1b2c3d4@example.com",
        data_type="NVARCHAR(100)",
        encrypted_original=encryption_mgr.encrypt("john@example.com")
    )
    
    stats = mapping_mgr.store_mappings([entry])
    print(f"Stored {stats.total_mappings} mappings")
    ```
"""

from mapping.encryption_utils import (
    EncryptionManager,
    EncryptionError,
    EncryptionKeyError,
    DecryptionError,
    generate_encryption_key,
    validate_encryption_key,
    quick_encrypt,
    quick_decrypt
)

from mapping.mapping_models import (
    MappingEntry,
    MappingBatch,
    MappingStats,
    create_mapping_entry,
    batch_mapping_entries
)

from mapping.mapping_manager import (
    MappingManager,
    MappingError
)

__all__ = [
    # Encryption
    'EncryptionManager',
    'EncryptionError',
    'EncryptionKeyError',
    'DecryptionError',
    'generate_encryption_key',
    'validate_encryption_key',
    'quick_encrypt',
    'quick_decrypt',
    
    # Models
    'MappingEntry',
    'MappingBatch',
    'MappingStats',
    'create_mapping_entry',
    'batch_mapping_entries',
    
    # Manager
    'MappingManager',
    'MappingError',
]

__version__ = '1.0.0'
__author__ = 'Database Sanitization Team'
