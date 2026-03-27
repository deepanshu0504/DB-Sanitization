"""Unit tests for Schema Extractor.

Tests cover:
- SchemaExtractor initialization and dependency injection
- Table extraction with multiple schemas
- Column extraction with data types, lengths, precision, scale
- Primary key extraction including composite keys
- Foreign key extraction including self-referencing and circular dependencies
- Unique constraint extraction
- Index extraction
- Metadata integrity validation
- Exception handling for various error scenarios
- Edge cases (special characters, no PKs, orphaned tables)

These tests use mocking to avoid requiring a real SQL Server instance.
For integration tests with a real database, see tests/integration/.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
import pyodbc

from src.database.schema_extractor import SchemaExtractor
from src.database.connection_manager import DatabaseConnectionManager
from src.exceptions import (
    SchemaExtractionError,
    DatabaseConnectionError,
    DatabaseQueryError
)


class TestSchemaExtractorInit:
    """Test SchemaExtractor initialization."""
    
    def test_init_with_connection_manager(self):
        """Test initialization with valid connection manager."""
        mock_conn_mgr = Mock(spec=DatabaseConnectionManager)
        extractor = SchemaExtractor(mock_conn_mgr)
        
        assert extractor.connection_manager is mock_conn_mgr
        assert extractor.logger is not None
    
    def test_init_stores_connection_manager(self):
        """Test that connection manager is stored as instance variable."""
        mock_conn_mgr = Mock(spec=DatabaseConnectionManager)
        extractor = SchemaExtractor(mock_conn_mgr)
        
        # Verify we can access the connection manager
        assert hasattr(extractor, 'connection_manager')
        assert extractor.connection_manager == mock_conn_mgr


class TestExtractTables:
    """Test table extraction functionality."""
    
    @pytest.fixture
    def mock_connection_manager(self):
        """Create a mock connection manager."""
        return Mock(spec=DatabaseConnectionManager)
    
    @pytest.fixture
    def extractor(self, mock_connection_manager):
        """Create a SchemaExtractor instance with mocked connection."""
        return SchemaExtractor(mock_connection_manager)
    
    def test_extract_tables_single_schema(self, extractor, mock_connection_manager):
        """Test extracting tables from a single schema."""
        # Mock query results
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Customers"),
            ("dbo", "Orders"),
            ("dbo", "Products")
        ]
        
        tables = extractor._get_tables("TestDB")
        
        assert len(tables) == 3
        assert tables[0] == {"schema": "dbo", "name": "Customers", "qualified_name": "[dbo].[Customers]"}
        assert tables[1] == {"schema": "dbo", "name": "Orders", "qualified_name": "[dbo].[Orders]"}
        assert tables[2] == {"schema": "dbo", "name": "Products", "qualified_name": "[dbo].[Products]"}
    
    def test_extract_tables_multiple_schemas(self, extractor, mock_connection_manager):
        """Test extracting tables from multiple schemas."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Customers"),
            ("sales", "Orders"),
            ("hr", "Employees")
        ]
        
        tables = extractor._get_tables("TestDB")
        
        assert len(tables) == 3
        assert tables[0]["schema"] == "dbo"
        assert tables[1]["schema"] == "sales"
        assert tables[2]["schema"] == "hr"
    
    def test_extract_tables_empty_database(self, extractor, mock_connection_manager):
        """Test extracting tables from empty database returns empty list."""
        mock_connection_manager.execute_query.return_value = []
        
        tables = extractor._get_tables("EmptyDB")
        
        assert tables == []
    
    def test_extract_tables_database_not_found(self, extractor, mock_connection_manager):
        """Test that non-existent database raises SchemaExtractionError."""
        mock_connection_manager.execute_query.side_effect = pyodbc.ProgrammingError(
            "Invalid object name 'NonExistentDB.sys.tables'"
        )
        
        with pytest.raises(SchemaExtractionError) as exc_info:
            extractor._get_tables("NonExistentDB")
        
        assert exc_info.value.error_code == "DB_NOT_FOUND"
        assert "NonExistentDB" in str(exc_info.value)
    
    def test_extract_tables_query_error(self, extractor, mock_connection_manager):
        """Test that query errors are properly raised."""
        mock_connection_manager.execute_query.side_effect = pyodbc.Error("Connection timeout")
        
        with pytest.raises(DatabaseQueryError):
            extractor._get_tables("TestDB")


