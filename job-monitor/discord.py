"""Discord webhook embeds and rate-limit-aware delivery."""

from dataclasses import dataclass
import requests


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    error: str = ""
    retry_after_seconds: int = 60


class DiscordClient:
    def __init__(self, webhook_url: str, timeout: int, session: requests.Session | None = None):
        self.webhook_url = webhook_url
        self.timeout = timeout
        self.session = session or requests.Session()

    def _send(self, payload: dict) -> DeliveryResult:
        if not self.webhook_url:
            return DeliveryResult(False, "DISCORD_WEBHOOK_URL is not configured", 300)
        try:
            response = self.session.post(self.webhook_url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            return DeliveryResult(False, str(exc), 60)
        if 200 <= response.status_code < 300:
            return DeliveryResult(True)
        if response.status_code == 429:
            try:
                body = response.json()
            except ValueError:
                body = {}
            seconds = float(body.get("retry_after", response.headers.get("Retry-After", 1)))
            return DeliveryResult(False, "Discord rate limited the webhook", max(1, int(seconds + 0.999)))
        retry = 60 if response.status_code >= 500 else 300
        return DeliveryResult(False, f"Discord HTTP {response.status_code}: {response.text[:200]}", retry)

    def send_job(self, row) -> DeliveryResult:
        fields = [
            {"name": "Company", "value": row["company"], "inline": True},
            {"name": "Location", "value": row["location"] or "Not specified", "inline": True},
            {"name": "Source", "value": row["ats"].title(), "inline": True},
        ]
        if row["posted_at"]:
            fields.append({"name": "Posted", "value": row["posted_at"], "inline": True})
        fields.append({"name": "First detected", "value": row["first_seen_at"], "inline": False})
        return self._send({"embeds": [{"title": row["title"], "url": row["url"],
                                       "description": f"[Apply directly]({row['url']})",
                                       "color": 0x2ECC71, "fields": fields}]})

    def send_test(self) -> DeliveryResult:
        return self._send({"embeds": [{"title": "✅ Job Monitor Connected",
                                       "description": "Discord webhook is working.", "color": 0x2ECC71}]})
