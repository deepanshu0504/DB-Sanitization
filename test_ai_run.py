"""Test wrapper to run AI detection and capture output."""
import sys
import subprocess
import os

output_file = "test_ai_output.txt"

def write_output(msg):
    """Write to both console and file."""
    print(msg)
    with open(output_file, 'a', encoding='utf-8') as f:
        f.write(msg + '\n')

# Clear previous output
if os.path.exists(output_file):
    os.remove(output_file)

write_output("=" * 60)
write_output("Testing AI Detection with Pydantic Fix")
write_output("=" * 60)

try:
    # Run with -B to bypass bytecode cache
    result = subprocess.run(
        [sys.executable, "-B", "examples/ai_detection_example.py"],
        capture_output=True,
        text=True,
        timeout=120
    )
    
    write_output("\n📋 STDERR OUTPUT:")
    write_output("-" * 60)
    if result.stderr:
        # Filter for warnings and errors
        lines = result.stderr.split('\n')
        warning_found = False
        for line in lines:
            if any(keyword in line for keyword in ['UserWarning', 'schema', 'ERROR', 'Error', 'Exception']):
                write_output(line)
                warning_found = True
        if not warning_found:
            write_output("(No warnings or errors matching filter)")
    else:
        write_output("(No stderr output)")
    
    write_output("\n📋 STDOUT OUTPUT (last 50 lines):")
    write_output("-" * 60)
    if result.stdout:
        lines = result.stdout.split('\n')
        for line in lines[-50:]:
            write_output(line)
    
    write_output(f"\n📋 EXIT CODE: {result.returncode}")
    
    # Check if output file was created
    if os.path.exists("config/pii_config_ai_generated.json"):
        write_output("✅ SUCCESS: config/pii_config_ai_generated.json was created!")
    else:
        write_output("❌ FAILURE: config/pii_config_ai_generated.json was NOT created")
    
    write_output(f"\n✅ Full results saved to: {output_file}")
    sys.exit(result.returncode)
    
except subprocess.TimeoutExpired:
    write_output("❌ TIMEOUT: Script took too long (>120s)")
    sys.exit(1)
except Exception as e:
    write_output(f"❌ EXCEPTION: {e}")
    import traceback
    write_output(traceback.format_exc())
    sys.exit(1)
