# Retired Files — Haven Migration Log

## 2026-06-09 — ToolOutput Integration + AgentLoop Retirement

### Retired
| File | Reason |
|------|--------|
| `haven_discord.py` | Temporary standalone Discord bot; replaced by `dev/kid/core/router.py` + `dev/kid/transport/discord_bot.py` |
| `haven_telegram.py` | Temporary standalone Telegram bot; replaced by `dev/kid/transport/telegram_bot.py` |
| `agent/loop.py` | AgentLoop (standalone ReAct); superseded by `dev/kid/core/router.py` Router |
| `agent/model.py` | DeepSeek model wrapper for AgentLoop; superseded by `dev/kid/core/http_provider.py` + `base_provider.py` |
| `agent/tools/discord_file_tool.py` | AgentLoop-specific tool; router uses `dev/kid/tools/` registry |
| `agent/tools/mail_tool.py` | AgentLoop-specific tool; router uses `dev/kid/tools/` registry |
| `agent/tools/scan_tool.py` | AgentLoop-specific tool; router uses `dev/kid/tools/` registry |

### Retained
| File | Reason |
|------|--------|
| `agent/tool_output.py` | **Integrated** into Router's `_execute_tool()`; shared output contract |
| `agent/tool_spec.py` | Referenced by tool registration machinery |
| `agent/tool_to_registry.py` | Referenced by tool registration machinery |

### Architecture Post-Migration
```
dev/kid/
├── core/router.py         — ReAct loop with ToolOutput wrapping
├── transport/
│   ├── discord_bot.py     — Discord transport
│   └── telegram_bot.py    — Telegram transport
├── main.py                — Shared entry point (Discord + Telegram + Terminal)
├── tools/                 — @tool-decorated implementations
│
agent/
├── tool_output.py         — shared output contract (used by router)
├── tool_spec.py           — shared (used by dev/kid/)
└── tool_to_registry.py    — shared (used by dev/kid/)
```
