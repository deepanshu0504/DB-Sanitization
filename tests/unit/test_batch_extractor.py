"""
Unit tests for BatchExtractor with comprehensive edge case coverage.

Tests cover:
- Pagination strategy selection
- Key-based extraction (single numeric PK)
- Composite key extraction (multi-column PK)
- ROW_NUMBER extraction (no suitable PK)
- Edge cases (empty tables, NULL values, special characters, etc.)
- Error handling and validation

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from typing import List, Any, Dict

from src.database.batch_extractor import (
    BatchExtractor,
    Batch,
    PaginationStrategy,
)
from src.database.connection_manager import DatabaseConnectionManager
from src.database.schema_extractor import SchemaExtractor
from src.exceptions import DataExtractionError


# ==================== Fixtures ====================


@pytest.fixture
def mock_connection_manager():
    """Create a mocked ConnectionConnectionManager."""
    mock_mgr = Mock(spec=DatabaseConnectionManager)
    mock_mgr.config = Mock()
    mock_mgr.config.database = "TestDB"
    return mock_mgr


@pytest.fixture
def mock_schema_extractor():
    """Create a mocked SchemaExtractor."""
    return Mock(spec=SchemaExtractor)


@pytest.fixture
def batch_extractor(mock_connection_manager, mock_schema_extractor):
    """Create a BatchExtractor instance with mocked dependencies."""
    return BatchExtractor(
        connection_manager=mock_connection_manager,
        schema_extractor=mock_schema_extractor,
        batch_size=10,  # Small batch size for testing
    )


def create_mock_schema(tables: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Helper to create schema metadata."""
    return {
        "tables": tables,
        "database_name": "TestDB",
        "extraction_timestamp": "2026-03-26T12:00:00",
    }


# ==================== Initialization Tests ====================


def test_batch_extractor_initialization_valid(mock_connection_manager, mock_schema_extractor):
    """Test valid BatchExtractor initialization."""
    extractor = BatchExtractor(mock_connection_manager, mock_schema_extractor, batch_size=5000)
    assert extractor.batch_size == 5000
    assert extractor.max_batch_size == 100000
    assert extractor.connection_manager == mock_connection_manager
    assert extractor.schema_extractor == mock_schema_extractor


def test_batch_extractor_initialization_default_batch_size(mock_connection_manager, mock_schema_extractor):
    """Test default batch size."""
    extractor = BatchExtractor(mock_connection_manager, mock_schema_extractor)
    assert extractor.batch_size == 10000


def test_batch_extractor_initialization_invalid_batch_size_too_small(
    mock_connection_manager, mock_schema_extractor
):
    """Test initialization fails with batch size < 1."""
    with pytest.raises(DataExtractionError) as exc_info:
        BatchExtractor(mock_connection_manager, mock_schema_extractor, batch_size=0)
    assert "Invalid batch size" in str(exc_info.value)


def test_batch_extractor_initialization_invalid_batch_size_too_large(
    mock_connection_manager, mock_schema_extractor
):
    """Test initialization fails with batch size > 100,000."""
    with pytest.raises(DataExtractionError) as exc_info:
        BatchExtractor(mock_connection_manager, mock_schema_extractor, batch_size=100001)
    assert "Invalid batch size" in str(exc_info.value)


# ==================== Batch Dataclass Tests ====================


def test_batch_progress_percentage():
    """Test progress percentage calculation."""
    batch = Batch(
        rows=[{"id": 1}, {"id": 2}],
        batch_number=1,
        total_rows_in_batch=2,
        rows_processed=50,
        total_rows=100,
        schema_name="dbo",
        table_name="Users",
        columns=["id"],
        strategy=PaginationStrategy.KEY_BASED,
    )
    assert batch.progress_percentage == pytest.approx(50.0)


def test_batch_progress_percentage_zero_total():
    """Test progress percentage with zero total rows."""
    batch = Batch(
        rows=[],
        batch_number=1,
        total_rows_in_batch=0,
        rows_processed=0,
        total_rows=0,
        schema_name="dbo",
        table_name="Empty",
        columns=["id"],
        strategy=PaginationStrategy.ROW_NUMBER,
    )
    assert batch.progress_percentage == pytest.approx(0.0)


