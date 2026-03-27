"""
Transaction management with savepoint support, audit trail, and advanced features.

This module provides comprehensive transaction lifecycle management for SQL Server with:
- Savepoint support for nested transactions
- Transaction audit trail and metrics tracking
- Isolation level control
- Rollback hooks for compensation logic
- Transaction timeout handling
- Thread-safe state management

Key Features:
    - SQL Server savepoints enable partial rollbacks without affecting outer transaction
    - Automatic audit logging of transaction lifecycle
    - Support for all SQL Server isolation levels
    - Configurable timeout with automatic rollback
    - LIFO rollback hooks for cleanup operations
    - Context manager pattern for clean API

Author: Database Sanitization Team
Date: 2026-03-26
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from contextlib import contextmanager
from datetime import datetime, timedelta
from collections import deque
import threading
import uuid
import re
import time

import pyodbc

from .connection_manager import DatabaseConnectionManager
from ..exceptions import TransactionError
from ..logging.logger import get_logger
from ..logging.correlation import CorrelationContext


class IsolationLevel(Enum):
    """SQL Server transaction isolation levels."""
    
    READ_UNCOMMITTED = "READ UNCOMMITTED"
    READ_COMMITTED = "READ COMMITTED"  # SQL Server default
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"
    SNAPSHOT = "SNAPSHOT"
    
    @classmethod
    def from_string(cls, level_str: str) -> "IsolationLevel":
        """Convert string to IsolationLevel enum."""
        level_str_upper = level_str.upper().strip().replace("-", " ").replace("_", " ")
        for level in cls:
            if level.value.replace(" ", "") == level_str_upper.replace(" ", ""):
                return level
        raise TransactionError.invalid_isolation_level(level_str)


@dataclass
class TransactionAudit:
    """
    Audit record for a transaction.
    
    Attributes:
        transaction_id: Unique ID for this transaction
        start_time: When transaction began
        end_time: When transaction ended (None if active)
        status: Transaction status (active, committed, rolled_back, failed)
        isolation_level: Isolation level used (None if default)
        savepoints_used: Number of savepoints created
        operations_count: Number of operations performed
        affected_rows: Total rows affected
        error_message: Error message if transaction failed
        duration_ms: Transaction duration in milliseconds
    """
    
    transaction_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "active"
    isolation_level: Optional[str] = None
    savepoints_used: int = 0
    operations_count: int = 0
    affected_rows: int = 0
    error_message: Optional[str] = None
    
    @property
    def duration_ms(self) -> float:
        """Calculate transaction duration in milliseconds."""
        if self.end_time is None:
            return (datetime.now() - self.start_time).total_seconds() * 1000
        return (self.end_time - self.start_time).total_seconds() * 1000


class TransactionManager:
    """
    Comprehensive transaction manager with savepoint support for SQL Server.
    
    This class provides production-grade transaction management building on
    ConnectionManager's basic transaction support. Key features include:
    
    - **Savepoint Support**: Nested transactions via SQL Server savepoints
    - **Audit Trail**: Complete lifecycle logging of all transactions
    - **Metrics Tracking**: Duration, row counts, operation counts
    - **Isolation Levels**: Support for all SQL Server isolation levels
    - **Rollback Hooks**: Cleanup callbacks executed on rollback
    - **Timeout Handling**: Automatic rollback on timeout
    - **Thread Safe**: Uses threading.Lock for state management
    
    Attributes:
        connection_manager: DatabaseConnectionManager for DB operations
        enable_audit_trail: Whether to maintain audit records
        default_timeout_seconds: Default transaction timeout (None = no timeout)
        max_savepoint_depth: Maximum nesting depth (SQL Server max: 32)
        logger: Logger with context for operation tracking
    
    Example:
        >>> from src.database import DatabaseConnectionManager, TransactionManager
        >>> conn_mgr = DatabaseConnectionManager(config)
        >>> txn_mgr = TransactionManager(conn_mgr)
        >>> 
        >>> # Basic transaction
        >>> with txn_mgr.begin():
        ...     # Operations auto-commit on success
        ...     updater.update_batch(table, data)
        >>> 
        >>> # Nested transaction with savepoint
        >>> with txn_mgr.begin():
        ...     updater.update_batch(table1, data1)
        ...     with txn_mgr.begin():  # Creates savepoint
        ...         updater.update_batch(table2, data2)
        ...         # Auto-rolls back to savepoint on exception
    """
    
    # SQL Server maximum savepoint nesting depth
    MAX_SAVEPOINT_DEPTH = 32
    
    # Valid savepoint name pattern (alphanumeric + underscore)
    SAVEPOINT_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]+$')
    
    def __init__(
        self,
        connection_manager: DatabaseConnectionManager,
        enable_audit_trail: bool = True,
        default_timeout_seconds: Optional[int] = None,
        max_savepoint_depth: int = 32,
        max_audit_history: int = 1000,
        logger: Optional[Any] = None,
    ) -> None:
        """
        Initialize the TransactionManager.
        
        Args:
            connection_manager: DatabaseConnectionManager for DB operations
            enable_audit_trail: Whether to track transaction audit records (default: True)
            default_timeout_seconds: Default timeout for transactions (None = no default)
            max_savepoint_depth: Maximum nesting depth (default: 32, SQL Server max)
            max_audit_history: Maximum audit records to keep in memory (default: 1000)
            logger: Optional logger with context
        
        Raises:
            ValueError: If max_savepoint_depth > 32 or < 1
        """
        if max_savepoint_depth < 1 or max_savepoint_depth > self.MAX_SAVEPOINT_DEPTH:
            raise ValueError(
                f"max_savepoint_depth must be between 1 and {self.MAX_SAVEPOINT_DEPTH}, "
                f"got {max_savepoint_depth}"
            )
        
        self.connection_manager = connection_manager
        self.enable_audit_trail = enable_audit_trail
        self.default_timeout_seconds = default_timeout_seconds
        self.max_savepoint_depth = max_savepoint_depth
        self.max_audit_history = max_audit_history
        self.logger = logger or get_logger(__name__).with_context(module="transaction_manager")
        
        # Transaction state (protected by lock)
        self._lock = threading.Lock()
        self._active_transaction: Optional[str] = None  # transaction_id
        self._transaction_start_time: Optional[datetime] = None
        self._timeout_seconds: Optional[int] = None
        self._current_isolation_level: Optional[IsolationLevel] = None
        self._savepoint_stack: List[str] = []  # Stack of active savepoint names
        self._rollback_hooks: List[Callable[[], None]] = []  # LIFO queue
        self._operations_count: int = 0
        self._affected_rows: int = 0
        
        # Audit trail (circular buffer)
        self._audit_history: deque = deque(maxlen=max_audit_history)
        self._current_audit: Optional[TransactionAudit] = None
    
    def is_active(self) -> bool:
        """
        Check if a transaction is currently active.
        
        Returns:
            True if transaction is active, False otherwise
        """
        with self._lock:
            return self._active_transaction is not None
    
    def get_transaction_id(self) -> Optional[str]:
        """
        Get the current transaction ID.
        
        Returns:
            Transaction ID if active, None otherwise
        """
        with self._lock:
            return self._active_transaction
    
    def get_savepoint_depth(self) -> int:
        """
        Get the current savepoint nesting depth.
        
        Returns:
            Number of active savepoints (0 = no savepoints)
        """
        with self._lock:
            return len(self._savepoint_stack)
    
    @contextmanager
    def begin(
        self,
        isolation_level: Optional[IsolationLevel] = None,
        timeout_seconds: Optional[int] = None,
    ):
        """
        Begin a transaction or savepoint (if nested).
        
        This context manager automatically handles:
        - Transaction begin/commit/rollback
        - Savepoint creation for nested contexts
        - Isolation level setting
        - Timeout monitoring
        - Audit trail logging
        - Rollback hooks execution
        
        Args:
            isolation_level: Transaction isolation level (outer transaction only)
            timeout_seconds: Transaction timeout in seconds (None = use default)
        
        Yields:
            Connection object for use within transaction
        
        Raises:
            TransactionError: If transaction operations fail
            TransactionTimeoutError: If transaction exceeds timeout
        
        Example:
            >>> with txn_mgr.begin(isolation_level=IsolationLevel.REPEATABLE_READ):
            ...     cursor.execute("UPDATE Users SET active = 1")
            ...     # Auto-commits on success, auto-rolls back on exception
        """
        # Check if this is a nested context (savepoint) or new transaction
        is_nested = self.is_active()
        
        if is_nested:
            # Nested context - create savepoint
            savepoint_name = self._begin_savepoint_internal()
            try:
                # Yield control to caller (reuse existing connection context)
                yield self.connection_manager
                # Savepoint implicitly committed (no explicit release needed)
                self._remove_savepoint_from_stack(savepoint_name)
            except Exception as e:
                # Rollback to savepoint on exception
                self._rollback_to_savepoint_internal(savepoint_name, error=e)
                raise
        else:
            # New transaction - use ConnectionManager's transaction_context
            transaction_id = str(uuid.uuid4())
            
            with self._lock:
                self._active_transaction = transaction_id
                self._transaction_start_time = datetime.now()
                self._timeout_seconds = timeout_seconds or self.default_timeout_seconds
                self._current_isolation_level = isolation_level
                self._savepoint_stack = []
                self._rollback_hooks = []
                self._operations_count = 0
                self._affected_rows = 0
                
                if self.enable_audit_trail:
                    self._current_audit = TransactionAudit(
                        transaction_id=transaction_id,
                        start_time=self._transaction_start_time,
                        isolation_level=isolation_level.value if isolation_level else None,
                    )
            
            self._log_transaction_start(transaction_id, isolation_level)
            
            try:
                # Set isolation level if specified
                if isolation_level:
                    self._set_isolation_level(isolation_level)
                
                # Use ConnectionManager's transaction context
                with self.connection_manager.transaction_context() as conn:
                    yield conn
                    
                    # Check timeout before commit
                    self._check_timeout()
                    
                    # Transaction committed successfully
                    self._log_transaction_commit(transaction_id)
                    
                    if self.enable_audit_trail and self._current_audit:
                        self._current_audit.end_time = datetime.now()
                        self._current_audit.status = "committed"
                        self._audit_history.append(self._current_audit)
                
            except Exception as e:
                # Rollback occurred (handled by ConnectionManager.transaction_context)
                self._log_transaction_rollback(transaction_id, e)
                
                # Execute rollback hooks in LIFO order
                self._execute_rollback_hooks()
                
                if self.enable_audit_trail and self._current_audit:
                    self._current_audit.end_time = datetime.now()
                    self._current_audit.status = "rolled_back"
                    self._current_audit.error_message = str(e)
                    self._audit_history.append(self._current_audit)
                
                raise
            finally:
                with self._lock:
                    self._active_transaction = None
                    self._transaction_start_time = None
                    self._timeout_seconds = None
                    self._current_isolation_level = None
                    self._savepoint_stack = []
                    self._rollback_hooks = []
                    self._current_audit = None
    
    def begin_savepoint(self, name: Optional[str] = None) -> str:
        """
        Create a named savepoint within the current transaction.
        
        Args:
            name: Savepoint name (auto-generated if None)
        
        Returns:
            Savepoint name
        
        Raises:
            TransactionError: If no active transaction or nesting limit exceeded
        
        Example:
            >>> sp_name = txn_mgr.begin_savepoint("sp_before_update")
            >>> try:
            ...     cursor.execute("UPDATE Users SET active = 1")
            ... except Exception:
            ...     txn_mgr.rollback_to_savepoint(sp_name)
        """
        return self._begin_savepoint_internal(name)
    
    def rollback_to_savepoint(self, savepoint_name: str) -> None:
        """
        Rollback to a specific savepoint.
        
        Args:
            savepoint_name: Name of the savepoint to rollback to
        
        Raises:
            TransactionError: If savepoint not found or rollback fails
        
        Example:
            >>> sp1 = txn_mgr.begin_savepoint()
            >>> cursor.execute("UPDATE table1 SET...")
            >>> sp2 = txn_mgr.begin_savepoint()
            >>> cursor.execute("UPDATE table2 SET...")  # This fails
            >>> txn_mgr.rollback_to_savepoint(sp2)  # Rollback table2 only
        """
        self._rollback_to_savepoint_internal(savepoint_name)
    
    def add_rollback_hook(self, callback: Callable[[], None]) -> None:
        """
        Register a callback to execute on transaction rollback.
        
        Hooks are executed in LIFO order (last registered, first executed).
        Hook exceptions are logged but don't prevent rollback.
        
        Args:
            callback: Function to call on rollback (no arguments)
        
        Example:
            >>> def cleanup_temp_file():
            ...     os.remove("/tmp/temp_file.dat")
            >>> txn_mgr.add_rollback_hook(cleanup_temp_file)
        """
        if not self.is_active():
            self.logger.warning("Cannot add rollback hook: no active transaction")
            return
        
        with self._lock:
            self._rollback_hooks.append(callback)
    
    def increment_operations(self, count: int = 1, affected_rows: int = 0) -> None:
        """
        Increment transaction operation counters.
        
        Args:
            count: Number of operations to add (default: 1)
            affected_rows: Number of rows affected
        """
        with self._lock:
            self._operations_count += count
            self._affected_rows += affected_rows
            
            if self._current_audit:
                self._current_audit.operations_count = self._operations_count
                self._current_audit.affected_rows = self._affected_rows
    
    def get_transaction_metrics(self) -> Dict[str, Any]:
        """
        Get metrics for the current transaction.
        
        Returns:
            Dictionary with transaction metrics
        
        Example:
            >>> metrics = txn_mgr.get_transaction_metrics()
            >>> print(f"Duration: {metrics['duration_ms']}ms")
        """
        with self._lock:
            if not self._active_transaction:
                return {"active": False}
            
            duration_ms = 0.0
            if self._transaction_start_time:
                duration_ms = (datetime.now() - self._transaction_start_time).total_seconds() * 1000
            
            return {
                "active": True,
                "transaction_id": self._active_transaction,
                "duration_ms": duration_ms,
                "operations_count": self._operations_count,
                "affected_rows": self._affected_rows,
                "savepoint_depth": len(self._savepoint_stack),
                "isolation_level": self._current_isolation_level.value if self._current_isolation_level else None,
                "timeout_seconds": self._timeout_seconds,
            }
    
    def get_audit_history(self, limit: int = 100) -> List[TransactionAudit]:
        """
        Get recent transaction audit records.
        
        Args:
            limit: Maximum number of records to return (default: 100)
        
        Returns:
            List of TransactionAudit records (most recent first)
        """
        with self._lock:
            # Convert deque to list and reverse (most recent first)
            history = list(self._audit_history)
            history.reverse()
            return history[:limit]
    
    # ==================== Internal Methods ====================
    
    def _begin_savepoint_internal(self, name: Optional[str] = None) -> str:
        """Create savepoint (internal implementation)."""
        if not self.is_active():
            raise TransactionError.begin_failed(reason="No active transaction for savepoint")
        
        with self._lock:
            # Check nesting depth
            if len(self._savepoint_stack) >= self.max_savepoint_depth:
                raise TransactionError.max_nesting_exceeded(max_depth=self.max_savepoint_depth)
            
            # Generate or validate savepoint name
            if name is None:
                name = f"sp_{len(self._savepoint_stack) + 1}"
            else:
                # Validate name
                if not self.SAVEPOINT_NAME_PATTERN.match(name):
                    raise TransactionError.invalid_savepoint_name(
                        name,
                        reason="must contain only alphanumeric characters and underscores"
                    )
                
                # Check for duplicates
                if name in self._savepoint_stack:
                    raise TransactionError.savepoint_create_failed(
                        name,
                        reason="savepoint with this name already exists"
                    )
            
            # Create savepoint via SQL
            try:
                with self.connection_manager.get_connection_context() as conn:
                    cursor = conn.cursor()
                    cursor.execute(f"SAVE TRANSACTION {name}")
                    cursor.close()
                
                self._savepoint_stack.append(name)
                
                if self._current_audit:
                    self._current_audit.savepoints_used += 1
                
                self.logger.debug(
                    f"Created savepoint '{name}' (depth: {len(self._savepoint_stack)})"
                )
                
                return name
                
            except pyodbc.Error as e:
                raise TransactionError.savepoint_create_failed(name, reason=str(e)) from e
    
    def _rollback_to_savepoint_internal(
        self,
        savepoint_name: str,
        error: Optional[Exception] = None
    ) -> None:
        """Rollback to savepoint (internal implementation)."""
        with self._lock:
            # Validate savepoint exists
            if savepoint_name not in self._savepoint_stack:
                raise TransactionError.savepoint_not_found(savepoint_name)
            
            # Find savepoint index
            savepoint_index = self._savepoint_stack.index(savepoint_name)
        
        # Rollback via SQL
        try:
            with self.connection_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute(f"ROLLBACK TRANSACTION {savepoint_name}")
                cursor.close()
            
            with self._lock:
                # Remove savepoint and all nested savepoints from stack
                self._savepoint_stack = self._savepoint_stack[:savepoint_index]
            
            self.logger.warning(
                f"Rolled back to savepoint '{savepoint_name}'",
                extra={"savepoint": savepoint_name, "error": str(error) if error else None}
            )
            
        except pyodbc.Error as e:
            raise TransactionError.savepoint_rollback_failed(savepoint_name, reason=str(e)) from e
    
    def _remove_savepoint_from_stack(self, savepoint_name: str) -> None:
        """Remove savepoint from stack (successful completion)."""
        with self._lock:
            if savepoint_name in self._savepoint_stack:
                self._savepoint_stack.remove(savepoint_name)
    
    def _set_isolation_level(self, level: IsolationLevel) -> None:
        """Set transaction isolation level."""
        try:
            with self.connection_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute(f"SET TRANSACTION ISOLATION LEVEL {level.value}")
                cursor.close()
            
            self.logger.debug(f"Set transaction isolation level to {level.value}")
            
        except pyodbc.Error as e:
            error_msg = str(e).lower()
            if "snapshot" in level.value.lower() and ("snapshot" in error_msg or "database" in error_msg):
                raise TransactionError.isolation_level_not_supported(
                    level.value,
                    reason="SNAPSHOT isolation not enabled on database"
                ) from e
            else:
                raise TransactionError.isolation_level_not_supported(level.value, reason=str(e)) from e
    
    def _check_timeout(self) -> None:
        """Check if transaction has exceeded timeout."""
        with self._lock:
            if self._timeout_seconds is None or self._transaction_start_time is None:
                return
            
            elapsed = (datetime.now() - self._transaction_start_time).total_seconds()
            
            # Warning thresholds
            if elapsed >= self._timeout_seconds * 0.9 and elapsed < self._timeout_seconds:
                self.logger.warning(
                    f"Transaction approaching timeout (90%): {elapsed:.1f}s / {self._timeout_seconds}s"
                )
            elif elapsed >= self._timeout_seconds * 0.7 and elapsed < self._timeout_seconds * 0.9:
                self.logger.warning(
                    f"Transaction approaching timeout (70%): {elapsed:.1f}s / {self._timeout_seconds}s"
                )
            
            # Hard timeout
            if elapsed >= self._timeout_seconds:
                raise TransactionError.timeout(
                    timeout_seconds=self._timeout_seconds,
                    elapsed_seconds=elapsed
                )
    
    def _execute_rollback_hooks(self) -> None:
        """Execute rollback hooks in LIFO order."""
        with self._lock:
            hooks = list(reversed(self._rollback_hooks))
        
        for i, hook in enumerate(hooks, 1):
            try:
                hook()
                self.logger.debug(f"Executed rollback hook {i}/{len(hooks)}")
            except Exception as e:
                self.logger.error(
                    f"Rollback hook {i}/{len(hooks)} failed: {e}",
                    extra={"hook_index": i, "error": str(e)}
                )
                # Continue with remaining hooks
    
    def _log_transaction_start(
        self,
        transaction_id: str,
        isolation_level: Optional[IsolationLevel]
    ) -> None:
        """Log transaction start."""
        self.logger.info(
            f"Transaction started: {transaction_id[:8]}...",
            extra={
                "transaction_id": transaction_id,
                "isolation_level": isolation_level.value if isolation_level else "default",
                "timeout_seconds": self._timeout_seconds,
            }
        )
    
    def _log_transaction_commit(self, transaction_id: str) -> None:
        """Log transaction commit."""
        metrics = self.get_transaction_metrics()
        
        self.logger.info(
            f"Transaction committed: {transaction_id[:8]}...",
            extra={
                "transaction_id": transaction_id,
                "duration_ms": metrics["duration_ms"],
                "operations_count": metrics["operations_count"],
                "affected_rows": metrics["affected_rows"],
                "savepoints_used": metrics["savepoint_depth"],
            }
        )
    
    def _log_transaction_rollback(self, transaction_id: str, error: Exception) -> None:
        """Log transaction rollback."""
        metrics = self.get_transaction_metrics()
        
        self.logger.warning(
            f"Transaction rolled back: {transaction_id[:8]}...",
            extra={
                "transaction_id": transaction_id,
                "error": str(error),
                "duration_ms": metrics["duration_ms"],
                "operations_count": metrics["operations_count"],
                "savepoints_active": metrics["savepoint_depth"],
            }
        )
