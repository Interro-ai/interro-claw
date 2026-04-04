"""
Interro-Claw — Sentry Integration

Initializes Sentry for error tracking and performance monitoring.
Logs are captured automatically; breadcrumbs track agent execution.

Sentry DSN is stored in ~/.interro-claw/.env (never in the package).
Set SENTRY_DSN="" to disable Sentry entirely.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_initialized = False


def init_sentry() -> None:
    """
    Initialize Sentry SDK if SENTRY_DSN is configured.
    Safe to call multiple times — only initializes once.
    """
    global _initialized
    if _initialized:
        return

    from interro_claw import config

    if not config.SENTRY_DSN:
        logger.debug("Sentry disabled (no SENTRY_DSN configured)")
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_logging = LoggingIntegration(
            level=logging.INFO,        # Capture INFO+ as breadcrumbs
            event_level=logging.ERROR,  # Send ERROR+ as events
        )

        sentry_sdk.init(
            dsn=config.SENTRY_DSN,
            traces_sample_rate=config.SENTRY_TRACES_SAMPLE_RATE,
            environment=config.SENTRY_ENVIRONMENT,
            release=f"interro-claw@{_get_version()}",
            integrations=[sentry_logging],
            # Don't send PII
            send_default_pii=False,
        )
        _initialized = True
        logger.info("Sentry initialized (env=%s)", config.SENTRY_ENVIRONMENT)

    except ImportError:
        logger.debug("sentry-sdk not installed — Sentry disabled")
    except Exception as exc:
        logger.warning("Sentry initialization failed: %s", exc)


def capture_exception(exc: Exception, **extra: Any) -> None:
    """Send an exception to Sentry (if initialized)."""
    if not _initialized:
        return
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            for k, v in extra.items():
                scope.set_extra(k, v)
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass  # Never let Sentry crash the main application


def set_user_context(session_id: str, project_id: str) -> None:
    """Attach session context to Sentry events."""
    if not _initialized:
        return
    try:
        import sentry_sdk
        sentry_sdk.set_user({"id": session_id})
        sentry_sdk.set_tag("project_id", project_id)
    except Exception:
        pass


def add_breadcrumb(message: str, category: str = "agent", **data: Any) -> None:
    """Add a breadcrumb trail entry for debugging."""
    if not _initialized:
        return
    try:
        import sentry_sdk
        sentry_sdk.add_breadcrumb(
            message=message,
            category=category,
            data=data,
            level="info",
        )
    except Exception:
        pass


def _get_version() -> str:
    try:
        from interro_claw import __version__
        return __version__
    except Exception:
        return "0.0.0"
