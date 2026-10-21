"""YMRO: every class's part of a step, base class first, synchronous or asynchronous."""
import asyncio

import pytest

from gppu import mixin_Stepper, sync


class Base(mixin_Stepper):
  def __init__(self): self.seen = []
  def __init(self): self.seen.append('base init')
  def __load(self): self.seen.append('base load')
  def __start(self): self.seen.append('base start')
  def __stop(self): self.seen.append('base stop')


class Child(Base):
  def __load(self): self.seen.append('child load')
  def __start(self): self.seen.append('child start')


class AsyncChild(Base):
  @sync
  async def __load(self):
    await asyncio.sleep(0)
    self.seen.append('async load')


def test_a_step_runs_every_class_part_base_first_and_once():
  child = Child()
  assert child.init() is None and child.load() is None and child.start() is None
  child.start()
  assert child.seen == ['base init', 'base load', 'child load', 'base start', 'child start']
  assert child.initialized and child.loaded and child.started


def test_load_needs_init():
  with pytest.raises(AssertionError): Child().load()


def test_stop_undoes_load_and_start():
  child = Child()
  child.init(); child.load(); child.start(); child.stop()
  assert not child.loaded and not child.started and child.stopped
  assert child.seen[-1] == 'base stop'


def test_an_asynchronous_part_runs_through_sync():
  child = AsyncChild()
  child.init(); child.load()
  assert child.seen == ['base init', 'base load', 'async load'] and child.loaded
