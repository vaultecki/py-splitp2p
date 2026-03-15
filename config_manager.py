# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
Configuration Manager Module - Handles persistent application configuration storage.

This module provides persistent configuration storage with automatic
directory creation and error handling.
"""

import json
import os
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Manages application configuration with JSON file storage.

    Features:
    - Automatic config directory creation
    - Platform-specific paths (Windows/Linux/macOS)
    - Safe loading with fallback to empty config
    - Type-safe get/set operations
    """

    def __init__(self, app_name: str = "ThaOTP", filename: str = "config.json"):
        """
        Initialize the configuration manager.

        Args:
            app_name: application name for the config directory
            filename: configuration filename
        """
        self.app_name = app_name
        self.config_path = self._get_config_path(app_name)
        self.config_file = os.path.join(self.config_path, filename)
        self.data = {}
        self._ensure_directory_exists()
        self.load()

    @staticmethod
    def _get_config_path(app_name: str) -> str:
        """
        Returns platform-specific configuration directory path.

        Args:
            app_name: Application name for directory

        Returns:
            Full path to config directory

        Platform paths:
            Windows:   %LOCALAPPDATA%\{app_name}
            Linux/Mac: ~/.config/{app_name}
        """
        home_dir = os.path.expanduser("~")

        if os.name == "nt":  # Windows
            config_dir = os.path.join(home_dir, "AppData", "Local", app_name)
        else:  # Linux, Mac, Unix
            config_dir = os.path.join(home_dir, ".config", app_name)

        logger.debug(f"Config path: {config_dir}")
        return config_dir

    def _ensure_directory_exists(self) -> None:
        """
        Creates config directory if it does not exist.

        Creates all intermediate directories as needed.
        """
        if not os.path.exists(self.config_path):
            try:
                os.makedirs(self.config_path, exist_ok=True)
                logger.info(f"Created config directory: {self.config_path}")
            except OSError as e:
                logger.error(f"Failed to create config directory: {e}")
                raise

    def load(self) -> None:
        """
        Loads configuration from file.

        If file does not exist or is invalid, starts with empty config.
        Does not raise exceptions - logs warnings instead.
        """
        try:
            if not os.path.exists(self.config_file):
                logger.info("Config file not found, starting with empty config")
                self.data = {}
                return

            with open(self.config_file, "r", encoding="utf-8") as f:
                self.data = json.load(f)
                logger.info(f"Loaded config with {len(self.data)} entries")

        except json.JSONDecodeError as e:
            logger.warning(f"Config file invalid JSON: {e}. Starting with empty config.")
            self.data = {}
        except IOError as e:
            logger.warning(f"Could not read config file: {e}. Starting with empty config.")
            self.data = {}

    def save(self) -> None:
        """
        Saves configuration to file.

        Creates formatted JSON with 4-space indentation.

        Raises:
            IOError: if file cannot be written
        """
        try:
            # Ensure directory still exists
            self._ensure_directory_exists()

            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)

            logger.debug(f"Saved config with {len(self.data)} entries")

        except IOError as e:
            logger.error(f"Could not save config file: {e}")
            raise

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by key.

        Args:
            key: configuration key
            default: default value if key not found

        Returns:
            configuration value or default
        """
        value = self.data.get(key, default)
        logger.debug(f"Config get: {key} = {type(value).__name__}")
        return value

    def set(self, key: str, value: Any) -> None:
        """
        Set configuration value.

        Args:
            key: configuration key
            value: value to store (must be JSON serializable)
        """
        logger.debug(f"Config set: {key} = {type(value).__name__}")
        self.data[key] = value

    def delete(self, key: str) -> bool:
        """
        Delete a configuration key.

        Args:
            key: configuration key to delete

        Returns:
            True if deleted, False if key did not exist
        """
        if key in self.data:
            del self.data[key]
            logger.debug(f"Config deleted: {key}")
            return True
        return False

    def has_key(self, key: str) -> bool:
        """
        Check if configuration key exists.

        Args:
            key: configuration key to check

        Returns:
            True if key exists, False otherwise
        """
        return key in self.data

    def clear(self) -> None:
        """Clears all configuration data."""
        self.data.clear()
        logger.info("Config cleared")

    def get_all(self) -> dict:
        """
        Get all configuration data.

        Returns:
            Dictionary of all configuration entries
        """
        return self.data.copy()

    def __repr__(self) -> str:
        """String representation."""
        return f"ConfigManager(app='{self.app_name}', entries={len(self.data)})"


if __name__ == '__main__':
    # Test configuration manager
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info("Testing ConfigManager")

    config = ConfigManager("TestApp", "test_config.json")
    config.set("test_key", "test_value")
    config.set("test_number", 42)
    config.save()

    logger.info(f"Config: {config}")
    logger.info(f"Test key value: {config.get('test_key')}")
