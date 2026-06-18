# Data Visualization Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python-generated static HTML dashboard (`dashboard.html`) showing key email metrics, 30-day inbox size trends, top senders breakdown, and weekly cleaning volumes from the SQLite database.

**Architecture:** Create a `src/gmail_cleanup/dashboard.py` module containing SQL query logic to fetch metrics, aggregate weekly/sender statistics, read the latest AI summary report, and populate a premium dark-themed HTML template using `Chart.js` via CDN. Add a `--dashboard` flag to the main CLI.

**Tech Stack:** Python stdlib (sqlite3, json, pathlib), Chart.js (via CDN), Google Fonts (Inter), HTML5/CSS3.

## Global Constraints

- **Single Project:** Maintain the two-pillar structure under `gmail-cleanup`.
- **Static Dashboard:** python-generated, double-click to open (`dashboard.html`), zero local npm/web server required.
- **Security:** Ensure no personal names or emails are hardcoded anywhere.
- **TDD:** Write failing tests, verify failure, implement minimal code to pass, verify pass, commit.

---

### Task 1: Create Dashboard Generator & SQL Logic

**Files:**
- Create: `src/gmail_cleanup/dashboard.py`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: SQLite Database path (`db_path`), account name (`account`), and output file path (`output_path`).
- Produces: `generate_dashboard(account: str, db_path: str, output_path: str) -> None`

- [ ] **Step 1: Write a failing unit test**

Create the test file `tests/test_dashboard.py` to verify that `generate_dashboard` executes successfully and writes an HTML file with critical data matching what is stored in a test database.

```python
import os
import sqlite3
import pytest
from pathlib import Path
from gmail_cleanup.analytics import AnalyticsDB
from gmail_cleanup.dashboard import generate_dashboard

def test_generate_dashboard(tmp_path):
    db_file = tmp_path / "test_analytics.db"
    html_file = tmp_path / "dashboard.html"
    
    # 1. Initialize test DB
    db = AnalyticsDB(str(db_file))
    
    # 2. Populate mock run & stats
    run_id = db.record_run(
        account="dummy",
        apply_mode=True,
        rule_stats=[
            {"rule_name": "promotions", "found_count": 100, "deleted_count": 100},
            {"rule_name": "social", "found_count": 50, "deleted_count": 50}
        ],
        sender_counts=[
            {"sender_name": "GitHub", "sender_email": "noreply@github.com", "category": "social", "count": 50},
            {"sender_name": "PromoCorp", "sender_email": "promo@promo.com", "category": "promotions", "count": 100}
        ],
        primary_stats={
            "total": 500,
            "unread": 20,
            "newsletters": 10,
            "top_senders": [{"email": "noreply@github.com", "name": "GitHub", "count": 50}],
            "top_unread_senders": [],
            "top_newsletters": []
        }
    )
    
    # 3. Populate snapshots
    db.record_snapshot("dummy", {"inbox": 200, "promotions": 150, "social": 50, "trash": 120})
    db.close()
    
    # Verify file does not exist yet
    assert not html_file.exists()
    
    # 4. Generate dashboard (this will fail initially because generate_dashboard does not exist)
    generate_dashboard(account="dummy", db_path=str(db_file), output_path=str(html_file))
    
    # 5. Assertions on generated file
    assert html_file.exists()
    html_content = html_file.read_text(encoding="utf-8")
    assert "dashboard" in html_content.lower()
    assert "noreply@github.com" in html_content
    assert "promo@promo.com" in html_content
    assert "150" in html_content  # promotions count
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dashboard.py`
Expected: `ModuleNotFoundError: No module named 'gmail_cleanup.dashboard'` or similar.

- [ ] **Step 3: Implement minimal dashboard generator**

Create `src/gmail_cleanup/dashboard.py` and implement the database queries, markdown parser for the latest AI report, and HTML builder.