def test_batch_is_last_batch():
    """Test is_last_batch property."""
    batch = Batch(
        rows=[{"id": 10}],
        batch_number=2,
        total_rows_in_batch=1,
        rows_processed=10,
        total_rows=10,
        schema_name="dbo",
        table_name="Users",
        columns=["id"],
        strategy=PaginationStrategy.KEY_BASED,
    )
    assert batch.is_last_batch is True


def test_batch_full_table_name():
    """Test full_table_name property."""
    batch = Batch(
        rows=[],
        batch_number=1,
        total_rows_in_batch=0,
        rows_processed=0,
        total_rows=0,
        schema_name="custom_schema",
        table_name="SomeTable",
        columns=["col1"],
        strategy=PaginationStrategy.COMPOSITE_KEY,
    )
    assert batch.full_table_name == "custom_schema.SomeTable"


# ==================== Pagination Strategy Selection Tests ====================


def test_select_pagination_strategy_key_based_single_int_pk(
    batch_extractor, mock_schema_extractor
):
    """Test KEY_BASED selected for single INT PK."""
    schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [
                {"name": "UserID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
            ],
        }
    ])
    mock_schema_extractor.extract_schema.return_value = schema
    
    strategy = batch_extractor._select_pagination_strategy("dbo", "Users", ["UserID"])
    assert strategy == PaginationStrategy.KEY_BASED


def test_select_pagination_strategy_key_based_bigint_pk(
    batch_extractor, mock_schema_extractor
):
    """Test KEY_BASED selected for single BIGINT PK."""
    schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Orders",
            "columns": [
                {"name": "OrderID", "data_type": "bigint"},
                {"name": "Amount", "data_type": "decimal"},
            ],
        }
    ])
    mock_schema_extractor.extract_schema.return_value = schema
    
    strategy = batch_extractor._select_pagination_strategy("dbo", "Orders", ["OrderID"])
    assert strategy == PaginationStrategy.KEY_BASED


def test_select_pagination_strategy_composite_key_two_columns(
    batch_extractor, mock_schema_extractor
):
    """Test COMPOSITE_KEY selected for 2-column PK."""
    strategy = batch_extractor._select_pagination_strategy(
        "dbo", "OrderDetails", ["OrderID", "ProductID"]
    )
    assert strategy == PaginationStrategy.COMPOSITE_KEY


def test_select_pagination_strategy_composite_key_three_columns(
    batch_extractor, mock_schema_extractor
):
    """Test COMPOSITE_KEY selected for 3-column PK."""
    strategy = batch_extractor._select_pagination_strategy(
        "dbo", "MultiKey", ["Key1", "Key2", "Key3"]
    )
    assert strategy == PaginationStrategy.COMPOSITE_KEY


def test_select_pagination_strategy_row_number_no_pk(
    batch_extractor, mock_schema_extractor
):
    """Test ROW_NUMBER selected when no PK exists."""
    strategy = batch_extractor._select_pagination_strategy("dbo", "NoPKTable", [])
    assert strategy == PaginationStrategy.ROW_NUMBER


def test_select_pagination_strategy_row_number_guid_pk(
    batch_extractor, mock_schema_extractor
):
    """Test ROW_NUMBER selected for GUID PK."""
    schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "GuidTable",
            "columns": [
                {"name": "ID", "data_type": "uniqueidentifier"},
                {"name": "Name", "data_type": "nvarchar"},
            ],
        }
    ])
    mock_schema_extractor.extract_schema.return_value = schema
    
    strategy = batch_extractor._select_pagination_strategy("dbo", "GuidTable", ["ID"])
    assert strategy == PaginationStrategy.ROW_NUMBER


def test_select_pagination_strategy_row_number_string_pk(
    batch_extractor, mock_schema_extractor
):
    """Test ROW_NUMBER selected for string PK."""
    schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "StringTable",
            "columns": [
                {"name": "Code", "data_type": "varchar"},
                {"name": "Description", "data_type": "nvarchar"},
            ],
        }
    ])
    mock_schema_extractor.extract_schema.return_value = schema
    
    strategy = batch_extractor._select_pagination_strategy("dbo", "StringTable", ["Code"])
    assert strategy == PaginationStrategy.ROW_NUMBER


