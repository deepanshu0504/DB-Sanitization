"""
Test utilities and helpers for mapping table integration tests.

Provides shared fixtures, helper functions, and utilities for testing
the MappingManager with real SQL Server databases. These helpers ensure
consistent test setup, teardown, and validation across all mapping tests.

Author: Database Sanitization Team
Date: 2026-03-27
"""

import os
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID, uuid4

import pytest
import pyodbc

from src.database.connection_manager import DatabaseConnectionManager
from src.database.connection_config import ConnectionConfig, AuthType
from src.mapping.mapping_models import MappingEntry, MappingBatch
from src.mapping.mapping_config import MappingConfig
from src.mapping.encryption_utils import EncryptionManager


def get_test_db_config() -> ConnectionConfig:
    """
    Get SQL Server configuration from environment variables.
    
    Returns:
        ConnectionConfig instance for testing
    
    Raises:
        pytest.skip: If required environment variables are not set
    
    Environment Variables:
        - SQLSERVER_HOST: SQL Server address (e.g., localhost)
        - SQLSERVER_DB: Database name (e.g., TestDB)
        - SQLSERVER_AUTH: Authentication type (windows|sql)
        - SQLSERVER_USER: Username (required for SQL auth)
        - SQLSERVER_PASS: Password (required for SQL auth)
    """
    server = os.getenv("SQLSERVER_HOST")
    database = os.getenv("SQLSERVER_DB", "TestDB")
    auth_type_str = os.getenv("SQLSERVER_AUTH")
    
    if not server or not auth_type_str:
        pytest.skip(
            "SQL Server integration tests require environment variables: "
            "SQLSERVER_HOST, SQLSERVER_AUTH"
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
            password=password,
            timeout=30
        )
    else:
        return ConnectionConfig(
            server=server,
            database=database,
            auth_type=auth_type,
            timeout=30
        )


