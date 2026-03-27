"""
Validation result models for configuration schema validation.

This module defines data structures for representing validation results,
including errors, warnings, and informational messages with categorization
by severity level.

Author: Database Sanitization Team
Date: 2026-03-26
"""

from enum import Enum
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field


class IssueSeverity(Enum):
    """
    Severity levels for validation issues.
    
    Values:
        ERROR: Blocks execution, must be fixed before proceeding
        WARNING: Should be reviewed but doesn't block execution
        INFO: Informational message for user awareness
    """
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """
    Represents a single validation issue (error, warning, or info).
    
    Attributes:
        severity: Issue severity level (ERROR, WARNING, INFO)
        message: Human-readable description of the issue
        column: Affected column in format [schema].[table].[column] (optional)
        code: Error code for programmatic handling (optional)
        suggested_action: Recommended fix or mitigation (optional)
        context: Additional context information (optional)
    
    Example:
        >>> issue = ValidationIssue(
        ...     severity=IssueSeverity.ERROR,
        ...     message="Column 'Email' not found in table 'Users'",
        ...     column="[dbo].[Users].[Email]",
        ...     code="COLUMN_NOT_FOUND",
        ...     suggested_action="Verify column name or remove from configuration"
        ... )
    """
    severity: IssueSeverity
    message: str
    column: Optional[str] = None
    code: Optional[str] = None
    suggested_action: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        """Human-readable string representation."""
        parts = [f"[{self.severity.value.upper()}]"]
        if self.column:
            parts.append(f"{self.column}:")
        parts.append(self.message)
        if self.suggested_action:
            parts.append(f"→ {self.suggested_action}")
        return " ".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "severity": self.severity.value,
            "message": self.message,
            "column": self.column,
            "code": self.code,
            "suggested_action": self.suggested_action,
            "context": self.context
        }