# ==================== Row Count Tests ====================


def test_get_row_count_valid_table(batch_extractor, mock_connection_manager):
    """Test getting row count for valid table."""
    mock_connection_manager.execute_query.return_value = [[100]]  # 100 rows
    
    count = batch_extractor._get_row_count("dbo", "Users")
    
    assert count == 100
    mock_connection_manager.execute_query.assert_called_once()
    call_args = mock_connection_manager.execute_query.call_args[0]
    assert "[dbo].[Users]" in call_args[0]
    assert "COUNT(*)" in call_args[0]


def test_get_row_count_empty_table(batch_extractor, mock_connection_manager):
    """Test getting row count for empty table."""
    mock_connection_manager.execute_query.return_value = [[0]]
    
    count = batch_extractor._get_row_count("dbo", "Empty")
    
    assert count == 0


def test_get_row_count_table_not_found(batch_extractor, mock_connection_manager):
    """Test table not found raises appropriate error."""
    from src.exceptions import DatabaseQueryError
    
    mock_connection_manager.execute_query.side_effect = DatabaseQueryError(
        message="Invalid object name 'dbo.NonExistent'",
        error_code="QUERY_FAILED",
    )
    
    with pytest.raises(DataExtractionError) as exc_info:
        batch_extractor._get_row_count("dbo", "NonExistent")
    
    assert "not found" in str(exc_info.value).lower()


# ==================== Column Validation Tests ====================


def test_validate_columns_exist_valid_columns(batch_extractor, mock_schema_extractor):
    """Test validation passes for existing columns."""
    schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [
                {"name": "UserID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
                {"name": "Phone", "data_type": "nvarchar"},
            ],
        }
    ])
    mock_schema_extractor.extract_schema.return_value = schema
    
    # Should not raise any exception
    batch_extractor._validate_columns_exist("dbo", "Users", ["Email", "Phone"])


def test_validate_columns_exist_column_not_found(batch_extractor, mock_schema_extractor):
    """Test validation fails for non-existent column."""
    schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [
                {"name": "UserID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
            ],
        }
    ])
    mock_schema_extractor.extract_schema.return_value = schema
    
    with pytest.raises(DataExtractionError) as exc_info:
        batch_extractor._validate_columns_exist("dbo", "Users", ["Email", "NonExistentColumn"])
    
    assert "Column not found" in str(exc_info.value)
    assert "NonExistentColumn" in str(exc_info.value)


# ==================== Key-Based Extraction Tests ====================


def test_extract_key_based_single_batch(batch_extractor, mock_connection_manager):
    """Test key-based extraction with single batch."""
    # Mock query results (fewer rows than batch size)
    mock_connection_manager.execute_query.return_value = [
        (1, "user1@example.com"),
        (2, "user2@example.com"),
        (3, "user3@example.com"),
    ]
    
    batches = list(batch_extractor._extract_key_based(
        "dbo", "Users", ["Email"], "UserID", 3, "test-correlation-id"
    ))
    
    assert len(batches) == 1
    batch = batches[0]
    assert batch.batch_number == 1
    assert batch.total_rows_in_batch == 3
    assert batch.rows_processed == 3
    assert batch.total_rows == 3
    assert batch.strategy == PaginationStrategy.KEY_BASED
    assert len(batch.rows) == 3


def test_extract_key_based_multiple_batches(batch_extractor, mock_connection_manager):
    """Test key-based extraction with multiple batches."""
    # Configure batch size of 10
    batch_extractor.batch_size = 10
    
    # Mock two batches: first with 10 rows, second with 5 rows
    mock_connection_manager.execute_query.side_effect = [
        [(i, f"user{i}@example.com") for i in range(1, 11)],  # Batch 1: rows 1-10
        [(i, f"user{i}@example.com") for i in range(11, 16)],  # Batch 2: rows 11-15
    ]
    
    batches = list(batch_extractor._extract_key_based(
        "dbo", "Users", ["Email"], "UserID", 15, "test-correlation-id"
    ))
    
    assert len(batches) == 2
    
    # Check first batch
    assert batches[0].batch_number == 1
    assert batches[0].total_rows_in_batch == 10
    assert batches[0].rows_processed == 10
    assert batches[0].progress_percentage == pytest.approx(66.67, rel=0.1)
    
    # Check second batch
    assert batches[1].batch_number == 2
    assert batches[1].total_rows_in_batch == 5
    assert batches[1].rows_processed == 15
    assert batches[1].progress_percentage == pytest.approx(100.0)


