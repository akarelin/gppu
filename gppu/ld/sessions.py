"""The sessions' records (_Standards/Linked Data/Linked Data - Sessions): schema `sessions`, shard1 0x20, built on Linked Data's
record (gppu.ld) and served at /ld/v1/sessions, documented at /ld/v1/sessions/docs.

A session's type is its harness, and it is known by its type and `uid`, the id its harness gives it; a message is one line its
harness wrote in a session, its type its kind and its parent the session; a link joins a session or a message to the task it worked
on, or a session to the session that continued it (`next`). Each is created, read, updated, deleted and searched at its own path,
`/sessions`, `/sessions/messages` and `/sessions/links`, and the sessions' types at `/sessions/types`."""
from typing import Self

from sqlalchemy import String, UniqueConstraint
from sqlmodel import Field, select

from . import _Link, _Record, _Type, api_at, operations


class Type(_Type, table=True):
    """The sessions' types and statuses: a session's harness, a message's kind, a link's kind."""
    __tablename__, __table_args__, __shard__ = 'types', (UniqueConstraint('shard', 'slug'), {'schema': 'sessions'}), 0x2000


class _Session(_Record):
    """A session's column, and its rule: a session is known by its type and uid, so one created with a type and uid that are there
    is written into it, as its harness writes more."""
    uid: str | None = Field(None, sa_type=String, description='The id its harness gives it, unique within its `type`.')

    @classmethod
    async def create(cls, sent: '_Session') -> Self:
        known = sent.uid and (await cls.db().exec(select(cls.id).where(cls.type == sent.type, cls.uid == sent.uid))).first()
        return await cls.update(known or None, sent)


class Session(_Session, table=True):
    """A container of its messages; a subagent's session has the session that started it as its `parent_id`. `status` `active`
    while its harness writes it, `completed` once it ended, `discarded` once it is not kept; `span` from its first message to its
    last; `name` its title once it is named. `data.host`, `data.cwd` where it ran; `data.title`, `data.topic`, `data.models`;
    `data.turns`, `data.human`, `data.messages` how many turns, human turns and messages; `data.subagent`, `data.sidechain_only`
    whether a subagent ran it. `meta.read` how far each source was read, in lines and bytes; `meta.parent_uid` the uid of the session
    that started it, until that session is there; `meta.named`, `meta.processed` how it was named and processed; `meta.registry` the
    record it was imported from."""
    __tablename__, __table_args__, __shard__ = 'sessions', (UniqueConstraint('type', 'uid'), {'schema': 'sessions'}), 0x2001


class Message(_Record, table=True):
    """One line its harness wrote in a session, of one of the five kinds, its type: `user`, `agent`, `thinking`, `tool_use`,
    `tool_result`. Its `parent_id` is the session; `span` when it was written; `data` the line as the harness wrote it; `meta.uid`
    the id its harness gives it, a message being written once; `meta.line` its line in the session's file, which orders the
    messages."""
    __tablename__, __table_args__, __shard__ = 'messages', {'schema': 'sessions'}, 0x2002


class Link(_Link, table=True):
    """A link from a session or a message to the task it worked on, or from a session to the session that continued it (`next`).
    `status` `new` while it is a proposal, `active` once it holds. `data.conclusion`, `data.messages` what the session concluded
    for the task and the messages that show it; `data.started`, `data.ended` when the work on the task started and ended;
    `meta.evidence` why the link was proposed; `meta.generated` who proposed it, when and how."""
    __tablename__, __table_args__, __shard__ = 'links', {'schema': 'sessions'}, 0x2010


app = api_at('/sessions', 'sessions', 'The sessions of every harness, their messages and their links.',
             operations('/sessions/types', _Type, 'session type', Type),   # before /sessions, whose /{id} would take their word
             operations('/sessions/messages', _Record, 'session message', Message),
             operations('/sessions/links', _Link, 'session link', Link),
             operations('/sessions', _Session, 'session', Session))
