"""
Maintenance utilities package for database sanitization framework.

This package provides automated maintenance tools for optimizing
performance and managing database artifacts.

Story 5.3: Optimized Mapping Lookups
"""

from .optimize_mapping_indexes import optimize_mapping_indexes

__all__ = [
    "optimize_mapping_indexes",
]
