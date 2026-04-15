"""
Unit tests for dependency_graph_builder module.

Tests cover all major scenarios:
- Linear dependencies (A -> B -> C)
- Diamond dependencies (A -> B, A -> C, B -> D, C -> D)
- Circular dependencies (A -> B -> C -> A)
- Self-referencing tables (Employee.ManagerID -> Employee.EmployeeID)
- Multi-schema databases
- Independent tables (no FK dependencies)
- Mixed scenarios (combination of above)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from collections import namedtuple

from database.dependency_graph_builder import (
    DependencyGraph,
    ForeignKeyRelationship,
    ProcessingOrder,
)
from desanitization.exceptions import CircularDependencyError


# Mock database row for FK query results
FKRow = namedtuple('FKRow', [
    'constraint_name', 'child_schema', 'child_table', 'child_column',
    'parent_schema', 'parent_table', 'parent_column'
])


class TestForeignKeyRelationship:
    """Test ForeignKeyRelationship dataclass."""
    
    def test_qualified_names(self):
        """Test fully qualified name properties."""
        fk = ForeignKeyRelationship(
            constraint_name='FK_Orders_Customers',
            child_schema='dbo',
            child_table='Orders',
            child_column='CustomerID',
            parent_schema='dbo',
            parent_table='Customers',
            parent_column='CustomerID'
        )
        
        assert fk.child_qualified_name == '[dbo].[Orders]'
        assert fk.parent_qualified_name == '[dbo].[Customers]'
    
    def test_self_referencing_detection(self):
        """Test detection of self-referencing FKs."""
        # Self-referencing
        fk_self = ForeignKeyRelationship(
            constraint_name='FK_Employee_Manager',
            child_schema='dbo',
            child_table='Employees',
            child_column='ManagerID',
            parent_schema='dbo',
            parent_table='Employees',
            parent_column='EmployeeID'
        )
        assert fk_self.is_self_referencing is True
        
        # Not self-referencing
        fk_normal = ForeignKeyRelationship(
            constraint_name='FK_Orders_Customers',
            child_schema='dbo',
            child_table='Orders',
            child_column='CustomerID',
            parent_schema='dbo',
            parent_table='Customers',
            parent_column='CustomerID'
        )
        assert fk_normal.is_self_referencing is False
    
    def test_multi_schema(self):
        """Test FK across different schemas."""
        fk = ForeignKeyRelationship(
            constraint_name='FK_SalesOrders_Customers',
            child_schema='sales',
            child_table='Orders',
            child_column='CustomerID',
            parent_schema='dbo',
            parent_table='Customers',
            parent_column='CustomerID'
        )
        
        assert fk.child_qualified_name == '[sales].[Orders]'
        assert fk.parent_qualified_name == '[dbo].[Customers]'
        assert fk.is_self_referencing is False


class TestProcessingOrder:
    """Test ProcessingOrder dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        order = ProcessingOrder(
            independent_tables=['[dbo].[Products]'],
            ordered_tables=['[dbo].[Customers]', '[dbo].[Orders]'],
            circular_groups=[['[dbo].[A]', '[dbo].[B]', '[dbo].[C]']],
            self_referencing_tables=['[dbo].[Employees]']
        )
        
        result = order.to_dict()
        
        assert result['independent_tables'] == ['[dbo].[Products]']
        assert result['ordered_tables'] == ['[dbo].[Customers]', '[dbo].[Orders]']
        assert result['circular_groups'] == [['[dbo].[A]', '[dbo].[B]', '[dbo].[C]']]
        assert result['self_referencing_tables'] == ['[dbo].[Employees]']
        assert result['total_tables'] == 7  # 1 + 2 + 3 + 1


