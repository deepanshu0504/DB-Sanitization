"""
Sanitization orchestration and dependency resolution module.

This module provides classes for managing the sanitization workflow,
including dependency resolution for foreign key relationships and
the central orchestrator for coordinating all sanitization operations.

Classes:
    - DependencyResolver: Resolves foreign key dependencies and provides topological sort
    - SanitizationOrchestrator: Central coordinator for the sanitization workflow
    - SanitizationReport: Comprehensive report of sanitization execution
    - TableProgress: Progress tracking for individual tables
    - Checkpoint: Checkpoint for resuming sanitization after failure
    - ExecutionPhase: Enum for execution phase tracking

Author: Database Sanitization Team
Date: 2026-03-26
"""

from .dependency_resolver import DependencyResolver
from .orchestrator import (
    SanitizationOrchestrator,
    SanitizationReport,
    TableProgress,
    Checkpoint,
    ExecutionPhase,
    ProgressCallback
)

__all__ = [
    "DependencyResolver",
    "SanitizationOrchestrator",
    "SanitizationReport",
    "TableProgress",
    "Checkpoint",
    "ExecutionPhase",
    "ProgressCallback"
]