class TestExtractColumns:
    """Test column extraction functionality."""
    
    @pytest.fixture
    def mock_connection_manager(self):
        """Create a mock connection manager."""
        return Mock(spec=DatabaseConnectionManager)
    
    @pytest.fixture
    def extractor(self, mock_connection_manager):
        """Create a SchemaExtractor instance with mocked connection."""
        return SchemaExtractor(mock_connection_manager)
    
    def test_extract_columns_basic_types(self, extractor, mock_connection_manager):
        """Test extracting columns with basic data types."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Customers", "CustomerID", "int", 4, 10, 0, 0, 1, 0),
            ("dbo", "Customers", "Name", "varchar", 100, 0, 0, 0, 0, 0),
            ("dbo", "Customers", "Email", "varchar", 255, 0, 0, 1, 0, 0),
        ]
        
        columns = extractor._get_columns("TestDB", ["[dbo].[Customers]"])
        
        assert "[dbo].[Customers]" in columns
        customer_columns = columns["[dbo].[Customers]"]
        assert len(customer_columns) == 3
        
        # Check CustomerID
        assert customer_columns[0]["name"] == "CustomerID"
        assert customer_columns[0]["data_type"] == "INT"
        assert customer_columns[0]["is_identity"] is True
        assert customer_columns[0]["is_nullable"] is False
        
        # Check Name
        assert customer_columns[1]["name"] == "Name"
        assert customer_columns[1]["data_type"] == "VARCHAR"
        assert customer_columns[1]["max_length"] == 100
        
        # Check Email
        assert customer_columns[2]["name"] == "Email"
        assert customer_columns[2]["is_nullable"] is True
    
    def test_extract_columns_nvarchar_length(self, extractor, mock_connection_manager):
        """Test that NVARCHAR length is correctly divided by 2."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Customers", "Name", "nvarchar", 200, 0, 0, 0, 0, 0),  # 200 bytes = 100 chars
        ]
        
        columns = extractor._get_columns("TestDB", ["[dbo].[Customers]"])
        
        assert columns["[dbo].[Customers]"][0]["max_length"] == 100
    
    def test_extract_columns_varchar_max(self, extractor, mock_connection_manager):
        """Test that VARCHAR(MAX) is properly identified."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Documents", "Content", "varchar", -1, 0, 0, 0, 0, 0),
        ]
        
        columns = extractor._get_columns("TestDB", ["[dbo].[Documents]"])
        
        doc_column = columns["[dbo].[Documents]"][0]
        assert doc_column["max_length"] == -1
        assert doc_column["is_max_type"] is True
    
    def test_extract_columns_decimal_precision_scale(self, extractor, mock_connection_manager):
        """Test extracting DECIMAL columns with precision and scale."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Products", "Price", "decimal", 9, 18, 2, 0, 0, 0),
        ]
        
        columns = extractor._get_columns("TestDB", ["[dbo].[Products]"])
        
        price_column = columns["[dbo].[Products]"][0]
        assert price_column["data_type"] == "DECIMAL"
        assert price_column["precision"] == 18
        assert price_column["scale"] == 2
    
    def test_extract_columns_computed_column(self, extractor, mock_connection_manager):
        """Test that computed columns are properly identified."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Orders", "TotalPrice", "decimal", 9, 18, 2, 0, 0, 1),
        ]
        
        columns = extractor._get_columns("TestDB", ["[dbo].[Orders]"])
        
        assert columns["[dbo].[Orders]"][0]["is_computed"] is True
    
    def test_extract_columns_empty_table_list(self, extractor, mock_connection_manager):
        """Test that empty table list returns empty dict."""
        columns = extractor._get_columns("TestDB", [])
        
        assert columns == {}
        mock_connection_manager.execute_query.assert_not_called()
    
    def test_extract_columns_multiple_tables(self, extractor, mock_connection_manager):
        """Test extracting columns from multiple tables."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Customers", "CustomerID", "int", 4, 10, 0, 0, 1, 0),
            ("dbo", "Orders", "OrderID", "int", 4, 10, 0, 0, 1, 0),
        ]
        
        columns = extractor._get_columns("TestDB", ["[dbo].[Customers]", "[dbo].[Orders]"])
        
        assert "[dbo].[Customers]" in columns
        assert "[dbo].[Orders]" in columns