class ValidationResult:
    """
    Container for validation results with categorized issues.
    
    Collects validation errors, warnings, and informational messages
    during configuration validation. Provides methods to query and
    format results.
    
    Attributes:
        errors: List of error-level issues (block execution)
        warnings: List of warning-level issues (should review)
        infos: List of informational messages
    
    Example:
        >>> result = ValidationResult()
        >>> result.add_error(
        ...     "Column not found",
        ...     column="[dbo].[Users].[Email]",
        ...     code="COLUMN_NOT_FOUND"
        ... )
        >>> result.add_warning(
        ...     "Column is a foreign key",
        ...     column="[dbo].[Orders].[CustomerID]"
        ... )
        >>> print(result.is_valid)
        False
        >>> print(result.error_count)
        1
    """
    
    def __init__(self):
        """Initialize empty validation result."""
        self.errors: List[ValidationIssue] = []
        self.warnings: List[ValidationIssue] = []
        self.infos: List[ValidationIssue] = []
    
    def add_error(
        self,
        message: str,
        column: Optional[str] = None,
        code: Optional[str] = None,
        suggested_action: Optional[str] = None,
        **context: Any
    ) -> None:
        """
        Add an error-level issue.
        
        Args:
            message: Human-readable error description
            column: Affected column (optional)
            code: Error code (optional)
            suggested_action: Recommended fix (optional)
            **context: Additional context data
        """
        issue = ValidationIssue(
            severity=IssueSeverity.ERROR,
            message=message,
            column=column,
            code=code,
            suggested_action=suggested_action,
            context=context
        )
        self.errors.append(issue)
    
    def add_warning(
        self,
        message: str,
        column: Optional[str] = None,
        code: Optional[str] = None,
        suggested_action: Optional[str] = None,
        **context: Any
    ) -> None:
        """
        Add a warning-level issue.
        
        Args:
            message: Human-readable warning description
            column: Affected column (optional)
            code: Warning code (optional)
            suggested_action: Recommended action (optional)
            **context: Additional context data
        """
        issue = ValidationIssue(
            severity=IssueSeverity.WARNING,
            message=message,
            column=column,
            code=code,
            suggested_action=suggested_action,
            context=context
        )
        self.warnings.append(issue)
    
    def add_info(
        self,
        message: str,
        column: Optional[str] = None,
        code: Optional[str] = None,
        **context: Any
    ) -> None:
        """
        Add an informational message.
        
        Args:
            message: Informational message
            column: Related column (optional)
            code: Info code (optional)
            **context: Additional context data
        """
        issue = ValidationIssue(
            severity=IssueSeverity.INFO,
            message=message,
            column=column,
            code=code,
            context=context
        )
        self.infos.append(issue)
    
    @property
    def is_valid(self) -> bool:
        """
        Check if validation passed (no errors).
        
        Returns:
            True if no errors exist, False otherwise
        """
        return len(self.errors) == 0
    
    @property
    def error_count(self) -> int:
        """Get number of errors."""
        return len(self.errors)
    
    @property
    def warning_count(self) -> int:
        """Get number of warnings."""
        return len(self.warnings)
    
    @property
    def info_count(self) -> int:
        """Get number of info messages."""
        return len(self.infos)
    
    @property
    def total_issue_count(self) -> int:
        """Get total number of issues (errors + warnings + infos)."""
        return self.error_count + self.warning_count + self.info_count
    
    def has_errors(self) -> bool:
        """Check if validation has errors."""
        return self.error_count > 0
    
    def has_warnings(self) -> bool:
        """Check if validation has warnings."""
        return self.warning_count > 0
    
    def has_issues(self) -> bool:
        """Check if validation has any issues (errors or warnings)."""
        return self.has_errors() or self.has_warnings()
    
    def get_all_issues(self) -> List[ValidationIssue]:
        """
        Get all issues sorted by severity (errors, warnings, infos).
        
        Returns:
            Combined list of all issues
        """
        return self.errors + self.warnings + self.infos
    
    def get_issues_by_severity(self) -> Dict[IssueSeverity, List[ValidationIssue]]:
        """
        Get issues grouped by severity level.
        
        Returns:
            Dictionary mapping severity to list of issues
        """
        return {
            IssueSeverity.ERROR: self.errors,
            IssueSeverity.WARNING: self.warnings,
            IssueSeverity.INFO: self.infos
        }
    
    def get_issues_by_column(self, column: str) -> List[ValidationIssue]:
        """
        Get all issues for a specific column.
        
        Args:
            column: Column identifier in format [schema].[table].[column]
        
        Returns:
            List of issues affecting the specified column
        """
        return [
            issue for issue in self.get_all_issues()
            if issue.column == column
        ]
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert validation result to dictionary for serialization.
        
        Returns:
            Dictionary with errors, warnings, infos, and summary counts
        
        Example:
            >>> result.to_dict()
            {
                'is_valid': False,
                'error_count': 2,
                'warning_count': 1,
                'info_count': 0,
                'errors': [...],
                'warnings': [...],
                'infos': []
            }
        """
        return {
            "is_valid": self.is_valid,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "total_issue_count": self.total_issue_count,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "infos": [issue.to_dict() for issue in self.infos]
        }
    
    def __str__(self) -> str:
        """
        Human-readable string representation.
        
        Returns:
            Summary of validation results with counts
        """
        status = "PASSED" if self.is_valid else "FAILED"
        parts = [f"Validation {status}"]
        
        if self.error_count > 0:
            parts.append(f"{self.error_count} error(s)")
        if self.warning_count > 0:
            parts.append(f"{self.warning_count} warning(s)")
        if self.info_count > 0:
            parts.append(f"{self.info_count} info(s)")
        
        return " - ".join(parts)
    
    def __repr__(self) -> str:
        """Detailed representation for debugging."""
        return (
            f"ValidationResult(errors={self.error_count}, "
            f"warnings={self.warning_count}, infos={self.info_count}, "
            f"is_valid={self.is_valid})"
        )
    
    def format_summary(self, show_issues: bool = True) -> str:
        """
        Format a detailed summary of validation results.
        
        Args:
            show_issues: Whether to include individual issues in output
        
        Returns:
            Formatted multi-line summary string
        
        Example:
            >>> print(result.format_summary())
            Validation FAILED - 2 error(s), 1 warning(s)
            
            ERRORS:
            [ERROR] [dbo].[Users].[Email]: Column not found
            [ERROR] [dbo].[Orders].[OrderID]: Cannot mask INT column as email
            
            WARNINGS:
            [WARNING] [dbo].[Orders].[CustomerID]: Column is a foreign key
        """
        lines = [str(self)]
        
        if show_issues and self.has_issues():
            lines.append("")
            
            if self.errors:
                lines.append("ERRORS:")
                for error in self.errors:
                    lines.append(f"  {error}")
            
            if self.warnings:
                if self.errors:
                    lines.append("")
                lines.append("WARNINGS:")
                for warning in self.warnings:
                    lines.append(f"  {warning}")
            
            if self.infos:
                if self.errors or self.warnings:
                    lines.append("")
                lines.append("INFO:")
                for info in self.infos:
                    lines.append(f"  {info}")
        
        return "\n".join(lines)
