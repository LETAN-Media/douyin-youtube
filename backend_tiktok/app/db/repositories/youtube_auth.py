from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts


async def create_oauth_state(
    state: str, destination_id: str, pipeline_id: str, expires_at: str, return_to: str | None = None
) -> None:
    await execute(
        """
        INSERT INTO youtube_oauth_states (state, destination_id, pipeline_id, expires_at, return_to)
        VALUES (:state, :destination_id, :pipeline_id, :expires_at, :return_to)
        """,
        {"state": state, "destination_id": destination_id, "pipeline_id": pipeline_id,
         "expires_at": expires_at, "return_to": return_to},
    )


async def get_oauth_state(state: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT state, destination_id, pipeline_id, expires_at, created_at, return_to "
        "FROM youtube_oauth_states WHERE state = :state",
        {"state": state},
    )
    return result_to_dict(res)


async def delete_oauth_state(state: str) -> None:
    await execute("DELETE FROM youtube_oauth_states WHERE state = :state", {"state": state})


async def delete_oauth_states_for_destination(destination_id: str) -> None:
    await execute(
        "DELETE FROM youtube_oauth_states WHERE destination_id = :destination_id",
        {"destination_id": destination_id},
    )


async def consume_oauth_state(state: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT state, destination_id, pipeline_id, expires_at, created_at, return_to "
        "FROM youtube_oauth_states WHERE state = :state",
        {"state": state},
    )
    row = result_to_dict(res)
    if row is None:
        return None
    await execute("DELETE FROM youtube_oauth_states WHERE state = :state", {"state": state})
    return row


async def save_credentials(destination_id: str, credentials_json: str) -> None:
    await execute(
        """
        INSERT INTO youtube_credentials (destination_id, credentials_json)
        VALUES (:destination_id, :credentials_json)
        ON CONFLICT(destination_id) DO UPDATE SET
            credentials_json = excluded.credentials_json,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        """,
        {"destination_id": destination_id, "credentials_json": credentials_json},
    )


async def get_credentials(destination_id: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT destination_id, credentials_json, updated_at FROM youtube_credentials WHERE destination_id = :id",
        {"id": destination_id},
    )
    return result_to_dict(res)


async def delete_credentials(destination_id: str) -> None:
    await execute("DELETE FROM youtube_credentials WHERE destination_id = :id", {"id": destination_id})