class TestExtractPrimaryKeys:
    """Test primary key extraction functionality."""
    
    @pytest.fixture
    def mock_connection_manager(self):
        """Create a mock connection manager."""
        return Mock(spec=DatabaseConnectionManager)
    
    @pytest.fixture
    def extractor(self, mock_connection_manager):
        """Create a SchemaExtractor instance with mocked connection."""
        return SchemaExtractor(mock_connection_manager)
    
    def test_extract_primary_keys_single_column(self, extractor, mock_connection_manager):
        """Test extracting single-column primary keys."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Customers", "CustomerID", 1),
        ]
        
        pks = extractor._get_primary_keys("TestDB", ["[dbo].[Customers]"])
        
        assert "[dbo].[Customers]" in pks
        assert pks["[dbo].[Customers]"] == ["CustomerID"]
    
    def test_extract_primary_keys_composite(self, extractor, mock_connection_manager):
        """Test extracting composite primary keys with correct order."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "OrderItems", "OrderID", 1),
            ("dbo", "OrderItems", "ProductID", 2),
        ]
        
        pks = extractor._get_primary_keys("TestDB", ["[dbo].[OrderItems]"])
        
        assert pks["[dbo].[OrderItems]"] == ["OrderID", "ProductID"]
    
    def test_extract_primary_keys_multiple_tables(self, extractor, mock_connection_manager):
        """Test extracting primary keys from multiple tables."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Customers", "CustomerID", 1),
            ("dbo", "Orders", "OrderID", 1),
        ]
        
        pks = extractor._get_primary_keys("TestDB", ["[dbo].[Customers]", "[dbo].[Orders]"])
        
        assert "[dbo].[Customers]" in pks
        assert "[dbo].[Orders]" in pks
    
    def test_extract_primary_keys_empty_table_list(self, extractor, mock_connection_manager):
        """Test that empty table list returns empty dict."""
        pks = extractor._get_primary_keys("TestDB", [])
        
        assert pks == {}
        mock_connection_manager.execute_query.assert_not_called()
    
    def test_extract_primary_keys_no_pk_on_table(self, extractor, mock_connection_manager):
        """Test table without primary key returns empty list."""
        # Return no rows for tables without PKs
        mock_connection_manager.execute_query.return_value = []
        
        pks = extractor._get_primary_keys("TestDB", ["[dbo].[LogTable]"])
        
        assert pks == {}


class TestExtractForeignKeys:
    """Test foreign key extraction functionality."""
    
    @pytest.fixture
    def mock_connection_manager(self):
        """Create a mock connection manager."""
        return Mock(spec=DatabaseConnectionManager)
    
    @pytest.fixture
    def extractor(self, mock_connection_manager):
        """Create a SchemaExtractor instance with mocked connection."""
        return SchemaExtractor(mock_connection_manager)
    
    def test_extract_foreign_keys_simple(self, extractor, mock_connection_manager):
        """Test extracting simple foreign key relationships."""
        mock_connection_manager.execute_query.return_value = [
            ("FK_Orders_Customers", "dbo", "Customers", "CustomerID", "dbo", "Orders", "CustomerID", 1),
        ]
        
        fks = extractor._get_foreign_keys("TestDB", ["[dbo].[Customers]", "[dbo].[Orders]"])
        
        assert len(fks) == 1
        fk = fks[0]
        assert fk["constraint_name"] == "FK_Orders_Customers"
        assert fk["parent_schema"] == "dbo"
        assert fk["parent_table"] == "Customers"
        assert fk["parent_column"] == "CustomerID"
        assert fk["child_schema"] == "dbo"
        assert fk["child_table"] == "Orders"
        assert fk["child_column"] == "CustomerID"
        assert fk["is_self_referencing"] is False
    
    def test_extract_foreign_keys_self_referencing(self, extractor, mock_connection_manager):
        """Test extracting self-referencing foreign keys."""
        mock_connection_manager.execute_query.return_value = [
            ("FK_Employees_Manager", "dbo", "Employees", "EmployeeID", "dbo", "Employees", "ManagerID", 1),
        ]
        
        fks = extractor._get_foreign_keys("TestDB", ["[dbo].[Employees]"])
        
        assert len(fks) == 1
        assert fks[0]["is_self_referencing"] is True
    
    def test_extract_foreign_keys_composite(self, extractor, mock_connection_manager):
        """Test extracting composite foreign keys."""
        mock_connection_manager.execute_query.return_value = [
            ("FK_OrderItems", "dbo", "Orders", "OrderID", "dbo", "OrderItems", "OrderID", 1),
            ("FK_OrderItems", "dbo", "Products", "ProductID", "dbo", "OrderItems", "ProductID", 2),
        ]
        
        fks = extractor._get_foreign_keys("TestDB", ["[dbo].[Orders]", "[dbo].[Products]", "[dbo].[OrderItems]"])
        
        assert len(fks) == 2
        assert fks[0]["constraint_name"] == "FK_OrderItems"
        assert fks[0]["ordinal_position"] == 1
        assert fks[1]["constraint_name"] == "FK_OrderItems"
        assert fks[1]["ordinal_position"] == 2
    
    def test_extract_foreign_keys_multiple_fks_same_tables(self, extractor, mock_connection_manager):
        """Test extracting multiple FKs between same tables."""
        mock_connection_manager.execute_query.return_value = [
            ("FK_Orders_BillingAddress", "dbo", "Addresses", "AddressID", "dbo", "Orders", "BillingAddressID", 1),
            ("FK_Orders_ShippingAddress", "dbo", "Addresses", "AddressID", "dbo", "Orders", "ShippingAddressID", 1),
        ]
        
        fks = extractor._get_foreign_keys("TestDB", ["[dbo].[Orders]", "[dbo].[Addresses]"])
        
        assert len(fks) == 2
        assert fks[0]["constraint_name"] != fks[1]["constraint_name"]
    
    def test_extract_foreign_keys_empty_table_list(self, extractor, mock_connection_manager):
        """Test that empty table list returns empty list."""
        fks = extractor._get_foreign_keys("TestDB", [])
        
        assert fks == []
        mock_connection_manager.execute_query.assert_not_called()
    
    def test_extract_foreign_keys_cross_schema(self, extractor, mock_connection_manager):
        """Test extracting foreign keys across different schemas."""
        mock_connection_manager.execute_query.return_value = [
            ("FK_Sales_HR", "hr", "Employees", "EmployeeID", "sales", "Orders", "EmployeeID", 1),
        ]
        
        fks = extractor._get_foreign_keys("TestDB", ["[hr].[Employees]", "[sales].[Orders]"])
        
        assert len(fks) == 1
        assert fks[0]["parent_schema"] == "hr"
        assert fks[0]["child_schema"] == "sales"
    
    def test_extract_foreign_keys_circular_dependency(self, extractor, mock_connection_manager):
        """Test extracting circular foreign key dependencies."""
        mock_connection_manager.execute_query.return_value = [
            ("FK_Order_Promotion", "dbo", "Promotions", "PromotionID", "dbo", "Orders", "PromotionID", 1),
            ("FK_Promotion_Order", "dbo", "Orders", "OrderID", "dbo", "Promotions", "BestOrderID", 1),
        ]
        
        fks = extractor._get_foreign_keys("TestDB", ["[dbo].[Orders]", "[dbo].[Promotions]"])
        
        # Both FKs should be extracted - circular dependency detection is for Story 2.2
        assert len(fks) == 2


class TestExtractUniqueConstraints:
    """Test unique constraint extraction functionality."""
    
    @pytest.fixture
    def mock_connection_manager(self):
        """Create a mock connection manager."""
        return Mock(spec=DatabaseConnectionManager)
    
    @pytest.fixture
    def extractor(self, mock_connection_manager):
        """Create a SchemaExtractor instance with mocked connection."""
        return SchemaExtractor(mock_connection_manager)
    
    def test_extract_unique_constraints_single_column(self, extractor, mock_connection_manager):
        """Test extracting single-column unique constraints."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Customers", "UQ_Customers_Email", "Email", 1),
        ]
        
        ucs = extractor._get_unique_constraints("TestDB", ["[dbo].[Customers]"])
        
        assert "[dbo].[Customers]" in ucs
        assert len(ucs["[dbo].[Customers]"]) == 1
        assert ucs["[dbo].[Customers]"][0]["constraint_name"] == "UQ_Customers_Email"
        assert ucs["[dbo].[Customers]"][0]["columns"] == ["Email"]
    
    def test_extract_unique_constraints_multi_column(self, extractor, mock_connection_manager):
        """Test extracting multi-column unique constraints."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "OrderItems", "UQ_OrderItems", "OrderID", 1),
            ("dbo", "OrderItems", "UQ_OrderItems", "ProductID", 2),
        ]
        
        ucs = extractor._get_unique_constraints("TestDB", ["[dbo].[OrderItems]"])
        
        assert ucs["[dbo].[OrderItems]"][0]["columns"] == ["OrderID", "ProductID"]
    
    def test_extract_unique_constraints_empty_table_list(self, extractor, mock_connection_manager):
        """Test that empty table list returns empty dict."""
        ucs = extractor._get_unique_constraints("TestDB", [])
        
        assert ucs == {}
        mock_connection_manager.execute_query.assert_not_called()


class TestExtractIndexes:
    """Test index extraction functionality."""
    
    @pytest.fixture
    def mock_connection_manager(self):
        """Create a mock connection manager."""
        return Mock(spec=DatabaseConnectionManager)
    
    @pytest.fixture
    def extractor(self, mock_connection_manager):
        """Create a SchemaExtractor instance with mocked connection."""
        return SchemaExtractor(mock_connection_manager)
    
    def test_extract_indexes_clustered(self, extractor, mock_connection_manager):
        """Test extracting clustered indexes."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Customers", "PK_Customers", "CLUSTERED", 1, 1, "CustomerID", 1),
        ]
        
        indexes = extractor._get_indexes("TestDB", ["[dbo].[Customers]"])
        
        assert "[dbo].[Customers]" in indexes
        idx = indexes["[dbo].[Customers]"][0]
        assert idx["name"] == "PK_Customers"
        assert idx["type"] == "CLUSTERED"
        assert idx["is_unique"] is True
        assert idx["is_primary_key"] is True
        assert idx["columns"] == ["CustomerID"]
    
    def test_extract_indexes_non_clustered(self, extractor, mock_connection_manager):
        """Test extracting non-clustered indexes."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Customers", "IX_Customers_Email", "NONCLUSTERED", 1, 0, "Email", 1),
        ]
        
        indexes = extractor._get_indexes("TestDB", ["[dbo].[Customers]"])
        
        idx = indexes["[dbo].[Customers]"][0]
        assert idx["type"] == "NONCLUSTERED"
        assert idx["is_primary_key"] is False
    
    def test_extract_indexes_composite(self, extractor, mock_connection_manager):
        """Test extracting composite indexes."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Orders", "IX_Orders_Customer_Date", "NONCLUSTERED", 0, 0, "CustomerID", 1),
            ("dbo", "Orders", "IX_Orders_Customer_Date", "NONCLUSTERED", 0, 0, "OrderDate", 2),
        ]
        
        indexes = extractor._get_indexes("TestDB", ["[dbo].[Orders]"])
        
        idx = indexes["[dbo].[Orders]"][0]
        assert idx["columns"] == ["CustomerID", "OrderDate"]
    
    def test_extract_indexes_empty_table_list(self, extractor, mock_connection_manager):
        """Test that empty table list returns empty dict."""
        indexes = extractor._get_indexes("TestDB", [])
        
        assert indexes == {}
        mock_connection_manager.execute_query.assert_not_called()


