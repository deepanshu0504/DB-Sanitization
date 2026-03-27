"""
AI integration module for PII detection using GitHub Copilot Model API.

This module provides automated PII detection capabilities by sending database
schema metadata to AI models and receiving structured recommendations for
columns that likely contain personally identifiable information.

Key Components:
    - CopilotClient: Main client for GitHub Copilot API integration
    - PIIColumn: Pydantic model for PII column recommendations
    - PIIDetectionResponse: Pydantic model for API responses
    - Prompt templates for structured PII detection

Author: Database Sanitization Team
Date: 2026-03-26
"""

from .copilot_client import CopilotClient
from .models import PIIColumn, PIIDetectionResponse

__all__ = [
    "CopilotClient",
    "PIIColumn",
    "PIIDetectionResponse",
]
