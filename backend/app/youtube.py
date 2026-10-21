import hashlib
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting, Destination, OAuthState, Pipeline


logger = logging.getLogger("douyin-youtube-youtube")


#: Required to read comments and post replies (comments.insert).
#: Channels authorised before this scope was added must reconnect.
YOUTUBE_FORCE_SSL_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"

#: Required to read OWNED channel analytics (YouTube Analytics API).
#: No monetary/revenue scope is requested.
YOUTUBE_ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    YOUTUBE_FORCE_SSL_SCOPE,
    YOUTUBE_ANALYTICS_READONLY_SCOPE,
]

GLOBAL_TOKEN_SETTING_KEY = "youtube_credentials"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OAuthFlowError(RuntimeError):
    """A user-actionable OAuth failure with a stable, safe error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def oauth_state_fingerprint(state: str | None) -> str:
    """Return a short non-reversible fingerprint; never log the raw state."""
    if not state:
        return "none"

    return hashlib.sha256(state.encode("utf-8")).hexdigest()[:12]


def _flow_session_state(flow: Any) -> str | None:
    session = getattr(flow, "oauth2session", None)
    if session is None:
        return None

    value = getattr(session, "state", None)
    if value is None:
        value = getattr(session, "_state", None)

    return value


def validate_google_config() -> None:
    if not settings.google_client_id:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID chưa được cấu hình"
        )

    if not settings.google_client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_SECRET chưa được cấu hình"
        )


def client_config() -> dict:
    validate_google_config()

    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": (
                "https://accounts.google.com/o/oauth2/v2/auth"
            ),
            "token_uri": (
                "https://oauth2.googleapis.com/token"
            ),
            "redirect_uris": [
                public_callback_url()
            ],
        }
    }


def save_setting(
    db: Session,
    key: str,
    value: str,
) -> None:
    row = db.get(
        AppSetting,
        key,
    )

    if row is None:
        row = AppSetting(
            key=key,
            value=value,
        )
        db.add(row)
    else:
        row.value = value

    db.commit()


def read_setting(
    db: Session,
    key: str,
) -> str | None:
    row = db.get(
        AppSetting,
        key,
    )

    if row is None:
        return None

    return row.value


def public_callback_url() -> str:
    """The ONE registered redirect_uri: PUBLIC_BASE_URL + /auth/youtube/callback.

    It MUST be https: oauthlib rejects insecure transports and Google only
    permits http for loopback redirect URIs. We fail loudly (never set
    OAUTHLIB_INSECURE_TRANSPORT) when a deployment is misconfigured.
    """
    callback = settings.youtube_callback_url
    parsed = urlsplit(callback)
    if parsed.scheme.lower() != "https":
        raise RuntimeError(
            "PUBLIC_BASE_URL phải là HTTPS để làm OAuth redirect URI "
            f"(đang nhận {parsed.scheme}://{parsed.netloc}). "
            "Đặt PUBLIC_BASE_URL=https://<public-domain> và khai báo "
            f"{callback} trong Google Cloud Console OAuth client."
        )
    return callback


def canonical_authorization_response(url_or_query: str) -> str:
    """Rebuild the OAuth authorization response on the public https callback.

    The reverse proxy (Northflank) terminates TLS, so the ASGI request reaches
    the app as ``http://<internal>:8000/auth/youtube/callback`` and
    ``str(request.url)`` is http -> oauthlib raises InsecureTransportError.
    Only the query (code/state/scope) is meaningful; scheme+host are always
    the configured public callback, exactly matching flow.redirect_uri.
    """
    raw = (url_or_query or "").strip()
    if not raw:
        raise RuntimeError("Thiếu authorization_response từ Google")

    query = urlsplit(raw).query if "://" in raw else raw.lstrip("?")
    callback = public_callback_url()

    return f"{callback}?{query}" if query else callback


def create_oauth_url(
    db: Session,
    pipeline_id: str | None = None,
    destination_id: str | None = None,
    workspace_id: str | None = None,
    initiated_by_user_id: str | None = None,
) -> str:
    validate_google_config()
    oauth_client_config = client_config()
    callback_url = public_callback_url()

    state = secrets.token_urlsafe(48)
    state_fp = oauth_state_fingerprint(state)

    resolved_destination_id = destination_id

    if not resolved_destination_id and pipeline_id:
        destination = db.execute(
            select(Destination)
            .where(Destination.pipeline_id == pipeline_id)
            .where(Destination.platform == "youtube")
            .limit(1)
        ).scalar_one_or_none()

        if destination:
            resolved_destination_id = destination.id

    # Tenant binding (Phase 9): derive the workspace from the destination
    # (or pipeline) when the caller did not pass one explicitly, so the
    # callback can verify credentials land ONLY in the intended workspace.
    bound_workspace_id = workspace_id
    if not bound_workspace_id and resolved_destination_id:
        dest_row = db.get(Destination, resolved_destination_id)
        if dest_row is not None:
            bound_workspace_id = dest_row.workspace_id or (
                db.get(Pipeline, dest_row.pipeline_id).workspace_id
                if dest_row.pipeline_id and db.get(Pipeline, dest_row.pipeline_id)
                else None
            )
    if not bound_workspace_id and pipeline_id:
        pipe_row = db.get(Pipeline, pipeline_id)
        if pipe_row is not None:
            bound_workspace_id = pipe_row.workspace_id

    state_row = OAuthState(
        state=state,
        pipeline_id=pipeline_id,
        destination_id=resolved_destination_id,
        workspace_id=bound_workspace_id,
        initiated_by_user_id=initiated_by_user_id,
        expires_at=(
            utcnow()
            + timedelta(minutes=15)
        ),
    )
    db.add(state_row)
    db.commit()

    try:
        flow = Flow.from_client_config(
            oauth_client_config,
            scopes=SCOPES,
            state=state,
            autogenerate_code_verifier=False,
        )

        flow.redirect_uri = callback_url

        authorization_url, returned_state = (
            flow.authorization_url(
                access_type="offline",
                include_granted_scopes="true",
                prompt="consent select_account",
            )
        )
    except Exception:
        db.delete(state_row)
        db.commit()
        logger.exception(
            "OAuth URL generation failed state_fp=%s destination=%s pipeline=%s",
            state_fp,
            resolved_destination_id,
            pipeline_id,
        )
        raise

    internal_state = _flow_session_state(flow)
    if returned_state != state or internal_state != state:
        db.delete(state_row)
        db.commit()
        logger.error(
            "OAuth state generation mismatch state_fp=%s returned_fp=%s "
            "internal_fp=%s destination=%s pipeline=%s",
            state_fp,
            oauth_state_fingerprint(returned_state),
            oauth_state_fingerprint(internal_state),
            resolved_destination_id,
            pipeline_id,
        )
        raise OAuthFlowError(
            "oauth_state_generation_failed",
            "Không tạo được phiên OAuth an toàn. Vui lòng thử kết nối lại.",
        )

    logger.info(
        "OAuth URL created state_fp=%s destination=%s pipeline=%s "
        "workspace=%s expires_at=%s",
        state_fp,
        resolved_destination_id,
        pipeline_id,
        bound_workspace_id,
        state_row.expires_at.isoformat() if state_row.expires_at else None,
    )

    return authorization_url


def complete_oauth(
    db: Session,
    state: str,
    code: str,
    pipeline_id: str | None = None,
    destination_id: str | None = None,
) -> dict:
    state_fp = oauth_state_fingerprint(state)

    if not (state or "").strip():
        logger.warning(
            "OAuth callback rejected code=oauth_state_invalid reason=missing"
        )
        raise OAuthFlowError(
            "oauth_state_invalid",
            "Thiếu OAuth state. Vui lòng bấm Kết nối lại từ dashboard.",
        )

    if not (code or "").strip():
        logger.warning(
            "OAuth callback rejected code=oauth_callback_missing_code state_fp=%s",
            state_fp,
        )
        raise OAuthFlowError(
            "oauth_callback_missing_code",
            "Google không trả về authorization code. Vui lòng kết nối lại.",
        )

    state_row = db.get(
        OAuthState,
        state,
    )

    if state_row is None:
        logger.warning(
            "OAuth callback rejected code=oauth_state_invalid state_fp=%s",
            state_fp,
        )
        raise OAuthFlowError(
            "oauth_state_invalid",
            "Phiên OAuth không tồn tại hoặc đã được sử dụng. "
            "Vui lòng bấm Kết nối lại để tạo phiên mới.",
        )

    expires_at = state_row.expires_at

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(
            tzinfo=timezone.utc
        )

    if expires_at < utcnow():
        db.delete(state_row)
        db.commit()
        logger.warning(
            "OAuth callback rejected code=oauth_state_expired state_fp=%s "
            "expires_at=%s",
            state_fp,
            expires_at.isoformat(),
        )
        raise OAuthFlowError(
            "oauth_state_expired",
            "Phiên OAuth đã hết hạn. Vui lòng bấm Kết nối lại.",
        )

    # The OAuth state is the single source of truth for the target. Never
    # accept a callback query that tries to attach the token to a different
    # destination/pipeline than the one the signed flow was created for.
    if destination_id and str(destination_id) != str(
        state_row.destination_id or ""
    ):
        db.delete(state_row)
        db.commit()
        logger.warning(
            "OAuth callback rejected code=oauth_state_destination_mismatch "
            "state_fp=%s expected_destination=%s callback_destination=%s",
            state_fp,
            state_row.destination_id,
            destination_id,
        )
        raise OAuthFlowError(
            "oauth_state_destination_mismatch",
            "Phiên OAuth không khớp với channel đích. "
            "Không có thay đổi nào được lưu. Vui lòng Kết nối lại.",
        )

    if pipeline_id and str(pipeline_id) != str(
        state_row.pipeline_id or ""
    ):
        db.delete(state_row)
        db.commit()
        logger.warning(
            "OAuth callback rejected code=oauth_state_pipeline_mismatch "
            "state_fp=%s expected_pipeline=%s callback_pipeline=%s",
            state_fp,
            state_row.pipeline_id,
            pipeline_id,
        )
        raise OAuthFlowError(
            "oauth_state_pipeline_mismatch",
            "Phiên OAuth không khớp với pipeline đích. "
            "Không có thay đổi nào được lưu. Vui lòng Kết nối lại.",
        )

    resolved_destination_id = state_row.destination_id
    resolved_pipeline_id = state_row.pipeline_id

    # Tenant binding (Phase 9): a workspace-bound flow may ONLY attach
    # credentials to a destination/pipeline inside that same workspace.
    # Never fall back to global credentials and never cross tenants.
    bound_ws = getattr(state_row, "workspace_id", None)
    if bound_ws:
        if resolved_destination_id:
            _dest = db.get(Destination, resolved_destination_id)
            if _dest is None:
                db.delete(state_row)
                db.commit()
                raise OAuthFlowError(
                    "oauth_destination_not_found",
                    "Destination đích không còn tồn tại.",
                )
            _dest_ws = _dest.workspace_id
            if not _dest_ws and _dest.pipeline_id:
                _pipe = db.get(Pipeline, _dest.pipeline_id)
                _dest_ws = _pipe.workspace_id if _pipe else None
            if str(_dest_ws or "") != str(bound_ws):
                db.delete(state_row)
                db.commit()
                logger.warning(
                    "OAuth callback rejected code=oauth_tenant_mismatch "
                    "state_fp=%s destination=%s",
                    state_fp,
                    resolved_destination_id,
                )
                raise OAuthFlowError(
                    "oauth_tenant_mismatch",
                    "Phiên OAuth không thuộc workspace của channel này. "
                    "Không có thay đổi nào được lưu.",
                )
        elif resolved_pipeline_id:
            _pipe = db.get(Pipeline, resolved_pipeline_id)
            if _pipe is None:
                db.delete(state_row)
                db.commit()
                raise OAuthFlowError(
                    "oauth_pipeline_not_found",
                    "Pipeline đích không còn tồn tại.",
                )
            if str(_pipe.workspace_id or "") != str(bound_ws):
                db.delete(state_row)
                db.commit()
                logger.warning(
                    "OAuth callback rejected code=oauth_tenant_mismatch "
                    "state_fp=%s pipeline=%s",
                    state_fp,
                    resolved_pipeline_id,
                )
                raise OAuthFlowError(
                    "oauth_tenant_mismatch",
                    "Phiên OAuth không thuộc workspace của pipeline này. "
                    "Không có thay đổi nào được lưu.",
                )
        else:
            db.delete(state_row)
            db.commit()
            raise OAuthFlowError(
                "oauth_state_invalid_target",
                "Phiên OAuth thiếu channel/pipeline đích. "
                "Vui lòng Kết nối lại từ dashboard.",
            )

    old_refresh_token = None
    destination = None
    pipeline = None

    if resolved_destination_id:
        destination = db.get(
            Destination,
            resolved_destination_id,
        )
        if destination is not None and destination.credentials:
            try:
                old_refresh_token = (
                    json.loads(destination.credentials)
                    .get("refresh_token")
                )
            except Exception:
                old_refresh_token = None
    elif resolved_pipeline_id:
        pipeline = db.get(
            Pipeline,
            resolved_pipeline_id,
        )
        if pipeline is not None and pipeline.youtube_credentials:
            try:
                old_refresh_token = (
                    json.loads(pipeline.youtube_credentials)
                    .get("refresh_token")
                )
            except Exception:
                old_refresh_token = None
    else:
        existing = read_setting(
            db,
            GLOBAL_TOKEN_SETTING_KEY,
        )

        if existing:
            try:
                old_refresh_token = (
                    json.loads(existing)
                    .get("refresh_token")
                )
            except Exception:
                old_refresh_token = None

    try:
        oauth_client_config = client_config()
        callback_url = public_callback_url()
        flow = Flow.from_client_config(
            oauth_client_config,
            scopes=SCOPES,
            state=state,
            autogenerate_code_verifier=False,
        )
        flow.redirect_uri = callback_url
    except Exception as exc:
        logger.exception(
            "OAuth setup failed state_fp=%s destination=%s pipeline=%s",
            state_fp,
            resolved_destination_id,
            resolved_pipeline_id,
        )
        raise OAuthFlowError(
            "oauth_config_invalid",
            "Cấu hình OAuth phía server chưa hợp lệ. "
            "Vui lòng kiểm tra HTTPS/PUBLIC_BASE_URL và thử lại.",
        ) from exc

    internal_state = _flow_session_state(flow)
    if internal_state != state:
        db.delete(state_row)
        db.commit()
        logger.error(
            "OAuth state internal mismatch state_fp=%s internal_fp=%s "
            "destination=%s pipeline=%s",
            state_fp,
            oauth_state_fingerprint(internal_state),
            resolved_destination_id,
            resolved_pipeline_id,
        )
        raise OAuthFlowError(
            "oauth_state_internal_mismatch",
            "Không xác thực được phiên OAuth. "
            "Không có thay đổi nào được lưu. Vui lòng Kết nối lại.",
        )

    # Consume the state atomically BEFORE the network exchange. This prevents
    # duplicate/concurrent callbacks from exchanging the same code twice, and
    # makes a replay fail closed instead of reaching Google.
    consumed = db.execute(
        delete(OAuthState).where(
            OAuthState.state == state
        )
    )
    db.commit()

    if consumed.rowcount == 0:
        logger.warning(
            "OAuth callback rejected code=oauth_state_reused state_fp=%s",
            state_fp,
        )
        raise OAuthFlowError(
            "oauth_state_reused",
            "Phiên OAuth đã được sử dụng bởi một callback khác. "
            "Vui lòng bấm Kết nối lại.",
        )

    logger.info(
        "OAuth callback accepted state_fp=%s destination=%s pipeline=%s",
        state_fp,
        resolved_destination_id,
        resolved_pipeline_id,
    )

    try:
        # Validate state ourselves from the single-use DB row, then exchange
        # only the code. Do NOT let oauthlib re-check a reconstructed
        # authorization_response (that was the source of mismatching_state).
        flow.fetch_token(code=code)
    except Exception as exc:
        error_text = str(exc).lower()

        if "invalid_grant" in error_text:
            error_code = "oauth_invalid_grant"
            message = (
                "Google từ chối authorization code (invalid_grant). "
                "Code có thể đã hết hạn hoặc đã được sử dụng. "
                "Vui lòng bấm Kết nối lại."
            )
        elif "access_denied" in error_text:
            error_code = "oauth_access_denied"
            message = (
                "Bạn đã từ chối cấp quyền cho ứng dụng. "
                "Vui lòng Kết nối lại và chấp nhận các quyền cần thiết."
            )
        elif "insufficient" in error_text or "forbidden" in error_text:
            error_code = "oauth_permission_denied"
            message = (
                "Tài khoản Google không có đủ quyền cho kênh này. "
                "Vui lòng kiểm tra quyền YouTube và Kết nối lại."
            )
        else:
            error_code = "oauth_exchange_failed"
            message = (
                "Không đổi được authorization code thành token. "
                "Vui lòng thử Kết nối lại; nếu vẫn lỗi, kiểm tra log backend."
            )

        logger.warning(
            "OAuth token exchange failed state_fp=%s destination=%s "
            "pipeline=%s code=%s error_type=%s",
            state_fp,
            resolved_destination_id,
            resolved_pipeline_id,
            error_code,
            type(exc).__name__,
        )
        raise OAuthFlowError(error_code, message) from exc

    credentials = getattr(flow, "credentials", None)
    if credentials is None or not getattr(credentials, "token", None):
        logger.warning(
            "OAuth token exchange returned no access token state_fp=%s "
            "destination=%s pipeline=%s",
            state_fp,
            resolved_destination_id,
            resolved_pipeline_id,
        )
        raise OAuthFlowError(
            "oauth_exchange_failed",
            "Google không trả về access token. Vui lòng Kết nối lại.",
        )

    refresh_token = (
        credentials.refresh_token
        or old_refresh_token
    )

    if not refresh_token:
        logger.warning(
            "OAuth callback rejected code=oauth_missing_refresh_token "
            "state_fp=%s destination=%s pipeline=%s",
            state_fp,
            resolved_destination_id,
            resolved_pipeline_id,
        )
        raise OAuthFlowError(
            "oauth_missing_refresh_token",
            "Google không trả về refresh token nên kênh sẽ không tự "
            "upload lâu dài. Vui lòng Kết nối lại và chấp nhận quyền offline.",
        )

    data = {
        "token": credentials.token,
        "refresh_token": refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": (
            credentials.client_secret
        ),
        "scopes": list(
            credentials.scopes or SCOPES
        ),
    }

    try:
        youtube = build(
            "youtube",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )

        result = youtube.channels().list(
            part="id,snippet",
            mine=True,
        ).execute()
    except HttpError as exc:
        status = getattr(
            getattr(exc, "resp", None),
            "status",
            None,
        )
        logger.warning(
            "YouTube channel lookup failed state_fp=%s destination=%s "
            "pipeline=%s http_status=%s",
            state_fp,
            resolved_destination_id,
            resolved_pipeline_id,
            status,
        )
        if status == 403:
            raise OAuthFlowError(
                "oauth_permission_denied",
                "Tài khoản Google không có quyền đọc kênh YouTube. "
                "Vui lòng kiểm tra quyền và Kết nối lại.",
            ) from exc

        raise OAuthFlowError(
            "oauth_channel_lookup_failed",
            "Không kiểm tra được kênh YouTube sau khi kết nối. "
            "Token cũ (nếu có) vẫn được giữ nguyên. Vui lòng thử lại.",
        ) from exc
    except Exception as exc:
        logger.exception(
            "YouTube channel lookup crashed state_fp=%s destination=%s "
            "pipeline=%s",
            state_fp,
            resolved_destination_id,
            resolved_pipeline_id,
        )
        raise OAuthFlowError(
            "oauth_channel_lookup_failed",
            "Không kiểm tra được kênh YouTube sau khi kết nối. "
            "Token cũ (nếu có) vẫn được giữ nguyên. Vui lòng thử lại.",
        ) from exc

    channels = result.get("items", []) or []

    if not channels:
        logger.warning(
            "OAuth callback rejected code=oauth_channel_not_found state_fp=%s "
            "destination=%s pipeline=%s",
            state_fp,
            resolved_destination_id,
            resolved_pipeline_id,
        )
        raise OAuthFlowError(
            "oauth_channel_not_found",
            "Không tìm thấy kênh YouTube nào trên tài khoản Google này.",
        )

    channel = channels[0]
    channel_id = channel["id"]
    channel_title = channel["snippet"]["title"]
    thumbnails = channel["snippet"].get("thumbnails", {})
    avatar_url = (
        thumbnails.get("default", {}).get("url")
        or thumbnails.get("medium", {}).get("url")
        or thumbnails.get("high", {}).get("url")
    )
    if avatar_url:
        data["avatar_url"] = avatar_url
    token_json = json.dumps(data)

    try:
        if resolved_destination_id:
            if destination is None:
                destination = db.get(
                    Destination,
                    resolved_destination_id,
                )
                if destination is None:
                    raise OAuthFlowError(
                        "oauth_destination_not_found",
                        "Destination đích không còn tồn tại.",
                    )

            destination.credentials = token_json
            destination.external_account_id = channel_id
            destination.external_account_name = channel_title
            destination.connected = True
            db.commit()
            logger.info(
                "Saved YouTube OAuth for destination=%s state_fp=%s",
                resolved_destination_id,
                state_fp,
            )
        elif resolved_pipeline_id:
            if pipeline is None:
                pipeline = db.get(
                    Pipeline,
                    resolved_pipeline_id,
                )
                if pipeline is None:
                    raise OAuthFlowError(
                        "oauth_pipeline_not_found",
                        "Pipeline đích không còn tồn tại.",
                    )

            pipeline.youtube_credentials = token_json
            pipeline.youtube_channel_id = channel_id
            pipeline.youtube_channel_title = channel_title
            pipeline.youtube_connected = True
            db.commit()
            logger.info(
                "Saved YouTube OAuth for pipeline=%s state_fp=%s",
                resolved_pipeline_id,
                state_fp,
            )
        else:
            save_setting(
                db,
                GLOBAL_TOKEN_SETTING_KEY,
                token_json,
            )
            logger.info(
                "Saved YouTube OAuth globally state_fp=%s",
                state_fp,
            )
    except OAuthFlowError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception(
            "OAuth token save failed state_fp=%s destination=%s pipeline=%s",
            state_fp,
            resolved_destination_id,
            resolved_pipeline_id,
        )
        raise OAuthFlowError(
            "oauth_save_failed",
            "Không lưu được token YouTube vào destination. "
            "Token cũ (nếu có) vẫn được giữ nguyên. Vui lòng thử lại.",
        ) from exc

    return {
        "destination_id": resolved_destination_id,
        "pipeline_id": resolved_pipeline_id,
        "channel_id": channel_id,
    }


def _load_from_json(
    raw: str | None,
) -> Credentials:
    if not raw:
        raise RuntimeError(
            "YouTube chưa được kết nối OAuth"
        )

    data = json.loads(raw)

    credentials = Credentials(
        token=data.get("token"),
        refresh_token=data.get(
            "refresh_token"
        ),
        token_uri=data.get(
            "token_uri"
        ),
        client_id=data.get(
            "client_id"
        ),
        client_secret=data.get(
            "client_secret"
        ),
        scopes=data.get(
            "scopes"
        ),
    )

    if credentials.expired:
        if not credentials.refresh_token:
            raise RuntimeError(
                "YouTube refresh token không tồn tại"
            )

        try:
            credentials.refresh(
                GoogleRequest()
            )
        except Exception as exc:
            if "invalid_grant" in str(exc).lower():
                raise RuntimeError(
                    "YouTube refresh token đã bị thu hồi hoặc hết hạn "
                    "(invalid_grant). Vui lòng bấm Reconnect OAuth để "
                    "kết nối lại kênh."
                ) from exc
            raise

        data["token"] = (
            credentials.token
        )

    return credentials


def load_credentials(
    db: Session,
    pipeline_id: str | None = None,
    destination_id: str | None = None,
) -> Credentials:
    # Destination OAuth isolation: when a destination is specified, its own
    # credentials MUST be used. Never fall back to another destination,
    # pipeline-global or app-global token (would upload YouTube A with B's
    # credentials).
    if destination_id:
        destination = db.get(Destination, destination_id)
        raw = None
        if destination is not None:
            raw = destination.credentials
        if not raw:
            raise RuntimeError(
                "Destination YouTube chưa được kết nối OAuth "
                f"(destination_id={destination_id})"
            )
        credentials = _load_from_json(raw)
        # Persist refreshed access token back to this destination only.
        try:
            data = json.loads(raw)
            if credentials.token and data.get("token") != credentials.token:
                data["token"] = credentials.token
                destination.credentials = json.dumps(data)
                db.commit()
        except Exception:
            pass
        return credentials

    raw = None

    if pipeline_id:
        pipeline = db.get(Pipeline, pipeline_id)
        if pipeline is not None and pipeline.youtube_credentials:
            raw = pipeline.youtube_credentials

    if not raw:
        raw = read_setting(
            db,
            GLOBAL_TOKEN_SETTING_KEY,
        )

    return _load_from_json(raw)


def destination_oauth_ready(
    destination: Destination | None,
) -> tuple[bool, str | None]:
    """Check a Destination is ready for YouTube scheduling/upload.

    Returns (ready, reason). Reasons use scheduler reason codes.
    """
    if destination is None:
        return False, "DESTINATION_NOT_FOUND"
    if not destination.enabled:
        return False, "SCHEDULER_DISABLED"
    if (destination.platform or "").lower() != "youtube":
        return False, "UNSUPPORTED_PLATFORM"
    if not destination.connected:
        return False, "DESTINATION_NOT_CONNECTED"
    if not destination.credentials:
        return False, "DESTINATION_NOT_CONNECTED"
    try:
        data = json.loads(destination.credentials)
    except Exception:
        return False, "DESTINATION_NOT_CONNECTED"
    if not data.get("refresh_token"):
        return False, "DESTINATION_NOT_CONNECTED"
    return True, None


def granted_scopes(raw_credentials: str | None) -> list[str]:
    """Scopes saved with a destination's OAuth token (never a secret)."""
    if not raw_credentials:
        return []
    try:
        data = json.loads(raw_credentials)
    except Exception:
        return []
    scopes = data.get("scopes")
    if not isinstance(scopes, list):
        return []
    return [str(item) for item in scopes if item]


