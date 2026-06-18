import os
from pathlib import Path
import yaml

DEFAULT_CONFIG_PATH_HOME = Path.home() / ".gmail_cleanup" / "config.yaml"
DEFAULT_CONFIG_PATH_LOCAL = Path("config.yaml")

DEFAULT_CONFIG_CONTENT = {
    "accounts": {
        "dummy": "dev_test_account@gmail.com",
        "personal": "your_email@gmail.com"
    },
    "obsidian_vault_path": "",
    "db_path": str(Path.home() / ".gmail_cleanup" / "analytics.db"),
    "rules": {
        "promotions": {
            "days": 30,
            "action": "TRASH",
            "enabled": True
        },
        "social": {
            "days": 7,
            "action": "TRASH",
            "enabled": True
        },
        "receipts": {
            "days": 730,  # 2 years
            "action": "TRASH",
            "enabled": True
        }
    },
    "ai": {
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "api_key_env": "GEMINI_API_KEY",
        "api_key": "",
        "base_url": "https://opencode.ai/zen/go/v1"
    }
}

class AppConfig:
    def __init__(self):
        self.config_path = self._resolve_config_path()
        self.data = self._load_or_create_config()

    def _resolve_config_path(self) -> Path:
        # Check if local config.yaml exists
        if DEFAULT_CONFIG_PATH_LOCAL.exists():
            return DEFAULT_CONFIG_PATH_LOCAL
        # Otherwise use/create home path
        return DEFAULT_CONFIG_PATH_HOME

    def _load_or_create_config(self) -> dict:
        if not self.config_path.exists():
            # Ensure parent directories exist
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(DEFAULT_CONFIG_CONTENT, f, default_flow_style=False, sort_keys=False)
            return DEFAULT_CONFIG_CONTENT

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                user_data = yaml.safe_load(f)
                # Merge defaults to handle missing fields gracefully
                merged = DEFAULT_CONFIG_CONTENT.copy()
                if user_data:
                    for k, v in user_data.items():
                        if isinstance(v, dict) and k in merged:
                            merged[k].update(v)
                        else:
                            merged[k] = v
                return merged
        except Exception as e:
            print(f"Warning: Failed to load config from {self.config_path} due to: {e}. Using defaults.")
            return DEFAULT_CONFIG_CONTENT

    @property
    def accounts(self) -> dict[str, str]:
        return self.data.get("accounts", {})

    @property
    def obsidian_vault_path(self) -> str:
        return self.data.get("obsidian_vault_path", "")

    @property
    def db_path(self) -> str:
        return self.data.get("db_path", str(Path.home() / ".gmail_cleanup" / "analytics.db"))

    @property
    def rules(self) -> dict:
        return self.data.get("rules", {})

    @property
    def ai(self) -> dict:
        return self.data.get("ai", {})
