from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select, delete

from app.db.session import SessionLocal
from app.models.alert import AlertRule
from app.services.data_service import get_market_overview, init_database


class AlertService:
    @staticmethod
    def list_alerts(user_id: str = "default_user") -> list[dict[str, Any]]:
        init_database()
        with SessionLocal() as session:
            stmt = select(AlertRule).where(AlertRule.user_id == user_id).order_by(AlertRule.created_at.desc())
            rules = session.scalars(stmt).all()
            return [
                {
                    "id": r.id,
                    "alert_type": r.alert_type,
                    "target_metric": r.target_metric,
                    "threshold": r.threshold,
                    "is_active": r.is_active,
                    "last_triggered_at": r.last_triggered_at.isoformat() if r.last_triggered_at else None,
                    "notes": r.notes,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rules
            ]

    @staticmethod
    def create_alert(data: dict[str, Any], user_id: str = "default_user") -> dict[str, Any]:
        init_database()
        alert_type = str(data.get("alert_type", "PRICE_ABOVE")).upper()
        threshold = float(data["threshold"])
        metric = str(data.get("target_metric", "KJPL_GOLD")).upper()
        notes = data.get("notes")

        rule = AlertRule(
            user_id=user_id,
            alert_type=alert_type,
            target_metric=metric,
            threshold=threshold,
            is_active=True,
            notes=notes,
        )

        with SessionLocal() as session:
            session.add(rule)
            session.commit()
            session.refresh(rule)
            rule_id = rule.id

        return {
            "id": rule_id,
            "alert_type": alert_type,
            "target_metric": metric,
            "threshold": threshold,
            "is_active": True,
            "notes": notes,
        }

    @staticmethod
    def delete_alert(alert_id: int, user_id: str = "default_user") -> bool:
        init_database()
        with SessionLocal() as session:
            stmt = delete(AlertRule).where(AlertRule.id == alert_id, AlertRule.user_id == user_id)
            res = session.execute(stmt)
            session.commit()
            return res.rowcount > 0

    @staticmethod
    def evaluate_alerts(user_id: str = "default_user") -> list[dict[str, Any]]:
        rules = AlertService.list_alerts(user_id=user_id)
        overview = get_market_overview()
        if overview.get("status") != "SUCCESS":
            return []

        kjpl_gold = overview["kjpl"]["gold_mjdta"]
        kjpl_silver = overview["kjpl"]["silver_mjdta"]
        us_gold = overview["market"]["xauusd"]
        premium_pct = overview["derived"]["domestic_premium_pct"]
        daily_change = abs(overview["kjpl"]["change_24h_pct"])

        notifications = []
        for r in rules:
            if not r["is_active"]:
                continue

            triggered = False
            message = ""
            current_val = 0.0

            if r["alert_type"] == "PRICE_ABOVE":
                current_val = kjpl_gold if r["target_metric"] == "KJPL_GOLD" else us_gold
                if current_val >= r["threshold"]:
                    triggered = True
                    message = f"{r['target_metric']} crossed above ₹{r['threshold']:,.0f} (Current: ₹{current_val:,.0f})"
            elif r["alert_type"] == "PRICE_BELOW":
                current_val = kjpl_gold if r["target_metric"] == "KJPL_GOLD" else us_gold
                if current_val <= r["threshold"]:
                    triggered = True
                    message = f"{r['target_metric']} crossed below ₹{r['threshold']:,.0f} (Current: ₹{current_val:,.0f})"
            elif r["alert_type"] == "PREMIUM_ABOVE":
                current_val = premium_pct
                if current_val >= r["threshold"]:
                    triggered = True
                    message = f"Domestic premium crossed above {r['threshold']}% (Current: {current_val}%)"
            elif r["alert_type"] == "DAILY_CHANGE_PCT":
                current_val = daily_change
                if current_val >= r["threshold"]:
                    triggered = True
                    message = f"24h price volatility exceeded {r['threshold']}% (Current: {current_val}%)"

            if triggered:
                notifications.append({
                    "rule_id": r["id"],
                    "alert_type": r["alert_type"],
                    "message": message,
                    "current_value": current_val,
                    "threshold": r["threshold"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        return notifications
