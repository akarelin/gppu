# .. deleted_by_fable.py: code gppu had and lost. Nothing imports this file and it is not part of gppu.
# .. Part 1 is gppu.py, app.py, iot.py, data.py and __init__.py as they were on 2026-11-20 at 23:34 (94b4f31): every
# .. class, function and statement that was gone, or read differently, on 2026-11-24 at 15:35 (920dfc8). Each one is
# .. whole and in its old form, with the comment lines that stood right above it. A line above each says which:
# ..   "gone"     nothing of that name was left in gppu;
# ..   "changed"  something of that name was still there, in the file named, with other code.
# .. Part 2 is what those files had on 2026-11-11 and on 2026-10-19 and no longer had on 2026-11-20.
# .. Not here: import lines; uuid_create and probe_path, which moved to gppu/fs unchanged in what they do; and the
# .. other files of the package that changed in those days (28 of them, under gppu/fs, gppu/ld and gppu/tui, with
# .. chrome.py). What went from gppu/tui is in archive/gppu/tui/.



# region - gppu/gppu.py as of 2026-11-20 (52)

# .. gone
try: _ver_full = _pkg_version('gppu')
except PackageNotFoundError: _ver_full = '0.0.0'


# .. gone
_ver_parts = _ver_full.split('.')


# .. gone
VER_GPPU_BASE = '.'.join(_ver_parts[:3])


# .. gone
VER_GPPU_BUILD = _ver_parts[3] if len(_ver_parts) > 3 else '0'


# .. changed
VER_GPPU = _ver_full


# .. gone
_log_root = logging.getLogger('gppu'); _log_root.setLevel(logging.DEBUG)


# .. gone
_sh = logging.StreamHandler(sys.stderr); _log_root.addHandler(_sh)


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
def full_path(path: str | Path, base_dir: str | Path | None = None, *, strict: bool = False) -> Path:
  """
    Resolve a user-supplied path to a local Path suitable for open()/read/write.

    Expands environment variables and ~. Leaves native absolute paths absolute.
    Resolves relative paths against base_dir, or cwd when base_dir is None.
    On Windows, maps WSL-style drive paths like /mnt/d/x to D:\\x.

    If strict=True, requires the resolved path to exist.
  """
  raw = os.path.expandvars(str(path))

  if detect_os() == OSType.W11 and len(raw) >= 7 and raw.startswith('/mnt/') and raw[5].isalpha() and raw[6] == '/': result = Path(f'{raw[5].upper()}:\\') / raw[7:]
  else: result = Path(raw)
  result = result.expanduser()

  if not result.is_absolute(): result = (Path.cwd() if base_dir is None else full_path(base_dir)) / result
  
  return result.resolve(strict=strict)


# .. changed; the one of 2026-11-24 is in gppu/fs/handlers.py
def probe_path(path: str | Path) -> dict:
  """Filesystem attributes and content handler without reading contents."""
  _CONFIG = {
    "ignored_suffixes": (".tmp", ".bak", ".swp"),
    "ignored_prefixes": ("~$",),
    "ignored_names": ("Thumbs.db", ".DS_Store", "desktop.ini"),
    "ignored_folders": (
      ".git", ".svn", "__pycache__", ".venv", "venv", "node_modules", ".idea", ".vscode",
      ".SynologyWorking Directory", ".SynologyWorkingDirectory", "$RECYCLE.BIN", "RECYCLE.BIN",
      "System Volume Information", "OneDriveTemp", "Cache", ".cache",
    ),
    "session_folders": (".hermes", ".gemini/antigravity", ".gemini/antigravity-cli", ".gemini/antigravity-cli/brain/*"),
    "partitioned_folders": {"Work": "WorkFolderHandler", "Projects": "ProjectsFolderHandler"},
    "suffix_handlers": {
      ".sqlite": "SqliteHandler", ".sqlite3": "SqliteHandler", ".db": "SqliteHandler",
      ".md": "MarkdownHandler", ".csv": "CSVHandler", ".log": "LogHandler",
      ".eml": "EmailHandler", ".msg": "EmailHandler", ".jsonl": "SessionHandler",
    },
    "named_handlers": {"conversations.json": "ExportHandler", "conversations-*.json": "ExportHandler"},
  }

  path = Path(path) # type: ignore
  info = path.info
  stat = path.stat(follow_symlinks=False)
  attributes = getattr(stat, "st_file_attributes", 0)

  result = {
    "symlink": info.is_symlink(),
    "junction": path.is_junction(),
    "folder": info.is_dir(follow_symlinks=False),
    "file": info.is_file(follow_symlinks=False),
    "offline": bool(attributes & 0x5000),
    "created": dt.fromtimestamp(stat.st_birthtime, timezone.utc)
               if getattr(stat, "st_birthtime", None) is not None else None,
    "modified": dt.fromtimestamp(stat.st_mtime, timezone.utc),
  }

  result["ignored"] = bool(path.name) and (
    path.suffix.casefold() in _CONFIG["ignored_suffixes"]
    or any(path.name.startswith(p) for p in _CONFIG["ignored_prefixes"])
    or path.name in _CONFIG["ignored_names"]
    or result["folder"] and (
      path.name in _CONFIG["ignored_folders"]
      or bool(attributes & 0x4)
    )
  )

  result["type"] = next(
    (k for k in ("symlink", "junction", "folder", "file") if result[k]),
    "other",
  )
  result["status"] = next(
    (k for k in ("symlink", "junction", "offline", "ignored") if result[k]),
    "normal",
  )

  handler = None
  if result["status"] == "normal":
    if result["folder"]:
      handler = (
        "SessionFolderHandler"
        if any(path.match(p) for p in _CONFIG["session_folders"])
        else _CONFIG["partitioned_folders"].get(path.name, "FolderHandler")
      )
    elif result["file"]:
      handler = (
        next((h for name, h in _CONFIG["named_handlers"].items() if path.match(name)),
             _CONFIG["suffix_handlers"].get(path.suffix.casefold(), "FileHandler"))
        if stat.st_size else "FileHandler"
      )

  result.update(
    handler=handler,
    size=stat.st_size if result["file"] else None,
    target=path.readlink() if result["symlink"] or result["junction"] else None,
    attributes=getattr(stat, "st_file_attributes", None),
  )
  return result


# .. gone
def safe_datetime(o: object) -> dt | None:
  if isinstance(o, int | float): 
    try: result = dt.fromtimestamp(o, MY_TZ)
    except (OverflowError, OSError, ValueError): return None
    return result
  
  if isinstance(o, dt):
    if o.tzinfo is None: return o.replace(tzinfo=MY_TZ)
    return o.astimezone(MY_TZ)

  if isinstance(o, str):
    try: result = dt.fromisoformat(o)
    except: return None
    if result.tzinfo is None: return result.replace(tzinfo=MY_TZ)
    return result.astimezone(MY_TZ)


# .. gone
def format_duration(seconds: int | float) -> str:
  """Format a duration as '0s' / '5s' / '12m 30s' / '2h 5m'.

  Input is seconds (use ``ms / 1000`` for millisecond inputs).  Returns
  ``'-'`` for negative values; ``0`` formats as ``'0s'`` so callers using
  this for uptime get a legitimate zero rather than a placeholder.
  """
  seconds = float(seconds)
  if seconds < 0: return "-"
  if seconds < 60: return f"{seconds:.0f}s"
  if seconds < 3600:
    m, s = divmod(seconds, 60)
    return f"{int(m)}m {int(s)}s"
  h, rem = divmod(seconds, 3600)
  m, _ = divmod(rem, 60)
  return f"{int(h)}h {int(m)}m"


# .. gone
def format_since(when) -> str:
  """Compact "time since" — '5s', '5m', '2h', '3d', '4w', '6mo', '2y'.

  Accepts ISO-8601 string, ``datetime``, or epoch seconds (int/float).
  Returns empty string on parse failure.  Negative deltas (future timestamps)
  return ``'0s'``.
  """

  moment = None
  if isinstance(when, dt):
    moment = when
  elif isinstance(when, (int, float)):
    moment = dt.fromtimestamp(float(when), tz=timezone.utc)
  elif isinstance(when, str):
    s = when.strip()
    if not s: return ""
    if s.endswith('Z'): s = s[:-1] + '+00:00'
    try: moment = dt.fromisoformat(s)
    except ValueError: return ""
  else:
    return ""

  if moment.tzinfo is None:
    moment = moment.replace(tzinfo=dt.now().astimezone().tzinfo)

  secs = int((dt.now(timezone.utc) - moment).total_seconds())
  if secs < 0:    return "0s"
  if secs < 60:   return f"{secs}s"
  mins = secs // 60
  if mins < 60:   return f"{mins}m"
  hrs = mins // 60
  if hrs < 24:    return f"{hrs}h"
  days = hrs // 24
  if days < 7:    return f"{days}d"
  if days < 30:   return f"{days // 7}w"
  if days < 365:  return f"{days // 30}mo"
  return f"{days // 365}y"


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
class TimeSpan(Span):
  """[start, end], its end None while it goes on; a date and a duration, [date, date + duration]; a date alone,
  [date, date + 1 day); a ts alone, [ts, ts + 1 second). A duration is a timedelta or seconds. `bounds` says
  which ends it holds: '[]' both, '[)' not its end."""
  start: dt
  end: dt | None
  bounds: str

  def __init__(self, start=None, end=None, *, date=None, duration=None, ts=None, bounds: str = '[]'):
    length = None
    if ts is not None: start, length, bounds = ts, timedelta(seconds=1), '[)'
    elif date is not None and duration is not None: start, length = date, duration if isinstance(duration, timedelta) else timedelta(seconds=duration)
    elif date is not None: start, length, bounds = date, timedelta(days=1), '[)'
    self.start = safe_datetime(start)
    if self.start is None: raise ValueError('TimeSpan requires a valid start')
    self.end = self.start + length if length is not None else None if end is None else safe_datetime(end)
    if end is not None and self.end is None: raise ValueError('TimeSpan requires a valid end or none')
    if self.end is not None and self.end < self.start: raise ValueError('TimeSpan end precedes start')
    if bounds not in ('[]', '[)'): raise ValueError(f"TimeSpan bounds are '[]' or '[)', not {bounds!r}")
    self.bounds = bounds


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
class Path(y2path, pathlib.Path):
  """A file system path: y2path's segments and operators, everything else from pathlib.Path."""
  # _drv, _root, _tail_cached, _str, _parts_normcase_cached, _hash, _info = (_cached() for _ in range(7))
  _raw_paths = property(lambda self: [str(self)])
  _str_normcase = property(lambda self: pathlib.PurePath(self)._str_normcase)
  # pathlib keeps what it parsed; a Path's segments change, so it parses them each time and keeps nothing
  _drv = property(lambda self: pathlib.PurePath(self).drive, lambda self, value: None)
  _root = property(lambda self: pathlib.PurePath(self).root, lambda self, value: None)
  _tail_cached = property(lambda self: pathlib.PurePath(self)._tail, lambda self, value: None)

  def __truediv__(self, other: str | y2path) -> Path: return type(self)(self, other)
  def __eq__(self, other): return str(self) == str(type(self)(other)) if isinstance(other, PurePath) else y2path.__eq__(self, other)
  __hash__ = y2path.__hash__

  def copy(self, *args, **kwargs): return y2path.copy(self) if not args and not kwargs else pathlib.Path.copy(self, *args, **kwargs)

  def probe(self) -> dict:
    """Filesystem attributes and content handler without reading contents."""
    return probe_path(self)


# .. gone
deepdict: Callable[[], DefaultDict[Any, Any]] = lambda: defaultdict(deepdict)


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
def dict_to_yml(filename: str | Path, data=None, sort_keys=False):
  class IndentedListDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
      return super(IndentedListDumper, self).increase_indent(flow, False)

  assert filename
  if not data: return
  redata = dict_sanitize(data, sort_keys=sort_keys)

  yaml.add_representer(defaultdict, SafeRepresenter.represent_dict)
  yaml.add_representer(UserDict, SafeRepresenter.represent_dict)
  yaml.add_representer(set, SafeRepresenter.represent_list)
  yaml.add_representer(tuple, _tuple_representer)

  with open(filename,'w+', encoding='utf-8') as f:
    try: yaml.dump(redata, f, indent=2, Dumper=IndentedListDumper, sort_keys=sort_keys, width=2147483647)
    except Exception as err:
      error = f"Error dumping {filename}\n{err} {type(err)}\n{pfy(redata)}\n\n"
      with open(str(filename) + '_error.txt', 'w+', encoding='utf-8') as ferr: ferr.write(error)


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
def dict_from_yml(filename: str | Path) -> dict:
  """ yaml file to dictionary, resolving includes, but not templates"""
  filename = full_path(filename)
  dir_stack: list[Path] = [filename.parent]

  class Loader(YmlLoader): pass

  def yml_include(loader: FullLoader, node: Node) -> Any:
    fn = full_path(loader.construct_scalar(node), dir_stack[-1])

    dir_stack.append(fn.parent)

    try:
      with open(fn, "r", encoding='utf-8') as f:
        if fn.suffix.lower().endswith('.json'): return json.load(f)                        
        return yaml.load(f, Loader=Loader)
    finally: dir_stack.pop()

  Loader.add_constructor("!include", yml_include)

  with open(filename, encoding='utf-8') as f: return dict(yaml.load(f, Loader=yaml.FullLoader))


# .. gone
def dict_to_json(filename: str | Path, data=None, indent=2):
  assert filename
  if not data: return
  with open(filename, 'w', encoding='utf-8') as f:
    try: json.dump(data, f, indent=indent, ensure_ascii=False, default=str)
    except Exception as err:
      error = f"Error dumping {filename}\n{err} {type(err)}\n{pfy(data)}\n\n"
      with open(str(filename)+'_error.txt', 'w', encoding='utf-8') as ferr: ferr.write(error)


# .. gone
def dict_from_json(filename: str | Path):
  with open(filename, encoding='utf-8') as f: return json.load(f)


# .. gone
def inline_config(filename: str | Path) -> str:
  """ Not human reviewed. This method was found in the middle of yaml code that it has not business be a part of  """
  """The YAML a script carries inline: in a .py the string its global MANIFEST is assigned, read without running
  the script; in a .cmd the :: lines it opens with; in a .ps1 the .NOTES of the <# #> block it opens with, nothing
  below either block read. A script with none raises."""
  filename = full_path(filename)
  suffix = filename.suffix.lower()
  with open(filename, encoding='utf-8-sig') as f:
    if suffix == '.py':
      for node in ast.parse(f.read(), str(filename)).body:
        if (isinstance(node, ast.Assign) and [getattr(target, 'id', None) for target in node.targets] == ['MANIFEST']
            and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)): return node.value.value
    elif suffix == '.cmd':
      lines = []
      for line in f:
        if not line.startswith('::'): break
        lines.append(line[2:])
      if lines: return ''.join(lines)
    elif suffix == '.ps1':
      lines = iter(f)
      if next((line for line in lines if line.strip()), '').strip() == '<#':
        notes, keyword = [], None
        for line in lines:
          if line.strip() == '#>': break
          if re.fullmatch(r'\.[A-Za-z]+', line.strip()): keyword = line.strip().upper()
          elif keyword == '.NOTES': notes.append(line)
        if notes: return ''.join(notes)
  raise ValueError(f'{filename}: no inline configuration')


# .. gone
def jinja_helpers() -> dict:
  """gppu's own filters, offered to every Jinja environment it builds."""
  return {
    'safe_int': safe_int, 'safe_float': safe_float, 'safe_list': safe_list,
    'safe_timedelta': safe_timedelta, 'dict_sanitize': dict_sanitize,
    'pretty_timedelta': pretty_timedelta, 'pfy': pfy, 'slugify': slugify,
  }


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
class JinjaEnvironment(SandboxedEnvironment, NativeEnvironment):
  """Jinja templates with native values and gppu's formatting helpers."""

  def __init__(self, **options):
    super().__init__(undefined=StrictUndefined, autoescape=False, **options)
    self.filters.update(jinja_helpers())
    self.globals.update(jinja_helpers())


# .. gone
class JinjaDocument(SandboxedEnvironment):
  """Jinja templates that write a document rather than a value.

  A value is rendered natively, so `{{ 1 }}` is the number. A document must not be:
  a macro that writes `"seven"` would have its quotes evaluated away and the YAML it
  was building would stop being YAML. This renders text, and reaches the files beside
  the template so a document can import macros and read the facts it applies them to.
  """

  def __init__(self, search_path: Path, **options):
    super().__init__(loader=FileSystemLoader(str(search_path)), undefined=StrictUndefined, autoescape=False,
                     trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True, **options)
    self.filters.update(jinja_helpers())
    self.globals.update(jinja_helpers())
    self.filters['from_yaml'] = lambda name: dict_from_yml(full_path(name, search_path))
    self.filters['to_yaml'] = lambda value: yaml.safe_dump(value, default_flow_style=True).strip()
    self.globals['hostname'] = lambda: socket.gethostname().split('.')[0].casefold()
    # The builtins a document needs to merge a row onto its template and count what
    # it loops over; the same set Y2 gives its own templates.
    self.globals.update({name: getattr(builtins, name) for name in
                         ('dict', 'list', 'int', 'float', 'str', 'len', 'sorted', 'min', 'max', 'range')})


# .. gone
@pass_context
def _render_template_in(context, name: str, **values) -> Any:
  """A named template rendered from inside another one: it sees the caller's values, and its keywords win over them."""
  return jinja.get_template(name).render(context.get_all() | values)


# .. changed; on 2026-11-24 the name is an assignment in gppu/gppu.py
def render_template(template: str, values: Mapping = {}, /, **more) -> Any:
  """template, the name of a template in a `*_templates` block or Jinja text, rendered with values and more."""
  values = {**values, **more}
  if template in jinja.loader.mapping: return jinja.get_template(template).render(values)
  return _jinja_compile(template).render(values)


# .. gone
def jinja_configuration(node: Any) -> None:
  """Every `macros:` block and every named template (a `*_templates` or `generators` block) of a configuration,
  wherever it sits, added to gppu's Jinja: a macro is then callable by its name from any template."""
  if not isinstance(node, dict): return
  for key, value in node.items():
    if key == 'macros' and isinstance(value, str):
      module = jinja.from_string(value).make_module()
      jinja.globals.update({name: getattr(module, name) for name in dir(module) if not name.startswith('_')})
    elif (key == 'generators' or str(key).endswith('_templates')) and isinstance(value, dict):
      jinja.loader.mapping.update(value)
      jinja.cache.clear()
    else: jinja_configuration(value)


# .. gone
def templates_of(node: Any, found: dict | None = None) -> dict:
  """Every template of a configuration by its name: a mapping in a `templates:` block. A name is declared once."""
  found = {} if found is None else found
  if isinstance(node, list):
    for value in node: templates_of(value, found)
  if not isinstance(node, dict): return found
  for key, value in node.items():
    if key == 'templates' and isinstance(value, dict):
      for name, template in value.items():
        if not isinstance(template, dict): continue
        if name in found: raise ValueError(f'template {name!r} is declared twice')
        found[name] = template
    templates_of(value, found)
  return found


# .. changed; on 2026-11-24 the name is an assignment in gppu/gppu.py
def apply_template(node: Any, templates: dict) -> Any:
  """Every row of node whose `template:` names one of templates, merged over that template: the row wins. The
  template's Jinja that reads the row stays as written, for the app that renders it."""
  if isinstance(node, list): return [apply_template(value, templates) for value in node]
  if not isinstance(node, dict): return node
  node = {key: apply_template(value, templates) for key, value in node.items()}
  if isinstance(name := node.get('template'), str) and name in templates:
    return apply_template(templates[name], templates) | node
  return node


# .. gone
@cache
def _jinja_compile(template: str):
  return jinja.from_string(template)


# .. changed; on 2026-11-24 the name is an assignment in gppu/gppu.py
def jinja_template(template: Any, /, **data) -> Any:
  """Render Jinja strings, including keys and values of a configuration node; missing inputs raise."""
  if isinstance(template, dict):
    return {key: jinja_template(value, **data) for key, value in
            ((jinja_template(key, **data), value) for key, value in template.items()) if key != ''}
  if isinstance(template, list): return [jinja_template(value, **data) for value in template]
  if not isinstance(template, str): return template
  if '{{' not in template and '{%' not in template and '{#' not in template: return template
  value = _jinja_compile(template).render(**data)
  if isinstance(value, Undefined): return str(value)
  return value


# .. gone
@cache
def _jinja_inputs(template: str) -> frozenset[str]:
  """The names a Jinja string reads beyond gppu's own Jinja globals."""
  environment = JinjaEnvironment()
  return frozenset(meta.find_undeclared_variables(environment.parse(template))) - set(environment.globals)


# .. changed; on 2026-11-24 the name is an assignment in gppu/gppu.py
def jinja_fill(node: Any, /, **data) -> Any:
  """Render the Jinja strings of a configuration node, keys included, that read only the given names. Jinja that
  reads any other name stays as written, for the app that renders it later."""
  if isinstance(node, dict): return {jinja_fill(key, **data): jinja_fill(value, **data) for key, value in node.items()}
  if isinstance(node, list): return [jinja_fill(value, **data) for value in node]
  if isinstance(node, str) and ('{{' in node or '{%' in node) and (inputs := _jinja_inputs(node)) and inputs <= data.keys():
    return jinja_template(node, **data)
  return node


# .. gone
jinja.globals.update({name: getattr(builtins, name) for name in
                      ('dict', 'list', 'int', 'float', 'str', 'bool', 'len', 'round', 'sorted', 'min', 'max', 'range')},
                     re=re, render_template=_render_template_in)


# .. gone
_IGNORE_FUNCTIONS = ['dpcp', 'trace', 'pcp', 'Trace', 'Info', 'Debug', 'Warn', 'Error', '_LogColorizer', '_PlainFormatter']


# .. gone
def dpcp(*a: Any, conditional: Optional[bool] = None, rules: Dict[str, bool] = {}, no_prefix: bool = False, severity: Optional[str] = None, **kw: Any) -> str | None:
  """ Version of pcp that adds info on where it was called from """
  def is_traced(name : Optional[str] = None) -> bool:
    if not conditional: return True
    if not name or name not in rules: return rules.get('all', False)
    else: return rules.get(name, False)

  def is_ignored(f, fi) -> bool:
    if 'python' in fi.filename: return True # !!! Ignoring all python3 libraries
    elif fi.function in _IGNORE_FUNCTIONS: return True
    elif 'self' in f.f_locals and f.f_locals['self'].__class__.__name__ in _IGNORE_FUNCTIONS: return True
    return False

  print = lambda *a, **kw: None

  if not conditional and rules: conditional = True
  frame = inspect.currentframe()
  if frame is None: return None
  frame_info = inspect.getframeinfo(frame)
  func_name = frame_info.function
  filename = frame_info.filename

  frame = frame.f_back
  while frame and frame.f_back:
    frame = frame.f_back
    frame_info = inspect.getframeinfo(frame)
    filename = frame_info.filename
    func_name = frame_info.function
    if not is_ignored(frame, frame_info): break

    func_name = _remove_prefixes(func_name, _SHORTEN_BY_PREFIX)

  if frame is None: print(f"\tframe is None"); return None

  if not is_traced(func_name): print(f"\tis_traced({func_name}) is False"); return None
  module = filename.rsplit('/', 1)[-1].rsplit('.', 1)[0]
  if not is_traced(module) or not is_traced(f"{module}.{func_name}"): print(f"\tis_traced({module}.{func_name}) is False"); return None

  if 'self' in frame.f_locals: 
    if not is_traced(class_name := frame.f_locals["self"].__class__.__name__): print(f"\tis_traced({class_name}) is False"); return None
    if not is_traced(f"{class_name}.{func_name}"): print(f"\tis_traced({class_name}.{func_name}) is False"); return None
    _ = ['GRAY0', f"{class_name}.", 'GRAY1', f".{func_name}"]
  else: _ = ['GRAY1', f".{func_name}"]
  _ += ['NONE']

  if severity: _ = [_SEVERITY_COLORS.get(severity, _SEVERITY_COLORS[None]), severity] + _
  if no_prefix: _ = list(a)
  else: _ += list(a)

  result = pcp(*_, **kw)
  # Never return None - return empty string instead to prevent logging issues
  return result if result is not None else ''


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
class _LogColorizer(logging.Formatter):
  """A record as gppu's coloured line: severity, caller, then the arguments as they were given."""
  ANSI = re.compile(r'\x1b\[[0-9;]*m')
  no_prefix = False

  def format(self, record: logging.LogRecord) -> str:
    args = list(record.gppu_args) if hasattr(record, 'gppu_args') else [record.getMessage()]
    if not self.no_prefix:
      function = _remove_prefixes(record.funcName or '', _SHORTEN_BY_PREFIX)
      class_name = getattr(record, 'gppu_class', '')
      caller = f'{class_name}.{function}' if class_name else function
      severity = 'Warn' if record.levelno == logging.WARNING else record.levelname.title()
      args = [_SEVERITY_COLORS.get(severity, _SEVERITY_COLORS[None]), severity, 'GRAY1', caller, 'NONE'] + args
    text = pcp(*args)
    if record.exc_info: text += '\n' + logging.Formatter().formatException(record.exc_info)
    if record.stack_info: text += '\n' + record.stack_info
    return text


# .. gone
class _PlainFormatter(_LogColorizer):
  """The line without colours or prefix, for the log file."""
  no_prefix = True

  def format(self, record: logging.LogRecord) -> str: return self.ANSI.sub('', super().format(record))


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
class _EmptyMessageFilter(logging.Filter):
  """Drops an empty record, and a Debug record the trace rules do not trace."""

  def filter(self, record: logging.LogRecord) -> bool:
    if record.levelno == logging.DEBUG:
      function = _remove_prefixes(record.funcName or '', _SHORTEN_BY_PREFIX)
      names = [function, record.module, f'{record.module}.{function}']
      if class_name := getattr(record, 'gppu_class', ''): names += [class_name, f'{class_name}.{function}']
      if not all(TRACE_RULES[name] if name in TRACE_RULES else TRACE_RULES.get('all', False) for name in names): return False
    return bool(record.getMessage().strip() or record.exc_info)


# .. gone
# ^~            Logger
TRACE_RULES: dict = {}


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
class Logger:
  """The program's log: the console the bootstrap started, with colours and trace rules, and the file mirror. Its
  calls reconfigure it: ``Logger.init_logger(name, trace_rules)``, ``Logger.enable_file_logging(log_file=...)``.
  A class logs with it through ``mixin_Logger``."""

  trace_folder: str = '.'
  trace_rules: dict = TRACE_RULES

  _root = _logger = _log_root
  _console = _sh
  _console.setFormatter(_LogColorizer())
  _console.addFilter(_EmptyMessageFilter())
  _file_handlers: dict[str, logging.Handler] = {}   # on the shared parent, so classes made earlier receive them


  @staticmethod
  def init_logger(name: str = 'gppu', trace_rules: dict | None = None) -> None:
    """Name the global logger, and optionally set the trace rules."""
    if trace_rules is not None:
      trace_rules = dict(trace_rules)
      TRACE_RULES.clear()
      TRACE_RULES.update(trace_rules)
    Logger._logger = Logger._root if name == 'gppu' else Logger._root.getChild(name)


  @staticmethod
  def enable_file_logging(name: str | None = None, log_dir: str | Path | None = None,
                          level: int = logging.DEBUG, log_file: str | None = None) -> Path:
    """Mirror logs to an explicit `log_file`, or an explicit name + log_dir.

    Env passes its `log_file` when YAML declares one. No directory
    or filename is inferred. Creation errors propagate to the caller.
    """
    if log_dir is not None:
      if not name: raise ValueError('File logging with log_dir requires a name')
      path = full_path(Path(log_dir) / f'{name}.log')
    else:
      value = log_file
      if not isinstance(value, str) or not value.strip():
        raise ValueError('File logging requires an explicit log_file in configuration')
      path = full_path(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path)
    if key in Logger._file_handlers:
      return path
    from logging.handlers import RotatingFileHandler
    fh = RotatingFileHandler(path, maxBytes=4_000_000, backupCount=5, encoding='utf-8')
    fh.setLevel(level)
    fh.setFormatter(_PlainFormatter())
    fh.addFilter(_EmptyMessageFilter())
    Logger._root.addHandler(fh)
    Logger._file_handlers[key] = fh
    return path


  @staticmethod
  def file_log(msg: str, *args, level: int = logging.INFO) -> None:
    """Emit a line only to gppu's file handler(s), bypassing the console handler.

    For Textual TUI apps whose visible "console" is the on-screen panel: this
    mirrors panel lines into the log file without writing to stderr (which would
    corrupt the live TUI). No-op when file logging isn't enabled.
    """
    if not Logger._file_handlers:
      return
    record = Logger._logger.makeRecord(Logger._logger.name, level, '(app)', 0,
                                       _LogColorizer.ANSI.sub('', pcp(msg, *args)), (), None,
                                       func='file_log', extra={'gppu_args': (msg, *args)})
    for h in Logger._file_handlers.values():
      if record.levelno >= h.level:
        h.handle(record)


  @staticmethod
  def _log(level: int, args: tuple, logger, options: dict) -> None:
    target = Logger._logger if logger is None else logger
    if not target.isEnabledFor(level): return
    frame = inspect.currentframe().f_back.f_back
    extra = dict(options.pop('extra')) if 'extra' in options else {}
    extra['gppu_args'] = args
    extra['gppu_class'] = type(frame.f_locals['self']).__name__ if 'self' in frame.f_locals else ''
    del frame
    stacklevel = options.pop('stacklevel') if 'stacklevel' in options else 1
    target.log(level, _LogColorizer.ANSI.sub('', pcp(*args)), extra=extra, stacklevel=stacklevel + 2, **options)


  @staticmethod
  def Debug(*a, logger=None, **kw): Logger._log(logging.DEBUG, a, logger, kw)
  @staticmethod
  def Info(*a, logger=None, **kw): Logger._log(logging.INFO, a, logger, kw)
  @staticmethod
  def Warn(*a, logger=None, **kw): Logger._log(logging.WARNING, a, logger, kw)
  @staticmethod
  def Error(*a, logger=None, **kw): Logger._log(logging.ERROR, a, logger, kw)
  @staticmethod
  @sync
  async def Dump(filename: str, data: dict = {}, **kw) -> None:
    """ Saves data object to yml file in trace folder """
    if '.' not in filename or not filename.endswith('.yml'): filename += '.yml'
    if Logger.trace_folder:
      filename = f"{Logger.trace_folder}/{filename}"
    dict_to_yml(filename=filename, data=data)


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
class mixin_Logger(_mixin):
  """A class that has it logs with ``self.Info(...)`` under its own name, a child of the program's log; Env, whose
  ``_global_log`` is set, logs as the program."""
  _global_log = False

  @classmethod
  def __init_subclass__(cls, **kw):
    super().__init_subclass__(**kw)
    if cls.__dict__.get('_global_log'):
      for name in ('Debug', 'Info', 'Warn', 'Error', 'Dump'): setattr(cls, name, Logger.__dict__[name])
      return
    cls._logger = Logger._logger.getChild(cls.__name__)
    for name in ('Debug', 'Info', 'Warn', 'Error', 'Dump'): setattr(cls, name, staticmethod(partial(getattr(Logger, name), logger=cls._logger)))


# .. changed
Debug = Logger.Debug


# .. changed
Info = Logger.Info


# .. changed
Warn = Logger.Warn


# .. changed
Error = Logger.Error


# .. changed
Dump = Logger.Dump


# .. changed
_DC_BASE_TYPE_MAP = {'str': str, 'list': list, 'dict': dict, 'set': set, 'int': int, 'float': float, 'bool': bool, 'None': type(None)}


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
class _DC(UserDict):
  """Pseudo-dataclass base class backed by a UserDict.

  Dynamically generates properties for annotated class attributes based on
  `_DC_TYPE_MAP`, providing default values for missing or falsy values and
  enabling dictionary-backed state management.
  """
  _DC_TYPE_MAP: dict[str, type] = _DC_BASE_TYPE_MAP.copy()
  _DC_EXCLUDE_NAMES: list[str] = []


  def _init_from_kw(self, **kw) -> None:
    data = kw.pop('data', {})
    if isinstance(data, str): data = {'data': data}
    self.data = kw | data


  # _INIT_STEPS: list[Callable] = [_init_from_kw]
  # _INIT_STEPS: list[Callable[Concatenate["_DC", ...], None]] = [_init_from_kw]
  # _INIT_STEPS: ClassVar[tuple[InitStep, ...]] = (_init_from_kw,)
  _INIT_STEPS: list[Callable[Concatenate[Any, ...], None]] = [_init_from_kw]


  def __init_subclass__(cls, **kw) -> None:
    def _simple_type(typ: type | str) -> str:
      typ = str(typ)
      origin, bracket, _ = typ.partition('[')
      return origin if bracket and origin in cls._DC_TYPE_MAP else typ

    super().__init_subclass__(**kw)

    annotations_raw = [(n, t if isinstance(t, str) else str(t.__name__)) for c in cls.mro() if hasattr(c, '__annotations__') for n, t in c.__annotations__.items() if n[0] != '_' and n not in cls._DC_EXCLUDE_NAMES]
    annotations = {n: _simple_type(t) for n, t in annotations_raw}

    mro = [(n, t) for n, t in annotations.items() if n[0] != '_' and t in cls._DC_TYPE_MAP]
    for aname, atype in mro:
      def getter(self, name=aname, atype=atype):
        result = self.data.get(name)
        if result is not None and isinstance(result, cls._DC_TYPE_MAP[atype]): return result
        if not result:
          if atype == 'str': result = ''
          elif atype == 'list': result = []
          elif atype == 'dict': result = {}
          elif atype == 'set': result = set()
        return result
      def setter(self, value, name=aname, type_hint=atype, _owner_mod=sys.modules[cls.__module__]):
        if not hasattr(self, 'data'): self.data = {}
        self.data[name] = value
      setattr(cls, aname, property(getter, setter))


  def __init__(self, **kw):
    self.data = {}
    for step in self._INIT_STEPS: step(self, **kw)


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
class mixin_Config(_mixin):
  """ Very sus. Looks like slop """
  _my: dict[str, Any] = {}


  def _config_load(self, source: Mapping | str | Path, argv: list[str] = []) -> None:
    """The one loader of Env and every app: a YAML file, or a section already loaded, becomes this object's own
    configuration, a copy of its source, with its templates applied. A Jinja value that reads only ``glob``,
    ``glob_int``, ``glob_list`` or ``glob_dict`` is filled here, each reading the environment filled; Jinja that reads
    anything else, and ``$`` text, stay. The command line goes over it: ``--key value`` sets the key, a slash path a
    nested one, to the string, ``--flag`` with no value after it sets it to True, and other arguments are the
    program's own."""
    self._my = deepcopy(dict(source)) if isinstance(source, Mapping) else dict_from_yml(source)
    jinja_configuration(self._my)
    def read(path: str) -> Any: return jinja_fill(glob(path), **readers)
    readers = {'glob': read,
               'glob_int': lambda path: _ if isinstance(_ := read(path), int) else 0,
               'glob_list': lambda path: _ if isinstance(_ := read(path), list) else [],
               'glob_dict': lambda path: _ if isinstance(_ := read(path), dict) else {}}
    self._my = jinja_fill(self._my, **readers)
    self._my = apply_template(self._my, templates_of(self._my))
    i = 0
    while i < len(argv):
      arg, i = argv[i], i + 1
      if not arg.startswith('--') or len(arg) == 2: continue
      value = True
      if i < len(argv) and not argv[i].startswith('--'): value, i = argv[i], i + 1
      deepset(arg[2:], self._my, value)


  def my(self, path: str | y2path, default=None) -> Any: return deepget(path, self._my, default=default)
  def my_int(self, path: str | y2path, default: int = 0) -> int: return deepget_int(path, self._my, default=default)
  def my_float(self, path: str | y2path, default: float = float('nan')) -> float: return deepget_float(path, self._my, default=default)
  def my_list(self, path: str | y2path, default: list = []) -> list: return deepget_list(path, self._my, default=default or [])
  def my_dict(self, path: str | y2path, default: dict = {}) -> dict: return deepget_dict(path, self._my, default=default or {})


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
class App(_Base, _DC):
  """ Not human reviewed """
  def _init_config(self, environment: str | None = None, config: str | Path | None = None, argv: list[str] = [], **kw) -> None:
    if not self.name: self.name = type(self).__name__.lower()
    Env.init(environment=environment)
    self._config_load(glob_dict(self.name) if config is None else config, argv)

  _INIT_STEPS = _DC._INIT_STEPS + [_init_config]


# .. changed; the one of 2026-11-24 is in gppu/gppu.py
class _Env(_Base):
  """The program's environment: singleton app object. It's my is glob"""
  home: Path
  user: str
  os: OSType
  host: str
  path: Path   # the environment's YAML file
  environment: str   # the environment loaded: RAN or IoT

  _global_log = True

  @property
  def initialized(self) -> bool: return getattr(self, '_initialized', False)
  @initialized.setter
  def initialized(self, value: bool): self._initialized = value


  def init(self, **kw):
    _ENV_PATHS = {"RAN": "RAN/_config/config.yaml", "IoT": "IoT/_Creekview/_creekview.yaml"}

    environment = kw.get('environment') or ''
    if self.initialized:
      if environment and environment != self.environment: raise ValueError(f'Environment {self.environment!r} is loaded; {environment!r} cannot load as well')
      return

    self.os = detect_os()
    self.host = socket.gethostname().split('.')[0].lower()
    self.user = getpass.getuser()
    self.home = Path.home()

    if environment in _ENV_PATHS:
      if self.os == OSType.W11: path = Path("D:\\Dev")
      else: path = Path("~").expanduser()
      path /= Path(_ENV_PATHS[environment])

      if path.exists():
        self.path = path
        self.environment = environment
        self._config_load(path)
        if 'log_file' in self._my: Logger.enable_file_logging(log_file=self._my['log_file'])
        if 'trace_rules' in self._my: Logger.init_logger(trace_rules=self._my['trace_rules'])
        self.initialized = True
      else: raise FileNotFoundError(path)
    elif environment: raise ValueError(f'Unknown environment {environment!r}: one of {", ".join(_ENV_PATHS)}')


  def reset(self) -> None:
    self._my = {}
    self.initialized = False


# .. changed
# the configuration's readers are globals: Env's my readers
glob, glob_int, glob_list, glob_dict = Env.my, Env.my_int, Env.my_list, Env.my_dict

# endregion


# region - gppu/app.py as of 2026-11-20 (14)

# .. changed; the one of 2026-11-24 is in gppu/gppu.py
class _YMRO:
  POSSIBLE_STEPS = ['init', 'load', 'start', 'stop']

  @property
  def _trace_mro(self) -> bool:
    result = getattr(self, 'args', {}).get('trace_mro', False)
    global _trace_mro
    _trace_mro = result
    return result


  def print_ymro(self):
    Debug('BY', self.__class__.__qualname__)
    siblings = [c for c in reversed(self.__class__.__mro__) if c != _YMRO and issubclass(c, _YMRO)]
    step = 'init'
    for sibling in siblings:
      Debug('DG', f"  {sibling.__qualname__}")
      qname = f"{sibling.__qualname__}__{step}"
      if qname[0] != '_': qname = '_' + qname
      method = getattr(self, qname, None)
      if method:
        Debug('INFO', f"  {method.__qualname__}")
        initers = getattr(sibling, '_initers', [])
        for initer in initers: Debug('DIM', f"     {initer.__qualname__}")


  def _ymros(self):
    result = {}
    siblings = [c for c in reversed(self.__class__.__mro__) if c != _YMRO and issubclass(c, _YMRO)]
    for step in self.POSSIBLE_STEPS:
      result[step] = []
      for sibling in siblings:
        qname = f"{sibling.__qualname__}__{step}"
        if qname[0] != '_': qname = '_' + qname
        method = getattr(self, qname, None)
        if method: result[step].append(method)
    return result

  def _ymro(self, method: str) -> list: return self._ymros().get(method, [])

  def _callall(self, method, *a, **kw):
    if any(inspect.iscoroutinefunction(m) for m in self._ymro(method)): return self._acallall(method, *a, **kw)
    [m(*a, **kw) for m in self._ymro(method)]

  async def _acallall(self, method: str, *a, **kw) -> None:
    for m in self._ymro(method):
      result = m(*a, **kw)
      if asyncio.iscoroutine(result): await result


# .. gone
class _YInit(_YMRO):
  @abstractmethod
  def __init(self): pass

  @final
  def init(self):
    if self.initialized: return
    result = self._callall('init')
    self.initialized = True
    return result

  @property
  def initialized(self) -> bool: return getattr(self, '_initialized', False)
  @initialized.setter
  def initialized(self, value: bool): self._initialized = value


# .. gone
class _YLoad(_YInit):
  @abstractmethod
  def __load(self): pass

  @final
  def load(self):
    if self.loaded: return
    assert self.initialized
    result = self._callall('load')
    self.loaded = True
    return result

  @property
  def loaded(self) -> bool: return getattr(self, '_loaded', False)
  @loaded.setter
  def loaded(self, value: bool): self._loaded = value


# .. gone
class _YStart(_YLoad):
  @abstractmethod
  def __start(self): pass

  @final
  def start(self):
    if self.started: return
    result = self._callall('start')
    self.started = True
    return result

  @property
  def started(self) -> bool: return getattr(self, '_started', False)
  @started.setter
  def started(self, value: bool): self._started = value


  @final
  def stop(self):
    if self.stopped: return
    result = self._callall('stop')
    self.started = False
    self.stopped = True
    self.loaded = False
    return result


  @property
  def stopped(self) -> bool: return getattr(self, '_stopped', False)
  @stopped.setter
  def stopped(self, value: bool): self._stopped = value


# .. gone
YStepper = _YStart


# .. gone
class mixin_Stepper(YStepper, _mixin): pass


# .. gone
type AsyncSubmission[T] = Future[T] | asyncio.Task[T]


# .. gone
class mixin_EventLoopBridge(_mixin):
  """Schedules coroutines on an externally owned loop; ``call`` blocks off-loop."""

  def schedule[T](self, coroutine: Coroutine[Any, Any, T], /) -> AsyncSubmission[T]:
    return self._schedule(self._get_loop(), coroutine)

  def submit[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> AsyncSubmission[T]:
    return self.schedule(function(*args, **kwargs))

  def call[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> T:
    loop = self._get_loop()
    if self._on_loop(loop): raise RuntimeError('cannot block the target event-loop thread')
    future = self._schedule(loop, function(*args, **kwargs))
    try: return future.result()
    except BaseException:
      if not future.done(): future.cancel()
      raise

  def on_loop(self) -> bool: return self._on_loop(self._get_loop())

  @staticmethod
  def _schedule[T](loop: asyncio.AbstractEventLoop, coroutine: Coroutine[Any, Any, T], /) -> AsyncSubmission[T]:
    try:
      if mixin_EventLoopBridge._on_loop(loop): return loop.create_task(coroutine)
      return asyncio.run_coroutine_threadsafe(coroutine, loop)
    except BaseException:
      coroutine.close()
      raise

  @staticmethod
  def _on_loop(loop: asyncio.AbstractEventLoop) -> bool:
    try: return asyncio.get_running_loop() is loop
    except RuntimeError: return False

  def _get_loop(self) -> asyncio.AbstractEventLoop:
    raise NotImplementedError


# .. gone
@dataclass
class TimerHandle:
  """An armed timer: the callback's name, whether it fires once or repeats, its interval, and when it next fires
  (epoch seconds)."""
  id: int
  name: str = ''
  kind: str = ''
  interval: float | None = None
  next_run: float = 0.0
  _cancelled: bool = False
  _spent: bool = False          # a one-shot that has fired

  def cancel(self) -> None:
    self._cancelled = True

  @property
  def running(self) -> bool:
    return not self._cancelled and not self._spent


# .. gone
class _Scheduler:
  """One thread holds every armed timer, instead of one thread per arm.

  `threading.Timer` parks an OS thread for the whole delay, and `run_every`
  builds a fresh one on every tick: the live process carried 976 parked
  threads having created 460,972 of them at ~8/s. A due callback still gets a
  thread of its own, so one slow callback cannot hold up the rest — the same
  concurrency the Timer-per-arm had, without the parked threads.

  Deadlines are monotonic (a wall-clock step must not move an armed timer);
  `TimerHandle.next_run` stays epoch seconds, which is what the container view
  renders. A cancelled entry is skipped when it comes due rather than removed,
  so the heap holds it until then."""

  def __init__(self) -> None:
    self._heap: list[tuple[float, int, TimerHandle, Callable[[], None]]] = []
    self._wake = threading.Condition()
    self._thread: threading.Thread | None = None

  def arm(self, handle: TimerHandle, fire: Callable[[], None], delay: float) -> None:
    with self._wake:
      heapq.heappush(self._heap, (time.monotonic() + delay, handle.id, handle, fire))
      if self._thread is None:
        self._thread = threading.Thread(target=self._run, name='y2-timers', daemon=True)
        self._thread.start()
      self._wake.notify()

  def _run(self) -> None:
    while True:
      with self._wake:
        while not self._heap: self._wake.wait()
        due, _, handle, fire = self._heap[0]
        remaining = due - time.monotonic()
        if remaining > 0:
          self._wake.wait(remaining)      # a nearer arm notifies; re-read the head
          continue
        heapq.heappop(self._heap)
      if handle._cancelled: continue
      threading.Thread(target=fire, daemon=True).start()


# .. gone
_SCHEDULER = _Scheduler()


# .. changed; the one of 2026-11-24 is in gppu/app.py
class AsyncApp(App, mixin_Stepper, mixin_EventLoopBridge):
  """Application base for long-lived asyncio services, on the YMRO steps.

  Construction runs init; ``run()`` runs init (light loading, with the configuration ready),
  load (the heavy loading) and start, last, on the app's loop: ``asyncio.run(MyApp().run())``.
  An app gives its part of a step by overriding ``init``, ``load`` or ``start`` and calling
  super; a mixin gives its part as ``__init``, ``__load`` or ``__start``, sync or ``async def``.
  A part adds concurrent work with ``self._spawn(coro)``; ``run()`` returns when all of it
  has finished, and ``app.stop()`` cancels it.
  The app is a ``mixin_EventLoopBridge`` onto its own running loop, so off-loop threads
  ``schedule``/``submit``/``call`` work onto it.

  Its timers: ``run_later`` fires a callback once after a delay, and arming it again under the same key replaces it;
  ``run_every`` fires it at an interval. ``timers`` holds every armed timer by its id, ``h_timeouts`` those armed under
  a key.
  """

  _task_group: asyncio.TaskGroup | None
  _background_tasks: set[asyncio.Task[Any]]
  _loop: asyncio.AbstractEventLoop | None
  _timer_ids = count(1)
  restartable: ClassVar[bool] = True   # whether Runtime.restart_app may stop, reconstruct and start it

  def __init__(self, **kw) -> None:
    super().__init__(**kw)
    self._task_group = None
    self._background_tasks = set()
    self._loop = None
    self.timers: dict[int, TimerHandle] = {}
    self.h_timeouts: dict[str, TimerHandle] = {}
    self.init()

  def run_later(self, callback: Callable[..., Any], *, delay: int | float, key: str | None = None, **data: Any) -> TimerHandle:
    if key is not None:
      previous = self.h_timeouts.pop(key, None)
      if previous is not None:
        previous.cancel()
        self.timers.pop(previous.id, None)
    name = getattr(callback, '__name__', '') or getattr(getattr(callback, 'func', None), '__name__', '')
    callback = _callback_wrapper(callback)
    handle = TimerHandle(id=next(self._timer_ids), name=name, kind='once', next_run=now_ts() + float(delay))

    def wrapped() -> None:
      handle._spent = True                  # a one-shot is spent once it fires, and so is its slot under the key
      self.timers.pop(handle.id, None)
      if self.h_timeouts.get(key) is handle: del self.h_timeouts[key]
      if handle._cancelled: return
      callback(**data)

    self.timers[handle.id] = handle
    if key is not None: self.h_timeouts[key] = handle
    _SCHEDULER.arm(handle, wrapped, float(delay))
    return handle

  def run_every(self, callback: Callable[..., Any], *, start: int | float, interval: int | float, **data: Any) -> TimerHandle:
    name = getattr(callback, '__name__', '') or getattr(getattr(callback, 'func', None), '__name__', '')
    callback = _callback_wrapper(callback)
    handle = TimerHandle(id=next(self._timer_ids), name=name, kind='interval',
                         interval=float(interval), next_run=now_ts() + float(start))

    def wrapped() -> None:
      if handle._cancelled: return
      try:
        callback(**data)
      finally:
        # Space completions without overlap; a failed poll must not stop the timer.
        if not handle._cancelled:
          handle.next_run = now_ts() + float(interval)
          _SCHEDULER.arm(handle, wrapped, float(interval))

    self.timers[handle.id] = handle
    _SCHEDULER.arm(handle, wrapped, float(start))
    return handle

  def cancel_timer(self, handle: TimerHandle) -> None:
    handle.cancel()
    self.timers.pop(handle.id, None)

  def timer_running(self, handle: TimerHandle) -> bool:
    return handle.running

  def cancel_timers(self) -> None:
    """Every timer this app armed, cancelled."""
    for handle in list(self.h_timeouts.values()) + list(self.timers.values()):
      handle.cancel()
    self.timers.clear()
    self.h_timeouts.clear()

  def __stop(self) -> None:
    loop = self._loop
    if loop is None: return                    # not running: nothing it spawned is left to cancel
    try: on_loop = asyncio.get_running_loop() is loop
    except RuntimeError: on_loop = False
    if not on_loop:                            # stopped from another thread: the loop cancels its own tasks
      loop.call_soon_threadsafe(lambda: [task.cancel() for task in list(self._background_tasks) if not task.done()])
      return
    current = asyncio.current_task()
    for task in self._background_tasks:
      if task is not current and not task.done(): task.cancel()

  def _get_loop(self) -> asyncio.AbstractEventLoop:
    loop = self._loop
    if loop is None: raise RuntimeError(f'{self!r} is not running')
    return loop

  async def run(self) -> None:
    """init, load and start on this loop; returns when the work they spawned has finished."""
    if self._task_group is not None: raise RuntimeError(f'{self!r} is already running')
    try:
      self._loop = asyncio.get_running_loop()
      async with asyncio.TaskGroup() as tasks:
        self._task_group = tasks
        for step in (self.init, self.load, self.start):
          if result := step(): await result
    finally:
      self._task_group = None
      self._loop = None
      self._background_tasks.clear()

  def _spawn[T](self, coroutine: Coroutine[Any, Any, T], /) -> asyncio.Task[T]:
    tasks = self._task_group
    if tasks is None:
      coroutine.close()
      raise RuntimeError(f'{self!r} is not running')
    try: task = tasks.create_task(coroutine)
    except BaseException:
      coroutine.close()
      raise
    self._background_tasks.add(task)
    task.add_done_callback(self._background_tasks.discard)
    return task

  async def launch(self, command: list[str], line: Callable[[str], Any], cwd: str, env: dict) -> str | None:
    """Start a process and hand `line` each line of its output; the error, or None when it exits with 0."""
    try:
      process = await asyncio.create_subprocess_exec(
        *command, cwd=cwd, env=env,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
      )
      async for raw in process.stdout:
        line(raw.decode('utf-8', errors='replace').rstrip())
      if code := await process.wait():
        return f'process exited with {code}'
    except OSError as failure:
      return str(failure)
    return None

  async def run_parallel(self, units: list, run: Callable[[Any], Coroutine], conflicts: Callable[[Any, list], bool],
                         failed: Callable[[Any, BaseException], Any]) -> None:
    """Run every unit at once with `run`. A unit waits while `conflicts(unit, running)` says it clashes with one that
    is running, and starts when that one ends; `failed` hears of a unit whose run raised, as it ends."""
    pending, running = list(units), {}
    while pending or running:
      for unit in pending[:]:
        if conflicts(unit, list(running.values())): continue
        running[asyncio.create_task(run(unit))] = unit
        pending.remove(unit)
      finished, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
      for task in finished:
        unit = running.pop(task)
        if task.exception(): failed(unit, task.exception())


# .. changed; the one of 2026-11-24 is in gppu/app.py
class mixin_Rest:
  """Every public member of the application's own classes, over HTTP, and nothing
  declared. A field or property reads; a method is called with the JSON body as
  its keyword arguments; a synchronous method needing none answers a GET as well.
  A name is the application's when a class born in the application's folder, the
  folder of the file that defines the app, defines it — a base may define it too —
  and the private names and the lifecycle steps are the only exclusion.

  The universal REST API to any object. It works only in an AsyncApp. It is not the default: no gppu app
  includes it; an application that wants it composes it before its application
  base, as Y2 does. Override ``rest_registries()`` with
  ``{registry: {key: object}}``; by default it contains the app itself. The HTTP
  host serves ``rest_manifest`` and binds ``rest_objects``, ``rest_read`` and
  awaited ``rest_call``, which return ``(payload, status)``. The host supplies
  the HTTP listener and JSON serialization.
  """
  REST_RESERVED = (*_YMRO.POSSIBLE_STEPS, 'initialize', 'terminate', 'setup', 'run')

  @staticmethod
  def _born(cls: type) -> str: # type: ignore
    """Where a class's source lives; a built-in has none."""
    try: return inspect.getsourcefile(cls) or ''
    except TypeError: return ''
  _rest_manifest: dict | None = None

  def _rest_home(self) -> str:
    """The application's folder: where the file that defines the app lives, and its own classes with it."""
    return os.path.dirname(self._born(type(self)))

  def rest_registries(self) -> dict[str, Mapping]:
    """name -> roster of live objects (key -> object); the host names its own."""
    return {'app': {getattr(self, 'name', 'app'): self}}

  def _rest_members(self, cls: type) -> dict[str, dict]:
    home, rows = self._rest_home(), {}
    for name in dir(cls):
      if name[0] == '_' or name in self.REST_RESERVED: continue
      if not any(self._born(c).startswith(home) for c in cls.__mro__ if name in c.__dict__): continue
      member = inspect.getattr_static(cls, name)
      fn = getattr(member, '__func__', member)
      if not inspect.isfunction(fn): rows[name] = {'kind': 'value'}; continue
      params = [p for n, p in inspect.signature(fn).parameters.items() if n not in ('self', 'cls')]
      needed = [p for p in params if p.default is p.empty and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)]
      rows[name] = {'kind': 'method', 'async': inspect.iscoroutinefunction(fn), 'doc': (fn.__doc__ or '').split('\n')[0],
                    'args': {p.name: {'required': p.default is p.empty} for p in params if p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)},
                    'free': any(p.kind is p.VAR_KEYWORD for p in params),
                    'read': not needed and not inspect.iscoroutinefunction(fn)}
    return rows

  @property
  def rest_manifest(self) -> dict:
    """The classes born in the application's folder and their members, walked once."""
    if self._rest_manifest is None:
      seen, stack = set(), [_mixin, _Base, _DC]
      while stack:
        cls = stack.pop()
        if cls not in seen: seen.add(cls); stack.extend(cls.__subclasses__())
      home = self._rest_home()
      classes = {c.__name__: {'members': self._rest_members(c)} for c in sorted(seen, key=lambda c: c.__name__) if self._born(c).startswith(home)}
      self._rest_manifest = {'registries': list(self.rest_registries()), 'classes': {n: c for n, c in classes.items() if c['members']}}
    return self._rest_manifest

  def _rest_find(self, registry: str, key: str):
    return next((o for k, o in (self.rest_registries().get(registry) or {}).items() if str(k) == key), None)

  def _rest_rows(self, obj) -> dict[str, dict]:
    return self.rest_manifest['classes'].get(type(obj).__name__, {}).get('members', {})

  def rest_payload(self, obj) -> dict:
    """What the object holds and what it can be asked to do. Values only are read
    here: calling a method to build a payload would run it for anyone listing the objects."""
    rows = self._rest_rows(obj)
    return {'class': type(obj).__name__,
            'members': {n: getattr(obj, n) for n, r in rows.items() if r['kind'] == 'value'},
            'methods': {n: r['args'] for n, r in rows.items() if r['kind'] == 'method'}}

  def rest_objects(self, kind: str | None = None, full: bool = False) -> tuple[dict, int]:
    out = {f'{registry}/{key}': self.rest_payload(obj) if full else type(obj).__name__
           for registry, roster in self.rest_registries().items() for key, obj in roster.items()
           if not kind or type(obj).__name__ == kind}
    return {'objects': out}, 200

  def rest_read(self, registry: str, key: str, name: str | None = None) -> tuple[dict, int]:
    obj = self._rest_find(registry, key)
    if obj is None: return {'success': False, 'error': 'no such object'}, 404
    if name is None: return self.rest_payload(obj), 200
    row = self._rest_rows(obj).get(name)
    if row is None: return {'success': False, 'error': f'{type(obj).__name__} has no {name!r}'}, 404
    if row['kind'] == 'method' and not row['read']: return {'success': False, 'error': f'{name} takes arguments; POST it'}, 405
    member = getattr(obj, name)
    return {name: member() if row['kind'] == 'method' else member}, 200

  async def rest_call(self, registry: str, key: str, name: str, body: Mapping) -> tuple[dict, int]:
    obj = self._rest_find(registry, key)
    if obj is None: return {'success': False, 'error': 'no such object'}, 404
    row = self._rest_rows(obj).get(name)
    if row is None or row['kind'] != 'method': return {'success': False, 'error': f'{name} is not a method'}, 405
    method, args = getattr(obj, name), dict(body)
    if row['async']: result = await method(**args)
    else: result = await asyncio.get_running_loop().run_in_executor(None, lambda: method(**args))
    return {'success': True, 'result': result}, 200


# .. changed; the one of 2026-11-24 is in gppu/api.py
class APIApp(AsyncApp):
    """An AsyncApp that serves HTTP: on uvicorn, at the ``host`` and ``port`` of its configuration, each ASGI app
    ``apis()`` gives at its path, from the end of ``start``. Override ``apis()``; work needed before serving is done
    in ``load``. FastAPI and uvicorn come with the ``ld`` extra::

        class LDAPI(APIApp, _SQABase):   # its store: the configuration's `db`, the engine and each request's session
            def apis(self): return {'/ld/v1': ld.serve({'/work': work.app}, self)}
    """

    def apis(self) -> dict[str, Any]:
        """path -> the FastAPI (or any ASGI) app served there."""
        return {}

    def asgi(self):
        """The app uvicorn serves: the apps of ``apis()`` at their paths."""
        from fastapi import FastAPI

        root = FastAPI(title=self.name)
        for path, app in self.apis().items(): root.mount(path, app)
        return root

    def __start(self) -> None:
        import uvicorn
        self._spawn(uvicorn.Server(uvicorn.Config(self.asgi(), host=self.my('host'), port=self.my('port'))).serve())

# endregion


# region - gppu/iot.py as of 2026-11-20 (18)

# .. gone
try:
  import aiomqtt
  from paho.mqtt.packettypes import PacketTypes
  from paho.mqtt.properties import Properties
except ImportError:
  aiomqtt = None  # type: ignore[assignment]
  PacketTypes = None  # type: ignore[assignment]
  Properties = None  # type: ignore[assignment]


# .. gone
try:
  import aiohttp
except ImportError:
  aiohttp = None  # type: ignore[assignment]


# .. gone
class y2slug(y2list):
  def __init__(self, o):
    self.token = '_'

    if '@' in str(o): o = str(o).split('@')[0]
    self.data = self._any2list(o)


# .. gone
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


# .. gone
_DC_BASE_TYPE_MAP |= {'y2eid': y2eid, 'y2topic': y2topic, 'y2path': y2path, 'y2uri': y2uri}


# .. gone
_DC._DC_TYPE_MAP |= {'y2eid': y2eid, 'y2topic': y2topic, 'y2path': y2path, 'y2uri': y2uri}


# .. gone
@dataclass(frozen=True)
class ListenerHandle:
  """A registered listener: its id, and the call that removes it."""
  id: int
  cancel: Callable[[], None]


# .. gone
class _Runtime:
  """The program's apps, which all share it: ``apps`` by name, the registries they fill (``actions``, ``buttons``,
  ``indicators``), and the listeners to events, to entity states and to topics. ``Runtime`` is its one instance. A
  callback is called with only the keywords it takes."""

  def __init__(self) -> None:
    self._init_runtime()

  def _init_runtime(self) -> None:
    self.apps: dict[str, Any] = {}
    self.actions: dict[str, Any] = {}
    self.buttons: dict[str, Any] = {}
    self.indicators: dict[str, Any] = {}
    self.event_listeners: dict[int, tuple[str | None, Callable[..., Any], dict[str, Any]]] = {}
    self.state_listeners: dict[int, tuple[y2eid | None, str | None, Callable[..., Any], dict[str, Any]]] = {}
    self.topic_listeners: dict[int, tuple[y2path | None, Callable[..., Any], dict[str, Any]]] = {}
    self._listener_ids = count(1)
    self.data = {
      'apps': self.apps,
      'actions': self.actions,
      'buttons': self.buttons,
      'indicators': self.indicators,
    }

  def reset(self) -> None:
    """Every app's timers cancelled, and the apps, the registries and the listeners empty."""
    for app in self.apps.values():
      app.cancel_timers()
    self._init_runtime()

  def register_app(self, app: Any) -> None:
    self.apps[app.name] = app

  def restart_app(self, name: str) -> Any:
    """Stop one app, discard it, and start a fresh instance of the same class with the same name, which reads its own
    configuration again. Raises for an unknown or non-restartable name."""
    app = self.apps.get(name)
    if app is None:
      raise ValueError(f"Unknown app: {name}")
    if not app.restartable:
      raise ValueError(f"App is not restartable: {name}")
    cls = type(app)
    app.stop()
    self.apps.pop(name, None)
    new_app = cls(name=name)
    new_app.start()
    return new_app

  def listen_event(self, callback: Callable[..., Any], *, event: str | None = None, **data: Any) -> ListenerHandle:
    callback = _callback_wrapper(callback)
    key = next(self._listener_ids)
    self.event_listeners[key] = (event, callback, dict(data))

    def cancel() -> None:
      self.event_listeners.pop(key, None)

    return ListenerHandle(id=key, cancel=cancel)

  def fire_event(self, event: str, **data: Any) -> None:
    for expected, callback, listener_data in tuple(self.event_listeners.values()):
      if expected is not None and expected != event: continue
      callback(event=event, data=dict(data), **listener_data)

  def listen_state(self, callback: Callable[..., Any], *, eid: str | y2eid | None = None, attribute: str | None = None,
                   **data: Any) -> ListenerHandle:
    parsed = y2eid(eid) if eid else None
    callback = _callback_wrapper(callback)
    key = next(self._listener_ids)
    self.state_listeners[key] = (parsed, attribute, callback, dict(data))

    def cancel() -> None:
      self.state_listeners.pop(key, None)

    return ListenerHandle(id=key, cancel=cancel)

  def state_changed(self, entity: Any, *, old_state: Any, old_attrs: Mapping[str, Any]) -> None:
    changes: list[tuple[str | None, Any, Any]] = []
    if old_state != entity.state:
      changes.append((None, old_state, entity.state))
    for attr in sorted(set(old_attrs) | set(entity.attributes)):
      old = old_attrs.get(attr)
      new = entity.attributes.get(attr)
      if old != new:
        changes.append((attr, old, new))
    for attribute, old, new in changes:
      for expected_eid, expected_attr, callback, data in tuple(self.state_listeners.values()):
        if expected_eid is not None and expected_eid != entity.eid: continue
        if expected_attr != '*' and expected_attr != attribute: continue
        callback(entity=entity, attribute=attribute, old=old, new=new, **data)

  def listen_topic_state(self, callback: Callable[..., Any], *, path: str | y2path | None = None, **data: Any) -> ListenerHandle:
    parsed = y2path(path) if path else None
    callback = _callback_wrapper(callback)
    key = next(self._listener_ids)
    self.topic_listeners[key] = (parsed, callback, dict(data))

    def cancel() -> None:
      self.topic_listeners.pop(key, None)

    return ListenerHandle(id=key, cancel=cancel)

  def topic_changed(self, path: y2path, *, old: Any, new: Any) -> None:
    if old == new: return
    for expected_path, callback, data in tuple(self.topic_listeners.values()):
      if expected_path is not None and expected_path != path: continue
      callback(path=path, old=old, new=new, **data)


# .. gone
Runtime = _Runtime()


# .. gone
type MqttPayload = JsonValue | bytes


# .. gone
type MqttCallback = Callable[[y2topic, object], object | Awaitable[object]]


# .. gone
if aiomqtt is None:
  class _MqttError(Exception): pass
else:
  _MqttError = aiomqtt.MqttError


# .. changed; the one of 2026-11-24 is in gppu/app.py
class mixin_Mqtt:
  """MQTT for a host that owns its lifecycle and loop, as Y2 does.

  Supply ``connection``, ``Info``/``Warn`` and ``_spawn(coro)`` to schedule and
  track work on that loop. Call ``_start_mqtt()`` there at startup, then cancel
  and await the host's tasks at shutdown. Use the same subscription, publishing
  and connected-work hooks described on ``MqttApp``.
  """

  _CLIENT_KEYS = ('hostname', 'port', 'username', 'password', 'identifier')
  MQTT_RECONNECT_DELAY = 5

  connection: dict[str, Any]
  MQTT_PROTOCOL: Any = None
  _client: Any = None
  _mqtt_task: Any = None
  _callbacks: dict[y2topic, list[tuple[MqttCallback, object, bool, bool]]]
  _subscriptions: dict[y2topic, int]
  _mqtt_lock: asyncio.Lock
  _callback_lock: asyncio.Lock

  def _start_mqtt(self):
    task = self._mqtt_task
    if task is not None and not task.done(): return task

    coroutine = self._mqtt_loop()
    try: task = self._spawn(coroutine)
    except BaseException:
      coroutine.close()
      raise
    self._mqtt_task = task
    return task

  def _ensure_mqtt_state(self) -> None:
    if getattr(self, '_mqtt_lock', None) is not None: return
    self._callbacks = {}
    self._subscriptions = {}
    self._mqtt_lock = asyncio.Lock()
    self._callback_lock = asyncio.Lock()

  async def mqtt_listen(self, callback: MqttCallback, topic: y2topic | str, payload: object = None, *, ignore_retained: bool = False, raise_errors: bool = False, **data: Any) -> None:
    self._ensure_mqtt_state()
    topic = y2topic(topic)
    qos = int(data.get('qos', 0))

    async with self._mqtt_lock:
      callbacks = self._callbacks.setdefault(topic, [])
      entry = (callback, payload, ignore_retained, raise_errors)
      if entry not in callbacks: callbacks.append(entry)

      old_qos = self._subscriptions.get(topic, -1)
      qos = max(old_qos, qos)
      self._subscriptions[topic] = qos
      client = self._client if qos != old_qos else None

    if client is not None: await client.subscribe(str(topic), qos=qos)

  async def mqtt_publish(self, topic: y2topic | str, payload: MqttPayload = '', **data: Any) -> None:
    client = self._client
    if client is None: return

    if isinstance(payload, (dict, list)): wire_payload = json.dumps(payload)
    elif isinstance(payload, bytes): wire_payload = payload
    else: wire_payload = str(payload)
    retain = bool(data.pop('retain', False))
    qos = int(data.pop('qos', 0))
    expiry = data.pop('expiry', None)
    properties = None

    if expiry is not None or data:
      properties = Properties(PacketTypes.PUBLISH)
      if expiry is not None: properties.MessageExpiryInterval = int(expiry)
      if data: properties.UserProperty = [(key, str(value)) for key, value in data.items()]

    await client.publish(str(topic), wire_payload, qos=qos, retain=retain, properties=properties)

  @property
  def _status_topic(self) -> y2topic:
    return y2topic(self.connection.get('status_topic', ''))

  def _mqtt_client(self):
    if aiomqtt is None: raise RuntimeError('aiomqtt is required for mixin_Mqtt')
    options = {key: self.connection[key] for key in self._CLIENT_KEYS if key in self.connection}
    if self.MQTT_PROTOCOL is not None: options['protocol'] = self.MQTT_PROTOCOL
    if self._status_topic: options['will'] = aiomqtt.Will(topic=str(self._status_topic), payload=b'offline', qos=1, retain=True)
    return aiomqtt.Client(**options)

  def _mqtt_tasks(self) -> Iterable[Coroutine[Any, Any, object]]: return ()

  async def _mqtt_loop(self) -> None:
    self._ensure_mqtt_state()
    while True:
      try:
        async with self._mqtt_client() as client:
          self._client = client
          try:
            self.Info('connected:', self.connection.get('hostname'), self.connection.get('port'))
            await self._mqtt_replay(client)
            if self._status_topic: await client.publish(str(self._status_topic), 'online', qos=1, retain=True)

            async with asyncio.TaskGroup() as tasks:
              dispatch = tasks.create_task(self._mqtt_dispatch(client))
              extras = [tasks.create_task(coroutine) for coroutine in self._mqtt_tasks()]
              await dispatch
              for task in extras: task.cancel()
          finally:
            self._client = None
            if self._status_topic:
              try: await client.publish(str(self._status_topic), 'offline', qos=1, retain=True)
              except _MqttError: pass
      except _MqttError as error:
        self.Warn(f'mqtt error, reconnect in {self.MQTT_RECONNECT_DELAY}s:', error)
      except BaseExceptionGroup as group:
        # TaskGroup wraps task failures in a group; peel off MqttError, re-raise the rest.
        # (Avoid `except*` syntax: debugpy's source scanner crashes on TryStar nodes.)
        mqtt_errors, other = group.split(_MqttError)
        if mqtt_errors is not None:
          self.Warn(f'mqtt error, reconnect in {self.MQTT_RECONNECT_DELAY}s:', *mqtt_errors.exceptions)
        if other is not None: raise other
      finally:
        self._client = None

      await asyncio.sleep(self.MQTT_RECONNECT_DELAY)

  async def _mqtt_replay(self, client: Any) -> None:
    async with self._mqtt_lock: subscriptions = tuple(self._subscriptions.items())
    for topic, qos in subscriptions: await client.subscribe(str(topic), qos=qos)

  async def _mqtt_dispatch(self, client: Any) -> None:
    async for message in client.messages:
      topic = str(message.topic)
      raw = message.payload.decode(errors='replace') if isinstance(message.payload, bytes) else str(message.payload)
      payload: object = raw
      structured = raw.lstrip()
      if structured[:1] in '[{':
        try: payload = json.loads(structured)
        except json.JSONDecodeError: pass

      async with self._mqtt_lock:
        callbacks = [(callback, raise_errors) for pattern, entries in self._callbacks.items()
                     if self._topic_matches(topic, str(pattern))
                     for callback, expected, ignore_retained, raise_errors in entries
                     if not (ignore_retained and message.retain) and (expected is None or expected == payload)]

      for callback, raise_errors in callbacks:
        self._spawn(self._mqtt_callback(callback, y2topic(topic), payload, raise_errors=raise_errors))

  async def _mqtt_callback(self, callback: MqttCallback, topic: y2topic, payload: object, *, raise_errors: bool = False) -> None:
    async with self._callback_lock:
      try:
        result = callback(topic, payload)
        if inspect.isawaitable(result): await result
      except Exception as error:
        if raise_errors: raise
        self.Warn('callback error:', topic, error)

  @staticmethod
  def _topic_matches(topic: str, pattern: str) -> bool:
    if topic.startswith('$') and not pattern.startswith('$'): return False
    topic_parts = topic.split('/')
    pattern_parts = pattern.split('/')
    for index, expected in enumerate(pattern_parts):
      if expected == '#': return index == len(pattern_parts) - 1
      if index == len(topic_parts) or expected not in ('+', topic_parts[index]): return False
    return len(topic_parts) == len(pattern_parts)


# .. gone
class MqttApp(mixin_Mqtt, AsyncApp):
  """AsyncApp with one reconnecting MQTT client; import from ``gppu``.

  Its broker mapping is the configuration's ``connection``; set ``self.connection`` in an ``__init`` part to change it.
  Override async ``subscribe()`` to ``await self.mqtt_listen(callback,
  topic)``; callbacks take ``(topic, payload)`` and may be sync or async.

  Run with ``asyncio.run(MyApp().run())`` and stop as for ``AsyncApp``; its
  ``__start`` subscribes and connects. Subscriptions register
  before connection; for work needing a connection, have ``_mqtt_tasks()``
  return fresh coroutines for each connection. Publish with
  ``await self.mqtt_publish(topic, payload)``; disconnected publishes are discarded.
  """

  def __init(self) -> None:
    self.connection = self.my('connection')

  async def subscribe(self) -> None: pass

  async def __start(self) -> None:
    await self.subscribe()
    self._start_mqtt()


# .. changed; the one of 2026-11-24 is in gppu/app.py
class AppService(MqttApp):
  """An MqttApp whose part of Env arrives over MQTT: ``config_mqtt/topics`` in its own configuration maps each
  retained topic to the path in Env that its payload replaces, the same as loading it again, so ``glob`` reads it as
  it reads the rest of Env. The app's own configuration stays its own. An app that acts on new configuration listens
  to the same topic: its listener runs after the section is loaded. ``await app.from_mqtt()`` reads every topic once,
  then disconnects."""

  def __init(self) -> None:
    self.topics = self.my_dict('config_mqtt/topics')
    self.until_loaded: set[str] | None = None   # from_mqtt: the topics still to arrive

  async def from_mqtt(self) -> None:
    """Each of its topics read once, then the connection closed."""
    self.until_loaded = set(self.topics)
    await self.run()

  async def __load(self) -> None:
    if not self.topics or any('+' in topic or '#' in topic for topic in self.topics):
      raise ValueError('MQTT configuration topics must be exact topic names')
    for topic in self.topics: await self.mqtt_listen(self._receive_config, topic, qos=1, raise_errors=True)

  async def _receive_config(self, topic: y2topic, payload: object) -> None:
    data = yaml.safe_load(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict): raise TypeError(f'MQTT configuration must be a mapping: {topic}')
    configuration = deepcopy(Env.my_dict(''))
    deepset(self.topics[str(topic)], configuration, data)
    Env._config_load(configuration)
    if self.until_loaded is not None:
      self.until_loaded.discard(str(topic))
      if not self.until_loaded: self.stop()


# .. changed; the one of 2026-11-24 is in gppu/iot.py
# $$
# $$        Serialized controls (mixin_EventLoopBridge lives in gppu.app)
# $$
class SerializedControl(mixin_EventLoopBridge):
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


# .. changed; the one of 2026-11-24 is in gppu/iot.py
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
    if aiohttp is None: raise RuntimeError('aiohttp is required for HTTPControl')
    request_headers = {**(self._http_headers or {}), **(headers or {})} or None
    try:
      timeout = aiohttp.ClientTimeout(total=self._http_timeout)
      async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method, url, data=body, headers=request_headers, ssl=self._http_ssl) as response:
          response.raise_for_status()
          return await response.text()
    except (aiohttp.ClientError, TimeoutError, OSError, UnicodeError):
      return None


# .. changed; the one of 2026-11-24 is in gppu/iot.py
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

# endregion


# region - gppu/data.py as of 2026-11-20 (17)

# .. changed; the one of 2026-11-24 is in gppu/data.py
class _PersistentBase(_Base):
  """Base class for database-backed components.

  Handles common DB connection string resolution from config.
  Subclasses: _PGBase (psycopg2), _SQABase (SQLAlchemy)
  """
  db_connection_string: str

  def __init__(self, **kw):
    super().__init__(**kw)
    self.db_connection_string = glob('db') or self.my('db') or ''
    if not self.db_connection_string:
      raise ValueError("Database connection string 'db' not found in config")

  def close(self):
    """Close database connection. Override in subclasses."""
    pass

  def __enter__(self):
    return self

  def __exit__(self, *_):
    self.close()


# .. changed; the one of 2026-11-24 is in gppu/data.py
class _SQABase(_PersistentBase):
  """SQLModel ORM database access: SQLAlchemy's async engine on psycopg 3 (`async_engine`), as gppu.ld uses it.

  `session()` is one database session, committed when it closes and rolled back on an error. `scoped_session` is
  SQLAlchemy's `async_scoped_session` on the engine: called, it gives the session of the asyncio task calling, so each
  request served has its own without passing it along; `remove()` closes it.
  Needs the `ld` extra.
  """
  _engine: Any
  _scoped: Any

  def __init__(self, **kw):
    super().__init__(**kw)
    self._engine = None
    self._scoped = None

  @property
  def engine(self):
    """Lazy engine - creates on first use."""
    if self._engine is None: self._engine = async_engine(self.db_connection_string)
    return self._engine

  @property
  def scoped_session(self):
    """The session of the asyncio task calling, one per task (SQLAlchemy's async_scoped_session); made on first use."""
    if self._scoped is None:
      import asyncio
      from sqlalchemy.ext.asyncio import async_scoped_session, async_sessionmaker
      from sqlmodel.ext.asyncio.session import AsyncSession
      self._scoped = async_scoped_session(async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False), scopefunc=asyncio.current_task)
    return self._scoped

  @asynccontextmanager
  async def session(self):
    """Async context manager for an ORM session with auto-commit/rollback."""
    from sqlmodel.ext.asyncio.session import AsyncSession
    async with AsyncSession(self.engine, expire_on_commit=False) as sess:
      try:
        yield sess
        await sess.commit()
      except Exception:
        await sess.rollback()
        raise

  async def close(self):
    """Dispose the engine connection pool."""
    if self._engine:
      await self._engine.dispose()
      self._engine = None

  async def __aenter__(self):
    return self

  async def __aexit__(self, *_):
    await self.close()


# .. gone
class _PersistentDC(_DC):
  """_DC subclass that persists self.data through a pluggable backend.

  Storage is namespaced by (type(self).__name__, self.data[_persist_key]).
  Subclasses wanting custom storage override _do_persist() / load().

  Backend protocol (duck-typed; see `gppu.data.Persistence` for the standard
  factory and built-in backends: json, pickle, sqlite, postgres):
    upsert(cls: str, key: str, data: dict) -> None
    load(cls: str, key: str)   -> dict | None
    delete(cls: str, key: str) -> None
    close()                    -> None

  Bind once per process:
    from gppu.data import Persistence
    _PersistentDC.bind_db(Persistence('/var/lib/y2.db', backend='sqlite'))
  """

  _persist_key: ClassVar[str] = 'gppu'
  _persist_db:  ClassVar[Any] = None

  @classmethod
  def bind_db(cls, db: Any) -> None: cls._persist_db = db

  def persist(self) -> None:
    db = type(self)._persist_db
    if db is None: return
    pk = self.data.get(self._persist_key)
    if not pk: return
    self._do_persist(db, str(pk))

  def _do_persist(self, db: Any, pk: str) -> None:
    db.upsert(type(self).__name__, pk, dict(self.data))

  @classmethod
  def load(cls, key: str) -> Optional[dict]:
    db = cls._persist_db
    if db is None: return None
    return db.load(cls.__name__, str(key))

  @classmethod
  def iter_all(cls):
    """Yield (key, data) for every persisted row of this class. Empty if unbound."""
    db = cls._persist_db
    if db is None: return
    yield from db.iter(cls.__name__)


# .. gone
class _JsonBackend:
  """JSON-file cache backend. No dependencies."""

  def __init__(self, path: str):
    import os, json
    self._path = path
    self._data: dict = {}
    os.makedirs(os.path.dirname(path) if not os.path.isdir(path) else path, exist_ok=True)
    if os.path.isdir(path):
      self._path = os.path.join(path, '_cache.json')
    try:
      with open(self._path) as f: self._data = json.load(f)
    except Exception: pass

  def _flush(self):
    import json
    try:
      with open(self._path, 'w') as f: json.dump(self._data, f)
    except Exception: pass

  def _alive(self, entry: dict) -> bool:
    import time
    exp = entry.get('_exp')
    return exp is None or time.time() < exp

  def get(self, key: str, default=None):
    entry = self._data.get(key)
    if entry is None or not self._alive(entry): return default
    return entry.get('v', default)

  def set(self, key: str, value, expire=None):
    import time
    entry: dict = {'v': value}
    if expire is not None: entry['_exp'] = time.time() + expire
    self._data[key] = entry
    self._flush()

  def delete(self, key: str):
    self._data.pop(key, None)
    self._flush()

  def close(self): self._flush()


# .. changed; the one of 2026-11-24 is in gppu/data.py
class _SqliteBackend:
  """SQLite cache backend. No external dependencies (stdlib sqlite3)."""

  def __init__(self, path: str):
    import os, sqlite3
    os.makedirs(os.path.dirname(path) if not os.path.isdir(path) else path, exist_ok=True)
    if os.path.isdir(path):
      path = os.path.join(path, '_cache.db')
    self._conn = sqlite3.connect(path)
    self._conn.execute(
      'CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value BLOB, expire REAL)')

  def get(self, key: str, default=None):
    import pickle, time
    row = self._conn.execute('SELECT value, expire FROM cache WHERE key=?', (key,)).fetchone()
    if row is None: return default
    if row[1] is not None and time.time() >= row[1]:
      self._conn.execute('DELETE FROM cache WHERE key=?', (key,))
      self._conn.commit()
      return default
    return pickle.loads(row[0])

  def set(self, key: str, value, expire=None):
    import pickle, time
    exp = (time.time() + expire) if expire else None
    self._conn.execute('INSERT OR REPLACE INTO cache (key, value, expire) VALUES (?, ?, ?)',
                       (key, pickle.dumps(value), exp))
    self._conn.commit()

  def delete(self, key: str):
    self._conn.execute('DELETE FROM cache WHERE key=?', (key,))
    self._conn.commit()

  def close(self):
    if self._conn: self._conn.close(); self._conn = None


# .. gone
class _PickleBackend:
  """Pickle-file cache backend. No external dependencies."""

  def __init__(self, path: str):
    import os, pickle
    self._path = path
    self._data: dict = {}
    os.makedirs(os.path.dirname(path) if not os.path.isdir(path) else path, exist_ok=True)
    if os.path.isdir(path):
      self._path = os.path.join(path, '_cache.pkl')
    try:
      with open(self._path, 'rb') as f: self._data = pickle.load(f)
    except Exception: pass

  def _flush(self):
    import pickle
    try:
      with open(self._path, 'wb') as f: pickle.dump(self._data, f)
    except Exception: pass

  def _alive(self, entry: dict) -> bool:
    import time
    exp = entry.get('_exp')
    return exp is None or time.time() < exp

  def get(self, key: str, default=None):
    entry = self._data.get(key)
    if entry is None or not self._alive(entry): return default
    return entry.get('v', default)

  def set(self, key: str, value, expire=None):
    import time
    entry: dict = {'v': value}
    if expire is not None: entry['_exp'] = time.time() + expire
    self._data[key] = entry
    self._flush()

  def delete(self, key: str):
    self._data.pop(key, None)
    self._flush()

  def close(self): self._flush()


# .. gone
class _DiskcacheBackend:
  """diskcache backend. Requires: pip install diskcache"""

  def __init__(self, path: str):
    from diskcache import Cache
    self._cache = Cache(path)

  def get(self, key: str, default=None): return self._cache.get(key, default)
  def set(self, key: str, value, expire=None): self._cache.set(key, value, expire=expire)
  def delete(self, key: str): self._cache.delete(key)
  def close(self): self._cache.close(); self._cache = None


# .. gone
class _DbBackend:
  """SQLAlchemy-based cache backend for any remote database."""

  def __init__(self, url: str):
    from sqlalchemy import create_engine, text
    self._engine = create_engine(url)
    with self._engine.connect() as conn:
      conn.execute(text(
        'CREATE TABLE IF NOT EXISTS cache (key VARCHAR(512) PRIMARY KEY, value BYTEA, expire FLOAT)'))
      conn.commit()

  def get(self, key: str, default=None):
    import pickle, time
    from sqlalchemy import text
    with self._engine.connect() as conn:
      row = conn.execute(text('SELECT value, expire FROM cache WHERE key=:k'), {'k': key}).fetchone()
    if row is None: return default
    if row[1] is not None and time.time() >= row[1]:
      self.delete(key)
      return default
    return pickle.loads(row[0])

  def set(self, key: str, value, expire=None):
    import pickle, time
    from sqlalchemy import text
    exp = (time.time() + expire) if expire else None
    blob = pickle.dumps(value)
    with self._engine.connect() as conn:
      conn.execute(text(
        'INSERT INTO cache (key, value, expire) VALUES (:k, :v, :e) '
        'ON CONFLICT (key) DO UPDATE SET value=:v, expire=:e'),
        {'k': key, 'v': blob, 'e': exp})
      conn.commit()

  def delete(self, key: str):
    from sqlalchemy import text
    with self._engine.connect() as conn:
      conn.execute(text('DELETE FROM cache WHERE key=:k'), {'k': key})
      conn.commit()

  def close(self):
    if self._engine: self._engine.dispose(); self._engine = None


# .. changed
_BACKENDS = {
  'json': _JsonBackend,
  'pickle': _PickleBackend,
  'sqlite': _SqliteBackend,
  'diskcache': _DiskcacheBackend,
  'db': _DbBackend,
}


# .. gone
DiskCache = None  # removed, use Cache


# .. changed; the one of 2026-11-24 is in gppu/data.py
class Cache:
  """Key/value cache with TTL and env-var bypass.

  Standalone utility -- does not require Env or config initialization.

  Backends (explicit, no fallback):
    json      — JSON file, no deps
    pickle    — pickle file, no deps
    sqlite    — stdlib sqlite3
    diskcache — pip install diskcache
    db        — any SQLAlchemy URL (postgres, mysql, etc.)
  """
  _cache: Any
  _ttl: int
  _skip: bool

  def __init__(self, directory: str, ttl: int = 86400, *,
               backend: str = 'sqlite', skip_env: str = 'SKIP_CACHE'):
    """
    Args:
      directory:  Cache path (file/dir) or DB URL for 'db' backend.
      ttl:        Default TTL in seconds (default: 86400 = 24h).
      backend:    'json', 'pickle', 'sqlite', 'diskcache', or 'db'.
      skip_env:   Env var name to check for bypass (empty string disables).
    """
    import os
    self._ttl = ttl
    self._skip = bool(skip_env and os.getenv(skip_env, '').lower() in ('true', '1', 'yes'))
    if backend not in _BACKENDS:
      raise ValueError(f"Unknown backend {backend!r}, expected one of: {', '.join(_BACKENDS)}")
    path = directory if backend == 'db' else os.path.expanduser(directory)
    self._cache = _BACKENDS[backend](path)

  @property
  def skip(self) -> bool: return self._skip

  def get(self, key: str, default: Any = None) -> Any:
    if self._skip: return default
    try: return self._cache.get(key, default)
    except Exception: return default

  def set(self, key: str, value: Any, ttl: int | None = None) -> None:
    if self._skip: return
    try: self._cache.set(key, value, expire=self._ttl if ttl is None else (ttl or None))
    except Exception: pass

  def delete(self, key: str) -> None:
    try: self._cache.delete(key)
    except Exception: pass

  def __call__(self, fn):
    """Use as @cache decorator for automatic memoization."""
    if self._skip: return fn
    import functools, hashlib
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
      k = f'memo:{fn.__module__}.{fn.__qualname__}:{hashlib.md5(repr((args, kwargs)).encode()).hexdigest()}'
      cached = self.get(k)
      if cached is not None: return cached
      result = fn(*args, **kwargs)
      self.set(k, result)
      return result
    return wrapper

  def close(self):
    if self._cache: self._cache.close(); self._cache = None

  def __enter__(self): return self
  def __exit__(self, *_): self.close()


# .. gone
class _JsonPersistBackend:
  """JSON-file backend. One file, nested dict {cls: {key: data}}. No deps."""

  def __init__(self, path: str):
    import os, json
    self._path = path
    os.makedirs(os.path.dirname(path) if not os.path.isdir(path) else path, exist_ok=True)
    if os.path.isdir(path): self._path = os.path.join(path, '_persist.json')
    self._data: dict[str, dict[str, dict]] = {}
    try:
      with open(self._path) as f: self._data = json.load(f)
    except Exception: pass

  def _flush(self):
    import json
    with open(self._path, 'w') as f: json.dump(self._data, f)

  def upsert(self, cls: str, key: str, data: dict) -> None:
    self._data.setdefault(cls, {})[key] = data
    self._flush()

  def load(self, cls: str, key: str) -> Optional[dict]:
    return self._data.get(cls, {}).get(key)

  def iter(self, cls: str):
    for k, v in self._data.get(cls, {}).items(): yield k, dict(v)

  def delete(self, cls: str, key: str) -> None:
    if self._data.get(cls, {}).pop(key, None) is not None: self._flush()

  def close(self): self._flush()


# .. gone
class _PicklePersistBackend:
  """Pickle-file backend. Same shape as _JsonPersistBackend. No deps."""

  def __init__(self, path: str):
    import os, pickle
    self._path = path
    os.makedirs(os.path.dirname(path) if not os.path.isdir(path) else path, exist_ok=True)
    if os.path.isdir(path): self._path = os.path.join(path, '_persist.pkl')
    self._data: dict[str, dict[str, dict]] = {}
    try:
      with open(self._path, 'rb') as f: self._data = pickle.load(f)
    except Exception: pass

  def _flush(self):
    import pickle
    with open(self._path, 'wb') as f: pickle.dump(self._data, f)

  def upsert(self, cls: str, key: str, data: dict) -> None:
    self._data.setdefault(cls, {})[key] = data
    self._flush()

  def load(self, cls: str, key: str) -> Optional[dict]:
    return self._data.get(cls, {}).get(key)

  def iter(self, cls: str):
    for k, v in self._data.get(cls, {}).items(): yield k, dict(v)

  def delete(self, cls: str, key: str) -> None:
    if self._data.get(cls, {}).pop(key, None) is not None: self._flush()

  def close(self): self._flush()


# .. gone
class _SqlitePersistBackend:
  """SQLite backend. One file, one table `persistent_dc(cls, key, data)`. Stdlib only."""

  def __init__(self, path: str):
    import os, sqlite3, threading
    os.makedirs(os.path.dirname(path) if not os.path.isdir(path) else path, exist_ok=True)
    if os.path.isdir(path): path = os.path.join(path, '_persist.db')
    self._conn = sqlite3.connect(path, check_same_thread=False)
    self._lock = threading.Lock()
    self._conn.execute(
      'CREATE TABLE IF NOT EXISTS persistent_dc '
      '(cls TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL, '
      ' updated_at REAL NOT NULL, PRIMARY KEY (cls, key))')
    self._conn.commit()

  def upsert(self, cls: str, key: str, data: dict) -> None:
    import json, time
    with self._lock:
      self._conn.execute(
        'INSERT OR REPLACE INTO persistent_dc (cls, key, data, updated_at) VALUES (?, ?, ?, ?)',
        (cls, key, json.dumps(data), time.time()))
      self._conn.commit()

  def load(self, cls: str, key: str) -> Optional[dict]:
    import json
    with self._lock:
      row = self._conn.execute(
        'SELECT data FROM persistent_dc WHERE cls=? AND key=?', (cls, key)).fetchone()
    return json.loads(row[0]) if row else None

  def iter(self, cls: str):
    import json
    with self._lock:
      rows = self._conn.execute(
        'SELECT key, data FROM persistent_dc WHERE cls=? ORDER BY key', (cls,)).fetchall()
    for k, d in rows: yield k, json.loads(d)

  def delete(self, cls: str, key: str) -> None:
    with self._lock:
      self._conn.execute('DELETE FROM persistent_dc WHERE cls=? AND key=?', (cls, key))
      self._conn.commit()

  def close(self):
    if self._conn: self._conn.close(); self._conn = None  # type: ignore[assignment]


# .. gone
class _PgPersistBackend(_PGBase):
  """Postgres backend (psycopg2). Table `persistent_dc(cls, key, data JSONB, updated_at)`."""

  SCHEMA_DDL = """
  CREATE TABLE IF NOT EXISTS persistent_dc (
    cls         TEXT NOT NULL,
    key         TEXT NOT NULL,
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (cls, key)
  );
  CREATE INDEX IF NOT EXISTS persistent_dc_cls_idx ON persistent_dc (cls);
  """

  def __init__(self, **kw):
    super().__init__(**kw)
    import threading
    self._lock = threading.Lock()
    with self._lock, self.cursor(dict_cursor=False) as cur:
      cur.execute(self.SCHEMA_DDL)

  def upsert(self, cls: str, key: str, data: dict) -> None:
    from psycopg2.extras import Json
    with self._lock, self.cursor(dict_cursor=False) as cur:
      cur.execute(
        "INSERT INTO persistent_dc (cls, key, data, updated_at) "
        "VALUES (%s, %s, %s, now()) "
        "ON CONFLICT (cls, key) DO UPDATE SET "
        "  data=EXCLUDED.data, updated_at=now()",
        (cls, key, Json(data)))

  def load(self, cls: str, key: str) -> Optional[dict]:
    with self._lock, self.cursor() as cur:
      cur.execute(
        "SELECT data FROM persistent_dc WHERE cls=%s AND key=%s", (cls, key))
      row = cur.fetchone()
    return dict(row['data']) if row else None

  def iter(self, cls: str):
    with self._lock, self.cursor() as cur:
      cur.execute(
        "SELECT key, data FROM persistent_dc WHERE cls=%s ORDER BY key", (cls,))
      rows = cur.fetchall()
    for r in rows: yield r['key'], dict(r['data'])

  def delete(self, cls: str, key: str) -> None:
    with self._lock, self.cursor(dict_cursor=False) as cur:
      cur.execute("DELETE FROM persistent_dc WHERE cls=%s AND key=%s", (cls, key))


# .. gone
_PERSIST_BACKENDS = {
  'json':     _JsonPersistBackend,
  'pickle':   _PicklePersistBackend,
  'sqlite':   _SqlitePersistBackend,
  'postgres': _PgPersistBackend,
}


# .. gone
class Persistence:
  """Storage for `_PersistentDC` instances, multi-backend.

  Mirrors the `Cache` class shape.

  Backends (explicit, no fallback):
    json      — JSON file, no deps
    pickle    — pickle file, no deps
    sqlite    — stdlib sqlite3
    postgres  — psycopg2 + JSONB; takes a connection string (db kwarg)

  Usage:
    p = Persistence('/var/lib/y2/persist.db', backend='sqlite')
    p = Persistence('postgresql://...', backend='postgres')   # target is the DSN

    _PersistentDC.bind_db(p)
  """

  def __init__(self, target: str, *, backend: str = 'sqlite'):
    import os
    if backend not in _PERSIST_BACKENDS:
      raise ValueError(f"Unknown backend {backend!r}, expected one of: {', '.join(_PERSIST_BACKENDS)}")
    if backend == 'postgres':
      self._b = _PgPersistBackend(db=target)
    else:
      self._b = _PERSIST_BACKENDS[backend](os.path.expanduser(target))

  def upsert(self, cls: str, key: str, data: dict) -> None: self._b.upsert(cls, key, data)
  def load(self, cls: str, key: str) -> Optional[dict]: return self._b.load(cls, key)
  def iter(self, cls: str): yield from self._b.iter(cls)
  def delete(self, cls: str, key: str) -> None: self._b.delete(cls, key)
  def close(self):
    if self._b: self._b.close(); self._b = None  # type: ignore[assignment]

  def __enter__(self): return self
  def __exit__(self, *_): self.close()

# endregion


# region - gppu/gppu.py as of 2026-11-20: what was deleted outside the definitions above (26 lines)

# .. comments and commented-out code, as they stood
  # def endswith(self, suffix) -> bool: return self.path.endswith(suffix)
  # def __truediv__(self, path: y2path | str) -> 'y2uri':
  #   if not isinstance(path, (str, y2path)):
  #     return NotImplemented
  #   value = str(path)
  #   if '://' in value:
  #     raise ValueError('Join a path, not another URI')
  #   if '?' in value or '#' in value:
  #     raise ValueError('Join an escaped path; set params and fragment separately')
  #   if not value:
  #     return y2uri(self)
  #   tail = str(self.path)
  #   base = self.scheme + '://' + (tail.rstrip('/') + '/' if tail else '')
  #   result = y2uri(base + value.lstrip('/'))
  #   result.query = self.query
  #   result.fragment = self.fragment
  #   return result
  # def __add__(self, path: y2path | str) -> 'y2uri':
  #   return self / path
# Custom types register themselves here (e.g. iot.py adds y2eid/y2topic)

# .. headers that were replaced
#    region Env: the configuration

# .. other lines that read differently now: docstring text, and lines whose trailing comment was changed
#    jinja = JinjaEnvironment(loader=DictLoader({}))
#    if path in d.keys(): return d[path]   # a key that holds a slash itself
#    if not out.endswith('\u001b[0m'): out = out + '\u001b[0m' # Check if color reset is already present
#    return ''.join(result)  # Reset color at the end
#    ESC = '\033'  # ANSI escape code for terminal colors

# endregion


# region - gppu/app.py as of 2026-11-20: what was deleted outside the definitions above (6 lines)

# .. headers that were replaced
#    region event-loop bridge
#    region Timers: an async app's, held by one thread
#    region API application

# .. other lines that read differently now: docstring text, and lines whose trailing comment was changed
#    ``App`` with ``mixin_Stepper``, the YMRO (Y2 Method Resolution Order) init, load and start steps; ``APIApp`` serves HTTP # type: ignore
#    on it. For Textual, use ``gppu.tui.TUIApp``; for MQTT, ``gppu.iot.MqttApp``.
#    Env, ``_Base`` and ``App``, the regular app with no steps, are in gppu.gppu. Here is ``AsyncApp``, which composes # pyright: ignore[C0301:line-too-long]

# endregion


# region - gppu/iot.py as of 2026-11-20: what was deleted outside the definitions above (7 lines)

# .. headers that were replaced
#    region y2eid
#    region Runtime: Y2's, the program's apps and who listens to what
#    region mqtt

# .. other lines that read differently now: docstring text, and lines whose trailing comment was changed
#    """IoT value types, MQTT transport, and serialized async controls.
#    ``MqttApp`` serves standalone asyncio services. ``mixin_Mqtt`` is the same
#    transport without lifecycle ownership, used by Y2. Controls bridge synchronous
#    callers to one dedicated event-loop thread and serialize each device instance.

# endregion


# region - gppu/data.py as of 2026-11-20: what was deleted outside the definitions above (9 lines)

# .. comments and commented-out code, as they stood
#
# Backend interface (duck-typed):
#   upsert(cls: str, key: str, data: dict) -> None
#   load(cls: str, key: str) -> dict | None
#   delete(cls: str, key: str) -> None
#   close() -> None
#
# All backends namespace storage by (cls, key) pair.

# .. headers that were replaced
#    region Persistence backends for _PersistentDC

# endregion


# region - gppu/__init__.py as of 2026-11-20, whole: what programs could import from gppu

"""
GPPU - General Purpose Python Utilities

A comprehensive utility library providing configuration loading, logging,
data manipulation, and type safety utilities.
"""

from .fs import Container, DataObject, FileSystem, Location, Provider

from .gppu import (
    # Env, its configuration mixins and the regular apps
    Env,
    glob,
    glob_int,
    glob_list,
    glob_dict,
    mixin_Config,
    _Base,
    App,

    # caching, from the standard library
    cache,
    lru_cache,
    cached_property,
)

from .app import (
    # apps with steps
    AsyncApp,
    TimerHandle,
    _callback_wrapper,
    APIApp,
    mixin_Rest,

    # sync lifecycle (AppDaemon / Y2)
    _YMRO,
    YStepper,
    mixin_Stepper,
)

from .gppu import (
    Span,
    TimeSpan,
    uuid_create,
    y2list,
    y2path,
    y2uri,
    y2topic,

    # Version info
    VER_GPPU,
    VER_GPPU_BASE,
    VER_GPPU_BUILD,

    # Human-readable formatters
    format_size,
    format_duration,
    format_since,

    # OS detection
    OSType,
    detect_os,

    # Logger setup

    # Async helpers
    sync,

    # Global configuration
    TRACE_RULES,

    # Configuration loading
    dict_from_yml,
    dict_to_yml,
    dict_from_json,
    dict_to_json,
    dict_sanitize,
    template_populate,
    jinja_template,
    jinja,
    jinja_configuration,
    render_template,
    apply_template,
    JinjaDocument,

    # Dictionary utilities
    deepget,
    deepget_dict,
    deepget_int,
    deepget_float,
    deepget_list,
    deepdict,

    # Type safety and coercion
    safe_int,
    safe_float,
    safe_list,
    safe_timedelta,

    # Time utilities
    now_str,
    now_ts,
    pretty_timedelta,
    prepend_datestamp,
    append_timestamp,

    # String utilities
    pfy,
    slugify,

    # Colored printing
    pcp,
    dpcp,
    TColor,

    # Logging
    Debug,
    Info,
    Warn,
    Error,
    Dump,

    # Mixins
    _mixin,
    Logger,
    mixin_Logger,

    # Foundation classes
)

from .iot import (
    # y2xxx classes
    y2slug,
    y2eid,

    # the program's apps and their listeners
    Runtime,
    ListenerHandle,

    # mqtt library (aiomqtt optional — gppu[mqtt])
    mixin_Mqtt,
    MqttApp,
    AppService,

    # event-loop and device-control bridges
    mixin_EventLoopBridge,
    SerializedControl,
    HTTPControl,
    JSONHTTPControl,
)


__version__ = VER_GPPU
__all__ = [
    'Span', 'TimeSpan', 'uuid_create',
    # Version
    'VER_GPPU', 'VER_GPPU_BASE', 'VER_GPPU_BUILD', '__version__',

    # OS detection
    'OSType', 'detect_os',

    # Logger setup

    # Async helpers
    'sync',

    # Global configuration
    'TRACE_RULES',

    # Configuration
    'dict_from_yml', 'dict_to_yml', 'dict_from_json', 'dict_to_json', 'dict_sanitize',
    'template_populate', 'jinja_template', 'jinja', 'jinja_configuration', 'render_template', 'apply_template',
    'JinjaDocument',

    # Dictionary utilities
    'deepget', 'deepget_dict', 'deepget_float', 'deepget_int', 'deepget_list',
    'deepdict',

    # Type utilities
    'safe_int', 'safe_float', 'safe_list', 'safe_timedelta',

    # Time utilities
    'now_str', 'now_ts', 'pretty_timedelta', 'prepend_datestamp', 'append_timestamp',

    # String utilities
    'pfy', 'slugify',

    # Colored printing
    'pcp', 'dpcp', 'TColor',

    # Logging
    'Debug', 'Info', 'Warn', 'Error', 'Dump',

    # Mixins
    '_mixin', 'mixin_Config',
    'Logger', 'mixin_Logger',

    # Vault / Secrets
    'Vault', 'VaultProvider',
    'VaultProviderOSEnviron', 'VaultProviderAzure',

    # Human-readable formatters
    'format_size', 'format_duration', 'format_since',

    # Env
    'Env',

    # Config access
    'glob', 'glob_int', 'glob_list', 'glob_dict',

    # Foundation classes
    '_Base', 'App', 'TimerHandle', '_callback_wrapper', 'AsyncApp', 'APIApp', 'mixin_Rest',

    # caching, from the standard library
    'cache', 'lru_cache', 'cached_property',

    # y2xxx classes
    'y2list', 'y2path', 'y2uri', 'y2topic', 'y2slug', 'y2eid', 'Runtime', 'ListenerHandle',

    # mqtt library
    'mixin_Mqtt', 'MqttApp', 'AppService',

    # event-loop and device-control bridges
    'mixin_EventLoopBridge', 'SerializedControl', 'HTTPControl', 'JSONHTTPControl',

    # lifecycle: sync YMRO (AppDaemon/Y2)
    'YStepper', 'mixin_Stepper',
]


def __getattr__(name: str):
  """The Vault names import gppu.vault on first use, which gives dict_from_yml ``!secret``."""
  if name in ('Vault', 'VaultProvider', 'VaultProviderOSEnviron', 'VaultProviderAzure'):
    from . import vault
    return getattr(vault, name)
  raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

# endregion


# region - gppu/gppu.py as of 2026-11-11, gone by 2026-11-20 (6)

# .. gone
## _________Code below has deviated from the golden rule                                                  
## !! templates are simple inline functtions that return lists, dicts or scalars to be merged into dicts.
def dict_template_populate(o, data: dict = {}, excludes:list = []) -> dict:
  _ = template_populate(o, data, excludes)
  return _ if isinstance(_, dict) else {}


# .. gone
def jinja_document(filename: str | Path, /, **data) -> str:
  """Render a template file to text, with its own directory as the search path."""
  filename = full_path(filename)
  return JinjaDocument(filename.parent).get_template(filename.name).render(**data)


# .. gone
class TemplateSet:
  """The macros, generators and templates of one configuration, compiled once.

  The configuration's Jinja is of two kinds, evaluated at different times:

  - Startup: templates, generators, behaviors and refs, evaluated once while the
    configuration loads (`resolve`). What they compute is the row's data.
  - Runtime: the named templates of the `*_templates` blocks (`render_template`) and
    the macros code calls (`Env.<table>.<macro>(...)`), evaluated when code asks,
    with what it knows then.

  A macro is a function either kind may call.

  Startup. A template generates the dict an object is built from. A row names
  the template it is an instance of — one name, or a list applied in order — and
  carries only what differs. A template value written in Jinja renders against the
  merged row, so the template says in one place what it computes; a value the row
  carries is data and is never rendered. Resolving a row is

      1. template = the named templates, in order          (rightmost wins)
      2. values   = template | row
      3. data     = generator(values) | template | row      (rightmost wins)
      4. each Jinja value of the template renders against data, in template order
      5. data     = data | behavior(data)

  so an explicit value always beats a computed one. A generator and a behavior are
  named Jinja templates that return an object, never text; a behavior runs after the
  merge and so is the only thing that can rewrite a key the row itself carries. A row
  un-inherits a key its template carries by setting it to null.

  A template declares what its rows reference with `refs`, field to table:
  `{connections: connections}` says the field's value (or each of its values, or each
  of its keys) is a row of the `connections` table; `{'smb/*': connections}` says every
  key of the row shaped `smb/<name>` references one. A table is a mapping at a slash
  path of the context, or a list of such paths. A reference nothing answers fails the
  resolution naming row, field and value.

  Runtime. A `*_templates` block holds named templates that render later — the grammar of an
  address, the payload of a command — with what a rule knows then:
  `render_template(name, **values)`. A row names one; it is data until rendered. The
  blocks are the configuration's, not one table's, so any rule may render any of them.
  """

  RESERVED = ('template', 'generator', 'behavior', 'refs')
  BUILTINS = ('dict', 'list', 'int', 'float', 'str', 'bool', 'len', 'round', 'sorted', 'min', 'max', 'range')

  def __init__(self, macros: str = '', generators: dict | None = None, templates: dict | None = None,
               context: dict | None = None, named: dict[str, dict] | None = None, **globals):
    self.environment = JinjaEnvironment()
    self.environment.globals.update(context or {})
    self.environment.globals.update(globals)
    self.environment.globals.update({name: getattr(builtins, name) for name in self.BUILTINS})
    self.environment.globals['re'] = re
    self.named = {name: source for block in (named or {}).values() for name, source in block.items()}   # the table's
    self.environment.loader = DictLoader(self.named)                                                    # *_templates
    self.environment.globals.update(named or {})                                                        # blocks, by name
    self.environment.globals['render_template'] = self.render_template
    if macros:                                                                             # every macro the block
      module = self.environment.from_string(macros).make_module()                          # defines, callable by
      self.environment.globals.update({name: getattr(module, name)                         # name from any generator
                                       for name in dir(module) if not name.startswith('_')})
    self.templates = dict(templates or {})
    self.generators = {name: self.environment.from_string(source)
                       for name, source in (generators or {}).items()}

  # -- runtime: what code evaluates when it asks ----------------------------------------
  def render_template(self, name: str, /, **values) -> Any:
    """A named template of the table, rendered with these values: the grammar a row names,
    filled in later by a rule with what it knows then."""
    if name not in self.named: raise KeyError(f'no named template {name!r}')
    return self.environment.get_template(name).render(values)

  # -- startup: what the configuration evaluates while it loads ---------------------------
  def _computed(self, name: str, values: dict) -> dict:
    if name not in self.generators: raise KeyError(f'no generator named {name!r}')
    computed = self.generators[name].render(values)
    if not isinstance(computed, dict): raise TypeError(f'generator {name!r} returned {type(computed).__name__}, not an object')
    return computed

  def layers(self, row: dict) -> list[dict]:
    """The templates a row names, in the order they apply."""
    names = row.get('template') or []
    if isinstance(names, str): names = [names]
    for name in names:
      if name not in self.templates: raise KeyError(f'{self._label(row)}: no template named {name!r}')
    return [self.templates[name] for name in names]

  def template(self, row: dict) -> dict:
    """The row's templates merged, rightmost winning; `refs` merged across them."""
    merged, refs = {}, {}
    for layer in self.layers(row):
      merged |= layer
      refs |= layer.get('refs') or {}
    if refs: merged['refs'] = refs
    return merged

  def values(self, row: dict) -> dict:
    """The template's data with the row over it: what the generator is given."""
    return self.template(row) | row

  def resolve(self, row: dict) -> dict:
    template = self.template(row)
    values = template | row
    computed = self._computed(values['generator'], values) if values.get('generator') else {}
    data = computed | template | row
    pending = [key for key, value in template.items()                                      # a Jinja value of the template
               if key not in row and key not in self.RESERVED and self._is_jinja(value)]    # renders against the merged row;
    while pending:                                                                         # the row's own value is data and
      key = pending.pop(0)                                                                 # is never rendered. It sees what
      settled = {k: v for k, v in data.items() if k != key and k not in pending}           # is settled: a value still to be
      data[key] = self.environment.from_string(template[key]).render(settled)              # rendered is not a name yet
    if name := values.get('behavior'): data = data | self._computed(name, data)
    self.check(self._label(row), data, template.get('refs') or {})
    return {k: v for k, v in data.items() if k not in self.RESERVED and v is not None}

  def resolve_all(self, rows) -> list[dict] | dict:
    """Every row of a list, or every value of a mapping keyed by name."""
    if isinstance(rows, dict): return {name: self.resolve(row) for name, row in rows.items()}
    return [self.resolve(row) for row in rows]

  def check(self, label: str, data: dict, refs: dict) -> None:
    """Every reference the row makes is a row of the table it names."""
    for field, tables in refs.items():
      tables = [tables] if isinstance(tables, str) else list(tables)
      if '*' in field:
        prefix, _, suffix = field.partition('*')
        names = [key[len(prefix):len(key) - len(suffix)] for key in data
                 if key.startswith(prefix) and key.endswith(suffix) and len(key) > len(prefix) + len(suffix)]
      else:
        value = data.get(field)
        names = [] if value is None else [value] if isinstance(value, str) else list(value)
      for name in names:
        if not any(name in self.table(path) for path in tables):
          raise KeyError(f'{label}: {field} names {name!r}, which is not in {" or ".join(tables)}')

  def table(self, path: str | y2path) -> dict:
    """The mapping at a slash path of the context."""
    table = deepget(path, self.environment.globals)
    if not isinstance(table, dict): raise KeyError(f'no table at {path!r}')
    return table

  @staticmethod
  def _is_jinja(value) -> bool: return isinstance(value, str) and ('{{' in value or '{%' in value)

  @staticmethod
  def _label(row: dict) -> str: return str(row.get('uid') or row.get('name') or 'row')


# .. its _config_from_key, _config_copy, _config_from_dict, _config_from_env are gone
class mixin_Config(_mixin):
  _my: dict[str, Any] = {}

  def _config_from_key(self, key: str) -> None: self._my.update(Env.glob_dict(key))
  def _config_copy(self, other: mixin_Config) -> None: self._my = dict(other._my)
  def _config_from_dict(self, d: dict) -> None: self._my = deepcopy(d)
  def _config_from_env(self) -> None: self._my = deepcopy(Env._my)

  def my(self, path: str | y2path, default=None) -> Any: return deepget(path, self._my, default=default)
  def my_int(self, path: str | y2path, default: int = 0) -> int: return deepget_int(path, self._my, default=default)
  def my_float(self, path: str | y2path, default: float = float('nan')) -> float: return deepget_float(path, self._my, default=default)
  def my_list(self, path: str | y2path, default: list = []) -> list: return deepget_list(path, self._my, default=default or [])
  def my_dict(self, path: str | y2path, default: dict = {}) -> dict: return deepget_dict(path, self._my, default=default or {})


# .. gone
class Env(mixin_Logger, mixin_Config):
  """The program's environment: singleton app object. It's my is glob"""
  home: Path = Path.home()
  user: str = getpass.getuser()
  os: OSType = detect_os()
  host: str = socket.gethostname().split('.')[0].lower()

  _global_log = True
  initialized: bool = False

  name: str = ''
  app_path: Path

  @staticmethod
  def _load_dict(d: dict) -> None:
    _ = json.dumps(d)
    data = json.loads(Template(_).safe_substitute())

    if Env.initialized or Env._my: 
      Env.reset()
      Info('INFO', 'Environment', 'WRED', 'reset()')

    Env._my = data
    Env.initialized = True

    if 'log_file' in Env._my: Logger.enable_file_logging(log_file=Env._my['log_file'])


  @staticmethod
  def reset() -> None:
    Env._my = {}
    Env.initialized = False


  glob, glob_int, glob_list, glob_dict = (classmethod(mixin_Config.__dict__[n]) for n in ('my', 'my_int', 'my_list', 'my_dict'))
  # @staticmethod
  # @sync
  # async def dump():
  #   Dump('Env.data', Env.data)
  #   return await asyncio.sleep(0)  # Make it truly async


  @staticmethod
  def from_dict(d: dict) -> None:
    """
    Initialize Env from a dict. 
    A topology key (a yaml path) is loaded as the base data; 
    tunables (an inline dict) and the remaining keys override it — mirroring Y2's Environment loader. 
    Without topology the dict itself is the data (back-compatible).
    """
    # config = dict(d)
    # topology = config.pop('topology', None)
    # tunables = config.pop('tunables', None)
    # data = dict_from_yml(topology) if topology else {}
    # if isinstance(tunables, dict): data.update(tunables)
    # data.update(config)
    Env._load_dict(d)


  @staticmethod
  def from_env(name: Optional[str] = None, app_path: Optional[Path] = None, config: str | Path | None = None,
               topology: bool = False) -> None:
    """
    Initialize Env from name + app_path, resolving config file and loading YAML
    config names the file, and
    topology puts the nearest ``_config/config.yaml`` upward under it.
    """
    Env._main_file, Env._main_dir = Env._main()

    Env.name = name or Env._program_name()
    Env.app_path = Env._resolve_app_path(app_path)
    Env.config_file = full_path(config) if config else Env._config_file()

    Logger.init_logger(Env.name)

    config_data = dict_from_yml(Env.config_file) if Env.config_file else {}
    if topology and 'topology' not in config_data: config_data['topology'] = Env._topology_file()
    Env.from_dict(config_data)   # resolves a `topology:` key if the config has one

  @staticmethod
  def init() -> None:
    """Create the environment from ``APP``: ``name``, ``config`` (the file; found by the name when it is not set),
    ``topology`` (the nearest ``_config/config.yaml`` upward goes under the configuration), ``cli`` (the command
    line goes over it), and the log's ``log_file`` and ``trace_rules``, which the configuration and the command line
    override."""
    Env.from_env(name=APP['name'], config=APP['config'], topology=APP['topology'])
    for key in ('log_file', 'trace_rules'):
      if APP[key] is not None and key not in Env._my: Env._my[key] = APP[key]
    if APP['cli']: Env.from_argv(sys.argv[1:])
    if isinstance(rules := Env._my.get('trace_rules'), dict): TRACE_RULES.update(rules)
    if Env._my.get('log_file'): Logger.enable_file_logging(log_file=Env._my['log_file'])

  @staticmethod
  def _topology_file() -> Path:
    for parent in (Env.app_path, *Env.app_path.parents):
      if (candidate := parent / '_config' / 'config.yaml').exists(): return candidate
    raise FileNotFoundError(f"The program needs a topology: no _config/config.yaml walking up from '{Env.app_path}'")

  @staticmethod
  def _main() -> tuple[Path, Path]:
    import __main__
    main_file = Path(getattr(__main__, '__file__', 'app')).resolve()
    return main_file, main_file.parent

  @staticmethod
  def _program_name() -> str:
    # Under PyInstaller __main__.__file__ resolves to __main__; use exe name instead
    return Path(sys.executable).stem if getattr(sys, 'frozen', False) else Env._main()[0].stem

  @staticmethod
  def _app() -> dict:
    """APP as every program starts with it: named after the program, its configuration found by that name, no
    topology, no command line."""
    Env._main_file, Env._main_dir = Env._main()
    Env.name, Env.app_path = Env._program_name(), Env._main_dir
    return {'name': Env.name, 'config': None, 'topology': False, 'cli': False, 'log_file': None, 'trace_rules': None}

  @staticmethod
  def from_argv(argv: list[str]) -> None:
    """The command line over the configuration: ``--key value`` sets that key to the string, ``--verbose`` with no
    value after it sets ``verbose`` to True, and a slash path names a nested key. Arguments that are not a key or its
    value are the program's own."""
    i = 0
    while i < len(argv):
      arg, i = argv[i], i + 1
      if not arg.startswith('--') or len(arg) == 2: continue
      name, value = arg[2:], True
      if i < len(argv) and not argv[i].startswith('--'): value, i = argv[i], i + 1
      node = Env._my
      *parents, key = y2path(name)
      for parent in parents: node = node.setdefault(parent, {})
      node[key] = value

  @staticmethod
  def _resolve_app_path(app_path: Optional[Path] = None) -> Path:
    if not app_path: return Env._main_dir
    if app_path.is_absolute(): return app_path
    # Walk up from script location to find the relative path
    parent = Env._main_dir
    while parent != parent.parent:
      candidate = parent / app_path
      if candidate.exists(): return candidate
      parent = parent.parent
    return Env._main_dir / app_path

  @staticmethod
  def _config_file() -> Path | None:
    """``<name>.yaml`` then ``config.yaml``, searched from ``app_path`` upward —
    so a service in a subdir (e.g. /app/brultech) finds the suite's /app/config.yaml.
    A program with none runs on the command line alone."""
    stem = Path(Env.name).with_suffix('.yaml').name
    names = (stem, 'config.yaml')
    for parent in (Env.app_path, *Env.app_path.parents):
      for name in names:
        candidate = parent / name
        if candidate.exists(): return candidate
    return None


# .. gone
# Global aliases for Env.glob* methods
APP: dict = Env._app()   # what the program's environment is created from; a program sets its keys at its start

# endregion


# region - gppu/app_service.py as of 2026-11-11, gone by 2026-11-20 (2)

# .. its _config_changes, _config_topics, on_change, update_config, config_topics are gone
class AppService(MqttApp):
  """An MqttApp that runs all the time and reloads its configuration from MQTT.

  ``config_mqtt/topics`` in its configuration names the topics. Register what reacts to a
  change with ``AppService.on_change(callback, path)``; the configuration is already replaced
  when a callback runs, so it reads ``Env`` as usual.
  """

  changed_paths: frozenset[str] = frozenset()
  _listeners: list[tuple[str, Callable[[frozenset[str]], None]]] = []
  _config_paths: dict[str, str]

  @staticmethod
  def _config_changes(before: dict, after: dict, prefix: str = '') -> frozenset[str]:
    changed = set()
    for key in before.keys() | after.keys():
      path = f'{prefix}/{key}' if prefix else str(key)
      if key not in before or key not in after:
        changed.add(path)
      elif isinstance(before[key], dict) and isinstance(after[key], dict):
        changed.update(AppService._config_changes(before[key], after[key], path))
      elif isinstance(before[key], list) and isinstance(after[key], list):
        if json.dumps(before[key], sort_keys=True) != json.dumps(after[key], sort_keys=True): changed.add(path)
      elif type(before[key]) is not type(after[key]) or before[key] != after[key]:
        changed.add(path)
    return frozenset(changed)


  @staticmethod
  def _config_topics(topics: dict[str, str]) -> dict[str, str]:
    if not isinstance(topics, dict) or not topics:
      raise ValueError('MQTT configuration requires a topic to Env path mapping')
    paths = []
    for topic, path in topics.items():
      if not isinstance(topic, str) or not topic or '+' in topic or '#' in topic:
        raise ValueError('MQTT configuration topics must be exact topic names')
      if not isinstance(path, str) or (path and any(not part for part in path.split('/'))):
        raise ValueError('MQTT configuration paths must be slash paths or empty for the root')
      if any(not path or not other or path == other or path.startswith(other + '/')
             or other.startswith(path + '/') for other in paths):
        raise ValueError('MQTT configuration paths must not overlap')
      paths.append(path)
    return dict(topics)

  @staticmethod
  def on_change(callback: Callable[[frozenset[str]], None], path: str | y2path = '') -> Callable[[], None]:
    """Observe changed slash paths after loading; return a callable to unsubscribe.

    Callbacks are synchronous. The consumer decides how to apply each change.
    Registrations survive configuration reloads and Env.reset().
    """
    if inspect.iscoroutinefunction(callback): raise TypeError('configuration change callbacks must be synchronous')
    entry = (str(path).strip('/'), callback)
    AppService._listeners.append(entry)
    def unsubscribe():
      if entry in AppService._listeners: AppService._listeners.remove(entry)
    return unsubscribe

  @staticmethod
  def update_config(data: dict, path: str | y2path = '') -> None:
    """Replace one configuration subtree; an empty path replaces the whole config."""
    if not isinstance(data, dict): raise TypeError('configuration must be a mapping')
    updated = deepcopy(Env._my) if path else data
    if path:
      node = updated
      *parents, key = y2path(path)
      for parent in parents:
        if parent not in node: node[parent] = {}
        node = node[parent]
        if not isinstance(node, dict): raise TypeError(f'configuration parent is not a mapping: {path}')
      node[key] = data
    changed = AppService._config_changes(Env._my, updated)
    AppService.changed_paths = changed
    if Env.initialized and not changed: return
    Env._load_dict(updated)
    for watched, callback in tuple(AppService._listeners):
      relevant = frozenset(key for key in changed if not watched or key == watched
                           or key.startswith(watched + '/') or watched.startswith(key + '/'))
      if relevant: callback(relevant)

  @staticmethod
  async def from_mqtt(config: dict) -> None:
    """Load exact topics into their declared Env paths, then disconnect.

    config contains connection and topics (MQTT topic -> Env path).
    """
    await _StartupConfig(config).run()

  def config_topics(self) -> dict[str, str]:
    """MQTT topic -> the configuration path it replaces."""
    return self.my('config_mqtt/topics')

  async def __load(self) -> None:
    if not Env.initialized: raise RuntimeError('load the MQTT bootstrap with Env.from_env() first')
    self._config_paths = self._config_topics(self.config_topics())
    for topic in self._config_paths:
      await self.mqtt_listen(self._receive_config, topic, qos=1, raise_errors=True)

  async def _receive_config(self, topic: y2topic, payload: object) -> None:
    data = yaml.safe_load(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict): raise TypeError(f'MQTT configuration must be a mapping: {topic}')
    AppService.update_config(data, self._config_paths[str(topic)])


# .. gone
class _StartupConfig(AppService):
  """Read retained startup configuration, then close the temporary connection."""

  def __init__(self, config: dict):
    connection, topics = config['connection'], self._config_topics(config['topics'])
    if not isinstance(connection, dict) or not connection.get('hostname'):
      raise ValueError('MQTT configuration requires connection.hostname')
    if not Env.initialized: raise RuntimeError('load the MQTT bootstrap with Env.from_env() first')
    super().__init__(name='config-mqtt')
    self.connection = connection
    self.topics = dict(topics)
    self.pending = set(topics)

  def config_topics(self) -> dict[str, str]: return self.topics

  async def _receive_config(self, topic: y2topic, payload: object) -> None:
    await super()._receive_config(topic, payload)
    self.pending.discard(str(topic))
    if not self.pending: self.stop()

# endregion


# region - gppu/gppu.py as of 2026-10-19, gone by 2026-11-20 (21)

# .. its __fspath__, __getattr__, copy, cwd, home, from_uri are gone
class y2path(y2list):
  """
    A slash-separated path held as a list. An element of the list can be called a segment,
    as in https://www.rfc-editor.org/rfc/rfc3986.html#section-3.3

    Path methods and properties operate on the current segments: p.read_text(), p.parent.
    Return values follow pathlib; supplied targets can remain y2path. Segment operators stay unchanged.
    copy() copies the segments; copy(target, **kwargs) copies the filesystem entry.
  """
  def __init__(self, *args):
    data = []
    self.token = '/'
    self._root = ''
    self._drive_root = False

    for i, a in enumerate(args):
      if isinstance(a, os.PathLike): a = os.fspath(a)
      if isinstance(a, str):
        if os.sep != '/': a = a.replace(os.sep, '/')
        if i == 0:
          self._root = '//' if a.startswith('//') else '/' if a.startswith('/') else ''
          self._drive_root = bool(PureWindowsPath(a).drive and PureWindowsPath(a).root)
      data += self._any2list(a)
    self.data = self._any2list(data)

  def __str__(self):
    result = self._root + super().__str__()
    if self._drive_root and len(self.data) == 1 and result.endswith(':'): result += '/'
    return result

  def __fspath__(self) -> str: return str(self)

  def __getattr__(self, name):
    if name.startswith('__') or 'data' not in self.__dict__: raise AttributeError(name)
    return getattr(Path(self), name)

  def copy(self, *args, **kwargs):
    if not args and not kwargs: return super().copy()
    return Path(self).copy(*args, **kwargs)

  @classmethod
  def cwd(cls): return cls(Path.cwd())

  @classmethod
  def home(cls): return cls(Path.home())

  @classmethod
  def from_uri(cls, uri): return cls(Path.from_uri(uri))

  def __truediv__(self, other: str | y2path) -> y2path:
    return y2path(self, other)


# .. gone
def dict_sort_keylen(d, reverse: bool = True) -> dict:
  if not isinstance(d,dict): return {}
  return dict(sorted(d.items(), key=lambda key: len(key[0]), reverse=reverse))


# .. gone
def dict_element_append(d: dict, key: str, value, unique=False) -> None:
  """ coerces key value in dict to list, than appends value to it
      Replaces safe_add_unique """
  key = str(key)
  if isinstance(value, list):
    for v in value: dict_element_append(d, key, v, unique)
  elif not d.get(key): d[key] = [value]
  elif isinstance(d[key], str): d[key] = [d[key], value]
  elif isinstance(d[key], list):
    if unique and value in d[key]: pass
    else: d[key] += [value]
  else: raise Exception(f"Unrecognized type: {type(d[key])}")


# .. gone
def dict_all_paths(d: dict) -> list:
  """Returns all paths in a dict as a list of strings"""
  result: list = []
  for key, value in d.items():
    if isinstance(value, dict):
      new_keys: list = dict_all_paths(value)
      result.append(key)
      for innerkey in new_keys: result.append(f'{key}/{innerkey}')
    else: result.append(key)
  return result


# .. gone
YML_BARE_INCLUDE = re.compile(r"^!include\s+\S.*$", re.MULTILINE)


# .. gone
YML_BARE_KEY = '__include_'


# .. gone
_ANSI = re.compile(r'\x1b\[[0-9;]*m')


# .. gone
def _traced(record: logging.LogRecord) -> bool:
  if record.levelno != logging.DEBUG: return True
  function = _remove_prefixes(record.funcName or '', _SHORTEN_BY_PREFIX)
  names = [function, record.module, f'{record.module}.{function}']
  if class_name := getattr(record, 'gppu_class', ''):
    names += [class_name, f'{class_name}.{function}']
  return all(TRACE_RULES[name] if name in TRACE_RULES else TRACE_RULES.get('all', False) for name in names)


# .. gone
def _fmt(record: logging.LogRecord, *, no_prefix: bool = False) -> str:
  args = list(record.gppu_args) if hasattr(record, 'gppu_args') else [record.getMessage()]
  if not no_prefix:
    function = _remove_prefixes(record.funcName or '', _SHORTEN_BY_PREFIX)
    class_name = getattr(record, 'gppu_class', '')
    caller = f'{class_name}.{function}' if class_name else function
    severity = 'Warn' if record.levelno == logging.WARNING else record.levelname.title()
    color = _SEVERITY_COLORS.get(severity, _SEVERITY_COLORS[None])
    args = [color, severity, 'GRAY1', caller, 'NONE'] + args
  text = pcp(*args)
  if record.exc_info:
    text += '\n' + logging.Formatter().formatException(record.exc_info)
  if record.stack_info: text += '\n' + record.stack_info
  return text


# .. gone
_logger = _log_root


# .. gone
# File handlers live on the shared parent so pre-existing mixins receive them.
_file_handlers: dict[str, logging.Handler] = {}


# .. gone
def enable_file_logging(name: str | None = None, log_dir: str | Path | None = None,
                        level: int = logging.DEBUG) -> Path:
  """Mirror logs to Env's explicit `log_file`, or an explicit name + log_dir.

  Env enables this automatically when YAML declares `log_file`. No directory
  or filename is inferred. Creation errors propagate to the caller.
  """
  if log_dir is not None:
    if not name: raise ValueError('File logging with log_dir requires a name')
    path = full_path(Path(log_dir) / f'{name}.log')
  else:
    value = Env.glob('log_file')
    if not isinstance(value, str) or not value.strip():
      raise ValueError('File logging requires an explicit log_file in configuration')
    path = full_path(value)
  path.parent.mkdir(parents=True, exist_ok=True)
  key = str(path)
  if key in _file_handlers:
    return path
  from logging.handlers import RotatingFileHandler
  fh = RotatingFileHandler(path, maxBytes=4_000_000, backupCount=5, encoding='utf-8')
  fh.setLevel(level)
  fh.setFormatter(_PlainFormatter())
  fh.addFilter(_EmptyMessageFilter())
  _log_root.addHandler(fh)
  _file_handlers[key] = fh
  return path


# .. gone
def file_log(msg: str, *args, level: int = logging.INFO) -> None:
  """Emit a line only to gppu's file handler(s), bypassing the console handler.

  For Textual TUI apps whose visible "console" is the on-screen panel: this
  mirrors panel lines into the log file without writing to stderr (which would
  corrupt the live TUI). No-op when file logging isn't enabled.
  """
  if not _file_handlers:
    return
  record = _logger.makeRecord(_logger.name, level, '(app)', 0,
                              _ANSI.sub('', pcp(msg, *args)), (), None,
                              func='file_log', extra={'gppu_args': (msg, *args)})
  for h in _file_handlers.values():
    if record.levelno >= h.level:
      h.handle(record)


# .. gone
def _init_logger_base(name: str = 'gppu', trace_rules: dict | None = None) -> None:
  """Initialize global logger with a specific name and optional trace rules."""
  global _logger
  if trace_rules is not None:
    trace_rules = dict(trace_rules)
    TRACE_RULES.clear()
    TRACE_RULES.update(trace_rules)
  _logger = _log_root if name == 'gppu' else _log_root.getChild(name)


# .. gone
init_logger = _init_logger_base


# .. gone
def _config_changes(before: dict, after: dict, prefix: str = '') -> frozenset[str]:
  changed = set()
  for key in before.keys() | after.keys():
    path = f'{prefix}/{key}' if prefix else str(key)
    if key not in before or key not in after:
      changed.add(path)
    elif isinstance(before[key], dict) and isinstance(after[key], dict):
      changed.update(_config_changes(before[key], after[key], path))
    elif isinstance(before[key], list) and isinstance(after[key], list):
      if json.dumps(before[key], sort_keys=True) != json.dumps(after[key], sort_keys=True): changed.add(path)
    elif type(before[key]) is not type(after[key]) or before[key] != after[key]:
      changed.add(path)
  return frozenset(changed)


# .. its on_change, update_config, from_mqtt, template_set, named_templates, glob, glob_int, glob_list, glob_dict, dump are gone
class Env:
  data: dict[str, Any] = {}
  initialized: bool = False
  changed_paths: frozenset[str] = frozenset()
  _listeners: list[tuple[str, Callable[[frozenset[str]], None]]] = []

  name: str
  app_path: Path

  home: Path = Path.home()
  user: str = getpass.getuser()
  os: OSType = detect_os()

  _logger: logging.Logger

  @staticmethod
  def _load_dict(d: dict) -> None:
    s = json.dumps(d)
    data = json.loads(Template(s).safe_substitute())
    if not isinstance(data, dict): raise TypeError('configuration must be a mapping')
    if 'trace_rules' in data and not isinstance(data['trace_rules'], dict):
      raise TypeError('trace_rules must be a mapping')
    if 'log_file' in data and (not isinstance(data['log_file'], str) or not data['log_file'].strip()):
      raise ValueError('File logging requires an explicit log_file in configuration')
    changed = _config_changes(Env.data, data)
    if Env.initialized and not changed:
      Env.changed_paths = changed
      return
    if 'trace_rules' in Env.data and 'trace_rules' not in data: TRACE_RULES.clear()
    if Env.initialized or Env.data: Env.reset(); Logger.Info('INFO', 'Environment', 'WRED', 'reset()')
    Env.data = data
    Env.initialized = True
    if 'trace_rules' in Env.data:
      rules = Env.glob('trace_rules')
      if not isinstance(rules, dict): raise TypeError('trace_rules must be a mapping')
      TRACE_RULES.clear()
      TRACE_RULES.update(rules)
    if 'log_file' in Env.data: enable_file_logging()
    Env.changed_paths = changed
    for path, callback in tuple(Env._listeners):
      relevant = frozenset(key for key in changed if not path or key == path
                           or key.startswith(path + '/') or path.startswith(key + '/'))
      if relevant: callback(relevant)

  @staticmethod
  def reset() -> None:
    for handler in tuple(_file_handlers.values()):
      _log_root.removeHandler(handler)
      handler.close()
    _file_handlers.clear()
    Env.data = {}
    Env.initialized = False
    Env.changed_paths = frozenset()

  @staticmethod
  def on_change(callback: Callable[[frozenset[str]], None], path: str = '') -> Callable[[], None]:
    """Observe changed slash paths after loading; return a callable to unsubscribe.

    Callbacks are synchronous. The consumer decides how to apply each change.
    Registrations survive configuration reloads and reset().
    """
    if inspect.iscoroutinefunction(callback): raise TypeError('configuration change callbacks must be synchronous')
    entry = (path.strip('/'), callback)
    Env._listeners.append(entry)
    def unsubscribe():
      if entry in Env._listeners: Env._listeners.remove(entry)
    return unsubscribe

  @staticmethod
  def update_config(data: dict, path: str = '') -> None:
    """Replace one configuration subtree; an empty path replaces the whole config."""
    if not isinstance(data, dict): raise TypeError('configuration must be a mapping')
    if not path:
      Env._load_dict(data)
      return
    updated = deepcopy(Env.data)
    node = updated
    *parents, key = path.split('/')
    for parent in parents:
      if parent not in node: node[parent] = {}
      node = node[parent]
      if not isinstance(node, dict): raise TypeError(f'configuration parent is not a mapping: {path}')
    node[key] = data
    Env._load_dict(updated)

  @staticmethod
  async def from_mqtt(config: dict) -> None:
    """Load exact topics into their declared Env paths through gppu's MQTT transport.

    config contains connection and topics (MQTT topic -> Env path). Disconnect
    once all topics arrive. Apps needing updates use their own mqtt_config().
    """
    from .iot import _MqttConfig
    await _MqttConfig(config).run()

  @staticmethod
  def template_set(path: str = '', **context) -> 'TemplateSet':
    """The macros, generators and templates of one table of the configuration.

    A table that declares them resolves its own rows; the root's macros are offered to
    every table, and the rest of the configuration to every generator, so one can reach
    the tables it computes against."""
    table = Env.glob_dict(path) if path else Env.data
    macros = chr(10).join(block for block in (Env.data.get('macros', '') if path else '', table.get('macros', '')) if block)
    return TemplateSet(macros=macros, generators=table.get('generators'), templates=table.get('templates'),
                       named=Env.named_templates(), context=Env.data | context)

  @staticmethod
  def named_templates() -> dict[str, dict]:
    """Every `*_templates` block of the configuration, the root's and every table's, by block
    name: the named templates any rule may render, as in Y2. A name is unique across the
    configuration."""
    blocks: dict[str, dict] = {}
    for holder in (Env.data, *(content for content in Env.data.values() if isinstance(content, dict))):
      for key, block in holder.items():
        if not (key.endswith('_templates') and isinstance(block, dict)): continue
        if clash := set(blocks.get(key, {})) & set(block): raise ValueError(f'{key}: {sorted(clash)} defined twice')
        blocks.setdefault(key, {}).update(block)
    return blocks

  @staticmethod
  def glob(path, default=None) -> Any: return Env.data if path == '' else deepget(path, Env.data, default=default)
  @staticmethod
  def glob_int(path, default: int = 0) -> int: return deepget_int(path, Env.data, default=default)
  @staticmethod
  def glob_list(path, default=[]) -> list: return deepget_list(path, Env.data, default=default)
  @staticmethod
  def glob_dict(path, default={}) -> dict: return Env.data if path == '' else deepget_dict(path, Env.data, default=default)
  @staticmethod
  @sync
  async def dump():
    Dump('Env.data', Env.data)
    return await asyncio.sleep(0)  # Make it truly async

  @staticmethod
  def from_dict(d: dict) -> None:
    """Initialize Env from a dict. A ``topology`` key (a yaml path) is loaded as
    the base data; ``tunables`` (an inline dict) and the remaining keys override
    it — mirroring Y2's Environment loader. Without ``topology`` the dict itself
    is the data (back-compatible)."""
    config = dict(d)
    topology = config.pop('topology', None)
    tunables = config.pop('tunables', None)
    data = dict_from_yml(topology) if topology else {}
    if isinstance(tunables, dict): data.update(tunables)
    data.update(config)
    Env._load_dict(data)

  @staticmethod
  def from_env(name: Optional[str] = None, app_path: Optional[Path] = None) -> None:
    """Initialize Env from name + app_path, resolving config file and loading YAML."""
    import __main__
    Env._main_file = Path(getattr(__main__, '__file__', 'app')).resolve()
    Env._main_dir = Env._main_file.parent

    # Under PyInstaller __main__.__file__ resolves to __main__; use exe name instead
    if name:
      Env.name = name
    elif getattr(sys, 'frozen', False):
      Env.name = Path(sys.executable).stem
    else:
      Env.name = Env._main_file.stem
    Env.app_path = Env._resolve_app_path(app_path)
    Env.config_file = Env._config_file()

    Env._logger = _logger.getChild(Env.name)
    for attr_name, fn in (('Debug', Debug), ('Info', Info), ('Warn', Warn), ('Error', Error), ('Dump', Dump)):
      setattr(Env, attr_name, staticmethod(partial(fn, logger=Env._logger)))

    config_data = dict_from_yml(Env.config_file)
    Env.from_dict(config_data)   # resolves a `topology:` key if the config has one

  @staticmethod
  def _resolve_app_path(app_path: Optional[Path] = None) -> Path:
    if not app_path: return Env._main_dir
    if app_path.is_absolute(): return app_path
    # Walk up from script location to find the relative path
    parent = Env._main_dir
    while parent != parent.parent:
      candidate = parent / app_path
      if candidate.exists(): return candidate
      parent = parent.parent
    return Env._main_dir / app_path

  @staticmethod
  def _config_file() -> Path:
    """``<name>.yaml`` then ``config.yaml``, searched from ``app_path`` upward —
    so a service in a subdir (e.g. /app/brultech) finds the suite's /app/config.yaml.
    Each is matched as a Jinja document too, so a templated configuration is found
    with no change at the call site."""
    stem = Path(Env.name).with_suffix('.yaml').name
    names = (stem, f'{stem}.j2', 'config.yaml', 'config.yaml.j2')
    for parent in (Env.app_path, *Env.app_path.parents):
      for name in names:
        candidate = parent / name
        if candidate.exists(): return candidate
    raise FileNotFoundError(f"Config ({' or '.join(names)}) not found walking up from '{Env.app_path}'")


# .. gone
class protocol_Logger:
  Debug: Callable[..., Any]
  Info : Callable[..., Any]
  Warn : Callable[..., Any]
  Error: Callable[..., Any]
  Dump : Callable[..., Any]


# .. its __init__ is gone
class mixin_Logger(protocol_Logger, _mixin):
  _logger: logging.Logger

  @classmethod
  def __init_subclass__(cls, **kw):
    super().__init_subclass__(**kw)
    cls._logger = _logger.getChild(cls.__name__)
    for name, fn in (('Debug', Debug), ('Info', Info), ('Warn', Warn), ('Error', Error), ('Dump', Dump)): setattr(cls, name, staticmethod(partial(fn, logger=cls._logger)))

  def __init__(self, *a, **kw):
    super(mixin_Logger, self).__init__(*a, **kw)
    for name in ('Debug', 'Info', 'Warn', 'Error', 'Dump'): setattr(self, name, getattr(self.__class__, name))


# .. gone
class _Logger(mixin_Logger): pass


# .. gone
class _Config(mixin_Config):
  _base_path: Path

  def __init__(self, **kw) -> None:
    super().__init__(**kw)
    if Env.initialized:
      self._config_from_env()
    self._base_path = Path('.')

# endregion


# region - gppu/app.py as of 2026-10-19, gone by 2026-11-20 (6)

# .. gone
class _App(_Base):
  """Base class with logging, configuration, and automatic Env discovery."""

  name: str = ''

  def __init__(self, name: str = '', **kw) -> None:
    app_file = Path(inspect.getfile(type(self))).resolve()
    self.name = name or app_file.stem
    if not Env.initialized:
      Environment.from_env(name=self.name, app_path=app_file.parent)   # the config, and what it constructs
    super().__init__(name=self.name, **kw)


# .. gone
class CliApp(App):
  """Runs ``main`` once; the command line gives its parameters (gppu.params). What it returns is printed as JSON on
  stdout; logs go to stderr. A parameter the command line does not give comes from the app's table in the
  configuration, named after the app, or from the whole configuration when there is no such table.

  Usage::

      from gppu import CliApp
      class Archive(CliApp):
        def main(self, since: str = '7d', dry_run: bool = False) -> dict:
          '''Archive what changed.'''
      if __name__ == '__main__': Archive.cli()
  """

  def main(self, *a, **kw) -> Any: raise NotImplementedError(f'{type(self).__name__} defines no main')

  def params(self, **given: Any) -> dict[str, Any]:
    """main's keyword arguments: given, then configuration, then defaults."""
    table = Env.data.get(self.name)
    return resolve(self.main, given, table if isinstance(table, dict) else Env.data)

  def invoke(self, **given: Any) -> Any: return call(self.main, self.params(**given))

  @classmethod
  def cli(cls, argv: list[str] | None = None) -> Any:
    """Start from the command line; ``--schema`` prints the parameters instead."""
    app = cls()
    given = vars(parser(app.main, app.name).parse_args(argv))
    if given.pop('schema', False): return print(json.dumps(schema(app.main), indent=2))
    result = app.invoke(**given)
    if result is not None: print(json.dumps(result, indent=2, default=str))
    return result


# .. gone
class EventLoopBridge:
  """Schedules coroutines on an externally owned loop; ``call`` blocks off-loop."""

  def schedule[T](self, coroutine: Coroutine[Any, Any, T], /) -> AsyncSubmission[T]:
    return self._schedule(self._get_loop(), coroutine)

  def submit[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> AsyncSubmission[T]:
    return self.schedule(function(*args, **kwargs))

  def call[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> T:
    loop = self._get_loop()
    if self._on_loop(loop): raise RuntimeError('cannot block the target event-loop thread')
    future = self._schedule(loop, function(*args, **kwargs))
    try: return future.result()
    except BaseException:
      if not future.done(): future.cancel()
      raise

  def on_loop(self) -> bool: return self._on_loop(self._get_loop())

  @staticmethod
  def _schedule[T](loop: asyncio.AbstractEventLoop, coroutine: Coroutine[Any, Any, T], /) -> AsyncSubmission[T]:
    try:
      if EventLoopBridge._on_loop(loop): return loop.create_task(coroutine)
      return asyncio.run_coroutine_threadsafe(coroutine, loop)
    except BaseException:
      coroutine.close()
      raise

  @staticmethod
  def _on_loop(loop: asyncio.AbstractEventLoop) -> bool:
    try: return asyncio.get_running_loop() is loop
    except RuntimeError: return False

  def _get_loop(self) -> asyncio.AbstractEventLoop:
    raise NotImplementedError


# .. gone
def _born(cls: type) -> str:
  """Where a class's source lives; a built-in has none."""
  try: return inspect.getsourcefile(cls) or ''
  except TypeError: return ''


# .. its setup, start, stop are gone
class AsyncApp(mixin_Rest, App, EventLoopBridge):
  """Application base for long-lived asyncio services.

  Override ``setup()`` for synchronous setup during construction with config ready,
  and async ``start()`` for work. Run with ``asyncio.run(MyApp().run())`` or
  ``await app.run()`` on a host's loop. In ``start()``, use ``self._spawn(coro)``
  for concurrent work; ``run()`` waits for start and its TaskGroup to finish.

  On that loop, ``await app.stop()`` cancels spawned tasks, not ``start()`` itself.
  Put resource cleanup in the owning coroutine's ``finally`` or async context;
  ``run()`` does not call ``stop()`` automatically.
  The app is an ``EventLoopBridge`` onto its own running loop, so off-loop threads
  ``schedule``/``submit``/``call`` work onto it. See ``mixin_Rest`` for HTTP hosting.
  """

  _task_group: asyncio.TaskGroup | None
  _background_tasks: set[asyncio.Task[Any]]
  _loop: asyncio.AbstractEventLoop | None

  def __init__(self, name: str = '', **kw) -> None:
    super().__init__(name=name, **kw)
    self._task_group = None
    self._background_tasks = set()
    self._loop = None
    self.setup()

  def setup(self) -> None: pass
  async def start(self) -> None: pass

  def _get_loop(self) -> asyncio.AbstractEventLoop:
    loop = self._loop
    if loop is None: raise RuntimeError(f'{self!r} is not running')
    return loop

  async def run(self) -> None:
    if self._task_group is not None: raise RuntimeError(f'{self!r} is already running')
    try:
      self._loop = asyncio.get_running_loop()
      async with asyncio.TaskGroup() as tasks:
        self._task_group = tasks
        await self.start()
    finally:
      self._task_group = None
      self._loop = None
      self._background_tasks.clear()

  async def stop(self) -> None:
    current = asyncio.current_task()
    tasks = [task for task in self._background_tasks if task is not current and not task.done()]
    for task in tasks: task.cancel()
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)

  def _spawn[T](self, coroutine: Coroutine[Any, Any, T], /) -> asyncio.Task[T]:
    tasks = self._task_group
    if tasks is None:
      coroutine.close()
      raise RuntimeError(f'{self!r} is not running')
    try: task = tasks.create_task(coroutine)
    except BaseException:
      coroutine.close()
      raise
    self._background_tasks.add(task)
    task.add_done_callback(self._background_tasks.discard)
    return task


# .. its start is gone
class APIApp(AsyncApp):
    """An AsyncApp that serves HTTP, the transport ``mixin_Rest`` leaves to its host: on uvicorn, at the ``host`` and ``port`` of its
    configuration, its own objects at ``/rest`` and each ASGI app ``apis()`` gives at its path.

    ``GET /rest`` lists the objects, ``GET /rest/{registry}/{key}`` reads one and ``GET /rest/{registry}/{key}/{name}`` one of its
    values, ``POST /rest/{registry}/{key}/{name}`` calls a method with the JSON body as its arguments. Override ``apis()``; override
    ``start()`` for work before serving and end it with ``await super().start()``. FastAPI and uvicorn come with the ``ld`` extra::

        class LDAPI(APIApp):
            def setup(self): ld.connect(self.my('postgres'))
            def apis(self): return {'/ld/v1': ld.served({'/work': work.app})}
    """

    def apis(self) -> dict[str, Any]:
        """path -> the FastAPI (or any ASGI) app served there."""
        return {}

    def asgi(self):
        """The app uvicorn serves: ``/rest``, and the apps of ``apis()`` at their paths."""
        from fastapi import Body, FastAPI, Response

        def answer(reply: tuple[Any, int]) -> Response:   # a value gppu holds (a time, a uri) is sent as its text
            return Response(json.dumps(reply[0], default=str, ensure_ascii=False), status_code=reply[1], media_type='application/json')

        root = FastAPI(title=self.name)

        @root.get('/rest')
        def objects(kind: str | None = None): return answer(self.rest_objects(kind, full=True))

        @root.get('/rest/{registry}/{key}')
        def read(registry: str, key: str): return answer(self.rest_read(registry, key))

        @root.get('/rest/{registry}/{key}/{name}')
        def value(registry: str, key: str, name: str): return answer(self.rest_read(registry, key, name))

        @root.post('/rest/{registry}/{key}/{name}')
        async def call(registry: str, key: str, name: str, body: dict = Body(default_factory=dict)):
            return answer(await self.rest_call(registry, key, name, body))

        for path, app in self.apis().items(): root.mount(path, app)
        return root

    async def start(self) -> None:
        import uvicorn
        await uvicorn.Server(uvicorn.Config(self.asgi(), host=self.my('host'), port=self.my('port'))).serve()

# endregion


# region - gppu/iot.py as of 2026-10-19, gone by 2026-11-20 (4)

# .. its mqtt_config, _receive_config are gone
class mixin_Mqtt:
  """MQTT for a host that owns its lifecycle and loop, as Y2 does.

  Supply ``connection``, ``Info``/``Warn`` and ``_spawn(coro)`` to schedule and
  track work on that loop. Call ``_start_mqtt()`` there at startup, then cancel
  and await the host's tasks at shutdown. Use the same subscription, publishing
  and connected-work hooks described on ``MqttApp``.
  """

  _CLIENT_KEYS = ('hostname', 'port', 'username', 'password', 'identifier')
  MQTT_RECONNECT_DELAY = 5

  connection: dict[str, Any]
  MQTT_PROTOCOL: Any = None
  _client: Any = None
  _mqtt_task: Any = None
  _callbacks: dict[y2topic, list[tuple[MqttCallback, object, bool, bool]]]
  _subscriptions: dict[y2topic, int]
  _config_paths: dict[str, str]
  _mqtt_lock: asyncio.Lock
  _callback_lock: asyncio.Lock

  def _start_mqtt(self):
    task = self._mqtt_task
    if task is not None and not task.done(): return task

    coroutine = self._mqtt_loop()
    try: task = self._spawn(coroutine)
    except BaseException:
      coroutine.close()
      raise
    self._mqtt_task = task
    return task

  def _ensure_mqtt_state(self) -> None:
    if getattr(self, '_mqtt_lock', None) is not None: return
    self._callbacks = {}
    self._subscriptions = {}
    self._config_paths = {}
    self._mqtt_lock = asyncio.Lock()
    self._callback_lock = asyncio.Lock()

  async def mqtt_listen(self, callback: MqttCallback, topic: y2topic | str, payload: object = None, *, ignore_retained: bool = False, raise_errors: bool = False, **data: Any) -> None:
    self._ensure_mqtt_state()
    topic = y2topic(topic)
    qos = int(data.get('qos', 0))

    async with self._mqtt_lock:
      callbacks = self._callbacks.setdefault(topic, [])
      entry = (callback, payload, ignore_retained, raise_errors)
      if entry not in callbacks: callbacks.append(entry)

      old_qos = self._subscriptions.get(topic, -1)
      qos = max(old_qos, qos)
      self._subscriptions[topic] = qos
      client = self._client if qos != old_qos else None

    if client is not None: await client.subscribe(str(topic), qos=qos)

  async def mqtt_config(self, topics: dict[str, str]) -> None:
    """Receive Env configuration on this app's existing MQTT transport.

    Register in subscribe() or while connected. This does not start a connection
    or wait for initial delivery; Env.on_change() reports received changes.
    """
    if not Env.initialized: raise RuntimeError('load the MQTT bootstrap with Env.from_env() first')
    self._ensure_mqtt_state()
    topics = _mqtt_config_topics(topics)
    self._config_paths = _mqtt_config_topics(self._config_paths | topics)
    for topic in topics:
      await self.mqtt_listen(self._receive_config, topic, qos=1, raise_errors=True)

  async def _receive_config(self, topic: y2topic, payload: object) -> None:
    data = yaml.safe_load(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict): raise TypeError(f'MQTT configuration must be a mapping: {topic}')
    Env.update_config(data, self._config_paths[str(topic)])

  async def mqtt_publish(self, topic: y2topic | str, payload: MqttPayload = '', **data: Any) -> None:
    client = self._client
    if client is None: return

    if isinstance(payload, (dict, list)): wire_payload = json.dumps(payload)
    elif isinstance(payload, bytes): wire_payload = payload
    else: wire_payload = str(payload)
    retain = bool(data.pop('retain', False))
    qos = int(data.pop('qos', 0))
    expiry = data.pop('expiry', None)
    properties = None

    if expiry is not None or data:
      properties = Properties(PacketTypes.PUBLISH)
      if expiry is not None: properties.MessageExpiryInterval = int(expiry)
      if data: properties.UserProperty = [(key, str(value)) for key, value in data.items()]

    await client.publish(str(topic), wire_payload, qos=qos, retain=retain, properties=properties)

  @property
  def _status_topic(self) -> y2topic:
    return y2topic(self.connection.get('status_topic', ''))

  def _mqtt_client(self):
    if aiomqtt is None: raise RuntimeError('aiomqtt is required for mixin_Mqtt')
    options = {key: self.connection[key] for key in self._CLIENT_KEYS if key in self.connection}
    if self.MQTT_PROTOCOL is not None: options['protocol'] = self.MQTT_PROTOCOL
    if self._status_topic: options['will'] = aiomqtt.Will(topic=str(self._status_topic), payload=b'offline', qos=1, retain=True)
    return aiomqtt.Client(**options)

  def _mqtt_tasks(self) -> Iterable[Coroutine[Any, Any, object]]: return ()

  async def _mqtt_loop(self) -> None:
    self._ensure_mqtt_state()
    while True:
      try:
        async with self._mqtt_client() as client:
          self._client = client
          try:
            self.Info('connected:', self.connection.get('hostname'), self.connection.get('port'))
            await self._mqtt_replay(client)
            if self._status_topic: await client.publish(str(self._status_topic), 'online', qos=1, retain=True)

            async with asyncio.TaskGroup() as tasks:
              dispatch = tasks.create_task(self._mqtt_dispatch(client))
              extras = [tasks.create_task(coroutine) for coroutine in self._mqtt_tasks()]
              await dispatch
              for task in extras: task.cancel()
          finally:
            self._client = None
            if self._status_topic:
              try: await client.publish(str(self._status_topic), 'offline', qos=1, retain=True)
              except _MqttError: pass
      except _MqttError as error:
        self.Warn(f'mqtt error, reconnect in {self.MQTT_RECONNECT_DELAY}s:', error)
      except BaseExceptionGroup as group:
        # TaskGroup wraps task failures in a group; peel off MqttError, re-raise the rest.
        # (Avoid `except*` syntax: debugpy's source scanner crashes on TryStar nodes.)
        mqtt_errors, other = group.split(_MqttError)
        if mqtt_errors is not None:
          self.Warn(f'mqtt error, reconnect in {self.MQTT_RECONNECT_DELAY}s:', *mqtt_errors.exceptions)
        if other is not None: raise other
      finally:
        self._client = None

      await asyncio.sleep(self.MQTT_RECONNECT_DELAY)

  async def _mqtt_replay(self, client: Any) -> None:
    async with self._mqtt_lock: subscriptions = tuple(self._subscriptions.items())
    for topic, qos in subscriptions: await client.subscribe(str(topic), qos=qos)

  async def _mqtt_dispatch(self, client: Any) -> None:
    async for message in client.messages:
      topic = str(message.topic)
      raw = message.payload.decode(errors='replace') if isinstance(message.payload, bytes) else str(message.payload)
      payload: object = raw
      structured = raw.lstrip()
      if structured[:1] in '[{':
        try: payload = json.loads(structured)
        except json.JSONDecodeError: pass

      async with self._mqtt_lock:
        callbacks = [(callback, raise_errors) for pattern, entries in self._callbacks.items()
                     if self._topic_matches(topic, str(pattern))
                     for callback, expected, ignore_retained, raise_errors in entries
                     if not (ignore_retained and message.retain) and (expected is None or expected == payload)]

      for callback, raise_errors in callbacks:
        self._spawn(self._mqtt_callback(callback, y2topic(topic), payload, raise_errors=raise_errors))

  async def _mqtt_callback(self, callback: MqttCallback, topic: y2topic, payload: object, *, raise_errors: bool = False) -> None:
    async with self._callback_lock:
      try:
        result = callback(topic, payload)
        if inspect.isawaitable(result): await result
      except Exception as error:
        if raise_errors: raise
        self.Warn('callback error:', topic, error)

  @staticmethod
  def _topic_matches(topic: str, pattern: str) -> bool:
    if topic.startswith('$') and not pattern.startswith('$'): return False
    topic_parts = topic.split('/')
    pattern_parts = pattern.split('/')
    for index, expected in enumerate(pattern_parts):
      if expected == '#': return index == len(pattern_parts) - 1
      if index == len(topic_parts) or expected not in ('+', topic_parts[index]): return False
    return len(topic_parts) == len(pattern_parts)


# .. its start is gone
class MqttApp(mixin_Mqtt, AsyncApp):
  """AsyncApp with one reconnecting MQTT client; import from ``gppu``.

  Supply the configured broker mapping in ``data['connection']`` at construction.
  Override async ``subscribe()`` to ``await self.mqtt_listen(callback,
  topic)``; callbacks take ``(topic, payload)`` and may be sync or async.

  Run with ``asyncio.run(MyApp(data=config).run())`` and stop as for ``AsyncApp``. Keep
  ``await super().start()`` if overriding ``start()``. Subscriptions register
  before connection; for work needing a connection, have ``_mqtt_tasks()``
  return fresh coroutines for each connection. Publish with
  ``await self.mqtt_publish(topic, payload)``; disconnected publishes are discarded.
  """

  async def subscribe(self) -> None: pass

  async def start(self) -> None:
    await super().start()
    await self.subscribe()
    self._start_mqtt()


# .. gone
def _mqtt_config_topics(topics: dict[str, str]) -> dict[str, str]:
  if not isinstance(topics, dict) or not topics:
    raise ValueError('MQTT configuration requires a topic to Env path mapping')
  paths = []
  for topic, path in topics.items():
    if not isinstance(topic, str) or not topic or '+' in topic or '#' in topic:
      raise ValueError('MQTT configuration topics must be exact topic names')
    if not isinstance(path, str) or (path and any(not part for part in path.split('/'))):
      raise ValueError('MQTT configuration paths must be slash paths or empty for the root')
    if any(not path or not other or path == other or path.startswith(other + '/')
           or other.startswith(path + '/') for other in paths):
      raise ValueError('MQTT configuration paths must not overlap')
    paths.append(path)
  return dict(topics)


# .. gone
class _MqttConfig(MqttApp):
  """Read retained startup configuration, then close the temporary connection."""

  def __init__(self, config: dict):
    connection, topics = config['connection'], _mqtt_config_topics(config['topics'])
    if not isinstance(connection, dict) or not connection.get('hostname'):
      raise ValueError('MQTT configuration requires connection.hostname')
    if not Env.initialized: raise RuntimeError('load the MQTT bootstrap with Env.from_env() first')
    super().__init__(name='config-mqtt', data={'connection': connection})
    self.topics = dict(topics)
    self.pending = set(topics)

  async def subscribe(self) -> None:
    await self.mqtt_config(self.topics)

  async def _receive_config(self, topic: y2topic, payload: object) -> None:
    await super()._receive_config(topic, payload)
    self.pending.discard(str(topic))
    if not self.pending: await self.stop()

# endregion


# region - gppu/environment.py as of 2026-10-19, gone by 2026-11-20 (8)

# .. gone
def is_table_key(name: str) -> bool:   # what a table holds beside its rows: its macros, its generators, its templates and
  return name in ('macros', 'generators', 'templates') or name.endswith('_templates')   # its named templates


# .. gone
_MISSING = object()


# .. gone
def platform_name() -> str:
  """The platform vocabulary of the shared configuration, for gppu's `detect_os`: windows, wsl, debian, macos."""
  return {OSType.W11: 'windows', OSType.WSL: 'wsl', OSType.LINUX: 'debian', OSType.MACOS: 'macos'}[Env.os]


# .. gone
class _Environment:
  """The global environment and configuration registry.

  Provides system attributes (os, platform, host, user, home), strict data lookups
  via `glob`, `glob_list`, and `glob_dict`, and dynamic access to table rules and macros.
  Initialized once at startup via `from_env` or `from_dict`.
  """
  os = Env.os   # Env's, which detects them once
  platform: str = platform_name()
  host: str = socket.gethostname().split('.')[0].lower()
  user: str = Env.user
  home: Path = Env.home

  # -- loading: gppu Env underneath, State constructed on top --------------------------
  def from_env(self, name: str | None = None, app_path: Path | None = None) -> None:
    Env.from_env(name=name, app_path=app_path)
    State.load()

  def from_dict(self, d: dict) -> None:
    Env.from_dict(d)
    State.load()

  def trace(self) -> dict: return TRACE_RULES

  # -- lookups: strict, as in Y2 — a missing key raises, nothing has a default -------------
  def glob(self, path: str) -> Any:
    result = deepget(path, Env.data, default=_MISSING)
    if result is _MISSING: raise KeyError(path)
    return result

  def glob_list(self, path: str) -> list:
    result = self.glob(path)
    if not isinstance(result, list): raise TypeError(f'{path} is not a list')
    return result

  def glob_dict(self, path: str) -> dict:
    result = self.glob(path)
    if not isinstance(result, dict): raise TypeError(f'{path} is not a mapping')
    return result

  # -- rules: Environment.<table>.<rule>(...) is a macro of that table ---------------------
  def __getattr__(self, table: str):
    if table in State.templates: return _Rules(table, State.templates[table])
    raise AttributeError(f'no table named {table!r}')


# .. gone
class _Rules:
  def __init__(self, table: str, templates: TemplateSet):
    self._table, self._globals = table, templates.environment.globals

  def __getattr__(self, name: str):
    rule = self._globals.get(name)
    if not callable(rule): raise AttributeError(f'{self._table} defines no rule {name!r}')
    return rule


# .. gone
class _State:
  def __init__(self) -> None:
    self.tables: dict[str, dict[str, Any]] = {}
    self.templates: dict[str, TemplateSet] = {}
    self.services: dict[str, Any] = {}
    self.kinds: dict[str, type] = {}

  def register(self, **kinds: type) -> None:
    """The classes a template's `kind` may name."""
    self.kinds.update(kinds)

  def reset(self) -> None:
    for table in self.tables: delattr(self, table)
    self.tables, self.templates, self.services = {}, {}, {}

  def rows(self, table: str) -> dict[str, dict]:
    """The rows of a table: every mapping under its key that is not macros, generators or templates."""
    return {uid: row for uid, row in Env.glob_dict(table).items() if not is_table_key(uid) and isinstance(row, dict)}

  def load(self) -> None:
    """Construct every table of the loaded configuration."""
    self.reset()
    names = [name for name, content in Env.data.items() if isinstance(content, dict) and 'templates' in content]
    rows = {name: self.rows(name) for name in names}   # what a macro sees under a table's name: its rows, resolved
    for name in names:                                  # once the table is, so a table resolved later sees what an
      if hasattr(self, name): raise ValueError(f'{name}: a table cannot be named after a State member')   # earlier one computed
      templates = Env.template_set(name, Environment=Environment, State=self, **rows)
      resolved = {uid: templates.resolve({'uid': uid, **row}) for uid, row in rows[name].items()}
      rows[name].clear(); rows[name].update(resolved)
      table = {}
      for uid, data in resolved.items():
        obj = self.kinds.get(data.get('kind'), _DC)(data=data)   # the app that cares registers the class
        table[uid] = obj
        if data.get('service'): self.services[uid] = obj
      self.tables[name], self.templates[name] = table, templates
      setattr(self, name, table)


# .. gone
Environment = _Environment()


# .. gone
State = _State()

# endregion


# .. Part 3 is what gppu work took out of, or rewrote in, programs of other repositories from 2026-11-21 to 2026-11-24:
# .. RAN outside Hosts (ccba13044, 2026-11-20 13:59), CRAP (334ddfdb, 2026-11-14, the last one before) and IoT's neo-mqtt
# .. (0478592c), each compared with how it is now. Marks are as above, for the same file. Lines of YAML and shell files,
# .. and import lines, are comments. Not here: Hosts, documents, files moved whole, and what was only added.
# .. Credentials are withheld, because gppu is public; they are in the private repositories.
# ..
# .. What was found on 2026-11-24. The edits stand in RAN, CRAP and IoT, and are pushed.
# ..   Called archived or not used by Alex, and edited: CRAP file_indexer and ticktick-export, IoT neo-mqtt, and the
# ..     Linked Data API (RAN Systems/ld), which has no container on five and answers 502.
# ..   No container, schedule or launcher that runs it was found: RAN Services/Kuma's CCTV scripts (CCTV-detective is down
# ..     and its site answers 502) and CRAP plaud.standalone. CRAP FileIndexer is replaced by RAN Systems/ld/fileindexer.
# ..     craptui cannot start: three files its configuration includes are not there. setup-ld-monitors sets up the
# ..     monitors of the Linked Data API.
# ..   Run by hand or not at all, not known: RAN eMail-triage, md-indexer, openapi_query, YuE2 (its two Mac jobs point at
# ..     Systems/YuE2, which is not there), linkml; CRAP Transcriber's recordings/cli.py.
# ..   In use, and edited: RAN's configuration (config.yaml, hosts.yaml, topology/locations.yaml), the Lake, Session
# ..     Manager, the devops and coverage skills, Dagster's compose file; CRAP's admin UI.
# ..   RAN settings files moved from their programs to _config, config.yaml now loading them: yue2, sessionmanager,
# ..     projectmanager, gppufs, coverage, eMail-triage, sync_to_operon, operon_remove; and file_indexer, already there.
# ..   Env.from_env, Env.from_dict, CliApp, APP and resolve_secret were gone from gppu by 2026-11-20, so the calls of them
# ..     were broken before. Still calling Env.from_env now: CRAP Transcriber, plaud.standalone, craptui's inventory
# ..     (tenant_config.py), file_indexer's extract_archives.py; RAN md-indexer.
# ..   Broken by gppu since 2026-11-20: RAN Systems/static_sites/start-page.py (load_sidecar_registry), which no one edited;
# ..     CRAP Cruft/needs_triage/omi/raw.py (Container, DataObject, FileSystem) and FileIndexer's test_indexer.py (TimeSpan).
# ..   Archive folders: no file archived before 2026-11-21 changed in gppu, RAN, CRAP, IoT or y2. Y2's tests/test_sensibo.py
# ..     had entity.pod_id, and reads entity.uid in the archive. IoT PCC/archive/obsolete lost install.ps1, rewritten into
# ..     PCC/src, and install.sh, deleted, 37 minutes after both were archived.


# region - RAN AI/skills/md-indexer/md_indexer/app.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN AI/skills/md-indexer/md_indexer/app.py
def bootstrap() -> None:
  Env.from_env(name="md-indexer", app_path=APP_DIR)
  init_logger("md-indexer")

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, init_logger

# endregion


# region - RAN AI/skills/md-indexer/md_indexer/config.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN AI/skills/md-indexer/md_indexer/config.py
def llm_params() -> dict:
  d = _section("llm")
  return {
    "endpoint": str(_req(d, "endpoint", "llm")),
    "model": str(_req(d, "model", "llm")),
    "api_key": resolve_secret(str(_req(d, "api_key_secret", "llm"))),
    "temperature": float(_req(d, "temperature", "llm")),
    "max_tokens": int(_req(d, "max_tokens", "llm")),
    "timeout": int(_req(d, "timeout", "llm")),
  }

# .. imports, comments and docstring text that read differently now
#    "no hardcoded config / no fallbacks"). The LiteLLM API key is resolved via gppu
#    ``resolve_secret`` (env -> vault -> config); only its secret *name* lives in the
#    config file.
#    from gppu import Env, resolve_secret

# endregion


# region - RAN AI/skills/md-indexer/md_indexer/llm.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    The endpoint and model are config; the API key is resolved via gppu
#    ``resolve_secret`` by the app layer (no hardcoded key here, per AGENTS.md).

# endregion


# region - RAN Projects/YuE2/album.py as of 2026-11-20 (2)

# .. changed; the one of now is in RAN Projects/YuE2/album.py
class Album(CliApp):
    def main(self, manifest: Path, work_root: Path, output_root: Path, models_file: Path,
             transcriber_python: Path, transcriber_model: Path,
             transcriber_revision: str, base_model: Path, skill_scripts: Path,
             lock_file: Path, device: str, source_cover: Path) -> dict:
        """Resume verified stages, generate missing recordings and update the player."""
        from yue2.cli import request_kwargs
        from yue2.pipeline import YuE2Pipeline
        from yue2.protocol import SongRequest, CONTEXT, token_prefixes
        from yue2.storage import verify_result, identity
        from yue2.tokenization_yue2 import YuE2TextTokenizer

        sys.path.insert(0, str(skill_scripts))
        from instrumentalize import convert_score
        from instrumental import validate_request
        from abc_tools import parse_abc

        album = json.loads(manifest.read_text())
        models = json.loads(models_file.read_text())
        output_root.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_cover, output_root / 'cover.jpg')
        write_json(output_root / 'album.json', album)
        tokenizer = YuE2TextTokenizer(Path(models['YuE2-3B']['path']) / 'qwen.tiktoken')
        entries = []
        for track in album['tracks']:
            entries.append(dict(id=track['id'], title=track['title'], collection='Album', source=track))
            if 'retakes' in track:
                for retake in track['retakes']:
                    request = json.loads(Path(retake['request']).read_text())
                    entries.append(dict(id=request['id'], title=retake['title'], collection='Album',
                        source=track, retake_request=request))
            for arrangement in track['instrumental_arrangements']:
                identifier = arrangement['render_id'] if 'render_id' in arrangement else f"{track['id']}-instrumental-{arrangement['variant']}"
                entries.append(dict(id=identifier,
                    title=arrangement['title'], collection=f"Instrumentals {arrangement['variant']}",
                    source=track, arrangement=arrangement))
        self.entries = entries
        self.output_root = output_root
        self.write_player(album['title'])
        active = 'preparing'
        with lock_file.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                for track in album['tracks']:
                    active = track['id'] + ': transcription'
                    write_json(output_root / 'status.json', dict(state='transcribing', current=track['title']))
                    transcription = work_root / 'transcription' / track['id']
                    if not (transcription / 'transcription_manifest.json').exists():
                        self.Info(active)
                        subprocess.run([str(transcriber_python), str(skill_scripts / 'transcribe_cover.py'),
                            track['source_audio'], '--output', str(transcription), '--task', 'full',
                            '--model', str(transcriber_model), '--revision', transcriber_revision,
                            '--base-model', str(base_model), '--offline', '--device', device, '--dtype', 'fp32'],
                            env=environment(transcriber_python), check=True)
                    report = json.loads((transcription / 'result.json').read_text())
                    if report['abc_error']:
                        raise ValueError(report['abc_error'])
                    self.Info(f"{track['title']}: transcription warnings {report['warnings']}")
                    source_abc = (transcription / 'score.abc').read_text()
                    source_bpm = parse_abc(source_abc).bpm
                    converted, transfer = convert_score(source_abc, keep_chords=False)
                    for entry in [e for e in entries if e['source']['id'] == track['id']]:
                        request = dict(id=entry['id'], style=track['style'], lyrics=track['lyrics'],
                            abc=source_abc, cot='full', seed=831001)
                        if 'retake_request' in entry:
                            request = entry['retake_request'].copy()
                        if 'arrangement' in entry:
                            arrangement = entry['arrangement']
                            abc = converted
                            tempos = re.findall(r'(\d+)\s*BPM', arrangement['styles'], re.I)
                            if len(tempos) > 1:
                                raise ValueError(f"Ambiguous arrangement tempo: {entry['title']}")
                            style = arrangement['styles'].replace('the attached original', 'the provided score')
                            if tempos:
                                groove_bpm = int(tempos[0])
                                # The briefs retain the source duration. Interpret half/double-time
                                # pulse at the metrical level closest to the source quarter-note tempo.
                                octave = round(math.log2(source_bpm / groove_bpm))
                                score_bpm = round(groove_bpm * 2 ** octave)
                                abc = re.sub(r'^Q:1/4=\d+$', f'Q:1/4={score_bpm}', abc, flags=re.M)
                                if octave:
                                    style += f' The {groove_bpm} BPM groove is a metrical pulse over a {score_bpm} BPM quarter-note score; retain the source phrase lengths.'
                            before = parse_abc(abc)
                            lines = [line for line in abc.splitlines() if not line.startswith('% ')]
                            key_line = next(i for i, line in enumerate(lines) if line.startswith('K:'))
                            lines.insert(key_line + 1, '% instrumental')
                            abc = '\n'.join(lines) + '\n'
                            after = parse_abc(abc)
                            for voice in ('Vocal', 'Ins'):
                                if before.voices[voice].notes != after.voices[voice].notes or before.voices[voice].bars != after.voices[voice].bars:
                                    raise ValueError('Instrumental section cues changed musical events')
                            style += ' No vocals, no singing, no spoken words, no humming, no choir.'
                            request.update(style=style, lyrics='[Instrumental]\n', abc=abc, cot='melody')
                            validate_request(request)
                            record = dict(transfer, arrangement_bpm=parse_abc(abc).bpm,
                                tempo_source='existing arrangement brief' if tempos else 'source transcription',
                                section_cues='instrumental', note_events_preserved_after_section_cues=True)
                            if tempos:
                                record.update(groove_bpm=groove_bpm, metrical_octave=octave,
                                    tempo_basis='Source duration retained by the nearest half/double-time metrical interpretation.')
                            write_json(work_root / 'prepared' / entry['id'] / 'transfer.json', record)
                        # The model's context is the declared upper bound. Long scores must not
                        # silently hit the six-minute default. No song is deliberately cropped.
                        prepared_score = parse_abc(request['abc'])
                        seconds = float(prepared_score.voices['Ins'].time * 60 / prepared_score.bpm)
                        prefix = token_prefixes(SongRequest(**request), tokenizer)
                        if seconds * 25 >= CONTEXT - len(prefix):
                            raise ValueError(f"Score duration exceeds the model context: {entry['title']}")
                        if seconds * 25 >= 9000:
                            request['semantic_sampling'] = {'max_tokens': CONTEXT - len(prefix)}
                        entry['request'] = request
                        entry['nominal_seconds'] = seconds
                        write_json(work_root / 'prepared' / entry['id'] / 'request.json', request)

                with YuE2Pipeline.from_pretrained(models['YuE2-3B']['path'], vae=models['YuE2-Vae']['path'],
                        device=device, local_files_only=True) as pipe:
                    for entry in entries:
                        active = entry['id']
                        request = entry['request']
                        kwargs = request_kwargs(request)
                        song_request = pipe._request(**{k: v for k, v in kwargs.items() if k != 'semantic_sampling'})
                        config = pipe.effective_config(song_request, semantic_sampling=kwargs.get('semantic_sampling'))
                        expected = identity(dict(request=song_request.to_dict(), config=config, weights=pipe.weights))
                        destination = output_root / 'recordings' / entry['id']
                        if (destination / 'result.json').exists():
                            verify_result(destination, expected)
                        else:
                            self.Info(f"Generating {entry['title']}")
                            write_json(output_root / 'status.json', dict(state='generating', current=entry['title']))
                            render(pipe, song_request, destination, kwargs.get('semantic_sampling'))
                        result = verify_result(destination, expected)
                        write_text(destination / 'prompt.txt', song_request.text() + '\n[Provided ABC]\n' + song_request.abc)
                        if any(result['truncated'].values()):
                            raise ValueError(f"Generation reached its limit: {entry['title']}")
                        self.verify_audio(destination)
                        if not (destination / 'audio.mp3').exists():
                            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-n',
                                '-i', str(destination / 'audio.flac'), '-codec:a', 'libmp3lame', '-q:a', '2',
                                '-metadata', 'album=' + album['title'] + ' — YuE-2',
                                '-metadata', 'title=' + entry['title'], '-metadata', 'artist=Karelin',
                                str(destination / 'audio.mp3')], check=True)
                        if not (destination / 'lyric-check.json').exists():
                            self.Info(f"Checking recognized words: {entry['title']}")
                            check = CheckLyrics().invoke(audio=destination / 'audio.flac',
                                output=destination / 'lyric-check.json',
                                language='russian' if re.search('[А-Яа-яЁё]', entry['source']['lyrics']) else 'english')
                            words = re.sub(r'<\|[^|]*\|>', '', check['transcript']).strip()
                            if 'arrangement' in entry and re.search(r'[A-Za-zА-Яа-яЁё]', words):
                                write_json(destination / 'review.json', dict(state='speech-recognition-review-needed',
                                    evidence='The recognizer produced text over this instrumental; this may be vocal leakage or an ASR hallucination. See lyric-check.json.',
                                    artistic_audition=False))
                        if not (destination / 'audio-events.json').exists():
                            CheckEvents().invoke(audio=destination / 'audio.flac',
                                output=destination / 'audio-events.json')
                        self.write_player(album['title'])
                        self.Info(f"{entry['title']}: audio verified, {result['audio_seconds']:.2f} seconds")
                write_json(output_root / 'status.json', dict(state='generated', technical_verification='passed',
                    artistic_audition=False, vocal_absence_audition=False))
            except BaseException as exc:
                write_json(output_root / 'status.json', dict(state='failed', current=active,
                    error_type=type(exc).__name__, error=str(exc)))
                raise
        return dict(album=str(output_root / 'index.html'), state='generated', artistic_audition=False)

    def verify_audio(self, directory):
        import numpy as np
        import soundfile as sf
        audio, rate = sf.read(directory / 'audio.flac', always_2d=True)
        if rate != 48000 or audio.shape[1] != 2 or not len(audio) or not np.isfinite(audio).all():
            raise ValueError(f'Invalid audio: {directory}')
        peak = float(np.max(np.abs(audio)))
        if peak == 0:
            raise ValueError(f'Silent audio: {directory}')
        write_json(directory / 'technical-check.json', dict(sample_rate=rate, channels=2,
            seconds=len(audio)/rate, peak=peak, rms=float(np.sqrt(np.mean(audio*audio))),
            finite=True, non_silent=True, artistic_audition=False, vocal_absence_audition=False))

    def write_player(self, title):
        shutil.copyfile(Path(__file__).with_name('player.js'), self.output_root / 'player.js')
        groups = {}
        for entry in self.entries:
            groups.setdefault(entry['collection'], []).append(entry)
        cards = []
        for collection, entries in groups.items():
            cards.append('<h2>' + html.escape(collection) + '</h2>')
            for entry in entries:
                directory = self.output_root / 'recordings' / entry['id']
                url = 'recordings/' + entry['id']
                body = '<p class="pending">Generation pending</p>'
                if (directory / 'result.json').exists():
                    receipt = json.loads((directory / 'result.json').read_text())
                    body = f'<audio controls preload="none" src="{url}/audio.flac"></audio>'
                    body += f'<p>{receipt["audio_seconds"]:.1f} seconds · <a href="{url}/audio.flac">FLAC</a>'
                    if (directory / 'audio.mp3').exists():
                        body += f' · <a href="{url}/audio.mp3">MP3</a>'
                    body += f' · <a href="{url}/score.abc">Score</a> · <a href="{url}/request.json">Exact request</a>'
                    if (directory / 'prompt.txt').exists():
                        body += f' · <a href="{url}/prompt.txt">Full prompt</a>'
                    body += '</p>'
                    if (directory / 'review.json').exists():
                        review = json.loads((directory / 'review.json').read_text())
                        body += '<p>' + html.escape(review['state']) + ': ' + html.escape(review['evidence']) + '</p>'
                cards.append('<article id="' + html.escape(entry['id'], quote=True) + '"><h3>' + html.escape(entry['title']) + '</h3>' + body + '</article>')
        content = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Neuralese, please! — YuE-2</title><style>body{background:#14151c;color:#f2eee7;font:17px/1.6 system-ui;max-width:1000px;margin:40px auto;padding:0 24px}header{display:flex;gap:28px;align-items:center}img{width:180px;border-radius:12px}h1{font-size:38px;line-height:1.15}h2{margin-top:48px;border-bottom:1px solid #4d4a60}article{padding:16px 0;border-bottom:1px solid #333342}h3{margin:0 0 12px}audio{width:100%}a{color:#dab5ff}.pending,small{color:#aaa6b6}</style>
<header><img src="cover.jpg" alt="Album cover"><div><h1>Neuralese, please!</h1><p>YuE-2 · Generated locally on the Mac</p><small>Original songs and instrumental reimaginings</small></div></header>
<p id="status">Loading generation status…</p>
<p>Recordings appear as they finish. Technical checks and musical listening are separate; these recordings have not yet been artistically auditioned.</p>'''
        write_text(self.output_root / 'index.html', content + '\n'.join(cards) + '\n<script src="player.js"></script></html>')


# .. gone
if __name__ == '__main__':
    Album.cli()

# .. imports, comments and docstring text that read differently now
#    from gppu import CliApp

# endregion


# region - RAN Projects/YuE2/check_events.py as of 2026-11-20 (2)

# .. changed; the one of now is in RAN Projects/YuE2/check_events.py
class CheckEvents(CliApp):
    def main(self, audio: Path, model_file: Path, output: Path, threads: int,
             window_seconds: float) -> dict:
        """Classify every ten-second window with the AudioSet-trained model."""
        torch.set_num_threads(threads)
        info = json.loads(model_file.read_text())
        processor = AutoFeatureExtractor.from_pretrained(info['path'], local_files_only=True)
        model = ASTForAudioClassification.from_pretrained(info['path'], local_files_only=True).eval()
        rate = processor.sampling_rate
        raw = subprocess.check_output(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(audio),
            '-ac', '1', '-ar', str(rate), '-f', 'f32le', '-'])
        waveform = np.frombuffer(raw, dtype='<f4').copy()
        size = int(rate * window_seconds)
        windows = []
        for offset in range(0, len(waveform), size):
            inputs = processor(waveform[offset:offset+size], sampling_rate=rate, return_tensors='pt')
            with torch.inference_mode():
                probabilities = model(**inputs).logits[0].sigmoid().tolist()
            scores = {model.config.id2label[i]: value for i, value in enumerate(probabilities)}
            windows.append(dict(start_seconds=offset/rate,
                end_seconds=min(offset+size, len(waveform))/rate, scores=scores))
        result = dict(model=info, audio=str(audio), window_seconds=window_seconds, windows=windows,
            artistic_audition=False,
            scope='Independent audio-event estimates; neither a vocal-absence guarantee nor a listening judgment.')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        return dict(output=str(output), state='classified', artistic_audition=False)


# .. gone
if __name__ == '__main__':
    CheckEvents.cli()

# .. imports, comments and docstring text that read differently now
#    from gppu import CliApp

# endregion


# region - RAN Projects/YuE2/check_lyrics.py as of 2026-11-20 (2)

# .. changed; the one of now is in RAN Projects/YuE2/check_lyrics.py
class CheckLyrics(CliApp):
    def main(self, audio: Path, model_file: Path, output: Path, language: str, threads: int) -> dict:
        """Transcribe the complete recording for lyric and vocal-leakage review."""
        torch.set_num_threads(threads)
        model_info = json.loads(model_file.read_text())
        model = AutoModelForSpeechSeq2Seq.from_pretrained(model_info['path'], dtype=torch.float32,
            low_cpu_mem_usage=True, use_safetensors=True, local_files_only=True).eval()
        processor = AutoProcessor.from_pretrained(model_info['path'], local_files_only=True)
        rate = processor.feature_extractor.sampling_rate
        raw = subprocess.check_output(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(audio),
            '-ac', '1', '-ar', str(rate), '-f', 'f32le', '-'])
        waveform = np.frombuffer(raw, dtype='<f4').copy()
        inputs = processor(waveform, sampling_rate=rate, return_tensors='pt',
            truncation=False, padding='longest', return_attention_mask=True)
        generation = dict(language=language, task='transcribe', return_timestamps=True,
            condition_on_prev_tokens=False, temperature=0.0, no_speech_threshold=0.6,
            logprob_threshold=-1.0, compression_ratio_threshold=1.35)
        with torch.inference_mode():
            tokens = model.generate(**inputs, **generation)
        text = processor.batch_decode(tokens, skip_special_tokens=True, decode_with_timestamps=True)[0]
        result = dict(model=model_info, audio=str(audio), audio_seconds=len(waveform)/rate,
            device='cpu', generation=generation, transcript=text, artistic_audition=False,
            scope='Speech recognition can miss singing or hallucinate words over instruments; review flagged text.')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        return result


# .. gone
if __name__ == '__main__':
    CheckLyrics.cli()

# .. imports, comments and docstring text that read differently now
#    from gppu import CliApp

# endregion


# region - RAN Projects/YuE2/generate.py as of 2026-11-20 (2)

# .. changed; the one of now is in RAN Projects/YuE2/generate.py
class Generate(CliApp):
    def main(self, request: Path, output_root: Path, runtime: Path, models_file: Path,
             lock_file: Path, device: str) -> dict:
        """Generate a new take; retain its exact request, score and audio."""
        models = json.loads(models_file.read_text())
        data = json.loads(request.read_text())
        output = output_root / datetime.now(ZoneInfo('America/Los_Angeles')).strftime('%y%m%d-%H%M%S')
        env = os.environ.copy()
        env['VIRTUAL_ENV'] = str(runtime.parent.parent)
        env['PATH'] = str(runtime.parent) + os.pathsep + os.environ['PATH']
        with lock_file.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.Info(f"YuE-2: generating {data['id']} on {device}")
            subprocess.run([
                str(runtime), 'generate', '--request', str(request.resolve()),
                '--output', str(output), '--device', device, '--offline',
                '--model', models['YuE2-3B']['path'], '--vae', models['YuE2-Vae']['path'],
            ], check=True, env=env)
        result_dir = output / data['id']
        result = json.loads((result_dir / 'result.json').read_text())
        return {'audio': str(result_dir / 'audio.flac'), 'score': str(result_dir / 'score.abc'),
                'duration_seconds': result['audio_seconds'], 'truncated': result['truncated']}


# .. gone
if __name__ == '__main__':
    Generate.cli()

# .. imports, comments and docstring text that read differently now
#    from gppu import CliApp

# endregion


# region - RAN Projects/YuE2/serve.py as of 2026-11-20 (2)

# .. changed; the one of now is in RAN Projects/YuE2/serve.py
class Serve(CliApp):
    def main(self, directory: Path, host: str, port: int):
        """Keep the album player available while rendering continues."""
        handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
        with ThreadingHTTPServer((host, port), handler) as server:
            self.Info(f'YuE-2 library: http://{host}:{port}')
            server.serve_forever()


# .. gone
if __name__ == '__main__':
    Serve.cli()

# .. imports, comments and docstring text that read differently now
#    from gppu import CliApp

# endregion


# region - RAN Projects/linkml/dagster_linkml/reader.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import DataObject

# endregion


# region - RAN Projects/linkml/dagster_linkml/runtime.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import Container, FileSystem, jinja

# endregion


# region - RAN Scripts/eMail-triage/common.py as of 2026-11-20 (2)

# .. gone
Env.from_env(name="", app_path=HERE)


# .. changed
CONFIG = glob_dict("")

# .. imports, comments and docstring text that read differently now
#    from gppu import Env

# endregion


# region - RAN Scripts/eMail-triage/gmail_triage.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Scripts/eMail-triage/gmail_triage.py
def main(argv):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("command", nargs="?", default="autotriage")
  parser.add_argument("args", nargs="*")
  parser.add_argument("-A", "--account", choices=list(ACCOUNTS), default=CONFIG["account"])
  mode = parser.add_mutually_exclusive_group()
  mode.add_argument("--dry-run", dest="dry_run", action="store_true")
  mode.add_argument("--apply", dest="dry_run", action="store_false")
  parser.set_defaults(dry_run=CONFIG["dry_run"])
  parser.add_argument("--max-moves", type=int, default=CONFIG["max_moves"])
  parser.add_argument("--cap", type=float, default=CONFIG["max_move_fraction"])
  parser.add_argument("--from", dest="source", choices=list(ACCOUNTS))
  parser.add_argument("--to", dest="target", choices=list(ACCOUNTS))
  parser.add_argument("--dest-id")
  parser.add_argument("--source-action", choices=["archive", "trash", "keep"], default=CONFIG["source_action"])
  args = parser.parse_args(argv[1:])
  cmd, account = args.command, args.account
  if CONFIG["approval_required"] and (cmd == "move" or (cmd in ("autotriage", "apply", "transfer") and not args.dry_run)):
    parser.error("Filing requires individual approval in the Email Triage dashboard")
  if cmd == "accounts":
    print(json.dumps({key: {"provider": value["provider"], "mailbox": value["mailbox"]}
                      for key, value in ACCOUNTS.items()}, ensure_ascii=False, indent=2))
  elif cmd in ("autotriage", "apply"):
    report = autotriage(build_ctx(account), account, args.dry_run, args.max_moves, args.cap, args.source_action)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.dry_run and (report["errors"] or not report["cap_ok"]):
      raise SystemExit(1)
  elif cmd in ("genrules", "generate", "import-filters"):
    die("sender-based rule generation and filter import are disabled; content rules belong in config.yaml")
  elif cmd == "transfer":
    if not args.source or not args.target or len(args.args) != 1:
      die("transfer requires --from <acct> --to <acct> <srcId>")
    if args.source == args.target:
      die("--from and --to are the same mailbox; use move")
    result = transfer(build_ctx(args.source), build_ctx(args.target), args.args[0],
                      args.dest_id, args.source_action, args.dry_run)
    print(json.dumps(result, ensure_ascii=False))
  else:
    if cmd not in ("labels", "folders", "inbox", "inbox-full", "get", "move", "count"):
      die(f"unknown command: {cmd}")
    run(build_ctx(account), cmd, args.args)

# .. imports, comments and docstring text that read differently now
#    """Multi-mailbox content triage, configured through config.yaml and gppu.

# endregion


# region - RAN Scripts/eMail-triage/outlook_worker.py as of 2026-11-20 (2)

# .. changed; the one of now is in RAN Scripts/eMail-triage/outlook_worker.py
class OutlookWorker(CliApp):
    def main(self, install_credential: bool = False, collect_only: bool = False) -> dict:
        """Publish Outlook triage and execute only individually approved moves.

        Args:
            install_credential: Store an existing Site token from the hidden console prompt.
            collect_only: Collect proposals without executing approved moves.
        """
        if install_credential:
            import win32cred
            token = getpass.getpass("Existing Site service token (hidden): ").strip()
            if not token:
                raise ValueError("No service credential supplied")
            win32cred.CredWrite({"Type": win32cred.CRED_TYPE_GENERIC, "TargetName": CREDENTIAL,
                                "UserName": "Sites", "CredentialBlob": token, "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE}, 0)
            return {"credential_stored": True}
        with single_instance() as acquired:
            if not acquired:
                return {"already_running": True}
            return run(collect_only)


# .. gone
if __name__ == "__main__":
    OutlookWorker.cli()

# .. imports, comments and docstring text that read differently now
#    from gppu import CliApp, Info

# endregion


# region - RAN Scripts/eMail-triage/ruler.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Scripts/eMail-triage/ruler.py
@cache
def load():
  rules = CONFIG["rules"]
  if not isinstance(rules, list):
    raise ValueError("config.yaml rules must be a list")
  nlp = spacy.blank("en")
  ruler = nlp.add_pipe("span_ruler", config={"validate": True, "phrase_matcher_attr": "LOWER"})
  ids, patterns = set(), []
  for rule in rules:
    rid, dest, required, entities = (rule[key] for key in ("id", "dest", "requires", "entities"))
    if not isinstance(rid, str) or not rid.strip() or rid in ids:
      raise ValueError("each rule needs a unique, nonempty id")
    ids.add(rid)
    if not isinstance(dest, str) or not dest.strip():
      raise ValueError(f"{rid}: dest must be a nonempty string")
    if not isinstance(required, list) or not required or any(not isinstance(label, str) or not label for label in required):
      raise ValueError(f"{rid}: requires must be a nonempty list of labels")
    if not isinstance(entities, dict) or not set(required) <= entities.keys():
      raise ValueError(f"{rid}: each required label needs patterns in this rule")
    for label, alternatives in entities.items():
      if not isinstance(label, str) or not label or not isinstance(alternatives, list) or not alternatives:
        raise ValueError(f"{rid}: each entity needs a label and patterns")
      for pattern in alternatives:
        if not isinstance(pattern, (str, list)) or not pattern:
          raise ValueError(f"{rid}/{label}: patterns must be nonempty phrases or token lists")
        patterns.append({"id": rid, "label": label, "pattern": pattern})
  if patterns:
    ruler.add_patterns(patterns)
  return nlp, rules

# .. imports, comments and docstring text that read differently now
#    """Content-only spaCy rules from config.yaml; first complete rule wins.

# endregion


# region - RAN Scripts/eMail-triage/test_approval.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Scripts/eMail-triage/test_approval.py
class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OutlookTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.adapter = self.fixture.adapter
        self.adapter.allow_moves = True
        self.adapter.session.GetFolderFromID = lambda mid, sid: self.fixture.source if (mid, sid) == (self.fixture.source.EntryID, self.fixture.source.StoreID) else self.fixture.get_folder(mid, sid)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = Journal(Path(self.temp.name) / "journal.sqlite")
        self.addCleanup(self.journal.db.close)
        self.message = self.adapter.summary(self.fixture.mail[(self.fixture.source.StoreID, "match")], True)
        source = self.adapter.describe(self.fixture.source)
        target = folder_record("test", self.adapter.describe(self.fixture.filed))
        report = {"kept": [], "moved_plan": [], "errors": []}
        data = proposals("test", "gmail", source, [self.message], report, [target])[0]
        data["destination"] = target
        self.row = {"id": data["id"], "account": "gmail", "data": data}
        self.requests = []

    def cloud(self, path, data):
        self.requests.append((path, data))
        if path == "claim":
            return {**self.row, "state": "executing", "approved_by": "human", "claim_token": data["token"]}
        return {"ok": True}

    def test_automatic_apply_is_blocked(self):
        with patch.dict(common.CONFIG, {"approval_required": True}):
            with self.assertRaises(PermissionError):
                triage_messages([], "gmail", None, None, False, 1, 0.75)

    def test_worker_cli_binds_read_only_option_without_outlook(self):
        with patch.object(worker, "single_instance", return_value=contextlib.nullcontext(True)), patch.object(worker, "run", return_value={"ok": True}) as run, contextlib.redirect_stdout(io.StringIO()):
            result = worker.OutlookWorker.cli(["--collect-only"])
        run.assert_called_once_with(True)
        self.assertTrue(result["ok"])

    def test_missing_human_approval_never_moves(self):
        def unapproved(path, data):
            return {**self.row, "state": "executing", "approved_by": None, "claim_token": data["token"]}
        with patch.object(worker, "request", side_effect=unapproved), self.assertRaises(PermissionError):
            worker.execute(self.adapter, self.row, self.journal)
        self.assertEqual(self.fixture.calls, [])

    def test_changed_body_expires_approval(self):
        self.fixture.mail[(self.fixture.source.StoreID, "match")].Body = "changed"
        with patch.object(worker, "request", side_effect=self.cloud):
            worker.execute(self.adapter, self.row, self.journal)
        self.assertEqual(self.fixture.calls, [])
        self.assertEqual(self.requests[-1][1]["state"], "stale")

    def test_expired_claim_does_not_block_future_scans(self):
        expired = urllib.error.HTTPError("https://fixture.invalid", 409, "approval expired", {}, None)
        with patch.object(worker, "request", side_effect=expired):
            worker.execute(self.adapter, self.row, self.journal)
        self.assertEqual(self.fixture.calls, [])
        self.assertEqual(self.journal.pending(), [])

    def test_approved_move_executes_once_and_records_new_id(self):
        with patch.object(worker, "request", side_effect=self.cloud):
            worker.execute(self.adapter, self.row, self.journal)
            worker.execute(self.adapter, self.row, self.journal)
        self.assertEqual(len(self.fixture.calls), 1)
        self.assertEqual(self.requests[-1][1]["state"], "completed")
        self.assertTrue(self.requests[-1][1]["result"]["new_id"])

    def test_interrupted_move_is_not_retried(self):
        self.journal.prepare(self.row["id"])
        self.journal.state(self.row["id"], "executing")
        with patch.object(worker, "request", side_effect=self.cloud):
            worker.execute(self.adapter, self.row, self.journal)
        self.assertEqual(self.fixture.calls, [])
        self.assertEqual(self.requests[-1][1]["state"], "uncertain")

    def test_lost_ack_replays_result_without_move(self):
        def lost_ack(path, data):
            if path == "result":
                raise TimeoutError("response lost")
            return self.cloud(path, data)
        with patch.object(worker, "request", side_effect=lost_ack), self.assertRaises(TimeoutError):
            worker.execute(self.adapter, self.row, self.journal)
        with patch.object(worker, "request", side_effect=self.cloud):
            worker.execute(self.adapter, self.row, self.journal)
        self.assertEqual(len(self.fixture.calls), 1)
        self.assertEqual(self.journal.pending(), [])

    def test_recovered_claim_uses_server_account(self):
        self.journal.prepare(self.row["id"])
        self.journal.state(self.row["id"], "claimed")
        with patch.object(worker, "request", side_effect=self.cloud):
            worker.execute(self.adapter, {"id": self.row["id"]}, self.journal)
        self.assertEqual(self.requests[-1][1]["state"], "completed")

    def test_message_version_changes_proposal_identity(self):
        self.assertNotEqual(digest(self.message), digest({**self.message, "unread": False}))

    def test_offline_store_does_not_prevent_inbox_reporting(self):
        def offline(index):
            raise RuntimeError("Exchange unavailable")
        self.adapter.session.Stores = SimpleNamespace(Count=1, Item=offline)
        with patch.object(self.adapter, "messages", return_value=[]), patch.object(worker, "request", return_value={}) as cloud:
            report = worker.collect(self.adapter)
        self.assertEqual(report["scanned_accounts"], list(common.ACCOUNTS))
        final = cloud.call_args.args[1]
        self.assertIn("Exchange unavailable", final["report"]["errors"][0])

    def test_unavailable_child_does_not_hide_other_folders(self):
        root = self.fixture.roots[0]
        bad = fixtures.folder("Unavailable", self.fixture.stores["gmail"], root)
        good = fixtures.folder("Accessible", self.fixture.stores["gmail"], root)
        original = self.adapter.describe
        def describe(folder):
            if folder.EntryID == bad.EntryID:
                raise RuntimeError("folder offline")
            return original(folder)
        self.adapter.session.Stores = SimpleNamespace(Count=0)
        with patch.object(self.adapter, "messages", return_value=[]), patch.object(self.adapter, "describe", side_effect=describe), patch.object(worker, "request", return_value={}) as cloud:
            worker.collect(self.adapter)
        published = [folder for call in cloud.call_args_list if call.args[0] == "batch" for folder in call.args[1]["folders"]]
        self.assertIn(good.EntryID, [folder["id"] for folder in published])

# endregion


# region - RAN Scripts/openapi_query.py as of 2026-11-20 (2)

# .. changed; the one of now is in RAN Scripts/openapi_query.py
def main(url: str = BASE_URL, spec: str = "openapi.json", operation: str = "",
         params: str = "{}", headers: str = "{}", body: str = "", describe: bool = False):
    """Discover operations, describe one, or execute it with JSON parameters."""
    # No client-side time limit or implicit paging limit.
    with httpx.Client(headers=json.loads(headers), timeout=None) as client:
        response = client.get(url.rstrip("/") + "/" + spec.lstrip("/"))
        response.raise_for_status()
        document = response.json()
        if not document["openapi"].startswith("3."):
            raise ValueError("This script requires an OpenAPI 3 JSON description")
        operations = []
        for path, item in document["paths"].items():
            item = resolve(document, item)
            for method, definition in item.items():
                if method in METHODS:
                    operations.append((path, method, definition, item))
        if not operation:
            return [{"operation": definition.get("operationId"),
                     "request": f"{method.upper()} {path}",
                     "description": definition.get("description", "")}
                    for path, method, definition, _ in operations]
        matches = [entry for entry in operations
                   if operation in (entry[2].get("operationId"), f"{entry[1].upper()} {entry[0]}")]
        if len(matches) != 1:
            raise ValueError(f"Expected one OpenAPI operation matching {operation!r}; found {len(matches)}")
        path, method, definition, item = matches[0]
        parameters = {}
        for parameter in item.get("parameters", []) + definition.get("parameters", []):
            parameter = resolve(document, parameter)
            parameters[parameter["in"], parameter["name"]] = parameter
        if describe:
            return {**definition, "parameters": list(parameters.values())}
        supplied = json.loads(params)
        unknown = supplied.keys() - {name for _, name in parameters}
        if unknown:
            raise ValueError(f"Unknown parameters: {sorted(unknown)}; use --describe")
        query, request_headers, cookies = [], {}, {}
        for (location, name), parameter in parameters.items():
            if name not in supplied:
                if parameter.get("required"):
                    raise ValueError(f"Missing required {location} parameter: {name}")
                continue
            value = supplied[name]
            if isinstance(value, (dict, list, bool)) or value is None:
                value = json.dumps(value, separators=(",", ":"))
            else:
                value = str(value)
            if location == "path":
                path = path.replace("{" + name + "}", quote(value, safe=""))
            elif location == "query":
                query.append((name, value))
            elif location == "header":
                request_headers[name] = value
            elif location == "cookie":
                cookies[name] = value
            else:
                raise ValueError(f"Unsupported parameter location: {location}")
        request_body = resolve(document, definition.get("requestBody", {}))
        if request_body.get("required") and not body:
            raise ValueError("This operation requires --body with JSON")
        arguments = {}
        if body:
            if "application/json" not in request_body.get("content", {}):
                raise ValueError("This operation does not declare an application/json request body")
            arguments["json"] = json.loads(body)
        if cookies:
            client.cookies.update(cookies)
        response = client.request(method, url.rstrip("/") + path, params=query,
                                  headers=request_headers, **arguments)
        if response.is_error:
            raise RuntimeError(f"HTTP {response.status_code} {response.url}\n{response.text}")
        if not response.content:
            return None
        if "json" in response.headers.get("content-type", ""):
            return response.json()
        return response.text


# .. gone
if __name__ == "__main__":
    APP["cli"] = True
    cli(**glob_dict(""))

# .. imports, comments and docstring text that read differently now
#    Uses the current gppu APP CLI interface (CliApp is no longer exported).
#    from gppu import APP, glob_dict

# endregion


# region - RAN Services/Kuma/cctv-repair.py as of 2026-11-20 (2)

# .. gone
def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--incident')
  parser.add_argument('--status', choices=ACTIVE + TERMINAL + ('needs_decision',))
  parser.add_argument('--turn')
  parser.add_argument('--evidence')
  parser.add_argument('--owner-stopped', type=Path, help='Native read_thread capture proving the claiming turn ended')
  args = parser.parse_args()
  Env.from_env(name='cctv-repair', app_path=HERE)
  glob_dict('')
  path = Path(glob('inbox'))
  if args.owner_stopped:
    capture = json.loads(args.owner_stopped.read_text())
    with inbox(path) as data:
      incident = data['incidents'][args.incident]
      if incident['status'] not in ACTIVE or capture['thread']['id'] != incident['claimed_by']:
        raise ValueError('Capture does not identify the active claim owner')
      [turn] = [t for t in capture['turns'] if t['id'] == incident['turn_id']]
      if turn['status'] not in ('completed', 'failed', 'interrupted'):
        raise ValueError('Native claiming turn has not stopped')
      incident['evidence'].append({'at': now(), 'text': f'Owner stopped: {args.owner_stopped}; turn {turn["id"]}: {turn["status"]}'})
      incident['status'], incident['updated'] = 'queued', now()
    Info('Stopped owner claim returned to queue')
    return
  if args.incident:
    if not args.status or (args.status == 'diagnosing' and not args.turn):
      parser.error('Status and a claiming native turn ID are required')
    with inbox(path) as data:
      transition(data, args.incident, args.status, args.turn, args.evidence)
    Info(f'Incident {args.incident}: {args.status}')
    return
  credentials = dict_from_yml(HERE / 'client.yaml')
  auth = 'Basic ' + base64.b64encode(f"{credentials['username']}:{credentials['password']}".encode()).decode()
  allowed = glob('monitor_ids')

  class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
      pass  # Request headers and bodies contain credentials and private monitor details.

    def do_POST(self):
      if self.path != '/kuma':
        self.send_error(404)
        return
      if not hmac.compare_digest(self.headers.get('Authorization', ''), auth):
        self.send_error(401)
        return
      try:
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        with inbox(path) as data:
          result = receive(data, payload, allowed)
      except (ValueError, KeyError, TypeError) as error:
        Info(f'Rejected Kuma payload: {type(error).__name__}')
        self.send_error(400)
        return
      body = json.dumps(result).encode()
      self.send_response(202)
      self.send_header('Content-Type', 'application/json')
      self.send_header('Content-Length', str(len(body)))
      self.end_headers()
      self.wfile.write(body)
      Info(f"Kuma incident {result['state']}: {result['key']}")

  server = HTTPServer((glob('bind'), glob('port')), Handler)
  context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
  context.load_cert_chain(glob('certificate'), glob('private_key'))
  server.socket = context.wrap_socket(server.socket, server_side=True)
  Info('CCTV repair authenticated inbox listening')
  server.serve_forever()


# .. gone
if __name__ == '__main__':
  main()

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, Info, dict_from_yml
#    from gppu import glob, glob_dict

# endregion


# region - RAN Services/Kuma/cctv-repair.yaml as of 2026-11-20

# .. the lines that are gone or read differently now
#    inbox: /Users/alex/Work/10/02/cctv-repair/incidents.codex.json
#    bind: 0.0.0.0
#    port: 8770
#    certificate: /Users/alex/RAN/Keys/SSL/fullchain.pem
#    private_key: /Users/alex/RAN/Keys/SSL/privkey.pem
#    monitor_ids: [307, 308, 309, 310, 311, 312, 313, 314, 315, 316, 317, 318, 319, 320, 321, 322, 323, 324, 325, 326, 327, 328, 329, 330, 331]

# endregion


# region - RAN Services/Kuma/setup-cctv-monitors.py as of 2026-11-20 (3)

# .. changed
CCTV_CONFIG = HERE.parents[1] / 'Systems/CCTV-detective/service.yaml'


# .. gone
def main():
  parser = argparse.ArgumentParser(description=__doc__)
  mode = parser.add_mutually_exclusive_group()
  mode.add_argument('--dry-run', action='store_true')
  mode.add_argument('--check', action='store_true')
  args = parser.parse_args()
  Env.from_env(name='client', app_path=HERE)
  glob_dict('')
  age = dict_from_yml(CCTV_CONFIG)['stale_seconds']
  dashboard, status = read('/api/dashboard'), read('/api/status')
  checks = [(f"{row['camera']} detection", '/api/dashboard', f"cameras[camera={json.dumps(row['camera'])}].checked_age_seconds", '<=', age)
            for row in dashboard['cameras']]
  checks += [(f"{row['title']} heartbeat", '/api/status', f"services[name={json.dumps(row['name'])}].heartbeat_age_seconds", '<=', age)
             for row in status['services']]
  checks += [('Main-HTPC storage', '/api/dashboard', 'storage.disk_free / 1073741824', '>=', FREE_GIB),
             ('Failed investigations', '/api/dashboard', 'attention.investigations_failed', '==', 0),
             ('Failed extractions', '/api/dashboard', 'attention.extraction_failed', '==', 0)]
  with UptimeKumaApi(glob('url'), timeout=120) as api:
    api.login(glob('username'), glob('password'))
    existing = api.get_monitors()
    [cctv] = [m for m in existing if m['type'] == 'group' and m['name'] == 'CCTV' and m['parent'] is None]
    groups = [m for m in existing if m['type'] == 'group' and m['name'] == GROUP and m['parent'] == cctv['id']]
    if len(groups) > 1:
      raise RuntimeError(f'Duplicate {GROUP} groups')
    if not groups:
      if args.check:
        raise RuntimeError(f'{GROUP} monitors are not installed')
      Info(f'Create {GROUP} under CCTV')
      if not args.dry_run:
        result = api.add_monitor(type=MonitorType.GROUP, name=GROUP, parent=cctv['id'])
        groups = [{'id': result['monitorID']}]
    parent = groups[0]['id'] if groups else None  # A dry run does not create a group.
    for name, route, query, operator, limit in checks:
      matches = [m for m in existing if parent is not None and m['parent'] == parent and m['type'] == 'json-query'
                 and m['url'] == BASE + route and m['jsonPath'] == query]
      if matches:
        [monitor] = matches
        Info(f"Keep {monitor['name']}: {monitor['jsonPathOperator']} {monitor['expectedValue']} in Kuma")
        if args.check:
          if not monitor['active']:
            raise RuntimeError(f'{name}: monitor is paused')
          beats = api.get_monitor_beats(monitor['id'], 1)
          if not beats:
            raise RuntimeError(f'{name}: no heartbeat')
          beat = max(beats, key=lambda row: row['time'])
          Info(f"{name}: {beat['time']} — {beat['msg']}")
          elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(beat['time']).replace(tzinfo=timezone.utc)).total_seconds()
          if beat['status'] != 1 or elapsed > monitor['interval'] + monitor['timeout']:
            raise RuntimeError(f"{name}: stale or unsuccessful heartbeat — {beat['msg']}")
        continue
      if args.check:
        raise RuntimeError(f'{name}: monitor is missing')
      if any(m['parent'] == parent and m['name'] == name for m in existing):
        raise RuntimeError(f'{name}: existing monitor has a different query')
      Info(f'Add {name}: {query} {operator} {limit}')
      if not args.dry_run:
        payload = api._build_monitor_data(type=MonitorType.JSON_QUERY, name=name, parent=parent,
                                         url=BASE + route, jsonPath=query, expectedValue=str(limit), **TIMING)
        payload['jsonPathOperator'] = operator  # The installed SDK does not expose Kuma 2's comparison field.
        api._call('add', payload)['monitorID']
  Info('CCTV numeric monitors: live heartbeats verified' if args.check else
       'CCTV numeric monitors: preview complete' if args.dry_run else 'CCTV numeric monitors: installed')


# .. gone
if __name__ == '__main__':
  main()

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, Info, dict_from_yml
#    from gppu import glob, glob_dict

# endregion


# region - RAN Services/Kuma/setup-ld-monitors.py as of 2026-11-20 (4)

# .. gone
APP['name'] = 'client'   # Kuma's address and login, client.yaml beside this file


# .. gone
APP['cli'] = True        # the command line goes over it: --try, --check, --dry_run, --resume, --pause


# .. gone
def main():
    paths = routes()
    if glob('try'):
        return attempt(paths)
    preview, check, resume, pause = glob('dry_run'), glob('check'), glob('resume'), glob('pause')
    only_read = preview or check or resume or pause
    with UptimeKumaApi(glob('url'), timeout=120) as api:
        api.login(glob('username'), glob('password'))
        existing = api.get_monitors()
        tags = {tag['name']: tag['id'] for tag in api.get_tags()}
        for severity, color in (('Critical', '#DC2626'), ('Warning', '#F59E0B')):
            if severity not in tags and not only_read:
                tags[severity] = api.add_tag(name=severity, color=color)['id']

        def group(name: str, parent: int | None) -> int | None:
            found = [m for m in existing if m['type'] == 'group' and m['name'] == name and m['parent'] == parent]
            if len(found) > 1:
                raise RuntimeError(f'{name}: more than one group')
            if found or only_read:
                return found[0]['id'] if found else None
            Info(f'Add group {name}')
            return api._call('add', api._build_monitor_data(type=MonitorType.GROUP, name=name, parent=parent) | PAUSED)['monitorID']
        top = group(GROUP, None)
        parents = {name: group(name, top) for name in ('five:8096', 'api.karel.in', 'Last record')}
        for (where, name), monitor in wanted(paths).items():
            parent = parents[where]
            found = [m for m in existing if parent is not None and m['parent'] == parent and m['name'] == name]
            if found:
                [m] = found
                # a monitor made before its route asked one page, or before its age read `created` for a record never changed,
                # asks as it does now
                changes = {key: monitor[key] for key in ('url', 'jsonPath') if key in monitor and m.get(key) != monitor[key]}
                if not only_read and changes:
                    Info(f"Change {where} {name}: {changes}")
                    api.edit_monitor(m['id'], **changes)
                if check:
                    beats = api.get_monitor_beats(m['id'], 1)
                    beat = max(beats, key=lambda row: row['time']) if beats else None
                    Info(f"{where} {name}: {'active' if m['active'] else 'paused'}, "
                         + (f"{beat['time']} {'up' if beat['status'] == 1 else 'down'} {beat['msg']}" if beat else 'no heartbeat'))
                elif resume and not m['active']:
                    api.resume_monitor(m['id'])
                elif pause and m['active']:
                    api.pause_monitor(m['id'])
                continue
            if only_read:
                Info(f'{where} {name}: missing')
                continue
            severity = monitor.pop('severity')
            Info(f"Add {severity} {where} {name}: {monitor['url']}"
                 + (f" age <= {monitor['expectedValue']} s" if 'jsonPath' in monitor else ''))
            payload = api._build_monitor_data(name=name, parent=parent, **monitor, **TIMING) | PAUSED
            if 'jsonPath' in monitor:
                payload['jsonPathOperator'] = '<='   # the installed SDK does not expose Kuma 2's comparison field
            api.add_monitor_tag(tag_id=tags[severity], monitor_id=api._call('add', payload)['monitorID'])
        for parent in (*parents.values(), top):
            if parent is not None and (resume or pause):
                (api.resume_monitor if resume else api.pause_monitor)(parent)
    Info('Linked Data monitors: ' + ('checked' if check else 'previewed' if preview else 'resumed' if resume
                                     else 'paused' if pause else 'installed, paused'))


# .. gone
if __name__ == '__main__':
    main()

# .. imports, comments and docstring text that read differently now
#    from gppu import APP, Info, glob

# endregion


# region - RAN Services/Kuma/test_cctv_repair.py as of 2026-11-20 (1)

# .. changed
repair = importlib.util.module_from_spec(spec)

# endregion


# region - RAN Skills/coverage/coverage.yaml as of 2026-11-20

# .. the lines that are gone or read differently now
#    coverage:
#      database: /data/ov-coverage/coverage.sqlite3
#      output: /data/ov-coverage/reports
#      start: '2026-01-01'
#      timezone: America/Los_Angeles
#      authorship_manifest: /data/ov-coverage/sources/fileindexer-authorship.jsonl
#      identity_manifest: /data/ov-coverage/sources/windows-native-identity.jsonl
#      hermes_activity_manifest: /data/ov-coverage/sources/hermes-weekly-activity.jsonl
#      scope_manifest: /data/ov-coverage/sources/openclaw-scope-overlay.jsonl
#      ov_roots:
#        - /data/ov-data/viking/karelin/user/alex/sessions
#      source_manifests:
#        - /data/ov-coverage/sources/chatgpt-export-20261015.sessions.jsonl
#        - /data/ov-coverage/sources/claude-web-export-20260904.sessions.jsonl
#        - /data/ov-coverage/sources/codex-web-export-20261015.sessions.jsonl
#        - /data/ov-coverage/sources/windows-native.sessions.jsonl
#        - /data/ov-coverage/sources/mac-native.sessions.jsonl
#        - /data/ov-coverage/sources/openclaw-snapshot-20261012.sessions.jsonl
#        - /data/ov-coverage/sources/openclaw-native-sqlite.sessions.jsonl
#        - /data/ov-coverage/sources/fileindexer-records.sessions.jsonl
#        - /data/ov-coverage/sources/fileindexer-textlake.sessions.jsonl

# endregion


# region - RAN Skills/coverage/scripts/coverage.py as of 2026-11-20 (2)

# .. gone
SKILL_ROOT = Path(__file__).resolve().parents[1]


# .. changed; the one of now is in RAN Skills/coverage/scripts/coverage.py
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-only', action='store_true', help='query the latest complete index without rereading sources')
    args = parser.parse_args()
    Env.from_env(name='coverage', app_path=SKILL_ROOT)
    cfg = glob_dict('coverage')
    path = Path(cfg['database'])
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        if not args.report_only:
            Info('Indexing conversation evidence without changing source data')
            index(db, cfg)
        from coverage_report import build_report
        build_report(db, cfg)

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, Info

# endregion


# region - RAN Skills/devops/scripts/atv-pair.py as of 2026-11-20 (11)

# .. gone
Env.from_env(name='atv-pair', app_path=Path(__file__).resolve().parent)


# .. gone
DEVICE = glob('device')


# .. gone
PIN_FILE = glob('pin_file')


# .. gone
SCAN_TIMEOUT = glob('scan_timeout')


# .. gone
PIN_WAIT = glob('pin_wait')


# .. gone
PIN_POLL = glob('pin_poll')


# .. gone
async def find(loop, name):
  for atv in await pyatv.scan(loop, timeout=SCAN_TIMEOUT):
    if atv.name == name: return atv
  raise SystemExit(f"{name} not found on the network")


# .. gone
async def read_pin(protocol):
  """Wait for PIN_FILE to hold a fresh PIN, then consume it."""
  from pathlib import Path
  path = Path(PIN_FILE)
  path.unlink(missing_ok=True)
  print(f"  {protocol.name}: PIN is on the TV screen — write it to {PIN_FILE}", flush=True)
  for _ in range(PIN_WAIT // PIN_POLL):
    if path.exists() and (pin := path.read_text().strip()):
      path.unlink(missing_ok=True)
      return pin
    await asyncio.sleep(PIN_POLL)
  raise SystemExit(f"no PIN in {PIN_FILE} after {PIN_WAIT}s")


# .. gone
async def pair(loop, config, protocol):
  pairing = await pyatv.pair(config, protocol, loop)
  await pairing.begin()
  if pairing.device_provides_pin:
    pairing.pin(await read_pin(protocol))
  else:
    raise SystemExit(f"{protocol.name} expects the PIN on this side; not supported here")
  await pairing.finish()
  credentials = pairing.service.credentials
  await pairing.close()
  if not pairing.has_paired: raise SystemExit(f"{protocol.name} pairing did not complete")
  return credentials


# .. gone
async def main():
  name = sys.argv[1] if len(sys.argv) > 1 else DEVICE
  loop = asyncio.get_running_loop()
  config = await find(loop, name)
  print(f"{config.name}  {config.address}  id={config.identifier}", flush=True)

  paired = {}
  for protocol in PROTOCOLS:
    paired[protocol.value] = await pair(loop, config, protocol)
    print(f"  {protocol.name}: paired", flush=True)

  print('\n# -> _Creekview/av.yaml, top level')
  print('apple_tvs:')
  print(f"  - name: {config.name}")
  print(f"    address: {config.address}")
  print(f"    identifiers: ['{config.identifier}']")
  print('    credentials:')
  for proto_int, credential in sorted(paired.items()):
    print(f"      {proto_int}: {credential}        # {Protocol(proto_int).name}")


# .. gone
asyncio.run(main())

# .. imports, comments and docstring text that read differently now
#    each puts a four-digit PIN on the TV screen. The PIN is read from PIN_FILE rather
#        docker run --rm --network host -v $PWD/atv-pair.py:/app/atv-pair.py:ro \
#          -v $PWD/atv-pair.yaml:/app/atv-pair.yaml:ro -v /tmp:/tmp \
#    from gppu import Env
#    from gppu import glob

# endregion


# region - RAN Skills/devops/scripts/atv-pair.yaml as of 2026-11-20

# .. the lines that are gone or read differently now
#    device: AO AppleTV
#    pin_file: /tmp/atv-pin
#    scan_timeout: 8
#    pin_wait: 300
#    pin_poll: 2

# endregion


# region - RAN Skills/devops/scripts/iot-compare.sh as of 2026-11-20

# .. the lines that are gone or read differently now
#    docker run --rm --network none "${MOUNTS[@]}" -w "$WORKDIR" "$IMAGE" python y2-compare.py --wiring |
#      docker run --rm -i --network host "${MOUNTS[@]}" -w "$WORKDIR" "$IMAGE" python y2-compare.py --from-wiring "$@"

# endregion


# region - RAN Skills/devops/scripts/iot-monitor.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Skills/devops/scripts/iot-monitor.py
def settings() -> dict:
  config = Path(__file__).with_suffix('.yaml').resolve(strict=True)
  image = subprocess.run(['docker', 'inspect', 'y2', '--format', '{{.Image}}'],
                         check=True, capture_output=True, text=True).stdout.strip()
  code = (
    "import json; from pathlib import Path; from gppu import Env, glob; "
    "Env.from_env(name='iot-monitor', app_path=Path('/config')); "
    "print(json.dumps({key: glob(key) for key in "
    "('broker','broker_port','broker_user','broker_pass','y2_host','y2_port','mute','control')}))"
  )
  result = subprocess.run([
    'docker', 'run', '--rm', '--network', 'none',
    '--mount', f'type=bind,source={config},target=/config/iot-monitor.yaml,readonly',
    image, 'python', '-c', code,
  ], check=True, capture_output=True, text=True)
  return json.loads(result.stdout)

# endregion


# region - RAN Skills/devops/scripts/kea.py as of 2026-11-20 (3)

# .. gone
CONFIG = {'url': 'https://ons.karel.in',
 'key': 'credential withheld',
 'secret': 'credential withheld'}


# .. gone
def main():
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('path', nargs='?', default='dhcpv4/search_reservation')
  parser.add_argument('body', nargs='?', help='JSON request body')
  parser.add_argument('--method', choices=['GET', 'POST'])
  args = parser.parse_args()
  Env.from_dict(CONFIG.copy())
  session = requests.Session()
  session.auth = (glob('key'), glob('secret'))
  method = args.method or ('POST' if args.body is not None else 'GET')
  body = json.loads(args.body) if args.body is not None else None
  response = session.request(method, glob('url') + '/api/kea/' + args.path,
                             json=body, timeout=REQUEST_TIMEOUT)
  response.raise_for_status()
  result = response.json()
  if isinstance(result, dict) and any(result.get(key) in ('failed', 'error') for key in ('result', 'status')):
    raise RuntimeError(json.dumps(result))
  print(json.dumps(result, indent=2))


# .. gone
if __name__ == '__main__':
  main()

# .. imports, comments and docstring text that read differently now
#    from gppu import Env
#    from gppu import glob

# endregion


# region - RAN Skills/devops/scripts/kuma.py as of 2026-11-20 (8)

# .. gone
Env.from_env(name='kuma', app_path=Path(__file__).resolve().parent)


# .. gone
URL = glob('url')


# .. gone
USERNAME = glob('username')


# .. gone
PASSWORD = glob('password')


# .. gone
method = sys.argv[1] if len(sys.argv) > 1 else 'get_monitors'


# .. gone
args = [int(a) if a.lstrip('-').isdigit() else a for a in sys.argv[2:]]


# .. gone
api = UptimeKumaApi(URL, timeout=120)   # the initial payload for 236 monitors is slow


# .. gone
try:
  api.login(USERNAME, PASSWORD)
  print(json.dumps(getattr(api, method)(*args), indent=2, default=str))
finally:
  api.disconnect()

# .. imports, comments and docstring text that read differently now
#    from gppu import Env
#    from gppu import glob

# endregion


# region - RAN Skills/devops/scripts/mqtt.py as of 2026-11-20 (15)

# .. gone
Env.from_env(name='mqtt', app_path=Path(__file__).resolve().parent)


# .. gone
topic = sys.argv[1] if len(sys.argv) > 1 else 'status/#'


# .. gone
seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 6


# .. gone
broker = glob('brokers/' + (sys.argv[3] if len(sys.argv) > 3 else glob('broker')))


# .. gone
seen = {}


# .. gone
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)


# .. gone
c.username_pw_set(glob('username'), glob('password'))


# .. gone
c.on_connect = lambda cl, u, f, rc, props=None: cl.subscribe(topic)


# .. gone
c.on_message = lambda cl, u, m: seen.__setitem__(m.topic, m.payload.decode(errors='replace'))


# .. gone
c.connect(broker, glob('port'), 30)


# .. gone
c.loop_start()


# .. gone
time.sleep(seconds)


# .. gone
c.loop_stop()


# .. gone
c.disconnect()


# .. gone
print(json.dumps(seen, indent=2, default=str))

# .. imports, comments and docstring text that read differently now
#    from pathlib import Path
#    from gppu import Env
#    from gppu import glob

# endregion


# region - RAN Skills/devops/scripts/mqtt.yaml as of 2026-11-20

# .. the lines that are gone or read differently now
#    brokers:
#      iot: mqtt.c.karel.in
#    port: 1883
#    username: kuma
#    password: 'credential withheld'
#    broker: iot

# endregion


# region - RAN Skills/devops/scripts/tests/test_webmin.py as of 2026-11-20 (2)

# .. changed
webmin = importlib.util.module_from_spec(SPEC)


# .. changed; the one of now is in RAN Skills/devops/scripts/tests/test_webmin.py
class WebminTests(unittest.TestCase):
  def test_rename_preserves_old_identity_ttl_and_comment_for_webmin(self):
    identity = OLD + '/A/' + ADDRESS
    query = urlencode({'id': identity, 'zone': FORWARD['name']})
    listing = MagicMock(url='https://webmin.example/bind8/edit_recs.cgi',
                        text='<a href="edit_record.cgi?' + query + '">old</a>')
    editing = MagicMock(url='https://webmin.example/bind8/edit_record.cgi', text=f'''<form action="save_record.cgi">
      <input type="hidden" name="zone" value="{FORWARD['name']}">
      <input type="hidden" name="type" value="A">
      <input type="hidden" name="id" value="{identity}">
      <input type="hidden" name="oldname" value="{OLD}">
      <input type="hidden" name="oldvalue0" value="{ADDRESS}">
      <input type="radio" name="ttl_def" value="0" checked>
      <input type="text" name="ttl" value="30">
      <select name="ttlunit"><option value="M" selected></option></select>
      <input type="text" name="comment" value="Keep this comment">
      <input type="radio" name="rev" value="1" checked>
      <input type="submit" name="delete" value="Delete"></form>''')
    session = MagicMock()
    session.get.side_effect = [listing, editing]
    session.post.return_value.status_code = 302
    session.post.return_value.headers = {'Location': 'edit_recs.cgi'}
    with patch.object(webmin.Env, 'glob', return_value='https://webmin.example'):
      webmin.save_address(session, FORWARD, entries(FORWARD, OLD)[0], NEW, ADDRESS)
    sent = session.post.call_args.kwargs['data']
    self.assertEqual({key: sent[key] for key in ('oldname', 'oldvalue0', 'name', 'value0', 'rev', 'ttl', 'ttlunit', 'comment')},
                     {'oldname': OLD, 'oldvalue0': ADDRESS, 'name': NEW, 'value0': ADDRESS, 'rev': '1',
                      'ttl': '30', 'ttlunit': 'M', 'comment': 'Keep this comment'})
    self.assertNotIn('delete', sent)

  def test_adoption_requests_automatic_reverse_without_an_old_record(self):
    page = MagicMock(url='https://webmin.example/bind8/edit_recs.cgi', text=f'''<form action="save_record.cgi">
      <input type="hidden" name="zone" value="{FORWARD['name']}">
      <input type="hidden" name="type" value="A">
      <input type="hidden" name="new" value="1">
      <input type="radio" name="rev" value="1" checked></form>''')
    session = MagicMock()
    session.get.return_value = page
    session.post.return_value.status_code = 302
    session.post.return_value.headers = {'Location': 'edit_recs.cgi'}
    with patch.object(webmin.Env, 'glob', return_value='https://webmin.example'):
      webmin.save_address(session, FORWARD, None, NEW, ADDRESS)
    sent = session.post.call_args.kwargs['data']
    self.assertEqual((sent['new'], sent['name'], sent['value0'], sent['rev']), ('1', NEW, ADDRESS, '1'))
    self.assertNotIn('oldname', sent)

  def test_save_form_excludes_delete_and_unchecked_overwrite(self):
    page = webmin.RecordPage('''<form action="save_record.cgi">
      <input type="hidden" name="type" value="A">
      <input type="radio" name="rev" value="1" checked>
      <input type="radio" name="rev" value="2">
      <input type="radio" name="rev" value="0">
      <input type="submit" name="delete" value="Delete">
      <select name="ttlunit"><option value="" selected></option><option value="H"></option></select>
      </form><form action="delete_recs.cgi"><input type="hidden" name="type" value="PTR"></form>''')
    self.assertEqual(page.fields, {'type': 'A', 'rev': '1', 'ttlunit': ''})

  def test_zone_selection_respects_delegation_and_rejects_ambiguous_views(self):
    parent = dict(FORWARD, name='test')
    self.assertEqual(webmin.zone_for([parent, FORWARD], NEW), FORWARD)
    self.assertEqual(webmin.zone_for([parent, FORWARD], 'example.test.'), FORWARD)
    with self.assertRaisesRegex(ValueError, 'ambiguous'):
      webmin.zone_for([FORWARD, dict(FORWARD, view='other')], NEW)

  def test_both_zones_are_released_when_save_fails(self):
    calls = []

    @contextmanager
    def fake_module(session):
      frozen = set()
      def call(function, args):
        if function == 'try_cmd':
          name = args[0].split(' ', 1)[1]
          return ['dynamic: yes\nfrozen: ' + ('yes' if name in frozen else 'no'), '1']
        if function == 'before_editing':
          frozen.add(args[0]['name'])
        if function == 'after_editing':
          frozen.remove(args[0]['name'])
        calls.append((function, args[0]['name']))
      try:
        yield call
      finally:
        calls.append(('quit', ''))

    with patch.object(webmin, 'zones', return_value=[FORWARD, REVERSE]), \
         patch.object(webmin, 'records', side_effect=lambda session, zone: entries(zone, OLD)), \
         patch.object(webmin, 'module', fake_module), \
         patch.object(webmin, 'save_address', side_effect=RuntimeError('permission denied')):
      with self.assertRaisesRegex(RuntimeError, 'permission denied'):
        webmin.set_host(None, NEW, ADDRESS, OLD)
    self.assertEqual(calls, [('before_editing', FORWARD['name']), ('before_editing', REVERSE['name']),
                             ('after_editing', REVERSE['name']), ('after_editing', FORWARD['name']), ('quit', '')])

  def test_silent_save_without_persistence_is_failure(self):
    with patch.object(webmin, 'zones', return_value=[FORWARD, REVERSE]), \
         patch.object(webmin, 'records', side_effect=lambda session, zone: entries(zone, OLD)), \
         patch.object(webmin.dns.resolver, 'Resolver') as resolver:
      with self.assertRaisesRegex(RuntimeError, 'persist'):
        webmin.verify_host(None, NEW, ADDRESS)
      resolver.assert_not_called()

  def test_missing_automatic_reverse_is_failure(self):
    with patch.object(webmin, 'zones', return_value=[FORWARD, REVERSE]), \
         patch.object(webmin, 'records', side_effect=lambda session, zone: entries(zone, NEW) if zone == FORWARD else []):
      with self.assertRaisesRegex(RuntimeError, 'automatic PTR'):
        webmin.verify_host(None, NEW, ADDRESS)

  def test_saved_but_unapplied_zone_is_failure(self):
    resolver = MagicMock()
    resolver.resolve.side_effect = [[ADDRESS], [OLD]]
    with patch.object(webmin, 'zones', return_value=[FORWARD, REVERSE]), \
         patch.object(webmin, 'records', side_effect=lambda session, zone: entries(zone, NEW)), \
         patch.object(webmin.dns.resolver, 'Resolver', return_value=resolver), \
         patch.object(webmin.socket, 'gethostbyname', return_value='192.0.2.53'), \
         patch.object(webmin.Env, 'glob', return_value='dns.example.test'):
      with self.assertRaisesRegex(RuntimeError, 'not serving'):
        webmin.verify_host(None, NEW, ADDRESS)

  def test_conflicting_reverse_record_blocks_the_forward_write(self):
    with patch.object(webmin, 'zones', return_value=[FORWARD, REVERSE]), \
         patch.object(webmin, 'records', side_effect=lambda session, zone: entries(zone, OLD if zone == FORWARD else 'another.example.test.')), \
         patch.object(webmin, 'save_address') as save:
      with self.assertRaisesRegex(ValueError, 'Conflicting PTR'):
        webmin.set_host(None, NEW, ADDRESS, OLD)
      save.assert_not_called()

# endregion


# region - RAN Skills/devops/scripts/unifi.py as of 2026-11-20 (3)

# .. gone
CONFIG = {'url': 'https://uos.karel.in',
 'username': 'hassio',
 'password': 'credential withheld',
 'site': 'default',
 'verify_tls': False}


# .. gone
def main():
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('path', nargs='?', default='stat/device')
  parser.add_argument('body', nargs='?', help='JSON request body')
  parser.add_argument('--method', choices=['GET', 'POST', 'PUT', 'DELETE'])
  args = parser.parse_args()
  Env.from_dict(CONFIG.copy())
  urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
  session = requests.Session()
  session.verify = glob('verify_tls')
  login = session.post(glob('url') + '/api/auth/login', timeout=LOGIN_TIMEOUT,
                       json={'username': glob('username'), 'password': glob('password')})
  login.raise_for_status()
  session.headers['x-csrf-token'] = login.headers['x-csrf-token']
  base = glob('url') + '/proxy/network/'
  if args.path.startswith('v2/'):
    url = base + 'v2/api/site/' + glob('site') + '/' + args.path[3:]
  else:
    url = base + 'api/s/' + glob('site') + '/' + args.path
  method = args.method or ('POST' if args.body is not None else 'GET')
  body = json.loads(args.body) if args.body is not None else None
  response = session.request(method, url, json=body, timeout=REQUEST_TIMEOUT)
  response.raise_for_status()
  result = response.json() if response.content else response.status_code
  if isinstance(result, dict) and 'meta' in result and result['meta']['rc'] != 'ok':
    raise RuntimeError(json.dumps(result['meta']))
  print(json.dumps(result, indent=2, default=str))


# .. gone
if __name__ == '__main__':
  main()

# .. imports, comments and docstring text that read differently now
#    from gppu import Env
#    from gppu import glob

# endregion


# region - RAN Skills/devops/scripts/unifi.yaml as of 2026-11-20

# .. the lines that are gone or read differently now
#    url: https://uos.karel.in
#    username: hassio
#    password: 'credential withheld'
#    site: default
#    verify_tls: false

# endregion


# region - RAN Skills/devops/scripts/webmin.py as of 2026-11-20 (7)

# .. gone
CONFIG = {'url': 'https://webmin.karel.in', 'username': 'root', 'password': 'credential withheld', 'dns_server': 'dns.karel.in'}


# .. changed; the one of now is in RAN Skills/devops/scripts/webmin.py
def login():
  session = requests.Session()
  session.cookies.set('testing', '1')
  response = session.post(glob('url') + '/session_login.cgi',
                          data={'user': glob('username'), 'pass': glob('password'), 'page': '/bind8/'},
                          headers={'Referer': glob('url') + '/'}, timeout=REQUEST_TIMEOUT)
  response.raise_for_status()
  if 'sid' not in session.cookies.get_dict():
    raise RuntimeError('Webmin login failed')
  session.headers['Referer'] = glob('url') + '/bind8/'
  return session


# .. changed; the one of now is in RAN Skills/devops/scripts/webmin.py
def rpc(session, payload):
  response = session.post(glob('url') + '/rpc.cgi', data=encode(payload),
                          headers={'Content-Type': 'application/octet-stream'}, timeout=REQUEST_TIMEOUT)
  response.raise_for_status()
  result = decode(response.text)
  if result['status'] != '1':
    raise RuntimeError('Webmin RPC failed: ' + json.dumps(result))
  return result


# .. changed; the one of now is in RAN Skills/devops/scripts/webmin.py
def save_address(session, zone, current, name, address, rtype='A', rev='1'):
  response = session.get(glob('url') + '/bind8/edit_recs.cgi',
                          params={'zone': zone['name'], 'view': 'any', 'type': rtype}, timeout=REQUEST_TIMEOUT)
  response.raise_for_status()
  page = RecordPage(response.text)
  if current is not None:
    identity = current['name'] + '/A/' + current['values'][0]
    links = [link for link in page.links if link.startswith('edit_record.cgi?') and
             parse_qs(urlsplit(link).query)['id'] == [identity]]
    if len(links) != 1:
      raise RuntimeError('Cannot identify the Webmin record to edit: ' + identity)
    response = session.get(urljoin(response.url, links[0]), timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    page = RecordPage(response.text)
    if page.fields['oldname'] != current['name'] or page.fields['oldvalue0'] != current['values'][0]:
      raise RuntimeError('Webmin record changed before saving')
  elif page.fields['new'] != '1':
    raise RuntimeError('Webmin did not return the new-record form')
  fields = page.fields.copy()
  if fields['type'] != rtype or fields['zone'] != zone['name'] or 'delete' in fields:
    raise RuntimeError('Unexpected Webmin record form')
  fields.update(name=name, value0=address)
  if rev:
    fields['rev'] = rev
  result = session.post(urljoin(response.url, 'save_record.cgi'), data=fields,
                        headers={'Referer': response.url}, allow_redirects=False, timeout=REQUEST_TIMEOUT)
  result.raise_for_status()
  if result.status_code != 302 or 'edit_recs.cgi' not in result.headers['Location']:
    raise RuntimeError('Webmin rejected the save; HTTP ' + str(result.status_code))


# .. changed; the one of now is in RAN Skills/devops/scripts/webmin.py
def verify_host(session, name, address):
  known = zones(session)
  forward = zone_for(known, name)
  reverse = zone_for(known, IPv4Address(address).reverse_pointer + '.')
  current = address_record(records(session, forward), name)
  if current is None or current['values'] != [address]:
    raise RuntimeError('Webmin did not persist the expected A record')
  if not check_pointer(session, reverse, address, {name.lower()}):
    raise RuntimeError('Webmin did not persist the automatic PTR record')
  resolver = dns.resolver.Resolver(configure=False)
  resolver.nameservers = [socket.gethostbyname(glob('dns_server'))]
  resolver.timeout = resolver.lifetime = REQUEST_TIMEOUT
  answers = [str(item) for item in resolver.resolve(name, 'A', tcp=True)]
  pointers = [str(item).lower() for item in resolver.resolve(IPv4Address(address).reverse_pointer, 'PTR', tcp=True)]
  if answers != [address] or pointers != [name.lower()]:
    raise RuntimeError('BIND is not serving the saved A/PTR records: ' + json.dumps({'A': answers, 'PTR': pointers}))
  with module(session) as call:
    for zone in (forward, reverse):
      status = zone_status(call, zone)
      if 'frozen: yes' in status:
        raise RuntimeError('BIND zone is frozen: ' + zone['name'])
  return {'name': name, 'address': address, 'A': answers, 'PTR': pointers, 'status': 'verified'}


# .. changed; the one of now is in RAN Skills/devops/scripts/webmin.py
def set_alias(session, name, target):
  known = zones(session)
  forward = zone_for(known, name)
  if any(entry['name'].lower() == name.lower() for entry in records(session, forward)):
    raise ValueError('DNS name already exists: ' + name)
  with module(session) as call, ExitStack() as cleanup:
    if 'frozen: yes' in zone_status(call, forward):
      raise RuntimeError('Zone was already frozen before this operation: ' + forward['name'])
    call('before_editing', [forward])
    cleanup.callback(call, 'after_editing', [forward])
    save_address(session, forward, None, name, target, rtype='CNAME', rev=None)
  resolver = dns.resolver.Resolver(configure=False)
  resolver.nameservers = [socket.gethostbyname(glob('dns_server'))]
  resolver.timeout = resolver.lifetime = REQUEST_TIMEOUT
  expected = target if target.endswith('.') else target + '.' + forward['name'].rstrip('.') + '.'
  answers = [str(item).lower() for item in resolver.resolve(name, 'CNAME', tcp=True)]
  if answers != [expected.lower()]:
    raise RuntimeError('BIND is not serving the saved CNAME: ' + json.dumps(answers))
  return {'name': name, 'CNAME': answers, 'status': 'verified'}


# .. changed; the one of now is in RAN Skills/devops/scripts/webmin.py
def main():
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  commands = parser.add_subparsers(dest='command')
  commands.add_parser('zones')
  listing = commands.add_parser('records')
  listing.add_argument('zone')
  for command in ('set', 'verify'):
    sub = commands.add_parser(command)
    sub.add_argument('name', help='fully qualified DNS name')
    sub.add_argument('address', type=lambda value: str(IPv4Address(value)))
    if command == 'set':
      sub.add_argument('--old-name', help='existing fully qualified name to rename')
  alias = commands.add_parser('alias')
  alias.add_argument('name', help='fully qualified DNS name')
  alias.add_argument('target', help='target name, relative to the zone unless it ends with a dot')
  args = parser.parse_args()
  Env.from_dict(CONFIG.copy())
  with login() as session:
    if args.command is None or args.command == 'zones':
      result = zones(session)
    elif args.command == 'records':
      matches = [zone for zone in zones(session) if zone['name'] == args.zone]
      if len(matches) != 1:
        raise ValueError('Zone is missing or ambiguous: ' + args.zone)
      result = records(session, matches[0])
    elif args.command == 'alias':
      result = set_alias(session, args.name.rstrip('.') + '.', args.target)
    else:
      name = args.name.rstrip('.') + '.'
      if args.command == 'set':
        old_name = args.old_name.rstrip('.') + '.' if args.old_name is not None else None
        result = set_host(session, name, args.address, old_name)
      else:
        result = verify_host(session, name, args.address)
  print(json.dumps(result, indent=2))

# .. imports, comments and docstring text that read differently now
#    from gppu import Env
#    from gppu import glob

# endregion


# region - RAN Skills/devops/scripts/y2-compare.py as of 2026-11-20 (3)

# .. changed; the one of now is in RAN Skills/devops/scripts/y2-compare.py
def build() -> None:
  configure({**glob_dict(''), 'y2': {**glob_dict('y2'), 'dry_run': True}})
  for name, row in glob_dict('y2/apps').items():
    data = dict(row)
    kind = data.pop('kind')
    if kind == 'UI': continue  # HTTP server, not entity construction.
    KINDS[kind](name=name, data=data).start()


# .. changed; the one of now is in RAN Skills/devops/scripts/y2-compare.py
async def _retained() -> dict:
  """One read-only subscription, held long enough for the broker to replay its
  retained set. Only retained messages are kept — a live message arriving during
  the window is not the stored value."""
  import aiomqtt
  out: dict[str, str] = {}
  mqtt = glob('y2/mqtt')
  async with aiomqtt.Client(hostname=mqtt['hostname'], port=mqtt['port'],
                            username=mqtt['username'], password=mqtt['password']) as client:
    await client.subscribe('#')
    try:
      async with asyncio.timeout(SNAPSHOT_SECONDS):
        async for message in client.messages:
          if not message.retain: continue
          payload = message.payload
          out[str(message.topic)] = payload.decode(errors='replace') if isinstance(payload, bytes) else str(payload)
    except TimeoutError:
      pass
  return out


# .. changed; the one of now is in RAN Skills/devops/scripts/y2-compare.py
def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('filter', nargs='*', help='keep objects whose eid, name or topics contain any of these')
  parser.add_argument('--bad', action='store_true', help='only disagreements and unresolved states')
  parser.add_argument('--detail', metavar='EID', help='full three-way view of one object')
  parser.add_argument('--button', metavar='TOPIC', help='what a press on this button topic is wired to do')
  parser.add_argument('--cross', action='store_true', help='join button, object state and keypad LED for every chain')
  parser.add_argument('--action', metavar='PATH', help='is this action path registered, and by what')
  parser.add_argument('--wiring', action='store_true', help='dump the configuration side as JSON and stop')
  parser.add_argument('--no-broker', action='store_true', help='skip the retained snapshot')
  parser.add_argument('--from-wiring', action='store_true', help=argparse.SUPPRESS)
  args = parser.parse_args()

  Env.init(environment='IoT')
  if args.from_wiring:
    wire = json.load(sys.stdin)
  else:
    build()
    wire = {
      'entities': wiring(),
      'actions':  sorted(str(a) for a in Runtime.actions),
      'buttons':  {str(k): member_ref(v) for k, v in Runtime.buttons.items()},
      'services': sorted(Runtime.services),
    }
  if args.wiring:
    json.dump(wire, sys.stdout, indent=1, sort_keys=True, default=str); sys.stdout.write('\n'); return

  # --cross joins configuration against belief only: every topic in that chain is
  # published non-retained, so the snapshot has nothing to add and is skipped.
  retained = {} if args.no_broker or args.cross else asyncio.run(_retained())
  live = _live()
  entities = wire['entities']
  print(f"# config {len(entities)} objects | retained {len(retained)} topics | y2 {len(live)} live states")

  if args.action:
    hits = [a for a in wire['actions'] if args.action in a]
    print(f"\naction paths containing {args.action!r}: {len(hits)}")
    for a in hits[:40]: print('  ', a)
    if not hits: print('   none — a post to this path is dispatched by nothing')
    return

  if args.cross:
    cross(wire, live, args.filter, args.bad); return

  if args.button:
    button_chain(args.button, wire, live, retained); return

  if args.detail:
    eid = args.detail if args.detail in entities else next((k for k in entities if args.detail in k), None)
    if eid is None: print(f'no object matches {args.detail!r}'); return
    detail(eid, entities[eid], live, retained); return

  # Objects the runtime holds but the rebuild does not are as interesting as the
  # reverse, so both directions are listed.
  rows, counts = [], {}
  for eid in sorted(set(entities) | set(live)):
    cfg = entities.get(eid, {})
    blob = f"{eid} {cfg.get('name','')} {cfg.get('listen_topic','')} {cfg.get('state_topic','')} {cfg.get('indicator','')} {cfg.get('button','')} {cfg.get('area','')}"
    if args.filter and not any(f in blob for f in args.filter): continue
    if eid not in entities:
      rows.append(f"{'NOT-IN-CONFIG':<14} {eid:<34} {live[eid].get('state','-'):<12} runtime holds it; the rebuild does not")
      counts['NOT-IN-CONFIG'] = counts.get('NOT-IN-CONFIG', 0) + 1
      continue
    verdict, _ = judge(cfg, live.get(eid, {}), retained, not args.no_broker)
    counts[verdict] = counts.get(verdict, 0) + 1
    if args.bad and verdict in ('ok', 'no-listen', 'no-snapshot'): continue
    rows.append(row(eid, cfg, live.get(eid, {}), retained, not args.no_broker))

  for line in rows: print(line)
  print('\n# ' + '  '.join(f'{k}={v}' for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, glob, glob_dict

# endregion


# region - RAN Systems/lake/common/catalog_configuration.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/lake/common/catalog_configuration.py
def catalog(host=None):
  from . import graph_configuration as configuration
  from lake.providers import location_types, templates
  with configuration.ENVIRONMENT_LOCK:
    configuration.environment()
    host = host or Env.host
    locations = {}
    for uid, item in configuration.tables()['locations'].items():
      row = dict(item)
      for field in ('access', 'storage', 'local'):
        row.pop(field, None)
      locations[uid] = row
    return GppuCatalog({'locations': locations,
      'connections': {uid: dict(row) for uid, row in configuration.tables()['connections'].items()},
      # Processes and sources as configured: /config shows the configuration, not what was built from it.
      'processes': glob_dict('processes'), 'sources': glob_dict('sources')}, host=host,
      location_types=location_types(), templates=templates())

# endregion


# region - RAN Systems/lake/common/dagster.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/lake/common/dagster.py
class Configuration(dg.ConfigurableResource):
  """Shared Location lookup, resolved for the host executing this run."""

  def setup_for_execution(self, context: dg.InitResourceContext) -> None:
    if not Env.initialized:
      environment()

  @property
  def catalog(self) -> GppuCatalog:
    return configured_catalog()

# .. imports, comments and docstring text that read differently now
#    from gppu import Env

# endregion


# region - RAN Systems/lake/common/graph_configuration.py as of 2026-11-20 (2)

# .. changed; the one of now is in RAN Systems/lake/common/graph_configuration.py
def environment() -> None:
  global _loaded_tree, _loaded_data
  with ENVIRONMENT_LOCK:
    held = data()
    written = json.dumps(held, ensure_ascii=False)
    if written != _loaded_tree or Env.data is not _loaded_data:
      Env.from_dict(held)
      _loaded_tree = written
      _loaded_data = Env.data


# .. changed; the one of now is in RAN Systems/lake/common/graph_configuration.py
def _resolved() -> tuple[dict[str, dict[str, dict]], dict[str, Environment]]:
  global _loaded_tables
  with ENVIRONMENT_LOCK:
    if _loaded_tables is None or _loaded_tables[0] is not Env.data:
      _loaded_tables = (Env.data, *resolve(Env.data))
    return _loaded_tables[1:]

# .. imports, comments and docstring text that read differently now
#    _loaded_tables = None   # (Env.data, its tables resolved, their Jinja), as _resolved() last built them

# endregion


# region - RAN Systems/lake/common/textlake.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/lake/common/textlake.py
class TextLake(dg.Component, dg.Model, dg.Resolvable):
  """Shared TextLake filesystem, source and destination resources, and naming rules.

  Instantiating this component registers storage capabilities and catalog entries.
  It creates no ingestion jobs and does not contact source providers.
  """

  def build_defs(self, context: dg.ComponentLoadContext) -> dg.Definitions:
    return self.definitions()

  def definitions(self) -> dg.Definitions:
    """Build from the configuration already loaded by the application."""
    config = glob_dict('textlake')
    if set(config['rules']) != set(config['choices']):
      raise ValueError('Every TextLake naming rule must declare its allowed field values')
    resources = {
      f'textlake_{role}': TextLakeResource(**config, role=role)
      for role in ('source', 'destination')
    }
    assets = [dg.AssetSpec(
      key=['TextLake', role], group_name='TextLake', kinds={'filesystem'},
      description=f'TextLake filesystem {role}; shared resource textlake_{role} enforces the declared naming rules.',
      metadata={'root': dg.MetadataValue.path(config['root']), 'uri': config['uri'],
                'resource': f'textlake_{role}', 'rules': dg.MetadataValue.json(config['rules'])},
    ) for role in ('source', 'destination')]
    return dg.Definitions(assets=assets, resources=resources)

# .. imports, comments and docstring text that read differently now
#    from gppu import Env
#    from gppu import glob_dict

# endregion


# region - RAN Systems/lake/dagster/catalog.py as of 2026-11-20 (1)

# .. gone
Logger.init_logger('lake')

# .. imports, comments and docstring text that read differently now
#    from gppu import Logger

# endregion


# region - RAN Systems/lake/dagster/defs.py as of 2026-11-20 (2)

# .. changed
MARKDOWN = glob_dict('processes')['source_markdown']


# .. changed; the one of now is in RAN Systems/lake/dagster/defs.py
@dg.asset(key=dg.AssetKey(MARKDOWN['asset'].split('/')), group_name='TextLake',
          deps=[dg.AssetKey(key.split('/')) for key in MARKDOWN['dependencies']],
          description=MARKDOWN['name'], pool=MARKDOWN['pool'])
def source_markdown(context: dg.AssetExecutionContext, configuration: Configuration) -> dg.MaterializeResult:
  """Render changed saved JSON into Markdown; source files remain unchanged."""
  definitions = glob_dict('sources')['markdown_templates']
  state = {}
  cursor = None
  while True:
    page = context.instance.fetch_materializations(context.asset_key, limit=1, cursor=cursor)
    checkpoint = None
    for record in page.records:
      entry = record.event_log_entry
      run = context.instance.get_run_by_id(entry.run_id) if entry.run_id else None
      if run is not None and run.status == dg.DagsterRunStatus.SUCCESS:
        checkpoint = entry.asset_materialization.metadata
        break
    if checkpoint is not None:
      if 'refresh state' in checkpoint and 'templates' in checkpoint and checkpoint['templates'].value == definitions:
        state = checkpoint['refresh state'].value
      break
    if not page.has_more:
      break
    cursor = page.cursor
  catalog = configuration.catalog
  destination = catalog.location(MARKDOWN['destination_location_uid']).container()
  templates = jinja.overlay(loader=DictLoader(definitions))
  written = 0
  process = context.run.tags.get('source')
  source_uids = [tables()['sources'][process]['writes']] if process is not None else MARKDOWN['source_location_uids']
  for uid in source_uids:
    source = catalog.location(uid).container()
    with source.refresh(state) as objects:
      for obj in objects:
        if obj.removed or not obj.name.casefold().endswith('.json'):
          continue
        content = templates.get_template(MARKDOWN['template']).render(it=obj.content,
                                             uri=str(obj.uri), identity=obj.identity)
        if content is None or not str(content).strip():
          continue
        rendered = DataObject(obj.uri, str(content).encode('utf-8'), obj.identity,
                              kind='markdown', parent=obj)
        destination.write(destination.path_of(rendered), rendered)
        written += 1
  return dg.MaterializeResult(metadata={'refresh state': dg.MetadataValue.json(state),
                                        'templates': dg.MetadataValue.json(definitions),
                                        'documents written': written})

# .. imports, comments and docstring text that read differently now
#    from gppu import DataObject, Env, jinja
#    from gppu import glob_dict
#    from lake.common.graph_configuration import tables

# endregion


# region - RAN Systems/lake/dagster/test_templates.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import FileSystem, Location, y2uri

# endregion


# region - RAN Systems/lake/m365/config.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/lake/m365/config.py
@lru_cache(maxsize=None)
def _load_lake_config_cached(app_path_text: str) -> dict[str, Any]:
    app_path = Path(app_path_text)
    Env.reset()
    Env.from_env(name="lake", app_path=app_path)
    if not isinstance(Env.data, dict):
        raise TypeError(f"expected YAML mapping in {app_path / 'lake.yaml'}")
    return Env.data

# .. imports, comments and docstring text that read differently now
#    from gppu import Env

# endregion


# region - RAN Systems/lake/m365/msgraph/contacts.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import DataObject

# endregion


# region - RAN Systems/lake/plaud/dagster.py as of 2026-11-20 (3)

# .. changed; the one of now is in RAN Systems/lake/plaud/dagster.py
class PlaudResource(dg.ConfigurableResource):
  """The Plaud developer API, using the plaintext credentials resource."""

  provider: str
  api_base: str
  credentials: dg.ResourceDependency[PlaudCredentialsResource]

  def connect(self) -> tuple[PlaudImporterConfig, PlaudClient]:
    config = PlaudImporterConfig.from_mapping(glob('plaud'))
    return config, PlaudClient(config.client, request.urlopen, self.credentials)


# .. changed; the one of now is in RAN Systems/lake/plaud/dagster.py
def _containers(configuration: Configuration) -> tuple[Container, Container]:
  process = glob_dict('processes')['plaud_import']
  if len(process['source_location_uids']) != 1:
    raise ValueError('Plaud import requires one configured source Location')
  catalog = configuration.catalog
  return (catalog.location(process['source_location_uids'][0]).container(),
          catalog.location(process['destination_location_uid']).container())


# .. changed; the one of now is in RAN Systems/lake/plaud/dagster.py
@dg.asset(key=RECORDINGS, group_name='Transcriber', kinds={'audio', 'filesystem'},
          ins={'source': dg.AssetIn(key=SOURCE)},
          description='Original recordings downloaded through their Plaud Location. Existing audio is reused unchanged.')
def download_recordings(context: dg.AssetExecutionContext, source: list[dict],
                        configuration: Configuration) -> dict:
  origin, destination = _containers(configuration)
  downloaded, reused, unavailable, recordings = 0, 0, [], {}
  extensions = glob_dict('textlake')['choices']['recording_audio']['extension']
  for raw in source:
    obj = _recording(origin, raw)
    saved = _manifest(destination, obj)
    found = []
    for extension in extensions:
      audio = DataObject(obj.uri / 'audio', b'', obj.identity,
                         kind='recording_audio', name=extension, parent=obj)
      try:
        existing = destination.read(audio)
      except FileNotFoundError:
        continue
      found.append(_file_metadata(existing, _EXTENSION_CONTENT_TYPES[extension]))
    if len(found) > 1:
      raise dg.Failure('Plaud destination contains multiple audio objects')
    if found:
      actual = found[0]
      if saved and saved['audio'] is not None:
        if any(saved['audio'][key] != actual[key] for key in ('file_name', 'size', 'md5', 'sha256')):
          raise dg.Failure(f'Existing audio conflicts with its manifest for Plaud recording {obj.identity}')
      recordings[obj.identity] = actual
      reused += 1
      continue
    detail = replace(origin.read(quote(obj.identity, safe='')), kind='recording_manifest')
    with origin.provider.audio(detail) as audio:
      if audio is None:
        unavailable.append(obj.identity)
        recordings[obj.identity] = None
        continue
      destination.write(destination.path_of(audio), audio)
      recordings[obj.identity] = _file_metadata(destination.read(audio), _EXTENSION_CONTENT_TYPES[audio.name])
      downloaded += 1
  context.add_output_metadata({'downloaded': downloaded, 'reused': reused,
    'unavailable_audio': len(unavailable), 'unavailable_audio_ids': unavailable,
    PENDING_IDS: dg.MetadataValue.json(unavailable)})
  return recordings

# .. imports, comments and docstring text that read differently now
#    from gppu import Container, DataObject, Env
#    from gppu import glob, glob_dict

# endregion


# region - RAN Systems/lake/plaud/dumper.py as of 2026-11-20 (2)

# .. changed; the one of now is in RAN Systems/lake/plaud/dumper.py
class PlaudResource(dg.ConfigurableResource):
  """The Plaud developer API, using the plaintext credentials resource."""

  provider: str
  api_base: str
  credentials: dg.ResourceDependency[PlaudCredentialsResource]

  def connect(self):
    config = PlaudImporterConfig.from_mapping(glob('plaud'))
    return config, PlaudClient(config.client, request.urlopen, self.credentials)


# .. changed; the one of now is in RAN Systems/lake/plaud/dumper.py
class Plaud(dg.Component, dg.Model, dg.Resolvable):
  """Plaud API: independent recording and transcription downloads.

  Standalone source and import nodes. Uses the existing
  API client, byte-preserving download helpers and the shared TextLake resource.
  No transcription generation, database indexing or downstream publishing.
  """

  textlake_component: str

  def build_defs(self, context: dg.ComponentLoadContext) -> dg.Definitions:
    textlake = context.build_defs(self.textlake_component).resources['textlake_destination']
    return self.definitions(textlake)

  def definitions(self, textlake: TextLakeResource) -> dg.Definitions:
    """Reuse the same jobs when their configuration comes from the graph."""
    config = glob_dict('plaud')
    credential_config = glob_dict('plaud_credentials')
    credentials = PlaudCredentialsResource(**credential_config,
      refresh_token=full_path(credential_config['refresh_token_file']).read_text(encoding='utf-8').strip())
    assets = [
      read_plaud_source.with_attributes(metadata_by_key={SOURCE: {'source': dg.MetadataValue.url(config['api_base'])}}),
      download_recordings.with_attributes(metadata_by_key={RECORDINGS: {
        'naming_rules': dg.MetadataValue.json({key: textlake.rules[key] for key in ('recording_audio',)})}}),
      download_transcriptions.with_attributes(metadata_by_key={TRANSCRIPTIONS: {
        'naming_rules': dg.MetadataValue.json({key: textlake.rules[key] for key in
          ('recording_source', 'recording_note', 'recording_manifest')})}}),
    ]
    resources = {'plaud_credentials': credentials,
                 'plaud': PlaudResource(provider=config['provider'], api_base=config['api_base'], credentials=credentials),
                 'textlake_destination': textlake}
    definitions = dg.Definitions(assets=assets, resources=resources,
      jobs=[dg.define_asset_job('plaud_import', selection=dg.AssetSelection.assets(*assets),
                               description='Download recordings and existing transcriptions directly from the Plaud API to local files.',
                               executor_def=dg.in_process_executor)])
    # Bind the job before the catalog merges in unrelated component resources.
    return dg.Definitions(assets=assets, resources=resources,
      jobs=[definitions.resolve_job_def('plaud_import')])

# .. imports, comments and docstring text that read differently now
#    from gppu import Env
#    from gppu import glob, glob_dict

# endregion


# region - RAN Systems/lake/plaud/plaud_auth.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/lake/plaud/plaud_auth.py
def _load_config() -> PlaudAuthConfig:
    from lake.plaud.plaud_importer import PlaudImporterConfig
    from lake.common import graph_configuration

    # TEMPORARY: Alex, 2026-09-21, requested recovery while gppu is being worked on.
    # Replace this bootstrap once the canonical gppu entry supplies these settings and is verified.
    graph_configuration.environment()
    importer = PlaudImporterConfig.from_mapping(glob("plaud"))
    return _auth_config_from_mapping(glob("plaud_auth"), importer.client)

# .. imports, comments and docstring text that read differently now
#    from gppu import Env
#    from gppu import glob

# endregion


# region - RAN Systems/lake/plaud/plaud_console.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/lake/plaud/plaud_console.py
def main() -> int:
    from lake.common.graph_configuration import environment
    environment()
    Logger.init_logger("recordings")
    config = PlaudConsoleConfig.from_mapping(glob("plaud"))
    textlake = glob_dict('textlake')
    client = PlaudClient(
        config.client,
        urlrequest.urlopen,
        PlaudVaultRefreshTokenStore(config.client),
    )
    result = PlaudConsoleExporter(config, client, urlrequest.urlopen, textlake).run()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, Logger  # type: ignore
#    from gppu import glob, glob_dict

# endregion


# region - RAN Systems/lake/plaud/plaud_importer.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/lake/plaud/plaud_importer.py
def run_import() -> dict:
    from file_indexer.database_schema import FileDatabase
    from lake.common.graph_configuration import environment
    from Transcriber.recordings.db import AssetsDB, RecordingsDB

    environment()
    Logger.init_logger('recordings')
    config = PlaudImporterConfig.from_mapping(glob('plaud'))
    textlake = glob_dict('textlake')
    client = PlaudClient(
        config.client,
        urlrequest.urlopen,
        PlaudVaultRefreshTokenStore(config.client),
    )
    with (
        RecordingsDB() as recordings,
        AssetsDB() as assets,
        FileDatabase() as files,
    ):
        result = PlaudImporter(
            config,
            client,
            recordings,
            assets,
            files,
            urlrequest.urlopen,
            textlake,
        ).run()
    return result

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, Logger  # type: ignore
#    from gppu import glob, glob_dict

# endregion


# region - RAN Systems/lake/plaud/tables.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/lake/plaud/tables.py
@dg.asset(key=['plaud', 'recordings'], group_name='Transcriber', kinds={'dbt', 'postgres'}, deps=[TRANSCRIPTIONS],
          description='Plaud recordings as Plaud understands them, and the segments of their transcripts, from the raw files; linkml/plaud.yaml.',
          metadata={'dagster/table_name': 'everything.plaud.recordings', 'also': 'everything.plaud.segments'})
def plaud_recordings(context: dg.AssetExecutionContext, dbt_plaud: DbtResource) -> dg.MaterializeResult:
    root = f"{glob_dict('textlake')['root']}/sources/*/recordings/plaud"   # the textlake rules' sources/{YYYY}/recordings/{provider}
    return build(context, dbt_plaud, 'everything.plaud.recordings', {'recording_root': root})

# .. imports, comments and docstring text that read differently now
#    from gppu import Env
#    from gppu import glob_dict
#    from lake.common.graph_configuration import postgres

# endregion


# region - RAN Systems/lake/providers/__init__.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/lake/providers/__init__.py
def templates() -> dict[str, str]:
  """The naming templates every file Container places DataObjects by."""
  return location_templates(glob_dict('')['sources']['uri_templates'])

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, FileSystem, Provider
#    from gppu import glob_dict

# endregion


# region - RAN Systems/lake/providers/m365.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import DataObject, Provider, y2uri

# endregion


# region - RAN Systems/lake/providers/plaud.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/lake/providers/plaud.py
class Plaud(Provider):
  """Plaud recordings, each directly inside plaud:// and read-only. Credentials come from the plaud configuration."""
  scheme = 'plaud'

  def __init__(self, connection: dict[str, object] | None = None) -> None:
    super().__init__(connection)
    self._client: PlaudClient | None = None

  def _connect(self) -> PlaudClient:
    if self._client is None:
      from lake.plaud.dagster import PlaudCredentialsResource, PlaudResource
      config = glob_dict('plaud')
      settings = glob_dict('plaud_credentials')
      credentials = PlaudCredentialsResource(**settings,
        refresh_token=full_path(settings['refresh_token_file']).read_text(encoding='utf-8').strip())
      resource = PlaudResource(provider=config['provider'], api_base=config['api_base'], credentials=credentials)
      configured, self._client = resource.connect()
      self._page_size = configured.page_size
    return self._client

  def join(self, uri: y2uri, path: str) -> y2uri:
    """Paths here are uri-escaped ids, joined as they are."""
    return y2uri(uri) / str(path) if str(path) else y2uri(uri)

  @staticmethod
  def _identity(uri: y2uri) -> str:
    """The recording id uri names, or an empty string for plaud:// itself."""
    parsed = urlsplit(str(uri))
    if parsed.scheme != Plaud.scheme:
      raise ValueError(f'{uri}: Plaud reaches plaud uris')
    path = (parsed.netloc + parsed.path).strip('/')
    if '/' in path:
      raise ValueError('A recording is directly inside its Plaud Location')
    return unquote(path)

  def ls(self, uri: y2uri) -> list[dict[str, object]]:
    from lake.plaud.plaud_importer import _validate_list_entry
    if self._identity(uri):
      raise NotADirectoryError(uri)
    client = self._connect()
    return [{'name': quote(_validate_list_entry(row).plaud_id, safe=''), 'type': 'file',
             'size': len(json.dumps(row).encode()), 'gppu': {'record': row}}
            for row in client.iter_files(page_size=self._page_size)]

  def read(self, uri: y2uri) -> DataObject:
    from lake.plaud.plaud_importer import _validate_detail
    identity = self._identity(uri)
    if not identity:
      raise IsADirectoryError(uri)
    return DataObject(uri, _validate_detail(self._connect().get_file(identity), identity), identity)

  @contextmanager
  def audio(self, obj: DataObject) -> Iterator[DataObject | None]:
    """Yield validated original audio while its temporary stream remains open."""
    from lake.plaud.plaud_importer import _download_audio, _EXTENSION_CONTENT_TYPES
    detail = obj.content
    if detail['presigned_url'] is None:
      yield None
      return
    with tempfile.TemporaryDirectory(prefix='plaud-audio-') as directory:
      paths = {extension: Path(directory) / ('audio.' + extension) for extension in _EXTENSION_CONTENT_TYPES}
      audio, _ = _download_audio(detail['presigned_url'], paths, self._connect().urlopen)
      with audio.path.open('rb') as stream:
        yield DataObject(obj.uri / 'audio', stream, obj.identity,
                         kind='recording_audio', name=audio.path.suffix.lstrip('.'), parent=obj)

  def texts(self, obj: DataObject) -> Iterator[DataObject]:
    """Return Plaud's original source and note blocks without transformation."""
    from lake.plaud.plaud_importer import _require_mapping, _require_string, _text_content_type, _validate_path_component
    for group, field in (('source', 'source_list'), ('note', 'note_list')):
      for index, raw in enumerate(obj.content[field]):
        block = _require_mapping(raw, f'Plaud {field} item')
        data_type = _require_string(block.get('data_type'), f'Plaud {field} data_type')
        _validate_path_component(data_type)
        text = self._connect().load_block_content(block)
        if not isinstance(text, str) or not text:
          raise RuntimeError('Plaud text block content is empty or not text')
        extension, _ = _text_content_type(text, group=group)
        uri = obj.uri / group / str(index) / quote(data_type, safe='')
        yield DataObject(uri, text.encode('utf-8'), obj.identity, kind='recording_' + group,
                         name=extension, parent=obj)

  @contextmanager
  def refresh(self, state: dict[str, Any], uri: y2uri) -> Iterator[tuple[Iterator[DataObject], Callable[[], None]]]:
    from lake.plaud.plaud_importer import _validate_list_entry
    if self._identity(uri):
      raise NotADirectoryError(uri)
    scope = str(uri)
    previous = state[scope] if scope in state else {}
    pending = {}
    client = self._connect()
    def objects() -> Iterator[DataObject]:
      from dataclasses import replace
      from lake.plaud.plaud_importer import _strip_manifest_links
      for row in client.iter_files(page_size=self._page_size):
        identity = _validate_list_entry(row).plaud_id
        if identity in pending:
          raise ValueError('Plaud returned duplicate recording IDs')
        pending[identity] = row
        if identity not in previous or previous[identity] != row:
          # The recording without its links, its source and note blocks, then its audio, as plaud.dagster keeps them.
          obj = self.read(y2uri(uri) / quote(identity, safe=''))
          yield replace(obj, content=_strip_manifest_links(obj.content))
          yield from self.texts(obj)
          with self.audio(obj) as audio:
            if audio is None:
              del pending[identity]   # audio not yet available: read again by the next refresh (plaud.dagster PENDING_IDS)
              continue
            yield audio
    yield objects(), lambda: state.update({scope: pending})

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, DataObject, Provider, y2uri
#    from gppu import glob_dict

# endregion


# region - RAN Systems/lake/providers/telegram.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import DataObject, Provider, y2uri

# endregion


# region - RAN Systems/lake/providers/test_m365_refresh.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import Container

# endregion


# region - RAN Systems/lake/providers/test_m365_types.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import Container, y2uri

# endregion


# region - RAN Systems/lake/providers/test_providers.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import DataObject, y2uri
#    from gppu import Location

# endregion


# region - RAN Systems/lake/serve.py as of 2026-11-20 (1)

# .. gone
if __name__ == '__main__':
  asyncio.run(LakeAPI(name='lake', environment='RAN', config=Path(__file__).with_name('serve.yaml')).run())

# .. imports, comments and docstring text that read differently now
#    from gppu import APIApp, Env

# endregion


# region - RAN Systems/lake/sources/__init__.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/lake/sources/__init__.py
def stored(read):
  """Retained console dumper naming; scheduled refreshes do not use this path."""
  naming = glob_dict('sources')['uri_templates']
  templates = {'date': naming['m365_original_date'], 'filename': naming['m365_file'],
               'attachment': naming['m365_attachment'], 'photo': naming['m365_photo']}
  templates = jinja.overlay(loader=DictLoader(templates))

  def object_path(obj):
    if obj.parent is not None:
      return str(templates.get_template(obj.kind).render(object_path=object_path(obj.parent),
                                           filename=obj.name, uri=str(obj.uri)))
    uri = urlsplit(str(obj.uri))
    value = templates.get_template('date').render(it=obj.content, uri=str(obj.uri))
    date = datetime.fromisoformat(value) if value else None
    return str(templates.get_template('filename').render(uri=str(obj.uri), endpoint=uri.path,
      tenant=uri.netloc, date=date, inside='.', it=obj.content, unquote=unquote,
      identity=obj.identity, filename=obj.name))

  for obj in read.records():
    if isinstance(obj, DataObject):
      yield str(PurePosixPath(tables()['sources'][read.uid]['inside']) / object_path(obj)), obj.content, obj.identity
    else:
      yield obj

# .. imports, comments and docstring text that read differently now
#    from gppu import DataObject, Env
#    from gppu import glob_dict
#    from lake.common.graph_configuration import tables

# endregion


# region - RAN Systems/lake/sources/m365.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import DataObject

# endregion


# region - RAN Systems/lake/sources/test_objects.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import Container, DataObject, Env, FileSystem

# endregion


# region - RAN Systems/ld/api.py as of 2026-11-20 (1)

# .. gone
if __name__ == '__main__':
  Env.from_env(app_path=Path(sys.argv[1]) if sys.argv[1:] else None)   # a folder given: its config.yaml; none: gppu's, beside this file
  asyncio.run(LDAPI(name='ld').run(), loop_factory=asyncio.SelectorEventLoop)   # psycopg's async connections need the selector loop on Windows

# .. imports, comments and docstring text that read differently now
#    from gppu import APIApp, Env, ld

# endregion


# region - RAN Systems/ld/api_v2.py as of 2026-11-20 (1)

# .. gone
if __name__ == '__main__':
    folder = Path(sys.argv[1]) if sys.argv[1:] else LINKML
    Env.from_env(name='ld', config=folder / 'config.yaml')
    asyncio.run(LDAPI(name='ld').run(), loop_factory=asyncio.SelectorEventLoop)   # psycopg's async connections need the selector loop on Windows

# .. imports, comments and docstring text that read differently now
#    from gppu import APIApp, Env

# endregion


# region - RAN Systems/ld/check_fileindexer.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/ld/check_fileindexer.py
@contextmanager
def lake_served(folder: Path):
    """The Lake's API over a folder of the check's, laid out by the Lake's lines in RAN's locations and served here, with the catalog's at
    /lake/catalog as the Lake's service serves it, its address: the Lake the run's indexes are sent to, so none reaches production's,
    which keeps what it is given; it loads them into the catalog, the checked API's fs."""
    folder.mkdir(parents=True, exist_ok=True)
    Env.init(environment='RAN')   # the Lake's lines, its row in RAN's locations
    places = GppuCatalog({'connections': {'file': {'provider': 'file'}},
                          'locations': {'lake': {'path': '', 'connection': 'file', 'canonical': folder.as_uri()}}})
    app = FastAPI()
    app.mount('/lake/catalog', catalog_api(CONTENTS))   # the catalog first: the Lake's paths are uris, and /lake would take /lake/catalog's
    app.mount('/lake', lakes.api(lakes.Lake(places, folder.as_uri(), CONTENTS)))
    with TestClient(app) as client:
        class Through(BaseHTTPRequestHandler):
            def answer(self):
                body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                r = client.request(self.command, self.path, content=body)
                self.send_response(r.status_code)
                self.send_header('Content-Type', r.headers.get('content-type', 'application/json'))
                self.send_header('Content-Length', str(len(r.content)))
                self.end_headers()
                self.wfile.write(r.content)

            do_GET = do_POST = answer

            def log_message(self, *_):
                pass
        http = HTTPServer(('127.0.0.1', 0), Through)
        threading.Thread(target=http.serve_forever, daemon=True).start()
        try:
            yield f'http://127.0.0.1:{http.server_port}/lake'
        finally:
            http.shutdown()

# .. imports, comments and docstring text that read differently now
#    from gppu import Env

# endregion


# region - RAN Systems/ld/fileindexer/cli.py as of 2026-11-20 (2)

# .. changed; the one of now is in RAN Systems/ld/fileindexer/cli.py
def ingest(catalog, store):
    """What is new in this host's locations to ingest, gppufs.yaml's ingest by their uris, each indexed recursively at the files
    level on its own and its indexes sent to the Lake: each location's run, or what stopped it, which does not stop the others."""
    host = socket.gethostname().split('.')[0].casefold()   # as the catalog's file uris name this host
    by_uri = {row['canonical']: uid for uid, row in catalog.locations.items()}
    ingested = {}
    for uri in glob('ingest')[host]:
        try:
            ingested[uri] = Indexer(catalog, store).index(by_uri[uri], '', 'files', 'recursive')
        except Exception as error:   # raised with the others once every location was ingested (main)
            ingested[uri] = error
    return ingested


# .. changed; the one of now is in RAN Systems/ld/fileindexer/cli.py
def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='FileIndexer through gppu Locations and Containers')
    parser.add_argument('--version', action='version', version='FileIndexer ' + __version__)
    parser.add_argument('--api', help='the address of another Linked Data API')
    parser.add_argument('--lake', help='the address of another Lake API, which the indexes a run writes are sent to')
    parser.add_argument('--drives', action='store_true', help="in this PC's WSL: its drives where WSL mounts them (gppufs.yaml)")
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('locations', help='Show configured Locations without reading their contents')
    commands.add_parser('stats', help='Show the current FileIndexer index')
    commands.add_parser('runs', help='Show FileIndexer run outcomes')
    fresh = commands.add_parser('freshness', help='Show last observations and completed whole-Location reads')
    fresh.add_argument('level', choices=LEVELS, nargs='?', default='files')
    queued = commands.add_parser('queue', help='Resume unread local Locations at the selected level')
    queued.add_argument('level', choices=LEVELS, nargs='?', default='files')
    queued.add_argument('scope', choices=('one level', 'recursive'), nargs='?', default='recursive')
    queued.add_argument('--allow', action='store_true', help='Alex explicitly authorized the restricted S1 archive selection')
    commands.add_parser('ingest', help="Index what is new in this host's locations to ingest (gppufs.yaml's ingest), each recursively")
    commands.add_parser('link', help="Add the files each session read, edited or wrote to the session's task, project or epic, proposed")
    sent = commands.add_parser('send', help="Send every index of one location on this host to the Lake, whatever copy the catalog holds")
    sent.add_argument('location')
    index = commands.add_parser('index', help='Index one selected Location or folder')
    index.add_argument('location')
    index.add_argument('level', choices=LEVELS, nargs='?', default='files')
    index.add_argument('scope', choices=('one level', 'recursive'), nargs='?', default='one level')
    index.add_argument('--container', default='', help='Path at the Location selecting its Container')
    index.add_argument('--path', default='', help='Folder path inside the Container')
    index.add_argument('--level', choices=LEVELS, dest='level_override')
    index.add_argument('--recursive', action='store_true')
    index.add_argument('--allow', action='store_true', help='Alex explicitly authorized this restricted S1 archive selection')
    words = sys.argv[1:]
    at = next((i for i, word in enumerate(words) if word in ('index', 'queue')), None)
    if at is not None:
        words = [*words[:at + 1], *('--allow' if word == 'allow' else word for word in words[at + 1:])]
    args = parser.parse_args(words)
    Env.from_env(name='gppufs', app_path=Path(__file__).parent)   # gppufs.yaml: Linked Data's addresses and where WSL mounts the drives
    Logger.init_logger('FileIndexer')
    if args.command is None:
        from .tui import FileIndexerApp
        index = FileIndexerDatabase(*opened(args.api, args.drives, args.lake))   # the TUI reads it as it read admin_ui's FileIndexer routes
        FileIndexerApp(database=index, api=index).run()
        return
    if args.command == 'link':   # reads Linked Data and this host's disk: no catalog of locations, no store
        ingested = glob('ingest')[socket.gethostname().split('.')[0].casefold()]   # the folders this host ingests, as ingest() names them
        print(json.dumps(link(args.api or glob('api'), ingested), ensure_ascii=False, indent=2))
        return
    catalog, store = opened(args.api, args.drives, args.lake)
    if args.command == 'locations':
        answer = [{'uid': uid, 'canonical': row['canonical'], 'parent': row['parent']}
                  for uid, row in catalog.locations.items()]
    elif args.command == 'stats':
        answer = FileIndexerDatabase(catalog, store).stats()
    elif args.command in ('runs', 'queue'):
        parser.error(RUNS)
    elif args.command == 'freshness':
        answer = freshness(catalog, store, args.level)
    elif args.command == 'ingest':
        answer = ingest(catalog, store)
    elif args.command == 'send':
        uid, below = selection(catalog, args.location)
        if below:
            parser.error(f'{args.location}: send takes a location, and this is a folder inside one')
        answer = store.send(uid, every=True)
    else:
        uid, selected_path = selection(catalog, args.location)
        if selected_path and (args.path or args.container):
            parser.error('Use a path address or Location with --container/--path')
        level = args.level_override if args.level_override is not None else args.level
        answer = Indexer(catalog, store).index(uid, selected_path or args.path, level,
                                               'recursive' if args.recursive else args.scope, args.container, allow=args.allow)
    print(json.dumps(answer, ensure_ascii=False, default=repr, indent=2))
    if args.command == 'ingest' and (failed := [run for run in answer.values() if isinstance(run, Exception)]):
        raise ExceptionGroup(f'{len(failed)} of the locations to ingest failed', failed)

# .. imports, comments and docstring text that read differently now
#    arguments, another with --api, at the addresses gppufs.yaml beside this file gives; what it reads kept in
#    from gppu import Env, Logger, glob

# endregion


# region - RAN Systems/ld/fileindexer/indexer.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import Location

# endregion


# region - RAN Systems/ld/fileindexer/runtime.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/ld/fileindexer/runtime.py
def opened(api=None, drives=False, lake=None):
    """The catalog of Linked Data's locations, at api or the configuration's, and the store over it, sending its indexes to the
    Lake at lake or the configuration's."""
    with httpx.Client(base_url=api or glob('api'), timeout=300) as client:
        answer = client.get('/fs/locations')   # every location: a list without a limit gives every match
        answer.raise_for_status()
    locations = catalog(answer.json()['items'], **({'file': Drives} if drives else {}))
    return locations, Store(locations, lake or glob('lake'))

# endregion


# region - RAN Systems/ld/projectmanager/__main__.py as of 2026-11-20 (2)

# .. changed; the one of now is in RAN Systems/ld/projectmanager/__main__.py
def setting(key: str):
    """A value of projectmanager.yaml; one it does not have is an error."""
    if (value := glob(key)) is None:
        raise KeyError(f'projectmanager.yaml has no {key}')
    return value


# .. gone
Env.from_env(name='projectmanager', app_path=Path(__file__).parent)

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, glob

# endregion


# region - RAN Systems/ld/sessionmanager/__main__.py as of 2026-11-20 (2)

# .. changed; the one of now is in RAN Systems/ld/sessionmanager/__main__.py
def setting(key: str):
    """A value of sessionmanager.yaml; one it does not have is an error."""
    if (value := glob(key)) is None:
        raise KeyError(f'sessionmanager.yaml has no {key}')
    return value


# .. gone
Env.from_env(name='sessionmanager', app_path=Path(__file__).parent)

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, glob

# endregion


# region - RAN Systems/ld/sessionmanager/link.py as of 2026-11-20 (2)

# .. changed; the one of now is in RAN Systems/ld/sessionmanager/link.py
def setting(key: str):
    """A value of sessionmanager.yaml; one it does not have is an error."""
    if (value := glob(key)) is None:
        raise KeyError(f'sessionmanager.yaml has no {key}')
    return value


# .. gone
Env.from_env(name='sessionmanager', app_path=Path(__file__).parent)

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, glob

# endregion


# region - RAN Systems/ld/sessionmanager/rules.py as of 2026-11-20 (1)

# .. changed; the one of now is in RAN Systems/ld/sessionmanager/rules.py
@cache
def load():
    """The rules as spaCy reads them; a rule missing what it needs is an error."""
    rules = glob('rules')
    if not isinstance(rules, list):
        raise ValueError('sessionmanager.yaml rules must be a list')
    nlp = spacy.blank('en')
    ruler = nlp.add_pipe('span_ruler', config={'validate': True, 'phrase_matcher_attr': 'LOWER'})
    ids, patterns = set(), []
    for rule in rules:
        rid, dest, required, entities = (rule[key] for key in ('id', 'dest', 'requires', 'entities'))
        if not isinstance(rid, str) or not rid.strip() or rid in ids:
            raise ValueError('each rule needs a unique, nonempty id')
        ids.add(rid)
        if not isinstance(dest, str) or not dest.strip():
            raise ValueError(f'{rid}: dest must be a work id or previous')
        if not isinstance(required, list) or not required or not set(required) <= entities.keys():
            raise ValueError(f'{rid}: requires must name labels that have patterns in this rule')
        for label, alternatives in entities.items():
            for pattern in alternatives:
                patterns.append({'id': rid, 'label': label, 'pattern': pattern})
    if patterns:
        ruler.add_patterns(patterns)
    return nlp, rules

# endregion


# region - RAN _config/config.yaml as of 2026-11-20

# .. the lines that are gone or read differently now
#    log_file: ~/.cache/gppu/hosts.log
#    server_mounts: >-
#        {%- set mounts = {} -%}
#        {%- for uid in ['public', 'netbackup', 'lake', 'everything', 'downloads', 'sd-agents'] -%}
#        {%- set location = glob('locations')[uid] -%}
#        {%- set _ = mounts.update({location.get('at', glob('hosts/s1/mount') ~ '/' ~ location['smb/s1']):
#                                   '//' ~ glob('hosts/s1/hostname') ~ '/' ~ location['smb/s1']}) -%}
#        {%- endfor -%}
#        {{- mounts -}}
#    ssh:

# endregion


# region - RAN _config/topology/locations.yaml as of 2026-11-20

# .. the lines that are gone or read differently now
#        sessionfolder: "{% set found = re.search('([^/]+)/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/(.+)$', path) %}timeseries/{{ start.year }}/Sessions/{{ '%02d' % start.month }}/{{ record.data['harness'] }}/{{ found.group(1) }}/{{ record.data['uid'] }}/{{ found.group(2) }}"

# endregion


# region - CRAP Processes/Transcriber/recordings/cli.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Processes/Transcriber/recordings/cli.py
def _bootstrap_env():
    """Initialize the shared lake configuration through gppu Env."""
    Env.from_env(name='lake', app_path=Path(__file__).resolve().parents[3] / 'Projects/lake')
    init_logger('recordings')

# .. imports, comments and docstring text that read differently now
#    # REVIEW: requires gppu dev-tui (top-level init_logger). Older gppu will ImportError.
#    from gppu import Env, init_logger  # type: ignore

# endregion


# region - CRAP Processes/plaud.standalone/plaud-omi-gd.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Processes/plaud.standalone/plaud-omi-gd.py
def main() -> int:
  init_logger('plaud')
  Vault.provider_set(VaultProviderAzure(AZURE_VAULT))
  access = token()
  service = build('drive', 'v3', cache_discovery=False,
                  credentials=Credentials.from_authorized_user_info(json.loads(Vault.get(DRIVE_SECRET))))
  root = service.files().get(fileId='root', fields='id').execute()['id']
  drive = Drive(service, root)
  audio_folder = drive.folder((RECORDINGS, SYSTEM))

  # A part with no credential says so and is skipped; the rest of the pass still happens.
  try: omi_key = Vault.get(OMI_SECRET)
  except ValueError:
    omi_key = ''
    Error(f'{OMI_SECRET} is not in the {AZURE_VAULT} vault — omi is skipped')
  vault_here = OBSIDIAN_NOTES.is_dir()
  if not vault_here:
    Error(f'{OBSIDIAN_NOTES.resolve()} does not exist — Obsidian notes are skipped')

  done = set(json.loads(LEDGER.read_text())) if LEDGER.exists() else set()
  collected = skipped = failed = 0
  page = 1
  while True:
    rows = plaud(f'/open/third-party/files/?page={page}&page_size={PAGE_SIZE}', access)['data']
    if not rows: break
    for row in rows:
      if row['id'] in done:
        skipped += 1
        continue
      try:
        record = plaud(f"/open/third-party/files/{row['id']}", access)
        turns = json.loads(block(record.get('source_list'), 'transaction') or '[]')
        summary = block(record.get('note_list'), 'auto_sum_note')
        Info(base(record))

        audio_id = ''
        if record.get('presigned_url'):
          audio_id = drive.put(audio_folder, f'{base(record)}.mp3',
                    b'' if DRY else fetch(record['presigned_url']), 'audio/mpeg', stem(record))

        assets = drive.folder((TRANSCRIPTS, SYSTEM, base(record)))
        drive.put(assets, asset(record, 'manifest'), manifest(record, turns, summary).encode(),
                  'text/markdown', f'{stem(record)} manifest')
        if turns:
          drive.put(assets, asset(record, 'transcript'), transcript_text(record, turns).encode(),
                    'text/markdown', f'{stem(record)} - transcript')
          if summary:
            drive.put(assets, asset(record, 'summary'),
                      POSTER.sub('', summary.lstrip()).rstrip().encode(), 'text/markdown',
                      f'{stem(record)} - summary')
          if vault_here and not DRY and not noted(record['id']):
            link = f'https://drive.google.com/file/d/{audio_id}/view' if audio_id else ''
            (OBSIDIAN_NOTES / f'{started_at(record):%Y-%m-%d %H%M%S} - '
             f'{title(record) or record["id"]}.md').write_text(
               note_text(record, turns, summary, link), encoding='utf-8')
          if omi_key: omi_put(omi_key, record, turns)
        else:
          Warn(f'  no transcript in Plaud — audio and manifest only')
        done.add(row['id'])
        collected += 1
      except Exception as failure:
        Error(f"{row.get('name') or row['id']}: {type(failure).__name__}: {failure}")
        failed += 1
    page += 1

  if not DRY: LEDGER.write_text(json.dumps(sorted(done), indent=1))
  Info(f'collected={collected} skipped={skipped} failed={failed}')
  return 1 if failed else 0

# .. imports, comments and docstring text that read differently now
#    from gppu import Error, Info, Vault, VaultProviderAzure, Warn, init_logger

# endregion


# region - CRAP Processes/plaud.standalone/plaud_sync.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Processes/plaud.standalone/plaud_sync.py
def main() -> int:
  sys.stdout.reconfigure(encoding='utf-8')   # recording titles are not ASCII
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument('--dry-run', action='store_true',
                      help='report what each sink would receive; write nothing')
  args = parser.parse_args()
  Env.from_env(name='plaud', app_path=APP_DIR)
  init_logger('plaud')
  try:
    return asyncio.run(Run(dry_run=args.dry_run)())
  except Exception as failure:
    # Setup — credentials, config, the token cache — fails before any recording
    # is reached. Say what is missing; a traceback is not a report.
    Error(reason(failure))
    return 1

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, Error, Info, Warn, glob, glob_dict, init_logger

# endregion


# region - CRAP Projects/FileIndexer/cli.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Projects/FileIndexer/cli.py
def main():
  for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
      stream.reconfigure(encoding='utf-8')
  parser = argparse.ArgumentParser(description='FileIndexer through gppu Locations and Containers')
  parser.add_argument('--version', action='version', version='FileIndexer ' + __version__)
  commands = parser.add_subparsers(dest='command')
  commands.add_parser('locations', help='Show configured Locations without reading their contents')
  commands.add_parser('stats', help='Show the current FileIndexer index')
  commands.add_parser('runs', help='Show FileIndexer run outcomes')
  fresh = commands.add_parser('freshness', help='Show last observations and completed whole-Location reads')
  fresh.add_argument('level', choices=LEVELS, nargs='?', default='files')
  queued = commands.add_parser('queue', help='Resume unread local Locations at the selected level')
  queued.add_argument('level', choices=LEVELS, nargs='?', default='files')
  queued.add_argument('scope', choices=('one level', 'recursive'), nargs='?', default='recursive')
  queued.add_argument('--allow', action='store_true', help='Alex explicitly authorized the restricted S1 archive selection')
  index = commands.add_parser('index', help='Index one selected Location or folder')
  index.add_argument('location')
  index.add_argument('level', choices=LEVELS, nargs='?', default='files')
  index.add_argument('scope', choices=('one level', 'recursive'), nargs='?', default='one level')
  index.add_argument('--container', default='', help='Path at the Location selecting its Container')
  index.add_argument('--path', default='', help='Folder path inside the Container')
  index.add_argument('--level', choices=LEVELS, dest='level_override')
  index.add_argument('--recursive', action='store_true')
  index.add_argument('--allow', action='store_true', help='Alex explicitly authorized this restricted S1 archive selection')
  words = sys.argv[1:]
  if words and words[0] in ('index', 'queue'):
    words = [words[0], *('--allow' if word == 'allow' else word for word in words[1:])]
  args = parser.parse_args(words)
  init_logger('FileIndexer')
  if args.command is None:
    from .tui import FileIndexerApp
    FileIndexerApp().run()
    return
  catalog, store = opened()
  with store:
    if args.command == 'locations':
      answer = [{'uid': uid, 'canonical': row['canonical'], 'parent': row['parent']}
                for uid, row in catalog.locations.items()]
    elif args.command == 'stats':
      answer = FileIndexerDatabase(catalog, store).stats()
    elif args.command == 'runs':
      answer = store.runs()
    elif args.command == 'freshness':
      answer = freshness(catalog, store, args.level)
    elif args.command == 'queue':
      results = queue(catalog, store, args.level, args.scope,
        report=lambda value: print(json.dumps(value, ensure_ascii=False, default=str), flush=True), allow=args.allow)
      if any(row['phase'] == 'failed' for row in results):
        raise SystemExit(1)
      return
    else:
      uid, selected_path = selection(catalog, args.location)
      if selected_path and (args.path or args.container):
        parser.error('Use a path address or Location with --container/--path')
      level = args.level_override if args.level_override is not None else args.level
      answer = Indexer(catalog, store).index(uid, selected_path or args.path, level,
        'recursive' if args.recursive else args.scope, args.container, allow=args.allow)
    print(json.dumps(answer, ensure_ascii=False, default=str, indent=2))

# .. imports, comments and docstring text that read differently now
#    from gppu import init_logger

# endregion


# region - CRAP Projects/FileIndexer/indexer.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import Location

# endregion


# region - CRAP Projects/FileIndexer/tests/test_indexer.py as of 2026-11-20 (2)

# .. changed; the one of now is in CRAP Projects/FileIndexer/tests/test_indexer.py
def test_failed_enumeration_preserves_children_and_records_failure(persisted, monkeypatch):
  from gppu import Container
  root, catalog, store, indexer = persisted
  (root / 'retained.txt').write_text('retained')
  indexer.index('fixture', level='files')
  def failed(*args, **kwargs):
    raise PermissionError('unreadable')
    yield
  monkeypatch.setattr(Container, 'walk', failed)
  with pytest.raises(PermissionError, match='unreadable'):
    indexer.index('fixture', level='files')
  assert store.contents('fixture')[0]['name'] == 'retained.txt'
  run = store.runs()[0]['run']
  assert run['phase'] == 'failed' and 'PermissionError' in run['error']


# .. changed; the one of now is in CRAP Projects/FileIndexer/tests/test_indexer.py
def test_api_container_is_indexed_without_filesystem_access(persisted):
  from gppu import DataObject, Provider
  root, _, store, _ = persisted
  class Source(Provider):
    scheme = 'api'
    def ls(self, uri):
      assert uri == 'api://fixture'
      return [{'name': 'object', 'type': 'file', 'size': None}]
    def read(self, uri):
      return DataObject(uri, {'id': 'native-object'}, 'native-object')
  catalog = GppuCatalog({'connections': {}, 'locations': {
    'api-fixture': {'canonical': 'api://fixture'}}}, location_types={'api': Source})
  Indexer(catalog, store).index('api-fixture', level='handlers')
  assert store.contents('api-fixture')[0]['indexed']['object']['identity'] == 'native-object'

# endregion


# region - CRAP Projects/FileIndexer/tests/test_tui.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import Container, FileSystem

# endregion


# region - CRAP Projects/file_indexer/database_schema.py as of 2026-11-20 (2)

# .. changed; the one of now is in CRAP Projects/file_indexer/database_schema.py
class FileDatabase(_PGBase):
    """
    Normalized PostgreSQL database for file index.

    Schema:
    - server_types: Protocol types with CHAR(16) id (local, smb, s3, etc.)
    - locations: Storage locations with CHAR(16) id (sd, xphotos, etc.)
    - file_paths: Directory paths within locations
    - files: Individual files with extension and file_type_id FK

    Lookup tables (CHAR(16) string keys):
    - file_type_classes: Categories (image, video, code, etc.)
    - file_types: Normalized types (jpeg, png, python, etc.) with class_id FK
    - extension_mappings: Extension → file_type_id lookup
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self._location_cache = {}
        self._path_cache = {}
        self._file_type_cache = {}

    # --
    #    Lookup table sync
    # --

    def sync_lookup_tables(self, server_types: Dict, file_type_classes: Dict) -> Tuple[List[str], List[str]]:
        """
        Sync lookup tables from config to database.
        Auto-inserts missing entries. Returns (errors, inserted).

        Args:
            server_types: {type_id: {uri_scheme, description}}
            file_type_classes: {class_id: {description, types: {type_id: [extensions]}}}

        Returns:
            Tuple of (error messages, inserted entries)
        """
        errors = []
        inserted = []

        # Build derived structures from file_type_classes
        config_file_types = {}   # file_type_id -> class_id
        config_extensions = {}   # extension -> file_type_id

        for class_id, class_data in file_type_classes.items():
            if class_data and 'types' in class_data:
                for file_type_id, extensions in class_data['types'].items():
                    config_file_types[file_type_id] = class_id
                    for ext in extensions:
                        config_extensions[ext] = file_type_id

        with self.cursor() as cur:
            # -- Server Types (CHAR(16) PK) --
            cur.execute("SELECT id, uri_scheme FROM server_types")
            db_server_types = {row['id'].strip(): row['uri_scheme'].strip() for row in cur.fetchall()}

            for type_id, cfg in server_types.items():
                if type_id not in db_server_types:
                    cur.execute(
                        "INSERT INTO server_types (id, uri_scheme, description) VALUES (%s, %s, %s)",
                        (type_id, cfg.get('uri_scheme', 'file'), cfg.get('description', ''))
                    )
                    inserted.append(f"server_types: {type_id}")
                elif db_server_types[type_id] != cfg.get('uri_scheme'):
                    errors.append(f"server_types[{type_id}].uri_scheme: config={cfg.get('uri_scheme')}, db={db_server_types[type_id]}")

            # -- File Type Classes (CHAR(16) PK) --
            cur.execute("SELECT id FROM file_type_classes")
            db_classes = {row['id'].strip() for row in cur.fetchall()}

            for class_id, class_data in file_type_classes.items():
                if class_id not in db_classes:
                    cur.execute(
                        "INSERT INTO file_type_classes (id, description) VALUES (%s, %s)",
                        (class_id, class_data.get('description', '') if class_data else '')
                    )
                    db_classes.add(class_id)
                    inserted.append(f"file_type_classes: {class_id}")

            # -- File Types (CHAR(16) PK) --
            cur.execute("SELECT id, class_id FROM file_types")
            db_file_types = {row['id'].strip(): row['class_id'].strip() for row in cur.fetchall()}

            for ft_id, class_id in config_file_types.items():
                if class_id not in db_classes:
                    errors.append(f"file_types[{ft_id}]: references unknown class '{class_id}'")
                    continue

                if ft_id not in db_file_types:
                    cur.execute(
                        "INSERT INTO file_types (id, class_id) VALUES (%s, %s)",
                        (ft_id, class_id)
                    )
                    db_file_types[ft_id] = class_id
                    inserted.append(f"file_types: {ft_id} -> {class_id}")
                elif db_file_types[ft_id] != class_id:
                    cur.execute(
                        "UPDATE file_types SET class_id = %s WHERE id = %s",
                        (class_id, ft_id)
                    )
                    inserted.append(f"file_types: {ft_id} class {db_file_types[ft_id]} -> {class_id}")

            # -- Extension Mappings --
            cur.execute("SELECT extension, file_type_id FROM extension_mappings")
            db_extensions = {row['extension'].strip(): row['file_type_id'].strip() for row in cur.fetchall()}

            for ext, ft_id in config_extensions.items():
                if ft_id not in db_file_types:
                    errors.append(f"extension_mappings[{ext}]: references unknown file_type '{ft_id}'")
                    continue

                if ext not in db_extensions:
                    cur.execute(
                        "INSERT INTO extension_mappings (extension, file_type_id) VALUES (%s, %s)",
                        (ext, ft_id)
                    )
                    inserted.append(f"extension_mappings: .{ext} -> {ft_id}")
                elif db_extensions[ext] != ft_id:
                    cur.execute(
                        "UPDATE extension_mappings SET file_type_id = %s WHERE extension = %s",
                        (ft_id, ext)
                    )
                    inserted.append(f"extension_mappings: .{ext} {db_extensions[ext]} -> {ft_id}")

        return errors, inserted

    # --
    #    File type resolution
    # --

    def resolve_file_type(self, extension: str) -> tuple:
        """
        Resolve file_type_id and class_id from extension.

        Returns:
            Tuple of (file_type_id, class_id) or (None, None) if unknown

        Blank/None extension → ('binary', 'binary') (t_7abd9bd6).
        Extensionless files are overwhelmingly content-addressed blobs
        (M365 backup hashes, Telegram media downloads, mbox archives) —
        `binary` is the correct catch-all. Per-stem detection of
        literate files (README, LICENSE, Makefile, Dockerfile) is a
        follow-up if it becomes valuable.
        """
        ext = (extension or '').lower().lstrip('.')

        if ext in self._file_type_cache:
            return self._file_type_cache[ext]

        if ext == '':
            result = ('binary', 'binary')
            self._file_type_cache[ext] = result
            return result

        with self.cursor() as cur:
            cur.execute("""
                SELECT em.file_type_id, ft.class_id
                FROM extension_mappings em
                JOIN file_types ft ON em.file_type_id = ft.id
                WHERE em.extension = %s
            """, (ext,))

            row = cur.fetchone()
            if row:
                result = (row['file_type_id'].strip(), row['class_id'].strip())
                self._file_type_cache[ext] = result
            else:
                # t_11163261: do NOT cache (None, None). A long-running loader
                # would otherwise pin negative results and ignore extension_mappings
                # rows inserted later (by sync_lookup_tables in another process,
                # or by a future in-process sync). Unknown extensions are rare;
                # re-querying on each miss is cheap.
                result = (None, None)

            return result

    # --
    #    Location operations
    # --

    def get_or_create_location(self, location_id: str, server_type: str,
                                hostname: Any = _UNSET, uri_prefix: Any = _UNSET,
                                description: Any = _UNSET) -> str:
        """Get or create a location and refresh only supplied metadata fields."""
        location_id = location_id.strip()[:16]
        if not server_type:
            raise ValueError("server_type is required")

        optional_fields = {
            'hostname': hostname,
            'uri_prefix': uri_prefix,
            'description': description,
        }
        update_columns = ['server_type_id = EXCLUDED.server_type_id']
        update_columns.extend(
            f"{column} = EXCLUDED.{column}"
            for column, value in optional_fields.items()
            if value is not _UNSET
        )
        insert_values = {
            column: None if value is _UNSET else value
            for column, value in optional_fields.items()
        }

        with self.cursor() as cur:
            cur.execute(f"""
                INSERT INTO locations (id, server_type_id, hostname, uri_prefix, description)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    {', '.join(update_columns)}
            """, (
                location_id,
                server_type,
                insert_values['hostname'],
                insert_values['uri_prefix'],
                insert_values['description'],
            ))

        self._location_cache[location_id] = True
        return location_id

    def update_location_stats(self, location_id: str) -> Dict[str, Any]:
        """Update locations.last_indexed + files_indexed from current file count.

        Call once at the end of a loader run for `location_id`. Counts files
        actually present (not delta), so it's idempotent and self-healing
        across crashed/partial runs.

        Returns: {'location_id': ..., 'files_indexed': N, 'last_indexed': ts}
        """
        location_id = location_id.strip()[:16]
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE locations l
                   SET last_indexed = CURRENT_TIMESTAMP,
                       files_indexed = COALESCE((
                         SELECT count(*)
                           FROM files f
                           JOIN file_paths fp ON f.path_id = fp.id
                          WHERE fp.location_id = l.id
                       ), 0)
                 WHERE l.id = %s
                 RETURNING id, last_indexed, files_indexed
                """,
                (location_id,),
            )
            row = cur.fetchone()
            if not row:
                return {
                    'location_id': location_id,
                    'files_indexed': 0,
                    'last_indexed': None,
                    'updated': False,
                }
            return {
                'location_id': row['id'].strip() if isinstance(row['id'], str) else row['id'],
                'files_indexed': row['files_indexed'],
                'last_indexed': row['last_indexed'],
                'updated': True,
            }

    # --
    #    Path operations
    # --

    def get_or_create_path_id(self, location_id: str, path: str,
                               parent_path_id: Optional[int] = None,
                               folder_class_id: Optional[str] = None) -> int:
        """Get or create a file path entry.

        `parent_path_id` / `folder_class_id` are only applied on first
        creation (COALESCE keeps whatever is already stored on a repeat
        visit) — e.g. a file's directory is looked up again by
        `_process_file` after the walk already created the row with its
        real parent, and should not clobber that.
        """
        cache_key = f"{location_id}:{path}"
        if cache_key in self._path_cache:
            return self._path_cache[cache_key]

        with self.cursor() as cur:
            cur.execute("""
                INSERT INTO file_paths (location_id, path, parent_file_path_id, folder_class_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (location_id, path) DO UPDATE
                    SET parent_file_path_id = COALESCE(file_paths.parent_file_path_id, EXCLUDED.parent_file_path_id),
                        folder_class_id     = COALESCE(file_paths.folder_class_id, EXCLUDED.folder_class_id)
                RETURNING id
            """, (location_id, path, parent_path_id, folder_class_id))
            path_id = cur.fetchone()['id']

        self._path_cache[cache_key] = path_id
        return path_id

    def rollup_folder_stats(self, location_id: str) -> int:
        """Recompute recursive folder rollups for every `file_paths` row in
        `location_id`: child_file_count, child_folder_count, total_size,
        span_created, span_modified (`span` is a GENERATED column, derived
        by Postgres from the latter two — see sql/006_folder_classes.sql).

        Recursive across the WHOLE subtree, not just direct children — a
        folder_class row (e.g. a `.git` folder) naturally rolls up to
        zero/NULL since its contents were never walked/inserted into `files`.

        Call once per location after its file-processing loop completes.
        Two passes: (1) pull every file_paths row's parent link plus its own
        direct file aggregates; (2) walk rows in true tree-depth order
        (deepest first, via parent_file_path_id — NOT path string depth,
        since archive-member synthetic paths under sql/005 don't nest that
        way), folding each row's totals into its parent before writing back.

        Returns the number of file_paths rows updated.
        """
        with self.cursor() as cur:
            cur.execute(
                "SELECT id, parent_file_path_id FROM file_paths WHERE location_id = %s",
                (location_id,)
            )
            parent_of = {row['id']: row['parent_file_path_id'] for row in cur.fetchall()}

            cur.execute("""
                SELECT fp.id AS path_id,
                       count(f.id) AS file_count,
                       COALESCE(sum(f.file_size), 0) AS total_size,
                       min(f.date_created) AS min_created,
                       max(f.date_created) AS max_created,
                       min(f.date_modified) AS min_modified,
                       max(f.date_modified) AS max_modified
                FROM file_paths fp
                LEFT JOIN files f ON f.path_id = fp.id
                WHERE fp.location_id = %s
                GROUP BY fp.id
            """, (location_id,))
            acc = {
                row['path_id']: {
                    'file_count': row['file_count'] or 0,
                    'folder_count': 0,
                    'total_size': row['total_size'] or 0,
                    'min_created': row['min_created'],
                    'max_created': row['max_created'],
                    'min_modified': row['min_modified'],
                    'max_modified': row['max_modified'],
                }
                for row in cur.fetchall()
            }

        depth_cache: Dict[int, int] = {}

        def depth(path_id: int) -> int:
            if path_id in depth_cache:
                return depth_cache[path_id]
            parent_id = parent_of.get(path_id)
            d = 0 if parent_id is None else 1 + depth(parent_id)
            depth_cache[path_id] = d
            return d

        # Deepest first, so a directory's totals are complete before they're
        # folded into its parent.
        for path_id in sorted(parent_of, key=depth, reverse=True):
            parent_id = parent_of.get(path_id)
            if parent_id is None or parent_id not in acc:
                continue
            a, p = acc[path_id], acc[parent_id]
            p['file_count'] += a['file_count']
            p['folder_count'] += 1 + a['folder_count']
            p['total_size'] += a['total_size']
            p['min_created'] = _min_ts(p['min_created'], a['min_created'])
            p['max_created'] = _max_ts(p['max_created'], a['max_created'])
            p['min_modified'] = _min_ts(p['min_modified'], a['min_modified'])
            p['max_modified'] = _max_ts(p['max_modified'], a['max_modified'])

        with self.cursor() as cur:
            for path_id, a in acc.items():
                cur.execute("""
                    UPDATE file_paths
                       SET child_file_count   = %s,
                           child_folder_count = %s,
                           total_size         = %s,
                           span_created  = CASE WHEN %s::timestamptz IS NULL THEN NULL
                                                 ELSE tstzrange(%s, %s, '[]') END,
                           span_modified = CASE WHEN %s::timestamptz IS NULL THEN NULL
                                                 ELSE tstzrange(%s, %s, '[]') END
                     WHERE id = %s
                """, (
                    a['file_count'], a['folder_count'], a['total_size'],
                    a['min_created'], a['min_created'], a['max_created'],
                    a['min_modified'], a['min_modified'], a['max_modified'],
                    path_id,
                ))

        return len(acc)

    # --
    #    File operations
    # --

    def insert_file(self, file_data: Dict[str, Any]) -> int:
        """
        Insert or update a file record.

        Args:
            file_data: Dictionary with:
                Required: path_id, file_name
                Optional: extension, size, md5, date_created, date_modified, metadata
        """
        path_id = file_data.get('path_id')
        if not path_id:
            raise ValueError("path_id is required")

        file_name = file_data.get('file_name') or file_data.get('name')
        extension = file_data.get('extension', '')

        if not file_name:
            raise ValueError("file_name is required")

        # Normalize extension once at the insert boundary. resolve_file_type()
        # already lowercases internally, but the value persisted in
        # files.extension must also be lowercased — otherwise SP-loader writes
        # like 'IMG.DNG' / 'XYZ.PDF' land with mixed case and become invisible
        # to case-sensitive extension joins (the JOIN that drives % classified
        # uses files.extension = extension_mappings.extension verbatim). See
        # t_48468dc3 for the regression analysis.
        if extension:
            extension = extension.strip().lstrip('.').lower()

        # Resolve file_type_id from extension
        file_type_id, _ = self.resolve_file_type(extension)

        # Handle MD5
        md5_binary = None
        md5_value = file_data.get('md5')
        if md5_value:
            if isinstance(md5_value, str) and len(md5_value) == 32:
                try:
                    md5_binary = bytes.fromhex(md5_value)
                except ValueError:
                    pass
            elif isinstance(md5_value, bytes):
                md5_binary = md5_value

        metadata = file_data.get('metadata', {})

        with self.cursor() as cur:
            cur.execute("""
                INSERT INTO files (
                    path_id, file_name, extension, file_type_id,
                    file_size, md5, date_created, date_modified, metadata, indexed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (path_id, file_name, extension)
                DO UPDATE SET
                    file_type_id = COALESCE(EXCLUDED.file_type_id, files.file_type_id),
                    file_size = EXCLUDED.file_size,
                    md5 = COALESCE(EXCLUDED.md5, files.md5),
                    date_created = COALESCE(EXCLUDED.date_created, files.date_created),
                    date_modified = EXCLUDED.date_modified,
                    metadata = COALESCE(files.metadata, '{}'::jsonb)
                               || COALESCE(EXCLUDED.metadata, '{}'::jsonb),
                    indexed_at = CURRENT_TIMESTAMP
                RETURNING id
            """, (
                path_id,
                file_name,
                extension,
                file_type_id,
                file_data.get('size') or file_data.get('file_size'),
                md5_binary,
                file_data.get('date_created'),
                file_data.get('date_modified'),
                Json(metadata) if metadata else None
            ))

            return cur.fetchone()['id']

    def get_file(self, file_id: int) -> Optional[Dict[str, Any]]:
        """Get a file by ID using the file_uris view."""
        with self.cursor() as cur:
            cur.execute("SELECT * FROM file_uris WHERE id = %s", (file_id,))
            row = cur.fetchone()
            if row:
                result = dict(row)
                if result.get('md5'):
                    result['md5'] = result['md5'].hex()
                return result
            return None

    def search_files(self, filters: Dict[str, Any] = None, limit: int = None) -> List[Dict[str, Any]]:
        """Search files with filters."""
        where_clauses = ["1=1"]
        params = []

        if filters:
            if 'extension' in filters:
                where_clauses.append("extension = %s")
                params.append(filters['extension'])
            if 'file_type' in filters:
                where_clauses.append("file_type_id = %s")
                params.append(filters['file_type'])
            if 'file_type_class' in filters:
                where_clauses.append("file_type_class_id = %s")
                params.append(filters['file_type_class'])
            if 'location' in filters:
                where_clauses.append("location_id = %s")
                params.append(filters['location'])
            if 'min_size' in filters:
                where_clauses.append("file_size >= %s")
                params.append(filters['min_size'])
            if 'max_size' in filters:
                where_clauses.append("file_size <= %s")
                params.append(filters['max_size'])
            if 'directory_contains' in filters:
                where_clauses.append("directory ILIKE %s")
                params.append(f"%{filters['directory_contains']}%")

        where_sql = " AND ".join(where_clauses)
        limit_sql = f"LIMIT {limit}" if limit else ""

        with self.cursor() as cur:
            cur.execute(f"""
                SELECT * FROM file_uris
                WHERE {where_sql}
                ORDER BY date_modified DESC NULLS LAST
                {limit_sql}
            """, params)

            results = []
            for row in cur.fetchall():
                result = dict(row)
                if result.get('md5'):
                    result['md5'] = result['md5'].hex()
                results.append(result)

            return results

    # --
    #    Archive members (parent_file_id self-FK) — migration 005
    # --

    def insert_archive_member(self, parent_file_id: int, member_data: Dict[str, Any]) -> int:
        """
        Insert (or upsert) one archive-member file row.

        Identical to `insert_file` except `parent_file_id` is set on the row,
        which classifies the row as an archive member (vs. a top-level file).

        Args:
            parent_file_id: `files.id` of the parent archive.
            member_data: same dict shape as `insert_file` accepts.
        """
        if parent_file_id is None:
            raise ValueError("parent_file_id is required for archive members")

        path_id = member_data.get('path_id')
        if not path_id:
            raise ValueError("path_id is required")

        file_name = member_data.get('file_name') or member_data.get('name')
        if not file_name:
            raise ValueError("file_name is required")

        extension = member_data.get('extension', '')
        file_type_id, _ = self.resolve_file_type(extension)

        md5_binary = None
        md5_value = member_data.get('md5')
        if md5_value:
            if isinstance(md5_value, str) and len(md5_value) == 32:
                try:
                    md5_binary = bytes.fromhex(md5_value)
                except ValueError:
                    pass
            elif isinstance(md5_value, bytes):
                md5_binary = md5_value

        metadata = member_data.get('metadata', {})

        with self.cursor() as cur:
            cur.execute("""
                INSERT INTO files (
                    path_id, file_name, extension, file_type_id,
                    file_size, md5, date_created, date_modified, metadata,
                    parent_file_id, indexed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (path_id, file_name, extension)
                DO UPDATE SET
                    file_type_id   = COALESCE(EXCLUDED.file_type_id, files.file_type_id),
                    file_size      = EXCLUDED.file_size,
                    md5            = COALESCE(EXCLUDED.md5, files.md5),
                    date_created   = COALESCE(EXCLUDED.date_created, files.date_created),
                    date_modified  = EXCLUDED.date_modified,
                    metadata       = files.metadata || EXCLUDED.metadata,
                    parent_file_id = EXCLUDED.parent_file_id,
                    indexed_at     = CURRENT_TIMESTAMP
                RETURNING id
            """, (
                path_id,
                file_name,
                extension,
                file_type_id,
                member_data.get('size') or member_data.get('file_size'),
                md5_binary,
                member_data.get('date_created'),
                member_data.get('date_modified'),
                Json(metadata) if metadata else None,
                parent_file_id,
            ))
            return cur.fetchone()['id']

    def get_archive_path_id(self, parent_file_id: int, member_dir: str) -> int:
        """
        Get or create the synthetic `file_paths` row that anchors archive members
        beneath their parent archive.

        Path key shape: ``<archive-basename>!/<member_dir>`` — uses the conventional
        ``!/`` URI separator. The synthetic row lives in the SAME location as the
        parent archive and points `parent_file_path_id` at the archive's directory.

        Args:
            parent_file_id: `files.id` of the parent archive row.
            member_dir: posix-style directory of the member WITHIN the archive
                (use '' for archive-root members).

        Returns:
            file_paths.id of the synthetic row (cached).
        """
        if parent_file_id is None:
            raise ValueError("parent_file_id is required")

        member_dir = (member_dir or '').strip('/').replace('\\', '/')

        with self.cursor() as cur:
            cur.execute("""
                SELECT f.file_name, f.extension, fp.id AS parent_path_id,
                       fp.location_id, fp.path AS parent_path
                FROM files f
                JOIN file_paths fp ON f.path_id = fp.id
                WHERE f.id = %s
            """, (parent_file_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"parent file_id={parent_file_id} not found")

            archive_basename = row['file_name']
            if row['extension']:
                archive_basename = f"{archive_basename}.{row['extension']}"

            # Synthetic path lives flat under the parent's location, so prepend
            # the parent archive's directory to keep the resulting URI consistent
            # with where the archive physically sits.
            parent_path = (row['parent_path'] or '').strip('/')
            archive_path = f"{parent_path}/{archive_basename}" if parent_path else archive_basename

            synthetic_path = f"{archive_path}!"
            if member_dir:
                synthetic_path = f"{synthetic_path}/{member_dir}"

            cache_key = f"{row['location_id']}:{synthetic_path}"
            if cache_key in self._path_cache:
                return self._path_cache[cache_key]

            cur.execute("""
                INSERT INTO file_paths (location_id, parent_file_path_id, path)
                VALUES (%s, %s, %s)
                ON CONFLICT (location_id, path) DO UPDATE
                    SET parent_file_path_id =
                        COALESCE(file_paths.parent_file_path_id,
                                 EXCLUDED.parent_file_path_id)
                RETURNING id
            """, (row['location_id'], row['parent_path_id'], synthetic_path))
            path_id = cur.fetchone()['id']

        self._path_cache[cache_key] = path_id
        return path_id

    def update_metadata(self, file_id: int, json_dict: Dict[str, Any]) -> None:
        """
        Merge `json_dict` into `files.metadata` JSONB (Postgres `||` semantics:
        top-level keys in the new dict overwrite existing ones, others preserved).

        Used by both the archive walker (parent-archive summary stats) and the
        SharePoint walker (drive_id / etag / site_url augmentations).
        """
        if not json_dict:
            return
        with self.cursor() as cur:
            cur.execute("""
                UPDATE files
                   SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                 WHERE id = %s
            """, (Json(json_dict), file_id))

    def update_indexer_metadata(
        self,
        file_id: int,
        indexer: str,
        state: Dict[str, Any],
    ) -> None:
        """Replace one metadata.indexers.<indexer> state object."""
        self.update_indexer_metadata_batch([(file_id, indexer, state)])

    def update_indexer_metadata_batch(
        self,
        updates: Sequence[Tuple[int, str, Dict[str, Any]]],
    ) -> None:
        """Replace indexer states atomically in one database transaction."""
        prepared = list(updates)
        identities = [(file_id, indexer) for file_id, indexer, _state in prepared]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate file/indexer metadata update")
        for file_id, indexer, state in prepared:
            if not isinstance(file_id, int) or file_id <= 0:
                raise ValueError("file_id must be a positive integer")
            if not indexer:
                raise ValueError("indexer is required")
            if not isinstance(state, dict):
                raise TypeError("indexer state must be a dictionary")

        if not prepared:
            return

        with self.cursor() as cur:
            for file_id, indexer, state in prepared:
                cur.execute("""
                    UPDATE files
                       SET metadata = jsonb_set(
                           COALESCE(metadata, '{}'::jsonb),
                           '{indexers}',
                           jsonb_set(
                               CASE
                                   WHEN metadata -> 'indexers' = 'null'::jsonb
                                       THEN '{}'::jsonb
                                   ELSE COALESCE(
                                       metadata -> 'indexers',
                                       '{}'::jsonb
                                   )
                               END,
                               ARRAY[%s]::text[],
                               %s::jsonb,
                               true
                           ),
                           true
                       )
                     WHERE id = %s
                """, (indexer, Json(state), file_id))
                if cur.rowcount != 1:
                    raise LookupError(f"file not found: {file_id}")

    def update_canonical_locations_batch(
        self,
        assignments: Sequence[Tuple[str, str]],
    ) -> None:
        """Validate targets, then update canonical locations in one transaction."""
        prepared = list(assignments)
        duplicates = [duplicate for duplicate, _canonical in prepared]
        if len(duplicates) != len(set(duplicates)):
            raise ValueError("duplicate canonical-assignment source")
        targets = {canonical for _duplicate, canonical in prepared}
        if set(duplicates) & targets:
            raise ValueError("canonical assignment target cannot also be a duplicate source")
        for duplicate, canonical in prepared:
            if not duplicate or not canonical:
                raise ValueError("canonical assignment location IDs are required")
            if duplicate == canonical:
                raise ValueError("duplicate and canonical location IDs must differ")

        if not prepared:
            return

        location_ids = sorted({location_id for pair in prepared for location_id in pair})
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT RTRIM(id) AS location_id,
                       RTRIM(canonical_location_id) AS canonical_location_id
                  FROM locations
                 WHERE id = ANY(%s)
                   FOR UPDATE
                """,
                (location_ids,),
            )
            current = {
                row['location_id']: row['canonical_location_id']
                for row in cur.fetchall()
            }
            missing = sorted(set(location_ids) - set(current))
            if missing:
                raise LookupError(f"canonical assignment locations not found: {missing}")
            for canonical in targets:
                if current[canonical] is not None:
                    raise ValueError(
                        f"canonical assignment target is not terminal: {canonical}"
                    )
            for duplicate, canonical in prepared:
                existing = current[duplicate]
                if existing is not None and existing != canonical:
                    raise ValueError(
                        f"canonical assignment conflicts with current location state: {duplicate}"
                    )

            for duplicate, canonical in prepared:
                cur.execute(
                    """
                    UPDATE locations
                       SET canonical_location_id = %s
                     WHERE id = %s
                    """,
                    (canonical, duplicate),
                )
                if cur.rowcount != 1:
                    raise LookupError(f"canonical assignment source not found: {duplicate}")

    @contextmanager
    def session_lake_writer_lock(self):
        """Serialize Lake file replacement across FileIndexer processes."""
        with self.cursor(dict_cursor=False) as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (SESSION_LAKE_WRITER_LOCK,),
            )
            yield

    @contextmanager
    def location_indexing_lock(self, location_id: str):
        """Serialize complete indexing runs for one configured location."""
        lock_name = f"{FILE_INDEXER_LOCATION_LOCK_PREFIX}:{location_id}"
        with self.cursor(dict_cursor=False) as cur:
            cur.execute(
                "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
                (lock_name,),
            )
        try:
            yield
        finally:
            with self.cursor(dict_cursor=False) as cur:
                cur.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                    (lock_name,),
                )

    # --
    #    Statistics
    # --

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self.cursor() as cur:
            cur.execute("SELECT COUNT(*) as count FROM files")
            total_files = cur.fetchone()['count']

            cur.execute("SELECT COUNT(*) as count FROM files WHERE md5 IS NOT NULL")
            files_with_md5 = cur.fetchone()['count']

            cur.execute("SELECT COUNT(*) as count FROM locations")
            total_locations = cur.fetchone()['count']

            cur.execute("SELECT COALESCE(SUM(file_size), 0) as total FROM files")
            total_size = cur.fetchone()['total']

            cur.execute("""
                SELECT ft.class_id as file_type_class, COUNT(*) as count
                FROM files f
                JOIN file_types ft ON f.file_type_id = ft.id
                GROUP BY ft.class_id
                ORDER BY count DESC
            """)
            by_class = [dict(row) for row in cur.fetchall()]

            cur.execute("""
                SELECT extension, COUNT(*) as count
                FROM files
                GROUP BY extension
                ORDER BY count DESC
                LIMIT 15
            """)
            top_extensions = [dict(row) for row in cur.fetchall()]

            return {
                'total_files': total_files,
                'files_with_md5': files_with_md5,
                'total_locations': total_locations,
                'total_size_bytes': total_size,
                'by_file_type_class': by_class,
                'top_extensions': top_extensions
            }

    # --
    #    Run queue (migration 007) — request rows written by the admin tool,
    #    claimed and completed by file_indexer/runner.py on the target host
    # --

    def queue_indexer_run(
        self,
        kind: str,
        target_host: str,
        requested_by: str,
        location_id: Optional[str] = None,
        prefer_smb: bool = False,
    ) -> Dict[str, Any]:
        """Enqueue one run request and wake the runner on ``target_host``."""
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO indexer_runs
                       (kind, location_id, target_host, prefer_smb, requested_by)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (kind, location_id, target_host, prefer_smb, requested_by),
            )
            run = dict(cur.fetchone())
            # NOTIFY is transactional: it fires on commit, so a runner that
            # wakes on it always sees the row.
            cur.execute("SELECT pg_notify(%s, %s)", (INDEXER_RUN_CHANNEL, target_host))
        return run

    def list_indexer_runs(
        self,
        limit: int,
        location_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Recent run requests, newest first."""
        conditions, params = [], []
        if location_id is not None:
            conditions.append("location_id = %s")
            params.append(location_id)
        if status is not None:
            conditions.append("status = %s")
            params.append(status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM indexer_runs
                {where}
                ORDER BY requested_at DESC
                LIMIT %s
                """,
                tuple(params),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_indexer_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        """One run request by id, or None."""
        with self.cursor() as cur:
            cur.execute("SELECT * FROM indexer_runs WHERE id = %s", (run_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def cancel_queued_indexer_run(self, run_id: int) -> bool:
        """Cancel a request that no runner has claimed yet.

        A running walk is not interruptible — it holds the location's advisory
        lock in-process — so cancellation only applies while still queued.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE indexer_runs
                   SET status = 'cancelled', finished_at = now()
                 WHERE id = %s AND status = 'queued'
                """,
                (run_id,),
            )
            return cur.rowcount == 1

    def claim_indexer_run(
        self, target_host: str, runner_host: str, runner_pid: int
    ) -> Optional[Dict[str, Any]]:
        """Claim the oldest queued request for ``target_host``, or None.

        ``SKIP LOCKED`` makes concurrent runners on the same host safe: each
        claims a different row instead of blocking on the same one.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE indexer_runs
                   SET status = 'running',
                       claimed_at = now(),
                       heartbeat_at = now(),
                       runner_host = %s,
                       runner_pid = %s
                 WHERE id = (
                       SELECT id FROM indexer_runs
                        WHERE status = 'queued' AND target_host = %s
                        ORDER BY requested_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                 )
                RETURNING *
                """,
                (runner_host, runner_pid, target_host),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def heartbeat_indexer_run(self, run_id: int) -> None:
        """Mark a running request as still alive."""
        with self.cursor(dict_cursor=False) as cur:
            cur.execute(
                "UPDATE indexer_runs SET heartbeat_at = now() WHERE id = %s AND status = 'running'",
                (run_id,),
            )

    def finish_indexer_run(
        self,
        run_id: int,
        status: str,
        processed_files: Optional[int] = None,
        failed_files: Optional[int] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Record the outcome of a claimed request."""
        with self.cursor(dict_cursor=False) as cur:
            cur.execute(
                """
                UPDATE indexer_runs
                   SET status = %s,
                       finished_at = now(),
                       heartbeat_at = now(),
                       processed_files = %s,
                       failed_files = %s,
                       result = %s,
                       error = %s
                 WHERE id = %s
                """,
                (
                    status,
                    processed_files,
                    failed_files,
                    _run_result(result),
                    error,
                    run_id,
                ),
            )

    def fail_orphaned_indexer_runs(self, target_host: str, reason: str) -> int:
        """Fail the runs left `running` by a runner that is no longer alive.

        One runner serves a host, so any run still marked `running` for this host
        when that runner starts was interrupted — its process is gone and nothing
        will ever finish the row. Without this it stays `running` for ever.
        """
        with self.cursor(dict_cursor=False) as cur:
            cur.execute(
                """
                UPDATE indexer_runs
                   SET status = 'failed', finished_at = now(), error = %s
                 WHERE status = 'running' AND target_host = %s
                """,
                (reason, target_host),
            )
            return cur.rowcount


# .. changed; the one of now is in CRAP Projects/file_indexer/database_schema.py
class RecordingDatabase(_PGBase):
    """
    Database operations for recordings and recording_files tables.

    Schema:
    - recordings: One row per unique recording (keyed by recording_time)
    - recording_files: Multiple files per recording (audio, video, transcripts)

    Works with files already indexed in the files table.
    """

    VIDEO_EXTENSIONS = {'mp4', 'webm', 'mov', 'mkv', 'avi', 'flv'}
    AUDIO_EXTENSIONS = {'mp3', 'm4a', 'wav', 'ogg', 'opus'}
    TRANSCRIPT_EXTENSIONS = {'txt', 'docx', 'md', 'srt', 'vtt'}

    def __init__(self, **kw):
        super().__init__(**kw)

    # --
    #    File type helpers
    # --

    @classmethod
    def get_file_type(cls, extension: str) -> str:
        """Determine file type: video, audio, or transcript."""
        ext = extension.lower().lstrip('.')
        if ext in cls.VIDEO_EXTENSIONS:
            return 'video'
        elif ext in cls.AUDIO_EXTENSIONS:
            return 'audio'
        elif ext in cls.TRANSCRIPT_EXTENSIONS:
            return 'transcript'
        return 'unknown'

    @staticmethod
    def extract_folder(directory: str) -> str:
        """Extract the first folder from directory path."""
        if not directory:
            return ''
        parts = directory.replace('\\', '/').strip('/').split('/')
        return parts[0] if parts else ''

    # --
    #    Query operations
    # --

    def get_existing_file_ids(self) -> set:
        """Get all file_ids already in recording_files table."""
        with self.cursor(dict_cursor=False) as cur:
            cur.execute("SELECT file_id FROM recording_files")
            return {row[0] for row in cur.fetchall()}

    def get_existing_recording_times(self) -> Dict[str, int]:
        """Get mapping of recording_time -> recording_id."""
        with self.cursor() as cur:
            cur.execute("SELECT id, recording_time FROM recordings")
            return {str(row['recording_time']): row['id'] for row in cur.fetchall()}

    def get_candidate_files(self, recording_locations: List[Tuple[str, str, List[str]]],
                            location_filter: str = None) -> List[Dict[str, Any]]:
        """
        Query file_uris view for files in configured recording locations.

        Args:
            recording_locations: List of (location_id, folder_name, processors) tuples
            location_filter: Optional location_id to filter by

        Returns:
            List of file records from configured recording folders
        """
        if not recording_locations:
            return []

        # Filter by location if specified
        if location_filter:
            recording_locations = [
                (loc_id, folder, procs)
                for loc_id, folder, procs in recording_locations
                if loc_id == location_filter
            ]

        if not recording_locations:
            return []

        # Build query with location/folder conditions
        extensions_tuple = tuple(ALL_RECORDING_EXTENSIONS)
        conditions = []
        params = []

        for loc_id, folder_name, _ in recording_locations:
            if folder_name:
                conditions.append("(fu.location_id = %s AND (fu.directory = %s OR fu.directory LIKE %s))")
                params.extend([loc_id, folder_name, f"{folder_name}/%"])
            else:
                conditions.append("(fu.location_id = %s)")
                params.append(loc_id)

        where_clause = f"WHERE fu.extension IN %s AND ({' OR '.join(conditions)})"
        params.insert(0, extensions_tuple)

        query = f"""
            SELECT
                fu.id as file_id,
                fu.file_name,
                fu.extension,
                fu.file_size,
                fu.directory,
                fu.location_id,
                fu.uri
            FROM file_uris fu
            {where_clause}
            ORDER BY fu.id
        """

        with self.cursor() as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    # --
    #    Insert operations
    # --

    def get_or_create_recording(self, data: Dict[str, Any]) -> int:
        """
        Get existing or create new recording by recording_time.

        Args:
            data: Dictionary with recording metadata

        Returns:
            Recording ID
        """
        recording_time = data.get('recording_time')
        if not recording_time:
            raise ValueError("recording_time is required")

        with self.cursor() as cur:
            # Try to find existing
            cur.execute(
                "SELECT id FROM recordings WHERE recording_time = %s",
                (recording_time,)
            )
            row = cur.fetchone()
            if row:
                return row['id']

            # Create new
            cur.execute("""
                INSERT INTO recordings (
                    recording_time, title, duration_seconds, timezone,
                    medium, axis, participants, no_audio, short, next_step,
                    google_drive_id, folder
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s
                )
                RETURNING id
            """, (
                recording_time,
                data.get('title'),
                data.get('duration_seconds'),
                data.get('timezone'),
                data.get('medium', 'unknown'),
                data.get('axis'),
                Json(data.get('participants', [])),
                data.get('no_audio', False),
                data.get('short', False),
                data.get('next_step', 'transcribe'),
                data.get('google_drive_id'),
                data.get('folder'),
            ))
            return cur.fetchone()['id']

    def add_recording_file(self, recording_id: int, file_data: Dict[str, Any]) -> Optional[int]:
        """
        Add a file to a recording.

        Args:
            recording_id: ID of the recording
            file_data: File metadata

        Returns:
            Recording file ID if inserted, None if already exists
        """
        with self.cursor() as cur:
            cur.execute("""
                INSERT INTO recording_files (
                    recording_id, file_id, file_type,
                    source_filename, source_path, file_size, extension
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (file_id) DO NOTHING
                RETURNING id
            """, (
                recording_id,
                file_data.get('file_id'),
                file_data.get('file_type', 'unknown'),
                file_data.get('source_filename'),
                file_data.get('source_path'),
                file_data.get('file_size'),
                file_data.get('extension'),
            ))
            row = cur.fetchone()
            return row['id'] if row else None

    # --
    #    Statistics
    # --

    def get_stats(self) -> Dict[str, Any]:
        """Get recordings statistics."""
        with self.cursor() as cur:
            cur.execute("SELECT COUNT(*) as count FROM recordings")
            total_recordings = cur.fetchone()['count']

            cur.execute("SELECT COUNT(*) as count FROM recording_files")
            total_files = cur.fetchone()['count']

            cur.execute("""
                SELECT file_type, COUNT(*) as count
                FROM recording_files
                GROUP BY file_type
            """)
            by_file_type = {row['file_type']: row['count'] for row in cur.fetchall()}

            cur.execute("""
                SELECT medium, COUNT(*) as count
                FROM recordings
                GROUP BY medium
                ORDER BY count DESC
            """)
            by_medium = {row['medium']: row['count'] for row in cur.fetchall()}

            cur.execute("""
                SELECT axis, COUNT(*) as count
                FROM recordings
                WHERE axis IS NOT NULL
                GROUP BY axis
                ORDER BY count DESC
            """)
            by_axis = {row['axis']: row['count'] for row in cur.fetchall()}

            cur.execute("""
                SELECT next_step, COUNT(*) as count
                FROM recordings
                GROUP BY next_step
            """)
            by_next_step = {row['next_step']: row['count'] for row in cur.fetchall()}

            cur.execute("SELECT COALESCE(SUM(file_size), 0) as total FROM recording_files")
            total_size = cur.fetchone()['total']

            video_files = by_file_type.get('video', 0)
            audio_files = by_file_type.get('audio', 0)
            return {
                'total_recordings': total_recordings,
                'total_files': total_files,
                'recordings': video_files + audio_files,
                'video_files': video_files,
                'audio_files': audio_files,
                'transcripts': by_file_type.get('transcript', 0),
                'total_size_bytes': total_size,
                'by_medium': by_medium,
                'by_axis': by_axis,
                'by_next_step': by_next_step,
            }

# endregion


# region - CRAP Projects/file_indexer/file_indexer.py as of 2026-11-20 (4)

# .. gone
# gppu's public `__init__` may not re-export every symbol depending on install
# (dev-tui gppu exposes OSType/init_logger/Error from the top level; older
# packages only expose them via gppu.gppu). Try both so the indexer runs
# against either.
try:
    from gppu import Env, OSType, detect_os, init_logger, Error, glob_dict, glob_list  # type: ignore
except ImportError:  # older gppu — pull from submodule
    from gppu import Env, detect_os, glob_dict, glob_list  # type: ignore
    from gppu.gppu import OSType, init_logger, Error  # type: ignore


# .. changed; the one of now is in CRAP Projects/file_indexer/file_indexer.py
class FileIndexer(_Base):
    """Universal file indexer with PostgreSQL backend."""

    VERSION = "2.0.0"

    def __init__(self, **kw):
        """Initialize the file indexer using gppu Env for config."""
        super().__init__(**kw)
        self._db = None

    @property
    def db(self) -> FileDatabase:
        """Get database instance."""
        return self._db

    def __enter__(self):
        """Context manager entry - initialize database connection."""
        self._db = FileDatabase()

        # Sync lookup tables
        server_types = glob_dict('server_types')
        file_types = glob_dict('file_types').get('file_type_classes', {})

        errors, inserted = self._db.sync_lookup_tables(server_types, file_types)

        if inserted:
            self.Info(f"Auto-inserted {len(inserted)} lookup entries: {', '.join(inserted)}")

        if errors:
            self._db.close()
            raise LookupTableMismatchError(errors)

        return self

    def __exit__(self, *_):
        """Context manager exit - close database connection."""
        if self._db:
            self._db.close()

    def _should_exclude(self, path: str, file_name: str, location_exclusions: List[str] = None) -> bool:
        """Check if a file or path should be excluded based on patterns."""
        full_path = os.path.join(path, file_name)

        # Check global exclusions
        global_exc = glob_dict('global_exclusions')

        # Check file patterns
        for pattern in global_exc.get('patterns', []):
            if fnmatch.fnmatch(file_name, pattern):
                return True

        # Check directory exclusions
        for dir_name in global_exc.get('directories', []):
            if f"/{dir_name}/" in full_path or f"\\{dir_name}\\" in full_path:
                return True
            if full_path.endswith(f"/{dir_name}") or full_path.endswith(f"\\{dir_name}"):
                return True

        # Check location-specific exclusions
        if location_exclusions:
            for pattern in location_exclusions:
                if fnmatch.fnmatch(file_name, pattern) or fnmatch.fnmatch(full_path, pattern):
                    return True

        return False

    def _process_file(
        self,
        file_path: str,
        location_id: str,
        root_path: str,
        indexer_associations: Dict[str, Any] | None,
        sessioner_lake_root: str | None = None,
    ) -> bool:
        """
        Process a single file and add to database.

        Args:
            file_path: Full path to file
            location_id: Location ID (CHAR(16) string like 'sd')
            root_path: Root path of the location (for calculating relative directory)

        Returns:
            True if processed successfully, False otherwise
        """
        try:
            path_obj = Path(file_path)

            if not path_obj.exists() or not path_obj.is_file():
                return False

            # Get file stats
            stat = path_obj.stat()

            # Calculate relative directory from root path.
            # POSIX separators always: file_paths.path must be host-independent
            # (mac/WSL walks wrote 'a/b'; a Windows walk must not write 'a\b'
            # for the same logical directory).
            directory = _relative_posix_dir(root_path, str(path_obj.parent))

            # Get path_id for this directory (FileDatabase handles caching)
            path_id = self.db.get_or_create_path_id(location_id, directory)

            # Build file data for normalized schema
            extension = _normalize_extension(path_obj.suffix)
            file_data = {
                'path_id': path_id,
                'file_name': path_obj.stem if extension else path_obj.name,
                'extension': extension,
                'size': stat.st_size,
                'date_created': datetime.fromtimestamp(stat.st_ctime),
                'date_modified': datetime.fromtimestamp(stat.st_mtime),
                'metadata': {}
            }

            # Insert into database
            file_id = self.db.insert_file(file_data)

            if indexer_associations is not None:
                try:
                    dispatch_results = dispatch_indexers(
                        file_id=file_id,
                        location_id=location_id,
                        file_path=path_obj,
                        associations=indexer_associations,
                    )
                except Exception as error:
                    for indexer, config in indexer_associations.items():
                        state = {
                            'recognized': False,
                            'inspection': {
                                'status': 'error',
                                'error_type': type(error).__name__,
                            },
                        }
                        if indexer == SESSIONER:
                            state['configured_source'] = config['source']
                            state['sessions'] = []
                        self.db.update_indexer_metadata(file_id, indexer, state)
                    raise

                if SESSIONER in indexer_associations:
                    configured_source = indexer_associations[SESSIONER]['source']
                    preserve_originals = indexer_associations[SESSIONER][
                        'preserve_originals'
                    ]
                    session_results = tuple(
                        result
                        for result in dispatch_results
                        if result.indexer == SESSIONER
                    )
                    state = {
                        'recognized': bool(session_results),
                        'configured_source': configured_source,
                        'sessions': [
                            {
                                'provider': result.provider,
                                'native_session_id': result.native_session_id,
                                'session_start': result.session_start,
                                'complete': result.complete,
                            }
                            for result in session_results
                        ],
                    }

                    if (
                        session_results
                        and preserve_originals
                        and sessioner_lake_root is not None
                    ):
                        try:
                            with self.db.session_lake_writer_lock():
                                lake_result = preserve_original_session(
                                    path_obj,
                                    sessioner_lake_root,
                                )
                        except Exception as error:
                            state['lake'] = {
                                'status': 'error',
                                'error_type': type(error).__name__,
                            }
                            self.db.update_indexer_metadata(
                                file_id,
                                SESSIONER,
                                state,
                            )
                            raise

                        lake_state = {'status': lake_result.status}
                        if lake_result.destination is not None:
                            lake_state['relative_path'] = lake_result.destination.relative_to(
                                Path(sessioner_lake_root)
                            ).as_posix()
                        state['lake'] = lake_state

                    self.db.update_indexer_metadata(
                        file_id,
                        SESSIONER,
                        state,
                    )

                if PHOTO_INDEXER in indexer_associations:
                    photo_results = tuple(
                        result
                        for result in dispatch_results
                        if result.indexer == PHOTO_INDEXER
                    )
                    photo_state = {'recognized': bool(photo_results)}
                    if photo_results:
                        if len(photo_results) != 1:
                            raise RuntimeError(
                                'photo_indexer returned multiple results for one file'
                            )
                        photo_state.update(
                            {
                                'media_kind': photo_results[0].media_kind,
                                'detected_format': photo_results[0].detected_format,
                                'extension': photo_results[0].extension,
                            }
                        )
                    self.db.update_indexer_metadata(
                        file_id,
                        PHOTO_INDEXER,
                        photo_state,
                    )

            return True

        except Exception as e:
            self.Error(f"Error processing file {file_path}: {e}")
            return False

    def _ensure_ancestor_path_ids(self, location_id: str, rel_path: str,
                                   dir_path_ids: Dict[str, int]) -> int:
        """Ensure a `file_paths` row exists for `rel_path` AND every ancestor
        between it and the location root (''), chaining `parent_file_path_id`.

        Needed because `location_config['folders']` can scope a walk to a
        subfolder (e.g. 'Photos/2024') whose intermediate ancestors ('',
        'Photos') would otherwise never get their own row. `dir_path_ids`
        caches rel-path -> id for the duration of one `_discover_files` call.
        """
        if rel_path in dir_path_ids:
            return dir_path_ids[rel_path]

        if rel_path == '':
            path_id = self.db.get_or_create_path_id(location_id, '')
        else:
            parent_rel = rel_path.rsplit('/', 1)[0] if '/' in rel_path else ''
            parent_id = self._ensure_ancestor_path_ids(location_id, parent_rel, dir_path_ids)
            path_id = self.db.get_or_create_path_id(
                location_id, rel_path, parent_path_id=parent_id)

        dir_path_ids[rel_path] = path_id
        return path_id

    def _discover_files(self, walk_root: str, location_root: str, location_id: str,
                        extensions: List[str] = None,
                        exclusions: List[str] = None, recursive: bool = True) -> List[str]:
        """
        Discover files under `walk_root` (a location's own root, or one of its
        `folders:`-scoped subfolders).

        As a side effect (recursive mode only), creates a `file_paths` row for
        every directory visited — paths always relative to `location_root`, so
        they line up with what `_process_file` computes for each file's own
        directory, even when `walk_root` is a scoped subfolder. Rows are linked
        to their parent via `parent_file_path_id`. A directory whose name
        matches `glob_dict('folder_classes')` gets `folder_class_id` set on
        its row and is pruned from the walk — its contents are
        recognized-and-classified but never enumerated (see
        sql/006_folder_classes.sql). `FileIndexer.index_location` rolls up
        recursive stats (size, file/folder counts, date spans) onto these rows
        after the file-processing loop via `FileDatabase.rollup_folder_stats`.

        Args:
            walk_root: Directory to actually os.walk from
            location_root: The location's own root path (basis for relative
                directory strings — same one `_process_file` uses)
            location_id: Location ID — needed to create file_paths rows during the walk
            extensions: List of extensions to filter (None = all)
            exclusions: List of exclusion patterns
            recursive: Whether to scan subdirectories

        Returns:
            List of file paths
        """
        files = []

        # Normalize extensions
        if extensions:
            extensions = [ext.lower().lstrip('.') for ext in extensions]

        folder_classes = glob_dict('folder_classes') or {}

        try:
            if recursive:
                dir_path_ids: Dict[str, int] = {}
                walk_root_rel = _relative_posix_dir(location_root, walk_root)
                self._ensure_ancestor_path_ids(location_id, walk_root_rel, dir_path_ids)

                for dirpath, dirnames, filenames in os.walk(walk_root):
                    rel_dir = _relative_posix_dir(location_root, dirpath)
                    this_path_id = dir_path_ids[rel_dir]

                    kept_dirnames = []
                    for d in dirnames:
                        full_dir = os.path.join(dirpath, d)

                        # Prune symlinks and NTFS junctions (os.walk descends
                        # junctions even with followlinks=False) — unchanged,
                        # zero DB trace, same as before.
                        if _is_link_dir(full_dir):
                            continue

                        child_rel = f"{rel_dir}/{d}" if rel_dir else d

                        class_id = folder_classes.get(d)
                        if class_id:
                            # Recognized + classified: one file_paths row,
                            # contents intentionally never walked.
                            self.db.get_or_create_path_id(
                                location_id, child_rel,
                                parent_path_id=this_path_id, folder_class_id=class_id)
                            continue

                        if self._should_exclude(dirpath, d, exclusions):
                            continue

                        dir_path_ids[child_rel] = self.db.get_or_create_path_id(
                            location_id, child_rel, parent_path_id=this_path_id)
                        kept_dirnames.append(d)

                    dirnames[:] = kept_dirnames

                    for filename in filenames:
                        full_path = os.path.join(dirpath, filename)

                        # Check exclusions
                        if self._should_exclude(dirpath, filename, exclusions):
                            continue

                        # Check extensions
                        if extensions:
                            ext = Path(filename).suffix.lower().lstrip('.')
                            if ext not in extensions:
                                continue

                        files.append(full_path)
            else:
                for item in os.listdir(root_path):
                    full_path = os.path.join(root_path, item)
                    if os.path.isfile(full_path):
                        if self._should_exclude(root_path, item, exclusions):
                            continue
                        if extensions:
                            ext = Path(item).suffix.lower().lstrip('.')
                            if ext not in extensions:
                                continue
                        files.append(full_path)

        except PermissionError as e:
            self.Warn(f"Permission denied accessing {root_path}: {e}")
        except Exception as e:
            self.Error(f"Error discovering files in {root_path}: {e}")

        return files

    def index_location(
        self, location_id: str, location_config: Dict[str, Any],
        *, prefer_smb: bool = False,
    ) -> Dict[str, Any]:
        """
        Index a single location.

        Args:
            location_id: Location ID (CHAR(16) string like 'sd')
            location_config: Location configuration dictionary

        Returns:
            Dictionary with indexing results
        """
        # Resolve path based on current OS.
        # Supports BOTH the legacy flat shape (path_windows / path_wsl / path_macos)
        # AND the nested shape used by topology/locations.yaml (paths.windows / paths.wsl / paths.macos).
        # NOTE: gppu.detect_os() returns OSType.OTHER on Darwin (it only knows
        # W11 / WSL / LINUX); we fall back to platform.system() to recognise macOS.
        os_type = detect_os()
        if os_type == OSType.OTHER and platform.system() == 'Darwin':
            os_type = OSType.MACOS
        paths_nested = location_config.get('paths') or {}

        def _pick(*keys):
            for k in keys:
                v = location_config.get(k)
                if v:
                    return v
                v = paths_nested.get(k.removeprefix('path_'))
                if v:
                    return v
            return ''

        if os_type == OSType.W11:
            location_path = _pick('path_windows', 'path_wsl', 'path_macos')
        elif os_type == OSType.MACOS:
            # Prefer macOS-native mount (typically an smbfs mount under /Volumes/smb/<host>/<share>)
            location_path = _pick('path_macos', 'path_wsl', 'path_windows')
        else:  # LINUX / WSL / OTHER
            location_path = _pick('path_wsl', 'path_macos', 'path_windows')

        # Provider-shaped topology entries (2026-07 refactor: `local/<host>`,
        # `smb/<slug>` keys) carry no flat path_* keys; adapt them via
        # path_resolver, which also supplies server identity for the DB row.
        adapted = None
        if not location_path:
            configured_locations = glob_dict('locations')
            if location_id not in configured_locations:
                configured_locations = {
                    **configured_locations,
                    location_id: location_config,
                }
            adapted = resolve_configured_topology_location(
                location_id,
                configured_locations,
                shares=glob_dict('shares'),
                prefer_smb=prefer_smb,
            )
            if adapted:
                location_path = adapted['path']

        if not location_path:
            # Tenant/provider-shaped top-level entries in topology/locations.yaml
            # (e.g. `karelin:`, `nas:`, `local:`) have no paths of their own; they
            # are documentation containers. Skip cleanly rather than erroring.
            return {
                'status': 'skipped',
                'location_id': location_id,
                'reason': 'no path for current OS (likely a tenant/container entry, not a leaf location)'
            }

        indexer_associations = None
        if adapted is not None and 'indexers' in adapted:
            indexer_associations = adapted['indexers']
        elif 'indexers' in location_config:
            indexer_associations = location_config['indexers']
        if indexer_associations is not None:
            validate_indexer_associations(indexer_associations)

        sessioner_lake_root = None
        if indexer_associations is not None and SESSIONER in indexer_associations:
            if indexer_associations[SESSIONER]['preserve_originals']:
                lake_location_id = indexer_associations[SESSIONER]['lake_location_id']
                configured_locations = glob_dict('locations')
                if lake_location_id not in configured_locations:
                    raise KeyError(
                        f"unknown Sessioner Lake location: {lake_location_id}"
                    )
                lake_location = resolve_configured_topology_location(
                    lake_location_id, configured_locations,
                    shares=glob_dict('shares'),
                )
                if lake_location is None:
                    raise RuntimeError(
                        "Sessioner Lake location is not accessible from this host: "
                        f"{lake_location_id}"
                    )
                sessioner_lake_root = lake_location['path']
                if not os.path.isdir(sessioner_lake_root):
                    raise RuntimeError(
                        "Sessioner Lake root is not an accessible directory: "
                        f"{sessioner_lake_root}"
                    )

        if not os.path.exists(location_path):
            return {
                'status': 'error',
                'location_id': location_id,
                'error': f'Path does not exist: {location_path}'
            }

        self.Info(f"Indexing location: {location_id} ({location_path})")

        start_time = time.time()

        # Ensure location exists in DB.
        # `uri_prefix` (optional in yaml) lets SMB shares set the share-inclusive
        # prefix e.g. `smb://s1.karel.in/SD.Lake` so file URIs render correctly.
        if adapted is not None:
            location_metadata = {
                'location_id': location_id,
                'server_type': adapted['server_type'],
                'hostname': adapted['hostname'],
                'uri_prefix': adapted['uri_prefix'],
            }
            if adapted.get('description'):
                location_metadata['description'] = adapted['description']
        else:
            if not location_config.get('server_type'):
                raise ValueError(
                    f"server_type is required for legacy location: {location_id}"
                )
            location_metadata = {
                'location_id': location_id,
                'server_type': location_config['server_type'],
            }
            if 'server_name' in location_config:
                location_metadata['hostname'] = location_config['server_name']
            elif 'hostname' in location_config:
                location_metadata['hostname'] = location_config['hostname']
            if 'uri_prefix' in location_config:
                location_metadata['uri_prefix'] = location_config['uri_prefix']
            if 'description' in location_config:
                location_metadata['description'] = location_config['description']
        self.db.get_or_create_location(**location_metadata)

        # Discover files
        extensions = location_config.get('extensions', [])
        exclusions = location_config.get('exclusions', [])
        recursive = location_config.get('recursive', True)
        folders = location_config.get('folders', {})

        files = []
        if folders:
            # Only index specified folders
            for folder_name in folders.keys():
                folder_path = os.path.join(location_path, folder_name)
                if os.path.exists(folder_path):
                    self.Info(f"  Scanning folder: {folder_name}")
                    folder_files = self._discover_files(
                        folder_path, location_path, location_id, extensions, exclusions, recursive)
                    files.extend(folder_files)
                else:
                    self.Warn(f"  Folder not found: {folder_path}")
        else:
            # Index entire location
            files = self._discover_files(
                location_path, location_path, location_id, extensions, exclusions, recursive)

        if not files:
            # Write back location bookkeeping even on empty-share runs (t_531e9064).
            # Without this, locations with zero files never get last_indexed set
            # and stay flagged as "stale > 7d" forever (false positive on the
            # inventory-curator stale-loader signal).
            # Folder-class rows (e.g. a lone .git folder) may still have been
            # created during the walk above even though no indexable file was
            # found, so roll up stats before returning.
            try:
                self.db.rollup_folder_stats(location_id)
            except Exception as e:
                self.Warn(f"  rollup_folder_stats({location_id}) failed on no_files path: {e}")
            try:
                self.db.update_location_stats(location_id)
            except Exception as e:
                self.Warn(f"  update_location_stats({location_id}) failed on no_files path: {e}")
            return {
                'status': 'no_files',
                'location_id': location_id,
                'location_path': location_path,
                'total_files': 0,
                'processed_files': 0,
                'failed_files': 0,
                'duration_seconds': time.time() - start_time
            }

        self.Info(f"Found {len(files)} files to process")

        # Process files
        processed = 0
        failed = 0
        loc_stats = None

        # try/finally so writeback ALWAYS runs, even if the per-file loop
        # raises (KeyboardInterrupt, OOM, IOError on a single SMB file).
        # Bug: pre-fix, a single uncaught exception in _process_file killed
        # the run before line 396, leaving files in the DB but
        # locations.last_indexed=NULL forever. s1-photoarchive (80k files)
        # exhibited this for multiple runs — same defect class as t_531e9064
        # (empty-share path) and t_ab4e8739 (success path), now closed on the
        # interrupted-run path too. (t_afbf3b7c)
        try:
            for i, file_path in enumerate(files):
                success = self._process_file(
                    file_path,
                    location_id,
                    location_path,
                    indexer_associations,
                    sessioner_lake_root,
                )
                if success:
                    processed += 1
                    print("o", end="", flush=True)
                else:
                    failed += 1
                    print("x", end="", flush=True)

                # Print progress every 100 files
                if (i + 1) % 100 == 0:
                    print(f" [{i + 1}/{len(files)}]")

            print()  # Final newline
        finally:
            # Recursive folder rollups (size, file/folder counts, date spans)
            # first, so they're in place before the location-level writeback.
            # Idempotent: recomputed from current `files`/`file_paths` rows,
            # not a delta. Safe on partial/crashed runs — next successful pass
            # self-heals.
            try:
                self.db.rollup_folder_stats(location_id)
            except Exception as e:
                self.Warn(f"  rollup_folder_stats({location_id}) failed: {e}")

            # Write back location bookkeeping (last_indexed + files_indexed).
            # Idempotent: counts files actually present, not delta. Safe on
            # partial/crashed runs — next successful pass self-heals.
            try:
                loc_stats = self.db.update_location_stats(location_id)
            except Exception as e:
                self.Warn(f"  update_location_stats({location_id}) failed: {e}")
                loc_stats = None

        duration = time.time() - start_time

        return {
            'status': 'completed',
            'location_id': location_id,
            'location_path': location_path,
            'total_files': len(files),
            'processed_files': processed,
            'failed_files': failed,
            'duration_seconds': duration,
            'files_per_second': processed / duration if duration > 0 else 0,
            'location_stats': loc_stats,
        }

    def index_configured_location(self, location_id: str, *, prefer_smb: bool = False) -> Dict[str, Any]:
        """Index one location by its configuration ID, never by a caller path."""
        locations = glob_dict('locations')
        if location_id not in locations:
            raise KeyError(f"unknown configured location: {location_id}")
        if location_id in set(glob_list('exclude_locations')):
            raise ValueError(f"configured location is excluded: {location_id}")
        location = locations[location_id]
        if not location.get('enabled', True):
            raise ValueError(f"configured location is disabled: {location_id}")
        with self.db.location_indexing_lock(location_id):
            if prefer_smb:
                return self.index_location(location_id, location, prefer_smb=True)
            return self.index_location(location_id, location)

    def index_all_locations(self) -> Dict[str, Any]:
        """
        Index all configured locations.

        Returns:
            Dictionary with comprehensive indexing results
        """
        locations = glob_dict('locations')

        if not locations:
            return {
                'status': 'no_locations',
                'message': 'No locations configured in config.yaml'
            }

        start_time = time.time()
        results = []
        total_processed = 0
        total_failed = 0

        location_items = list(locations.items())
        excluded = set(glob_list('exclude_locations'))
        for i, (loc_id, location) in enumerate(location_items, 1):
            if loc_id in excluded:
                self.Info(f"Skipping excluded location: {loc_id}")
                continue
            if not location.get('enabled', True):
                self.Info(f"Skipping disabled location: {loc_id}")
                continue

            self.Info(f"Processing location {i}/{len(location_items)}: {loc_id}")

            try:
                result = self.index_location(loc_id, location)
                results.append(result)

                if result['status'] == 'completed':
                    total_processed += result.get('processed_files', 0)
                    total_failed += result.get('failed_files', 0)

            except Exception as e:
                self.Error(f"Error indexing location {loc_id}: {e}")
                results.append({
                    'status': 'error',
                    'location_id': loc_id,
                    'error': str(e)
                })

        total_duration = time.time() - start_time

        return {
            'status': 'completed',
            'locations_processed': len(results),
            'total_files_processed': total_processed,
            'total_files_failed': total_failed,
            'duration_seconds': total_duration,
            'location_results': results
        }

    def run(self) -> None:
        """Run the file indexer with full output."""
        # Print startup banner
        print("\n" + "=" * 60)
        print(f"FILE INDEXER v{self.VERSION}")
        print("=" * 60)
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Show configured locations
        print("\n" + "-" * 40)
        print("CONFIGURED LOCATIONS")
        print("-" * 40)

        locations = glob_dict('locations')
        for i, (loc_id, loc) in enumerate(locations.items(), 1):
            paths_nested = (loc.get('paths') if isinstance(loc, dict) else None) or {}
            path = (
                loc.get('path_macos') or paths_nested.get('macos')
                or loc.get('path_wsl') or paths_nested.get('wsl')
                or loc.get('path_windows') or paths_nested.get('windows')
                or '(container — no path)'
            )
            status = "[ENABLED]" if loc.get('enabled', True) else "[DISABLED]"
            print(f"{i}. {loc_id} {status}")
            print(f"   Path: {path}")
            if loc.get('description'):
                print(f"   Description: {loc['description']}")

        # Show database stats before
        print("\n" + "-" * 40)
        print("DATABASE STATISTICS (BEFORE)")
        print("-" * 40)

        stats_before = self.db.get_stats()
        print(f"Total files: {stats_before['total_files']:,}")
        print(f"Total size: {stats_before['total_size_bytes']:,} bytes")

        # Run indexing
        print("\n" + "=" * 60)
        print("STARTING INDEXING")
        print("=" * 60)

        result = self.index_all_locations()

        # Show results
        print("\n" + "-" * 40)
        print("INDEXING RESULTS")
        print("-" * 40)

        for loc_result in result.get('location_results', []):
            print(f"\n{loc_result.get('location_id', 'Unknown')}:")
            print(f"  Status: {loc_result['status']}")
            if loc_result['status'] == 'completed':
                print(f"  Files processed: {loc_result.get('processed_files', 0):,}")
                print(f"  Files failed: {loc_result.get('failed_files', 0):,}")
                print(f"  Duration: {loc_result.get('duration_seconds', 0):.2f}s")
            elif loc_result.get('error'):
                print(f"  Error: {loc_result['error']}")

        # Show database stats after
        print("\n" + "-" * 40)
        print("DATABASE STATISTICS (AFTER)")
        print("-" * 40)

        stats_after = self.db.get_stats()
        files_added = stats_after['total_files'] - stats_before['total_files']
        size_added = stats_after['total_size_bytes'] - stats_before['total_size_bytes']

        print(f"Total files: {stats_after['total_files']:,} (added {files_added:,})")
        print(f"Total size: {stats_after['total_size_bytes']:,} bytes (added {size_added:,})")

        print("\n" + "=" * 60)
        print(f"COMPLETED at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)


# .. changed; the one of now is in CRAP Projects/file_indexer/file_indexer.py
def main():
    """CLI entry point."""
    init_logger('file-indexer')

    try:
        with FileIndexer() as indexer:
            indexer.run()

    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        Error(f"Indexing failed: {e}")
        print(f"\nError: {e}")
        sys.exit(1)


# .. gone
if __name__ == '__main__':
    init_logger('file-indexer')
    Env.from_env(name='file_indexer', app_path=Path('_config/file_indexer'))

    main()

# endregion


# region - CRAP Projects/file_indexer/qdrant/__main__.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Projects/file_indexer/qdrant/__main__.py
def main():
    # REVIEW: requires gppu dev-tui (top-level init_logger). Older gppu will ImportError.
    from gppu import Env, init_logger
    from pathlib import Path

    init_logger('qdrant')
    Env.from_env(name='qdrant', app_path=Path("CRAP/file_indexer"))

    parser = argparse.ArgumentParser(
        prog="qdrant",
        description="Local semantic file indexer with BGE-M3 embeddings",
    )

    sub = parser.add_subparsers(dest='command', required=True)

    # -- index --
    p_index = sub.add_parser('index', help='Index files into local .qd.idx')
    p_index.add_argument('paths', nargs='+', help='Directories to index')
    p_index.add_argument('--workers', type=int, default=None, help='Content extraction threads')
    p_index.add_argument('--batch-size', type=int, default=None, help='Embedding batch size')
    p_index.add_argument('--dry-run', action='store_true', help='Show what would be indexed')
    p_index.add_argument('--force', action='store_true', help='Re-embed all files, ignore mtime')
    p_index.add_argument('--extension', default=None, help='Only index files with this extension')

    # -- search --
    p_search = sub.add_parser('search', help='Semantic search across all indexes')
    p_search.add_argument('query', help='Search query text')
    p_search.add_argument('paths', nargs='*', help='Specific folders to search (default: all)')
    p_search.add_argument('--limit', type=int, default=10, help='Number of results')
    p_search.add_argument('--extension', default=None, help='Filter by extension')

    # -- status --
    p_status = sub.add_parser('status', help='Show index info')
    p_status.add_argument('paths', nargs='*', help='Specific folders (default: all registered)')

    # -- purge --
    p_purge = sub.add_parser('purge', help='Delete index for a folder')
    p_purge.add_argument('path', help='Folder to purge')

    # -- list --
    p_list = sub.add_parser('list', help='List indexed files with descriptions')
    p_list.add_argument('paths', nargs='*', help='Specific folders (default: all registered)')
    p_list.add_argument('--extension', default=None, help='Filter by extension')

    # -- cluster --
    p_cluster = sub.add_parser('cluster', help='Cluster, find duplicates, detect outliers')
    p_cluster.add_argument('paths', nargs='*', help='Specific folders (default: all registered)')
    p_cluster.add_argument('--min-cluster', type=int, default=5, help='Min cluster size for HDBSCAN')
    p_cluster.add_argument('--dup-threshold', type=float, default=0.95, help='Cosine similarity threshold for duplicates')

    args = parser.parse_args()

    commands = {
        'index': cmd_index,
        'search': cmd_search,
        'status': cmd_status,
        'purge': cmd_purge,
        'list': cmd_list,
        'cluster': cmd_cluster,
    }

    commands[args.command](args)

# endregion


# region - CRAP Projects/file_indexer/recording_indexer.py as of 2026-11-20 (2)

# .. changed; the one of now is in CRAP Projects/file_indexer/recording_indexer.py
class RecordingIndexer(_Base):
    """Recording file indexer with PostgreSQL backend and filename classification."""

    VERSION = "3.0.0"

    def __init__(self, **kw):
        """Initialize the recording indexer using gppu Env for config."""
        super().__init__(**kw)
        self._db = None

    @property
    def db(self) -> RecordingDatabase:
        """Get database instance."""
        return self._db

    def __enter__(self):
        """Context manager entry - initialize database connection."""
        self._db = RecordingDatabase()
        return self

    def __exit__(self, *_):
        """Context manager exit - close database connection."""
        if self._db:
            self._db.close()

    # --
    #    Location discovery
    # --

    def get_recording_locations(self) -> List[Tuple[str, str, List[str]]]:
        """
        Scan locations.yaml for locations with 'recordings' or 'transcriptions' file_classes.

        Returns:
            List of (location_id, folder_name, file_classes) tuples
        """
        locations = glob_dict('locations')
        recording_locations = []

        for loc_id, loc_config in locations.items():
            if not loc_config.get('enabled', True):
                continue

            file_classes = loc_config.get('file_classes', [])
            if 'recordings' in file_classes or 'transcriptions' in file_classes:
                recording_locations.append((loc_id, '', file_classes))

        return recording_locations

    def list_locations(self) -> None:
        """Print all locations configured for recording processing."""
        locations = self.get_recording_locations()

        if not locations:
            print("No locations configured with 'recordings' or 'transcripts' processors.")
            print("\nTo configure, add 'processors: [recordings]' to a folder in locations.yaml")
            return

        print("\nConfigured Recording Locations:")
        print("-" * 60)
        for loc_id, folder_name, processors in locations:
            print(f"  {loc_id}/{folder_name}")
            print(f"    Processors: {', '.join(processors)}")
        print("-" * 60)
        print(f"Total: {len(locations)} folder(s)\n")

    # --
    #    Indexing
    # --

    def index(self, location_filter: str = None, dry_run: bool = False) -> Dict[str, Any]:
        """
        Index recording files from configured locations with full metadata extraction.

        Groups files by recording_time into unique recordings.

        Args:
            location_filter: Optional location_id to filter by
            dry_run: If True, don't write to database

        Returns:
            Dictionary with indexing results
        """
        recording_locations = self.get_recording_locations()

        result = {
            'timestamp': datetime.now().isoformat(),
            'location_filter': location_filter or 'all',
            'configured_locations': [
                f"{loc}/{folder}" for loc, folder, _ in recording_locations
            ],
            'dry_run': dry_run,
            'scanned': 0,
            'recordings_created': 0,
            'files_added': 0,
            'skipped_existing': 0,
            'skipped_no_date': 0,
            'by_medium': {},
            'by_axis': {},
            'by_next_step': {},
            'errors': [],
            'sample_records': [],
        }

        if not recording_locations:
            result['errors'].append("No locations configured with 'recordings' or 'transcripts' processors")
            return result

        # Get existing file_ids to avoid duplicates
        existing_file_ids = self.db.get_existing_file_ids()
        self.Info(f"Found {len(existing_file_ids)} existing file entries")

        # Get candidate files from configured locations
        candidates = self.db.get_candidate_files(recording_locations, location_filter)
        result['scanned'] = len(candidates)
        self.Info(f"Found {len(candidates)} candidate files from configured locations")

        # Group files by recording_time
        by_time: Dict[str, List[Dict[str, Any]]] = {}
        no_date_files = []

        for file_data in candidates:
            file_id = file_data['file_id']

            # Skip if already indexed
            if file_id in existing_file_ids:
                result['skipped_existing'] += 1
                continue

            # Classify filename to extract metadata
            filename = f"{file_data['file_name']}.{file_data['extension']}"
            directory = file_data['directory'] or ''
            metadata = classify_recording(directory, filename)

            # Build record combining file data and classified metadata
            record = metadata.to_dict()
            record.update({
                'file_id': file_id,
                'file_type': self.db.get_file_type(file_data['extension']),
                'folder': self.db.extract_folder(directory),
                'file_size': file_data['file_size'],
                'source_path': file_data.get('uri', directory),
                'extension': file_data['extension'],
            })

            # Group by recording_time
            recording_time = record.get('recording_time')
            if recording_time:
                time_key = str(recording_time)
                if time_key not in by_time:
                    by_time[time_key] = []
                by_time[time_key].append(record)
            else:
                no_date_files.append(record)
                result['skipped_no_date'] += 1

        self.Info(f"Grouped into {len(by_time)} unique recordings, {len(no_date_files)} files without dates")

        # Insert recordings and files
        if not dry_run:
            for time_key, files in by_time.items():
                # Use first file's metadata for the recording
                first = files[0]

                # Create or get recording
                recording_id = self.db.get_or_create_recording(first)
                result['recordings_created'] += 1

                # Add all files to this recording
                for f in files:
                    if self.db.add_recording_file(recording_id, f):
                        result['files_added'] += 1

                # Update stats (count once per recording)
                medium = first.get('medium', 'unknown')
                result['by_medium'][medium] = result['by_medium'].get(medium, 0) + 1

                axis = first.get('axis')
                if axis:
                    result['by_axis'][axis] = result['by_axis'].get(axis, 0) + 1

                next_step = first.get('next_step', 'transcribe')
                result['by_next_step'][next_step] = result['by_next_step'].get(next_step, 0) + 1
        else:
            result['recordings_created'] = len(by_time)
            result['files_added'] = sum(len(files) for files in by_time.values())

            # Stats for dry run
            for time_key, files in by_time.items():
                first = files[0]
                medium = first.get('medium', 'unknown')
                result['by_medium'][medium] = result['by_medium'].get(medium, 0) + 1
                axis = first.get('axis')
                if axis:
                    result['by_axis'][axis] = result['by_axis'].get(axis, 0) + 1
                next_step = first.get('next_step', 'transcribe')
                result['by_next_step'][next_step] = result['by_next_step'].get(next_step, 0) + 1

        # Sample records for output
        sample_times = list(by_time.keys())[:5]
        result['sample_records'] = [
            {
                'title': by_time[t][0].get('title', '')[:50],
                'medium': by_time[t][0].get('medium'),
                'axis': by_time[t][0].get('axis'),
                'recording_time': t,
                'file_count': len(by_time[t]),
            }
            for t in sample_times
        ]

        return result

    def run(self, location_filter: str = None, dry_run: bool = False) -> None:
        """Run the recording indexer with full output."""
        print("\n" + "=" * 60)
        print(f"RECORDING INDEXER v{self.VERSION}")
        print("=" * 60)
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Show configured locations
        print("\n" + "-" * 40)
        print("CONFIGURED RECORDING LOCATIONS")
        print("-" * 40)

        recording_locations = self.get_recording_locations()
        if not recording_locations:
            print("  None configured")
        else:
            for loc_id, folder_name, processors in recording_locations:
                print(f"  {loc_id}/{folder_name}")
                print(f"    Processors: {', '.join(processors)}")

        # Show database stats before
        print("\n" + "-" * 40)
        print("DATABASE STATISTICS (BEFORE)")
        print("-" * 40)

        stats_before = self.db.get_stats()
        print(f"Unique recordings: {stats_before['total_recordings']:,}")
        print(f"Total files: {stats_before['total_files']:,}")
        print(f"  - Video: {stats_before['video_files']:,}")
        print(f"  - Audio: {stats_before['audio_files']:,}")
        print(f"  - Transcripts: {stats_before['transcripts']:,}")
        if stats_before.get('by_medium'):
            print(f"By medium: {stats_before['by_medium']}")
        if stats_before.get('by_axis'):
            print(f"By axis: {stats_before['by_axis']}")

        # Run indexing
        print("\n" + "=" * 60)
        print("STARTING INDEXING" + (" (DRY RUN)" if dry_run else ""))
        print("=" * 60)

        result = self.index(location_filter=location_filter, dry_run=dry_run)

        # Show results
        print("\n" + "-" * 40)
        print("INDEXING RESULTS")
        print("-" * 40)
        print(f"Scanned: {result['scanned']:,} files")
        print(f"Recordings created: {result['recordings_created']:,}")
        print(f"Files added: {result['files_added']:,}")
        print(f"Skipped (existing): {result['skipped_existing']:,}")
        print(f"Skipped (no date): {result['skipped_no_date']:,}")

        if result['by_medium']:
            print(f"\nBy medium:")
            for medium, count in sorted(result['by_medium'].items(), key=lambda x: -x[1]):
                print(f"  {medium}: {count}")

        if result['by_axis']:
            print(f"\nBy axis:")
            for axis, count in sorted(result['by_axis'].items(), key=lambda x: -x[1]):
                print(f"  {axis}: {count}")

        if result['by_next_step']:
            print(f"\nBy next_step:")
            for step, count in sorted(result['by_next_step'].items(), key=lambda x: -x[1]):
                print(f"  {step}: {count}")

        if result.get('errors'):
            print(f"\nErrors: {len(result['errors'])}")
            for err in result['errors']:
                print(f"  - {err}")

        if result.get('sample_records'):
            print("\nSample recordings:")
            for sample in result['sample_records']:
                print(f"  - {sample['title']} [{sample['medium']}] ({sample['file_count']} files)")

        # Show database stats after (only if not dry run)
        if not dry_run:
            print("\n" + "-" * 40)
            print("DATABASE STATISTICS (AFTER)")
            print("-" * 40)

            stats_after = self.db.get_stats()
            added_recs = stats_after['total_recordings'] - stats_before['total_recordings']
            added_files = stats_after['total_files'] - stats_before['total_files']

            print(f"Unique recordings: {stats_after['total_recordings']:,} (+{added_recs:,})")
            print(f"Total files: {stats_after['total_files']:,} (+{added_files:,})")

        print("\n" + "=" * 60)
        print(f"COMPLETED at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)


# .. gone
if __name__ == '__main__':
    init_logger('recording-indexer')
    Env.from_env(name='file_indexer', app_path=Path('/home/alex/CRAP/_config/file_indexer'))

    main()

# .. imports, comments and docstring text that read differently now
#    # REVIEW: requires gppu dev-tui (top-level init_logger). Older gppu will ImportError.
#    from gppu import Env, init_logger, Error  # type: ignore

# endregion


# region - CRAP Projects/file_indexer/runner.py as of 2026-11-20 (3)

# .. gone
try:
    from gppu import init_logger  # type: ignore  # noqa: E402
except ImportError:
    from gppu.gppu import init_logger  # type: ignore  # noqa: E402


# .. changed; the one of now is in CRAP Projects/file_indexer/runner.py
class IndexerRunner(_Base):
    """Claim and execute run requests addressed to this host."""

    VERSION = "1.0.0"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.host = current_host()
        settings = glob_dict('runner')
        self.wait_seconds = settings['wait_seconds']
        self.heartbeat_seconds = settings['heartbeat_seconds']
        self._db: Optional[FileDatabase] = None

    @property
    def db(self) -> FileDatabase:
        if self._db is None:
            self._db = FileDatabase()
        return self._db

    # --
    #    Job execution
    # --

    def _index_location(self, run: Dict[str, Any]) -> Dict[str, Any]:
        """Walk one configured location, in-process."""
        location_id = run['location_id'].strip()  # CHAR(16) is space-padded
        with FileIndexer() as indexer:
            return indexer.index_configured_location(
                location_id, prefer_smb=run['prefer_smb'],
            )

    def _run_clusterings(self, _run: Dict[str, Any]) -> Dict[str, Any]:
        """Re-apply the declarative rule clusterings.

        Run as a subprocess rather than imported: `scripts/run_rule_clusterings.py`
        is a zero-arg script whose progress is its stdout, and its output is what
        the admin UI shows for this job.
        """
        completed = subprocess.run(
            [sys.executable, str(CLUSTERINGS_SCRIPT)],
            capture_output=True,
            cwd=str(FILE_INDEXER_DIR),
            text=True,
        )
        result = {
            'status': 'completed' if completed.returncode == 0 else 'failed',
            'returncode': completed.returncode,
            'output': completed.stdout,
        }
        if completed.returncode != 0:
            result['error'] = completed.stderr.strip() or f"exit {completed.returncode}"
        return result

    @staticmethod
    def reload_config() -> None:
        """Re-read the config from disk before running a job.

        `Env` is process-global and loaded once at startup, so a long-lived
        daemon would serve every request against the configuration it happened
        to start with — a location added in the admin UI would fail with
        "unknown configured location" until someone restarted the runner, and an
        edited rule would silently not apply. `from_env` re-reads the YAML and is
        documented as safe to call repeatedly (its file-logging setup is
        idempotent per path).
        """
        Env.from_env(name='file_indexer', app_path=REPO_ROOT / '_config' / 'file_indexer')

    def _execute_job(self, run: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch on `kind`; the CHECK constraint in migration 007 bounds it."""
        if run['kind'] == 'index_location':
            return self._index_location(run)
        if run['kind'] == 'run_clusterings':
            return self._run_clusterings(run)
        raise ValueError(f"unsupported run kind: {run['kind']}")

    def execute(self, run: Dict[str, Any]) -> None:
        """Execute one claimed request and record its outcome on the row.

        A failing job is recorded as `failed` and the daemon keeps serving: the
        error is the run row's payload, not something swallowed. Anything that
        also breaks recording (a dead database) still propagates out of `serve`.
        """
        kind = run['kind']
        label = f"run {run['id']} ({kind}{' ' + run['location_id'].strip() if run['location_id'] else ''})"
        self.Info(f"Starting {label}")
        try:
            self.reload_config()
            with _Heartbeat(run['id'], self.heartbeat_seconds):
                result = self._execute_job(run)
        except Exception as error:
            self.Error(f"{label} failed: {error}")
            self.db.finish_indexer_run(
                run['id'], 'failed',
                error="".join(traceback.format_exception_only(type(error), error)).strip(),
            )
            return

        status = 'completed' if result.get('status') == 'completed' else 'failed'
        self.db.finish_indexer_run(
            run['id'],
            status,
            processed_files=result.get('processed_files'),
            failed_files=result.get('failed_files'),
            result=result,
            error=result.get('error'),
        )
        self.Info(f"Finished {label}: {status}")

    # --
    #    Queue loop
    # --

    def drain(self) -> int:
        """Execute every request queued for this host. Returns how many ran."""
        executed = 0
        while True:
            run = self.db.claim_indexer_run(self.host, self.host, os.getpid())
            if run is None:
                return executed
            self.execute(run)
            executed += 1

    def _wait(self) -> None:
        """Block until notified for this host, or until `wait_seconds` elapses."""
        connection = self.db.connection
        connection.poll()
        connection.notifies.clear()
        select.select([connection], [], [], self.wait_seconds)
        connection.poll()
        connection.notifies.clear()

    def _listen(self) -> None:
        """Subscribe the queue connection to the wake-up channel."""
        with self.db.cursor(dict_cursor=False) as cur:
            cur.execute(f"LISTEN {INDEXER_RUN_CHANNEL}")

    def _reconnect(self) -> None:
        """Replace a dropped queue connection and re-subscribe.

        Between runs the daemon sits on one idle connection, and the server
        eventually closes it — observed as `SSL connection has been closed
        unexpectedly` on the next claim, which killed the process. Reconnecting
        is the declared recovery for that transport failure and nothing else:
        only psycopg2's two connection-level errors are caught here, so a query
        or data error still propagates and stops the runner.
        """
        self.close()
        self._listen()

    def serve(self) -> None:
        """Drain, then wait for the next notification, forever."""
        self._listen()
        orphaned = self.db.fail_orphaned_indexer_runs(
            self.host, f"interrupted: the runner on {self.host} restarted mid-run",
        )
        if orphaned:
            self.Warn(f"Failed {orphaned} run(s) interrupted by a previous restart")
        self.Info(
            f"Runner serving host '{self.host}' "
            f"(wait {self.wait_seconds}s, heartbeat {self.heartbeat_seconds}s)"
        )
        while True:
            try:
                self.drain()
                self._wait()
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as error:
                self.Warn(f"Queue connection lost ({type(error).__name__}: {error}); reconnecting")
                self._reconnect()

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None


# .. changed; the one of now is in CRAP Projects/file_indexer/runner.py
def main() -> None:
    init_logger('file-indexer-runner')
    Env.from_env(name='file_indexer', app_path=REPO_ROOT / '_config' / 'file_indexer')
    runner = IndexerRunner()
    try:
        runner.serve()
    except KeyboardInterrupt:
        runner.Info("Runner stopped")
    finally:
        runner.close()

# .. imports, comments and docstring text that read differently now
#    from gppu import Env  # noqa: E402

# endregion


# region - CRAP Projects/file_indexer/scripts/apply_telemetry_canonicalization.py as of 2026-11-20 (2)

# .. gone
try:
    from gppu import init_logger  # type: ignore  # noqa: E402
except ImportError:
    from gppu.gppu import init_logger  # type: ignore  # noqa: E402


# .. changed; the one of now is in CRAP Projects/file_indexer/scripts/apply_telemetry_canonicalization.py
def main() -> int:
    if len(sys.argv) != 1:
        raise SystemExit("apply_telemetry_canonicalization accepts no arguments")
    init_logger("telemetry-canonicalization-apply")
    Env.from_env(
        name="file_indexer",
        app_path=REPO_ROOT / "_config" / "file_indexer",
    )
    db = FileDatabase()
    try:
        applied = apply_canonical_assignments(db, glob_dict("telemetry_inventory"))
    finally:
        db.close()
    sys.stdout.write(json.dumps({"applied": applied}, ensure_ascii=False, sort_keys=True) + "\n")
    return 0

# .. imports, comments and docstring text that read differently now
#    from gppu import Env  # noqa: E402

# endregion


# region - CRAP Projects/file_indexer/scripts/apply_telemetry_metadata.py as of 2026-11-20 (2)

# .. gone
try:
    from gppu import init_logger  # type: ignore  # noqa: E402
except ImportError:
    from gppu.gppu import init_logger  # type: ignore  # noqa: E402


# .. changed; the one of now is in CRAP Projects/file_indexer/scripts/apply_telemetry_metadata.py
def main() -> int:
    if len(sys.argv) != 1:
        raise SystemExit("apply_telemetry_metadata accepts no arguments")
    init_logger("telemetry-metadata-apply")
    Env.from_env(
        name="file_indexer",
        app_path=REPO_ROOT / "_config" / "file_indexer",
    )
    db = FileDatabase()
    try:
        result = apply_telemetry_metadata(
            db,
            glob_dict("telemetry_inventory"),
            glob_dict("locations"),
        )
    finally:
        db.close()
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0

# .. imports, comments and docstring text that read differently now
#    from gppu import Env  # noqa: E402

# endregion


# region - CRAP Projects/file_indexer/scripts/backfill_null_indexed_locations.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Projects/file_indexer/scripts/backfill_null_indexed_locations.py
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true',
                    help='actually run the UPDATE (default: dry-run)')
    ap.add_argument('--location', default=None,
                    help='restrict to a single location id (default: all NULL-stale)')
    args = ap.parse_args()

    from gppu.app import Env  # type: ignore
    from gppu.gppu import init_logger  # type: ignore
    init_logger('backfill-null-indexed')
    Env.from_env(name='file_indexer', app_path=Path('_config/file_indexer'))

    from database_schema import FileDatabase

    db = FileDatabase()
    with db.cursor() as cur:
        sql = """
            SELECT l.id, l.last_indexed, l.files_indexed,
                   (SELECT count(*) FROM files f
                    JOIN file_paths fp ON f.path_id=fp.id
                    WHERE fp.location_id=l.id) AS actual_files
              FROM locations l
             WHERE l.last_indexed IS NULL
               AND l.id IN (SELECT DISTINCT location_id FROM file_paths)
        """
        params: tuple = ()
        if args.location:
            sql += " AND l.id = %s"
            params = (args.location,)
        sql += " ORDER BY actual_files DESC"
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        print('no NULL-stale locations to backfill')
        return 0

    print(f'== {len(rows)} location(s) with NULL last_indexed + nonzero file_paths ==')
    for r in rows:
        print(f"  {r['id']:<20} actual_files={r['actual_files']:>8}")

    if not args.apply:
        print('\ndry run — pass --apply to backfill')
        return 0

    print('\n== applying ==')
    for r in rows:
        result = db.update_location_stats(r['id'])
        print(f"  {result['location_id']:<20} -> last_indexed={result['last_indexed']}"
              f" files_indexed={result['files_indexed']}")
    return 0

# endregion


# region - CRAP Projects/file_indexer/scripts/build_telemetry_manifest.py as of 2026-11-20 (2)

# .. gone
try:
    from gppu import init_logger  # type: ignore  # noqa: E402
except ImportError:
    from gppu.gppu import init_logger  # type: ignore  # noqa: E402


# .. changed; the one of now is in CRAP Projects/file_indexer/scripts/build_telemetry_manifest.py
def main() -> int:
    if len(sys.argv) != 1:
        raise SystemExit("build_telemetry_manifest accepts no arguments")
    init_logger("telemetry-manifest")
    Env.from_env(
        name="file_indexer",
        app_path=REPO_ROOT / "_config" / "file_indexer",
    )
    config = glob_dict("telemetry_inventory")
    db = FileDatabase()
    try:
        manifest = build_telemetry_manifest(
            db, config, glob_dict("locations"), glob_dict("shares")
        )
    finally:
        db.close()
    serialized = serialize_telemetry_manifest(manifest)
    if "manifest_output_path" in config:
        publish_manifest_atomic(serialized, Path(config["manifest_output_path"]))
    else:
        sys.stdout.write(serialized)
    return 0

# .. imports, comments and docstring text that read differently now
#    from gppu import Env  # noqa: E402

# endregion


# region - CRAP Projects/file_indexer/scripts/extract_archives.py as of 2026-11-20 (2)

# .. gone
try:
    from gppu import Env, init_logger, glob_dict, glob_list  # type: ignore
except ImportError:  # older gppu — pull logger from submodule
    from gppu import Env, glob_dict, glob_list  # type: ignore
    from gppu.gppu import init_logger  # type: ignore


# .. changed; the one of now is in CRAP Projects/file_indexer/scripts/extract_archives.py
def main() -> None:
    if len(sys.argv) != 1:
        raise SystemExit("extract_archives accepts no arguments")

    init_logger("extract-archives")
    Env.from_env(
        name="file_indexer",
        app_path=Path(__file__).resolve().parent.parent.parent / "_config" / "file_indexer",
    )

    locations = glob_dict("locations")
    if not locations:
        raise SystemExit("no `locations` defined in config")
    shares = glob_dict("shares")
    inventory_config = glob_dict("telemetry_inventory")
    scopes = selected_archive_scopes(inventory_config)
    roots = resolve_selected_roots(
        scopes,
        locations,
        shares,
        glob_list("exclude_locations"),
    )

    db = FileDatabase()
    try:
        result = index_selected_archive_members(db, scopes, roots)
    finally:
        db.close()

    print(
        f"Selected {', '.join(result['selected_locations'])}: "
        f"{result['listed']} listed, {result['errored']} errored, "
        f"{result['skipped_out_of_scope']} skipped outside declared scope"
    )

# endregion


# region - CRAP Projects/file_indexer/scripts/index_selected_locations.py as of 2026-11-20 (2)

# .. gone
try:
    from gppu import init_logger  # type: ignore  # noqa: E402
except ImportError:
    from gppu.gppu import init_logger  # type: ignore  # noqa: E402


# .. changed; the one of now is in CRAP Projects/file_indexer/scripts/index_selected_locations.py
def main() -> int:
    if len(sys.argv) != 1:
        raise SystemExit("index_selected_locations accepts no arguments")
    init_logger("file-indexer-selected-locations")
    Env.from_env(
        name="file_indexer",
        app_path=REPO_ROOT / "_config" / "file_indexer",
    )
    config = glob_dict("telemetry_inventory")
    with FileIndexer() as indexer:
        results = run_selected_locations(indexer, config)
    sys.stdout.write(json.dumps(results, default=str, ensure_ascii=False, sort_keys=True) + "\n")
    return 0

# .. imports, comments and docstring text that read differently now
#    from gppu import Env  # noqa: E402

# endregion


# region - CRAP Projects/file_indexer/scripts/ingest_developer_sessions.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Projects/file_indexer/scripts/ingest_developer_sessions.py
def main() -> int:
    if len(sys.argv) != 1:
        raise SystemExit("ingest_developer_sessions accepts no arguments")
    from gppu import Env, glob_dict

    config_root = FILE_INDEXER_DIR.parent / "_config" / "file_indexer"
    # The deployed gppu exposes ``from_env``; the currently installed local
    # release exposes the same operation as constructor + ``load``.
    from_env = getattr(Env, "from_env", None)
    if callable(from_env):
        from_env(name="file_indexer", app_path=config_root)
    else:
        Env("file_indexer", config_root)
        Env.load()
    config = glob_dict("developer_sessions")
    if not config:
        raise SystemExit("no `developer_sessions` configuration is defined")
    reports = run_configured(config)
    print(
        json.dumps(
            {
                "schema_version": BATCH_REPORT_SCHEMA,
                "reports": {str(report["provider"]): report for report in reports},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if all(report["run_success_count"] == 1 for report in reports) else 1

# endregion


# region - CRAP Projects/file_indexer/scripts/reindex_after_folder_classes_20260720.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Projects/file_indexer/scripts/reindex_after_folder_classes_20260720.py
def main():
    init_logger('file-indexer')
    # Relative, matching file_indexer.py's own __main__ block — gppu's
    # _resolve_app_path walks up from this script's directory to find
    # ../_config/file_indexer (the real config lives beside file_indexer/,
    # not inside it). An absolute path here would skip that walk-up entirely.
    Env.from_env(name='file_indexer', app_path=Path('_config/file_indexer'))

    locations = glob_dict('locations')

    with FileIndexer() as indexer:
        for loc_id in TARGET_LOCATIONS:
            cfg = locations.get(loc_id)
            if cfg is None:
                print(f"SKIP {loc_id}: not present in locations config")
                continue

            print(f"\n=== {loc_id} ===", flush=True)
            start = time.time()
            try:
                result = indexer.index_location(loc_id, cfg)
            except Exception as e:
                print(f"ERROR {loc_id}: {type(e).__name__}: {e}", flush=True)
                continue
            elapsed = time.time() - start
            print(
                f"DONE {loc_id}: status={result.get('status')} "
                f"processed={result.get('processed_files')} "
                f"failed={result.get('failed_files')} "
                f"elapsed={elapsed:.1f}s",
                flush=True,
            )

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, init_logger  # type: ignore

# endregion


# region - CRAP Projects/file_indexer/scripts/report_telemetry_inventory.py as of 2026-11-20 (2)

# .. gone
try:
    from gppu import init_logger  # type: ignore  # noqa: E402
except ImportError:
    from gppu.gppu import init_logger  # type: ignore  # noqa: E402


# .. changed; the one of now is in CRAP Projects/file_indexer/scripts/report_telemetry_inventory.py
def main() -> int:
    if len(sys.argv) != 1:
        raise SystemExit("report_telemetry_inventory accepts no arguments")
    init_logger("telemetry-inventory-report")
    Env.from_env(
        name="file_indexer",
        app_path=REPO_ROOT / "_config" / "file_indexer",
    )
    db = FileDatabase()
    try:
        report = build_inventory_report(
            db,
            glob_dict("telemetry_inventory"),
            glob_dict("locations"),
            glob_dict("shares"),
        )
    finally:
        db.close()
    sys.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n")
    return 0

# .. imports, comments and docstring text that read differently now
#    from gppu import Env  # noqa: E402

# endregion


# region - CRAP Projects/file_indexer/scripts/run_rule_clusterings.py as of 2026-11-20 (2)

# .. gone
try:
    from gppu import init_logger  # type: ignore  # noqa: E402
except ImportError:
    from gppu.gppu import init_logger  # type: ignore  # noqa: E402


# .. changed; the one of now is in CRAP Projects/file_indexer/scripts/run_rule_clusterings.py
def main() -> None:
    init_logger('run-rule-clusterings')
    Env.from_env(name='file_indexer',
                 app_path=Path(__file__).resolve().parent.parent.parent / '_config' / 'file_indexer')

    clusterings = glob_dict('clusterings')
    if not clusterings:
        raise SystemExit("no `clusterings` defined in config")

    db = FileDatabase()
    try:
        for name, spec in clusterings.items():
            if spec.get('kind') != 'rule':
                print(f"{name}: kind={spec.get('kind')} — only 'rule' is runnable here, skipping")
                continue
            sql = CANDIDATE_SQL.get(name)
            if sql is None:
                print(f"{name}: no candidate SQL registered in this runner, skipping")
                continue

            with db.cursor() as cur:
                cur.execute(sql)
                rows = [dict(r) for r in cur.fetchall()]
            print(f"{name}: {len(rows)} candidate rows")

            clusterer = RuleClusterer(
                name=name,
                rules=spec.get('rules') or [],
                default_label=spec.get('default_label', 'unlabeled'),
                description=spec.get('description') or '',
                created_by='run_rule_clusterings',
            )
            with db.cursor() as cur:
                # Resync semantics: rules are first-match-wins (one label per file),
                # but apply() only upserts — after a rule change, a reassigned file
                # would keep its old membership too. Clear this clustering's
                # memberships for the files being re-fed; cluster rows (which carry
                # annotations) are never deleted.
                cur.execute("""
                    DELETE FROM file_cluster_memberships fcm
                    USING clusters c, clusterings cl
                    WHERE c.id = fcm.cluster_id
                      AND cl.id = c.clustering_id
                      AND cl.name = %s
                      AND fcm.file_id = ANY(%s)
                """, (name, [r['file_id'] for r in rows]))
                counts = apply_clustering(cur, clusterer, rows)
            print(f"{name}: clustering_id={counts['clustering_id']} "
                  f"clusters={counts['clusters_written']} memberships={counts['memberships_written']}")

            with db.cursor() as cur:
                cur.execute("""
                    SELECT c.label, c.member_count
                    FROM clusters c
                    WHERE c.clustering_id = %s
                    ORDER BY c.member_count DESC
                """, (counts['clustering_id'],))
                for r in cur.fetchall():
                    print(f"    {r['label']}: {r['member_count']}")
    finally:
        db.close()

# .. imports, comments and docstring text that read differently now
#    from gppu import Env  # noqa: E402

# endregion


# region - CRAP Projects/file_indexer/scripts/run_smb_fullpass.py as of 2026-11-20 (3)

# .. gone
init_logger('smb-fullpass-driver')


# .. gone
Env.from_env(name='file_indexer', app_path=_P('_config/file_indexer'))


# .. changed; the one of now is in CRAP Projects/file_indexer/scripts/run_smb_fullpass.py
def _candidate_shares(only_mounted_s1: bool, slugs_filter: list[str] | None) -> list[tuple[str, dict]]:
    locations = glob_dict('locations')
    out: list[tuple[str, dict]] = []
    # If a slug filter is given, preserve its order (smallest→largest is the
    # canonical ops order). Otherwise iterate yaml insertion order.
    iter_slugs = slugs_filter if slugs_filter else list(locations.keys())
    for slug in iter_slugs:
        cfg = locations.get(slug)
        if not isinstance(cfg, dict):
            continue
        if cfg.get('server_type') != 'smb':
            continue
        if cfg.get('enabled') is False:
            continue
        if only_mounted_s1 and cfg.get('hostname') != 's1.karel.in':
            continue
        macos_path = (cfg.get('paths') or {}).get('macos')
        if macos_path and not Path(macos_path).exists():
            continue  # silently skip un-mounted
        out.append((slug, cfg))
    return out

# .. imports, comments and docstring text that read differently now
#    from gppu.app import Env, glob_dict  # type: ignore
#    from gppu.gppu import init_logger  # type: ignore

# endregion


# region - CRAP Projects/file_indexer/scripts/t_3de3ab8b_apply.py as of 2026-11-20 (2)

# .. gone
init_logger('t_3de3ab8b-apply')


# .. gone
Env.from_env(name='file_indexer', app_path=Path('_config/file_indexer'))

# .. imports, comments and docstring text that read differently now
#    from gppu.app import Env  # type: ignore
#    from gppu.gppu import init_logger  # type: ignore

# endregion


# region - CRAP Projects/file_indexer/scripts/t_d1415c23_apply.py as of 2026-11-20 (3)

# .. gone
init_logger('t_d1415c23-apply')


# .. gone
# Use this worktree's config so the new file_types.yaml additions are picked up.
Env.from_env(name='file_indexer', app_path=Path('/tmp/wt-t_d1415c23/_config/file_indexer'))


# .. changed
# Verify what classes/types we're about to sync from THIS worktree's YAML.
ftc = glob_dict('file_types').get('file_type_classes', {})

# .. imports, comments and docstring text that read differently now
#    from gppu.app import Env, glob_dict  # type: ignore
#    from gppu.gppu import init_logger  # type: ignore

# endregion


# region - CRAP Projects/file_indexer/sharepoint_walker.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Projects/file_indexer/sharepoint_walker.py
def walk_site(dsn: str, auth: PnPAuth, location: LocationRow,
              only_library: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Discover libraries and walk them."""
    discovered = list_libraries(auth)
    if not discovered.get('ok'):
        return {'site_url': auth.site_url, 'error': discovered}

    libs = discovered.get('libraries') or []
    if only_library:
        libs = [l for l in libs if l.get('title') == only_library]
        if not libs:
            return {'site_url': auth.site_url, 'error': f'library not found: {only_library}',
                    'available': [l.get('title') for l in discovered.get('libraries') or []]}

    # Connect once per site
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from gppu.app import Env
    Env.from_dict({'db': dsn})
    from database_schema import FileDatabase
    db = FileDatabase()

    site_stats: Dict[str, Any] = {
        'site_url': auth.site_url, 'location_id': location.id,
        'libraries_discovered': len(libs), 'libraries': [],
    }
    try:
        for lib in libs:
            title = lib['title']
            print(f'[walk] {auth.site_url} / {title} ({lib.get("item_count", 0)} items)', file=sys.stderr)
            try:
                stats = walk_library(db, auth, location, title, dry_run=dry_run)
            except Exception as e:
                stats = LibStats(site_url=auth.site_url, library=title, error=str(e))
                stats.ended_at = time.time()
            site_stats['libraries'].append(stats.to_dict())

        if not dry_run:
            total = sum(l['files_inserted'] for l in site_stats['libraries'])
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE locations SET last_indexed = NOW(), files_indexed = %s WHERE id = %s",
                    (total, location.id))
            site_stats['files_indexed'] = total
    finally:
        db.close()
    return site_stats

# endregion


# region - CRAP Projects/file_indexer/sync_files.py as of 2026-11-20 (3)

# .. gone
def load_config() -> None:
    """Load configuration from config.yaml using gppu."""
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    config_data = dict_from_yml(config_path)
    Env._from_dict(config_data)


# .. changed; the one of now is in CRAP Projects/file_indexer/sync_files.py
def get_db_connection():
    """Create database connection from config."""
    db_connection = glob('db')
    if not db_connection:
        raise ValueError("Database connection string 'db' not found in config")
    return psycopg2.connect(db_connection)


# .. changed; the one of now is in CRAP Projects/file_indexer/sync_files.py
def sync_files(
    server_name: str,
    server_type: str,
    location_name: str,
    location_path: str,
    local_path: str,
    dry_run: bool = False,
    with_md5: bool = False,
    hostname: str = None
) -> Dict[str, Any]:
    """Main sync function."""

    result = {
        'timestamp': datetime.now().isoformat(),
        'server': server_name,
        'location': location_path,
        'local_path': local_path,
        'dry_run': dry_run,
        'scanned': 0,
        'inserted': 0,
        'updated': 0,
        'marked_missing': 0,
        'unchanged': 0,
        'by_class': {},
        'errors': []
    }

    load_config()

    # Scan filesystem
    print(f"Scanning {local_path}...", file=sys.stderr)
    local_files = scan_files(local_path, with_md5=with_md5)
    result['scanned'] = len(local_files)

    if not local_files:
        result['errors'].append(f"No files found in {local_path}")
        return result

    print(f"Found {len(local_files)} files", file=sys.stderr)

    try:
        conn = get_db_connection()

        # Get or create server and location
        server_id = get_or_create_server(conn, server_name, server_type, hostname)
        location_id = get_or_create_location(conn, server_id, location_name, location_path)

        # Get existing files from DB for this location
        existing_files = get_existing_files(conn, location_id)
        print(f"Found {len(existing_files)} existing files in DB", file=sys.stderr)

        # Track statistics by file type class
        class_counts = {}

        # Process files
        now = datetime.now()
        to_insert = []
        to_update = []
        path_cache = {}

        for file_key, info in local_files.items():
            # Resolve file type
            file_type, file_type_class = resolve_file_type(conn, info['extension'])

            # Track by class
            if file_type_class:
                class_counts[file_type_class] = class_counts.get(file_type_class, 0) + 1

            # Get or create path_id
            dir_path = info['directory']
            if dir_path not in path_cache:
                path_cache[dir_path] = get_or_create_path(conn, location_id, dir_path)
            path_id = path_cache[dir_path]

            # Check if file exists in DB
            if file_key in existing_files:
                existing = existing_files[file_key]
                # Check if update needed (size or md5 changed)
                size_changed = existing['file_size'] != info['size']
                md5_changed = info['md5'] and existing.get('md5') and existing['md5'].hex() != info['md5']

                if size_changed or md5_changed:
                    to_update.append({
                        'id': existing['id'],
                        'size': info['size'],
                        'md5': bytes.fromhex(info['md5']) if info['md5'] else None,
                        'date_modified': info['date_modified'],
                        'file_type': file_type,
                        'file_type_class': file_type_class,
                    })
                else:
                    result['unchanged'] += 1
            else:
                # New file
                to_insert.append({
                    'path_id': path_id,
                    'file_name': info['file_name'],
                    'extension': info['extension'],
                    'file_type': file_type,
                    'file_type_class': file_type_class,
                    'size': info['size'],
                    'md5': bytes.fromhex(info['md5']) if info['md5'] else None,
                    'date_created': info['date_created'],
                    'date_modified': info['date_modified'],
                })

        # Find missing files (in DB but not on disk)
        local_keys = set(local_files.keys())
        existing_keys = set(existing_files.keys())
        missing_keys = existing_keys - local_keys
        missing_ids = [existing_files[k]['id'] for k in missing_keys]

        result['by_class'] = class_counts

        if not dry_run:
            with conn.cursor() as cur:
                # Insert new files
                for file_data in to_insert:
                    cur.execute("""
                        INSERT INTO files (
                            path_id, file_name, extension, file_type, file_type_class,
                            file_size, md5, date_created, date_modified, indexed_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        file_data['path_id'],
                        file_data['file_name'],
                        file_data['extension'],
                        file_data['file_type'],
                        file_data['file_type_class'],
                        file_data['size'],
                        file_data['md5'],
                        file_data['date_created'],
                        file_data['date_modified'],
                        now
                    ))
                result['inserted'] = len(to_insert)

                # Update existing files
                for file_data in to_update:
                    cur.execute("""
                        UPDATE files SET
                            file_size = %s,
                            md5 = COALESCE(%s, md5),
                            date_modified = %s,
                            file_type = %s,
                            file_type_class = %s,
                            indexed_at = %s
                        WHERE id = %s
                    """, (
                        file_data['size'],
                        file_data['md5'],
                        file_data['date_modified'],
                        file_data['file_type'],
                        file_data['file_type_class'],
                        now,
                        file_data['id']
                    ))
                result['updated'] = len(to_update)

                # Mark missing files by setting metadata flag
                if missing_ids:
                    cur.execute("""
                        UPDATE files SET
                            metadata = COALESCE(metadata, '{}'::jsonb) || '{"status": "missing"}'::jsonb,
                            indexed_at = %s
                        WHERE id = ANY(%s)
                    """, (now, missing_ids))
                result['marked_missing'] = len(missing_ids)

                conn.commit()

                # Update path indexing stats
                for dir_path, path_id in path_cache.items():
                    file_count = sum(1 for f in local_files.values() if f['directory'] == dir_path)
                    cur.execute("""
                        UPDATE file_paths SET last_indexed = %s, files_indexed = %s
                        WHERE id = %s
                    """, (now, file_count, path_id))
                conn.commit()
        else:
            result['inserted'] = len(to_insert)
            result['updated'] = len(to_update)
            result['marked_missing'] = len(missing_ids)
            result['would_insert_sample'] = [f"{d['file_name']}.{d['extension']}" for d in to_insert[:5]]
            result['would_mark_missing_sample'] = list(missing_keys)[:5]

        conn.close()

    except Exception as e:
        result['errors'].append(str(e))
        import traceback
        result['traceback'] = traceback.format_exc()

    return result

# .. imports, comments and docstring text that read differently now
#    from gppu import Env, dict_from_yml

# endregion


# region - CRAP Projects/file_indexer/test_runner.py as of 2026-11-20 (1)

# .. gone
class ConfigReloadTest(unittest.TestCase):
    """A daemon that caches config from startup silently ignores every edit the
    admin UI makes — a location added there fails as unknown until a restart."""

    def setUp(self):
        patcher = patch.object(runner_module, "_Heartbeat", _no_heartbeat)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_config_is_reloaded_before_each_job(self):
        runner = _StubbedRunner()
        order = []
        runner.reload_config = lambda: order.append("reload")
        runner._index_location = lambda run: order.append("run") or {"status": "completed"}

        runner.execute(_run())

        self.assertEqual(order, ["reload", "run"])

    def test_a_failing_reload_is_recorded_on_the_run(self):
        runner = _StubbedRunner()

        def explode():
            raise FileNotFoundError("no config")

        runner.reload_config = explode
        runner._index_location = lambda run: {"status": "completed"}

        runner.execute(_run())

        _, status = runner._db.finish_indexer_run.call_args.args
        self.assertEqual(status, "failed")
        self.assertIn("FileNotFoundError", runner._db.finish_indexer_run.call_args.kwargs["error"])

# endregion


# region - CRAP Projects/file_indexer/tests/test_folder_classes.py as of 2026-11-20 (1)

# .. gone
Env.from_env(name='file_indexer',
             app_path=_ConfigPath(os.path.join(_REPO_ROOT, '..', '_config', 'file_indexer')))

# .. imports, comments and docstring text that read differently now
#    from gppu import Env  # noqa: E402

# endregion


# region - CRAP Projects/file_indexer/web_ui.py as of 2026-11-20 (1)

# .. gone
if __name__ == '__main__':
    init_logger('web-ui')
    # Portable app_path (gppu walks up from the script dir), same pattern as
    # file_indexer.py — the previous absolute /home/alex/... path only resolved
    # on the mac/WSL hosts.
    Env.from_env(name='file_indexer', app_path=Path('_config/file_indexer'))

    main()

# .. imports, comments and docstring text that read differently now
#    # REVIEW: requires gppu dev-tui (top-level init_logger). Older gppu will ImportError.
#    from gppu import Env, init_logger  # type: ignore

# endregion


# region - CRAP Projects/ticktick-export/operon_remove.py as of 2026-11-20 (3)

# .. gone
APP['cli'] = True  # operon_remove.yaml beside this file; --path on the command line names the note


# .. gone
def main() -> None:
    path = glob('path')
    if not path:
        raise RuntimeError('set path to the note whose Operon tasks are removed')
    tasks = query(path, [])
    Info(len(tasks), 'tasks in', path)
    by_id = {t['identity']['operonId']: t for t in tasks}
    removed = []
    while by_id:
        leaves = [t for t in by_id.values() if not any(c in by_id for c in t['relationships']['childOperonIds'])]
        for t in leaves:
            op = t['identity']['operonId']
            if t['recurrence'].get('repeating'):
                applied(lambda: operon('task', 'update', '--id', op, '--clear', 'repeat', '--scope', 'this-and-following'), f'clear repeat on {op}')
            if t['relationships'].get('parentOperonId') or t.get('parentTask'):
                applied(lambda: operon('task', 'update', '--id', op, '--clear', 'parentTask'), f'clear parent on {op}')
            delete(op)
            removed.append((op, t['description']))
            del by_id[op]
            Info('removed', op, t['description'])
    left = query(path, [])
    Info('removed', len(removed), 'tasks;', len(left), 'remain in', path)
    if left:
        raise RuntimeError(f'{len(left)} tasks remain in {path}')


# .. gone
if __name__ == '__main__':
    main()

# .. imports, comments and docstring text that read differently now
#    from gppu import APP, Info, glob

# endregion


# region - CRAP Projects/ticktick-export/operon_remove.yaml as of 2026-11-20

# .. the lines that are gone or read differently now
#    profile: main
#    folder: Operon/Tasks/TickTick
#    work: D:\Work
#    path: ''

# endregion


# region - CRAP Projects/ticktick-export/sync_to_operon.py as of 2026-11-20 (8)

# .. gone
APP['cli'] = True  # sync_to_operon.yaml beside this file; --key value on the command line overrides it


# .. changed
PROFILE = glob('profile')


# .. changed
FOLDER = glob('folder')


# .. changed; the one of now is in CRAP Projects/ticktick-export/sync_to_operon.py
def run_folder() -> Path:
    now = datetime.now(LOCAL)
    folder = Path(glob('work')) / now.strftime('%m') / now.strftime('%d') / 'operon' / 'ticktick-sync' / 'runs' / now.strftime('%H%M%S')
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# .. changed; the one of now is in CRAP Projects/ticktick-export/sync_to_operon.py
def create(folder: Path) -> None:
    items = load(folder, 'items.json')
    vault = Path(operon('profile', 'list')['result']['profiles'][0]['canonicalPath'])
    for item in items:
        ensure_note(vault, item['target']['filePath'], item['list'])
    mapping = existing_map(items)
    Info(len(mapping), 'tasks already in Operon')
    plans = []
    remaining = [i for i in items if i['tt'] not in mapping]
    while remaining:
        progressed = False
        for name in LIST_STATUS:
            batch = [i for i in remaining if i['list'] == name]
            ready = [i for i in batch if not i['parent_tt'] or i['parent_tt'] in mapping or any(p['tt'] == i['parent_tt'] for p in batch)]
            ordered, placed = [], set()  # parents before children, TickTick order otherwise
            while len(ordered) < len(ready):
                for i in ready:
                    if i['tt'] not in placed and (not i['parent_tt'] or i['parent_tt'] in mapping or i['parent_tt'] in placed):
                        ordered.append(i)
                        placed.add(i['tt'])
            for start in range(0, len(ordered), PLAN_ITEMS):
                chunk = ordered[start:start + PLAN_ITEMS]
                ids = {c['tt'] for c in chunk}
                chunk = [i for i in chunk if not i['parent_tt'] or i['parent_tt'] in mapping or i['parent_tt'] in ids]
                if chunk:
                    number = len(list(folder.glob('plan-*-intent.json'))) + 1  # unique across runs on this folder
                    plans.append(create_plan(folder, chunk, mapping, number))
                    progressed = True
                    if glob('preview') == 'true':
                        Info('preview only: stopped after the first plan')
                        return
        remaining = [i for i in items if i['tt'] not in mapping]
        if remaining and not progressed:
            raise RuntimeError(f'{len(remaining)} items could not be created: {[i["description"] for i in remaining][:10]}')
    save(folder, 'map.json', mapping)
    save(folder, 'plans.json', plans)
    Info('created', sum(p['created'] for p in plans), 'tasks in', len(plans), 'plans;', len(mapping), 'mapped in total')


# .. changed; the one of now is in CRAP Projects/ticktick-export/sync_to_operon.py
def create_plan(folder: Path, chunk: list[dict], mapping: dict[str, str], number: int) -> dict:
    refs = {i['tt']: f"tt-{i['tt']}" for i in chunk}
    spec_items = []
    for i in chunk:
        entry = {'itemRef': refs[i['tt']], 'description': i['description'], 'target': i['target'],
                 'fields': i['fields'], 'tags': i['tags'], 'statusId': i['statusId']}
        if i.get('priorityId'):
            entry['priorityId'] = i['priorityId']
        if i['parent_tt']:
            entry['parent'] = ({'kind': 'created', 'itemRef': refs[i['parent_tt']]} if i['parent_tt'] in refs
                               else {'kind': 'existing', 'operonId': mapping[i['parent_tt']]})
        spec_items.append(entry)
    key = hashlib.sha256(','.join(sorted(refs)).encode()).hexdigest()[:48]
    intent = {'contractVersion': 1, 'kind': 'mutation-intent', 'requestId': f'sync-create-{number}-{uuid.uuid4().hex[:8]}',
              'idempotencyKey': f'ticktick-sync-{key}', 'reason': 'TickTick unfinished tasks sync',
              'spec': {'operation': 'create', 'items': spec_items}}
    save(folder, f'plan-{number:02d}-intent.json', intent)
    preview = operon('task', 'create', '--input', '-', stdin=json.dumps(intent))
    save(folder, f'plan-{number:02d}-preview.json', preview)
    plan = ((preview.get('result') or {}).get('plan') or {})
    ref = (preview.get('client') or {}).get('planRef')
    if not preview.get('ok') or not ref:
        raise RuntimeError(f'preview {number} refused: {json.dumps(preview)[:900]}')
    if plan.get('requiresConfirmation') or plan.get('riskLevel') != 'routine' or plan.get('requiredAcknowledgements'):
        raise RuntimeError(f'preview {number} needs a person: risk {plan.get("riskLevel")}, confirmation {plan.get("requiresConfirmation")}, planRef {ref}')
    Info(f'plan {number}: {len(spec_items)} tasks into {chunk[0]["target"]["filePath"]}, planRef {ref}, warnings {len(plan.get("warnings") or [])}')
    if glob('preview') == 'true':
        save(folder, f'plan-{number:02d}-discard.json', operon('plan', 'discard', ref))
        return {'number': number, 'planRef': ref, 'file': chunk[0]['target']['filePath'], 'created': 0}
    applied = operon('plan', 'apply', ref)
    save(folder, f'plan-{number:02d}-apply.json', applied)
    if not applied.get('ok'):
        raise RuntimeError(f'apply {number} failed: {json.dumps(applied)[:900]}')
    ids = {e['itemRef']: e['operonId'] for e in plan.get('createEffects') or []}
    for i in chunk:
        mapping[i['tt']] = ids[refs[i['tt']]]
    return {'number': number, 'planRef': ref, 'file': chunk[0]['target']['filePath'], 'created': len(chunk)}


# .. gone
def main() -> None:
    if not OPERON or not Path(OPERON[1]).exists():
        raise RuntimeError('operon CLI not on PATH, or its Node module is not where the npm shim points')
    stage, until = glob('stage'), glob('until')
    if stage not in STAGES or until not in STAGES:
        raise RuntimeError(f'stage and until must be one of {STAGES}')
    folder = Path(glob('raw')) if glob('raw') else run_folder()
    if stage != 'tasks' and not (folder / 'tasks.json').exists():
        raise RuntimeError(f'stage {stage} continues a run; set raw to its folder')
    Info('run folder', folder)
    for name in STAGES[STAGES.index(stage):STAGES.index(until) + 1]:
        Info('stage', name)
        globals()[name](folder)


# .. gone
if __name__ == '__main__':
    main()

# .. imports, comments and docstring text that read differently now
#    from gppu import APP, Info, glob

# endregion


# region - CRAP Projects/ticktick-export/sync_to_operon.yaml as of 2026-11-20

# .. the lines that are gone or read differently now
#    profile: main
#    folder: Operon/Tasks/TickTick
#    work: D:\Work
#    stage: tasks
#    until: verify
#    preview: 'false'
#    raw: ''

# endregion


# region - CRAP Systems/admin_ui/shared/api.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Systems/admin_ui/shared/api.py
class Api(Layer):
  """Shared operations consumed by Admin and the existing specialized applications.

  Graph node identities and relationship endpoints are decimal strings. A node
  retains its label, vocabulary term, displayed meaning, properties and exact
  source references. Relationships retain their type, term and direction.
  Topology queries return the defined Location/Provider/Host/Container views;
  indexed record and timespan rows retain their separate retrieval operations.
  Threads remain the ProjectManager/SessionManager domain. Each public method
  documents its parameters and the structure returned by that operation.
  """
  DAGSTER = 'admin_ui.dagster'
  def __init__(self):
    self._entities = None
    self._bases = None
    self._inventory = None
    self._holdings = None
    from shared.graph_sources import GraphSources, GraphVocabulary
    from shared.graph_pm import GraphProjectManager
    self.sources = GraphSources(self)
    self.vocabulary = GraphVocabulary(self)
    self.project_manager = GraphProjectManager(self)

  @contextmanager
  def process(self, who):
    """Run generated-data operations in one Python process transaction.

    Args:
      who (str): Nonblank producer identity; human identities are not permitted.

    Yields:
      Api: This same API. Its existing annotation and span operations share a
      transaction, retain the producer identity and leave proposals unapproved.
      An exception rolls back the whole transaction. This Python entry point is
      not an HTTP route and does not enable admin_ui or configuration editing.
    """
    if not who.strip() or who.casefold().startswith('human:'):
      raise ValueError('a process requires a non-human producer identity')
    if PROCESS.get() is not None:
      raise ValueError('a process transaction is already open')
    with GraphConnection.connect(configuration.postgres(), row_factory=dict_row) as db:
      age.initialize(db)
      token = PROCESS.set((db, who))
      try:
        yield self
      finally:
        PROCESS.reset(token)
    self.invalidate()

  def session_evidence(self, uid, path):
    """Read a registered session's complete human-turn evidence through gppu.

    Args:
      uid (str): Existing Registry session identity.
      path (str): Accessible native transcript file. Its own identity must match uid.

    Returns:
      dict: uid, source (absolute transcript path), revision (content digest),
      and turns [{index, at, ended, text, replies}]. All mainline human messages
      and their assistant replies are retained with source timestamps. Scaffolding is excluded by
      gppu. Missing timestamps, another session's file and subagents are rejected.
    """
    from shared.sessions.processing import evidence
    self.session(uid)
    return evidence(uid, path)

  def session_inputs(self):
    """Read registered parent candidates for the SessionManager data_flow.

    Returns:
      dict: items contains {uid} once per registered session with file evidence.
      Known accessible copies come first, then unresolved copies; each group is
      newest first. Native canonical comparison and useful Alex text are
      checked before processing; stored message counts impose no size threshold.
      No session, Location, configuration or original file is changed.
    """
    from shared.sessions.processing import inputs
    return inputs(self)

  def register_session(self, uid: str, manifest: str) -> dict:
    """Register the complete staged session after collating its native copies.

    Args:
      uid (str): Native session ID shared by the collated transcripts.
      manifest (str): Completed stage_session manifest. Native copies must agree
        as complete-record prefixes before the Registry connection is opened.

    Returns:
      dict: uid, source, session_added, copy_added, subagent, parent_uid, began_at
      and ended_at describe the checked file. Exact repeats make no changes.
      New rows extend the same session. Earlier factual timestamps are untouched;
      aggregate end/message fields can grow with the native transcript. Conflicting
      copies fail before persistence. This adds no HTTP write route.
    """
    from shared.sessions.discovery import register
    return register(self, uid, manifest)

  def session_ids(self, uids: list[str]) -> list[str]:
    """Identify supplied native session identities without loading their details.

    Args:
      uids (list[str]): Candidate identities, such as incoming association subjects.
        Values are compared exactly with the stored session Registry UID.

    Returns:
      list[str]: Only registered native session identities, deduplicated in input
      order. Missing identities are omitted. Empty input returns an empty list
      without opening the index. Thread kinds are separate and are not inferred
      here. This bounded read creates no references and reads no transcript files.
    """
    if not isinstance(uids, list) or any(not isinstance(uid, str) for uid in uids):
      raise ValueError('uids must be a list of strings')
    unique = list(dict.fromkeys(uids))
    if not unique:
      return []
    with self.index() as db:
      found = {str(row[0]) for row in db.execute(
        'SELECT uid FROM lake.session WHERE uid = ANY(%s)', (unique,)).fetchall()}
    return [uid for uid in unique if uid in found]

  def session_originals(self, uids: list[str]) -> dict[str, str]:
    """Resolve supplied Registry IDs and explicit aliases to original session IDs.

    Known originals map to themselves, unknown IDs are omitted, and input order
    is retained. Empty input performs no database read. This bounded operation
    creates no references, proposals or aliases and exposes no new route.
    session_ids continues to test exact registered native IDs independently.
    """
    from shared.sessions.identity import originals
    return originals(self, uids)

  def session_copies(self, uid: str) -> list[dict]:
    """Read one Registry session's original copy references and local source paths.

    Args:
      uid (str): Exact native session ID; an unregistered ID returns no stored copies.

    Returns:
      list[dict]: entity, address, producer and paths for every recorded copy.
        Paths use native absolute addresses or indexed entity parents beneath a
        recorded Location copy on this host. Archive members remain references;
        this method neither extracts archives nor changes configuration or files.
        Indexed Lake collections add preserved transcript paths without removing
        any of the original Registry references.
    """
    from shared.sessions.canonical import copies
    rows = copies(self, uid)
    preserved = set()
    for collection in self.session_collections(uid):
      for row in collection['files']:
        if row['kind'] == 'transcript' and row['published'] not in preserved:
          rows.append({'entity': '', 'address': row['published'], 'producer': 'agent/session-manager',
                       'paths': [row['published']]})
          preserved.add(row['published'])
    return rows

  def session_canonical(self, uid: str) -> dict:
    """Compare a registered session's accessible native transcript copies.

    Args:
      uid (str): Exact native session identity.

    Returns:
      dict: status, source, copies and children record full JSON-object prefix
        comparisons, including all original payloads and embedded assets. Native
        child identities are separate from the parent's human work. Divergence,
        malformed input and unexpected identities prevent a selected source.
        discovered includes exact-ID current Claude transcripts omitted by old
        indexes; registered/unavailable retain missing copy evidence. A ready result covers
        accessible native copies only; external assets and archive recovery remain
        separate from this read. No source, Registry row or proposal is changed.
    """
    from shared.sessions.canonical import canonical
    return canonical(self, uid)

  def session_assets(self, uid: str, sources: list[str] | tuple = ()) -> dict:
    """Read files associated with one native session before persistence.

    Args:
      uid (str): Exact native session ID, whether or not already registered.
      sources (list[str]): Native file paths supplied by runtime capture or backfill.

    Returns:
      dict: files retain every available transcript and discovered Claude
      session-ID folder file, including file-history versions, todos and child
      transcripts. references preserve native snapshot backup metadata; missing,
      unavailable and invalid retain unresolved evidence. pending_harnesses names
      formats whose external-file discovery is not yet implemented. No work-tree
      file is read merely because a transcript mentions it. Nothing is copied,
      deleted, indexed or queued by this read, and no HTTP route is added.
    """
    from shared.sessions.assets import associated
    return associated(self, uid, sources)

  def stage_session(self, uid: str, directory: str, sources: list[str] | tuple = ()) -> dict:
    """Stage available session files for a producer without altering any source.

    Args:
      uid (str): Exact native session ID, whether or not already registered.
      directory (str): Absolute local staging directory owned by the producer.
      sources (list[str]): Native paths to collate with discovered and stored copies.

    Returns:
      dict: manifest path, original/staged file pairs, canonical comparison of
      staged transcripts, original backup references and unresolved observations.
      Each file is compared directly with its source before the manifest is
      published. Errors leave the partial staging folder without a manifest;
      no source is deleted or rewritten. Staging is not Lake publication or
      queue approval. This Python producer method adds no Admin mutation route.
    """
    from shared.sessions.collection import stage
    return stage(self, uid, directory, sources)

  def session_collections(self, uid: str) -> list[dict]:
    """Read indexed Lake collections for one exact native session identity.

    Returns:
      list[dict]: Original manifests, published file paths and selected canonical
      paths. Every original field and unresolved observation remains available.
      These producer records use the existing file index; no source file or
      Registry row is changed and no Admin route is added.
    """
    from shared.sessions.publication import collections
    return collections(self, uid)

  def publish_session(self, uid: str, manifest: str, lake_root: str) -> dict:
    """Preserve a staged session collection in Lake and index it through this API.

    Args:
      uid (str): Exact registered session identity.
      manifest (str): Absolute completed stage_session manifest path.
      lake_root (str): Existing absolute Lake root supplied by the producer.

    Returns:
      dict: Published files and manifest, canonical path and indexed record
      identities. Equal and prefix transcript copies share one canonical file
      under sources/YYYY/sessions/MM/DD/uid; appended native records extend it.
      Every staged byte is checked against its original before
      publication. A per-session producer lock serializes publication and index
      writes. Exact retries reuse files and records; conflicts remain untouched.
      An index failure retains preserved files for an exact retry. Staging and
      original copies remain. This operation owns its producer transaction and
      adds no HTTP route, configuration entry or schema.
    """
    from shared.sessions.publication import publish
    return publish(self, uid, manifest, lake_root)

  def clear_session_stage(self, uid: str, manifest: str) -> dict:
    """Clear one fully preserved and indexed staging collection through its owner.

    Args:
      uid (str): Exact registered session identity.
      manifest (str): Exact preserved Lake manifest path, retained on retry.

    Returns:
      dict: uid, staging directory, preserved Lake manifest and cleared=true.
      Every remaining staged file must equal its indexed Lake copy or be a complete
      record prefix of the preserved transcript. Extra files,
      missing index records and conflicting bytes stop cleanup before deletion.
      Only explicitly listed staging files and their empty directories are
      removed. Originals and Lake files remain. Interrupted cleanup can retry
      using the indexed manifest. No Admin HTTP route or configuration is added.
    """
    from shared.sessions.publication import clear_stage
    return clear_stage(self, uid, manifest)

  def publish_session_summary(self, uid: str, manifest: str, text_root: str, qualification: dict | None = None) -> dict:
    """Publish the latest lightweight text from a preserved Lake session collection.

    Args:
      uid (str): Exact registered parent session identity.
      manifest (str): Absolute indexed Lake collection manifest.
      text_root (str): Existing absolute text root supplied by the producer.
      qualification (dict | None): Explicit unapproved classifier exclusion of
        the exact remaining source range: revision, first, last, useful=false,
        reason and model. Omit when every source turn has a saved work span.

    Returns:
      dict: Session uid, summary path and record identity, raw canonical path,
      manifest and evidence revision. The complete raw collection must already
      exist and be indexed. Saved naming/span proposals supply the summary;
      original generation and review fields remain separate from the document's
      unapproved provenance. YYYY/sessions/MM/DD uses the native session start.
      Exact retries reuse the document and record. Only unchanged, unreviewed
      producer output may be refreshed. This owns its producer transaction and
      adds no Admin route, configuration or schema.
    """
    from shared.sessions.summary import publish
    return publish(self, uid, manifest, text_root, qualification)

  def propose_session_deletions(self, uid: str, manifest: str) -> dict:
    """Mark preserved original copies for deletion review in the existing index.

    Args:
      uid (str): Exact registered session identity.
      manifest (str): Exact indexed and preserved Lake collection manifest.

    Returns:
      dict: Session uid, manifest and copies containing record/proposal/existing.
      Each workflow.session_copy_deletion entry records the original observation,
      its exact preserved copy, generated provenance and verified=null. All Lake
      files must exist in the index and source bytes must still match. Existing
      native observation identities, unknown fields, earlier proposals and review events are
      retained; exact retries return the existing proposal even after review.
      No source or Lake file is removed. Registry rows and Admin mutation routes
      remain unchanged. This operation owns its producer transaction.
    """
    from shared.sessions.copy_cleanup import propose
    return visible(propose(self, uid, manifest))

  def session_proposals(self, uid, revision, who='agent/session-manager'):
    """Find a completed proposal batch for one exact session evidence revision.

    Args:
      uid (str): Registry session identity.
      revision (str): Revision returned by session_evidence.
      who (str): Producer identity that submitted the proposal batch.

    Returns:
      dict | None: session, title annotation identity, span identities and
      existing=true, or null when this revision has not been processed.
    """
    from shared.sessions.processing import existing
    return existing(self, uid, revision, who)

  def session_progress(self, evidence, who='agent/session-manager'):
    """Read saved work ranges that cover a prefix of this session's Alex turns.

    Args:
      evidence (dict): Complete session_evidence result from the native log.
      who (str): The producer whose saved proposals are being inspected.

    Returns:
      dict: first is the next unclassified source-turn index; spans and work
      retain the existing span IDs, names and factual times. Title identifies
      their session-name annotation. Earlier source text and start times must
      still agree. Later replies can extend the transcript without rewriting
      earlier spans. This read adds no references, records or HTTP route.
    """
    from shared.sessions.processing import progress
    return progress(self, evidence, who)

  def propose_session(self, evidence, title, spans, model, who):
    """Save session naming and work-span proposals from a process, atomically.

    Args:
      evidence (dict): Complete result of session_evidence, with original turns.
      title (str): Proposed session name, distinct from its existing title.
      spans (list[dict]): Ordered work ranges with first/last source-turn indexes,
        title, task/project Thread IDs (blank when unmatched), an exact quote and
        outcome (blank, finished or abandoned).
      model (str): Model used to generate these proposals.
      who (str): Actual non-human producer identity.

    Returns:
      dict: session, title (annotation identity), spans (saved span identities),
      and existing (true for an identical source revision already processed).
      Existing rulings and proposals are preserved. Bounds come from source
      timestamps; every human turn must belong to exactly one range. Saves are
      readable through session, spans and about_span. No configuration is changed.
    """
    from shared.sessions.processing import save
    return save(self, evidence, title, spans, model, who)

  def correct_session_span(self, session, span, expected, fields, why):
    """Correct an unreviewed SessionManager span description through its producer.

    Python producer operation only; no Admin mutation route. expected is the
    exact title/during/metadata/generated/verified snapshot, with during as text.
    fields accepts title, project and outcome. Original timestamps, session
    membership, other annotations and PM-owned incoming links cannot change.
    A machine review event records why; it supplies no human approval or ruling.
    """
    from shared.sessions.correction import correct
    return correct(self, session, span, expected, fields, why)

  def restore_session_source_times(self, uid, path, expected):
    """Repair misread import or Copilot bounds using preserved native events.

    Python producer operation only. expected maps inspected span IDs to exact
    title/during/metadata/generated/verified snapshots. Native turn identities
    and saved source indexes supply every bound; no date is accepted as input.
    Missing original completions remain unknown. This changes only the owning
    producer's misread bounds, retaining names, text, links and raw provenance.
    A changed span or source fails atomically; exact same-source retries do not
    write. No Admin route, schema, revision history or configuration is added.
    """
    from shared.sessions.source_repair import restore
    return restore(self, uid, path, expected)

  def file_indexer_stats(self):
    """FileIndexer's figures over the whole index, the line above its tree.

    Returns:
      dict: folders, files and bytes observed, notes, first_modified and last_modified of the files, last_seen, and the counts of configured locations, sessions and runs.

    Example:
      {}
    """
    from FileIndexer.shared_index import FileIndexerDatabase
    with FileIndexerDatabase() as index:
      return index.stats()

  def file_indexer_children(self, location='', folder=''):
    """What FileIndexer's tree shows directly under the root, a Location or a folder.

    Args:
      location (str): Configured Location UID; blank with folder blank lists the root Locations.
      folder (str): Indexed folder UID; when given, location is ignored.

    Returns:
      list[dict]: Entries typed location, folder or file. A location carries its configured row, summary (file_count, total_size, is_indexed, is_processing) and root_folder; a folder its indexed row, counts, span and processing; a file its name, extension, size, modified_at and span. Under a Location, its child Locations come first, then the contents of its root folder unless that folder is a boundary.

    Example:
      {}
    """
    from FileIndexer.shared_index import FileIndexerDatabase
    with FileIndexerDatabase() as index:
      return index.children(location, folder)

  def file_indexer_location(self, uid):
    """One Location as FileIndexer's tree row and details panel show it.

    Args:
      uid (str): Configured Location UID.

    Returns:
      dict: The Location's row as in file_indexer_children, plus details: span, folder_count, file_count, total_size, session_count and recognized_sets over it and the Locations below it.

    Example:
      {"uid": "alex-pc-data"}
    """
    from FileIndexer.shared_index import FileIndexerDatabase
    with FileIndexerDatabase() as index:
      return index.location_entry(uid)

  def file_indexer_folder(self, uid):
    """One indexed folder as FileIndexer's tree row shows it.

    Args:
      uid (str): Indexed folder UID.

    Returns:
      dict: The folder's row as in file_indexer_children.

    Example:
      {"uid": "file://alex-pc/D:/.claude"}
    """
    from FileIndexer.shared_index import FileIndexerDatabase
    with FileIndexerDatabase() as index:
      return index.folder_entry(uid)

  def readers(self):
    routes = {'/config': self.configuration, '/config/{table}': self.configuration,
              '/file_indexer/stats': self.file_indexer_stats, '/file_indexer/children': self.file_indexer_children,
              '/file_indexer/location': self.file_indexer_location, '/file_indexer/folder': self.file_indexer_folder,
              '/config/{table}/{uid}': self.configuration,
              '/lake': self.topology, '/data_flows': dagster_configuration.flows,
              '/locations': self.locations, '/location_navigation': self.location_navigation,
              '/location_lineage': self.location_lineage,
              '/physical_children': self.physical_children,
              '/config/location': self.config_locations,
              '/config/process': dagster_configuration.processes, '/config/resource': dagster_configuration.resources,
              '/config/file': file_configuration.read,
              '/config/provider': self.config_providers, '/config/provider/schemas': self.config_provider_schemas,
              '/config/connection': self.config_connections,
              '/configuration': configuration.config, '/configuration_definitions': configuration.configuration_definitions,
              '/hosts': configuration.hosts, '/platforms': configuration.platforms,
              '/connections': configuration.connections, '/resources': configuration.resources,
              '/graph/model': self.model, '/sources/resolve': self.resolve, '/sources/record': self.source, '/sources/query': self.query,
              '/graph/node_roots': self.node_roots, '/graph/neighbors': self.neighbors,
              '/systems/temporal': graph_temporal.systems, '/spans/temporal': graph_temporal.spans,
              '/spans/temporal_links': graph_temporal.span_links,
              '/graph/topology': self.topology, '/graph/nodes': self.nodes,
              '/graph/node': self.node, '/records': self.records,
              '/records/record': self.record, '/spans/facts': self.fact_spans, '/spans/fact': self.fact_span,
              '/projects/threads': self.threads, '/spans': self.spans,
              '/spans/chains': self.chains, '/annotations': self.annotations,
              '/sessions/recent': self.recent_sessions, '/sessions/timeline': self.timeline_sessions,
              '/sessions/session': self.session, '/registry': self.registry, '/projects/thread_text': self.thread_text,
              '/sessions/about': self.about_session, '/spans/span': self.about_span, '/sessions/coverage': self.coverage,
              '/sessions/accounting': self.accounting, '/systems/processes': self.processes,
              '/admin_ui/overview': self.overview, '/projects': self.projects, '/projects/timeline': self.timeline,
              '/projects/timeline_of': self.timeline_of, '/records/browse': self.browse, '/graph': self.graph}
    routes.update({'/systems': self.sources.systems_overview, '/systems/standing': self.sources.systems_standing,
                   '/systems/operations': operations.graph, '/systems/observations': operations.observations,
                   '/systems/sources': self.sources.systems_sources,
                   '/systems/marks': self.sources.systems_marks,
                   '/systems/node': self.sources.systems_node,
                   '/systems/schematic': self.sources.systems_schematic,
                   '/systems/map': self.sources.systems_map, '/systems/roadmap': self.sources.systems_roadmap,
                   '/vocabulary/themes': self.vocabulary.themes, '/vocabulary/axes': self.vocabulary.axes, '/vocabulary/tags': self.vocabulary.tags,
                   '/vocabulary/proposals': self.vocabulary.proposals, '/vocabulary': self.vocabulary.standing})
    routes['/sources/deprecated'] = self.deprecated
    return routes

  def writers(self):
    """Admin HTTP mutation routes remain disabled."""
    return {}


  def index(self):
    """Open the index and its AGE-backed Thread and annotation projections."""
    db = GraphConnection.connect(configuration.postgres(), options='-c default_transaction_read_only=on')
    age.initialize(db)
    return db

  @property
  def INDEX(self):
    return 'admin_ui.index'

  def opened(self, database):
    return references.opened_source(database)

  def invalidate(self):
    self._inventory = None
    self._holdings = None

  def model(self):
    """Read the configured graph vocabulary and allowed relationship, Thread and ruling values.

    Returns:
      dict: The configured model fields, including thread_kinds, thread_statuses, links and rulings, plus terms, relationships and labels. Each term has term, qualifies, iri, reads, from_label and to_label; relationships contains the terms qualifying graph edge labels; labels lists vertex labels.

    Example:
      {}
    """
    with opened() as db:
      terms = graph_read.vocabulary(db)
      labels = age.query(db, 'MATCH (n) RETURN DISTINCT label(n) ORDER BY label(n)')
      edge_labels = set(age.query(db, 'MATCH ()-[e]->() RETURN DISTINCT type(e)'))
    return configuration.row('admin_ui', 'model') | {
      'terms': terms, 'relationships': [t for t in terms if t['qualifies'] in edge_labels],
      'labels': [label for label in labels if label]}

  def nodes(self, label='', q=''):
    """Find graph nodes by label and text.

    Args:
      label (str): Exact graph label; blank includes all labels.
      q (str): Case-insensitive substring in slug, displayed term, name or title; blank includes all nodes.

    Returns:
      list[dict]: Graph node rows with id, slug, label, term, says, data and references [{sourceRelation, sourceKey}]. Protected values are masked and Connection data is empty.

    Example:
      {"label": "Thread"}
    """
    with opened() as db:
      return graph_read.search(db, label, q)

  def node_roots(self, q='', label='', limit=100, offset=0):
    """Page graph roots, or search nodes across the graph.

    Args:
      q (str): Case-insensitive substring in slug, displayed term, name or title. Nonblank text searches all nodes; blank text selects nodes without an outgoing isPartOf parent link.
      label (str): Exact graph label; blank includes all labels.
      limit (int): Maximum rows to return; must be positive.
      offset (int): Number of matching rows to skip; must be nonnegative.

    Returns:
      dict: nodes contains presented node rows with id, uid, name, shown, label, data, references and has_children. total is the matching node count; offset and limit echo pagination; next is the next offset or null.

    Example:
      {"label": "Thread", "limit": 25}
    """
    if limit < 1 or offset < 0:
      raise ValueError('limit must be positive and offset must be nonnegative')
    with opened() as db:
      rows, total = graph_read.roots(db, q, label, limit, offset)
    return node_page(rows, total, offset, limit)

  def neighbors(self, id, relation='IS_PART_OF', direction='in', term='', limit=100, offset=0):
    """Follow graph relationships from a known node.

    Args:
      id (str): Graph node ID from /graph/node_roots or /graph/nodes; use id, not a slug.
      relation (str): Exact edge type such as IS_PART_OF; blank accepts all edge types.
      direction (str): in follows incoming edges to their source; out follows outgoing edges to their target.
      term (str): Exact vocabulary term on the edge; blank accepts all terms.
      limit (int): Maximum rows to return; must be positive.
      offset (int): Number of matching rows to skip; must be nonnegative.

    Returns:
      dict: nodes, total, offset, limit and next describe the neighboring-node page. edges contains id, source, target, type, term and shown. relationships lists the available type/term/direction combinations and distinct neighbor counts.

    Example:
      {"id": "<node_id>", "direction": "in", "limit": 25}
    """
    if direction not in ('in', 'out'):
      raise ValueError('direction must be in or out')
    if limit < 1 or offset < 0:
      raise ValueError('limit must be positive and offset must be nonnegative')
    with opened() as db:
      rows, total, edges, options = graph_read.neighbors(db, id, relation, direction, term, limit, offset)
    return node_page(rows, total, offset, limit) | {'edges': edges, 'relationships': options}

  def node(self, uid):
    """Read a graph node, its relationships, annotations and original source records.

    Args:
      uid (str): Graph node ID from /graph/nodes; the HTTP query alias id takes precedence if both are supplied.

    Returns:
      dict: The graph node with properties, relations (edges with source and target IDs), annotations, references and sources (hydrated native references). Protected values are masked; Connection properties and data are empty.

    Example:
      {"uid": "<node_id>"}
    """
    with opened() as db:
      node = age.node(db, uid)
      row = graph_read.node_rows(db, [node])[0]
      row['properties'] = node['properties']
      row['relations'] = graph_read.edge_rows(db, age.edges(db, 'id(a) = $id OR id(b) = $id', {'id': int(uid)}))
      row['annotations'] = visible(row['properties'].get('annotations', []))
      if row['label'] == 'Connection':
        row['properties'] = {}
        row['data'] = {}
    row['sources'] = [references.fetch(ref['sourceRelation'], ref['sourceKey']) for ref in row['references']]
    return visible(row)

  def topology(self):
    """Read the stored topology, including configured and discovered nodes.

    Returns:
      dict: nodes contains Location, Host, Container, Connection, Provider and Tenant rows with id, uid, label, term, shown, name, service, location_uid, configured, data, references and approval fields verified, ruling, ruled_at, ruled_by and why. configured means the node has a native catalog definition or a stored configuration property; it is independent of approval. IDs are decimal strings. data retains the supported configuration or discovered properties, with credentials masked. edges contains stored links whose endpoints are both in nodes: id, source, target, type, term and shown. The full hierarchy is returned without enumerating sources or running handlers; clients choose a starting view and collapsed state.

    Example:
      {}
    """
    with opened() as db:
      rows = presented(graph_read.node_rows(db, age.nodes(db, 'label(n) IN $labels', {'labels': list(TOPOLOGY_LABELS)})))
      nodes = rows
      edges = graph_read.edge_rows(db, age.edges(db, 'label(a) IN $labels AND label(b) IN $labels', {'labels': list(TOPOLOGY_LABELS)}))
    return {'nodes': nodes, 'edges': edges}

  def configuration(self, table='', uid=''):
    """Read topology configuration from the same graph as the Lake.

    Args:
      table (str): Configuration section name; blank lists the exposed sections. locations returns flat Location rows; other sections return maps keyed by configured identity.
      uid (str): Optional identity within the selected section. URL-encode the identity, including any slashes.

    Returns:
      list[dict] | list[str] | dict: Without table, section names. locations returns rows containing the editable body fields plus id, uid, provider, provider_id, parent, canonical and generated; id and provider_id are decimal graph IDs, and parent is a Location UID or null. A selected Location returns one row. Other sections return their authored field maps, or the selected row. Connection secrets are masked. This release has no write routes; later writes must use these same identities and preserve fields they do not edit.

    Example:
      {"table": "locations"}
    """
    if table == 'locations':
      rows = [row['body'] | {key: value for key, value in row.items() if key != 'body'}
              for row in catalog_configuration.document()['locations']]
      if uid:
        return {row['uid']: row for row in rows}[uid]
      return rows
    sections = configuration.config()
    if not table:
      if uid:
        raise ValueError('select a configuration section before its identity')
      return sorted(sections)
    rows = sections[table]
    return rows[uid] if uid else rows

  def locations(self, q='', view='all'):
    """Read configured Location navigation rows from AGE.

    Args:
      q (str): Case-insensitive substring in UID, name, URI or host access path.
      view (str): Existing navigation selection: all or configured. Both currently return configured Location roots; /lake includes discovered topology.

    Returns:
      list[dict]: Rows with id, uid, name, canonical, body, parent, access (host to path), physical (host/path/access entries), under (parent UIDs), ordinal, label, shown, tags and folders. Runtime index totals remain null until read through the index APIs.

    Example:
      {"view": "configured"}
    """
    return shared_locations.locations(q, view)

  def location_lineage(self, host=None):
    """Read configured Location and Process references displayed by Inventory.

    Args:
      host (str | None): Host for resolving configured access paths; omitted uses the configured runtime host.

    Returns:
      dict: host names the resolution scope. providers contains catalog definitions with asset key and dependencies; locations contains UID, canonical URI, local path, asset key and dependencies; processes contains id, reads, writes, origin, inside, runs_on, asset, key and dependencies. plaud retains its declared source URI, destination identity, resource URI/root and relative naming rules. A missing or mismatched Location remains unresolved; the response does not infer actual run destinations or start a run.

    Example:
      {"host": "trix"}
    """
    from gppu import glob_dict
    with CONFIG_LOCK:
      result = shared_locations.asset_lineage(host)
      plaud, textlake = glob_dict('plaud'), glob_dict('textlake')
      # Plaud's resource still declares the share root; do not equate it with the
      # current Location merely because the legacy configuration also calls it lake.
      result['plaud'] = {
        'source_location_uid': None, 'source_uri': plaud['api_base'],
        'destination_location_uid': plaud['lake']['location']['id'],
        'configured_uri_prefix': plaud['lake']['location']['uri_prefix'],
        'resource_uri': textlake['uri'], 'resource_root': textlake['root'],
        'relative_rules': {key: value for key, value in textlake['rules'].items() if key.startswith('recording_')}}
      return result

  def records(self, q='', location='', term='', parent='', limit=100, offset=0):
    """Search indexed records with pagination.

    Args:
      q (str): Case-insensitive substring in record name, path or URI; blank disables text filtering.
      location (str): Exact recorded Location value; blank includes all Locations.
      term (str): Exact record term; blank includes all terms.
      parent (str): Exact parent record UID; blank does not restrict parentage.
      limit (int): Maximum rows to return; must be positive.
      offset (int): Number of matching rows to skip; must be nonnegative.

    Returns:
      dict: items contains fact.record rows with shown (vocabulary caption), ruling (latest ruling state) and references [{sourceRelation, sourceKey}]. limit and offset echo the request; has_more indicates another page. Protected values are masked.

    Example:
      {"q": "session", "limit": 25}
    """
    clauses, values = [], []
    for name, value in (('location',location),('term',term),('parent_uid',parent)):
      if value:
        clauses.append(f'r.{name} = %s')
        values.append(value)
    if q:
      clauses.append("concat_ws(' ',r.name,r.path,r.uri) ILIKE %s")
      values.append('%' + q + '%')
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    with opened() as db:
      result = page(db, "SELECT r.* FROM fact.record r"
                  + where + ' ORDER BY r.uid', values, limit, offset)
      attach_references(db, 'record', result['items'])
      meanings = {row['term']: row['reads'] for row in graph_read.vocabulary(db)}
      for row in result['items']:
        row.update(decision_fields(row['verified']))
        row['shown'] = meanings.get(row['term'], 'Record')
      return visible(result)

  def observe_folder(self, path, who):
    """Measure one existing directory into Inventory through the producer API.

    path is an absolute directory on this host; who names its machine producer.
    The configured Location supplies its canonical URI; native stat measures it.
    Existing URI identities and other payload/provenance are retained. No child
    scan, Location configuration, Task link or Admin mutation route is created.
    Returns uid, uri, term, path and the measured observation for linking.
    """
    from shared.inventory.folders import observe
    return observe(self, path, who)

  def record(self, uid):
    """Read one indexed record with its spans and native source records.

    Args:
      uid (str): Record UID from GET /records.

    Returns:
      dict: The fact.record row, plus shown, ruling, spans (fact.every_span rows ordered by time and text position), references and sources (hydrated native records). Protected values are masked.

    Example:
      {"uid": "<record_uid>"}
    """
    with opened() as db:
      result = one(db, "SELECT r.* FROM fact.record r WHERE uid = %s", (uid,))
      result.update(decision_fields(result['verified']))
      result['spans'] = db.execute('SELECT * FROM fact.every_span WHERE record = %s ORDER BY began,starts', (uid,)).fetchall()
      attach_references(db, 'record', [result])
      meanings = {row['term']: row['reads'] for row in graph_read.vocabulary(db)}
      result['shown'] = meanings.get(result['term'], 'Record')
    result['sources'] = [references.fetch(ref['sourceRelation'], ref['sourceKey']) for ref in result['references']]
    return visible(result)

  def fact_spans(self, q='', limit=100, offset=0):
    """Search indexed time and text spans.

    Args:
      q (str): Case-insensitive substring in span title or meaning; blank includes all spans.
      limit (int): Maximum rows to return; must be positive.
      offset (int): Number of matching rows to skip; must be nonnegative.

    Returns:
      dict: items contains fact.every_span rows. Each row retains the view fields, including uid, title and coordinates. limit and offset echo the request; has_more indicates another page. Protected values are masked.

    Example:
      {"q": "API", "limit": 25}
    """
    with opened() as db:
      return visible(page(db, "SELECT * FROM fact.every_span WHERE (%s = '' OR concat_ws(' ',title,meaning) ILIKE %s)"
                  ' ORDER BY uid', (q, '%' + q + '%'), limit, offset))

  def fact_span(self, uid):
    """Read one indexed span using its native UID.

    Args:
      uid (str): Span UID from GET /spans/facts.

    Returns:
      dict: The matching fact.every_span row, including its UID, title, meaning, owning record and available time/text coordinates. Protected values are masked; a missing UID returns HTTP 404.

    Example:
      {"uid": "<span_uid>"}
    """
    with opened() as db:
      return visible(one(db, 'SELECT * FROM fact.every_span WHERE uid = %s', (uid,)))

  def config_locations(self) -> list[dict[str, object]]:
    """Configured Locations as a flat tree; parent names another Location UID.

    Returns:
      list[dict]: Each row contains id (decimal graph ID as a string), uid, provider, provider_id, parent (Location UID or null), canonical (URI), body (editable name, path, service, kind, icon, tags and folders), and generated (author and timestamp). Use id and body as id and expected when saving an existing Location.

    Example:
      {}
    """
    return catalog_configuration.document()['locations']

  def config_providers(self) -> list[dict[str, object]]:
    """Read-only Provider and Connection choices for configuring a Location.

    Returns:
      list[dict]: Each row contains id, uid, parent (Provider graph ID or null), connection, scheme and authority. Graph IDs are decimal strings. The selected id becomes provider_id when saving a Location.

    Example:
      {}
    """
    return catalog_configuration.document()['providers']

  def config_provider_schemas(self) -> list[dict[str, str]]:
    """URI schemes supported by the Provider implementations loaded in gppu.

    Returns the catalog's runtime schemes and implementation names. Saved
    Provider/Connection pairings remain available through config/provider.

    Returns:
      list[dict]: Runtime catalog entries with scheme and implementation names. These describe supported implementations; GET /config/provider supplies saved Provider identities for Location edits.

    Example:
      {}
    """
    return catalog_configuration.catalog().schemas

  def config_connections(self) -> list[dict[str, str | None]]:
    """Connection names for selectors; credentials are not part of this response.

    Returns:
      list[dict]: Each row contains uid (Connection selector value) and name (configured display name or null).

    Example:
      {}
    """
    with CONFIG_LOCK:
      configuration.environment()
      return [{'uid': uid, 'name': row.get('name')} for uid, row in configuration.tables()['connections'].items()]

  def mutate(self, what, uid, apply):
    with opened() as db:
      if what == 'node':
        age.lock(db, uid)
        body = age.node(db, uid)['properties']
        result = apply(body, body)
        age.replace(db, uid, body)
      elif what in ('record', 'span'):
        table = sql.Identifier('fact', what)
        row = one(db, sql.SQL('SELECT metadata,verified FROM {} WHERE uid = %s FOR UPDATE').format(table), (uid,))
        result = apply(row['metadata'], row)
        db.execute(sql.SQL('UPDATE {} SET metadata = %s, verified = %s WHERE uid = %s').format(table),
                   (Jsonb(row['metadata']), Jsonb(row['verified']) if row['verified'] is not None else None, uid))
      else:
        raise ValueError('what must be node, record or span')
    self.invalidate()
    return {'what': what, 'uid': uid, **result}

  def owner(self, subject, who=HUMAN):
    """Resolve an existing subject without guessing whether its name denotes a graph or fact row."""
    with opened() as db:
      nodes = [row for row in graph_read.search(db, q=subject) if row['slug'] == subject]
      records = db.execute('SELECT uid FROM fact.record WHERE uid = %s OR uri = %s', (subject, subject)).fetchall()
      spans = db.execute('SELECT uid FROM fact.span WHERE uid = %s', (subject,)).fetchall()
    found = [('node', n['id']) for n in nodes] + [('record', r['uid']) for r in records] + [('span', s['uid']) for s in spans]
    if not found:
      # An annotation may precede indexing. Its original subject remains the source identity.
      with opened() as db:
        body = {'slug': subject, 'generated': signed(who)}
        uid = age.create(db, '', body)
      return 'node', uid
    if len(found) != 1:
      raise ValueError('the subject must identify one existing object; use what and uid for an ambiguous subject')
    return found[0]

  def reference(self, source, key, create=False):
    if not source or not isinstance(key, dict) or not key:
      raise ValueError('a reference requires its source and native key object')
    if create:
      references.source_node(source, key)
    with opened() as db:
      rows = age.nodes(db, 'label(n) = "" AND n.sourceRelation = $source AND n.sourceKey = $key', {'source': source, 'key': key})
      if len(rows) > 1:
        raise ValueError('the source reference has more than one graph mapping')
      if rows:
        return rows[0]
      raise KeyError('the source reference has not been mapped')

  def resolve(self, source, key):
    """Find indexed owners and registered read queries for an exact native source reference.

    Args:
      source (str): Exact sourceRelation URI from a returned references entry; this names a registered source relation.
      key (dict | str): Native sourceKey object from the same reference. In an HTTP query, encode it as a JSON string; preserve native key names and value types.

    Returns:
      dict: sourceRelation and sourceKey echo the reference. owners contains {kind, uid} entries for indexed graph/fact owners. queries contains {name, parameters} entries for enabled matching read queries. Empty lists mean no matching mapping or read query was registered.

    Example:
      {"source": "pg://pg.karel.in/everything/systems/nodes", "key": {"node_id": 1}}
    """
    if isinstance(key, str):
      key = json.loads(key)
    return references.resolve(source, key)

  def source(self, source, key):
    """Read a native source record and its graph curation.

    Args:
      source (str): Exact sourceRelation URI from a returned references entry; this names a registered source relation.
      key (dict | str): Native sourceKey object from the same reference. In an HTTP query, encode it as a JSON string; preserve native key names and value types.

    Returns:
      dict: sourceRelation, sourceKey and owners identify the reference. Each queries entry contains name, parameters and rows from that registered query. annotations and verified aggregate curation from indexed owners. Protected values are masked.

    Example:
      {"source": "pg://pg.karel.in/everything/systems/nodes", "key": {"node_id": 1}}
    """
    if isinstance(key, str):
      key = json.loads(key)
    result = references.fetch(source, key)
    result.update(annotations=[], verified=[])
    with opened() as db:
      for owner in result['owners']:
        if owner['kind'] == 'node':
          body = age.node(db, owner['uid'])['properties']
          result['annotations'].extend(body.get('annotations', []))
          owner.update(provenance_fields(body.get('generated'), body.get('verified')))
        else:
          row = one(db, sql.SQL('SELECT metadata,verified FROM fact.{} WHERE uid=%s')
            .format(sql.Identifier(owner['kind'])), (owner['uid'],))
          result['annotations'].extend(row['metadata'].get('annotations', []))
          owner.update(provenance_fields(row['metadata'].get('generated'), row['verified']))
        result['verified'].extend(verification_events(owner['verified']))
    if len(result['owners']) == 1:
      owner = result['owners'][0]
      result.update(provenance_fields(owner['generated'], owner['verified']))
    else:
      # Multiple owners retain their raw event shapes on each owner; this is an aggregate.
      result.update(provenance_fields(None, result['verified']))
    return visible(result)

  def source_owner(self, sourceRelation, sourceKey):
    if not sourceRelation or not isinstance(sourceKey, dict) or not sourceKey:
      raise ValueError('a reference requires its source and native key object')
    owners = references.resolve(sourceRelation, sourceKey)['owners']
    if len(owners) > 1:
      raise ValueError('the source reference maps to more than one indexed owner')
    if owners:
      return owners[0]['kind'], owners[0]['uid']
    return 'node', self.reference(sourceRelation, sourceKey, create=True)['id']

  def annotate_source(self, sourceRelation, sourceKey, predicate, obj='', value='', evidence='', who=HUMAN, objectSource=None):
    """Append an annotation to the owner of an exact native source reference.

    Args:
      sourceRelation (str): Exact sourceRelation URI from a native reference.
      sourceKey (dict): Nonempty sourceKey object with the native key names and types. The reference must resolve to at most one owner; an unmapped reference is materialized as a graph source node.
      predicate (str): Nonblank annotation predicate.
      obj (str): Related object identity. HTTP also accepts object; object takes precedence. Leave blank when using objectSource.
      value (str): Literal annotation value; blank is allowed when the annotation points to an object.
      evidence (str): Explanation or source evidence for the statement.
      who (str): Author identity. Browser HTTP writes supply this from the authenticated session; omit it from the JSON body. Direct Python calls must supply the actual author.
      objectSource (dict | None): Optional exact native object reference with sourceRelation and sourceKey. Cannot be combined with a nonblank obj/object.

    Returns:
      dict: what and uid identify the stored owner; annotation_uid is the new annotation identity; index is its zero-based position. annotation contains uid, subject, predicate, object, value, evidence, generated {by, at}, and verified (rulings or null). Source objects also carry objectSource and objectOwner.

    Example:
      {"sourceRelation": "pg://pg.karel.in/everything/systems/nodes", "sourceKey": {"node_id": 1}, "predicate": "tag", "value": "API"}
    """
    what, uid = self.source_owner(sourceRelation, sourceKey)
    return self.annotate(what, uid, predicate, obj, value, evidence, who,
                         subject=str(sourceKey['uid']) if set(sourceKey) == {'uid'} else '', objectSource=objectSource)

  def verify_source(self, sourceRelation, sourceKey, state='approved', why='', who=HUMAN):
    """Append a ruling to the owner of a native source reference.

    Args:
      sourceRelation (str): Exact sourceRelation URI from a native reference.
      sourceKey (dict): Nonempty sourceKey object with the native key names and types. The reference must resolve to at most one owner; an unmapped reference is materialized as a graph source node.
      state (str): Ruling declared in GET /graph/model under rulings, such as approved or rejected.
      why (str): Reason attached to the ruling.
      who (str): Author identity. Browser HTTP writes supply this from the authenticated session; omit it from the JSON body. Direct Python calls must supply the actual author.

    Returns:
      dict: what and uid identify the resolved stored owner; ruling contains by, at, state and why. For an annotation, thread or native span, the returned owner can differ from the input identity.

    Example:
      {"sourceRelation": "pg://pg.karel.in/everything/systems/nodes", "sourceKey": {"node_id": 1}, "state": "approved", "why": "Reviewed"}
    """
    what, uid = self.source_owner(sourceRelation, sourceKey)
    return self.verify(what, uid, state, why, who)

  def query(self, name, parameters):
    """Run a registered read query with its declared native arguments.

    Args:
      name (str): Enabled registered query name returned by /sources/resolve or /sources/record.
      parameters (dict | str): Argument object whose keys exactly match the registered query. Values must match its declared types. In an HTTP query, encode this object as JSON.

    Returns:
      list[dict]: Rows returned by the registered SQL query. Field names and value types depend on that query; an empty result is an empty list. AGE row queries retain native field names and exact string IDs, with properties returned as a JSON object so protected fields can be masked. No arbitrary SQL is accepted.

    Example:
      {"name": "<query_name>", "parameters": {"uid": "<native_uid>"}}
    """
    if isinstance(parameters, str):
      parameters = json.loads(parameters)
    return references.query(name, parameters)

  def location_navigation(self, q='', physical=True, logical=True):
    """Read the existing configured Location navigation tree.

    Args:
      q (str): Search text for Location names and addresses.
      physical (bool | str): Include host access paths; accepts true/1 or false/0 over HTTP.
      logical (bool | str): Include the configured Location hierarchy; accepts true/1 or false/0 over HTTP.

    Returns:
      dict: roots and children describe displayed navigation nodes with id, uid, name, shown and term. Lookup maps associate those navigation IDs with Location owners, host paths, scopes and identities. This does not enumerate files or run handlers.

    Example:
      {"physical": true, "logical": true}
    """
    return shared_locations.location_navigation(q, physical, logical)

  def physical_children(self, uid, host, path='', show_system=True, show_ignored=True):
    """Read indexed children under a Location on one host.

    Args:
      uid (str): Configured Location UID.
      host (str): Declared host holding this Location.
      path (str): Relative path below the configured root; empty selects the root.
      show_system (bool | str): Include indexed system entries; accepts true/1 or false/0 over HTTP.
      show_ignored (bool | str): Include indexed ignored entries; accepts true/1 or false/0 over HTTP.

    Returns:
      dict: uid, host, path and root identify the scope; origin is index. available and reason describe whether recorded enumeration exists; observed_at and enumeration identify its observation. entries contains indexed children with address, name, kind, physical_path, mappings, references, span, classification and association metadata. No filesystem traversal occurs.

    Example:
      {"uid": "alex-pc-data", "host": "alex-pc"}
    """
    result = shared_locations.physical_children(uid, host, path, show_system, show_ignored)
    result['entries'] = self.with_associations(result['entries'])
    return result

  def browse(self, address='', locations='', host='', show_system=True, show_ignored=True):
    """Browse indexed children or inventory entries in a configured Location scope.

    Args:
      address (str): Blank lists roots; loc:<location_id> lists a legacy indexed Location; otherwise use a record UID or indexed PostgreSQL catalog URI. With locations, this is the scoped path.
      locations (list[str] | str): Location scope accepted by scoped_inventory; blank uses record browsing. Pass a list of Location UIDs in Python or a JSON-encoded array in HTTP.
      host (str): Host used to resolve scoped Location access; blank uses the configured host.
      show_system (bool | str): Whether scoped browsing includes system entries. Python accepts bool; HTTP accepts true/1 and false/0.
      show_ignored (bool | str): Whether scoped browsing includes ignored entries. Python accepts bool; HTTP accepts true/1 and false/0.

    Returns:
      list[dict]: Browse entries with address, label, container, kind, handlers, span, references and association fields tied/proposed. Scoped entries retain their Location reader fields. container says whether children can be opened.

    Example:
      {}
    """
    if locations:
      return self.with_associations(shared_locations.scoped_inventory(locations, host, address, show_system, show_ignored))
    if not address:
      rows = super().browse('')
      for row in rows:
        row['references'] = [{'sourceRelation': 'pg://pg.karel.in/files/lake/location',
                              'sourceKey': {'id': int(row['address'][4:])}}]
      with opened() as db:
        roots = db.execute("SELECT uid,name,coalesce(lower(term),metadata->'postgres_catalog'->>'kind','') AS kind"
                           " FROM fact.record WHERE metadata ? 'postgres_catalog' AND parent_uid IS NULL"
                           ' ORDER BY name').fetchall()
      rows += [{'address': row['uid'], 'label': row['name'], 'container': True, 'kind': row['kind'],
                'handlers': '', 'span': [], 'tied': [], 'references': []} for row in roots]
    elif address.startswith('loc:'):
      with references.opened_source('admin_ui.index', row_factory=dict_row) as db:
        roots = db.execute('SELECT uid,name,kind FROM lake.entity WHERE location_id = %s AND parent_uid IS NULL'
                           ' ORDER BY kind,name', (int(address[4:]),)).fetchall()
      rows = [{'address': str(row['uid']), 'label': row['name'], 'kind': row['kind'],
               'handlers': '', 'span': [], 'container': False} for row in roots]
    else:
      with opened() as db:
        matched = db.execute("SELECT uid FROM fact.record WHERE uid = %s OR (uri = %s AND metadata ? 'postgres_catalog')",
                             (address, address)).fetchall()
        if len(matched) != 1:
          raise ValueError('the address must identify one indexed record')
        children = db.execute("SELECT uid,name,coalesce(lower(term),metadata->'postgres_catalog'->>'kind','') AS kind"
                              ' FROM fact.record WHERE parent_uid = %s AND specialization_of IS NULL'
                              ' ORDER BY term,name', (matched[0]['uid'],)).fetchall()
      rows = [{'address': row['uid'], 'label': row['name'], 'kind': row['kind'],
               'handlers': '', 'span': [], 'container': False} for row in children]
    indexed = [row for row in rows if not row['address'].startswith('loc:')]
    ids = [row['address'] for row in indexed]
    with opened() as db:
      children = {row['parent_uid'] for row in db.execute('SELECT DISTINCT parent_uid FROM fact.record'
                   ' WHERE parent_uid = ANY(%s) AND specialization_of IS NULL', (ids,))}
      pointers = [{'uid': row['address']} for row in indexed]
      attach_references(db, 'record', pointers)
      by_id = {row['uid']: row['references'] for row in pointers}
    for row in indexed:
      row['container'] = row['address'] in children
      row['references'] = by_id[row['address']]
    original = {ref['sourceKey']['uid']: row for row in indexed for ref in row['references']
                if ref['sourceRelation'] == 'pg://pg.karel.in/files/lake/entity'}
    if original:
      with references.opened_source('admin_ui.index', row_factory=dict_row) as db:
        measured = db.execute("SELECT i.entity_uid,min(lower(i.timespan)) AS began,max(upper(i.timespan)) AS ended,"
            " string_agg(DISTINCT h.handler, ', ') AS handlers FROM lake.instance i"
            " LEFT JOIN LATERAL jsonb_array_elements_text(coalesce(i.metadata->'handlers','[]'::jsonb)) h(handler) ON true"
            ' WHERE i.entity_uid = ANY(%s::uuid[]) GROUP BY i.entity_uid', (list(original),)).fetchall()
      for measurement in measured:
        row = original[str(measurement['entity_uid'])]
        row['handlers'] = measurement['handlers'] or ''
        row['span'] = [self.local(measurement[key])[:10] if measurement[key] else '' for key in ('began','ended')]
    return self.with_associations(rows)

  def say(self, subject, predicate, obj='', value='', evidence='', who=HUMAN):
    """Write a statement using a subject identity, resolving its stored owner.

    Args:
      subject (str): Nonblank subject: graph slug, record UID/URI or span UID. An unknown subject creates an unlabeled graph reference; ambiguous subjects must use what and uid in the owner variant.
      predicate (str): Nonblank annotation predicate.
      obj (str): Related object identity. HTTP also accepts object; object takes precedence. Leave blank when using objectSource.
      value (str): Literal annotation value; blank is allowed when the annotation points to an object.
      evidence (str): Explanation or source evidence for the statement.
      who (str): Author identity. Browser HTTP writes supply this from the authenticated session; omit it from the JSON body. Direct Python calls must supply the actual author.

    Returns:
      dict: uid is the created annotation identity; subject, predicate, object and value are the normalized statement. Declared link predicates require an object; other predicates require a value.

    Example:
      {"subject": "<subject_uid>", "predicate": "tag", "value": "API"}
    """
    subject, predicate, obj, value = subject.strip(), predicate.strip(), obj.strip(), value.strip()
    links = configuration.row('admin_ui', 'model')['links']
    if not subject or not predicate:
      raise ValueError('a statement needs a subject and a predicate')
    if predicate in links and not obj:
      raise ValueError(f'{predicate} points at another thing: give it the thing')
    if predicate not in links and not value:
      raise ValueError(f'{predicate} says something: give it a value')
    what, uid = self.owner(subject, who)
    made = self.annotate(what, uid, predicate, obj, value, evidence, who, subject=subject)
    return {'uid': made['annotation_uid'], 'subject': subject, 'predicate': predicate,
            'object': obj, 'value': value}

  def annotate(self, what, uid, predicate, obj='', value='', evidence='', who=HUMAN, subject='', objectSource=None):
    """Append an annotation to a graph node, record or span.

    Args:
      what (str): Stored owner kind: node, record or span.
      uid (str): Graph node ID or fact record/span UID for the selected owner kind.
      predicate (str): Nonblank annotation predicate.
      obj (str): Related object identity. HTTP also accepts object; object takes precedence. Leave blank when using objectSource.
      value (str): Literal annotation value; blank is allowed when the annotation points to an object.
      evidence (str): Explanation or source evidence for the statement.
      who (str): Author identity. Browser HTTP writes supply this from the authenticated session; omit it from the JSON body. Direct Python calls must supply the actual author.
      subject (str): Python-only subject spelling stored on the annotation; blank uses uid. In HTTP, a subject key selects the say variant instead.
      objectSource (dict | None): Optional exact native object reference with sourceRelation and sourceKey. Cannot be combined with a nonblank obj/object.

    Returns:
      dict: what and uid identify the stored owner; annotation_uid is the new annotation identity; index is its zero-based position. annotation contains uid, subject, predicate, object, value, evidence, generated {by, at}, and verified (rulings or null). Source objects also carry objectSource and objectOwner.

    Example:
      {"what": "record", "uid": "<record_uid>", "predicate": "tag", "value": "API"}
    """
    if not str(predicate).strip():
      raise ValueError('an annotation needs a predicate')
    annotation = {'subject': subject or uid, 'predicate': predicate, 'object': obj, 'value': value, 'evidence': evidence,
                  'generated': signed(who), 'verified': [signed(who) | {'state': 'approved'}] if human(who) else None}
    if objectSource is not None:
      if obj or not isinstance(objectSource, dict) or set(objectSource) != {'sourceRelation', 'sourceKey'}:
        raise ValueError('objectSource requires its sourceRelation and sourceKey, with object omitted')
      object_kind, object_uid = self.source_owner(**objectSource)
      native_key = objectSource['sourceKey']
      annotation.update(object=str(native_key['uid']) if set(native_key) == {'uid'} else object_uid,
                        objectOwner={'kind': object_kind, 'uid': object_uid}, objectSource=objectSource)
    def append(body, row):
      if 'annotations' not in body:
        body['annotations'] = []
      if not isinstance(body['annotations'], list):
        raise ValueError('existing annotations are not an ordered list')
      annotation['uid'] = f'{what}:{uid}/annotations/{len(body["annotations"])}'
      body['annotations'].append(annotation)
      return {'annotation': annotation, 'annotation_uid': annotation['uid'],
              'index': len(body['annotations']) - 1}
    return self.mutate(what, uid, append)

  def associate(self, subject, thread, evidence='', who=HUMAN):
    """Tie a subject to an existing Thread.

    Args:
      subject (str): Subject identity to associate, such as a session UID or record URI.
      thread (str): Existing Thread UID from /projects/threads.
      evidence (str): Explanation for the association.
      who (str): Author identity. Browser HTTP writes supply this from the authenticated session; omit it from the JSON body. Direct Python calls must supply the actual author.

    Returns:
      dict: uid is the new annotation identity; subject is the original subject; predicate is association; object is the Thread UID; value is blank.

    Example:
      {"subject": "<session_uid>", "thread": "<thread_uid>", "evidence": "This conversation implements the task."}
    """
    self.thread_node(thread)
    return self.say(subject, 'association', obj=thread, evidence=evidence, who=who)

  def thread_node(self, uid):
    with opened() as db:
      rows = age.nodes(db, 'label(n) = "Thread" AND n.slug = $uid', {'uid': uid})
      if not rows:
        raise KeyError('the requested Thread does not exist')
      return graph_read.node_rows(db, rows)[0]

  def create_thread(self, kind, title, status='', parent='', who=HUMAN):
    """Create a named Thread and optionally link it to a parent.

    Args:
      kind (str): Thread kind declared in GET /graph/model under thread_kinds.
      title (str): Nonblank human-readable title; surrounding whitespace is removed.
      status (str): Status from model.thread_statuses, or blank for no status.
      parent (str): Existing parent Thread UID; blank creates no up link.
      who (str): Author identity. Browser HTTP writes supply this from the authenticated session; omit it from the JSON body. Direct Python calls must supply the actual author.

    Returns:
      dict: uid is the new Thread UID; kind, title, status and parent contain the saved values. The graph node ID is separate from this UID.

    Example:
      {"kind": "Task", "title": "Document the API", "parent": "<thread_uid>"}
    """
    model = configuration.row('admin_ui', 'model')
    if kind not in model['thread_kinds'] or (status and status not in model['thread_statuses']):
      raise ValueError('the Thread kind or status is not declared in the model')
    if not title.strip():
      raise ValueError('a Thread needs a title')
    if parent:
      self.thread_node(parent)
    with opened() as db:
      # Preserve the existing API's database-generated internal Thread handle.
      uid = one(db, 'SELECT gen_random_uuid()::text AS uid')['uid']
      stamp = signed(who)
      body = {'slug': uid, 'term': kind, 'data': {'title': title.strip(), 'status': status,
              'openedAt': stamp['at'], 'changedAt': stamp['at']}, 'generated': stamp}
      if human(who):
        body['verified'] = [stamp | {'state': 'approved'}]
      if parent:
        body['annotations'] = [{'uid': f'thread:{uid}/annotations/0', 'subject': uid, 'predicate': 'up',
          'object': parent, 'value': '', 'evidence': '', 'generated': stamp, 'verified': body.get('verified')}]
      age.create(db, 'Thread', body)
    self.invalidate()
    return {'uid': uid, 'kind': kind, 'title': title.strip(), 'status': status, 'parent': parent}

  def save_thread(self, uid, fields, who=HUMAN):
    """Update a Thread title, kind or status while recording changed values.

    Args:
      uid (str): Existing Thread UID from /projects/threads.
      fields (dict): Fields to change: title, kind and/or status. Omitted fields keep their values. Title must remain nonblank; kind and nonblank status must be declared in /graph/model. Other keys are ignored by the current implementation.
      who (str): Author identity. Browser HTTP writes supply this from the authenticated session; omit it from the JSON body. Direct Python calls must supply the actual author.

    Returns:
      dict: what is node; uid is the Thread UID; kind, title and status are the resulting values. changed lists the field names whose values changed.

    Example:
      {"uid": "<thread_uid>", "fields": {"title": "Document the API"}}
    """
    model = configuration.row('admin_ui', 'model')
    if fields.get('kind') and fields['kind'] not in model['thread_kinds']:
      raise ValueError('the Thread kind is not declared in the model')
    if fields.get('status') and fields['status'] not in model['thread_statuses']:
      raise ValueError('the Thread status is not declared in the model')
    node = self.thread_node(uid)
    def save(body, row):
      data = body['data']
      old = {'kind': body['term'], 'title': data.get('title') or '', 'status': data.get('status') or ''}
      wanted = {key: str(fields[key] or '').strip() if key in fields else value for key, value in old.items()}
      if not wanted['title']:
        raise ValueError('a Thread needs a title')
      if wanted['kind'] not in model['thread_kinds']:
        raise ValueError('the Thread kind is not declared in the model')
      changed = [key for key in wanted if wanted[key] != old[key]]
      if changed:
        stamp = signed(who)
        body['term'], data['title'], data['status'] = wanted['kind'], wanted['title'], wanted['status']
        data['changedAt'], body['generated'] = stamp['at'], stamp
        if 'annotations' not in body:
          body['annotations'] = []
        for key in changed:
          body['annotations'].append({'uid': f'node:{node["id"]}/annotations/{len(body["annotations"])}',
            'subject': uid, 'predicate': 'category' if key == 'kind' else key, 'object': '',
            'value': wanted[key], 'evidence': f'was {old[key] or "blank"}', 'generated': stamp,
            'verified': [stamp | {'state': 'approved'}] if human(who) else None})
      return {**wanted, 'changed': changed}
    result = self.mutate('node', node['id'], save)
    return result | {'uid': uid}

  def thread_text(self, thread):
    """Read the latest authored text for one Thread.

    Args:
      thread (str): Thread UID from /projects/threads.

    Returns:
      dict: uid, kind and title identify the Thread. text is its latest stored Markdown or blank, by and at identify its author and time, and written indicates whether a text annotation exists.

    Example:
      {"thread": "<thread_uid>"}
    """
    node = self.thread_node(thread)
    with opened() as db:
      said = db.execute("SELECT value,generated FROM lake.annotation WHERE subject = %s AND predicate = 'text'"
                        " ORDER BY generated->>'at' DESC NULLS LAST LIMIT 1", (thread,)).fetchone()
    stamp = (said['generated'] or {}) if said else {}
    return {'uid': thread, 'kind': node['term'], 'title': node['data'].get('title') or '',
            'text': (said['value'] or '') if said else '', 'by': stamp.get('by') or '',
            'at': stamp.get('at') or '', 'written': said is not None}

  def save_thread_text(self, thread, text, who=HUMAN):
    """Save Thread Markdown, keep its previous revision and export the document.

    Args:
      thread (str): Existing Thread UID from /projects/threads.
      text (str): Complete replacement Markdown body; surrounding whitespace is removed.
      who (str): Author identity. Browser HTTP writes supply this from the authenticated session; omit it from the JSON body. Direct Python calls must supply the actual author.

    Returns:
      dict: uid, kind and title identify the Thread. text is its latest stored Markdown or blank, by and at identify its author and time, and written indicates whether a text annotation exists. The result also contains exported, a string with the export commit result. written is true after the save.

    Example:
      {"thread": "<thread_uid>", "text": "Method parameters and returns are documented."}
    """
    known = self.thread_text(thread)
    value, stamp = text.strip(), signed(who)
    with opened() as db:
      target = db.execute("SELECT uid,owner_kind,owner_uid,annotation_index FROM lake.annotation"
                          " WHERE subject = %s AND predicate = 'text'"
                          " ORDER BY generated->>'at' DESC NULLS LAST LIMIT 1", (thread,)).fetchone()
    if target:
      target = self.annotation_target(str(target['uid']))
      def save(body, row):
        annotation = body['annotations'][target['annotation_index']]
        previous = {key: val for key, val in annotation.items() if key != 'revisions'}
        if 'revisions' not in annotation:
          annotation['revisions'] = []
        annotation['revisions'].append(previous)
        annotation.update(value=value, generated=stamp,
                          verified=[stamp | {'state': 'approved'}] if human(who) else None)
        return {}
      self.mutate(target['owner_kind'], target['owner_uid'], save)
    else:
      node = self.thread_node(thread)
      self.annotate('node', node['id'], 'text', value=value, who=who, subject=thread)
    return known | {'text': value, 'written': True, 'by': who, 'at': stamp['at'],
                    'exported': self.export_thread(thread, known, value, who)}

  def export_thread(self, thread, known, body, who):
    where = THREAD_EXPORTS / f'{thread}.md'
    where.parent.mkdir(parents=True, exist_ok=True)
    now = signed(who)['at']
    where.write_text('\n'.join(['---', 'fileClass: Document', f'uid: {thread}',
      f"kind: {known['kind']}", f"title: {known['title']}", f'created: {now}', f'updated: {now}',
      f'generated: {{ by: {who}, at: {now} }}',
      'source: everything.meta.Thread on pg.karel.in; this file is its export', '---', '', body, '']), encoding='utf-8')
    return self.commit(where, f'graph: {known["kind"]} “{known["title"]}”')

  def adopt_thread_annotations(self, thread: str, expected: dict, annotations: list[dict]) -> dict:
    """Adopt bounded outgoing source annotations into one existing Thread payload.

    Args:
      thread: Exact existing Thread slug, selected by its domain owner.
      expected: Complete raw Thread properties from the reviewed before snapshot.
      annotations: Original uid, subject, predicate, object, value, evidence,
        generated and verified fields. No identity or provenance is regenerated.

    Returns:
      dict: uid is the Thread slug; owner_kind and owner_uid identify its graph
      node; adopted and existing list annotation UIDs in supplied order.

    Requires an Api.process transaction at READ COMMITTED. Annotation identity
    locks precede the node lock and are shared with annotation_target. Source and
    ownership are re-read under those locks. Stale snapshots, duplicate identities
    and another owner fail without a partial append. Exact same-owner retries are
    idempotent; source rows remain untouched. This operation has no HTTP route.
    """
    if not isinstance(thread, str) or not thread or not isinstance(expected, dict) or expected.get('slug') != thread:
      raise ValueError('thread and its expected raw payload must identify the same existing Thread')
    if not isinstance(annotations, list) or not annotations:
      raise ValueError('annotations must be a nonempty list of original source annotations')
    expected, annotations = deepcopy(expected), deepcopy(annotations)
    for annotation in annotations:
      if (not isinstance(annotation, dict) or set(annotation) != set(ANNOTATION_FIELDS)
          or not isinstance(annotation['uid'], str) or not annotation['uid']
          or annotation['subject'] != thread):
        raise ValueError('each original annotation must retain its native UID and outgoing Thread subject')
    originals = {row['uid']: row for row in annotations}
    if len(originals) != len(annotations):
      raise ValueError('annotation identities must be unique')
    if PROCESS.get() is None:
      raise ValueError('annotation adoption requires an Api.process transaction')
    with opened() as db, db.transaction():
      lock_annotations(db, originals)
      nodes = age.nodes(db, 'label(n) = "Thread" AND n.slug = $uid', {'uid': thread})
      if len(nodes) != 1:
        raise ValueError('thread must identify exactly one existing Thread node')
      owner = nodes[0]['id']

      def adopt(body, row):
        current = body.get('annotations', [])
        prior = expected.get('annotations', [])
        if not isinstance(current, list) or not isinstance(prior, list):
          raise ValueError('Thread annotations must be an ordered list')
        if len({item['uid'] for item in current}) != len(current):
          raise ValueError('the Thread contains duplicate annotation identities')
        # A retry may differ from its before snapshot only by exact adopted originals.
        if body != expected:
          appended = current[len(prior):]
          if (current[:len(prior)] != prior or not appended
              or any(item['uid'] not in originals or item != originals[item['uid']] for item in appended)):
            raise ValueError('the expected Thread payload is stale')
          before = dict(body)
          if 'annotations' in expected:
            before['annotations'] = prior
          else:
            before.pop('annotations')
          if before != expected:
            raise ValueError('the expected Thread payload is stale')

        source = db.execute('SELECT uid::text AS uid,subject,predicate,object,value,evidence,generated,verified'
                            ' FROM files_source.annotation WHERE uid::text = ANY(%s)', (list(originals),)).fetchall()
        if len(source) != len(originals) or {item['uid']: dict(item) for item in source} != originals:
          raise ValueError('an original source annotation is missing or stale')
        projected = annotation_rows(db, originals)
        adopted, existing = [], []
        for uid, original in originals.items():
          target = projected[uid]
          if {key: target[key] for key in ANNOTATION_FIELDS} != original:
            raise ValueError('an annotation has changed since the ownership preview')
          if target['owner_kind'] == 'source':
            if any(item['uid'] == uid for item in current):
              raise ValueError('the Thread payload and annotation projection disagree')
            adopted.append(uid)
          elif (target['owner_kind'] == 'node' and str(target['owner_uid']) == str(owner)
                and 0 <= target['annotation_index'] < len(current)
                and current[target['annotation_index']] == original):
            existing.append(uid)
          else:
            raise ValueError('an annotation belongs to another owner or has conflicting content')
        if adopted:
          if 'annotations' not in body:
            body['annotations'] = []
          body['annotations'].extend(deepcopy(originals[uid]) for uid in adopted)
        return {'adopted': adopted, 'existing': existing}

      result = self.mutate('node', owner, adopt)
      return {'uid': thread, 'owner_kind': 'node', 'owner_uid': owner,
              'adopted': result['adopted'], 'existing': result['existing']}

  def annotation_target(self, uid):
    """Resolve or materialize an annotation under its shared ownership identity lock."""
    if not isinstance(uid, str) or not uid:
      raise ValueError('annotation UID is required')
    with opened() as db, db.transaction():
      lock_annotations(db, [uid])
      target = annotation_rows(db, [uid])[uid]
      if target['owner_kind'] != 'source':
        return {key: target[key] for key in ('owner_kind', 'owner_uid', 'annotation_index')}
      if PROCESS.get() is None:
        raise ValueError('source annotation ownership requires an Api.process transaction')
      original = {key: target[key] for key in ANNOTATION_FIELDS}
      owner = references.source_node('pg://pg.karel.in/files/lake/annotation', {'uid': uid}, connection=db)

      def materialize(body, row):
        if 'annotations' not in body:
          body['annotations'] = []
        current = body['annotations']
        if not isinstance(current, list):
          raise ValueError('existing annotations must be an ordered list')
        matches = [index for index, item in enumerate(current) if item['uid'] == uid]
        if matches:
          if len(matches) != 1 or current[matches[0]] != original:
            raise ValueError('the annotation reference contains conflicting content')
          return {'annotation_index': matches[0]}
        current.append(deepcopy(original))
        return {'annotation_index': len(current) - 1}

      result = self.mutate('node', owner, materialize)
      return {'owner_kind': 'node', 'owner_uid': owner, 'annotation_index': result['annotation_index']}

  def verify(self, what, uid, state='approved', why='', who=HUMAN):
    """Append a ruling to an object or an individual annotation.

    Args:
      what (str): Target kind: node, record, span, thread or annotation. thread uses its Thread UID; annotation uses its annotation UID.
      uid (str): Identity of the target selected by what.
      state (str): Ruling declared in GET /graph/model under rulings, such as approved or rejected.
      why (str): Reason attached to the ruling.
      who (str): Author identity. Browser HTTP writes supply this from the authenticated session; omit it from the JSON body. Direct Python calls must supply the actual author.

    Returns:
      dict: what and uid identify the resolved stored owner; ruling contains by, at, state and why. For an annotation, thread or native span, the returned owner can differ from the input identity.

    Example:
      {"what": "record", "uid": "<record_uid>", "state": "approved", "why": "Reviewed"}
    """
    if state not in configuration.row('admin_ui', 'model')['rulings']:
      raise ValueError('a ruling must approve or reject')
    ruling = signed(who) | {'state': state, 'why': why}
    annotation_index = None
    if what == 'thread':
      uid = self.thread_node(uid)['id']
      what = 'node'
    elif what == 'annotation':
      target = self.annotation_target(uid)
      what, uid, annotation_index = target['owner_kind'], target['owner_uid'], target['annotation_index']
    elif what == 'span':
      with opened() as db:
        stored = db.execute('SELECT uid FROM fact.span WHERE uid = %s', (uid,)).fetchone()
        if stored is None:
          original = one(db, 'SELECT verified FROM lake.span WHERE uid::text = %s', (uid,))
      if stored is None:
        ref = self.reference('pg://pg.karel.in/files/lake/span', {'uid': str(uid)}, create=True)
        def materialize(body, row):
          if 'verified' not in body and original['verified'] is not None:
            body['verified'] = original['verified']
          return {}
        self.mutate('node', ref['id'], materialize)
        what, uid = 'node', ref['id']
    def append(body, row):
      if annotation_index is not None:
        row = body['annotations'][annotation_index]
      row['verified'] = verification_events(row.get('verified')) + [ruling]
      return {'ruling': ruling}
    return self.mutate(what, uid, append)

# endregion


# region - CRAP Systems/admin_ui/shared/dagster_configuration.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Systems/admin_ui/shared/dagster_configuration.py
def flows() -> dict[str, LocationFlow]:
  """Read the Location flows consumed by Dagster from the graph's configuration.

  Returns:
    dict: Map keyed by Dagster asset key. Each LocationFlow contains uid, name, asset, implementation, sources [{uid, uri}], destination {uid, uri} or null, template or null, dependencies and file_templates. Sources and destinations reference the same Location identities as /config/locations. Future configuration edits belong under /config; this operation only reads.

  Example:
    {}
  """
  with configuration.ENVIRONMENT_LOCK:
    configuration.environment()
    file_templates = [key for key in glob_dict('sources')['uri_templates'] if key.startswith('file_')]
    tables = configuration.tables()

    def location(uid: str) -> LocationReference:
      return {'uid': uid, 'uri': tables['locations'][uid]['canonical']}

    def flow(uid: str, row: dict[str, Any], sources: list[str], destination: str | None) -> LocationFlow:
      target = location(destination) if destination else None
      return {'uid': uid, 'name': row.get('name') or uid, 'asset': row['asset'],
        'implementation': row.get('implementation') or '', 'sources': [location(source) for source in sources],
        'destination': target, 'template': row.get('template'), 'dependencies': row.get('dependencies', []),
        'file_templates': file_templates if target and target['uri'].startswith('file://')
                          and row.get('implementation') not in ('TelegramContacts', 'TelegramChats') else []}

    result = {row['asset']: flow(uid, row, [row['location']], row.get('writes'))
              for uid, row in tables['sources'].items()}
    for uid, row in glob_dict('processes').items():
      if isinstance(row, dict) and 'source_location_uids' in row:
        result[row['asset']] = flow(uid, row, row['source_location_uids'], row['destination_location_uid'])
    return result

# .. imports, comments and docstring text that read differently now
#    from gppu import Env
#    from gppu import glob_dict

# endregion


# region - CRAP Systems/admin_ui/shared/file_configuration.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu import Container, DataObject, FileSystem, Location, jinja

# endregion


# region - CRAP Systems/admin_ui/shared/inventory/graph.py as of 2026-11-20 (1)

# .. gone
if __name__ == '__main__':
  import asyncio

  from gppu import Info
  from gppu.app import AsyncApp

  class GraphApp(AsyncApp):
    async def start(self) -> None:
      for uid, row in configuration.tables()['connections'].items():
        if 'app' not in row:
          continue
        graph = Graph(uid)
        who = graph.get('organization')['value'][0]
        print(f'  {uid:<10}{who["displayName"]:<22}{graph.identity["client_id"]}')
      Info('the tenants the configuration has credentials for')

  asyncio.run(GraphApp().run())

# endregion


# region - CRAP Systems/admin_ui/shared/inventory/locations.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Systems/admin_ui/shared/inventory/locations.py
class Locations:
  """Every location this machine has, and the reader each one is read by."""

  def __init__(self) -> None:
    self.readers: dict[str, object] = {}
    tables = configuration.tables()
    self.all = dict(tables['locations'])
    self.placed = set(configuration.rule('locations', 'on_host')(Env.host))
    self.here = {uid: self.all[uid] for uid in self.placed}
    self.sources = {source['location']: source for source in tables['sources'].values()
                    if source['provides'] == 'contacts'}
    self._index = None
    self._manifested = None
    self._sessions = None
    self.show = {'physical': False, 'logical': True}   # logical is the index; physical reads the folder

  def index(self):
    """The index: the database the locations, their copies and everything read of them are in."""
    return psycopg.connect(configuration.rule('connections', 'dsn')('pg', INDEX), connect_timeout=10)

  # -- what a location is, and which ones the filters leave ---------------------------------
  def logical(self, uid: str) -> bool:
    """Whether the registry records no physical Location for this one, on any host.

    Alex, 2026-09-18: "locations are configuration. When laptop is turned off - it should work
    the same way. Configuration is not derived form laptop's disk." So this reads the registry
    and never this machine: a Location is physical where a physical Location of it is recorded, and
    the answer is the same on every host.

    It used to ask the configuration's `local`, which is this laptop's path, so the same
    configuration split the tree differently on every machine that read it.
    """
    return self.address(uid).rstrip('/').casefold() not in self.manifested()

  def manifested(self) -> set[str]:
    """Every Location the registry records a physical Location for, by the address it answers at."""
    if self._manifested is None:
      with self.index() as db:
        self._manifested = {str(uri).rstrip('/').casefold() for uri, in db.execute(
          'SELECT DISTINCT coalesce(nullif(l.canonical, %(e)s), i.uri) FROM archive_260921_lake.location l'
          ' JOIN archive_260921_lake.location_instance i ON i.location_id = l.id', {'e': ''}).fetchall() if uri}
    return self._manifested

  def local_roots(self) -> dict:
    """What this host holds as its own: a location placed here that no service answers for."""
    return {uid: row for uid, row in self.all.items() if uid in self.placed and not self.logical(uid)}

  def folders(self) -> dict:
    """The folder each location is in on this host, named as gppufs names a folder: the location map gppu's
    `locate` reads. The configuration places a location here, mirrors among them, which `reached` would not find
    from the location's own uri."""
    return {full_path(row['local']).as_posix(): {'location': uid, 'canonical': self.address(uid)}
            for uid, row in self.here.items() if row.get('local')}

  def logicals(self) -> list[dict]:
    """Every location the index holds, read once: the logical side comes from there.

    lake.location is the tree — a name, the service that answers for it, and its parent.
    lake.location_instance is the copy on a host: where it is and the address it answers at.

    It used to join the instance on this host, so the node held the 44 locations this laptop has
    a copy of rather than all 343 — the opposite of what it is for. A location this host does not
    have is exactly what belongs here, so the copy is joined only to learn the path, and a location
    without one still comes back and says so.

    An address is read, never built: this host's copy answers first, then the location's own, then
    any host's copy. The eight roots have none anywhere, because nothing addresses a machine, and
    they stand under their own name.
    """
    if self._index is None:
      with self.index() as db:
        self._index = [dict(zip(('id', 'parent', 'name', 'service', 'places', 'uri'), row)) for row in db.execute(
          'SELECT l.id, l.parent_id, l.name, l.service,'
          ' (SELECT count(*) FROM archive_260921_lake.location_instance WHERE location_id = l.id),'
          ' coalesce(nullif(l.canonical, %(e)s), nullif(far.uri, %(e)s), l.name)'
          ' FROM archive_260921_lake.location l'
          ' LEFT JOIN LATERAL (SELECT uri FROM archive_260921_lake.location_instance'
          ' WHERE location_id = l.id AND uri <> %(e)s ORDER BY host LIMIT 1) far ON true'
          ' ORDER BY l.name', {'e': ''}).fetchall()]
    return self._index

  def graph(self) -> dict:
    """The locations as a graph: every location the index holds, and every host that has one.

    A tree is one view of this — a location under its parent. The graph is the other: one
    location with copies on several hosts is a node with an edge per copy, which no tree shows.

    The annotation layer sits on top of these locations and is drawn on them: what is said about
    a thing is said about an entity, and an entity is in one location. A thread is not drawn as
    attached to a location, because it is not — Alex links threads and spans himself, and until
    he does, an edge from one to a location would be invented.
    """
    with self.index() as db:
      locations = db.execute('SELECT id, parent_id, name, service FROM archive_260921_lake.location ORDER BY name').fetchall()
      instances = db.execute('SELECT location_id, host, server_type, path FROM archive_260921_lake.location_instance').fetchall()
      annotated = dict(db.execute('SELECT e.location_id, count(DISTINCT a.subject) FROM lake.annotation a'
                                  ' JOIN lake.entity e ON e.uid::text = a.subject GROUP BY 1').fetchall())
      layer = dict(zip(('threads', 'spans', 'annotations'), db.execute(
        'SELECT (SELECT count(*) FROM lake.thread), (SELECT count(*) FROM lake.span),'
        ' (SELECT count(*) FROM lake.annotation)').fetchone()))
    hosts = sorted({host for _, host, _, _ in instances})
    nodes = [{'id': f'l{lid}', 'label': name.rsplit(chr(92), 1)[-1], 'kind': 'location',
              'service': service or '', 'name': name, 'annotated': annotated.get(lid, 0)}
             for lid, _, name, service in locations]
    nodes += [{'id': f'h{host}', 'label': host, 'kind': 'host', 'service': '', 'name': host} for host in hosts]
    edges = [{'source': f'l{lid}', 'target': f'l{parent}', 'kind': 'inside'}
             for lid, parent, _, _ in locations if parent is not None]
    edges += [{'source': f'l{lid}', 'target': f'h{host}', 'kind': server or 'local', 'path': path}
              for lid, host, server, path in instances]
    return {'nodes': nodes, 'edges': edges, 'layer': layer}

  def sessions(self) -> list[dict]:
    """The session folders the index holds, each with the span its sessions cover.

    The index knows every host's folders, so this is not only what is here. A folder's path
    is walked up the entity tree in this process rather than in the query, which turns a
    recursive join over two million rows into one read of the folders and a dictionary walk.
    """
    if self._sessions is None:
      with self.index() as db:
        parents = {uid: (parent, name) for uid, parent, name in db.execute(FOLDER_TREE).fetchall()}
        locations = dict(db.execute('SELECT id, name FROM archive_260921_lake.location').fetchall())
        # where this host keeps each location, so a folder can be handed back to the handlers
        roots = dict(db.execute('SELECT location_id, path FROM archive_260921_lake.location_instance'
                                ' WHERE lower(host) = lower(%s)', (Env.host,)).fetchall())
        rows = db.execute(SESSION_FOLDERS).fetchall()

      def path(uid) -> str:
        trail = []
        while uid in parents:
          uid, name = parents[uid]
          trail.append(name)
        return '/'.join(reversed(trail))

      folders = []
      for uid, lid, sessions, began, ended, bytes_, turns, human, harnesses in rows:
        inside = path(uid)
        root = roots.get(lid, '').replace('\\', '/')
        below = inside.partition('/')[2]   # the trail under the entity tree's root, which is the location's
        folders.append({'path': inside, 'name': inside.rsplit('/', 1)[-1], 'location': locations.get(lid, ''),
                        'root': root, 'inside': below, 'sessions': sessions, 'turns': turns, 'human': human,
                        'bytes': bytes_, 'harnesses': harnesses or [],
                        'began': began.isoformat() if began else '',
                        'ended': ended.isoformat() if ended else ''})
      self._sessions = sorted(folders, key=lambda row: row['ended'], reverse=True)
    return self._sessions

  def roots(self) -> list[dict]:
    """The locations this host holds, and where: what a walk can be started on."""
    return [{'location': row['name'], 'root': row['local'].replace('\\', '/')}
            for row in self.here.values() if row.get('local')]

  def walk_sessions(self, root: str, inside: str = '', archives: bool = False):
    """The session folders under one root, a folder at a time, as gppu's walk meets them.

    The walk is gppu's (`walk_files`): each folder with the rows of what it holds, every file read
    by its handler, so a session's record is its handler's, read once. A folder is yielded the
    moment the walk has finished it, so a caller sees folders arriving and no folder waits on the
    tree. With `archives`, an archive's members are walked too: listed with no bytes read, a member
    a handler reads fetched alone when the walk reaches it.
    """
    if not root:
      raise FileNotFoundError(f'{Env.host} has no copy of this location')
    start = Path(f'{root.rstrip("/")}/{inside}' if inside else root)
    for folder, rows in walk_files(start, '', 'archives' if archives else 'handlers', True, ()):
      sessions = [row['record'] for row in rows if row['type'] == 'file' and row['record']['type'] in SessionHandler.TURNS]
      if sessions:
        yield self.read_sessions(start, folder['name'], sessions)

  def read_sessions(self, start: Path, folder: str, sessions: list[dict]) -> dict:
    """One folder's sessions, as their handler read them: what each session says of itself, and the span over
    them all. A folder inside an archive is addressed through the archive it is in."""
    spans = [record['span'] for record in sessions if record['span']]
    inside = PurePosixPath(folder)
    return {'path': f'{start.as_posix()}/{folder}'.rstrip('/'), 'name': inside.name or start.name,
            'inside': folder, 'sessions': len(sessions),
            **({'archived': True} if any(part.casefold().endswith(ARCHIVES) for part in inside.parts) else {}),
            'turns': sum(record['data']['turns'] for record in sessions),
            'harnesses': sorted({record['type'] for record in sessions}),
            'models': sorted({model for record in sessions for model in record['data'].get('models') or []}),
            'began': min(span.start for span in spans).isoformat() if spans else '',
            'ended': max(span.end for span in spans).isoformat() if spans else ''}

  def indexed_row(self, row: dict, addresses: dict) -> dict:
    """One indexed location as a tree row: what it is, and whether a physical Location is recorded.

    A Location is physical where the registry records a physical Location of it, on any host, and
    logical where it records none — the same question `row` asks of the configuration and in the
    same words, so the two halves of the tree say the same thing about the same Location, and say
    it the same way on every machine that reads them.
    """
    kind = 'physical' if row['places'] else 'logical'
    return {'name': row['uri'], 'type': 'directory', 'local': '',
            'gppu': {'name': row['name'].rsplit(chr(92), 1)[-1], 'is_container': True,
                     'location': {'location': str(row['id']), 'canonical': row['uri'],
                                  'address': row['uri'], 'folder': ''},
                     'parent': addresses.get(row['parent'], LOGICAL),
                     'handlers': ['location', kind] + ([] if row['places'] else ['elsewhere'])
                                 + ([row['service']] if row['service'] else []),
                     'files': None, 'folders': None, 'bytes': None, 'span': [], 'probed_at': None,
                     'source': {'service': row['service'] or 'local', 'location': ''}}}

  def logical_row(self) -> dict:
    """The one node under which every logical location hangs."""
    return {'name': LOGICAL, 'type': 'directory', 'local': '',
            'gppu': {'name': LOGICAL, 'is_container': True, 'parent': ROOT,
                     'location': {'location': LOGICAL, 'canonical': '', 'address': LOGICAL, 'folder': ''},
                     'handlers': ['location', 'logical'],
                     'files': None, 'folders': None, 'bytes': None,
                     'span': [], 'probed_at': None}}

  # -- the locations, as rows --------------------------------------------------------------
  def address(self, uid: str) -> str:
    return self.all[uid]['canonical']

  def row(self, uid: str) -> dict:
    """A location as a row: its own address, and the node it hangs under."""
    location = self.all[uid]
    local = location.get('local') or ''
    kind = 'logical' if self.logical(uid) else 'physical'
    return {'name': self.address(uid), 'type': 'directory', 'local': local,
            'gppu': {'name': location['name'], 'is_container': bool(local),
                     # a location identifies itself the way the handler identifies a folder in one
                     'location': {'location': uid, 'canonical': self.address(uid),
                                  'address': self.address(uid), 'folder': ''},
                     'parent': LOGICAL if kind == 'logical' else ROOT,
                     'handlers': ['location', kind] + ([] if local else ['elsewhere'])
                                 + ([self.sources[uid]['provides']] if uid in self.sources else location['tags']),
                     'files': None, 'folders': None, 'bytes': None, 'span': [], 'probed_at': None,
                     'source': {'service': location['service'], 'location': local}}}

  def root(self) -> dict:
    return {'name': ROOT, 'type': 'directory',
            'gppu': {'name': f'{Env.host} ({Env.platform})', 'is_container': True,
                     'parent': '', 'handlers': [], 'files': None, 'folders': len(self.local_roots()) + 1,
                     'bytes': None, 'span': [], 'probed_at': None}}

  # -- the reader of a location ------------------------------------------------------------
  def reader(self, uid: str):
    """What reads this location: the source that reads it as contacts, else the one gppufs, which reads every
    folder by its full path."""
    if uid not in self.readers:
      if uid not in self.placed:
        raise FileNotFoundError(f'{uid}: {Env.host} has no copy of {self.address(uid)}')
      self.readers[uid] = (ContactsFileSystem(self.sources[uid]['uid']) if uid in self.sources
                           else GppuFileSystem())
    return self.readers[uid]

  def owner(self, address: str):
    """The reader of the location an address is in, and what that reader is asked for. A location's own
    address opens the location, a folder location at its folder here; anything below it belongs to that
    location's reader."""
    here = {self.address(uid): uid for uid in self.here}          # a folder location's address is
    base = max((a for a in here if address == a or address.startswith(a.rstrip('/') + '/')),
               key=len, default=None)                             # its own; location_of only knows
    uid = here[base] if base else configuration.rule('locations', 'location_of')(address)   # the served schemes
    if uid and uid in self.here:
      reader = self.reader(uid)
      if address == self.address(uid): return reader, None if uid in self.sources else self.here[uid]['local']
      rest = ('' if not base else address[len(base):] if base.endswith('://')
              else address[len(base.rstrip('/')) + 1:])   # a logical address below a location
      return reader, (f"{self.here[uid]['local'].rstrip('/')}/{rest}" if rest else address)
    folders = self.folders()                              # a folder's rows are named by their path
    folder = max((f for f in folders if address == f or address.startswith(f.rstrip('/') + '/')),
                 key=len, default=None)                   # here, D:/TextLake/…
    if folder is not None:
      return self.reader(folders[folder]['location']), address
    raise FileNotFoundError(address)

  def located(self, reader, rows):
    """gppufs's rows with the configured location each is in; a contacts source's rows carry their own."""
    return [locate(self.folders(), row) for row in rows] if isinstance(reader, GppuFileSystem) else rows

  # -- listing ------------------------------------------------------------------------------
  async def info(self, address: str | None = None, refresh: bool = False, **kwargs) -> dict:
    if address in (None, ROOT): return self.root()
    if address == LOGICAL: return self.logical_row()
    for uid in self.all:
      if address == self.address(uid): return self.row(uid)   # the Location itself
    reader, inside = self.owner(address)
    return self.located(reader, [await reader._info(inside, refresh=refresh)])[0]

  async def ls(self, address: str | None = None, detail: bool = True,
               recurse: bool = False, refresh: bool = False, **kwargs) -> list:
    if address in (None, ROOT):
      # a root is always there; the checkboxes say where a listing under it is read from
      return [self.row(uid) for uid in self.local_roots()] + [self.logical_row()]
    if address == LOGICAL:
      rows = self.logicals()
      addresses = {row['id']: row['uri'] for row in rows}
      return [self.indexed_row(row, addresses) for row in rows]
    reader, inside = self.owner(address)
    # a location is both: physical is the folder as gppufs reads it, logical is what its index holds
    rows = await reader._ls(inside, detail=detail, recurse=recurse, refresh=refresh,
                            live=self.show['physical'])   # reading the folder is what indexes it
    return self.located(reader, rows) if detail else rows

# .. imports, comments and docstring text that read differently now
#    from gppu import Env

# endregion


# region - CRAP Systems/admin_ui/shared/server.py as of 2026-11-20 (1)

# .. gone
# gppu's REST surface (/api) lists the classes born under Env.app_path, which only from_env sets. The
# configuration itself is the graph on pg.karel.in, loaded by lake.common.graph_configuration; the
# file from_env reads beside this module declares nothing.
Env.from_env(name='admin-graph-api', app_path=Path(__file__).resolve().parent)

# .. imports, comments and docstring text that read differently now
#    from pathlib import Path
#    from gppu import Env

# endregion


# region - CRAP Systems/craptui/craptui.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Systems/craptui/craptui.py
def main() -> None:
  apps = load_registry(APP_DIR, App(environment='RAN', config=CRAPTUIApp.CONFIG))
  launcher_main(apps, CRAPTUIApp, APP_DIR, 'craptui — Superapp launcher')

# .. imports, comments and docstring text that read differently now
#    from gppu.tui import TUILauncher, launcher_main, load_registry

# endregion


# region - CRAP Systems/craptui/inventory/bootstrap_db.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu.gppu import Vault, VaultProviderAzure

# endregion


# region - CRAP Systems/craptui/inventory/db.py as of 2026-11-20 (1)

# .. changed; the one of now is in CRAP Systems/craptui/inventory/db.py
def init_pool_from_kv(tenant: str, *, read_only: bool = False,
                      max_size: int = 4) -> ConnectionPool:
    """Fetch URL from KV via gppu.Vault, populate local cache, open pool."""
    from gppu.gppu import Vault, VaultProviderAzure
    from tenant_config import load_tenant_config
    cfg = load_tenant_config(tenant)
    os.environ["AZURE_KEYVAULT_NAME"] = cfg.vault_name
    Vault.provider_set(VaultProviderAzure(cfg.vault_name))
    secret = (cfg.secrets["postgres_reader_url"] if read_only
              else cfg.secrets["postgres_writer_url"])
    url = Vault.get(secret)
    write_url_cache(tenant, url, read_only=read_only)
    return init_pool(url, max_size=max_size)

# endregion


# region - CRAP Systems/craptui/inventory/inventory.py as of 2026-11-20

# .. imports, comments and docstring text that read differently now
#    from gppu.gppu import Vault, VaultProviderAzure

# endregion


# region - CRAP Systems/craptui/rewrite-commits/rewrite_commits.py as of 2026-11-20 (2)

# .. gone
def _plain(s: str) -> str:
  """Strip Textual/Rich console markup (``[red]…[/red]`` etc.) for file output."""
  try:
    return Text.from_markup(s).plain
  except Exception:
    return s


# .. changed; the one of now is in CRAP Systems/craptui/rewrite-commits/rewrite_commits.py
class RewriteCommitsApp(TUIApp):
  TITLE = 'Rewrite Commits'

  CSS = """
  Screen { align: center top; }
  #body {
    width: 100%;
    height: 1fr;
    padding: 1 2;
  }
  #title {
    text-style: bold;
    padding: 0 0 1 0;
  }
  #select-header {
    padding: 0 2;
    color: $text-muted;
  }
  #selection {
    border: solid $accent;
    padding: 0 1;
    margin-bottom: 1;
    height: 1fr;
    min-height: 8;
  }
  #preview {
    border: solid $accent;
    padding: 1 2;
    margin-bottom: 1;
    height: 1fr;
    min-height: 8;
    display: none;
  }
  #log {
    border: solid $warning;
    padding: 0 1;
    height: 10;
  }
  #buttons {
    height: 3;
    padding: 0 1;
    align: center middle;
  }
  Button { margin: 0 1; }
  .muted { color: $text-muted; }
  .error { color: $error; }
  .ok { color: $success; }
  """

  BINDINGS = [
    Binding('q', 'quit', 'Quit'),
    Binding('escape', 'back', 'Back'),
  ]

  def __init__(self, config_path: Path = CONFIG_FILE, **kwargs) -> None:
    super().__init__(**kwargs)
    self._config_path = config_path
    cfg = load_config(config_path)
    self._configured_repos = parse_repos(cfg)
    self._owners = parse_owners(cfg)
    self._all_repos: list[RepoSpec] = []
    self._repos: list[RepoSpec] = []  # set on Start from selection
    self._markers = list(cfg.get('markers') or ['co-authored-by:', 'generated with', 'generated by'])
    self._targets = list(cfg.get('targets') or ['claude', 'codex', 'bots'])
    self._author_rewrites = parse_author_rewrites(cfg)
    self._match_regex = build_match_regex(self._markers, self._targets)
    self._callback_code = build_callback_code(self._targets, self._author_rewrites)
    self._workdir: Path | None = None
    self._repo_idx = 0
    self._phase = 'idle'  # idle | cloning | previewing | awaiting | rewriting | done
    self._abort = threading.Event()
    self._decision_ready = threading.Event()
    self._decision: str = ''  # skip | proceed | pause
    self._current_preflight: PreflightResult | None = None
    self._auto_proceed_all = False
    self._stats = {'skipped': 0, 'proceeded': 0, 'clean': 0, 'errors': 0}
    self._stats_lock = threading.Lock()
    self._state: dict[str, str] = load_state()
    self._state_lock = threading.Lock()
    self._parallel = parse_parallel(cfg)
    self._small_done = threading.Event()
    self._small_done.set()

  # ── compose ────────────────────────────────────────────────────────────

  def compose(self) -> ComposeResult:
    yield Header()
    with Vertical(id='body'):
      yield Static('Rewrite Commits — large=sequential, small=parallel', id='title')
      yield Static(self._selection_header_text(), id='select-header')
      yield SelectionList[str](id='selection')
      yield RichLog(id='preview', markup=True, wrap=False, highlight=False)
      yield RichLog(id='log', markup=True, wrap=True, highlight=False)
      with Horizontal(id='buttons'):
        yield Button('Start', id='btn-start', variant='primary', disabled=True)
        yield Button('Skip', id='btn-skip', disabled=True)
        yield Button('Proceed', id='btn-proceed', disabled=True, variant='warning')
        yield Button('Proceed All', id='btn-proceed-all', disabled=True, variant='warning')
        yield Button('Pause', id='btn-pause', disabled=True)
        yield Button('Quit', id='btn-quit')
    yield Footer()

  @staticmethod
  def _selection_header_text() -> str:
    return (
      f'{"":2s}  {"Repo":40s}  {"Size":>10s}  {"Last rewritten":20s}  '
      f'Tags   (⊘ archived, ○ public)'
    )

  def _selection_label(self, r: RepoSpec) -> str:
    size_str = '—' if r.size_kb is None else f'{r.size_kb / 1024:.1f} MB'
    ts = self._state.get(r.full, 'never')
    if ts != 'never':
      ts = ts[:19]  # trim Z, keep YYYY-MM-DDTHH:MM:SS
    flags = ('⊘' if r.archived else ' ') + ('○' if r.private is False else ' ')
    tags: list[str] = []
    if r.in_yaml:
      tags.append('yaml')
    if r.fork:
      tags.append('fork')
    tag_str = ' '.join(f'[{t}]' for t in tags)
    return f'{flags}  {r.full:40s}  {size_str:>10s}  {ts:20s}  {tag_str}'

  def on_mount(self) -> None:
    missing = check_prereqs()
    log = self.query_one('#log', RichLog)
    if missing:
      log.write(f'[red]Missing required commands:[/red] {", ".join(missing)}')
      return
    log.write(f'[dim]Config: {self._config_path}[/dim]')
    log.write(f'[dim]State:  {STATE_FILE}[/dim]')
    if self._author_rewrites:
      names = ', '.join(sorted(self._author_rewrites.names))
      log.write(f'[dim]Author rewrites: {names} → {self._author_rewrites.target_name}[/dim]')
    log.write('[dim]Loading repository list from GitHub…[/dim]')
    self._populate_selection()

  @work(thread=True, exit_on_error=False)
  def _populate_selection(self) -> None:
    yaml_repos = list(self._configured_repos)
    discovered: list[RepoSpec] = []
    for owner in self._owners:
      self.call_from_thread(
        self._log_msg, 'gh',
        f'[dim]Fetching {owner}/* via gh repo list…[/dim]',
      )
      repos, err = fetch_all_repos_for_owner(owner)
      if err:
        self.call_from_thread(
          self._log_msg, 'gh', f'[red]{owner}: {err}[/red]',
        )
        continue
      discovered.extend(repos)
    self._all_repos, missing = merge_yaml_and_discovered(yaml_repos, discovered)
    if missing:
      names = ', '.join(r.full for r in missing)
      self.call_from_thread(
        self._log_msg, 'gh',
        f'[yellow]In yaml but not on GitHub (dropped): {names}[/yellow]',
      )
    self.call_from_thread(self._render_selection)

  def _render_selection(self) -> None:
    sel = self.query_one('#selection', SelectionList)
    sel.clear_options()
    for r in self._all_repos:
      sel.add_option(Selection(self._selection_label(r), r.full, r.in_yaml))
    self.query_one('#btn-start', Button).disabled = False
    self.query_one('#log', RichLog).write(
      f'[dim]{len(self._all_repos)} repos loaded; '
      f'{sum(1 for r in self._all_repos if r.in_yaml)} pre-selected from yaml. '
      f'Adjust selection then press Start.[/dim]'
    )

  # ── buttons ────────────────────────────────────────────────────────────

  def on_button_pressed(self, event: Button.Pressed) -> None:
    bid = event.button.id
    if bid == 'btn-quit':
      self.done()
    elif bid == 'btn-start':
      self._begin_sequence()
    elif bid == 'btn-proceed-all':
      self._auto_proceed_all = True
      self._resolve_decision('proceed')
    elif bid in ('btn-skip', 'btn-proceed', 'btn-pause'):
      self._resolve_decision(bid.replace('btn-', ''))

  def _set_decision_buttons(self, enabled: bool) -> None:
    for name in ('btn-skip', 'btn-proceed', 'btn-proceed-all', 'btn-pause'):
      self.query_one(f'#{name}', Button).disabled = not enabled

  def _resolve_decision(self, choice: str) -> None:
    self._decision = choice
    self._set_decision_buttons(False)
    self._decision_ready.set()

  # ── sequential flow ───────────────────────────────────────────────────

  def _begin_sequence(self) -> None:
    sel = self.query_one('#selection', SelectionList)
    selected = set(sel.selected)
    self._repos = [r for r in self._all_repos if r.full in selected]
    if not self._repos:
      self.query_one('#log', RichLog).write(
        '[yellow]No repos selected — nothing to do.[/yellow]'
      )
      return
    self.query_one('#btn-start', Button).disabled = True
    # Hide selection panel, reveal preview panel
    self.query_one('#selection').styles.display = 'none'
    self.query_one('#select-header').styles.display = 'none'
    self.query_one('#preview').styles.display = 'block'
    self._auto_proceed_all = False
    self._workdir = Path(tempfile.mkdtemp(prefix='rewrite-commits-'))
    self.query_one('#log', RichLog).write(
      f'[dim]Processing {len(self._repos)} selected repo(s)…[/dim]'
    )
    self._repo_idx = 0
    self._process_sequence()

  @work(thread=True, exit_on_error=False)
  def _process_sequence(self) -> None:
    # Prefer sizes already populated from `gh repo list`; only refetch the unknowns
    sizes: dict[str, int] = {
      r.full: r.size_kb for r in self._repos if r.size_kb is not None
    }
    missing = [r for r in self._repos if r.size_kb is None]
    if missing:
      self.call_from_thread(
        self._log_msg, 'sizes',
        f'[dim]Fetching sizes for {len(missing)} repo(s)…[/dim]',
      )
      sizes.update(fetch_repo_sizes_kb(missing))
    max_kb = self._parallel['max_size_kb']
    small: list[RepoSpec] = []
    large: list[RepoSpec] = []
    for repo in self._repos:
      size = sizes.get(repo.full)
      if size is not None and size <= max_kb:
        small.append(repo)
      else:
        large.append(repo)
    self.call_from_thread(
      self._log_msg, 'sizes',
      f'[dim]Parallel ({len(small)}): '
      f'{", ".join(r.full for r in small) or "(none)"}[/dim]',
    )
    self.call_from_thread(
      self._log_msg, 'sizes',
      f'[dim]Sequential ({len(large)}): '
      f'{", ".join(r.full for r in large) or "(none)"}[/dim]',
    )

    # Fan out small repos in a daemon thread (auto-proceed, no preview)
    if small:
      self._small_done.clear()
      threading.Thread(
        target=self._run_small_pool, args=(small,), daemon=True,
      ).start()
    else:
      self._small_done.set()

    # Sequential large repos with the Skip/Proceed/Pause TUI gate
    self._run_sequential(large)

    # Wait for the background pool to finish before printing summary
    self._small_done.wait()
    if self._abort.is_set():
      return

    self._phase = 'done'
    s = self._stats
    self.call_from_thread(self._update_title, 'Done')
    self.call_from_thread(
      self._log_msg, 'summary',
      f'[green]Complete.[/green] '
      f'Proceeded: {s["proceeded"]}  Skipped: {s["skipped"]}  '
      f'Clean: {s["clean"]}  Errors: {s["errors"]}'
    )

  # ── stats / state helpers (thread-safe) ────────────────────────────────

  def _bump_stat(self, key: str) -> None:
    with self._stats_lock:
      self._stats[key] = self._stats.get(key, 0) + 1

  def _record_rewritten(self, repo: RepoSpec, log) -> None:
    ts = iso_now()
    with self._state_lock:
      self._state[repo.full] = ts
      try:
        save_state(self._state)
        log(f'[dim]Recorded last-rewritten: {ts}[/dim]')
      except OSError as e:
        log(f'[yellow]Could not save state: {e}[/yellow]')

  # ── large repos: sequential w/ TUI prompt ──────────────────────────────

  def _run_sequential(self, large: list[RepoSpec]) -> None:
    self._repo_idx = 0
    while self._repo_idx < len(large):
      if self._abort.is_set():
        return
      repo = large[self._repo_idx]
      n = self._repo_idx + 1
      total = len(large)
      self.call_from_thread(self._update_title,
                            f'[{n}/{total}] {repo.full}')

      def log(msg, _repo=repo):
        self.call_from_thread(self._log_msg, _repo.full, str(msg))

      last_ts = self._state.get(repo.full)
      if last_ts:
        log(f'[dim]Last rewritten {last_ts} — checking GitHub for new commits…[/dim]')
        dirty, err_msg = has_dirty_commits_since(
          repo, last_ts, self._match_regex, self._author_rewrites,
        )
        if not dirty and not err_msg:
          log(f'[green]No new dirty commits since {last_ts} — skipping clone[/green]')
          self._bump_stat('clean')
          self._repo_idx += 1
          continue
        if err_msg:
          log(f'[yellow]{err_msg}; updating cache anyway[/yellow]')

      self._phase = 'cloning'
      dest, err = fetch_or_clone(repo, log)
      if err:
        log(f'[red]Fetch/clone failed: {err}[/red]')
        self._bump_stat('errors')
        self._repo_idx += 1
        continue

      lfs_fetch_if_needed(dest, log)

      self._phase = 'previewing'
      try:
        matches = scan_matches(dest, self._markers, self._targets,
                               self._author_rewrites)
      except subprocess.CalledProcessError as e:
        log(f'[red]Scan failed: {e}[/red]')
        self._bump_stat('errors')
        self._repo_idx += 1
        continue

      pr = PreflightResult(repo=repo, clone_dir=dest, matches=matches)
      self._current_preflight = pr

      if not pr.has_matches:
        log('No matches — skipping')
        self._bump_stat('clean')
        self._repo_idx += 1
        shutil.rmtree(dest, ignore_errors=True)
        continue

      self.call_from_thread(self._render_preview, pr)
      if self._auto_proceed_all:
        log('[cyan]Auto-proceed (run-all)[/cyan]')
        choice = 'proceed'
      else:
        self._phase = 'awaiting'
        self._decision = ''
        self._decision_ready.clear()
        self.call_from_thread(self._set_decision_buttons, True)
        self._decision_ready.wait()
        if self._abort.is_set():
          return
        choice = self._decision
      if choice == 'skip':
        log('Skipped')
        self._bump_stat('skipped')
        shutil.rmtree(dest, ignore_errors=True)
        self._repo_idx += 1
        continue
      elif choice == 'pause':
        log('Paused — press Start to resume')
        self.call_from_thread(self._enable_resume)
        return

      self._phase = 'rewriting'
      err = run_filter_repo(dest, self._callback_code, repo.purge_globs, log)
      if err:
        log(f'[red]filter-repo failed: {err}[/red]')
        self._bump_stat('errors')
        self._repo_idx += 1
        continue

      bad = verify_clean(dest, self._match_regex, self._author_rewrites)
      if bad:
        log(f'[red]{len(bad)} commit(s) still dirty after rewrite[/red]')
        self._bump_stat('errors')
        self._repo_idx += 1
        continue

      pushed, failed = push_all(dest, repo, log)
      self._bump_stat('proceeded')

      pushed_s = ', '.join(pushed) or '(none)'
      msg = f'[green]Done[/green]: pushed [{pushed_s}]'
      if failed:
        msg += f'  [red]failed: {", ".join(failed)}[/red]'
      log(msg)

      if not failed and pushed:
        self._record_rewritten(repo, log)

      log('Scanning release notes…')
      rel_matches = scan_release_notes(repo, self._match_regex, log)
      if rel_matches:
        log(f'[yellow]{len(rel_matches)} release(s) still mention targets[/yellow]')
        for m in rel_matches:
          log(f'  {m["tag"]}  {m["url"]}')

      shutil.rmtree(dest, ignore_errors=True)
      self._repo_idx += 1

  # ── small repos: parallel auto-proceed pool ────────────────────────────

  def _run_small_pool(self, small: list[RepoSpec]) -> None:
    try:
      conc = self._parallel['max_concurrent']
      with ThreadPoolExecutor(max_workers=conc) as ex:
        futs = {ex.submit(self._run_one_small, r): r for r in small}
        for f in as_completed(futs):
          try:
            f.result()
          except Exception as e:
            repo = futs[f]
            self.call_from_thread(
              self._log_msg, repo.full, f'[red]Worker crashed: {e}[/red]',
            )
            self._bump_stat('errors')
    finally:
      self._small_done.set()

  def _run_one_small(self, repo: RepoSpec) -> None:
    def log(msg, _r=repo):
      self.call_from_thread(self._log_msg, _r.full, str(msg))
    result = process_repo_auto(
      repo,
      markers=self._markers,
      targets=self._targets,
      match_regex=self._match_regex,
      callback_code=self._callback_code,
      author_rewrites=self._author_rewrites,
      state=self._state,
      state_lock=self._state_lock,
      log=log,
      abort=self._abort,
    )
    self._bump_stat(result)

  def _enable_resume(self) -> None:
    btn = self.query_one('#btn-start', Button)
    btn.disabled = False
    btn.label = 'Resume'

  def _update_title(self, text: str) -> None:
    self.query_one('#title', Static).update(text)

  def _log_msg(self, repo_full: str, msg: str) -> None:
    self.query_one('#log', RichLog).write(f'[dim][{repo_full}][/dim] {msg}')
    file_log(f'[{repo_full}] {_plain(msg)}')

  def _render_preview(self, pr: PreflightResult) -> None:
    panel = self.query_one('#preview', RichLog)
    panel.clear()
    header = (f'{pr.repo.full}  {pr.count} commit(s) to rewrite  '
              f'({pr.trailer_count} trailers, {pr.author_count} author rewrites)')
    panel.write(f'[bold]{pr.repo.full}[/bold]  '
                f'{pr.count} commit(s) to rewrite  '
                f'({pr.trailer_count} trailers, {pr.author_count} author rewrites)')
    file_log(f'[preview] {header}')
    for m in pr.matches:
      date_short = m.date[:10] if m.date else ''
      line = f'  [cyan]{m.sha[:10]}[/cyan]  {date_short}  {m.subject}'
      if m.author_rewrite:
        line += f'  [magenta]author={m.author_rewrite}[/magenta]'
      panel.write(line)
      file_log(f'[preview] {_plain(line)}')
      for t in m.trailers:
        panel.write(f'    [yellow]▸[/yellow] [dim]{t}[/dim]')
        file_log(f'[preview]     - {t}')

  # ── cleanup ────────────────────────────────────────────────────────────

  def action_back(self) -> None:
    self.done()

  def done(self, result=None) -> None:
    # Unblock worker threads so app shutdown doesn't hang on the executor
    # join (asyncio's 300s "did not finish joining its threads" warning):
    # release the decision gate, flag the pipeline, kill live git/gh children.
    self._abort.set()
    self._decision_ready.set()
    terminate_active_procs()
    if self._workdir and self._workdir.exists():
      shutil.rmtree(self._workdir, ignore_errors=True)
    super().done(result)

# .. imports, comments and docstring text that read differently now
#    from gppu import dict_from_yml, file_log
#    from rich.text import Text

# endregion


# region - IoT Projects/neo-mqtt/mesh/engine/xmqtt2mqtt.py as of 2026-11-20 (3)

# .. changed; the one of now is in IoT Projects/neo-mqtt/mesh/engine/xmqtt2mqtt.py
class Xmqtt2Mqtt(App, MqttMixin):
    def run(self):
        self._engine = Engine(
            buttons=self.my('buttons') or {},
            scene_buttons=self._scene_buttons(),
            reactions=self.my('reactions') or {},
            actions=self.my('actions') or {},
        )
        self.connstring = {
            'hostname': self.my('connection/hostname'),
            'port': self.my_int('connection/port'),
            'username': self.my('connection/username'),
            'password': self.my('connection/password'),
            'identifier': self.my('connection/identifier'),
        }
        self._status_topic = self.my('connection/status_topic') or ''
        self._subs = self._engine.subscriptions
        self._mqtt_init()
        self.Info('node', self.my('node'), '— subscriptions:', self._subs)
        asyncio.run(self._run())

    def _scene_buttons(self):
        """Build the scene_buttons map by DERIVING it from the two source-of-truth
        configs the node names (no hand-authored topic map): `scenes` (the
        insteon-mqtt scene file — which keypad button drives which relay) and
        `groups` (groups.yaml — the relay device's door path). Absent block ->
        feature off."""
        cfg = self.my('scene_buttons') or {}
        if not cfg:
            return {}
        # scenes is a top-level LIST (gppu's dict_from_yml is dict-only); the file
        # carries no !include/!secret, so plain safe_load is lossless. groups is a
        # dict -> dict_from_yml (its !include tree resolves).
        with open(cfg['scenes'], encoding='utf-8') as f:
            scenes = yaml.safe_load(f)
        groups = dict_from_yml(cfg['groups'])
        relays = derive_relay_paths(groups, cfg['relay_template'])
        smap = derive_scene_buttons(scenes, relays)
        self.Info('scene_buttons derived:', sum(len(v) for v in smap.values()),
                  'button(s) ->', sorted(set(relays.values())))
        return {'system': cfg['system'], 'map': smap}

    async def _run(self):
        will = (aiomqtt.Will(topic=self._status_topic, payload=b'offline', qos=1, retain=True)
                if self._status_topic else None)
        while True:
            try:
                async with aiomqtt.Client(**self.connstring, will=will) as client:
                    self._client = client
                    if self._status_topic:
                        await self.mqtt_publish(self._status_topic, 'online', retain=True, qos=1)
                    for topic in self._subs:
                        await client.subscribe(topic, qos=1)
                    await self._message_loop(client)
            except aiomqtt.MqttError as e:
                self.Warn('mqtt error, reconnect in 5s:', e)
                await asyncio.sleep(5)
            finally:
                self.mqtt_disconnect()

    async def _message_loop(self, client):
        async for msg in client.messages:
            topic = str(msg.topic)
            raw = msg.payload if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload).encode()
            try:
                outs = self._engine.on_event(topic, raw)
            except Exception as e:
                self.Warn('rule error on', topic, ':', e)
                continue
            for o in outs:
                try:
                    await self.mqtt_publish(o.topic, o.payload, retain=o.retain, qos=o.qos)
                except Exception as e:
                    self.Warn('publish error', o.topic, ':', e)


# .. gone
Env.from_dict(dict_from_yml(CONFIG))


# .. gone
Xmqtt2Mqtt(name='xmqtt2mqtt').run()

# .. imports, comments and docstring text that read differently now
#    Same plumbing as the any2mqtt pollers (gppu App + MqttMixin + aiomqtt, per-node
#    import aiomqtt
#    from gppu import App, Env, dict_from_yml
#    from gppu.iot import MqttMixin

# endregion


# region - IoT Projects/neo-mqtt/emqx/gen_rules.py as of 2026-11-20 (1)

# .. changed; the one of now is in IoT Projects/neo-mqtt/emqx/gen_rules.py
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='print in->out table, no files')
    ap.add_argument('--out', help='dir for *.generated.conf')
    args = ap.parse_args()

    Env.from_env()
    motion, measure, zwjs = build()

    motion_out = [r for spec in motion.sensors.values() for r in motion_rules(spec)]
    measure_out = [measure_rule(spec) for spec in measure.sensors.values()]
    zwjs_out = zwjs_device_rules(zwjs)

    if args.check:
        print(f"# motion: {len(motion.sensors)} sensors -> {len(motion_out)} rules")
        for spec in motion.sensors.values():
            print(f"  {spec['name']:28} {spec['listen_topic']}")
            print(f"{'':30}-> {spec['state_topic']}  flavors={list((spec.get('motion_posts') or {}).values())}")
        print(f"# measure: {len(measure.sensors)} -> {len(measure_out)} rules")
        for spec in measure.sensors.values():
            print(f"  {spec['name']:28} {spec['listen_topic']} -> {spec['state_topic']}")
        print(f"# zwjs devices: {len(zwjs_out)} rules ({len(zwjs._readers)} readers, {len(zwjs._set_map)} controls)")
        return 0

    if not args.out:
        ap.error('need --check or --out')
    os.makedirs(args.out, exist_ok=True)
    header = "## GENERATED by gen_rules.py from Creekview config. Do not hand-edit.\n\n"
    for fname, rules in (('motion.generated.conf', motion_out),
                         ('measures.generated.conf', measure_out),
                         ('zwjs_devices.generated.conf', zwjs_out)):
        with open(os.path.join(args.out, fname), 'w') as f:
            f.write(header + '\n'.join(rules))
        print(f"wrote {fname}: {len(rules)} rules")
    return 0

# .. imports, comments and docstring text that read differently now
#    from gppu import Env                                   # noqa: E402

# endregion


# region - IoT Projects/neo-mqtt/mesh/rules/i2.node.yaml as of 2026-11-20

# .. the lines that are gone or read differently now
#    connection:

# endregion
