"""
Unit tests for mapping_models.py data classes.

Tests cover:
- MappingEntry: Creation, validation, to_dict(), edge cases
- MappingBatch: Creation, validation, properties, progress calculation
- MappingStats: Creation, validation, duration calculation, averages

Test Organization:
- TestMappingEntry: MappingEntry creation and validation
- TestMappingEntryToDict: Serialization to dictionary
- TestMappingEntryEdgeCases: NULL values, empty strings, validation errors
- TestMappingBatch: MappingBatch creation and validation
- TestMappingBatchProperties: entry_count, progress_percent
- TestMappingBatchToDict: Serialization
- TestMappingStats: MappingStats creation and validation
- TestMappingStatsProperties: duration_seconds, avg_entries_per_table/column
- TestMappingStatsToDict: Serialization

Author: Database Sanitization Team
Date: 2026-03-27
"""

import pytest
from datetime import datetime, timedelta
from uuid import UUID, uuid4
import hashlib

from src.mapping.mapping_models import MappingEntry, MappingBatch, MappingStats


class TestMappingEntry:
    """Test MappingEntry dataclass."""
    
    def test_mapping_entry_creation(self):
        """Test creating a valid MappingEntry."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test_value").digest()
        
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="Users",
            column_name="email",
            original_value_hash=value_hash,
            original_value_encrypted=b"encrypted_data",
            masked_value="masked@example.com",
            data_type="VARCHAR(255)",
            is_null=False
        )
        
        assert entry.operation_id == operation_id
        assert entry.schema_name == "dbo"
        assert entry.table_name == "Users"
        assert entry.column_name == "email"
        assert entry.original_value_hash == value_hash
        assert entry.masked_value == "masked@example.com"
        assert entry.is_null is False
    
    def test_mapping_entry_with_null_value(self):
        """Test creating MappingEntry for NULL value."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"NULL").digest()
        
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="Orders",
            column_name="notes",
            original_value_hash=value_hash,
            original_value_encrypted=None,
            masked_value=None,
            data_type="NVARCHAR(MAX)",
            is_null=True
        )
        
        assert entry.is_null is True
        assert entry.masked_value is None
        assert entry.original_value_encrypted is None
    
    def test_mapping_entry_default_created_at(self):
        """Test that created_at defaults to current UTC time."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        before = datetime.utcnow()
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="Users",
            column_name="email",
            original_value_hash=value_hash,
            original_value_encrypted=None,
            masked_value="test@example.com",
            data_type="VARCHAR(255)",
            is_null=False
        )
        after = datetime.utcnow()
        
        assert before <= entry.created_at <= after
    
    def test_mapping_entry_validation_invalid_operation_id(self):
        """Test validation rejects non-UUID operation_id."""
        value_hash = hashlib.sha256(b"test").digest()
        
        with pytest.raises(ValueError, match="operation_id must be UUID"):
            MappingEntry(
                operation_id="not-a-uuid",  # Invalid
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value="test@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
    
    def test_mapping_entry_validation_empty_schema(self):
        """Test validation rejects empty schema_name."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        with pytest.raises(ValueError, match="schema_name.*cannot be empty"):
            MappingEntry(
                operation_id=operation_id,
                schema_name="",  # Empty
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value="test@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
    
    def test_mapping_entry_validation_empty_table(self):
        """Test validation rejects empty table_name."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        with pytest.raises(ValueError, match="table_name.*cannot be empty"):
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="",  # Empty
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value="test@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
    
    def test_mapping_entry_validation_empty_column(self):
        """Test validation rejects empty column_name."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        with pytest.raises(ValueError, match="column_name.*cannot be empty"):
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Users",
                column_name="",  # Empty
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value="test@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
    
    def test_mapping_entry_validation_invalid_hash_length(self):
        """Test validation rejects hash not 32 bytes."""
        operation_id = uuid4()
        
        with pytest.raises(ValueError, match="original_value_hash must be 32 bytes"):
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=b"short_hash",  # Not 32 bytes
                original_value_encrypted=None,
                masked_value="test@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
    
    def test_mapping_entry_validation_null_with_masked_value(self):
        """Test validation rejects is_null=True with non-None masked_value."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"NULL").digest()
        
        with pytest.raises(ValueError, match="masked_value must be None when is_null is True"):
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value="should_be_none",  # Conflict with is_null=True
                data_type="VARCHAR(255)",
                is_null=True
            )
    
    def test_mapping_entry_validation_not_null_without_masked_value(self):
        """Test validation rejects is_null=False with None masked_value."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        with pytest.raises(ValueError, match="masked_value cannot be None when is_null is False"):
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value=None,  # Conflict with is_null=False
                data_type="VARCHAR(255)",
                is_null=False
            )