def destination_comment_scope_status(
    destination: Destination | None,
) -> tuple[bool, str | None]:
    """Can this destination read/reply to comments?

    Returns (ok, reason). A channel authorised before force-ssl was added
    MUST reconnect: an old refresh token does not silently gain the scope.
    """
    if destination is None:
        return False, "DESTINATION_NOT_FOUND"
    if not destination.credentials:
        return False, "YOUTUBE_REAUTH_REQUIRED"
    scopes = granted_scopes(destination.credentials)
    if not scopes:
        # Token predates scope recording: assume it lacks force-ssl rather
        # than risk a 403 mid-reply.
        return False, "YOUTUBE_SCOPE_MISSING"
    if YOUTUBE_FORCE_SSL_SCOPE in scopes:
        return True, None
    if any(str(s).endswith("youtube.force-ssl") for s in scopes):
        return True, None
    return False, "YOUTUBE_SCOPE_MISSING"


def destination_analytics_scope_status(
    destination: Destination | None,
) -> tuple[bool, str | None]:
    """Can this destination read OWNED channel analytics?

    Returns (ok, reason). Channels authorised before yt-analytics.readonly
    was added MUST reconnect (RECONNECT_REQUIRED): an old refresh token
    does not silently gain the scope. Never touches the channel otherwise.
    """
    if destination is None:
        return False, "DESTINATION_NOT_FOUND"
    if not destination.credentials:
        return False, "YOUTUBE_REAUTH_REQUIRED"
    scopes = granted_scopes(destination.credentials)
    if not scopes:
        # Token predates scope recording: assume analytics scope missing.
        return False, "RECONNECT_REQUIRED"
    if YOUTUBE_ANALYTICS_READONLY_SCOPE in scopes:
        return True, None
    if any(str(s).endswith("yt-analytics.readonly") for s in scopes):
        return True, None
    return False, "RECONNECT_REQUIRED"


