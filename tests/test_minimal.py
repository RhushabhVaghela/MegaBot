import asyncio

import pytest


@pytest.mark.asyncio
async def test_simple_async():
    print("Simple async test starting")
    await asyncio.sleep(0.1)
    print("Simple async test finished")
    assert True
