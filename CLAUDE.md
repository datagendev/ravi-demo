## Datagen Python SDK (how to use)

### Purpose

Use the Datagen Python SDK (`datagen-python-sdk`) when you need to run DataGen-connected tools from a local Python codebase (apps, scripts, cron jobs). Use Datagen MCP for interactive discovery/debugging of tool names and schemas.

### Prerequisites

- Install: `pip install datagen-python-sdk`
- Auth: set `DATAGEN_API_KEY` in the environment

### Mental model (critical)

- You execute tools by alias name: `client.execute_tool("<tool_alias>", params)`
- Tool aliases are commonly:
  - `mcp_<Provider>_<tool_name>` for connected MCP servers (Gmail/Linear/Neon/etc.)
  - First-party DataGen tools like `listTools`, `searchTools`, `getToolDetails`
- Always be schema-first: confirm params via `getToolDetails` before calling a tool from code.

### Recommended workflow (always follow)

1) Verify `DATAGEN_API_KEY` exists (if missing, ask user to set it)
2) Import and create the SDK client:
   - `from datagen_sdk import DatagenClient`
   - `client = DatagenClient()`
3) Discover tool alias with `searchTools` (don't guess)
4) Confirm tool schema with `getToolDetails`
5) Execute with `client.execute_tool(tool_alias, params)`
6) Handle errors:
   - 401/403: missing/invalid API key OR the target MCP server isn't connected/authenticated in DataGen dashboard
   - 400/422: wrong params -> re-check `getToolDetails` and retry

### Minimal example

```python
import os
from datagen_sdk import DatagenClient

if not os.getenv("DATAGEN_API_KEY"):
    raise RuntimeError("DATAGEN_API_KEY not set")

client = DatagenClient()
result = client.execute_tool(
    "mcp_Gmail_gmail_send_email",
    {
        "to": "user@example.com",
        "subject": "Hello",
        "body": "Hi from DataGen!",
    },
)
print(result)
```

### Long-running scripts (must follow)

- Always use `tqdm` for progress bars in loops that may take a while (API calls, enrichment, scraping).
- Run Python scripts with `-u` flag (unbuffered stdout) so progress is visible in real-time: `python -u script.py`
- This lets the user see exactly where the script is at instead of waiting blindly.

### Discovery examples (don't skip)

```python
from datagen_sdk import DatagenClient

client = DatagenClient()

# List all tools
tools = client.execute_tool("listTools")

# Search by intent
matches = client.execute_tool("searchTools", {"query": "send email"})

# Get schema for a tool alias
details = client.execute_tool("getToolDetails", {"tool_name": "mcp_Gmail_gmail_send_email"})
```
