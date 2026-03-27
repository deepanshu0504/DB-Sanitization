"""Unit tests for Database Connection Manager.

Tests cover:
- ConnectionConfig validation and connection string generation
- Retry decorator behavior and exponential backoff
- ConnectionPool lifecycle and connection reuse
- DatabaseConnectionManager query execution and batch operations
- Context manager support and error handling

These tests use mocking to avoid requiring a real SQL Server instance.
For integration tests with a real database, see tests/integration/.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
import pyodbc

from src.database.connection_config import ConnectionConfig, AuthType
from src.database.connection_manager import (
    DatabaseConnectionManager,
    ConnectionPool,
    retry_on_connection_error
)
from src.exceptions import ConfigValidationError, ConnectionPoolError, DatabaseConnectionError


class TestConnectionConfig:
    """Test ConnectionConfig class for configuration validation."""
    
    def test_windows_auth_config(self):
        """Test Windows authentication configuration is valid."""
        config = ConnectionConfig(
            server="localhost",
            database="TestDB",
            auth_type=AuthType.WINDOWS
        )
        
        assert config.server == "localhost"
        assert config.database == "TestDB"
        assert config.auth_type == AuthType.WINDOWS
        assert config.port == 1433
        assert config.timeout == 30
        assert config.username is None
        assert config.password is None
    
    def test_sql_auth_config(self):
        """Test SQL Server authentication configuration is valid."""
        config = ConnectionConfig(
            server="localhost",
            database="TestDB",
            auth_type=AuthType.SQL,
            username="sa",
            password="P@ssw0rd123"
        )
        
        assert config.auth_type == AuthType.SQL
        assert config.username == "sa"
        assert config.password == "P@ssw0rd123"
    
    def test_sql_auth_missing_username(self):
        """Test SQL auth fails without username."""
        with pytest.raises(ValueError, match="username and password are required"):
            ConnectionConfig(
                server="localhost",
                database="TestDB",
                auth_type=AuthType.SQL,
                password="P@ssw0rd123"
            )
    
    def test_sql_auth_missing_password(self):
        """Test SQL auth fails without password."""
        with pytest.raises(ValueError, match="username and password are required"):
            ConnectionConfig(
                server="localhost",
                database="TestDB",
                auth_type=AuthType.SQL,
                username="sa"
            )
    
    def test_sql_auth_empty_credentials(self):
        """Test SQL auth fails with empty credentials."""
        with pytest.raises(ValueError, match="username and password are required"):
            ConnectionConfig(
                server="localhost",
                database="TestDB",
                auth_type=AuthType.SQL,
                username="",
                password=""
            )
    
    def test_invalid_timeout_zero(self):
        """Test timeout of zero raises error."""
        with pytest.raises(ValueError, match="timeout must be positive"):
            ConnectionConfig(
                server="localhost",
                database="TestDB",
                auth_type=AuthType.WINDOWS,
                timeout=0
            )
    
    def test_invalid_timeout_negative(self):
        """Test negative timeout raises error."""
        with pytest.raises(ValueError, match="timeout must be positive"):
            ConnectionConfig(
                server="localhost",
                database="TestDB",
                auth_type=AuthType.WINDOWS,
                timeout=-5
            )
    
    def test_invalid_port_zero(self):
        """Test port of zero raises error."""
        with pytest.raises(ValueError, match="port must be between"):
            ConnectionConfig(
                server="localhost",
                database="TestDB",
                auth_type=AuthType.WINDOWS,
                port=0
            )
    
    def test_invalid_port_too_high(self):
        """Test port above 65535 raises error."""
        with pytest.raises(ValueError, match="port must be between"):
            ConnectionConfig(
                server="localhost",
                database="TestDB",
                auth_type=AuthType.WINDOWS,
                port=70000
            )
    
    def test_empty_server(self):
        """Test empty server name raises error."""
        with pytest.raises(ValueError, match="server cannot be empty"):
            ConnectionConfig(
                server="",
                database="TestDB",
                auth_type=AuthType.WINDOWS
            )
    
    def test_empty_database(self):
        """Test empty database name raises error."""
        with pytest.raises(ValueError, match="database cannot be empty"):
            ConnectionConfig(
                server="localhost",
                database="",
                auth_type=AuthType.WINDOWS
            )
    
    def test_custom_port(self):
        """Test custom port is used."""
        config = ConnectionConfig(
            server="localhost",
            database="TestDB",
            auth_type=AuthType.WINDOWS,
            port=1435
        )
        
        assert config.port == 1435
    
    def test_custom_timeout(self):
        """Test custom timeout is used."""
        config = ConnectionConfig(
            server="localhost",
            database="TestDB",
            auth_type=AuthType.WINDOWS,
            timeout=60
        )
        
        assert config.timeout == 60
    
    def test_connection_string_windows_auth(self):
        """Test connection string generation for Windows authentication."""
        config = ConnectionConfig(
            server="localhost",
            database="TestDB",
            auth_type=AuthType.WINDOWS
        )
        
        conn_str = config.get_connection_string()
        
        assert "DRIVER={ODBC Driver 17 for SQL Server}" in conn_str
        assert "SERVER=localhost,1433" in conn_str
        assert "DATABASE=TestDB" in conn_str
        assert "Trusted_Connection=yes" in conn_str
        assert "Timeout=30" in conn_str
        assert "Encrypt=yes" in conn_str
        assert "TrustServerCertificate=yes" in conn_str
        assert "PWD" not in conn_str
        assert "UID" not in conn_str
    
    def test_connection_string_sql_auth(self):
        """Test connection string generation for SQL authentication."""
        config = ConnectionConfig(
            server="localhost",
            database="TestDB",
            auth_type=AuthType.SQL,
            username="sa",
            password="P@ssw0rd123"
        )
        
        conn_str = config.get_connection_string()
        
        assert "UID=sa" in conn_str
        assert "PWD=P@ssw0rd123" in conn_str
        assert "Trusted_Connection" not in conn_str
    
    def test_connection_string_custom_port(self):
        """Test connection string includes custom port."""
        config = ConnectionConfig(
            server="localhost",
            database="TestDB",
            auth_type=AuthType.WINDOWS,
            port=1435
        )
        
        conn_str = config.get_connection_string()
        assert "SERVER=localhost,1435" in conn_str
    
    def test_repr_no_password_windows(self):
        """Test __repr__ doesn't expose password for Windows auth."""
        config = ConnectionConfig(
            server="localhost",
            database="TestDB",
            auth_type=AuthType.WINDOWS
        )
        
        repr_str = repr(config)
        
        assert "localhost" in repr_str
        assert "TestDB" in repr_str
        assert "windows" in repr_str
        assert "password" not in repr_str.lower()
    
    def test_repr_no_password_sql(self):
        """Test __repr__ doesn't expose password for SQL auth."""
        config = ConnectionConfig(
            server="localhost",
            database="TestDB",
            auth_type=AuthType.SQL,
            username="sa",
            password="P@ssw0rd123"
        )
        
        repr_str = repr(config)
        
        assert "P@ssw0rd123" not in repr_str
        assert "sa" in repr_str  # Username is OK to show
        assert "localhost" in repr_str


