"""
Unit tests for MaskerFactory class.

Tests cover:
- Basic factory functionality (singleton, registry)
- Masker instantiation for all PII types
- Caching behavior (cache hits, misses, keys)
- Generic masker parameter handling (character_class)
- Error handling (unsupported types, invalid params)
- Thread safety (concurrent access, cache integrity)
- Custom masker registration

Test Organization:
- TestMaskerFactoryBasic: Singleton pattern, registry access
- TestMaskerFactoryInstantiation: get_masker for each PII type
- TestMaskerFactoryCaching: Cache behavior and management
- TestMaskerFactoryGenericParams: GenericMasker-specific parameters
- TestMaskerFactoryErrorHandling: Error scenarios and messages
- TestMaskerFactoryThreadSafety: Concurrent access patterns
- TestMaskerFactoryCustomMaskers: Custom registration

Author: Database Sanitization Team
Date: 2026-03-26
"""

import pytest
import threading
from unittest.mock import Mock, patch

from src.masking.masker_factory import MaskerFactory
from src.masking.base_masker import BaseMasker, ColumnInfo, MaskingStrategy
from src.masking.email_masker import EmailMasker
from src.masking.phone_masker import PhoneMasker
from src.masking.name_masker import NameMasker
from src.masking.ssn_masker import SSNMasker
from src.masking.generic_masker import GenericMasker
from src.exceptions import MaskingError


class TestMaskerFactoryBasic:
    """Test basic factory functionality."""
    
    def setup_method(self):
        """Reset factory singleton before each test."""
        MaskerFactory._reset_instance()
    
    def test_singleton_pattern(self):
        """Test that factory implements singleton pattern."""
        factory1 = MaskerFactory()
        factory2 = MaskerFactory()
        
        assert factory1 is factory2
    
    def test_initialization(self):
        """Test factory initializes with correct state."""
        factory = MaskerFactory()
        
        assert factory._cache == {}
        assert factory._cache_lock is not None
        assert factory._logger is not None
    
    def test_registry_contains_all_maskers(self):
        """Test that registry contains all built-in maskers."""
        factory = MaskerFactory()
        
        expected_types = ["email", "phone", "name", "ssn", "generic"]
        registered_types = factory.get_registered_types()
        
        assert registered_types == expected_types
    
    def test_registry_maps_to_correct_classes(self):
        """Test that registry maps PII types to correct masker classes."""
        factory = MaskerFactory()
        
        assert factory._registry["email"] == EmailMasker
        assert factory._registry["phone"] == PhoneMasker
        assert factory._registry["name"] == NameMasker
        assert factory._registry["ssn"] == SSNMasker
        assert factory._registry["generic"] == GenericMasker
    
    def test_get_registered_types(self):
        """Test get_registered_types returns sorted list."""
        factory = MaskerFactory()
        
        types = factory.get_registered_types()
        
        assert types == sorted(types)
        assert len(types) == 5
        assert "email" in types
        assert "generic" in types
    
    def test_clear_cache_empty(self):
        """Test clear_cache on empty cache returns 0."""
        factory = MaskerFactory()
        
        cleared = factory.clear_cache()
        
        assert cleared == 0


