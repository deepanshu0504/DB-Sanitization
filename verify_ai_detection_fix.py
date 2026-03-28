#!/usr/bin/env python3
"""
Quick verification that all AI detection scripts include performance settings
"""

import re
from pathlib import Path

print("=" * 70)
print("VERIFYING AI DETECTION SCRIPTS - PERFORMANCE SETTINGS")
print("=" * 70)

scripts = [
    "ai_detection_direct.py",
    "ai_detection_simple.py",
    "ai_detection_standalone.py",
    "examples/ai_detection_example.py"
]

required_settings = [
    "log_batch_frequency",
    "bulk_update_strategy",
    "enable_fast_executemany",
    "enable_parallel_processing",
    "max_parallel_tables"
]

all_passed = True

for script_path in scripts:
    print(f"\n[Checking {script_path}]")
    
    full_path = Path(script_path)
    if not full_path.exists():
        print(f"  ✗ File not found!")
        all_passed = False
        continue
    
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    missing = []
    for setting in required_settings:
        # Look for the setting in output_config definition
        pattern = f'"{setting}"\\s*:'
        if not re.search(pattern, content):
            missing.append(setting)
    
    if missing:
        print(f"  ✗ MISSING: {', '.join(missing)}")
        all_passed = False
    else:
        print(f"  ✓ All 5 performance settings present")

print("\n" + "=" * 70)
if all_passed:
    print("SUCCESS! All AI detection scripts have performance optimizations")
    print()
    print("You can now run any of these scripts without losing settings:")
    for script in scripts:
        print(f"  - python {script}")
else:
    print("FAILED! Some scripts are missing performance settings")
    print("Review and fix the scripts listed above")

print("=" * 70)
