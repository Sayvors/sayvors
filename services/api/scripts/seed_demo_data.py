"""Seed demo data that mirrors real Google Business Profile API shapes.

Everything written here matches row-for-row what the production pipeline
stores — so the dashboards render exactly as they would with a real
connected GBP location:

- channels               as the Google OAuth callback would create
- auto_reply_configs     as the connect flow would create
- channel_messages       as reviews_worker._store_inbound_review mirrors them
- review_insights        as the Kafka enrichment consumer would store
                         (sentiment/topics/products/problems JSON payloads)
- review_replies         as the auto-reply worker would post them
- location_daily_metrics as the GBP Performance API sync + rollups would write

Usage (from services/api, venv active):
    python scripts/seed_demo_data.py                 # seed for first user
    python scripts/seed_demo_data.py --email you@x   # seed for a user
    python scripts/seed_demo_data.py --reset         # wipe that user's demo data first
"""
import argparse
import asyncio
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

random.seed(42)

DEMO_ACCOUNT = "accounts/demo-acc-123"
DEMO_LOCATION = "demo-loc-456"

REVIEWER_NAMES = [
    "Aisha K.", "Daniel M.", "Sara T.", "Omar R.", "Layla H.", "Faisal N.",
    "Mona A.", "Yusuf B.", "Nora S.", "Khalid Z.", "Hana M.", "Tariq J.",
    "Salma D.", "Bilal Q.", "Dana F.", "Rami L.", "Lina W.", "Ziad H.",
]

# (rating, text, sentiment, score, topics, products, problems)
TEMPLATES = {
    5: [
        ("Absolutely loved the Chicken Burger — juicy, perfectly seasoned, and the staff were super friendly. Best spot in the city!",
         "positive", 0.95,
         [{"name": "quality", "sentiment": "positive"}, {"name": "staff", "sentiment": "positive"}, {"name": "service", "sentiment": "positive"}],
         [{"name": "Chicken Burger", "sentiment": "positive"}], []),
        ("Great food, quick service and a lovely atmosphere. The milkshake was amazing too!",
         "positive", 0.9,
         [{"name": "quality", "sentiment": "positive"}, {"name": "service", "sentiment": "positive"}, {"name": "atmosphere", "sentiment": "positive"}],
         [{"name": "Milkshake", "sentiment": "positive"}], []),
        ("Ordered delivery — arrived hot and on time. The beef burger was delicious. Highly recommend!",
         "positive", 0.88,
         [{"name": "delivery", "sentiment": "positive"}, {"name": "quality", "sentiment": "positive"}],
         [{"name": "Beef Burger", "sentiment": "positive"}], []),
        ("Clean place, welcoming team and the fries were perfectly crispy. Will definitely come back.",
         "positive", 0.9,
         [{"name": "cleanliness", "sentiment": "positive"}, {"name": "staff", "sentiment": "positive"}, {"name": "quality", "sentiment": "positive"}],
         [{"name": "Fries", "sentiment": "positive"}], []),
    ],
    4: [
        ("Really good burgers and friendly service. Prices are a bit high but the quality makes up for it.",
         "positive", 0.65,
         [{"name": "quality", "sentiment": "positive"}, {"name": "price", "sentiment": "negative"}, {"name": "service", "sentiment": "positive"}],
         [{"name": "Chicken Burger", "sentiment": "positive"}], []),
        ("Tasty food and nice location with easy parking. The wait was slightly long on a busy night, but worth it.",
         "positive", 0.6,
         [{"name": "quality", "sentiment": "positive"}, {"name": "location", "sentiment": "positive"}, {"name": "waiting time", "sentiment": "neutral"}],
         [{"name": "Beef Burger", "sentiment": "positive"}], []),
        ("Good experience overall. Staff were helpful, though the place got noisy during rush hour.",
         "positive", 0.6,
         [{"name": "staff", "sentiment": "positive"}, {"name": "atmosphere", "sentiment": "neutral"}],
         [], []),
    ],
    3: [
        ("Food was okay but we waited almost 30 minutes even though the place wasn't full. Prices are fair.",
         "neutral", 0.05,
         [{"name": "waiting time", "sentiment": "negative"}, {"name": "quality", "sentiment": "neutral"}, {"name": "price", "sentiment": "positive"}],
         [], [{"name": "slow service", "severity": "medium"}]),
        ("Average experience. The burger was fine but lukewarm when it arrived. Delivery guy was polite though.",
         "neutral", 0.0,
         [{"name": "quality", "sentiment": "neutral"}, {"name": "delivery", "sentiment": "neutral"}],
         [{"name": "Beef Burger", "sentiment": "neutral"}], [{"name": "cold food", "severity": "medium"}]),
    ],
    2: [
        ("Fries were cold and the order took forever. Staff apologized but the service needs work.",
         "negative", -0.6,
         [{"name": "quality", "sentiment": "negative"}, {"name": "waiting time", "sentiment": "negative"}, {"name": "service", "sentiment": "negative"}],
         [{"name": "Fries", "sentiment": "negative"}],
         [{"name": "cold food", "severity": "medium"}, {"name": "slow service", "severity": "high"}]),
        ("Disappointed — wrong drink in the order and nobody answered the phone when I called to fix it.",
         "negative", -0.65,
         [{"name": "communication", "sentiment": "negative"}, {"name": "delivery", "sentiment": "negative"}],
         [],
         [{"name": "wrong order", "severity": "high"}, {"name": "no answer on phone", "severity": "medium"}]),
    ],
    1: [
        ("Very disappointed. My order was wrong twice and nobody answered the phone when I called to fix it. Won't order again.",
         "negative", -0.9,
         [{"name": "service", "sentiment": "negative"}, {"name": "communication", "sentiment": "negative"}],
         [],
         [{"name": "wrong order", "severity": "high"}, {"name": "no answer on phone", "severity": "high"}]),
        ("Waited 40 minutes on a Friday evening while the place was understaffed. Rude response when we asked about our food.",
         "negative", -0.85,
         [{"name": "waiting time", "sentiment": "negative"}, {"name": "staff", "sentiment": "negative"}],
         [],
         [{"name": "slow service", "severity": "high"}, {"name": "staff attitude", "severity": "high"}]),
        ("Table was dirty and the floor was sticky. Health inspection should visit this place.",
         "negative", -0.8,
         [{"name": "cleanliness", "sentiment": "negative"}],
         [],
         [{"name": "dirty tables", "severity": "high"}]),
    ],
}

