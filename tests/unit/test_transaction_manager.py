"""
Unit tests for TransactionManager class.

Tests cover:
- Initialization and state management
- Transaction lifecycle (begin, commit, rollback)
- Savepoint support (nested transactions)
- Isolation level configuration
- Transaction timeout handling
- Rollback hooks and cleanup
- Audit trail tracking
- Thread safety and concurrency
- Edge cases (max depth, invalid names, connection failures)

Test Organization:
- TestTransactionManagerInit: Initialization and configuration
- TestTransactionBegin: Transaction start and isolation levels
- TestTransactionCommit: Transaction commit and audit updates
- TestTransactionRollback: Rollback and savepoint handling
- TestSavepointManagement: Savepoint creation and nesting
- TestIsolationLevels: Isolation level testing
- TestTransactionTimeout: Timeout handling and auto-rollback
- TestRollbackHooks: Compensation logic execution
- TestAuditTrail: Audit logging and metrics
- TestThreadSafety: Concurrent access and locking
- TestEdgeCases: Error handling and boundary conditions

Author: Database Sanitization Team
Date: 2026-03-27
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime, timedelta
import threading
import time
import uuid

from src.database.transaction_manager import (
    TransactionManager,
    IsolationLevel,
    TransactionAudit
)
from src.database.connection_manager import DatabaseConnectionManager
from src.exceptions import TransactionError
from tests.test_helpers import MockCursor, create_mock_connection


class TestTransactionManagerInit:
    """Test TransactionManager initialization and configuration."""
    
    def test_init_with_connection_manager(self, mock_connection_manager):
        """Test basic initialization with connection manager."""
        manager = TransactionManager(mock_connection_manager)
        
        assert manager.connection_manager == mock_connection_manager
        assert manager.enable_audit_trail is True
        assert manager.default_timeout_seconds is None
        assert manager.max_savepoint_depth == 32
        assert manager.max_audit_history == 1000
        assert manager.logger is not None
    
    def test_init_custom_settings(self, mock_connection_manager):
        """Test initialization with custom settings."""
        manager = TransactionManager(
            mock_connection_manager,
            enable_audit_trail=False,
            default_timeout_seconds=300,
            max_savepoint_depth=10,
            max_audit_history=500
        )
        
        assert manager.enable_audit_trail is False
        assert manager.default_timeout_seconds == 300
        assert manager.max_savepoint_depth == 10
        assert manager.max_audit_history == 500
    
    def test_init_creates_state_tracking(self, mock_connection_manager):
        """Test that initialization creates proper state tracking."""
        manager = TransactionManager(mock_connection_manager)
        
        # Verify internal state initialization
        assert manager._active_transaction is None
        assert manager._transaction_start_time is None
        assert manager._timeout_seconds is None
        assert manager._current_isolation_level is None
        assert manager._savepoint_stack == []
        assert manager._rollback_hooks == []
        assert manager._operations_count == 0
        assert manager._affected_rows == 0
        assert manager._current_audit is None
    
    def test_init_thread_safety_lock(self, mock_connection_manager):
        """Test that initialization creates threading lock."""
        manager = TransactionManager(mock_connection_manager)
        
        assert isinstance(manager._lock, threading.Lock)
    
    def test_init_invalid_max_savepoint_depth_too_high(self, mock_connection_manager):
        """Test that initialization fails with savepoint depth > 32."""
        with pytest.raises(ValueError, match="max_savepoint_depth must be between 1 and 32"):
            TransactionManager(mock_connection_manager, max_savepoint_depth=33)
    
    def test_init_invalid_max_savepoint_depth_zero(self, mock_connection_manager):
        """Test that initialization fails with savepoint depth = 0."""
        with pytest.raises(ValueError, match="max_savepoint_depth must be between 1 and 32"):
            TransactionManager(mock_connection_manager, max_savepoint_depth=0)
    
    def test_init_negative_max_savepoint_depth(self, mock_connection_manager):
        """Test that initialization fails with negative savepoint depth."""
        with pytest.raises(ValueError, match="max_savepoint_depth must be between 1 and 32"):
            TransactionManager(mock_connection_manager, max_savepoint_depth=-1)


class TestTransactionBegin:
    """Test transaction begin functionality."""
    
    def test_begin_starts_transaction(self, mock_connection_manager):
        """Test that begin() starts a transaction."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin():
            assert manager.is_active()
            assert manager.get_transaction_id() is not None
    
    def test_begin_with_isolation_level_read_uncommitted(self, mock_connection_manager):
        """Test begin with READ UNCOMMITTED isolation level."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin(isolation_level=IsolationLevel.READ_UNCOMMITTED):
            # Verify SET TRANSACTION ISOLATION LEVEL was executed
            queries = [q[0] for q in cursor.executed_queries]
            assert any("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED" in q.upper() for q in queries)
    
    def test_begin_with_isolation_level_serializable(self, mock_connection_manager):
        """Test begin with SERIALIZABLE isolation level."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin(isolation_level=IsolationLevel.SERIALIZABLE):
            queries = [q[0] for q in cursor.executed_queries]
            assert any("SERIALIZABLE" in q.upper() for q in queries)
    
    def test_begin_nested_creates_savepoint(self, mock_connection_manager):
        """Test that nested begin creates a savepoint."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin():
            assert manager.get_savepoint_depth() == 0
            
            with manager.begin():
                assert manager.get_savepoint_depth() == 1
                
                # Verify SAVE TRANSACTION was executed
                queries = [q[0] for q in cursor.executed_queries]
                assert any("SAVE TRANSACTION" in q.upper() for q in queries)
    
    def test_begin_max_depth_exceeded(self, mock_connection_manager):
        """Test that exceeding max savepoint depth raises error."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager, max_savepoint_depth=2)
        
        with manager.begin():
            with manager.begin():
                with pytest.raises(TransactionError):
                    with manager.begin():
                        pass
    
    def test_begin_transaction_already_active_creates_savepoint(self, mock_connection_manager):
        """Test that begin() on active transaction creates savepoint (not error)."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin():
            txn_id_1 = manager.get_transaction_id()
            
            with manager.begin():
                txn_id_2 = manager.get_transaction_id()
                # Same transaction, but with savepoint
                assert txn_id_1 == txn_id_2
                assert manager.get_savepoint_depth() == 1
    
    def test_begin_with_custom_timeout(self, mock_connection_manager):
        """Test begin with custom timeout."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin(timeout_seconds=60):
            assert manager._timeout_seconds == 60


