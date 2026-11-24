"""Serialized async controls: synchronous callers wait on the app's loop, and each device instance is serialized; HTTP
over aiohttp, the ``iot`` extra.
"""
from __future__ import annotations

import asyncio
import json
import ssl

from collections.abc import Callable, Coroutine, Mapping
from typing import Any

import aiohttp

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


class HTTPControl(SerializedControl):
  """Serialized textual HTTP; a request or response that fails raises."""

  _http_timeout: float = 10
  _http_headers: Mapping[str, str] | None = None
  _http_ssl: ssl.SSLContext | bool | None = None

  def _http_get(self, url: str, *, headers: Mapping[str, str] | None = None) -> str:
    return self._http_request('GET', url, headers=headers)

  def _http_put(self, url: str, body: HttpBody | None = None, *, headers: Mapping[str, str] | None = None) -> str:
    return self._http_request('PUT', url, body, headers=headers)

  def _http_post(self, url: str, body: HttpBody | None = None, *, headers: Mapping[str, str] | None = None) -> str:
    return self._http_request('POST', url, body, headers=headers)

  def _http_request(self, method: str, url: str, body: HttpBody | None = None, *, headers: Mapping[str, str] | None = None) -> str:
    return self._control_call(self._http_request_async, method, url, body, headers)

  async def _http_request_async(self, method: str, url: str, body: HttpBody | None = None, headers: Mapping[str, str] | None = None) -> str:
    request_headers = {**(self._http_headers or {}), **(headers or {})} or None
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._http_timeout)) as session:
      async with session.request(method, url, data=body, headers=request_headers, ssl=self._http_ssl) as response:
        response.raise_for_status()
        return await response.text()


_NO_JSON_BODY = object()


class JSONHTTPControl(HTTPControl):
  """Explicit JSON request/response layer over ``HTTPControl``."""

  def _json_get(self, url: str, *, headers: Mapping[str, str] | None = None) -> JsonValue:
    return self._json_request('GET', url, headers=headers)

  def _json_put(self, url: str, payload: JsonValue, *, headers: Mapping[str, str] | None = None) -> JsonValue:
    return self._json_request('PUT', url, payload, headers=headers)

  def _json_post(self, url: str, payload: JsonValue, *, headers: Mapping[str, str] | None = None) -> JsonValue:
    return self._json_request('POST', url, payload, headers=headers)

  def _json_request(self, method: str, url: str, payload: JsonValue | object = _NO_JSON_BODY, *, headers: Mapping[str, str] | None = None) -> JsonValue:
    return self._control_call(self._json_request_async, method, url, payload, headers)

  async def _json_request_async(self, method: str, url: str, payload: JsonValue | object = _NO_JSON_BODY, headers: Mapping[str, str] | None = None) -> JsonValue:
    request_headers = {'Accept': 'application/json', **(headers or {})}
    body = None
    if payload is not _NO_JSON_BODY:
      request_headers.setdefault('Content-Type', 'application/json')
      body = json.dumps(payload)
    return json.loads(await self._http_request_async(method, url, body, request_headers))
