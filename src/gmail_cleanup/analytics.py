import sqlite3
import json
from pathlib import Path
from datetime import datetime

class AnalyticsDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            db_path_obj = Path(db_path)
            db_path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._init_db()

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None


    def _init_db(self):
        with self.conn as conn:
            
            # 1. Cleanup runs table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cleanup_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT (datetime('now', 'localtime')),
                    account TEXT NOT NULL,
                    apply_mode INTEGER NOT NULL,  -- 0 for dry-run, 1 for apply
                    total_found INTEGER DEFAULT 0,
                    total_deleted INTEGER DEFAULT 0
                );
            """)

            # 2. Rule breakdown table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rule_breakdown (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    rule_name TEXT NOT NULL,
                    found_count INTEGER DEFAULT 0,
                    deleted_count INTEGER DEFAULT 0,
                    FOREIGN KEY(run_id) REFERENCES cleanup_runs(id) ON DELETE CASCADE
                );
            """)

            # 3. Sender stats table (sender breakdown)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sender_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    sender_name TEXT,
                    sender_email TEXT NOT NULL,
                    category TEXT NOT NULL,       -- 'promotions', 'social', 'receipts'
                    email_count INTEGER DEFAULT 0,
                    FOREIGN KEY(run_id) REFERENCES cleanup_runs(id) ON DELETE CASCADE
                );
            """)

            # 4. Inbox snapshots table (overall size trends)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS inbox_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT (datetime('now', 'localtime')),
                    account TEXT NOT NULL,
                    inbox_count INTEGER NOT NULL,
                    promotions_count INTEGER NOT NULL,
                    social_count INTEGER NOT NULL,
                    trash_count INTEGER NOT NULL
                );
            """)

            # 5. Primary inbox profiling stats
            conn.execute("""
                CREATE TABLE IF NOT EXISTS primary_inbox_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    total_emails INTEGER NOT NULL,
                    unread_emails INTEGER NOT NULL,
                    newsletters_count INTEGER NOT NULL,
                    top_senders_json TEXT,
                    top_unread_senders_json TEXT,
                    top_newsletters_json TEXT,
                    FOREIGN KEY(run_id) REFERENCES cleanup_runs(id) ON DELETE CASCADE
                );
            """)
            
            # Safe schema migrations for existing databases
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(primary_inbox_stats);")
            columns = [row[1] for row in cursor.fetchall()]
            if columns:
                if "top_senders_json" not in columns:
                    conn.execute("ALTER TABLE primary_inbox_stats ADD COLUMN top_senders_json TEXT;")
                if "top_unread_senders_json" not in columns:
                    conn.execute("ALTER TABLE primary_inbox_stats ADD COLUMN top_unread_senders_json TEXT;")
                if "top_newsletters_json" not in columns:
                    conn.execute("ALTER TABLE primary_inbox_stats ADD COLUMN top_newsletters_json TEXT;")
            
            conn.commit()

    def record_run(self, account: str, apply_mode: bool, rule_stats: list[dict], sender_counts: list[dict], primary_stats: dict = None) -> int:
        """Records a cleanup run and all associated breakdown and sender statistics."""
        total_found = sum(r["found_count"] for r in rule_stats)
        total_deleted = sum(r["deleted_count"] for r in rule_stats)

        with self.conn as conn:
            cursor = conn.cursor()
            # 1. Insert run
            cursor.execute(
                "INSERT INTO cleanup_runs (account, apply_mode, total_found, total_deleted) VALUES (?, ?, ?, ?)",
                (account, 1 if apply_mode else 0, total_found, total_deleted)
            )
            run_id = cursor.lastrowid

            # 2. Insert rule breakdowns
            for r in rule_stats:
                cursor.execute(
                    "INSERT INTO rule_breakdown (run_id, rule_name, found_count, deleted_count) VALUES (?, ?, ?, ?)",
                    (run_id, r["rule_name"], r["found_count"], r["deleted_count"])
                )

            # 3. Insert sender stats
            for s in sender_counts:
                cursor.execute(
                    "INSERT INTO sender_stats (run_id, sender_name, sender_email, category, email_count) VALUES (?, ?, ?, ?, ?)",
                    (run_id, s.get("sender_name", ""), s["sender_email"], s["category"], s["count"])
                )

            # 4. Insert Primary Inbox stats if provided
            if primary_stats:
                cursor.execute(
                    "INSERT INTO primary_inbox_stats (run_id, total_emails, unread_emails, newsletters_count, top_senders_json, top_unread_senders_json, top_newsletters_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        primary_stats["total"],
                        primary_stats["unread"],
                        primary_stats["newsletters"],
                        json.dumps(primary_stats.get("top_senders", [])),
                        json.dumps(primary_stats.get("top_unread_senders", [])),
                        json.dumps(primary_stats.get("top_newsletters", []))
                    )
                )

            conn.commit()
            return run_id

    def record_snapshot(self, account: str, snapshot: dict):
        """Records an overall inbox snapshot."""
        with self.conn as conn:
            conn.execute(
                "INSERT INTO inbox_snapshots (account, inbox_count, promotions_count, social_count, trash_count) VALUES (?, ?, ?, ?, ?)",
                (account, snapshot["inbox"], snapshot["promotions"], snapshot["social"], snapshot["trash"])
            )
            conn.commit()

    def get_weekly_data(self, account: str) -> dict:
        """Retrieves runs, sender analytics, and snapshot trends over the past 7 days."""
        data = {
            "runs": [],
            "top_senders": [],
            "snapshots": [],
            "primary_stats": None
        }

        with self.conn as conn:
            # Recent runs in past 7 days
            runs_rows = conn.execute("""
                SELECT * FROM cleanup_runs 
                WHERE account = ? AND datetime(timestamp) >= datetime('now', '-7 days')
                ORDER BY timestamp DESC
            """, (account,)).fetchall()
            
            data["runs"] = [dict(r) for r in runs_rows]
            
            # Map breakdowns for these runs
            for run in data["runs"]:
                breakdown_rows = conn.execute(
                    "SELECT rule_name, found_count, deleted_count FROM rule_breakdown WHERE run_id = ?",
                    (run["id"],)
                ).fetchall()
                run["breakdown"] = [dict(b) for b in breakdown_rows]

            # Top senders in past 7 days
            sender_rows = conn.execute("""
                SELECT sender_name, sender_email, category, SUM(email_count) as total_count 
                FROM sender_stats 
                JOIN cleanup_runs ON sender_stats.run_id = cleanup_runs.id
                WHERE cleanup_runs.account = ? AND datetime(cleanup_runs.timestamp) >= datetime('now', '-7 days')
                GROUP BY sender_email, category
                ORDER BY total_count DESC
                LIMIT 15
            """, (account,)).fetchall()
            
            data["top_senders"] = [dict(s) for s in sender_rows]

            # Recent snapshots (past 14 days to compute week-over-week trends)
            snapshot_rows = conn.execute("""
                SELECT * FROM inbox_snapshots 
                WHERE account = ? AND datetime(timestamp) >= datetime('now', '-14 days')
                ORDER BY timestamp ASC
            """, (account,)).fetchall()
            
            data["snapshots"] = [dict(s) for s in snapshot_rows]

            # Latest Primary Inbox stats
            if data["runs"]:
                latest_run_id = data["runs"][0]["id"]
                p_row = conn.execute(
                    "SELECT * FROM primary_inbox_stats WHERE run_id = ?",
                    (latest_run_id,)
                ).fetchone()
                if p_row:
                    data["primary_stats"] = dict(p_row)

        return data

    def generate_json_report(self, account: str) -> str:
        """Generates a structured JSON string containing run histories and trends."""
        data = self.get_weekly_data(account)
        return json.dumps(data, indent=2)

    def generate_text_report(self, account: str) -> str:
        """Generates a human-readable text report of the cleanup runs and trends."""
        data = self.get_weekly_data(account)
        if not data["runs"]:
            return f"No cleanup logs found in the database for account '{account}' in the past 7 days."

        report = []
        report.append("=" * 60)
        report.append(f"GMAIL CLEANUP WEEKLY SUMMARY REPORT - ACCOUNT: {account.upper()}")
        report.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("=" * 60)
        report.append("")

        # 1. Recent Runs Table
        report.append("--- RECENT RUNS (PAST 7 DAYS) ---")
        report.append(f"{'Run Time':<20} | {'Mode':<8} | {'Found':<6} | {'Deleted':<8}")
        report.append("-" * 50)
        for r in data["runs"]:
            mode = "APPLY" if r["apply_mode"] == 1 else "DRY-RUN"
            report.append(f"{r['timestamp']:<20} | {mode:<8} | {r['total_found']:<6} | {r['total_deleted']:<8}")
        report.append("")

        # 2. Rule Breakdown
        report.append("--- CLEANUP RULE EFFECTIVENESS ---")
        rule_totals = {}
        for r in data["runs"]:
            for b in r.get("breakdown", []):
                name = b["rule_name"]
                if name not in rule_totals:
                    rule_totals[name] = {"found": 0, "deleted": 0}
                rule_totals[name]["found"] += b["found_count"]
                rule_totals[name]["deleted"] += b["deleted_count"]

        for name, totals in rule_totals.items():
            report.append(f"• Rule: {name:<12} | Total Found: {totals['found']:<5} | Total Deleted: {totals['deleted']}")
        report.append("")

        # 3. Top Senders Scanned
        if data["top_senders"]:
            report.append("--- TOP CLUTTER SENDERS (PROMOTIONS / SOCIAL) ---")
            report.append(f"{'Sender Email':<35} | {'Category':<10} | {'Count':<5}")
            report.append("-" * 55)
            for s in data["top_senders"]:
                email = s["sender_email"]
                # Truncate long emails
                if len(email) > 35:
                    email = email[:32] + "..."
                report.append(f"{email:<35} | {s['category']:<10} | {s['total_count']:<5}")
            report.append("")

        # 4. Primary Inbox Profile
        if data["primary_stats"]:
            p = data["primary_stats"]
            report.append("--- PRIMARY INBOX SCAN (LATEST 30 DAYS PROFILE) ---")
            report.append(f"• Total emails scanned: {p['total_emails']}")
            report.append(f"• Unread emails:        {p['unread_emails']} ({(p['unread_emails']/p['total_emails'])*100:.1f}%)")
            report.append(f"• Newsletters detected: {p['newsletters_count']} ({(p['newsletters_count']/p['total_emails'])*100:.1f}%)")
            report.append("")

        # 5. Inbox Size Snapshot Trends
        if len(data["snapshots"]) >= 2:
            first = data["snapshots"][0]
            last = data["snapshots"][-1]
            report.append("--- WEEK-OVER-WEEK INBOX TRENDS ---")
            
            diff_inbox = last["inbox_count"] - first["inbox_count"]
            pct_inbox = (diff_inbox / first["inbox_count"] * 100) if first["inbox_count"] > 0 else 0
            trend_str = "increased" if diff_inbox >= 0 else "decreased"
            
            report.append(f"• Inbox Size: {first['inbox_count']} -> {last['inbox_count']} ({trend_str} by {abs(pct_inbox):.1f}%)")
            report.append(f"• Promotions: {first['promotions_count']} -> {last['promotions_count']}")
            report.append(f"• Social:     {first['social_count']} -> {last['social_count']}")
            report.append(f"• Trash:      {first['trash_count']} -> {last['trash_count']}")
            report.append("")

        report.append("=" * 60)
        return "\n".join(report)
