# Integration Test for litellm.chrisvouga.dev

This directory contains integration tests to verify that the LiteLLM proxy at `litellm.chrisvouga.dev` is functioning correctly.

## Files Created

1. **`tests/test_litellm_api.py`** - A pytest-based test suite with three test functions:
   - `test_litellm_api_endpoint_accessible`: Tests the main chat/completions endpoint
   - `test_litellm_api_health_check`: Tests the health check endpoint
   - `test_litellm_api_model_list`: Tests the model list endpoint

2. **`tests/test_litellm_simple.py`** - A standalone script that can be run directly without pytest:
   - Can be executed with `python tests/test_litellm_simple.py`
   - Doesn't require environment variables to run (though will use them if available)
   - Provides clear output about the API status

## How to Run

### Using pytest (requires LITELLM_MASTER_KEY in environment):
```bash
# Install dev dependencies first
pip install -e ".[dev]"

# Run all tests
pytest tests/test_litellm_api.py -v

# Run specific test
pytest tests/test_litellm_api.py::test_litellm_api_endpoint_accessible -v
```

### Using the standalone script:
```bash
python tests/test_litellm_simple.py
```

## Test Coverage

The integration tests verify that:

1. The main API endpoint is reachable and responding
2. The health check endpoint works properly  
3. The model list endpoint returns valid data
4. The server responds appropriately to requests (even with errors like authentication failures)

Note: The tests require the `LITELLM_MASTER_KEY` environment variable to be set for full functionality, but will still work to verify basic connectivity without it.