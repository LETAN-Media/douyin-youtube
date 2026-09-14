"""QR-based Douyin login session manager.

Dashboard flow: Sources -> Douyin Session -> Connect Douyin -> a real
Playwright Chromium opens douyin.com, the real QR login modal is
screenshotted and shown on the dashboard, the user scans it with the
Douyin app, the backend detects the login for real (login cookies +
dismissed login modal) and stores the Playwright storage_state
Fernet-encrypted in the database.

Nothing here is faked: without a real QR scan the session stays
``pending`` until it expires. Cookie values are never logged and never
returned by any API.
"""

import base64
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal

logger = logging.getLogger("douyin-youtube-douyin-session")

LOGIN_URL = "https://www.douyin.com/"
QR_TAB_TEXT = "扫码登录"
POLL_SECONDS = 3

DOUYIN_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

_registry_lock = threading.Lock()
_active_flows: dict[str, dict[str, Any]] = {}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _qr_png_path(session_id: str) -> Path:
    temp_dir = Path(settings.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"douyin-qr-{session_id}.png"


def _png_to_b64(path: Path) -> str | None:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return None
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


def _has_login_cookie(cookies: list[dict[str, Any]]) -> bool:
    for cookie in cookies:
        try:
            if str(cookie.get("name") or "") == "sessionid" and len(
                str(cookie.get("value") or "")
            ) > 10:
                return True
        except Exception:
            continue
    return False


def _login_modal_visible(page: Any) -> bool:
    try:
        return page.query_selector(f"text={QR_TAB_TEXT}") is not None
    except Exception:
        return False


def _read_account_name(page: Any) -> str | None:
    """Best-effort account nickname from the logged-in header."""
    selectors = [
        "header img[alt]",
        "[class*='avatar'] img[alt]",
        "header [class*='name']",
        "header [class*='nick']",
    ]
    for selector in selectors:
        try:
            el = page.query_selector(selector)
            if el is None:
                continue
            for attr in ("alt", "title"):
                try:
                    value = (el.get_attribute(attr) or "").strip()
                except Exception:
                    value = ""
                if value and "登录" not in value and len(value) < 100:
                    return value
            try:
                text = (el.inner_text() or "").strip()
            except Exception:
                text = ""
            if text and "登录" not in text and len(text) < 100:
                return text
        except Exception:
            continue
    return None


def detect_login_success(page: Any, context: Any) -> tuple[bool, str, str | None]:
    """Real login detection. Returns (ok, reason, account_name|None).

    Requires BOTH a Douyin login cookie and a dismissed login modal.
    Never returns success on QR display alone.
    """
    try:
        cookies = context.cookies()
    except Exception as exc:
        return False, f"cannot read cookies: {exc}", None

    if not _has_login_cookie(cookies):
        return False, "no login cookie yet", None

    if _login_modal_visible(page):
        return False, "login modal still visible", None

    return True, "login cookie present and login modal dismissed", _read_account_name(page)


def _capture_qr_screenshot(page: Any, path: Path) -> bool:
    """Screenshot the real QR login modal (element preferred, page fallback)."""
    try:
        modal = page.query_selector(f"text={QR_TAB_TEXT}")
        target = None
        if modal is not None:
            try:
                # Climb to the dialog container for a scannable capture.
                target = modal.evaluate_handle(
                    "e => e.closest('[role=\"dialog\"]') || "
                    "e.closest('div[class*=\"modal\"]') || e.parentElement"
                )
            except Exception:
                target = None
        if target is not None:
            try:
                target.screenshot(path=str(path))
                return True
            except Exception:
                pass
        page.screenshot(path=str(path))
        return True
    except Exception:
        logger.exception("QR screenshot failed")
        return False


def _cleanup_flow(session_id: str) -> None:
    flow = None
    with _registry_lock:
        flow = _active_flows.pop(session_id, None)
    if not flow:
        return
    for closer in (
        flow.get("page"),
        flow.get("context"),
        flow.get("browser"),
    ):
        if closer is None:
            continue
        try:
            closer.close()
        except Exception:
            pass
    stopper = flow.get("playwright")
    if stopper is not None:
        try:
            stopper.stop()
        except Exception:
            pass


def _watch_login(session_id: str, deadline: datetime) -> None:
    from app.models import DouyinSession

    while utcnow() < deadline:
        with _registry_lock:
            flow = _active_flows.get(session_id)
        if flow is None:
            return
        page = flow.get("page")
        context = flow.get("context")
        try:
            ok, reason, account_name = detect_login_success(page, context)
        except Exception as exc:
            logger.warning("Login watch error for %s: %s", session_id, exc)
            time.sleep(POLL_SECONDS)
            continue

        if ok:
            try:
                storage_state = context.storage_state()
            except Exception as exc:
                logger.warning("storage_state capture failed: %s", exc)
                time.sleep(POLL_SECONDS)
                continue
            try:
                import json

                from app.douyin_session_crypto import encrypt_storage_state

                encrypted = encrypt_storage_state(json.dumps(storage_state))
            except Exception:
                logger.exception("Session encryption failed")
                with SessionLocal.begin() as db:
                    row = db.get(DouyinSession, session_id)
                    if row is not None:
                        row.status = "failed"
                        row.last_error = "Failed to store login session securely"
                _cleanup_flow(session_id)
                return
            with SessionLocal.begin() as db:
                row = db.get(DouyinSession, session_id)
                if row is not None:
                    row.status = "connected"
                    row.storage_state_encrypted = encrypted
                    row.account_name = account_name
                    row.last_error = None
                    row.expires_at = None
                    row.last_validated_at = utcnow()
            logger.info("Douyin session %s connected (reason: %s)", session_id, reason)
            try:
                _qr_png_path(session_id).unlink(missing_ok=True)
            except OSError:
                pass
            _cleanup_flow(session_id)
            return

        # Refresh the QR capture while waiting (Douyin rotates QR codes).
        try:
            _capture_qr_screenshot(page, _qr_png_path(session_id))
        except Exception:
            pass
        time.sleep(POLL_SECONDS)

    with SessionLocal.begin() as db:
        row = db.get(DouyinSession, session_id)
        if row is not None and row.status == "pending":
            row.status = "expired"
            row.last_error = "QR login timed out waiting for a real scan"
    try:
        _qr_png_path(session_id).unlink(missing_ok=True)
    except OSError:
        pass
    _cleanup_flow(session_id)
    logger.info("Douyin session %s expired waiting for QR scan", session_id)


def start_login_flow() -> dict[str, Any]:
    """Launch a real browser, open the Douyin QR login, return QR image."""
    from playwright.sync_api import sync_playwright

    from app.models import DouyinSession

    timeout_seconds = int(getattr(settings, "douyin_login_timeout_seconds", 300) or 300)

    with _registry_lock:
        for tracked_id, flow in list(_active_flows.items()):
            if flow.get("deadline") is not None and utcnow() < flow["deadline"]:
                raise ValueError("A Douyin login flow is already in progress")
            _active_flows.pop(tracked_id, None)

    with SessionLocal.begin() as db:
        row = DouyinSession(status="pending", label="Douyin")
        db.add(row)
        db.flush()
        session_id = row.id

    browser = None
    context = None
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=DOUYIN_USER_AGENT,
            locale="zh-CN",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            raise RuntimeError(f"Douyin login page failed to load: {exc}") from exc
        page.wait_for_timeout(5000)

        try:
            page.wait_for_selector(f"text={QR_TAB_TEXT}", timeout=30000)
        except Exception as exc:
            raise RuntimeError(
                "Douyin QR login did not appear (page may be challenged)"
            ) from exc

        png_path = _qr_png_path(session_id)
        if not _capture_qr_screenshot(page, png_path):
            raise RuntimeError("Failed to capture Douyin QR login image")

        qr_b64 = _png_to_b64(png_path)
        if not qr_b64:
            raise RuntimeError("Captured QR image is empty")

        deadline = utcnow() + timedelta(seconds=timeout_seconds)
        with SessionLocal.begin() as db:
            row = db.get(DouyinSession, session_id)
            if row is not None:
                row.expires_at = deadline

        with _registry_lock:
            _active_flows[session_id] = {
                "browser": browser,
                "context": context,
                "page": page,
                "playwright": playwright,
                "deadline": deadline,
            }

        watcher = threading.Thread(
            target=_watch_login, args=(session_id, deadline), daemon=True
        )
        watcher.start()

        return {
            "session_id": session_id,
            "status": "pending",
            "qr_image_b64": qr_b64,
            "expires_at": deadline.isoformat(),
        }
    except Exception:
        with SessionLocal.begin() as db:
            row = db.get(DouyinSession, session_id)
            if row is not None:
                row.status = "failed"
                row.last_error = "Failed to open Douyin QR login"
        try:
            if context is not None:
                context.close()
        except Exception:
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            _qr_png_path(session_id).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def get_flow_status(session_id: str) -> dict[str, Any]:
    from app.models import DouyinSession

    with SessionLocal() as db:
        row = db.get(DouyinSession, session_id)
        if row is None:
            raise KeyError("Douyin session not found")
        data = {
            "session_id": row.id,
            "status": row.status,
            "account_name": row.account_name,
            "error": row.last_error,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "last_validated_at": (
                row.last_validated_at.isoformat() if row.last_validated_at else None
            ),
        }

    with _registry_lock:
        live = session_id in _active_flows
    if data["status"] == "pending" and live:
        data["qr_image_b64"] = _png_to_b64(_qr_png_path(session_id))
    else:
        data["qr_image_b64"] = None
    return data


def disconnect_session(session_id: str | None = None) -> int:
    """Delete saved session state (real disconnect). Returns rows removed."""
    from app.models import DouyinSession

    removed = 0
    with SessionLocal.begin() as db:
        if session_id:
            row = db.get(DouyinSession, session_id)
            rows = [row] if row is not None else []
        else:
            rows = list(
                db.execute(select(DouyinSession)).scalars().all()
            )
        for row in rows:
            db.delete(row)
            removed += 1
            with _registry_lock:
                _active_flows.pop(row.id, None)
            try:
                _qr_png_path(row.id).unlink(missing_ok=True)
            except OSError:
                pass
    # Close any tracked browsers for removed flows.
    return removed


def get_active_session_snapshot() -> dict[str, Any] | None:
    """Plain-data snapshot of the latest connected session (no ORM detach)."""
    from app.models import DouyinSession

    with SessionLocal() as db:
        row = (
            db.execute(
                select(DouyinSession)
                .where(DouyinSession.status == "connected")
                .order_by(DouyinSession.updated_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        )
        if row is None:
            return None
        return {
            "id": row.id,
            "account_name": row.account_name,
            "last_validated_at": (
                row.last_validated_at.isoformat() if row.last_validated_at else None
            ),
            "has_state": bool(row.storage_state_encrypted),
        }


def load_saved_session_cookies() -> list[dict[str, Any]]:
    """Playwright cookies from the saved QR login session, or [].

    Never raises for missing sessions; decryption problems are logged
    without values and yield [].
    """
    import json

    from app.models import DouyinSession

    with SessionLocal() as db:
        row = (
            db.execute(
                select(DouyinSession)
                .where(DouyinSession.status == "connected")
                .order_by(DouyinSession.updated_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        )
        encrypted = row.storage_state_encrypted if row is not None else None

    if not encrypted:
        return []
    try:
        from app.douyin_session_crypto import decrypt_storage_state

        raw = decrypt_storage_state(encrypted)
        state = json.loads(raw)
    except Exception:
        logger.warning("Saved Douyin session cannot be decrypted/parsed")
        return []
    cookies = state.get("cookies") if isinstance(state, dict) else None
    if not isinstance(cookies, list):
        return []
    out: list[dict[str, Any]] = []
    for cookie in cookies:
        if not isinstance(cookie, dict) or not cookie.get("name"):
            continue
        out.append(cookie)
    return out


def validate_saved_session() -> dict[str, Any]:
    """Check the saved session against the real Douyin homepage.

    Logged-out visitors get the QR login modal; a valid session does not.
    No video inventory is collected here.
    """
    from playwright.sync_api import sync_playwright

    from app.models import DouyinSession

    cookies = load_saved_session_cookies()
    if not cookies:
        return {
            "valid": False,
            "account_name": None,
            "error": "No Douyin session saved (Connect Douyin first)",
            "last_validated_at": utcnow().isoformat(),
        }

    browser = None
    context = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                user_agent=DOUYIN_USER_AGENT,
                locale="zh-CN",
                viewport={"width": 1366, "height": 900},
            )
            try:
                context.add_cookies(cookies)
            except Exception as exc:
                return {
                    "valid": False,
                    "account_name": None,
                    "error": f"Saved session cookies rejected: {exc}",
                    "last_validated_at": utcnow().isoformat(),
                }
            page = context.new_page()
            try:
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
            except Exception as exc:
                return {
                    "valid": False,
                    "account_name": None,
                    "error": f"Douyin page failed to load: {exc}",
                    "last_validated_at": utcnow().isoformat(),
                }
            page.wait_for_timeout(5000)
            try:
                content = page.content()
            except Exception:
                content = ""
            modal_visible = _login_modal_visible(page)
            account_name = None if modal_visible else _read_account_name(page)
            try:
                page.close()
            except Exception:
                pass

            if modal_visible or QR_TAB_TEXT in (content or ""):
                with SessionLocal.begin() as db:
                    snapshot = get_active_session_snapshot()
                    if snapshot is not None:
                        fresh = db.get(DouyinSession, snapshot["id"])
                        if fresh is not None:
                            fresh.status = "expired"
                            fresh.last_error = "Douyin session expired (login required again)"
                            fresh.last_validated_at = utcnow()
                return {
                    "valid": False,
                    "account_name": None,
                    "error": "Douyin session expired",
                    "last_validated_at": utcnow().isoformat(),
                }

            with SessionLocal.begin() as db:
                snapshot = get_active_session_snapshot()
                if snapshot is not None:
                    fresh = db.get(DouyinSession, snapshot["id"])
                    if fresh is not None:
                        fresh.last_validated_at = utcnow()
                        fresh.last_error = None
                        if account_name:
                            fresh.account_name = account_name
            return {
                "valid": True,
                "account_name": account_name,
                "error": None,
                "last_validated_at": utcnow().isoformat(),
            }
    finally:
        try:
            if context is not None:
                context.close()
        except Exception:
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass


def get_aggregate_status() -> dict[str, Any]:
    snapshot = get_active_session_snapshot()
    if snapshot is None:
        return {
            "connected": False,
            "valid": False,
            "account_name": None,
            "last_validated_at": None,
        }
    return {
        "connected": True,
        "valid": True,
        "account_name": snapshot["account_name"],
        "last_validated_at": snapshot["last_validated_at"],
    }
