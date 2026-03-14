#!/usr/bin/env python3
"""
Model Registration Script for TS-Arena

This script registers models defined in config.json with the TS-Arena API.
Run this once before starting the challenge-uploads service to ensure
your models are registered and can participate in challenges.

PREREQUISITES:
1. A user account must exist in the backend
2. An API key must be generated for that user

Usage:
    python register_models.py              # Register all unregistered models
    python register_models.py --list       # List currently registered models
    python register_models.py --force      # Re-register all models (update existing)
"""

import os
import sys
import json
import logging
import argparse
from typing import Any, Dict, List, Optional
from datetime import date

import requests
from dotenv import load_dotenv

# --- Initialization ---
load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8457")
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "60"))
API_KEY = os.environ.get("API_UPLOAD_KEY", "")
CONFIG_FILE = os.environ.get("CONFIG_FILE", "config.json")


def load_config() -> Dict[str, Any]:
    """Load config file"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        CONFIG_FILE,
        os.path.join(script_dir, CONFIG_FILE),
        os.path.join("..", CONFIG_FILE),
        "/app/config.json"
    ]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    logger.info(f"Loading config from {path}")
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading config {path}: {e}")
                return {}
    logger.warning(f"No config file found (searched in {paths})")
    return {}


def get_registered_models() -> List[Dict[str, Any]]:
    """
    Fetch all registered models for the current user from API.
    Uses GET /api/v1/models/ - returns only models owned by the API key's user.
    """
    url = f"{API_BASE_URL}/api/v1/models/"
    headers = {"X-API-Key": API_KEY}
    
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json() or []
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error fetching models: {e}")
        if e.response is not None:
            logger.error(f"  Response: {e.response.text[:500]}")
        return []
    except Exception as e:
        logger.error(f"Error fetching models: {e}")
        return []


def register_model(model_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Register a new model with the API.
    
    Uses POST /api/v1/models/register endpoint.
    The user_id is automatically determined from the API key.
    
    Expected model_data format (from config.json):
    {
        "name": "example/naive-forecast",
        "model_type": "Statistical",
        "model_family": "naive",
        "model_size": 0,
        "hosting": "self-hosted",
        "architecture": "naive",
        "pretraining_data": "None",
        "publishing_date": "2026-02-02",
        "parameters": {}
    }
    """
    url = f"{API_BASE_URL}/api/v1/models/register"
    headers = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json"
    }
    
    # Build registration payload matching ModelInfoCreate schema
    payload = {
        "name": model_data.get("name"),
        "model_type": model_data.get("model_type"),
        "model_family": model_data.get("model_family"),
        "model_size": model_data.get("model_size"),
        "hosting": model_data.get("hosting"),
        "architecture": model_data.get("architecture"),
        "pretraining_data": model_data.get("pretraining_data"),
        "parameters": model_data.get("parameters", {}),
    }
    
    # Handle publishing_date - convert to date format if present
    pub_date = model_data.get("publishing_date")
    if pub_date:
        payload["publishing_date"] = pub_date
    
    # Remove None values to use server defaults
    payload = {k: v for k, v in payload.items() if v is not None}
    
    try:
        logger.info(f"Registering model: {payload.get('name')}")
        logger.debug(f"  Payload: {json.dumps(payload, indent=2)}")
        
        resp = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()
        
        readable_id = result.get("readable_id", "unknown")
        logger.info(f"✓ Model registered successfully: {payload['name']}")
        logger.info(f"  Readable ID: {readable_id}")
        return result
        
    except requests.exceptions.HTTPError as e:
        logger.error(f"✗ HTTP Error registering model '{payload.get('name')}': {e}")
        if e.response is not None:
            logger.error(f"  Status: {e.response.status_code}")
            logger.error(f"  Response: {e.response.text[:500]}")
        return None
    except Exception as e:
        logger.error(f"✗ Error registering model '{payload.get('name')}': {e}")
        return None


