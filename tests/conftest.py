"""
Shared pytest fixtures for unit and integration tests.

This module provides reusable fixtures for:
- Mock database connections and cursors
- Configuration objects (SanitizationConfig, DatabaseConfig, MappingConfig)
- Test data generators (FK metadata, sample tables, PII patterns)
- Temporary directories and logging mocks
- Faker instances with controlled seeds

Fixture Scopes:
- function: Default scope, recreated for each test
- module: Shared across all tests in a module
- session: Shared across entire test session

Author: Database Sanitization Team
Date: 2026-03-27
"""

import os
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Any
from unittest.mock import Mock, MagicMock
import pytest
from faker import Faker

from src.config import SanitizationConfig, DatabaseConfig, PIIColumnConfig, MappingConfig
from src.database.connection_config import ConnectionConfig, IsolationLevel
from src.masking.base_masker import MaskingStrategy


# ============================================================================
# DATABASE MOCKS
# ============================================================================

@pytest.fixture
def mock_cursor():
    """
    Mock database cursor with common methods.
    
    Usage:
        def test_something(mock_cursor):
            mock_cursor.execute.return_value = None
            mock_cursor.fetchone.return_value = ('result',)
    """
    cursor = MagicMock()
    cursor.execute = Mock(return_value=None)
    cursor.fetchone = Mock(return_value=None)
    cursor.fetchall = Mock(return_value=[])
    cursor.fetchmany = Mock(return_value=[])
    cursor.rowcount = 0
    cursor.description = None
    cursor.close = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    return cursor


@pytest.fixture
def mock_connection(mock_cursor):
    """
    Mock database connection with cursor support.
    
    Usage:
        def test_something(mock_connection):
            mock_connection.cursor.return_value = mock_cursor
            mock_connection.commit.assert_called_once()
    """
    connection = MagicMock()
    connection.cursor = Mock(return_value=mock_cursor)
    connection.commit = Mock()
    connection.rollback = Mock()
    connection.close = Mock()
    connection.autocommit = False
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    return connection


@pytest.fixture
def mock_connection_manager(mock_connection):
    """
    Mock DatabaseConnectionManager with get_connection() context manager.
    
    Usage:
        def test_something(mock_connection_manager):
            with mock_connection_manager.get_connection() as conn:
                conn.cursor().execute("SELECT 1")
    """
    from src.database.connection_manager import DatabaseConnectionManager
    
    manager = Mock(spec=DatabaseConnectionManager)
    manager.get_connection = Mock()
    manager.get_connection.return_value.__enter__ = Mock(return_value=mock_connection)
    manager.get_connection.return_value.__exit__ = Mock(return_value=False)
    manager.connection_config = ConnectionConfig(
        server="test_server",
        database="test_db",
        username="test_user",
        password="test_pass",
        driver="ODBC Driver 17 for SQL Server",
        port=1433,
        trust_certificate=True,
        isolation_level=IsolationLevel.READ_COMMITTED
    )
    return manager


# ============================================================================
# CONFIGURATION MOCKS
# ============================================================================

@pytest.fixture
def mock_database_config():
    """Standard DatabaseConfig for testing."""
    return DatabaseConfig(
        server="test_server",
        database="test_db",
        username="test_user",
        password="test_pass",
        driver="ODBC Driver 17 for SQL Server",
        port=1433,
        trust_certificate=True
    )


@pytest.fixture
def mock_sanitization_config(mock_database_config):
    """Standard SanitizationConfig with sample PII columns."""
    return SanitizationConfig(
        database=mock_database_config,
        pii_columns=[
            PIIColumnConfig(
                schema="dbo",
                table="Users",
                column="email",
                pii_type="email",
                data_type="VARCHAR(255)",
                max_length=255,
                is_nullable=False
            ),
            PIIColumnConfig(
                schema="dbo",
                table="Users",
                column="first_name",
                pii_type="name",
                data_type="VARCHAR(100)",
                max_length=100,
                is_nullable=False
            ),
            PIIColumnConfig(
                schema="dbo",
                table="Users",
                column="phone",
                pii_type="phone",
                data_type="VARCHAR(20)",
                max_length=20,
                is_nullable=True
            ),
            PIIColumnConfig(
                schema="dbo",
                table="Employees",
                column="ssn",
                pii_type="ssn",
                data_type="CHAR(11)",
                max_length=11,
                is_nullable=False
            )
        ],
        batch_size=1000,
        seed=42,
        null_strategy=MaskingStrategy.PRESERVE,
        enable_mapping=True
    )


@pytest.fixture
def mock_mapping_config(tmp_path):
    """Standard MappingConfig with temporary mapping file."""
    mapping_file = tmp_path / "test_mapping.db"
    return MappingConfig(
        mapping_file=str(mapping_file),
        encryption_key="test-encryption-key-32-bytes!!",
        enable_compression=True,
        cache_size=1000
    )


