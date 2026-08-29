"""配置中心：模型协议、数据源开关、股票池。"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    # ---- LLM ----
    protocol: str = os.getenv("MA_PROTOCOL", "anthropic")   # anthropic | openai | mock | off
    model: str = os.getenv("MA_MODEL", "MiniMax-M2")
    api_key: str = os.getenv("MA_API_KEY", "")
    base_url: str = os.getenv("MA_BASE_URL", "https://api.minimaxi.com/anthropic")
    temperature: float = float(os.getenv("MA_TEMPERATURE", "0.3"))
    max_tokens: int = int(os.getenv("MA_MAX_TOKENS", "1000"))
    # anthropic 协议下模型名不确定时的候选（按序探测，命中即缓存）
    model_fallbacks: tuple = (
        "MiniMax-M2",
        "MiniMax-M1",
        "MiniMax-Text-01",
        "abab7-chat",
    )

    # ---- 行为 ----
    revisions_max: int = 2          # 风控打回重写的上限
    kline_days: int = 140           # 拉多少天日K
    news_pool_size: int = 200       # 财联社电报池大小

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        key = s.api_key or os.getenv("ANTHROPIC_API_KEY", "")
        protocol = s.protocol
        if not key and protocol != "mock":
            protocol = "off"        # 无 Key 自动降级为规则模式
        if os.getenv("MA_MOCK") == "1":
            protocol = "mock"
        return cls(
            protocol=protocol, model=s.model, api_key=key, base_url=s.base_url,
            temperature=s.temperature, max_tokens=s.max_tokens,
            model_fallbacks=s.model_fallbacks, revisions_max=s.revisions_max,
            kline_days=s.kline_days, news_pool_size=s.news_pool_size,
        )


def load_watchlist() -> list[dict]:
    """读 watchlist.toml；不存在则返回示例股。"""
    path = ROOT / "watchlist.toml"
    if path.exists():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return data.get("stocks", [])
    return [{"code": "600519", "note": "示例股"}, {"code": "300750", "note": "示例股"}]


def load_holdings() -> list[dict]:
    path = ROOT / "holdings.toml"
    if path.exists():
        return tomllib.loads(path.read_text(encoding="utf-8")).get("holdings", [])
    return []


def load_focus() -> list[dict]:
    path = ROOT / "focus.toml"
    if path.exists():
        return tomllib.loads(path.read_text(encoding="utf-8")).get("groups", [])
    return []


settings = Settings.load()
