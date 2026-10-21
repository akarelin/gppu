#!/usr/bin/env python
"""A utility on the app object. Its configuration, and everything the shared one
constructs, is there when the object is; a location's rules turn an address into a path
on this host, and gppufs lists it the same way wherever it is. Zero arguments."""
from gppu import App, Env, State
from gppu.gppu import _DC
from gppu.fs import GppuFileSystem


class Location(_DC):
  name: str
  tags: list
  canonical: str
  mirrors: list
  local: str


State.register(Location=Location)


class Browse(App):
  def main(self) -> None:
    print(f'{Env.host} ({Env.platform})\n')
    for uid, location in State.locations.items():
      print(f'{uid:14} {location.name:22} {location.local or "-":34} {location.canonical:40} {" ".join(location.mirrors)}')

    for address in self.my_list('browse/addresses'):
      uid, local = Env.locations.location_of(address), Env.locations.local_of(address)
      resource = State.resources[address.partition('://')[0]]['class']
      print(f'\n{address}  ->  {resource}  ->  {uid or "no location"}  ->  {local or "not on this host"}')
      if local:
        for entry in GppuFileSystem(State.locations[uid].local).ls(local, detail=False): print(f'  {entry}')


if __name__ == '__main__':
  Browse().main()
