from autotrade.config import EventRiskConfig
from autotrade.services.event_risk import EventRiskService


def make_event_risk_config() -> EventRiskConfig:
    return EventRiskConfig(
        enabled=True,
        rss_urls=[],
        symbol_aliases={
            "AAPL": ["apple", "iphone", "tim cook"],
            "MSFT": ["microsoft", "azure"],
        },
        severity_keywords={
            "critical": ["breach", "cyberattack"],
            "high": ["lawsuit", "investigation"],
            "medium": ["delay"],
            "low": ["partnership"],
        },
        recommendation_overrides={
            "critical": "EXIT_NOW",
            "high": "SELL_OR_HEDGE",
            "medium": "WATCH_CLOSELY",
            "low": "WATCH",
        },
    )


def test_event_risk_service_classifies_manual_items() -> None:
    service = EventRiskService(make_event_risk_config())

    alerts = service.collect_alerts(
        manual_items=[
            {
                "title": "Apple hit by cyberattack",
                "summary": "A severe breach affects iphone services.",
                "source": "manual",
                "published_at": "2026-04-16T08:00:00Z",
            }
        ]
    )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.event_type == "event_risk_alert"
    assert alert.details["symbol"] == "AAPL"
    assert alert.details["severity"] == "critical"
    assert alert.details["recommendation_override"] == "EXIT_NOW"


def test_event_risk_service_ignores_unmapped_items() -> None:
    service = EventRiskService(make_event_risk_config())

    alerts = service.collect_alerts(
        manual_items=[
            {
                "title": "Unknown retailer investigation",
                "summary": "A lawsuit is pending for another company.",
                "source": "manual",
            }
        ]
    )

    assert alerts == []
