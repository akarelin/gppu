"""The pages mkdocs-gen-files makes at build time out of gppu's code: a page per module, its reference, which mkdocstrings writes from
the docstrings; on the home page, the version of gppu they document and what the package `gppu` exports, by its own import lines;
graph.html, graphify's graph of every class and function of gppu, read from the code without a model and grouped by gppu's modules;
and under guides/, gppu's own documents, README first, as they are in the repository."""
import ast
import json
import os
import posixpath
import re
import subprocess
import tempfile
from pathlib import Path, PurePath

ROOT = Path(__file__).parents[1]   # the repository, beside docs/
PACKAGE = ROOT / 'gppu'
WRITTEN = ROOT / 'docs' / 'written'   # what Claude Code wrote of each module (docs/written.py), at the top of its page
GUIDES = 'guides'                  # where the site carries gppu's documents, laid out as in the repository, so their links hold
LINK = re.compile(r'(?P<lead>\]\(|href="|src=")(?P<target>[^)"#\s]+)')   # a document's links, Markdown's and its HTML's


def modules():
    """Every module of gppu as (its name, its file): a file whose name is not a module's (fs-dumpoftext.py) is no module."""
    for source in sorted(PACKAGE.rglob('*.py')):
        parts = source.relative_to(ROOT).with_suffix('').parts
        if all(p.isidentifier() for p in parts):
            yield '.'.join(parts[:-1] if parts[-1] == '__init__' else parts), source


def defines(source: Path) -> bool:
    """Whether a module defines a class or a function of its own, rather than only gathering others' as a package does."""
    return any(isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.parse(source.read_text(encoding='utf-8')).body)


def defined_in(module: str, name: str) -> str:
    """The module that defines `name`, following the imports from `module` it passes through: iot passes on app's EventLoopBridge."""
    source = dict(modules())[module]
    for node in ast.parse(source.read_text(encoding='utf-8')).body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return module
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return module
        if isinstance(node, ast.ImportFrom) and node.level and any(a.name == name for a in node.names):
            base = module if source.stem == '__init__' else module.rpartition('.')[0]
            for _ in range(node.level - 1):
                base = base.rpartition('.')[0]
            return defined_in(f'{base}.{node.module}' if node.module else base, name)
    return module


def exports(name: str, source: Path) -> str:
    """What a package gathers from its modules, by its own `from .x import` lines and the comments that group them, each name linked
    to where it is defined; a private name has no page, so it is named without a link."""
    lines, text = source.read_text(encoding='utf-8').splitlines(), ['## What it exports', '']
    for node in ast.parse('\n'.join(lines)).body:
        if not (isinstance(node, ast.ImportFrom) and node.level == 1):
            continue
        module = f'{name}.{node.module}'
        text += [f'### From {module}', '']
        names = {a.name for a in node.names}
        group, items = None, []
        for line in lines[node.lineno - 1:node.end_lineno]:
            code, _, comment = line.partition('#')
            if comment.strip() and not code.strip():
                if items:
                    text += [f'- {group + ": " if group else ""}{", ".join(items)}']
                group, items = comment.strip(), []
            for word in re.findall(r'\b\w+\b', code):
                if word in names:
                    names.discard(word)
                    items.append(f'`{word}`' if word.startswith('_') else f'[`{word}`][{defined_in(module, word)}.{word}]')
        if items:
            text += [f'- {group + ": " if group else ""}{", ".join(items)}']
        text += ['']
    return '\n'.join(text)


def graph() -> str:
    """graphify's graph of gppu's code as one page: graphify reads the code (`update`, no model), each node goes into the group of
    the gppu module it is in, a package's modules one group (gppu.tui), and graphify draws it (`export html`). Left out: the files
    that are no module, and the names gppu only uses (Any, Path), which graphify makes nodes of with an id of their file's, fs_py_any."""
    skipped = {s.name for s in PACKAGE.rglob('*.py') if s not in {f for _, f in modules()}}
    with tempfile.TemporaryDirectory() as out:
        env = os.environ | {'GRAPHIFY_OUT': out, 'PYTHONIOENCODING': 'utf-8'}
        subprocess.run(['graphify', 'update', str(PACKAGE)], env=env, check=True, capture_output=True)
        drawn = json.loads(Path(out, 'graph.json').read_text(encoding='utf-8'))
        kept = [n for n in drawn['nodes'] if '_py_' not in n['id'] and n.get('source_file', '').endswith('.py')
                and PurePath(n['source_file']).name not in skipped]
        groups = sorted({group(n) for n in kept})
        for n in kept:
            n['community'] = str(groups.index(group(n)))
        ids = {n['id'] for n in kept}
        drawn |= {'nodes': kept, 'links': [e for e in drawn['links'] if e['source'] in ids and e['target'] in ids]}
        Path(out, 'graph.json').write_text(json.dumps(drawn), encoding='utf-8')
        Path(out, 'labels.json').write_text(json.dumps(dict(enumerate(groups))), encoding='utf-8')
        subprocess.run(['graphify', 'export', 'html', '--graph', str(Path(out, 'graph.json')), '--labels', str(Path(out, 'labels.json'))],
                       env=env, check=True, capture_output=True)
        return Path(out, 'graph.html').read_text(encoding='utf-8')


