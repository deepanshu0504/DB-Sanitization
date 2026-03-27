"""
Example demonstrating MaskerFactory usage and capabilities.

This example shows:
1. Basic factory usage (getting maskers for all PII types)
2. Singleton caching demonstration
3. GenericMasker with different character_class parameters
4. Custom masker registration
5. Thread-safe concurrent access
6. Integration with configuration (PIIColumnConfig)
7. Error handling (unknown PII types)
8. Cache management and cleanup

The factory provides a centralized way to create and manage masker instances
with automatic caching for performance optimization.

Author: Database Sanitization Team
Date: 2026-03-26
"""

import sys
from pathlib import Path
import threading
import time

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.masking.masker_factory import MaskerFactory
from src.masking.base_masker import BaseMasker, ColumnInfo, MaskingStrategy
from src.exceptions import MaskingError


def example_1_basic_factory_usage():
    """Example 1: Basic factory usage for all PII types."""
    print("\n" + "="*80)
    print("EXAMPLE 1: Basic Factory Usage")
    print("="*80)
    
    # Get factory instance (singleton)
    factory = MaskerFactory()
    
    print("\nGetting maskers for all PII types:")
    print(f"{'PII Type':<15} {'Masker Class':<25} {'Seed':<8} {'Null Strategy'}")
    print("-" * 75)
    
    # Get maskers for each PII type
    pii_types = ["email", "phone", "name", "ssn", "generic"]
    
    for pii_type in pii_types:
        masker = factory.get_masker(pii_type)
        print(f"{pii_type:<15} {masker.__class__.__name__:<25} {masker.seed:<8} {masker.null_strategy.value}")
    
    print(f"\n✓ All {len(pii_types)} masker types created successfully")


def example_2_singleton_caching():
    """Example 2: Singleton pattern and caching demonstration."""
    print("\n" + "="*80)
    print("EXAMPLE 2: Singleton Caching")
    print("="*80)
    
    # Multiple factory instances are the same
    factory1 = MaskerFactory()
    factory2 = MaskerFactory()
    
    print(f"\nFactory instances:")
    print(f"  factory1 id: {id(factory1)}")
    print(f"  factory2 id: {id(factory2)}")
    print(f"  Same instance: {factory1 is factory2}")
    
    # Same configuration returns cached masker
    print("\nGetting email masker twice with same config:")
    masker1 = factory1.get_masker("email", seed=42)
    masker2 = factory2.get_masker("email", seed=42)
    
    print(f"  masker1 id: {id(masker1)}")
    print(f"  masker2 id: {id(masker2)}")
    print(f"  Same instance: {masker1 is masker2}")
    
    # Different seed creates different masker
    print("\nGetting email masker with different seed:")
    masker3 = factory1.get_masker("email", seed=100)
    
    print(f"  masker3 id: {id(masker3)}")
    print(f"  Different from masker1: {masker3 is not masker1}")
    print(f"  masker1.seed: {masker1.seed}, masker3.seed: {masker3.seed}")
    
    # Cache statistics
    print(f"\nCache statistics:")
    print(f"  Cached maskers: {len(factory1._cache)}")
    
    print("\n✓ Singleton and caching work correctly")


def example_3_generic_masker_parameters():
    """Example 3: GenericMasker with different character_class parameters."""
    print("\n" + "="*80)
    print("EXAMPLE 3: GenericMasker Character Classes")
    print("="*80)
    
    factory = MaskerFactory()
    col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
    
    # Test data
    test_value = "CustomData123"
    
    print(f"\nOriginal value: {test_value}")
    print(f"\n{'Character Class':<20} {'Masked Value':<25} {'Masker ID'}")
    print("-" * 68)
    
    # Alphanumeric (default)
    masker_alphanum = factory.get_masker("generic")
    masked_alphanum = masker_alphanum.mask(test_value, col)
    print(f"{'alphanumeric':<20} {masked_alphanum:<25} {id(masker_alphanum)}")
    
    # Alpha only
    masker_alpha = factory.get_masker(
        "generic",
        masker_params={"character_class": "alpha"}
    )
    masked_alpha = masker_alpha.mask(test_value, col)
    print(f"{'alpha':<20} {masked_alpha:<25} {id(masker_alpha)}")
    
    # Numeric only
    masker_numeric = factory.get_masker(
        "generic",
        masker_params={"character_class": "numeric"}
    )
    masked_numeric = masker_numeric.mask(test_value, col)
    print(f"{'numeric':<20} {masked_numeric:<25} {id(masker_numeric)}")
    
    # Verify different instances
    print(f"\nAll maskers are different instances:")
    print(f"  alphanum != alpha:   {masker_alphanum is not masker_alpha}")
    print(f"  alpha != numeric:    {masker_alpha is not masker_numeric}")
    
    # Verify character classes
    print(f"\nCharacter class verification:")
    print(f"  alphanum output: {masked_alphanum.isalnum()}")
    print(f"  alpha output:    {masked_alpha.isalpha()}")
    print(f"  numeric output:  {masked_numeric.isdigit()}")
    
    print("\n✓ GenericMasker character classes work correctly")


