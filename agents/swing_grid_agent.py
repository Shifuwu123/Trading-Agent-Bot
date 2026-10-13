"""
agents/swing_grid_agent.py

SubAgent: Swing / Grid Trading
Monedas: BNB/USDT, XRP/USDT (Transferidas desde Scalper Tier 1)
Configuración: configs/agent_swing_grid.yaml
Estrategia: GridSwingStrategy (Bandas de Bollinger 20, 2.0 + RSI 14)
"""
from agents.base_agent import BaseAgent
from tradingbot.strategies.grid_swing import GridSwingStrategy
from tradingbot.utils.logger import log


class SwingGridAgent(BaseAgent):
    """
    SubAgent Swing & Grid Trading.

    Especializado en activos de alta liquidez y capitalización de mercado
    con movimientos de canal y oscilación predecible en velas de 15m/1h (BNB y XRP).
    Modo TARGET: busca tomas de ganancia institucionales al +2.5% sin cortes por tiempo prematuros.
    Capital: 20% del total.
    """

    def _build_strategy(self) -> GridSwingStrategy:
        """Construye GridSwingStrategy con soporte para dict u objeto de configuración."""
        strategy_cfg = getattr(self.config, "strategies", None)
        bb_period, bb_std = 20, 2.0
        rsi_period, rsi_oversold, rsi_overbought = 14, 38.0, 65.0

        if isinstance(strategy_cfg, dict):
            grid_cfg = strategy_cfg.get("grid_swing", {})
            if isinstance(grid_cfg, dict):
                bb_period = grid_cfg.get("bb_period", 20)
                bb_std = grid_cfg.get("bb_std", 2.0)
                rsi_period = grid_cfg.get("rsi_period", 14)
                rsi_oversold = grid_cfg.get("rsi_oversold", 38.0)
                rsi_overbought = grid_cfg.get("rsi_overbought", 65.0)
        elif strategy_cfg and hasattr(strategy_cfg, "grid_swing"):
            grid_cfg = strategy_cfg.grid_swing
            bb_period = getattr(grid_cfg, "bb_period", 20)
            bb_std = getattr(grid_cfg, "bb_std", 2.0)
            rsi_period = getattr(grid_cfg, "rsi_period", 14)
            rsi_oversold = getattr(grid_cfg, "rsi_oversold", 38.0)
            rsi_overbought = getattr(grid_cfg, "rsi_overbought", 65.0)

        log.info(
            f"[SwingGridAgent] Estrategia: Bollinger({bb_period}, {bb_std}) + RSI({rsi_period})"
        )
        return GridSwingStrategy(
            bb_period=bb_period,
            bb_std=bb_std,
            rsi_period=rsi_period,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
        )
