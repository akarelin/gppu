"""The parts of gppu's documentation a language model writes, by Claude Code on Alex's subscription, into docs/written/: each
module's description, from docs/prompts/module.md and the module's source, which docs_pages.py puts at the top of the module's page,
and what graphify's model reads in gppu's documentation, which docs_pages.py joins to the graph of gppu's code. It runs on a PC
where Claude Code is signed in, not in the documentation build, and reads gppu as its last commit has it, not edits in progress, and
its own descriptions as it has just written them. A
module's description is written again only when the module or the template has changed since it was written: the description's first
line names the git blob of each. graphify keeps what its model
read under CACHE and reads a document again only when it has changed.

  python docs/written.py                 every module whose description is out of date, then the graph
  python docs/written.py gppu.fs.handlers   these modules, whether or not, then the graph"""
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from docs_pages import ROOT, WRITTEN, committed, corpus, modules
from gppu.fs import CACHE

MODEL = 'haiku'                            # Claude Code's model for the descriptions
TEMPLATE = Path(__file__).parent / 'prompts' / 'module.md'
GRAPH = CACHE / 'gppu-graph'               # graphify's corpus and what its model has read


def blob(path: Path) -> str:
    """git's name for a file's content in gppu's last commit."""
    return subprocess.run(['git', 'rev-parse', f'HEAD:{path.relative_to(ROOT).as_posix()}'], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def heading(name: str, source: Path) -> str:
    """The first line of a description: what it was written from, which says when it is out of date."""
    return (f'<!-- written by Claude Code ({MODEL}) from docs/prompts/module.md {blob(TEMPLATE)} and '
            f'{source.relative_to(ROOT).as_posix()} {blob(source)} -->')


def write(name: str, source: Path) -> Path:
    """A module's description, written by Claude Code from the template and the module's source."""
    prompt = committed(TEMPLATE).decode('utf-8').format(module=name, path=source.relative_to(ROOT).as_posix(),
                                                        source=committed(source).decode('utf-8'))
    answer = subprocess.run(['claude', '-p', '--model', MODEL, '--output-format', 'text', '--tools', '', '--no-session-persistence'],
                            input=prompt, cwd=ROOT, check=True, capture_output=True, text=True, encoding='utf-8')
    target = WRITTEN / f'{name}.md'
    target.parent.mkdir(exist_ok=True)
    target.write_text(f'{heading(name, source)}\n{answer.stdout.strip()}\n', encoding='utf-8', newline='\n')
    return target


def stale(name: str, source: Path) -> bool:
    target = WRITTEN / f'{name}.md'
    return not target.exists() or target.read_text(encoding='utf-8').split('\n', 1)[0] != heading(name, source)


def bare(label: str) -> str:
    """A name as the code and the model both write it: probe() is probe, and the model's Handler (base) Handler."""
    return re.sub(r'\s*\([^)]*\)$', '', label).removesuffix('()').strip()


def graph() -> Path:
    """What graphify's model reads in gppu's documentation: graphify reads gppu's code and its documentation, its model the
    documentation, and the nodes it read in the documents, with every link to or from them, are docs/written/graph.json. A class
    or a function the model names that the code defines once is the code's node, not one of its own."""
    env = os.environ | {'GRAPHIFY_CLAUDE_CLI_MODEL': MODEL, 'PYTHONIOENCODING': 'utf-8'}
    out = GRAPH / 'graphify-out'
    for previous in ('graph.json', 'manifest.json'):   # the graph is what the documents say now: graphify holds a changed
        (out / previous).unlink(missing_ok=True)       # document's new reading against its old one; its cache keeps the rest
    documentation = corpus(GRAPH / 'corpus', read=True, content=lambda path: path.read_bytes() if path.parent == WRITTEN else committed(path))
    subprocess.run(['uvx', '--python', '3.14', '--from', 'graphifyy', 'graphify', 'extract', str(documentation),
                    '--backend', 'claude-cli', '--out', str(GRAPH)], env=env, check=True)
    drawn = json.loads((out / 'graph.json').read_text(encoding='utf-8'))
    unread = {p.relative_to(documentation).as_posix() for p in documentation.rglob('*.md')} - {n['source_file'] for n in drawn['nodes']}
    if unread:
        raise RuntimeError(f'graphify read nothing of {sorted(unread)}')
    defined = defaultdict(set)
    for n in drawn['nodes']:
        if n['source_file'].endswith('.py'):
            defined[bare(n['label'])].add(n['id'])
    read = [n for n in drawn['nodes'] if n['source_file'].endswith('.md')]
    same = {n['id']: min(defined[bare(n['label'])]) for n in read if n['file_type'] == 'code' and len(defined[bare(n['label'])]) == 1}
    nodes = [n for n in read if n['id'] not in same]
    ids = {n['id'] for n in nodes}
    links = [e | {'source': same.get(e['source'], e['source']), 'target': same.get(e['target'], e['target'])} for e in drawn['links']]
    links = [e for e in links if (e['source'] in ids or e['target'] in ids) and e['source'] != e['target']]
    target = WRITTEN / 'graph.json'
    target.write_text(json.dumps({'nodes': nodes, 'links': links}, indent=1, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    return target


if __name__ == '__main__':
    every = dict(modules())
    for name in sys.argv[1:] or [name for name, source in every.items() if stale(name, source)]:
        print(write(name, every[name]).relative_to(ROOT))
    print(graph().relative_to(ROOT))