class TestExtractSchemaOrchestration:
    """Test the full extract_schema orchestration method."""
    
    @pytest.fixture
    def mock_connection_manager(self):
        """Create a mock connection manager."""
        return Mock(spec=DatabaseConnectionManager)
    
    @pytest.fixture
    def extractor(self, mock_connection_manager):
        """Create a SchemaExtractor instance with mocked connection."""
        return SchemaExtractor(mock_connection_manager)
    
    def test_extract_schema_complete_workflow(self, extractor, mock_connection_manager):
        """Test complete schema extraction workflow."""
        # Mock tables
        mock_connection_manager.execute_query.side_effect = [
            # Tables
            [("dbo", "Customers")],
            # Columns
            [("dbo", "Customers", "CustomerID", "int", 4, 10, 0, 0, 1, 0)],
            # Primary keys
            [("dbo", "Customers", "CustomerID", 1)],
            # Foreign keys
            [],
            # Unique constraints
            [],
            # Indexes
            [("dbo", "Customers", "PK_Customers", "CLUSTERED", 1, 1, "CustomerID", 1)],
        ]
        
        schema = extractor.extract_schema("TestDB")
        
        assert schema["database_name"] == "TestDB"
        assert len(schema["tables"]) == 1
        assert "[dbo].[Customers]" in schema["columns"]
        assert "[dbo].[Customers]" in schema["primary_keys"]
        assert "extraction_timestamp" in schema
        assert "extraction_duration_ms" in schema
    
    def test_extract_schema_empty_database(self, extractor, mock_connection_manager):
        """Test extracting schema from empty database."""
        mock_connection_manager.execute_query.return_value = []
        
        schema = extractor.extract_schema("EmptyDB")
        
        assert schema["database_name"] == "EmptyDB"
        assert schema["tables"] == []
        assert schema["columns"] == {}
        assert len(schema["warnings"]) > 0
    
    def test_extract_schema_connection_error(self, extractor, mock_connection_manager):
        """Test that connection errors are properly propagated."""
        mock_connection_manager.execute_query.side_effect = DatabaseConnectionError(
            message="Connection failed",
            error_code="CONN_FAILED"
        )
        
        with pytest.raises(DatabaseConnectionError):
            extractor.extract_schema("TestDB")
    
    def test_extract_schema_database_not_found(self, extractor, mock_connection_manager):
        """Test that database not found error is raised."""
        mock_connection_manager.execute_query.side_effect = pyodbc.ProgrammingError(
            "Cannot find database 'NonExistent'"
        )
        
        with pytest.raises(SchemaExtractionError) as exc_info:
            extractor.extract_schema("NonExistent")
        
        assert exc_info.value.error_code == "DB_NOT_FOUND"


