"""Integration tests for DatabaseConnectionManager with real SQL Server.

IMPORTANT: These tests require a running SQL Server instance.

Setup:
    Set environment variables before running:
    - SQLSERVER_HOST=localhost (or your server address)
    - SQLSERVER_DB=master (or test database name)
    - SQLSERVER_AUTH=windows|sql
    - SQLSERVER_USER=sa (required if SQLSERVER_AUTH=sql)
    - SQLSERVER_PASS=YourPassword (required if SQLSERVER_AUTH=sql)

Run:
    # Windows Authentication
    $env:SQLSERVER_HOST="localhost"
    $env:SQLSERVER_DB="master"
    $env:SQLSERVER_AUTH="windows"
    pytest tests/integration/ -v

    # SQL Authentication
    $env:SQLSERVER_HOST="localhost"
    $env:SQLSERVER_DB="master"
    $env:SQLSERVER_AUTH="sql"
    $env:SQLSERVER_USER="sa"
    $env:SQLSERVER_PASS="YourPassword123"
    pytest tests/integration/ -v

Note:
    Tests will be skipped if SQL Server is not available or
    environment variables are not set.
"""

import os
import pytest
import pyodbc

from src.database.connection_config import ConnectionConfig, AuthType
from src.database.connection_manager import DatabaseConnectionManager


def get_test_config() -> ConnectionConfig:
    """Get SQL Server configuration from environment variables.
    
    Returns:
        ConnectionConfig instance
    
    Raises:
        pytest.skip: If required environment variables are not set
    """
    server = os.getenv("SQLSERVER_HOST")
    database = os.getenv("SQLSERVER_DB")
    auth_type_str = os.getenv("SQLSERVER_AUTH")
    
    if not server or not database or not auth_type_str:
        pytest.skip(
            "SQL Server integration tests require environment variables: "
            "SQLSERVER_HOST, SQLSERVER_DB, SQLSERVER_AUTH"
        )
    
    auth_type = AuthType.WINDOWS if auth_type_str.lower() == "windows" else AuthType.SQL
    
    if auth_type == AuthType.SQL:
        username = os.getenv("SQLSERVER_USER")
        password = os.getenv("SQLSERVER_PASS")
        
        if not username or not password:
            pytest.skip(
                "SQL authentication requires SQLSERVER_USER and SQLSERVER_PASS "
                "environment variables"
            )
        
        return ConnectionConfig(
            server=server,
            database=database,
            auth_type=auth_type,
            username=username,
            password=password
        )
    else:
        return ConnectionConfig(
            server=server,
            database=database,
            auth_type=auth_type
        )


@pytest.fixture(scope="module")
def connection_manager():
    """Fixture providing connection manager for all tests.
    
    Yields:
        DatabaseConnectionManager instance
    
    Cleanup:
        Closes all connections after tests complete
    """
    config = get_test_config()
    manager = DatabaseConnectionManager(config, pool_size=3, enable_pooling=True)
    
    yield manager
    
    # Cleanup
    manager.close()


