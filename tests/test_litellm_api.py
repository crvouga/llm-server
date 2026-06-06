"""
Integration test to verify that litellm.chrisvouga.dev is a working OpenAPI server.
"""

import os
import pytest
import requests
from typing import Optional


def test_litellm_api_endpoint_accessible():
    """Test that the litellm API endpoint is accessible and responding."""
    # Skip if we don't have the master key in environment
    master_key = os.environ.get("LITELLM_MASTER_KEY")
    if not master_key:
        pytest.skip("LITELLM_MASTER_KEY not set in environment")
    
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
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        # The endpoint should return a 200 status code or appropriate error
        # We're mainly checking that the server is reachable and responding
        assert response.status_code in [200, 400, 401, 403], f"Unexpected status code: {response.status_code}"
        
        # If it's a successful request, check for valid response structure
        if response.status_code == 200:
            data = response.json()
            assert "choices" in data
            assert len(data["choices"]) > 0
            assert "message" in data["choices"][0]
            
    except requests.exceptions.RequestException as e:
        pytest.fail(f"Failed to connect to litellm API: {str(e)}")


def test_litellm_api_health_check():
    """Test that the litellm health check endpoint is working."""
    # Skip if we don't have the master key in environment
    master_key = os.environ.get("LITELLM_MASTER_KEY")
    if not master_key:
        pytest.skip("LITELLM_MASTER_KEY not set in environment")
    
    url = "https://litellm.chrisvouga.dev/health"
    
    headers = {
        "Authorization": f"Bearer {master_key}",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        # Health endpoint should return 200
        assert response.status_code == 200, f"Health check failed with status code: {response.status_code}"
        
    except requests.exceptions.RequestException as e:
        pytest.fail(f"Failed to connect to litellm health endpoint: {str(e)}")


def test_litellm_api_model_list():
    """Test that the litellm model list endpoint is working."""
    # Skip if we don't have the master key in environment
    master_key = os.environ.get("LITELLM_MASTER_KEY")
    if not master_key:
        pytest.skip("LITELLM_MASTER_KEY not set in environment")
    
    url = "https://litellm.chrisvouga.dev/v1/models"
    
    headers = {
        "Authorization": f"Bearer {master_key}",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        # Model list endpoint should return 200
        assert response.status_code == 200, f"Model list failed with status code: {response.status_code}"
        
        # Check that we get valid JSON back
        data = response.json()
        assert "data" in data
        
    except requests.exceptions.RequestException as e:
        pytest.fail(f"Failed to connect to litellm model list endpoint: {str(e)}")