class TestRetryDecorator:
    """Test retry_on_connection_error decorator."""
    
    def test_successful_call_no_retry(self):
        """Test successful call on first attempt doesn't retry."""
        call_count = 0
        
        @retry_on_connection_error(max_attempts=3)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = succeed()
        
        assert result == "success"
        assert call_count == 1
    
    def test_retry_on_failure(self, mocker):
        """Test function retries on transient failure."""
        call_count = 0
        
        @retry_on_connection_error(max_attempts=3, backoff_factor=0.01)
        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise pyodbc.OperationalError("Connection failed")
            return "success"
        
        # Mock time.sleep to speed up test
        mocker.patch('time.sleep')
        
        result = fail_twice()
        
        assert result == "success"
        assert call_count == 3
    
    def test_max_retries_exceeded(self, mocker):
        """Test exception is raised after max retries."""
        call_count = 0
        
        @retry_on_connection_error(max_attempts=3, backoff_factor=0.01)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise pyodbc.OperationalError("Always fails")
        
        mocker.patch('time.sleep')
        
        with pytest.raises(pyodbc.OperationalError, match="Always fails"):
            always_fail()
        
        assert call_count == 3
    
    def test_exponential_backoff(self, mocker):
        """Test exponential backoff delays are correct."""
        @retry_on_connection_error(max_attempts=4, backoff_factor=1.0)
        def always_fail():
            raise pyodbc.OperationalError("Fail")
        
        mock_sleep = mocker.patch('time.sleep')
        
        with pytest.raises(pyodbc.OperationalError):
            always_fail()
        
        # Verify sleep was called with exponential delays: 1s, 2s, 4s
        expected_delays = [1.0, 2.0, 4.0]
        actual_delays = [call[0][0] for call in mock_sleep.call_args_list]
        assert actual_delays == expected_delays
    
    def test_custom_backoff_factor(self, mocker):
        """Test custom backoff factor is used."""
        @retry_on_connection_error(max_attempts=3, backoff_factor=2.0)
        def always_fail():
            raise pyodbc.OperationalError("Fail")
        
        mock_sleep = mocker.patch('time.sleep')
        
        with pytest.raises(pyodbc.OperationalError):
            always_fail()
        
        # With backoff_factor=2.0: 2s, 4s
        expected_delays = [2.0, 4.0]
        actual_delays = [call[0][0] for call in mock_sleep.call_args_list]
        assert actual_delays == expected_delays


