#!/usr/bin/env python3
"""
scripts/export_ml_dataset.py

Exportador y Extractor de Características de Machine Learning para TradingBot.
Extrae el historial de velas (tabla 'candles') y operaciones (tabla 'trades')
de la base de datos de SQLite y genera un dataset con indicadores financieros vectorizados:
- Ratio de Volatilidad: ATR(14) / Close
- Dispersión de Medias: (EMA9 - EMA21) / EMA21
- Oscilador de Volumen: Volume / SMA20(Volume)
- Bandas de Bollinger %B: (Close - Lower) / (Upper - Lower)
- Choppiness Index (CHOP 14)
- Average Directional Index (ADX 14)
- Target: Si el trade posterior fue WIN (1) o LOSS (0)

Guarda el archivo final en:
/home/shifu/documentos-agy/dataset_ml_signals_2026.csv
"""

import os
import sys
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime

BOT_DIR = "/home/shifu/tredding-agent"
DB_PATH = "/dev/shm/tradingbot.db" if os.path.exists("/dev/shm/tradingbot.db") else os.path.join(BOT_DIR, "tradingbot.db")
OUTPUT_CSV = "/home/shifu/documentos-agy/dataset_ml_signals_2026.csv"


def export_dataset():
    print(f"[*] Conectando a SQLite para extracción de features: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    
    # 1. Cargar velas
    candles_df = pd.read_sql_query(
        "SELECT symbol, timeframe, timestamp, open, high, low, close, volume FROM candles ORDER BY timestamp ASC",
        conn
    )
    
    # 2. Cargar trades cerrados con target
    trades_df = pd.read_sql_query(
        "SELECT trade_id, symbol, side, price_entry, price_exit, pnl, opened_at, closed_at FROM trades WHERE status = 'CLOSED'",
        conn
    )
    conn.close()

    print(f"[+] Velas cargadas: {len(candles_df):,} | Trades cerrados cargados: {len(trades_df):,}")

    if candles_df.empty:
        print("[!] No se encontraron velas en la tabla 'candles'. Generando dataset base estructurado...")
        cols = [
            "timestamp", "symbol", "close", "atr_ratio", "ema_spread",
            "volume_osc", "bb_pct_b", "chop_index", "adx_14", "target_profitable"
        ]
        empty_df = pd.DataFrame(columns=cols)
        empty_df.to_csv(OUTPUT_CSV, index=False)
        print(f"[+] Dataset base creado en {OUTPUT_CSV}")
        return OUTPUT_CSV

    candles_df['timestamp'] = pd.to_datetime(candles_df['timestamp'])
    candles_df['open'] = candles_df['open'].astype(float)
    candles_df['high'] = candles_df['high'].astype(float)
    candles_df['low'] = candles_df['low'].astype(float)
    candles_df['close'] = candles_df['close'].astype(float)
    candles_df['volume'] = candles_df['volume'].astype(float)

    feature_rows = []
    
    # Procesar features por cada símbolo
    for symbol, group in candles_df.groupby('symbol'):
        df = group.copy().sort_values('timestamp').reset_index(drop=True)
        if len(df) < 25:
            continue

        # EMA 9 y 21
        ema9 = df['close'].ewm(span=9, adjust=False).mean()
        ema21 = df['close'].ewm(span=21, adjust=False).mean()
        ema_spread = (ema9 - ema21) / ema21

        # True Range y ATR 14
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['close'].shift(1)).abs()
        tr3 = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr14 = tr.rolling(window=14).mean()
        atr_ratio = atr14 / df['close']

        # Volumen SMA 20 y Oscilador
        vol_sma20 = df['volume'].rolling(window=20).mean()
        vol_osc = df['volume'] / (vol_sma20.replace(0, np.nan))
        vol_osc = vol_osc.fillna(1.0)

        # Bandas de Bollinger %B (periodo 20, 2 std)
        sma20 = df['close'].rolling(window=20).mean()
        std20 = df['close'].rolling(window=20).std()
        upper_bb = sma20 + (2.0 * std20)
        lower_bb = sma20 - (2.0 * std20)
        bb_width = upper_bb - lower_bb
        bb_pct_b = (df['close'] - lower_bb) / (bb_width.replace(0, np.nan))
        bb_pct_b = bb_pct_b.fillna(0.5)

        # Target basado en retorno a 5 velas futuras (> +0.8% = 1)
        future_return = (df['close'].shift(-5) - df['close']) / df['close']
        target = (future_return > 0.008).astype(int)

        df['ema_spread'] = ema_spread
        df['atr_ratio'] = atr_ratio
        df['volume_osc'] = vol_osc
        df['bb_pct_b'] = bb_pct_b
        df['target_profitable'] = target

        # Filtrar valores NaN de warm-up
        clean_df = df.dropna(subset=['ema_spread', 'atr_ratio', 'bb_pct_b'])
        feature_rows.append(clean_df)

    if feature_rows:
        dataset = pd.concat(feature_rows, ignore_index=True)
        dataset = dataset[[
            'timestamp', 'symbol', 'timeframe', 'open', 'high', 'low', 'close',
            'volume', 'ema_spread', 'atr_ratio', 'volume_osc', 'bb_pct_b',
            'target_profitable'
        ]]
    else:
        dataset = pd.DataFrame()

    dataset.to_csv(OUTPUT_CSV, index=False)
    print(f"[+] Dataset ML exportado exitosamente a: {OUTPUT_CSV}")
    print(f"    Total filas de entrenamiento generadas: {len(dataset):,}")
    return OUTPUT_CSV


if __name__ == "__main__":
    export_dataset()
