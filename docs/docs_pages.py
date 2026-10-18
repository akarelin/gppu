"""The pages mkdocs-gen-files makes at build time out of the code: one per module of gppu.ld, its class diagram, which pyreverse (pylint)
draws from the code as Mermaid, over its reference, which mkdocstrings writes from the module's docstrings. The home page comes from
docs_dir."""
import re
import subprocess
import tempfile
from pathlib import Path

import mkdocs_gen_files

ROOT = Path(__file__).parents[1]   # the repository, beside docs/
METHOD = re.compile(r'\s+\w+\(')   # pyreverse's line of a method, name(args) return; an attribute's is name : type


def diagram(source: Path) -> str:
    """The module's classes and those they are made from (`-a 1`), coloured by module, laid out left to right, so that a module's
    classes stack instead of standing in one row too wide to read."""
    with tempfile.TemporaryDirectory() as out:
        subprocess.run(['pyreverse', '-o', 'mmd', '--colorized', '-a', '1', '-p', source.stem, '-d', out, source.relative_to(ROOT)],
                       cwd=ROOT, check=True)
        classes = Path(out, f'classes_{source.stem}.mmd').read_text()
    # Mermaid reads a member holding a parenthesis as a method, so an attribute's type that holds one (Span.bounds, Literal['[]', '[)'])
    # has it as Mermaid's entity code, which it draws as the parenthesis
    classes = ''.join(line if METHOD.match(line) else line.replace('(', '#40;').replace(')', '#41;') for line in classes.splitlines(True))
    return classes.replace('classDiagram\n', 'classDiagram\n  direction LR\n', 1)


for source in sorted((ROOT / 'gppu' / 'ld').glob('*.py')):
    name, page = ('gppu.ld', 'ld/index.md') if source.stem == '__init__' else (f'gppu.ld.{source.stem}', f'ld/{source.stem}.md')
    with mkdocs_gen_files.open(page, 'w') as f:
        f.write(f'# {name}\n\n```mermaid\n{diagram(source)}```\n\n::: {name}\n')
