import pandas as pd
from tradingbot.strategies.base_strategy import BaseStrategy
from tradingbot.utils.logger import log


class EMAMacroStrategy(BaseStrategy):
    """
    EMA Macro Strategy — Golden/Death Cross institucional.

    Diseñada específicamente para BTC/ETH con timeframes de 15m y 1h.

    Características:
    - EMA 50 / EMA 200 (periodos configurables)
    - Filtro de volumen: confirma señal solo si volumen > avg(20 velas)
    - Zona de ruido: ignora cruces dentro del ±0.3% del precio
    - Genera ~2-5 señales/mes con ~20-25% falsas (vs ~70% de EMA 9/21)

    Aplicada en: SubAgent 4 — MacroTrader BTC/ETH
    Recomendación #4 del informe: EMA 50/200 sobre EMA 21/55 por mayor
    precisión y menor costo de comisiones en activos de rango diario ~1%.
    """

    def __init__(
        self,
        fast_period: int = 50,
        slow_period: int = 200,
        volume_filter: bool = True,
        noise_filter_pct: float = 0.003,  # Ignora cruces dentro del ±0.3%
    ):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.volume_filter = volume_filter
        self.noise_filter_pct = noise_filter_pct
        log.info(
            f"Initialized EMAMacroStrategy: EMA{fast_period}/{slow_period}, "
            f"volume_filter={volume_filter}, noise_filter={noise_filter_pct*100:.1f}%"
        )

    def generate_signal(self, df: pd.DataFrame) -> str:
        """
        Analiza un DataFrame OHLCV y retorna señal de trading basada en
        Golden/Death Cross de EMA 50/200 con confirmación de volumen.

        Args:
            df: DataFrame con columnas OHLCV (open, high, low, close, volume)

        Returns:
            "BUY"  — Golden Cross confirmado (EMA50 cruza sobre EMA200)
            "SELL" — Death Cross confirmado (EMA50 cruza bajo EMA200)
            "HOLD" — Sin señal o en zona de ruido
        """
        if df is None or df.empty:
            log.warning("EMAMacroStrategy: DataFrame vacío recibido.")
            return "HOLD"

        # Necesitamos al menos slow_period + 1 velas para calcular la EMA lenta
        if len(df) < self.slow_period + 1:
            log.warning(
                f"EMAMacroStrategy: Datos insuficientes. "
                f"Necesario: {self.slow_period + 1}, Disponible: {len(df)}"
            )
            return "HOLD"

        close_col = "close" if "close" in df.columns else "Close"
        if close_col not in df.columns:
            log.error(f"EMAMacroStrategy: Columna 'close' no encontrada. Columnas: {list(df.columns)}")
            return "HOLD"

        # Calcular EMA fast y slow
        fast_ema = df[close_col].ewm(span=self.fast_period, adjust=False).mean()
        slow_ema = df[close_col].ewm(span=self.slow_period, adjust=False).mean()

        curr_fast = fast_ema.iloc[-1]
        curr_slow = slow_ema.iloc[-1]
        prev_fast = fast_ema.iloc[-2]
        prev_slow = slow_ema.iloc[-2]

        if any(pd.isna(v) for v in [curr_fast, curr_slow, prev_fast, prev_slow]):
            return "HOLD"

        # --- Filtro de zona de ruido ---
        # Ignora cruces cuando la diferencia EMA fast/slow es menor al noise_filter_pct
        # Esto evita whipsaws por oscilaciones mínimas del precio
        current_price = float(df[close_col].iloc[-1])
        ema_gap_pct = abs(curr_fast - curr_slow) / current_price
        if ema_gap_pct < self.noise_filter_pct:
            log.info(
                f"EMAMacroStrategy: Dentro de zona de ruido "
                f"(gap EMA: {ema_gap_pct*100:.3f}% < {self.noise_filter_pct*100:.1f}%). HOLD."
            )
            return "HOLD"

        # --- Filtro de volumen ---
        # Confirma la señal solo si el volumen de la vela actual supera
        # el promedio de las últimas 20 velas (evita cruces muertos sin liquidez)
        volume_confirms = True
        if self.volume_filter and "volume" in df.columns:
            vol_avg = df["volume"].rolling(20).mean().iloc[-1]
            current_vol = df["volume"].iloc[-1]
            volume_confirms = current_vol > vol_avg
            if not volume_confirms:
                log.info(
                    f"EMAMacroStrategy: Volumen insuficiente para confirmar señal. "
                    f"Vol actual: {current_vol:.2f}, Avg20: {vol_avg:.2f}"
                )

        # --- Golden Cross (BUY): EMA50 cruza sobre EMA200 ---
        if curr_fast > curr_slow and prev_fast <= prev_slow and volume_confirms:
            log.info(
                f"EMAMacroStrategy: GOLDEN CROSS ✅ BUY | "
                f"EMA{self.fast_period}={curr_fast:.4f} > EMA{self.slow_period}={curr_slow:.4f} | "
                f"Vol confirmado: {volume_confirms}"
            )
            return "BUY"

        # --- Death Cross (SELL): EMA50 cruza bajo EMA200 ---
        elif curr_fast < curr_slow and prev_fast >= prev_slow and volume_confirms:
            log.info(
                f"EMAMacroStrategy: DEATH CROSS ✅ SELL | "
                f"EMA{self.fast_period}={curr_fast:.4f} < EMA{self.slow_period}={curr_slow:.4f} | "
                f"Vol confirmado: {volume_confirms}"
            )
            return "SELL"

        return "HOLD"
