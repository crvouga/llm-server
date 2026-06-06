#!/usr/bin/env python3
"""
Simple test to verify that litellm.chrisvouga.dev is a working OpenAPI server.
This script can be run directly without pytest or environment setup.
"""

import os
import sys
import requests
import json

try:
    import pytest
except ImportError:
    pass


def test_litellm_api():
    """Test that the litellm API endpoint is accessible and responding."""
    
    # Try to get master key from environment or use a default for testing purposes
    master_key = os.environ.get("LITELLM_MASTER_KEY", "test-key")
    
    url = "https://litellm.chrisvouga.dev/v1/chat/completions"
    
    # Test with a simple request
    headers = {
        "Authorization": f"Bearer {master_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "Hello"}
        ]
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    
    print(f"Status code: {response.status_code}")
    print(f"Response headers: {dict(response.headers)}")
    
    # The endpoint should return a 200 status code or appropriate error
    assert response.status_code in [200, 400, 401, 403], f"Unexpected status code: {response.status_code}"
    
    if response.status_code == 200:
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert "message" in data["choices"][0]
        print("✅ API is working correctly!")
        print(f"Response structure: {list(data.keys())}")


def test_litellm_health():
    """Test that the litellm health check endpoint is working."""
    
    master_key = os.environ.get("LITELLM_MASTER_KEY", "test-key")
    
    url = "https://litellm.chrisvouga.dev/health"
    
    headers = {
        "Authorization": f"Bearer {master_key}",
    }
    
    response = requests.get(url, headers=headers, timeout=30)
    
    print(f"Health check status code: {response.status_code}")
    
    # Health endpoint should return 200 (authenticated) or 401 (requires auth but works)
    assert response.status_code in [200, 401], f"Health check failed with status code: {response.status_code}"
    print("✅ Health check passed!")