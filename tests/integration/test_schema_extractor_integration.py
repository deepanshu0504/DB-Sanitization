"""Integration tests for Schema Extractor.

These tests require an actual SQL Server database connection.
They are skipped if SQL Server is not available.

To run these tests, ensure:
1. SQL Server is running and accessible
2. Environment variables are set with valid connection details
3. Test database exists with appropriate permissions

Environment Variables:
- SANITIZATION_DATABASE_SERVER: SQL Server hostname
- SANITIZATION_DATABASE_DATABASE: Test database name
- SANITIZATION_DATABASE_AUTH_TYPE: 'windows' or 'sql'
- SANITIZATION_DATABASE_USERNAME: (for SQL auth)
- SANITIZATION_DATABASE_PASSWORD: (for SQL auth)
"""

import pytest
import os
import pyodbc

from src.database import DatabaseConnectionManager, SchemaExtractor
from src.config import ConfigLoader
from src.exceptions import SchemaExtractionError


# Check if SQL Server is available
def sql_server_available():
    """Check if SQL Server is available for testing."""
    try:
        # Try to load config
        config = ConfigLoader.load()
        conn_mgr = DatabaseConnectionManager(config.database)
        with conn_mgr:
            result = conn_mgr.execute_query("SELECT 1 AS test")
            return result[0][0] == 1
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not sql_server_available(),
    reason="SQL Server not available or connection configuration missing"
)


