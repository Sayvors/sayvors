"""The catalog seeder is what makes a models-only rebuild usable.

``Base.metadata.create_all`` creates the catalog tables but no rows. With an
empty ``tones`` table every tone is invalid, and with no
``response_strategies`` strategy matching returns nothing. These tests pin the
three properties the seeder must have: it fills an empty database, it never
duplicates on a restart, and it never overwrites an admin's edit.
"""
from sqlalchemy import delete, func, select, update

from app.modules.review_engine.catalog_seed import (
    DIALECTS,
    STRATEGIES,
    TONES,
    VOICE_MODELS,
    seed_catalogs,
)
from app.modules.review_engine.models import Dialect, ResponseStrategy, Tone
from app.modules.tts.models import VoiceModelConfig

EXPECTED_FIRST_RUN = {
    "tones": len(TONES),
    "dialects": len(DIALECTS),
    "response_strategies": len(STRATEGIES),
    "voice_model_configs": len(VOICE_MODELS),
}


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_first_run_fills_every_catalog(db):
    counts = await seed_catalogs(db)

    assert counts == EXPECTED_FIRST_RUN
    assert await _count(db, Tone) == len(TONES)
    assert await _count(db, Dialect) == len(DIALECTS)
    assert await _count(db, ResponseStrategy) == len(STRATEGIES)
    assert await _count(db, VoiceModelConfig) == len(VOICE_MODELS)


async def test_second_run_inserts_nothing(db):
    await seed_catalogs(db)

    counts = await seed_catalogs(db)

    assert counts == dict.fromkeys(EXPECTED_FIRST_RUN, 0)
    # The totals are unchanged, so nothing was duplicated either.
    assert await _count(db, Tone) == len(TONES)
    assert await _count(db, Dialect) == len(DIALECTS)
    assert await _count(db, ResponseStrategy) == len(STRATEGIES)
    assert await _count(db, VoiceModelConfig) == len(VOICE_MODELS)


async def test_admin_edit_survives_a_restart(db):
    await seed_catalogs(db)
    await db.execute(
        update(Tone).where(Tone.code == "friendly").values(label="Warm & friendly")
    )
    await db.commit()

    counts = await seed_catalogs(db)

    assert counts == dict.fromkeys(EXPECTED_FIRST_RUN, 0)
    label = (
        await db.execute(select(Tone.label).where(Tone.code == "friendly"))
    ).scalar_one()
    assert label == "Warm & friendly"


async def test_deleted_row_is_refilled_on_next_start(db):
    await seed_catalogs(db)
    await db.execute(delete(Tone).where(Tone.code == "playful"))
    await db.commit()

    counts = await seed_catalogs(db)

    assert counts == {**dict.fromkeys(EXPECTED_FIRST_RUN, 0), "tones": 1}
    tone = (
        await db.execute(select(Tone).where(Tone.code == "playful"))
    ).scalar_one()
    assert tone.label == "Playful"
    assert tone.description == "light and fun"


async def test_seed_rows_have_unique_primary_keys(db):
    # A duplicate key inside the constants would be swallowed by
    # ON CONFLICT DO NOTHING: the seeder would report fewer rows than the
    # list contains and the missing catalog entry would never be noticed.
    assert len({row["code"] for row in TONES}) == len(TONES)
    assert len({row["code"] for row in DIALECTS}) == len(DIALECTS)
    assert len({row["id"] for row in STRATEGIES}) == len(STRATEGIES)
    assert len({row["id"] for row in VOICE_MODELS}) == len(VOICE_MODELS)


async def test_seeded_strategy_is_usable_by_the_engine(db):
    # The strategy rows must carry the fields matching reads, not just ids:
    # selection filters on conditions/priority and generation reads
    # instructions.
    await seed_catalogs(db)

    strategy = (
        await db.execute(
            select(ResponseStrategy).where(
                ResponseStrategy.id == "apologize_for_issue"
            )
        )
    ).scalar_one()
    assert strategy.enabled is True
    assert strategy.priority == 80
    assert "negative" in strategy.conditions["sentiments"]
    assert strategy.instructions