class TestMetadataValidation:
    """Test metadata integrity validation."""
    
    @pytest.fixture
    def mock_connection_manager(self):
        """Create a mock connection manager."""
        return Mock(spec=DatabaseConnectionManager)
    
    @pytest.fixture
    def extractor(self, mock_connection_manager):
        """Create a SchemaExtractor instance with mocked connection."""
        return SchemaExtractor(mock_connection_manager)
    
    def test_validate_metadata_table_without_columns(self, extractor):
        """Test validation warns about tables without columns."""
        tables = [{"schema": "dbo", "name": "EmptyTable", "qualified_name": "[dbo].[EmptyTable]"}]
        columns = {}
        primary_keys = {}
        foreign_keys = []
        
        warnings = extractor._validate_metadata_integrity(tables, columns, primary_keys, foreign_keys)
        
        assert any("no columns" in w.lower() for w in warnings)
    
    def test_validate_metadata_table_without_pk(self, extractor):
        """Test validation warns about tables without primary keys."""
        tables = [{"schema": "dbo", "name": "LogTable", "qualified_name": "[dbo].[LogTable]"}]
        columns = {"[dbo].[LogTable]": [{"name": "LogID", "data_type": "INT"}]}
        primary_keys = {}
        foreign_keys = []
        
        warnings = extractor._validate_metadata_integrity(tables, columns, primary_keys, foreign_keys)
        
        assert any("no primary key" in w.lower() for w in warnings)
    
    def test_validate_metadata_pk_column_not_in_columns(self, extractor):
        """Test validation warns about PK columns missing from column list."""
        tables = [{"schema": "dbo", "name": "Customers", "qualified_name": "[dbo].[Customers]"}]
        columns = {"[dbo].[Customers]": [{"name": "Name", "data_type": "VARCHAR"}]}
        primary_keys = {"[dbo].[Customers]": ["CustomerID"]}
        foreign_keys = []
        
        warnings = extractor._validate_metadata_integrity(tables, columns, primary_keys, foreign_keys)
        
        assert any("CustomerID" in w for w in warnings)
    
    def test_validate_metadata_valid_schema(self, extractor):
        """Test validation returns no warnings for valid schema."""
        tables = [{"schema": "dbo", "name": "Customers", "qualified_name": "[dbo].[Customers]"}]
        columns = {"[dbo].[Customers]": [{"name": "CustomerID", "data_type": "INT"}]}
        primary_keys = {"[dbo].[Customers]": ["CustomerID"]}
        foreign_keys = []
        
        warnings = extractor._validate_metadata_integrity(tables, columns, primary_keys, foreign_keys)
        
        # Only warning should be about no PK (which is actually present, so no warning)
        assert len(warnings) == 0


