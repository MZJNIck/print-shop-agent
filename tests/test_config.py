"""config.yaml 读取与优先级测试。"""
from pathlib import Path

from printshop.agent import PrintShopAgent
from printshop.config import AppConfig, load_config


def test_default_config_loads():
    cfg = load_config()
    assert cfg.model == "deepseek-flash"
    assert cfg.base_url == "https://api.deepseek.com"
    assert cfg.timeout == 45
    # 本地 config.yaml 可能已填真实 key，这里只校验类型，不强制为空
    assert isinstance(cfg.api_key, str)
    # 没有 config.yaml 时 pricing_path 为 None，由 PriceBook 使用默认 pricing.yaml
    if cfg.pricing_path is not None:
        assert Path(cfg.pricing_path).name == "pricing.yaml"


def test_config_reads_api_key_and_relative_pricing(tmp_path):
    folder = tmp_path / "conf"
    folder.mkdir()
    path = folder / "config.yaml"
    path.write_text(
        "deepseek:\n"
        "  api_key: 'sk-test-123'\n"
        "  model: 'deepseek-chat'\n"
        "  base_url: 'https://example.com'\n"
        "  timeout: 10\n"
        "pricing:\n"
        "  file: 'my-prices.yaml'\n"
        "typeset_default: all\n",
        encoding="utf-8",
    )
    cfg = load_config(str(path))
    assert cfg.api_key == "sk-test-123"
    assert cfg.model == "deepseek-chat"
    assert cfg.base_url == "https://example.com"
    assert cfg.timeout == 10
    # 相对路径按 config.yaml 所在目录解析
    assert Path(cfg.pricing_path) == (folder / "my-prices.yaml").resolve()
    assert cfg.typeset_default == "all"


def test_missing_config_uses_defaults(tmp_path):
    cfg = load_config(str(tmp_path / "nope.yaml"))
    assert cfg == AppConfig()


def test_config_key_makes_agent_llm_ready():
    cfg = AppConfig(api_key="sk-test")
    agent = PrintShopAgent(api_key=cfg.api_key, model=cfg.model)
    assert agent.llm_ready is True