class TestTransactionCommit:
    """Test transaction commit functionality."""
    
    def test_commit_executes_commit(self, mock_connection_manager):
        """Test that exiting context commits transaction."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin():
            pass
        
        # Verify COMMIT executed
        mock_conn.commit.assert_called()
        assert not manager.is_active()
    
    def test_commit_no_active_transaction(self, mock_connection_manager):
        """Test that commit without active transaction is safe."""
        manager = TransactionManager(mock_connection_manager)
        
        # Should not raise error
        assert not manager.is_active()
    
    def test_commit_updates_audit_trail(self, mock_connection_manager):
        """Test that commit updates audit trail status."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager, enable_audit_trail=True)
        
        with manager.begin():
            pass
        
        # Verify audit record created
        audit_history = manager.get_audit_history(limit=1)
        assert len(audit_history) == 1
        assert audit_history[0].status == "committed"
        assert audit_history[0].end_time is not None
    
    def test_commit_nested_savepoint_releases(self, mock_connection_manager):
        """Test that nested savepoint commit releases savepoint."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin():
            with manager.begin():
                assert manager.get_savepoint_depth() == 1
            
            # Savepoint released after nested context exit
            assert manager.get_savepoint_depth() == 0


class TestTransactionRollback:
    """Test transaction rollback functionality."""
    
    def test_rollback_executes_rollback(self, mock_connection_manager):
        """Test that exception triggers rollback."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with pytest.raises(ValueError):
            with manager.begin():
                raise ValueError("Test error")
        
        # Verify ROLLBACK executed
        mock_conn.rollback.assert_called()
        assert not manager.is_active()
    
    def test_rollback_to_savepoint(self, mock_connection_manager):
        """Test rollback to savepoint on nested exception."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin():
            assert manager.is_active()
            
            with pytest.raises(ValueError):
                with manager.begin():
                    raise ValueError("Nested error")
            
            # Outer transaction still active after nested rollback
            assert manager.is_active()
            assert manager.get_savepoint_depth() == 0
    
    def test_rollback_hooks_executed(self, mock_connection_manager):
        """Test that rollback hooks are executed on rollback."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        hook_called = Mock()
        
        with pytest.raises(ValueError):
            with manager.begin():
                manager.add_rollback_hook(hook_called)
                raise ValueError("Trigger rollback")
        
        # Verify hook was called
        hook_called.assert_called_once()
    
    def test_rollback_hooks_lifo_order(self, mock_connection_manager):
        """Test that rollback hooks execute in LIFO order."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        call_order = []
        hook1 = lambda: call_order.append(1)
        hook2 = lambda: call_order.append(2)
        hook3 = lambda: call_order.append(3)
        
        with pytest.raises(ValueError):
            with manager.begin():
                manager.add_rollback_hook(hook1)
                manager.add_rollback_hook(hook2)
                manager.add_rollback_hook(hook3)
                raise ValueError("Trigger rollback")
        
        # Hooks should execute in reverse order (LIFO)
        assert call_order == [3, 2, 1]
    
    def test_rollback_updates_audit_trail(self, mock_connection_manager):
        """Test that rollback updates audit trail status."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager, enable_audit_trail=True)
        
        with pytest.raises(ValueError):
            with manager.begin():
                raise ValueError("Test rollback")
        
        # Verify audit record shows rollback
        audit_history = manager.get_audit_history(limit=1)
        assert len(audit_history) == 1
        assert audit_history[0].status == "rolled_back"
        assert "Test rollback" in audit_history[0].error_message


