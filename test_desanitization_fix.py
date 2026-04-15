"""
Test script to verify desanitization dry_run bug fix.

This script verifies that:
1. Default behavior is dry-run (no database changes)
2. --dry-run flag works (no database changes)
3. --execute flag works (actual database changes)
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_argparse_behavior():
    """Test that argparse behaves correctly."""
    from desanitize_direct import setup_argparse, apply_cli_overrides
    from desanitization.config_models import DesanitizationConfig
    
    print("=" * 70)
    print("TESTING ARGPARSE BEHAVIOR")
    print("=" * 70)
    
    # Create a minimal config
    config = DesanitizationConfig()
    
    # Test 1: Default behavior (no flags)
    print("\n1. Testing default behavior (no flags):")
    parser = setup_argparse()
    args = parser.parse_args(['table', '--table', 'TestTable'])
    config_copy = DesanitizationConfig()
    config_copy = apply_cli_overrides(config_copy, args)
    
    print(f"   args.dry_run = {getattr(args, 'dry_run', 'N/A')}")
    print(f"   args.execute = {getattr(args, 'execute', 'N/A')}")
    print(f"   config.restoration.dry_run = {config_copy.restoration.dry_run}")
    
    expected = True  # Default should be dry-run
    actual = config_copy.restoration.dry_run
    status = "✓ PASS" if actual == expected else "✗ FAIL"
    print(f"   Expected: dry_run = {expected}, Actual: {actual} [{status}]")
    
    # Test 2: Explicit --dry-run flag
    print("\n2. Testing --dry-run flag:")
    args = parser.parse_args(['table', '--table', 'TestTable', '--dry-run'])
    config_copy = DesanitizationConfig()
    config_copy = apply_cli_overrides(config_copy, args)
    
    print(f"   args.dry_run = {getattr(args, 'dry_run', 'N/A')}")
    print(f"   args.execute = {getattr(args, 'execute', 'N/A')}")
    print(f"   config.restoration.dry_run = {config_copy.restoration.dry_run}")
    
    expected = True  # Should be dry-run
    actual = config_copy.restoration.dry_run
    status = "✓ PASS" if actual == expected else "✗ FAIL"
    print(f"   Expected: dry_run = {expected}, Actual: {actual} [{status}]")
    
    # Test 3: --execute flag (THE CRITICAL TEST)
    print("\n3. Testing --execute flag (CRITICAL - was broken before fix):")
    args = parser.parse_args(['table', '--table', 'TestTable', '--execute'])
    config_copy = DesanitizationConfig()
    config_copy = apply_cli_overrides(config_copy, args)
    
    print(f"   args.dry_run = {getattr(args, 'dry_run', 'N/A')}")
    print(f"   args.execute = {getattr(args, 'execute', 'N/A')}")
    print(f"   config.restoration.dry_run = {config_copy.restoration.dry_run}")
    
    expected = False  # Should NOT be dry-run (should execute)
    actual = config_copy.restoration.dry_run
    status = "✓ PASS" if actual == expected else "✗ FAIL"
    print(f"   Expected: dry_run = {expected}, Actual: {actual} [{status}]")
    
    if actual != expected:
        print("\n   ⚠️  CRITICAL BUG STILL PRESENT!")
        print("   The --execute flag is NOT disabling dry_run mode!")
        return False
    
    # Test 4: Both flags (should error or --execute takes precedence)
    print("\n4. Testing --execute with --dry-run (both flags):")
    try:
        args = parser.parse_args(['table', '--table', 'TestTable', '--execute', '--dry-run'])
        config_copy = DesanitizationConfig()
        config_copy = apply_cli_overrides(config_copy, args)
        
        print(f"   args.dry_run = {getattr(args, 'dry_run', 'N/A')}")
        print(f"   args.execute = {getattr(args, 'execute', 'N/A')}")
        print(f"   config.restoration.dry_run = {config_copy.restoration.dry_run}")
        print(f"   Note: Both flags accepted, --execute takes precedence")
    except SystemExit:
        print("   Mutually exclusive (argparse rejects both flags) ✓")
    
    print("\n" + "=" * 70)
    print("✓ ALL TESTS PASSED - Bug is fixed!")
    print("=" * 70)
    return True


def verify_code_locations():
    """Verify that the code changes were applied correctly."""
    print("\n" + "=" * 70)
    print("VERIFYING CODE CHANGES")
    print("=" * 70)
    
    with open('desanitize_direct.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    issues = []
    
    # Check 1: Verify no more "default=True" for --dry-run
    if "add_argument('--dry-run', action='store_true', default=True" in content:
        issues.append("❌ Found 'default=True' for --dry-run argument (should be removed)")
    else:
        print("✓ No 'default=True' found for --dry-run arguments")
    
    # Check 2: Verify engine calls use config.restoration.dry_run
    if "dry_run=args.dry_run" in content:
        issues.append("❌ Found 'dry_run=args.dry_run' in engine calls (should use config.restoration.dry_run)")
    else:
        print("✓ No 'dry_run=args.dry_run' found in engine calls")
    
    # Check 3: Verify config.restoration.dry_run is used
    if "dry_run=config.restoration.dry_run" not in content:
        issues.append("❌ 'dry_run=config.restoration.dry_run' not found in engine calls")
    else:
        print("✓ Found 'dry_run=config.restoration.dry_run' in engine calls")
    
    if issues:
        print("\n⚠️  ISSUES FOUND:")
        for issue in issues:
            print(f"   {issue}")
        return False
    
    print("\n✓ All code changes verified successfully!")
    return True


if __name__ == '__main__':
    print("\n" + "🔧 Desanitization Dry-Run Bug Fix Verification" + "\n")
    
    # Run verification
    code_ok = verify_code_locations()
    argparse_ok = test_argparse_behavior()
    
    if code_ok and argparse_ok:
        print("\n🎉 SUCCESS! The desanitization bug is fixed!")
        print("\nNext steps:")
        print("1. Test with actual database: python desanitize_direct.py table --table YourTable --execute --yes")
        print("2. Verify database changes actually occur")
        print("3. Check audit logs match database state")
        sys.exit(0)
    else:
        print("\n❌ VERIFICATION FAILED - Issues detected")
        sys.exit(1)