class TestMaskerFactoryInstantiation:
    """Test masker instantiation for all PII types."""
    
    def setup_method(self):
        """Reset factory singleton before each test."""
        MaskerFactory._reset_instance()
    
    def test_get_email_masker(self):
        """Test getting EmailMasker instance."""
        factory = MaskerFactory()
        
        masker = factory.get_masker("email")
        
        assert isinstance(masker, EmailMasker)
        assert masker.seed == 42
        assert masker.null_strategy == MaskingStrategy.PRESERVE
    
    def test_get_phone_masker(self):
        """Test getting PhoneMasker instance."""
        factory = MaskerFactory()
        
        masker = factory.get_masker("phone")
        
        assert isinstance(masker, PhoneMasker)
        assert masker.seed == 42
    
    def test_get_name_masker(self):
        """Test getting NameMasker instance."""
        factory = MaskerFactory()
        
        masker = factory.get_masker("name")
        
        assert isinstance(masker, NameMasker)
        assert masker.seed == 42
    
    def test_get_ssn_masker(self):
        """Test getting SSNMasker instance."""
        factory = MaskerFactory()
        
        masker = factory.get_masker("ssn")
        
        assert isinstance(masker, SSNMasker)
        assert masker.seed == 42
    
    def test_get_generic_masker(self):
        """Test getting GenericMasker instance."""
        factory = MaskerFactory()
        
        masker = factory.get_masker("generic")
        
        assert isinstance(masker, GenericMasker)
        assert masker.seed == 42
        assert masker.character_class == "alphanumeric"
    
    def test_get_masker_with_custom_seed(self):
        """Test getting masker with custom seed value."""
        factory = MaskerFactory()
        
        masker = factory.get_masker("email", seed=999)
        
        assert masker.seed == 999
    
    def test_get_masker_with_custom_null_strategy(self):
        """Test getting masker with custom NULL strategy."""
        factory = MaskerFactory()
        
        masker = factory.get_masker("email", null_strategy=MaskingStrategy.MASK)
        
        assert masker.null_strategy == MaskingStrategy.MASK
    
    def test_get_masker_with_custom_logger(self):
        """Test getting masker with custom logger."""
        factory = MaskerFactory()
        custom_logger = Mock()
        
        masker = factory.get_masker("email", logger=custom_logger)
        
        # Logger is passed to masker
        assert masker.logger is not None
    
    def test_different_seeds_create_different_instances(self):
        """Test that different seeds create different masker instances."""
        factory = MaskerFactory()
        
        masker1 = factory.get_masker("email", seed=42)
        masker2 = factory.get_masker("email", seed=100)
        
        assert masker1 is not masker2
        assert masker1.seed == 42
        assert masker2.seed == 100
    
    def test_different_pii_types_create_different_instances(self):
        """Test that different PII types create different maskers."""
        factory = MaskerFactory()
        
        email_masker = factory.get_masker("email")
        phone_masker = factory.get_masker("phone")
        
        assert type(email_masker) != type(phone_masker)
        assert isinstance(email_masker, EmailMasker)
        assert isinstance(phone_masker, PhoneMasker)


class TestMaskerFactoryCaching:
    """Test caching behavior."""
    
    def setup_method(self):
        """Reset factory singleton before each test."""
        MaskerFactory._reset_instance()
    
    def test_same_config_returns_cached_instance(self):
        """Test that same configuration returns cached masker."""
        factory = MaskerFactory()
        
        masker1 = factory.get_masker("email", seed=42)
        masker2 = factory.get_masker("email", seed=42)
        
        assert masker1 is masker2
    
    def test_cache_key_includes_pii_type(self):
        """Test that cache key distinguishes PII types."""
        factory = MaskerFactory()
        
        email_masker = factory.get_masker("email", seed=42)
        phone_masker = factory.get_masker("phone", seed=42)
        
        assert email_masker is not phone_masker
    
    def test_cache_key_includes_seed(self):
        """Test that cache key distinguishes seeds."""
        factory = MaskerFactory()
        
        masker1 = factory.get_masker("email", seed=42)
        masker2 = factory.get_masker("email", seed=100)
        
        assert masker1 is not masker2
    
    def test_cache_key_includes_null_strategy(self):
        """Test that cache key distinguishes NULL strategies."""
        factory = MaskerFactory()
        
        masker1 = factory.get_masker("email", null_strategy=MaskingStrategy.PRESERVE)
        masker2 = factory.get_masker("email", null_strategy=MaskingStrategy.MASK)
        
        assert masker1 is not masker2
    
    def test_cache_key_includes_masker_params(self):
        """Test that cache key distinguishes masker parameters."""
        factory = MaskerFactory()
        
        masker1 = factory.get_masker("generic", masker_params={"character_class": "alpha"})
        masker2 = factory.get_masker("generic", masker_params={"character_class": "numeric"})
        
        assert masker1 is not masker2
    
    def test_clear_cache_removes_all_instances(self):
        """Test that clear_cache removes all cached maskers."""
        factory = MaskerFactory()
        
        # Create multiple cached maskers
        factory.get_masker("email")
        factory.get_masker("phone")
        factory.get_masker("name")
        
        cleared = factory.clear_cache()
        
        assert cleared == 3
        assert len(factory._cache) == 0
    
    def test_cache_after_clear_creates_new_instance(self):
        """Test that maskers are recreated after cache clear."""
        factory = MaskerFactory()
        
        masker1 = factory.get_masker("email", seed=42)
        factory.clear_cache()
        masker2 = factory.get_masker("email", seed=42)
        
        assert masker1 is not masker2
    
    def test_create_cache_key_consistency(self):
        """Test that _create_cache_key produces consistent keys."""
        factory = MaskerFactory()
        
        key1 = factory._create_cache_key("email", 42, MaskingStrategy.PRESERVE, None)
        key2 = factory._create_cache_key("email", 42, MaskingStrategy.PRESERVE, None)
        
        assert key1 == key2


