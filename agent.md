## Datagen SDK + Datagen MCP (agent rules)

### When to use what

- Use **Datagen MCP** for interactive discovery/debugging:
  - `searchTools` to find the right tool alias
  - `getToolDetails` to confirm exact input schema
- Use **Datagen Python SDK** for execution in real code:
  - `DatagenClient.execute_tool(tool_alias, params)`

### Non-negotiable workflow

1) If you don't know the tool name: call `searchTools`.
2) In code, always create the SDK client as `client`:
   - `from datagen_sdk import DatagenClient`
   - `client = DatagenClient()`
3) Before you call a tool from code: call `getToolDetails` and match the schema exactly.
4) Execute via SDK using the exact alias name you discovered:
   - `client.execute_tool(tool_alias, params)`
5) If you hit auth errors: tell the user to set `DATAGEN_API_KEY` and/or connect/auth the relevant MCP server in DataGen.

### SDK quickstart

```python
import os
from datagen_sdk import DatagenClient

assert os.getenv("DATAGEN_API_KEY"), "Set DATAGEN_API_KEY first"

client = DatagenClient()
print(client.execute_tool("listTools"))
```
