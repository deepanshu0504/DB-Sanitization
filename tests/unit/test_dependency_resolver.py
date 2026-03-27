"""
Unit tests for DependencyResolver class.

These tests use mocked foreign key data to validate graph construction,
cycle detection, topological sorting, and self-referencing table identification.

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from typing import List, Dict, Any

from src.sanitization.dependency_resolver import DependencyResolver
from src.exceptions import CircularDependencyError


# ==================== Test Fixtures ====================


@pytest.fixture
def simple_fks() -> List[Dict[str, Any]]:
    """
    Simple linear dependency: Customer <- Order <- OrderItem.
    
    No circular dependencies, no self-references.
    Expected order: [Customer, Order, OrderItem]
    """
    return [
        {
            "constraint_name": "FK_Order_Customer",
            "parent_schema": "dbo",
            "parent_table": "Customer",
            "parent_column": "CustomerID",
            "child_schema": "dbo",
            "child_table": "Order",
            "child_column": "CustomerID",
            "is_self_referencing": False,
            "ordinal_position": 1
        },
        {
            "constraint_name": "FK_OrderItem_Order",
            "parent_schema": "dbo",
            "parent_table": "Order",
            "parent_column": "OrderID",
            "child_schema": "dbo",
            "child_table": "OrderItem",
            "child_column": "OrderID",
            "is_self_referencing": False,
            "ordinal_position": 1
        },
    ]


@pytest.fixture
def circular_fks() -> List[Dict[str, Any]]:
    """
    Circular dependency: Order -> OrderItem -> Promotion -> Order.
    
    Should detect one cycle with 3 tables.
    Should raise CircularDependencyError when getting processing order.
    """
    return [
        {
            "constraint_name": "FK_Order_Customer",
            "parent_schema": "dbo",
            "parent_table": "Customer",
            "parent_column": "CustomerID",
            "child_schema": "dbo",
            "child_table": "Order",
            "child_column": "CustomerID",
            "is_self_referencing": False,
            "ordinal_position": 1
        },
        {
            "constraint_name": "FK_OrderItem_Order",
            "parent_schema": "dbo",
            "parent_table": "Order",
            "parent_column": "OrderID",
            "child_schema": "dbo",
            "child_table": "OrderItem",
            "child_column": "OrderID",
            "is_self_referencing": False,
            "ordinal_position": 1
        },
        {
            "constraint_name": "FK_Promotion_OrderItem",
            "parent_schema": "dbo",
            "parent_table": "OrderItem",
            "parent_column": "OrderItemID",
            "child_schema": "dbo",
            "child_table": "Promotion",
            "child_column": "OrderItemID",
            "is_self_referencing": False,
            "ordinal_position": 1
        },
        {
            "constraint_name": "FK_Order_Promotion",
            "parent_schema": "dbo",
            "parent_table": "Promotion",
            "parent_column": "PromotionID",
            "child_schema": "dbo",
            "child_table": "Order",
            "child_column": "PromotionID",
            "is_self_referencing": False,
            "ordinal_position": 1
        },
    ]


@pytest.fixture
def self_referencing_fks() -> List[Dict[str, Any]]:
    """
    Self-referencing table: Employee.ManagerID -> Employee.EmployeeID.
    
    Should identify Employee as self-referencing.
    Should NOT count as circular dependency.
    Should allow topological sort.
    """
    return [
        {
            "constraint_name": "FK_Employee_Manager",
            "parent_schema": "dbo",
            "parent_table": "Employee",
            "parent_column": "EmployeeID",
            "child_schema": "dbo",
            "child_table": "Employee",
            "child_column": "ManagerID",
            "is_self_referencing": True,
            "ordinal_position": 1
        },
    ]


@pytest.fixture
def composite_pk_fks() -> List[Dict[str, Any]]:
    """
    Composite foreign key: OrderItem depends on both Order and Product.
    
    FK has 2 columns but should create only 1 edge in graph.
    """
    return [
        {
            "constraint_name": "FK_OrderItem_Order",
            "parent_schema": "dbo",
            "parent_table": "Order",
            "parent_column": "OrderID",
            "child_schema": "dbo",
            "child_table": "OrderItem",
            "child_column": "OrderID",
            "is_self_referencing": False,
            "ordinal_position": 1
        },
        {
            "constraint_name": "FK_OrderItem_Product",
            "parent_schema": "dbo",
            "parent_table": "Product",
            "parent_column": "ProductID",
            "child_schema": "dbo",
            "child_table": "OrderItem",
            "child_column": "ProductID",
            "is_self_referencing": False,
            "ordinal_position": 1
        },
    ]


@pytest.fixture
def multiple_independent_chains() -> List[Dict[str, Any]]:
    """
    Two independent chains: A -> B and C -> D.
    
    No cycles, no dependencies between chains.
    Expected order: [A, C, B, D] or [C, A, D, B] (either valid).
    """
    return [
        {
            "constraint_name": "FK_B_A",
            "parent_schema": "dbo",
            "parent_table": "A",
            "parent_column": "ID",
            "child_schema": "dbo",
            "child_table": "B",
            "child_column": "AID",
            "is_self_referencing": False,
            "ordinal_position": 1
        },
        {
            "constraint_name": "FK_D_C",
            "parent_schema": "dbo",
            "parent_table": "C",
            "parent_column": "ID",
            "child_schema": "dbo",
            "child_table": "D",
            "child_column": "CID",
            "is_self_referencing": False,
            "ordinal_position": 1
        },
    ]


@pytest.fixture
def orphaned_tables() -> List[Dict[str, Any]]:
    """
    Empty FK list - simulates tables with no foreign keys.
    
    Should create empty graph.
    Should return empty processing order.
    """
    return []


@pytest.fixture
def deep_dependency_chain() -> List[Dict[str, Any]]:
    """
    Deep 5-level chain: A -> B -> C -> D -> E.
    
    Expected depth: A=0, B=1, C=2, D=3, E=4.
    Expected order: [A, B, C, D, E].
    """
    return [
        {"constraint_name": "FK_B_A", "parent_schema": "dbo", "parent_table": "A",
         "parent_column": "ID", "child_schema": "dbo", "child_table": "B",
         "child_column": "AID", "is_self_referencing": False, "ordinal_position": 1},
        {"constraint_name": "FK_C_B", "parent_schema": "dbo", "parent_table": "B",
         "parent_column": "ID", "child_schema": "dbo", "child_table": "C",
         "child_column": "BID", "is_self_referencing": False, "ordinal_position": 1},
        {"constraint_name": "FK_D_C", "parent_schema": "dbo", "parent_table": "C",
         "parent_column": "ID", "child_schema": "dbo", "child_table": "D",
         "child_column": "CID", "is_self_referencing": False, "ordinal_position": 1},
        {"constraint_name": "FK_E_D", "parent_schema": "dbo", "parent_table": "D",
         "parent_column": "ID", "child_schema": "dbo", "child_table": "E",
         "child_column": "DID", "is_self_referencing": False, "ordinal_position": 1},
    ]


# ==================== Graph Construction Tests ====================


def test_simple_dependency_graph_construction(simple_fks):
    """Test basic graph construction with linear dependencies."""
    resolver = DependencyResolver(simple_fks)
    
    assert resolver.graph.number_of_nodes() == 3
    assert resolver.graph.number_of_edges() == 2
    
    # Verify nodes exist
    assert "dbo.Customer" in resolver.graph
    assert "dbo.Order" in resolver.graph
    assert "dbo.OrderItem" in resolver.graph


def test_composite_fk_creates_single_edge(composite_pk_fks):
    """Test that composite FKs create one edge per constraint."""
    resolver = DependencyResolver(composite_pk_fks)
    
    # 3 tables: Order, Product, OrderItem
    assert resolver.graph.number_of_nodes() == 3
    
    # 2 edges: Order -> OrderItem, Product -> OrderItem
    assert resolver.graph.number_of_edges() == 2
    
    # Verify edge metadata
    edge_data = resolver.graph.get_edge_data("dbo.Order", "dbo.OrderItem")
    assert edge_data is not None
    assert edge_data["constraint_name"] == "FK_OrderItem_Order"


def test_empty_fk_list_creates_empty_graph(orphaned_tables):
    """Test that empty FK list results in empty graph."""
    resolver = DependencyResolver(orphaned_tables)
    
    assert resolver.graph.number_of_nodes() == 0
    assert resolver.graph.number_of_edges() == 0
    assert len(resolver.self_referencing_tables) == 0


# ==================== Self-Referencing Detection Tests ====================


def test_self_referencing_table_detection(self_referencing_fks):
    """Test identification of self-referencing tables."""
    resolver = DependencyResolver(self_referencing_fks)
    
    # Should identify Employee as self-referencing
    assert "dbo.Employee" in resolver.self_referencing_tables
    assert resolver.is_self_referencing("dbo.Employee")
    
    # Graph should have 1 node and 1 self-loop edge
    assert resolver.graph.number_of_nodes() == 1
    assert resolver.graph.number_of_edges() == 1


def test_non_self_referencing_table(simple_fks):
    """Test that normal tables are not flagged as self-referencing."""
    resolver = DependencyResolver(simple_fks)
    
    assert not resolver.is_self_referencing("dbo.Customer")
    assert not resolver.is_self_referencing("dbo.Order")
    assert not resolver.is_self_referencing("dbo.OrderItem")
    assert len(resolver.self_referencing_tables) == 0


# ==================== Cycle Detection Tests ====================


def test_no_cycles_in_simple_graph(simple_fks):
    """Test that simple linear dependencies have no cycles."""
    resolver = DependencyResolver(simple_fks)
    
    assert not resolver.has_circular_dependencies()
    cycles = resolver.get_cycles()
    assert len(cycles) == 0


def test_circular_dependency_detection(circular_fks):
    """Test detection of circular FK dependencies."""
    resolver = DependencyResolver(circular_fks)
    
    assert resolver.has_circular_dependencies()
    cycles = resolver.get_cycles()
    
    # Should detect 1 cycle: Order -> OrderItem -> Promotion -> Order
    assert len(cycles) >= 1
    
    # Verify cycle contains expected tables
    cycle = cycles[0]
    assert "dbo.Order" in cycle
    assert "dbo.OrderItem" in cycle
    assert "dbo.Promotion" in cycle


def test_self_reference_not_counted_as_cycle(self_referencing_fks):
    """Test that self-referencing FKs are not counted as circular dependencies."""
    resolver = DependencyResolver(self_referencing_fks)
    
    # Self-references should NOT count as cycles
    assert not resolver.has_circular_dependencies()
    cycles = resolver.get_cycles()
    assert len(cycles) == 0


# ==================== Topological Sort Tests ====================


def test_simple_processing_order(simple_fks):
    """Test topological sort for simple linear dependencies."""
    resolver = DependencyResolver(simple_fks)
    
    order = resolver.get_processing_order()
    
    # Must process parents before children
    customer_idx = order.index("dbo.Customer")
    order_idx = order.index("dbo.Order")
    orderitem_idx = order.index("dbo.OrderItem")
    
    assert customer_idx < order_idx  # Customer before Order
    assert order_idx < orderitem_idx  # Order before OrderItem


def test_circular_dependency_raises_exception(circular_fks):
    """Test that circular dependencies raise exception on topological sort."""
    resolver = DependencyResolver(circular_fks)
    
    with pytest.raises(CircularDependencyError) as exc_info:
        resolver.get_processing_order()
    
    # Verify exception contains cycle information
    assert exc_info.value.error_code == "CIRCULAR_DEPENDENCY"
    assert "cycle" in exc_info.value.message.lower()
    assert "cycles" in exc_info.value.operation_context


def test_self_referencing_allows_topological_sort(self_referencing_fks):
    """Test that self-referencing tables can be topologically sorted."""
    resolver = DependencyResolver(self_referencing_fks)
    
    # Should not raise exception
    order = resolver.get_processing_order()
    
    # Employee should be in the order
    assert "dbo.Employee" in order


def test_multiple_independent_chains_ordering(multiple_independent_chains):
    """Test that independent chains can be processed in parallel."""
    resolver = DependencyResolver(multiple_independent_chains)
    
    order = resolver.get_processing_order()
    
    # Verify dependencies within each chain
    a_idx = order.index("dbo.A")
    b_idx = order.index("dbo.B")
    c_idx = order.index("dbo.C")
    d_idx = order.index("dbo.D")
    
    assert a_idx < b_idx  # A before B
    assert c_idx < d_idx  # C before D
    
    # No constraint between chains (A/C and B/D can be in any order)


def test_deep_dependency_chain_ordering(deep_dependency_chain):
    """Test correct ordering for deep dependency chains."""
    resolver = DependencyResolver(deep_dependency_chain)
    
    order = resolver.get_processing_order()
    
    # Verify strict ordering: A -> B -> C -> D -> E
    a_idx = order.index("dbo.A")
    b_idx = order.index("dbo.B")
    c_idx = order.index("dbo.C")
    d_idx = order.index("dbo.D")
    e_idx = order.index("dbo.E")
    
    assert a_idx < b_idx < c_idx < d_idx < e_idx


# ==================== Dependency Query Tests ====================


def test_get_dependencies(simple_fks):
    """Test retrieving direct dependencies for a table."""
    resolver = DependencyResolver(simple_fks)
    
    # Customer has no dependencies
    assert resolver.get_dependencies("dbo.Customer") == []
    
    # Order depends on Customer
    order_deps = resolver.get_dependencies("dbo.Order")
    assert "dbo.Customer" in order_deps
    assert len(order_deps) == 1
    
    # OrderItem depends on Order
    orderitem_deps = resolver.get_dependencies("dbo.OrderItem")
    assert "dbo.Order" in orderitem_deps
    assert len(orderitem_deps) == 1


def test_get_dependencies_composite_fk(composite_pk_fks):
    """Test dependencies for table with composite FK."""
    resolver = DependencyResolver(composite_pk_fks)
    
    # OrderItem depends on both Order and Product
    deps = resolver.get_dependencies("dbo.OrderItem")
    assert len(deps) == 2
    assert "dbo.Order" in deps
    assert "dbo.Product" in deps


def test_get_dependencies_nonexistent_table(simple_fks):
    """Test getting dependencies for table not in graph."""
    resolver = DependencyResolver(simple_fks)
    
    # Should return empty list for nonexistent table
    deps = resolver.get_dependencies("dbo.NonExistent")
    assert deps == []


# ==================== Depth Calculation Tests ====================


def test_dependency_depth_calculation(deep_dependency_chain):
    """Test calculation of dependency depth."""
    resolver = DependencyResolver(deep_dependency_chain)
    
    # Verify depths: A=0, B=1, C=2, D=3, E=4
    assert resolver.get_dependency_depth("dbo.A") == 0
    assert resolver.get_dependency_depth("dbo.B") == 1
    assert resolver.get_dependency_depth("dbo.C") == 2
    assert resolver.get_dependency_depth("dbo.D") == 3
    assert resolver.get_dependency_depth("dbo.E") == 4


def test_dependency_depth_nonexistent_table(simple_fks):
    """Test depth calculation for nonexistent table."""
    resolver = DependencyResolver(simple_fks)
    
    assert resolver.get_dependency_depth("dbo.NonExistent") == -1


# ==================== Graph Summary Tests ====================


def test_graph_summary_simple(simple_fks):
    """Test graph summary generation."""
    resolver = DependencyResolver(simple_fks)
    
    summary = resolver.get_graph_summary()
    
    assert summary["total_tables"] == 3
    assert summary["total_foreign_keys"] == 2
    assert summary["self_referencing_tables"] == 0
    assert summary["circular_dependencies"] == 0
    assert len(summary["root_tables"]) == 1  # Customer
    assert "dbo.Customer" in summary["root_tables"]
    assert len(summary["leaf_tables"]) == 1  # OrderItem
    assert "dbo.OrderItem" in summary["leaf_tables"]


def test_graph_summary_circular(circular_fks):
    """Test graph summary with circular dependencies."""
    resolver = DependencyResolver(circular_fks)
    
    summary = resolver.get_graph_summary()
    
    assert summary["circular_dependencies"] >= 1
    assert len(summary["cycles"]) >= 1


def test_graph_summary_self_referencing(self_referencing_fks):
    """Test graph summary with self-referencing table."""
    resolver = DependencyResolver(self_referencing_fks)
    
    summary = resolver.get_graph_summary()
    
    assert summary["self_referencing_tables"] == 1
    assert "dbo.Employee" in summary["self_referencing_list"]


# ==================== All Tables Query ====================


def test_get_all_tables(simple_fks):
    """Test retrieving all tables from graph."""
    resolver = DependencyResolver(simple_fks)
    
    all_tables = resolver.get_all_tables()
    
    assert len(all_tables) == 3
    assert "dbo.Customer" in all_tables
    assert "dbo.Order" in all_tables
    assert "dbo.OrderItem" in all_tables


# ==================== Edge Cases ====================


def test_missing_constraint_name():
    """Test handling of FKs with missing constraint names."""
    fks = [
        {
            # Missing constraint_name - should generate one
            "parent_schema": "dbo",
            "parent_table": "Parent",
            "parent_column": "ID",
            "child_schema": "dbo",
            "child_table": "Child",
            "child_column": "ParentID",
            "is_self_referencing": False,
            "ordinal_position": 1
        }
    ]
    
    # Should not raise exception - generates constraint name
    resolver = DependencyResolver(fks)
    
    assert resolver.graph.number_of_nodes() == 2
    assert resolver.graph.number_of_edges() == 1


def test_processing_order_caching():
    """Test that processing order is cached after first calculation."""
    resolver = DependencyResolver([
        {"constraint_name": "FK_B_A", "parent_schema": "dbo", "parent_table": "A",
         "parent_column": "ID", "child_schema": "dbo", "child_table": "B",
         "child_column": "AID", "is_self_referencing": False, "ordinal_position": 1}
    ])
    
    # First call
    order1 = resolver.get_processing_order()
    
    # Second call should return cached result
    order2 = resolver.get_processing_order()
    
    assert order1 == order2
    assert order1 is order2  # Same object (cached)


def test_cycles_caching():
    """Test that cycle detection results are cached."""
    fks = [
        {"constraint_name": "FK_B_A", "parent_schema": "dbo", "parent_table": "A",
         "parent_column": "ID", "child_schema": "dbo", "child_table": "B",
         "child_column": "AID", "is_self_referencing": False, "ordinal_position": 1},
        {"constraint_name": "FK_A_B", "parent_schema": "dbo", "parent_table": "B",
         "parent_column": "ID", "child_schema": "dbo", "child_table": "A",
         "child_column": "BID", "is_self_referencing": False, "ordinal_position": 1}
    ]
    
    resolver = DependencyResolver(fks)
    
    # First call
    cycles1 = resolver.get_cycles()
    
    # Second call should return cached result
    cycles2 = resolver.get_cycles()
    
    assert cycles1 == cycles2
    assert cycles1 is cycles2  # Same object (cached)
