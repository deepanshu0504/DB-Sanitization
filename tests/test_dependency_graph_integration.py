"""
Integration tests for dependency_graph_builder with real database.

These tests require a live database connection and validate the dependency
graph builder against actual SQL Server system tables.

Prerequisites:
    - Active database connection configured in .env or config
    - Database schema with FK relationships (test tables recommended)
    - READ access to sys.foreign_keys and sys.foreign_key_columns

Usage:
    pytest tests/test_dependency_graph_integration.py -v
    pytest tests/test_dependency_graph_integration.py -v -k "test_extract_real_fk"
"""

import pytest
import os
import pyodbc
from database.dependency_graph_builder import (
    DependencyGraph,
    ForeignKeyRelationship,
    ProcessingOrder,
)
from desanitization.exceptions import CircularDependencyError


@pytest.fixture(scope="module")
def db_connection():
    """
    Create database connection for integration tests.
    
    Reads connection string from environment variables:
        DB_SERVER, DB_NAME, DB_USER, DB_PASSWORD
    Or uses Windows Authentication if credentials not provided.
    """
    server = os.getenv("DB_SERVER", "localhost")
    database = os.getenv("DB_NAME", "TestSanitizationDB")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    
    # Build connection string
    if user and password:
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};DATABASE={database};"
            f"UID={user};PWD={password}"
        )
    else:
        # Windows Authentication
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};DATABASE={database};"
            f"Trusted_Connection=yes;"
        )
    
    try:
        conn = pyodbc.connect(conn_str, timeout=10)
        yield conn
        conn.close()
    except pyodbc.Error as e:
        pytest.skip(f"Database connection failed: {e}")


@pytest.fixture(scope="module")
def test_schema_setup(db_connection):
    """
    Setup test schema with FK relationships for integration testing.
    
    Creates a simple schema:
        Categories (independent)
        Products -> Categories
        Customers (independent)
        Orders -> Customers
        OrderDetails -> Orders, Products
    
    Cleans up after all tests complete.
    """
    cursor = db_connection.cursor()
    
    # Drop existing test tables (if any)
    cleanup_sql = """
        IF OBJECT_ID('dbo.OrderDetails', 'U') IS NOT NULL DROP TABLE dbo.OrderDetails;
        IF OBJECT_ID('dbo.Orders', 'U') IS NOT NULL DROP TABLE dbo.Orders;
        IF OBJECT_ID('dbo.Products', 'U') IS NOT NULL DROP TABLE dbo.Products;
        IF OBJECT_ID('dbo.Customers', 'U') IS NOT NULL DROP TABLE dbo.Customers;
        IF OBJECT_ID('dbo.Categories', 'U') IS NOT NULL DROP TABLE dbo.Categories;
    """
    
    # Create test schema
    setup_sql = """
        CREATE TABLE dbo.Categories (
            CategoryID INT PRIMARY KEY,
            CategoryName NVARCHAR(50)
        );
        
        CREATE TABLE dbo.Products (
            ProductID INT PRIMARY KEY,
            ProductName NVARCHAR(100),
            CategoryID INT,
            CONSTRAINT FK_Products_Categories FOREIGN KEY (CategoryID) 
                REFERENCES dbo.Categories(CategoryID)
        );
        
        CREATE TABLE dbo.Customers (
            CustomerID INT PRIMARY KEY,
            CustomerName NVARCHAR(100)
        );
        
        CREATE TABLE dbo.Orders (
            OrderID INT PRIMARY KEY,
            CustomerID INT,
            OrderDate DATE,
            CONSTRAINT FK_Orders_Customers FOREIGN KEY (CustomerID) 
                REFERENCES dbo.Customers(CustomerID)
        );
        
        CREATE TABLE dbo.OrderDetails (
            OrderDetailID INT PRIMARY KEY,
            OrderID INT,
            ProductID INT,
            Quantity INT,
            CONSTRAINT FK_OrderDetails_Orders FOREIGN KEY (OrderID) 
                REFERENCES dbo.Orders(OrderID),
            CONSTRAINT FK_OrderDetails_Products FOREIGN KEY (ProductID) 
                REFERENCES dbo.Products(ProductID)
        );
    """
    
    try:
        # Cleanup first
        for statement in cleanup_sql.split(';'):
            if statement.strip():
                try:
                    cursor.execute(statement)
                except:
                    pass  # Ignore errors if tables don't exist
        
        db_connection.commit()
        
        # Create schema
        for statement in setup_sql.split(';'):
            if statement.strip():
                cursor.execute(statement)
        
        db_connection.commit()
        
        yield  # Run tests
        
        # Cleanup after tests
        for statement in cleanup_sql.split(';'):
            if statement.strip():
                try:
                    cursor.execute(statement)
                    db_connection.commit()
                except:
                    pass
    
    except Exception as e:
        pytest.skip(f"Test schema setup failed: {e}")