class TestSchemaExtractorIntegration:
    """Integration tests for SchemaExtractor with real database."""
    
    @pytest.fixture(scope="module")
    def config(self):
        """Load configuration from environment."""
        return ConfigLoader.load()
    
    @pytest.fixture(scope="module")
    def connection_manager(self, config):
        """Create a connection manager for testing."""
        return DatabaseConnectionManager(config.database)
    
    @pytest.fixture(scope="module")
    def extractor(self, connection_manager):
        """Create a SchemaExtractor instance."""
        return SchemaExtractor(connection_manager)
    
    @pytest.fixture(scope="module")
    def database_name(self, config):
        """Get the test database name from config."""
        return config.database.database
    
    def test_extract_schema_basic(self, extractor, database_name):
        """Test basic schema extraction from real database."""
        schema = extractor.extract_schema(database_name)
        
        # Verify structure
        assert "database_name" in schema
        assert schema["database_name"] == database_name
        assert "tables" in schema
        assert "columns" in schema
        assert "primary_keys" in schema
        assert "foreign_keys" in schema
        assert "unique_constraints" in schema
        assert "indexes" in schema
        assert "extraction_timestamp" in schema
        assert "extraction_duration_ms" in schema
        assert "warnings" in schema
        
        # If database has tables, verify they have columns
        if schema["tables"]:
            first_table = schema["tables"][0]
            qualified_name = first_table["qualified_name"]
            assert qualified_name in schema["columns"]
            assert len(schema["columns"][qualified_name]) > 0
    
    def test_extract_tables_returns_user_tables_only(self, extractor, database_name):
        """Test that only user tables are extracted, not system tables."""
        tables = extractor._get_tables(database_name)
        
        # Verify all tables have proper structure
        for table in tables:
            assert "schema" in table
            assert "name" in table
            assert "qualified_name" in table
            
            # Verify qualified name format
            expected_qualified = f"[{table['schema']}].[{table['name']}]"
            assert table["qualified_name"] == expected_qualified
            
            # System tables should not be included
            assert table["name"] not in ["sysdiagrams", "trace_xe_action_map"]
    
    def test_extract_columns_has_correct_types(self, extractor, database_name):
        """Test that column extraction returns correct data types."""
        tables = extractor._get_tables(database_name)
        
        if not tables:
            pytest.skip("No tables in database for testing")
        
        qualified_names = [t["qualified_name"] for t in tables]
        columns = extractor._get_columns(database_name, qualified_names)
        
        # Verify columns have required fields
        for table_name, table_columns in columns.items():
            for col in table_columns:
                assert "name" in col
                assert "data_type" in col
                assert "max_length" in col
                assert "precision" in col
                assert "scale" in col
                assert "is_nullable" in col
                assert "is_identity" in col
                assert "is_computed" in col
                assert "is_max_type" in col
                
                # Data type should be uppercase
                assert col["data_type"] == col["data_type"].upper()
    
    def test_extract_primary_keys_valid_columns(self, extractor, database_name):
        """Test that primary key columns exist in column metadata."""
        tables = extractor._get_tables(database_name)
        
        if not tables:
            pytest.skip("No tables in database for testing")
        
        qualified_names = [t["qualified_name"] for t in tables]
        columns = extractor._get_columns(database_name, qualified_names)
        primary_keys = extractor._get_primary_keys(database_name, qualified_names)
        
        # Verify PK columns exist in column list
        for table_name, pk_columns in primary_keys.items():
            assert table_name in columns, f"Table {table_name} has PK but no columns"
            
            column_names = {col["name"] for col in columns[table_name]}
            for pk_col in pk_columns:
                assert pk_col in column_names, f"PK column {pk_col} not in column list"
    
    def test_extract_foreign_keys_valid_references(self, extractor, database_name):
        """Test that foreign key references point to existing tables."""
        tables = extractor._get_tables(database_name)
        
        if not tables:
            pytest.skip("No tables in database for testing")
        
        qualified_names = [t["qualified_name"] for t in tables]
        foreign_keys = extractor._get_foreign_keys(database_name, qualified_names)
        
        # Build set of known tables
        known_tables = {f"[{t['schema']}].[{t['name']}]" for t in tables}
        
        # Verify FK references
        for fk in foreign_keys:
            parent_qualified = f"[{fk['parent_schema']}].[{fk['parent_table']}]"
            child_qualified = f"[{fk['child_schema']}].[{fk['child_table']}]"
            
            # Both parent and child should be in known tables
            # (unless the FK references a table outside our extraction scope)
            if parent_qualified not in known_tables:
                # This is okay - might reference a table we didn't extract
                pass
            
            assert child_qualified in known_tables, f"Child table {child_qualified} not found"
            
            # Verify self-referencing flag
            if parent_qualified == child_qualified:
                assert fk["is_self_referencing"] is True
            else:
                assert fk["is_self_referencing"] is False
    
    def test_extract_schema_consistent_runs(self, extractor, database_name):
        """Test that multiple extractions return consistent results."""
        schema1 = extractor.extract_schema(database_name)
        schema2 = extractor.extract_schema(database_name)
        
        # Table count should be the same
        assert len(schema1["tables"]) == len(schema2["tables"])
        
        # Table names should match
        tables1 = {t["qualified_name"] for t in schema1["tables"]}
        tables2 = {t["qualified_name"] for t in schema2["tables"]}
        assert tables1 == tables2
        
        # Column counts should match
        for table_name in tables1:
            if table_name in schema1["columns"] and table_name in schema2["columns"]:
                assert len(schema1["columns"][table_name]) == len(schema2["columns"][table_name])
    
    def test_extract_schema_performance(self, extractor, database_name):
        """Test that schema extraction completes in reasonable time."""
        schema = extractor.extract_schema(database_name)
        
        duration_ms = schema["extraction_duration_ms"]
        table_count = len(schema["tables"])
        
        # Performance expectations (adjust based on database size)
        if table_count <= 10:
            assert duration_ms < 5000, "Small database should extract in < 5s"
        elif table_count <= 100:
            assert duration_ms < 15000, "Medium database should extract in < 15s"
        # Larger databases allowed to take longer
    
    def test_extract_nonexistent_database(self, extractor):
        """Test that extracting non-existent database raises proper error."""
        with pytest.raises(SchemaExtractionError) as exc_info:
            extractor.extract_schema("NonExistentDatabase_12345")
        
        assert exc_info.value.error_code == "DB_NOT_FOUND"
        assert "NonExistentDatabase_12345" in str(exc_info.value)
    
    def test_metadata_integrity_validation(self, extractor, database_name):
        """Test that extracted metadata passes integrity checks."""
        schema = extractor.extract_schema(database_name)
        
        # Check warnings - should not have critical integrity issues
        warnings = schema["warnings"]
        
        # Tables without PKs are okay (logged as warnings)
        # But critical issues shouldn't occur
        for warning in warnings:
            # Make sure no critical integrity violations
            assert "not found in column metadata" not in warning.lower()


