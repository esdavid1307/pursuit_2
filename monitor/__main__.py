"""Command-line entry point for the personal ATS job monitor."""

from argparse import ArgumentParser
import sys

from monitor.config import load_settings
from monitor.database import Database
from monitor.discord import DiscordClient
from monitor.scheduler import Scheduler


def main() -> int:
    parser = ArgumentParser(description="Monitor ATS boards and alert new internship postings.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--once", action="store_true", help="Check due boards once and exit.")
    modes.add_argument("--validate", action="store_true", help="Fetch every configured board without alerts.")
    modes.add_argument("--test-discord", action="store_true", help="Send a Discord connection test.")
    args = parser.parse_args()

    try:
        settings = load_settings()
    except (ValueError, OSError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    discord = DiscordClient(settings.webhook_url, settings.request_timeout_seconds)
    usa_discord = (DiscordClient(settings.usa_webhook_url, settings.request_timeout_seconds)
                   if settings.usa_webhook_url else None)
    if args.test_discord:
        failures = 0
        for label, client in (("canada", discord), ("usa", usa_discord)):
            if client is None:
                continue
            result = client.send_test()
            if result.success:
                print(f"Discord test sent successfully [{label}].")
            else:
                print(f"Discord test failed [{label}]: {result.error}", file=sys.stderr)
                failures += 1
        return 1 if failures else 0

    if not settings.companies_json.is_file():
        print(f"Companies JSON not found: {settings.companies_json}", file=sys.stderr)
        return 2

    db = Database(settings.database_path)
    try:
        counts = db.import_targets(settings.companies_json,
                                   settings.high_priority_interval_minutes,
                                   settings.normal_priority_interval_minutes)
        disabled = db.connection.execute("SELECT COUNT(*) FROM monitor_targets WHERE enabled=0").fetchone()[0]
        print(f"Targets:\nHigh priority: {counts['high']}\nNormal priority: {counts['normal']}\nDisabled: {disabled}\nUnsupported: {counts['unsupported']}")
        scheduler = Scheduler(db, settings, discord, usa_discord)
        if args.validate:
            scheduler.validate()
        elif args.once:
            scheduler.run_due_scan()
        else:
            scheduler.run_forever()
        return 0
    except KeyboardInterrupt:
        print("Monitor stopped.")
        return 130
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
