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

def generate_dashboard(account: str, db_path: str, output_path: str) -> None:
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

    # 2. Fetch Trend Chart Data (Last 30 snapshots, chronologically sorted)
    trend_rows = conn.execute("""
        SELECT timestamp, inbox_count, promotions_count, social_count, trash_count 
        FROM (
            SELECT timestamp, inbox_count, promotions_count, social_count, trash_count 
            FROM inbox_snapshots 
            WHERE account = ? 
            ORDER BY timestamp DESC LIMIT 30
        )
        ORDER BY timestamp ASC
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

    # 4. Fetch Weekly Bar Chart Data
    bar_rows = conn.execute("""
        SELECT timestamp, total_deleted 
        FROM (
            SELECT timestamp, total_deleted 
            FROM cleanup_runs 
            WHERE account = ? AND apply_mode = 1 
            ORDER BY timestamp DESC LIMIT 8
        )
        ORDER BY timestamp ASC
    """, (account,)).fetchall()
    
    bar_labels = [row["timestamp"][:10] for row in bar_rows]
    bar_data = [row["total_deleted"] for row in bar_rows]

    # 5. Fetch Recent Email Snippets
    recent_email_rows = conn.execute("""
        SELECT sender_name, sender_email, subject, snippet, date 
        FROM recent_primary_emails 
        WHERE account = ?
        ORDER BY date DESC LIMIT 100
    """, (account,)).fetchall()
    
    recent_emails_html = []
    for row in recent_email_rows:
        sender = row["sender_name"] or row["sender_email"].split("@")[0]
        recent_emails_html.append(f"""
        <div class="email-item">
            <div class="email-meta">
                <span class="email-sender" title="{row['sender_email']}">{sender}</span>
                <span class="email-date">{row['date'][:10]}</span>
            </div>
            <div class="email-subject">{row['subject'] or '(無主旨)'}</div>
            <div class="email-snippet">{row['snippet'] or '(無郵件內文摘要)'}</div>
        </div>
        """)
    recent_emails_html_str = "\n".join(recent_emails_html) if recent_emails_html else "<p class='no-data'>近 7 天主要收件箱沒有掃描到郵件。</p>"

    # 6. Fetch Actionable To-dos and Topics
    ai_todos_list = []
    ai_topics_list = []
    
    latest_ai_row = conn.execute("""
        SELECT suggested_todos_json, topics_catchup_json 
        FROM primary_inbox_stats 
        JOIN cleanup_runs ON primary_inbox_stats.run_id = cleanup_runs.id
        WHERE cleanup_runs.account = ?
        ORDER BY cleanup_runs.timestamp DESC LIMIT 1
    """, (account,)).fetchone()
    
    if latest_ai_row:
        try:
            if latest_ai_row["suggested_todos_json"]:
                ai_todos_list = json.loads(latest_ai_row["suggested_todos_json"])
            if latest_ai_row["topics_catchup_json"]:
                ai_topics_list = json.loads(latest_ai_row["topics_catchup_json"])
        except Exception as parse_err:
            print(f"Warning: Failed to parse stored AI checklist: {parse_err}")

    todos_html = []
    for i, todo in enumerate(ai_todos_list):
        todos_html.append(f"""
        <label class="todo-item">
            <input type="checkbox" id="todo-{i}">
            <span class="todo-text">{todo}</span>
        </label>
        """)
    todos_html_str = "\n".join(todos_html) if todos_html else "<p class='no-data'>本週沒有代辦事項建議。</p>"
    
    topics_html = []
    for topic in ai_topics_list:
        topics_html.append(f"""
        <div class="topic-item">
            <div class="topic-icon">📌</div>
            <div class="topic-text">{topic}</div>
        </div>
        """)
    topics_html_str = "\n".join(topics_html) if topics_html else "<p class='no-data'>本週沒有追蹤摘要建議。</p>"

    conn.close()

    # 7. Read latest AI Report markdown file
    ai_report_html = "<p>無可用本週 AI 分析報告。</p>"
    reports_dir = Path("reports")
    try:
        from gmail_cleanup.config import AppConfig
        config = AppConfig()
        if config.obsidian_vault_path:
            vault_dir = Path(config.obsidian_vault_path) / "00 - Inbox" / "Agent_Output"
            if vault_dir.exists():
                reports_dir = vault_dir
    except Exception as e:
        print(f"Warning: Could not check Obsidian vault path: {e}")
            
    if reports_dir.exists():
        report_files = sorted(reports_dir.glob("Weekly-Cleanup-Report-*.md"), key=lambda p: p.name, reverse=True)
        if report_files:
            try:
                latest_report = report_files[0].read_text(encoding="utf-8")
                ai_report_html = _markdown_to_html(latest_report)
            except Exception as e:
                ai_report_html = f"<p>無法載入最新報告: {e}</p>"

    # 8. Generate HTML from premium template
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
            --card-bg: rgba(30, 41, 59, 0.6);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-cyan: #22d3ee;
            --accent-emerald: #34d399;
            --accent-purple: #c084fc;
            --accent-rose: #f43f5e;
            --sidebar-width: 420px;
        }}

        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; }}
        body {{ background-color: var(--bg-color); color: var(--text-main); padding: 2rem; min-height: 100vh; }}
        .dashboard-container {{ max-width: 1500px; margin: 0 auto; }}
        header {{ margin-bottom: 2rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-color); padding-bottom: 1.5rem; }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1.2rem; margin-bottom: 2rem; }}
        .kpi-card {{ background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 16px; padding: 1.2rem; backdrop-filter: blur(12px); }}
        .kpi-card .label {{ font-size: 0.85rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; margin-bottom: 0.4rem; }}
        .kpi-card .value {{ font-size: 1.8rem; font-weight: 800; }}
        .card-cyan {{ border-left: 4px solid var(--accent-cyan); }}
        .card-emerald {{ border-left: 4px solid var(--accent-emerald); }}
        .card-purple {{ border-left: 4px solid var(--accent-purple); }}
        .card-rose {{ border-left: 4px solid var(--accent-rose); }}
        .cyan-text {{ color: var(--accent-cyan); }}
        .emerald-text {{ color: var(--accent-emerald); }}
        .purple-text {{ color: var(--accent-purple); }}
        .rose-text {{ color: var(--accent-rose); }}
        
        .dashboard-grid {{ display: grid; grid-template-columns: 1fr var(--sidebar-width); gap: 2rem; align-items: start; }}
        @media (max-width: 1100px) {{ .dashboard-grid {{ grid-template-columns: 1fr; }} }}
        .main-panel {{ display: flex; flex-direction: column; gap: 1.5rem; }}
        .panel-card {{ background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 16px; padding: 1.5rem; min-height: 400px; }}
        .panel-tabs {{ display: flex; gap: 0.5rem; margin-bottom: 1.2rem; border-bottom: 1px solid var(--border-color); padding-bottom: 0.5rem; }}
        .panel-tab-btn {{ background: transparent; border: none; color: var(--text-muted); padding: 0.6rem 1.2rem; font-size: 0.95rem; font-weight: 600; cursor: pointer; border-radius: 8px; }}
        .panel-tab-btn.active {{ color: var(--accent-cyan); background: rgba(34, 211, 238, 0.1); }}
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}
        
        .charts-container-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem; }}
        .chart-box {{ background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border-color); border-radius: 12px; padding: 1.2rem; }}
        
        .email-item {{ background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color); border-radius: 10px; padding: 1rem; margin-bottom: 0.75rem; }}
        .email-sender {{ font-weight: 600; color: var(--accent-purple); font-size: 0.85rem; }}
        .ai-panel {{ background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 16px; padding: 1.5rem; min-height: 800px; position: sticky; top: 2rem; }}
        .ai-tabs {{ display: flex; gap: 0.2rem; margin-bottom: 1rem; background: rgba(15, 23, 42, 0.4); border-radius: 10px; padding: 4px; }}
        .ai-tab-btn {{ flex: 1; border: none; color: var(--text-muted); padding: 0.5rem; font-size: 0.85rem; cursor: pointer; border-radius: 8px; }}
        .ai-tab-btn.active {{ color: var(--text-main); background: var(--card-bg); }}
        .ai-tab-content {{ display: none; }}
        .ai-tab-content.active {{ display: block; }}
        .todo-item {{ display: flex; align-items: flex-start; gap: 0.75rem; padding: 0.8rem; border: 1px solid var(--border-color); margin-bottom: 0.5rem; border-radius: 8px; }}
    </style>
</head>
<body>
    <div class="dashboard-container">
        <header>
            <div><h1>Gmail 智能清理儀表板</h1><p>帳號：{account}</p></div>
            <div class="meta-info">更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
        </header>

        <div class="kpi-grid">
            <div class="kpi-card card-cyan"><div class="label">Inbox</div><div class="value cyan-text">{inbox_count}</div></div>
            <div class="kpi-card card-purple"><div class="label">Promotions</div><div class="value purple-text">{promotions_count}</div></div>
            <div class="kpi-card card-rose"><div class="label">Social</div><div class="value rose-text">{social_count}</div></div>
            <div class="kpi-card card-emerald"><div class="label">累計清理</div><div class="value emerald-text">{lifetime_cleaned}</div></div>
        </div>

        <div class="dashboard-grid">
            <div class="main-panel">
                <div class="panel-card">
                    <div class="panel-tabs">
                        <button class="panel-tab-btn active" onclick="switchMainTab('tab-charts')">📊 分析</button>
                        <button class="panel-tab-btn" onclick="switchMainTab('tab-emails')">✉️ 近期郵件</button>
                    </div>
                    <div id="tab-charts" class="tab-content active">
                        <div class="charts-container-grid">
                            <div class="chart-box"><h4>走勢</h4><canvas id="trendChart"></canvas></div>
                            <div class="chart-box"><h4>來源</h4><canvas id="pieChart"></canvas></div>
                        </div>
                        <div class="chart-box"><h4>每週清理量</h4><canvas id="weeklyBarChart"></canvas></div>
                    </div>
                    <div id="tab-emails" class="tab-content">
                        <div class="email-list-container">{recent_emails_html_str}</div>
                    </div>
                </div>
            </div>

            <div class="ai-panel">
                <div class="ai-tabs">
                    <button class="ai-tab-btn active" onclick="switchAiTab('tab-ai-report')">報告</button>
                    <button class="ai-tab-btn" onclick="switchAiTab('tab-ai-todos')">待辦</button>
                    <button class="ai-tab-btn" onclick="switchAiTab('tab-ai-topics')">摘要</button>
                </div>
                <div id="tab-ai-report" class="ai-tab-content active">{ai_report_html}</div>
                <div id="tab-ai-todos" class="ai-tab-content">{todos_html_str}</div>
                <div id="tab-ai-topics" class="ai-tab-content">{topics_html_str}</div>
            </div>
        </div>
    </div>
    <script>
        function switchMainTab(id) {{ 
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.querySelectorAll('.panel-tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(id).classList.add('active');
            event.currentTarget.classList.add('active');
        }}
        function switchAiTab(id) {{
            document.querySelectorAll('.ai-tab-content').forEach(c => c.classList.remove('active'));
            document.querySelectorAll('.ai-tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(id).classList.add('active');
            event.currentTarget.classList.add('active');
        }}
        new Chart(document.getElementById('trendChart'), {{ type: 'line', data: {{ labels: {json.dumps(trend_labels)}, datasets: [{{ data: {json.dumps(trend_inbox)}, borderColor: '#22d3ee' }}] }} }});
        new Chart(document.getElementById('pieChart'), {{ type: 'doughnut', data: {{ labels: {json.dumps(pie_labels)}, datasets: [{{ data: {json.dumps(pie_data)} }}] }} }});
        new Chart(document.getElementById('weeklyBarChart'), {{ type: 'bar', data: {{ labels: {json.dumps(bar_labels)}, datasets: [{{ data: {json.dumps(bar_data)} }}] }} }});
    </script>
</body>
</html>"""

    Path(output_path).write_text(html_template, encoding="utf-8")
    print(f"Dashboard successfully generated at: {Path(output_path).resolve()}")
