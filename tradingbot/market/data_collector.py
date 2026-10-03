import pandas as pd
from typing import Optional
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
            
            # Save to dataset for future ML training
            self._save_to_db(df, symbol, timeframe)
            
            log.info(f"Successfully collected and processed {len(df)} rows of data for {symbol}")
            return df
            
        except Exception as e:
            log.error(f"Failed to collect historical data for {symbol}: {e}")
            # Depending on use-case, you might want to raise the exception or return empty df
            raise

    def _save_to_db(self, df: pd.DataFrame, symbol: str, timeframe: str):
        """Guarda nuevas velas en la base de datos SQLite para ML (ignora duplicados)."""
        session = DatabaseSession.get_session()
        try:
            # Check the latest timestamp in DB for this symbol/timeframe
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