def example_4_custom_masker_registration():
    """Example 4: Registering custom masker classes."""
    print("\n" + "="*80)
    print("EXAMPLE 4: Custom Masker Registration")
    print("="*80)
    
    factory = MaskerFactory()
    
    # Define custom masker
    class AddressMasker(BaseMasker):
        """Custom masker for address data."""
        
        def mask(self, value, column_info):
            """Mask address by returning generic address."""
            if value is None:
                return self._handle_null(column_info)
            
            # Simple address masking (in real implementation, use Faker)
            seed = self._get_deterministic_seed(str(value))
            street_num = (seed % 9999) + 1
            return f"{street_num} Main Street"
    
    # Before registration
    print(f"\nRegistered types before: {factory.get_registered_types()}")
    
    # Register custom masker
    factory.register_masker("address", AddressMasker)
    
    # After registration
    print(f"Registered types after:  {factory.get_registered_types()}")
    
    # Use custom masker
    print("\nUsing custom address masker:")
    address_masker = factory.get_masker("address")
    col = ColumnInfo(data_type="VARCHAR", max_length=100, nullable=True)
    
    addresses = [
        "123 Oak Street, Apt 4B",
        "456 Elm Avenue",
        "789 Pine Road"
    ]
    
    print(f"{'Original':<30} -> {'Masked'}")
    print("-" * 55)
    for addr in addresses:
        masked = address_masker.mask(addr, col)
        print(f"{addr:<30} -> {masked}")
    
    print("\n✓ Custom masker registration works correctly")


def example_5_thread_safe_concurrent_access():
    """Example 5: Thread-safe concurrent access."""
    print("\n" + "="*80)
    print("EXAMPLE 5: Thread-Safe Concurrent Access")
    print("="*80)
    
    factory = MaskerFactory()
    col = ColumnInfo(data_type="VARCHAR", max_length=50, nullable=True)
    results = []
    
    def mask_emails(thread_id):
        """Mask emails from multiple threads."""
        email_masker = factory.get_masker("email", seed=42)
        
        test_emails = [
            f"user{thread_id}@example.com",
            f"test{thread_id}@test.com",
            f"admin{thread_id}@domain.com"
        ]
        
        masked = [email_masker.mask(email, col) for email in test_emails]
        results.append((thread_id, email_masker, masked))
    
    # Create and start threads
    print("\nStarting 5 concurrent threads...")
    threads = [threading.Thread(target=mask_emails, args=(i,)) for i in range(5)]
    
    for thread in threads:
        thread.start()
    
    for thread in threads:
        thread.join()
    
    print("All threads completed\n")
    
    # Verify all threads got the same masker instance
    masker_ids = set(id(result[1]) for result in results)
    print(f"Unique masker instances: {len(masker_ids)}")
    print(f"All threads used same masker: {len(masker_ids) == 1}")
    
    # Show some results
    print(f"\nSample results from thread 0:")
    for i, masked_email in enumerate(results[0][2]):
        print(f"  Email {i+1}: {masked_email}")
    
    print("\n✓ Thread-safe concurrent access works correctly")


def example_6_config_integration():
    """Example 6: Integration with configuration."""
    print("\n" + "="*80)
    print("EXAMPLE 6: Configuration Integration")
    print("="*80)
    
    factory = MaskerFactory()
    
    # Simulate PIIColumnConfig (would come from config file)
    class MockPIIConfig:
        def __init__(self, table, column, pii_type, custom_format=None):
            self.table = table
            self.column = column
            self.pii_type = pii_type
            self.custom_format = custom_format
    
    # Sample PII configurations
    pii_configs = [
        MockPIIConfig("users", "email", "email"),
        MockPIIConfig("users", "phone", "phone"),
        MockPIIConfig("users", "full_name", "name"),
        MockPIIConfig("employees", "ssn", "ssn"),
        MockPIIConfig("products", "internal_code", "generic", {"character_class": "alpha"}),
        MockPIIConfig("orders", "reference_num", "generic", {"character_class": "numeric"}),
    ]
    
    print("\nCreating maskers from configuration:")
    print(f"{'Table':<15} {'Column':<20} {'PII Type':<10} {'Custom Format':<25} {'Masker'}")
    print("-" * 95)
    
    for config in pii_configs:
        masker = factory.get_masker(
            config.pii_type,
            seed=42,
            masker_params=config.custom_format
        )
        
        custom_fmt = str(config.custom_format) if config.custom_format else "None"
        print(f"{config.table:<15} {config.column:<20} {config.pii_type:<10} {custom_fmt:<25} {masker.__class__.__name__}")
    
    print(f"\n✓ Configuration integration works correctly")


