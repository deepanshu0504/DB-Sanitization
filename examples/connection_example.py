"""Example usage of DatabaseConnectionManager.

This script demonstrates various ways to use the connection manager:
1. Windows Authentication
2. SQL Server Authentication
3. Query execution with parameters
4. Batch operations
5. Context managers
6. Health checks

Requirements:
    - SQL Server instance running (localhost or remote)
    - Appropriate authentication credentials
    - pyodbc and ODBC Driver installed

Run:
    python examples/connection_example.py
"""

from src.database import DatabaseConnectionManager, ConnectionConfig, AuthType


def example_1_windows_authentication():
    """Example 1: Connect using Windows Authentication."""
    print("=" * 70)
    print("Example 1: Windows Authentication")
    print("=" * 70)
    
    config = ConnectionConfig(
        server="localhost",
        database="master",
        auth_type=AuthType.WINDOWS
    )
    
    with DatabaseConnectionManager(config) as manager:
        # Health check
        if manager.health_check():
            print("✓ Connection healthy")
        else:
            print("✗ Connection failed")
            return
        
        # Get SQL Server version
        results = manager.execute_query("SELECT @@VERSION AS version")
        version = results[0][0]
        print(f"✓ SQL Server version: {version[:60]}...")
        
        # Get current database
        results = manager.execute_query("SELECT DB_NAME() AS current_db")
        db_name = results[0][0]
        print(f"✓ Connected to database: {db_name}")


def example_2_sql_authentication():
    """Example 2: Connect using SQL Server Authentication.
    
    Note: Update username and password with your credentials.
    """
    print("\n" + "=" * 70)
    print("Example 2: SQL Server Authentication")
    print("=" * 70)
    
    # WARNING: For production, use environment variables or secure config
    config = ConnectionConfig(
        server="localhost",
        database="master",
        auth_type=AuthType.SQL,
        username="sa",
        password="YourPassword123"  # Change this!
    )
    
    try:
        manager = DatabaseConnectionManager(config, pool_size=5)
        
        try:
            # Context manager for connection
            with manager.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT SYSTEM_USER AS current_user")
                user = cursor.fetchone()[0]
                print(f"✓ Connected as user: {user}")
        finally:
            manager.close()
    
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        print("  (Update username/password in script)")


def example_3_parameterized_queries():
    """Example 3: Execute parameterized queries safely."""
    print("\n" + "=" * 70)
    print("Example 3: Parameterized Queries (SQL Injection Safe)")
    print("=" * 70)
    
    config = ConnectionConfig(
        server="localhost",
        database="master",
        auth_type=AuthType.WINDOWS
    )
    
    with DatabaseConnectionManager(config) as manager:
        # Query system databases with parameter
        results = manager.execute_query(
            "SELECT name, database_id FROM sys.databases WHERE database_id > ?",
            params=(4,)
        )
        
        print(f"✓ Found {len(results)} user databases:")
        for row in results:
            print(f"  - {row[0]} (ID: {row[1]})")
        
        # Query with multiple parameters
        results = manager.execute_query(
            "SELECT ? AS param1, ? AS param2, ? AS param3",
            params=("Hello", 42, "World")
        )
        
        print(f"✓ Multi-parameter query: {results[0]}")


def example_4_batch_operations():
    """Example 4: Perform batch insert operations."""
    print("\n" + "=" * 70)
    print("Example 4: Batch Operations")
    print("=" * 70)
    
    config = ConnectionConfig(
        server="localhost",
        database="master",
        auth_type=AuthType.WINDOWS
    )
    
    with DatabaseConnectionManager(config) as manager:
        # Create temporary table
        manager.execute_query(
            """
            IF OBJECT_ID('tempdb..#BatchDemo') IS NOT NULL
                DROP TABLE #BatchDemo
            
            CREATE TABLE #BatchDemo (
                id INT PRIMARY KEY,
                name NVARCHAR(50),
                value INT
            )
            """,
            fetch=False
        )
        print("✓ Created temporary table #BatchDemo")
        
        # Prepare batch data
        data = [
            (1, "Alice", 100),
            (2, "Bob", 200),
            (3, "Charlie", 300),
            (4, "David", 400),
            (5, "Eve", 500),
        ]
        
        # Execute batch insert
        affected = manager.execute_batch(
            "INSERT INTO #BatchDemo (id, name, value) VALUES (?, ?, ?)",
            data
        )
        
        print(f"✓ Inserted {affected} rows in batch operation")
        
        # Verify inserted data
        results = manager.execute_query("SELECT * FROM #BatchDemo ORDER BY id")
        print(f"✓ Retrieved {len(results)} rows:")
        for row in results:
            print(f"  - ID: {row[0]}, Name: {row[1]}, Value: {row[2]}")
        
        # Cleanup happens automatically (temp table dropped on connection close)


