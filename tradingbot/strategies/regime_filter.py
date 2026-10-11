"""
tradingbot/strategies/regime_filter.py

Filtro Cuantitativo de Régimen de Mercado para Mitigación de Decaimiento de Alfa (Alpha Decay).
Implementa cálculos vectorizados de alta eficiencia (NumPy / Pandas) para:
1. Choppiness Index (CHOP - 14): Detecta si el mercado está en rango caótico o en tendencia.
2. Average Directional Index (ADX - 14): Mide la fuerza intrínseca de la inercia del movimiento.

Reglas Cuantitativas:
- Si CHOP > 61.8: Mercado lateral/consolidación errática -> BLOQUEO DE ENTRADA.
- Si ADX <= 22.0: Falta de inercia direccional (falsos rompimientos) -> BLOQUEO DE ENTRADA.
- Si CHOP <= 61.8 y ADX > 22.0: Régimen tendencial saludable -> ENTRADA AUTORIZADA.
"""

import numpy as np
import pandas as pd
from typing import Tuple, Dict, Any
from tradingbot.utils.logger import log


class MarketRegimeFilter:
    """
    Filtro de régimen cuantitativo para eliminar compras en fases de compresión lateral o ruido.
    """

    @staticmethod
    def calculate_chop(df: pd.DataFrame, period: int = 14) -> float:
        """
        Calcula el Choppiness Index (CHOP) para la última vela.
        CHOP = 100 * log10( sum(ATR(1)_14) / (max(High_14) - min(Low_14)) ) / log10(14)
        """
        if len(df) < period + 1:
            return 50.0  # Valor neutral por defecto si faltan datos

        high = df['high'].values
        low = df['low'].values
        close = df['close'].values

        # 1. True Range para cada vela
        tr1 = high[1:] - low[1:]
        tr2 = np.abs(high[1:] - close[:-1])
        tr3 = np.abs(low[1:] - close[:-1])
        tr = np.maximum(tr1, np.maximum(tr2, tr3))

        if len(tr) < period:
            return 50.0

        # Ventana de los últimos `period` valores
        recent_tr_sum = np.sum(tr[-period:])
        recent_max_high = np.max(high[-period:])
        recent_min_low = np.min(low[-period:])

        range_hl = recent_max_high - recent_min_low
        if range_hl <= 0:
            return 100.0  # Rango nulo = máxima lateralidad

        chop = 100.0 * (np.log10(recent_tr_sum / range_hl) / np.log10(period))
        return float(np.clip(chop, 0.0, 100.0))

    @staticmethod
    def calculate_adx(df: pd.DataFrame, period: int = 14) -> float:
        """
        Calcula el Average Directional Index (ADX) según la formulación estándar de Welles Wilder.
        """
        if len(df) < (period * 2):
            # Retorna valor moderado si el histórico es corto
            return 25.0

        high = df['high'].values
        low = df['low'].values
        close = df['close'].values

        # Movimientos direccionales
        up_move = high[1:] - high[:-1]
        down_move = low[:-1] - low[1:]

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        # True Range
        tr1 = high[1:] - low[1:]
        tr2 = np.abs(high[1:] - close[:-1])
        tr3 = np.abs(low[1:] - close[:-1])
        tr = np.maximum(tr1, np.maximum(tr2, tr3))

        # Suavizado exponencial de Wilder (alpha = 1 / period)
        # Inicializar primeras sumas
        tr_smooth = np.zeros(len(tr))
        pdm_smooth = np.zeros(len(plus_dm))
        mdm_smooth = np.zeros(len(minus_dm))

        tr_smooth[period - 1] = np.sum(tr[:period])
        pdm_smooth[period - 1] = np.sum(plus_dm[:period])
        mdm_smooth[period - 1] = np.sum(minus_dm[:period])

        for i in range(period, len(tr)):
            tr_smooth[i] = tr_smooth[i - 1] - (tr_smooth[i - 1] / period) + tr[i]
            pdm_smooth[i] = pdm_smooth[i - 1] - (pdm_smooth[i - 1] / period) + plus_dm[i]
            mdm_smooth[i] = mdm_smooth[i - 1] - (mdm_smooth[i - 1] / period) + minus_dm[i]

        # Calcular +DI y -DI evitando división por cero
        safe_tr = np.where(tr_smooth == 0, 1e-9, tr_smooth)
        plus_di = 100.0 * (pdm_smooth / safe_tr)
        minus_di = 100.0 * (mdm_smooth / safe_tr)

        di_sum = plus_di + minus_di
        safe_di_sum = np.where(di_sum == 0, 1e-9, di_sum)
        dx = 100.0 * (np.abs(plus_di - minus_di) / safe_di_sum)

        # Suavizado de DX para obtener ADX
        if len(dx) < period * 2 - 1:
            return float(dx[-1])

        adx = np.zeros(len(dx))
        start_idx = period * 2 - 2
        adx[start_idx] = np.mean(dx[period - 1:start_idx + 1])

        for i in range(start_idx + 1, len(dx)):
            adx[i] = ((adx[i - 1] * (period - 1)) + dx[i]) / period

        return float(np.clip(adx[-1], 0.0, 100.0))

    @classmethod
    def evaluate_regime(
        cls,
        df: pd.DataFrame,
        chop_max: float = 61.8,
        adx_min: float = 22.0
    ) -> Tuple[bool, str, Dict[str, float]]:
        """
        Evalúa el régimen del mercado para la última vela disponible.
        Retorna:
            (is_tradeable, reason, metrics_dict)
        """
        if df is None or len(df) < 15:
            return True, "Histórico insuficiente para cálculo de régimen (Permitido)", {"chop": 50.0, "adx": 25.0}

        try:
            chop = cls.calculate_chop(df, period=14)
            adx = cls.calculate_adx(df, period=14)
            metrics = {"chop": round(chop, 2), "adx": round(adx, 2)}

            # 1. Comprobar Choppiness Index (mercado lateral caótico)
            if chop > chop_max:
                return False, f"Mercado Lateral/Caótico (CHOP {chop:.1f} > {chop_max})", metrics

            # 2. Comprobar ADX (fuerza de la tendencia)
            if adx < adx_min:
                return False, f"Tendencia Débil/Sin Momentum (ADX {adx:.1f} < {adx_min})", metrics

            return True, f"Régimen Tendencial Robusto (CHOP {chop:.1f}, ADX {adx:.1f})", metrics
        except Exception as e:
            log.warning(f"[RegimeFilter] Error evaluando régimen de mercado: {e}")
            return True, f"Filtro de régimen omitido por error: {e}", {"chop": 50.0, "adx": 25.0}