REPLY_TEXTS = {
    5: "Thank you so much for the wonderful review! We're thrilled you enjoyed your visit — feedback like yours keeps our team motivated. Hope to see you again soon!",
    4: "Thank you for the kind words and honest feedback! We're always working to improve, and we hope your next visit is a five-star one.",
    3: "Thanks for the honest feedback. We're glad parts of your visit worked well, and we're actively working on the areas you mentioned. We'd love to welcome you back!",
    2: "We're truly sorry about your experience — that's not the standard we aim for. We've shared your feedback with the team and would love to make this right. Please reach out to us directly.",
    1: "We sincerely apologize for your experience. This is not acceptable and we're addressing it with the team immediately. Please contact us directly so we can make this right.",
}


def pick_template(rating: int):
    return random.choice(TEMPLATES[rating])


def gen_reviews(days: int):
    """(review_time, rating, text, sentiment, score, topics, products, problems) tuples."""
    now = datetime.now(timezone.utc)
    out = []
    for d in range(days, 0, -1):
        day = now - timedelta(days=d)
        recency = 1 - d / days  # 0 oldest -> 1 newest
        base = 0.6 + recency * 1.6  # volume ramps up over time
        count = max(0, int(round(base + random.uniform(-0.5, 0.9))))
        for _ in range(count):
            if d <= 14:  # recent dip: more 1-2 star (slow service complaints)
                rating = random.choices([5, 4, 3, 2, 1], weights=[28, 27, 15, 16, 14])[0]
            else:
                rating = random.choices([5, 4, 3, 2, 1], weights=[45, 30, 12, 8, 5])[0]
            text, sentiment, score, topics, products, problems = pick_template(rating)
            # Friday-evening slow service spike in the recent window
            if d <= 14 and day.weekday() == 4 and random.random() < 0.5:
                text = "Waited almost an hour for our food on Friday evening. The place was clearly understaffed and the kitchen couldn't keep up."
                sentiment, score = "negative", -0.85
                topics = [{"name": "waiting time", "sentiment": "negative"}, {"name": "service", "sentiment": "negative"}]
                problems = [{"name": "slow service", "severity": "high"}]
            hour = random.choices([12, 13, 14, 18, 19, 20, 21, 22], weights=[10, 12, 8, 15, 18, 15, 12, 10])[0]
            review_time = day.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59), microsecond=0)
            out.append((review_time, rating, text, sentiment, score, topics, products, problems))
    return out