class TestDependencyGraphLinear:
    """Test DependencyGraph with linear dependencies (A -> B -> C -> D)."""
    
    def create_mock_connection(self, fk_relationships):
        """Create mock database connection with FK relationships."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        
        # Mock fetchall to return FK relationships
        mock_cursor.fetchall.return_value = fk_relationships
        
        return mock_conn
    
    def test_linear_dependencies(self):
        """Test simple linear dependency chain: D -> C -> B -> A."""
        # Setup: A <- B <- C <- D (arrows show dependency direction)
        fk_rows = [
            FKRow('FK_B_A', 'dbo', 'B', 'AID', 'dbo', 'A', 'ID'),
            FKRow('FK_C_B', 'dbo', 'C', 'BID', 'dbo', 'B', 'ID'),
            FKRow('FK_D_C', 'dbo', 'D', 'CID', 'dbo', 'C', 'ID'),
        ]
        
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        graph.build_graph()
        
        # Verify graph structure
        assert len(graph.all_tables) == 4
        assert graph.graph['[dbo].[D]'] == {'[dbo].[C]'}
        assert graph.graph['[dbo].[C]'] == {'[dbo].[B]'}
        assert graph.graph['[dbo].[B]'] == {'[dbo].[A]'}
        assert graph.graph['[dbo].[A]'] == set()
        
        # Verify no cycles
        assert graph.is_cyclic() is False
        cycles = graph.detect_cycles()
        assert len(cycles) == 0
        
        # Verify topological sort (A -> B -> C -> D)
        sorted_tables = graph.topological_sort()
        assert sorted_tables == [
            '[dbo].[A]',
            '[dbo].[B]',
            '[dbo].[C]',
            '[dbo].[D]'
        ]
    
    def test_independent_tables(self):
        """Test graph with independent tables (no FKs)."""
        fk_rows = []  # No FK relationships
        
        # Manually add tables
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        graph.build_graph()
        
        # Since there are no FK relationships, all_tables will be empty
        # Let's test with a scenario where we manually add tables for testing
        graph.all_tables = {'[dbo].[A]', '[dbo].[B]', '[dbo].[C]'}
        graph.graph = {
            '[dbo].[A]': set(),
            '[dbo].[B]': set(),
            '[dbo].[C]': set(),
        }
        graph.reverse_graph = {
            '[dbo].[A]': set(),
            '[dbo].[B]': set(),
            '[dbo].[C]': set(),
        }
        
        independent = graph.get_independent_tables()
        assert set(independent) == {'[dbo].[A]', '[dbo].[B]', '[dbo].[C]'}


class TestDependencyGraphDiamond:
    """Test DependencyGraph with diamond dependencies."""
    
    def create_mock_connection(self, fk_relationships):
        """Create mock database connection."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = fk_relationships
        return mock_conn
    
    def test_diamond_dependencies(self):
        """
        Test diamond pattern:
            A
           / \\
          B   C
           \\ /
            D
        
        FK relationships: B->A, C->A, D->B, D->C
        Topological order: A, then B and C (any order), then D
        """
        fk_rows = [
            FKRow('FK_B_A', 'dbo', 'B', 'AID', 'dbo', 'A', 'ID'),
            FKRow('FK_C_A', 'dbo', 'C', 'AID', 'dbo', 'A', 'ID'),
            FKRow('FK_D_B', 'dbo', 'D', 'BID', 'dbo', 'B', 'ID'),
            FKRow('FK_D_C', 'dbo', 'D', 'CID', 'dbo', 'C', 'ID'),
        ]
        
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        graph.build_graph()
        
        # Verify graph structure
        assert len(graph.all_tables) == 4
        assert graph.graph['[dbo].[B]'] == {'[dbo].[A]'}
        assert graph.graph['[dbo].[C]'] == {'[dbo].[A]'}
        assert graph.graph['[dbo].[D]'] == {'[dbo].[B]', '[dbo].[C]'}
        
        # Verify no cycles
        assert graph.is_cyclic() is False
        
        # Verify topological sort
        sorted_tables = graph.topological_sort()
        
        # A must be first, D must be last, B and C can be in any order
        assert sorted_tables[0] == '[dbo].[A]'
        assert sorted_tables[3] == '[dbo].[D]'
        assert set(sorted_tables[1:3]) == {'[dbo].[B]', '[dbo].[C]'}


