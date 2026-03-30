# Cold Email Hunter

Automated cold email outreach system for Revanth Mudavath's SWE job search.

## What This Does

Daily scheduled task finds entry-level SWE job postings (LinkedIn + Indeed via Apify), finds recruiter contacts (Hunter.io), writes personalized cold emails referencing specific job URLs, and sends them via Gmail. Tracks sent contacts with 30-day company cooldown.

## Architecture

```
[Scheduled Task: cold-email-daily]  →  [cold-email-agent subagent]
                                            ├─ WebSearch/WebFetch (built-in)
                                            ├─ mcp__apify__* (job scraping)
                                            └─ mcp__cold-email-tools__* (this server)
```

The Python FastMCP server (`agent/mcp_server.py`) runs over stdio and exposes 9 tools.

## Key Files

| File | Purpose |
|------|---------|
| `agent/mcp_server.py` | FastMCP server — all 9 MCP tools |
| `data/config.json` | API keys + Revanth's profile (fill in FILL_IN values) |
| `data/contacted.json` | Auto-managed dedup list (don't edit manually) |
| `docs/cold_email.md` | Email template guide the agent follows |
| `C:\Users\DELL\.claude\agents\cold-email-agent.md` | Agent definition |
| `C:\Users\DELL\.claude\scheduled-tasks\cold-email-daily\SKILL.md` | Daily trigger |
| `C:\Users\DELL\.claude\settings.local.json` | MCP server config |

## Setup (one-time)

```bat
cd F:\cold-email-hunter
setup.bat
# Then fill in data\config.json
```

## Running the MCP Server (for testing)

```bash
.venv\Scripts\python.exe -m agent.mcp_server
```

No output = good. It waits on stdin for JSON-RPC messages.

## Critical Rules

- **NEVER write to stdout** in `mcp_server.py` — it corrupts the JSON-RPC stream. Use `log.info()` (goes to stderr).
- **PYTHONUNBUFFERED=1** must be set in the MCP config (already in settings.local.json) — without it, Python buffers stdout and the MCP client hangs.
- All tools must be `async def`. No sync blocking calls — use `asyncio.get_event_loop().run_in_executor(None, ...)` for sync library calls.
- Tools must raise `ToolError` (from `fastmcp.exceptions`) for expected failures (missing config, API errors) — not generic Python exceptions.

## MCP Tools (9 total)

1. `get_config` — read data/config.json
2. `lookup_email` — Hunter.io email finder
3. `verify_email` — Hunter.io email verifier
4. `send_email` — Gmail SMTP
5. `check_replies` — Gmail IMAP (inbox scan)
6. `read_contacted_list` — read data/contacted.json
7. `update_contacted_list` — append to data/contacted.json
8. `update_sheet` — Google Sheets (optional, no-op if unconfigured)
9. `notify_slack` — Slack webhook (optional, no-op if unconfigured)

## Candidate Profile

Revanth Mudavath — MS CS @ Oregon State (GPA 4.0, March 2026).
Target: new grad SWE / backend engineer roles.
Key email bullets (in data/config.json `achievements` field):
- 30+ REST API endpoints, 50K users (StylePilot.ai)
- 75% latency reduction via PostgreSQL dual-indexing
- 45%→78% test coverage (SpeedScore)
- 60+ articles/min event-driven microservices (RaveDigest)

## Dependencies

```
fastmcp>=2.0.0, aiofiles, aiosmtplib, requests, gspread, google-auth
```

Venv: `.venv\` (run `setup.bat` to create)