```python
import sqlite3
import json
import re
from pathlib import Path
from datetime import datetime

def _markdown_to_html(md_text: str) -> str:
    """Helper to convert basic markdown formatting (headers, lists, bold) to HTML."""
    if not md_text:
        return "<p>無可用報告資料。</p>"
    
    html = []
    lines = md_text.split("\n")
    in_list = False
    
    for line in lines:
        # Frontmatter block skipping
        if line.strip() == "---":
            continue
        if re.match(r"^(type|created|tags|source):", line):
            continue
            
        # Headers
        if line.startswith("# "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h2>{line[2:]}</h2>")
        elif line.startswith("## "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h3>{line[3:]}</h3>")
        elif line.startswith("### "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h4>{line[4:]}</h4>")
        # Unordered list items
        elif line.startswith("- ") or line.startswith("* "):
            if not in_list:
                html.append("<ul>")
                in_list = True
            content = line[2:]
            # Replace bolding
            content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", content)
            # Replace code tags
            content = re.sub(r"`(.*?)`", r"<code>\1</code>", content)
            html.append(f"<li>{content}</li>")
        # Blank lines
        elif not line.strip():
            if in_list:
                html.append("</ul>")
                in_list = False
        # Paragraphs
        else:
            if in_list:
                html.append("</ul>")
                in_list = False
            content = line.strip()
            content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", content)
            content = re.sub(r"`(.*?)`", r"<code>\1</code>", content)
            html.append(f"<p>{content}</p>")
            
    if in_list:
        html.append("</ul>")
        
    return "\n".join(html)

def generate_dashboard(account: str, db_path: str, output_path: str):
    """Queries SQLite statistics and writes a premium HTML/Chart.js dashboard."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # 1. Fetch KPI Metrics
    # Latest snapshot
    snapshot_row = conn.execute("""
        SELECT inbox_count, promotions_count, social_count, trash_count 
        FROM inbox_snapshots 
        WHERE account = ? 
        ORDER BY timestamp DESC LIMIT 1
    """, (account,)).fetchone()
    
    inbox_count = snapshot_row["inbox_count"] if snapshot_row else 0
    promotions_count = snapshot_row["promotions_count"] if snapshot_row else 0
    social_count = snapshot_row["social_count"] if snapshot_row else 0
    
    # Lifetime cleaned count
    cleaned_row = conn.execute("""
        SELECT SUM(total_deleted) as total 
        FROM cleanup_runs 
        WHERE account = ? AND apply_mode = 1
    """, (account,)).fetchone()
    lifetime_cleaned = cleaned_row["total"] if cleaned_row and cleaned_row["total"] is not None else 0
    
    # Top sender
    top_sender_row = conn.execute("""
        SELECT sender_name, sender_email, SUM(email_count) as total 
        FROM sender_stats 
        JOIN cleanup_runs ON sender_stats.run_id = cleanup_runs.id 
        WHERE cleanup_runs.account = ? 
        GROUP BY sender_email 
        ORDER BY total DESC LIMIT 1
    """, (account,)).fetchone()
    
    if top_sender_row:
        top_sender = f"{top_sender_row['sender_name'] or top_sender_row['sender_email']} ({top_sender_row['total']})"
    else:
        top_sender = "N/A"
        
    # Daily Average
    avg_row = conn.execute("""
        SELECT AVG(total_deleted) as avg_deleted 
        FROM cleanup_runs 
        WHERE account = ? AND apply_mode = 1
    """, (account,)).fetchone()
    daily_avg = int(round(avg_row["avg_deleted"])) if avg_row and avg_row["avg_deleted"] is not None else 0

    # 2. Fetch Trend Chart Data (Last 30 snapshots)
    trend_rows = conn.execute("""
        SELECT timestamp, inbox_count, promotions_count, social_count, trash_count 
        FROM inbox_snapshots 
        WHERE account = ? 
        ORDER BY timestamp ASC LIMIT 30
    """, (account,)).fetchall()
    
    trend_labels = [row["timestamp"][:10] for row in trend_rows]
    trend_inbox = [row["inbox_count"] for row in trend_rows]
    trend_promo = [row["promotions_count"] for row in trend_rows]
    trend_social = [row["social_count"] for row in trend_rows]
    trend_trash = [row["trash_count"] for row in trend_rows]

    # 3. Fetch Top 10 Senders Pie Chart Data
    pie_rows = conn.execute("""
        SELECT sender_email, SUM(email_count) as total 
        FROM sender_stats 
        JOIN cleanup_runs ON sender_stats.run_id = cleanup_runs.id 
        WHERE cleanup_runs.account = ? 
        GROUP BY sender_email 
        ORDER BY total DESC LIMIT 10
    """, (account,)).fetchall()
    
    pie_labels = [row["sender_email"] for row in pie_rows]
    pie_data = [row["total"] for row in pie_rows]

    # 4. Fetch Weekly Bar Chart Data (Last 8 runs)
    bar_rows = conn.execute("""
        SELECT timestamp, total_deleted 
        FROM cleanup_runs 
        WHERE account = ? AND apply_mode = 1 
        ORDER BY timestamp ASC LIMIT 8
    """, (account,)).fetchall()
    
    bar_labels = [row["timestamp"][:10] for row in bar_rows]
    bar_data = [row["total_deleted"] for row in bar_rows]

    conn.close()

    # 5. Read latest AI Report markdown file
    ai_report_html = "<p>無可用本週 AI 分析報告。</p>"
    reports_dir = Path("reports")
    # If a custom Obsidian vault path was configured, check there first
    from gmail_cleanup.config import AppConfig
    config = AppConfig()
    if config.obsidian_vault_path:
        vault_dir = Path(config.obsidian_vault_path) / "00 - Inbox" / "Agent_Output"
        if vault_dir.exists():
            reports_dir = vault_dir
            
    if reports_dir.exists():
        report_files = sorted(reports_dir.glob("Weekly-Cleanup-Report-*.md"), key=os.path.getmtime, reverse=True)
        if report_files:
            try:
                latest_report = report_files[0].read_text(encoding="utf-8")
                ai_report_html = _markdown_to_html(latest_report)
            except Exception as e:
                ai_report_html = f"<p>無法載入最新報告: {e}</p>"

    # 6. Generate HTML from premium template
    html_template = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gmail Auto-Cleanup Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --bg-color: #0f172a;
            --card-bg: rgba(30, 41, 59, 0.7);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-cyan: #22d3ee;
            --accent-emerald: #34d399;
            --accent-purple: #c084fc;
            --accent-rose: #f43f5e;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Outfit', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }}

        body {{
            background-color: var(--bg-color);
            color: var(--text-main);
            padding: 2rem;
            min-height: 100vh;
        }}

        .dashboard-container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        header {{
            margin-bottom: 2.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1.5rem;
        }}

        header h1 {{
            font-size: 2.2rem;
            font-weight: 800;
            background: linear-gradient(135deg, var(--accent-cyan), var(--accent-emerald));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        header .meta-info {{
            text-align: right;
            color: var(--text-muted);
            font-size: 0.9rem;
        }}

        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}

        .kpi-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            backdrop-filter: blur(12px);
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .kpi-card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 10px 20px rgba(0, 0, 0, 0.2);
            border-color: rgba(255, 255, 255, 0.15);
        }}

        .kpi-card .label {{
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 0.5rem;
        }}

        .kpi-card .value {{
            font-size: 2rem;
            font-weight: 800;
        }}

        .card-cyan {{ border-left: 4px solid var(--accent-cyan); }}
        .card-emerald {{ border-left: 4px solid var(--accent-emerald); }}
        .card-purple {{ border-left: 4px solid var(--accent-purple); }}
        .card-rose {{ border-left: 4px solid var(--accent-rose); }}

        .cyan-text {{ color: var(--accent-cyan); }}
        .emerald-text {{ color: var(--accent-emerald); }}
        .purple-text {{ color: var(--accent-purple); }}
        .rose-text {{ color: var(--accent-rose); }}

        .charts-grid {{
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}

        @media (max-width: 1024px) {{
            .charts-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        .chart-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            min-height: 350px;
        }}

        .chart-card h3 {{
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 1.5rem;
            color: var(--text-main);
        }}

        .insights-section {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
        }}

        @media (max-width: 768px) {{
            .insights-section {{
                grid-template-columns: 1fr;
            }}
        }}

        .insights-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 2rem;
        }}

        .insights-card h3 {{
            font-size: 1.3rem;
            font-weight: 600;
            margin-bottom: 1rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 0.5rem;
        }}

        .ai-report {{
            color: #e2e8f0;
            font-size: 0.95rem;
            line-height: 1.6;
        }}

        .ai-report ul {{
            padding-left: 1.25rem;
            margin: 1rem 0;
        }}

        .ai-report li {{
            margin-bottom: 0.5rem;
        }}

        .ai-report h2, .ai-report h3, .ai-report h4 {{
            margin: 1.5rem 0 0.5rem 0;
            color: var(--accent-cyan);
        }}

        .ai-report code {{
            background: rgba(255, 255, 255, 0.1);
            padding: 2px 6px;
            border-radius: 4px;
            font-family: monospace;
        }}
    </style>
</head>
<body>
    <div class="dashboard-container">
        <header>
            <div>
                <h1>Gmail Auto-Cleanup Dashboard</h1>
                <div class="meta-info">帳號：{account}</div>
            </div>
            <div class="meta-info">
                最後更新於：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>
        </header>

        <!-- KPI Grid -->
        <div class="kpi-grid">
            <div class="kpi-card card-cyan">
                <div class="label">Inbox 數量</div>
                <div class="value cyan-text">{inbox_count}</div>
            </div>
            <div class="kpi-card card-emerald">
                <div class="label">累計清理信件</div>
                <div class="value emerald-text">{lifetime_cleaned}</div>
            </div>
            <div class="kpi-card card-purple">
                <div class="label">最大發信來源</div>
                <div class="value purple-text" style="font-size: 1.1rem; margin-top: 0.6rem; word-break: break-all;">{top_sender}</div>
            </div>
            <div class="kpi-card card-rose">
                <div class="label">平均單次清理量</div>
                <div class="value rose-text">{daily_avg}</div>
            </div>
        </div>

        <!-- Charts Grid -->
        <div class="charts-grid">
            <!-- 30-Day Trend Chart -->
            <div class="chart-card">
                <h3>30 天收件箱容量走勢</h3>
                <div style="position: relative; height: 300px;">
                    <canvas id="trendChart"></canvas>
                </div>
            </div>

            <!-- Top Senders Pie Chart -->
            <div class="chart-card">
                <h3>前 10 大垃圾信來源</h3>
                <div style="position: relative; height: 300px; display: flex; justify-content: center;">
                    <canvas id="pieChart"></canvas>
                </div>
            </div>
        </div>

        <!-- Insights Grid -->
        <div class="insights-section">
            <!-- Weekly cleanup bar chart -->
            <div class="chart-card">
                <h3>每週清理信件數量</h3>
                <div style="position: relative; height: 300px;">
                    <canvas id="weeklyBarChart"></canvas>
                </div>
            </div>

            <!-- AI Reports panel -->
            <div class="insights-card">
                <h3>最新 AI 智能整理報告</h3>
                <div class="ai-report">
                    {ai_report_html}
                </div>
            </div>
        </div>
    </div>

    <script>
        // Set Chart.js Defaults for Dark Theme
        Chart.defaults.color = '#94a3b8';
        Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.05)';

        // 1. 30-Day Trend Chart
        const trendCtx = document.getElementById('trendChart').getContext('2d');
        new Chart(trendCtx, {{
            type: 'line',
            data: {{
                labels: {json.dumps(trend_labels)},
                datasets: [
                    {{
                        label: 'Inbox',
                        data: {json.dumps(trend_inbox)},
                        borderColor: '#22d3ee',
                        backgroundColor: 'rgba(34, 211, 238, 0.1)',
                        fill: true,
                        tension: 0.4
                    }},
                    {{
                        label: 'Promotions',
                        data: {json.dumps(trend_promo)},
                        borderColor: '#c084fc',
                        backgroundColor: 'transparent',
                        tension: 0.4
                    }},
                    {{
                        label: 'Social',
                        data: {json.dumps(trend_social)},
                        borderColor: '#f43f5e',
                        backgroundColor: 'transparent',
                        tension: 0.4
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ position: 'top' }}
                }}
            }}
        }});

        // 2. Top Senders Pie Chart
        const pieCtx = document.getElementById('pieChart').getContext('2d');
        new Chart(pieCtx, {{
            type: 'doughnut',
            data: {{
                labels: {json.dumps(pie_labels)},
                datasets: [{{
                    data: {json.dumps(pie_data)},
                    backgroundColor: [
                        '#22d3ee', '#34d399', '#c084fc', '#f43f5e', 
                        '#fbbf24', '#3b82f6', '#f97316', '#ec4899', 
                        '#14b8a6', '#6366f1'
                    ],
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ display: false }}
                }}
            }}
        }});

        // 3. Weekly Volume Bar Chart
        const barCtx = document.getElementById('weeklyBarChart').getContext('2d');
        new Chart(barCtx, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(bar_labels)},
                datasets: [{{
                    label: '清理件數',
                    data: {json.dumps(bar_data)},
                    backgroundColor: 'linear-gradient(to top, #34d399, #22d3ee)',
                    backgroundColor: '#34d399',
                    borderRadius: 6
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ display: false }}
                }}
            }}
        }});
    </script>
</body>
</html>"""

    Path(output_path).write_text(html_template, encoding="utf-8")
    print(f"Dashboard successfully generated at: {Path(output_path).resolve()}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dashboard.py`