# ============================================================================
# LOGGING MOCKS
# ============================================================================

@pytest.fixture
def mock_logger():
    """Mock logger with standard logging methods."""
    logger = MagicMock()
    logger.debug = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    logger.critical = Mock()
    logger.exception = Mock()
    return logger


# ============================================================================
# FAKER & TEST DATA
# ============================================================================

@pytest.fixture(scope="session")
def faker_instance():
    """
    Session-scoped Faker instance with fixed seed for deterministic tests.
    
    Usage:
        def test_something(faker_instance):
            name = faker_instance.name()  # Always returns same name for seed 42
    """
    return Faker()
    Faker.seed(42)
    return Faker()


@pytest.fixture
def sample_table_data():
    """
    Sample table data with PII patterns for testing.
    
    Returns:
        List of dictionaries with PII data (emails, names, phones, SSNs).
    """
    return [
        {
            "id": 1,
            "email": "john.doe@example.com",
            "first_name": "John",
            "last_name": "Doe",
            "phone": "555-123-4567",
            "ssn": "123-45-6789"
        },
        {
            "id": 2,
            "email": "jane.smith@test.org",
            "first_name": "Jane",
            "last_name": "Smith",
            "phone": "(555) 987-6543",
            "ssn": "987-65-4321"
        },
        {
            "id": 3,
            "email": "bob.jones@company.net",
            "first_name": "Robert",
            "last_name": "Jones",
            "phone": "+1-555-111-2222",
            "ssn": "456-78-9012"
        },
        {
            "id": 4,
            "email": None,  # NULL email
            "first_name": "Alice",
            "last_name": "Williams",
            "phone": None,  # NULL phone
            "ssn": "234-56-7890"
        }
    ]


@pytest.fixture
def sample_fk_metadata():
    """
    Sample foreign key metadata for testing FK validation and dependency resolution.
    
    Returns:
        Dict with keys: simple_fk, composite_fk, circular_fk, self_referencing_fk
    """
    return {
        # Simple FK: Orders -> Customers
        "simple_fk": [
            {
                "fk_table_schema": "dbo",
                "fk_table": "Orders",
                "fk_columns": ["customer_id"],
                "pk_table_schema": "dbo",
                "pk_table": "Customers",
                "pk_columns": ["id"],
                "constraint_name": "FK_Orders_Customers"
            }
        ],
        
        # Composite FK: OrderItems -> Orders (order_id, product_id)
        "composite_fk": [
            {
                "fk_table_schema": "dbo",
                "fk_table": "OrderItems",
                "fk_columns": ["order_id", "product_id"],
                "pk_table_schema": "dbo",
                "pk_table": "Orders",
                "pk_columns": ["id", "product_id"],
                "constraint_name": "FK_OrderItems_Orders"
            }
        ],
        
        # Circular FK: A -> B -> C -> A
        "circular_fk": [
            {
                "fk_table_schema": "dbo",
                "fk_table": "TableA",
                "fk_columns": ["b_id"],
                "pk_table_schema": "dbo",
                "pk_table": "TableB",
                "pk_columns": ["id"],
                "constraint_name": "FK_A_B"
            },
            {
                "fk_table_schema": "dbo",
                "fk_table": "TableB",
                "fk_columns": ["c_id"],
                "pk_table_schema": "dbo",
                "pk_table": "TableC",
                "pk_columns": ["id"],
                "constraint_name": "FK_B_C"
            },
            {
                "fk_table_schema": "dbo",
                "fk_table": "TableC",
                "fk_columns": ["a_id"],
                "pk_table_schema": "dbo",
                "pk_table": "TableA",
                "pk_columns": ["id"],
                "constraint_name": "FK_C_A"
            }
        ],
        
        # Self-referencing FK: Employees.manager_id -> Employees.id
        "self_referencing_fk": [
            {
                "fk_table_schema": "dbo",
                "fk_table": "Employees",
                "fk_columns": ["manager_id"],
                "pk_table_schema": "dbo",
                "pk_table": "Employees",
                "pk_columns": ["id"],
                "constraint_name": "FK_Employees_Manager"
            }
        ]
    }


# ============================================================================
# TEMPORARY DIRECTORIES
# ============================================================================