def version() -> str:
    """The version of gppu the pages document: its release tag, gppu/v3.6.23, or the release before the code and how far past it
    the code is, gppu/v3.6.22-41-g8fb96fa."""
    return subprocess.run(['git', 'describe', '--tags', '--match', 'gppu/v*'], cwd=ROOT, check=True, capture_output=True,
                          text=True).stdout.strip()


def group(node: dict) -> str:
    """The gppu module a node is in: gppu.<module>, or gppu.<package> for a module in a package; the package's own __init__.py is gppu."""
    parts = PurePath(node['source_file']).with_suffix('').parts
    return 'gppu' if parts == ('__init__',) else 'gppu.' + parts[0]


def page(name: str, source: Path) -> str:
    """A module's page: gppu.tui.tree's is tui/tree.md, a package's the index.md of its folder, the package gppu's the home page."""
    return '/'.join(name.split('.')[1:] + (['index'] if source.stem == '__init__' else [])) + '.md'


def documents():
    """gppu's documents: README, the documents beside it and those in docs/; a plan, a 2Do or a handoff is work, not documentation."""
    for source in sorted([*ROOT.glob('*.md'), *(ROOT / 'docs').glob('*.md')]):
        if not source.name.startswith(('PLAN_', '2DO', 'HANDOFF_')):
            yield source.relative_to(ROOT).as_posix()


def relinked(document: str, published: set) -> str:
    """A document's text with each link to a file the site does not carry made into one that answers: gppu's code goes to its module's
    page, an image is copied beside the document, anything else (an example, a workflow, w11) goes to the file in the repository."""
    pages = {source.relative_to(ROOT).as_posix(): page(name, source) for name, source in modules()}
    here = posixpath.dirname(document)

    def relink(match):
        lead, target = match['lead'], match['target']
        file = posixpath.normpath(posixpath.join(here, target))
        if re.match(r'[a-z][a-z0-9+.-]*:|/', target) or file in published:
            return match[0]
        if file in pages:   # mkdocs turns a Markdown link to a page into the page's address; an HTML link is written as one
            return lead + posixpath.relpath(pages[file] if lead == '](' else pages[file][:-3] + '.html', posixpath.join(GUIDES, here))
        if PurePath(file).suffix in {'.svg', '.png', '.jpg', '.gif'}:
            with mkdocs_gen_files.open(f'{GUIDES}/{file}', 'wb') as f:
                f.write((ROOT / file).read_bytes())
            return match[0]
        return f'{lead}{mkdocs_gen_files.config.repo_url}/blob/master/{file}'

    return LINK.sub(relink, (ROOT / document).read_text(encoding='utf-8'))


def build():
    """Every page, made while mkdocs builds the site."""
    with mkdocs_gen_files.open('graph.html', 'w') as f:
        f.write(graph())

    for name, source in modules():
        if name == 'gppu':   # the package itself: its version, its docstring and what it exports, on the home page
            with mkdocs_gen_files.open('index.md', 'a') as f:
                f.write(f'\n**Version** {version()}\n\n::: gppu\n    options:\n      members: false\n      show_root_heading: false\n\n'
                        f'{exports(name, source)}\n')
            continue
        body = f'::: {name}\n' if defines(source) else (   # a package: its docstring and what it gathers, defined on its modules' pages
            f'::: {name}\n    options:\n      members: false\n      show_root_heading: false\n\n{exports(name, source)}\n')
        written = WRITTEN / f'{name}.md'
        description = written.read_text(encoding='utf-8').split('\n', 1)[1] + '\n' if written.exists() else ''
        with mkdocs_gen_files.open(page(name, source), 'w') as f:
            f.write(f'# {name}\n\n{description}{body}')

    published = set(documents())
    for document in published:
        with mkdocs_gen_files.open(f'{GUIDES}/{document}', 'w') as f:
            f.write(relinked(document, published))


if __name__ != 'docs_pages':   # run by mkdocs-gen-files; docs/written.py imports it for modules() alone
    import mkdocs_gen_files
    build()
