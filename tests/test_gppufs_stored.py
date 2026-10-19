"""GppuFileSystem.stored, and ls with live=False: what the index holds, read without touching the file system."""
import zipfile

from gppu.fs import GppuFileSystem


def test_ls_not_live_reads_the_index_alone(tmp_path):
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'a.txt').write_text('a')
    with zipfile.ZipFile(tmp_path / 'arch.zip', 'w') as z:
        z.writestr('in/m.txt', 'member')
    fs = GppuFileSystem(tmp_path)
    fs.ls()   # the root listed: sub and arch.zip identified, neither listed
    index = next(tmp_path.glob('.*.gppufs.sqlite'))
    before = index.read_bytes()
    names = [row['gppu']['name'] for row in fs.ls(recurse=True, live=False)]
    assert sorted(names) == ['arch.zip', 'sub'], names   # the archive not opened, the folder not read
    assert fs.ls('sub', live=False) == [] and fs.ls('nowhere', live=False) == []   # what the index never saw lists nothing
    assert index.read_bytes() == before   # nothing written
    assert fs.stored('arch.zip')[1] is None


def test_stored_answers_from_the_index_alone(tmp_path):
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'a.txt').write_text('a')
    fs = GppuFileSystem(tmp_path)
    assert fs.stored() is None   # nothing listed, nothing read
    fs.ls()
    root, listing = fs.stored()
    assert root['type'] == 'directory' and [child['path'] for child in listing] == ['sub']
    sub, below = fs.stored('sub')
    assert sub['gppu']['name'] == 'sub' and below is None   # sub was identified by its parent's listing, not listed itself
    (tmp_path / 'sub' / 'b.txt').write_text('b')
    assert fs.stored('sub/b.txt') is None   # stored never reads the folder
    fs.ls('sub')
    assert sorted(child['path'] for child in fs.stored('sub')[1]) == ['sub/a.txt', 'sub/b.txt']
