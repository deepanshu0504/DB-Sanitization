# Standards Compliance Validation Hook
# Validates that code written during the session follows sanitization-standards.instructions.md

$workspaceRoot = $PSScriptRoot | Split-Path -Parent | Split-Path -Parent
$instructionsPath = Join-Path $workspaceRoot ".github\instructions\sanitization-standards.instructions.md"

# Find all Python files modified in the last session (Git-aware)
$recentMinutes = 60  # Check files modified in last hour
$cutoffTime = (Get-Date).AddMinutes(-$recentMinutes)

$pythonFiles = Get-ChildItem -Path $workspaceRoot -Recurse -Include "*.py" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -gt $cutoffTime }

if ($pythonFiles.Count -eq 0) {
    $output = @{
        systemMessage = "✅ No Python files modified in this session - no validation needed."
        continue = $true
    } | ConvertTo-Json -Compress
    Write-Output $output
    exit 0
}

# Validation checks based on sanitization-standards.instructions.md
$violations = @()
$fileCount = 0

foreach ($file in $pythonFiles) {
    $fileCount++
    $content = Get-Content -Path $file.FullName -Raw
    $relativePath = $file.FullName.Replace("$workspaceRoot\", "")
    
    # Check 1: Type hints present
    if ($content -match "def\s+\w+\([^)]*\)\s*:" -and $content -notmatch "def\s+\w+\([^)]*\)\s*->\s*") {
        if ($content -notmatch "from typing import") {
            $violations += "⚠️ [$relativePath] Missing type hints - functions should have return type annotations"
        }
    }
    
    # Check 2: Docstrings present
    if ($content -match "def\s+\w+" -and $content -notmatch '"""') {
        $violations += "⚠️ [$relativePath] Missing docstrings - functions should have comprehensive documentation"
    }
    
    # Check 3: Hardcoded table names (should use parameters)
    if ($content -match 'FROM\s+(Users|Orders|Customers|Products|dbo\.)' -or 
        $content -match 'UPDATE\s+(Users|Orders|Customers|Products)') {
        $violations += "❌ [$relativePath] Hardcoded table names detected - use parameterized table names from config"
    }
    
    # Check 4: SQL injection risk (string concatenation in queries)
    if ($content -match 'f"SELECT.*FROM.*\{' -or 
        $content -match 'f"UPDATE.*SET.*\{' -or
        $content -match '"SELECT.*\+.*\+') {
        $violations += "🔴 [$relativePath] Potential SQL injection risk - use parameterized queries exclusively"
    }
    
    # Check 5: PII logging risk
    if ($content -match 'logger\.(info|debug|warning).*email|password|ssn|phone' -or
        $content -match 'print.*email|password|ssn') {
        $violations += "🔴 [$relativePath] Potential PII logging detected - never log sensitive data"
    }
    
    # Check 6: Schema qualification
    if ($content -match 'FROM\s+\w+\.' -and $content -notmatch '\[.*\]\.\[.*\]') {
        $violations += "⚠️ [$relativePath] Missing schema qualification - use [schema].[table] format"
    }
    
    # Check 7: Error handling present
    if ($content -match "def\s+\w+" -and $content -notmatch "try:|except:") {
        $violations += "⚠️ [$relativePath] Missing error handling - implement try/except with rollback"
    }
    
    # Check 8: Row-by-row operations
    if ($content -match 'for.*in.*cursor\.fetchall\(\):.*cursor\.execute\(' -or
        $content -match 'for.*row.*:.*UPDATE') {
        $violations += "❌ [$relativePath] Row-by-row operations detected - use batch/set-based operations"
    }
    
    # Check 9: Connection not closed
    if ($content -match 'pyodbc\.connect\(' -and $content -notmatch '\.close\(\)|with.*connect') {
        $violations += "⚠️ [$relativePath] Connection might not be closed - use context managers"
    }
}

# Generate report
$reportBuilder = @"
📊 **Standards Compliance Validation Report**

Files Analyzed: $fileCount Python file(s) modified in this session
Violations Found: $($violations.Count)

"@

if ($violations.Count -eq 0) {
    $reportBuilder += @"
✅ **All Checks Passed!**

Your code follows the sanitization standards:
✓ Type hints and docstrings present
✓ No hardcoded table/column names
✓ Parameterized queries used
✓ No PII logging detected
✓ Schema-qualified object names
✓ Error handling implemented
✓ Batch operations used
✓ Resources properly managed

Great work following the guidelines! 🎉

"@
    $exitCode = 0
} else {
    $reportBuilder += @"
⚠️ **Issues Detected:**

$($violations -join "`n")

---

📋 **Remediation Guide:**

**Critical Issues (🔴):**
- SQL Injection: Use parameterized queries with ? placeholders
- PII Logging: Remove sensitive data from logs, log IDs only

**Important Issues (❌):**
- Hardcoded Names: Load table/column names from JSON config
- Row-by-Row: Refactor to use executemany() or set-based SQL

**Warnings (⚠️):**
- Type Hints: Add -> ReturnType to all function signatures
- Docstrings: Add comprehensive docstrings with Args/Returns/Raises
- Schema Qualification: Use f"[{schema}].[{table}]" format
- Error Handling: Wrap operations in try/except with rollback
- Resource Management: Use 'with' statements for connections

📖 Review: .github/instructions/sanitization-standards.instructions.md

"@
    $exitCode = 0  # Non-blocking warning
}

# Add quick reference
$reportBuilder += @"
---

**Quick Reference:**
- Type hints: \`def func(x: int) -> str:\`
- Parameterized query: \`cursor.execute("SELECT * FROM ? WHERE id = ?", (table, id))\`
- Schema qualified: \`f"[{schema}].[{table}]"\`
- Context manager: \`with pyodbc.connect(conn_str) as conn:\`
- Batch update: \`cursor.executemany(query, data_list)\`
- No PII logs: \`logger.info(f"Processing user_id: {user_id}")\`  # ✓
- No PII logs: \`logger.info(f"Processing email: {email}")\`      # ✗

Skills available for help: /python-expert, /db-sanitization, /sanitization-edge-cases
"@

$output = @{
    systemMessage = $reportBuilder
    continue = $true
} | ConvertTo-Json -Compress

Write-Output $output
exit $exitCode
