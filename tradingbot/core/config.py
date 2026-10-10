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

class TimeStopConfig(BaseModel):
    enabled: bool = True
    min_duration_minutes: int = 120        # Tiempo mínimo de maduración antes de evaluar salida
    consecutive_cycles_required: int = 3   # Seguro: 3 ciclos consecutivos cerrando en zona de pérdida
    max_loss_pct: float = 0.02             # Pérdida máxima acotada al ejecutar Time-Stop (-2.0%)
    hard_stop_loss_pct: float = 0.045      # Hard Stop de emergencia absoluta (flash crash: -4.5%)
    oversold_grace_enabled: bool = True    # Gracia si detecta rebote o sobreventa temporal

class MarketBiasConfig(BaseModel):
    enabled: bool = True
    btc_symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    ema_period: int = 50
    cache_ttl_seconds: int = 60

class ProfitHarvestConfig(BaseModel):
    enabled: bool = True
    threshold_pct: float = 1.00            # Ganancia umbral (+100%) para cosechar
    threshold_usd: float = 15.00           # Ganancia en USD mínima para cosechar
    harvest_ratio: float = 1.00            # 1.0 = liquidar posición completa de ganancia extraordinaria

class MicroDCAConfig(BaseModel):
    enabled: bool = True
    initial_tranche_pct: float = 0.5333    # Tramo 1: ~$0.40 USD de $0.75 USD
    pullback_tranche_pct: float = 0.4667   # Tramo 2: ~$0.35 USD de $0.75 USD
    pullback_min_pct: float = 0.006        # Retroceso mínimo -0.6% para gatillar Tramo 2
    pullback_max_pct: float = 0.025        # Retroceso máximo -2.5% para Tramo 2

class RiskConfig(BaseModel):
    max_open_positions: int = 20
    max_capital_exposure_pct: float = 0.30
    reserve_capital_pct: float = 0.30
    coin_reserve_pct: float = 0.25
    max_coin_order_pct: float = 0.75
    max_loss_per_trade_pct: float = 0.02
    daily_loss_limit_pct: float = 0.05
    max_drawdown_pct: float = 0.20
    default_take_profit_pct: float = 0.04
    trailing_stop: bool = True
    trailing_stop_positive: float = 0.02
    min_order_usd: float = 0.10
    time_stop: TimeStopConfig = Field(default_factory=TimeStopConfig)
    market_bias: MarketBiasConfig = Field(default_factory=MarketBiasConfig)
    profit_harvest: ProfitHarvestConfig = Field(default_factory=ProfitHarvestConfig)
    micro_dca: MicroDCAConfig = Field(default_factory=MicroDCAConfig)

class AgentMetadataConfig(BaseModel):
    name: str = "UnnamedAgent"
    agent_id: str = "unknown"
    capital_pool_pct: float = 0.0

class AppConfig(BaseModel):
    agent: Optional[AgentMetadataConfig] = None
    bot: BotConfig
    risk: RiskConfig
    # Se pueden agregar strategies y scheduler después

class EnvSettings(BaseSettings):
    exchange_id: str = "binance"
    exchange_api_key: str = ""
    exchange_api_secret: str = ""
    exchange_testnet: bool = True
    
    database_url: str = "sqlite:////dev/shm/tradingbot.db"
    active_db_path: str = "/dev/shm/tradingbot.db"
    persistent_db_path: str = "/home/shifu/tredding-agent/tradingbot.db"
    db_backup_dir: str = "/home/shifu/tredding-agent/backups_db"
    db_sync_interval_seconds: int = 300

    cloud_sync_enabled: bool = False
    cloud_sync_provider: str = "turso"
    cloud_sync_url: str = ""
    cloud_sync_auth_token: str = ""
    cloud_sync_interval_seconds: int = 600

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
