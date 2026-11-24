"""Serialized async controls: synchronous callers wait on the app's loop, and each device instance is serialized; their
HTTP is mixin_Rest's.
"""
from __future__ import annotations

import asyncio

from collections.abc import Callable, Coroutine, Mapping
from typing import Any

from .app import _NO_JSON_BODY, mixin_Rest
from .gppu import _mixin


type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


# $$
# $$        Serialized controls
# $$
class SerializedControl(_mixin):
  """Runs controls on the loop ``_get_loop`` gives, its app's, serialized by a per-instance lock."""

  _control_lock: asyncio.Lock | None = None

  def _control_call[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> T:
    """The control run on the app's loop, waited for: a caller on that loop's own thread would block it."""
    loop = self._get_loop()
    try: on_loop = asyncio.get_running_loop() is loop
    except RuntimeError: on_loop = False   # .. no loop runs on this thread
    if on_loop: raise RuntimeError('cannot block the target event-loop thread')
    return asyncio.run_coroutine_threadsafe(self._control_run(function, *args, **kwargs), loop).result()

  async def _control_run[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> T:
    lock = self._control_lock
    if lock is None: lock = self._control_lock = asyncio.Lock()
    async with lock: return await function(*args, **kwargs)


# $$
# $$        HTTP and JSON-over-HTTP controls
# $$
type HttpBody = str | bytes


class HTTPControl(SerializedControl, mixin_Rest):
  """Serialized textual HTTP, mixin_Rest's request; a request or response that fails raises."""

  def _http_get(self, url: str, *, headers: Mapping[str, str] | None = None) -> str:
    return self._http_request('GET', url, headers=headers)

  def _http_put(self, url: str, body: HttpBody | None = None, *, headers: Mapping[str, str] | None = None) -> str:
    return self._http_request('PUT', url, body, headers=headers)

  def _http_post(self, url: str, body: HttpBody | None = None, *, headers: Mapping[str, str] | None = None) -> str:
    return self._http_request('POST', url, body, headers=headers)

  def _http_request(self, method: str, url: str, body: HttpBody | None = None, *, headers: Mapping[str, str] | None = None) -> str:
    return self._control_call(self._http_request_async, method, url, body, headers)


class JSONHTTPControl(HTTPControl):
  """Explicit JSON request/response layer over ``HTTPControl``, mixin_Rest's JSON request."""

  def _json_get(self, url: str, *, headers: Mapping[str, str] | None = None) -> JsonValue:
    return self._json_request('GET', url, headers=headers)

  def _json_put(self, url: str, payload: JsonValue, *, headers: Mapping[str, str] | None = None) -> JsonValue:
    return self._json_request('PUT', url, payload, headers=headers)

  def _json_post(self, url: str, payload: JsonValue, *, headers: Mapping[str, str] | None = None) -> JsonValue:
    return self._json_request('POST', url, payload, headers=headers)

  def _json_request(self, method: str, url: str, payload: JsonValue | object = _NO_JSON_BODY, *, headers: Mapping[str, str] | None = None) -> JsonValue:
    return self._control_call(self._json_request_async, method, url, payload, headers)
