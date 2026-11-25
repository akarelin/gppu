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