class TestExceptionHandling:
    """Test exception handling scenarios."""
    
    @pytest.fixture
    def mock_connection_manager(self):
        """Create a mock connection manager."""
        return Mock(spec=DatabaseConnectionManager)
    
    @pytest.fixture
    def extractor(self, mock_connection_manager):
        """Create a SchemaExtractor instance with mocked connection."""
        return SchemaExtractor(mock_connection_manager)
    
    def test_query_error_raises_database_query_error(self, extractor, mock_connection_manager):
        """Test that pyodbc errors are converted to DatabaseQueryError."""
        mock_connection_manager.execute_query.side_effect = pyodbc.Error("Query failed")
        
        with pytest.raises(DatabaseQueryError):
            extractor._get_tables("TestDB")
    
    def test_permission_denied_raises_error(self, extractor, mock_connection_manager):
        """Test that permission errors are properly raised."""
        mock_connection_manager.execute_query.side_effect = pyodbc.Error(
            "SELECT permission denied on sys.tables"
        )
        
        with pytest.raises(DatabaseQueryError):
            extractor._get_tables("TestDB")


class TestEdgeCases:
    """Test edge cases and special scenarios."""
    
    @pytest.fixture
    def mock_connection_manager(self):
        """Create a mock connection manager."""
        return Mock(spec=DatabaseConnectionManager)
    
    @pytest.fixture
    def extractor(self, mock_connection_manager):
        """Create a SchemaExtractor instance with mocked connection."""
        return SchemaExtractor(mock_connection_manager)
    
    def test_special_characters_in_table_names(self, extractor, mock_connection_manager):
        """Test handling tables with special characters in names."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Order-Details"),
            ("dbo", "User Data"),
        ]
        
        tables = extractor._get_tables("TestDB")
        
        # Check that qualified names properly escape special characters
        assert tables[0]["qualified_name"] == "[dbo].[Order-Details]"
        assert tables[1]["qualified_name"] == "[dbo].[User Data]"
    
    def test_case_sensitive_schema_names(self, extractor, mock_connection_manager):
        """Test that schema names preserve case."""
        mock_connection_manager.execute_query.return_value = [
            ("DBO", "Customers"),
            ("Sales", "Orders"),
        ]
        
        tables = extractor._get_tables("TestDB")
        
        # Case should be preserved as returned by SQL Server
        assert tables[0]["schema"] == "DBO"
        assert tables[1]["schema"] == "Sales"
    
    def test_data_type_normalization(self, extractor, mock_connection_manager):
        """Test that data types are normalized to uppercase."""
        mock_connection_manager.execute_query.return_value = [
            ("dbo", "Customers", "Name", "varchar", 100, 0, 0, 0, 0, 0),
        ]
        
        columns = extractor._get_columns("TestDB", ["[dbo].[Customers]"])
        
        # Data type should be uppercase regardless of how SQL Server returns it
        assert columns["[dbo].[Customers]"][0]["data_type"] == "VARCHAR"
