
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from .models import InventoryMode, SideMode


class ExchangeConfig(BaseModel):
    dry_run: bool = True
    allow_live_orders: bool = False
    demo: bool = False
    dotenv_path: str


class MarketConfig(BaseModel):
    series_ticker: str
    event_ticker: str
    market_whitelist: list[str] = Field(default_factory=list)


class QuotingConfig(BaseModel):
    side_mode: SideMode = SideMode.BOTH
    inventory_mode: InventoryMode = InventoryMode.OFFSET_OPPOSITE_BY_INVENTORY
    target_contracts_per_order: float = 1000.0
    default_tick_size: int = 1
    passive_floor_price: int = 1


class ThresholdConfig(BaseModel):
    reference_mm_min_size: float = 100000.0
    quote_follow_min_size: float = 250.0
    flatten_follow_min_size: float = 250.0


class ScheduleConfig(BaseModel):
    capture_reference_time: str = "15:55"
    begin_repricing_time: str = "16:05"
    end_overnight_time: str = "09:25"
    reprice_every_minutes: int = 5


class StorageConfig(BaseModel):
    snapshot_json_path: str = "data/reference_snapshot.json"
    sqlite_path: str = "data/strategy_state.sqlite"
    log_path: str = "logs/strategy.log"


class LoggingConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class StrategyConfig(BaseModel):
    strategy_name: str = "kalshi-afterhours-shadow"
    timezone: str = "America/New_York"
    exchange: ExchangeConfig
    market: MarketConfig
    quoting: QuotingConfig = Field(default_factory=QuotingConfig)
    thresholds: ThresholdConfig = Field(default_factory=ThresholdConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def load_config(path: str | Path) -> StrategyConfig:
    """Load YAML config into a validated StrategyConfig object."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return StrategyConfig.model_validate(raw)