class TestSchemaExtractorWithTestData:
    """Integration tests with controlled test data.
    
    These tests create temporary test tables to verify specific scenarios.
    Requires CREATE/DROP table permissions.
    """
    
    @pytest.fixture(scope="class")
    def config(self):
        """Load configuration from environment."""
        return ConfigLoader.load()
    
    @pytest.fixture(scope="class")
    def connection_manager(self, config):
        """Create a connection manager for testing."""
        return DatabaseConnectionManager(config.database)
    
    @pytest.fixture(scope="class")
    def extractor(self, connection_manager):
        """Create a SchemaExtractor instance."""
        return SchemaExtractor(connection_manager)
    
    @pytest.fixture(scope="class")
    def database_name(self, config):
        """Get the test database name from config."""
        return config.database.database
    
    @pytest.fixture(scope="class")
    def test_schema_name(self):
        """Schema name for test tables."""
        return "dbo"
    
    def test_extract_composite_primary_key(self, extractor, connection_manager, database_name, test_schema_name):
        """Test extraction of composite primary key."""
        table_name = "TestCompositeKey"
        qualified_name = f"[{test_schema_name}].[{table_name}]"
        
        try:
            # Create test table with composite key
            connection_manager.execute_query(f"""
                IF OBJECT_ID('{qualified_name}', 'U') IS NOT NULL
                    DROP TABLE {qualified_name}
                
                CREATE TABLE {qualified_name} (
                    OrderID INT NOT NULL,
                    ProductID INT NOT NULL,
                    Quantity INT,
                    PRIMARY KEY (OrderID, ProductID)
                )
            """)
            
            # Extract schema
            pks = extractor._get_primary_keys(database_name, [qualified_name])
            
            # Verify composite key extracted with correct order
            assert qualified_name in pks
            assert len(pks[qualified_name]) == 2
            assert pks[qualified_name] == ["OrderID", "ProductID"]
            
        finally:
            # Cleanup
            try:
                connection_manager.execute_query(f"DROP TABLE IF EXISTS {qualified_name}")
            except:
                pass
    
    def test_extract_self_referencing_foreign_key(self, extractor, connection_manager, database_name, test_schema_name):
        """Test extraction of self-referencing foreign key."""
        table_name = "TestSelfRef"
        qualified_name = f"[{test_schema_name}].[{table_name}]"
        
        try:
            # Create test table with self-referencing FK
            connection_manager.execute_query(f"""
                IF OBJECT_ID('{qualified_name}', 'U') IS NOT NULL
                    DROP TABLE {qualified_name}
                
                CREATE TABLE {qualified_name} (
                    EmployeeID INT PRIMARY KEY,
                    ManagerID INT NULL,
                    Name VARCHAR(100),
                    FOREIGN KEY (ManagerID) REFERENCES {qualified_name}(EmployeeID)
                )
            """)
            
            # Extract FKs
            fks = extractor._get_foreign_keys(database_name, [qualified_name])
            
            # Verify self-referencing FK
            assert len(fks) > 0
            self_ref_fk = next((fk for fk in fks if fk["is_self_referencing"]), None)
            assert self_ref_fk is not None, "Self-referencing FK not found"
            assert self_ref_fk["parent_table"] == table_name
            assert self_ref_fk["child_table"] == table_name
            
        finally:
            # Cleanup
            try:
                connection_manager.execute_query(f"DROP TABLE IF EXISTS {qualified_name}")
            except:
                pass