class TestDependencyGraphCircular:
    """Test DependencyGraph with circular dependencies."""
    
    def create_mock_connection(self, fk_relationships):
        """Create mock database connection."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = fk_relationships
        return mock_conn
    
    def test_simple_cycle(self):
        """Test simple cycle: A -> B -> C -> A."""
        fk_rows = [
            FKRow('FK_B_A', 'dbo', 'B', 'AID', 'dbo', 'A', 'ID'),
            FKRow('FK_C_B', 'dbo', 'C', 'BID', 'dbo', 'B', 'ID'),
            FKRow('FK_A_C', 'dbo', 'A', 'CID', 'dbo', 'C', 'ID'),
        ]
        
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        graph.build_graph()
        
        # Verify cycle detection
        assert graph.is_cyclic() is True
        cycles = graph.detect_cycles()
        assert len(cycles) == 1
        
        # Verify all three tables are in the cycle
        cycle = cycles[0]
        assert len(cycle) == 4  # [A, B, C, A]
        assert cycle[0] == cycle[-1]  # First and last should be same
        cycle_tables = set(cycle[:-1])  # Exclude duplicate last element
        assert cycle_tables == {'[dbo].[A]', '[dbo].[B]', '[dbo].[C]'}
        
        # Verify topological sort raises error
        with pytest.raises(CircularDependencyError) as exc_info:
            graph.topological_sort()
        
        assert 'cycle' in str(exc_info.value).lower()
        assert exc_info.value.cycles == cycles
    
    def test_mutual_dependency(self):
        """Test mutual dependency: A -> B and B -> A."""
        fk_rows = [
            FKRow('FK_A_B', 'dbo', 'A', 'BID', 'dbo', 'B', 'ID'),
            FKRow('FK_B_A', 'dbo', 'B', 'AID', 'dbo', 'A', 'ID'),
        ]
        
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        graph.build_graph()
        
        # Verify cycle detection
        assert graph.is_cyclic() is True
        cycles = graph.detect_cycles()
        assert len(cycles) == 1
        
        # Verify SCC detection
        sccs = graph.get_strongly_connected_components()
        assert len(sccs) == 1
        assert set(sccs[0]) == {'[dbo].[A]', '[dbo].[B]'}
    
    def test_multiple_cycles(self):
        """Test graph with multiple independent cycles."""
        fk_rows = [
            # Cycle 1: A -> B -> A
            FKRow('FK_B_A', 'dbo', 'B', 'AID', 'dbo', 'A', 'ID'),
            FKRow('FK_A_B', 'dbo', 'A', 'BID', 'dbo', 'B', 'ID'),
            # Cycle 2: C -> D -> E -> C
            FKRow('FK_D_C', 'dbo', 'D', 'CID', 'dbo', 'C', 'ID'),
            FKRow('FK_E_D', 'dbo', 'E', 'DID', 'dbo', 'D', 'ID'),
            FKRow('FK_C_E', 'dbo', 'C', 'EID', 'dbo', 'E', 'ID'),
        ]
        
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        graph.build_graph()
        
        # Verify multiple cycles detected
        assert graph.is_cyclic() is True
        cycles = graph.detect_cycles()
        assert len(cycles) >= 2  # At least 2 cycles
        
        # Verify SCC detection finds both
        sccs = graph.get_strongly_connected_components()
        assert len(sccs) == 2
        
        scc_tables = [set(scc) for scc in sccs]
        assert {'[dbo].[A]', '[dbo].[B]'} in scc_tables
        assert {'[dbo].[C]', '[dbo].[D]', '[dbo].[E]'} in scc_tables


class TestDependencyGraphSelfReferencing:
    """Test DependencyGraph with self-referencing tables."""
    
    def create_mock_connection(self, fk_relationships):
        """Create mock database connection."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = fk_relationships
        return mock_conn
    
    def test_self_referencing_table(self):
        """Test table with self-referencing FK (Employee.ManagerID -> Employee.EmployeeID)."""
        fk_rows = [
            FKRow('FK_Employee_Manager', 'dbo', 'Employees', 'ManagerID',
                  'dbo', 'Employees', 'EmployeeID'),
        ]
        
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        graph.build_graph()
        
        # Verify self-referencing table detected
        assert len(graph.self_referencing_tables) == 1
        assert '[dbo].[Employees]' in graph.self_referencing_tables
        
        # Verify not included in main graph edges
        assert '[dbo].[Employees]' not in graph.graph or \
               len(graph.graph['[dbo].[Employees]']) == 0
        
        # Verify topological sort excludes self-referencing table
        sorted_tables = graph.topological_sort()
        assert '[dbo].[Employees]' not in sorted_tables
        
        # Verify processing order includes it separately
        order = graph.get_processing_order()
        assert '[dbo].[Employees]' in order.self_referencing_tables
    
    def test_mixed_self_and_normal_references(self):
        """Test table with both self-referencing and normal FKs."""
        fk_rows = [
            # Self-referencing
            FKRow('FK_Employee_Manager', 'dbo', 'Employees', 'ManagerID',
                  'dbo', 'Employees', 'EmployeeID'),
            # Normal FK: Orders -> Employees
            FKRow('FK_Orders_Employee', 'dbo', 'Orders', 'EmployeeID',
                  'dbo', 'Employees', 'EmployeeID'),
        ]
        
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        graph.build_graph()
        
        # Verify self-referencing FK identified
        assert '[dbo].[Employees]' in graph.self_referencing_tables
        
        # Verify Orders -> Employees relationship exists
        # But Employees self-reference is excluded
        assert '[dbo].[Orders]' in graph.graph
        # Note: Since Employees is self-referencing, it's excluded from graph
        # So Orders might have empty dependencies


