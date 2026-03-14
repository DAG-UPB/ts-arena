# master-controller/src/config.py

import os
import json
from typing import Optional, Dict, Any

def read_secret_file(file_path: str) -> Optional[str]:
    """Reads a secret value from a file (for Docker Secrets)"""
    try:
        with open(file_path, 'r') as f:
            return f.read().strip()
    except (FileNotFoundError, IOError):
        return None

def get_env_or_secret(env_var: str, secret_file_var: str = None) -> Optional[str]:
    """Gets a value from Environment Variable or Docker Secret File"""
    # First try to read from Environment Variable
    value = os.getenv(env_var)
    if value:
        return value
    
    # If not present, try Docker Secret File
    if secret_file_var:
        secret_file_path = os.getenv(secret_file_var)
        if secret_file_path:
            return read_secret_file(secret_file_path)
    
    return None

def load_json_config(env_var: str, secret_file_var: str = None) -> Optional[Dict[str, Any]]:
    """Loads a JSON configuration from Environment Variable or Secret File"""
    config_str = get_env_or_secret(env_var, secret_file_var)
    if config_str:
        try:
            return json.loads(config_str)
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing JSON configuration for {env_var}: {e}")
            return None
    return None

class Config:
    
    # Docker Configuration
    DOCKER_NETWORK = os.getenv("DOCKER_NETWORK", "tsfm-arena_default")
    
    # Logging Configuration
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")