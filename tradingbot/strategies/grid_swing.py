"""
tradingbot/strategies/grid_swing.py

Estrategia cuantitativa Grid/Swing Trading basada en Bandas de Bollinger y RSI.
Especializada para activos de alta liquidez y lateralidad en rangos delimitados
(como BNB/USDT y XRP/USDT en velas de 15m/1h).

Reglas de Generación de Señales:
- BUY:
    1. Precio de cierre toca o perfora la Banda Inferior de Bollinger (Close <= Lower Band).
    2. RSI(14) en zona de sobreventa o agotamiento bajista (RSI <= 38.0).
- SELL:
    1. Precio de cierre toca o supera la Banda Superior de Bollinger (Close >= Upper Band).
    2. O RSI(14) en zona de sobrecompra (RSI >= 65.0).
- HOLD:
    En cualquier otra condición intermedia de mercado.
"""

import pandas as pd
import numpy as np
from tradingbot.strategies.base_strategy import BaseStrategy
from tradingbot.utils.logger import log


class GridSwingStrategy(BaseStrategy):
    """
    Estrategia de reversión a la media / swing en canales para SwingGridAgent.
    """

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 38.0,
        rsi_overbought: float = 65.0,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        log.info(
            f"Initialized GridSwingStrategy | BB({bb_period}, {bb_std}) | "
            f"RSI({rsi_period}, OS={rsi_oversold}, OB={rsi_overbought})"
        )

    def _compute_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        """Calcula el Relative Strength Index (RSI) clásico de Wilder."""
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        # Promedio exponencial con alpha = 1 / period (Wilder smoothing)
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.fillna(50.0)

    def generate_signal(self, df: pd.DataFrame) -> str:
        """
        Analiza el DataFrame OHLCV y retorna 'BUY', 'SELL' o 'HOLD'.
        """
        if df is None or df.empty:
            log.warning("GridSwingStrategy: DataFrame vacío o None.")
            return "HOLD"

        min_required = max(self.bb_period, self.rsi_period) + 2
        if len(df) < min_required:
            log.warning(
                f"GridSwingStrategy: Datos insuficientes ({len(df)} filas, requeridas {min_required})."
            )
            return "HOLD"

        close_col = "close" if "close" in df.columns else "Close"
        if close_col not in df.columns:
            log.error(f"GridSwingStrategy: Columna de cierre no encontrada en {list(df.columns)}")
            return "HOLD"

        close_series = df[close_col].astype(float)

        # 1. Bandas de Bollinger (SMA + k*sigma)
        sma = close_series.rolling(window=self.bb_period).mean()
        std = close_series.rolling(window=self.bb_period).std(ddof=0)
        upper_band = sma + (self.bb_std * std)
        lower_band = sma - (self.bb_std * std)

        # 2. RSI (14)
        rsi_series = self._compute_rsi(close_series, period=self.rsi_period)

        curr_close = close_series.iloc[-1]
        curr_lower = lower_band.iloc[-1]
        curr_upper = upper_band.iloc[-1]
        curr_rsi = rsi_series.iloc[-1]

        if pd.isna(curr_lower) or pd.isna(curr_upper) or pd.isna(curr_rsi):
            return "HOLD"

        # Señal de Compra: Precio en o bajo la banda inferior con RSI en sobreventa
        if curr_close <= curr_lower * 1.002 and curr_rsi <= self.rsi_oversold:
            log.info(
                f"[GridSwing BUY] Close {curr_close:.4f} <= LowerBand {curr_lower:.4f} | "
                f"RSI {curr_rsi:.1f} <= {self.rsi_oversold}"
            )
            return "BUY"

        # Señal de Venta / Cierre Swing: Precio en o sobre la banda superior o RSI sobrecomprado
        if curr_close >= curr_upper * 0.998 or curr_rsi >= self.rsi_overbought:
            log.info(
                f"[GridSwing SELL] Close {curr_close:.4f} >= UpperBand {curr_upper:.4f} | "
                f"RSI {curr_rsi:.1f} >= {self.rsi_overbought}"
            )
            return "SELL"

        return "HOLD"