def build_destination_client(
    db: Session,
    destination_id: str,
) -> tuple[Credentials, Any]:
    """YouTube API client bound to ONE destination's own OAuth token.

    Never falls back to another destination / pipeline / global token.
    """
    credentials = load_credentials(db, destination_id=destination_id)
    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )
    return credentials, youtube


def youtube_connected(
    db: Session,
    pipeline_id: str | None = None,
) -> bool:
    if pipeline_id:
        pipeline = db.get(Pipeline, pipeline_id)
        if pipeline is not None:
            return bool(pipeline.youtube_connected)

    raw = read_setting(
        db,
        GLOBAL_TOKEN_SETTING_KEY,
    )

    if not raw:
        return False

    try:
        data = json.loads(raw)
    except Exception:
        return False

    return bool(
        data.get("refresh_token")
    )


def get_youtube_status(
    db: Session,
    pipeline_id: str | None = None,
    destination_id: str | None = None,
) -> dict:
    if destination_id:
        destination = db.get(Destination, destination_id)
        if destination is not None:
            return {
                "connected": destination.connected,
                "destination_id": destination.id,
                "pipeline_id": destination.pipeline_id,
                "channel_id": destination.external_account_id,
                "channel_title": destination.external_account_name,
            }
        return {
            "connected": False,
            "destination_id": destination_id,
        }

    connected = False
    channel_id = None
    channel_title = None

    if pipeline_id:
        pipeline = db.get(Pipeline, pipeline_id)
        if pipeline is not None:
            connected = bool(pipeline.youtube_credentials)
            channel_id = pipeline.youtube_channel_id
            channel_title = pipeline.youtube_channel_title
    else:
        raw = read_setting(
            db,
            GLOBAL_TOKEN_SETTING_KEY,
        )
        connected = bool(raw)

    return {
        "connected": connected,
        "pipeline_id": pipeline_id,
        "channel_id": channel_id,
        "channel_title": channel_title,
    }


