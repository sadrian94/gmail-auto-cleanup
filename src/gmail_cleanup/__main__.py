import argparse
import sys
import getpass
import keyring
from gmail_cleanup.config import AppConfig
from gmail_cleanup.layer1 import run_cleanup_task
from gmail_cleanup.analytics import AnalyticsDB
from gmail_cleanup.ai_summary import generate_weekly_report

def handle_password_setup(account_name: str, email_address: str):
    """Interactively prompts user for App Password and stores it in keyring."""
    print(f"=== Gmail App Password Configuration ===")
    print(f"Account: {account_name}")
    print(f"Email:   {email_address}")
    print("-----------------------------------------")
    print("Please enter your Gmail App Password.")
    print("(Note: This must be a 16-character App Password generated in Google Account Security, NOT your main password.)")
    print("The password will be stored securely in your system Credential Locker / Keychain.")
    print("-----------------------------------------")
    
    password = getpass.getpass("Enter App Password: ").strip()
    if not password:
        print("Error: Password cannot be empty.")
        sys.exit(1)
        
    try:
        keyring.set_password("gmail_cleanup", email_address, password)
        print(f"Success: App Password for {email_address} successfully saved to keyring.")
    except Exception as e:
        print(f"Error: Failed to save password to keyring: {e}")
        sys.exit(1)

def main():
    config = AppConfig()
    
    parser = argparse.ArgumentParser(description="Gmail Auto-Cleanup Tool")
    parser.add_argument(
        "--account",
        default="dummy",
        choices=list(config.accounts.keys()),
        help=f"Select account key from config.yaml (available: {', '.join(config.accounts.keys())}, default: dummy)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply changes to Gmail (moves matching messages to Trash). Default is dry-run."
    )
    parser.add_argument(
        "--analytics",
        action="store_true",
        help="Execute cleanup rules and save run statistics to the SQLite DB."
    )
    parser.add_argument(
        "--analytics-deep",
        action="store_true",
        help="Execute rules, perform sender deep scan, profile the Primary Inbox (30d), and save stats to SQLite."
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print JSON weekly report from the SQLite database to the console."
    )
    parser.add_argument(
        "--report-text",
        action="store_true",
        help="Print a human-readable summary of runs, senders, and snapshots to the console."
    )
    parser.add_argument(
        "--ai-summary",
        action="store_true",
        help="Generate the Markdown Weekly Report and write it directly to the configured Obsidian Vault."
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Generate the static HTML dashboard based on SQLite stats."
    )
    parser.add_argument(
        "--set-password",
        action="store_true",
        help="Set the Gmail App Password for the selected account in the system keyring."
    )

    args = parser.parse_args()
    
    email_address = config.accounts.get(args.account)
    if not email_address:
        print(f"Error: Account key '{args.account}' not configured in config.yaml.")
        sys.exit(1)

    # 1. Password Setup Utility
    if args.set_password:
        handle_password_setup(args.account, email_address)
        sys.exit(0)

    # 2. Database Reporting Utilities
    if args.report:
        db = AnalyticsDB(config.db_path)
        print(db.generate_json_report(args.account))
        sys.exit(0)

    if args.report_text:
        db = AnalyticsDB(config.db_path)
        print(db.generate_text_report(args.account))
        sys.exit(0)

    if args.dashboard:
        from gmail_cleanup.dashboard import generate_dashboard
        try:
            generate_dashboard(args.account, config.db_path, "dashboard.html")
            print("Successfully created dashboard.html")
        except Exception as e:
            print(f"Error generating dashboard: {e}")
            sys.exit(1)
        sys.exit(0)

    if args.ai_summary and not (args.analytics or args.analytics_deep):
        # Just generate the report based on existing DB stats
        try:
            generate_weekly_report(args.account, config.db_path, config.obsidian_vault_path)
        except Exception as e:
            print(f"Error generating report: {e}")
        sys.exit(0)

    # 3. Main Cleanup Run
    # Run deep scan if --analytics-deep is enabled
    deep_scan_mode = args.analytics_deep
    run_analytics = args.analytics or args.analytics_deep

    try:
        summary = run_cleanup_task(
            account_name=args.account,
            email_address=email_address,
            apply_mode=args.apply,
            run_analytics=run_analytics,
            deep_scan=deep_scan_mode,
            db_path=config.db_path,
            rules_config=config.rules
        )
        
        # 4. If --ai-summary is requested along with the cleanup run, generate it at the end
        if args.ai_summary:
            print("\nGenerating weekly report...")
            generate_weekly_report(args.account, config.db_path, config.obsidian_vault_path)
            
    except Exception as e:
        print(f"Execution Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
