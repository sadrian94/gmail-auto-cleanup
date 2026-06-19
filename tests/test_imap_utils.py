"""Unit tests for imap_utils.GmailSession.

All tests use mocks — no live IMAP connection required.
Coverage targets:
- Pure/static helpers: decode_mime_str, decode_and_parse_sender,
  _parse_header_lines, _clean_body_content
- Mock-based stateful methods: find_system_folder, search_uids,
  move_to_trash, fetch_headers, fetch_snippets
"""

import unittest
from unittest.mock import MagicMock, patch, call

from gmail_cleanup.imap_utils import GmailSession


def _make_session() -> GmailSession:
    """Return a GmailSession with a mocked IMAP connection (no real login)."""
    session = GmailSession.__new__(GmailSession)
    session.account_name = "dummy"
    session.email = "test@example.com"
    session.mail = MagicMock()
    session.all_mail_folder = '"[Gmail]/All Mail"'
    session.trash_folder = '"[Gmail]/Trash"'
    return session


# ---------------------------------------------------------------------------
# decode_mime_str
# ---------------------------------------------------------------------------

class TestDecodeMimeStr(unittest.TestCase):
    def test_plain_ascii(self):
        self.assertEqual(GmailSession.decode_mime_str("Hello"), "Hello")

    def test_base64_encoded(self):
        # "Subject" encoded in UTF-8 base64
        encoded = "=?UTF-8?B?5L2g5aW9?="  # "你好"
        result = GmailSession.decode_mime_str(encoded)
        self.assertEqual(result, "你好")

    def test_empty_string(self):
        self.assertEqual(GmailSession.decode_mime_str(""), "")

    def test_none_returns_empty(self):
        self.assertEqual(GmailSession.decode_mime_str(None), "")


# ---------------------------------------------------------------------------
# decode_and_parse_sender
# ---------------------------------------------------------------------------

class TestDecodeAndParseSender(unittest.TestCase):
    def test_name_and_email(self):
        name, addr = GmailSession.decode_and_parse_sender('"Newsletter" <news@example.com>')
        self.assertEqual(name, "Newsletter")
        self.assertEqual(addr, "news@example.com")

    def test_bare_email(self):
        name, addr = GmailSession.decode_and_parse_sender("user@example.com")
        self.assertEqual(addr, "user@example.com")
        # Falls back to username when name is empty
        self.assertEqual(name, "user")

    def test_empty_string(self):
        name, addr = GmailSession.decode_and_parse_sender("")
        self.assertEqual(name, "")
        self.assertEqual(addr, "")


# ---------------------------------------------------------------------------
# _parse_header_lines
# ---------------------------------------------------------------------------

class TestParseHeaderLines(unittest.TestCase):
    def test_basic_fields(self):
        header = (
            "From: Test Sender <sender@example.com>\r\n"
            "Subject: Hello World\r\n"
            "Date: Thu, 1 Jan 2026 00:00:00 +0000\r\n"
        )
        session = _make_session()
        result = session._parse_header_lines(header)
        self.assertEqual(result["from_email"], "sender@example.com")
        self.assertEqual(result["subject"], "Hello World")

    def test_folded_header(self):
        """Continuation lines (starting with whitespace) should be joined."""
        header = (
            "Subject: This is a very\r\n"
            "  long subject line\r\n"
        )
        session = _make_session()
        result = session._parse_header_lines(header)
        self.assertIn("long subject line", result["subject"])

    def test_list_unsubscribe_extraction(self):
        # Parser picks the first URL in angle-brackets; here that's mailto:
        header = (
            "From: news@promo.com\r\n"
            "List-Unsubscribe: <mailto:unsub@promo.com>, <https://promo.com/unsub>\r\n"
        )
        session = _make_session()
        result = session._parse_header_lines(header)
        self.assertEqual(result["list_unsubscribe"], "mailto:unsub@promo.com")

    def test_list_unsubscribe_https_first(self):
        # When https URL comes first, it is extracted
        header = (
            "From: news@promo.com\r\n"
            "List-Unsubscribe: <https://promo.com/unsub>, <mailto:unsub@promo.com>\r\n"
        )
        session = _make_session()
        result = session._parse_header_lines(header)
        self.assertEqual(result["list_unsubscribe"], "https://promo.com/unsub")


