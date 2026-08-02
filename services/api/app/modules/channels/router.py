from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db, get_current_user
from ..users.models import User
from .schemas import (
    ChannelCreate,
    ChannelListResponse,
    ChannelMessageListResponse,
    ChannelMessageResponse,
    ChannelMessageSend,
    ChannelResponse,
)
from .service import (
    create_channel,
    delete_channel,
    get_channel,
    handle_webhook,
    list_channels,
    list_messages,
    send_message,
)

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])


@router.post("/", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def connect_channel(
    body: ChannelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channel = await create_channel(body, user, db)
    return ChannelResponse(
        id=channel.id,
        platform=channel.platform,
        platform_user_id=channel.platform_user_id,
        display_name=channel.display_name,
        status=channel.status,
        avatar_url=channel.avatar_url,
        created_at=channel.created_at.isoformat(),
    )


@router.get("/", response_model=ChannelListResponse)
async def get_channels(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channels, total = await list_channels(user, db, limit, offset)
    return ChannelListResponse(
        channels=[
            ChannelResponse(
                id=c.id,
                platform=c.platform,
                platform_user_id=c.platform_user_id,
                display_name=c.display_name,
                status=c.status,
                avatar_url=c.avatar_url,
                created_at=c.created_at.isoformat(),
            )
            for c in channels
        ],
        total=total,
    )


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel_by_id(
    channel_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    channel = await get_channel(channel_id, user, db)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ChannelResponse(
        id=channel.id,
        platform=channel.platform,
        platform_user_id=channel.platform_user_id,
        display_name=channel.display_name,
        status=channel.status,
        avatar_url=channel.avatar_url,
        created_at=channel.created_at.isoformat(),
    )


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_channel(
    channel_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_channel(channel_id, user, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel not found")


@router.post("/{channel_id}/messages", response_model=ChannelMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_to_channel(
    channel_id: str,
    body: ChannelMessageSend,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        msg = await send_message(channel_id, body, user, db)
    except ValueError:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ChannelMessageResponse(
        id=msg.id,
        channel_id=msg.channel_id,
        platform_message_id=msg.platform_message_id,
        direction=msg.direction,
        content=msg.content,
        content_type=msg.content_type,
        status=msg.status,
        error=msg.error,
        created_at=msg.created_at.isoformat(),
    )


@router.get("/{channel_id}/messages", response_model=ChannelMessageListResponse)
async def get_channel_messages(
    channel_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msgs, total = await list_messages(channel_id, user, db, limit, offset)
    return ChannelMessageListResponse(
        messages=[
            ChannelMessageResponse(
                id=m.id,
                channel_id=m.channel_id,
                platform_message_id=m.platform_message_id,
                direction=m.direction,
                content=m.content,
                content_type=m.content_type,
                status=m.status,
                error=m.error,
                created_at=m.created_at.isoformat(),
            )
            for m in msgs
        ],
        total=total,
    )


# ── Webhooks (no auth — platform sends these) ──────────────────────────


@router.post("/webhook/{platform}")
async def channel_webhook(
    platform: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    payload = await request.json()
    msg = await handle_webhook(platform, payload, db)
    return {"status": "ok"}