def test_extract_key_based_with_gaps_in_pk(batch_extractor, mock_connection_manager):
    """Test key-based extraction handles gaps in PK sequence."""
    # Non-sequential PKs: 1, 5, 10, 100, 500
    mock_connection_manager.execute_query.return_value = [
        (1, "user1@example.com"),
        (5, "user5@example.com"),
        (10, "user10@example.com"),
        (100, "user100@example.com"),
        (500, "user500@example.com"),
    ]
    
    batches = list(batch_extractor._extract_key_based(
        "dbo", "Users", ["Email"], "UserID", 5, "test-correlation-id"
    ))
    
    assert len(batches) == 1
    assert batches[0].total_rows_in_batch == 5
    # Verify PK values (should preserve gaps)
    pk_values = [row["UserID"] for row in batches[0].rows]
    assert pk_values == [1, 5, 10, 100, 500]


def test_extract_key_based_empty_table(batch_extractor, mock_connection_manager):
    """Test key-based extraction from empty table."""
    mock_connection_manager.execute_query.return_value = []
    
    batches = list(batch_extractor._extract_key_based(
        "dbo", "Empty", ["Email"], "UserID", 0, "test-correlation-id"
    ))
    
    assert len(batches) == 0


# ==================== Composite Key Extraction Tests ====================


def test_extract_composite_key_two_columns(batch_extractor, mock_connection_manager):
    """Test composite key extraction with 2-column PK."""
    mock_connection_manager.execute_query.return_value = [
        (1, 10, 2),
        (1, 20, 5),
        (2, 10, 3),
    ]
    
    batches = list(batch_extractor._extract_composite_key(
        "dbo", "OrderDetails", ["Quantity"],
        ["OrderID", "ProductID"], 3, "test-correlation-id"
    ))
    
    assert len(batches) == 1
    assert batches[0].strategy == PaginationStrategy.COMPOSITE_KEY
    assert len(batches[0].rows) == 3
    
    # Verify row structure includes PK columns
    row = batches[0].rows[0]
    assert "OrderID" in row
    assert "ProductID" in row
    assert "Quantity" in row


def test_extract_composite_key_three_columns(batch_extractor, mock_connection_manager):
    """Test composite key extraction with 3-column PK."""
    mock_connection_manager.execute_query.return_value = [
        (1, 2, 3, "data1"),
        (1, 2, 4, "data2"),
    ]
    
    batches = list(batch_extractor._extract_composite_key(
        "dbo", "MultiKey", ["Data"],
        ["Key1", "Key2", "Key3"], 2, "test-correlation-id"
    ))
    
    assert len(batches) == 1
    assert len(batches[0].rows) == 2


def test_extract_composite_key_multiple_batches(batch_extractor, mock_connection_manager):
    """Test composite key extraction with multiple batches."""
    batch_extractor.batch_size = 2
    
    # Mock two batches
    mock_connection_manager.execute_query.side_effect = [
        [(1, 10, "A"), (1, 20, "B")],  # Batch 1
        [(2, 10, "C")],  # Batch 2 (partial)
    ]
    
    batches = list(batch_extractor._extract_composite_key(
        "dbo", "OrderDetails", ["Status"],
        ["OrderID", "ProductID"], 3, "test-correlation-id"
    ))
    
    assert len(batches) == 2
    assert batches[0].total_rows_in_batch == 2
    assert batches[1].total_rows_in_batch == 1


# ==================== ROW_NUMBER Extraction Tests ====================


def test_extract_row_number_single_batch(batch_extractor, mock_connection_manager):
    """Test ROW_NUMBER extraction with single batch."""
    mock_connection_manager.execute_query.return_value = [
        ("user1@example.com",),
        ("user2@example.com",),
        ("user3@example.com",),
    ]
    
    batches = list(batch_extractor._extract_row_number(
        "dbo", "Users", ["Email"], 3, "test-correlation-id"
    ))
    
    assert len(batches) == 1
    assert batches[0].strategy == PaginationStrategy.ROW_NUMBER
    assert batches[0].total_rows_in_batch == 3


