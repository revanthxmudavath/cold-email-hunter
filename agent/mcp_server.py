"""
Cold Email Hunter — FastMCP Server
9 tools for the cold-email-agent subagent.

CRITICAL: Never write to stdout — it corrupts the JSON-RPC stream.
All logging goes to stderr via the log object below.
"""
import asyncio
import email as email_lib
import imaplib
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiofiles
import aiosmtplib
import requests
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

# ── Logging: stderr only, never stdout ────────────────────────────────────────
logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("cold-email-tools")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "data" / "config.json"
CONTACTED_PATH = BASE_DIR / "data" / "contacted.json"

# ── MCP App ───────────────────────────────────────────────────────────────────
mcp = FastMCP("cold-email-tools")


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _load_config() -> dict:
    """Read data/config.json."""
    try:
        async with aiofiles.open(CONFIG_PATH) as f:
            return json.loads(await f.read())
    except FileNotFoundError:
        raise ToolError(
            f"config.json not found at {CONFIG_PATH}. "
            "Run setup.bat and fill in data/config.json."
        )


async def _load_contacted() -> dict:
    """Read data/contacted.json, returning empty structure if missing."""
    if not CONTACTED_PATH.exists():
        return {"contacts": []}
    async with aiofiles.open(CONTACTED_PATH) as f:
        raw = await f.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(f"contacted.json is corrupted: {exc}. Fix or delete data/contacted.json.") from exc


async def _save_contacted(data: dict) -> None:
    """Write data/contacted.json atomically via .tmp rename."""
    tmp = CONTACTED_PATH.with_suffix(".tmp")
    async with aiofiles.open(tmp, "w") as f:
        await f.write(json.dumps(data, indent=2))
    await asyncio.get_running_loop().run_in_executor(None, tmp.replace, CONTACTED_PATH)


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_config() -> dict:
    """Load candidate config, API keys, and job search settings. Call this first on every run."""
    return await _load_config()


