# ds.py

A coding agent that lives in your terminal. Understands your codebase, edits files, runs commands, and remembers across sessions. Powered by DeepSeek.

## Setup

```bash
export DEEPSEEK_API_KEY="sk-your-key-here"
pip install -r requirements.txt
python ds.py
```

Type `/help` to see all commands.

## How it works

ds.py starts a conversation loop in your terminal. You type what you want. It reads your filesystem, executes shell commands, searches the web, and edits code — all with line-number precision.

It spawns sub-agents for exploration, planning, research, or general tasks. Custom agents are defined as Markdown files with YAML frontmatter in `~/.ds_agents/`.

Memory persists across restarts in `~/.ds_memory/` with BM25 search over Markdown files. Multiple instances can message each other through `~/.ds_live/` — run one per terminal tab and delegate work across sessions.

Set `VISION_API_KEY` to enable image analysis via Qwen-VL. Set `PYTHON_BIN` to override the Python interpreter used for in-process code execution.

Templates for agents, skills, and commands ship in `.ds_agents/`, `.ds_skills/`, and `.ds_commands/`.

Python 3.10+. DeepSeek API key required. [Get one here](https://platform.deepseek.com).

## License

MIT
