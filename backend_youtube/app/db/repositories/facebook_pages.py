from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FacebookPage
from ...utils import decrypt_token, encrypt_token, gen_id


async def add_facebook_page(
    session: AsyncSession,
    pipeline_id: str,
    *,
    page_id: str,
    page_name: str | None = None,
    page_access_token: str | None = None,
    scopes: list[str] | None = None,
    is_default: bool = False,
) -> FacebookPage:
    page = FacebookPage(
        id=gen_id("page"),
        pipeline_id=pipeline_id,
        page_id=page_id,
        page_name=page_name,
        page_access_token_encrypted=encrypt_token(page_access_token) if page_access_token else None,
        scopes=scopes or [],
        is_default=is_default,
        status="enabled",
    )
    session.add(page)
    await session.commit()
    await session.refresh(page)
    return page


async def get_facebook_page(session: AsyncSession, page_row_id: str) -> FacebookPage | None:
    return await session.get(FacebookPage, page_row_id)


async def list_facebook_pages(session: AsyncSession, pipeline_id: str) -> Sequence[FacebookPage]:
    result = await session.execute(
        select(FacebookPage).where(FacebookPage.pipeline_id == pipeline_id).order_by(FacebookPage.is_default.desc(), FacebookPage.created_at)
    )
    return result.scalars().all()


async def get_default_facebook_page(session: AsyncSession, pipeline_id: str) -> FacebookPage | None:
    result = await session.execute(
        select(FacebookPage).where(
            FacebookPage.pipeline_id == pipeline_id,
            FacebookPage.is_default.is_(True),
            FacebookPage.status == "enabled",
        )
    )
    return result.scalars().first()


async def get_default_facebook_page_with_token(session: AsyncSession, pipeline_id: str) -> tuple[FacebookPage | None, str | None]:
    page = await get_default_facebook_page(session, pipeline_id)
    if page is None:
        return None, None
    return page, await decrypt_page_token(session, page.id)


async def decrypt_page_token(session: AsyncSession, page_row_id: str) -> str | None:
    page = await session.get(FacebookPage, page_row_id)
    if page is None or not page.page_access_token_encrypted:
        return None
    return decrypt_token(page.page_access_token_encrypted)


async def update_facebook_page_token(session: AsyncSession, page_row_id: str, token: str, expires_at=None) -> FacebookPage | None:
    page = await session.get(FacebookPage, page_row_id)
    if page is None:
        return None
    page.page_access_token_encrypted = encrypt_token(token) if token else None
    page.page_access_token_expires_at = expires_at
    session.add(page)
    await session.commit()
    await session.refresh(page)
    return page


async def set_default_facebook_page(session: AsyncSession, pipeline_id: str, page_row_id: str) -> bool:
    await session.execute(
        update(FacebookPage).where(
            FacebookPage.pipeline_id == pipeline_id,
            FacebookPage.is_default.is_(True),
        ).values(is_default=False)
    )
    page = await session.get(FacebookPage, page_row_id)
    if page is None or page.pipeline_id != pipeline_id:
        await session.commit()
        return False
    page.is_default = True
    await session.commit()
    return True


async def enable_facebook_page(session: AsyncSession, page_row_id: str, enabled: bool, error: str | None = None) -> FacebookPage | None:
    page = await session.get(FacebookPage, page_row_id)
    if page is None:
        return None
    page.status = "enabled" if enabled else "disabled"
    page.error = error
    session.add(page)
    await session.commit()
    await session.refresh(page)
    return page


async def delete_facebook_page(session: AsyncSession, page_row_id: str) -> bool:
    page = await session.get(FacebookPage, page_row_id)
    if page is None:
        return False
    await session.delete(page)
    await session.commit()
    return True
