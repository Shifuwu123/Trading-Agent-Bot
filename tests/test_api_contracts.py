"""
tests/test_api_contracts.py

Pruebas de contratos e interfaces entre Frontend (script.js), Backend (FastAPI / api.py)
y el Motor de Trading (OrchestratorBot / bot_commands).
"""

import sys
import os
import pytest
from httpx import AsyncClient, ASGITransport
from decimal import Decimal

# Asegurar path de ambos proyectos
sys.path.insert(0, "/home/shifu/dashboard-trading-bot")
sys.path.insert(0, "/home/shifu/tredding-agent")

from app.main import app
from app.routers.api import (
    StatsResponse, PortfolioItemResponse, DecisionLogResponse, CommandRequest, CommandResponse
)
from tradingbot.execution.portfolio_manager import DatabaseSession
from tradingbot.database.models import Trade, Portfolio, DigitalWallet, DecisionLog, BotCommand
from tradingbot.core.orchestrator import OrchestratorBot


@pytest.mark.asyncio
async def test_api_stats_contract():
    """Verifica que /api/stats cumpla estrictamente con el contrato esperado por script.js."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()

        # Validar contrato Pydantic
        stats = StatsResponse(**data)
        assert isinstance(stats.balance_usd, float)
        assert isinstance(stats.realized_pnl, float)
        assert isinstance(stats.unrealized_pnl, float)
        assert isinstance(stats.roi_pct, float)
        assert isinstance(stats.open_trades_count, int)
        assert stats.open_trades_count >= 0


@pytest.mark.asyncio
async def test_api_portfolio_contract():
    """Verifica que /api/portfolio retorne los campos exactos esperados por el render de tabla en script.js."""
    session = DatabaseSession.get_session()
    try:
        session.query(Portfolio).delete()
        p = Portfolio(
            asset="SOL",
            quantity=Decimal("0.5"),
            avg_price=Decimal("150.0"),
            current_price=Decimal("155.0"),
            unrealized_pnl=Decimal("2.5"),
            is_paper=True,
            agent_id="scalper_t1"
        )
        session.add(p)
        session.commit()
    finally:
        session.close()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/portfolio")
        assert response.status_code == 200
        data = response.json()

        assert len(data) >= 1
        item = PortfolioItemResponse(**data[0])
        assert item.symbol in ("SOL", "SOL/USDT")
        assert item.quantity == 0.5
        assert item.avg_entry == 150.0
        assert item.current_price == 155.0
        assert item.pnl == 2.5
        assert item.agent_id == "scalper_t1"


@pytest.mark.asyncio
async def test_api_logs_contract():
    """Verifica que /api/logs responda con lista ordenada y tipada."""
    session = DatabaseSession.get_session()
    try:
        session.query(DecisionLog).delete()
        dlog = DecisionLog(
            symbol="BTC/USDT",
            decision="HOLD",
            reason="Market flat EMA 9 == EMA 21"
        )
        session.add(dlog)
        session.commit()
    finally:
        session.close()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/logs?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        log_entry = DecisionLogResponse(**data[0])
        assert log_entry.symbol == "BTC/USDT"
        assert log_entry.decision == "HOLD"


@pytest.mark.asyncio
async def test_api_command_validation_and_bot_execution():
    """
    Verifica el flujo completo de comandos:
    1. Envío desde API con validación de comando permitido.
    2. Rechazo de comandos no autorizados o maliciosos.
    3. Encolado en bot_commands.
    4. Procesamiento y ejecución por OrchestratorBot.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # A. Comando malicioso o inválido debe ser rechazado (422)
        bad_res = await client.post("/api/command", json={"command": "DROP_DATABASE", "args": ""})
        assert bad_res.status_code == 422

        # B. Comando válido permitido (PAUSE)
        valid_res = await client.post("/api/command", json={"command": "PAUSE", "args": ""})
        assert valid_res.status_code == 200
        cmd_resp = CommandResponse(**valid_res.json())
        assert cmd_resp.status == "success"
        assert cmd_resp.command_id is not None

    # C. Verificar que OrchestratorBot procesa el comando
    orch = OrchestratorBot()
    assert orch.paused is False  # Estado inicial

    processed = orch.process_pending_db_commands()
    assert len(processed) >= 1
    p_cmd = [c for c in processed if c["command"] == "PAUSE"][0]
    assert p_cmd["status"] == "COMPLETED"
    assert orch.paused is True  # Efecto verificado en el motor

    # D. Enviar RESUME y procesar
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resume_res = await client.post("/api/command", json={"command": "RESUME", "args": ""})
        assert resume_res.status_code == 200

    processed_resume = orch.process_pending_db_commands()
    p_resume = [c for c in processed_resume if c["command"] == "RESUME"][0]
    assert p_resume["status"] == "COMPLETED"
    assert orch.paused is False
