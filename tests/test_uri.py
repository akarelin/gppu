"""gppu/fs's y2uri against the URI convention (_Standards/Conventions/URI.md): every form it lists comes back as written, and fsspec
opens what it addresses."""
import zipfile

import fsspec
import pytest

import gppu.fs.gppufs  # registers gppu
from gppu.fs import y2uri

FORMS = ['file:///D:/TextLake', 'local:///D:/TextLake', 'm365://karelin/sites/x/doc.docx', 'git://github.com/akarelin/gppu',
         'lake://timeseries/2026/Sessions/10/cc/a.jsonl', 'uuid:10020100-0000-0000-0193-0000aaaa0000', 'gppu::file:///D:/TextLake',
         'gppu::smb://s1/Lake', 'zip://member.txt::file:///D:/bundle.zip', 'rar://member.txt::file:///D:/bundle.rar',
         'file:///D:/a.md#heading', 'file:///D:/a.md#:~:text=start', 'file:///D:/a.md#:~:text=start,end',
         'file:///D:/a.md#:~:text=prefix-,start,end,-suffix', 'file:///D:/a.md#heading:~:text=start,end', 'file:///D:/a.txt#line=10,20',
         'file:///D:/a.txt#char=120,480', 'file:///D:/a.m4a#t=95,140', 'file:///D:/a.m4a#t=npt:95,140', 'file:///D:/My%20Docs/a%23b.md',
         'work://', 'file://alex-pc/D:/Dev', 'D:/TextLake']


@pytest.mark.parametrize('form', FORMS)
def test_every_form_comes_back_as_written(form):
    expected = 'null://D:/TextLake' if form == 'D:/TextLake' else form   # no scheme reads as gppu's y2uri reads it
    assert str(y2uri(form)) == expected


def test_scheme_authority_path_and_target():
    u = y2uri('uuid:10020100-0000-0000-0193-0000aaaa0000')
    assert (u.scheme, u.authority, str(u.path)) == ('uuid', None, '10020100-0000-0000-0193-0000aaaa0000')
    u = y2uri('file:///D:/TextLake')
    assert (u.scheme, u.authority, str(u.path)) == ('file', '', 'D:/TextLake')
    u = y2uri('gppu::file:///D:/TextLake')
    assert (u.scheme, str(u.target)) == ('gppu', 'file:///D:/TextLake')
    u = y2uri('zip://member.txt::file:///D:/bundle.zip')
    assert (u.scheme, u.authority, str(u.target)) == ('zip', 'member.txt', 'file:///D:/bundle.zip')


def test_a_path_joins_below_the_uri():
    assert str(y2uri('file:///D:/TextLake') / 'a/b.md') == 'file:///D:/TextLake/a/b.md'
    assert str(y2uri('work://') / 'x') == 'work://x'
    assert str(y2uri('lake://timeseries') / '2026') == 'lake://timeseries/2026'


def test_the_fragment_selects():
    assert y2uri('file:///D:/a.md#heading').selection == {'anchor': 'heading'}
    assert y2uri('file:///D:/a.txt#line=10,20').selection == {'line': (10, 20)}
    assert y2uri('file:///D:/a.txt#char=120,480').selection == {'char': (120, 480)}
    assert y2uri('file:///D:/a.m4a#t=npt:95,140').selection == {'t': (95.0, 140.0)}
    assert y2uri('file:///D:/a.md#heading:~:text=start,end').selection == {
        'anchor': 'heading', 'text': [{'prefix': None, 'start': 'start', 'end': 'end', 'suffix': None}]}
    assert y2uri('file:///D:/a.md#:~:text=prefix-,start,end,-suffix').selection == {
        'text': [{'prefix': 'prefix', 'start': 'start', 'end': 'end', 'suffix': 'suffix'}]}
    assert y2uri('file:///D:/a.md').selection == {}


def test_fsspec_opens_what_it_addresses(tmp_path):
    bundle = tmp_path / 'bundle.zip'
    with zipfile.ZipFile(bundle, 'w') as z:
        z.writestr('member.txt', 'in the bundle')
    (tmp_path / 'a.txt').write_text('a file')
    with fsspec.open(str(y2uri(f'zip://member.txt::{bundle.as_uri()}')), 'rt') as f:
        assert f.read() == 'in the bundle'
    with fsspec.open(str(y2uri(f'gppu::{(tmp_path / "a.txt").as_uri()}')), 'rt') as f:
        assert f.read() == 'a file'
    with fsspec.open(str(y2uri((tmp_path / 'a.txt').as_uri())), 'rt') as f:
        assert f.read() == 'a file'
