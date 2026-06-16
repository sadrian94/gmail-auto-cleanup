# Gmail Auto-Cleanup & Primary Inbox Analyzer

An automated, safety-first, AI-enhanced email cleanup system and Primary Inbox analyzer for Gmail. 

Built using standard Python IMAP libraries (zero external API registration required) and SQLite for trend tracking, it runs once a week to move promotions, social notifications, and old receipts to the Trash, while profiling your Primary Inbox for newsletters and clutter to recommend manual cleanup.

---

## 📐 Architecture & Workflow

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Gmail Auto-Cleanup Tool                         │
│                                                                        │
│   ┌─────────────────────┐  ┌──────────────────────────────────────┐    │
│   │  🧹 Cleanup Engine   │  │  📊 Primary Inbox Analyzer           │    │
│   │  (Pillar 1)         │  │  (Pillar 2)                          │    │
│   │  • Promotions > 30d │  │  • Scans past 30 days of Primary     │    │
│   │  • Social > 7d      │  │  • Analyzes Unread vs Read           │    │
│   │  • Receipts > 2y    │  │  • List-Unsubscribe Header Parser    │    │
│   │  • Chunks of 500    │  │  • Identifies top newsletter senders │    │
│   └─────────┬───────────┘  └──────────────────┬───────────────────┘    │
│             │                                 │                        │
│             └────────────────┬────────────────┘                        │
│                              ▼                                         │
│                   ┌──────────────────────┐                             │
│                   │  💾 SQLite Analytics │                             │
│                   │  • Save run history  │                             │
│                   │  • Log inbox sizes   │                             │
│                   └──────────┬───────────┘                             │
│                              ▼                                         │
│                   ┌──────────────────────┐                             │
│                   │   📝 Weekly Report   │                             │
│                   │  • Growth WoW trends │                             │
│                   │  • Unsubscribe tips  │                             │
│                   │  • Copy-paste Search │                             │
│                   └──────────────────────┘                             │
└────────────────────────────────────────────────────────────────────────┘
```

1. **Clean & Scrape:** Connects securely to Gmail IMAP, runs configured cleanup rules, and fetches headers from the past 30 days of the Primary Inbox.
2. **Log SQLite Stats:** Records sizes, rule deletions, sender analytics, and unread statistics to `~/.gmail_cleanup/analytics.db`.
3. **Generate Weekly Report:** Programmatically evaluates email trends, growth rates, and clutter senders, compiling them into a beautiful Markdown report file (Weekly-Cleanup-Report-YYYY-MM-DD.md).
4. **Obsidian Integration:** Directly publishes the report into your Obsidian Vault's `00 - Inbox/Agent_Output/` directory for immediate viewing.

---

## 🚀 Installation & Setup

This tool uses [uv](https://github.com/astral-sh/uv) for fast, reliable package management.

### 1. Clone & Install
Install the tool in editable mode with development/testing dependencies:
```bash
git clone https://github.com/sadrian94/gmail-auto-cleanup.git
cd gmail-auto-cleanup
uv pip install -e .[test,ai]
```

### 2. Configure Settings (`config.yaml`)
Create a configuration file at `~/.gmail_cleanup/config.yaml` or directly in the workspace root as `config.yaml`.

```yaml
accounts:
  dummy: wokfromhomie@gmail.com
  personal: sadrian94@gmail.com

# Path to write weekly report markdown files directly into Obsidian
obsidian_vault_path: "C:/Users/sadri/Obsidian/My_Vault"

# Days of age required before moving to Gmail Trash
rules:
  promotions:
    days: 30
    action: TRASH
    enabled: true
  social:
    days: 7
    action: TRASH
    enabled: true
  receipts:
    days: 730  # 2 years
    action: TRASH
    enabled: true
```

### 3. Secure Credentials Setup (Keyring)
Instead of plaintext passwords on disk, credentials are saved inside your operating system's Keychain/Credential Locker.

Run the interactive setup flag to register your **Gmail App Password** (generate one under Google Account > Security > App Passwords):
```bash
# Register personal account password
gmail-cleanup --account personal --set-password
```

---

## 💻 CLI Reference

### 🔍 Dry-Run Mode (Safe — no changes)
Verify what will be deleted and scan the Primary Inbox:
```bash
# Scan dummy account
gmail-cleanup --account dummy

# Scan personal account (Deep sender scan + Primary Inbox profile)
gmail-cleanup --account personal --analytics-deep
```

### 🧹 Execution Mode (Actually Clean & Log)
Move matching Promotions/Social/Receipts to Trash and record stats:
```bash
# Run weekly cleanup + update database + output Markdown report
gmail-cleanup --account personal --analytics-deep --apply --ai-summary
```

### 📊 Reports & Summaries
View historical runs and trends directly from the SQLite database:
```bash
# Print raw JSON weekly metrics
gmail-cleanup --report

# Print human-readable summary to terminal
gmail-cleanup --report-text
```

---

## ⏱️ Scheduling (Weekly Automation)

To automate the workflow to run once a week, configure the provided scripts in your OS scheduler:

### Windows (Task Scheduler)
Create a weekly Task Scheduler task pointing to:
- **Program/Script:** `powershell.exe`
- **Arguments:** `-ExecutionPolicy Bypass -File C:\path\to\workspace\scripts\run-weekly.ps1`

### macOS / Linux (cron / launchd)
Add a cron job using `crontab -e` to trigger the weekly script:
```cron
# Run every Sunday at 09:00 CST
0 9 * * 0 /bin/bash /path/to/workspace/scripts/run-weekly.sh >> /path/to/workspace/cleanup.log 2>&1
```

---

## 🔒 Safety First Principles
- **No Primary Inbox Auto-deletion:** The tool only scans Primary Inbox headers to recommend improvements. It will **never** automatically delete or archive anything in your Primary Inbox.
- **Copy-Paste Search Queries:** Suggested cleanup items (e.g. newsletter senders) in the weekly report are presented alongside ready-to-use search strings (e.g., `from:noreply@github.com label:inbox is:unread`). You can copy these directly into Gmail's search bar to bulk-archive or delete safely.
- **Gmail Trash Buffer:** Matching emails are moved to Gmail's native `Trash` (not permanently deleted immediately). They will remain in your trash for 30 days as a recovery safety buffer before Google automatically expunges them.