def example_5_connection_context():
    """Example 5: Manual connection management with context manager."""
    print("\n" + "=" * 70)
    print("Example 5: Manual Connection Management")
    print("=" * 70)
    
    config = ConnectionConfig(
        server="localhost",
        database="master",
        auth_type=AuthType.WINDOWS
    )
    
    manager = DatabaseConnectionManager(config, pool_size=3)
    
    try:
        # Get connection from pool
        with manager.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Execute multiple queries on same connection
            cursor.execute("SELECT GETDATE() AS current_time")
            current_time = cursor.fetchone()[0]
            print(f"✓ Current server time: {current_time}")
            
            cursor.execute("SELECT @@SERVERNAME AS server_name")
            server_name = cursor.fetchone()[0]
            print(f"✓ Server name: {server_name}")
            
            cursor.execute("SELECT @@SPID AS session_id")
            session_id = cursor.fetchone()[0]
            print(f"✓ Session ID: {session_id}")
            
            cursor.close()
        
        # Connection automatically returned to pool
        print("✓ Connection returned to pool")
        
    finally:
        manager.close()
        print("✓ Manager closed, all connections cleaned up")


def example_6_health_monitoring():
    """Example 6: Health check and monitoring."""
    print("\n" + "=" * 70)
    print("Example 6: Health Check and Monitoring")
    print("=" * 70)
    
    config = ConnectionConfig(
        server="localhost",
        database="master",
        auth_type=AuthType.WINDOWS,
        timeout=10  # 10 second timeout
    )
    
    with DatabaseConnectionManager(config, pool_size=5) as manager:
        # Perform health check
        is_healthy = manager.health_check()
        
        if is_healthy:
            print("✓ Database health check: PASSED")
            
            # Get some monitoring info
            results = manager.execute_query(
                "SELECT COUNT(*) FROM sys.databases"
            )
            db_count = results[0][0]
            print(f"✓ Number of databases: {db_count}")
            
            # Check connection count
            results = manager.execute_query(
                "SELECT COUNT(*) FROM sys.dm_exec_sessions WHERE is_user_process = 1"
            )
            session_count = results[0][0]
            print(f"✓ Active user sessions: {session_count}")
        else:
            print("✗ Database health check: FAILED")


def example_7_error_handling():
    """Example 7: Proper error handling."""
    print("\n" + "=" * 70)
    print("Example 7: Error Handling")
    print("=" * 70)
    
    config = ConnectionConfig(
        server="localhost",
        database="master",
        auth_type=AuthType.WINDOWS
    )
    
    with DatabaseConnectionManager(config) as manager:
        # Example 1: Handle invalid query
        try:
            manager.execute_query("SELECT * FROM NonExistentTable")
        except Exception as e:
            print(f"✓ Caught expected error: {type(e).__name__}")
        
        # Example 2: Handle invalid SQL syntax
        try:
            manager.execute_query("INVALID SQL")
        except Exception as e:
            print(f"✓ Caught expected error: {type(e).__name__}")
        
        # Example 3: Recover and continue
        results = manager.execute_query("SELECT 1 AS recovery_check")
        print(f"✓ Successfully recovered and executed query: {results[0][0]}")


def main():
    """Run all examples."""
    print("\n" + "█" * 70)
    print("DatabaseConnectionManager - Usage Examples")
    print("█" * 70)
    
    try:
        example_1_windows_authentication()
        # example_2_sql_authentication()  # Uncomment and configure credentials
        example_3_parameterized_queries()
        example_4_batch_operations()
        example_5_connection_context()
        example_6_health_monitoring()
        example_7_error_handling()
        
        print("\n" + "█" * 70)
        print("All examples completed successfully!")
        print("█" * 70 + "\n")
    
    except Exception as e:
        print(f"\n✗ Error running examples: {e}")
        print("  Make sure SQL Server is running and accessible.")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
