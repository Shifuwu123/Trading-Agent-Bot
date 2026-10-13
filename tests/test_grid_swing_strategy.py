"""
tests/test_grid_swing_strategy.py

Pruebas cuantitativas y algorítmicas de la estrategia GridSwingStrategy (Bollinger + RSI).
"""

import pandas as pd
import numpy as np
from tradingbot.strategies.grid_swing import GridSwingStrategy


def test_grid_swing_insufficient_data():
    strat = GridSwingStrategy(bb_period=20, bb_std=2.0, rsi_period=14)
    # Menos de 22 filas
    df = pd.DataFrame({"close": [100.0] * 10})
    assert strat.generate_signal(df) == "HOLD"
    assert strat.generate_signal(None) == "HOLD"
    assert strat.generate_signal(pd.DataFrame()) == "HOLD"


def test_grid_swing_buy_signal():
    strat = GridSwingStrategy(
        bb_period=20,
        bb_std=2.0,
        rsi_period=14,
        rsi_oversold=38.0,
        rsi_overbought=65.0
    )

    # Crear serie de 30 velas donde el precio se mantiene estable y al final cae abruptamente perforando la banda inferior
    prices = [100.0] * 25 + [98.0, 95.0, 90.0, 85.0, 75.0]
    df = pd.DataFrame({"close": prices})

    signal = strat.generate_signal(df)
    assert signal == "BUY"


def test_grid_swing_sell_signal():
    strat = GridSwingStrategy(
        bb_period=20,
        bb_std=2.0,
        rsi_period=14,
        rsi_oversold=38.0,
        rsi_overbought=65.0
    )

    # Crear serie de 30 velas donde el precio explota hacia arriba perforando la banda superior con RSI sobrecomprado
    prices = [100.0] * 25 + [102.0, 105.0, 110.0, 118.0, 130.0]
    df = pd.DataFrame({"close": prices})

    signal = strat.generate_signal(df)
    assert signal == "SELL"


def test_grid_swing_hold_signal_in_equilibrium():
    strat = GridSwingStrategy(
        bb_period=20,
        bb_std=2.0,
        rsi_period=14,
        rsi_oversold=38.0,
        rsi_overbought=65.0
    )

    # Precios oscilando levemente en el centro del canal (SMA 100)
    prices = [100.0 + (i % 2) * 0.5 for i in range(35)]
    df = pd.DataFrame({"close": prices})

    signal = strat.generate_signal(df)
    assert signal == "HOLD"
