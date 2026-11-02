"""运行配置：从 config.yaml 读取，命令行/环境变量可覆盖。

配置文件只负责"默认值"，优先级永远低于命令行参数和环境变量，
这样部署时可以用环境变量注入 key，而本地开发直接改 yaml 即可。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT = 45


@dataclass
class AppConfig:
    api_key: str = ""
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    timeout: int = DEFAULT_TIMEOUT
    pricing_path: Optional[str] = None
    typeset_default: str = "none"


def load_config(path: Optional[str] = None) -> AppConfig:
    """读取 config.yaml；文件不存在时返回全默认值（不报错）。"""
    p = Path(path) if path else DEFAULT_CONFIG
    if not p.exists():
        return AppConfig()

    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml 顶层必须是映射（key: value）")

    deepseek = data.get("deepseek") or {}
    pricing = data.get("pricing") or {}

    pricing_path: Optional[str] = None
    if pricing.get("file"):
        # 相对路径按 config.yaml 所在目录解析，避免依赖当前工作目录
        pricing_path = str((p.parent / str(pricing["file"])).resolve())

    return AppConfig(
        api_key=str(deepseek.get("api_key") or "").strip(),
        model=str(deepseek.get("model") or DEFAULT_MODEL),
        base_url=str(deepseek.get("base_url") or DEFAULT_BASE_URL),
        timeout=int(deepseek.get("timeout") or DEFAULT_TIMEOUT),
        pricing_path=pricing_path,
        typeset_default=str(data.get("typeset_default") or "none"),
    )