# ---------------------------------------------------------------------------
# _clean_body_content
# ---------------------------------------------------------------------------

class TestCleanBodyContent(unittest.TestCase):
    def test_plain_text(self):
        session = _make_session()
        body = b"Hello, this is a plain text email body."
        result = session._clean_body_content(body)
        self.assertIn("plain text email body", result)

    def test_html_stripped(self):
        session = _make_session()
        body = b"<html><body><p>Click <a href='#'>here</a>.</p></body></html>"
        result = session._clean_body_content(body)
        self.assertNotIn("<", result)
        self.assertIn("Click", result)

    def test_empty_bytes(self):
        session = _make_session()
        result = session._clean_body_content(b"")
        self.assertEqual(result, "")

    def test_snippet_truncated_at_1000(self):
        session = _make_session()
        body = ("A" * 1200).encode("utf-8")
        result = session._clean_body_content(body)
        self.assertLessEqual(len(result), 1000)


# ---------------------------------------------------------------------------
# find_system_folder
# ---------------------------------------------------------------------------

class TestFindSystemFolder(unittest.TestCase):
    def test_finds_matching_folder(self):
        session = _make_session()
        session.mail.list.return_value = (
            "OK",
            [b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"'],
        )
        result = session.find_system_folder("\\All", '"[Gmail]/All Mail"')
        self.assertEqual(result, '"[Gmail]/All Mail"')

    def test_falls_back_to_default(self):
        session = _make_session()
        session.mail.list.return_value = ("OK", [b'(\\HasNoChildren) "/" "INBOX"'])
        result = session.find_system_folder("\\All", '"[Gmail]/All Mail"')
        self.assertEqual(result, '"[Gmail]/All Mail"')

    def test_imap_error_returns_default(self):
        session = _make_session()
        session.mail.list.side_effect = Exception("connection lost")
        result = session.find_system_folder("\\Trash", '"[Gmail]/Trash"')
        self.assertEqual(result, '"[Gmail]/Trash"')


# ---------------------------------------------------------------------------
# search_uids
# ---------------------------------------------------------------------------

class TestSearchUids(unittest.TestCase):
    def test_returns_uid_list(self):
        session = _make_session()
        session.mail.select.return_value = ("OK", [b"100"])
        session.mail.uid.return_value = ("OK", [b"1 2 3"])
        result = session.search_uids("category:promotions older_than:30d")
        self.assertEqual(result, ["1", "2", "3"])

    def test_empty_result(self):
        session = _make_session()
        session.mail.select.return_value = ("OK", [b"0"])
        session.mail.uid.return_value = ("OK", [b""])
        result = session.search_uids("category:social older_than:7d")
        self.assertEqual(result, [])

    def test_non_ok_status_raises(self):
        session = _make_session()
        session.mail.select.return_value = ("OK", [b"0"])
        session.mail.uid.return_value = ("NO", [None])
        with self.assertRaises(RuntimeError):
            session.search_uids("something")


# ---------------------------------------------------------------------------
# move_to_trash
# ---------------------------------------------------------------------------

class TestMoveToTrash(unittest.TestCase):
    def test_empty_list_returns_zero(self):
        session = _make_session()
        result = session.move_to_trash([])
        self.assertEqual(result, 0)
        session.mail.uid.assert_not_called()

    def test_moves_and_returns_count(self):
        session = _make_session()
        session.mail.select.return_value = ("OK", [b"5"])
        session.mail.uid.return_value = ("OK", [b""])
        session.mail.expunge.return_value = ("OK", [b""])
        result = session.move_to_trash(["1", "2", "3"])
        self.assertEqual(result, 3)

    def test_chunking_calls_store_twice_for_large_batch(self):
        session = _make_session()
        session.mail.select.return_value = ("OK", [b"0"])
        session.mail.uid.return_value = ("OK", [b""])
        session.mail.expunge.return_value = ("OK", [b""])
        # 501 UIDs → 2 chunks (500 + 1)
        uids = [str(i) for i in range(501)]
        session.move_to_trash(uids)
        # Each chunk triggers 2 uid() calls (STORE trash + STORE deleted)
        self.assertEqual(session.mail.uid.call_count, 4)

    def test_store_failure_raises(self):
        session = _make_session()
        session.mail.select.return_value = ("OK", [b"0"])
        session.mail.uid.return_value = ("NO", [b"failed"])
        with self.assertRaises(RuntimeError):
            session.move_to_trash(["1"])


# ---------------------------------------------------------------------------
# fetch_headers
# ---------------------------------------------------------------------------

class TestFetchHeaders(unittest.TestCase):
    def _imap_response(self, uid: str, flags: str, header: str):
        """Build the tuple-pair IMAP response format fetch_headers expects."""
        desc = f"1 (UID {uid} FLAGS ({flags}) BODY[HEADER.FIELDS (FROM SUBJECT DATE LIST-UNSUBSCRIBE)])"
        return (
            "OK",
            [
                (
                    desc.encode("utf-8"),
                    header.encode("utf-8"),
                )
            ],
        )

    def test_happy_path_extracts_uid_and_fields(self):
        session = _make_session()
        session.mail.select.return_value = ("OK", [b"1"])
        status, data = self._imap_response(
            uid="42",
            flags="\\Seen",
            header="From: Sender <sender@example.com>\r\nSubject: Hello\r\n",
        )
        session.mail.uid.return_value = (status, data)

        result = session.fetch_headers(["42"])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["uid"], "42")
        self.assertEqual(result[0]["from_email"], "sender@example.com")
        self.assertEqual(result[0]["subject"], "Hello")

    def test_seen_flag_detected(self):
        session = _make_session()
        session.mail.select.return_value = ("OK", [b"1"])
        status, data = self._imap_response(
            uid="10",
            flags="\\Seen \\Answered",
            header="From: a@b.com\r\nSubject: Read\r\n",
        )
        session.mail.uid.return_value = (status, data)
        result = session.fetch_headers(["10"])
        self.assertTrue(result[0]["is_read"])

    def test_unseen_flag_detected(self):
        session = _make_session()
        session.mail.select.return_value = ("OK", [b"1"])
        status, data = self._imap_response(
            uid="11",
            flags="",
            header="From: a@b.com\r\nSubject: Unread\r\n",
        )
        session.mail.uid.return_value = (status, data)
        result = session.fetch_headers(["11"])
        self.assertFalse(result[0]["is_read"])

    def test_empty_uid_list_returns_empty(self):
        session = _make_session()
        result = session.fetch_headers([])
        self.assertEqual(result, [])
        session.mail.uid.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_snippets
# ---------------------------------------------------------------------------

class TestFetchSnippets(unittest.TestCase):
    def test_happy_path_returns_uid_to_snippet_map(self):
        session = _make_session()
        session.mail.select.return_value = ("OK", [b"1"])
        session.mail.uid.return_value = (
            "OK",
            [
                (
                    b"1 (UID 99 BODY[TEXT] {22})",
                    b"This is the email body",
                )
            ],
        )
        result = session.fetch_snippets(["99"])
        self.assertIn("99", result)
        self.assertIn("email body", result["99"])

    def test_empty_uid_list_returns_empty_dict(self):
        session = _make_session()
        result = session.fetch_snippets([])
        self.assertEqual(result, {})
        session.mail.uid.assert_not_called()


if __name__ == "__main__":
    unittest.main()
