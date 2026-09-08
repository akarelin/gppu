---
fileClass: Document
created: "2026-09-08 1250"
updated: "2026-09-08 1250"
generated: { by: "Claude/fable-5.1", at: "2026-09-08T12:50:00-07:00" }
---

# Environment and Jinja configuration

`gppu.Environment` is what an app knows about where it runs, and how to reach the rest of the fleet. It sits on top of `Env` and follows Y2's `_Environment`: lookups are strict, a missing key raises, and domain questions are methods.

## Basic level, no configuration file

Always available: `Environment.platform` (`windows`, `wsl`, `debian`, `macos`, the vocabulary of the RAN configuration), `host`, `user`, `home`, `os`, and the path grammar of `gppu/paths.j2` as methods: `win(sub, sep)`, `d(sub, sep)`, `wsl(path)`, `wsl_unc(sub)`, `posix(platform, sub)`, `tilde(sub)`, `volume(share)`, and `home_path(sub)` for this host. `trace()` returns the trace rules `Env` loaded.

## Fleet level, on request

`Environment.fleet(topology)` loads `RAN/_config/_ran.yaml.j2`; an app config with a `topology:` key does the same through `Env.from_env`. Nothing loads it by default. Then: `host_row(name)`, `ssh(name, env)` (the ssh command for a host or a workstation environment), `mount(nas, share)`, `local(location, host, platform)` and `smb(location)`.

## Jinja configuration files

`dict_from_yml` renders a file ending in `.j2` with Jinja before parsing it as YAML, so `!include x.yaml.j2` and `topology: x.yaml.j2` both work. The template sees `load('lists/x.yaml')` to read a list relative to itself, `| yaml` to write a value as a YAML scalar or flow collection, gppu's helpers as filters, and `{% import 'paths.j2' as p %}`: templates resolve beside the file first, then in gppu itself, where `paths.j2` lives.

Two kinds of files make a configuration: lists that are regenerated, not edited, and Jinja templates that loop over them and grow the tree the apps read. Every path is built by a `paths.j2` macro, so a home directory or a mount root changes in one place.