class TestMaskerFactoryGenericParams:
    """Test GenericMasker parameter handling."""
    
    def setup_method(self):
        """Reset factory singleton before each test."""
        MaskerFactory._reset_instance()
    
    def test_generic_masker_default_character_class(self):
        """Test GenericMasker gets default character_class."""
        factory = MaskerFactory()
        
        masker = factory.get_masker("generic")
        
        assert masker.character_class == "alphanumeric"
    
    def test_generic_masker_alpha_character_class(self):
        """Test GenericMasker with alpha character_class."""
        factory = MaskerFactory()
        
        masker = factory.get_masker(
            "generic",
            masker_params={"character_class": "alpha"}
        )
        
        assert masker.character_class == "alpha"
    
    def test_generic_masker_numeric_character_class(self):
        """Test GenericMasker with numeric character_class."""
        factory = MaskerFactory()
        
        masker = factory.get_masker(
            "generic",
            masker_params={"character_class": "numeric"}
        )
        
        assert masker.character_class == "numeric"
    
    def test_generic_masker_alphanumeric_character_class(self):
        """Test GenericMasker with explicit alphanumeric character_class."""
        factory = MaskerFactory()
        
        masker = factory.get_masker(
            "generic",
            masker_params={"character_class": "alphanumeric"}
        )
        
        assert masker.character_class == "alphanumeric"
    
    def test_generic_masker_empty_params_uses_default(self):
        """Test GenericMasker with empty params dict uses default."""
        factory = MaskerFactory()
        
        masker = factory.get_masker("generic", masker_params={})
        
        assert masker.character_class == "alphanumeric"
    
    def test_different_character_classes_cached_separately(self):
        """Test that different character_class values cache separately."""
        factory = MaskerFactory()
        
        masker1 = factory.get_masker("generic", masker_params={"character_class": "alpha"})
        masker2 = factory.get_masker("generic", masker_params={"character_class": "numeric"})
        
        assert masker1 is not masker2
        assert masker1.character_class == "alpha"
        assert masker2.character_class == "numeric"
    
    def test_masker_params_none_handled_gracefully(self):
        """Test that None masker_params works correctly."""
        factory = MaskerFactory()
        
        masker = factory.get_masker("generic", masker_params=None)
        
        assert masker.character_class == "alphanumeric"
    
    def test_masker_params_non_dict_ignored(self):
        """Test that non-dict masker_params are ignored."""
        factory = MaskerFactory()
        
        # Legacy string format should be ignored
        masker = factory.get_masker("generic", masker_params="invalid")
        
        assert masker.character_class == "alphanumeric"


class TestMaskerFactoryErrorHandling:
    """Test error handling and validation."""
    
    def setup_method(self):
        """Reset factory singleton before each test."""
        MaskerFactory._reset_instance()
    
    def test_unsupported_pii_type_raises_error(self):
        """Test that unknown PII type raises MaskingError."""
        factory = MaskerFactory()
        
        with pytest.raises(MaskingError) as exc_info:
            factory.get_masker("unknown_type")
        
        assert exc_info.value.error_code.name == "MASKING_UNSUPPORTED_PII_TYPE"
    
    def test_unsupported_pii_type_includes_valid_types(self):
        """Test that unsupported PII type error includes valid types."""
        factory = MaskerFactory()
        
        with pytest.raises(MaskingError) as exc_info:
            factory.get_masker("invalid")
        
        error_msg = str(exc_info.value)
        assert "email" in error_msg
        assert "phone" in error_msg
        assert "generic" in error_msg
    
    def test_invalid_character_class_raises_error(self):
        """Test that invalid character_class raises error."""
        factory = MaskerFactory()
        
        # GenericMasker validates character_class in __init__
        with pytest.raises((ValueError, MaskingError)):
            factory.get_masker(
                "generic",
                masker_params={"character_class": "invalid"}
            )
    
    def test_register_non_masker_class_raises_error(self):
        """Test that registering non-BaseMasker class raises ValueError."""
        factory = MaskerFactory()
        
        class NotAMasker:
            pass
        
        with pytest.raises(ValueError) as exc_info:
            factory.register_masker("custom", NotAMasker)
        
        assert "subclass of BaseMasker" in str(exc_info.value)
    
    def test_register_none_as_masker_raises_error(self):
        """Test that registering None raises ValueError."""
        factory = MaskerFactory()
        
        with pytest.raises(ValueError):
            factory.register_masker("custom", None)
    
    def test_register_invalid_type_raises_error(self):
        """Test that registering non-class raises ValueError."""
        factory = MaskerFactory()
        
        with pytest.raises(ValueError):
            factory.register_masker("custom", "not_a_class")


