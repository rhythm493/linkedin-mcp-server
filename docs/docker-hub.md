# MCP Server for LinkedIn (Docker Build)

> **Disclaimer:** This is an independent, community project. It is not affiliated with, authorized by, endorsed by, or sponsored by LinkedIn Corporation or Microsoft. "LinkedIn" is a registered trademark of LinkedIn Corporation and is used here only descriptively to identify the third-party service this software interoperates with.

> **Note**: Docker images are not published for this fork. Build locally from source.

Build and run:

```bash
git clone https://github.com/rhythm493/linkedin-mcp-server
cd linkedin-mcp-server
docker build -t linkedin-mcp-server .
```
```

Create a browser profile on the host first:

```bash
uv run -m linkedin_mcp_server --login
```

**Claude Desktop configuration:**

```json
{
  "mcpServers": {
    "linkedin": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "~/.linkedin-mcp:/home/pwuser/.linkedin-mcp",
        "linkedin-mcp-server:latest"
      ]
    }
  }
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `USER_DATA_DIR` | `~/.linkedin-mcp/profile` | Path to persistent browser profile directory |
| `LOG_LEVEL` | `WARNING` | Logging level: DEBUG, INFO, WARNING, ERROR |
| `TIMEOUT` | `5000` | Browser timeout in milliseconds |
| `TOOL_TIMEOUT` | `180` | Per-tool MCP execution timeout in seconds |
| `TRANSPORT` | `stdio` | Transport mode: stdio, streamable-http |
| `HOST` | `127.0.0.1` | HTTP server host (for streamable-http transport) |
| `PORT` | `8000` | HTTP server port (for streamable-http transport) |
| `HTTP_PATH` | `/mcp` | HTTP server path (for streamable-http transport) |
| `CHROME_PATH` | - | Path to Chrome/Chromium executable (rarely needed in Docker) |

## Repository

- **Source**: <https://github.com/rhythm493/linkedin-mcp-server>
- **License**: Apache 2.0
