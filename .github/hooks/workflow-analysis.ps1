# Workflow Analysis Hook - Injects project context at session start
# Reads requirement.md and CriticalRulesAndEdgeCases.md to understand the workflow

$workspaceRoot = $PSScriptRoot | Split-Path -Parent | Split-Path -Parent

# Read key documents
$requirementPath = Join-Path $workspaceRoot "Requirement\requirement.md"
$criticalRulesPath = Join-Path $workspaceRoot "CriticalRules\CriticalRulesAndEdgeCases.md"

$contextMessage = @"
📋 Database Sanitization Project Context Loaded

## Workflow Understanding (from Requirement Document):
1. **Database Connectivity** → SQL Server (both auth types supported)
2. **Schema Extraction** → Retrieve metadata (tables, columns, types) as JSON
3. **AI-Based PII Detection** → Send schema to Copilot API → Receive PII column suggestions
4. **User Review** → Manual override of AI suggestions → Finalized JSON config
5. **Batch Data Extraction** → Fetch only PII columns in batches (OFFSET/FETCH)
6. **Fake Data Generation** → Respect data type, length, constraints
7. **Batch Updates** → Replace PII with fake data efficiently
8. **Mapping Table** → Store original ↔ fake mappings for reversibility
9. **Validation** → Row counts, data types, referential integrity
10. **Desanitization** (optional) → Restore original data from mapping

## Critical Rules Active (from CriticalRules Document):
✅ **Schema Handling**: Always use [schema].[table] format, never assume dbo
✅ **Data Type Compliance**: Fake data must respect length, type, precision, constraints
✅ **Performance**: Batch processing, set-based operations, key-based pagination
✅ **Generic Design**: No hardcoded tables/columns, domain-agnostic, JSON-driven
✅ **Security**: No PII in logs, parameterized queries, encrypted mapping tables
✅ **Referential Integrity**: Handle FK dependencies, circular refs, composite keys
✅ **Edge Cases**: NULL strategies, unicode, orphaned records, triggers, self-references

## Available Resources:
- Skills: /mssql-expert, /python-expert, /db-sanitization, /sanitization-edge-cases
- Agents: Python Optimizer, SQL Server Expert
- Instructions: Auto-applied to all .py files (sanitization-standards)
- Memory: Project context stored in /memories/repo/

## Quick Reference Checklist:
☑ Review existing workflow before changes
☑ Use fully qualified object names
☑ Implement batch processing (1000 rows default)
☑ Add comprehensive error handling with rollback
☑ Type hints + docstrings required
☑ No PII in logs
☑ Validate referential integrity after operations
☑ Write tests for edge cases

Ready to assist with database sanitization development! 🚀
"@

# Output JSON for hook system
$output = @{
    systemMessage = $contextMessage
    continue = $true
} | ConvertTo-Json -Compress

Write-Output $output