def test_extract_row_number_multiple_batches(batch_extractor, mock_connection_manager):
    """Test ROW_NUMBER extraction with multiple batches."""
    batch_extractor.batch_size = 5
    
    mock_connection_manager.execute_query.side_effect = [
        [("email1",), ("email2",), ("email3",), ("email4",), ("email5",)],  # Batch 1
        [("email6",), ("email7",)],  # Batch 2 (partial)
    ]
    
    batches = list(batch_extractor._extract_row_number(
        "dbo", "Users", ["Email"], 7, "test-correlation-id"
    ))
    
    assert len(batches) == 2
    assert batches[0].rows_processed == 5
    assert batches[1].rows_processed == 7


def test_extract_row_number_empty_table(batch_extractor, mock_connection_manager):
    """Test ROW_NUMBER extraction from empty table."""
    mock_connection_manager.execute_query.return_value = []
    
    batches = list(batch_extractor._extract_row_number(
        "dbo", "Empty", ["Email"], 0, "test-correlation-id"
    ))
    
    assert len(batches) == 0


# ==================== End-to-End Extraction Tests ====================


def test_extract_batches_empty_table(batch_extractor, mock_connection_manager, mock_schema_extractor):
    """Test extract_batches with empty table yields nothing."""
    mock_connection_manager.execute_query.return_value = [[0]]  # Zero rows
    
    batches = list(batch_extractor.extract_batches("dbo", "Empty", ["Email"]))
    
    assert len(batches) == 0


def test_extract_batches_with_nulls_in_pii_columns(
    batch_extractor, mock_connection_manager, mock_schema_extractor
):
    """Test extraction includes NULL values in PII columns."""
    # Setup schema
    schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [
                {"name": "UserID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
            ],
            "primary_key": {"columns": ["UserID"], "name": "PK_Users"},
        }
    ])
    mock_schema_extractor.extract_schema.return_value = schema
    
    # Mock row count and data with NULL
    mock_connection_manager.execute_query.side_effect = [
        [[3]],  # Row count
        [(1, "user1@example.com"), (2, None), (3, "user3@example.com")],  # Data with NULL
    ]
    
    batches = list(batch_extractor.extract_batches("dbo", "Users", ["Email"]))
    
    assert len(batches) == 1
    assert batches[0].rows[1]["Email"] is None  # NULL preserved


def test_extract_batches_special_characters_in_table_name(
    batch_extractor, mock_connection_manager, mock_schema_extractor
):
    """Test extraction handles special characters in table names."""
    schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Order Details",  # Space in name
            "columns": [
                {"name": "OrderID", "data_type": "int"},
                {"name": "ProductID", "data_type": "int"},
            ],
            "primary_key": {"columns": ["OrderID", "ProductID"], "name": "PK_OrderDetails"},
        }
    ])
    mock_schema_extractor.extract_schema.return_value = schema
    
    mock_connection_manager.execute_query.side_effect = [
        [[2]],  # Row count
        [(1, 10), (1, 20)],  # Data
    ]
    
    batches = list(batch_extractor.extract_batches("dbo", "Order Details", ["ProductID"]))
    
    assert len(batches) == 1
    # Verify SQL used brackets
    calls = mock_connection_manager.execute_query.call_args_list
    assert any("[Order Details]" in str(call) for call in calls)


