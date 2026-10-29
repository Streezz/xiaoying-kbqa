"""读取 .env 配置。所有可调参数都在这里，其他模块不直接读环境变量。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    llm_mode: str
    api_key: str = field(repr=False)
    base_url: str
    model: str
    llm_timeout: float
    today: str
    max_steps: int
    max_tool_calls: int
    data_dir: Path
    synonyms_path: Path
    db_path: Path

    def with_overrides(self, **kw) -> "Settings":
        return replace(self, **{k: v for k, v in kw.items() if v is not None})


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def load_settings() -> Settings:
    return Settings(
        llm_mode=os.getenv("LLM_MODE", "deepseek"),
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        llm_timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        today=os.getenv("KBQA_TODAY", "2026-10-28"),
        max_steps=int(os.getenv("KBQA_MAX_STEPS", "12")),
        max_tool_calls=int(os.getenv("KBQA_MAX_TOOL_CALLS", "15")),
        data_dir=_path(os.getenv("KBQA_DATA_DIR", "data/docs")),
        synonyms_path=_path("data/synonyms.yaml"),
        db_path=_path(os.getenv("KBQA_DB_PATH", "var/sessions.db")),
    )
