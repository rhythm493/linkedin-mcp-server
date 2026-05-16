# LinkedIn MCP Server

> **Fork** of [stickerdaniel/linkedin-mcp-server](https://github.com/stickerdaniel/linkedin-mcp-server) with extra tools from [iushv/linkedin-agent-mcp](https://github.com/iushv/linkedin-agent-mcp) (job-search-manager-mcp branch).

<p align="left">
  <a href="https://github.com/rhythm493/linkedin-mcp-server/actions/workflows/ci.yml" target="_blank"><img src="https://github.com/rhythm493/linkedin-mcp-server/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI Status"></a>
  <a href="https://github.com/rhythm493/linkedin-mcp-server/actions/workflows/release.yml" target="_blank"><img src="https://github.com/rhythm493/linkedin-mcp-server/actions/workflows/release.yml/badge.svg?branch=main" alt="Release"></a>
  <a href="https://github.com/rhythm493/linkedin-mcp-server/blob/main/LICENSE" target="_blank"><img src="https://img.shields.io/badge/License-Apache%202.0-%233fb950?labelColor=32383f" alt="License"></a>
</p>

Through this LinkedIn MCP server, AI assistants like Claude can connect to your LinkedIn. Access profiles, companies, jobs, saved jobs, posts, and more.


## Installation Methods

[![uv + Git](https://img.shields.io/badge/uv+Git-Quick_Install-de5fe9?style=for-the-badge&logo=python&logoColor=white)](#-uv--git-setup-recommended)
[![Install MCP Bundle](https://img.shields.io/badge/Claude_Desktop_MCPB-d97757?style=for-the-badge&logo=anthropic)](#-claude-desktop-mcp-bundle-formerly-dxt)
[![Development](https://img.shields.io/badge/Development-Local-ffdc53?style=for-the-badge&logo=python&logoColor=ffdc53)](#-local-setup-develop--contribute)

> [!IMPORTANT]
> **FAQ**
>
> **Is this safe to use? Will I get banned?**
> This tool controls a real browser session; it doesn't exploit undocumented APIs or bypass authentication. That said, LinkedIn's TOS prohibit automated tools. With normal usage (not bulk scraping!) you're not risking a ban. So far, no users have been banned for using this MCP. If you encounter any issues, [open an issue](https://github.com/rhythm493/linkedin-mcp-server/issues).
>
> **What if my agents execute too many actions?**
> LinkedIn may send you a warning about automated tool usage. If that happens, reduce your automation volume. This MCP executes tool calls sequentially via a queue but has no built-in rate limits. Prompt your agents responsibly.

| Tool | Description | Status |
|------|-------------|--------|
| `get_person_profile` | Get profile info with explicit section selection (experience, education, interests, honors, languages, certifications, skills, projects, contact_info, posts) | working |
| `get_my_profile` | Get the authenticated user's own LinkedIn profile (same sections as get_person_profile) | working |
| `connect_with_person` | Send a connection request or accept an incoming one, with optional note | working |
| `get_sidebar_profiles` | Extract profile URLs from sidebar recommendation sections ("More profiles for you", "Explore premium profiles", "People you may know") on a profile page | working |
| `get_inbox` | List recent conversations from the LinkedIn messaging inbox | working |
| `get_conversation` | Read a specific messaging conversation by username or thread ID | working |
| `search_conversations` | Search messages by keyword | working |
| `send_message` | Send a message to a LinkedIn user (requires confirmation) | working |
| `get_company_profile` | Extract company information with explicit section selection (posts, jobs); about-section references may include a `company_urn` entry carrying the numeric id used by LinkedIn's people-search `currentCompany` URL facet | working |
| `get_company_posts` | Get recent posts from a company's LinkedIn feed | working |
| `search_companies` | Search for companies on LinkedIn by keywords | working |
| `get_company_employees` | List employees at a company from the /people/ page, with optional keyword filter | working |
| `search_jobs` | Search for jobs with keywords and location filters | working |
| `search_people` | Search for people by keywords, location, connection degree (1st/2nd/3rd), and current company | working |
| `get_job_details` | Get detailed information about a specific job posting | working |
| `get_feed` | Get recent posts from the authenticated user's home feed | working |
| `save_job` | Save a LinkedIn job posting for later review | working |
| `get_saved_jobs` | Return the current user's saved jobs list | working |
| `get_job_recommendations` | Return LinkedIn's personalized job recommendations | working |
| `get_company_people` | Get people at a company with optional title filter | working |
| `create_post` | Create a LinkedIn post from the feed composer | working |
| `create_poll` | Create a LinkedIn poll post with 2-4 options | working |
| `delete_post` | Delete a LinkedIn post by URL | working |
| `repost` | Repost an existing LinkedIn post with optional commentary | working |
| `react_to_post` | React to a LinkedIn post with a specific reaction (like, celebrate, support, funny, love, insightful) | working |
| `comment_on_post` | Add a comment to a LinkedIn post | working |
| `like_comment` | Like the Nth comment on a LinkedIn post | working |
| `send_connection_request` | Send a LinkedIn connection request to a profile | working |
| `get_pending_invitations` | List pending incoming LinkedIn invitations | working |
| `follow_person` | Follow a LinkedIn person profile | working |
| `update_profile_headline` | Update the logged-in user's LinkedIn headline | working |
| `set_open_to_work` | Enable or disable the Open To Work profile signal | working |
| `add_profile_skills` | Add new skills to the logged-in user's profile | working |
| `close_session` | Close browser session and clean up resources | working |

<br/>
<br/>

## 🚀 uv + Git Setup (Recommended)

**Prerequisites:** [Git](https://git-scm.com/downloads) and [uv](https://docs.astral.sh/uv/getting-started/installation/).

### Installation

```bash
# 1. Clone repository
git clone https://github.com/rhythm493/linkedin-mcp-server
cd linkedin-mcp-server

# 2. Install dependencies
uv sync

# 3. Login to LinkedIn (first time only)
uv run -m linkedin_mcp_server --login

# 4. Start the server
uv run -m linkedin_mcp_server
```

**Client Configuration (Claude Desktop):**

```json
{
  "mcpServers": {
    "linkedin": {
      "command": "uv",
      "args": ["--directory", "/path/to/linkedin-mcp-server", "run", "-m", "linkedin_mcp_server"]
    }
  }
}
```

### Setup Help

<details>
<summary><b>🔧 Configuration</b></summary>

**Transport Modes:**

- **Default (stdio)**: Standard communication for local MCP servers
- **Streamable HTTP**: For web-based MCP server
- If no transport is specified, the server defaults to `stdio`
- An interactive terminal without explicit transport shows a chooser prompt

**CLI Options:**

- `--login` - Open browser to log in and save persistent profile
- `--no-headless` - Show browser window (useful for debugging scraping issues)
- `--log-level {DEBUG,INFO,WARNING,ERROR}` - Set logging level (default: WARNING)
- `--transport {stdio,streamable-http}` - Optional: force transport mode (default: stdio)
- `--host HOST` - HTTP server host (default: 127.0.0.1)
- `--port PORT` - HTTP server port (default: 8000)
- `--path PATH` - HTTP server path (default: /mcp)
- `--logout` - Clear stored LinkedIn browser profile
- `--timeout MS` - Browser timeout for page operations in milliseconds (default: 5000)
- `--tool-timeout SECONDS` - Per-tool MCP execution timeout in seconds (default: 180.0). Increase further for heavy scrapes / cold-start Chromium / slow networks.
- `--user-data-dir PATH` - Path to persistent browser profile directory (default: ~/.linkedin-mcp/profile)
- `--chrome-path PATH` - Path to Chrome/Chromium executable (for custom browser installations)

**Basic Usage Examples:**

```bash
# Run with debug logging
uv run -m linkedin_mcp_server --log-level DEBUG
```

**HTTP Mode Example (for web-based MCP clients):**

```bash
uv run -m linkedin_mcp_server --transport streamable-http --host 127.0.0.1 --port 8080 --path /mcp
```

Runtime server logs are emitted by FastMCP/Uvicorn.

Tool calls are serialized within a single server process to protect the shared
LinkedIn browser session. Concurrent client requests queue instead of running in
parallel. Use `--log-level DEBUG` to see scraper lock wait/acquire/release logs.

**Test with mcp inspector:**

1. Install and run mcp inspector ```bunx @modelcontextprotocol/inspector```
2. Click pre-filled token url to open the inspector in your browser
3. Select `Streamable HTTP` as `Transport Type`
4. Set `URL` to `http://localhost:8080/mcp`
5. Connect
6. Test tools

</details>

<details>
<summary><b>❗ Troubleshooting</b></summary>

**Installation issues:**

- Ensure you have uv installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Check uv version: `uv --version` (should be 0.4.0 or higher)

**Session issues:**

- Browser profile is stored at `~/.linkedin-mcp/profile/`
- Managed browser downloads are cached at `~/.linkedin-mcp/patchright-browsers/`
- Make sure you have only one active LinkedIn session at a time

**Login issues:**

- LinkedIn may require a login confirmation in the LinkedIn mobile app for `--login`
- You might get a captcha challenge if you logged in frequently. Run `uv run -m linkedin_mcp_server --login` which opens a browser where you can solve it manually.

**Timeout issues:**

- *Page operations failing* (elements not found, navigation hangs): increase the browser page-op timeout — `--timeout 10000` or `TIMEOUT=10000` (milliseconds, default 5000).
- *Entire tool calls timing out* (e.g. multi-section profiles, cold-start Chromium, slow containers): increase the per-tool execution timeout — `--tool-timeout 300` or `TOOL_TIMEOUT=300` (seconds, default 180).
- Users on slow connections may need higher values for either.

**Custom Chrome path:**

- If Chrome is installed in a non-standard location, use `--chrome-path /path/to/chrome`
- Can also set via environment variable: `CHROME_PATH=/path/to/chrome`

</details>

<br/>
<br/>

## 📦 Claude Desktop MCP Bundle (formerly DXT)

**Prerequisites:** [Claude Desktop](https://claude.ai/download).

**One-click installation** for Claude Desktop users:

1. Download the latest `.mcpb` artifact from [releases](https://github.com/rhythm493/linkedin-mcp-server/releases/latest)
2. Click the downloaded `.mcpb` file to install it into Claude Desktop
3. Call any LinkedIn tool

On startup, the MCP Bundle starts preparing the shared Patchright Chromium browser cache in the background. If you call a tool too early, Claude will surface a setup-in-progress error. On the first tool call that needs authentication, the server opens a LinkedIn login browser window and asks you to retry after sign-in.

### MCP Bundle Setup Help

<details>
<summary><b>❗ Troubleshooting</b></summary>

**First-time setup behavior:**

- Claude Desktop starts the bundle immediately; browser setup continues in the background
- If the Patchright Chromium browser is still downloading, retry the tool after a short wait
- Managed browser downloads are shared under `~/.linkedin-mcp/patchright-browsers/`

**Login issues:**

- Make sure you have only one active LinkedIn session at a time
- LinkedIn may require a login confirmation in the LinkedIn mobile app for `--login`
- You might get a captcha challenge if you logged in frequently. Run `uv run -m linkedin_mcp_server --login` which opens a browser where you can solve captchas manually. See the [setup guide](#-uv--git-setup-recommended).

**Timeout issues:**

- *Page operations failing* (elements not found, navigation hangs): increase the browser page-op timeout — `--timeout 10000` or `TIMEOUT=10000` (milliseconds, default 5000).
- *Entire tool calls timing out* (e.g. multi-section profiles, cold-start Chromium, slow containers): increase the per-tool execution timeout — `--tool-timeout 300` or `TOOL_TIMEOUT=300` (seconds, default 180).
- Users on slow connections may need higher values for either.

</details>

<br/>
<br/>

## 🐳 Docker Setup

Not available for this fork — build your own image from source using the Dockerfile in the repository.

<br/>
<br/>

## 🐍 Local Setup (Develop & Contribute)

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture guidelines and checklists. Please [open an issue](https://github.com/rhythm493/linkedin-mcp-server/issues) first to discuss the feature or bug fix before submitting a PR.

**Prerequisites:** [Git](https://git-scm.com/downloads) and [uv](https://docs.astral.sh/uv/) installed

### Installation

```bash
# 1. Clone repository
git clone https://github.com/rhythm493/linkedin-mcp-server
cd linkedin-mcp-server

# 2. Install UV package manager (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Install dependencies
uv sync
uv sync --group dev

# 4. Install pre-commit hooks
uv run pre-commit install

# 5. Start the server
uv run -m linkedin_mcp_server
```

The local server uses the same managed-runtime flow as MCPB: it prepares the Patchright Chromium browser cache in the background and opens LinkedIn login on the first auth-requiring tool call. You can still run `uv run -m linkedin_mcp_server --login` when you want to create the session explicitly.

### Local Setup Help

<details>
<summary><b>🔧 Configuration</b></summary>

**CLI Options:**

- `--login` - Open browser to log in and save persistent profile
- `--no-headless` - Show browser window (useful for debugging scraping issues)
- `--log-level {DEBUG,INFO,WARNING,ERROR}` - Set logging level (default: WARNING)
- `--transport {stdio,streamable-http}` - Optional: force transport mode (default: stdio)
- `--host HOST` - HTTP server host (default: 127.0.0.1)
- `--port PORT` - HTTP server port (default: 8000)
- `--path PATH` - HTTP server path (default: /mcp)
- `--logout` - Clear stored LinkedIn browser profile
- `--timeout MS` - Browser timeout for page operations in milliseconds (default: 5000)
- `--tool-timeout SECONDS` - Per-tool MCP execution timeout in seconds (default: 180.0). Increase further for heavy scrapes / cold-start Chromium / slow networks.
- `--status` - Check if current session is valid and exit
- `--user-data-dir PATH` - Path to persistent browser profile directory (default: ~/.linkedin-mcp/profile)
- `--slow-mo MS` - Delay between browser actions in milliseconds (default: 0, useful for debugging)
- `--user-agent STRING` - Custom browser user agent
- `--viewport WxH` - Browser viewport size (default: 1280x720)
- `--chrome-path PATH` - Path to Chrome/Chromium executable (for custom browser installations)
- `--help` - Show help

> **Note:** Most CLI options have environment variable equivalents. See `.env.example` for details.

**HTTP Mode Example (for web-based MCP clients):**

```bash
uv run -m linkedin_mcp_server --transport streamable-http --host 127.0.0.1 --port 8000 --path /mcp
```

**Claude Desktop:**

```json
{
  "mcpServers": {
    "linkedin": {
      "command": "uv",
      "args": ["--directory", "/path/to/linkedin-mcp-server", "run", "-m", "linkedin_mcp_server"]
    }
  }
}
```

`stdio` is used by default for this config.

</details>

<details>
<summary><b>❗ Troubleshooting</b></summary>

**Login issues:**

- Make sure you have only one active LinkedIn session at a time
- LinkedIn may require a login confirmation in the LinkedIn mobile app for `--login`
- You might get a captcha challenge if you logged in frequently. The `--login` command opens a browser where you can solve it manually.

**Scraping issues:**

- Use `--no-headless` to see browser actions and debug scraping problems
- Add `--log-level DEBUG` to see more detailed logging

**Session issues:**

- Browser profile is stored at `~/.linkedin-mcp/profile/`
- Use `--logout` to clear the profile and start fresh

**Python/Patchright issues:**

- Check Python version: `python --version` (should be 3.12+)
- Reinstall Patchright: `uv run patchright install chromium`
- Reinstall dependencies: `uv sync --reinstall`

**Timeout issues:**

- *Page operations failing* (elements not found, navigation hangs): increase the browser page-op timeout — `--timeout 10000` or `TIMEOUT=10000` (milliseconds, default 5000).
- *Entire tool calls timing out* (e.g. multi-section profiles, cold-start Chromium, slow containers): increase the per-tool execution timeout — `--tool-timeout 300` or `TOOL_TIMEOUT=300` (seconds, default 180).
- Users on slow connections may need higher values for either.

**Custom Chrome path:**

- If Chrome is installed in a non-standard location, use `--chrome-path /path/to/chrome`
- Can also set via environment variable: `CHROME_PATH=/path/to/chrome`

</details>


<br/>
<br/>

## Acknowledgements

Built with [FastMCP](https://gofastmcp.com/) and [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python).

Use in accordance with [LinkedIn's Terms of Service](https://www.linkedin.com/legal/user-agreement). Web scraping may violate LinkedIn's terms. This tool is for personal use only.

## License

This project is licensed under the Apache 2.0 license.

<br>
