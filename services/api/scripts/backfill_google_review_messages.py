"""Backfill Google review names, avatars and replies into the inbox.

Google reviews arrive as `channel_messages` but older rows stored the synthetic
`google:<digest>` key and no reviewer name. Posted replies live in
`review_replies` and were never mirrored as outbound chat messages, so the
inbox showed the customer's review without the merchant's public response.

Idempotent: existing details are only filled when missing, and reply messages
use `google-reply:<reply id>` as their platform id.

Dry run by default:

    python -m scripts.backfill_google_review_messages

Apply:

    python -m scripts.backfill_google_review_messages --apply
"""
import argparse
import asyncio
import sys
import uuid
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[1]
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from sqlalchemy import select

from app.database import async_session
from app.modules.analytics.models import ReviewInsight
from app.modules.channels.models import (
    Channel,
    ChannelMessage,
    ChannelThread,
    ReviewReply,
)
from app.modules.channels.service import encrypt_message_content


async def main(apply: bool) -> None:
    async with async_session() as db:
        channels = (
            await db.execute(
                select(Channel).where(Channel.platform == "google_reviews")
            )
        ).scalars().all()
        updated_names = added_replies = skipped = 0

        for channel in channels:
            inbound = (
                await db.execute(
                    select(ChannelMessage)
                    .where(
                        ChannelMessage.channel_id == channel.id,
                        ChannelMessage.direction == "inbound",
                    )
                    .order_by(ChannelMessage.created_at.desc())
                    .limit(5000)
                )
            ).scalars().all()
            by_review = {
                m.platform_message_id: m
                for m in inbound
                if m.platform_message_id
            }
            if not by_review:
                continue

            insights = (
                await db.execute(
                    select(ReviewInsight).where(
                        ReviewInsight.channel_id == channel.id,
                        ReviewInsight.review_id.in_(list(by_review)),
                    )
                )
            ).scalars().all()
            by_review_insight = {i.review_id: i for i in insights}

            for review_id, message in by_review.items():
                insight = by_review_insight.get(review_id)
                if insight is None:
                    continue
                changed = False
                if not message.contact_name and insight.reviewer_name:
                    message.contact_name = insight.reviewer_name
                    changed = True
                if changed:
                    updated_names += 1
                    if apply:
                        db.add(message)
                        # Keep the denormalized thread name in step.
                        if message.contact_phone_hash:
                            thread = (
                                await db.execute(
                                    select(ChannelThread).where(
                                        ChannelThread.channel_id == channel.id,
                                        ChannelThread.contact_phone_hash
                                        == message.contact_phone_hash,
                                    )
                                )
                            ).scalar_one_or_none()
                            if thread is not None and not thread.contact_name:
                                thread.contact_name = insight.reviewer_name
                                db.add(thread)

            replies = (
                await db.execute(
                    select(ReviewReply).where(
                        ReviewReply.channel_id == channel.id,
                        ReviewReply.status == "posted",
                    )
                )
            ).scalars().all()
            for reply in replies:
                inbound_msg = by_review.get(reply.review_id)
                if inbound_msg is None:
                    skipped += 1
                    continue
                platform_id = f"google-reply:{reply.id}"[:200]
                exists = (
                    await db.execute(
                        select(ChannelMessage.id).where(
                            ChannelMessage.channel_id == channel.id,
                            ChannelMessage.platform_message_id == platform_id,
                        ).limit(1)
                    )
                ).scalar_one_or_none()
                if exists:
                    continue
                added_replies += 1
                print(
                    f"{'add' if apply else 'would add'} reply message: "
                    f"{channel.display_name} / {reply.reviewer_name or 'reviewer'}"
                )
                if apply:
                    handled_by = "human" if reply.reply_external_id else "ai"
                    db.add(
                        ChannelMessage(
                            id=str(uuid.uuid4()),
                            channel_id=channel.id,
                            platform_message_id=platform_id,
                            direction="outbound",
                            content=encrypt_message_content(reply.reply_text),
                            content_type="review_reply",
                            status="read",
                            contact_phone=inbound_msg.contact_phone,
                            contact_phone_hash=inbound_msg.contact_phone_hash,
                            contact_name=(
                                inbound_msg.contact_name or reply.reviewer_name
                            ),
                            handled_by=handled_by,
                            is_ai=handled_by == "ai",
                        )
                    )

            if apply:
                await db.commit()

        if apply:
            await db.commit()
    print(
        f"{'updated' if apply else 'would update'} {updated_names} reviewer name(s), "
        f"{'added' if apply else 'would add'} {added_replies} reply message(s), "
        f"skipped {skipped} reply/replies with no inbound row."
    )
    if not apply:
        print("Dry run only. Re-run with --apply to write.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.apply))
