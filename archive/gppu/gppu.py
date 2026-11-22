# .. archived 2026-11-22: what gppu's reduction removed from gppu/gppu.py, as it was last


# .. from fec31bb
_log_root = logging.getLogger('gppu'); _log_root.setLevel(logging.DEBUG)


# .. from fec31bb
_sh = logging.StreamHandler(sys.stderr); _log_root.addHandler(_sh)


# .. from fec31bb
def template_populate(o, data: dict = {}, excludes:list = []) -> Any:
  """ templates are simple inline functtions that return lists, dicts or scalars to be merged into dicts."""
  def __tp(o: dict | str, data: dict) -> Any:
    result: Any = None
    if not data: data = {}

    if not o: return None
    if isinstance(o, dict):
      result = {}
      for k, old in o.items():
        if k in excludes or inspect.isfunction(old): new = old
        else: new = __tp(old, o | data)
        result[k] = new
    elif isinstance(o, list):
      result = []
      for old in o:
        new = __tp(old, data)
        result.append(new)
    elif isinstance(o, (int, bool, float)): result = o
    elif inspect.isfunction(o): result = o
    else:
      if str(o) == 'DEL': result = None
      elif '$' in str(o): 
        _ = str(Template(str(o)).safe_substitute(data))
        if _[0] == '[' and _[-1] == ']':
          result = []
          _ = _[1:-1]
          for element in _.split(','):
            element = element.strip()
            if element.isdecimal(): element = int(element)
            elif element.isnumeric(): element = float(element)
            result.append(element)
        else: result = _
      else: result = o
    return result

  if isinstance(o, dict): _ = o.get('data', {}) | o
  else: _ = str(o)
  return __tp(_, data)


# .. from fec31bb
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
  # ^^ Never return None - return empty string instead to prevent logging issues
  return result if result is not None else ''


# .. from fec31bb
class _PlainFormatter(_LogColorizer):
  """The line without colours or prefix, for the log file."""
  no_prefix = True

  def format(self, record: logging.LogRecord) -> str: return self.ANSI.sub('', super().format(record))


# .. from gppu/v3.7.9
INLINE_CONFIG = ('.py', '.cmd', '.ps1')   # the scripts that carry their configuration inline


# .. from gppu/v3.7.9
def inline_config(filename: str | Path) -> str:
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


# .. from gppu/v3.7.9
@pass_context
def _render_template_in(context, name: str, **values) -> Any:
  """A named template rendered from inside another one: it sees the caller's values, and its keywords win over them."""
  return jinja.get_template(name).render(context.get_all() | values)


# .. from gppu/v3.7.9
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


# .. from gppu/v3.7.9
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


# .. from gppu/v3.7.9
def apply_template(node: Any, templates: dict) -> Any:
  """Every row of node whose `template:` names one of templates, merged over that template: the row wins. The
  template's Jinja that reads the row stays as written, for the app that renders it."""
  if isinstance(node, list): return [apply_template(value, templates) for value in node]
  if not isinstance(node, dict): return node
  node = {key: apply_template(value, templates) for key, value in node.items()}
  if isinstance(name := node.get('template'), str) and name in templates:
    return apply_template(templates[name], templates) | node
  return node


# .. from gppu/v3.7.9
@cache
def _jinja_compile(template: str):
  return jinja.from_string(template)


# .. from gppu/v3.7.9
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


# .. from gppu/v3.7.9
def jinja_fill(node: Any, /, **data) -> Any:
  """Render the Jinja strings of a configuration node, keys included, that read only the given names. Jinja that
  reads any other name stays as written, for the app that renders it later."""
  if isinstance(node, dict): return {jinja_fill(key, **data): jinja_fill(value, **data) for key, value in node.items()}
  if isinstance(node, list): return [jinja_fill(value, **data) for value in node]
  if isinstance(node, str) and ('{{' in node or '{%' in node) and (inputs := _jinja_inputs(node)) and inputs <= data.keys():
    return jinja_template(node, **data)
  return node


class Path:
  # .. from fec31bb
  def probe(self) -> dict:
    """Filesystem attributes and content handler without reading contents."""
    return probe_path(self)


