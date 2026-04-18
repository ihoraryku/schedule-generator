# MCP Server Recommendations for ShiftMaster АСКОЕ

## Overview
OpenCode doesn't use MCP servers in the same way as Claude Desktop. Instead, OpenCode has built-in tools and the Context7 integration for documentation queries.

## Recommended OpenCode Workflow

### 1. Documentation Queries (Context7)
For PyQt6, openpyxl, reportlab, and other library documentation:

```
Use context7_resolve-library-id first to get the library ID
Then use context7_query-docs with specific questions
```

Example workflow:
1. "How to create a QTableWidget with custom delegates in PyQt6?"
   - OpenCode will use Context7 to fetch PyQt6 documentation
2. "How to style Excel cells with openpyxl?"
   - OpenCode will use Context7 to fetch openpyxl documentation

### 2. SQLite Database Operations
Use the built-in `bash` tool to run SQLite commands:

```powershell
# View schema
sqlite3 schedule.db ".schema"

# Query data
sqlite3 schedule.db "SELECT * FROM employees LIMIT 5"

# Check table structure
sqlite3 schedule.db ".tables"
```

### 3. Git Operations
Use the built-in `bash` tool for git commands:

```powershell
git status
git log --oneline -10
git diff
git add .
git commit -m "feat(module): опис змін"
```

### 4. GitHub Integration
Use the built-in `bash` tool with `gh` CLI (if installed):

```powershell
# View issues
gh issue list

# Create PR
gh pr create --title "Title" --body "Description"

# View PR status
gh pr status
```

## Not Needed for This Project

### ❌ Filesystem MCP
OpenCode has built-in file operations (read, write, edit, glob, grep) that are more efficient than MCP filesystem servers.

### ❌ Brave Search MCP
OpenCode has built-in `webfetch` tool for fetching web content.

### ❌ PostgreSQL/MySQL MCP
This project uses SQLite, which is handled via bash + sqlite3 CLI.

### ❌ Puppeteer MCP
Not needed for desktop Python application development.

## What OpenCode Provides Out of the Box

1. **File Operations**: read, write, edit, glob, grep
2. **Shell Commands**: bash tool for running any CLI command
3. **Documentation**: Context7 integration for library docs
4. **Web Fetching**: webfetch tool for HTTP requests
5. **Task Management**: todowrite for tracking progress
6. **Specialized Agents**: task tool with explore/general agents
7. **Sequential Thinking**: for complex problem-solving

## Best Practices for This Project

### Use Context7 for Library Questions
```
❌ Don't: Search Google for "PyQt6 QTableWidget example"
✅ Do: Ask OpenCode directly, it will use Context7 automatically
```

### Use Bash for System Operations
```
❌ Don't: Try to find an MCP server for git/sqlite
✅ Do: Use bash tool with git/sqlite3 commands
```

### Use Skills for Specialized Tasks
```
❌ Don't: Ask generic "debug this" questions
✅ Do: Trigger skills with specific phrases:
  - "review this code" → code-reviewer
  - "write tests for" → test-master
  - "schedule is wrong" → debugging-wizard
  - "why does this crash" → debug-skill
```

### Use Task Tool for Exploration
```
❌ Don't: Manually grep through large codebases
✅ Do: Use task tool with explore agent for codebase questions
```

## Summary

OpenCode is designed to work without external MCP servers for most development tasks. The built-in tools (Context7, bash, file operations, skills, task agents) provide everything needed for Python + PyQt6 + SQLite development.

Focus on:
1. Using Context7 for documentation
2. Using bash for CLI tools (git, sqlite3, python)
3. Using skills for specialized workflows
4. Using task tool for codebase exploration