def test_extract_batches_non_dbo_schema(
    batch_extractor, mock_connection_manager, mock_schema_extractor
):
    """Test extraction from non-dbo schema."""
    schema = create_mock_schema([
        {
            "schema": "custom_schema",
            "name": "Customers",
            "columns": [
                {"name": "CustomerID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
            ],
            "primary_key": {"columns": ["CustomerID"], "name": "PK_Customers"},
        }
    ])
    mock_schema_extractor.extract_schema.return_value = schema
    
    mock_connection_manager.execute_query.side_effect = [
        [[1]],  # Row count
        [(1, "customer@example.com")],  # Data
    ]
    
    batches = list(batch_extractor.extract_batches("custom_schema", "Customers", ["Email"]))
    
    assert len(batches) == 1
    assert batches[0].schema_name == "custom_schema"
    # Verify SQL used custom schema
    calls = mock_connection_manager.execute_query.call_args_list
    assert any("[custom_schema].[Customers]" in str(call) for call in calls)


# ==================== Error Handling Tests ====================


def test_extract_batches_table_not_found(batch_extractor, mock_connection_manager):
    """Test appropriate error when table doesn't exist."""
    from src.exceptions import DatabaseQueryError
    
    mock_connection_manager.execute_query.side_effect = DatabaseQueryError(
        message="Invalid object name 'dbo.NonExistent'",
        error_code="QUERY_FAILED",
    )
    
    with pytest.raises(DataExtractionError) as exc_info:
        list(batch_extractor.extract_batches("dbo", "NonExistent", ["Email"]))
    
    assert "not found" in str(exc_info.value).lower()


def test_extract_batches_column_not_found(
    batch_extractor, mock_connection_manager, mock_schema_extractor
):
    """Test appropriate error when column doesn't exist."""
    schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Users",
            "columns": [
                {"name": "UserID", "data_type": "int"},
                {"name": "Email", "data_type": "nvarchar"},
            ],
        }
    ])
    mock_schema_extractor.extract_schema.return_value = schema
    
    mock_connection_manager.execute_query.return_value = [[10]]  # Row count
    
    with pytest.raises(DataExtractionError) as exc_info:
        list(batch_extractor.extract_batches("dbo", "Users", ["NonExistentColumn"]))
    
    assert "Column not found" in str(exc_info.value)


# ==================== Integration-style Tests ====================


def test_extract_batches_auto_detect_pk(
    batch_extractor, mock_connection_manager, mock_schema_extractor
):
    """Test auto-detection of primary key from schema."""
    schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Products",
            "columns": [
                {"name": "ProductID", "data_type": "int"},
                {"name": "Name", "data_type": "nvarchar"},
            ],
            "primary_key": {"columns": ["ProductID"], "name": "PK_Products"},
        }
    ])
    mock_schema_extractor.extract_schema.return_value = schema
    
    mock_connection_manager.execute_query.side_effect = [
        [[5]],  # Row count
        [(1, "Product1"), (2, "Product2"), (3, "Product3"), (4, "Product4"), (5, "Product5")],
    ]
    
    batches = list(batch_extractor.extract_batches("dbo", "Products", ["Name"]))
    
    assert len(batches) == 1
    # Should use KEY_BASED strategy for single INT PK
    assert batches[0].strategy == PaginationStrategy.KEY_BASED


def test_extract_batches_progress_tracking(
    batch_extractor, mock_connection_manager, mock_schema_extractor
):
    """Test progress tracking across multiple batches."""
    batch_extractor.batch_size = 3
    
    schema = create_mock_schema([
        {
            "schema": "dbo",
            "name": "Orders",
            "columns": [
                {"name": "OrderID", "data_type": "int"},
                {"name": "Amount", "data_type": "decimal"},
            ],
            "primary_key": {"columns": ["OrderID"], "name": "PK_Orders"},
        }
    ])
    mock_schema_extractor.extract_schema.return_value = schema
    
    mock_connection_manager.execute_query.side_effect = [
        [[7]],  # Row count: 7 rows total
        [(1, 100.0), (2, 200.0), (3, 300.0)],  # Batch 1: 3 rows
        [(4, 400.0), (5, 500.0), (6, 600.0)],  # Batch 2: 3 rows
        [(7, 700.0)],  # Batch 3: 1 row
    ]
    
    batches = list(batch_extractor.extract_batches("dbo", "Orders", ["Amount"]))
    
    assert len(batches) == 3
    
    # Check progress for each batch
    assert batches[0].rows_processed == 3
    assert batches[0].progress_percentage == pytest.approx(42.857, rel=0.1)
    
    assert batches[1].rows_processed == 6
    assert batches[1].progress_percentage == pytest.approx(85.714, rel=0.1)
    
    assert batches[2].rows_processed == 7
    assert batches[2].progress_percentage == pytest.approx(100.0)
    assert batches[2].is_last_batch is True
