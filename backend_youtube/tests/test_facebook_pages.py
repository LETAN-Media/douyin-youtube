import pytest

from app.db.repositories import facebook_pages as fb_repo
from app.db.repositories import pipelines as pipeline_repo
from app.utils import decrypt_token, encrypt_token


@pytest.mark.asyncio
async def test_facebook_page_crud(db_session):
    p = await pipeline_repo.create_pipeline(db_session, name="P1")
    page = await fb_repo.add_facebook_page(
        db_session, p.id, page_id="123456789", page_name="My Page",
        page_access_token="EAAB_TOKEN", scopes=["pages_manage_posts", "pages_read_engagement"], is_default=True,
    )
    assert page.id.startswith("page_")
    assert await fb_repo.get_default_facebook_page(db_session, p.id) is not None
    token = await fb_repo.decrypt_page_token(db_session, page.id)
    assert token == "EAAB_TOKEN"
    assert await fb_repo.set_default_facebook_page(db_session, p.id, "nonexistent") is False
    ok = await fb_repo.enable_facebook_page(db_session, page.id, enabled=False, error="revoked")
    assert ok.status == "disabled"
    deleted = await fb_repo.delete_facebook_page(db_session, page.id)
    assert deleted is True


@pytest.mark.asyncio
async def test_token_encryption_roundtrip():
    encrypted = encrypt_token("secret_token_value")
    assert encrypted != "secret_token_value"
    assert decrypt_token(encrypted) == "secret_token_value"