def list_registered_models():
    """List all registered models for current user"""
    models = get_registered_models()
    
    if not models:
        print("\nNo models registered for your user yet.")
        print("Use 'python register_models.py' to register models from config.json")
        return
    
    print(f"\n{'='*80}")
    print(f"Your Registered Models ({len(models)} total)")
    print(f"{'='*80}")
    
    # Get organization_id from first model
    org_id = None
    
    for model in models:
        readable_id = model.get("readable_id", "?")
        name = model.get("name", "Unknown")
        model_type = model.get("model_type", "?")
        model_family = model.get("model_family", "?")
        model_size = model.get("model_size", "?")
        created = model.get("created_at", "?")
        org_id = model.get("organization_id")
        
        print(f"\n  Readable ID: {readable_id}")
        print(f"  Name: {name}")
        print(f"  Type: {model_type} | Family: {model_family} | Size: {model_size}M")
        print(f"  Organization ID: {org_id if org_id else 'None (personal)'}")
        print(f"  Created: {created}")
    
    print(f"\n{'='*80}")
    print("\nUse the 'name' field when uploading forecasts (model_name in payload).")
    print(f"{'='*80}\n")


def register_all_models(force: bool = False):
    """Register all models from config that aren't already registered"""
    config = load_config()
    
    if not config:
        logger.error("No config loaded. Cannot register models.")
        return
    
    # Get already registered models
    registered = get_registered_models()
    registered_names = {m.get("name") for m in registered}
    
    logger.info(f"Found {len(config)} models in config")
    logger.info(f"Found {len(registered)} models already registered for your user")
    
    registered_count = 0
    skipped_count = 0
    failed_count = 0
    
    for container_name, model_data in config.items():
        model_name = model_data.get("name")
        
        if not model_name:
            logger.warning(f"Skipping '{container_name}': no 'name' field in config")
            continue
        
        if model_name in registered_names and not force:
            logger.info(f"Skipping '{model_name}': already registered")
            skipped_count += 1
            continue
        
        result = register_model(model_data)
        if result:
            registered_count += 1
        else:
            failed_count += 1
    
    print(f"\n{'='*60}")
    print(f"Registration Summary")
    print(f"{'='*60}")
    print(f"  Registered: {registered_count}")
    print(f"  Skipped (already registered): {skipped_count}")
    print(f"  Failed: {failed_count}")
    print(f"{'='*60}\n")


def check_api_connection():
    """Check if we can connect to the API"""
    try:
        resp = requests.get(f"{API_BASE_URL}/health", timeout=10)
        if resp.status_code == 200:
            logger.info(f"✓ API reachable at {API_BASE_URL}")
            return True
    except Exception as e:
        logger.error(f"✗ Cannot reach API at {API_BASE_URL}: {e}")
    return False


def check_authentication():
    """Check if API key is valid by listing user's models"""
    url = f"{API_BASE_URL}/api/v1/models/"
    headers = {"X-API-Key": API_KEY}
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            models = resp.json()
            logger.info(f"✓ API key valid - you have {len(models)} registered model(s)")
            return True
        elif resp.status_code == 401:
            logger.error("✗ Authentication failed: Invalid API key")
            return False
        elif resp.status_code == 403:
            logger.error("✗ Authentication failed: Access denied")
            return False
        else:
            logger.error(f"✗ Authentication check failed: {resp.status_code}")
            return False
    except Exception as e:
        logger.error(f"✗ Could not verify authentication: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Register models with the TS-Arena API")
    parser.add_argument("--list", action="store_true", help="List registered models")
    parser.add_argument("--force", action="store_true", help="Force re-registration of all models")
    parser.add_argument("--check", action="store_true", help="Check API connectivity only")
    args = parser.parse_args()
    
    # Validate configuration
    if not API_KEY:
        logger.error("API_UPLOAD_KEY environment variable not set!")
        logger.error("Set it in your .env file or export it:")
        logger.error("  export API_UPLOAD_KEY=your_api_key_here")
        sys.exit(1)
    
    logger.info(f"API Base URL: {API_BASE_URL}")
    
    # Check connectivity
    if not check_api_connection():
        sys.exit(1)
    
    if args.check:
        check_authentication()
        sys.exit(0)
    
    if args.list:
        list_registered_models()
    else:
        register_all_models(force=args.force)


if __name__ == "__main__":
    main()
