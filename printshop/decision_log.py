"""决策日志：每次处理写一行 JSONL，便于复盘、对账与追责。

日志只记录结构化结果（解析、合并、裁决、校验、确认、金额），不记录 API key。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_LOG = Path("logs") / "decisions.jsonl"


def log_decision(record: Dict[str, Any], path: Optional[str] = None) -> Optional[str]:
    """追加一条日志；返回写入路径，失败返回 None（日志失败不影响下单）。"""
    target = Path(path) if path else DEFAULT_LOG
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        entry = dict(record)
        entry.setdefault("time", datetime.now().isoformat(timespec="seconds"))
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return str(target)
    except OSError:
        return None


def read_decisions(limit: int = 10, path: Optional[str] = None) -> List[Dict[str, Any]]:
    """读取最近 N 条决策日志。"""
    target = Path(path) if path else DEFAULT_LOG
    if not target.exists():
        return []
    lines = target.read_text(encoding="utf-8").splitlines()[-limit:]
    records: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
