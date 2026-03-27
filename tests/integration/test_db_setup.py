"""
Integration Test Database Setup Helpers

Provides reusable functions and fixtures for setting up and tearing down
the comprehensive integration test database schema.

Usage:
    # Standalone script execution
    python -m tests.integration.test_db_setup
    
    # In pytest fixtures
    from tests.integration.test_db_setup import setup_test_database
    setup_test_database(connection_manager)

Features:
    - Execute SQL scripts from files
    - Idempotent setup (safe to run multiple times)
    - Comprehensive verification
    - Graceful teardown with error handling
    - Session-scoped and function-scoped fixtures

Author: Database Sanitization Team
Created: 2026-03-27
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import pyodbc
import pytest

from src.database.connection_manager import ConnectionManager
from src.config import DatabaseConfig
from src.exceptions import DatabaseConnectionError

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# PATH CONSTANTS
# ============================================================================

# Get project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SETUP_SCRIPT = SCRIPTS_DIR / "setup_test_db.sql"
TEARDOWN_SCRIPT = SCRIPTS_DIR / "teardown_test_db.sql"


# ============================================================================
# CORE FUNCTIONS
# ============================================================================

def execute_sql_script(
    connection_manager: ConnectionManager,
    script_path: Path,
    raise_on_error: bool = True
) -> bool:
    """
    Execute a SQL script file using the connection manager.
    
    Handles GO batch separators and provides detailed error reporting.
    
    Args:
        connection_manager: Configured ConnectionManager instance
        script_path: Path to SQL script file
        raise_on_error: If True, raise exception on errors; if False, log and continue
        
    Returns:
        bool: True if execution succeeded, False otherwise
        
    Raises:
        FileNotFoundError: If script file does not exist
        DatabaseConnectionError: If script execution fails (when raise_on_error=True)
    """
    if not script_path.exists():
        raise FileNotFoundError(f"SQL script not found: {script_path}")
    
    logger.info(f"Executing SQL script: {script_path.name}")
    
    try:
        # Read script content
        with open(script_path, 'r', encoding='utf-8') as f:
            script_content = f.read()
        
        # Split by GO batch separator (case-insensitive)
        batches = []
        current_batch = []
        
        for line in script_content.splitlines():
            line_stripped = line.strip().upper()
            
            # Check if line is GO batch separator (alone on line)
            if line_stripped == 'GO' or line_stripped == 'GO;':
                if current_batch:
                    batches.append('\n'.join(current_batch))
                    current_batch = []
            else:
                current_batch.append(line)
        
        # Add final batch if any
        if current_batch:
            batches.append('\n'.join(current_batch))
        
        logger.info(f"Parsed {len(batches)} SQL batches from script")
        
        # Execute each batch
        batch_num = 0
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            for batch in batches:
                batch_stripped = batch.strip()
                
                # Skip empty batches and comments-only batches
                if not batch_stripped or batch_stripped.startswith('/*'):
                    continue
                
                batch_num += 1
                
                try:
                    cursor.execute(batch)
                    conn.commit()
                    
                    # Log any messages from SQL Server
                    if cursor.messages:
                        for msg in cursor.messages:
                            logger.debug(f"SQL Message: {msg}")
                    
                except pyodbc.Error as e:
                    error_msg = f"Error in batch {batch_num}: {str(e)}"
                    logger.error(error_msg)
                    logger.debug(f"Failed batch content:\n{batch[:500]}")
                    
                    if raise_on_error:
                        raise DatabaseConnectionError(
                            message=error_msg,
                            error_code="SCRIPT_EXECUTION_FAILED"
                        ) from e
                    else:
                        return False
            
            cursor.close()
        
        logger.info(f"Successfully executed {batch_num} batches from {script_path.name}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to execute SQL script {script_path.name}: {e}")
        if raise_on_error:
            raise
        return False


def setup_test_database(
    connection_manager: ConnectionManager,
    force_recreate: bool = False
) -> bool:
    """
    Set up the integration test database schema and sample data.
    
    This function is idempotent - safe to run multiple times.
    If schema already exists and force_recreate=False, skips setup.
    
    Args:
        connection_manager: Configured ConnectionManager instance
        force_recreate: If True, tears down existing schema first
        
    Returns:
        bool: True if setup succeeded
        
    Raises:
        DatabaseConnectionError: If setup fails
    """
    logger.info("="*70)
    logger.info("SETTING UP INTEGRATION TEST DATABASE")
    logger.info("="*70)
    
    try:
        # Check if schema already exists
        schema_exists = verify_test_schema(connection_manager, silent=True)
        
        if schema_exists:
            if force_recreate:
                logger.info("Test schema exists - forcing recreation")
                teardown_test_database(connection_manager, raise_on_error=False)
            else:
                logger.info("Test schema already exists - skipping setup")
                return True
        
        # Execute setup script
        success = execute_sql_script(
            connection_manager,
            SETUP_SCRIPT,
            raise_on_error=True
        )
        
        if not success:
            logger.error("Setup script execution failed")
            return False
        
        # Verify setup
        if not verify_test_schema(connection_manager):
            logger.error("Setup verification failed")
            return False
        
        logger.info("="*70)
        logger.info("TEST DATABASE SETUP COMPLETE")
        logger.info("="*70)
        return True
        
    except Exception as e:
        logger.error(f"Test database setup failed: {e}")
        raise


def teardown_test_database(
    connection_manager: ConnectionManager,
    raise_on_error: bool = True
) -> bool:
    """
    Tear down the integration test database schema.
    
    Removes all test tables, FK constraints, and custom schemas.
    
    Args:
        connection_manager: Configured ConnectionManager instance
        raise_on_error: If True, raise exception on errors
        
    Returns:
        bool: True if teardown succeeded
    """
    logger.info("="*70)
    logger.info("TEARING DOWN INTEGRATION TEST DATABASE")
    logger.info("="*70)
    
    try:
        # Execute teardown script
        success = execute_sql_script(
            connection_manager,
            TEARDOWN_SCRIPT,
            raise_on_error=raise_on_error
        )
        
        if not success:
            logger.error("Teardown script execution failed")
            return False
        
        logger.info("="*70)
        logger.info("TEST DATABASE TEARDOWN COMPLETE")
        logger.info("="*70)
        return True
        
    except Exception as e:
        logger.error(f"Test database teardown failed: {e}")
        if raise_on_error:
            raise
        return False


def verify_test_schema(
    connection_manager: ConnectionManager,
    silent: bool = False
) -> bool:
    """
    Verify the integration test database schema is correctly set up.
    
    Checks for expected schemas, tables, and FK constraints.
    
    Args:
        connection_manager: Configured ConnectionManager instance
        silent: If True, only return boolean without logging details
        
    Returns:
        bool: True if schema is valid
    """
    try:
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check schemas
            cursor.execute("""
                SELECT name FROM sys.schemas 
                WHERE name IN ('sales', 'hr', 'archive')
                ORDER BY name
            """)
            schemas = [row[0] for row in cursor.fetchall()]
            
            expected_schemas = ['archive', 'hr', 'sales']
            if schemas != expected_schemas:
                if not silent:
                    logger.warning(f"Expected schemas {expected_schemas}, found {schemas}")
                return False
            
            # Check tables
            cursor.execute("""
                SELECT TABLE_SCHEMA, TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'BASE TABLE'
                  AND TABLE_SCHEMA IN ('dbo', 'sales', 'hr', 'archive')
                ORDER BY TABLE_SCHEMA, TABLE_NAME
            """)
            tables = [(row[0], row[1]) for row in cursor.fetchall()]
            
            expected_table_count = 9  # Minimum expected
            if len(tables) < expected_table_count:
                if not silent:
                    logger.warning(f"Expected at least {expected_table_count} tables, found {len(tables)}")
                return False
            
            # Check FK constraints
            cursor.execute("""
                SELECT COUNT(*) AS fk_count
                FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
                WHERE CONSTRAINT_SCHEMA IN ('dbo', 'sales', 'hr', 'archive')
            """)
            fk_count = cursor.fetchone()[0]
            
            expected_fk_count = 8  # Minimum expected
            if fk_count < expected_fk_count:
                if not silent:
                    logger.warning(f"Expected at least {expected_fk_count} FK constraints, found {fk_count}")
                return False
            
            # Count total rows
            cursor.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM sales.Customers) +
                    (SELECT COUNT(*) FROM sales.Orders) +
                    (SELECT COUNT(*) FROM sales.OrderDetails) +
                    (SELECT COUNT(*) FROM sales.OrderLineItems) +
                    (SELECT COUNT(*) FROM hr.Employees) +
                    (SELECT COUNT(*) FROM dbo.Suppliers) +
                    (SELECT COUNT(*) FROM dbo.Categories) +
                    (SELECT COUNT(*) FROM dbo.Products) +
                    (SELECT COUNT(*) FROM archive.ArchivedCustomers) AS total_rows
            """)
            total_rows = cursor.fetchone()[0]
            
            if not silent:
                logger.info(f"✓ Verified {len(schemas)} schemas")
                logger.info(f"✓ Verified {len(tables)} tables")
                logger.info(f"✓ Verified {fk_count} FK constraints")
                logger.info(f"✓ Verified {total_rows} total rows")
            
            cursor.close()
            return True
            
    except Exception as e:
        if not silent:
            logger.error(f"Schema verification failed: {e}")
        return False