class TestDependencyGraphIntegrationBasic:
    """Basic integration tests with real database."""
    
    def test_extract_real_fk_relationships(self, db_connection, test_schema_setup):
        """Test FK extraction from real database system tables."""
        graph = DependencyGraph(db_connection)
        graph.build_graph()
        
        # Verify relationships were extracted
        assert len(graph.relationships) > 0
        
        # Verify specific FK relationships exist
        fk_names = [fk.constraint_name for fk in graph.relationships]
        
        # Check for our test FKs
        assert any('Products_Categories' in name for name in fk_names)
        assert any('Orders_Customers' in name for name in fk_names)
        assert any('OrderDetails_Orders' in name for name in fk_names)
        assert any('OrderDetails_Products' in name for name in fk_names)
    
    def test_graph_structure_with_real_data(self, db_connection, test_schema_setup):
        """Test graph structure built from real database."""
        graph = DependencyGraph(db_connection)
        graph.build_graph()
        
        # Verify tables are in graph
        assert '[dbo].[Categories]' in graph.all_tables
        assert '[dbo].[Products]' in graph.all_tables
        assert '[dbo].[Customers]' in graph.all_tables
        assert '[dbo].[Orders]' in graph.all_tables
        assert '[dbo].[OrderDetails]' in graph.all_tables
        
        # Verify dependencies
        assert '[dbo].[Categories]' in graph.graph['[dbo].[Products]']
        assert '[dbo].[Customers]' in graph.graph['[dbo].[Orders]']
        assert '[dbo].[Orders]' in graph.graph['[dbo].[OrderDetails]']
        assert '[dbo].[Products]' in graph.graph['[dbo].[OrderDetails]']
    
    def test_topological_sort_with_real_data(self, db_connection, test_schema_setup):
        """Test topological sort produces valid order."""
        graph = DependencyGraph(db_connection)
        graph.build_graph()
        
        # Should not have cycles
        assert graph.is_cyclic() is False
        
        # Get topological sort
        sorted_tables = graph.topological_sort()
        
        # Verify all test tables included
        assert '[dbo].[Categories]' in sorted_tables
        assert '[dbo].[Products]' in sorted_tables
        assert '[dbo].[Customers]' in sorted_tables
        assert '[dbo].[Orders]' in sorted_tables
        assert '[dbo].[OrderDetails]' in sorted_tables
        
        # Verify parent tables come before child tables
        categories_idx = sorted_tables.index('[dbo].[Categories]')
        products_idx = sorted_tables.index('[dbo].[Products]')
        assert categories_idx < products_idx
        
        customers_idx = sorted_tables.index('[dbo].[Customers]')
        orders_idx = sorted_tables.index('[dbo].[Orders]')
        assert customers_idx < orders_idx
        
        orderdetails_idx = sorted_tables.index('[dbo].[OrderDetails]')
        assert products_idx < orderdetails_idx
        assert orders_idx < orderdetails_idx
    
    def test_get_processing_order_with_real_data(self, db_connection, test_schema_setup):
        """Test complete processing order analysis."""
        graph = DependencyGraph(db_connection)
        graph.build_graph()
        
        order = graph.get_processing_order()
        
        # Verify structure
        assert isinstance(order, ProcessingOrder)
        
        # Categories and Customers should be independent or early in ordered list
        all_tables = (order.independent_tables + order.ordered_tables + 
                     sum(order.circular_groups, []) + order.self_referencing_tables)
        
        assert '[dbo].[Categories]' in all_tables
        assert '[dbo].[Customers]' in all_tables
        assert '[dbo].[Products]' in all_tables
        assert '[dbo].[Orders]' in all_tables
        assert '[dbo].[OrderDetails]' in all_tables
        
        # Should have no circular groups for this simple schema
        assert len(order.circular_groups) == 0
        
        # Should have no self-referencing tables
        assert len(order.self_referencing_tables) == 0


