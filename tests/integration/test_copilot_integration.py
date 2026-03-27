"""
Integration tests for GitHub Copilot API client.

These tests verify end-to-end integration with:
- Configuration loading
- Schema extraction
- AI API interaction (mocked)
- Complete workflow from schema to PII recommendations

Note: Real API calls are optional and require GITHUB_COPILOT_API_KEY.

Author: Database Sanitization Team
Date: 2026-03-26
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, Mock

from src.config import ConfigLoader, AIConfig
from src.ai import CopilotClient, PIIColumn
from src.exceptions import APIRequestError


# ==================== Fixtures ====================


@pytest.fixture
def ai_config():
    """Create AI configuration for testing."""
    return AIConfig(
        enabled=True,
        api_url="https://api.test.com/copilot",
        timeout_seconds=30,
        cache_enabled=True,
        cache_ttl_hours=1
    )


@pytest.fixture
def sample_schema():
    """Create realistic schema metadata."""
    return {
        "database": "TestDB",
        "server": "localhost",
        "tables": [
            {
                "schema": "dbo",
                "name": "Users",
                "columns": [
                    {"name": "UserID", "data_type": "INT", "nullable": False, "is_primary_key": True},
                    {"name": "Email", "data_type": "NVARCHAR", "max_length": 100, "nullable": False},
                    {"name": "Phone", "data_type": "VARCHAR", "max_length": 20, "nullable": True},
                    {"name": "FirstName", "data_type": "NVARCHAR", "max_length": 50, "nullable": False},
                    {"name": "LastName", "data_type": "NVARCHAR", "max_length": 50, "nullable": False},
                ]
            },
            {
                "schema": "dbo",
                "name": "Orders",
                "columns": [
                    {"name": "OrderID", "data_type": "INT", "nullable": False, "is_primary_key": True},
                    {"name": "UserID", "data_type": "INT", "nullable": False},
                    {"name": "OrderDate", "data_type": "DATETIME2", "nullable": False},
                ]
            }
        ]
    }


@pytest.fixture
def mock_api_response():
    """Create mock API response."""
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "pii_columns": [
                        {
                            "schema": "dbo",
                            "table": "Users",
                            "column": "Email",
                            "pii_type": "email",
                            "confidence": 0.98,
                            "reason": "Column name 'Email' strongly indicates email addresses"
                        },
                        {
                            "schema": "dbo",
                            "table": "Users",
                            "column": "Phone",
                            "pii_type": "phone",
                            "confidence": 0.95,
                            "reason": "Column name 'Phone' indicates phone numbers"
                        },
                        {
                            "schema": "dbo",
                            "table": "Users",
                            "column": "FirstName",
                            "pii_type": "name",
                            "confidence": 0.99
                        },
                        {
                            "schema": "dbo",
                            "table": "Users",
                            "column": "LastName",
                            "pii_type": "name",
                            "confidence": 0.99
                        }
                    ]
                })
            }
        }]
    }
    return mock_resp


# ==================== Integration Tests ====================


def test_end_to_end_pii_detection(ai_config, sample_schema, mock_api_response, tmp_path):
    """Test complete PII detection workflow."""
    with patch.dict('os.environ', {'GITHUB_COPILOT_API_KEY': 'test_api_key'}):
        # Initialize client
        client = CopilotClient(
            api_url=ai_config.api_url,
            timeout_seconds=ai_config.timeout_seconds,
            cache_enabled=ai_config.cache_enabled,
            cache_ttl_hours=ai_config.cache_ttl_hours
        )
        client.cache_dir = tmp_path / "cache"
        client.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Mock API call
        with patch.object(client.session, 'post', return_value=mock_api_response):
            # Detect PII
            pii_columns = client.detect_pii(sample_schema)
            
            # Verify results
            assert len(pii_columns) == 4
            assert all(isinstance(col, PIIColumn) for col in pii_columns)
            
            # Verify specific columns
            email_col = next(c for c in pii_columns if c.column == "Email")
            assert email_col.pii_type == "email"
            assert email_col.confidence == 0.98
            assert email_col.reason is not None
            
            name_cols = [c for c in pii_columns if c.pii_type == "name"]
            assert len(name_cols) == 2


def test_configuration_loading_with_ai_section(tmp_path):
    """Test loading configuration with AI section."""
    config_data = {
        "database": {
            "server": "localhost",
            "database": "TestDB",
            "auth_type": "windows",
            "batch_size": 10000
        },
        "ai": {
            "enabled": True,
            "api_url": "https://custom.api.com",
            "timeout_seconds": 60,
            "cache_enabled": False
        },
        "pii_columns": [],
        "dry_run": True
    }
    
    config_file = tmp_path / "test_config.json"
    with open(config_file, 'w') as f:
        json.dump(config_data, f)
    
    # Load configuration
    loader = ConfigLoader()
    config = loader.load_from_files([config_file])
    
    # Verify AI configuration
    assert config.ai is not None
    assert config.ai.enabled is True
    assert config.ai.api_url == "https://custom.api.com"
    assert config.ai.timeout_seconds == 60
    assert config.ai.cache_enabled is False


def test_workflow_schema_to_config_file(ai_config, sample_schema, mock_api_response, tmp_path):
    """Test complete workflow: schema → AI → config file."""
    with patch.dict('os.environ', {'GITHUB_COPILOT_API_KEY': 'test_key'}):
        # Initialize client
        client = CopilotClient(
            api_url=ai_config.api_url,
            cache_enabled=False  # Disable cache for test
        )
        
        # Mock API
        with patch.object(client.session, 'post', return_value=mock_api_response):
            # Detect PII
            pii_columns = client.detect_pii(sample_schema)
            
            # Convert to config format
            pii_configs = []
            for col in pii_columns:
                pii_configs.append({
                    "schema": col.schema,
                    "table": col.table,
                    "column": col.column,
                    "pii_type": col.pii_type,
                    "nullable": True  # Would need schema metadata to set correctly
                })
            
            # Save to file
            output_file = tmp_path / "generated_config.json"
            output_data = {
                "database": {
                    "server": "localhost",
                    "database": "TestDB",
                    "auth_type": "windows",
                    "batch_size": 10000
                },
                "pii_columns": pii_configs,
                "dry_run": True
            }
            
            with open(output_file, 'w') as f:
                json.dump(output_data, f, indent=2)
            
            # Verify file created
            assert output_file.exists()
            
            # Reload and verify
            with open(output_file, 'r') as f:
                reloaded = json.load(f)
            
            assert len(reloaded["pii_columns"]) == 4
            assert any(c["column"] == "Email" for c in reloaded["pii_columns"])


def test_client_without_api_key_graceful_degradation(sample_schema):
    """Test client gracefully handles missing API key."""
    with patch.dict('os.environ', {}, clear=True):
        client = CopilotClient()
        
        # Should return empty list, not raise exception
        pii_columns = client.detect_pii(sample_schema)
        
        assert pii_columns == []


def test_api_error_handling_integration(ai_config, sample_schema, tmp_path):
    """Test error handling in integrated workflow."""
    with patch.dict('os.environ', {'GITHUB_COPILOT_API_KEY': 'test_key'}):
        client = CopilotClient(
            api_url=ai_config.api_url,
            cache_enabled=False
        )
        
        # Mock API failure
        error_response = Mock()
        error_response.status_code = 500
        error_response.raise_for_status.side_effect = Exception("Server error")
        
        with patch.object(client.session, 'post', return_value=error_response):
            # Should raise appropriate exception
            with pytest.raises(Exception):  # Will be caught by retry logic
                client._make_api_request(
                    {"system": "test", "user": "test"},
                    "correlation_id"
                )


@pytest.mark.skipif(
    not os.getenv("GITHUB_COPILOT_API_KEY"),
    reason="Requires GITHUB_COPILOT_API_KEY environment variable"
)
def test_real_api_call(sample_schema):
    """Test real API call (optional, requires API key)."""
    client = CopilotClient(
        timeout_seconds=60,
        cache_enabled=False  # Don't cache for testing
    )
    
    try:
        pii_columns = client.detect_pii(sample_schema)
        
        # Verify we got some results
        assert isinstance(pii_columns, list)
        # Exact results may vary, but should detect at least email/phone
        
    except APIRequestError as e:
        pytest.skip(f"API call failed: {e}")


# ==================== Performance Tests ====================


def test_large_schema_performance(ai_config, mock_api_response, tmp_path):
    """Test performance with large schema (100+ tables)."""
    import time
    
    # Generate large schema
    large_schema = {
        "database": "LargeDB",
        "tables": [
            {
                "schema": "dbo",
                "name": f"Table_{i}",
                "columns": [
                    {"name": "ID", "data_type": "INT"},
                    {"name": "Data", "data_type": "NVARCHAR", "max_length": 100}
                ]
            }
            for i in range(100)
        ]
    }
    
    with patch.dict('os.environ', {'GITHUB_COPILOT_API_KEY': 'test_key'}):
        client = CopilotClient(
            api_url=ai_config.api_url,
            max_tables_per_request=50,
            cache_enabled=False
        )
        
        with patch.object(client.session, 'post', return_value=mock_api_response):
            start_time = time.time()
            pii_columns = client.detect_pii(large_schema)
            duration = time.time() - start_time
            
            # Should complete in reasonable time (mocked, so should be fast)
            assert duration < 5.0  # Generous limit for mocked calls
            assert isinstance(pii_columns, list)


# ==================== Cache Persistence Tests ====================


def test_cache_persistence_across_instances(ai_config, sample_schema, mock_api_response, tmp_path):
    """Test cache persists across different client instances."""
    cache_dir = tmp_path / "shared_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    with patch.dict('os.environ', {'GITHUB_COPILOT_API_KEY': 'test_key'}):
        # First client - populate cache
        client1 = CopilotClient(
            api_url=ai_config.api_url,
            cache_enabled=True,
            cache_ttl_hours=24
        )
        client1.cache_dir = cache_dir
        
        with patch.object(client1.session, 'post', return_value=mock_api_response) as mock_post1:
            pii_columns1 = client1.detect_pii(sample_schema)
            assert mock_post1.call_count == 1
        
        # Second client - should use persisted cache
        client2 = CopilotClient(
            api_url=ai_config.api_url,
            cache_enabled=True,
            cache_ttl_hours=24
        )
        client2.cache_dir = cache_dir
        
        with patch.object(client2.session, 'post', return_value=mock_api_response) as mock_post2:
            pii_columns2 = client2.detect_pii(sample_schema)
            assert mock_post2.call_count == 0  # Should not make API call
        
        # Results should match
        assert len(pii_columns1) == len(pii_columns2)
