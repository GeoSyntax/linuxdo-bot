"""配置加载：从 config.yaml 读取，支持环境变量覆盖敏感项。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 注意：yaml 改为 load() 内惰性导入。机器人运行时只用默认配置构造 Config()，
# 从不读 config.yaml，故 slim 容器（仅 requests+numpy）无需装 PyYAML 也能启动。

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"


@dataclass
class ComplianceConfig:
    respect_robots: bool = True
    requests_per_second: float = 0.33
    burst: int = 1
    max_retries: int = 3
    backoff_base: float = 2.0
    backoff_max: float = 60.0


@dataclass
class AIConfig:
    enabled: bool = True
    provider: str = "rule"
    ollama: dict[str, Any] = field(default_factory=dict)
    openai: dict[str, Any] = field(default_factory=dict)


@dataclass
class StorageConfig:
    backend: str = "sqlite"
    sqlite_path: str = "data/zhihu.db"
    mysql: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    crawler: dict[str, Any] = field(default_factory=dict)
    compliance: ComplianceConfig = field(default_factory=ComplianceConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    distributed: dict[str, Any] = field(default_factory=dict)
    project_root: Path = _PROJECT_ROOT

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        import yaml  # 惰性导入：仅在真正读 config.yaml 时才需要 PyYAML

        path = Path(path) if path else _DEFAULT_CONFIG_PATH
        raw: dict[str, Any] = {}
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        compliance = ComplianceConfig(**(raw.get("compliance") or {}))
        storage = StorageConfig(**(raw.get("storage") or {}))
        ai_raw = raw.get("ai") or {}
        ai = AIConfig(
            enabled=ai_raw.get("enabled", True),
            provider=ai_raw.get("provider", "rule"),
            ollama=ai_raw.get("ollama") or {},
            openai=ai_raw.get("openai") or {},
        )

        # 环境变量覆盖敏感项：不把密钥写进仓库
        env_key = os.getenv("OPENAI_API_KEY")
        if env_key:
            ai.openai["api_key"] = env_key

        return cls(
            crawler=raw.get("crawler") or {},
            compliance=compliance,
            storage=storage,
            ai=ai,
            distributed=raw.get("distributed") or {},
        )


# 便捷单例
_config: Config | None = None


def get_config(path: str | Path | None = None) -> Config:
    global _config
    if _config is None or path is not None:
        _config = Config.load(path)
    return _config
