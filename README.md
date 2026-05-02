# DS Terminal

A terminal-native AI assistant powered by DeepSeek. Built from scratch in Python, modeled after Claude Code's interaction patterns — autonomous tool calling, persistent memory, multi-agent orchestration, and multi-instance collaboration.

## Quick Start

```bash
# 1. Set your API key
export DEEPSEEK_API_KEY="sk-your-key-here"

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch
python ds.py
```

Type `/help` to see all commands.

## Capabilities

**File system** — read, write, edit (exact string replacement), glob, grep. All with line-number precision.

**Shell** — execute system commands, run background jobs, monitor output in real-time.

**Web** — multi-engine search (auto / Bing / Baidu / DDG), fetch any URL with proxy fallback.

**Vision** — read images and screenshots via Qwen-VL (set `VISION_API_KEY` to enable).

**Memory** — persistent long-term memory in `~/.ds_memory/`. Markdown files + BM25 search. Survives restarts.

**Agents** — spawn sub-agents for exploration, planning, research, or general tasks. Define custom agents in `~/.ds_agents/` with YAML frontmatter.

**Multi-instance** — run multiple DS instances, message each other, delegate tasks across sessions. Instance registry in `~/.ds_live/`.

**MCP Server** — elastic pool with auto-scaling for tool servers.

**Local models** — fallback to Ollama when offline (optional, requires `ds_local_model.py`).

## Configuration

All sensitive values come from environment variables. Nothing is hardcoded.

| Variable | Required | Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | Yes | DeepSeek API key |
| `VISION_API_KEY` | No | Qwen-VL key (Alibaba DashScope) |
| `PYTHON_BIN` | No | Python executable path (default: current interpreter) |

## Extending

### Custom Agents

Drop a `.md` file in `~/.ds_agents/`:

```markdown
---
name: my-agent
description: What this agent does
tools: [shell, read_file, grep_files]
model: deepseek-chat
---

Agent instructions in Markdown.
```

Then call it: `/agent my-agent <task>`

### Custom Skills

Skills are Python modules in `~/.ds_skills/<name>/`. Each skill defines tool functions that DS auto-discovers and registers.

### Custom Commands

Slash commands live in `~/.ds_commands/<name>/COMMAND.md`. They can invoke agents or run predefined workflows.

## Requirements

- Python 3.10+
- DeepSeek API key ([get one here](https://platform.deepseek.com))

## Project Structure

```
ds.py                          # Main CLI (~6500 lines)
ds_input.py                    # Custom input session
terminal_frame.py              # Claude Code-style bottom input panel
enhanced_api_fixer.py          # API proxy detection & health checks
simple_network_monitor.py      # Background network monitoring
keyboard_library.py            # Input handling utilities
vision_helper.py               # Vision API integration
ds_solidworks_tool.py          # SolidWorks CAD automation (optional)
ds_mcp_improved_framework*.py  # MCP server cluster framework
.ds_agents/                    # Agent definition templates
.ds_skills/                    # Skill module templates
.ds_commands/                  # Slash command templates
```

## License

MIT
