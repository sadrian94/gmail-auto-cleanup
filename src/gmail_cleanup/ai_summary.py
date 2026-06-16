import os
from pathlib import Path
from datetime import datetime
from gmail_cleanup.analytics import AnalyticsDB

def generate_weekly_report(account: str, db_path: str, vault_path: str) -> str:
    """Generates the weekly cleanup and Primary Inbox analysis report in Markdown."""
    db = AnalyticsDB(db_path)
    data = db.get_weekly_data(account)

    if not data["runs"]:
        return f"No cleanup runs found in the past 7 days to generate a report."

    from gmail_cleanup.config import AppConfig
    config = AppConfig()
    email_address = config.accounts.get(account, "")

    # Parse data for report
    runs = data["runs"]
    top_senders = data["top_senders"]
    snapshots = data["snapshots"]
    primary = data["primary_stats"]

    # Calculate basic metrics
    total_cleaned = sum(r["total_deleted"] for r in runs)
    latest_run = runs[0]

    # Calculate trends
    trend_section = ""
    if len(snapshots) >= 2:
        first = snapshots[0]
        last = snapshots[-1]
        diff_inbox = last["inbox_count"] - first["inbox_count"]
        pct_inbox = (diff_inbox / first["inbox_count"] * 100) if first["inbox_count"] > 0 else 0
        trend_dir = "📈 增加" if diff_inbox >= 0 else "📉 減少"
        
        trend_section = f"""###  WoW 收件箱趨勢 (過去 14 天)
- **總收件箱數量 (Inbox)：** {first['inbox_count']} → {last['inbox_count']} ({trend_dir} {abs(pct_inbox):.1f}%)
- **推廣郵件 (Promotions)：** {first['promotions_count']} → {last['promotions_count']}
- **社群郵件 (Social)：** {first['social_count']} → {last['social_count']}
- **垃圾桶容量 (Trash)：** {first['trash_count']} → {last['trash_count']}"""

    # Unsubscribe Tips & Anomalies (Programmatic Analysis)
    unsubscribe_tips = []
    anomalies = []
    
    # 1. High frequency senders in Promotions/Social (>= 15 emails)
    for s in top_senders:
        if s["total_count"] >= 15:
            unsubscribe_tips.append(s)
            
        # 2. Anomaly: Sender takes up >30% of a category's scanned volume
        # (Heuristic anomaly detection)
        if s["total_count"] >= 25:
            anomalies.append(s)

    # Compile unsubscribe tips markdown
    unsubscribe_section = ""
    if unsubscribe_tips:
        unsubscribe_section = "### 🚫 建議退訂或建立過濾器的發信者 (每週發信 >= 15 封)\n"
        for idx, u in enumerate(unsubscribe_tips, 1):
            query = f'from:{u["sender_email"]} category:{u["category"]}'
            unsubscribe_section += f"""{idx}. **{u['sender_name'] or u['sender_email']}** ({u['sender_email']})
   - 類別: `{u['category']}` | 數量: **{u['total_count']}** 封
   - 🔍 Gmail 快速搜尋指令: `{query}`
"""
    else:
        unsubscribe_section = "### 🚫 建議退訂或建立過濾器\n- 本週暫無發信頻率過高 (>=15 封) 的 Promotions/Social 寄件者。"

    # Compile anomalies markdown
    anomalies_section = ""
    if anomalies:
        anomalies_section = "### ⚠️ 異常發信活動偵測 (單週大量郵件)\n"
        for a in anomalies:
            anomalies_section += f"- **{a['sender_name'] or a['sender_email']}** ({a['sender_email']}) 在 `{a['category']}` 類別內發送了 **{a['total_count']}** 封郵件，請留意是否有訂閱異常或通知洗版。\n"
    else:
        anomalies_section = "### ⚠️ 異常發信活動偵測\n- 本週未偵測到異常洗版發件者。"

    # Primary Inbox Clutter Analysis
    primary_section = ""
    primary_action_section = ""
    if primary:
        total = primary["total_emails"]
        unread = primary["unread_emails"]
        newsletters = primary["newsletters_count"]
        unread_pct = (unread / total * 100) if total > 0 else 0
        news_pct = (newsletters / total * 100) if total > 0 else 0

        # Deserialize JSON fields safely
        import json
        top_senders = json.loads(primary.get("top_senders_json") or "[]")
        top_unread = json.loads(primary.get("top_unread_senders_json") or "[]")
        top_news = json.loads(primary.get("top_newsletters_json") or "[]")

        # Build list of top senders in Primary
        top_primary_md = ""
        for s in top_senders:
            top_primary_md += f"  - `{s['count']:>3} 封` | **{s['name'] or s['email']}** ({s['email']})\n"

        primary_section = f"""### 📬 主要收件箱 (Primary Inbox) 近 30 天快照
- **掃描郵件總量：** **{total}** 封
- **未讀郵件數量：** **{unread}** 封 ({unread_pct:.1f}%)
- **訂閱電子報佔比：** **{newsletters}** 封 ({news_pct:.1f}%)
- **前 10 大發信寄件者：**
{top_primary_md}"""

        # Generate actionable advice for Primary Inbox clutter
        primary_action_section = "### 💡 主要收件箱 (Primary) 整理建議與 Gmail 搜尋指令\n"
        has_advice = False
        
        # Unread senders analysis
        if top_unread:
            has_advice = True
            primary_action_section += "#### 🔹 長期未讀通知（建議批次歸檔/已讀）\n"
            primary_action_section += "以下寄件者在你的主要收件箱中堆積了許多未讀信件，你可以複製後方的搜尋指令，手動在 Gmail 中選取並一鍵「已讀」或「歸檔」：\n\n"
            for u in top_unread[:5]:
                q = f'from:{u["email"]} label:inbox is:unread'
                primary_action_section += f"- **{u['name'] or u['email']}** ({u['count']} 封未讀) \n  - 🔍 搜尋指令: `{q}`\n"
            primary_action_section += "\n"

        # Newsletters in Primary Inbox
        if top_news:
            has_advice = True
            primary_action_section += "#### 🔹 混在主要收件箱的電子報（建議手動退訂或移至專門標籤）\n"
            primary_action_section += "以下寄件者被偵測為訂閱郵件但寄到了你的 Primary Inbox，如果你不想在主收件箱看到郵件，可以考慮手動退訂或建立過濾器：\n\n"
            for n in top_news[:5]:
                q = f'from:{n["email"]} label:inbox'
                primary_action_section += f"- **{n['name'] or n['email']}** ({n['count']} 封訂閱信) \n  - 🔍 搜尋指令: `{q}`\n"
            primary_action_section += "\n"

        if not has_advice:
            primary_action_section += "- 你的主要收件箱十分乾淨，本週無特別整理建議！\n"
    else:
        primary_section = "### 📬 主要收件箱 (Primary Inbox)\n- 本週無 Primary 收件箱深層掃描紀錄（需執行 `--analytics-deep`）。"
        primary_action_section = ""

    # Build weekly runs history table
    runs_history_rows = ""
    for r in runs:
        mode = "實際清理" if r["apply_mode"] == 1 else "模擬運行"
        runs_history_rows += f"| {r['timestamp']} | {mode} | {r['total_found']} | {r['total_deleted']} |\n"

    # Call Gemini API if GEMINI_API_KEY is present
    gemini_insights = ""
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        try:
            from google import genai
            print("GEMINI_API_KEY detected. Invoking Gemini API for advanced insights...")
            client = genai.Client(api_key=api_key)
            
            # Formulate prompt with raw data
            raw_data = {
                "account": account,
                "total_cleaned_this_week": total_cleaned,
                "snapshots": snapshots[-5:] if snapshots else [],
                "top_senders": top_senders[:10] if top_senders else [],
                "primary_stats": {
                    "total": primary["total"] if primary else 0,
                    "unread": primary["unread"] if primary else 0,
                    "newsletters": primary["newsletters"] if primary else 0,
                    "top_senders": primary["top_senders"][:5] if primary else []
                } if primary else None
            }
            
            prompt = f"""You are a professional email productivity analyst. Analyze the following email statistics and generate a concise list of "Advanced AI Insights" in Traditional Chinese (繁體中文).
Identify patterns, hidden anomalies (e.g. notifications flood, subscription drift), and give actionable advice on improving email workflow. Keep it short and high-impact.

Raw Data:
{json.dumps(raw_data, indent=2)}

Format your response as markdown starting directly with '### 🤖 AI 智能深度分析與建議'."""
            
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            gemini_insights = "\n" + response.text.strip() + "\n"
        except Exception as e:
            print(f"Warning: Failed to call Gemini API: {e}. Falling back to programmatic statistics only.")

    # Combine everything into the final Markdown Report
    date_str = datetime.now().strftime("%Y-%m-%d")
    report_md = f"""---
type: report
created: {date_str}
tags:
  - gmail-cleanup
  - report
  - automation
source: gmail-cleanup-cli
---

# 📩 Gmail 收件箱清理與分析週報 — {date_str}

## 📊 本週清理總覽
- **執行帳號：** `{account}` ({email_address})
- **本週累計自動清理：** **{total_cleaned}** 封信件
- **最新清理狀態：** 匹配 {latest_run['total_found']} 封，執行移入垃圾桶 {latest_run['total_deleted']} 封

### ⏱️ 清理紀錄歷史 (過去 7 天)
| 執行時間 | 運行模式 | 匹配數量 | 刪除數量 |
| :--- | :--- | :--- | :--- |
{runs_history_rows}
---

{trend_section}

---

{primary_section}

---

{gemini_insights if gemini_insights else ""}

{primary_action_section}

---

{unsubscribe_section}

---

{anomalies_section}

## Connections
- **Area:** [[System & DevOps]]
- **Related Projects:** [[Project -- Gmail Auto-Cleanup]]
"""

    # Resolve output path
    output_dir = Path("reports")
    if vault_path:
        vault_inbox = Path(vault_path) / "00 - Inbox" / "Agent_Output"
        if vault_inbox.exists():
            output_dir = vault_inbox

    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = output_dir / f"Weekly-Cleanup-Report-{date_str}.md"
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_md)
        
    print(f"Weekly report successfully written to: {report_file.resolve()}")
    return report_md
