import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

# load .env so os.getenv sees DATABASE_URL
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# import Base + all models so autogenerate sees them
from app.database import Base
from app.modules.users import models as users_models  # noqa: F401
from app.modules.tts import models as tts_models  # noqa: F401
from app.modules.stt import models as stt_models  # noqa: F401
from app.modules.llm import models as llm_models  # noqa: F401
from app.modules.channels import models as channels_models  # noqa: F401
from app.modules.rag import models as rag_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401

target_metadata = Base.metadata

# override sqlalchemy.url from .env
db_url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
config.set_main_option("sqlalchemy.url", db_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
