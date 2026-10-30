"""gppu/fs's y2uri: gppu's y2uri as the URI convention (_Standards/Conventions/URI.md) has it, each form fsspec reads.

A uri is RFC 3986's `scheme:[//authority]path[?query][#fragment]`, so `uuid:...`, which has no authority, is a uri; fsspec's
chained urls are a uri with its `target`, the uri it is read through: `gppu::file:///D:/TextLake`, `zip://member.txt::file:///D:/bundle.zip`.
str() gives the uri as it was written, which is what fsspec opens. A fragment's selection is read by `selection`."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

from ..gppu import y2path, y2uri as _y2uri

SCHEME = re.compile(r'([A-Za-z][A-Za-z0-9+.-]+):(.*)', re.S)   # two characters at least, so a drive, D:, is a path
RANGE = re.compile(r'(line|char|t)=(?:npt:)?([0-9.]*),?([0-9.]*)')


class y2uri(_y2uri):
    """A uri, its chain and its fragment, as the URI convention has them. A path joined with / goes below this uri's path;
    a chained uri's target is where fsspec reads it from."""
    authority: str | None
    target: y2uri | None

    def __init__(self, o: Any, scheme: str | None = None):
        s = o['uri'] if isinstance(o, dict) and 'uri' in o else str(o)
        s, chained, rest = s.partition('::')
        self.target = type(self)(rest) if chained else None
        s, _, self._fragment = s.partition('#')
        s, _, self._query = s.partition('?')
        if match := SCHEME.fullmatch(s):
            head, s = match.groups()
            if scheme and head != scheme:
                raise ValueError(f'Two schemas in uri {head} {scheme}')
            self.scheme = head
            self.authority = None
            if s.startswith('//'):
                self.authority, slash, s = s[2:].partition('/')
                s = slash + s
        elif chained and s and '/' not in s:   # fsspec's bare protocol in a chain: gppu::file:///D:/TextLake
            self.scheme, self.authority, s = s, None, ''
        else:   # no scheme: the whole of it is a path, as gppu's y2uri reads it
            self.scheme, self.authority = scheme or 'null', ''
        self.path = y2path(s.split('/'))
        self._path_absolute = s.startswith('/')
        self._last_segment_empty = s.endswith('/') and bool(self.path)

    def __str__(self) -> str:
        path = str(self.path)
        if self._path_absolute:
            path = '/' + path
        elif path and self.authority:
            path = '/' + path
        if self._last_segment_empty:
            path += '/'
        result = self.scheme + (':' if self.authority is None else f'://{self.authority}') + path
        if self.authority is None and self.target is not None and not path:
            result = self.scheme
        if self._query:
            result += f'?{self._query}'
        if self._fragment:
            result += f'#{self._fragment}'
        return result if self.target is None else f'{result}::{self.target}'

    def __hash__(self) -> int: return hash(str(self))
    def __eq__(self, other): return str(self) == str(other)

    @property
    def selection(self) -> dict[str, Any]:
        """What the fragment selects: `anchor`, `text` (each prefix, start, end, suffix), `line`, `char` or `t` as (start, end)."""
        if not self._fragment:
            return {}
        anchor, _, directives = self._fragment.partition(':~:')
        result: dict[str, Any] = {}
        if match := RANGE.fullmatch(anchor):
            name, start, end = match.groups()
            number = float if name == 't' else int
            result[name] = (number(start) if start else None, number(end) if end else None)
        elif anchor:
            result['anchor'] = unquote(anchor)
        texts = []
        for directive in filter(None, directives.split('&')):
            name, _, value = directive.partition('=')
            if name != 'text':
                continue
            parts = [unquote(part) for part in value.split(',')]
            prefix = parts.pop(0)[:-1] if parts[0].endswith('-') else None
            suffix = parts.pop()[1:] if len(parts) > 1 and parts[-1].startswith('-') else None
            texts.append({'prefix': prefix, 'start': parts[0], 'end': parts[1] if len(parts) > 1 else None, 'suffix': suffix})
        if texts:
            result['text'] = texts
        return result