@pytest.fixture
def temp_test_dir():
    """
    Create a temporary directory for test file operations.
    Automatically cleaned up after test completion.
    
    Usage:
        def test_something(temp_test_dir):
            test_file = temp_test_dir / "test.txt"
            test_file.write_text("content")
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="db_sanitization_test_"))
    yield temp_dir
    # Cleanup after test
    if temp_dir.exists():
        shutil.rmtree(temp_dir)


@pytest.fixture
def temp_mapping_db(temp_test_dir):
    """
    Create a temporary mapping database file path.
    
    Usage:
        def test_something(temp_mapping_db):
            manager = MappingManager(str(temp_mapping_db))
    """
    return temp_test_dir / "test_mapping.db"


# ============================================================================
# EDGE CASE GENERATORS
# ============================================================================

@pytest.fixture
def unicode_test_data():
    """
    Unicode test data covering multiple character sets.
    
    Returns:
        Dict with keys: chinese, arabic, emoji, mixed, cyrillic
    """
    return {
        "chinese": "李明 (Lǐ Míng)",
        "arabic": "محمد أحمد (Muhammad Ahmad)",
        "emoji": "John 😀 Doe 🎉",
        "mixed": "José María O'Brien-Smith Ñoño",
        "cyrillic": "Александр Иванов (Aleksandr Ivanov)",
        "greek": "Αλέξανδρος Παπαδόπουλος",
        "hebrew": "דוד כהן (David Cohen)",
        "korean": "김철수 (Kim Chul-soo)",
        "thai": "สมชาย ใจดี (Somchai Jaidee)",
        "vietnamese": "Nguyễn Văn An"
    }


@pytest.fixture
def long_string_test_data():
    """
    Long strings for testing length constraints.
    
    Returns:
        Dict with keys: varchar_255, varchar_max, text_8kb, text_64kb
    """
    return {
        "varchar_255": "A" * 255,
        "varchar_500": "B" * 500,
        "varchar_1000": "C" * 1000,
        "varchar_4000": "D" * 4000,
        "varchar_max": "E" * 10000,
        "text_8kb": "F" * 8192,
        "text_64kb": "G" * 65536
    }


@pytest.fixture
def edge_date_test_data():
    """
    Edge case dates for testing date handling.
    
    Returns:
        Dict with keys: min_date, max_date, y2k, leap_year, etc.
    """
    return {
        "min_date": "1753-01-01",  # SQL Server minimum date
        "max_date": "9999-12-31",  # SQL Server maximum date
        "y2k": "2000-01-01",
        "leap_year": "2024-02-29",
        "epoch": "1970-01-01",
        "null_date": None
    }


# ============================================================================
# INTEGRATION TEST FIXTURES
# ============================================================================

@pytest.fixture(scope="session")
def integration_db_config():
    """
    Session-scoped database configuration for integration tests.
    
    Reads from environment variables with fallback to defaults for
    SQL Server test database connection.
    
    Environment Variables:
        SQLSERVER_HOST: Database server hostname (default: localhost)
        SQLSERVER_DB: Database name (default: SanitizationTest)
        SQLSERVER_AUTH: Authentication type (windows|sql, default: windows)
        SQLSERVER_USER: SQL username (required for SQL auth)
        SQLSERVER_PASS: SQL password (required for SQL auth)
    
    Usage:
        def test_something(integration_db_config):
            manager = ConnectionManager(integration_db_config)
    """
    return DatabaseConfig(
        server=os.getenv('SQLSERVER_HOST', 'localhost'),
        database=os.getenv('SQLSERVER_DB', 'SanitizationTest'),
        auth_type=os.getenv('SQLSERVER_AUTH', 'windows'),
        username=os.getenv('SQLSERVER_USER'),
        password=os.getenv('SQLSERVER_PASS'),
        timeout=60,
        batch_size=1000
    )


@pytest.fixture(scope="session")
def integrated_test_db(integration_db_config):
    """
    Session-scoped test database setup.
    
    Creates test database once at the beginning of the test session
    and tears it down at the end. All tests within the session share
    the same database instance.
    
    Use this fixture when:
        - Tests are read-only
        - Tests can tolerate shared state
        - Fast execution is critical
    
    Usage:
        @pytest.mark.usefixtures("integrated_test_db")
        def test_something(integration_db_config):
            # Test database already set up
    """
    from src.database.connection_manager import ConnectionManager
    from tests.integration.test_db_setup import (
        setup_test_database,
        teardown_test_database,
        verify_test_schema
    )
    
    manager = ConnectionManager(integration_db_config)
    
    # Setup database once for entire session
    success = setup_test_database(manager, force_recreate=True)
    assert success, "Failed to setup integration test database"
    
    is_valid = verify_test_schema(manager)
    assert is_valid, "Integration test database schema verification failed"
    
    yield manager
    
    # Teardown at end of session
    teardown_test_database(manager, raise_on_error=False)


@pytest.fixture
def fresh_test_db(integration_db_config):
    """
    Function-scoped test database setup (fresh for each test).
    
    Creates a new test database for each test function to ensure
    complete isolation. This is slower but guarantees no test
    interference.
    
    Use this fixture when:
        - Tests modify database state
        - Complete isolation is required
        - Tests cannot tolerate shared state
    
    Usage:
        def test_something(fresh_test_db):
            # Guaranteed fresh test database
    """
    from src.database.connection_manager import ConnectionManager
    from tests.integration.test_db_setup import (
        setup_test_database,
        teardown_test_database,
        verify_test_schema
    )
    
    manager = ConnectionManager(integration_db_config)
    
    # Setup fresh database
    success = setup_test_database(manager, force_recreate=True)
    assert success, "Failed to setup fresh test database"
    
    is_valid = verify_test_schema(manager)
    assert is_valid, "Fresh test database schema verification failed"
    
    yield manager
    
    # Teardown after each test
    teardown_test_database(manager, raise_on_error=False)


@pytest.fixture
def performance_config():
    """
    Performance benchmark configuration thresholds.
    
    Defines expected minimum performance thresholds for various
    operations. CI/CD environments have 2x variance tolerance.
    
    Returns:
        Dict with keys: extraction_rows_per_sec, update_rows_per_sec,
                       mapping_entries_per_sec, workflow_max_seconds
    
    Usage:
        def test_performance(performance_config):
            assert actual_throughput >= performance_config['extraction_rows_per_sec']
    """
    return {
        "extraction_rows_per_sec": 3000,
        "update_rows_per_sec": 1500,
        "mapping_entries_per_sec": 2000,
        "workflow_max_seconds": 120,
        "variance_multiplier": 2.0,  # Allow 2x variance in CI
        "min_batch_size": 100,
        "max_memory_per_batch_mb": 1.0
    }


@pytest.fixture
def large_dataset_fixture(integration_db_config):
    """
    Create a large dataset (1000+ rows) for performance testing.
    
    Populates sales.Customers table with 1000+ sample rows to enable
    realistic performance benchmarks.
    
    Usage:
        def test_large_dataset(large_dataset_fixture):
            # sales.Customers has 1000+ rows now
    """
    from src.database.connection_manager import ConnectionManager
    from faker import Faker
    
    manager = ConnectionManager(integration_db_config)
    fake = Faker()
    
    # Generate 1000 additional customers
    customers = []
    for i in range(1000):
        customers.append((
            f'large_{i}_{fake.email()}',
            fake.phone_number()[:20] if i % 3 != 0 else None,  # 1/3 NULL
            fake.first_name(),
            fake.last_name(),
            fake.city()
        ))
    
    # Bulk insert
    with manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT INTO sales.Customers (Email, Phone, FirstName, LastName, City)
            VALUES (?, ?, ?, ?, ?)
            """,
            customers
        )
        conn.commit()
    
    yield manager
    
    # Cleanup large dataset
    with manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sales.Customers WHERE Email LIKE 'large_%'")
        conn.commit()


