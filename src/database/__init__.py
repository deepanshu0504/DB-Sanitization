"""Database connection management package.

This package provides robust SQL Server connection management with:
- Connection pooling for performance
- Automatic retry with exponential backoff
- Context manager support for automatic cleanup
- Health checks and monitoring
- Secure credential handling
- Schema metadata extraction
- Batch data extraction with intelligent pagination
- Batch data updates with transaction safety and deadlock handling
- Transaction management with savepoint support and audit trail
"""

from .connection_config import ConnectionConfig, AuthType
from .connection_manager import DatabaseConnectionManager, ConnectionPool
from .schema_extractor import SchemaExtractor
from .batch_extractor import BatchExtractor, Batch, PaginationStrategy
from .batch_updater import BatchUpdater, UpdateBatch, UpdateStrategy
from .transaction_manager import TransactionManager, TransactionAudit, IsolationLevel

__all__ = [
    "ConnectionConfig",
    "AuthType",
    "DatabaseConnectionManager",
    "ConnectionPool",
    "SchemaExtractor",
    "BatchExtractor",
    "Batch",
    "PaginationStrategy",
    "BatchUpdater",
    "UpdateBatch",
    "UpdateStrategy",
    "TransactionManager",
    "TransactionAudit",
    "IsolationLevel",
]
