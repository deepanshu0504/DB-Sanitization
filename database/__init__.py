"""
Database utilities for schema inspection and metadata extraction.
"""

from .schema_inspector import SchemaInspector, PrimaryKeyInfo, SchemaInspectionError
from .dependency_graph_builder import (
    DependencyGraph,
    ForeignKeyRelationship,
    ProcessingOrder,
)
from .query_performance_analyzer import (
    QueryPerformanceAnalyzer,
    QueryPlanAnalysis,
    IndexFragmentation,
    IndexUsageStats,
)

__all__ = [
    "SchemaInspector",
    "PrimaryKeyInfo",
    "SchemaInspectionError",
    "DependencyGraph",
    "ForeignKeyRelationship",
    "ProcessingOrder",
    "QueryPerformanceAnalyzer",
    "QueryPlanAnalysis",
    "IndexFragmentation",
    "IndexUsageStats",
]