@pytest.fixture
def integration_mapping_config():
    """
    Mapping configuration for integration tests.
    
    Creates a test-specific mapping table in sanitization schema.
    
    Usage:
        def test_mapping(integration_mapping_config):
            manager = MappingManager(connection_manager, integration_mapping_config)
    """
    return MappingConfig(
        enabled=True,
        schema_name="sanitization",
        table_name="pii_mappings_integration_test",
        encryption_enabled=False,
        batch_size=1000
    )


# ============================================================================
# MOCK HELPER FUNCTIONS
# ============================================================================

def create_mock_cursor_with_results(results: List[tuple]) -> MagicMock:
    """
    Create a mock cursor that returns specific results.
    
    Args:
        results: List of tuples to return from fetchall()
    
    Returns:
        Configured MagicMock cursor
    
    Usage:
        cursor = create_mock_cursor_with_results([('John',), ('Jane',)])
        assert cursor.fetchall() == [('John',), ('Jane',)]
    """
    cursor = MagicMock()
    cursor.execute = Mock(return_value=None)
    cursor.fetchone = Mock(return_value=results[0] if results else None)
    cursor.fetchall = Mock(return_value=results)
    cursor.rowcount = len(results)
    cursor.close = Mock()
    return cursor


def create_mock_connection_with_cursor(cursor: MagicMock) -> MagicMock:
    """
    Create a mock connection that returns a specific cursor.
    
    Args:
        cursor: Mock cursor to return from connection.cursor()
    
    Returns:
        Configured MagicMock connection
    
    Usage:
        cursor = create_mock_cursor_with_results([('result',)])
        conn = create_mock_connection_with_cursor(cursor)
        with conn:
            assert conn.cursor() == cursor
    """
    connection = MagicMock()
    connection.cursor = Mock(return_value=cursor)
    connection.commit = Mock()
    connection.rollback = Mock()
    connection.close = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    return connection
