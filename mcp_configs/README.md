# MCP client configurations

This directory contains example MCP client configurations. MCP (Model Context
Protocol) lets any MCP-compatible host discover and call tools exposed by the
migration framework, Databricks, Snowflake, and other systems.

## Running the migration-framework MCP server

The package installs a `migrate-mcp` console script that speaks MCP over stdio.
Install the framework with the MCP extra, then start the server:

```bash
pip install "migration-framework[mcp]"
migrate-mcp
```

You should see the server start and wait on `stdin` for MCP messages.  In most
hosts the process is started for you; you do not run `migrate-mcp` manually.

### Tools exposed

- `list_connectors` - list available source/target connectors
- `list_skills` - list built-in skills and workflows
- `run_skill` - run a single skill with JSON inputs
- `run_workflow` - run a built-in workflow with JSON inputs
- `discover` - discover schema mapping and emit a config YAML
- `migrate` - run a migration from a config path

### Test the server manually

You can sanity-check `migrate-mcp` without a full MCP host by piping a single
JSON-RPC request.  For example, list the available connectors:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_connectors","arguments":{}}}' | migrate-mcp
```

A real host will wrap this in the MCP lifecycle (`initialize`, etc.), but the
response confirms the server is loading and responding.

### Run with Claude Desktop

1. Copy `claude_desktop_config.json.example` to your Claude Desktop config
   location (usually `~/Library/Application Support/Claude/claude_desktop_config.json`
   on macOS).
2. Replace the placeholder values with your credentials.
3. Restart Claude Desktop.  The migration-framework tools will appear in the
   available MCP tools list.

The example file also wires in Databricks and Snowflake MCP servers.  You can
install those separately, for example:

```bash
pip install databricks-mcp
npx -y @isaacwasserman/mcp-snowflake-server
```

The migration-framework server itself does not require those tools; it can run
standalone and use the native connectors in this package.

### Run from the project source

If you are developing in this repository:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[mcp]"
migrate-mcp
```
