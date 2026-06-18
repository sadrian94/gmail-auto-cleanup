import unittest
import unittest.mock
from gmail_cleanup.analytics import AnalyticsDB

class TestAnalyticsDB(unittest.TestCase):
    def setUp(self):
        # Use in-memory SQLite database for fast, isolated testing
        self.db = AnalyticsDB(":memory:")

    def test_record_and_get_weekly_data(self):
        account = "dummy"
        
        # 1. Record a cleanup run
        rule_stats = [
            {"rule_name": "promotions", "found_count": 10, "deleted_count": 10},
            {"rule_name": "social", "found_count": 5, "deleted_count": 5}
        ]
        sender_counts = [
            {"sender_name": "Sender A", "sender_email": "a@promo.com", "category": "promotions", "count": 8},
            {"sender_name": "Sender B", "sender_email": "b@social.com", "category": "social", "count": 5}
        ]
        primary_stats = {
            "total": 100,
            "unread": 10,
            "newsletters": 5
        }
        
        run_id = self.db.record_run(account, apply_mode=True, rule_stats=rule_stats, sender_counts=sender_counts, primary_stats=primary_stats)
        self.assertIsNotNone(run_id)
        
        # 2. Record inbox snapshot
        snapshot = {
            "inbox": 500,
            "promotions": 120,
            "social": 45,
            "trash": 15
        }
        self.db.record_snapshot(account, snapshot)
        
        # 3. Retrieve weekly data
        weekly_data = self.db.get_weekly_data(account)
        
        self.assertEqual(len(weekly_data["runs"]), 1)
        self.assertEqual(weekly_data["runs"][0]["total_found"], 15)
        self.assertEqual(weekly_data["runs"][0]["total_deleted"], 15)
        self.assertEqual(len(weekly_data["runs"][0]["breakdown"]), 2)
        
        self.assertEqual(len(weekly_data["top_senders"]), 2)
        self.assertEqual(weekly_data["top_senders"][0]["sender_email"], "a@promo.com")
        self.assertEqual(weekly_data["top_senders"][0]["total_count"], 8)
        
        self.assertEqual(len(weekly_data["snapshots"]), 1)
        self.assertEqual(weekly_data["snapshots"][0]["inbox_count"], 500)
        
        self.assertIsNotNone(weekly_data["primary_stats"])
        self.assertEqual(weekly_data["primary_stats"]["total_emails"], 100)
        self.assertEqual(weekly_data["primary_stats"]["unread_emails"], 10)

    def test_generate_text_report(self):
        account = "personal"
        
        # Record data
        self.db.record_run(account, False, [{"rule_name": "social", "found_count": 2, "deleted_count": 0}], [])
        self.db.record_snapshot(account, {"inbox": 10, "promotions": 0, "social": 2, "trash": 0})
        
        report = self.db.generate_text_report(account)
        self.assertIn("GMAIL CLEANUP WEEKLY SUMMARY REPORT", report)
        self.assertIn("DRY-RUN", report)
        self.assertIn("social", report)
        
    def test_generate_json_report(self):
        account = "dummy"
        self.db.record_run(account, True, [], [])
        json_report = self.db.generate_json_report(account)
        self.assertIn("runs", json_report)
        self.assertIn("top_senders", json_report)

    @unittest.mock.patch('gmail_cleanup.dashboard.generate_dashboard')
    @unittest.mock.patch('gmail_cleanup.__main__.AppConfig')
    @unittest.mock.patch('sys.argv', ['__main__.py', '--dashboard'])
    def test_cli_dashboard_flag(self, mock_app_config, mock_generate_dashboard):
        mock_config_instance = mock_app_config.return_value
        mock_config_instance.accounts = {"dummy": "dev_test_account@gmail.com"}
        mock_config_instance.db_path = "mock_analytics.db"
        
        from gmail_cleanup.__main__ import main
        
        with self.assertRaises(SystemExit) as cm:
            main()
            
        self.assertEqual(cm.exception.code, 0)
        mock_generate_dashboard.assert_called_once_with(
            "dummy", "mock_analytics.db", "dashboard.html"
        )

    @unittest.mock.patch('gmail_cleanup.ai_summary.label_clutter_emails')
    @unittest.mock.patch('urllib.request.urlopen')
    @unittest.mock.patch('gmail_cleanup.config.AppConfig')
    @unittest.mock.patch('os.environ', {"OPENCODE_API_KEY": "mock-opencode-key"})
    def test_generate_weekly_report_opencoder_go(self, mock_app_config, mock_urlopen, mock_label_clutter):
        # Setup mock config
        mock_config_instance = mock_app_config.return_value
        mock_config_instance.accounts = {"dummy": "dev_test_account@gmail.com"}
        mock_config_instance.ai = {
            "provider": "opencoder-go",
            "model": "deepseek-chat",
            "api_key_env": "OPENCODE_API_KEY",
            "base_url": "https://opencode.ai/zen/go/v1"
        }
        
        # Setup mock db and run generation within a temp directory
        import tempfile
        from pathlib import Path
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = str(Path(tmpdir) / "test_analytics.db")
            db = AnalyticsDB(db_file)
            # Populate runs to make report generation happy
            db.record_run("dummy", True, [{"rule_name": "social", "found_count": 5, "deleted_count": 5}], [])
            db.close()
            
            # Mock API response returning structured JSON
            mock_response = unittest.mock.Mock()
            mock_response.read.return_value = b'{"choices": [{"message": {"content": "{\\"report_markdown\\": \\"### AI Insights\\\\n- Mocked Opencode Go Insights\\", \\"suggested_clutter_senders\\": [\\"spammer@company.com\\"]}"}}]}'
            mock_urlopen.return_value.__enter__.return_value = mock_response
            
            from gmail_cleanup.ai_summary import generate_weekly_report
            report_md = generate_weekly_report("dummy", db_file, tmpdir)
            self.assertIn("Mocked Opencode Go Insights", report_md)
            
        # Verify labeling was triggered with mock senders list
        mock_label_clutter.assert_called_once_with("dummy", ["spammer@company.com"])

        # Verify urlopen was called
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://opencode.ai/zen/go/v1/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer mock-opencode-key")

    @unittest.mock.patch('gmail_cleanup.imap_utils.GmailSession')
    @unittest.mock.patch('gmail_cleanup.config.AppConfig')
    def test_label_clutter_emails(self, mock_app_config, mock_session_class):
        # Configure mock config
        mock_config_instance = mock_app_config.return_value
        mock_config_instance.accounts = {"dummy": "dev_test_account@gmail.com"}
        mock_config_instance.labels = {
            "review_to_delete": "Review-to-delete",
            "do_not_delete": "Do-not-delete"
        }
        
        # Configure mock session
        mock_session = unittest.mock.MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_session.search_uids.return_value = ["10", "20"]
        mock_session.add_label_to_uids.return_value = 2
        
        from gmail_cleanup.ai_summary import label_clutter_emails
        label_clutter_emails("dummy", ["spammer1@spam.com", "spammer2@spam.com"])
        
        # Verify search query
        mock_session.search_uids.assert_called_once_with(
            "label:inbox category:primary newer_than:30d -label:Do-not-delete (from:spammer1@spam.com OR from:spammer2@spam.com)"
        )
        
        # Verify labeling call
        mock_session.add_label_to_uids.assert_called_once_with(["10", "20"], "Review-to-delete")

if __name__ == "__main__":
    import unittest.mock
    unittest.main()
