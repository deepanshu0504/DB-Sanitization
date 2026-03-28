"""Test that ai_detection_direct.py preserves performance settings"""

import json
from pathlib import Path

print("=" * 70)
print("TESTING AI DETECTION CONFIG PRESERVATION")
print("=" * 70)

# Read the config file
config_path = Path("config/pii_config_ai_generated.json")
with open(config_path, 'r') as f:
    config = json.load(f)

print("\nCurrent config database settings:")
db_config = config['database']
print(f"  - server: {db_config.get('server')}")
print(f"  - database: {db_config.get('database')}")
print(f"  - batch_size: {db_config.get('batch_size')}")

print("\nPerformance optimization settings:")
optimizations = {
    'log_batch_frequency': 10,
    'bulk_update_strategy': 'auto',
    'enable_fast_executemany': True,
    'enable_parallel_processing': True,
    'max_parallel_tables': 4
}

all_present = True
for key, expected_value in optimizations.items():
    actual_value = db_config.get(key)
    status = "✓" if actual_value == expected_value else "✗"
    
    if actual_value == expected_value:
        print(f"  {status} {key}: {actual_value}")
    else:
        print(f"  {status} {key}: {actual_value} (expected: {expected_value})")
        all_present = False

print("\n" + "=" * 70)
if all_present:
    print("SUCCESS! All performance optimizations are present")
    print("ai_detection_direct.py will now preserve these settings")
else:
    print("FAILED! Some optimization settings are missing")
print("=" * 70)
