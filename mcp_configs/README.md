# MCP client configurations

This directory contains example MCP client configurations. MCP (Model Context
Protocol) lets any MCP-compatible host discover and call tools exposed by the
migration framework, Databricks, Snowflake, and other systems.

## migration-framework MCP server

The package installs a `migrate-mcp` console script that speaks MCP over stdio:

```bash
pip install "migration-framework[mcp]"
migrate-mcp
```

It exposes tools such as `discover`, `run_skill`, `run_workflow`, `migrate`,
`list_skills`, and `list_connectors`.  Use these from Claude Desktop, Claude
Code, Cursor, or any other MCP host.

## Example Claude Desktop config

Copy `claude_desktop_config.json.example` to your Claude Desktop config location
(usually `~/Library/Application Support/Claude/claude_desktop_config.json` on
macOS) and fill in your credentials.

You will need to install the Databricks and Snowflake MCP servers separately,
for example:

```bash
pip install databricks-mcp
npx -y @isaacwasserman/mcp-snowflake-server
```

The migration-framework server itself does not require those tools; it can run
standalone and use the native connectors in this package.
