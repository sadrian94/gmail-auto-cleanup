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
    
    # 4. Generate dashboard
    generate_dashboard(account="dummy", db_path=str(db_file), output_path=str(html_file))
    
    # 5. Assertions on generated file
    assert html_file.exists()
    html_content = html_file.read_text(encoding="utf-8")
    assert "dashboard" in html_content.lower()
    assert "noreply@github.com" in html_content
    assert "promo@promo.com" in html_content
    assert "150" in html_content  # promotions count


def test_generate_dashboard_empty(tmp_path):
    db_file = tmp_path / "empty_analytics.db"
    html_file = tmp_path / "dashboard_empty.html"
    
    # Initialize empty DB
    db = AnalyticsDB(str(db_file))
    db.close()
    
    # Generate dashboard
    generate_dashboard(account="dummy", db_path=str(db_file), output_path=str(html_file))
    
    assert html_file.exists()
    html_content = html_file.read_text(encoding="utf-8")
    assert "dashboard" in html_content.lower()
    assert "0" in html_content  # counts are 0 when empty


def test_generate_dashboard_with_report(tmp_path, monkeypatch):
    db_file = tmp_path / "test_analytics_report.db"
    html_file = tmp_path / "dashboard_report.html"
    
    db = AnalyticsDB(str(db_file))
    db.close()
    
    # Mock AppConfig to point obsidian_vault_path to our tmp_path directory
    from gmail_cleanup.config import AppConfig
    monkeypatch.setattr(AppConfig, "obsidian_vault_path", str(tmp_path))
    
    # Create the simulated Obsidian reports directory structure
    reports_dir = tmp_path / "00 - Inbox" / "Agent_Output"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    temp_report = reports_dir / "Weekly-Cleanup-Report-test.md"
    report_content = """---
type: weekly-report
created: 2026-06-18
---
# Weekly Summary
- **Total deleted**: 150 emails.
- Deleted `github` notifications.
"""
    temp_report.write_text(report_content, encoding="utf-8")
    
    generate_dashboard(account="dummy", db_path=str(db_file), output_path=str(html_file))
    assert html_file.exists()
    html_content = html_file.read_text(encoding="utf-8")
    assert "Weekly Summary" in html_content
    assert "<strong>Total deleted</strong>: 150 emails." in html_content
    assert "<code>github</code>" in html_content