def get_test_db_stats(connection_manager: ConnectionManager) -> Dict[str, Any]:
    """
    Get detailed statistics about the test database.
    
    Returns information about schemas, tables, rows, and FK relationships.
    
    Args:
        connection_manager: Configured ConnectionManager instance
        
    Returns:
        dict: Database statistics
    """
    stats = {
        'schemas': [],
        'tables': {},
        'fk_constraints': [],
        'total_rows': 0
    }
    
    try:
        with connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get schemas
            cursor.execute("""
                SELECT name FROM sys.schemas 
                WHERE name IN ('dbo', 'sales', 'hr', 'archive')
                ORDER BY name
            """)
            stats['schemas'] = [row[0] for row in cursor.fetchall()]
            
            # Get table row counts
            for schema in stats['schemas']:
                cursor.execute(f"""
                    SELECT TABLE_NAME
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = ?
                      AND TABLE_TYPE = 'BASE TABLE'
                    ORDER BY TABLE_NAME
                """, (schema,))
                
                tables = [row[0] for row in cursor.fetchall()]
                
                for table in tables:
                    full_name = f"{schema}.{table}"
                    cursor.execute(f"SELECT COUNT(*) FROM [{schema}].[{table}]")
                    row_count = cursor.fetchone()[0]
                    
                    stats['tables'][full_name] = row_count
                    stats['total_rows'] += row_count
            
            # Get FK constraints
            cursor.execute("""
                SELECT 
                    RC.CONSTRAINT_SCHEMA,
                    RC.CONSTRAINT_NAME,
                    FK.TABLE_SCHEMA + '.' + FK.TABLE_NAME AS FK_Table,
                    PK.TABLE_SCHEMA + '.' + PK.TABLE_NAME AS PK_Table
                FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS RC
                INNER JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS FK
                    ON RC.CONSTRAINT_NAME = FK.CONSTRAINT_NAME
                INNER JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS PK
                    ON RC.UNIQUE_CONSTRAINT_NAME = PK.CONSTRAINT_NAME
                WHERE RC.CONSTRAINT_SCHEMA IN ('dbo', 'sales', 'hr', 'archive')
                ORDER BY FK.TABLE_SCHEMA, FK.TABLE_NAME
            """)
            
            stats['fk_constraints'] = [
                {
                    'name': row[1],
                    'child_table': row[2],
                    'parent_table': row[3]
                }
                for row in cursor.fetchall()
            ]
            
            cursor.close()
            
    except Exception as e:
        logger.error(f"Failed to get database stats: {e}")
    
    return stats