@pytest.fixture
def mock_config():
    """Fixture providing mock configuration."""
    return ConnectionConfig(
        server="localhost",
        database="TestDB",
        auth_type=AuthType.WINDOWS
    )


@pytest.fixture
def mock_connection():
    """Fixture providing mock pyodbc connection."""
    conn = MagicMock(spec=pyodbc.Connection)
    cursor = MagicMock()
    
    # Mock cursor behavior
    cursor.execute.return_value = None
    cursor.fetchall.return_value = [(1,)]
    cursor.fetchone.return_value = (1,)
    cursor.rowcount = 1
    
    conn.cursor.return_value = cursor
    conn.timeout = 30
    
    return conn


class TestConnectionPool:
    """Test ConnectionPool class."""
    
    def test_pool_initialization(self, mock_config):
        """Test pool initializes with correct parameters."""
        pool = ConnectionPool(mock_config, pool_size=5, timeout=30)
        
        assert pool.pool_size == 5
        assert pool.timeout == 30
        assert pool._connection_count == 0
    
    def test_invalid_pool_size(self, mock_config):
        """Test pool rejects invalid pool size."""
        with pytest.raises(ValueError, match="pool_size must be positive"):
            ConnectionPool(mock_config, pool_size=0)
    
    def test_invalid_timeout(self, mock_config):
        """Test pool rejects invalid timeout."""
        with pytest.raises(ValueError, match="timeout must be positive"):
            ConnectionPool(mock_config, pool_size=5, timeout=-1)
    
    @patch('pyodbc.connect')
    def test_get_connection_creates_new(self, mock_connect, mock_config, mock_connection):
        """Test getting connection when pool is empty creates new connection."""
        mock_connect.return_value = mock_connection
        
        pool = ConnectionPool(mock_config, pool_size=5)
        conn = pool.get_connection()
        
        assert conn is not None
        assert pool._connection_count == 1
        mock_connect.assert_called_once()
    
    @patch('pyodbc.connect')
    def test_return_connection_to_pool(self, mock_connect, mock_config, mock_connection):
        """Test returning connection adds it to pool."""
        mock_connect.return_value = mock_connection
        
        pool = ConnectionPool(mock_config, pool_size=5)
        conn = pool.get_connection()
        pool.return_connection(conn)
        
        # Pool should now have 1 connection
        assert not pool._pool.empty()
    
    @patch('pyodbc.connect')
    def test_reuse_pooled_connection(self, mock_connect, mock_config, mock_connection):
        """Test connection is reused from pool."""
        mock_connect.return_value = mock_connection
        
        pool = ConnectionPool(mock_config, pool_size=5)
        
        # Get and return connection
        conn1 = pool.get_connection()
        pool.return_connection(conn1)
        
        # Get connection again - should reuse
        conn2 = pool.get_connection()
        
        assert conn1 is conn2
        # Should only call connect once
        assert mock_connect.call_count == 1
    
    @patch('pyodbc.connect')
    def test_pool_max_capacity(self, mock_connect, mock_config, mock_connection):
        """Test pool respects maximum capacity."""
        mock_connect.return_value = mock_connection
        
        pool = ConnectionPool(mock_config, pool_size=2)
        
        # Get max connections
        conn1 = pool.get_connection()
        conn2 = pool.get_connection()
        
        # Trying to get another should raise error
        with pytest.raises(RuntimeError, match="Connection pool exhausted"):
            pool.get_connection()
    
    @patch('pyodbc.connect')
    def test_close_all(self, mock_connect, mock_config, mock_connection):
        """Test closing all connections in pool."""
        mock_connect.return_value = mock_connection
        
        pool = ConnectionPool(mock_config, pool_size=5)
        
        # Create and return some connections
        conn1 = pool.get_connection()
        conn2 = pool.get_connection()
        pool.return_connection(conn1)
        pool.return_connection(conn2)
        
        pool.close_all()
        
        assert pool._pool.empty()
        assert pool._connection_count == 0


