"""
tests/test_db_test_shield.py

Pruebas automatizadas para certificar el blindaje Fail-Safe de la base de datos (Test DB Shield).
Garantiza que ninguna prueba pueda conectarse por error a tradingbot.db ni a la base en RAM.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from tradingbot.execution.portfolio_manager import DatabaseSession


def test_database_session_shield_blocks_production_db():
    """
    Verifica que DatabaseSession.initialize() lance un RuntimeError bloqueante
    si detecta que la URL apunta a tradingbot.db durante la ejecución de pytest.
    """
    mock_settings = MagicMock()
    mock_settings.database_url = "sqlite:////home/shifu/tredding-agent/tradingbot.db"

    with patch("tradingbot.execution.portfolio_manager.get_settings", return_value=mock_settings):
        # Aseguramos que DatabaseSession no tenga engine activo para forzar initialize()
        old_engine = DatabaseSession._engine
        try:
            DatabaseSession._engine = None
            with pytest.raises(RuntimeError) as exc_info:
                DatabaseSession.initialize()
            assert "FATAL TEST SHIELD" in str(exc_info.value)
            assert "tradingbot.db" in str(exc_info.value)
        finally:
            DatabaseSession._engine = old_engine


def test_database_session_shield_blocks_ram_db():
    """
    Verifica que también bloquee intentos de conexión a la base de datos viva en /dev/shm.
    """
    mock_settings = MagicMock()
    mock_settings.database_url = "sqlite:////dev/shm/tradingbot.db"

    with patch("tradingbot.execution.portfolio_manager.get_settings", return_value=mock_settings):
        old_engine = DatabaseSession._engine
        try:
            DatabaseSession._engine = None
            with pytest.raises(RuntimeError) as exc_info:
                DatabaseSession.initialize()
            assert "FATAL TEST SHIELD" in str(exc_info.value)
        finally:
            DatabaseSession._engine = old_engine
