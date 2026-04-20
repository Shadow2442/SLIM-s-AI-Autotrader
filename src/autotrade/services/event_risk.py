from __future__ import annotations

from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx

from autotrade.config import EventRiskConfig
from autotrade.models import RunEvent


class EventRiskService:
    def __init__(self, config: EventRiskConfig, client: httpx.Client | None = None) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=10.0)

    def collect_alerts(self, manual_items: list[dict] | None = None) -> list[RunEvent]:
        if not self._config.enabled:
            return []
        items = list(manual_items or [])
        alerts: list[RunEvent] = []
        for url in self._config.rss_urls:
            try:
                items.extend(self._fetch_rss_items(url))
            except (httpx.HTTPError, ElementTree.ParseError, ValueError) as exc:
                alerts.append(
                    RunEvent(
                        event_type="event_risk_feed_error",
                        message=f"Failed to fetch event risk feed: {url}",
                        details={"source": url, "error": str(exc)},
                    )
                )

        for item in items:
            title = str(item.get("title", ""))
            summary = str(item.get("summary", ""))
            combined = f"{title} {summary}".lower()
            symbol = self._match_symbol(combined)
            if symbol is None:
                continue
            severity = self._classify_severity(combined)
            if severity is None:
                continue
            alerts.append(
                RunEvent(
                    event_type="event_risk_alert",
                    message=title or "Event risk detected.",
                    details={
                        "symbol": symbol,
                        "severity": severity,
                        "source": item.get("source", "unknown"),
                        "summary": summary,
                        "recommendation_override": self._config.recommendation_overrides.get(severity, "WATCH"),
                        "published_at": item.get("published_at", ""),
                    },
                )
            )
        return alerts

    def _fetch_rss_items(self, url: str) -> list[dict]:
        response = self._client.get(url)
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        items: list[dict] = []
        for item in root.findall(".//item"):
            title = item.findtext("title", default="")
            summary = item.findtext("description", default="")
            pub_date = item.findtext("pubDate", default="")
            published_at = ""
            if pub_date:
                try:
                    published_at = parsedate_to_datetime(pub_date).isoformat()
                except (TypeError, ValueError):
                    published_at = pub_date
            items.append(
                {
                    "title": title,
                    "summary": summary,
                    "source": url,
                    "published_at": published_at,
                }
            )
        return items

    def _match_symbol(self, text: str) -> str | None:
        for symbol, aliases in self._config.symbol_aliases.items():
            if symbol.lower() in text:
                return symbol
            for alias in aliases:
                if alias.lower() in text:
                    return symbol
        return None

    def _classify_severity(self, text: str) -> str | None:
        for severity in ("critical", "high", "medium", "low"):
            for keyword in self._config.severity_keywords.get(severity, []):
                if keyword.lower() in text:
                    return severity
        return None
