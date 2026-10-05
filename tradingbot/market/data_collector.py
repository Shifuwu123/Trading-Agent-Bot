import pandas as pd
import ccxt
from typing import Optional
from decimal import Decimal
from sqlalchemy import select
from tradingbot.market.connector import ExchangeConnector
from tradingbot.utils.logger import log
from tradingbot.database.models import Candle
from tradingbot.execution.portfolio_manager import DatabaseSession

class DataCollector:
    """
    DataCollector fetches market data via the ExchangeConnector and processes it.
    """
    
    def __init__(self, connector: ExchangeConnector):
        self.connector = connector
        log.info("Initialized DataCollector")

    async def get_historical_data(
        self, symbol: str, timeframe: str, since: Optional[int] = None, limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Fetches OHLCV data from the connector and returns a pandas DataFrame.
        """
        log.info(f"Collecting historical data for {symbol} (timeframe: {timeframe})")
        
        try:
            ohlcv = await self.connector.fetch_ohlcv(symbol, timeframe, since, limit)
            
            if not ohlcv:
                log.warning(f"No OHLCV data found for {symbol}")
                return pd.DataFrame()
                
            # Create a DataFrame from the raw OHLCV list
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Convert timestamp from milliseconds to a readable datetime format
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # Set the timestamp as the DataFrame index
            df.set_index('timestamp', inplace=True)
            
            # Save to dataset for future ML training asynchronously
            await self._save_to_db_async(df, symbol, timeframe)
            
            log.info(f"Successfully collected and processed {len(df)} rows of data for {symbol}")
            return df
            
        except (ccxt.RequestTimeout, ccxt.NetworkError) as e:
            log.warning(f"Conectividad transitoria fallida al obtener velas para {symbol} ({timeframe}): {e}")
            raise
        except Exception as e:
            log.error(f"Failed to collect historical data for {symbol}: {e}")
            raise

    async def _save_to_db_async(self, df: pd.DataFrame, symbol: str, timeframe: str):
        """Guarda nuevas velas en la base de datos de forma asíncrona para ML (ignora duplicados)."""
        try:
            async with DatabaseSession.get_async_session() as session:
                result = await session.execute(
                    select(Candle).filter(
                        Candle.symbol == symbol,
                        Candle.timeframe == timeframe
                    ).order_by(Candle.timestamp.desc()).limit(1)
                )
                latest_candle = result.scalars().first()
                latest_ts = latest_candle.timestamp if latest_candle else None

                if latest_ts:
                    df_new = df[df.index > latest_ts].copy()
                else:
                    df_new = df.copy()

                if not df_new.empty:
                    candles = [
                        Candle(
                            symbol=symbol,
                            timeframe=timeframe,
                            timestamp=ts.to_pydatetime() if hasattr(ts, 'to_pydatetime') else ts,
                            open=Decimal(str(row['open'])),
                            high=Decimal(str(row['high'])),
                            low=Decimal(str(row['low'])),
                            close=Decimal(str(row['close'])),
                            volume=Decimal(str(row['volume']))
                        )
                        for ts, row in df_new.iterrows()
                    ]
                    session.add_all(candles)
                    await session.commit()
                    log.info(f"[AsyncDB] Saved {len(candles)} new historical candles to dataset for {symbol}")
        except Exception as e:
            log.error(f"[AsyncDB] Failed to save ML dataset: {e}")

    def _save_to_db(self, df: pd.DataFrame, symbol: str, timeframe: str):
        """Guarda nuevas velas en la base de datos (fallback sincrónico)."""
        session = DatabaseSession.get_session()
        try:
            latest_candle = session.query(Candle).filter(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe
            ).order_by(Candle.timestamp.desc()).first()
            
            latest_ts = latest_candle.timestamp if latest_candle else None
            
            if latest_ts:
                df_new = df[df.index > latest_ts].copy()
            else:
                df_new = df.copy()

            if not df_new.empty:
                df_new['timestamp'] = df_new.index.to_pydatetime()
                df_new['symbol'] = symbol
                df_new['timeframe'] = timeframe
                
                records = df_new.to_dict(orient='records')
                session.bulk_insert_mappings(Candle, records)
                session.commit()
                log.info(f"Saved {len(records)} new historical candles to dataset for {symbol}")
        except Exception as e:
            session.rollback()
            log.error(f"Failed to save ML dataset: {e}")
        finally:
            session.close()
