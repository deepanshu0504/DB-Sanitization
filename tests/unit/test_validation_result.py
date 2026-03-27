"""
Unit tests for validation result models.

Tests cover:
- IssueSeverity enum
- ValidationIssue dataclass
- ValidationResult container
- Serialization and formatting

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from src.validation.validation_result import (
    IssueSeverity,
    ValidationIssue,
    ValidationResult
)


class TestIssueSeverity:
    """Tests for IssueSeverity enum."""
    
    def test_severity_values(self):
        """Test enum values are correct."""
        assert IssueSeverity.ERROR.value == "error"
        assert IssueSeverity.WARNING.value == "warning"
        assert IssueSeverity.INFO.value == "info"
    
    def test_severity_comparison(self):
        """Test enum comparisons."""
        assert IssueSeverity.ERROR == IssueSeverity.ERROR
        assert IssueSeverity.ERROR != IssueSeverity.WARNING


class TestValidationIssue:
    """Tests for ValidationIssue dataclass."""
    
    def test_create_minimal_issue(self):
        """Test creating issue with minimal fields."""
        issue = ValidationIssue(
            severity=IssueSeverity.ERROR,
            message="Test error"
        )
        
        assert issue.severity == IssueSeverity.ERROR
        assert issue.message == "Test error"
        assert issue.column is None
        assert issue.code is None
        assert issue.suggested_action is None
        assert issue.context == {}
    
    def test_create_full_issue(self):
        """Test creating issue with all fields."""
        issue = ValidationIssue(
            severity=IssueSeverity.WARNING,
            message="Column is a foreign key",
            column="[dbo].[Orders].[CustomerID]",
            code="FK_COLUMN_WARNING",
            suggested_action="Ensure parent column is sanitized",
            context={"table": "Orders", "ref": "Customers.CustomerID"}
        )
        
        assert issue.severity == IssueSeverity.WARNING
        assert issue.message == "Column is a foreign key"
        assert issue.column == "[dbo].[Orders].[CustomerID]"
        assert issue.code == "FK_COLUMN_WARNING"
        assert issue.suggested_action == "Ensure parent column is sanitized"
        assert issue.context["table"] == "Orders"
    
    def test_issue_str_minimal(self):
        """Test string representation with minimal fields."""
        issue = ValidationIssue(
            severity=IssueSeverity.ERROR,
            message="Test error"
        )
        
        result = str(issue)
        assert "[ERROR]" in result
        assert "Test error" in result
    
    def test_issue_str_with_column(self):
        """Test string representation with column."""
        issue = ValidationIssue(
            severity=IssueSeverity.WARNING,
            message="Test warning",
            column="[dbo].[Users].[Email]"
        )
        
        result = str(issue)
        assert "[WARNING]" in result
        assert "[dbo].[Users].[Email]" in result
        assert "Test warning" in result
    
    def test_issue_str_with_suggested_action(self):
        """Test string representation with suggested action."""
        issue = ValidationIssue(
            severity=IssueSeverity.ERROR,
            message="Column not found",
            suggested_action="Verify column name"
        )
        
        result = str(issue)
        assert "→ Verify column name" in result
    
    def test_issue_to_dict(self):
        """Test serialization to dictionary."""
        issue = ValidationIssue(
            severity=IssueSeverity.ERROR,
            message="Test error",
            column="[dbo].[Test].[Col]",
            code="TEST_ERROR",
            suggested_action="Fix it",
            context={"key": "value"}
        )
        
        result = issue.to_dict()
        
        assert result["severity"] == "error"
        assert result["message"] == "Test error"
        assert result["column"] == "[dbo].[Test].[Col]"
        assert result["code"] == "TEST_ERROR"
        assert result["suggested_action"] == "Fix it"
        assert result["context"] == {"key": "value"}


class TestValidationResult:
    """Tests for ValidationResult container."""
    
    def test_create_empty_result(self):
        """Test creating empty validation result."""
        result = ValidationResult()
        
        assert result.errors == []
        assert result.warnings == []
        assert result.infos == []
        assert result.is_valid is True
        assert result.error_count == 0
        assert result.warning_count == 0
        assert result.info_count == 0
        assert result.total_issue_count == 0
    
    def test_add_error(self):
        """Test adding error."""
        result = ValidationResult()
        result.add_error("Test error", column="[dbo].[Test].[Col]", code="TEST_ERROR")
        
        assert len(result.errors) == 1
        assert result.error_count == 1
        assert result.is_valid is False
        assert result.errors[0].severity == IssueSeverity.ERROR
        assert result.errors[0].message == "Test error"
    
    def test_add_warning(self):
        """Test adding warning."""
        result = ValidationResult()
        result.add_warning("Test warning", suggested_action="Do something")
        
        assert len(result.warnings) == 1
        assert result.warning_count == 1
        assert result.is_valid is True  # Warnings don't affect validity
        assert result.warnings[0].severity == IssueSeverity.WARNING
    
    def test_add_info(self):
        """Test adding info message."""
        result = ValidationResult()
        result.add_info("Test info", context={"key": "value"})
        
        assert len(result.infos) == 1
        assert result.info_count == 1
        assert result.is_valid is True
        assert result.infos[0].severity == IssueSeverity.INFO
    
    def test_is_valid_with_errors(self):
        """Test is_valid property with errors."""
        result = ValidationResult()
        assert result.is_valid is True
        
        result.add_error("Error 1")
        assert result.is_valid is False
        
        result.add_warning("Warning 1")
        assert result.is_valid is False  # Still invalid due to error
    
    def test_has_errors(self):
        """Test has_errors method."""
        result = ValidationResult()
        assert result.has_errors() is False
        
        result.add_error("Test error")
        assert result.has_errors() is True
    
    def test_has_warnings(self):
        """Test has_warnings method."""
        result = ValidationResult()
        assert result.has_warnings() is False
        
        result.add_warning("Test warning")
        assert result.has_warnings() is True
    
    def test_has_issues(self):
        """Test has_issues method."""
        result = ValidationResult()
        assert result.has_issues() is False
        
        result.add_info("Test info")
        assert result.has_issues() is False  # Info doesn't count as issue
        
        result.add_warning("Test warning")
        assert result.has_issues() is True
    
    def test_get_all_issues(self):
        """Test getting all issues."""
        result = ValidationResult()
        result.add_error("Error 1")
        result.add_warning("Warning 1")
        result.add_info("Info 1")
        
        all_issues = result.get_all_issues()
        
        assert len(all_issues) == 3
        assert all_issues[0].severity == IssueSeverity.ERROR
        assert all_issues[1].severity == IssueSeverity.WARNING
        assert all_issues[2].severity == IssueSeverity.INFO
    
    def test_get_issues_by_severity(self):
        """Test getting issues grouped by severity."""
        result = ValidationResult()
        result.add_error("Error 1")
        result.add_error("Error 2")
        result.add_warning("Warning 1")
        
        by_severity = result.get_issues_by_severity()
        
        assert len(by_severity[IssueSeverity.ERROR]) == 2
        assert len(by_severity[IssueSeverity.WARNING]) == 1
        assert len(by_severity[IssueSeverity.INFO]) == 0
    
    def test_get_issues_by_column(self):
        """Test getting issues for specific column."""
        result = ValidationResult()
        result.add_error("Error 1", column="[dbo].[Users].[Email]")
        result.add_warning("Warning 1", column="[dbo].[Users].[Email]")
        result.add_error("Error 2", column="[dbo].[Orders].[OrderID]")
        
        email_issues = result.get_issues_by_column("[dbo].[Users].[Email]")
        
        assert len(email_issues) == 2
        assert all(issue.column == "[dbo].[Users].[Email]" for issue in email_issues)
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        result = ValidationResult()
        result.add_error("Error 1")
        result.add_warning("Warning 1")
        
        result_dict = result.to_dict()
        
        assert result_dict["is_valid"] is False
        assert result_dict["error_count"] == 1
        assert result_dict["warning_count"] == 1
        assert result_dict["info_count"] == 0
        assert result_dict["total_issue_count"] == 2
        assert len(result_dict["errors"]) == 1
        assert len(result_dict["warnings"]) == 1
    
    def test_str_representation(self):
        """Test string representation."""
        result = ValidationResult()
        assert "PASSED" in str(result)
        
        result.add_error("Error 1")
        assert "FAILED" in str(result)
        assert "1 error" in str(result)
        
        result.add_warning("Warning 1")
        assert "1 warning" in str(result)
    
    def test_repr_representation(self):
        """Test detailed representation."""
        result = ValidationResult()
        result.add_error("Error 1")
        result.add_warning("Warning 1")
        
        repr_str = repr(result)
        
        assert "ValidationResult" in repr_str
        assert "errors=1" in repr_str
        assert "warnings=1" in repr_str
        assert "is_valid=False" in repr_str
    
    def test_format_summary_no_issues(self):
        """Test formatted summary with no issues."""
        result = ValidationResult()
        summary = result.format_summary()
        
        assert "PASSED" in summary
    
    def test_format_summary_with_errors(self):
        """Test formatted summary with errors."""
        result = ValidationResult()
        result.add_error("Test error", column="[dbo].[Test].[Col]")
        
        summary = result.format_summary(show_issues=True)
        
        assert "FAILED" in summary
        assert "ERRORS:" in summary
        assert "Test error" in summary
    
    def test_format_summary_without_issues(self):
        """Test formatted summary without displaying issues."""
        result = ValidationResult()
        result.add_error("Test error")
        
        summary = result.format_summary(show_issues=False)
        
        assert "FAILED" in summary
        assert "Test error" not in summary
    
    def test_total_issue_count(self):
        """Test total issue count calculation."""
        result = ValidationResult()
        
        assert result.total_issue_count == 0
        
        result.add_error("Error 1")
        assert result.total_issue_count == 1
        
        result.add_warning("Warning 1")
        assert result.total_issue_count == 2
        
        result.add_info("Info 1")
        assert result.total_issue_count == 3


class TestValidationResultComplexScenarios:
    """Tests for complex validation scenarios."""
    
    def test_multiple_issues_same_column(self):
        """Test handling multiple issues for same column."""
        result = ValidationResult()
        
        column = "[dbo].[Users].[Email]"
        result.add_error("Column not found", column=column)
        result.add_warning("Column is a foreign key", column=column)
        result.add_info("Column has index", column=column)
        
        column_issues = result.get_issues_by_column(column)
        assert len(column_issues) == 3
    
    def test_many_errors(self):
        """Test handling many errors."""
        result = ValidationResult()
        
        for i in range(100):
            result.add_error(f"Error {i}")
        
        assert result.error_count == 100
        assert result.is_valid is False
        assert len(result.get_all_issues()) == 100
    
    def test_mixed_severity_levels(self):
        """Test handling mixed severity levels."""
        result = ValidationResult()
        
        result.add_error("Critical error")
        result.add_error("Another error")
        result.add_warning("Minor warning")
        result.add_warning("Another warning")
        result.add_warning("Third warning")
        result.add_info("FYI")
        
        assert result.error_count == 2
        assert result.warning_count == 3
        assert result.info_count == 1
        assert result.total_issue_count == 6
        assert result.is_valid is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