Expected: `5/5 passed` or similar.

- [ ] **Step 5: Commit changes**

```bash
git add tests/test_dashboard.py src/gmail_cleanup/dashboard.py
git commit -m "feat: implement dashboard database query and static HTML generation logic"
```

---

### Task 2: CLI Integration & Makefile Action

**Files:**
- Modify: `src/gmail_cleanup/__main__.py`
- Modify: `Makefile`
- Modify: `.gitignore`

**Interfaces:**
- CLI flag `--dashboard` executes `generate_dashboard` with configuration variables.
- Makefile command `make dashboard` runs the python command.

- [ ] **Step 1: Write a failing CLI / Main test**

Modify `tests/test_analytics.py` or write an integration test verifying that calling the CLI entry point with `--dashboard` successfully triggers dashboard file generation.

- [ ] **Step 2: Add `--dashboard` argument to `__main__.py`**

In `src/gmail_cleanup/__main__.py`, add a parser argument:
```python
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Generate the static HTML dashboard based on SQLite stats."
    )
```

And in the main execute logic (around line 90-100):
```python
    if args.dashboard:
        from gmail_cleanup.dashboard import generate_dashboard
        try:
            generate_dashboard(args.account, config.db_path, "dashboard.html")
            print("Successfully created dashboard.html")
        except Exception as e:
            print(f"Error generating dashboard: {e}")
            sys.exit(1)
        sys.exit(0)
```