class TestDatabaseConnectionIntegration:
    """Integration tests with real SQL Server database."""
    
    def test_connection_success(self, connection_manager):
        """Test successful connection to SQL Server."""
        conn = connection_manager.get_connection()
        
        assert conn is not None
        assert isinstance(conn, pyodbc.Connection)
        
        connection_manager.return_connection(conn)
    
    def test_execute_simple_query(self, connection_manager):
        """Test executing simple SELECT query."""
        results = connection_manager.execute_query("SELECT 1 AS test_column")
        
        assert results is not None
        assert len(results) == 1
        assert results[0][0] == 1
    
    def test_execute_query_with_params(self, connection_manager):
        """Test executing parameterized query."""
        results = connection_manager.execute_query(
            "SELECT ? AS param_value, ? AS param_value2",
            params=(42, "test")
        )
        
        assert len(results) == 1
        assert results[0][0] == 42
        assert results[0][1] == "test"
    
    def test_execute_multiple_queries(self, connection_manager):
        """Test executing multiple queries sequentially."""
        results1 = connection_manager.execute_query("SELECT 1 AS first")
        results2 = connection_manager.execute_query("SELECT 2 AS second")
        results3 = connection_manager.execute_query("SELECT 3 AS third")
        
        assert results1[0][0] == 1
        assert results2[0][0] == 2
        assert results3[0][0] == 3
    
    def test_context_manager(self, connection_manager):
        """Test context manager usage with real connection."""
        with connection_manager.get_connection_context() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT @@VERSION")
            version = cursor.fetchone()
            
            assert version is not None
            # Should contain "Microsoft SQL Server" in version string
            assert "Microsoft" in version[0] or "SQL Server" in version[0]
    
    def test_health_check(self, connection_manager):
        """Test health check passes with real database."""
        is_healthy = connection_manager.health_check()
        
        assert is_healthy is True
    
    def test_connection_pooling(self, connection_manager):
        """Test connection pooling reuses connections."""
        # Get 3 connections
        conn1 = connection_manager.get_connection()
        conn2 = connection_manager.get_connection()
        conn3 = connection_manager.get_connection()
        
        # Return them to pool
        connection_manager.return_connection(conn1)
        connection_manager.return_connection(conn2)
        connection_manager.return_connection(conn3)
        
        # Get connection again - should reuse from pool
        conn4 = connection_manager.get_connection()
        
        # One of the original connections should be reused
        assert conn4 in [conn1, conn2, conn3]
        
        connection_manager.return_connection(conn4)
    
    def test_multiple_queries_same_connection(self, connection_manager):
        """Test executing multiple queries on same connection."""
        with connection_manager.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # First query
            cursor.execute("SELECT 1 AS first")
            result1 = cursor.fetchone()
            
            # Second query
            cursor.execute("SELECT 2 AS second")
            result2 = cursor.fetchone()
            
            # Third query
            cursor.execute("SELECT 3 AS third")
            result3 = cursor.fetchone()
            
            assert result1[0] == 1
            assert result2[0] == 2
            assert result3[0] == 3
    
    def test_query_system_tables(self, connection_manager):
        """Test querying SQL Server system tables."""
        # Query database name
        results = connection_manager.execute_query("SELECT DB_NAME() AS current_db")
        
        assert results is not None
        assert len(results) == 1
        # Should return the database name from config
        assert isinstance(results[0][0], str)
    
    def test_query_with_where_clause(self, connection_manager):
        """Test query with WHERE clause and parameters."""
        # Query system databases
        results = connection_manager.execute_query(
            "SELECT name FROM sys.databases WHERE database_id > ?",
            params=(0,)
        )
        
        assert results is not None
        assert len(results) > 0  # Should find at least one database
    
    def test_temp_table_operations(self, connection_manager):
        """Test creating and using temporary table."""
        with connection_manager.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Create temp table
            cursor.execute("""
                IF OBJECT_ID('tempdb..#TestTable') IS NOT NULL
                    DROP TABLE #TestTable
                
                CREATE TABLE #TestTable (
                    id INT PRIMARY KEY,
                    name NVARCHAR(50)
                )
            """)
            
            # Insert data
            cursor.execute("INSERT INTO #TestTable (id, name) VALUES (?, ?)", (1, "Test"))
            conn.commit()
            
            # Query data
            cursor.execute("SELECT COUNT(*) FROM #TestTable")
            count = cursor.fetchone()[0]
            
            assert count == 1
    
    def test_batch_insert(self, connection_manager):
        """Test batch insert operation."""
        with connection_manager.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Create temp table
            cursor.execute("""
                IF OBJECT_ID('tempdb..#BatchTest') IS NOT NULL
                    DROP TABLE #BatchTest
                
                CREATE TABLE #BatchTest (id INT, value NVARCHAR(50))
            """)
            conn.commit()
        
        # Batch insert
        data = [
            (1, "Alice"),
            (2, "Bob"),
            (3, "Charlie"),
            (4, "David"),
            (5, "Eve"),
        ]
        
        affected = connection_manager.execute_batch(
            "INSERT INTO #BatchTest (id, value) VALUES (?, ?)",
            data
        )
        
        # Verify count
        results = connection_manager.execute_query("SELECT COUNT(*) FROM #BatchTest")
        
        assert results[0][0] == 5
    
    @pytest.mark.parametrize("batch_size", [1, 10, 50, 100])
    def test_batch_operations_varying_sizes(self, connection_manager, batch_size):
        """Test batch operations with varying batch sizes."""
        with connection_manager.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Create temp table
            cursor.execute("""
                IF OBJECT_ID('tempdb..#VaryingBatch') IS NOT NULL
                    DROP TABLE #VaryingBatch
                
                CREATE TABLE #VaryingBatch (value INT)
            """)
            conn.commit()
        
        # Generate data
        data = [(i,) for i in range(batch_size)]
        
        # Insert batch
        affected = connection_manager.execute_batch(
            "INSERT INTO #VaryingBatch (value) VALUES (?)",
            data
        )
        
        # Verify
        results = connection_manager.execute_query("SELECT COUNT(*) FROM #VaryingBatch")
        assert results[0][0] == batch_size
    
    def test_connection_timeout_handling(self, connection_manager):
        """Test connection handles timeout configuration."""
        # This test just verifies the connection works with timeout set
        # Actual timeout would require a long-running query
        results = connection_manager.execute_query("SELECT 1")
        assert results is not None
    
    def test_error_handling_invalid_query(self, connection_manager):
        """Test error handling for invalid SQL query."""
        with pytest.raises(pyodbc.Error):
            connection_manager.execute_query("SELECT * FROM NonExistentTable")
    
    def test_error_handling_invalid_syntax(self, connection_manager):
        """Test error handling for SQL syntax errors."""
        with pytest.raises(pyodbc.Error):
            connection_manager.execute_query("INVALID SQL SYNTAX")
    
    def test_concurrent_connections(self, connection_manager):
        """Test multiple concurrent connections from pool."""
        # Get multiple connections at once
        connections = []
        for i in range(3):
            conn = connection_manager.get_connection()
            connections.append(conn)
        
        # All should be valid
        for conn in connections:
            assert conn is not None
        
        # Return all
        for conn in connections:
            connection_manager.return_connection(conn)


class TestConnectionManagerWithoutPooling:
    """Test connection manager with pooling disabled."""
    
    @pytest.fixture
    def manager_no_pool(self):
        """Fixture for connection manager without pooling."""
        config = get_test_config()
        manager = DatabaseConnectionManager(config, enable_pooling=False)
        
        yield manager
        
        manager.close()
    
    def test_execute_query_no_pooling(self, manager_no_pool):
        """Test query execution without connection pooling."""
        results = manager_no_pool.execute_query("SELECT 1")
        
        assert results is not None
        assert results[0][0] == 1
    
    def test_multiple_queries_no_pooling(self, manager_no_pool):
        """Test multiple queries without connection pooling."""
        results1 = manager_no_pool.execute_query("SELECT 1")
        results2 = manager_no_pool.execute_query("SELECT 2")
        
        assert results1[0][0] == 1
        assert results2[0][0] == 2
