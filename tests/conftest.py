import os
import tempfile
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from tradingbot.core.config import get_settings
from tradingbot.database.models import Base, DigitalWallet
from tradingbot.execution.portfolio_manager import DatabaseSession


@pytest.fixture(scope="session", autouse=True)
def setup_isolated_test_database():
    """
    Fixture de sesión que aísla completamente la base de datos de pruebas
    de la base de datos de producción (tradingbot.db).
    Crea una base de datos SQLite temporal y configura DatabaseSession para usarla.
    """
    # Crear archivo temporal para SQLite de prueba
    temp_db_fd, temp_db_path = tempfile.mkstemp(prefix="test_tradingbot_", suffix=".db")
    os.close(temp_db_fd)

    sync_url = f"sqlite:///{temp_db_path}"
    async_url = f"sqlite+aiosqlite:///{temp_db_path}"

    # Sobrescribir database_url en settings
    settings = get_settings()
    settings.database_url = sync_url

    # Resetear instancias previas de DatabaseSession
    DatabaseSession._engine = None
    DatabaseSession._SessionLocal = None
    DatabaseSession._async_engine = None
    DatabaseSession._AsyncSessionLocal = None

    # Configurar motores aislados
    sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False, "timeout": 15})
    
    @event.listens_for(sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        except Exception:
            pass

    Base.metadata.create_all(bind=sync_engine)

    # Migraciones ligeras
    with sync_engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE trades ADD COLUMN dca_step INTEGER DEFAULT 1"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE trades ADD COLUMN exit_reason TEXT"))
            conn.commit()
        except Exception:
            pass

        # Seed initial wallet
        conn.execute(text("INSERT OR REPLACE INTO digital_wallet (id, telegram_id, balance_usd, is_paper) VALUES (1, '1676283475', 16.0, 1)"))
        conn.commit()

    async_engine = create_async_engine(async_url, connect_args={"timeout": 15}, echo=False)

    DatabaseSession._engine = sync_engine
    DatabaseSession._SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)
    DatabaseSession._async_engine = async_engine
    DatabaseSession._AsyncSessionLocal = async_sessionmaker(
        bind=async_engine,
        expire_on_commit=False,
        class_=AsyncSession
    )

    yield

    # Teardown
    try:
        sync_engine.dispose()
    except Exception:
        pass
    if os.path.exists(temp_db_path):
        try:
            os.remove(temp_db_path)
        except Exception:
            pass