@mcp.tool()
async def lookup_email(first_name: str, last_name: str, domain: str) -> dict:
    """Find a contact's work email via Hunter.io. Returns {email, confidence, first_name, last_name}. Skip if confidence < 70."""
    cfg = await _load_config()
    api_key = cfg.get("hunter_io_api_key", "")
    if not api_key or api_key == "FILL_IN":
        raise ToolError("hunter_io_api_key not set in data/config.json")

    def _call() -> dict:
        resp = requests.get(
            "https://api.hunter.io/v2/email-finder",
            params={"domain": domain, "first_name": first_name, "last_name": last_name, "api_key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    result = await asyncio.get_running_loop().run_in_executor(None, _call)
    data = result.get("data", {})
    return {
        "email": data.get("email"),
        "confidence": data.get("score", 0),
        "first_name": data.get("first_name"),
        "last_name": data.get("last_name"),
    }


@mcp.tool()
async def verify_email(email_address: str) -> dict:
    """Verify an email via Hunter.io. Returns {email, status, deliverability, verified}. Only send if verified=True."""
    cfg = await _load_config()
    api_key = cfg.get("hunter_io_api_key", "")
    if not api_key or api_key == "FILL_IN":
        raise ToolError("hunter_io_api_key not set in data/config.json")

    def _call() -> dict:
        resp = requests.get(
            "https://api.hunter.io/v2/email-verifier",
            params={"email": email_address, "api_key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    result = await asyncio.get_running_loop().run_in_executor(None, _call)
    data = result.get("data", {})
    status = data.get("status", "unknown")
    return {
        "email": data.get("email"),
        "status": status,
        "deliverability": data.get("result"),
        "verified": status == "valid",
    }


@mcp.tool()
async def send_email(to: str, subject: str, body: str) -> dict:
    """Send a cold email via Gmail SMTP. Body must be plain text (no HTML). Returns {sent, to, subject}."""
    cfg = await _load_config()
    gmail = cfg.get("gmail_address", "")
    app_pw = cfg.get("gmail_app_password", "")
    if not gmail or gmail == "FILL_IN":
        raise ToolError("gmail_address not set in data/config.json")
    if not app_pw or app_pw == "FILL_IN":
        raise ToolError("gmail_app_password not set in data/config.json")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Revanth Mudavath <{gmail}>"
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))

    try:
        await aiosmtplib.send(
            msg,
            hostname="smtp.gmail.com",
            port=587,
            start_tls=True,
            username=gmail,
            password=app_pw,
        )
    except Exception as exc:
        raise ToolError(f"SMTP send failed: {exc}") from exc
    log.info(f"Sent email to {to}: {subject}")
    return {"sent": True, "to": to, "subject": subject}


@mcp.tool()
async def check_replies() -> list:
    """Check Gmail IMAP for replies in the last 30 days. Returns list of {from, subject, date, in_reply_to}."""
    cfg = await _load_config()
    gmail = cfg.get("gmail_address", "")
    app_pw = cfg.get("gmail_app_password", "")
    if not gmail or gmail == "FILL_IN":
        raise ToolError("gmail_address not set in data/config.json")
    if not app_pw or app_pw == "FILL_IN":
        raise ToolError("gmail_app_password not set in data/config.json")

    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%d-%b-%Y")

    def _fetch() -> list:
        replies = []
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail, app_pw)
        mail.select("inbox")
        _, data = mail.search(None, f'(SINCE "{since}" NOT FROM "{gmail}")')
        ids = (data[0].split() or [])[-20:]
        for uid in ids:
            _, msg_data = mail.fetch(uid, "(RFC822)")
            msg = email_lib.message_from_bytes(msg_data[0][1])
            if msg.get("In-Reply-To"):
                replies.append({
                    "from": msg.get("From"),
                    "subject": msg.get("Subject"),
                    "date": msg.get("Date"),
                    "in_reply_to": msg.get("In-Reply-To"),
                })
        mail.close()
        mail.logout()
        return replies

    try:
        return await asyncio.get_running_loop().run_in_executor(None, _fetch)
    except Exception as exc:
        raise ToolError(f"IMAP check_replies failed: {exc}") from exc


@mcp.tool()
async def read_contacted_list() -> dict:
    """Read contacted.json for 30-day company cooldown check. Returns {contacts: [...]}."""
    return await _load_contacted()


@mcp.tool()
async def update_contacted_list(
    email_address: str,
    company: str,
    contact_name: str,
    role: str,
    job_url: str,
    status: str = "sent",
) -> dict:
    """Append an entry to contacted.json. Call after every successful send_email."""
    data = await _load_contacted()
    entry = {
        "email": email_address,
        "company": company,
        "contact_name": contact_name,
        "role": role,
        "job_url": job_url,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
    }
    data["contacts"].append(entry)
    await _save_contacted(data)
    log.info(f"Logged contact: {contact_name} @ {company}")
    return {"updated": True, "total_contacts": len(data["contacts"])}


@mcp.tool()
async def update_sheet(
    contact_name: str,
    company: str,
    role: str,
    job_url: str,
    email_address: str,
    status: str = "sent",
) -> dict:
    """Append a row to Google Sheets. No-op if google_sheet_id not configured."""
    cfg = await _load_config()
    sheet_id = cfg.get("google_sheet_id", "")
    if not sheet_id:
        log.warning("google_sheet_id not configured — skipping sheet update")
        return {"updated": False, "reason": "google_sheet_id not configured"}

    def _append():
        import gspread
        from google.oauth2.service_account import Credentials
        creds_path = BASE_DIR / "data" / "google_credentials.json"
        if not creds_path.exists():
            raise RuntimeError("data/google_credentials.json not found for Sheets auth")
        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(sheet_id).sheet1
        sheet.append_row([datetime.now(timezone.utc).strftime("%Y-%m-%d"), contact_name, company, role, email_address, job_url, status])

    try:
        await asyncio.get_running_loop().run_in_executor(None, _append)
    except RuntimeError as exc:
        raise ToolError(str(exc)) from exc
    return {"updated": True, "company": company, "role": role}


@mcp.tool()
async def notify_slack(message: str) -> dict:
    """Post a summary to Slack. No-op if slack_webhook_url not configured."""
    cfg = await _load_config()
    webhook = cfg.get("slack_webhook_url", "")
    if not webhook:
        log.warning("slack_webhook_url not configured — skipping Slack notification")
        return {"sent": False, "reason": "slack_webhook_url not configured"}

    def _post():
        resp = requests.post(webhook, json={"text": message}, timeout=5)
        resp.raise_for_status()

    await asyncio.get_running_loop().run_in_executor(None, _post)
    log.info("Slack notification sent")
    return {"sent": True}


@mcp.tool()
async def search_jobs(query: str, max_results: int = 10) -> list:
    """
    Find SWE job postings via Apify Indeed scraper (synchronous — no polling).
    Returns list of {title, company, url, location, description}.
    Jobs without a direct apply URL are pre-filtered out.
    Single HTTP call — no polling loop needed.
    """
    cfg = await _load_config()
    api_key = cfg.get("apify_token", "")
    if not api_key or api_key == "FILL_IN":
        raise ToolError("apify_token not set in data/config.json")

    def _run() -> list:
        from apify_client import ApifyClient
        client = ApifyClient(api_key)
        run = client.actor("borderline/indeed-scraper").call(
            run_input={
                "query": query,
                "country": "us",
                "maxRows": max_results,
                "level": "entry_level",
                "jobType": "fulltime",
                "fromDays": "7",
            },
            timeout_secs=300,
        )
        if not run:
            raise ToolError("Apify actor run returned no result")
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        jobs = []
        for item in items:
            url = item.get("applyUrl") or item.get("jobUrl") or ""
            if not url:
                continue
            loc = item.get("location") or {}
            jobs.append({
                "title": item.get("title", ""),
                "company": "",  # actor doesn't return company name; agent uses WebFetch
                "url": url,
                "location": loc.get("formattedAddressShort", "") if isinstance(loc, dict) else str(loc),
                "description": (item.get("descriptionText") or "")[:400],
            })
        return jobs

    return await asyncio.get_running_loop().run_in_executor(None, _run)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()
