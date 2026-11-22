# .. archived 2026-11-22: what gppu's reduction removed from gppu/tui/config_editor.py, as it was last


# .. from fec31bb
def find_direct_includes(yaml_path: Path) -> list[Path]:
    """Return include targets declared in *yaml_path*."""
    includes: list[Path] = []
    base_dir = yaml_path.parent
    for line in yaml_path.read_text(encoding='utf-8').splitlines():
        match = INCLUDE_RE.search(line)
        if not match:
            continue
        raw_path = match.group('path').strip().strip('"\'')
        include_path = Path(raw_path)
        if not include_path.is_absolute():
            include_path = (base_dir / include_path).resolve()
        includes.append(include_path)
    return includes


# .. from gppu/v3.7.9
class LoaderWithInclude(yaml.SafeLoader):
    """YAML loader that tolerates !include tags for syntax validation."""
