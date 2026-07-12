import json
import os
import re
from pathlib import Path
from threading import Lock

from .tavily_reliability import key_fingerprint


class Config:
    _instance = None
    _SETUP_COMMAND = (
        "claude mcp add-json grok-search --scope user "
        '\'{"type":"stdio","command":"uvx","args":["--from",'
        '"git+https://github.com/Timmyzzo/WebSearch-MCP","grok-search"],'
        '"env":{"GROK_API_URL":"your-api-url","GROK_API_KEY":"your-api-key"}}\''
    )
    _DEFAULT_MODEL = "grok-4-fast"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config_file = None
            cls._instance._cached_model = None
            cls._instance._tavily_key_index = 0
            cls._instance._tavily_key_lock = Lock()
        return cls._instance

    @property
    def config_file(self) -> Path:
        if self._config_file is None:
            config_dir = Path.home() / ".config" / "grok-search"
            try:
                config_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                config_dir = Path.cwd() / ".grok-search"
                config_dir.mkdir(parents=True, exist_ok=True)
            self._config_file = config_dir / "config.json"
        return self._config_file

    def _load_config_file(self) -> dict:
        if not self.config_file.exists():
            return {}
        try:
            with open(self.config_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_config_file(self, config_data: dict) -> None:
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            raise ValueError(f"无法保存配置文件: {str(e)}")

    @property
    def debug_enabled(self) -> bool:
        return os.getenv("GROK_DEBUG", "false").lower() in ("true", "1", "yes")

    @property
    def grok_model_max_attempts(self) -> int:
        raw = os.getenv("GROK_MODEL_MAX_ATTEMPTS", "").strip()
        if not raw:
            return 3
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("GROK_MODEL_MAX_ATTEMPTS 必须是正整数") from exc
        if value < 1:
            raise ValueError("GROK_MODEL_MAX_ATTEMPTS 必须大于或等于 1")
        return value

    @property
    def retry_multiplier(self) -> float:
        return float(os.getenv("GROK_RETRY_MULTIPLIER", "1"))

    @property
    def retry_max_wait(self) -> int:
        return int(os.getenv("GROK_RETRY_MAX_WAIT", "10"))

    @property
    def grok_api_url(self) -> str:
        url = os.getenv("GROK_API_URL")
        if not url:
            raise ValueError(
                f"Grok API URL 未配置！\n请使用以下命令配置 MCP 服务器：\n{self._SETUP_COMMAND}"
            )
        return url

    @property
    def grok_api_key(self) -> str:
        key = os.getenv("GROK_API_KEY")
        if not key:
            raise ValueError(
                f"Grok API Key 未配置！\n请使用以下命令配置 MCP 服务器：\n{self._SETUP_COMMAND}"
            )
        return key

    @property
    def tavily_enabled(self) -> bool:
        return os.getenv("TAVILY_ENABLED", "true").lower() in ("true", "1", "yes")

    @property
    def tavily_api_url(self) -> str:
        return os.getenv("TAVILY_API_URL", "https://api.tavily.com")

    @staticmethod
    def _split_api_keys(value: str | None) -> list[str]:
        if not value:
            return []
        return [key.strip() for key in re.split(r"[,;\r\n]+", value) if key.strip()]

    @property
    def tavily_api_keys(self) -> list[str]:
        if not self.tavily_enabled:
            return []
        keys = self._split_api_keys(os.getenv("TAVILY_API_KEYS"))
        if keys:
            return keys
        return self._split_api_keys(os.getenv("TAVILY_API_KEY"))

    @property
    def tavily_api_key(self) -> str | None:
        keys = self.tavily_api_keys
        return keys[0] if keys else None

    @property
    def tavily_key_cooldown(self) -> float:
        return max(0.0, float(os.getenv("TAVILY_KEY_COOLDOWN", "30")))

    @property
    def tavily_quota_cooldown(self) -> float:
        return max(0.0, float(os.getenv("TAVILY_QUOTA_COOLDOWN", "3600")))

    @property
    def tavily_service_failure_threshold(self) -> int:
        return max(2, int(os.getenv("TAVILY_SERVICE_FAILURE_THRESHOLD", "2")))

    @property
    def tavily_service_cooldown(self) -> float:
        return max(0.0, float(os.getenv("TAVILY_SERVICE_COOLDOWN", "30")))

    def next_tavily_api_key(self) -> str | None:
        keys = self.tavily_api_keys
        if not keys:
            return None
        with self._tavily_key_lock:
            key = keys[self._tavily_key_index % len(keys)]
            self._tavily_key_index = (self._tavily_key_index + 1) % len(keys)
            return key

    @property
    def log_level(self) -> str:
        return os.getenv("GROK_LOG_LEVEL", "INFO").upper()

    @property
    def log_dir(self) -> Path:
        log_dir_str = os.getenv("GROK_LOG_DIR", "logs")
        log_dir = Path(log_dir_str)
        if log_dir.is_absolute():
            return log_dir

        home_log_dir = Path.home() / ".config" / "grok-search" / log_dir_str
        try:
            home_log_dir.mkdir(parents=True, exist_ok=True)
            return home_log_dir
        except OSError:
            pass

        cwd_log_dir = Path.cwd() / log_dir_str
        try:
            cwd_log_dir.mkdir(parents=True, exist_ok=True)
            return cwd_log_dir
        except OSError:
            pass

        tmp_log_dir = Path("/tmp") / "grok-search" / log_dir_str
        tmp_log_dir.mkdir(parents=True, exist_ok=True)
        return tmp_log_dir

    def _apply_model_suffix(self, model: str) -> str:
        try:
            url = self.grok_api_url
        except ValueError:
            return model
        if "openrouter" in url and ":online" not in model:
            return f"{model}:online"
        return model

    @staticmethod
    def _non_empty(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None

    def normalize_model(self, model: str) -> str:
        normalized = self._non_empty(model)
        if normalized is None:
            raise ValueError("模型名称不能为空")
        return self._apply_model_suffix(normalized)

    @property
    def grok_primary_model(self) -> str:
        if self._cached_model is not None:
            return self._cached_model

        file_config = self._load_config_file()
        model = (
            self._non_empty(os.getenv("GROK_PRIMARY_MODEL"))
            or self._non_empty(os.getenv("GROK_MODEL"))
            or self._non_empty(file_config.get("primary_model"))
            or self._non_empty(file_config.get("model"))
            or self._DEFAULT_MODEL
        )
        self._cached_model = self._apply_model_suffix(model)
        return self._cached_model

    @property
    def grok_fallback_model(self) -> str | None:
        file_config = self._load_config_file()
        model = self._non_empty(os.getenv("GROK_FALLBACK_MODEL")) or self._non_empty(
            file_config.get("fallback_model")
        )
        return self._apply_model_suffix(model) if model else None

    @property
    def grok_model(self) -> str:
        """兼容旧调用：GROK_MODEL 始终表示当前主模型。"""
        return self.grok_primary_model

    def set_model(self, model: str) -> None:
        normalized = self._non_empty(model)
        if normalized is None:
            raise ValueError("模型名称不能为空")
        config_data = self._load_config_file()
        config_data["primary_model"] = normalized
        config_data["model"] = normalized
        self._save_config_file(config_data)
        self._cached_model = self._apply_model_suffix(normalized)

    @staticmethod
    def _mask_api_key(key: str) -> str:
        """脱敏显示 API Key，只显示前后各 4 个字符"""
        return key_fingerprint(key)

    def _mask_api_keys(self, keys: list[str]) -> str:
        if not keys:
            return "未配置"
        masked = ", ".join(self._mask_api_key(key) for key in keys)
        if len(keys) == 1:
            return masked
        return f"{masked}（共 {len(keys)} 个）"

    def get_config_info(self) -> dict:
        """获取配置信息（API Key 已脱敏）"""
        try:
            api_url = self.grok_api_url
            api_key_raw = self.grok_api_key
            api_url = api_url.replace(api_key_raw, "[REDACTED]")
            api_key_masked = self._mask_api_key(api_key_raw)
            config_status = "✅ 配置完整"
        except ValueError as e:
            api_url = "未配置"
            api_key_masked = "未配置"
            config_status = f"❌ 配置错误: {str(e)}"

        try:
            max_attempts: int | str = self.grok_model_max_attempts
        except ValueError as exc:
            max_attempts = f"配置错误: {exc}"
            config_status = f"❌ 配置错误: {exc}"

        return {
            "GROK_API_URL": api_url,
            "GROK_API_KEY": api_key_masked,
            "GROK_PRIMARY_MODEL": self.grok_primary_model,
            "GROK_FALLBACK_MODEL": self.grok_fallback_model or "未配置",
            "GROK_MODEL_MAX_ATTEMPTS": max_attempts,
            "GROK_MODEL": self.grok_model,
            "GROK_DEBUG": self.debug_enabled,
            "GROK_LOG_LEVEL": self.log_level,
            "GROK_LOG_DIR": str(self.log_dir),
            "TAVILY_API_URL": self.tavily_api_url,
            "TAVILY_ENABLED": self.tavily_enabled,
            "TAVILY_API_KEY": self._mask_api_keys(self.tavily_api_keys),
            "TAVILY_KEY_COOLDOWN": self.tavily_key_cooldown,
            "TAVILY_QUOTA_COOLDOWN": self.tavily_quota_cooldown,
            "TAVILY_SERVICE_FAILURE_THRESHOLD": self.tavily_service_failure_threshold,
            "TAVILY_SERVICE_COOLDOWN": self.tavily_service_cooldown,
            "config_status": config_status,
        }


config = Config()
