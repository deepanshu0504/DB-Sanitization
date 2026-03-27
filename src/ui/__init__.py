"""
User interface module for interactive PII review and configuration.

This module provides terminal-based interfaces for reviewing AI-detected PII columns,
manually adding/removing columns, and saving finalized configurations for sanitization.

Key Components:
    - PIIReviewCLI: Interactive command-line interface for PII review
    - formatters: Rich terminal formatting utilities for tables and panels

Author: Database Sanitization Team
Date: 2026-03-26
"""

from .review_cli import PIIReviewCLI

__all__ = [
    "PIIReviewCLI",
]
