"""Server-side OAuth state + per-destination credentials (Task 7A).

Credentials live in their own table, never joined into public reads.
"""

from typing import Any

from ..client import get_client


async def create_oauth_state(
    *,
    state: str,
    destination_id: str,
    pipeline_id: str,
    expires_at: str,
    return_to: str | None = None,
) -> None:
    client = get_client()
    try:
        await client.execute(
            """
            INSERT INTO youtube_oauth_states (state, destination_id, pipeline_id, expires_at, return_to)
            VALUES (:state, :destination_id, :pipeline_id, :expires_at, :return_to)
            """,
            {
                "state": state,
                "destination_id": destination_id,
                "pipeline_id": pipeline_id,
                "expires_at": expires_at,
                "return_to": return_to,
            },
        )
    except Exception:
        # Older DBs without the return_to column (migration pending).
        await client.execute(
            """
            INSERT INTO youtube_oauth_states (state, destination_id, pipeline_id, expires_at)
            VALUES (:state, :destination_id, :pipeline_id, :expires_at)
            """,
            {
                "state": state,
                "destination_id": destination_id,
                "pipeline_id": pipeline_id,
                "expires_at": expires_at,
            },
        )


async def get_oauth_state(state: str) -> dict[str, Any] | None:
    client = get_client()
    try:
        rows = await client.execute(
            "SELECT state, destination_id, pipeline_id, expires_at, created_at, return_to "
            "FROM youtube_oauth_states WHERE state = :state",
            {"state": state},
        )
        if not rows.rows:
            return None
        r = rows.rows[0]
        return {
            "state": r[0],
            "destination_id": r[1],
            "pipeline_id": r[2],
            "expires_at": r[3],
            "created_at": r[4],
            "return_to": r[5] if len(r) > 5 else None,
        }
    except Exception:
        rows = await client.execute(
            "SELECT state, destination_id, pipeline_id, expires_at, created_at "
            "FROM youtube_oauth_states WHERE state = :state",
            {"state": state},
        )
        if not rows.rows:
            return None
        r = rows.rows[0]
        return {
            "state": r[0],
            "destination_id": r[1],
            "pipeline_id": r[2],
            "expires_at": r[3],
            "created_at": r[4],
            "return_to": None,
        }


async def delete_oauth_state(state: str) -> None:
    client = get_client()
    await client.execute(
        "DELETE FROM youtube_oauth_states WHERE state = :state", {"state": state}
    )


async def get_credentials(destination_id: str) -> str | None:
    """Raw credentials JSON for exactly one destination. Never expose via API."""
    client = get_client()
    rows = await client.execute(
        "SELECT credentials_json FROM youtube_credentials WHERE destination_id = :id",
        {"id": destination_id},
    )
    if not rows.rows:
        return None
    return rows.rows[0][0]


async def save_credentials(destination_id: str, credentials_json: str) -> None:
    client = get_client()
    await client.execute(
        """
        INSERT INTO youtube_credentials (destination_id, credentials_json, updated_at)
        VALUES (:id, :credentials_json, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        ON CONFLICT(destination_id) DO UPDATE SET
            credentials_json = excluded.credentials_json,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        """,
        {"id": destination_id, "credentials_json": credentials_json},
    )


async def delete_credentials(destination_id: str) -> None:
    """Delete stored OAuth credentials. Never logs the values."""
    client = get_client()
    await client.execute(
        "DELETE FROM youtube_credentials WHERE destination_id = :id",
        {"id": destination_id},
    )


async def delete_oauth_states_for_destination(destination_id: str) -> int:
    """Delete pending OAuth states. Returns rows removed."""
    client = get_client()
    res = await client.execute(
        "DELETE FROM youtube_oauth_states WHERE destination_id = :id",
        {"id": destination_id},
    )
    return res.rows_affected or 0