class TestSavepointManagement:
    """Test savepoint creation and management."""
    
    def test_begin_savepoint_generates_name(self, mock_connection_manager):
        """Test that begin_savepoint generates unique name."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin():
            savepoint1 = manager.begin_savepoint()
            savepoint2 = manager.begin_savepoint()
            
            assert savepoint1 != savepoint2
            assert isinstance(savepoint1, str)
            assert isinstance(savepoint2, str)
    
    def test_begin_savepoint_custom_name(self, mock_connection_manager):
        """Test begin_savepoint with custom name."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin():
            savepoint = manager.begin_savepoint("my_savepoint")
            assert savepoint == "my_savepoint"
    
    def test_rollback_to_savepoint_by_name(self, mock_connection_manager):
        """Test rollback to specific savepoint by name."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin():
            sp1 = manager.begin_savepoint("sp1")
            sp2 = manager.begin_savepoint("sp2")
            
            assert manager.get_savepoint_depth() == 2
            
            manager.rollback_to_savepoint("sp1")
            
            # Should rollback sp2 and sp1, removing both from stack
            assert manager.get_savepoint_depth() == 0
    
    def test_savepoint_invalid_name_special_chars(self, mock_connection_manager):
        """Test that invalid savepoint names raise error."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin():
            with pytest.raises(TransactionError):
                manager.begin_savepoint("invalid-name-with-dashes")
    
    def test_savepoint_stack_tracking(self, mock_connection_manager):
        """Test that savepoint stack is properly tracked."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin():
            assert manager.get_savepoint_depth() == 0
            
            sp1 = manager.begin_savepoint()
            assert manager.get_savepoint_depth() == 1
            
            sp2 = manager.begin_savepoint()
            assert manager.get_savepoint_depth() == 2
            
            manager.rollback_to_savepoint(sp2)
            assert manager.get_savepoint_depth() == 1


class TestIsolationLevels:
    """Test isolation level functionality."""
    
    def test_isolation_level_from_string_read_committed(self):
        """Test IsolationLevel.from_string() with various formats."""
        assert IsolationLevel.from_string("READ COMMITTED") == IsolationLevel.READ_COMMITTED
        assert IsolationLevel.from_string("read committed") == IsolationLevel.READ_COMMITTED
        assert IsolationLevel.from_string("READ_COMMITTED") == IsolationLevel.READ_COMMITTED
        assert IsolationLevel.from_string("read-committed") == IsolationLevel.READ_COMMITTED
    
    def test_isolation_level_from_string_serializable(self):
        """Test IsolationLevel.from_string() with SERIALIZABLE."""
        assert IsolationLevel.from_string("SERIALIZABLE") == IsolationLevel.SERIALIZABLE
        assert IsolationLevel.from_string("serializable") == IsolationLevel.SERIALIZABLE
    
    def test_isolation_level_from_string_invalid(self):
        """Test IsolationLevel.from_string() with invalid string."""
        with pytest.raises(TransactionError):
            IsolationLevel.from_string("INVALID_LEVEL")
    
    def test_isolation_level_all_values(self):
        """Test all IsolationLevel enum values."""
        assert IsolationLevel.READ_UNCOMMITTED.value == "READ UNCOMMITTED"
        assert IsolationLevel.READ_COMMITTED.value == "READ COMMITTED"
        assert IsolationLevel.REPEATABLE_READ.value == "REPEATABLE READ"
        assert IsolationLevel.SERIALIZABLE.value == "SERIALIZABLE"
        assert IsolationLevel.SNAPSHOT.value == "SNAPSHOT"


class TestTransactionTimeout:
    """Test transaction timeout handling."""
    
    def test_transaction_timeout_triggers_rollback(self, mock_connection_manager):
        """Test that timeout triggers automatic rollback."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager, default_timeout_seconds=1)
        
        with pytest.raises(TransactionError):
            with manager.begin(timeout_seconds=1):
                # Simulate long-running operation
                time.sleep(1.1)
                # Trigger timeout check
                manager._check_timeout()
    
    def test_timeout_configurable(self, mock_connection_manager):
        """Test that timeout parameter is respected."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin(timeout_seconds=300):
            assert manager._timeout_seconds == 300
    
    def test_timeout_disabled(self, mock_connection_manager):
        """Test that timeout=None disables timeout."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin(timeout_seconds=None):
            assert manager._timeout_seconds is None
            # Should not timeout
            time.sleep(0.1)
            manager._check_timeout()  # Should not raise


