"""The pages mkdocs-gen-files makes at build time out of the code: every class of gppu in one diagram, with the packages and what
they import, and a page per module of gppu, its class diagram over its reference. pyreverse (pylint) draws the diagrams from the code
as Mermaid; mkdocstrings writes the reference from the docstrings. The home page comes from docs_dir."""
import ast
import re
import subprocess
import tempfile
from pathlib import Path

import mkdocs_gen_files

ROOT = Path(__file__).parents[1]   # the repository, beside docs/
PACKAGE = ROOT / 'gppu'
METHOD = re.compile(r'\s+\w+\(')   # pyreverse's line of a method, name(args) return; an attribute's is name : type


def pyreverse(target: str, project: str, *options: str) -> tuple[str, str]:
    """pyreverse's class and package diagrams of `target`, a module's file or a package, as Mermaid; a module's file has no package
    diagram."""
    with tempfile.TemporaryDirectory() as out:
        subprocess.run(['pyreverse', '-o', 'mmd', '--colorized', *options, '-p', project, '-d', out, target], cwd=ROOT, check=True)
        classes = Path(out, f'classes_{project}.mmd').read_text()
        drawn = Path(out, f'packages_{project}.mmd')
        packages = drawn.read_text() if drawn.exists() else ''
    # Mermaid reads a member holding a parenthesis as a method, so an attribute's type that holds one (Span.bounds, Literal['[]', '[)'])
    # has it as Mermaid's entity code, which it draws as the parenthesis
    classes = ''.join(line if METHOD.match(line) else line.replace('(', '#40;').replace(')', '#41;') for line in classes.splitlines(True))
    return classes.replace('classDiagram\n', 'classDiagram\n  direction LR\n', 1), packages


def modules():
    """Every module of gppu as (its name, its file): a file whose name is not a module's (fs-dumpoftext.py) is no module."""
    for source in sorted(PACKAGE.rglob('*.py')):
        parts = source.relative_to(ROOT).with_suffix('').parts
        if all(p.isidentifier() for p in parts):
            yield '.'.join(parts[:-1] if parts[-1] == '__init__' else parts), source


def defines(source: Path) -> bool:
    """Whether a module defines a class or a function of its own, rather than only gathering others' as a package does."""
    return any(isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.parse(source.read_text(encoding='utf-8')).body)


skipped = [str(s.relative_to(PACKAGE)) for s in PACKAGE.rglob('*.py') if s not in dict((s, n) for n, s in modules())]
classes, packages = pyreverse('gppu', 'gppu', *(f'--ignore={Path(s).name}' for s in skipped))
with mkdocs_gen_files.open('classes.md', 'w') as f:
    f.write(f'# Every class\n\nEvery class of gppu and what it is made from.\n\n```mermaid\n{classes}```\n\n'
            f'## Packages\n\nEvery module of gppu and the modules it imports.\n\n```mermaid\n{packages}```\n')

for name, source in modules():
    page = '/'.join(name.split('.')[1:]) or 'gppu'
    page += '/index.md' if source.stem == '__init__' and name != 'gppu' else '.md'
    text = source.read_text(encoding='utf-8')
    drawn = f'```mermaid\n{pyreverse(str(source.relative_to(ROOT)), source.stem, "-a", "1")[0]}```\n\n' if 'class ' in text else ''
    options = '' if defines(source) else '\n    options:\n      members: false\n'   # a package's own docstring, its members on their pages
    with mkdocs_gen_files.open(page, 'w') as f:
        f.write(f'# {name}\n\n{drawn}::: {name}{options}\n')
