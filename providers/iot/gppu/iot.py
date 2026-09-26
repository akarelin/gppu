"""gppu.iot — provider: IoT value types and serialized device controls, from gppu 3 iot.py unchanged.

y2slug and y2eid name an entity; SerializedControl runs a device's coroutines on one daemon loop, one at a time per
instance, for synchronous callers; HTTPControl and JSONHTTPControl add HTTP on top. The MQTT transport that shared
the file is gppu.mqtt.
"""
from __future__ import annotations

import asyncio
import json
import ssl
import threading

from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import Future
from typing import Any, ClassVar, Optional

import aiohttp

from gppu import EventLoopBridge, _DC
from gppu.app import AsyncSubmission
from gppu.gppu import _DC_BASE_TYPE_MAP, y2list, y2path, y2topic, y2uri


# region y2eid
class y2slug(y2list):
  def __init__(self, o):
    self.token = '_'

    if '@' in str(o): o = str(o).split('@')[0]
    self.data = self._any2list(o)

class y2eid:
  ns: str
  domain: str
  slug: y2slug
  default_ns: ClassVar[str] = 'yala'
  default_domain: ClassVar[str] = 'entity'
  _ready: bool = False

  def __bool__(self) -> bool: return self._ready

  def __init__(self, o: Any, ns: Optional[str] = None, **kw):
    self._ready = False
    if not o: raise ValueError("y2eid: empty input")
    ns = ns or self.default_ns
    if isinstance(o, y2eid): s = str(o)
    elif isinstance(o, dict): s = str(o.get('entity_id', ""))
    elif isinstance(o, str): s = o
    elif hasattr(o, 'entity_id') and hasattr(o, 'namespace'): s = f"{o.entity_id}@{o.namespace}"
    elif hasattr(o, 'entity_id') and hasattr(o, 'ns'): s = f"{o.entity_id}@{o.ns}"
    elif hasattr(o, 'seid'): s = o.seid
    else: raise ValueError
    self.ns = ns
    self.domain = ''
    if '.' in s: self.domain, s = s.split('.', 1)
    if '@' in s: s, self.ns = s.rsplit('@', 1)
    self.ns = self.ns or self.default_ns
    self.domain = self.domain or self.default_domain
    self.slug = y2slug(s)
    for k in ['tail', 'head']: setattr(self, k, getattr(self.slug, k))
    self._ready = True

  def __str__(self):
    s = str(self.slug)
    if self.domain: s = self.domain + '.' + s
    if self.ns: s += '@' + self.ns
    return s
  def __repr__(self): return str(self)
  def __hash__(self): return hash(str(self))
  def __eq__(self, other): return str(self) == str(other)
  def __lt__(self, other): return str(self) < str(other)

  def endswith(self, ix) -> bool: return self.slug.endswith(ix)
  def startswith(self, ix) -> bool: return self.slug.startswith(ix)
  @property
  def entity_id(self) -> str: return f"{self.domain}.{self.slug}" if self._ready else ""
  @property
  def seid(self): return str(self)
# endregion


_DC_BASE_TYPE_MAP |= {'y2eid': y2eid, 'y2topic': y2topic, 'y2path': y2path, 'y2uri': y2uri}
_DC._DC_TYPE_MAP |= {'y2eid': y2eid, 'y2topic': y2topic, 'y2path': y2path, 'y2uri': y2uri}



# $$
# $$        Serialized controls
# $$
class SerializedControl(EventLoopBridge):
  """Runs controls on one daemon loop, serialized by a per-instance lock."""

  _control_loop: ClassVar[asyncio.AbstractEventLoop | None] = None
  _control_loop_start_lock: ClassVar[threading.Lock] = threading.Lock()
  _control_lock: asyncio.Lock | None = None

  def _get_loop(self) -> asyncio.AbstractEventLoop:
    loop = SerializedControl._control_loop
    if loop is not None: return loop

    with SerializedControl._control_loop_start_lock:
      loop = SerializedControl._control_loop
      if loop is None:
        ready = Future[asyncio.AbstractEventLoop]()
        threading.Thread(target=SerializedControl._run_loop, args=(ready,), daemon=True, name='gppu-controls').start()
        SerializedControl._control_loop = loop = ready.result()
    return loop

  @staticmethod
  def _run_loop(ready: Future[asyncio.AbstractEventLoop]) -> None:
    async def main() -> None:
      ready.set_result(asyncio.get_running_loop())
      await asyncio.Event().wait()

    try: asyncio.run(main())
    except BaseException as error:
      if ready.done(): raise
      ready.set_exception(error)

  def _control_call[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> T:
    return self.call(self._control_run, function, *args, **kwargs)

  def _control_submit[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> AsyncSubmission[T]:
    return self.submit(self._control_run, function, *args, **kwargs)

  async def _control_run[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> T:
    lock = self._control_lock
    if lock is None: lock = self._control_lock = asyncio.Lock()
    async with lock: return await function(*args, **kwargs)


# $$
# $$        HTTP and JSON-over-HTTP controls
# $$
type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type HttpBody = str | bytes


class HTTPControl(SerializedControl):
  """Serialized textual HTTP; returns ``None`` on request or response failure."""

  _http_timeout: float = 10
  _http_headers: Mapping[str, str] | None = None
  _http_ssl: ssl.SSLContext | bool | None = None

  def _http_get(self, url: str, *, headers: Mapping[str, str] | None = None) -> str | None:
    return self._http_request('GET', url, headers=headers)

  def _http_put(self, url: str, body: HttpBody | None = None, *, headers: Mapping[str, str] | None = None) -> str | None:
    return self._http_request('PUT', url, body, headers=headers)

  def _http_post(self, url: str, body: HttpBody | None = None, *, headers: Mapping[str, str] | None = None) -> str | None:
    return self._http_request('POST', url, body, headers=headers)

  def _http_request(self, method: str, url: str, body: HttpBody | None = None, *, headers: Mapping[str, str] | None = None) -> str | None:
    return self._control_call(self._http_request_async, method, url, body, headers)

  async def _http_request_async(self, method: str, url: str, body: HttpBody | None = None, headers: Mapping[str, str] | None = None) -> str | None:
    request_headers = {**(self._http_headers or {}), **(headers or {})} or None
    try:
      timeout = aiohttp.ClientTimeout(total=self._http_timeout)
      async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method, url, data=body, headers=request_headers, ssl=self._http_ssl) as response:
          response.raise_for_status()
          return await response.text()
    except (aiohttp.ClientError, TimeoutError, OSError, UnicodeError):
      return None


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
    response = await self._http_request_async(method, url, body, request_headers)
    if response is None: return None
    try: return json.loads(response)
    except json.JSONDecodeError: return None
