from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from .session import Session, SessionStats

ObjectT = TypeVar('ObjectT')
StatsT = TypeVar('StatsT')


@dataclass(frozen=True)
class Handler(Generic[ObjectT, StatsT]):
  load_object: Callable[[Path], ObjectT]
  derive_stats: Callable[[ObjectT], StatsT]

  def __call__(self, source: Path) -> tuple[StatsT, ObjectT]:
    obj = self.load_object(source)
    return self.derive_stats(obj), obj


session_handler = Handler(Session.from_path, SessionStats.from_session)
