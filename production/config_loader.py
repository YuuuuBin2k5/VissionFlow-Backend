"""
Config Loader for VisionFlow Auto Production System
Loads and caches configuration files (YAML) with fallback defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml


CONFIG_DIR = Path(__file__).resolve().parent / "config"


class ProductionConfigLoader:
    _instance: Optional[ProductionConfigLoader] = None
    _configs: Dict[str, Dict[str, Any]] = {}

    def __new__(cls) -> ProductionConfigLoader:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_all()
        return cls._instance

    def _load_yaml(self, file_name: str) -> Dict[str, Any]:
        file_path = CONFIG_DIR / file_name
        if not file_path.exists():
            return {}
        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_all(self) -> None:
        self._configs["production_defaults"] = self._load_yaml("production_defaults.yaml")
        self._configs["quality_thresholds"] = self._load_yaml("quality_thresholds.yaml")
        self._configs["model_routing"] = self._load_yaml("model_routing.yaml")
        self._configs["source_policy"] = self._load_yaml("source_policy.yaml")
        self._configs["channel_profile_example"] = self._load_yaml("channel_profile.example.yaml")

    def reload(self) -> None:
        """Reload all config files from disk."""
        self._load_all()

    @property
    def production_defaults(self) -> Dict[str, Any]:
        return self._configs.get("production_defaults", {})

    @property
    def quality_thresholds(self) -> Dict[str, Any]:
        return self._configs.get("quality_thresholds", {})

    @property
    def model_routing(self) -> Dict[str, Any]:
        return self._configs.get("model_routing", {})

    @property
    def source_policy(self) -> Dict[str, Any]:
        return self._configs.get("source_policy", {})

    def get_format_defaults(self, format_type: str = "short") -> Dict[str, Any]:
        format_defaults = self.production_defaults.get("format_defaults", {})
        return format_defaults.get(format_type, format_defaults.get("short", {}))


# Global singleton access
config_loader = ProductionConfigLoader()
