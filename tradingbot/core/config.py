import yaml
import os
from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from typing import List, Optional

class ActiveHoursConfig(BaseModel):
    start: int = 13
    end: int = 17

class DynamicTimeframeConfig(BaseModel):
    enabled: bool = False
    active_hours_utc: ActiveHoursConfig = ActiveHoursConfig()
    active_timeframe: str = "1m"
    passive_timeframe: str = "5m"

class BotConfig(BaseModel):
    name: str = "TradingBot"
    mode: str = "passive"
    trading_mode: str = "trend"
    trading_pairs: List[str]
    timeframe: str = "1m"
    dynamic_timeframe: Optional[DynamicTimeframeConfig] = None
    base_currency: str = "USDT"
    fiat_currency: str = "CLP"

class RiskConfig(BaseModel):
    max_open_positions: int = 3
    max_capital_exposure_pct: float = 0.30
    reserve_capital_pct: float = 0.30
    max_loss_per_trade_pct: float = 0.02
    daily_loss_limit_pct: float = 0.05
    max_drawdown_pct: float = 0.20
    default_take_profit_pct: float = 0.04
    trailing_stop: bool = True
    trailing_stop_positive: float = 0.02

class AppConfig(BaseModel):
    bot: BotConfig
    risk: RiskConfig
    # Se pueden agregar strategies y scheduler después

class EnvSettings(BaseSettings):
    exchange_id: str = "binance"
    exchange_api_key: str = ""
    exchange_api_secret: str = ""
    exchange_testnet: bool = True
    
    database_url: str = "sqlite:///tradingbot.db"
    environment: str = "development"
    paper_trading: bool = True
    
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    
    base_log_dir: str = str(Path.home() / ".log")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

def load_yaml_config(file_path="config.yaml") -> AppConfig:
    with open(file_path, "r") as f:
        data = yaml.safe_load(f)
    return AppConfig(**data)

def get_settings() -> EnvSettings:
    return EnvSettings()
