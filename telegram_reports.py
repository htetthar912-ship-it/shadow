"""Scheduled Telegram reports for the Shadow owner.

The report is deterministic and runs inside the Flask process. It is deliberately
rate-limited by a configurable interval and records every attempt in the database.
"""
from datetime import datetime, timedelta
import html
import os
import threading
import time

import telegram_bot


def _int_env(name, default, minimum=1):
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def reports_enabled():
    return (
        os.environ.get("TELEGRAM_REPORTS_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
        and telegram_bot.telegram_enabled()
    )


def _window_report(db, window_hours):
    from models import ChatMessage, CommerceSecurityEvent, Order, TelegramReportLog

    since = datetime.utcnow() - timedelta(hours=window_hours)
    orders = Order.query.filter(Order.created_at >= since).order_by(Order.created_at.desc()).all()
    security_events = CommerceSecurityEvent.query.filter(
        CommerceSecurityEvent.created_at >= since
    ).order_by(CommerceSecurityEvent.created_at.desc()).limit(10).all()
    bot_messages = ChatMessage.query.filter(
        ChatMessage.created_at >= since,
        ChatMessage.sender_name.in_(["Shadow Bot", "Shadow Security"]),
    ).order_by(ChatMessage.created_at.desc()).limit(5).all()
    open_orders = Order.query.filter(Order.status.notin_(["Delivered", "Cancelled"])).count()
    delivered = sum(1 for order in orders if order.status == "Delivered")
    cancelled = sum(1 for order in orders if order.status == "Cancelled")
    revenue = sum((order.total or 0) for order in orders if order.status == "Delivered")

    lines = [
        f"<b>Shadow platform report</b>",
        f"Window: last {window_hours} hour(s)",
        "",
        f"Orders: {len(orders)} | Delivered: {delivered} | Cancelled: {cancelled}",
        f"Active orders overall: {open_orders}",
        f"Delivered revenue in window: {revenue:,} Ks",
        f"Commerce security events: {len(security_events)}",
        f"Support bot replies: {len(bot_messages)}",
    ]
    if security_events:
        lines.append("\n<b>Recent security events</b>")
        for event in security_events[:5]:
            details = html.escape((event.details or "")[:160])
            lines.append(f"- {html.escape(event.kind)}: {details}")
    if bot_messages:
        lines.append("\n<b>Recent bot support activity</b>")
        for message in bot_messages[:3]:
            preview = html.escape(" ".join((message.body or "").split())[:140])
            lines.append(f"- {preview}")
    lines.append("\nOpen the Admin Panel for full customer/support chat history and audit details.")

    recipient = telegram_bot.current_chat_id()
    ok, error = telegram_bot.send_text("\n".join(lines), chat_id=recipient)
    log = TelegramReportLog(
        report_type="platform_summary", window_hours=window_hours,
        recipient=str(recipient) if recipient else None,
        status="sent" if ok else "failed", error=error,
    )
    db.session.add(log)
    db.session.commit()
    return ok


def send_report_now(db, force=False):
    if not reports_enabled():
        return False
    window_hours = _int_env("TELEGRAM_REPORT_INTERVAL_HOURS", 6)
    if not force:
        from models import TelegramReportLog
        recent_cutoff = datetime.utcnow() - timedelta(hours=window_hours)
        already_sent = TelegramReportLog.query.filter(
            TelegramReportLog.status == "sent",
            TelegramReportLog.sent_at >= recent_cutoff,
        ).first()
        if already_sent:
            return False
    return _window_report(db, window_hours)


def start_scheduler(app, db):
    """Start one lightweight in-process scheduler for this app worker."""
    if not reports_enabled():
        return None
    interval_seconds = _int_env("TELEGRAM_REPORT_INTERVAL_HOURS", 6) * 3600
    marker = "_shadow_telegram_report_scheduler_started"
    if app.extensions.get(marker):
        return None
    app.extensions[marker] = True

    def worker():
        while True:
            time.sleep(interval_seconds)
            try:
                with app.app_context():
                    send_report_now(db)
            except Exception as exc:  # scheduler must never take down the app
                print(f"[SHADOW Telegram] Scheduled report failed: {exc}")

    thread = threading.Thread(target=worker, name="shadow-telegram-report", daemon=True)
    thread.start()
    return thread
