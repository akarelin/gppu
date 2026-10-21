"""The parts of gppu's documentation a language model writes: each module's description, from docs/prompts/module.md and the
module's source, by Claude Code on Alex's subscription, into docs/written/, where docs_pages.py puts it at the top of the module's
page. It runs on a PC where Claude Code is signed in, not in the documentation build, and writes a module's description again only
when the module or the template has changed since it was written: the description's first line names the git blob of each.

  python docs/written.py                 every module whose description is out of date
  python docs/written.py gppu.handlers   these modules, whether or not"""
import subprocess
import sys
from pathlib import Path

from docs_pages import ROOT, modules

MODEL = 'haiku'                            # Claude Code's model for the descriptions
TEMPLATE = Path(__file__).parent / 'prompts' / 'module.md'
WRITTEN = Path(__file__).parent / 'written'


def blob(path: Path) -> str:
    """git's name for a file's content."""
    return subprocess.run(['git', 'hash-object', str(path)], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def heading(name: str, source: Path) -> str:
    """The first line of a description: what it was written from, which says when it is out of date."""
    return (f'<!-- written by Claude Code ({MODEL}) from docs/prompts/module.md {blob(TEMPLATE)} and '
            f'{source.relative_to(ROOT).as_posix()} {blob(source)} -->')


def write(name: str, source: Path) -> Path:
    """A module's description, written by Claude Code from the template and the module's source."""
    prompt = TEMPLATE.read_text(encoding='utf-8').format(module=name, path=source.relative_to(ROOT).as_posix(),
                                                         source=source.read_text(encoding='utf-8'))
    answer = subprocess.run(['claude', '-p', '--model', MODEL, '--output-format', 'text', '--tools', '', '--no-session-persistence'],
                            input=prompt, cwd=ROOT, check=True, capture_output=True, text=True, encoding='utf-8')
    target = WRITTEN / f'{name}.md'
    target.parent.mkdir(exist_ok=True)
    target.write_text(f'{heading(name, source)}\n{answer.stdout.strip()}\n', encoding='utf-8')
    return target


def stale(name: str, source: Path) -> bool:
    target = WRITTEN / f'{name}.md'
    return not target.exists() or target.read_text(encoding='utf-8').split('\n', 1)[0] != heading(name, source)


if __name__ == '__main__':
    every = dict(modules())
    for name in sys.argv[1:] or [name for name, source in every.items() if stale(name, source)]:
        print(write(name, every[name]).relative_to(ROOT))
