#!/usr/bin/env python
"""Contacts from their sources into the lake, one document per person or company.

The sources, the lake and the grammars are on the app object when it is constructed. Nothing
here knows a path or a host: a source says which location its records are in, the location
says where it is on the machine this runs on, so the same run works on a workstation and
under Dagster. A contact card is not the entity — the man is: his permalink is minted once
from his name and kept in his document, so a later run knows him again however the card has
changed, and so he keeps his address when the mailbox the card was in is gone.

The sync owns the frontmatter fields it writes and the generated block. Every other key, and
everything below that block, is Alex's and goes back untouched — including `same_as`, which
says two of them are one man: the sources of the one he points away from join the one he
names, and its document stays as the record of the decision. Zero arguments."""

import json
from datetime import datetime
from pathlib import Path

import yaml

from gppu import App, Environment, Info, State
from gppu.gppu import _DC

GENERATED = 'contacts/0.1.0'
OWN = ('fileClass', 'uri', 'name', 'company', 'title', 'emails', 'phones',
       'identities', 'photo', 'sources', 'generated')
OPEN, CLOSE = '<!-- generated -->', '<!-- /generated -->'


class Source(_DC):
  name: str
  provides: str
  records: str
  extensions: list
  exclude: list
  address: str
  local: str


class EntityKind(_DC):
  uid: str
  name: str
  scheme: str
  fileClass: str
  permalink: str
  document: str


State.register(Source=Source, EntityKind=EntityKind)


class Document:
  """One entity's document in the lake: what the sync writes, and what Alex wrote."""

  def __init__(self, path: Path):
    self.path, self.front, self.notes = path, {}, ''
    if not path.exists(): return
    body = text = path.read_text(encoding='utf-8-sig')
    if text.startswith('---'):
      _, front, body = text.split('---', 2)
      self.front = yaml.safe_load(front) or {}
    self.notes = body.partition(CLOSE)[2].strip() if CLOSE in body else '' if self.mine else body.strip()

  @property
  def mine(self) -> bool:
    """Written by this sync, so a body with no block of its own carries no text of his."""
    return (self.front.get('generated') or {}).get('by', '').startswith(GENERATED.partition('/')[0])

  def write(self, fields: dict, generated: str) -> bool:
    """The sync's fields, his keys over them, the generated block, then his own text. False
    when nothing about the entity changed, so a run that finds no news writes nothing."""
    front = fields | {key: value for key, value in self.front.items() if key not in OWN}
    front['generated'] = {'by': GENERATED, 'at': datetime.now().astimezone().isoformat(timespec='seconds')}
    body = f"# {fields['name']}\n\n{OPEN}\n{generated}\n{CLOSE}\n"
    if self.notes: body += f'\n{self.notes}\n'
    text = f"---\n{yaml.safe_dump(front, sort_keys=False, allow_unicode=True, default_flow_style=None)}---\n\n{body}"
    if self.path.exists() and self.unchanged(text): return False
    self.path.parent.mkdir(parents=True, exist_ok=True)
    self.path.write_text(text, encoding='utf-8', newline='\n')   # the lake reads the same everywhere
    return True

  def unchanged(self, text: str) -> bool:
    """The same document but for the moment it says it was written."""
    def lines(text): return [line for line in text.splitlines() if not line.startswith('generated:')]
    return lines(self.path.read_text(encoding='utf-8-sig')) == lines(text)