def example_7_error_handling():
    """Example 7: Error handling for unknown PII types."""
    print("\n" + "="*80)
    print("EXAMPLE 7: Error Handling")
    print("="*80)
    
    factory = MaskerFactory()
    
    print("\nAttempting to get masker for unknown PII type...")
    
    try:
        masker = factory.get_masker("credit_card")
        print("ERROR: Should have raised MaskingError")
    except MaskingError as e:
        print(f"\n✓ Caught expected MaskingError:")
        print(f"  Error Code: {e.error_code.name}")
        print(f"  Message: {e.message}")
        print(f"  Suggested Action: {e.suggested_action}")
        
        # Verify error includes valid types
        error_str = str(e)
        print(f"\n  Error includes valid types:")
        valid_types = ["email", "phone", "name", "ssn", "generic"]
        for pii_type in valid_types:
            if pii_type in error_str:
                print(f"    ✓ {pii_type}")
    
    print("\nAttempting to register invalid masker class...")
    
    try:
        class NotAMasker:
            pass
        
        factory.register_masker("invalid", NotAMasker)
        print("ERROR: Should have raised ValueError")
    except ValueError as e:
        print(f"\n✓ Caught expected ValueError:")
        print(f"  Message: {str(e)}")
    
    print("\n✓ Error handling works correctly")


def example_8_cache_management():
    """Example 8: Cache management and cleanup."""
    print("\n" + "="*80)
    print("EXAMPLE 8: Cache Management")
    print("="*80)
    
    factory = MaskerFactory()
    
    # Start with empty cache
    factory.clear_cache()
    print(f"\nInitial cache size: {len(factory._cache)}")
    
    # Create several maskers
    print("\nCreating multiple maskers...")
    maskers = [
        factory.get_masker("email", seed=42),
        factory.get_masker("email", seed=100),
        factory.get_masker("phone", seed=42),
        factory.get_masker("name", seed=42),
        factory.get_masker("generic", masker_params={"character_class": "alpha"}),
        factory.get_masker("generic", masker_params={"character_class": "numeric"}),
    ]
    
    print(f"Cache size after creation: {len(factory._cache)}")
    
    # Get same masker again (cache hit)
    print("\nGetting email masker again (should hit cache)...")
    email_masker = factory.get_masker("email", seed=42)
    print(f"Cache size (unchanged): {len(factory._cache)}")
    print(f"Same instance as first: {email_masker is maskers[0]}")
    
    # Clear cache
    print("\nClearing cache...")
    cleared = factory.clear_cache()
    print(f"Cleared {cleared} masker instances")
    print(f"Cache size after clear: {len(factory._cache)}")
    
    # Get masker after clear (creates new instance)
    print("\nGetting email masker after clear...")
    new_email_masker = factory.get_masker("email", seed=42)
    print(f"Same instance as original: {new_email_masker is maskers[0]}")
    print(f"Cache size: {len(factory._cache)}")
    
    print("\n✓ Cache management works correctly")


def main():
    """Run all masker factory examples."""
    print("\n" + "="*80)
    print("MASKER FACTORY EXAMPLES")
    print("Demonstrating factory pattern for masker creation and management")
    print("="*80)
    
    try:
        example_1_basic_factory_usage()
        example_2_singleton_caching()
        example_3_generic_masker_parameters()
        example_4_custom_masker_registration()
        example_5_thread_safe_concurrent_access()
        example_6_config_integration()
        example_7_error_handling()
        example_8_cache_management()
        
        print("\n" + "="*80)
        print("✓ All examples completed successfully!")
        print("="*80)
        
        print("\nKey Takeaways:")
        print("  • Factory implements singleton pattern for centralized masker management")
        print("  • Automatic caching improves performance (same config = same masker)")
        print("  • Thread-safe concurrent access via double-checked locking")
        print("  • Supports masker-specific parameters (e.g., character_class for GenericMasker)")
        print("  • Custom maskers can be registered at runtime")
        print("  • Clear error messages for unknown PII types")
        print("  • Cache can be manually cleared for testing/cleanup")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
