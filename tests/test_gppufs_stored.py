"""GppuFileSystem.stored: what the index holds of a path, read without touching the file system."""
from gppu.fs import GppuFileSystem


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