class Contacts(App):
  def main(self) -> None:
    self.rules = Environment.entities
    self.kinds = {kind.scheme: kind for kind in State.entities.values()}
    self.lake = Path(Environment.locations.local_of('lake://'))
    self.read_documents()
    self.photos = {self.rules.slug_of(path.stem): address
                   for source in self.sources('photos') for path, address in self.records(source)}

    entities: dict[str, list] = {}
    for source in self.sources('contacts'):
      for path, address in self.records(source):
        record = json.loads(path.read_text(encoding='utf-8'))
        entities.setdefault(self.permalink(record, address), []).append((record, address))

    written = sum(self.document(uri, seen) for uri, seen in sorted(entities.items()))
    photographed = sum(1 for seen in entities.values() if self.photo(seen[0][0]))
    Info(f'{len(entities)} people and companies, {len(self.minted)} of them new, '
         f'{photographed} with a photo; {written} documents written')

  # -- the sources, through the locations -------------------------------------------------
  def sources(self, provides: str) -> list:
    """Every source of that kind of record the machine this runs on reaches."""
    return [source for source in State.sources.values() if source.provides == provides and source.local]

  def records(self, source: Source) -> list:
    """Every record of a source, with the address it has: the location's own address,
    continued by where the record is below it."""
    root = Path(source.local)
    return [(path, f'{source.address}/{path.relative_to(root).as_posix()}')
            for path in sorted(root.glob(source.records))
            if path.suffix.lower() in source.extensions and path.name not in source.exclude and path.is_file()]

  # -- the permalink: minted once, then recognised ----------------------------------------
  def read_documents(self) -> None:
    """What the lake already knows: which entity a source record belongs to, which entity an
    identity is, and which of them Alex has declared one man."""
    self.by_source, self.by_identity, self.same_as, self.documents, self.minted = {}, {}, {}, {}, {}
    for kind in self.kinds.values():
      for path in sorted(self.path_of(self.address('document', kind, 'any')).parent.glob('*.md')):
        document = Document(path)
        if not (uri := document.front.get('uri')): continue
        self.documents[uri] = document
        self.same_as[uri] = document.front.get('same_as')
        for address in document.front.get('sources') or []: self.by_source[address] = uri
        for identity in document.front.get('identities') or []: self.by_identity[identity] = uri

  def permalink(self, record: dict, address: str) -> str:
    """Who a record is about: the one already listing this record, the one with the same
    identity, or a new one minted from the name — and then whoever Alex says it is."""
    identity = self.rules.identity_of(record)
    uri = self.by_source.get(address) or self.by_identity.get(identity)
    if not uri:
      kind = State.entities[self.rules.kind_of(record)]
      uri = self.address('permalink', kind, self.free(self.rules.slug_for(record)))
      self.minted[uri] = identity
    self.by_source[address], self.by_identity[identity] = uri, uri
    while self.same_as.get(uri): uri = self.same_as[uri]
    return uri

  def free(self, slug: str) -> str:
    """A slug nobody has taken."""
    taken = {uri.rpartition('/')[2] for uri in (*self.documents, *self.minted)}
    return slug if slug not in taken else next(f'{slug}-{n}' for n in range(2, 999) if f'{slug}-{n}' not in taken)

  # -- the document ------------------------------------------------------------------------
  def document(self, uri: str, seen: list) -> bool:
    kind, records = self.kinds[uri.partition('://')[0]], [record for record, address in seen]
    path = self.path_of(self.address('document', kind, uri.rpartition('/')[2]))
    fields = {
      'fileClass': kind.fileClass,
      'uri': uri,
      'name': str(self.rules.name_of(records[0])),   # a name that reads as a number comes back as one
      'company': self.first(records, 'companyName'),
      'title': self.first(records, 'jobTitle'),
      'emails': sorted({email['address'] for record in records
                        for email in record.get('emailAddresses') or [] if email.get('address')}),
      'phones': sorted({phone for record in records for phone
                        in (record.get('businessPhones') or []) + [record.get('mobilePhone')] if phone}),
      'identities': sorted({self.rules.identity_of(record) for record in records}),
      'photo': self.photo(records[0]),
      'sources': [address for record, address in seen],
    }
    document = self.documents.get(uri) or Document(path)
    return document.write({key: value for key, value in fields.items() if value}, self.generated(fields, records))

  def address(self, grammar: str, kind: EntityKind, slug: str) -> str:
    """An address of an entity: the grammar its kind names, filled in with the kind's own row."""
    return self.rules.render_template(getattr(kind, grammar), **kind.data, slug=slug)

  def path_of(self, address: str) -> Path:
    """Where an address in the lake is on this machine. The lake is resolved once, through the
    locations; what is below it is below it wherever the lake is."""
    return self.lake / address.partition('://')[2]

  def photo(self, record: dict) -> str:
    """The entity's photo, by the name the photo is filed under."""
    return self.photos.get(self.rules.filed_as(record), '')

  @staticmethod
  def first(records: list, field: str) -> str:
    return next((record[field] for record in records if record.get(field)), '')

  @staticmethod
  def generated(fields: dict, records: list) -> str:
    """What the sources say about the entity, as the document shows it."""
    lines = [' — '.join(part for part in (fields.get('company'), fields.get('title')) if part)]
    lines += [', '.join(str(part) for part in (place.get('street'), place.get('city'), place.get('state'),
                                               place.get('postalCode'), place.get('countryOrRegion')) if part)
              for record in records for place in record.get('postalAddresses') or []]
    lines += [record['personalNotes'].replace('\r\n', '\n').strip() for record in records if record.get('personalNotes')]
    return '\n\n'.join(line for line in lines if line.strip())


if __name__ == '__main__':
  Contacts().main()