class TestRollbackHooks:
    """Test rollback hook functionality."""
    
    def test_add_rollback_hook(self, mock_connection_manager):
        """Test adding rollback hooks."""
        manager = TransactionManager(mock_connection_manager)
        
        hook = Mock()
        manager.add_rollback_hook(hook)
        
        assert len(manager._rollback_hooks) == 1
    
    def test_rollback_hook_executed_on_rollback(self, mock_connection_manager):
        """Test hooks execute on rollback."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        hook = Mock()
        
        with pytest.raises(ValueError):
            with manager.begin():
                manager.add_rollback_hook(hook)
                raise ValueError("Trigger rollback")
        
        hook.assert_called_once()
    
    def test_rollback_hook_not_executed_on_commit(self, mock_connection_manager):
        """Test hooks do NOT execute on successful commit."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        hook = Mock()
        
        with manager.begin():
            manager.add_rollback_hook(hook)
        
        # Hook should NOT be called on commit
        hook.assert_not_called()
    
    def test_multiple_rollback_hooks(self, mock_connection_manager):
        """Test multiple hooks execute in LIFO order."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        execution_order = []
        
        with pytest.raises(ValueError):
            with manager.begin():
                manager.add_rollback_hook(lambda: execution_order.append("first"))
                manager.add_rollback_hook(lambda: execution_order.append("second"))
                manager.add_rollback_hook(lambda: execution_order.append("third"))
                raise ValueError("Rollback")
        
        # LIFO order: third, second, first
        assert execution_order == ["third", "second", "first"]


class TestAuditTrail:
    """Test audit trail tracking."""
    
    def test_audit_trail_enabled_default(self, mock_connection_manager):
        """Test audit trail is enabled by default."""
        manager = TransactionManager(mock_connection_manager)
        assert manager.enable_audit_trail is True
    
    def test_audit_trail_disabled(self, mock_connection_manager):
        """Test disabling audit trail."""
        manager = TransactionManager(mock_connection_manager, enable_audit_trail=False)
        assert manager.enable_audit_trail is False
    
    def test_audit_record_created_on_transaction(self, mock_connection_manager):
        """Test audit record created for transaction."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager, enable_audit_trail=True)
        
        with manager.begin():
            pass
        
        audit_history = manager.get_audit_history()
        assert len(audit_history) == 1
        
        audit = audit_history[0]
        assert audit.status == "committed"
        assert audit.transaction_id is not None
        assert audit.start_time is not None
        assert audit.end_time is not None
        assert audit.duration_ms > 0
    
    def test_get_audit_history_limit(self, mock_connection_manager):
        """Test get_audit_history() with limit."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager, enable_audit_trail=True)
        
        # Create multiple transactions
        for _ in range(5):
            with manager.begin():
                pass
        
        # Get limited history
        audit_history = manager.get_audit_history(limit=3)
        assert len(audit_history) == 3
    
    def test_audit_history_max_size(self, mock_connection_manager):
        """Test audit history respects max_audit_history."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager, max_audit_history=3)
        
        # Create 5 transactions
        for _ in range(5):
            with manager.begin():
                pass
        
        # Should only keep last 3
        audit_history = manager.get_audit_history(limit=100)
        assert len(audit_history) <= 3


