"""
Unit tests for PIIReviewCLI class.

Tests cover:
- Initialization
- PII column conversion
- Configuration merging
- User interactions (mocked)
- Validation logic
- File saving
- Undo functionality

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path
import json
from copy import deepcopy

from src.ui.review_cli import PIIReviewCLI
from src.ai.models import PIIColumn
from src.config.config_models import PIIColumnConfig
from src.database.schema_extractor import SchemaExtractor


@pytest.fixture
def mock_console():
    """Mock Rich Console."""
    console = Mock()
    console.print = Mock()
    console.clear = Mock()
    return console


@pytest.fixture
def mock_schema_extractor():
    """Mock SchemaExtractor."""
    extractor = Mock(spec=SchemaExtractor)
    
    # Mock get_tables
    extractor.get_tables.return_value = [
        {"table_name": "Users"},
        {"table_name": "Orders"}
    ]
    
    # Mock get_columns
    extractor.get_columns.return_value = [
        {
            "column_name": "Email",
            "data_type": "VARCHAR",
            "is_nullable": True,
            "is_primary_key": False,
            "is_foreign_key": False
        },
        {
            "column_name": "UserID",
            "data_type": "INT",
            "is_nullable": False,
            "is_primary_key": True,
            "is_foreign_key": False
        }
    ]
    
    return extractor


@pytest.fixture
def sample_pii_columns():
    """Sample PII columns for testing."""
    return [
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
        ),
        PIIColumn(
            schema="dbo",
            table="Orders",
            column="CreditCard",
            pii_type="CREDIT_CARD",
            confidence=0.99
        )
    ]


@pytest.fixture
def sample_pii_configs():
    """Sample PII configurations for testing."""
    return [
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


class TestPIIReviewCLIInitialization:
    """Tests for PIIReviewCLI initialization."""
    
    def test_init_default(self):
        """Test initialization with default parameters."""
        cli = PIIReviewCLI()
        
        assert cli.console is not None
        assert cli.schema_extractor is None
        assert cli.pii_configs == []
        assert cli.original_configs == []
        assert cli.history == []
        assert cli.stats == {
            "ai_detected": 0,
            "manually_added": 0,
            "removed": 0,
            "modified": 0
        }
    
    def test_init_with_schema_extractor(self, mock_schema_extractor):
        """Test initialization with schema extractor."""
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        
        assert cli.schema_extractor is mock_schema_extractor
    
    def test_init_with_console(self, mock_console):
        """Test initialization with custom console."""
        cli = PIIReviewCLI(console=mock_console)
        
        assert cli.console is mock_console
    
    def test_supported_pii_types(self):
        """Test that supported PII types are defined."""
        cli = PIIReviewCLI()
        
        assert len(PIIReviewCLI.SUPPORTED_PII_TYPES) >= 10
        assert "EMAIL" in PIIReviewCLI.SUPPORTED_PII_TYPES
        assert "PHONE" in PIIReviewCLI.SUPPORTED_PII_TYPES
        assert "SSN" in PIIReviewCLI.SUPPORTED_PII_TYPES


class TestConvertToConfigs:
    """Tests for _convert_to_configs method."""
    
    def test_convert_empty_list(self):
        """Test converting empty PII column list."""
        cli = PIIReviewCLI()
        configs = cli._convert_to_configs([])
        
        assert configs == []
    
    def test_convert_single_column(self):
        """Test converting single PII column."""
        cli = PIIReviewCLI()
        pii_columns = [
            PIIColumn(
                schema="dbo",
                table="Users",
                column="Email",
                pii_type="EMAIL",
                confidence=0.95
            )
        ]
        
        configs = cli._convert_to_configs(pii_columns)
        
        assert len(configs) == 1
        assert isinstance(configs[0], PIIColumnConfig)
        assert configs[0].schema == "dbo"
        assert configs[0].table == "Users"
        assert configs[0].column == "Email"
        assert configs[0].pii_type == "EMAIL"
        assert configs[0].nullable is True  # Default
    
    def test_convert_multiple_columns(self, sample_pii_columns):
        """Test converting multiple PII columns."""
        cli = PIIReviewCLI()
        configs = cli._convert_to_configs(sample_pii_columns)
        
        assert len(configs) == 3
        assert all(isinstance(cfg, PIIColumnConfig) for cfg in configs)
        assert configs[0].column == "Email"
        assert configs[1].column == "PhoneNumber"
        assert configs[2].column == "CreditCard"


class TestMergeExistingConfig:
    """Tests for _merge_existing_config method."""
    
    def test_merge_empty_config(self):
        """Test merging with empty existing config."""
        cli = PIIReviewCLI()
        cli.pii_configs = [
            PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=True)
        ]
        
        cli._merge_existing_config([])
        
        assert len(cli.pii_configs) == 1
        assert cli.stats["manually_added"] == 0
    
    def test_merge_no_overlap(self, sample_pii_configs):
        """Test merging configs with no overlap."""
        cli = PIIReviewCLI()
        cli.pii_configs = [
            PIIColumnConfig(schema="dbo", table="Orders", column="OrderID", pii_type="CUSTOM", nullable=False)
        ]
        
        cli._merge_existing_config(sample_pii_configs)
        
        assert len(cli.pii_configs) == 3
        assert cli.stats["manually_added"] == 2
    
    def test_merge_with_duplicates(self):
        """Test merging configs with duplicates (should skip)."""
        cli = PIIReviewCLI()
        cli.pii_configs = [
            PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=True)
        ]
        
        existing = [
            PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=False)
        ]
        
        cli._merge_existing_config(existing)
        
        assert len(cli.pii_configs) == 1  # No duplicate added
        assert cli.stats["manually_added"] == 0


class TestValidateColumn:
    """Tests for _validate_column method."""
    
    def test_validate_without_extractor(self):
        """Test validation without schema extractor."""
        cli = PIIReviewCLI(schema_extractor=None)
        
        errors, warnings = cli._validate_column("dbo", "Users", "Email")
        
        assert errors == []
        assert warnings == []
    
    def test_validate_existing_column(self, mock_schema_extractor):
        """Test validation of existing column."""
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        
        errors, warnings = cli._validate_column("dbo", "Users", "Email")
        
        assert errors == []
        # May or may not have warnings depending on column properties
    
    def test_validate_nonexistent_table(self, mock_schema_extractor):
        """Test validation with nonexistent table."""
        mock_schema_extractor.get_tables.return_value = []
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        
        errors, warnings = cli._validate_column("dbo", "NonExistent", "Email")
        
        assert len(errors) > 0
        assert "not found" in errors[0].lower()
    
    def test_validate_nonexistent_column(self, mock_schema_extractor):
        """Test validation with nonexistent column."""
        mock_schema_extractor.get_columns.return_value = [
            {"column_name": "Email", "is_primary_key": False, "is_foreign_key": False}
        ]
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        
        errors, warnings = cli._validate_column("dbo", "Users", "NonExistent")
        
        assert len(errors) > 0
        assert "not found" in errors[0].lower()
    
    def test_validate_primary_key_warning(self, mock_schema_extractor):
        """Test validation generates warning for primary key."""
        mock_schema_extractor.get_columns.return_value = [
            {
                "column_name": "UserID",
                "is_primary_key": True,
                "is_foreign_key": False
            }
        ]
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        
        errors, warnings = cli._validate_column("dbo", "Users", "UserID")
        
        assert errors == []
        assert len(warnings) > 0
        assert "PRIMARY KEY" in warnings[0]
    
    def test_validate_foreign_key_warning(self, mock_schema_extractor):
        """Test validation generates warning for foreign key."""
        mock_schema_extractor.get_columns.return_value = [
            {
                "column_name": "CustomerID",
                "is_primary_key": False,
                "is_foreign_key": True
            }
        ]
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        
        errors, warnings = cli._validate_column("dbo", "Orders", "CustomerID")
        
        assert errors == []
        assert len(warnings) > 0
        assert "FOREIGN KEY" in warnings[0]
    
    def test_validate_exception_handling(self, mock_schema_extractor):
        """Test validation handles exceptions gracefully."""
        mock_schema_extractor.get_tables.side_effect = Exception("Database error")
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        
        errors, warnings = cli._validate_column("dbo", "Users", "Email")
        
        # Should return warnings, not crash
        assert len(warnings) > 0


class TestIsDuplicate:
    """Tests for _is_duplicate method."""
    
    def test_is_duplicate_empty_list(self):
        """Test duplicate check with empty config list."""
        cli = PIIReviewCLI()
        config = PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=True)
        
        assert cli._is_duplicate(config) is False
    
    def test_is_duplicate_found(self):
        """Test duplicate check finds existing config."""
        cli = PIIReviewCLI()
        cli.pii_configs = [
            PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=True)
        ]
        
        config = PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="PHONE", nullable=False)
        
        assert cli._is_duplicate(config) is True
    
    def test_is_duplicate_not_found(self):
        """Test duplicate check with different column."""
        cli = PIIReviewCLI()
        cli.pii_configs = [
            PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=True)
        ]
        
        config = PIIColumnConfig(schema="dbo", table="Users", column="Phone", pii_type="PHONE", nullable=True)
        
        assert cli._is_duplicate(config) is False
    
    def test_is_duplicate_case_sensitive(self):
        """Test duplicate check is case-sensitive."""
        cli = PIIReviewCLI()
        cli.pii_configs = [
            PIIColumnConfig(schema="dbo", table="Users", column="email", pii_type="EMAIL", nullable=True)
        ]
        
        config = PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=True)
        
        # Should be case-sensitive (different columns)
        assert cli._is_duplicate(config) is False


class TestSaveToFile:
    """Tests for save_to_file method."""
    
    def test_save_empty_config(self, tmp_path, mock_console):
        """Test saving empty configuration."""
        cli = PIIReviewCLI(console=mock_console)
        output_path = tmp_path / "config.json"
        
        cli.save_to_file(output_path)
        
        assert output_path.exists()
        with output_path.open("r") as f:
            data = json.load(f)
        assert data == []
    
    def test_save_with_data(self, tmp_path, mock_console, sample_pii_configs):
        """Test saving configuration with data."""
        cli = PIIReviewCLI(console=mock_console)
        cli.pii_configs = sample_pii_configs
        output_path = tmp_path / "config.json"
        
        cli.save_to_file(output_path)
        
        assert output_path.exists()
        with output_path.open("r") as f:
            data = json.load(f)
        
        assert len(data) == 2
        assert data[0]["schema"] == "dbo"
        assert data[0]["table"] == "Users"
        assert data[0]["column"] == "Email"
        assert data[0]["pii_type"] == "EMAIL"
        assert data[0]["nullable"] is True
    
    def test_save_creates_directory(self, tmp_path, mock_console):
        """Test saving creates parent directories."""
        cli = PIIReviewCLI(console=mock_console)
        cli.pii_configs = [
            PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=True)
        ]
        output_path = tmp_path / "nested" / "dir" / "config.json"
        
        cli.save_to_file(output_path)
        
        assert output_path.exists()
    
    def test_save_overwrites_existing(self, tmp_path, mock_console):
        """Test saving overwrites existing file."""
        cli = PIIReviewCLI(console=mock_console)
        output_path = tmp_path / "config.json"
        
        # Create initial file
        output_path.write_text("old content")
        
        # Save new content
        cli.pii_configs = [
            PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=True)
        ]
        cli.save_to_file(output_path)
        
        # Verify new content
        with output_path.open("r") as f:
            data = json.load(f)
        assert len(data) == 1
    
    def test_save_handles_error(self, mock_console):
        """Test saving handles I/O errors."""
        cli = PIIReviewCLI(console=mock_console)
        cli.pii_configs = [
            PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=True)
        ]
        
        # Invalid path (directory as file)
        output_path = Path("/")
        
        with pytest.raises(IOError):
            cli.save_to_file(output_path)


class TestUndoFunctionality:
    """Tests for undo functionality."""
    
    def test_undo_add(self, mock_console):
        """Test undoing add operation."""
        cli = PIIReviewCLI(console=mock_console)
        
        # Simulate add
        config = PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=True)
        cli.pii_configs.append(config)
        cli.stats["manually_added"] = 1
        cli.history.append(("add", config))
        
        # Undo
        cli._handle_undo()
        
        assert len(cli.pii_configs) == 0
        assert cli.stats["manually_added"] == 0
    
    def test_undo_remove(self, mock_console):
        """Test undoing remove operation."""
        cli = PIIReviewCLI(console=mock_console)
        
        # Simulate remove
        config = PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=True)
        cli.stats["removed"] = 1
        cli.history.append(("remove", (0, config)))
        
        # Undo
        cli._handle_undo()
        
        assert len(cli.pii_configs) == 1
        assert cli.pii_configs[0] == config
        assert cli.stats["removed"] == 0
    
    def test_undo_modify(self, mock_console):
        """Test undoing modify operation."""
        cli = PIIReviewCLI(console=mock_console)
        
        # Setup
        original_config = PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=True)
        modified_config = PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="PHONE", nullable=False)
        cli.pii_configs = [modified_config]
        cli.stats["modified"] = 1
        cli.history.append(("modify", (0, original_config)))
        
        # Undo
        cli._handle_undo()
        
        assert cli.pii_configs[0].pii_type == "EMAIL"
        assert cli.pii_configs[0].nullable is True
        assert cli.stats["modified"] == 0
    
    def test_undo_empty_history(self, mock_console):
        """Test undo with empty history."""
        cli = PIIReviewCLI(console=mock_console)
        
        with patch("src.ui.review_cli.Prompt") as mock_prompt:
            cli._handle_undo()
            # Should just show message, not crash
            mock_prompt.ask.assert_called_once()


class TestConfirmQuit:
    """Tests for _confirm_quit method."""
    
    def test_confirm_quit_no_changes(self, mock_console):
        """Test quit confirmation with no changes."""
        cli = PIIReviewCLI(console=mock_console)
        
        result = cli._confirm_quit()
        
        assert result is True  # No history, safe to quit
    
    @patch("src.ui.review_cli.Confirm.ask")
    def test_confirm_quit_with_changes(self, mock_confirm, mock_console):
        """Test quit confirmation with unsaved changes."""
        cli = PIIReviewCLI(console=mock_console)
        cli.history = [("add", Mock())]
        mock_confirm.return_value = True
        
        result = cli._confirm_quit()
        
        assert result is True
        mock_confirm.assert_called_once()


class TestDisplayMethods:
    """Tests for display methods (basic smoke tests)."""
    
    def test_display_welcome(self, mock_console):
        """Test display welcome doesn't crash."""
        cli = PIIReviewCLI(console=mock_console)
        
        cli._display_welcome()
        
        assert mock_console.print.called
    
    def test_display_current_state(self, mock_console):
        """Test display current state doesn't crash."""
        cli = PIIReviewCLI(console=mock_console)
        cli.pii_configs = [
            PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="EMAIL", nullable=True)
        ]
        
        cli._display_current_state()
        
        assert mock_console.print.called
        assert mock_console.clear.called
    
    def test_display_help(self, mock_console):
        """Test display help doesn't crash."""
        cli = PIIReviewCLI(console=mock_console)
        
        with patch("src.ui.review_cli.Prompt.ask"):
            cli._display_help()
        
        assert mock_console.print.called


class TestShowMenu:
    """Tests for _show_menu method."""
    
    @patch("src.ui.review_cli.Prompt.ask")
    def test_show_menu_choices(self, mock_ask, mock_console):
        """Test menu returns correct actions."""
        cli = PIIReviewCLI(console=mock_console)
        
        test_cases = [
            ("a", "add"),
            ("r", "remove"),
            ("m", "modify"),
            ("u", "undo"),
            ("s", "save"),
            ("h", "help"),
            ("q", "quit")
        ]
        
        for user_input, expected_action in test_cases:
            mock_ask.return_value = user_input
            action = cli._show_menu()
            assert action == expected_action


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