def gen_performance(days: int):
    """Daily GBP performance metrics with weekly seasonality + growth trend."""
    now = datetime.now(timezone.utc)
    rows = []
    for d in range(days, 0, -1):
        day = (now - timedelta(days=d)).date()
        i = days - d
        weekend = 1.35 if day.weekday() in (4, 5) else 1.0
        growth = 1 + i / (days * 2.2)  # ~45% growth across the window
        desktop = int(random.uniform(38, 62) * weekend * growth)
        mobile = int(random.uniform(120, 190) * weekend * growth)
        clicks = int(desktop * random.uniform(0.10, 0.16) + mobile * random.uniform(0.10, 0.15))
        calls = int(random.uniform(2, 7) * weekend * growth)
        directions = int(random.uniform(6, 16) * weekend * growth)
        rows.append((day, desktop, mobile, clicks, calls, directions))
    return rows


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default=None, help="Attach demo data to this user (default: first user)")
    parser.add_argument("--reset", action="store_true", help="Delete existing demo/analytics data for the user first")
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()

    from app.database import async_session
    from app.modules.users.models import User
    from app.modules.channels.models import AutoReplyConfig, Channel, ChannelMessage, ReviewReply
    from app.modules.analytics.models import LocationDailyMetric, ReviewInsight

    async with async_session() as db:
        # ── resolve user ──
        if args.email:
            user = (await db.execute(select(User).where(User.email == args.email))).scalar_one_or_none()
        else:
            user = (await db.execute(select(User).order_by(User.created_at).limit(1))).scalar_one_or_none()
        if not user:
            print("ERROR: no user found. Sign up in the app first, then run:", file=sys.stderr)
            print("  python scripts/seed_demo_data.py --email your@email", file=sys.stderr)
            return 1
        print(f"Seeding demo data for user: {user.email}")

        second_user = (await db.execute(select(User).where(User.email == "syab293@gmail.com"))).scalar_one_or_none() or (await db.execute(select(User).where(User.id != user.id).limit(1))).scalar_one_or_none()
        if second_user:
            second_channel = (
                await db.execute(
                    select(Channel).where(Channel.user_id == second_user.id, Channel.platform == "google_reviews")
                )
            ).scalar_one_or_none()
            if not second_channel:
                second_channel = Channel(
                    id=str(uuid.uuid4()),
                    user_id=second_user.id,
                    platform="google_reviews",
                    platform_user_id="demo-acc-456",
                    display_name="Pizza Palace — Suburban",
                    status="active",
                    metadata_json='{"location_id": "demo-loc-789", "account_id": "demo-acc-456"}',
                    created_at=datetime.now(timezone.utc) - timedelta(days=args.days),
                )
                db.add(second_channel)
                await db.flush()
                await db.refresh(second_channel)
                print(f"  created second google_reviews channel {second_channel.id} for {second_user.email}")

        # ── resolve/create channel ──
        channel = (
            await db.execute(
                select(Channel).where(Channel.user_id == user.id, Channel.platform == "google_reviews")
            )
        ).scalar_one_or_none()
        if not channel:
            channel = Channel(
                id=str(uuid.uuid4()),
                user_id=user.id,
                platform="google_reviews",
                platform_user_id=DEMO_ACCOUNT.split("/")[-1],
                display_name="Demo Burgers — Riyadh",
                status="active",
                metadata_json=f'{{"location_id": "{DEMO_LOCATION}", "account_id": "demo-acc-123"}}',
                created_at=datetime.now(timezone.utc) - timedelta(days=args.days),
            )
            db.add(channel)
            await db.flush()
            print(f"  created google_reviews channel {channel.id}")
        else:
            print(f"  using existing channel {channel.id} ({channel.display_name})")

        if args.reset:
            for model in (ReviewInsight, LocationDailyMetric, ReviewReply, ChannelMessage):
                await db.execute(delete(model).where(model.channel_id == channel.id))
            await db.commit()
            print("  reset: deleted existing analytics/reply data for this channel")

        existing = (
            await db.execute(select(func.count()).where(ReviewInsight.channel_id == channel.id))
        ).scalar() or 0
        if existing > 0:
            print(f"  channel already has {existing} review insights — skipping (use --reset to reseed)")
            return 0

        # ── auto-reply config (as the connect flow would create) ──
        config = AutoReplyConfig(
            id=str(uuid.uuid4()),
            channel_id=channel.id,
            enabled=True,
            tone="friendly",
            min_rating_auto=4,
            model="openai:gpt-4o-mini",
        )
        db.add(config)

        # ── reviews + enrichment + replies ──
        reviews = gen_reviews(args.days)
        now = datetime.now(timezone.utc)
        replied_count = 0
        for review_time, rating, text, sentiment, score, topics, products, problems in reviews:
            age_days = (now - review_time).days
            reply_prob = 0.5 if age_days <= 14 else 0.85
            is_replied = random.random() < reply_prob
            replied_at = None
            if is_replied:
                delay_minutes = int(random.lognormvariate(4.2, 1.1))  # ~1h median, long tail
                replied_at = review_time + timedelta(minutes=min(delay_minutes, 60 * 40))
            review_id = f"{DEMO_ACCOUNT}/locations/{DEMO_LOCATION}/reviews/{uuid.uuid4().hex[:12]}"
            db.add(ReviewInsight(
                id=str(uuid.uuid4()),
                user_id=user.id,
                channel_id=channel.id,
                review_id=review_id,
                rating=rating,
                review_text=text,
                reviewer_name=random.choice(REVIEWER_NAMES),
                sentiment=sentiment,
                sentiment_score=score,
                topics=topics,
                products=products,
                problems=problems,
                enrichment_status="done",
                replied=is_replied,
                replied_at=replied_at,
                review_updated_at=review_time,
                created_at=review_time,
                updated_at=review_time,
            ))
            if is_replied:
                db.add(ReviewReply(
                    id=str(uuid.uuid4()),
                    channel_id=channel.id,
                    review_id=review_id,
                    rating=rating,
                    review_text=text,
                    reviewer_name=None,
                    reply_text=REPLY_TEXTS[rating],
                    status="posted",
                    created_at=replied_at,
                ))
                replied_count += 1
            # inbound mirror (as the worker stores it)
            db.add(ChannelMessage(
                id=str(uuid.uuid4()),
                channel_id=channel.id,
                platform_message_id=review_id[:200],
                direction="inbound",
                content=text or f"({rating}/5 stars, no comment)",
                content_type="review",
                status="read",
                created_at=review_time,
            ))

        # ── daily rollups + GBP performance metrics ──
        by_day: dict = {}
        for review_time, rating, text, sentiment, *_ in reviews:
            d = review_time.date()
            e = by_day.setdefault(d, {"n": 0, "sum": 0, "pos": 0, "neu": 0, "neg": 0})
            e["n"] += 1
            e["sum"] += rating
            e[{"positive": "pos", "neutral": "neu", "negative": "neg"}[sentiment]] += 1

        for day, desktop, mobile, clicks, calls, directions in gen_performance(args.days):
            e = by_day.get(day, {"n": 0, "sum": 0, "pos": 0, "neu": 0, "neg": 0})
            db.add(LocationDailyMetric(
                id=str(uuid.uuid4()),
                user_id=user.id,
                channel_id=channel.id,
                date=day,
                reviews_count=e["n"],
                avg_rating=round(e["sum"] / e["n"], 2) if e["n"] else 0.0,
                positive_count=e["pos"],
                neutral_count=e["neu"],
                negative_count=e["neg"],
                replies_count=e["n"],  # demo: all same-day replies counted
                impressions_maps_desktop=desktop,
                impressions_maps_mobile=mobile,
                website_clicks=clicks,
                call_clicks=calls,
                direction_requests=directions,
            ))

        await db.commit()
        print(f"  seeded {len(reviews)} reviews ({replied_count} replied), {args.days} days of performance metrics")

        # ── Second demo user / location (benchmark/comparison data) ──
        second_channel = (
            await db.execute(
                select(Channel).where(
                    Channel.user_id == second_user.id,
                    Channel.platform == "google_reviews",
                )
            )
        ).scalar_one_or_none()
        if second_channel:
            # Different profile: lower ratings, different products (pizza-focused),
            # more cleanliness/service problems (to show cross-location contrast).
            second_reviews = [
                (4, "Good pizza but slow on busy nights.", "neutral", 0.05,
                 [{"name": "service", "sentiment": "neutral"}], [{"name": "Pizza Margherita", "sentiment": "positive"}], [{"name": "slow service", "severity": "medium"}]),
                (2, "Dirty table and cold fries. Asked for ketchup twice.", "negative", -0.7,
                 [{"name": "cleanliness", "sentiment": "negative"}, {"name": "service", "sentiment": "negative"}], [{"name": "Fries", "sentiment": "negative"}], [{"name": "dirty table", "severity": "high"}, {"name": "cold food", "severity": "medium"}]),
                (5, "Best pizza in the neighborhood! Fast and clean.", "positive", 0.9,
                 [{"name": "service", "sentiment": "positive"}, {"name": "cleanliness", "sentiment": "positive"}], [{"name": "Pizza Margherita", "sentiment": "positive"}], []),
                (1, "Terrible. Never coming back. Manager was rude.", "negative", -0.9,
                 [{"name": "service", "sentiment": "negative"}, {"name": "staff", "sentiment": "negative"}], [], [{"name": "staff attitude", "severity": "high"}, {"name": "service failure", "severity": "high"}]),
            ]
            second_day_counts = 0
            second_now = datetime.now(timezone.utc)
            for review_time_offset, rating, text, sentiment, score, topics, products, problems in second_reviews:
                review_time = second_now - timedelta(days=random.randint(1, 14))
                review_time = review_time.replace(hour=random.choice([12, 13, 19, 21]), minute=random.randint(0, 59))
                review_time = review_time.replace(tzinfo=timezone.utc)
                review_id = f"{DEMO_ACCOUNT}/locations/demo-loc-789/reviews/{uuid.uuid4().hex[:12]}"
                db.add(ReviewInsight(
                    id=str(uuid.uuid4()), user_id=second_user.id, channel_id=second_channel.id,
                    review_id=review_id, rating=rating, review_text=text,
                    reviewer_name=random.choice(REVIEWER_NAMES), sentiment=sentiment,
                    sentiment_score=score, topics=topics, products=products, problems=problems,
                    enrichment_status="done", replied=False,
                    review_updated_at=review_time, created_at=review_time, updated_at=review_time,
                ))
                second_day_counts += 1
                db.add(ChannelMessage(
                    id=str(uuid.uuid4()), channel_id=second_channel.id,
                    platform_message_id=review_id[:200], direction="inbound",
                    content=text or f"({rating}/5 stars, no comment)", content_type="review", status="read",
                    created_at=review_time,
                ))
            # Second location performance: lower impressions, lower actions
            for d in range(1, args.days + 1):
                day = (second_now - timedelta(days=d)).date()
                desktop = int(random.uniform(25, 45) * 0.7)
                mobile = int(random.uniform(70, 130) * 0.7)
                db.add(LocationDailyMetric(
                    id=str(uuid.uuid4()), user_id=second_user.id, channel_id=second_channel.id,
                    date=day, reviews_count=0, avg_rating=0.0,
                    positive_count=0, neutral_count=0, negative_count=0,
                    replies_count=0,
                    impressions_maps_desktop=desktop, impressions_maps_mobile=mobile,
                    website_clicks=int(random.uniform(3, 10) * 0.7),
                    call_clicks=int(random.uniform(1, 4) * 0.7),
                    direction_requests=int(random.uniform(2, 8) * 0.7),
                ))
            await db.commit()
            print(f"  seeded second location {second_channel.display_name} ({second_day_counts} reviews, {args.days}d metrics)")

        print("Done — log in as either user and open the Analytics page.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
