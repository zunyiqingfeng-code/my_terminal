# ds.py

一个运行在终端里的 coding agent。理解你的代码库、读写文件、执行命令、跨会话记忆。DeepSeek 驱动。

A coding agent that lives in your terminal. Understands your codebase, edits files, runs commands, and remembers across sessions. Powered by DeepSeek.

## 快速开始 / Quick Start

```bash
export DEEPSEEK_API_KEY="sk-your-key-here"
pip install -r requirements.txt
python ds.py
```

启动后输入 `/help` 查看所有命令。首次运行会自动创建 `~/.ds_memory/` 和 `~/.ds_live/` 目录。

Type `/help` after launch to see all commands. First run auto-creates `~/.ds_memory/` and `~/.ds_live/`.

## 工作方式 / How It Works

ds.py 在终端里启动一个对话循环。你输入需求，它读取文件系统、执行 shell 命令、搜索网页、编辑代码 —— 所有操作带行号精度。

**文件系统** —— 读、写、编辑（精确字符串替换）、glob 模式匹配、grep 内容搜索。编辑操作要求 old_string 在文件中唯一匹配，防止误改。

**Shell** —— 执行系统命令，支持前台/后台运行。后台任务返回 job_id，可随时查询输出和状态。危险命令模式（rm -rf、git push --force 等）在首次出现时拦截确认。

**Web** —— 多引擎搜索，默认自动模式跨 Bing/DDG 切换，可指定 baidu/ddg。`fetch_url` 带编码检测和代理重试，HTML 转纯文本。

**Vision** —— 截图和图片分析，本地文件经 PIL 编码为 JPEG 后送 Qwen-VL-Plus（DashScope API）。1 小时缓存。`/image <path>` 将图片附到对话上下文。

**Memory** —— 长记忆存在 `~/.ds_memory/`，Markdown 文件 + YAML frontmatter。索引文件 `MEMORY.md` 分 User/Feedback/Project/Reference 四区。BM25 全文检索支持中英文混合分词。AI 可通过 XML 标签自动新增/删除记忆。会话结束自动生成摘要存入记忆。

**Agents** —— 内置 explore/plan/research/general 四种子代理。explore 只读代码探索，plan 输出详细方案，research 负责网页搜索和分析，general 拥有完整工具权限（不含递归 spawn 和会话操作）。自定义 agent 在 `~/.ds_agents/` 下放 Markdown 文件，YAML frontmatter 声明 name/description/tools/model，正文写系统提示词。子代理独立消息上下文，最多 20 轮，任务完成调用 `task_complete` 退出。

**Multi-instance** —— 多实例协作通过 `~/.ds_live/` 目录。每个实例注册 PID 和启动时间，通过 append-only JSONL 信箱互发消息。`/who` 列出在线实例，`/send <name> <msg>` 发送消息，`/inbox` 读取收件，每次输入提示前自动检查新消息。

**MCP Server** —— 弹性 MCP 服务池，max_workers=5，scale_threshold=3，idle_timeout=60s。daemon 线程启动。

**本地模型** —— 断网时 fallback 到 Ollama（localhost:11434，默认 qwen3:8b-16k）。`local_model` 工具支持 list/ask/status 三种操作。

**Browser** —— 通过 BrowserWing HTTP API（localhost:8080）操控 Chrome，32 种浏览器动作，断连自动重连/重启。

**计划模式** —— `/plan <task>` 启动。模型先输出详细计划步骤，确认后执行。`/retry` 回退最后一轮对话重跑，`/clear` 清空对话保留记忆。

ds.py starts a conversation loop in your terminal. You type what you want. It reads your filesystem, executes shell commands, searches the web, and edits code — all with line-number precision.

File operations include read/write/edit with unique-match enforcement, glob pattern matching, and grep content search. Shell execution supports foreground and background modes with job status polling. Web search spans multiple engines with automatic proxy failover. Image analysis goes through Qwen-VL-Plus with a 1-hour cache.

Long-term memory persists in `~/.ds_memory/` with BM25 search over Markdown files. The AI can auto-manage memories via XML tags. Sessions are archived on exit and the last session context is injected on next start.

Four built-in agent types — explore, plan, research, general — each with scoped tool access. Custom agents are defined as Markdown files in `~/.ds_agents/` with YAML frontmatter. Sub-agents run in isolated message loops with max 20 rounds.

