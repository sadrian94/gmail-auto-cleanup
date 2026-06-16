import unittest
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

if __name__ == "__main__":
    unittest.main()