class TestDatabaseConnectionManager:
    """Test DatabaseConnectionManager class."""
    
    @patch('pyodbc.connect')
    def test_manager_initialization_with_pooling(self, mock_connect, mock_config):
        """Test manager initializes correctly with pooling enabled."""
        manager = DatabaseConnectionManager(mock_config, pool_size=5, enable_pooling=True)
        
        assert manager.config is mock_config
        assert manager.enable_pooling is True
        assert manager._pool is not None
    
    @patch('pyodbc.connect')
    def test_manager_initialization_without_pooling(self, mock_connect, mock_config):
        """Test manager initializes correctly with pooling disabled."""
        manager = DatabaseConnectionManager(mock_config, enable_pooling=False)
        
        assert manager.config is mock_config
        assert manager.enable_pooling is False
        assert manager._pool is None
    
    @patch('pyodbc.connect')
    def test_get_connection(self, mock_connect, mock_config, mock_connection):
        """Test getting connection from manager."""
        mock_connect.return_value = mock_connection
        
        manager = DatabaseConnectionManager(mock_config)
        conn = manager.get_connection()
        
        assert conn is not None
        mock_connect.assert_called_once()
    
    @patch('pyodbc.connect')
    def test_context_manager(self, mock_connect, mock_config, mock_connection):
        """Test context manager usage."""
        mock_connect.return_value = mock_connection
        
        manager = DatabaseConnectionManager(mock_config)
        
        with manager.get_connection_context() as conn:
            assert conn is not None
        
        # Connection should be returned to pool
        assert not manager._pool._pool.empty()
    
    @patch('pyodbc.connect')
    def test_execute_query(self, mock_connect, mock_config, mock_connection):
        """Test simple query execution."""
        mock_connect.return_value = mock_connection
        
        manager = DatabaseConnectionManager(mock_config)
        results = manager.execute_query("SELECT 1")
        
        assert results is not None
        mock_connection.cursor().execute.assert_called_once_with("SELECT 1")
    
    @patch('pyodbc.connect')
    def test_execute_query_with_params(self, mock_connect, mock_config, mock_connection):
        """Test parameterized query execution."""
        mock_connect.return_value = mock_connection
        
        manager = DatabaseConnectionManager(mock_config)
        results = manager.execute_query(
            "SELECT * FROM Users WHERE id = ?",
            params=(123,)
        )
        
        mock_connection.cursor().execute.assert_called_with(
            "SELECT * FROM Users WHERE id = ?",
            (123,)
        )
    
    @patch('pyodbc.connect')
    def test_execute_query_no_fetch(self, mock_connect, mock_config, mock_connection):
        """Test query execution without fetching results."""
        mock_connect.return_value = mock_connection
        
        manager = DatabaseConnectionManager(mock_config)
        results = manager.execute_query(
            "UPDATE Users SET active = 1",
            fetch=False
        )
        
        assert results is None
        mock_connection.commit.assert_called_once()
    
    @patch('pyodbc.connect')
    def test_execute_batch(self, mock_connect, mock_config, mock_connection):
        """Test batch execution."""
        mock_connect.return_value = mock_connection
        mock_connection.cursor().rowcount = 3
        
        manager = DatabaseConnectionManager(mock_config)
        affected = manager.execute_batch(
            "INSERT INTO Users (name) VALUES (?)",
            [("Alice",), ("Bob",), ("Charlie",)]
        )
        
        assert affected == 3
        mock_connection.cursor().executemany.assert_called_once()
        mock_connection.commit.assert_called_once()
    
    @patch('pyodbc.connect')
    def test_health_check_success(self, mock_connect, mock_config, mock_connection):
        """Test successful health check."""
        mock_connect.return_value = mock_connection
        
        manager = DatabaseConnectionManager(mock_config)
        is_healthy = manager.health_check()
        
        assert is_healthy is True
    
    @patch('pyodbc.connect')
    def test_health_check_failure(self, mock_connect, mock_config, mock_connection):
        """Test failed health check."""
        mock_connect.return_value = mock_connection
        mock_connection.cursor().execute.side_effect = pyodbc.Error("Connection lost")
        
        manager = DatabaseConnectionManager(mock_config)
        is_healthy = manager.health_check()
        
        assert is_healthy is False
    
    @patch('pyodbc.connect')
    def test_manager_close(self, mock_connect, mock_config, mock_connection):
        """Test closing manager cleans up pool."""
        mock_connect.return_value = mock_connection
        
        manager = DatabaseConnectionManager(mock_config)
        conn = manager.get_connection()
        manager.return_connection(conn)
        
        manager.close()
        
        # Pool should be empty after close
        assert manager._pool._pool.empty()
    
    @patch('pyodbc.connect')
    def test_with_statement(self, mock_connect, mock_config, mock_connection):
        """Test using manager with 'with' statement."""
        mock_connect.return_value = mock_connection
        
        with DatabaseConnectionManager(mock_config) as manager:
            conn = manager.get_connection()
            assert conn is not None
        
        # Manager should be closed after with block
        # (pool cleaned up)
