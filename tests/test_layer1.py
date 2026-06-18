import unittest
from unittest.mock import MagicMock, patch
from gmail_cleanup.layer1 import run_cleanup_task

class TestLayer1(unittest.TestCase):
    @patch("gmail_cleanup.layer1.GmailSession")
    @patch("gmail_cleanup.layer1.AnalyticsDB")
    def test_run_cleanup_task_dry_run(self, mock_db_class, mock_session_class):
        # Configure mocks
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session
        
        # Mock search_uids responses
        # 1st call for promotions, 2nd call for social, 3rd call for receipts
        mock_session.search_uids.side_dict = {
            "category:promotions older_than:30d": ["1", "2"],
            "category:social older_than:7d": ["3"],
            "label:receipts older_than:730d": []
        }
        # Simplify side effect for search_uids
        def search_side_effect(query):
            if "promotions" in query:
                return ["1", "2"]
            elif "social" in query:
                return ["3"]
            elif "receipts" in query:
                return []
            elif "primary" in query:
                return ["10", "11"]
            return []
            
        mock_session.search_uids.side_effect = search_side_effect
        
        # Mock fetch_headers for deep scan
        mock_session.fetch_headers.side_effect = lambda uids: [
            {"from_email": "newsletter@promo.com", "from_name": "Newsletter", "uid": uid, "is_read": True, "list_unsubscribe": "https://unsubscribe.com"}
            for uid in uids
        ]
        
        # Mock get_inbox_snapshot
        mock_session.get_inbox_snapshot.return_value = {
            "inbox": 150, "promotions": 25, "social": 12, "trash": 5
        }
        
        # Mock DB
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        
        # Run config rules
        rules_config = {
            "promotions": {"days": 30, "enabled": True},
            "social": {"days": 7, "enabled": True},
            "receipts": {"days": 730, "enabled": True}
        }
        
        # Execute run_cleanup_task in dry-run mode (apply_mode=False)
        summary = run_cleanup_task(
            account_name="dummy",
            email_address="dev_test_account@gmail.com",
            apply_mode=False,
            run_analytics=True,
            deep_scan=True,
            db_path=":memory:",
            rules_config=rules_config
        )
        
        # Verify execution and assertions
        self.assertEqual(summary["account"], "dummy")
        self.assertEqual(summary["apply_mode"], False)
        
        # Verify search calls
        self.assertTrue(mock_session.search_uids.called)
        
        # Since it is dry-run, move_to_trash should NOT be called
        mock_session.move_to_trash.assert_not_called()
        
        # Verify snapshots were recorded
        mock_session.get_inbox_snapshot.assert_called_once()
        
        # Verify db.record_run was called
        mock_db.record_run.assert_called_once()
        mock_db.record_snapshot.assert_called_once()

        # Verify that ensure_label_exists was called for configured labels
        mock_session.ensure_label_exists.assert_any_call("Review-to-delete")
        mock_session.ensure_label_exists.assert_any_call("Do-not-delete")

        # Verify that search queries excluded Do-not-delete labeled emails
        search_calls = mock_session.search_uids.call_args_list
        queries = [call[0][0] for call in search_calls]
        self.assertTrue(any("category:promotions" in q and "-label:Do-not-delete" in q for q in queries))
        self.assertTrue(any("category:social" in q and "-label:Do-not-delete" in q for q in queries))
        self.assertTrue(any("label:purchases" in q and "-label:Do-not-delete" in q for q in queries))
        
    @patch("gmail_cleanup.layer1.GmailSession")
    @patch("gmail_cleanup.layer1.AnalyticsDB")
    def test_run_cleanup_task_apply_mode(self, mock_db_class, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session
        
        # Setup search to return uids
        mock_session.search_uids.return_value = ["100", "200"]
        mock_session.move_to_trash.return_value = 2
        mock_session.get_inbox_snapshot.return_value = {
            "inbox": 100, "promotions": 0, "social": 0, "trash": 10
        }
        
        rules_config = {
            "promotions": {"days": 30, "enabled": True}
        }
        
        summary = run_cleanup_task(
            account_name="dummy",
            email_address="dev_test_account@gmail.com",
            apply_mode=True,
            run_analytics=False,
            deep_scan=False,
            db_path=":memory:",
            rules_config=rules_config
        )
        
        # Verify cleanup application
        self.assertEqual(summary["apply_mode"], True)
        mock_session.move_to_trash.assert_called_once_with(["100", "200"])
        self.assertEqual(summary["rules_executed"][0]["deleted_count"], 2)

if __name__ == "__main__":
    unittest.main()