# ============================================================================
# PYTEST FIXTURES
# ============================================================================

@pytest.fixture(scope="session")
def integrated_test_db(request):
    """
    Session-scoped fixture for integration tests that need a shared test database.
    
    Sets up the test database once at the start of the test session and
    tears it down at the end. Suitable for read-only tests.
    
    Yields:
        ConnectionManager: Configured connection manager for test database
    """
    # Get database configuration from environment
    db_config = DatabaseConfig(
        server=os.getenv('SQLSERVER_HOST', 'localhost'),
        database=os.getenv('SQLSERVER_DB', 'SanitizationTest'),
        auth_type=os.getenv('SQLSERVER_AUTH', 'windows'),
        username=os.getenv('SQLSERVER_USER'),
        password=os.getenv('SQLSERVER_PASS'),
        timeout=30,
        batch_size=10000
    )
    
    conn_mgr = ConnectionManager(db_config)
    
    # Setup database
    try:
        setup_test_database(conn_mgr, force_recreate=False)
        yield conn_mgr
    finally:
        # Teardown on session end
        def teardown():
            try:
                teardown_test_database(conn_mgr, raise_on_error=False)
            except Exception as e:
                logger.warning(f"Session teardown failed: {e}")
        
        request.addfinalizer(teardown)


@pytest.fixture(scope="function")
def fresh_test_db(request):
    """
    Function-scoped fixture for integration tests that need an isolated test database.
    
    Sets up a fresh test database for each test function and tears it down after.
    Suitable for tests that modify data (sanitization, desensitization).
    
    Yields:
        ConnectionManager: Configured connection manager for test database
    """
    # Get database configuration from environment
    db_config = DatabaseConfig(
        server=os.getenv('SQLSERVER_HOST', 'localhost'),
        database=os.getenv('SQLSERVER_DB', 'SanitizationTest'),
        auth_type=os.getenv('SQLSERVER_AUTH', 'windows'),
        username=os.getenv('SQLSERVER_USER'),
        password=os.getenv('SQLSERVER_PASS'),
        timeout=30,
        batch_size=10000
    )
    
    conn_mgr = ConnectionManager(db_config)
    
    # Setup fresh database
    try:
        setup_test_database(conn_mgr, force_recreate=True)
        yield conn_mgr
    finally:
        # Teardown after test
        def teardown():
            try:
                teardown_test_database(conn_mgr, raise_on_error=False)
            except Exception as e:
                logger.warning(f"Function teardown failed: {e}")
        
        request.addfinalizer(teardown)


