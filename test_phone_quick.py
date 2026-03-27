#!/usr/bin/env python
"""Quick test to verify PhoneMasker works"""

from src.masking.phone_masker import PhoneMasker
from src.masking.base_masker import ColumnInfo

print("✓ PhoneMasker imported successfully")

masker = PhoneMasker(seed=42)
print(f"✓ PhoneMasker instantiated with area code {masker.AREA_CODE}")

col = ColumnInfo(data_type="VARCHAR", max_length=20, nullable=True)
masked = masker.mask("(555) 123-4567", col)
print(f"✓ Masked phone: {masked}")

print("\n🎉 All checks passed!")