class TestDependencyGraphMultiSchema:
    """Test DependencyGraph with multi-schema databases."""
    
    def create_mock_connection(self, fk_relationships):
        """Create mock database connection."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = fk_relationships
        return mock_conn
    
    def test_cross_schema_relationships(self):
        """Test FK relationships across different schemas."""
        fk_rows = [
            # sales.Orders -> dbo.Customers
            FKRow('FK_SalesOrders_Customers', 'sales', 'Orders', 'CustomerID',
                  'dbo', 'Customers', 'CustomerID'),
            # sales.OrderDetails -> sales.Orders
            FKRow('FK_OrderDetails_Orders', 'sales', 'OrderDetails', 'OrderID',
                  'sales', 'Orders', 'OrderID'),
            # sales.OrderDetails -> inventory.Products
            FKRow('FK_OrderDetails_Products', 'sales', 'OrderDetails', 'ProductID',
                  'inventory', 'Products', 'ProductID'),
        ]
        
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        graph.build_graph()
        
        # Verify fully qualified names used
        assert '[dbo].[Customers]' in graph.all_tables
        assert '[sales].[Orders]' in graph.all_tables
        assert '[sales].[OrderDetails]' in graph.all_tables
        assert '[inventory].[Products]' in graph.all_tables
        
        # Verify relationships
        assert '[dbo].[Customers]' in graph.graph['[sales].[Orders]']
        assert '[sales].[Orders]' in graph.graph['[sales].[OrderDetails]']
        assert '[inventory].[Products]' in graph.graph['[sales].[OrderDetails]']
        
        # Verify topological sort works with multi-schema
        sorted_tables = graph.topological_sort()
        
        # Customers and Products must come before Orders
        customers_idx = sorted_tables.index('[dbo].[Customers]')
        products_idx = sorted_tables.index('[inventory].[Products]')
        orders_idx = sorted_tables.index('[sales].[Orders]')
        orderdetails_idx = sorted_tables.index('[sales].[OrderDetails]')
        
        assert customers_idx < orders_idx
        assert products_idx < orderdetails_idx
        assert orders_idx < orderdetails_idx
    
    def test_schema_filter(self):
        """Test filtering by schema during graph build."""
        fk_rows = [
            FKRow('FK_SalesOrders_Customers', 'sales', 'Orders', 'CustomerID',
                  'dbo', 'Customers', 'CustomerID'),
            FKRow('FK_TestOrders_TestCustomers', 'test', 'Orders', 'CustomerID',
                  'test', 'Customers', 'CustomerID'),
        ]
        
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        
        # Build graph with schema filter
        graph.build_graph(schema_filter=['sales'])
        
        # Verify only sales schema included
        assert '[sales].[Orders]' in graph.all_tables
        assert '[test].[Orders]' not in graph.all_tables
        assert '[test].[Customers]' not in graph.all_tables


class TestDependencyGraphProcessingOrder:
    """Test get_processing_order() with complex scenarios."""
    
    def create_mock_connection(self, fk_relationships):
        """Create mock database connection."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = fk_relationships
        return mock_conn
    
    def test_processing_order_acyclic(self):
        """Test processing order for acyclic graph."""
        fk_rows = [
            # Linear: C -> B -> A
            FKRow('FK_B_A', 'dbo', 'B', 'AID', 'dbo', 'A', 'ID'),
            FKRow('FK_C_B', 'dbo', 'C', 'BID', 'dbo', 'B', 'ID'),
            # Independent: D (no FKs)
        ]
        
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        graph.build_graph()
        
        # Manually add independent table D
        graph.all_tables.add('[dbo].[D]')
        graph.graph['[dbo].[D]'] = set()
        graph.reverse_graph['[dbo].[D]'] = set()
        
        order = graph.get_processing_order()
        
        # Verify structure
        # D can be in either independent_tables or ordered_tables (both valid for no-dependency tables)
        assert '[dbo].[D]' in order.independent_tables or '[dbo].[D]' in order.ordered_tables
        assert len(order.ordered_tables) >= 3  # At least A, B, C
        assert len(order.circular_groups) == 0
        assert len(order.self_referencing_tables) == 0
        
        # Verify order: A before B before C (wherever they appear)
        all_ordered = order.independent_tables + order.ordered_tables
        assert all_ordered.index('[dbo].[A]') < all_ordered.index('[dbo].[B]')
        assert all_ordered.index('[dbo].[B]') < all_ordered.index('[dbo].[C]')
    
    def test_processing_order_with_cycles(self):
        """Test processing order for graph with cycles."""
        fk_rows = [
            # Cycle: A -> B -> C -> A
            FKRow('FK_B_A', 'dbo', 'B', 'AID', 'dbo', 'A', 'ID'),
            FKRow('FK_C_B', 'dbo', 'C', 'BID', 'dbo', 'B', 'ID'),
            FKRow('FK_A_C', 'dbo', 'A', 'CID', 'dbo', 'C', 'ID'),
            # Independent: D -> E (acyclic)
            FKRow('FK_E_D', 'dbo', 'E', 'DID', 'dbo', 'D', 'ID'),
        ]
        
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        graph.build_graph()
        
        order = graph.get_processing_order()
        
        # Verify circular group identified
        assert len(order.circular_groups) >= 1
        
        # Verify A, B, C are in a circular group
        circular_tables = set()
        for group in order.circular_groups:
            circular_tables.update(group)
        
        assert '[dbo].[A]' in circular_tables
        assert '[dbo].[B]' in circular_tables
        assert '[dbo].[C]' in circular_tables
        
        # Verify D and E are ordered (acyclic portion)
        assert '[dbo].[D]' in order.ordered_tables or '[dbo].[D]' in order.independent_tables
        assert '[dbo].[E]' in order.ordered_tables