- [ ] **Step 3: Modify `Makefile`**

Add the `dashboard` and `dashboard-apply` targets to the `Makefile`:
```makefile
dashboard:
	uv run python -m gmail_cleanup --account personal --dashboard
```

Also add `dashboard.html` to `.gitignore` under the `# Local Configurations & DBs` section:
```
dashboard.html
```

- [ ] **Step 4: Run CLI execution to verify it works**

Run: `make dashboard`
Expected: Output of "Dashboard successfully generated at..." and a `dashboard.html` file created in project root directory.

- [ ] **Step 5: Commit changes**

```bash
git add src/gmail_cleanup/__main__.py Makefile .gitignore
git commit -m "feat: integrate CLI dashboard command and makefile targets"
```

---

### Task 3: Portfolio Demo Recording and Embed

**Files:**
- Modify: `README.md`
- Create: Demo MP4 / GIF in media directory (or mock-ups)

**Interfaces:**
- Present a beautiful GIF or screenshot of the generated dashboard in the `README.md`.

- [ ] **Step 1: Run actual cleanup to populate full dashboard**
Run: `make weekly-apply` or `python -m gmail_cleanup --account personal --apply --ai-summary --dashboard` to generate complete data and the output `dashboard.html`.

- [ ] **Step 2: Generate visual screenshots / demo recording**
Capture a beautiful dashboard screen capture (and optionally, CLI output in ascii format or a GIF). Save it to `docs/dashboard_preview.png`.

- [ ] **Step 3: Embed screenshot in `README.md`**
Add the screenshot under the "📐 Architecture & Workflow" section in the README.

```markdown
### 📊 Dashboard Preview
![Dashboard Preview](docs/dashboard_preview.png)
```

- [ ] **Step 4: Commit and finalize v3.5**
```bash
git add README.md docs/dashboard_preview.png
git commit -m "docs: add dashboard preview screenshot to README"
```
