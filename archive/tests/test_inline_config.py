# .. archived 2026-11-22: what gppu's reduction removed from tests/test_inline_config.py, as it was last


# .. from gppu/v3.7.9
def test_python_script_reads_its_manifest_global_without_running(tmp_path):
    assert dict_from_yml(python_script(tmp_path)) == EXPECTED


# .. from gppu/v3.7.9
def test_python_script_reads_as_its_yaml_file_would(tmp_path):
    (tmp_path / 'example.yaml').write_text(MANIFEST, encoding='utf-8')
    assert dict_from_yml(python_script(tmp_path)) == dict_from_yml(tmp_path / 'example.yaml')


# .. from gppu/v3.7.9
def test_inline_config_includes_beside_the_script(tmp_path):
    (tmp_path / 'rules.yaml').write_text('- disk\n', encoding='utf-8')
    script = python_script(tmp_path, '\n  manifest: {name: example}\n  rules: !include rules.yaml\n')
    assert dict_from_yml(script)['rules'] == ['disk']


# .. from gppu/v3.7.9
def test_python_script_without_manifest_raises(tmp_path):
    script = tmp_path / 'plain.py'
    script.write_text('"""A docstring."""\n\n"""\n  manifest: {name: bare}\n"""\nCONFIG = "manifest: {}"\n', encoding='utf-8')
    with pytest.raises(ValueError, match='no inline configuration'):
        inline_config(script)


# .. from gppu/v3.7.9
def test_cmd_reads_only_the_lines_it_opens_with(tmp_path):
    script = tmp_path / 'mapper.cmd'
    script.write_text('::manifest:\n::  name: mapper\n::  platform: [W11]\n\nnet use \\\\yellow /u:admin secret\n'
                      '::later: not read\n', encoding='utf-8')
    assert inline_config(script) == 'manifest:\n  name: mapper\n  platform: [W11]\n'
    assert dict_from_yml(script) == {'manifest': {'name': 'mapper', 'platform': ['W11']}}


# .. from gppu/v3.7.9
def test_ps1_reads_the_notes_of_its_opening_block(tmp_path):
    script = tmp_path / 'tray-control.ps1'
    script.write_text('<#\n.SYNOPSIS\n  Promote the icons\n.NOTES\n  manifest:\n    name: tray-control\n.EXAMPLE\n'
                      '  ./tray-control.ps1\n#>\n\nStop-Process -Name explorer\n', encoding='utf-8')
    assert dict_from_yml(script) == {'manifest': {'name': 'tray-control'}}


# .. from gppu/v3.7.9
def test_script_without_its_opening_block_raises(tmp_path):
    cmd, ps1 = tmp_path / 'plain.cmd', tmp_path / 'plain.ps1'
    cmd.write_text('@echo off\n::manifest: {name: late}\n', encoding='utf-8')
    ps1.write_text('Write-Host hi\n<#\n.NOTES\n  manifest: {name: late}\n#>\n', encoding='utf-8')
    for script in (cmd, ps1):
        with pytest.raises(ValueError, match='no inline configuration'):
            inline_config(script)


# .. from gppu/v3.7.9
def test_app_given_the_script_reads_its_inline_config(tmp_path):
    class Example(App):
        pass

    app = Example(config=python_script(tmp_path))
    assert app.my('keep_hours') == 24
    assert app.my('manifest/name') == 'example'


# .. archived 2026-11-22 from tests/test_inline_config.py: an App given a script file read its MANIFEST; an app now passes its MANIFEST text as its configuration, and the launcher reads a script's manifest

def test_app_given_the_script_reads_its_manifest_without_running_it(tmp_path):
    class Example(App):
        pass

    app = Example(config=python_script(tmp_path))
    assert {key: app[key] for key in EXPECTED} == EXPECTED
    assert app.my('keep_hours') == 24
    assert app.my('manifest/name') == 'example'


def test_script_reads_as_its_yaml_file_would(tmp_path):
    (tmp_path / 'example.yaml').write_text(MANIFEST, encoding='utf-8')
    app = App(config=python_script(tmp_path))
    assert {key: app[key] for key in EXPECTED} == dict_from_yml(tmp_path / 'example.yaml')


def test_command_line_goes_over_the_manifest(tmp_path):
    assert App(config=str(python_script(tmp_path)), argv=['--keep_hours', '48']).my('keep_hours') == '48'


def test_raw_manifest_keeps_its_backslashes(tmp_path):
    script = tmp_path / 'raw.py'
    script.write_text('MANIFEST = r"""\n  folder: \'D:\\Work\'\n"""\n', encoding='utf-8')
    assert App(config=script).my('folder') == 'D:\\Work'


def test_script_without_a_manifest_assignment_raises(tmp_path):
    script = tmp_path / 'plain.py'
    script.write_text('"""A docstring."""\n\n"""\n  manifest: {name: bare}\n"""\nCONFIG = "manifest: {}"\n', encoding='utf-8')
    with pytest.raises(ValueError, match='no MANIFEST in its first 4 KB'):
        App(config=script)


def test_manifest_below_the_first_4_kb_is_not_read(tmp_path):
    script = tmp_path / 'late.py'
    script.write_text('#' * 4096 + '\nMANIFEST = """\n  manifest: {name: late}\n"""\n', encoding='utf-8')
    with pytest.raises(ValueError, match='no MANIFEST in its first 4 KB'):
        App(config=script)
