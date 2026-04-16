"""
Desanitization module for restoring original PII values.

This module provides comprehensive desanitization capabilities for reversing
database sanitization operations.

Modules:
    - desanitization_config: Configuration models for desanitization
    - desanitize: Main desanitization engine

Example:
    ```python
    from desanitization import Desanitizer, create_production_config
    from mapping import EncryptionManager
    from uuid import UUID
    
    # Initialize
    encryption_mgr = EncryptionManager()
    desanitizer = Desanitizer(
        connection_string="...",
        encryption_manager=encryption_mgr
    )
    
    # Restore
    operation_id = UUID("...")
    config = create_production_config()
    stats = desanitizer.restore(operation_id, config)
    
    print(f"Restored {stats.total_rows_restored} rows")
    ```
"""

from desanitization.desanitization_config import (
    DesanitizationConfig,
    RestoreStats,
    create_safe_config,
    create_production_config
)

from desanitization.desanitize import (
    Desanitizer,
    DesanitizationError
)

__all__ = [
    'DesanitizationConfig',
    'RestoreStats',
    'create_safe_config',
    'create_production_config',
    'Desanitizer',
    'DesanitizationError',
]

__version__ = '1.0.0'
__author__ = 'Database Sanitization Team'