class TestMappingEntryToDict:
    """Test MappingEntry.to_dict() method."""
    
    def test_to_dict_basic(self):
        """Test to_dict() with basic entry."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        created_at = datetime(2026, 3, 27, 10, 0, 0)
        
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="Users",
            column_name="email",
            original_value_hash=value_hash,
            original_value_encrypted=b"encrypted",
            masked_value="masked@example.com",
            data_type="VARCHAR(255)",
            is_null=False,
            created_at=created_at
        )
        
        result = entry.to_dict()
        
        assert result["operation_id"] == str(operation_id)
        assert result["schema_name"] == "dbo"
        assert result["table_name"] == "Users"
        assert result["column_name"] == "email"
        assert result["original_value_hash"] == value_hash.hex()
        assert result["original_value_encrypted"] == b"encrypted".hex()
        assert result["masked_value"] == "masked@example.com"
        assert result["data_type"] == "VARCHAR(255)"
        assert result["is_null"] is False
        assert result["created_at"] == "2026-03-27T10:00:00"
    
    def test_to_dict_with_null_encryption(self):
        """Test to_dict() with None encryption."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        entry = MappingEntry(
            operation_id=operation_id,
            schema_name="dbo",
            table_name="Users",
            column_name="email",
            original_value_hash=value_hash,
            original_value_encrypted=None,  # No encryption
            masked_value="masked@example.com",
            data_type="VARCHAR(255)",
            is_null=False
        )
        
        result = entry.to_dict()
        
        assert result["original_value_encrypted"] is None


