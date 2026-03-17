"""Integration smoke tests — require root + Mininet + Cefore."""

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.integration
def test_placeholder():
    """Placeholder: real integration tests require sudo environment.

    Run with:
        sudo uv run pytest -m integration
    """
    pytest.skip("requires root + Mininet + Cefore")
