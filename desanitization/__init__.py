"""
Database Desanitization Module

This module provides functionality to reverse database sanitization operations,
restoring original values from masked/sanitized data using stored mapping tables.

Core Components:
    - DesanitizationEngine: Main engine for performing restoration operations
    - CheckpointManager: Manages fault-tolerant operation checkpoints
    - Exceptions: Custom exception hierarchy for desanitization errors

Usage:
    from desanitization import DesanitizationEngine, CheckpointManager
    from desanitization.exceptions import DesanitizationError
    
    engine = DesanitizationEngine(connection, mapping_manager)
    result = engine.desanitize_records(table='Users', record_ids=['123', '456'])
    
    # For database-level operations with checkpointing
    checkpoint_mgr = CheckpointManager(connection_string)
    checkpoint_mgr.create_table()
"""

from desanitization.desanitization_engine import DesanitizationEngine
from desanitization.checkpoint_manager import (
    CheckpointManager,
    CheckpointStatus,
    CheckpointRecord,
    OperationStatus,
)
from desanitization.config_models import (
    DesanitizationConfig,
    MappingSourceConfig,
    EncryptionConfig,
    RestorationConfig,
    PerformanceConfig,
    CheckpointConfig,
    ValidationConfig,
    AuditConfig,
    SecurityConfig,
    create_minimal_config,
)
from desanitization.exceptions import (
    DesanitizationError,
    MappingNotFoundError,
    ValidationError,
    PreconditionError,
    RestorationError,
    CircularDependencyError,
    ConstraintViolationError,
    CheckpointError,
)

__all__ = [
    'DesanitizationEngine',
    'CheckpointManager',
    'CheckpointStatus',
    'CheckpointRecord',
    'OperationStatus',
    'DesanitizationConfig',
    'MappingSourceConfig',
    'EncryptionConfig',
    'RestorationConfig',
    'PerformanceConfig',
    'CheckpointConfig',
    'ValidationConfig',
    'AuditConfig',
    'SecurityConfig',
    'create_minimal_config',
    'DesanitizationError',
    'MappingNotFoundError',
    'ValidationError',
    'PreconditionError',
    'RestorationError',
    'CircularDependencyError',
    'ConstraintViolationError',
    'CheckpointError',
]

__version__ = '1.0.0'
