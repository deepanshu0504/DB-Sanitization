"""Simple wrapper to run AI detection and show clear results."""
import subprocess
import sys
import os

print("=" * 70)
print("AI DETECTION TEST - Checking for Pydantic warnings")
print("=" * 70)

# Run the script
result = subprocess.run(
    [sys.executable, "examples/ai_detection_example.py"],
    capture_output=True,
    text=True,
    cwd=os.getcwd()
)

# Check stderr for warnings
print("\n[STDERR CHECK]")
if "UserWarning" in result.stderr and "schema" in result.stderr:
    print("❌ FAILED: Pydantic warning still present")
    print("\nRelevant stderr lines:")
    for line in result.stderr.split('\n'):
        if 'UserWarning' in line or 'schema' in line or 'Field name' in line:
            print(f"  {line}")
else:
    print("✅ PASSED: No Pydantic schema warnings!")

# Check for errors
print("\n[ERROR CHECK]")
if result.returncode != 0:
    print(f"❌ FAILED: Script exited with code {result.returncode}")
    print("\nLast 30 lines of output:")
    for line in result.stdout.split('\n')[-30:]:
        if line.strip():
            print(f"  {line}")
    if "ERROR" in result.stderr or "Error" in result.stderr or "Exception" in result.stderr:
        print("\nErrors in stderr:")
        for line in result.stderr.split('\n'):
            if any(x in line for x in ['ERROR', 'Error', 'Exception', 'Traceback']):
                print(f"  {line}")
else:
    print(f"✅ PASSED: Script exited successfully (code 0)")

# Check for output file
print("\n[OUTPUT FILE CHECK]")
if os.path.exists("config/pii_config_ai_generated.json"):
    print("✅ PASSED: config/pii_config_ai_generated.json created!")
    print(f"   File size: {os.path.getsize('config/pii_config_ai_generated.json')} bytes")
else:
    print("❌ FAILED: config/pii_config_ai_generated.json NOT created")

print("\n" + "=" * 70)
print(f"OVERALL: {'SUCCESS' if result.returncode == 0 and os.path.exists('config/pii_config_ai_generated.json') else 'FAILED'}")
print("=" * 70)
