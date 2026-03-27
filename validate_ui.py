"""Quick validation script to test UI module imports."""
import sys
import importlib

# Force reload of modules
if 'src.ui' in sys.modules:
    del sys.modules['src.ui']
if 'src.ui.review_cli' in sys.modules:
    del sys.modules['src.ui.review_cli']
if 'src.ui.formatters' in sys.modules:
    del sys.modules['src.ui.formatters']

try:
    from src.ui import PIIReviewCLI
    from src.ui.formatters import format_pii_table, format_config_table
    from src.ai.models import PIIColumn
    from src.config.config_models import PIIColumnConfig
    
    print("✓ All UI module imports successful")
    print(f"✓ PIIReviewCLI class available: {PIIReviewCLI.__name__}")
    print(f"✓ Formatters available: format_pii_table, format_config_table")
    
    # Test basic instantiation
    cli = PIIReviewCLI()
    print(f"✓ PIIReviewCLI instantiation successful")
    print(f"✓ Supported PII types: {len(PIIReviewCLI.SUPPORTED_PII_TYPES)}")
    
    print("\n✅ All validation checks passed!")
    sys.exit(0)
    
except ImportError as e:
    print(f"✗ Import error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
except Exception as e:
    print(f"✗ Unexpected error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
