"""SQL Server connection manager with retry logic and connection pooling.

This module provides a robust connection management system for SQL Server with:
- Thread-safe connection pooling for improved performance
- Automatic retry with exponential backoff for transient failures
- Context manager support for clean resource management
- Health check capabilities
- Batch operation support

Security:
    - No credentials are logged
    - Supports encrypted connections
    - Parameterized query execution only
"""

import time
import logging
from typing import Optional, List, Tuple, Any, Callable, TypeVar
from functools import wraps
from contextlib import contextmanager
from queue import Queue, Empty
from threading import Lock

import pyodbc

from .connection_config import ConnectionConfig
from ..exceptions import (
    DatabaseConnectionError,
    DatabaseQueryError,
    ConnectionPoolError,
    HealthCheckError,
    ConfigValidationError,
    SanitizationError,
    TransactionError
)
from ..error_codes import ErrorCodes

# Configure module logger
logger = logging.getLogger(__name__)

# Type variable for generic retry decorator
T = TypeVar('T')


def retry_on_connection_error(
    max_attempts: int = 3,
    backoff_factor: float = 1.0,
    exceptions: tuple = (pyodbc.Error, pyodbc.OperationalError)
) -> Callable:
    """Decorator to retry operations on connection errors with exponential backoff.
    
    This decorator automatically retries a function when it raises specific exceptions,
    using exponential backoff to avoid overwhelming the database server.
    
    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
        backoff_factor: Base delay multiplier for exponential backoff (default: 1.0)
            Delays will be: backoff_factor * 2^0, backoff_factor * 2^1, backoff_factor * 2^2, ...
            Example: With backoff_factor=1.0, delays are 1s, 2s, 4s, 8s, ...
        exceptions: Tuple of exception types to catch and retry (default: pyodbc errors)
    
    Returns:
        Decorated function with retry logic
    
    Example:
        >>> @retry_on_connection_error(max_attempts=3, backoff_factor=2.0)
        ... def connect_to_database():
        ...     return pyodbc.connect(connection_string)
        
        >>> # Will retry up to 3 times with delays of 2s, 4s, 8s
        >>> connection = connect_to_database()
    
    Raises:
        Last exception encountered if all retry attempts fail
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    # Attempt to execute the function
                    return func(*args, **kwargs)
                
                except SanitizationError as e:
                    # For our custom exceptions, check if retryable
                    if not e.is_retryable:
                        logger.error(
                            f"{func.__name__} failed with non-retryable error [{e.error_code}]: {e.message}"
                        )
                        raise  # Don't retry, re-raise immediately
                    
                    last_exception = e
                    
                    # If this was the last attempt, log and re-raise
                    if attempt == max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts [{e.error_code}]: {e.message}"
                        )
                        # Mark as no longer retryable
                        e.is_retryable = False
                        raise
                    
                    # Calculate exponential backoff delay
                    delay = backoff_factor * (2 ** (attempt - 1))
                    
                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed [{e.error_code}]: {e.message}. "
                        f"Retrying in {delay}s..."
                    )
                    
                    time.sleep(delay)
                    
                except exceptions as e:
                    last_exception = e
                    
                    # If this was the last attempt, log error and raise custom exception
                    if attempt == max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        # Wrap in custom exception with retry metadata
                        raise DatabaseConnectionError(
                            message=f"Connection failed after {max_attempts} retry attempts: {str(e)}",
                            error_code=ErrorCodes.CONN_FAILED,
                            is_retryable=False,
                            suggested_action="Check connection settings and ensure the database server is accessible",
                            operation_context={"max_attempts": max_attempts, "original_error": str(e)}
                        ) from e
                    
                    # Calculate exponential backoff delay
                    delay = backoff_factor * (2 ** (attempt - 1))
                    
                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                        f"Retrying in {delay}s..."
                    )
                    
                    time.sleep(delay)
            
            # Should never reach here, but satisfy type checker
            if last_exception:
                raise last_exception
            raise DatabaseConnectionError(
                message="Unexpected state in retry decorator",
                error_code=ErrorCodes.CONN_FAILED,
                is_retryable=False,
                suggested_action="This should not occur; please report as a bug"
            )
        
        return wrapper
    return decorator


class ConnectionPool:
    """Thread-safe connection pool for SQL Server connections.
    
    Manages a pool of reusable database connections to minimize connection
    overhead and improve performance. Supports automatic health checks and
    connection recycling.
    
    Attributes:
        config: Connection configuration
        pool_size: Maximum number of connections in the pool
        timeout: Maximum time (seconds) to wait for an available connection
    
    Example:
        >>> config = ConnectionConfig(server="localhost", database="TestDB", auth_type=AuthType.WINDOWS)
        >>> pool = ConnectionPool(config, pool_size=5)
        >>> conn = pool.get_connection()
        >>> # Use connection...
        >>> pool.return_connection(conn)
        >>> pool.close_all()
    
    Thread Safety:
        All public methods are thread-safe and can be called from multiple threads.
    """
    
    def __init__(
        self,
        config: ConnectionConfig,
        pool_size: int = 5,
        timeout: int = 30
    ):
        """Initialize connection pool.
        
        Args:
            config: Database connection configuration
            pool_size: Maximum connections to maintain in pool (default: 5)
            timeout: Seconds to wait for available connection (default: 30)
        
        Raises:
            ValueError: If pool_size or timeout are invalid
        """
        if pool_size <= 0:
            raise ConfigValidationError.invalid_value(
                field="pool_size",
                value=pool_size,
                expected="positive integer"
            )
        if timeout <= 0:
            raise ConfigValidationError.invalid_value(
                field="timeout",
                value=timeout,
                expected="positive integer"
            )
        
        self.config = config
        self.pool_size = pool_size
        self.timeout = timeout
        
        self._pool: Queue = Queue(maxsize=pool_size)
        self._lock = Lock()
        self._connection_count = 0
        
        logger.info(
            f"Initialized connection pool (size={pool_size}) for "
            f"{config.server}/{config.database}"
        )
    
    def _create_connection(self) -> pyodbc.Connection:
        """Create new database connection with retry logic.
        
        Returns:
            New pyodbc connection
        
        Raises:
            pyodbc.Error: If connection fails after all retry attempts
        """
        @retry_on_connection_error(max_attempts=3, backoff_factor=1.0)
        def _connect() -> pyodbc.Connection:
            connection_string = self.config.get_connection_string()
            
            logger.debug(
                f"Creating connection to {self.config.server}/{self.config.database}"
            )
            
            conn = pyodbc.connect(connection_string)
            conn.timeout = self.config.timeout
            
            return conn
        
        return _connect()
    
    def get_connection(self) -> pyodbc.Connection:
        """Get connection from pool or create new one.
        
        Attempts to retrieve an existing connection from the pool. If the pool
        is empty and the pool size limit hasn't been reached, creates a new connection.
        Tests connection health before returning.
        
        Returns:
            Active database connection
        
        Raises:
            TimeoutError: If no connection available within timeout period
            RuntimeError: If pool is at maximum capacity
            pyodbc.Error: If connection creation fails
        """
        try:
            # Try to get existing connection from pool (blocking with timeout)
            conn = self._pool.get(block=True, timeout=self.timeout)
            
            # Test if connection is still alive
            if self._is_connection_alive(conn):
                logger.debug("Reusing pooled connection")
                return conn
            else:
                logger.warning("Pooled connection is dead, creating new one")
                try:
                    conn.close()
                except:
                    pass
                
                with self._lock:
                    self._connection_count -= 1
                
                return self._create_new_connection()
                
        except Empty:
            # Pool is empty, try to create new connection if under limit
            return self._create_new_connection()
    
    def _create_new_connection(self) -> pyodbc.Connection:
        """Create new connection if pool is not at capacity.
        
        Returns:
            New database connection
        
        Raises:
            RuntimeError: If pool is at maximum capacity
            pyodbc.Error: If connection creation fails
        """
        with self._lock:
            if self._connection_count >= self.pool_size:
                raise ConnectionPoolError.pool_exhausted(
                    pool_size=self.pool_size,
                    current_count=self._connection_count
                )
            
            conn = self._create_connection()
            self._connection_count += 1
            logger.info(
                f"Created new connection ({self._connection_count}/{self.pool_size})"
            )
            
            return conn
    
    def return_connection(self, conn: pyodbc.Connection):
        """Return connection to pool for reuse.
        
        Tests connection health before returning to pool. Dead connections
        are closed and discarded.
        
        Args:
            conn: Connection to return to pool
        """
        if conn is None:
            return
        
        try:
            if self._is_connection_alive(conn):
                self._pool.put(conn, block=False)
                logger.debug("Returned connection to pool")
            else:
                logger.warning("Not returning dead connection to pool")
                try:
                    conn.close()
                except:
                    pass
                
                with self._lock:
                    self._connection_count -= 1
                    
        except Exception as e:
            logger.error(f"Error returning connection to pool: {e}")
            try:
                conn.close()
            except:
                pass
    
    def _is_connection_alive(self, conn: pyodbc.Connection) -> bool:
        """Check if connection is still active.
        
        Args:
            conn: Connection to test
        
        Returns:
            True if connection is alive and responsive, False otherwise
        """
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            return True
        except:
            return False
    
    def close_all(self):
        """Close all connections in the pool.
        
        This method should be called when shutting down the application
        to ensure proper cleanup of database connections.
        """
        logger.info("Closing all pooled connections")
        
        closed_count = 0
        while not self._pool.empty():
            try:
                conn = self._pool.get(block=False)
                conn.close()
                closed_count += 1
            except Empty:
                break
            except Exception as e:
                logger.error(f"Error closing pooled connection: {e}")
        
        with self._lock:
            self._connection_count = 0
        
        logger.info(f"Closed {closed_count} pooled connections")


class DatabaseConnectionManager:
    """Manages SQL Server database connections with pooling and retry logic.
    
    This class provides a high-level interface for database operations with:
    - Automatic connection pooling for performance
    - Retry logic for transient failures
    - Context manager support for clean resource management
    - Health checks and monitoring
    - Batch operation support
    - Security best practices (no credential logging)
    
    Example:
        >>> # Basic usage
        >>> config = ConnectionConfig(
        ...     server="localhost",
        ...     database="TestDB",
        ...     auth_type=AuthType.WINDOWS
        ... )
        >>> manager = DatabaseConnectionManager(config)
        
        >>> # Execute query
        >>> results = manager.execute_query("SELECT * FROM Users WHERE age > ?", params=(18,))
        
        >>> # Context manager usage (recommended)
        >>> with manager.get_connection_context() as conn:
        ...     cursor = conn.cursor()
        ...     cursor.execute("SELECT COUNT(*) FROM Users")
        ...     count = cursor.fetchone()[0]
        
        >>> # Batch operations
        >>> data = [(1, "Alice"), (2, "Bob"), (3, "Charlie")]
        >>> affected = manager.execute_batch(
        ...     "INSERT INTO Users (id, name) VALUES (?, ?)",
        ...     data
        ... )
        
        >>> # Cleanup
        >>> manager.close()
    
    Thread Safety:
        This class is thread-safe when connection pooling is enabled.
    """
    
    def __init__(
        self,
        config: ConnectionConfig,
        pool_size: int = 5,
        enable_pooling: bool = True
    ):
        """Initialize connection manager.
        
        Args:
            config: Database connection configuration
            pool_size: Maximum connections in pool (default: 5, ignored if pooling disabled)
            enable_pooling: Enable connection pooling for better performance (default: True)
        """
        self.config = config
        self.enable_pooling = enable_pooling
        
        if enable_pooling:
            self._pool = ConnectionPool(config, pool_size)
        else:
            self._pool = None
        
        logger.info(
            f"Initialized DatabaseConnectionManager for "
            f"{config.server}/{config.database} "
            f"(pooling={'enabled' if enable_pooling else 'disabled'})"
        )
    
    def get_connection(self) -> pyodbc.Connection:
        """Get database connection from pool or create new one.
        
        Returns:
            Active database connection
        
        Raises:
            pyodbc.Error: If connection fails
            RuntimeError: If pool is exhausted (when pooling enabled)
        """
        if self.enable_pooling:
            return self._pool.get_connection()
        else:
            return self._create_direct_connection()
    
    def _create_direct_connection(self) -> pyodbc.Connection:
        """Create direct connection without pooling.
        
        Returns:
            New database connection
        
        Raises:
            pyodbc.Error: If connection fails after retries
        """
        @retry_on_connection_error(max_attempts=3, backoff_factor=1.0)
        def _connect() -> pyodbc.Connection:
            connection_string = self.config.get_connection_string()
            return pyodbc.connect(connection_string)
        
        return _connect()
    
    def return_connection(self, conn: pyodbc.Connection):
        """Return connection to pool or close it.
        
        Args:
            conn: Connection to return
        """
        if conn is None:
            return
        
        if self.enable_pooling:
            self._pool.return_connection(conn)
        else:
            try:
                conn.close()
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
    
    @contextmanager
    def get_connection_context(self):
        """Context manager for automatic connection management.
        
        Yields:
            Database connection
        
        Example:
            >>> with manager.get_connection_context() as conn:
            ...     cursor = conn.cursor()
            ...     cursor.execute("SELECT 1")
            ...     result = cursor.fetchone()
        
        The connection is automatically returned to the pool (or closed) when
        the context exits, even if an exception occurs.
        """
        conn = self.get_connection()
        try:
            yield conn
        finally:
            self.return_connection(conn)
    
    @contextmanager
    def transaction_context(self):
        """Context manager for transaction management with automatic commit/rollback.
        
        This context manager provides ACID transaction semantics:
        - Begins a transaction on entry
        - Commits the transaction on successful exit
        - Rolls back the transaction if an exception occurs
        - Ensures the connection is returned to the pool
        
        Yields:
            Database connection with active transaction
        
        Raises:
            TransactionError: If transaction operations fail
            Exception: Any exception from code within the context
        
        Example:
            >>> with manager.transaction_context() as conn:
            ...     cursor = conn.cursor()
            ...     cursor.execute("UPDATE Users SET active = 1 WHERE id = ?", (123,))
            ...     cursor.execute("INSERT INTO AuditLog (action) VALUES (?)", ("user_activated",))
            ...     # Auto-commits on success, auto-rolls back on exception
        
        Note:
            - Do not call conn.commit() or conn.rollback() manually within the context
            - Nested transactions are not supported - raises TransactionError
            - All operations within the context are part of a single transaction
        
        Security:
            Always use parameterized queries to prevent SQL injection.
        """
        conn = self.get_connection()
        
        # Check if connection already has an active transaction
        # SQL Server doesn't allow nested transactions with pyodbc in the same connection
        try:
            # Attempt to check transaction state
            cursor = conn.cursor()
            cursor.execute("SELECT @@TRANCOUNT AS trancount")
            trancount = cursor.fetchone()[0]
            cursor.close()
            
            if trancount > 0:
                logger.error(f"Nested transaction attempt detected (trancount={trancount})")
                self.return_connection(conn)
                raise TransactionError.nested_transaction_error(trancount=trancount)
        except pyodbc.Error as e:
            logger.error(f"Failed to check transaction state: {e}")
            self.return_connection(conn)
            raise TransactionError.begin_failed(
                reason=str(e),
                operation="check_transaction_state"
            ) from e
        
        # Begin transaction
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN TRANSACTION")
            cursor.close()
            logger.debug("Transaction started")
        except pyodbc.Error as e:
            logger.error(f"Failed to begin transaction: {e}")
            self.return_connection(conn)
            raise TransactionError.begin_failed(
                reason=str(e)
            ) from e
        
        try:
            # Yield connection for use within context
            yield conn
            
            # Commit transaction on successful completion
            try:
                cursor = conn.cursor()
                cursor.execute("COMMIT TRANSACTION")
                cursor.close()
                logger.debug("Transaction committed successfully")
            except pyodbc.Error as e:
                logger.error(f"Failed to commit transaction: {e}")
                raise TransactionError.commit_failed(
                    reason=str(e)
                ) from e
                
        except Exception as e:
            # Rollback transaction on any exception
            logger.warning(f"Exception in transaction context, rolling back: {e}")
            try:
                cursor = conn.cursor()
                cursor.execute("ROLLBACK TRANSACTION")
                cursor.close()
                logger.debug("Transaction rolled back successfully")
            except pyodbc.Error as rollback_error:
                logger.error(f"Failed to rollback transaction: {rollback_error}")
                # Re-raise rollback error as it's more critical
                raise TransactionError.rollback_failed(
                    reason=str(rollback_error),
                    original_error=str(e)
                ) from rollback_error
            
            # Re-raise the original exception after successful rollback
            raise
            
        finally:
            # Always return connection to pool
            self.return_connection(conn)
    
    def execute_query(
        self,
        query: str,
        params: Optional[Tuple] = None,
        fetch: bool = True
    ) -> Optional[List[Tuple]]:
        """Execute SQL query with automatic connection management.
        
        Args:
            query: SQL query to execute (use ? for parameters)
            params: Optional query parameters for parameterized queries
            fetch: Whether to fetch and return results (default: True)
        
        Returns:
            Query results as list of tuples if fetch=True, None otherwise
        
        Raises:
            pyodbc.Error: If query execution fails
        
        Example:
            >>> # Simple query
            >>> results = manager.execute_query("SELECT * FROM Users")
            
            >>> # Parameterized query
            >>> results = manager.execute_query(
            ...     "SELECT * FROM Users WHERE age > ? AND city = ?",
            ...     params=(18, "New York")
            ... )
            
            >>> # Non-query operation
            >>> manager.execute_query(
            ...     "UPDATE Users SET active = 1 WHERE id = ?",
            ...     params=(123,),
            ...     fetch=False
            ... )
        
        Security:
            Always use parameterized queries to prevent SQL injection.
        """
        with self.get_connection_context() as conn:
            cursor = conn.cursor()
            
            try:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                
                if fetch:
                    results = cursor.fetchall()
                    return results
                else:
                    conn.commit()
                    return None
                    
            finally:
                cursor.close()
    
    def execute_batch(
        self,
        query: str,
        params_list: List[Tuple]
    ) -> int:
        """Execute batch query with multiple parameter sets.
        
        This method is optimized for inserting or updating large numbers of rows
        by executing a single query with multiple parameter sets.
        
        Args:
            query: SQL query with parameter placeholders (?)
            params_list: List of parameter tuples
        
        Returns:
            Total number of affected rows
        
        Raises:
            pyodbc.Error: If batch execution fails
        
        Example:
            >>> data = [
            ...     ("Alice", 30),
            ...     ("Bob", 25),
            ...     ("Charlie", 35)
            ... ]
            >>> affected = manager.execute_batch(
            ...     "INSERT INTO Users (name, age) VALUES (?, ?)",
            ...     data
            ... )
            >>> print(f"Inserted {affected} rows")
        
        Performance:
            Much faster than executing individual queries in a loop.
        """
        with self.get_connection_context() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.executemany(query, params_list)
                conn.commit()
                return cursor.rowcount
                
            finally:
                cursor.close()
    
    def health_check(self) -> bool:
        """Perform health check on database connection.
        
        Returns:
            True if connection is healthy and database is responsive, False otherwise
        
        Example:
            >>> if manager.health_check():
            ...     print("Database is healthy")
            ... else:
            ...     print("Database connection failed")
        """
        try:
            result = self.execute_query("SELECT 1 AS health_check")
            return result is not None and len(result) > 0
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    def close(self):
        """Close all connections and cleanup resources.
        
        This method should be called when shutting down to ensure
        proper cleanup of all database connections.
        
        Example:
            >>> manager = DatabaseConnectionManager(config)
            >>> # Use manager...
            >>> manager.close()
        """
        if self.enable_pooling and self._pool:
            self._pool.close_all()
        
        logger.info("DatabaseConnectionManager closed")
    
    def __enter__(self):
        """Support 'with' statement for manager lifecycle.
        
        Example:
            >>> with DatabaseConnectionManager(config) as manager:
            ...     results = manager.execute_query("SELECT 1")
        """
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Cleanup on exit from 'with' block."""
        self.close()
        return False
