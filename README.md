# Cold Email Hunter

Automated daily cold email outreach for SWE job applications. Runs on a schedule inside Claude Code — no manual work required each day.

## What It Does

Every day it:
1. Scrapes Indeed for entry-level / new grad SWE job postings
2. Finds a recruiter or engineer at each company via Hunter.io
3. Writes a personalized cold email referencing the specific job URL
4. Sends it via Gmail
5. Logs everything and skips companies contacted in the last 30 days

Max 10 emails per run. Only sends to verified email addresses.

## Setup

**1. Clone and install dependencies**

```bash
cd F:\cold-email-hunter
setup.bat
```

**2. Fill in `data/config.json`**

```json
{
  "hunter_io_api_key": "your key from hunter.io/api-keys",
  "gmail_address": "you@gmail.com",
  "gmail_app_password": "xxxx xxxx xxxx xxxx",
  "apify_token": "your token from console.apify.com/account/integrations"
}
```

For the Gmail app password: Google Account → Security → 2-Step Verification → App passwords.

**3. Register the MCP server**

```bash
claude mcp add cold-email-tools -s user -e PYTHONUNBUFFERED=1 -- "F:\cold-email-hunter\.venv\Scripts\python.exe" -m agent.mcp_server
```

**4. Restart Claude Code**

The `cold-email-tools` server should show as Connected in `claude mcp list`.

**5. Test it**

Ask Claude: *"Call mcp__cold-email-tools__get_config and show me what it returns"*

If you see your config, you're ready.

## Running

**Manual:**
> "Run the cold-email-agent subagent to do today's outreach"

**Scheduled (daily):**
The `cold-email-daily` scheduled task in Claude Code handles this automatically.

## Project Structure

```
cold-email-hunter/
├── agent/
│   └── mcp_server.py      # FastMCP server — 9 tools
├── data/
│   ├── config.json        # API keys + candidate profile
│   └── contacted.json     # Auto-managed dedup list
├── docs/
│   └── cold_email.md      # Email template guide
├── requirements.txt
└── setup.bat
```

## Stack

- **Claude Code** — scheduled task + subagent orchestration
- **FastMCP** — Python MCP server exposing tools to the agent
- **Apify** — Indeed job scraping
- **Hunter.io** — recruiter email lookup and verification
- **Gmail** — SMTP sending, IMAP reply checking

## Notes

- `contacted.json` is auto-managed. Don't edit it manually.
- The 30-day company cooldown is enforced per run via `contacted.json`.
- Optional: set `google_sheet_id` in config for Google Sheets logging, `slack_webhook_url` for Slack summaries.
