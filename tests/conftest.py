import pytest

# Enable pytest-asyncio auto mode so @pytest.mark.asyncio works without boilerplate
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
