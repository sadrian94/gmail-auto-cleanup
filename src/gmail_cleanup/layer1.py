from collections import Counter
from gmail_cleanup.imap_utils import GmailSession
from gmail_cleanup.analytics import AnalyticsDB

def run_cleanup_task(
    account_name: str,
    email_address: str,
    apply_mode: bool,
    run_analytics: bool,
    deep_scan: bool,
    db_path: str,
    rules_config: dict
) -> dict:
    """Executes the Gmail Auto-Cleanup rules and profiles the Primary Inbox."""
    summary = {
        "account": account_name,
        "email": email_address,
        "timestamp": "",
        "apply_mode": apply_mode,
        "rules_executed": [],
        "primary_inbox_profile": None,
        "snapshot": None
    }

    rule_stats = []
    all_sender_counts = []  # For deep scan analytics
    primary_stats = None

    # Load DB
    db = AnalyticsDB(db_path) if run_analytics else None

    # Connect to Gmail
    with GmailSession(account_name, email_address) as session:
        # 1. Execute Cleanup Rules
        for rule_name, rule_data in rules_config.items():
            if not rule_data.get("enabled", True):
                continue

            days = rule_data.get("days", 30)
            
            # Formulate Gmail IMAP search query
            if rule_name == "promotions":
                query = f"category:promotions older_than:{days}d"
            elif rule_name == "social":
                query = f"category:social older_than:{days}d"
            elif rule_name == "receipts":
                query = f"label:receipts older_than:{days}d"
            else:
                # Custom rule support
                query = f"label:{rule_name} older_than:{days}d"

            print(f"[{account_name.upper()}] Running rule '{rule_name}' with query: '{query}'...")
            uids = session.search_uids(query)
            
            # Receipts fallback logic
            if rule_name == "receipts" and not uids:
                fallback_query = f'(subject:receipt OR subject:invoice OR subject:billing OR subject:"order confirmation") older_than:{days}d'
                print(f"[{account_name.upper()}] No labeled receipts found. Trying fallback query: '{fallback_query}'...")
                uids = session.search_uids(fallback_query)
                query = fallback_query  # update query for logging

            found_count = len(uids)
            deleted_count = 0

            if found_count > 0:
                print(f"[{account_name.upper()}] Found {found_count} messages matching rule '{rule_name}'.")
                
                # Perform Deep Scan if requested (only fetch headers for matching emails before deleting them)
                if deep_scan and rule_name in ["promotions", "social", "receipts"]:
                    print(f"[{account_name.upper()}] Fetching headers for sender analysis...")
                    try:
                        headers = session.fetch_headers(uids)
                        # Count senders
                        senders = [h["from_email"] for h in headers if h.get("from_email")]
                        names = {h["from_email"]: h["from_name"] for h in headers if h.get("from_email")}
                        
                        sender_counts = Counter(senders)
                        for email, count in sender_counts.items():
                            all_sender_counts.append({
                                "sender_name": names.get(email, ""),
                                "sender_email": email,
                                "category": rule_name,
                                "count": count
                            })
                    except Exception as e:
                        print(f"Warning: Failed to fetch headers for deep scan: {e}")

                # Move to Trash if apply mode is on
                if apply_mode:
                    print(f"[{account_name.upper()}] Moving {found_count} messages to Trash...")
                    deleted_count = session.move_to_trash(uids)
                    print(f"[{account_name.upper()}] Successfully moved {deleted_count} messages to Trash.")
                else:
                    print(f"[{account_name.upper()}] [DRY-RUN] Would move {found_count} messages to Trash.")
            else:
                print(f"[{account_name.upper()}] No messages found matching rule '{rule_name}'.")

            rule_stats.append({
                "rule_name": rule_name,
                "query": query,
                "found_count": found_count,
                "deleted_count": deleted_count
            })

        # 2. Deep Profile Primary Inbox (Lately scanned past 30 days)
        # We always profile the Primary Inbox on deep scans or when requested
        if deep_scan:
            primary_query = "label:inbox category:primary newer_than:30d"
            print(f"[{account_name.upper()}] Profiling Primary Inbox (past 30 days) with query: '{primary_query}'...")
            primary_uids = session.search_uids(primary_query)
            
            total_primary = len(primary_uids)
            unread_primary = 0
            newsletters_count = 0
            primary_senders = []
            primary_names = {}
            unread_senders = []
            newsletters_senders = []

            if total_primary > 0:
                print(f"[{account_name.upper()}] Fetching headers for {total_primary} Primary Inbox emails...")
                try:
                    primary_headers = session.fetch_headers(primary_uids)
                    for h in primary_headers:
                        email = h.get("from_email")
                        name = h.get("from_name", "")
                        if not email:
                            continue
                        
                        primary_senders.append(email)
                        primary_names[email] = name
                        
                        if not h.get("is_read", True):
                            unread_primary += 1
                            unread_senders.append(email)
                            
                        if h.get("list_unsubscribe"):
                            newsletters_count += 1
                            newsletters_senders.append(email)
                except Exception as e:
                    print(f"Warning: Failed to fetch headers for Primary Inbox profile: {e}")

            # Summarize top senders in Primary Inbox
            top_primary_senders = [
                {"email": email, "name": primary_names.get(email, ""), "count": count}
                for email, count in Counter(primary_senders).most_common(10)
            ]
            top_unread_senders = [
                {"email": email, "name": primary_names.get(email, ""), "count": count}
                for email, count in Counter(unread_senders).most_common(10)
            ]
            top_newsletters = [
                {"email": email, "name": primary_names.get(email, ""), "count": count}
                for email, count in Counter(newsletters_senders).most_common(10)
            ]

            primary_stats = {
                "total": total_primary,
                "unread": unread_primary,
                "newsletters": newsletters_count,
                "top_senders": top_primary_senders,
                "top_unread_senders": top_unread_senders,
                "top_newsletters": top_newsletters
            }
            summary["primary_inbox_profile"] = primary_stats

        # 3. Take Inbox Snapshot (Current sizes)
        print(f"[{account_name.upper()}] Taking inbox snapshot...")
        snapshot = session.get_inbox_snapshot()
        summary["snapshot"] = snapshot

        # 4. Save to database if requested
        if run_analytics and db:
            print(f"[{account_name.upper()}] Recording run statistics to database...")
            db.record_run(account_name, apply_mode, rule_stats, all_sender_counts, primary_stats)
            db.record_snapshot(account_name, snapshot)
            print(f"[{account_name.upper()}] DB records updated.")

    summary["rules_executed"] = rule_stats
    return summary
