"""
Simple orchestrator validation test without full imports.

This test validates the orchestrator implementation without
triggering the problematic phone_masker imports.
"""

import sys
from pathlib import Path

# Test basic orchestrator imports
try:
    from src.sanitization.orchestrator import (
        SanitizationOrchestrator,
        SanitizationReport,
        TableProgress,
        Checkpoint,
        ExecutionPhase
    )
    print("✓ All orchestrator imports successful")
except Exception as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

# Test data class creation
try:
    report = SanitizationReport(
        operation_id="test-001",
        phase=ExecutionPhase.VALIDATION
    )
    print(f"✓ Created SanitizationReport: {report.operation_id}")
    
    progress = TableProgress(schema="dbo", table="Users")
    print(f"✓ Created TableProgress: {progress.fully_qualified_name}")
    
    checkpoint =Checkpoint(
        operation_id="test-001",
        config_hash="abc123",
        tables_completed=[]
    )
    print(f"✓ Created Checkpoint: {checkpoint.operation_id}")
    
except Exception as e:
    print(f"✗ Data class creation failed: {e}")
    sys.exit(1)

# Test orchestrator initialization
try:
    orch = SanitizationOrchestrator()
    print(f"✓ Initialized orchestrator")
    print(f"  - Checkpoint dir: {orch.checkpoint_dir}")
    print(f"  - Masker factory: {orch.masker_factory is not None}")
    
except Exception as e:
    print(f"✗ Orchestrator initialization failed: {e}")
    sys.exit(1)

# Test report methods
try:
    report.add_error("Test error")
    report.add_warning("Test warning")
    assert len(report.errors) == 1
    assert len(report.warnings) == 1
    print("✓ Report methods working")
    
    report_dict = report.to_dict()
    assert "operation_id" in report_dict
    print("✓ Report serialization working")
    
except Exception as e:
    print(f"✗ Report methods failed: {e}")
    sys.exit(1)

# Test checkpoint save/load
try:
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        checkpoint_file = Path(tmpdir) / "test.json"
        checkpoint.save(checkpoint_file)
        print(f"✓ Checkpoint saved")
        
        loaded = Checkpoint.load(checkpoint_file)
        assert loaded.operation_id == checkpoint.operation_id
        print(f"✓ Checkpoint loaded")
        
except Exception as e:
    print(f"✗ Checkpoint save/load failed: {e}")
    sys.exit(1)

print("\n" + "="*60)
print("All orchestrator validations passed ✓")
print("="*60)