class TestMaskerFactoryThreadSafety:
    """Test thread safety of factory operations."""
    
    def setup_method(self):
        """Reset factory singleton before each test."""
        MaskerFactory._reset_instance()
    
    def test_concurrent_singleton_creation(self):
        """Test that concurrent access creates only one singleton."""
        instances = []
        
        def create_factory():
            factory = MaskerFactory()
            instances.append(factory)
        
        # Create factory from multiple threads
        threads = [threading.Thread(target=create_factory) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        
        # All instances should be the same
        assert len(set(id(instance) for instance in instances)) == 1
    
    def test_concurrent_get_masker(self):
        """Test that concurrent get_masker calls are thread-safe."""
        factory = MaskerFactory()
        maskers = []
        
        def get_email_masker():
            masker = factory.get_masker("email", seed=42)
            maskers.append(masker)
        
        # Get masker from multiple threads
        threads = [threading.Thread(target=get_email_masker) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        
        # All should get the same cached instance
        assert len(set(id(masker) for masker in maskers)) == 1
    
    def test_concurrent_cache_operations(self):
        """Test that concurrent cache operations don't corrupt cache."""
        factory = MaskerFactory()
        results = []
        
        def create_maskers():
            # Create maskers with different configs
            m1 = factory.get_masker("email", seed=42)
            m2 = factory.get_masker("phone", seed=42)
            m3 = factory.get_masker("name", seed=100)
            results.append((m1, m2, m3))
        
        # Run concurrent cache operations
        threads = [threading.Thread(target=create_maskers) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        
        # All threads should get consistent results
        first_result = results[0]
        for result in results[1:]:
            assert result[0] is first_result[0]  # Same email masker
            assert result[1] is first_result[1]  # Same phone masker
            assert result[2] is first_result[2]  # Same name masker
    
    def test_concurrent_clear_cache(self):
        """Test that concurrent clear_cache is thread-safe."""
        factory = MaskerFactory()
        
        # Pre-populate cache
        factory.get_masker("email")
        factory.get_masker("phone")
        
        cleared_counts = []
        
        def clear_cache():
            count = factory.clear_cache()
            cleared_counts.append(count)
        
        # Clear cache from multiple threads
        threads = [threading.Thread(target=clear_cache) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        
        # Cache should be empty
        assert len(factory._cache) == 0


class TestMaskerFactoryCustomMaskers:
    """Test custom masker registration."""
    
    def setup_method(self):
        """Reset factory singleton before each test."""
        MaskerFactory._reset_instance()
    
    def test_register_custom_masker(self):
        """Test registering a custom masker class."""
        factory = MaskerFactory()
        
        class CustomMasker(BaseMasker):
            def mask(self, value, column_info):
                return "CUSTOM"
        
        factory.register_masker("custom", CustomMasker)
        
        assert "custom" in factory.get_registered_types()
        assert factory._registry["custom"] == CustomMasker
    
    def test_get_custom_masker_instance(self):
        """Test getting instance of custom registered masker."""
        factory = MaskerFactory()
        
        class CustomMasker(BaseMasker):
            def mask(self, value, column_info):
                return "CUSTOM"
        
        factory.register_masker("custom", CustomMasker)
        masker = factory.get_masker("custom")
        
        assert isinstance(masker, CustomMasker)
    
    def test_override_built_in_masker(self):
        """Test that custom masker can override built-in."""
        factory = MaskerFactory()
        
        class CustomEmailMasker(BaseMasker):
            def mask(self, value, column_info):
                return "custom@example.com"
        
        # Override email masker
        factory.register_masker("email", CustomEmailMasker)
        masker = factory.get_masker("email")
        
        assert isinstance(masker, CustomEmailMasker)
        assert not isinstance(masker, EmailMasker)
    
    def test_custom_masker_with_params(self):
        """Test custom masker with specific parameters."""
        factory = MaskerFactory()
        
        class ParamMasker(BaseMasker):
            def __init__(self, seed=42, null_strategy=MaskingStrategy.PRESERVE, 
                        logger=None, custom_param="default"):
                super().__init__(seed, null_strategy, logger)
                self.custom_param = custom_param
            
            def mask(self, value, column_info):
                return self.custom_param
        
        factory.register_masker("param_masker", ParamMasker)
        
        # Note: Current implementation doesn't extract custom_param
        # This test documents current behavior
        masker = factory.get_masker("param_masker")
        assert masker.custom_param == "default"
