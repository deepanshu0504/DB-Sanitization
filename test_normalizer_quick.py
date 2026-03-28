"""Quick test script for name_normalizer.py"""
import sys
sys.path.insert(0, 'D:/Projects/Projects/DB-Sanitization/DB-Sanitization')

from src.database.name_normalizer import (
    normalize_identifier,
    build_qualified_name,
    CaseInsensitiveDict,
    identifiers_match
)

print("=" * 70)
print("Testing Name Normalizer")
print("=" * 70)

# Test 1: normalize_identifier
print("\n1. Testing normalize_identifier:")
assert normalize_identifier("Orders") == "orders"
assert normalize_identifier("EMAIL") == "email"
print("   ✓ normalize_identifier works")

# Test 2: build_qualified_name
print("\n2. Testing build_qualified_name:")
assert build_qualified_name("dbo", "Orders", normalize=True) == "[dbo].[orders]"
assert build_qualified_name("dbo", "Orders", "Email", normalize=True) == "[dbo].[orders].[email]"
print("   ✓ build_qualified_name works")

# Test 3: identifiers_match
print("\n3. Testing identifiers_match:")
assert identifiers_match("Orders", "orders") is True
assert identifiers_match("Orders", "Users") is False
print("   ✓ identifiers_match works")

# Test 4: CaseInsensitiveDict
print("\n4. Testing CaseInsensitiveDict:")
d = CaseInsensitiveDict()
d["Orders"] = {"count": 10}
assert d["orders"] == {"count": 10}
assert d["ORDERS"] == {"count": 10}
assert "orders" in d
assert list(d.keys()) == ["Orders"]  #  Original case preserved
print("   ✓ CaseInsensitiveDict works")

print("\n" + "=" * 70)
print("ALL TESTS PASSED!")
print("=" * 70)
