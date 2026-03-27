"""
Integration tests for DependencyResolver class with real database.

These tests require an actual SQL Server instance for end-to-end validation
of dependency resolution with real schema metadata extraction.

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from typing import List, Dict, Any

from src.config import ConfigLoader, SanitizationConfig
from src.database import DatabaseConnectionManager, SchemaExtractor
from src.sanitization import DependencyResolver
from src.exceptions import CircularDependencyError


# Skip tests if database is not available
pytestmark = pytest.mark.skipif(
    not pytest.config.getoption("--integration", default=False),
    reason="Integration tests require --integration flag and database availability"
)


@pytest.fixture(scope="class")
def config() -> SanitizationConfig:
    """Load configuration for integration tests."""
    config_path = "config/pii_config.example.json"
    return ConfigLoader.load_from_file(config_path)


@pytest.fixture(scope="class") 
def connection_manager(config: SanitizationConfig) -> DatabaseConnectionManager:
    """Create database connection manager."""
    return DatabaseConnectionManager(config.database)


@pytest.fixture(scope="class")
def schema_extractor(connection_manager: DatabaseConnectionManager) -> SchemaExtractor:
    """Create schema extractor."""
    return SchemaExtractor(connection_manager)


class TestDependencyResolverIntegration:
    """Integration tests with real database schema extraction."""
    
    def test_simple_dependency_resolution(
        self,
        connection_manager: DatabaseConnectionManager,
        schema_extractor: SchemaExtractor
    ):
        """Test dependency resolution with simple real schema."""
        # Create test tables with simple dependency
        try:
            connection_manager.execute_query("""
                IF OBJECT_ID('dbo.TestOrder', 'U') IS NOT NULL DROP TABLE dbo.TestOrder;
                IF OBJECT_ID('dbo.TestCustomer', 'U') IS NOT NULL DROP TABLE dbo.TestCustomer;
                
                CREATE TABLE dbo.TestCustomer (
                    CustomerID INT PRIMARY KEY,
                    CustomerName NVARCHAR(100)
                );
                
                CREATE TABLE dbo.TestOrder (
                    OrderID INT PRIMARY KEY,
                    CustomerID INT NOT NULL,
                    OrderDate DATETIME,
                    CONSTRAINT FK_TestOrder_Customer FOREIGN KEY (CustomerID)
                        REFERENCES dbo.TestCustomer(CustomerID)
                );
            """)
            
            # Extract foreign keys
            fks = schema_extractor._get_foreign_keys()
            
            # Filter to test tables only
            test_fks = [fk for fk in fks if fk["child_table"].startswith("Test")]
            
            # Create resolver
            resolver = DependencyResolver(test_fks)
            
            # Verify no cycles
            assert not resolver.has_circular_dependencies()
            
            # Get processing order
            order = resolver.get_processing_order()
            
            # Verify Customer comes before Order
            customer_idx = next((i for i, t in enumerate(order) if "TestCustomer" in t), None)
            order_idx = next((i for i, t in enumerate(order) if "TestOrder" in t), None)
            
            assert customer_idx is not None
            assert order_idx is not None
            assert customer_idx < order_idx
            
        finally:
            # Cleanup
            connection_manager.execute_query("""
                IF OBJECT_ID('dbo.TestOrder', 'U') IS NOT NULL DROP TABLE dbo.TestOrder;
                IF OBJECT_ID('dbo.TestCustomer', 'U') IS NOT NULL DROP TABLE dbo.TestCustomer;
            """)
    
    def test_self_referencing_table_resolution(
        self,
        connection_manager: DatabaseConnectionManager,
        schema_extractor: SchemaExtractor
    ):
        """Test dependency resolution with self-referencing table."""
        try:
            connection_manager.execute_query("""
                IF OBJECT_ID('dbo.TestEmployee', 'U') IS NOT NULL DROP TABLE dbo.TestEmployee;
                
                CREATE TABLE dbo.TestEmployee (
                    EmployeeID INT PRIMARY KEY,
                    EmployeeName NVARCHAR(100),
                    ManagerID INT NULL,
                    CONSTRAINT FK_TestEmployee_Manager FOREIGN KEY (ManagerID)
                        REFERENCES dbo.TestEmployee(EmployeeID)
                );
            """)
            
            # Extract foreign keys
            fks = schema_extractor._get_foreign_keys()
            test_fks = [fk for fk in fks if fk["child_table"].startswith("Test")]
            
            # Create resolver
            resolver = DependencyResolver(test_fks)
            
            # Verify Employee is identified as self-referencing
            assert "dbo.TestEmployee" in resolver.self_referencing_tables
            assert resolver.is_self_referencing("dbo.TestEmployee")
            
            # Should NOT count as circular dependency
            assert not resolver.has_circular_dependencies()
            
            # Should allow topological sort
            order = resolver.get_processing_order()
            assert "dbo.TestEmployee" in order
            
        finally:
            connection_manager.execute_query("""
                IF OBJECT_ID('dbo.TestEmployee', 'U') IS NOT NULL DROP TABLE dbo.TestEmployee;
            """)
    
    def test_circular_dependency_detection_real_schema(
        self,
        connection_manager: DatabaseConnectionManager,
        schema_extractor: SchemaExtractor
    ):
        """Test circular dependency detection with real schema."""
        try:
            # Create circular dependency: A -> B -> C -> A
            connection_manager.execute_query("""
                IF OBJECT_ID('dbo.TestC', 'U') IS NOT NULL DROP TABLE dbo.TestC;
                IF OBJECT_ID('dbo.TestB', 'U') IS NOT NULL DROP TABLE dbo.TestB;
                IF OBJECT_ID('dbo.TestA', 'U') IS NOT NULL DROP TABLE dbo.TestA;
                
                CREATE TABLE dbo.TestA (
                    AID INT PRIMARY KEY,
                    CID INT NULL
                );
                
                CREATE TABLE dbo.TestB (
                    BID INT PRIMARY KEY,
                    AID INT NOT NULL,
                    CONSTRAINT FK_TestB_A FOREIGN KEY (AID) REFERENCES dbo.TestA(AID)
                );
                
                CREATE TABLE dbo.TestC (
                    CID INT PRIMARY KEY,
                    BID INT NOT NULL,
                    CONSTRAINT FK_TestC_B FOREIGN KEY (BID) REFERENCES dbo.TestB(BID)
                );
                
                -- Add circular reference
                ALTER TABLE dbo.TestA
                ADD CONSTRAINT FK_TestA_C FOREIGN KEY (CID) REFERENCES dbo.TestC(CID);
            """)
            
            # Extract foreign keys
            fks = schema_extractor._get_foreign_keys()
            test_fks = [fk for fk in fks if fk["child_table"].startswith("Test")]
            
            # Create resolver
            resolver = DependencyResolver(test_fks)
            
            # Should detect circular dependency
            assert resolver.has_circular_dependencies()
            
            # Get cycles
            cycles = resolver.get_cycles()
            assert len(cycles) >= 1
            
            # Verify cycle contains all three tables
            cycle_tables = set()
            for cycle in cycles:
                cycle_tables.update(cycle)
            
            assert any("TestA" in t for t in cycle_tables)
            assert any("TestB" in t for t in cycle_tables)
            assert any("TestC" in t for t in cycle_tables)
            
            # Should raise exception on topological sort
            with pytest.raises(CircularDependencyError):
                resolver.get_processing_order()
            
        finally:
            connection_manager.execute_query("""
                IF OBJECT_ID('dbo.TestC', 'U') IS NOT NULL 
                    ALTER TABLE dbo.TestA DROP CONSTRAINT FK_TestA_C;
                IF OBJECT_ID('dbo.TestC', 'U') IS NOT NULL DROP TABLE dbo.TestC;
                IF OBJECT_ID('dbo.TestB', 'U') IS NOT NULL DROP TABLE dbo.TestB;
                IF OBJECT_ID('dbo.TestA', 'U') IS NOT NULL DROP TABLE dbo.TestA;
            """)
    
    def test_complex_dependency_graph(
        self,
        connection_manager: DatabaseConnectionManager,
        schema_extractor: SchemaExtractor
    ):
        """Test dependency resolution with complex multi-level dependencies."""
        try:
            # Create complex dependency graph
            connection_manager.execute_query("""
                IF OBJECT_ID('dbo.TestOrderItem', 'U') IS NOT NULL DROP TABLE dbo.TestOrderItem;
                IF OBJECT_ID('dbo.TestOrder', 'U') IS NOT NULL DROP TABLE dbo.TestOrder;
                IF OBJECT_ID('dbo.TestProduct', 'U') IS NOT NULL DROP TABLE dbo.TestProduct;
                IF OBJECT_ID('dbo.TestCustomer', 'U') IS NOT NULL DROP TABLE dbo.TestCustomer;
                
                CREATE TABLE dbo.TestCustomer (
                    CustomerID INT PRIMARY KEY,
                    CustomerName NVARCHAR(100)
                );
                
                CREATE TABLE dbo.TestProduct (
                    ProductID INT PRIMARY KEY,
                    ProductName NVARCHAR(100)
                );
                
                CREATE TABLE dbo.TestOrder (
                    OrderID INT PRIMARY KEY,
                    CustomerID INT NOT NULL,
                    CONSTRAINT FK_TestOrder_Customer FOREIGN KEY (CustomerID)
                        REFERENCES dbo.TestCustomer(CustomerID)
                );
                
                CREATE TABLE dbo.TestOrderItem (
                    OrderItemID INT PRIMARY KEY,
                    OrderID INT NOT NULL,
                    ProductID INT NOT NULL,
                    CONSTRAINT FK_TestOrderItem_Order FOREIGN KEY (OrderID)
                        REFERENCES dbo.TestOrder(OrderID),
                    CONSTRAINT FK_TestOrderItem_Product FOREIGN KEY (ProductID)
                        REFERENCES dbo.TestProduct(ProductID)
                );
            """)
            
            # Extract foreign keys
            fks = schema_extractor._get_foreign_keys()
            test_fks = [fk for fk in fks if fk["child_table"].startswith("Test")]
            
            # Create resolver
            resolver = DependencyResolver(test_fks)
            
            # No cycles
            assert not resolver.has_circular_dependencies()
            
            # Get processing order
            order = resolver.get_processing_order()
            
            # Find indices
            customer_idx = next((i for i, t in enumerate(order) if "TestCustomer" in t), None)
            product_idx = next((i for i, t in enumerate(order) if "TestProduct" in t), None)
            order_idx = next((i for i, t in enumerate(order) if "TestOrder" in t and "Item" not in t), None)
            item_idx = next((i for i, t in enumerate(order) if "TestOrderItem" in t), None)
            
            # Verify correct ordering
            assert customer_idx < order_idx  # Customer before Order
            assert product_idx < item_idx  # Product before OrderItem
            assert order_idx < item_idx  # Order before OrderItem
            
            # Check dependency depths
            summary = resolver.get_graph_summary()
            assert summary["max_dependency_depth"] >= 2  # At least 3 levels
            
        finally:
            connection_manager.execute_query("""
                IF OBJECT_ID('dbo.TestOrderItem', 'U') IS NOT NULL DROP TABLE dbo.TestOrderItem;
                IF OBJECT_ID('dbo.TestOrder', 'U') IS NOT NULL DROP TABLE dbo.TestOrder;
                IF OBJECT_ID('dbo.TestProduct', 'U') IS NOT NULL DROP TABLE dbo.TestProduct;
                IF OBJECT_ID('dbo.TestCustomer', 'U') IS NOT NULL DROP TABLE dbo.TestCustomer;
            """)
