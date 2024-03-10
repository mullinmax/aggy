# config_manager.py
import os

from .defaults import DEFAULT_CONFIG

class Config:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.config = {}

    def get(self, key):
        if key not in self.config:
            self.config[key] = os.getenv(key) or DEFAULT_CONFIG.get(key)
        return self.config.get(key)
        
    def set(self, key, value):
        self.config[key] = value

config = Config()
