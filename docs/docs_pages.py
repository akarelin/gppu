"""The pages mkdocs-gen-files makes at build time out of the code: one per module of gppu.ld, its reference written by mkdocstrings
from the module's docstrings, and on the package's page its class diagram, which pyreverse (pylint) draws from the code as Mermaid.
The home page comes from docs_dir."""
import re
import subprocess
import tempfile
from pathlib import Path

import mkdocs_gen_files

ROOT = Path(__file__).parents[1]   # the repository, beside docs/
METHOD = re.compile(r'\s+\w+\(')   # pyreverse's line of a method, name(args) return; an attribute's is name : type

with tempfile.TemporaryDirectory() as out:
    subprocess.run(['pyreverse', '-o', 'mmd', '--colorized', '-p', 'ld', '-d', out, 'gppu.ld'], cwd=ROOT, check=True)
    classes = Path(out, 'classes_ld.mmd').read_text()
# Mermaid reads a member holding a parenthesis as a method, so an attribute's type that holds one (Span.bounds, Literal['[]', '[)'])
# has it as Mermaid's entity code, which it draws as the parenthesis
classes = ''.join(line if METHOD.match(line) else line.replace('(', '#40;').replace(')', '#41;') for line in classes.splitlines(True))
classes = classes.replace('classDiagram\n', 'classDiagram\n  direction LR\n', 1)

with mkdocs_gen_files.open('ld/index.md', 'w') as f:
    f.write(f'# gppu.ld\n\n```mermaid\n{classes}```\n\n::: gppu.ld\n')
for module in sorted((ROOT / 'gppu' / 'ld').glob('*.py')):
    if module.stem != '__init__':
        with mkdocs_gen_files.open(f'ld/{module.stem}.md', 'w') as f:
            f.write(f'# gppu.ld.{module.stem}\n\n::: gppu.ld.{module.stem}\n')
