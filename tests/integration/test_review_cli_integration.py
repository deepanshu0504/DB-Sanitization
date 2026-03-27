"""
Integration tests for PII Review CLI.

These tests verify the complete workflow combining:
- AI PII detection
- Schema validation
- Interactive review
- Configuration persistence

Note: These tests use mocking for user interaction but test real
integration between components.

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import json

from src.ui.review_cli import PIIReviewCLI
from src.ai.models import PIIColumn
from src.config.config_models import PIIColumnConfig
from src.database.schema_extractor import SchemaExtractor


@pytest.fixture
def mock_schema_extractor():
    """Mock SchemaExtractor with realistic data."""
    extractor = Mock(spec=SchemaExtractor)
    
    # Mock get_tables
    extractor.get_tables.return_value = [
        {"table_name": "Users", "table_type": "TABLE"},
        {"table_name": "Orders", "table_type": "TABLE"},
        {"table_name": "Customers", "table_type": "TABLE"}
    ]
    
    # Mock get_columns with different scenarios
    def mock_get_columns(schema, table):
        if table == "Users":
            return [
                {
                    "column_name": "UserID",
                    "data_type": "INT",
                    "is_nullable": False,
                    "is_primary_key": True,
                    "is_foreign_key": False
                },
                {
                    "column_name": "Email",
                    "data_type": "VARCHAR",
                    "is_nullable": True,
                    "is_primary_key": False,
                    "is_foreign_key": False
                },
                {
                    "column_name": "PhoneNumber",
                    "data_type": "VARCHAR",
                    "is_nullable": True,
                    "is_primary_key": False,
                    "is_foreign_key": False
                },
                {
                    "column_name": "SSN",
                    "data_type": "VARCHAR",
                    "is_nullable": False,
                    "is_primary_key": False,
                    "is_foreign_key": False
                }
            ]
        elif table == "Orders":
            return [
                {
                    "column_name": "OrderID",
                    "data_type": "INT",
                    "is_nullable": False,
                    "is_primary_key": True,
                    "is_foreign_key": False
                },
                {
                    "column_name": "CustomerID",
                    "data_type": "INT",
                    "is_nullable": False,
                    "is_primary_key": False,
                    "is_foreign_key": True
                },
                {
                    "column_name": "CreditCard",
                    "data_type": "VARCHAR",
                    "is_nullable": True,
                    "is_primary_key": False,
                    "is_foreign_key": False
                }
            ]
        else:
            return []
    
    extractor.get_columns.side_effect = mock_get_columns
    
    return extractor


@pytest.fixture
def ai_detected_pii():
    """Realistic AI-detected PII columns."""
    return [
        PIIColumn(schema="dbo", table="Users", column="Email", pii_type="EMAIL", confidence=0.95),
        PIIColumn(schema="dbo", table="Users", column="PhoneNumber", pii_type="PHONE", confidence=0.88),
        PIIColumn(schema="dbo", table="Users", column="SSN", pii_type="SSN", confidence=0.99),
        PIIColumn(schema="dbo", table="Orders", column="CreditCard", pii_type="CREDIT_CARD", confidence=0.97)
    ]


class TestEndToEndWorkflow:
    """Integration tests for end-to-end workflows."""
    
    @patch("src.ui.review_cli.Prompt.ask")
    @patch("src.ui.review_cli.Confirm.ask")
    def test_accept_all_ai_recommendations(
        self,
        mock_confirm,
        mock_prompt,
        mock_schema_extractor,
        ai_detected_pii,
        tmp_path
    ):
        """Test workflow: Accept all AI recommendations and save."""
        # User chooses to save immediately
        mock_prompt.return_value = "s"
        
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        final_configs = cli.review_recommendations(ai_detected_pii)
        
        assert len(final_configs) == 4
        assert all(isinstance(cfg, PIIColumnConfig) for cfg in final_configs)
        assert final_configs[0].column == "Email"
        assert final_configs[1].column == "PhoneNumber"
        assert final_configs[2].column == "SSN"
        assert final_configs[3].column == "CreditCard"
    
    @patch("src.ui.review_cli.Prompt.ask")
    @patch("src.ui.review_cli.Confirm.ask")
    def test_add_manual_column_workflow(
        self,
        mock_confirm,
        mock_prompt,
        mock_schema_extractor,
        ai_detected_pii
    ):
        """Test workflow: Add manual column, then save."""
        # Simulate: Add -> inputs -> then Save
        mock_prompt.side_effect = [
            "a",  # Choose add
            "dbo",  # Schema
            "Users",  # Table
            "DateOfBirth",  # Column (not in mock, will get warning)
            "7",  # DATE_OF_BIRTH
            "s"  # Save
        ]
        mock_confirm.side_effect = [
            True,  # Nullable
            True  # Continue despite warning (column not validated)
        ]
        
        # Mock validation to allow non-existent column for this test
        with patch.object(
            PIIReviewCLI,
            "_validate_column",
            return_value=([], [])  # No errors or warnings
        ):
            cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
            final_configs = cli.review_recommendations(ai_detected_pii)
        
        # Should have 4 AI + 1 manual = 5 total
        assert len(final_configs) == 5
        assert cli.stats["manually_added"] == 1
    
    @patch("src.ui.review_cli.Prompt.ask")
    @patch("src.ui.review_cli.Confirm.ask")
    def test_remove_column_workflow(
        self,
        mock_confirm,
        mock_prompt,
        mock_schema_extractor,
        ai_detected_pii
    ):
        """Test workflow: Remove a column, then save."""
        # Simulate: Remove -> select column 2 -> Save
        mock_prompt.side_effect = [
            "r",  # Remove
            "2",  # Select second column (PhoneNumber)
            "s"  # Save
        ]
        
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        final_configs = cli.review_recommendations(ai_detected_pii)
        
        # Should have 4 - 1 = 3 total
        assert len(final_configs) == 3
        assert cli.stats["removed"] == 1
        # Verify PhoneNumber is removed
        assert not any(cfg.column == "PhoneNumber" for cfg in final_configs)
    
    @patch("src.ui.review_cli.Prompt.ask")
    @patch("src.ui.review_cli.Confirm.ask")
    def test_modify_column_workflow(
        self,
        mock_confirm,
        mock_prompt,
        mock_schema_extractor,
        ai_detected_pii
    ):
        """Test workflow: Modify a column, then save."""
        # Simulate: Modify -> select column 1 -> change type -> Save
        mock_prompt.side_effect = [
            "m",  # Modify
            "1",  # Select first column (Email)
            "2",  # Change PII type to PHONE
            "s"  # Save
        ]
        mock_confirm.side_effect = [
            True,  # Change PII type?
            False  # Change nullable?
        ]
        
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        final_configs = cli.review_recommendations(ai_detected_pii)
        
        assert len(final_configs) == 4
        assert cli.stats["modified"] == 1
        # Verify Email column is modified
        email_cfg = next(cfg for cfg in final_configs if cfg.column == "Email")
        assert email_cfg.pii_type == "PHONE"  # Changed from EMAIL
    
    @patch("src.ui.review_cli.Prompt.ask")
    @patch("src.ui.review_cli.Confirm.ask")
    def test_undo_workflow(
        self,
        mock_confirm,
        mock_prompt,
        mock_schema_extractor,
        ai_detected_pii
    ):
        """Test workflow: Remove, undo, then save."""
        # Simulate: Remove -> select column 1 -> Undo -> Save
        mock_prompt.side_effect = [
            "r",  # Remove
            "1",  # Select first column
            "u",  # Undo
            "s"  # Save
        ]
        
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        final_configs = cli.review_recommendations(ai_detected_pii)
        
        # Undo should restore, so back to 4
        assert len(final_configs) == 4
        assert cli.stats["removed"] == 0  # Undo decremented counter
    
    @patch("src.ui.review_cli.Prompt.ask")
    @patch("src.ui.review_cli.Confirm.ask")
    def test_quit_without_saving(
        self,
        mock_confirm,
        mock_prompt,
        mock_schema_extractor,
        ai_detected_pii
    ):
        """Test workflow: Quit without saving."""
        # Simulate: Quit -> confirm
        mock_prompt.return_value = "q"
        mock_confirm.return_value = True  # Confirm quit
        
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        final_configs = cli.review_recommendations(ai_detected_pii)
        
        # Should return empty list
        assert final_configs == []
    
    @patch("src.ui.review_cli.Prompt.ask")
    def test_keyboard_interrupt_handling(
        self,
        mock_prompt,
        mock_schema_extractor,
        ai_detected_pii
    ):
        """Test workflow: Handle Ctrl+C gracefully."""
        # Simulate user pressing Ctrl+C
        mock_prompt.side_effect = KeyboardInterrupt()
        
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        final_configs = cli.review_recommendations(ai_detected_pii)
        
        # Should handle gracefully and return empty
        assert final_configs == []


class TestSchemaValidationIntegration:
    """Integration tests for schema validation."""
    
    @patch("src.ui.review_cli.Prompt.ask")
    @patch("src.ui.review_cli.Confirm.ask")
    def test_validation_blocks_nonexistent_column(
        self,
        mock_confirm,
        mock_prompt,
        mock_schema_extractor
    ):
        """Test that validation prevents adding nonexistent column."""
        # Simulate: Add -> inputs for nonexistent column
        mock_prompt.side_effect = [
            "a",  # Add
            "dbo",  # Schema
            "Users",  # Table
            "NonExistent",  # Column (doesn't exist)
            "s"  # Save after error
        ]
        
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        
        # Mock the _handle_add to capture validation
        original_handle_add = cli._handle_add
        add_called = []
        
        def tracked_handle_add():
            add_called.append(True)
            original_handle_add()
        
        cli._handle_add = tracked_handle_add
        
        # Start with empty AI recommendations
        final_configs = cli.review_recommendations([])
        
        # Should not have added the invalid column
        assert len(final_configs) == 0
        assert cli.stats["manually_added"] == 0
    
    @patch("src.ui.review_cli.Prompt.ask")
    @patch("src.ui.review_cli.Confirm.ask")
    def test_validation_warns_primary_key(
        self,
        mock_confirm,
        mock_prompt,
        mock_schema_extractor
    ):
        """Test that validation warns when adding primary key column."""
        # Simulate: Add -> UserID (primary key) -> accept warning
        mock_prompt.side_effect = [
            "a",  # Add
            "dbo",  # Schema
            "Users",  # Table
            "UserID",  # Column (is primary key)
            "1",  # EMAIL type
            "s"  # Save
        ]
        mock_confirm.side_effect = [
            True,  # Accept warning
            False  # Not nullable
        ]
        
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        final_configs = cli.review_recommendations([])
        
        # Should allow adding despite warning
        assert len(final_configs) == 1
        assert final_configs[0].column == "UserID"
    
    @patch("src.ui.review_cli.Prompt.ask")
    @patch("src.ui.review_cli.Confirm.ask")
    def test_validation_warns_foreign_key(
        self,
        mock_confirm,
        mock_prompt,
        mock_schema_extractor
    ):
        """Test that validation warns when adding foreign key column."""
        # Simulate: Add -> CustomerID (foreign key) -> reject warning
        mock_prompt.side_effect = [
            "a",  # Add
            "dbo",  # Schema
            "Orders",  # Table
            "CustomerID",  # Column (is foreign key)
            "s"  # Save after rejection
        ]
        mock_confirm.side_effect = [
            False  # Reject warning, don't add
        ]
        
        cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
        final_configs = cli.review_recommendations([])
        
        # Should not add due to rejection
        assert len(final_configs) == 0


class TestConfigPersistence:
    """Integration tests for configuration persistence."""
    
    def test_save_and_reload_config(
        self,
        tmp_path,
        ai_detected_pii
    ):
        """Test saving config and reloading it."""
        output_path = tmp_path / "pii_config.json"
        
        # Mock to save immediately
        with patch("src.ui.review_cli.Prompt.ask") as mock_prompt:
            mock_prompt.return_value = "s"
            
            cli = PIIReviewCLI()
            final_configs = cli.review_recommendations(ai_detected_pii)
            cli.save_to_file(output_path)
        
        # Reload and verify
        assert output_path.exists()
        with output_path.open("r") as f:
            data = json.load(f)
        
        assert len(data) == 4
        assert data[0]["schema"] == "dbo"
        assert data[0]["table"] == "Users"
        assert data[0]["column"] == "Email"
        assert data[0]["pii_type"] == "EMAIL"
        assert data[0]["nullable"] is True
    
    def test_merge_with_existing_config(
        self,
        mock_schema_extractor,
        ai_detected_pii
    ):
        """Test merging AI recommendations with existing config."""
        existing_config = [
            PIIColumnConfig(
                schema="dbo",
                table="Customers",
                column="Address",
                pii_type="ADDRESS",
                nullable=True
            )
        ]
        
        with patch("src.ui.review_cli.Prompt.ask") as mock_prompt:
            mock_prompt.return_value = "s"
            
            cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
            final_configs = cli.review_recommendations(ai_detected_pii, existing_config)
        
        # Should have 4 AI + 1 existing = 5 total
        assert len(final_configs) == 5
        assert any(cfg.column == "Address" for cfg in final_configs)
    
    def test_duplicate_prevention_with_existing(
        self,
        mock_schema_extractor
    ):
        """Test that duplicates are prevented when merging."""
        ai_pii = [
            PIIColumn(schema="dbo", table="Users", column="Email", pii_type="EMAIL", confidence=0.95)
        ]
        
        existing_config = [
            PIIColumnConfig(schema="dbo", table="Users", column="Email", pii_type="PHONE", nullable=False)
        ]
        
        with patch("src.ui.review_cli.Prompt.ask") as mock_prompt:
            mock_prompt.return_value = "s"
            
            cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
            final_configs = cli.review_recommendations(ai_pii, existing_config)
        
        # Should have only 1 (duplicate not added)
        assert len(final_configs) == 1


class TestComplexWorkflows:
    """Integration tests for complex multi-step workflows."""
    
    @patch("src.ui.review_cli.Prompt.ask")
    @patch("src.ui.review_cli.Confirm.ask")
    def test_complex_workflow(
        self,
        mock_confirm,
        mock_prompt,
        mock_schema_extractor,
        ai_detected_pii,
        tmp_path
    ):
        """Test complex workflow: Add, Remove, Modify, Undo, Save."""
        # Simulate: Add -> Remove -> Modify -> Undo modify -> Save
        mock_prompt.side_effect = [
            "a",  # Add
            "dbo",  # Schema
            "Users",  # Table
            "DateOfBirth",  # Column
            "7",  # DATE_OF_BIRTH
            "r",  # Remove
            "2",  # Remove PhoneNumber (index 2 after add)
            "m",  # Modify
            "1",  # Modify Email
            "2",  # Change to PHONE
            "u",  # Undo modify
            "s"  # Save
        ]
        mock_confirm.side_effect = [
            True,  # Nullable for add
            True,  # Change PII type
            False  # Don't change nullable
        ]
        
        # Mock validation for DateOfBirth
        with patch.object(
            PIIReviewCLI,
            "_validate_column",
            return_value=([], [])
        ):
            cli = PIIReviewCLI(schema_extractor=mock_schema_extractor)
            final_configs = cli.review_recommendations(ai_detected_pii)
        
        # 4 AI + 1 added - 1 removed = 4, undo restored Email
        assert len(final_configs) == 4
        
        # Verify PhoneNumber is removed
        assert not any(cfg.column == "PhoneNumber" for cfg in final_configs)
        
        # Verify Email is back to EMAIL (undo worked)
        email_cfg = next((cfg for cfg in final_configs if cfg.column == "Email"), None)
        assert email_cfg is not None
        assert email_cfg.pii_type == "EMAIL"  # Restored by undo


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
