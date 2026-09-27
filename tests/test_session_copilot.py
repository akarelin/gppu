"""Native VS Code append-log reconstruction keeps the original transcript intact."""
import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from gppu.fs import SessionHandler

STAMP = 1790390936747


def initial():
  return {'kind': 0, 'v': {'sessionId': 'copilot-native', 'responderUsername': 'GitHub Copilot',
    'version': 3, 'creationDate': STAMP - 1000, 'requests': [{
      'timestamp': STAMP, 'message': {'text': 'Document'},
      'response': [{'value': 'old response'}], 'modelId': 'copilot/auto'}]}}


def read(tmp_path, rows):
  path = tmp_path/'session.jsonl'
  raw = '\n'.join(json.dumps(row) for row in rows).encode('utf-8')
  path.write_bytes(raw)
  handler = SessionHandler()
  assert handler.identify_sync(path)
  _, session = handler.call_sync(path)
  assert session.records == tuple(rows)
  assert path.read_bytes() == raw
  return session


def test_final_request_response_replays_tail_replacement_without_duplicate_turns(tmp_path):
  rows = [initial(),
    {'kind': 1, 'k': ['requests', 0, 'result'], 'v': {'metadata': {'timestamp': 1790430000000}}},
    {'kind': 2, 'k': ['requests', 0, 'response'], 'i': 0,
     'v': [{'value': 'Documented '}, {'kind': 'inlineReference', 'name': 'detect_os()'}, {'value': '.'}]},
    {'kind': 2, 'k': ['requests', 0, 'response'], 'v': [{'value': ' Complete.'}]},
    {'kind': 3, 'k': ['requests', 0, 'result']}]
  before = deepcopy(rows)
  session = read(tmp_path, rows)
  assert rows == before
  assert (session.harness, session.uid) == ('copilot', 'copilot-native')
  assert [(turn.role, turn.text) for turn in session.turns] == [
    ('user', 'Document'), ('assistant', 'Documented detect_os(). Complete.')]
  assert session.span_start == datetime.fromtimestamp((STAMP - 1000) / 1000, timezone.utc)
  assert session.span_end == datetime.fromtimestamp(STAMP / 1000, timezone.utc)
  assert session.turns[1].timestamp is None, 'no explicit completion timestamp in this request'


@pytest.mark.parametrize('state', [1, 2, 3])
def test_native_terminal_completion_is_response_and_session_end(tmp_path, state):
  completed = 1790390964532
  rows = [initial(), {'kind': 1, 'k': ['requests', 0, 'modelState'],
    'v': {'value': state, 'completedAt': completed}}]
  session = read(tmp_path, rows)
  assert session.turns[0].timestamp == datetime.fromtimestamp(STAMP / 1000, timezone.utc)
  assert session.turns[1].timestamp == datetime.fromtimestamp(completed / 1000, timezone.utc)
  assert session.span_end == session.turns[1].timestamp


@pytest.mark.parametrize('state,completed', [(0, STAMP+1000), (1, STAMP-1), (1, 'unknown'), (1, True)])
def test_invalid_completion_is_not_an_invented_end(tmp_path, state, completed):
  with pytest.raises(ValueError, match='Copilot completion'):
    read(tmp_path, [initial(), {'kind': 1, 'k': ['requests', 0, 'modelState'],
      'v': {'value': state, 'completedAt': completed}}])


def test_running_request_without_response_and_later_append(tmp_path):
  rows = [initial(), {'kind': 2, 'k': ['requests'], 'v': [
    {'timestamp': STAMP+5000, 'message': {'text': 'Continue'}}]}]
  first = read(tmp_path, rows)
  assert [turn.text for turn in first.turns] == ['Document', 'old response', 'Continue']
  rows.append({'kind': 2, 'k': ['requests', 1, 'response'], 'v': [{'value': 'Done'}]})
  second = read(tmp_path, rows)
  assert [turn.text for turn in second.turns] == ['Document', 'old response', 'Continue', 'Done']
  assert first.records == second.records[:-1]


@pytest.mark.parametrize('mutation', [
  {'kind': 1, 'k': ['sessionId'], 'v': 'changed'},
  {'kind': 2, 'k': ['requests'], 'i': -1},
  {'kind': 2, 'k': ['requests'], 'i': 5},
  {'kind': 2, 'k': ['requests'], 'v': 'invalid'},
  {'kind': 1, 'k': ['requests', 5, 'message'], 'v': 'missing parent'},
  {'kind': 0, 'v': {'sessionId': 'replacement'}},
])
def test_incomplete_or_conflicting_patch_never_produces_a_session(tmp_path, mutation):
  with pytest.raises(ValueError):
    read(tmp_path, [initial(), mutation])