class Logger:
  # .. from fec31bb
  @staticmethod
  def init_logger(name: str = 'gppu', trace_rules: dict | None = None) -> None:
    """Name the global logger, and optionally set the trace rules."""
    if trace_rules is not None:
      trace_rules = dict(trace_rules)
      TRACE_RULES.clear()
      TRACE_RULES.update(trace_rules)
    Logger._logger = Logger._root if name == 'gppu' else Logger._root.getChild(name)

  # .. from fec31bb
  @staticmethod
  def enable_file_logging(log_file: str) -> Path:
    """ Need justification for this to exist """
    # region - ^^ why enable_file_logging exists
    # ^^ RAN's config.yaml has the line `log_file: ~/.cache/gppu/hosts.log`, and loading that configuration calls this:
    # ^^ every line a RAN program prints also goes into that one file, without time or severity. No program reads it.
    # ^^ The file rotates at 4 MB and keeps 5 older files; both numbers are written here, not configured.
    # endregion
    if not isinstance(log_file, str) or not log_file.strip(): raise ValueError('File logging requires an explicit log_file in configuration')
    path = full_path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path)
    if key in Logger._file_handlers: return path
    fh = RotatingFileHandler(path, maxBytes=4_000_000, backupCount=5, encoding='utf-8')
    fh.setFormatter(_PlainFormatter())
    fh.addFilter(_EmptyMessageFilter())
    Logger._root.addHandler(fh)
    Logger._file_handlers[key] = fh
    return path

  # .. from fec31bb
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


class mixin_Logger:
  # .. from fec31bb
  @classmethod
  def __init_subclass__(cls, **kw):
    super().__init_subclass__(**kw)
    if cls.__dict__.get('_global_log'):
      for name in ('Debug', 'Info', 'Warn', 'Error', 'Dump'): setattr(cls, name, Logger.__dict__[name])
      return
    cls._logger = Logger._logger.getChild(cls.__name__)
    for name in ('Debug', 'Info', 'Warn', 'Error', 'Dump'): setattr(cls, name, staticmethod(partial(getattr(Logger, name), logger=cls._logger)))


class mixin_Config:
  # .. from fec31bb
  def my_float(self, path: str | y2path, default: float = float('nan')) -> float: return deepget_float(path, self.data, default=default)

  # .. from gppu/v3.7.9
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


class App:
  # .. from fec31bb
  def _config_load(self, source: Mapping | str | Path, argv: list[str] = []) -> None:
      """An app's own configuration over what it was constructed with: a row, a YAML file, or a script's MANIFEST;
      the command line over it: ``--key value`` sets a key, a slash path a nested one, ``--flag`` sets it to True."""
      if isinstance(source, Mapping): loaded = deepcopy(dict(source))
      elif str(source).lower().endswith(('.py', '.cmd', '.ps1', '.sh')):
          with open(full_path(source), encoding='utf-8-sig') as f: manifest = re.search(r'^MANIFEST = r?"""(.*?)"""', f.read(4096), re.M | re.S)
          if not manifest: raise ValueError(f'{source}: no MANIFEST in its first 4 KB')
          loaded = dict(yaml.load(manifest[1], Loader=YmlLoader))
      else: loaded = dict_from_yml(source)
      self.data = self.data | jinja.configuration(loaded)
      i = 0
      while i < len(argv):
          arg, i = argv[i], i + 1
          if not arg.startswith('--') or len(arg) == 2: continue
          value = True
          if i < len(argv) and not argv[i].startswith('--'): value, i = argv[i], i + 1
          deepset(arg[2:], self.data, value)

  # .. from gppu/v3.7.9
  def _init_config(self, environment: str | None = None, config: str | Path | None = None, argv: list[str] = [], **kw) -> None:
    if not self.name: self.name = type(self).__name__.lower()
    Env.init(environment=environment)
    self._config_load(glob_dict(self.name) if config is None else config, argv)


class _Env:
  # .. from fec31bb
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

    if not environment and 'config' not in kw: return   # .. a host without its repository is given its configuration, from MQTT
    self.environment = environment
    if environment: self.path = Path("D:\\Dev" if self.os == OSType.W11 else "~").expanduser() / _ENV_PATHS[environment]
    self.data = kw['config'] if 'config' in kw else dict_from_yml(self.path)   # .. one YAML load of its file; MQTT and Y2's configure give it whole
    # region - the configuration's macros, named templates, `template:` rows and the Jinja that reads only the configuration
    # .. Creekview and RAN use all four: _creekview.yaml's macros, the *_templates and templates blocks of groups, Insteon,
    # .. covers and the devices, and RAN config.yaml's mounts; glob reads the value it fills, filled
    # endregion
    self.data = jinja.configuration(self.data)
    if 'log_file' in self.data: Logger.enable_file_logging(self.data['log_file'])
    if 'trace_rules' in self.data: Logger.init_logger(trace_rules=self.data['trace_rules'])
    self.initialized = True