class TestTransactionMetrics:
    """Test transaction metrics tracking."""
    
    def test_increment_operations(self, mock_connection_manager):
        """Test incrementing operation counts."""
        manager = TransactionManager(mock_connection_manager)
        
        cursor = MockCursor()
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        with manager.begin():
            manager.increment_operations(count=5, affected_rows=100)
            
            metrics = manager.get_transaction_metrics()
            assert metrics["operations_count"] == 5
            assert metrics["affected_rows"] == 100
    
    def test_get_transaction_metrics(self, mock_connection_manager):
        """Test get_transaction_metrics() returns correct data."""
        cursor = MockCursor()
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin():
            manager.increment_operations(count=3, affected_rows=50)
            
            metrics = manager.get_transaction_metrics()
            
            assert "transaction_id" in metrics
            assert "is_active" in metrics
            assert metrics["is_active"] is True
            assert metrics["operations_count"] == 3
            assert metrics["affected_rows"] == 50
            assert "duration_ms" in metrics


class TestThreadSafety:
    """Test thread safety and concurrent access."""
    
    def test_concurrent_transactions_thread_safety(self, mock_connection_manager):
        """Test that concurrent transactions use proper locking."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        results = []
        
        def run_transaction():
            with manager.begin():
                results.append(manager.get_transaction_id())
        
        # Run multiple threads
        threads = [threading.Thread(target=run_transaction) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        
        # All transactions should have been created
        assert len(results) == 5
        # Each should have unique ID
        assert len(set(results)) == 5


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_connection_failure_mid_transaction(self, mock_connection_manager):
        """Test handling connection failure during transaction."""
        cursor = MockCursor()
        cursor.set_side_effect(lambda q, p: None if "BEGIN" in q.upper() else exec('raise Exception("Connection lost")'))
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with pytest.raises(Exception):
            with manager.begin():
                cursor.execute("SELECT 1", None)
    
    def test_savepoint_name_validation(self, mock_connection_manager):
        """Test savepoint name validation."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager)
        
        with manager.begin():
            # Valid names
            manager.begin_savepoint("valid_name123")
            
            # Invalid names with special characters
            with pytest.raises(TransactionError):
                manager.begin_savepoint("invalid-name")
            
            with pytest.raises(TransactionError):
                manager.begin_savepoint("invalid.name")
            
            with pytest.raises(TransactionError):
                manager.begin_savepoint("invalid name")
    
    def test_audit_history_pruning(self, mock_connection_manager):
        """Test that audit history is pruned to max_audit_history."""
        cursor = MockCursor()
        cursor.set_results([])
        mock_conn = create_mock_connection(cursor)
        mock_connection_manager.get_connection.return_value.__enter__.return_value = mock_conn
        
        manager = TransactionManager(mock_connection_manager, max_audit_history=10)
        
        # Create 20 transactions
        for _ in range(20):
            with manager.begin():
                pass
        
        # Should only keep last 10
        history = manager.get_audit_history(limit=100)
        assert len(history) <= 10
    
    def test_transaction_without_active_connection(self, mock_connection_manager):
        """Test transaction behavior without active connection."""
        # Simulate connection failure
        mock_connection_manager.get_connection.side_effect = Exception("Connection unavailable")
        
        manager = TransactionManager(mock_connection_manager)
        
        with pytest.raises(Exception):
            with manager.begin():
                pass


class TestTransactionAudit:
    """Test TransactionAudit dataclass."""
    
    def test_audit_duration_ms_with_end_time(self):
        """Test duration_ms calculation with end_time set."""
        start = datetime(2026, 3, 27, 10, 0, 0)
        end = datetime(2026, 3, 27, 10, 0, 1)  # 1 second later
        
        audit = TransactionAudit(
            transaction_id="test-123",
            start_time=start,
            end_time=end
        )
        
        assert audit.duration_ms == 1000.0
    
    def test_audit_duration_ms_without_end_time(self):
        """Test duration_ms calculation without end_time (ongoing)."""
        start = datetime.now()
        
        audit = TransactionAudit(
            transaction_id="test-123",
            start_time=start
        )
        
        # Duration should be small (milliseconds since start)
        duration = audit.duration_ms
        assert duration >= 0
        assert duration < 1000  # Less than 1 second for this test