class TestMappingBatch:
    """Test MappingBatch dataclass."""
    
    def test_mapping_batch_creation(self):
        """Test creating a valid MappingBatch."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        entries = [
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value=f"user{i}@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
            for i in range(5)
        ]
        
        batch = MappingBatch(
            entries=entries,
            batch_number=1,
            total_entries=10,
            operation_id=operation_id
        )
        
        assert batch.entries == entries
        assert batch.batch_number == 1
        assert batch.total_entries == 10
        assert batch.operation_id == operation_id
    
    def test_mapping_batch_with_table_column_filter(self):
        """Test MappingBatch with table_name and column_name."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        entries = [
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value="test@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
        ]
        
        batch = MappingBatch(
            entries=entries,
            batch_number=1,
            total_entries=1,
            operation_id=operation_id,
            table_name="Users",
            column_name="email"
        )
        
        assert batch.table_name == "Users"
        assert batch.column_name == "email"
    
    def test_mapping_batch_validation_empty_entries(self):
        """Test validation rejects empty entries list."""
        operation_id = uuid4()
        
        with pytest.raises(ValueError, match="Batch cannot be empty"):
            MappingBatch(
                entries=[],  # Empty
                batch_number=1,
                total_entries=0,
                operation_id=operation_id
            )
    
    def test_mapping_batch_validation_invalid_batch_number(self):
        """Test validation rejects batch_number < 1."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        entries = [
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value="test@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
        ]
        
        with pytest.raises(ValueError, match="batch_number must be >= 1"):
            MappingBatch(
                entries=entries,
                batch_number=0,  # Invalid
                total_entries=1,
                operation_id=operation_id
            )
    
    def test_mapping_batch_validation_total_entries_too_small(self):
        """Test validation rejects total_entries < batch size."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        entries = [
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value=f"user{i}@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
            for i in range(5)
        ]
        
        with pytest.raises(ValueError, match="total_entries .* cannot be less than batch size"):
            MappingBatch(
                entries=entries,
                batch_number=1,
                total_entries=3,  # Less than 5 entries
                operation_id=operation_id
            )
    
    def test_mapping_batch_validation_mixed_operation_ids(self):
        """Test validation rejects entries with different operation_ids."""
        operation_id1 = uuid4()
        operation_id2 = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        entries = [
            MappingEntry(
                operation_id=operation_id1,
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value="user1@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            ),
            MappingEntry(
                operation_id=operation_id2,  # Different operation_id
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value="user2@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
        ]
        
        with pytest.raises(ValueError, match="All entries must have operation_id"):
            MappingBatch(
                entries=entries,
                batch_number=1,
                total_entries=2,
                operation_id=operation_id1
            )


class TestMappingBatchProperties:
    """Test MappingBatch properties."""
    
    def test_entry_count_property(self):
        """Test entry_count property."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        entries = [
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value=f"user{i}@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
            for i in range(7)
        ]
        
        batch = MappingBatch(
            entries=entries,
            batch_number=1,
            total_entries=10,
            operation_id=operation_id
        )
        
        assert batch.entry_count == 7
    
    def test_progress_percent_first_batch(self):
        """Test progress_percent for first batch."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        # 5 entries in batch 1 out of 20 total
        entries = [
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value=f"user{i}@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
            for i in range(5)
        ]
        
        batch = MappingBatch(
            entries=entries,
            batch_number=1,
            total_entries=20,
            operation_id=operation_id
        )
        
        # (0 + 5) / 20 = 25%
        assert batch.progress_percent == 25.0
    
    def test_progress_percent_middle_batch(self):
        """Test progress_percent for middle batch."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        entries = [
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value=f"user{i}@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
            for i in range(5)
        ]
        
        batch = MappingBatch(
            entries=entries,
            batch_number=3,  # Third batch
            total_entries=20,
            operation_id=operation_id
        )
        
        # ((3-1) * 5 + 5) / 20 = 15 / 20 = 75%
        assert batch.progress_percent == 75.0
    
    def test_progress_percent_last_batch_caps_at_100(self):
        """Test progress_percent caps at 100%."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        entries = [
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value=f"user{i}@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
            for i in range(5)
        ]
        
        batch = MappingBatch(
            entries=entries,
            batch_number=4,
            total_entries=20,
            operation_id=operation_id
        )
        
        # Should cap at 100%
        assert batch.progress_percent == 100.0


class TestMappingBatchToDict:
    """Test MappingBatch.to_dict() method."""
    
    def test_to_dict(self):
        """Test to_dict() serialization."""
        operation_id = uuid4()
        value_hash = hashlib.sha256(b"test").digest()
        
        entries = [
            MappingEntry(
                operation_id=operation_id,
                schema_name="dbo",
                table_name="Users",
                column_name="email",
                original_value_hash=value_hash,
                original_value_encrypted=None,
                masked_value=f"user{i}@example.com",
                data_type="VARCHAR(255)",
                is_null=False
            )
            for i in range(5)
        ]
        
        batch = MappingBatch(
            entries=entries,
            batch_number=2,
            total_entries=20,
            operation_id=operation_id,
            table_name="Users",
            column_name="email"
        )
        
        result = batch.to_dict()
        
        assert result["batch_number"] == 2
        assert result["entry_count"] == 5
        assert result["total_entries"] == 20
        assert result["operation_id"] == str(operation_id)
        assert result["table_name"] == "Users"
        assert result["column_name"] == "email"
        assert result["progress_percent"] == 50.0


class TestMappingStats:
    """Test MappingStats dataclass."""
    
    def test_mapping_stats_creation(self):
        """Test creating valid MappingStats."""
        operation_id = uuid4()
        started = datetime(2026, 3, 27, 10, 0, 0)
        completed = datetime(2026, 3, 27, 10, 5, 30)
        
        stats = MappingStats(
            operation_id=operation_id,
            total_entries=1000,
            tables_processed=5,
            columns_processed=10,
            encryption_enabled=True,
            started_at=started,
            completed_at=completed
        )
        
        assert stats.operation_id == operation_id
        assert stats.total_entries == 1000
        assert stats.tables_processed == 5
        assert stats.columns_processed == 10
        assert stats.encryption_enabled is True
        assert stats.started_at == started
        assert stats.completed_at == completed
    
    def test_mapping_stats_validation_negative_total_entries(self):
        """Test validation rejects negative total_entries."""
        operation_id = uuid4()
        started = datetime.now()
        
        with pytest.raises(ValueError, match="total_entries cannot be negative"):
            MappingStats(
                operation_id=operation_id,
                total_entries=-10,
                tables_processed=5,
                columns_processed=10,
                encryption_enabled=True,
                started_at=started
            )
    
    def test_mapping_stats_validation_negative_tables(self):
        """Test validation rejects negative tables_processed."""
        operation_id = uuid4()
        started = datetime.now()
        
        with pytest.raises(ValueError, match="tables_processed cannot be negative"):
            MappingStats(
                operation_id=operation_id,
                total_entries=1000,
                tables_processed=-5,
                columns_processed=10,
                encryption_enabled=True,
                started_at=started
            )
    
    def test_mapping_stats_validation_negative_columns(self):
        """Test validation rejects negative columns_processed."""
        operation_id = uuid4()
        started = datetime.now()
        
        with pytest.raises(ValueError, match="columns_processed cannot be negative"):
            MappingStats(
                operation_id=operation_id,
                total_entries=1000,
                tables_processed=5,
                columns_processed=-10,
                encryption_enabled=True,
                started_at=started
            )
    
    def test_mapping_stats_validation_completed_before_started(self):
        """Test validation rejects completed_at before started_at."""
        operation_id = uuid4()
        started = datetime(2026, 3, 27, 10, 0, 0)
        completed = datetime(2026, 3, 27, 9, 0, 0)  # Before started
        
        with pytest.raises(ValueError, match="completed_at cannot be before started_at"):
            MappingStats(
                operation_id=operation_id,
                total_entries=1000,
                tables_processed=5,
                columns_processed=10,
                encryption_enabled=True,
                started_at=started,
                completed_at=completed
            )


class TestMappingStatsProperties:
    """Test MappingStats properties."""
    
    def test_duration_seconds_with_completion(self):
        """Test duration_seconds with completed operation."""
        operation_id = uuid4()
        started = datetime(2026, 3, 27, 10, 0, 0)
        completed = datetime(2026, 3, 27, 10, 5, 30)  # 5 minutes 30 seconds
        
        stats = MappingStats(
            operation_id=operation_id,
            total_entries=1000,
            tables_processed=5,
            columns_processed=10,
            encryption_enabled=True,
            started_at=started,
            completed_at=completed
        )
        
        assert stats.duration_seconds == 330.0  # 5*60 + 30
    
    def test_duration_seconds_without_completion(self):
        """Test duration_seconds returns None if not completed."""
        operation_id = uuid4()
        started = datetime.now()
        
        stats = MappingStats(
            operation_id=operation_id,
            total_entries=1000,
            tables_processed=5,
            columns_processed=10,
            encryption_enabled=True,
            started_at=started
        )
        
        assert stats.duration_seconds is None
    
    def test_avg_entries_per_table(self):
        """Test avg_entries_per_table calculation."""
        operation_id = uuid4()
        started = datetime.now()
        
        stats = MappingStats(
            operation_id=operation_id,
            total_entries=1000,
            tables_processed=5,
            columns_processed=10,
            encryption_enabled=True,
            started_at=started
        )
        
        assert stats.avg_entries_per_table == 200.0  # 1000 / 5
    
    def test_avg_entries_per_table_zero_tables(self):
        """Test avg_entries_per_table with zero tables."""
        operation_id = uuid4()
        started = datetime.now()
        
        stats = MappingStats(
            operation_id=operation_id,
            total_entries=0,
            tables_processed=0,
            columns_processed=0,
            encryption_enabled=True,
            started_at=started
        )
        
        assert stats.avg_entries_per_table == 0.0
    
    def test_avg_entries_per_column(self):
        """Test avg_entries_per_column calculation."""
        operation_id = uuid4()
        started = datetime.now()
        
        stats = MappingStats(
            operation_id=operation_id,
            total_entries=1000,
            tables_processed=5,
            columns_processed=10,
            encryption_enabled=True,
            started_at=started
        )
        
        assert stats.avg_entries_per_column == 100.0  # 1000 / 10
    
    def test_avg_entries_per_column_zero_columns(self):
        """Test avg_entries_per_column with zero columns."""
        operation_id = uuid4()
        started = datetime.now()
        
        stats = MappingStats(
            operation_id=operation_id,
            total_entries=0,
            tables_processed=0,
            columns_processed=0,
            encryption_enabled=True,
            started_at=started
        )
        
        assert stats.avg_entries_per_column == 0.0
