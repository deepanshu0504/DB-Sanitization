"""
Foreign key dependency resolution for database sanitization.

This module analyzes foreign key relationships to determine the correct table
processing order for sanitization. It uses graph algorithms to detect circular
dependencies, handle self-referencing tables, and perform topological sorting
to ensure parent tables are always sanitized before child tables.

Key Features:
- Directed graph construction from foreign key metadata
- Cycle detection using networkx algorithms (Tarjan's algorithm)
- Topological sorting for dependency-aware processing order
- Self-referencing table identification
- Support for composite foreign keys
- Comprehensive logging with correlation IDs

Algorithm Complexity:
- Graph construction: O(E) where E is the number of foreign keys
- Cycle detection: O(V + E) where V is number of tables, E is foreign keys
- Topological sort: O(V + E)

Author: Database Sanitization Team
Date: 2026-03-26
"""

from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict

import networkx as nx

from ..exceptions import CircularDependencyError
from ..logging import get_logger


class DependencyResolver:
    """
    Resolves table dependencies from foreign key relationships.
    
    This class builds a directed graph of table dependencies and provides
    methods to analyze the graph, detect cycles, and determine processing order.
    
    The graph is directed: parent table → child table, meaning child depends on
    parent. Processing order is reverse topological: parents processed before children.
    
    Attributes:
        foreign_keys: List of foreign key metadata dictionaries
        graph: NetworkX DiGraph representing table dependencies
        self_referencing_tables: Set of tables with self-referencing FKs
        logger: Structured logger with correlation context
    
    Example:
        >>> fks = schema_extractor._get_foreign_keys()
        >>> resolver = DependencyResolver(fks)
        >>> if resolver.has_circular_dependencies():
        ...     cycles = resolver.get_cycles()
        ...     print(f"Found {len(cycles)} cycles")
        >>> else:
        ...     order = resolver.get_processing_order()
        ...     print(f"Process tables in order: {order}")
    """
    
    def __init__(self, foreign_keys: List[Dict[str, Any]]) -> None:
        """
        Initialize the dependency resolver with foreign key metadata.
        
        Args:
            foreign_keys: List of FK dictionaries from SchemaExtractor._get_foreign_keys()
                Each dict must contain:
                - parent_schema: Referenced table schema
                - parent_table: Referenced (parent) table name
                - child_schema: Referencing table schema
                - child_table: Referencing (child) table name
                - constraint_name: FK constraint name
                - parent_column: Referenced column
                - child_column: Referencing column
                - is_self_referencing: Boolean flag
                - ordinal_position: Position in composite FK (1-based)
        
        Raises:
            CircularDependencyError: If invalid FK metadata provided
        """
        self.foreign_keys = foreign_keys
        self.logger = get_logger(__name__).with_context(
            component="DependencyResolver"
        )
        
        # Initialize graph and metadata
        self.graph: nx.DiGraph = nx.DiGraph()
        self.self_referencing_tables: Set[str] = set()
        self._cycles: Optional[List[List[str]]] = None  # Cached cycle detection result
        self._processing_order: Optional[List[str]] = None  # Cached topological order
        
        # Build the dependency graph
        self._build_dependency_graph()
        self._identify_self_referencing_tables()
        
        # Log graph statistics
        self.logger.info(
            "Dependency graph constructed",
            tables=self.graph.number_of_nodes(),
            foreign_keys=self.graph.number_of_edges(),
            self_referencing=len(self.self_referencing_tables)
        )
    
    def _build_dependency_graph(self) -> None:
        """
        Build a directed graph from foreign key relationships.
        
        The graph is directed: parent → child (child depends on parent).
        For composite FKs, groups columns by constraint_name and creates
        a single edge with all column pairs as metadata.
        
        Nodes: Qualified table names [schema].[table]
        Edges: Parent → Child with metadata (constraint_name, columns, is_self_ref)
        
        Raises:
            CircularDependencyError: If FK metadata is invalid
        """
        # Group foreign keys by constraint to handle composite FKs
        fk_by_constraint: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        
        for fk in self.foreign_keys:
            constraint_name = fk.get("constraint_name", "")
            if not constraint_name:
                self.logger.warning(
                    "Foreign key missing constraint_name, using generated name",
                    parent=f"{fk.get('parent_schema')}.{fk.get('parent_table')}",
                    child=f"{fk.get('child_schema')}.{fk.get('child_table')}"
                )
                # Generate constraint name from parent/child
                constraint_name = (
                    f"FK_{fk.get('child_table')}_{fk.get('parent_table')}_"
                    f"{fk.get('child_column')}"
                )
            
            fk_by_constraint[constraint_name].append(fk)
        
        # Create graph edges (one per constraint, not per column)
        for constraint_name, fk_columns in fk_by_constraint.items():
            # Get first FK record to extract parent/child tables
            first_fk = fk_columns[0]
            
            parent_table = f"{first_fk['parent_schema']}.{first_fk['parent_table']}"
            child_table = f"{first_fk['child_schema']}.{first_fk['child_table']}"
            
            # Collect all column pairs for this constraint (composite FK support)
            column_pairs = [
                {
                    "parent_column": fk["parent_column"],
                    "child_column": fk["child_column"],
                    "ordinal_position": fk.get("ordinal_position", 1)
                }
                for fk in sorted(fk_columns, key=lambda x: x.get("ordinal_position", 1))
            ]
            
            # Add edge with metadata
            self.graph.add_edge(
                parent_table,
                child_table,
                constraint_name=constraint_name,
                columns=column_pairs,
                is_self_referencing=first_fk.get("is_self_referencing", False)
            )
            
            self.logger.debug(
                "Added dependency edge",
                parent=parent_table,
                child=child_table,
                constraint=constraint_name,
                column_count=len(column_pairs)
            )
    
    def _identify_self_referencing_tables(self) -> None:
        """
        Identify tables with self-referencing foreign keys.
        
        A self-referencing table has a foreign key where the child table
        is the same as the parent table (e.g., Employee.ManagerID → Employee.EmployeeID).
        
        These tables require special handling during sanitization:
        - Sort records within the table to process parents before children
        - OR temporarily disable the self-referencing FK
        
        Updates:
            self.self_referencing_tables: Set of qualified table names
        """
        for parent, child, data in self.graph.edges(data=True):
            if parent == child or data.get("is_self_referencing", False):
                self.self_referencing_tables.add(parent)
                self.logger.debug(
                    "Identified self-referencing table",
                    table=parent,
                    constraint=data.get("constraint_name", "unknown")
                )
    
    def _detect_cycles(self) -> List[List[str]]:
        """
        Detect circular dependencies in the dependency graph.
        
        Uses networkx's simple_cycles algorithm (Johnson's algorithm) to find
        all elementary cycles. Results are cached for performance.
        
        Complexity: O(V + E + C) where C is total number of cycles
        
        Returns:
            List of cycles, where each cycle is a list of table names
            forming a closed loop
        
        Example:
            [
                ["dbo.Order", "dbo.OrderItem", "dbo.Promotion"],
                ["dbo.Customer", "dbo.Address"]
            ]
        """
        if self._cycles is not None:
            return self._cycles
        
        try:
            # Find all simple cycles using Johnson's algorithm
            cycles = list(nx.simple_cycles(self.graph))
            
            # Filter out self-referencing "cycles" (single node loops)
            # These are handled separately via self_referencing_tables
            cycles = [cycle for cycle in cycles if len(cycle) > 1]
            
            self._cycles = cycles
            
            if cycles:
                self.logger.warning(
                    "Circular dependencies detected",
                    cycle_count=len(cycles),
                    cycles=cycles[:3]  # Log first 3 cycles
                )
            else:
                self.logger.debug("No circular dependencies detected")
            
            return cycles
        
        except Exception as e:
            self.logger.error(
                "Cycle detection failed",
                error=str(e),
                error_type=type(e).__name__
            )
            raise CircularDependencyError.invalid_dependency_graph(
                reason=f"Cycle detection algorithm failed: {str(e)}"
            ) from e
    
    def get_cycles(self) -> List[List[str]]:
        """
        Get all circular dependency cycles.
        
        Returns:
            List of cycles, where each cycle is a list of qualified table names
            
        Example:
            >>> resolver.get_cycles()
            [
                ["dbo.Order", "dbo.OrderItem", "dbo.Promotion", "dbo.Order"],
                ["dbo.Customer", "dbo.Address", "dbo.Customer"]
            ]
        """
        return self._detect_cycles()
    
    def has_circular_dependencies(self) -> bool:
        """
        Check if the dependency graph contains circular dependencies.
        
        Returns:
            True if cycles exist (excluding self-references), False otherwise
            
        Note:
            Self-referencing tables are NOT considered circular dependencies
            for this check. They are handled separately.
        """
        cycles = self._detect_cycles()
        return len(cycles) > 0
    
    def get_processing_order(self) -> List[str]:
        """
        Get the correct processing order for tables using topological sort.
        
        Returns tables in dependency order: parent tables before child tables.
        Orphaned tables (no FKs) are included at the end in arbitrary order.
        
        Complexity: O(V + E) using Kahn's algorithm
        
        Returns:
            List of qualified table names in processing order
            
        Raises:
            CircularDependencyError: If circular dependencies detected
            
        Example:
            >>> order = resolver.get_processing_order()
            ['dbo.Customer', 'dbo.Product', 'dbo.Order', 'dbo.OrderItem']
            # Process Customer and Product first (no dependencies),
            # then Order (depends on Customer), then OrderItem (depends on Order)
        """
        # Return cached result if available
        if self._processing_order is not None:
            return self._processing_order
        
        # Check for circular dependencies first
        cycles = self._detect_cycles()
        if cycles:
            raise CircularDependencyError.circular_dependency_detected(
                cycles=cycles
            )
        
        try:
            # Perform topological sort using Kahn's algorithm
            # Returns iterator, convert to list
            processing_order = list(nx.topological_sort(self.graph))
            
            self._processing_order = processing_order
            
            self.logger.info(
                "Processing order determined",
                table_count=len(processing_order),
                first_tables=processing_order[:3] if processing_order else [],
                last_tables=processing_order[-3:] if processing_order else []
            )
            
            return processing_order
        
        except nx.NetworkXError as e:
            # Should not happen if we checked for cycles first, but handle gracefully
            self.logger.error(
                "Topological sort failed",
                error=str(e),
                error_type=type(e).__name__
            )
            raise CircularDependencyError.invalid_dependency_graph(
                reason=f"Topological sort failed: {str(e)}"
            ) from e
    
    def get_dependencies(self, table: str) -> List[str]:
        """
        Get direct parent dependencies for a given table.
        
        Args:
            table: Qualified table name (e.g., "dbo.Orders")
            
        Returns:
            List of parent table names that this table depends on
            
        Example:
            >>> resolver.get_dependencies("dbo.OrderItem")
            ["dbo.Order", "dbo.Product"]
            # OrderItem depends on both Order and Product
        """
        if table not in self.graph:
            self.logger.warning(
                "Table not found in dependency graph",
                table=table
            )
            return []
        
        # Get predecessors (tables this table has FKs to)
        dependencies = list(self.graph.predecessors(table))
        
        self.logger.debug(
            "Retrieved dependencies",
            table=table,
            dependency_count=len(dependencies),
            dependencies=dependencies
        )
        
        return dependencies
    
    def is_self_referencing(self, table: str) -> bool:
        """
        Check if a table has self-referencing foreign keys.
        
        Args:
            table: Qualified table name (e.g., "dbo.Employee")
            
        Returns:
            True if table has self-referencing FK, False otherwise
            
        Example:
            >>> resolver.is_self_referencing("dbo.Employee")
            True  # Employee.ManagerID → Employee.EmployeeID
        """
        return table in self.self_referencing_tables
    
    def get_all_tables(self) -> List[str]:
        """
        Get all tables in the dependency graph.
        
        Returns:
            List of qualified table names (in arbitrary order)
        """
        return list(self.graph.nodes())
    
    def get_dependency_depth(self, table: str) -> int:
        """
        Get the dependency depth (level) of a table in the graph.
        
        Depth is the length of the longest path from a root node (no dependencies)
        to this table. Root nodes have depth 0.
        
        Args:
            table: Qualified table name
            
        Returns:
            Dependency depth (0 = no dependencies, higher = more levels)
            -1 if table not in graph
            
        Example:
            >>> resolver.get_dependency_depth("dbo.Customer")
            0  # No dependencies (root)
            >>> resolver.get_dependency_depth("dbo.Order")
            1  # Depends on Customer
            >>> resolver.get_dependency_depth("dbo.OrderItem")
            2  # Depends on Order, which depends on Customer
        """
        if table not in self.graph:
            return -1
        
        # Find all paths from root nodes to this table
        # Depth is the maximum path length
        max_depth = 0
        
        for node in self.graph.nodes():
            # Check if node is a root (no predecessors)
            if self.graph.in_degree(node) == 0:
                # Try to find path from root to target table
                if nx.has_path(self.graph, node, table):
                    try:
                        path_length = len(nx.shortest_path(self.graph, node, table)) - 1
                        max_depth = max(max_depth, path_length)
                    except nx.NetworkXNoPath:
                        continue
        
        return max_depth
    
    def get_graph_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the dependency graph for logging/debugging.
        
        Returns:
            Dictionary containing graph statistics and metadata
            
        Example:
            >>> summary = resolver.get_graph_summary()
            {
                "total_tables": 15,
                "total_foreign_keys": 22,
                "self_referencing_tables": 2,
                "circular_dependencies": 1,
                "cycles": [["dbo.Order", "dbo.Promotion"]],
                "root_tables": ["dbo.Customer", "dbo.Product"],
                "max_depth": 4
            }
        """
        # Find root tables (no dependencies)
        root_tables = [
            node for node in self.graph.nodes()
            if self.graph.in_degree(node) == 0
        ]
        
        # Find leaf tables (nothing depends on them)
        leaf_tables = [
            node for node in self.graph.nodes()
            if self.graph.out_degree(node) == 0
        ]
        
        # Calculate max depth
        max_depth = 0
        for table in self.graph.nodes():
            depth = self.get_dependency_depth(table)
            max_depth = max(max_depth, depth)
        
        cycles = self._detect_cycles()
        
        summary = {
            "total_tables": self.graph.number_of_nodes(),
            "total_foreign_keys": self.graph.number_of_edges(),
            "self_referencing_tables": len(self.self_referencing_tables),
            "self_referencing_list": list(self.self_referencing_tables),
            "circular_dependencies": len(cycles),
            "cycles": cycles,
            "root_tables": root_tables,
            "root_table_count": len(root_tables),
            "leaf_tables": leaf_tables,
            "leaf_table_count": len(leaf_tables),
            "max_dependency_depth": max_depth,
        }
        
        self.logger.info(
            "Generated dependency graph summary",
            **{k: v for k, v in summary.items() if k not in ["cycles", "self_referencing_list", "root_tables", "leaf_tables"]}
        )
        
        return summary
