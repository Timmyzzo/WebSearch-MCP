![Image](../pic/image.png)
<div align="center">

# Grok Search MCP

English | [简体中文](../README.md)

**Integrate Grok search capabilities into Claude via MCP protocol, significantly enhancing document retrieval and fact-checking abilities**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/FastMCP-2.0.0+-green.svg)](https://github.com/jlowin/fastmcp)

</div>

---

## Overview

Grok Search MCP is an MCP (Model Context Protocol) server built on [FastMCP](https://github.com/jlowin/fastmcp), providing real-time web search capabilities for AI models like Claude and Claude Code by leveraging the powerful search capabilities of third-party platforms (such as Grok).

### Core Value

- **Break Knowledge Cutoff Limits**: Enable Claude to access the latest web information, no longer limited by training data cutoff
- **Enhanced Fact-Checking**: Real-time search to verify information accuracy and timeliness
- **Structured Output**: Returns standardized JSON with title, link, and summary for easy AI model understanding and citation
- **Plug and Play**: Seamlessly integrates with Claude Desktop, Claude Code, and other clients via MCP protocol

### How It Works

```
Claude/Claude Code → MCP Call → Search MCP Service → Relay to Grok API → Web Search → Structured Results Return
```

1. Claude calls the `web_search` tool via MCP protocol
2. Search MCP forwards the request to the Grok third-party platform (OpenAI compatible interface)
3. Grok performs real-time web search and returns results
4. Search MCP formats results into structured JSON: `{title, url, content}`
5. Claude generates more accurate and up-to-date responses based on search results

## Why Choose Grok?

Comparison with other search solutions:

| Feature | Grok Search MCP | Google Custom Search API | Bing Search API | SerpAPI |
|---------|----------------|-------------------------|-----------------|---------|
| **AI-Optimized Results** | ✅ Optimized for AI understanding | ❌ General search results | ❌ General search results | ❌ General search results |
| **Content Summary Quality** | ✅ AI-generated high-quality summaries | ⚠️ Requires post-processing | ⚠️ Requires post-processing | ⚠️ Requires post-processing |
| **Real-time** | ✅ Real-time web data | ✅ Real-time | ✅ Real-time | ✅ Real-time |
| **Integration Complexity** | ✅ MCP plug and play | ⚠️ Requires development | ⚠️ Requires development | ⚠️ Requires development |
| **Return Format** | ✅ AI-friendly JSON | ⚠️ Requires formatting | ⚠️ Requires formatting | ⚠️ Requires formatting |

## Features

- ✅ Call Grok search capabilities via OpenAI compatible format
- ✅ Flexible TOML configuration file management
- ✅ Formatted search result output (title + link + summary)
- ✅ Extensible architecture, supports adding other search providers
- ✅ Comprehensive logging system for debugging and monitoring
- ✅ Debug mode toggle for development and testing

## Quick Start

<details>
<summary><h3>0. Prerequisites (Click to expand)</h3></summary>

#### Install Required Tools

**Python Environment**:
- Python 3.10 or higher
- Claude Code or Claude Desktop configured

**uv tool** (Recommended Python package manager):

Please ensure you have successfully installed the [uv tool](https://docs.astral.sh/uv/getting-started/installation/):

<details>
<summary><b>Windows Installation</b></summary>

Run the following command in PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

</details>

<details>
<summary><b>Linux/macOS Installation</b></summary>

Download and install using curl or wget:

```bash
# Using curl
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or using wget
wget -qO- https://astral.sh/uv/install.sh | sh
```

</details>

> **💡 Important Note**: We **strongly recommend** Windows users run this project in WSL (Windows Subsystem for Linux)!

#### Get Grok API Access

- Register an account on a third-party platform that supports Grok
- Obtain API Endpoint and API Key

</details>

### 1. Installation

Use `claude mcp add` for one-click installation and configuration:

```bash
claude mcp add grok-search -s user --transport stdio -- uvx --from git+https://github.com/GuDaStudio/GrokSearch.git grok-search
```

### 2. Configuration

#### Configuration File Description

Configuration file location:
- **Auto-created location**: `~/.config/grok-search/config.toml`

A configuration file template will be automatically created on first run. **You must configure the URL and KEY**, otherwise you cannot access the service.

Edit the `config.toml` file:

```toml
[debug]
enabled = false  # Set to false for production, true for development debugging

[grok]
api_url = "https://your-grok-api-endpoint.com/v1"  # Replace with actual Grok API address (currently supports OpenAI format)
api_key = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"    # Replace with your actual API Key

[logging]
level = "INFO"  # Log level: DEBUG, INFO, WARNING, ERROR
dir = "logs"    # Log file storage directory
```
Welcome to use our service https://cc.guda.studio/

⚠️ **Security Notes**:
- Do not commit `config.toml` containing real API Keys to Git
- This file is already excluded in `.gitignore`
- User directory configuration (`~/.config/grok-search/`) will not be tracked by Git

### 3. Verify Installation

```bash
claude mcp list
```

You should see the `grok-search` server registered.

### 4. Project Details

#### Tool Response Format

JSON structure returned by the `web_search` tool:

```json
{
  "results": [
    {
      "title": "FastMCP - Python framework for MCP servers",
      "url": "https://github.com/jlowin/fastmcp",
      "content": "FastMCP is a Python framework that makes it easy to build Model Context Protocol (MCP) servers..."
    },
    {
      "title": "FastMCP Documentation",
      "url": "https://fastmcp.readthedocs.io/",
      "content": "Complete guide to building MCP servers with FastMCP..."
    }
  ],
  "provider": "grok",
  "query": "FastMCP latest version"
}
```

---

## Project Architecture

```
grok-search/
├── config.toml.example         # Configuration file template
├── pyproject.toml              # Project metadata and dependencies
├── README.md                   # Project documentation
└── src/grok_search/
    ├── __init__.py             # Package entry
    ├── config.py               # Configuration management (TOML loading)
    ├── logger.py               # Logging system
    ├── server.py               # MCP server main program
    ├── utils.py                # Result formatting utilities
    └── providers/              # Search Provider abstraction layer
        ├── __init__.py
        ├── base.py             # SearchProvider base class
        └── grok.py             # Grok API implementation
```

### Core Module Description

| Module | Responsibility |
|--------|---------------|
| `server.py` | FastMCP service entry, registers `web_search` tool |
| `config.py` | Singleton pattern for TOML configuration management |
| `providers/base.py` | Defines `SearchProvider` abstract interface and `SearchResult` data model |
| `providers/grok.py` | Implements Grok API calls and response parsing |
| `utils.py` | Formats search results into AI-friendly text |

## Others

### Submit Issues

Having problems or suggestions? Please [submit an Issue](https://github.com/yourusername/grok-search/issues).

## FAQ

<details>
<summary><b>Q: How do I get Grok API access?</b></summary>

A: This project uses third-party platforms to relay Grok API. You need to:
1. Register with a third-party service that supports Grok (such as some AI Gateways)
2. Obtain API Endpoint and API Key
3. Configure the relevant information in `config.toml`
</details>

<details>
<summary><b>Q: Can I use multiple search providers simultaneously?</b></summary>

A: The current version only supports a single Provider. Multi-Provider support is on the roadmap and will be implemented in future versions.
</details>

<details>
<summary><b>Q: How do I control the number of search results?</b></summary>

A: The `web_search` tool accepts a `max_results` parameter (default 5), and Claude will automatically adjust as needed.
</details>

<details>
<summary><b>Q: Does it support other AI models?</b></summary>

A: Yes! Any client compatible with the MCP protocol can use it, including but not limited to Claude Desktop, Claude Code, and other MCP clients.
</details>

## License

This project is open source under the [MIT License](LICENSE).

---

<div align="center">

**If this project helps you, please give it a ⭐ Star!**
[![Star History Chart](https://api.star-history.com/svg?repos=GuDaStudio/GrokSearch&type=date&legend=top-left)](https://www.star-history.com/#GuDaStudio/GrokSearch&type=date&legend=top-left)

</div>
