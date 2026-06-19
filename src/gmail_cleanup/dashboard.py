import sqlite3
import json
import re
import html
from pathlib import Path
from datetime import datetime

def _markdown_to_html(md_text: str) -> str:
    """Helper to convert basic markdown formatting (headers, lists, bold, tables) to HTML."""
    if not md_text:
        return "<p>無可用報告資料。</p>"
    
    html_out = []
    lines = md_text.split("\n")
    in_list = False
    in_table = False
    
    for line in lines:
        stripped = line.strip()
        
        # Frontmatter block skipping
        if stripped == "---":
            continue
        if re.match(r"^(type|created|tags|source):", stripped):
            continue
            
        # Table parsing
        if stripped.startswith("|") and stripped.endswith("|"):
            if in_list:
                html_out.append("</ul>")
                in_list = False
            
            # Check if it's a separator line like | :--- | :--- |
            if re.match(r"^\|[\s:-|]+$", stripped):
                continue
                
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            
            # Format text formatting inside cells
            formatted_cells = []
            for cell in cells:
                cell = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", cell)
                cell = re.sub(r"`(.*?)`", r"<code>\1</code>", cell)
                formatted_cells.append(cell)
                
            if not in_table:
                html_out.append("<div class='table-responsive'><table class='report-table'>")
                in_table = True
                html_out.append("<thead><tr>")
                for cell in formatted_cells:
                    html_out.append(f"<th>{cell}</th>")
                html_out.append("</tr></thead><tbody>")
            else:
                html_out.append("<tr>")
                for cell in formatted_cells:
                    html_out.append(f"<td>{cell}</td>")
                html_out.append("</tr>")
            continue
        else:
            if in_table:
                html_out.append("</tbody></table></div>")
                in_table = False
                
        # Headers
        if stripped.startswith("# "):
            if in_list:
                html_out.append("</ul>")
                in_list = False
            html_out.append(f"<h2>{stripped[2:]}</h2>")
        elif stripped.startswith("## "):
            if in_list:
                html_out.append("</ul>")
                in_list = False
            html_out.append(f"<h3>{stripped[3:]}</h3>")
        elif stripped.startswith("### "):
            if in_list:
                html_out.append("</ul>")
                in_list = False
            html_out.append(f"<h4>{stripped[4:]}</h4>")
        # Unordered list items
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_out.append("<ul>")
                in_list = True
            content = stripped[2:]
            content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", content)
            content = re.sub(r"`(.*?)`", r"<code>\1</code>", content)
            html_out.append(f"<li>{content}</li>")
        # Blank lines
        elif not stripped:
            if in_list:
                html_out.append("</ul>")
                in_list = False
        # Paragraphs
        else:
            if in_list:
                html_out.append("</ul>")
                in_list = False
            content = stripped
            content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", content)
            content = re.sub(r"`(.*?)`", r"<code>\1</code>", content)
            html_out.append(f"<p>{content}</p>")
            
    if in_list:
        html_out.append("</ul>")
    if in_table:
        html_out.append("</tbody></table></div>")
        
    return "\n".join(html_out)

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
        top_sender_name = top_sender_row['sender_name'] or top_sender_row['sender_email']
        top_sender = f"{html.escape(top_sender_name)} ({top_sender_row['total']})"
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
        sender_name = row["sender_name"] or ""
        sender_email = row["sender_email"]
        sender = html.escape(sender_name or sender_email.split("@")[0])
        sender_email = html.escape(sender_email)
        subject = html.escape(row["subject"] or '(無主旨)')
        snippet = html.escape(row["snippet"] or '(無郵件內文摘要)')
        date = html.escape(row["date"][:10])
        
        # Initials & Avatar color logic
        name_for_avatar = sender_name if sender_name else sender_email.split("@")[0]
        initials = name_for_avatar[0].upper() if name_for_avatar else "✉"
        # Stable color based on name hash
        avatar_colors = [
            "#6366f1", "#06b6d4", "#10b981", "#a855f7", "#f43f5e", 
            "#f97316", "#84cc16", "#3b82f6", "#ec4899", "#14b8a6"
        ]
        hash_val = sum(ord(char) for char in name_for_avatar) if name_for_avatar else 0
        avatar_color = avatar_colors[hash_val % len(avatar_colors)]
        
        recent_emails_html.append(f"""
        <div class="email-item">
            <div class="email-avatar" style="background-color: {avatar_color};">{initials}</div>
            <div class="email-details">
                <div class="email-meta">
                    <span class="email-sender" title="{sender_email}">{sender}</span>
                    <span class="email-date">{date}</span>
                </div>
                <div class="email-subject">{subject}</div>
                <div class="email-snippet">{snippet}</div>
            </div>
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
            <input type="checkbox" class="todo-checkbox" id="todo-{i}" onchange="toggleTodo(this)">
            <span class="todo-text">{html.escape(todo)}</span>
        </label>
        """)
    todos_html_str = "\n".join(todos_html) if todos_html else "<p class='no-data'>本週沒有代辦事項建議。</p>"
    
    topics_html = []
    for topic in ai_topics_list:
        topics_html.append(f"""
        <div class="topic-item">
            <span class="topic-pin">📌</span>
            <span class="topic-text">{html.escape(topic)}</span>
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
    <meta http-equiv="refresh" content="300">
    <title>Gmail Auto-Cleanup Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --bg-color: #0f172a;
            --bg-glass: rgba(15, 23, 42, 0.6);
            --card-bg: rgba(30, 41, 59, 0.45);
            --card-bg-hover: rgba(30, 41, 59, 0.65);
            --border-color: rgba(255, 255, 255, 0.08);
            --border-color-hover: rgba(255, 255, 255, 0.16);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-color: #6366f1;
            --accent-hover: #4f46e5;
            --accent-light: rgba(99, 102, 241, 0.15);
            
            --kpi-cyan: #06b6d4;
            --kpi-purple: #a855f7;
            --kpi-rose: #f43f5e;
            --kpi-emerald: #10b981;
        }}

        * {{ 
            box-sizing: border-box; 
            margin: 0; 
            padding: 0; 
            font-family: 'Outfit', sans-serif; 
        }}
        
        body {{ 
            background-color: var(--bg-color); 
            color: var(--text-main); 
            padding: 2rem; 
            min-height: 100vh;
            transition: background-color 0.3s ease, color 0.3s ease;
            line-height: 1.5;
        }}
        
        /* Custom Scrollbar */
        ::-webkit-scrollbar {{
            width: 8px;
            height: 8px;
        }}
        ::-webkit-scrollbar-track {{
            background: rgba(0, 0, 0, 0.05);
            border-radius: 4px;
        }}
        ::-webkit-scrollbar-thumb {{
            background: rgba(128, 128, 128, 0.3);
            border-radius: 4px;
        }}
        ::-webkit-scrollbar-thumb:hover {{
            background: rgba(128, 128, 128, 0.5);
        }}

        .dashboard-container {{ 
            max-width: 1500px; 
            margin: 0 auto; 
        }}
        
        /* Header Redesign */
        .dashboard-header {{ 
            margin-bottom: 2.5rem; 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            border-bottom: 1px solid var(--border-color); 
            padding-bottom: 1.5rem; 
            flex-wrap: wrap;
            gap: 1.5rem;
        }}
        
        .header-left {{
            display: flex;
            align-items: center;
            gap: 1rem;
        }}
        
        .logo-area {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}
        
        .logo-area h1 {{
            font-size: 1.8rem;
            font-weight: 800;
            background: linear-gradient(135deg, var(--text-main) 30%, var(--accent-color));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        
        .logo-area .account-badge {{
            background: var(--accent-light);
            color: var(--accent-color);
            padding: 0.2rem 0.6rem;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 600;
            margin-left: 0.5rem;
            border: 1px solid rgba(var(--accent-color), 0.2);
            display: inline-block;
        }}

        .header-right {{
            display: flex;
            align-items: center;
            gap: 1.5rem;
            flex-wrap: wrap;
        }}

        /* Theme Selector Styling */
        .theme-selector-container {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            background: var(--card-bg);
            padding: 0.5rem 0.75rem;
            border-radius: 12px;
            border: 1px solid var(--border-color);
        }}

        .theme-label {{
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--text-muted);
        }}

        .theme-buttons {{
            display: flex;
            gap: 0.4rem;
        }}

        .theme-btn {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 0.35rem 0.65rem;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.8rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.3rem;
            transition: all 0.2s ease;
        }}

        .theme-btn:hover {{
            background: rgba(255, 255, 255, 0.1);
            border-color: var(--accent-color);
        }}

        .theme-btn.active {{
            background: var(--accent-color);
            color: #ffffff;
            border-color: var(--accent-color);
            box-shadow: 0 0 10px rgba(var(--accent-color), 0.4);
        }}

        .lang-selector-container {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            background: var(--card-bg);
            padding: 0.5rem 0.75rem;
            border-radius: 12px;
            border: 1px solid var(--border-color);
        }}

        .lang-label {{
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--text-muted);
        }}

        .lang-buttons {{
            display: flex;
            gap: 0.4rem;
        }}

        .lang-btn {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 0.35rem 0.65rem;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.8rem;
            font-weight: 600;
            transition: all 0.2s ease;
        }}

        .lang-btn:hover {{
            background: rgba(255, 255, 255, 0.1);
            border-color: var(--accent-color);
        }}

        .lang-btn.active {{
            background: var(--accent-color);
            color: #ffffff;
            border-color: var(--accent-color);
            box-shadow: 0 0 10px rgba(var(--accent-color), 0.4);
        }}

        .update-time {{
            font-size: 0.85rem;
            color: var(--text-muted);
            display: flex;
            align-items: center;
            gap: 0.4rem;
            background: var(--card-bg);
            padding: 0.5rem 0.75rem;
            border-radius: 12px;
            border: 1px solid var(--border-color);
        }}

        /* KPI Redesign */
        .kpi-grid {{ 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); 
            gap: 1.5rem; 
            margin-bottom: 2.5rem; 
        }}
        
        .kpi-card {{ 
            background: var(--card-bg); 
            border: 1px solid var(--border-color); 
            border-radius: 20px; 
            padding: 1.5rem; 
            display: flex;
            align-items: center;
            gap: 1.25rem;
            backdrop-filter: blur(20px); 
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
        }}
        
        .kpi-card:hover {{ 
            transform: translateY(-5px); 
            border-color: var(--border-color-hover);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
        }}
        
        .kpi-icon-wrapper {{
            width: 54px;
            height: 54px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            flex-shrink: 0;
        }}
        
        .inbox-card .kpi-icon-wrapper {{ background: rgba(6, 182, 212, 0.12); color: var(--kpi-cyan); }}
        .promotions-card .kpi-icon-wrapper {{ background: rgba(168, 85, 247, 0.12); color: var(--kpi-purple); }}
        .social-card .kpi-icon-wrapper {{ background: rgba(244, 63, 94, 0.12); color: var(--kpi-rose); }}
        .cleaned-card .kpi-icon-wrapper {{ background: rgba(16, 185, 129, 0.12); color: var(--kpi-emerald); }}

        .kpi-content {{
            display: flex;
            flex-direction: column;
        }}
        
        .kpi-card .label {{ 
            font-size: 0.85rem; 
            font-weight: 600; 
            color: var(--text-muted); 
            text-transform: uppercase; 
            margin-bottom: 0.25rem; 
        }}
        
        .kpi-card .value {{ 
            font-size: 2.2rem; 
            font-weight: 800; 
            line-height: 1;
        }}
        
        /* Grid Layout */
        .dashboard-grid {{ 
            display: grid; 
            grid-template-columns: 1fr 420px; 
            gap: 2rem; 
            align-items: start; 
        }}
        
        @media (max-width: 1100px) {{ 
            .dashboard-grid {{ 
                grid-template-columns: 1fr; 
            }} 
        }}
        
        .main-panel {{ 
            display: flex; 
            flex-direction: column; 
            gap: 1.5rem; 
        }}
        
        .panel-card {{ 
            background: var(--card-bg); 
            border: 1px solid var(--border-color); 
            border-radius: 20px; 
            padding: 1.50rem; 
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(20px);
        }}
        
        .panel-tabs {{ 
            display: flex; 
            gap: 0.5rem; 
            margin-bottom: 1.5rem; 
            border-bottom: 1px solid var(--border-color); 
            padding-bottom: 0.75rem; 
        }}
        
        .panel-tab-btn {{ 
            background: transparent; 
            border: none; 
            color: var(--text-muted); 
            padding: 0.5rem 1.25rem; 
            font-size: 0.95rem; 
            font-weight: 600; 
            cursor: pointer; 
            border-radius: 8px; 
            transition: all 0.2s ease;
        }}
        
        .panel-tab-btn:hover {{
            color: var(--text-main);
            background: rgba(255, 255, 255, 0.03);
        }}
        
        .panel-tab-btn.active {{ 
            color: var(--accent-color); 
            background: var(--accent-light); 
            border: 1px solid rgba(var(--accent-color), 0.15);
        }}
        
        .tab-content {{ 
            display: none; 
        }}
        
        .tab-content.active {{ 
            display: block; 
        }}
        
        /* Charts styling */
        .charts-container-grid {{ 
            display: grid; 
            grid-template-columns: 1.3fr 1fr; 
            gap: 1.5rem; 
            margin-bottom: 1.5rem; 
        }}
        
        @media (max-width: 768px) {{
            .charts-container-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        
        .chart-box {{ 
            background: rgba(0, 0, 0, 0.15); 
            border: 1px solid var(--border-color); 
            border-radius: 16px; 
            padding: 1.25rem; 
            position: relative;
        }}
        
        .chart-box h4 {{
            font-size: 0.95rem;
            color: var(--text-muted);
            margin-bottom: 1rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .chart-wrapper {{
            height: 250px;
            position: relative;
        }}
        
        .chart-wrapper-large {{
            height: 280px;
            position: relative;
        }}
        
        /* Emails list redesigned */
        .email-list-container {{
            max-height: 700px;
            overflow-y: auto;
            padding-right: 0.5rem;
        }}
        
        .email-item {{ 
            display: flex;
            gap: 1rem;
            align-items: flex-start;
            background: rgba(255, 255, 255, 0.02); 
            border: 1px solid var(--border-color); 
            border-radius: 12px; 
            padding: 1.25rem; 
            margin-bottom: 1rem; 
            transition: all 0.2s ease;
        }}
        
        .email-item:hover {{ 
            background: rgba(255, 255, 255, 0.04);
            border-color: var(--border-color-hover);
            transform: translateX(4px);
        }}
        
        .email-avatar {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            font-size: 1.1rem;
            color: #ffffff;
            flex-shrink: 0;
        }}
        
        .email-details {{
            flex-grow: 1;
            min-width: 0;
        }}
        
        .email-meta {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.25rem;
            flex-wrap: wrap;
            gap: 0.5rem;
        }}
        
        .email-sender {{ 
            font-weight: 600; 
            color: var(--text-main); 
            font-size: 0.95rem; 
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 220px;
        }}
        
        .email-date {{
            font-size: 0.8rem;
            color: var(--text-muted);
        }}
        
        .email-subject {{ 
            font-weight: 600;
            color: var(--accent-color);
            font-size: 0.9rem;
            margin-bottom: 0.4rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        
        .email-snippet {{
            font-size: 0.85rem;
            color: var(--text-muted);
            line-height: 1.4;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}
        
        /* AI Sidebar Panel Redesign */
        .ai-panel {{ 
            background: var(--card-bg); 
            border: 1px solid var(--border-color); 
            border-radius: 20px; 
            padding: 1.50rem; 
            min-height: 700px; 
            position: sticky; 
            top: 2rem; 
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(20px);
        }}
        
        .ai-header {{
            margin-bottom: 1.25rem;
        }}
        
        .ai-header h3 {{
            font-size: 1.1rem;
            font-weight: 800;
            color: var(--text-main);
            letter-spacing: 0.05rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .ai-header .subtitle {{
            font-size: 0.75rem;
            color: var(--text-muted);
            text-transform: uppercase;
            font-weight: 600;
        }}
        
        .ai-tabs {{ 
            display: flex; 
            gap: 0.25rem; 
            margin-bottom: 1.25rem; 
            background: rgba(0, 0, 0, 0.15); 
            border-radius: 12px; 
            padding: 4px; 
            border: 1px solid var(--border-color);
        }}
        
        .ai-tab-btn {{ 
            flex: 1; 
            border: none; 
            color: var(--text-muted); 
            background: transparent;
            padding: 0.6rem 0.25rem; 
            font-size: 0.85rem; 
            font-weight: 600;
            cursor: pointer; 
            border-radius: 8px; 
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.3rem;
        }}
        
        .ai-tab-btn:hover {{
            color: var(--text-main);
        }}
        
        .ai-tab-btn.active {{ 
            color: var(--text-main); 
            background: var(--card-bg); 
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border-color);
        }}
        
        .ai-tab-content {{ 
            display: none; 
            max-height: 600px;
            overflow-y: auto;
            padding-right: 0.25rem;
        }}
        
        .ai-tab-content.active {{ 
            display: block; 
        }}
        
        /* Actionable To-dos */
        .todo-item {{ 
            display: flex; 
            align-items: flex-start; 
            gap: 0.85rem; 
            padding: 1rem; 
            background: rgba(255, 255, 255, 0.015);
            border: 1px solid var(--border-color); 
            margin-bottom: 0.75rem; 
            border-radius: 12px; 
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        
        .todo-item:hover {{
            background: rgba(255, 255, 255, 0.03);
            border-color: var(--border-color-hover);
        }}
        
        .todo-checkbox {{
            width: 18px;
            height: 18px;
            border-radius: 6px;
            border: 2px solid var(--border-color);
            appearance: none;
            outline: none;
            cursor: pointer;
            position: relative;
            transition: all 0.2s ease;
            flex-shrink: 0;
            margin-top: 2px;
        }}
        
        .todo-checkbox:checked {{
            background-color: var(--accent-color);
            border-color: var(--accent-color);
        }}
        
        .todo-checkbox:checked::after {{
            content: "✓";
            position: absolute;
            color: #ffffff;
            font-size: 0.75rem;
            font-weight: bold;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
        }}
        
        .todo-text {{
            font-size: 0.9rem;
            color: var(--text-main);
            transition: all 0.2s ease;
        }}
        
        .todo-item.completed .todo-text {{
            text-decoration: line-through;
            color: var(--text-muted);
            opacity: 0.65;
        }}
        
        .todo-header-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }}
        
        .todo-progress {{
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--accent-color);
            background: var(--accent-light);
            padding: 0.2rem 0.5rem;
            border-radius: 8px;
        }}

        /* Insights topics */
        .topic-item {{ 
            display: flex; 
            align-items: flex-start; 
            gap: 0.75rem; 
            padding: 1rem; 
            background: var(--accent-light); 
            border: 1px solid var(--border-color); 
            border-left: 4px solid var(--accent-color);
            margin-bottom: 0.75rem; 
            border-radius: 12px;
            font-size: 0.9rem;
        }}
        
        .topic-pin {{
            font-size: 1.1rem;
            line-height: 1;
        }}
        
        .topic-text {{
            color: var(--text-main);
            line-height: 1.4;
        }}

        /* Markdown report rendering styling */
        .markdown-content h2 {{
            font-size: 1.3rem;
            font-weight: 800;
            margin-top: 1.5rem;
            margin-bottom: 0.75rem;
            color: var(--accent-color);
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 0.25rem;
        }}
        
        .markdown-content h3 {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-top: 1.25rem;
            margin-bottom: 0.5rem;
            color: var(--text-main);
        }}
        
        .markdown-content h4 {{
            font-size: 0.95rem;
            font-weight: 600;
            margin-top: 1rem;
            margin-bottom: 0.5rem;
            color: var(--text-main);
        }}
        
        .markdown-content p {{
            font-size: 0.9rem;
            line-height: 1.5;
            margin-bottom: 0.75rem;
            color: var(--text-main);
        }}
        
        .markdown-content ul {{
            margin-left: 1.25rem;
            margin-bottom: 1rem;
        }}
        
        .markdown-content li {{
            font-size: 0.9rem;
            line-height: 1.5;
            margin-bottom: 0.35rem;
            color: var(--text-main);
        }}
        
        .markdown-content code {{
            background: rgba(255, 255, 255, 0.06);
            padding: 0.1rem 0.3rem;
            border-radius: 4px;
            font-family: monospace;
            font-size: 0.85em;
            color: var(--accent-color);
            border: 1px solid var(--border-color);
        }}
        
        .markdown-content strong {{
            font-weight: 600;
        }}

        /* Markdown tables parsed */
        .table-responsive {{
            overflow-x: auto;
            margin: 1rem 0;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }}
        
        .report-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.8rem;
            text-align: left;
        }}
        
        .report-table th, .report-table td {{
            padding: 0.6rem 0.8rem;
            border-bottom: 1px solid var(--border-color);
        }}
        
        .report-table th {{
            background: rgba(255, 255, 255, 0.03);
            font-weight: 600;
            color: var(--accent-color);
        }}
        
        .report-table tr:last-child td {{
            border-bottom: none;
        }}

        .no-data {{
            text-align: center;
            color: var(--text-muted);
            padding: 2rem;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
    <div class="dashboard-container">
        <header class="dashboard-header">
            <div class="header-left">
                <div class="logo-area">
                    <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: var(--accent-color);">
                        <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
                        <polyline points="22,6 12,13 2,6"></polyline>
                    </svg>
                    <div>
                        <h1 data-i18n="title">Gmail 智能清理儀表板</h1>
                        <p class="subtitle"><span data-i18n="account">帳號：</span><span class="account-badge">{account}</span></p>
                    </div>
                </div>
            </div>
            
            <div class="header-right">
                <div class="lang-selector-container">
                    <span class="lang-label" data-i18n="langLabel">🌐 語言:</span>
                    <div class="lang-buttons" role="radiogroup" aria-label="Language Selection">
                        <button class="lang-btn" data-lang="zh" onclick="changeLanguage('zh')" aria-label="繁體中文">
                            繁體中文
                        </button>
                        <button class="lang-btn" data-lang="en" onclick="changeLanguage('en')" aria-label="English">
                            English
                        </button>
                    </div>
                </div>

                <div class="theme-selector-container">
                    <span class="theme-label" data-i18n="themeLabel">🎨 主題:</span>
                    <div class="theme-buttons" role="radiogroup" aria-label="Theme Selection">
                        <button class="theme-btn" data-theme="slate" onclick="changeTheme('slate')" aria-label="Sleek Slate Theme">
                            <span>🌌</span><span>Slate</span>
                        </button>
                        <button class="theme-btn" data-theme="nord" onclick="changeTheme('nord')" aria-label="Nord Snow Theme">
                            <span>❄️</span><span>Nord</span>
                        </button>
                        <button class="theme-btn" data-theme="cyberpunk" onclick="changeTheme('cyberpunk')" aria-label="Neon Cyber Theme">
                            <span>⚡</span><span>Cyber</span>
                        </button>
                        <button class="theme-btn" data-theme="forest" onclick="changeTheme('forest')" aria-label="Moss Forest Theme">
                            <span>🌲</span><span>Forest</span>
                        </button>
                        <button class="theme-btn" data-theme="sunset" onclick="changeTheme('sunset')" aria-label="Sunset Ember Theme">
                            <span>🌇</span><span>Sunset</span>
                        </button>
                    </div>
                </div>
                
                <div class="update-time">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="12" cy="12" r="10"></circle>
                        <polyline points="12,6 12,12 16,14"></polyline>
                    </svg>
                    <span data-i18n="updated">更新: </span> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </div>
            </div>
        </header>

        <div class="kpi-grid">
            <div class="kpi-card inbox-card">
                <div class="kpi-icon-wrapper">
                    <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="22 12 16 12 14 15 10 15 8 12 2 12"></polyline>
                        <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"></path>
                    </svg>
                </div>
                <div class="kpi-content">
                    <div class="label" data-i18n="inbox">Inbox 郵件量</div>
                    <div class="value">{inbox_count}</div>
                </div>
            </div>
            <div class="kpi-card promotions-card">
                <div class="kpi-icon-wrapper">
                    <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path>
                        <line x1="7" y1="7" x2="7.01" y2="7"></line>
                    </svg>
                </div>
                <div class="kpi-content">
                    <div class="label" data-i18n="promotions">Promotions 促銷</div>
                    <div class="value">{promotions_count}</div>
                </div>
            </div>
            <div class="kpi-card social-card">
                <div class="kpi-icon-wrapper">
                    <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                        <circle cx="9" cy="7" r="4"></circle>
                        <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
                        <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
                    </svg>
                </div>
                <div class="kpi-content">
                    <div class="label" data-i18n="social">Social 社群</div>
                    <div class="value">{social_count}</div>
                </div>
            </div>
            <div class="kpi-card cleaned-card">
                <div class="kpi-icon-wrapper">
                    <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        <line x1="10" y1="11" x2="10" y2="17"></line>
                        <line x1="14" y1="11" x2="14" y2="17"></line>
                    </svg>
                </div>
                <div class="kpi-content">
                    <div class="label" data-i18n="cleaned">累計自動清理</div>
                    <div class="value">{lifetime_cleaned}</div>
                </div>
            </div>
        </div>

        <div class="dashboard-grid">
            <div class="main-panel">
                <div class="panel-card">
                    <div class="panel-tabs">
                        <button class="panel-tab-btn active" onclick="switchMainTab('tab-charts')" data-i18n="tabCharts">📊 分析與圖表</button>
                        <button class="panel-tab-btn" onclick="switchMainTab('tab-emails')" data-i18n="tabEmails">✉️ 近期收件箱郵件</button>
                    </div>
                    
                    <div id="tab-charts" class="tab-content active">
                        <div class="charts-container-grid">
                            <div class="chart-box">
                                <h4 data-i18n="trendTitle">📈 歷史走勢</h4>
                                <div class="chart-wrapper">
                                    <canvas id="trendChart"></canvas>
                                </div>
                            </div>
                            <div class="chart-box">
                                <h4 data-i18n="pieTitle">🍩 主要發件來源 (Top 10)</h4>
                                <div class="chart-wrapper">
                                    <canvas id="pieChart"></canvas>
                                </div>
                            </div>
                        </div>
                        <div class="chart-box">
                            <h4 data-i18n="barTitle">📊 每週清理量</h4>
                            <div class="chart-wrapper-large">
                                <canvas id="weeklyBarChart"></canvas>
                            </div>
                        </div>
                    </div>
                    
                    <div id="tab-emails" class="tab-content">
                        <div class="email-list-container">{recent_emails_html_str}</div>
                    </div>
                </div>
            </div>

            <div class="ai-panel">
                <div class="ai-header">
                    <span class="ai-subtitle">Gmail Cleanup AI</span>
                    <h3 data-i18n="aiTitle">🧠 AI 智能助理分析</h3>
                </div>
                
                <div class="ai-tabs">
                    <button class="ai-tab-btn active" onclick="switchAiTab('tab-ai-report')" data-i18n="aiTabReport">📋 報告</button>
                    <button class="ai-tab-btn" onclick="switchAiTab('tab-ai-todos')" data-i18n="aiTabTodos">☑️ 待辦</button>
                    <button class="ai-tab-btn" onclick="switchAiTab('tab-ai-topics')" data-i18n="aiTabTopics">📌 摘要</button>
                </div>
                
                <div id="tab-ai-report" class="ai-tab-content markdown-content active">{ai_report_html}</div>
                
                <div id="tab-ai-todos" class="ai-tab-content">
                    <div class="todo-header-row">
                        <h4 data-i18n="todoTitle">建議待辦清單</h4>
                        <span class="todo-progress" id="todo-progress-label">(0 / 0)</span>
                    </div>
                    {todos_html_str}
                </div>
                
                <div id="tab-ai-topics" class="ai-tab-content">
                    <h4 style="margin-bottom: 1rem;" data-i18n="topicTitle">本週核心追蹤摘要</h4>
                    {topics_html_str}
                </div>
            </div>
        </div>
    </div>

    <script>
        // Data injected from Python
        const trendLabelsJSON = '{json.dumps(trend_labels)}';
        const trendInboxJSON = '{json.dumps(trend_inbox)}';
        const pieLabelsJSON = '{json.dumps(pie_labels)}';
        const pieDataJSON = '{json.dumps(pie_data)}';
        const barLabelsJSON = '{json.dumps(bar_labels)}';
        const barDataJSON = '{json.dumps(bar_data)}';

        // Themes configurations
        const themes = {{
            slate: {{
                name: "Sleek Slate",
                colors: {{
                    bg: "#0f172a",
                    bgGlass: "rgba(15, 23, 42, 0.6)",
                    cardBg: "rgba(30, 41, 59, 0.45)",
                    cardBgHover: "rgba(30, 41, 59, 0.65)",
                    border: "rgba(255, 255, 255, 0.08)",
                    borderHover: "rgba(255, 255, 255, 0.16)",
                    textMain: "#f8fafc",
                    textMuted: "#94a3b8",
                    accent: "#6366f1",
                    accentHover: "#4f46e5",
                    accentLight: "rgba(99, 102, 241, 0.15)",
                    chartColors: ["#6366f1", "#38bdf8", "#34d399", "#fb7185", "#a78bfa", "#fb923c", "#f43f5e", "#2dd4bf", "#e2e8f0"],
                    gridColor: "rgba(255, 255, 255, 0.04)",
                    tickColor: "#64748b"
                }}
            }},
            nord: {{
                name: "Nord Snow",
                colors: {{
                    bg: "#eceff4",
                    bgGlass: "rgba(236, 239, 244, 0.6)",
                    cardBg: "rgba(255, 255, 255, 0.8)",
                    cardBgHover: "rgba(255, 255, 255, 0.95)",
                    border: "rgba(0, 0, 0, 0.06)",
                    borderHover: "rgba(0, 0, 0, 0.12)",
                    textMain: "#2e3440",
                    textMuted: "#4c566a",
                    accent: "#5e81ac",
                    accentHover: "#81a1c1",
                    accentLight: "rgba(94, 129, 172, 0.15)",
                    chartColors: ["#5e81ac", "#81a1c1", "#88c0d0", "#a3be8c", "#ebcb8b", "#bf616a", "#b48ead", "#4c566a"],
                    gridColor: "rgba(0, 0, 0, 0.05)",
                    tickColor: "#4c566a"
                }}
            }},
            cyberpunk: {{
                name: "Neon Cyber",
                colors: {{
                    bg: "#030008",
                    bgGlass: "rgba(3, 0, 8, 0.6)",
                    cardBg: "rgba(26, 0, 43, 0.4)",
                    cardBgHover: "rgba(26, 0, 43, 0.6)",
                    border: "rgba(255, 0, 255, 0.25)",
                    borderHover: "rgba(0, 255, 255, 0.5)",
                    textMain: "#00ffff",
                    textMuted: "#ff00ff",
                    accent: "#ff00ff",
                    accentHover: "#00ffff",
                    accentLight: "rgba(255, 0, 255, 0.15)",
                    chartColors: ["#ff00ff", "#00ffff", "#ffff00", "#ff0055", "#00ff66", "#7000ff", "#ff5500", "#00aaff"],
                    gridColor: "rgba(255, 0, 255, 0.1)",
                    tickColor: "#ff00ff"
                }}
            }},
            forest: {{
                name: "Moss Forest",
                colors: {{
                    bg: "#111813",
                    bgGlass: "rgba(17, 24, 19, 0.6)",
                    cardBg: "rgba(28, 38, 31, 0.5)",
                    cardBgHover: "rgba(28, 38, 31, 0.7)",
                    border: "rgba(255, 255, 255, 0.06)",
                    borderHover: "rgba(132, 204, 22, 0.25)",
                    textMain: "#f0ebe1",
                    textMuted: "#a0af9b",
                    accent: "#84cc16",
                    accentHover: "#a3e635",
                    accentLight: "rgba(132, 204, 22, 0.15)",
                    chartColors: ["#84cc16", "#10b981", "#eab308", "#f97316", "#a0af9b", "#065f46", "#b45309"],
                    gridColor: "rgba(255, 255, 255, 0.03)",
                    tickColor: "#7c8e74"
                }}
            }},
            sunset: {{
                name: "Sunset Ember",
                colors: {{
                    bg: "#1a0f0f",
                    bgGlass: "rgba(26, 15, 15, 0.6)",
                    cardBg: "rgba(45, 25, 25, 0.5)",
                    cardBgHover: "rgba(45, 25, 25, 0.7)",
                    border: "rgba(255, 255, 255, 0.05)",
                    borderHover: "rgba(249, 115, 22, 0.25)",
                    textMain: "#fff5f5",
                    textMuted: "#e0a3a3",
                    accent: "#f97316",
                    accentHover: "#ea580c",
                    accentLight: "rgba(249, 115, 22, 0.15)",
                    chartColors: ["#f97316", "#ef4444", "#eab308", "#ec4899", "#f43f5e", "#c084fc"],
                    gridColor: "rgba(255, 255, 255, 0.03)",
                    tickColor: "#b27a7a"
                }}
            }}
        }};

        const locales = {{
            zh: {{
                title: "Gmail 智能清理儀表板",
                account: "帳號：",
                updated: "更新: ",
                inbox: "Inbox 郵件量",
                promotions: "Promotions 促銷",
                social: "Social 社群",
                cleaned: "累計自動清理",
                tabCharts: "📊 分析與圖表",
                tabEmails: "✉️ 近期收件箱郵件",
                trendTitle: "📈 歷史走勢",
                pieTitle: "🍩 主要發件來源 (Top 10)",
                barTitle: "📊 每週清理量",
                aiTitle: "🧠 AI 智能助理分析",
                aiTabReport: "📋 報告",
                aiTabTodos: "☑️ 待辦",
                aiTabTopics: "📌 摘要",
                todoTitle: "建議待辦清單",
                topicTitle: "本週核心追蹤摘要",
                themeLabel: "🎨 主題:",
                langLabel: "🌐 語言:",
                trendDataset: "Inbox 郵件數",
                barDataset: "已移入垃圾桶數"
            }},
            en: {{
                title: "Gmail Auto-Cleanup Dashboard",
                account: "Account: ",
                updated: "Updated: ",
                inbox: "Inbox Emails",
                promotions: "Promotions",
                social: "Social",
                cleaned: "Lifetime Cleaned",
                tabCharts: "📊 Analytics & Trends",
                tabEmails: "✉️ Recent Inbox Emails",
                trendTitle: "📈 Historical Trends",
                pieTitle: "🍩 Top Senders (Top 10)",
                barTitle: "📊 Weekly Cleaned Amount",
                aiTitle: "🧠 AI Cleanup Assistant",
                aiTabReport: "📋 Report",
                aiTabTodos: "☑️ To-dos",
                aiTabTopics: "📌 Topics",
                todoTitle: "Suggested To-dos",
                topicTitle: "Weekly Core Insights",
                themeLabel: "🎨 Theme:",
                langLabel: "🌐 Language:",
                trendDataset: "Inbox Count",
                barDataset: "Moved to Trash"
            }}
        }};

        function changeLanguage(langKey) {{
            if (!locales[langKey]) return;

            document.querySelectorAll('[data-i18n]').forEach(el => {{
                const key = el.getAttribute('data-i18n');
                if (locales[langKey][key]) {{
                    el.innerText = locales[langKey][key];
                }}
            }});

            document.querySelectorAll('.lang-btn').forEach(btn => {{
                if (btn.getAttribute('data-lang') === langKey) {{
                    btn.classList.add('active');
                }} else {{
                    btn.classList.remove('active');
                }}
            }});

            updateChartLabels(langKey);
            localStorage.setItem('gmail-cleanup-lang', langKey);
        }}

        function updateChartLabels(langKey) {{
            const texts = locales[langKey];
            if (trendChart) {{
                trendChart.data.datasets[0].label = texts.trendDataset;
                trendChart.update();
            }}
            if (weeklyBarChart) {{
                weeklyBarChart.data.datasets[0].label = texts.barDataset;
                weeklyBarChart.update();
            }}
        }}

        let trendChart, pieChart, weeklyBarChart;

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

        function toggleTodo(checkbox) {{
            const parent = checkbox.closest('.todo-item');
            if (checkbox.checked) {{
                parent.classList.add('completed');
            }} else {{
                parent.classList.remove('completed');
            }}
            updateTodoProgress();
        }}

        function updateTodoProgress() {{
            const total = document.querySelectorAll('.todo-checkbox').length;
            const completed = document.querySelectorAll('.todo-checkbox:checked').length;
            const label = document.getElementById('todo-progress-label');
            if (label) {{
                label.innerText = '(' + completed + ' / ' + total + ')';
            }}
        }}

        function createGradient(ctx, color) {{
            const gradient = ctx.createLinearGradient(0, 0, 0, 250);
            gradient.addColorStop(0, color + '50');
            gradient.addColorStop(1, color + '00');
            return gradient;
        }}

        function getTooltipOptions(colors) {{
            return {{
                backgroundColor: colors.tooltipBg || 'rgba(15, 23, 42, 0.95)',
                titleColor: colors.textMain,
                bodyColor: colors.textMain,
                borderColor: colors.border,
                borderWidth: 1,
                titleFont: {{ family: 'Outfit', weight: 'bold' }},
                bodyFont: {{ family: 'Outfit' }},
                padding: 10,
                cornerRadius: 8
            }};
        }}

        function initCharts(colors) {{
            Chart.defaults.font.family = 'Outfit';
            
            const ctxTrend = document.getElementById('trendChart').getContext('2d');
            trendChart = new Chart(ctxTrend, {{
                type: 'line',
                data: {{
                    labels: JSON.parse(trendLabelsJSON),
                    datasets: [{{
                        label: 'Inbox 郵件數',
                        data: JSON.parse(trendInboxJSON),
                        borderColor: colors.accent,
                        backgroundColor: createGradient(ctxTrend, colors.accent),
                        fill: true,
                        tension: 0.4,
                        borderWidth: 3,
                        pointBackgroundColor: colors.accent,
                        pointBorderColor: '#ffffff',
                        pointBorderWidth: 2,
                        pointRadius: 4,
                        pointHoverRadius: 6
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: getTooltipOptions(colors)
                    }},
                    scales: {{
                        x: {{
                            grid: {{ display: false }},
                            ticks: {{ color: colors.tickColor, font: {{ family: 'Outfit', size: 10 }} }}
                        }},
                        y: {{
                            grid: {{ color: colors.gridColor }},
                            ticks: {{ color: colors.tickColor, font: {{ family: 'Outfit', size: 10 }} }}
                        }}
                    }}
                }}
            }});

            const ctxPie = document.getElementById('pieChart').getContext('2d');
            pieChart = new Chart(ctxPie, {{
                type: 'doughnut',
                data: {{
                    labels: JSON.parse(pieLabelsJSON),
                    datasets: [{{
                        data: JSON.parse(pieDataJSON),
                        backgroundColor: colors.chartColors,
                        borderWidth: 0
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '70%',
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{ color: colors.textMain, font: {{ family: 'Outfit', size: 10 }}, boxWidth: 10, padding: 12 }}
                        }},
                        tooltip: getTooltipOptions(colors)
                    }}
                }}
            }});

            const ctxBar = document.getElementById('weeklyBarChart').getContext('2d');
            weeklyBarChart = new Chart(ctxBar, {{
                type: 'bar',
                data: {{
                    labels: JSON.parse(barLabelsJSON),
                    datasets: [{{
                        label: '已移入垃圾桶數',
                        data: JSON.parse(barDataJSON),
                        backgroundColor: colors.accent,
                        borderRadius: 6,
                        maxBarThickness: 32
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: getTooltipOptions(colors)
                    }},
                    scales: {{
                        x: {{
                            grid: {{ display: false }},
                            ticks: {{ color: colors.tickColor, font: {{ family: 'Outfit', size: 10 }} }}
                        }},
                        y: {{
                            grid: {{ color: colors.gridColor }},
                            ticks: {{ color: colors.tickColor, font: {{ family: 'Outfit', size: 10 }} }}
                        }}
                    }}
                }}
            }});
        }}

        function updateCharts(colors) {{
            if (trendChart) {{
                trendChart.data.datasets[0].borderColor = colors.accent;
                const ctxTrend = document.getElementById('trendChart').getContext('2d');
                trendChart.data.datasets[0].backgroundColor = createGradient(ctxTrend, colors.accent);
                trendChart.data.datasets[0].pointBackgroundColor = colors.accent;
                
                trendChart.options.scales.x.ticks.color = colors.tickColor;
                trendChart.options.scales.y.grid.color = colors.gridColor;
                trendChart.options.scales.y.ticks.color = colors.tickColor;
                trendChart.options.plugins.tooltip = getTooltipOptions(colors);
                trendChart.update();
            }}
            
            if (pieChart) {{
                pieChart.data.datasets[0].backgroundColor = colors.chartColors;
                pieChart.options.plugins.legend.labels.color = colors.textMain;
                pieChart.options.plugins.tooltip = getTooltipOptions(colors);
                pieChart.update();
            }}
            
            if (weeklyBarChart) {{
                weeklyBarChart.data.datasets[0].backgroundColor = colors.accent;
                weeklyBarChart.options.scales.x.ticks.color = colors.tickColor;
                weeklyBarChart.options.scales.y.grid.color = colors.gridColor;
                weeklyBarChart.options.scales.y.ticks.color = colors.tickColor;
                weeklyBarChart.options.plugins.tooltip = getTooltipOptions(colors);
                weeklyBarChart.update();
            }}
        }}

        function changeTheme(themeKey) {{
            if (!themes[themeKey]) return;
            
            const colors = themes[themeKey].colors;
            const root = document.documentElement;
            
            // Set CSS variables
            root.style.setProperty('--bg-color', colors.bg);
            root.style.setProperty('--bg-glass', colors.bgGlass);
            root.style.setProperty('--card-bg', colors.cardBg);
            root.style.setProperty('--card-bg-hover', colors.cardBgHover);
            root.style.setProperty('--border-color', colors.border);
            root.style.setProperty('--border-color-hover', colors.borderHover);
            root.style.setProperty('--text-main', colors.textMain);
            root.style.setProperty('--text-muted', colors.textMuted);
            root.style.setProperty('--accent-color', colors.accent);
            root.style.setProperty('--accent-hover', colors.accentHover);
            root.style.setProperty('--accent-light', colors.accentLight);
            
            // Update active theme btn state
            document.querySelectorAll('.theme-btn').forEach(btn => {{
                if (btn.getAttribute('data-theme') === themeKey) {{
                    btn.classList.add('active');
                }} else {{
                    btn.classList.remove('active');
                }}
            }});
            
            // Update Charts
            updateCharts(colors);
            
            // Save to localStorage
            localStorage.setItem('gmail-cleanup-theme', themeKey);
        }}

        window.addEventListener('DOMContentLoaded', () => {{
            const savedTheme = localStorage.getItem('gmail-cleanup-theme') || 'slate';
            changeTheme(savedTheme);
            
            const savedLang = localStorage.getItem('gmail-cleanup-lang') || 'zh';
            changeLanguage(savedLang);
            
            const colors = themes[savedTheme].colors;
            initCharts(colors);
            
            updateChartLabels(savedLang);
            updateTodoProgress();
        }});
    </script>
</body>
</html>"""

    Path(output_path).write_text(html_template, encoding="utf-8")
    print(f"Dashboard successfully generated at: {Path(output_path).resolve()}")
