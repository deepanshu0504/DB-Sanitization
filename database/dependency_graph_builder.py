"""
Foreign key dependency graph builder for safe table processing order.

This module extracts foreign key relationships from the database schema and
builds a directed dependency graph. It provides algorithms for cycle detection,
topological sorting, and strongly connected component analysis to enable
safe table restoration order during desanitization operations.

Key Features:
    - FK relationship extraction from SQL Server system tables
    - Cycle detection using Depth-First Search (DFS)
    - Topological sorting using Kahn's algorithm
    - Strongly Connected Components (SCC) using Tarjan's algorithm
    - Multi-schema database support with fully qualified names

Usage:
    >>> from database.dependency_graph_builder import DependencyGraph
    >>> graph = DependencyGraph(connection)
    >>> graph.build_graph()
    >>> if not graph.is_cyclic():
    ...     order = graph.topological_sort()
    >>> else:
    ...     processing_order = graph.get_processing_order()
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple, Optional, Any
from collections import defaultdict, deque

from desanitization.exceptions import CircularDependencyError


@dataclass
class ForeignKeyRelationship:
    """
    Represents a foreign key relationship between two tables.
    
    Attributes:
        constraint_name: Name of the FK constraint
        child_schema: Schema containing the child (referencing) table
        child_table: Name of the child table
        child_column: Column in the child table
        parent_schema: Schema containing the parent (referenced) table
        parent_table: Name of the parent table
        parent_column: Column in the parent table
    """
    constraint_name: str
    child_schema: str
    child_table: str
    child_column: str
    parent_schema: str
    parent_table: str
    parent_column: str
    
    @property
    def child_qualified_name(self) -> str:
        """Return fully qualified name of child table."""
        return f"[{self.child_schema}].[{self.child_table}]"
    
    @property
    def parent_qualified_name(self) -> str:
        """Return fully qualified name of parent table."""
        return f"[{self.parent_schema}].[{self.parent_table}]"
    
    @property
    def is_self_referencing(self) -> bool:
        """Check if this FK is self-referencing (same table)."""
        return (self.child_schema == self.parent_schema and 
                self.child_table == self.parent_table)


@dataclass
class ProcessingOrder:
    """
    Represents the recommended processing order for tables based on dependencies.
    
    Attributes:
        independent_tables: Tables with no FK dependencies (can process in parallel)
        ordered_tables: Tables in topological order (parent before child)
        circular_groups: Groups of tables with circular dependencies (require special handling)
        self_referencing_tables: Tables with self-referencing FKs
    """
    independent_tables: List[str] = field(default_factory=list)
    ordered_tables: List[str] = field(default_factory=list)
    circular_groups: List[List[str]] = field(default_factory=list)
    self_referencing_tables: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "independent_tables": self.independent_tables,
            "ordered_tables": self.ordered_tables,
            "circular_groups": self.circular_groups,
            "self_referencing_tables": self.self_referencing_tables,
            "total_tables": (
                len(self.independent_tables) + 
                len(self.ordered_tables) + 
                sum(len(group) for group in self.circular_groups) +
                len(self.self_referencing_tables)
            )
        }


class DependencyGraph:
    """
    Builds and analyzes foreign key dependency graphs for database tables.
    
    This class extracts FK relationships from SQL Server system tables and
    provides algorithms for safe table processing order during desanitization.
    
    Attributes:
        connection: Active database connection (pyodbc)
        logger: Logger instance for debugging
        relationships: List of all FK relationships
        graph: Adjacency list (child -> [parents])
        reverse_graph: Reverse adjacency list (parent -> [children])
        all_tables: Set of all table names in the graph
    """
    
    def __init__(self, connection, logger: Optional[logging.Logger] = None):
        """
        Initialize dependency graph builder.
        
        Args:
            connection: Active pyodbc connection
            logger: Optional logger instance
        """
        self.connection = connection
        self.logger = logger or logging.getLogger(__name__)
        
        # Graph data structures
        self.relationships: List[ForeignKeyRelationship] = []
        self.graph: Dict[str, Set[str]] = defaultdict(set)
        self.reverse_graph: Dict[str, Set[str]] = defaultdict(set)
        self.all_tables: Set[str] = set()
        self.self_referencing_tables: Set[str] = set()
        
        # Cache for computed values
        self._cycles_cache: Optional[List[List[str]]] = None
        self._scc_cache: Optional[List[List[str]]] = None
    
    def extract_foreign_key_relationships(
        self, 
        schema_filter: Optional[List[str]] = None
    ) -> List[ForeignKeyRelationship]:
        """
        Extract all FK relationships from database system tables.
        
        This method queries sys.foreign_keys and sys.foreign_key_columns to
        build a complete list of FK relationships. Reuses the pattern from
        desanitization_engine._validate_referential_integrity().
        
        Args:
            schema_filter: Optional list of schema names to include (None = all schemas)
        
        Returns:
            List of ForeignKeyRelationship objects
        """
        self.logger.info("Extracting foreign key relationships from database...")
        
        cursor = self.connection.cursor()
        
        # Query FK relationships from system tables
        query = """
            SELECT 
                fk.name AS constraint_name,
                OBJECT_SCHEMA_NAME(fk.parent_object_id) AS child_schema,
                OBJECT_NAME(fk.parent_object_id) AS child_table,
                COL_NAME(fc.parent_object_id, fc.parent_column_id) AS child_column,
                OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS parent_schema,
                OBJECT_NAME(fk.referenced_object_id) AS parent_table,
                COL_NAME(fc.referenced_object_id, fc.referenced_column_id) AS parent_column
            FROM sys.foreign_keys AS fk
            INNER JOIN sys.foreign_key_columns AS fc 
                ON fk.object_id = fc.constraint_object_id
            ORDER BY fk.name, fc.constraint_column_id
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        relationships = []
        for row in rows:
            # Apply schema filter if specified
            if schema_filter and row.child_schema not in schema_filter:
                continue
            
            fk = ForeignKeyRelationship(
                constraint_name=row.constraint_name,
                child_schema=row.child_schema,
                child_table=row.child_table,
                child_column=row.child_column,
                parent_schema=row.parent_schema,
                parent_table=row.parent_table,
                parent_column=row.parent_column
            )
            relationships.append(fk)
        
        self.logger.info(
            f"Extracted {len(relationships)} FK relationships from {len(set(fk.child_qualified_name for fk in relationships))} tables"
        )
        
        return relationships
    
    def build_graph(self, schema_filter: Optional[List[str]] = None) -> None:
        """
        Build dependency graph from FK relationships.
        
        Constructs adjacency list representation where edges point from child
        tables to their parent tables (dependency direction).
        
        Args:
            schema_filter: Optional list of schema names to include
        """
        self.logger.info("Building dependency graph...")
        
        # Extract relationships
        self.relationships = self.extract_foreign_key_relationships(schema_filter)
        
        # Reset graph structures
        self.graph.clear()
        self.reverse_graph.clear()
        self.all_tables.clear()
        self.self_referencing_tables.clear()
        self._cycles_cache = None
        self._scc_cache = None
        
        # Build adjacency lists
        for fk in self.relationships:
            child = fk.child_qualified_name
            parent = fk.parent_qualified_name
            
            # Track all tables
            self.all_tables.add(child)
            self.all_tables.add(parent)
            
            # Handle self-referencing FKs separately
            if fk.is_self_referencing:
                self.self_referencing_tables.add(child)
                self.logger.debug(f"Self-referencing FK detected: {child}")
                continue
            
            # Build graph: child depends on parent
            self.graph[child].add(parent)
            self.reverse_graph[parent].add(child)
        
        # Ensure all tables are in graph (even those with no dependencies)
        for table in self.all_tables:
            if table not in self.graph:
                self.graph[table] = set()
            if table not in self.reverse_graph:
                self.reverse_graph[table] = set()
        
        self.logger.info(
            f"Graph built: {len(self.all_tables)} tables, "
            f"{len(self.relationships)} relationships, "
            f"{len(self.self_referencing_tables)} self-referencing"
        )
    
    def detect_cycles(self) -> List[List[str]]:
        """
        Detect circular dependencies using Depth-First Search (DFS).
        
        This implements a DFS-based cycle detection algorithm with path tracking
        to identify and return all cycles in the dependency graph.
        
        Returns:
            List of cycles, where each cycle is a list of table names forming a loop.
            Example: [['[dbo].[A]', '[dbo].[B]', '[dbo].[C]', '[dbo].[A]']]
        """
        if self._cycles_cache is not None:
            return self._cycles_cache
        
        self.logger.debug("Detecting cycles in dependency graph...")
        
        cycles = []
        visited = set()
        rec_stack = set()  # Recursion stack for current DFS path
        path = []  # Current path for cycle reconstruction
        
        def dfs(node: str) -> None:
            """DFS helper to detect cycles."""
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in self.graph[node]:
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    # Found a cycle - extract it from path
                    cycle_start_idx = path.index(neighbor)
                    cycle = path[cycle_start_idx:] + [neighbor]
                    
                    # Normalize cycle (rotate to start with lexicographically smallest)
                    min_idx = cycle.index(min(cycle[:-1]))  # Exclude last duplicate
                    normalized_cycle = cycle[min_idx:-1] + cycle[:min_idx] + [cycle[min_idx]]
                    
                    # Check if this cycle already exists
                    if normalized_cycle not in cycles:
                        cycles.append(normalized_cycle)
                        self.logger.debug(f"Cycle detected: {' → '.join(normalized_cycle)}")
            
            path.pop()
            rec_stack.remove(node)
        
        # Run DFS from each unvisited node
        for table in self.all_tables:
            if table not in visited and table not in self.self_referencing_tables:
                dfs(table)
        
        self._cycles_cache = cycles
        
        if cycles:
            self.logger.info(f"Found {len(cycles)} circular dependency cycle(s)")
        else:
            self.logger.info("No circular dependencies detected")
        
        return cycles
    
    def is_cyclic(self) -> bool:
        """
        Check if graph contains any cycles.
        
        Returns:
            True if circular dependencies exist, False otherwise
        """
        cycles = self.detect_cycles()
        return len(cycles) > 0
    
    def topological_sort(self) -> List[str]:
        """
        Perform topological sort using Kahn's algorithm.
        
        Returns tables in dependency order (parent tables before child tables).
        This is the safe restoration order for desanitization.
        
        Raises:
            CircularDependencyError: If the graph contains cycles
        
        Returns:
            List of table names in topological order
        """
        self.logger.debug("Performing topological sort (Kahn's algorithm)...")
        
        # Check for cycles first
        cycles = self.detect_cycles()
        if cycles:
            raise CircularDependencyError(
                f"Cannot perform topological sort: graph contains {len(cycles)} cycle(s)",
                cycles=cycles
            )
        
        # Calculate in-degree for each node (excluding self-referencing tables)
        in_degree = {}
        tables_to_sort = self.all_tables - self.self_referencing_tables
        
        for table in tables_to_sort:
            in_degree[table] = len(self.graph[table])
        
        # Initialize queue with nodes having in-degree 0 (no dependencies)
        queue = deque([table for table in tables_to_sort if in_degree[table] == 0])
        sorted_order = []
        
        while queue:
            # Process node with no dependencies
            current = queue.popleft()
            sorted_order.append(current)
            
            # Reduce in-degree for all children
            for child in self.reverse_graph[current]:
                if child in in_degree:  # Skip self-referencing tables
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        queue.append(child)
        
        # Verify all tables were processed
        if len(sorted_order) != len(tables_to_sort):
            remaining = tables_to_sort - set(sorted_order)
            self.logger.error(f"Topological sort incomplete: {len(remaining)} tables unprocessed")
            raise CircularDependencyError(
                f"Topological sort failed: {len(remaining)} tables have unresolved dependencies"
            )
        
        self.logger.info(f"Topological sort complete: {len(sorted_order)} tables ordered")
        return sorted_order
    
    def get_strongly_connected_components(self) -> List[List[str]]:
        """
        Find strongly connected components (SCCs) using Tarjan's algorithm.
        
        SCCs represent groups of tables with circular dependencies that must
        be processed together (with constraints temporarily disabled).
        
        Returns:
            List of SCCs, where each SCC is a list of mutually dependent tables
        """
        if self._scc_cache is not None:
            return self._scc_cache
        
        self.logger.debug("Computing strongly connected components (Tarjan's algorithm)...")
        
        # Tarjan's algorithm state
        index_counter = [0]
        stack = []
        lowlink = {}
        index = {}
        on_stack = set()
        sccs = []
        
        def strongconnect(node: str) -> None:
            """Tarjan's algorithm recursive helper."""
            # Set depth index for this node
            index[node] = index_counter[0]
            lowlink[node] = index_counter[0]
            index_counter[0] += 1
            stack.append(node)
            on_stack.add(node)
            
            # Consider successors
            for neighbor in self.graph[node]:
                if neighbor not in index:
                    # Successor not yet visited; recurse
                    strongconnect(neighbor)
                    lowlink[node] = min(lowlink[node], lowlink[neighbor])
                elif neighbor in on_stack:
                    # Successor is on stack and hence in current SCC
                    lowlink[node] = min(lowlink[node], index[neighbor])
            
            # If node is a root node, pop the stack to create an SCC
            if lowlink[node] == index[node]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack.remove(w)
                    scc.append(w)
                    if w == node:
                        break
                
                # Only include SCCs with more than one table (actual cycles)
                if len(scc) > 1:
                    sccs.append(sorted(scc))  # Sort for deterministic output
                    self.logger.debug(f"SCC found: {scc}")
        
        # Run algorithm for each unvisited node (excluding self-referencing)
        tables_to_process = self.all_tables - self.self_referencing_tables
        for table in tables_to_process:
            if table not in index:
                strongconnect(table)
        
        self._scc_cache = sccs
        
        if sccs:
            self.logger.info(f"Found {len(sccs)} strongly connected component(s)")
        else:
            self.logger.info("No strongly connected components (graph is acyclic)")
        
        return sccs
    
    def get_independent_tables(self) -> List[str]:
        """
        Get tables with no foreign key dependencies.
        
        These tables can be processed in parallel during desanitization.
        
        Returns:
            List of table names with no FK dependencies
        """
        independent = []
        for table in self.all_tables:
            # Table is independent if it has no parents and no children
            # (excluding self-referencing tables which are handled separately)
            if (table not in self.self_referencing_tables and
                len(self.graph[table]) == 0 and
                len(self.reverse_graph[table]) == 0):
                independent.append(table)
        
        self.logger.debug(f"Found {len(independent)} independent table(s)")
        return sorted(independent)
    
    def get_processing_order(self) -> ProcessingOrder:
        """
        Get comprehensive processing order for all tables.
        
        This is the high-level method that combines all analysis to provide
        a complete processing strategy for database-level desanitization.
        
        Returns:
            ProcessingOrder with categorized tables:
                - independent_tables: No dependencies (can parallelize)
                - ordered_tables: Topological order for acyclic portion
                - circular_groups: SCCs requiring constraint handling
                - self_referencing_tables: Tables with self-FKs
        """
        self.logger.info("Computing complete processing order...")
        
        # Get independent tables
        independent = self.get_independent_tables()
        
        # Get self-referencing tables
        self_ref = sorted(list(self.self_referencing_tables))
        
        # Try topological sort for acyclic portion
        try:
            ordered = self.topological_sort()
            circular = []
        except CircularDependencyError:
            # Graph has cycles - use SCCs
            sccs = self.get_strongly_connected_components()
            circular = sccs
            
            # For ordered tables, get tables not in any SCC
            tables_in_sccs = set()
            for scc in sccs:
                tables_in_sccs.update(scc)
            
            # Build subgraph excluding SCC tables
            remaining_tables = (self.all_tables - 
                              self.self_referencing_tables - 
                              tables_in_sccs - 
                              set(independent))
            
            # Try topological sort on remaining acyclic portion
            if remaining_tables:
                # Build temporary subgraph
                temp_graph = {}
                for table in remaining_tables:
                    temp_graph[table] = self.graph[table] & remaining_tables
                
                # Simple topological sort on subgraph
                in_degree = {t: len(temp_graph[t]) for t in remaining_tables}
                queue = deque([t for t in remaining_tables if in_degree[t] == 0])
                ordered = []
                
                while queue:
                    current = queue.popleft()
                    ordered.append(current)
                    for child in self.reverse_graph[current]:
                        if child in in_degree:
                            in_degree[child] -= 1
                            if in_degree[child] == 0:
                                queue.append(child)
            else:
                ordered = []
        
        processing_order = ProcessingOrder(
            independent_tables=independent,
            ordered_tables=ordered,
            circular_groups=circular,
            self_referencing_tables=self_ref
        )
        
        self.logger.info(
            f"Processing order computed: "
            f"{len(independent)} independent, "
            f"{len(ordered)} ordered, "
            f"{len(circular)} circular groups, "
            f"{len(self_ref)} self-referencing"
        )
        
        return processing_order
    
    def get_dependencies(self, table: str) -> Dict[str, List[str]]:
        """
        Get dependencies for a specific table.
        
        Args:
            table: Fully qualified table name
        
        Returns:
            Dictionary with 'parents' and 'children' lists
        """
        return {
            "parents": sorted(list(self.graph.get(table, set()))),
            "children": sorted(list(self.reverse_graph.get(table, set())))
        }
    
    def export_to_dot(self, output_file: str) -> None:
        """
        Export graph to DOT format for visualization with Graphviz.
        
        Args:
            output_file: Path to output .dot file
        """
        self.logger.info(f"Exporting dependency graph to {output_file}...")
        
        with open(output_file, 'w') as f:
            f.write("digraph DependencyGraph {\n")
            f.write("    rankdir=LR;\n")
            f.write("    node [shape=box];\n\n")
            
            # Add nodes
            for table in self.all_tables:
                label = table.replace('[', '').replace(']', '')
                color = "red" if table in self.self_referencing_tables else "black"
                f.write(f'    "{label}" [color={color}];\n')
            
            f.write("\n")
            
            # Add edges
            for child, parents in self.graph.items():
                child_label = child.replace('[', '').replace(']', '')
                for parent in parents:
                    parent_label = parent.replace('[', '').replace(']', '')
                    f.write(f'    "{child_label}" -> "{parent_label}";\n')
            
            f.write("}\n")
        
        self.logger.info(f"Graph exported to {output_file}")
