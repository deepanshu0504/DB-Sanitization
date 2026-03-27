"""
Example: Foreign Key Dependency Resolution

This example demonstrates how to use the DependencyResolver to analyze
foreign key relationships and determine the correct table processing order
for database sanitization.

The example covers:
- Basic dependency resolution for simple hierarchies
- Handling circular dependencies
- Identifying self-referencing tables
- Getting processing order for sanitization

Author: Database Sanitization Team
Date: 2026-03-26
"""

from src.config import ConfigLoader
from src.database import DatabaseConnectionManager, SchemaExtractor
from src.sanitization import DependencyResolver
from src.exceptions import CircularDependencyError
from src.logging import get_logger, CorrelationContext


def main():
    """Demonstrate dependency resolution workflow."""
    logger = get_logger(__name__)
    
    # Step 1: Load configuration
    logger.info("Loading configuration...")
    config = ConfigLoader.load_from_file("config/pii_config.example.json")
    
    with CorrelationContext():
        try:
            # Step 2: Connect to database
            logger.info("Connecting to database...", server=config.database.server)
            connection_manager = DatabaseConnectionManager(config.database)
            
            # Step 3: Extract schema metadata
            logger.info("Extracting schema metadata...")
            schema_extractor = SchemaExtractor(connection_manager)
            
            # Get foreign key relationships
            foreign_keys = schema_extractor._get_foreign_keys()
            logger.info("Extracted foreign keys", fk_count=len(foreign_keys))
            
            # Step 4: Build dependency graph
            logger.info("Building dependency graph...")
            resolver = DependencyResolver(foreign_keys)
            
            # Step 5: Analyze the graph
            logger.info("=" * 60)
            logger.info("DEPENDENCY GRAPH ANALYSIS")
            logger.info("=" * 60)
            
            # Get graph summary
            summary = resolver.get_graph_summary()
            print(f"\nGraph Statistics:")
            print(f"  Total tables: {summary['total_tables']}")
            print(f"  Total foreign keys: {summary['total_foreign_keys']}")
            print(f"  Self-referencing tables: {summary['self_referencing_tables']}")
            print(f"  Circular dependencies: {summary['circular_dependencies']}")
            print(f"  Max dependency depth: {summary['max_dependency_depth']}")
            
            # List root tables (no dependencies)
            if summary['root_tables']:
                print(f"\nRoot Tables (no dependencies):")
                for table in summary['root_tables']:
                    print(f"  - {table}")
            
            # List leaf tables (nothing depends on them)
            if summary['leaf_tables']:
                print(f"\nLeaf Tables (no dependents):")
                for table in summary['leaf_tables'][:5]:  # Show first 5
                    print(f"  - {table}")
                if len(summary['leaf_tables']) > 5:
                    print(f"  ... and {len(summary['leaf_tables']) - 5} more")
            
            # Check for self-referencing tables
            if summary['self_referencing_list']:
                print(f"\nSelf-Referencing Tables:")
                for table in summary['self_referencing_list']:
                    print(f"  - {table}")
                    print(f"    ⚠ Requires special handling during sanitization")
            
            # Step 6: Check for circular dependencies
            logger.info("\n" + "=" * 60)
            logger.info("CHECKING FOR CIRCULAR DEPENDENCIES")
            logger.info("=" * 60)
            
            if resolver.has_circular_dependencies():
                cycles = resolver.get_cycles()
                print(f"\n⚠ WARNING: {len(cycles)} circular dependency cycle(s) detected!")
                print("\nProblematic cycles:")
                for i, cycle in enumerate(cycles[:3], 1):
                    cycle_path = " → ".join(cycle + [cycle[0]])
                    print(f"\n  Cycle {i}: {cycle_path}")
                
                if len(cycles) > 3:
                    print(f"\n  ... and {len(cycles) - 3} more cycles")
                
                print("\nMitigation options:")
                print("  1. Temporarily disable FK constraints during sanitization")
                print("  2. Use multi-stage processing with mapping table lookups")
                print("  3. Exclude circular tables from sanitization scope")
                
                logger.warning("Circular dependencies detected", cycle_count=len(cycles))
            else:
                print("\n✓ No circular dependencies detected - safe to proceed")
                logger.info("No circular dependencies found")
            
            # Step 7: Get processing order (if no cycles)
            if not resolver.has_circular_dependencies():
                logger.info("\n" + "=" * 60)
                logger.info("PROCESSING ORDER")
                logger.info("=" * 60)
                
                try:
                    processing_order = resolver.get_processing_order()
                    
                    print(f"\nRecommended processing order ({len(processing_order)} tables):")
                    print("\nFirst 10 tables to process:")
                    for i, table in enumerate(processing_order[:10], 1):
                        depth = resolver.get_dependency_depth(table)
                        deps = resolver.get_dependencies(table)
                        self_ref = " [SELF-REF]" if resolver.is_self_referencing(table) else ""
                        
                        print(f"  {i:2d}. {table}{self_ref}")
                        print(f"      Depth: {depth}, Dependencies: {len(deps)}")
                        if deps:
                            print(f"      Depends on: {', '.join(deps[:2])}")
                            if len(deps) > 2:
                                print(f"                  ... and {len(deps) - 2} more")
                    
                    if len(processing_order) > 10:
                        print(f"\n  ... and {len(processing_order) - 10} more tables")
                    
                    print("\nLast 5 tables to process:")
                    for i, table in enumerate(processing_order[-5:], len(processing_order) - 4):
                        print(f"  {i:2d}. {table}")
                    
                    logger.info("Processing order determined successfully",
                               table_count=len(processing_order))
                
                except CircularDependencyError as e:
                    print(f"\n✗ ERROR: {e.message}")
                    logger.error("Failed to determine processing order", error=str(e))
            
            # Step 8: Example - Get dependencies for a specific table
            if resolver.get_all_tables():
                logger.info("\n" + "=" * 60)
                logger.info("EXAMPLE: DEPENDENCY LOOKUP")
                logger.info("=" * 60)
                
                # Pick a table from the middle of the processing order
                all_tables = resolver.get_all_tables()
                if len(all_tables) > 0:
                    example_table = all_tables[min(5, len(all_tables) - 1)]
                    
                    print(f"\nAnalyzing table: {example_table}")
                    
                    deps = resolver.get_dependencies(example_table)
                    depth = resolver.get_dependency_depth(example_table)
                    is_self_ref = resolver.is_self_referencing(example_table)
                    
                    print(f"  Dependency depth: {depth}")
                    print(f"  Self-referencing: {is_self_ref}")
                    print(f"  Direct dependencies: {len(deps)}")
                    
                    if deps:
                        print(f"  Depends on:")
                        for dep in deps:
                            print(f"    - {dep}")
            
            print("\n" +  "=" * 60)
            print("✓ Dependency analysis complete")
            print("=" * 60)
            logger.info("Dependency resolution example completed successfully")
            
        except CircularDependencyError as e:
            logger.error("Circular dependency detected", error=str(e))
            print(f"\n✗ ERROR: {e.message}")
            print(f"Suggested action: {e.suggested_action}")
            
        except Exception as e:
            logger.error("Dependency resolution failed", error=str(e))
            print(f"\n✗ ERROR: {str(e)}")
            raise
        
        finally:
            # Cleanup
            if 'connection_manager' in locals():
                connection_manager.close()
                logger.info("Database connection closed")


if __name__ == "__main__":
    print("=" * 60)
    print("FOREIGN KEY DEPENDENCY RESOLUTION EXAMPLE")
    print("=" * 60)
    print()
    print("This example demonstrates how to analyze foreign key")
    print("relationships and determine the correct table processing")
    print("order for database sanitization.")
    print()
    
    main()
