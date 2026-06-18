import email.header
import email.utils
import imaplib
import os
import keyring
from datetime import datetime

class GmailSession:
    def __init__(self, account_name: str, email_address: str):
        self.account_name = account_name
        self.email = email_address
        self.mail = None
        self.all_mail_folder = None
        self.trash_folder = None

    def __enter__(self):
        # Retrieve password
        password = self._get_password()
        if not password:
            raise ValueError(
                f"Password not found for service 'gmail_cleanup' and account '{self.email}'.\n"
                f"Please set it using the CLI command: gmail-cleanup --account {self.account_name} --set-password"
            )

        # Connect to Gmail IMAP
        try:
            self.mail = imaplib.IMAP4_SSL("imap.gmail.com")
            self.mail.login(self.email, password)
        except Exception as e:
            raise RuntimeError(f"Failed to log in to Gmail IMAP for {self.email}: {e}")

        # Resolve system folders dynamically
        self.all_mail_folder = self.find_system_folder("\\All", '"[Gmail]/All Mail"')
        self.trash_folder = self.find_system_folder("\\Trash", '"[Gmail]/Trash"')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.mail:
            try:
                self.mail.close()
            except Exception:
                pass
            try:
                self.mail.logout()
            except Exception:
                pass

    def _get_password(self) -> str:
        # 1. Try environment variables first (good for headless/CI)
        env_var_specific = f"GMAIL_APP_PASSWORD_{self.account_name.upper()}"
        password = os.environ.get(env_var_specific)
        if password:
            return password

        password = os.environ.get("GMAIL_APP_PASSWORD")
        if password:
            return password

        # 2. Try System Keychain/Credential Vault
        try:
            return keyring.get_password("gmail_cleanup", self.email)
        except Exception as e:
            print(f"Warning: Failed to retrieve password from keyring: {e}")
            return None

    def find_system_folder(self, attribute: str, default_fallback: str) -> str:
        """Finds system folders dynamically by querying their IMAP flags (e.g. \\All, \\Trash)

        to adapt to different Gmail accounts languages.
        """
        try:
            status, folder_list = self.mail.list()
            if status != 'OK' or not folder_list:
                return default_fallback
            for folder_bytes in folder_list:
                folder_str = folder_bytes.decode('utf-8', errors='ignore')
                if attribute in folder_str:
                    parts = folder_str.split('"')
                    if len(parts) >= 2:
                        return f'"{parts[-2]}"'
        except Exception:
            pass
        return default_fallback

    def search_uids(self, query: str) -> list[str]:
        """Searches messages using Gmail's X-GM-RAW extension."""
        # Always select All Mail first so search covers entire mailbox
        self.mail.select(self.all_mail_folder, readonly=True)
        # Escape any double quotes in the query to prevent IMAP syntax errors
        escaped_query = query.replace('"', '\\"')
        status, data = self.mail.uid('SEARCH', 'X-GM-RAW', f'"{escaped_query}"')
        if status != 'OK':
            raise RuntimeError(f"Gmail search failed: status={status}, query={query}")
        if not data or not data[0]:
            return []
        uids = data[0].split()
        return [uid.decode('utf-8') for uid in uids]

    def move_to_trash(self, uids: list[str]) -> int:
        """Moves UIDs to Gmail Trash in chunks of 500.

        Uses the recommended Trash workflow:
        1. Add +X-GM-LABELS (\\Trash)
        2. Add +FLAGS \\Deleted
        3. EXPUNGE
        """
        if not uids:
            return 0

        # Select All Mail in read-write mode to apply changes
        self.mail.select(self.all_mail_folder, readonly=False)

        chunk_size = 500
        count = 0
        for i in range(0, len(uids), chunk_size):
            chunk = uids[i:i+chunk_size]
            uid_str = ",".join(chunk)

            # 1. Add Trash label
            status, _ = self.mail.uid('STORE', uid_str, '+X-GM-LABELS', '\\Trash')
            if status != 'OK':
                raise RuntimeError(f"Failed to add Trash label to chunk {i}")

            # 2. Mark as deleted (flags)
            status, _ = self.mail.uid('STORE', uid_str, '+FLAGS', '\\Deleted')
            if status != 'OK':
                raise RuntimeError(f"Failed to set Deleted flag to chunk {i}")

            # 3. Expunge changes
            self.mail.expunge()
            count += len(chunk)

        return count

    def add_label_to_uids(self, uids: list[str], label_name: str) -> int:
        """Adds a Gmail label to the specified UIDs in chunks of 500."""
        if not uids:
            return 0

        # Ensure label exists (create it if not)
        try:
            self.mail.create(f'"{label_name}"')
        except Exception:
            pass # ignore if already exists or fails

        # Select INBOX in read-write mode
        self.mail.select("INBOX", readonly=False)

        chunk_size = 500
        count = 0
        for i in range(0, len(uids), chunk_size):
            chunk = uids[i:i+chunk_size]
            uid_str = ",".join(chunk)

            status, _ = self.mail.uid('STORE', uid_str, '+X-GM-LABELS', f'"{label_name}"')
            if status == 'OK':
                count += len(chunk)

        return count

    def fetch_headers(self, uids: list[str]) -> list[dict]:
        """Fetches header fields (From, Subject, Date, List-Unsubscribe, and flags) in chunks of 500

        without marking messages as read (using BODY.PEEK).
        """
        if not uids:
            return []

        self.mail.select(self.all_mail_folder, readonly=True)
        chunk_size = 500
        headers_list = []

        for i in range(0, len(uids), chunk_size):
            chunk = uids[i:i+chunk_size]
            uid_str = ",".join(chunk)

            # Fetch headers and flags
            status, data = self.mail.uid('FETCH', uid_str, '(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE LIST-UNSUBSCRIBE)])')
            if status != 'OK':
                raise RuntimeError(f"Failed to fetch headers for chunk {i}")

            # Parse tuple-pair format
            current_uid = None
            current_flags = []
            
            for item in data:
                if isinstance(item, tuple):
                    # item[0] contains UID and status info, item[1] contains the header content
                    desc = item[0].decode('utf-8', errors='ignore')
                    # Extract UID from description (e.g., "123 (UID 456 FLAGS (\Seen) BODY...")
                    uid_part = desc.split('UID')
                    if len(uid_part) > 1:
                        current_uid = uid_part[1].split()[0]
                    
                    # Extract flags
                    flags_part = desc.split('FLAGS')
                    if len(flags_part) > 1:
                        flags_str = flags_part[1].split(')')[0].replace('(', '')
                        current_flags = [f.strip() for f in flags_str.split() if f]

                    header_content = item[1].decode('utf-8', errors='ignore')
                    headers_dict = self._parse_header_lines(header_content)
                    
                    headers_dict['uid'] = current_uid or ""
                    # Check if \Seen flag is present (message is read)
                    headers_dict['is_read'] = '\\Seen' in current_flags
                    headers_list.append(headers_dict)
                    
                    # Reset variables for next message
                    current_uid = None
                    current_flags = []

        return headers_list

    def _parse_header_lines(self, header_content: str) -> dict:
        """Parses header text lines into a dictionary."""
        lines = header_content.splitlines()
        parsed = {
            "from": "",
            "subject": "",
            "date": "",
            "list_unsubscribe": ""
        }
        
        current_field = None
        for line in lines:
            if not line:
                continue
            
            # Check if this is a continuation line (starts with space or tab)
            if line[0] in (' ', '\t') and current_field:
                parsed[current_field] += " " + line.strip()
                continue

            parts = line.split(':', 1)
            if len(parts) == 2:
                field_name = parts[0].strip().lower().replace('-', '_')
                if field_name in parsed:
                    current_field = field_name
                    parsed[field_name] = parts[1].strip()
                else:
                    current_field = None

        # Clean fields
        parsed["from_name"], parsed["from_email"] = self.decode_and_parse_sender(parsed["from"])
        parsed["subject"] = self.decode_mime_str(parsed["subject"])
        
        # Clean List-Unsubscribe link (often looks like "<mailto:abc>, <https://link>")
        lu = parsed["list_unsubscribe"]
        if lu:
            # Extract links inside angled brackets
            links = []
            import re
            for match in re.finditer(r'<(https?://[^>]+|mailto:[^>]+)>', lu):
                links.append(match.group(1))
            parsed["list_unsubscribe"] = links[0] if links else lu

        return parsed

    @staticmethod
    def decode_mime_str(s: str) -> str:
        """Decodes MIME encoded strings (e.g.

        =?UTF-8?B?...=).
        """
        if not s:
            return ""
        try:
            decoded_fragments = email.header.decode_header(s)
            parts = []
            for text, charset in decoded_fragments:
                if isinstance(text, bytes):
                    parts.append(text.decode(charset or 'utf-8', errors='ignore'))
                else:
                    parts.append(text)
            return "".join(parts).strip()
        except Exception:
            return s

    @staticmethod
    def decode_and_parse_sender(from_header: str) -> tuple[str, str]:
        """Parses the 'From' header into (decoded_name, email_address)."""
        if not from_header:
            return "", ""
        
        name, email_address = email.utils.parseaddr(from_header)
        name = GmailSession.decode_mime_str(name)
        
        # If name is empty, use the email username as the name
        if not name and email_address:
            name = email_address.split('@')[0]
            
        return name, email_address

    def get_inbox_snapshot(self) -> dict:
        """Collects inbox size statistics for various categories."""
        snapshot = {
            "inbox": 0,
            "promotions": 0,
            "social": 0,
            "trash": 0
        }

        # 1. Total Inbox count
        try:
            status, data = self.mail.select("INBOX", readonly=True)
            if status == 'OK':
                snapshot["inbox"] = int(data[0])
        except Exception:
            pass

        # 2. Total Promotions count in Inbox
        try:
            snapshot["promotions"] = len(self.search_uids("label:inbox category:promotions"))
        except Exception:
            pass

        # 3. Total Social count in Inbox
        try:
            snapshot["social"] = len(self.search_uids("label:inbox category:social"))
        except Exception:
            pass

        # 4. Total Trash count
        try:
            self.mail.select(self.trash_folder, readonly=True)
            status, data = self.mail.select(self.trash_folder, readonly=True)
            if status == 'OK':
                snapshot["trash"] = int(data[0])
        except Exception:
            pass

        return snapshot