class TestDependencyGraphIntegrationAdvanced:
    """Advanced integration tests requiring specific schemas."""
    
    def test_get_dependencies_for_table(self, db_connection, test_schema_setup):
        """Test getting dependencies for specific table."""
        graph = DependencyGraph(db_connection)
        graph.build_graph()
        
        # Get dependencies for OrderDetails
        deps = graph.get_dependencies('[dbo].[OrderDetails]')
        
        # Should have 2 parents (Orders, Products)
        assert len(deps['parents']) == 2
        assert '[dbo].[Orders]' in deps['parents']
        assert '[dbo].[Products]' in deps['parents']
        
        # Should have no children
        assert len(deps['children']) == 0
        
        # Get dependencies for Categories
        deps = graph.get_dependencies('[dbo].[Categories]')
        
        # Should have no parents
        assert len(deps['parents']) == 0
        
        # Should have 1 child (Products)
        assert '[dbo].[Products]' in deps['children']
    
    def test_schema_filter(self, db_connection, test_schema_setup):
        """Test filtering by schema during graph build."""
        graph = DependencyGraph(db_connection)
        
        # Build graph for dbo schema only
        graph.build_graph(schema_filter=['dbo'])
        
        # All test tables should be included (they're all in dbo)
        assert '[dbo].[Categories]' in graph.all_tables
        assert '[dbo].[Products]' in graph.all_tables
    
    def test_export_to_dot_with_real_data(self, db_connection, test_schema_setup, tmp_path):
        """Test DOT export with real data."""
        graph = DependencyGraph(db_connection)
        graph.build_graph()
        
        output_file = tmp_path / "test_graph.dot"
        graph.export_to_dot(str(output_file))
        
        # Verify file created
        assert output_file.exists()
        
        # Verify content
        content = output_file.read_text()
        assert 'digraph DependencyGraph' in content
        assert 'Categories' in content
        assert 'Products' in content
        assert 'Orders' in content
        assert '->' in content


class TestDependencyGraphIntegrationEdgeCases:
    """Integration tests for edge cases."""
    
    @pytest.mark.skip(reason="Requires manual setup of self-referencing table")
    def test_self_referencing_table_integration(self, db_connection):
        """
        Test with self-referencing table (requires manual setup).
        
        To run this test, create:
            CREATE TABLE dbo.Employees (
                EmployeeID INT PRIMARY KEY,
                ManagerID INT,
                CONSTRAINT FK_Employees_Manager FOREIGN KEY (ManagerID)
                    REFERENCES dbo.Employees(EmployeeID)
            );
        """
        graph = DependencyGraph(db_connection)
        graph.build_graph()
        
        # Verify self-referencing table detected
        assert '[dbo].[Employees]' in graph.self_referencing_tables
        
        # Verify excluded from topological sort
        sorted_tables = graph.topological_sort()
        assert '[dbo].[Employees]' not in sorted_tables
        
        # Verify included in processing order
        order = graph.get_processing_order()
        assert '[dbo].[Employees]' in order.self_referencing_tables
    
    @pytest.mark.skip(reason="Requires manual setup of circular dependencies")
    def test_circular_dependencies_integration(self, db_connection):
        """
        Test with circular FK dependencies (requires manual setup).
        
        To run this test, create:
            CREATE TABLE dbo.A (ID INT PRIMARY KEY, BID INT);
            CREATE TABLE dbo.B (ID INT PRIMARY KEY, CID INT);
            CREATE TABLE dbo.C (ID INT PRIMARY KEY, AID INT);
            
            ALTER TABLE dbo.A ADD CONSTRAINT FK_A_B FOREIGN KEY (BID) REFERENCES dbo.B(ID);
            ALTER TABLE dbo.B ADD CONSTRAINT FK_B_C FOREIGN KEY (CID) REFERENCES dbo.C(ID);
            ALTER TABLE dbo.C ADD CONSTRAINT FK_C_A FOREIGN KEY (AID) REFERENCES dbo.A(ID);
        """
        graph = DependencyGraph(db_connection)
        graph.build_graph()
        
        # Verify cycle detected
        assert graph.is_cyclic() is True
        
        cycles = graph.detect_cycles()
        assert len(cycles) > 0
        
        # Verify topological sort raises error
        with pytest.raises(CircularDependencyError):
            graph.topological_sort()
        
        # Verify SCCs detected
        sccs = graph.get_strongly_connected_components()
        assert len(sccs) > 0
        
        # Verify processing order identifies circular groups
        order = graph.get_processing_order()
        assert len(order.circular_groups) > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