def create_test_mapping_table(
    connection_manager: DatabaseConnectionManager,
    schema_name: str = "test_sanitization",
    table_name: str = "test_pii_mappings"
) -> None:
    """
    Create mapping table schema and table for testing.
    
    Args:
        connection_manager: Database connection manager
        schema_name: Schema name for mapping table
        table_name: Table name for mappings
    
    Note:
        This function is idempotent - safe to call multiple times.
    """
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        
        # Create schema if not exists
        cursor.execute(f"""
            IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = '{schema_name}')
            BEGIN
                EXEC('CREATE SCHEMA [{schema_name}]')
            END
        """)
        
        # Create table
        cursor.execute(f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.tables t
                JOIN sys.schemas s ON t.schema_id = s.schema_id
                WHERE s.name = '{schema_name}' AND t.name = '{table_name}'
            )
            BEGIN
                CREATE TABLE [{schema_name}].[{table_name}] (
                    mapping_id BIGINT IDENTITY(1,1) PRIMARY KEY,
                    operation_id UNIQUEIDENTIFIER NOT NULL,
                    schema_name NVARCHAR(128) NOT NULL,
                    table_name NVARCHAR(128) NOT NULL,
                    column_name NVARCHAR(128) NOT NULL,
                    original_value_hash VARBINARY(32) NOT NULL,
                    original_value_encrypted VARBINARY(MAX),
                    masked_value NVARCHAR(MAX),
                    data_type NVARCHAR(128) NOT NULL,
                    is_null BIT NOT NULL DEFAULT 0,
                    created_at DATETIME2 DEFAULT GETUTCDATE()
                )
            END
        """)
        
        # Create indexes
        cursor.execute(f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.indexes
                WHERE object_id = OBJECT_ID('[{schema_name}].[{table_name}]')
                AND name = 'idx_lookup'
            )
            BEGIN
                CREATE NONCLUSTERED INDEX idx_lookup
                ON [{schema_name}].[{table_name}] (
                    schema_name,
                    table_name,
                    column_name,
                    original_value_hash
                )
            END
        """)
        
        cursor.execute(f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.indexes
                WHERE object_id = OBJECT_ID('[{schema_name}].[{table_name}]')
                AND name = 'idx_operation'
            )
            BEGIN
                CREATE NONCLUSTERED INDEX idx_operation
                ON [{schema_name}].[{table_name}] (operation_id)
            END
        """)
        
        conn.commit()
        cursor.close()


def cleanup_mapping_tables(
    connection_manager: DatabaseConnectionManager,
    schema_name: str = "test_sanitization",
    table_name: Optional[str] = None
) -> None:
    """
    Clean up mapping tables and schema after tests.
    
    Args:
        connection_manager: Database connection manager
        schema_name: Schema name to clean up
        table_name: Optional specific table to drop. If None, drops entire schema.
    """
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        
        try:
            if table_name:
                # Drop specific table
                cursor.execute(f"""
                    IF OBJECT_ID('[{schema_name}].[{table_name}]', 'U') IS NOT NULL
                        DROP TABLE [{schema_name}].[{table_name}]
                """)
            else:
                # Drop all tables in schema then schema itself
                cursor.execute(f"""
                    DECLARE @sql NVARCHAR(MAX) = '';
                    SELECT @sql = @sql + 'DROP TABLE [' + s.name + '].[' + t.name + ']; '
                    FROM sys.tables t
                    JOIN sys.schemas s ON t.schema_id = s.schema_id
                    WHERE s.name = '{schema_name}';
                    
                    EXEC sp_executesql @sql;
                """)
                
                cursor.execute(f"""
                    IF EXISTS (SELECT 1 FROM sys.schemas WHERE name = '{schema_name}')
                        DROP SCHEMA [{schema_name}]
                """)
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            # Ignore cleanup errors in tests
            pass
        finally:
            cursor.close()


def generate_mapping_entries(
    operation_id: UUID,
    count: int = 100,
    schema_name: str = "dbo",
    table_name: str = "TestTable",
    column_name: str = "Email",
    data_type: str = "VARCHAR"
) -> List[MappingEntry]:
    """
    Generate test mapping entries for testing.
    
    Args:
        operation_id: Operation UUID
        count: Number of entries to generate
        schema_name: Schema name
        table_name: Table name
        column_name: Column name
        data_type: SQL data type
    
    Returns:
        List of MappingEntry objects
    """
    entries = []
    
    for i in range(count):
        original_value = f"test{i}@example.com"
        masked_value = f"user_{i:08x}@masked.dev"
        
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name=schema_name,
            table_name=table_name,
            column_name=column_name,
            original_value_hash=hashlib.sha256(original_value.encode()).digest(),
            original_value_encrypted=None,
            masked_value=masked_value,
            data_type=data_type,
            is_null=False,
            created_at=datetime.utcnow()
        )
        entries.append(entry)
    
    return entries


def verify_mapping_integrity(
    connection_manager: DatabaseConnectionManager,
    schema_name: str,
    table_name: str,
    operation_id: UUID,
    expected_count: int
) -> Tuple[bool, List[str]]:
    """
    Verify mapping table integrity after operations.
    
    Checks:
        - Row count matches expected
        - All required columns are populated
        - Indexes exist
        - No duplicate entries
    
    Args:
        connection_manager: Database connection manager
        schema_name: Mapping table schema
        table_name: Mapping table name
        operation_id: Operation to verify
        expected_count: Expected number of entries
    
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        
        # Check row count
        cursor.execute(f"""
            SELECT COUNT(*) FROM [{schema_name}].[{table_name}]
            WHERE operation_id = ?
        """, (str(operation_id),))
        actual_count = cursor.fetchone()[0]
        
        if actual_count != expected_count:
            errors.append(
                f"Row count mismatch: expected {expected_count}, got {actual_count}"
            )
        
        # Check for NULL values in required columns
        cursor.execute(f"""
            SELECT COUNT(*) FROM [{schema_name}].[{table_name}]
            WHERE operation_id = ?
            AND (
                operation_id IS NULL
                OR schema_name IS NULL
                OR table_name IS NULL
                OR column_name IS NULL
                OR original_value_hash IS NULL
                OR data_type IS NULL
                OR is_null IS NULL
            )
        """, (str(operation_id),))
        null_count = cursor.fetchone()[0]
        
        if null_count > 0:
            errors.append(f"Found {null_count} rows with NULL in required columns")
        
        # Check for duplicates
        cursor.execute(f"""
            SELECT COUNT(*) as dup_count
            FROM (
                SELECT original_value_hash, COUNT(*) as cnt
                FROM [{schema_name}].[{table_name}]
                WHERE operation_id = ?
                GROUP BY original_value_hash
                HAVING COUNT(*) > 1
            ) dupes
        """, (str(operation_id),))
        dup_count = cursor.fetchone()[0]
        
        if dup_count > 0:
            errors.append(f"Found {dup_count} duplicate hash entries")
        
        # Check indexes exist
        cursor.execute(f"""
            SELECT COUNT(*) FROM sys.indexes
            WHERE object_id = OBJECT_ID('[{schema_name}].[{table_name}]')
            AND name IN ('idx_lookup', 'idx_operation')
        """)
        index_count = cursor.fetchone()[0]
        
        if index_count < 2:
            errors.append(f"Missing indexes: expected 2, found {index_count}")
        
        cursor.close()
    
    return (len(errors) == 0, errors)


def setup_encryption_key() -> str:
    """
    Setup encryption key for testing.
    
    Returns:
        Generated encryption key (base64 encoded)
    
    Side Effects:
        Sets SANITIZATION_MAPPING_ENCRYPTION_KEY environment variable
    """
    key = EncryptionManager.generate_key()
    os.environ['SANITIZATION_MAPPING_ENCRYPTION_KEY'] = key
    return key


def cleanup_encryption_key() -> None:
    """Remove encryption key from environment."""
    if 'SANITIZATION_MAPPING_ENCRYPTION_KEY' in os.environ:
        del os.environ['SANITIZATION_MAPPING_ENCRYPTION_KEY']


# Pytest fixtures for common test scenarios

@pytest.fixture(scope="function")
def test_operation_id() -> UUID:
    """Generate unique operation ID for each test."""
    return uuid4()


@pytest.fixture(scope="function")
def mapping_config() -> MappingConfig:
    """Create default mapping configuration for tests."""
    return MappingConfig(
        enabled=True,
        schema_name="test_sanitization",
        table_name="test_pii_mappings",
        encryption_enabled=False,
        batch_size=100,
        index_creation=True,
        transactional=True
    )


@pytest.fixture(scope="function")
def mapping_config_with_encryption() -> MappingConfig:
    """Create mapping configuration with encryption enabled."""
    setup_encryption_key()
    config = MappingConfig(
        enabled=True,
        schema_name="test_sanitization",
        table_name="test_pii_mappings",
        encryption_enabled=True,
        batch_size=100,
        index_creation=True,
        transactional=True
    )
    yield config
    cleanup_encryption_key()
