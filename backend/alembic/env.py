import sys
from pathlib import Path

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# 把backend目录加入path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import Base, get_sync_engine
import models  # 确保所有模型被导入

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    url = "postgresql://photonteck:photonteck@localhost:5432/photonteck"
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = get_sync_engine()
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