# ============================================================================
# STANDALONE EXECUTION
# ============================================================================

def main():
    """
    Standalone execution for manual database setup/teardown.
    
    Usage:
        python -m tests.integration.test_db_setup
    """
    import argparse
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    parser = argparse.ArgumentParser(
        description='Integration Test Database Setup/Teardown'
    )
    parser.add_argument(
        'action',
        choices=['setup', 'teardown', 'verify', 'stats'],
        help='Action to perform'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force recreation during setup'
    )
    
    args = parser.parse_args()
    
    # Get database configuration from environment
    db_config = DatabaseConfig(
        server=os.getenv('SQLSERVER_HOST', 'localhost'),
        database=os.getenv('SQLSERVER_DB', 'SanitizationTest'),
        auth_type=os.getenv('SQLSERVER_AUTH', 'windows'),
        username=os.getenv('SQLSERVER_USER'),
        password=os.getenv('SQLSERVER_PASS'),
        timeout=30,
        batch_size=10000
    )
    
    conn_mgr = ConnectionManager(db_config)
    
    try:
        if args.action == 'setup':
            success = setup_test_database(conn_mgr, force_recreate=args.force)
            exit(0 if success else 1)
            
        elif args.action == 'teardown':
            success = teardown_test_database(conn_mgr)
            exit(0 if success else 1)
            
        elif args.action == 'verify':
            is_valid = verify_test_schema(conn_mgr)
            print(f"\nTest schema is {'VALID' if is_valid else 'INVALID'}")
            exit(0 if is_valid else 1)
            
        elif args.action == 'stats':
            stats = get_test_db_stats(conn_mgr)
            print("\nTest Database Statistics:")
            print(f"  Schemas: {', '.join(stats['schemas'])}")
            print(f"  Tables: {len(stats['tables'])}")
            print(f"  Total Rows: {stats['total_rows']}")
            print(f"  FK Constraints: {len(stats['fk_constraints'])}")
            print("\nTable Row Counts:")
            for table, count in sorted(stats['tables'].items()):
                print(f"    {table}: {count}")
            exit(0)
            
    except Exception as e:
        logger.error(f"Operation failed: {e}")
        exit(1)


if __name__ == '__main__':
    main()