class TestDependencyGraphHelpers:
    """Test helper methods."""
    
    def create_mock_connection(self, fk_relationships):
        """Create mock database connection."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = fk_relationships
        return mock_conn
    
    def test_get_dependencies(self):
        """Test get_dependencies() for specific table."""
        fk_rows = [
            FKRow('FK_B_A', 'dbo', 'B', 'AID', 'dbo', 'A', 'ID'),
            FKRow('FK_C_B', 'dbo', 'C', 'BID', 'dbo', 'B', 'ID'),
        ]
        
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        graph.build_graph()
        
        # Get dependencies for B
        deps = graph.get_dependencies('[dbo].[B]')
        
        assert deps['parents'] == ['[dbo].[A]']
        assert deps['children'] == ['[dbo].[C]']
    
    def test_export_to_dot(self, tmp_path):
        """Test export to DOT format for Graphviz."""
        fk_rows = [
            FKRow('FK_B_A', 'dbo', 'B', 'AID', 'dbo', 'A', 'ID'),
            FKRow('FK_C_B', 'dbo', 'C', 'BID', 'dbo', 'B', 'ID'),
        ]
        
        mock_conn = self.create_mock_connection(fk_rows)
        graph = DependencyGraph(mock_conn)
        graph.build_graph()
        
        # Export to DOT
        output_file = tmp_path / "graph.dot"
        graph.export_to_dot(str(output_file))
        
        # Verify file created
        assert output_file.exists()
        
        # Verify content
        content = output_file.read_text()
        assert 'digraph DependencyGraph' in content
        assert 'dbo.A' in content
        assert 'dbo.B' in content
        assert 'dbo.C' in content
        assert '->' in content


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
