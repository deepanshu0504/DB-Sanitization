"""
Unit tests for UI formatters module.

Tests cover all formatting functions:
- format_pii_table
- format_config_table
- format_summary_panel
- format_validation_results
- format_help_panel
- format_column_detail

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from rich.table import Table
from rich.panel import Panel

from src.ui.formatters import (
    format_pii_table,
    format_config_table,
    format_summary_panel,
    format_validation_results,
    format_help_panel,
    format_column_detail
)
from src.ai.models import PIIColumn
from src.config.config_models import PIIColumnConfig


class TestFormatPIITable:
    """Tests for format_pii_table function."""
    
    def test_format_empty_pii_table(self):
        """Test formatting empty PII table."""
        table = format_pii_table([])
        
        assert isinstance(table, Table)
        assert table.title == "PII Columns"
        assert len(table.columns) == 5  # #, Schema.Table, Column, PII Type, Confidence
    
    def test_format_pii_table_with_data(self):
        """Test formatting PII table with data."""
        pii_columns = [
            PIIColumn(
                schema="dbo",
                table="Users",
                column="Email",
                pii_type="EMAIL",
                confidence=0.95
            ),
            PIIColumn(
                schema="dbo",
                table="Users",
                column="PhoneNumber",
                pii_type="PHONE",
                confidence=0.88
            )
        ]
        
        table = format_pii_table(pii_columns)
        
        assert isinstance(table, Table)
        assert table.title == "PII Columns"
        assert len(table.columns) == 5
    
    def test_format_pii_table_with_custom_title(self):
        """Test formatting PII table with custom title."""
        pii_columns = [
            PIIColumn(
                schema="dbo",
                table="Orders",
                column="CreditCard",
                pii_type="CREDIT_CARD",
                confidence=0.99
            )
        ]
        
        table = format_pii_table(pii_columns, title="AI Detected PII")
        
        assert table.title == "AI Detected PII"
    
    def test_format_pii_table_without_confidence(self):
        """Test formatting PII table with None confidence."""
        pii_columns = [
            PIIColumn(
                schema="dbo",
                table="Employees",
                column="SSN",
                pii_type="SSN",
                confidence=None
            )
        ]
        
        table = format_pii_table(pii_columns)
        
        assert isinstance(table, Table)


class TestFormatConfigTable:
    """Tests for format_config_table function."""
    
    def test_format_empty_config_table(self):
        """Test formatting empty config table."""
        table = format_config_table([])
        
        assert isinstance(table, Table)
        assert table.title == "Configuration"
        assert len(table.columns) == 5  # #, Schema.Table, Column, PII Type, Nullable
    
    def test_format_config_table_with_data(self):
        """Test formatting config table with data."""
        configs = [
            PIIColumnConfig(
                schema="dbo",
                table="Users",
                column="Email",
                pii_type="EMAIL",
                nullable=True
            ),
            PIIColumnConfig(
                schema="dbo",
                table="Users",
                column="SSN",
                pii_type="SSN",
                nullable=False
            )
        ]
        
        table = format_config_table(configs)
        
        assert isinstance(table, Table)
        assert table.title == "Configuration"
    
    def test_format_config_table_with_custom_title(self):
        """Test formatting config table with custom title."""
        configs = [
            PIIColumnConfig(
                schema="sales",
                table="Customers",
                column="CreditCard",
                pii_type="CREDIT_CARD",
                nullable=True
            )
        ]
        
        table = format_config_table(configs, title="Current Configuration")
        
        assert table.title == "Current Configuration"


class TestFormatSummaryPanel:
    """Tests for format_summary_panel function."""
    
    def test_format_summary_panel_all_zeros(self):
        """Test formatting summary with all zero stats."""
        panel = format_summary_panel(
            total_columns=0,
            ai_detected=0,
            manually_added=0,
            removed=0,
            modified=0
        )
        
        assert isinstance(panel, Panel)
        assert "Total PII Columns: 0" in panel.renderable.plain
    
    def test_format_summary_panel_with_data(self):
        """Test formatting summary with realistic data."""
        panel = format_summary_panel(
            total_columns=15,
            ai_detected=12,
            manually_added=3,
            removed=2,
            modified=1
        )
        
        assert isinstance(panel, Panel)
        content = panel.renderable.plain
        assert "Total PII Columns: 15" in content
        assert "AI Detected: 12" in content
        assert "Manually Added: 3" in content
        assert "Removed: 2" in content
        assert "Modified: 1" in content
    
    def test_format_summary_panel_no_manual_changes(self):
        """Test formatting summary without manual changes."""
        panel = format_summary_panel(
            total_columns=10,
            ai_detected=10,
            manually_added=0,
            removed=0,
            modified=0
        )
        
        assert isinstance(panel, Panel)
        content = panel.renderable.plain
        assert "Total PII Columns: 10" in content
        assert "AI Detected: 10" in content
        # Manual changes should not appear when zero
        assert "Manually Added" not in content
        assert "Removed" not in content
        assert "Modified" not in content


class TestFormatValidationResults:
    """Tests for format_validation_results function."""
    
    def test_format_validation_no_issues(self):
        """Test formatting validation with no errors or warnings."""
        table = format_validation_results(errors=[], warnings=[])
        
        assert isinstance(table, Table)
        assert table.title == "Validation Results"
    
    def test_format_validation_with_errors(self):
        """Test formatting validation with errors."""
        errors = [
            "Column 'Email' not found in table 'Users'",
            "Table 'Orders' does not exist"
        ]
        
        table = format_validation_results(errors=errors, warnings=[])
        
        assert isinstance(table, Table)
    
    def test_format_validation_with_warnings(self):
        """Test formatting validation with warnings."""
        warnings = [
            "Column 'UserID' is a primary key",
            "Column 'CustomerID' is a foreign key"
        ]
        
        table = format_validation_results(errors=[], warnings=warnings)
        
        assert isinstance(table, Table)
    
    def test_format_validation_with_both(self):
        """Test formatting validation with both errors and warnings."""
        errors = ["Column not found"]
        warnings = ["Column is a primary key"]
        
        table = format_validation_results(errors=errors, warnings=warnings)
        
        assert isinstance(table, Table)


class TestFormatHelpPanel:
    """Tests for format_help_panel function."""
    
    def test_format_help_panel(self):
        """Test formatting help panel."""
        panel = format_help_panel()
        
        assert isinstance(panel, Panel)
        content = panel.renderable.plain
        
        # Check for key commands
        assert "[A]dd" in content
        assert "[R]emove" in content
        assert "[M]odify" in content
        assert "[U]ndo" in content
        assert "[S]ave" in content
        assert "[H]elp" in content
        assert "[Q]uit" in content


class TestFormatColumnDetail:
    """Tests for format_column_detail function."""
    
    def test_format_column_detail_basic(self):
        """Test formatting basic column details."""
        panel = format_column_detail(
            schema="dbo",
            table="Users",
            column="Email",
            data_type="VARCHAR(255)",
            nullable=True
        )
        
        assert isinstance(panel, Panel)
        content = panel.renderable.plain
        assert "dbo.Users.Email" in content
        assert "VARCHAR(255)" in content
        assert "Yes" in content  # Nullable
    
    def test_format_column_detail_not_nullable(self):
        """Test formatting non-nullable column details."""
        panel = format_column_detail(
            schema="dbo",
            table="Orders",
            column="OrderID",
            data_type="INT",
            nullable=False
        )
        
        assert isinstance(panel, Panel)
        content = panel.renderable.plain
        assert "No" in content  # Not nullable
    
    def test_format_column_detail_primary_key(self):
        """Test formatting primary key column details."""
        panel = format_column_detail(
            schema="dbo",
            table="Users",
            column="UserID",
            data_type="INT",
            nullable=False,
            is_pk=True
        )
        
        assert isinstance(panel, Panel)
        content = panel.renderable.plain
        assert "PRIMARY KEY" in content
    
    def test_format_column_detail_foreign_key(self):
        """Test formatting foreign key column details."""
        panel = format_column_detail(
            schema="dbo",
            table="Orders",
            column="CustomerID",
            data_type="INT",
            nullable=True,
            is_fk=True,
            fk_reference="Customers.CustomerID"
        )
        
        assert isinstance(panel, Panel)
        content = panel.renderable.plain
        assert "FOREIGN KEY" in content
        assert "Customers.CustomerID" in content
    
    def test_format_column_detail_all_flags(self):
        """Test formatting column with all flags set."""
        panel = format_column_detail(
            schema="sales",
            table="OrderDetails",
            column="ProductID",
            data_type="BIGINT",
            nullable=False,
            is_pk=True,
            is_fk=True,
            fk_reference="Products.ProductID"
        )
        
        assert isinstance(panel, Panel)
        content = panel.renderable.plain
        assert "PRIMARY KEY" in content
        assert "FOREIGN KEY" in content
        assert "Products.ProductID" in content


class TestFormatterEdgeCases:
    """Tests for edge cases across all formatters."""
    
    def test_long_table_names(self):
        """Test formatting with very long table names."""
        pii_columns = [
            PIIColumn(
                schema="very_long_schema_name",
                table="very_long_table_name_exceeding_normal_length",
                column="very_long_column_name",
                pii_type="EMAIL",
                confidence=0.95
            )
        ]
        
        table = format_pii_table(pii_columns)
        assert isinstance(table, Table)
    
    def test_special_characters_in_names(self):
        """Test formatting with special characters in names."""
        configs = [
            PIIColumnConfig(
                schema="dbo",
                table="Table-With-Dashes",
                column="Column_With_Underscore",
                pii_type="EMAIL",
                nullable=True
            )
        ]
        
        table = format_config_table(configs)
        assert isinstance(table, Table)
    
    def test_unicode_in_column_names(self):
        """Test formatting with Unicode characters."""
        pii_columns = [
            PIIColumn(
                schema="dbo",
                table="国际化表",
                column="电子邮件",
                pii_type="EMAIL",
                confidence=0.90
            )
        ]
        
        table = format_pii_table(pii_columns)
        assert isinstance(table, Table)
    
    def test_extreme_confidence_values(self):
        """Test formatting with extreme confidence values."""
        pii_columns = [
            PIIColumn(
                schema="dbo",
                table="Test",
                column="Col1",
                pii_type="EMAIL",
                confidence=0.0
            ),
            PIIColumn(
                schema="dbo",
                table="Test",
                column="Col2",
                pii_type="PHONE",
                confidence=1.0
            )
        ]
        
        table = format_pii_table(pii_columns)
        assert isinstance(table, Table)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