Multi-instance collaboration works through `~/.ds_live/` — each instance registers itself, sends JSONL-formatted messages to others, and checks inboxes before every input prompt. An elastic MCP server pool runs as a daemon thread for tool server orchestration.

Ollama fallback kicks in when the DeepSeek API is unreachable. Browser automation is available through BrowserWing. SolidWorks CAD automation tools are included as optional extras.

## 配置 / Configuration

所有敏感值从环境变量读取，不硬编码。

All sensitive values come from environment variables. Nothing is hardcoded.

| 变量 Variable | 必需 Required | 说明 Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | 是 Yes | DeepSeek API key |
| `VISION_API_KEY` | 否 No | Qwen-VL API key（DashScope） |
| `PYTHON_BIN` | 否 No | Python 解释器路径，默认当前解释器 |

代理设置（`HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`）启动时自动检测并补全。

Proxy settings are auto-detected and configured at startup.

## 扩展 / Extending

三种扩展机制，模板文件随仓库发布。

Three extension mechanisms. Templates ship with the repo.

### 自定义 Agent / Custom Agents

在 `~/.ds_agents/` 下放置 `.md` 文件：

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

通过 tool `spawn_subagent` 或 `/agents` 列表调用。

### 自定义 Skill / Custom Skills

Python 模块放在 `~/.ds_skills/<name>/`。每个 skill 定义 tool 函数，ds.py 自动发现并注册。Skill 配置文件为 `skill_config.yaml`，声明名称、版本、依赖和接口。

Python modules in `~/.ds_skills/<name>/`. Each skill defines tool functions that ds.py auto-discovers and registers. Configuration via `skill_config.yaml`.

### 自定义命令 / Custom Commands

Slash 命令定义在 `~/.ds_commands/<name>/COMMAND.md`。可调用 agent 或触发预设工作流。

Slash commands live in `~/.ds_commands/<name>/COMMAND.md`. They can invoke agents or trigger predefined workflows.

## 命令参考 / Command Reference

| 命令 Command | 操作 Action |
|---|---|
| `/model chat\|r1` | 切换模型 Switch model |
| `/memory` | 列出所有记忆 List all memories |
| `/forget <name>` | 删除指定记忆 Delete a memory |
| `/clear` | 清空对话 Keep memories, clear chat |
| `/retry` | 重跑上一条消息 Re-run last message |
| `/context` | 显示会话统计 Show session stats |
| `/sessions` | 列出历史会话 List past sessions |
| `/plan <task>` | 计划模式 Planning mode |
| `/agents` | 列出可用代理 List agents |
| `/image <path>` | 附加图片 Attach image |
| `/who` | 列出在线实例 List online instances |
| `/send <name> <msg>` | 发送消息到另一实例 Send to another instance |
| `/inbox [clear]` | 读取/清空收件箱 Read or clear inbox |
| `/name <name>` | 设置实例名 Set instance name |
| `/todo [clear]` | 显示/清空任务列表 Show or clear task list |
| `/network` | 网络状态 Network status |
| `/netmon` | 切换网络监控 Toggle network monitoring |

`Esc` 或 `Ctrl+C` 中断当前 AI 流式输出。

`Esc` or `Ctrl+C` interrupts the current AI stream.

## 项目结构 / Project Structure

```
ds.py                              # 主 CLI Main CLI (~6500 lines)
ds_input.py                        # 自定义输入会话 Custom input session
terminal_frame.py                  # Claude Code 风格底部输入面板 Bottom input panel
enhanced_api_fixer.py              # API 代理检测与健康检查 Proxy detection & health checks
simple_network_monitor.py          # 后台网络监控 Background network monitoring
keyboard_library.py                # 输入处理工具 Input handling utilities
vision_helper.py                   # Vision API 集成 Vision API integration
ds_solidworks_tool.py              # SolidWorks CAD 自动化 (可选 optional)
ds_mcp_improved_framework.py       # MCP 服务池框架 MCP server pool framework
ds_mcp_improved_framework_fixed.py # MCP 框架修复版 MCP framework (fixed)
.ds_agents/                        # Agent 定义模板 Agent definition templates
.ds_skills/                        # Skill 模块模板 Skill module templates
.ds_commands/                      # Slash 命令模板 Slash command templates
```

## 依赖 / Requirements

- Python 3.10+
- DeepSeek API key — [获取 Get one](https://platform.deepseek.com)

Python 依赖见 `requirements.txt`。Python dependencies listed in `requirements.txt`.

## License

MIT