def upload_video(
    db: Session,
    file_path: Path,
    title: str,
    description: str,
    privacy_status: str,
    pipeline_id: str | None = None,
    destination_id: str | None = None,
    publish_at: datetime | str | None = None,
    publish_mode: str | None = None,
) -> str:
    """Upload with native YouTube scheduling support.

    publish_mode: immediate | scheduled | private | unlisted.
    When scheduled, privacy_status is forced to private and publishAt (RFC3339
    UTC) is sent. publishAt is never sent for public/unlisted/private.
    """
    if not file_path.exists():
        raise RuntimeError(
            f"Không tìm thấy video: {file_path}"
        )

    credentials = load_credentials(
        db,
        pipeline_id=pipeline_id,
        destination_id=destination_id,
    )

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )

    # Resolve native scheduling status (never mutate caller args).
    from app.youtube_scheduling import (
        build_insert_status,
        ensure_utc,
        normalize_youtube_error,
        parse_publish_at,
        validate_scheduled_mode,
    )

    mode = (publish_mode or "").lower() or None
    if mode is None:
        # Backwards compat: infer from privacy_status.
        mode = {"public": "immediate", "private": "private", "unlisted": "unlisted"}.get(
            (privacy_status or "public").lower(), "immediate"
        )
    publish_at_utc = None
    if publish_at is not None:
        try:
            publish_at_utc = parse_publish_at(publish_at)
        except Exception as exc:
            raise RuntimeError(f"INVALID_PUBLISH_AT: {exc}") from exc
    try:
        validate_scheduled_mode(mode, publish_at_utc)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    try:
        status_body = build_insert_status(mode, publish_at_utc)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    body = {
        "snippet": {
            "title": title[:100],
            "description": (
                description[:5000]
            ),
            "categoryId": "22",
        },
        "status": {
            **status_body,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(file_path),
        chunksize=8 * 1024 * 1024,
        resumable=True,
    )

    request = (
        youtube.videos()
        .insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
    )

    retry_count = 0
    max_retries = 6

    while True:
        try:
            _, response = (
                request.next_chunk()
            )

            if response is None:
                continue

            video_id = response.get(
                "id"
            )

            if not video_id:
                raise RuntimeError(
                    "YouTube không trả về video ID"
                )

            return video_id

        except HttpError as exc:
            status_code = (
                exc.resp.status
                if exc.resp
                else 0
            )

            retryable = status_code in {
                500,
                502,
                503,
                504,
            }

            if not retryable:
                from app.youtube_scheduling import normalize_youtube_error as _norm

                raise RuntimeError(
                    _norm(exc)
                    or (
                        f"YouTube API error "
                        f"{status_code}: {exc}"
                    )
                ) from exc

            retry_count += 1

            if retry_count > max_retries:
                raise RuntimeError(
                    "YouTube upload thất bại "
                    "sau nhiều lần retry"
                )

            time.sleep(
                min(
                    2 ** retry_count,
                    30,
                )
            )

        except (
            OSError,
            TimeoutError,
            ConnectionError,
        ) as exc:
            retry_count += 1

            if retry_count > max_retries:
                raise RuntimeError(
                    "Mất kết nối khi upload YouTube"
                ) from exc

            time.sleep(
                min(
                    2 ** retry_count,
                    30,
                )
            )


def _youtube_client_for_destination(db: Session, destination_id: str):
    _, youtube = build_destination_client(db, destination_id)
    return youtube


def update_video_schedule(
    db: Session,
    destination_id: str,
    youtube_video_id: str,
    new_publish_at: datetime | str,
) -> dict:
    """Change schedule: videos.update with privacyStatus=private + publishAt."""
    from app.youtube_scheduling import (
        build_reschedule_status,
        normalize_youtube_error,
        parse_publish_at,
        validate_publish_at,
    )

    publish_at_utc = parse_publish_at(new_publish_at)
    if publish_at_utc is None:
        raise RuntimeError("INVALID_PUBLISH_AT: new publish_at is required")
    try:
        validate_publish_at(publish_at_utc)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    youtube = _youtube_client_for_destination(db, destination_id)
    body = {"id": youtube_video_id, "status": build_reschedule_status(publish_at_utc)}
    try:
        return (
            youtube.videos()
            .update(part="status", body=body)
            .execute()
        )
    except HttpError as exc:
        raise RuntimeError(normalize_youtube_error(exc)) from exc


def publish_video_now(
    db: Session,
    destination_id: str,
    youtube_video_id: str,
) -> dict:
    """Scheduled -> Publish now: videos.update privacyStatus=public."""
    from app.youtube_scheduling import build_publish_now_status, normalize_youtube_error

    youtube = _youtube_client_for_destination(db, destination_id)
    body = {"id": youtube_video_id, "status": build_publish_now_status()}
    try:
        return (
            youtube.videos()
            .update(part="status", body=body)
            .execute()
        )
    except HttpError as exc:
        raise RuntimeError(normalize_youtube_error(exc)) from exc


def cancel_video_schedule(
    db: Session,
    destination_id: str,
    youtube_video_id: str,
) -> dict:
    """Cancel schedule: keep video private, clear publishAt.

    Safe behavior: videos.update with privacyStatus=private and NO publishAt.
    YouTube treats omission as clearing the scheduled publish (video stays
    private). Never deletes the video. Callers must preserve other status
    fields by only sending status part.
    """
    from app.youtube_scheduling import normalize_youtube_error

    youtube = _youtube_client_for_destination(db, destination_id)
    body = {"id": youtube_video_id, "status": {"privacyStatus": "private"}}
    try:
        return (
            youtube.videos()
            .update(part="status", body=body)
            .execute()
        )
    except HttpError as exc:
        raise RuntimeError(normalize_youtube_error(exc)) from exc


def get_video_status(
    db: Session,
    destination_id: str,
    youtube_video_id: str,
) -> dict:
    """Read privacyStatus / publishedAt / scheduled publishAt via videos.list."""
    from app.youtube_scheduling import normalize_youtube_error

    youtube = _youtube_client_for_destination(db, destination_id)
    try:
        resp = (
            youtube.videos()
            .list(part="status,snippet", id=youtube_video_id)
            .execute()
        )
    except HttpError as exc:
        raise RuntimeError(normalize_youtube_error(exc)) from exc
    items = (resp or {}).get("items", [])
    if not items:
        raise RuntimeError(f"YouTube video not found: {youtube_video_id}")
    item = items[0]
    status = item.get("status", {}) or {}
    snippet = item.get("snippet", {}) or {}
    return {
        "video_id": youtube_video_id,
        "privacyStatus": status.get("privacyStatus"),
        "publishAt": status.get("publishAt"),
        "uploadStatus": status.get("uploadStatus"),
        "publishedAt": snippet.get("publishedAt"),
        "raw": item,
    }
