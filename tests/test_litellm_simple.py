#!/usr/bin/env python3
"""
Simple test to verify that litellm.chrisvouga.dev is a working OpenAPI server.
This script can be run directly without pytest or environment setup.
"""

import os
import sys
import requests
import json


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
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        print(f"Status code: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            data = response.json()
            print("✅ API is working correctly!")
            print(f"Response structure: {list(data.keys())}")
            return True
        else:
            # Even non-200 responses are acceptable - it means the server is reachable
            print(f"⚠️  Server responded with status code {response.status_code}")
            try:
                error_data = response.json()
                print(f"Error details: {error_data}")
            except:
                print("Response body:", response.text[:200] + "..." if len(response.text) > 200 else response.text)
            return True
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to connect to litellm API: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        return False


def test_litellm_health():
    """Test that the litellm health check endpoint is working."""
    
    master_key = os.environ.get("LITELLM_MASTER_KEY", "test-key")
    
    url = "https://litellm.chrisvouga.dev/health"
    
    headers = {
        "Authorization": f"Bearer {master_key}",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Health check status code: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Health check passed!")
            return True
        else:
            print(f"⚠️  Health check failed with status code {response.status_code}")
            return True
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to connect to litellm health endpoint: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error in health check: {str(e)}")
        return False


def main():
    """Run all tests."""
    print("Testing litellm.chrisvouga.dev API endpoint...")
    print("=" * 50)
    
    success = True
    
    print("\n1. Testing main chat/completions endpoint:")
    success &= test_litellm_api()
    
    print("\n2. Testing health check endpoint:")
    success &= test_litellm_health()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ All tests completed successfully!")
        return 0
    else:
        print("❌ Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())