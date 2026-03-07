"""Tests for async helpers: sync decorator."""
import asyncio
from gppu import sync


class TestSync:
    def test_sync_wraps_async_function(self):
        @sync
        async def add(a, b):
            return a + b

        result = add(2, 3)
        assert result == 5

    def test_sync_preserves_function_name(self):
        @sync
        async def my_func():
            pass

        assert my_func.__name__ == "my_func"

    def test_sync_with_async_sleep(self):
        @sync
        async def delayed():
            await asyncio.sleep(0.01)
            return "done"

        assert delayed() == "done"
