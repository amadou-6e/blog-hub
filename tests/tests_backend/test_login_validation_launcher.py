import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import struct
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zlib

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('launcher', ROOT / 'scripts/run-login-validation.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def config(project):
    return {
        'services': {
            'tests': {'build': {'context': str(ROOT)}, 'image': 'shared:runtime',
                      'volumes': [{'type': 'volume', 'source': 'results', 'target': '/results'}]},
            'fixture': {'build': {'context': str(ROOT)}, 'image': 'shared:runtime'},
            'provision': {'image': 'shared:runtime'},
            'postgres': {'image': 'postgres@sha256:' + '1' * 64},
        },
        'volumes': {'results': {'name': project + '_results'}},
        'networks': {'validation': {'name': project + '_validation', 'internal': True}},
    }


@pytest.mark.parametrize('failure', [None, 'build', 'up', 'test', 'cp', 'down', 'interrupt', 'timeout', 'xml',
                                    'prepare', 'restart', 'health', 'after', 'runtime_mismatch', 'skipped'])
def test_lifecycle(tmp_path, failure):
    calls = []
    secret = 'PRIVATE-CREDENTIAL-MUST-NOT-LEAK'

    def run(self, args, **kwargs):
        calls.append(args)
        result = subprocess.CompletedProcess(args, 0, '')
        if args[:2] == ['git', 'rev-parse']:
            result.stdout = 'a' * 40
        elif args[:2] == ['git', 'status']:
            result.stdout = ' M dirty.py'
        elif 'config' in args:
            assert Path(args[args.index('--project-directory') + 1]) == ROOT / 'validation'
            assert Path(args[args.index('--env-file') + 1]).parent.parent == ROOT / 'tests/results'
            result.stdout = json.dumps(config(args[args.index('--project-name') + 1]))
        elif args[-1] == 'build':
            override = Path(args[args.index('-f', args.index('-f') + 1) + 1])
            services = json.loads(override.read_text())['services']
            assert services['tests']['image'] == services['provision']['image']
            assert services['tests']['image'].startswith('bloghub-login-')
            if failure == 'build':
                raise launcher.ValidationError(secret)
        elif 'up' in args:
            if failure == 'interrupt':
                raise KeyboardInterrupt
            if failure in {'up', 'timeout'}:
                raise launcher.ValidationError(secret)
        elif 'restart' in args:
            assert args[-5:] == ['restart', '--no-deps', 'backend', 'runner', 'skyvern']
            if failure == 'restart':
                raise launcher.ValidationError(secret)
        elif 'run' in args:
            assert '--detach' in args and '--no-deps' in args
            assert 'validation/test_restart.py::test_prepare_restart' in args or 'validation/test_restart.py::test_after_restart' in args
            result.stdout = ('d' if 'validation/test_restart.py::test_prepare_restart' in args else 'e') * 64
        elif 'exec' in args:
            result.stdout = json.dumps({'python': '3.12.8', 'patchright': '1.58.0',
                                        'playwright': '1.58.0', 'chromium_skyvern': '145.0.7632.6',
                                        'chromium_patchright': '144.0.0.0' if failure == 'runtime_mismatch' else '145.0.7632.6',
                                        'unexpected': secret, 'fastapi': secret})
        elif 'ps' in args:
            result.stdout = ('b' if args[-1] == 'tests' else 'f') * 64
        elif args[1:3] == ['image', 'inspect']:
            result.stdout = 'sha256:' + 'c' * 64
        elif args[1] == 'inspect':
            if args[-1] == 'f' * 64:
                result.stdout = json.dumps({'Status': 'exited' if failure == 'health' else 'running',
                                            'Health': {'Status': 'healthy'}})
            else:
                failed = (failure == 'test' and args[-1] == 'b' * 64 or
                          failure == 'prepare' and args[-1] == 'd' * 64 or
                          failure == 'after' and args[-1] == 'e' * 64)
                result.stdout = json.dumps({'Status': 'exited', 'ExitCode': int(failed),
                                            'OOMKilled': False, 'Error': secret})
        elif args[1] == 'cp':
            assert args[2] == 'b' * 64 + ':/results/.'
            if failure == 'cp':
                raise launcher.ValidationError(secret)
            else:
                xml = ('<testsuites><testsuite><properties><property value="' + secret + '"/></properties>'
                       '<testcase name="test_cancel_waiting" time="2"><system-out>' + secret +
                       '</system-out></testcase></testsuite></testsuites>')
                if failure == 'skipped':
                    xml = xml.replace('</testcase>', '<skipped message="missing prerequisite"/></testcase>')
                for name in launcher.JUNIT_REPORTS:
                    Path(args[3], name).write_text('<malformed' if failure == 'xml' else xml)
                Path(args[3], 'restart.json').write_text(json.dumps({
                    'status': 'connected', 'verifiedAt': '2026-09-07T12:00:00+00:00', 'secret': secret,
                }))
                Path(args[3], 'trace.zip').write_text(secret)
        elif 'down' in args:
            assert '--volumes' in args and '--remove-orphans' in args
            if failure == 'down':
                result.returncode = 1
        return result

    output = io.StringIO()
    with patch.object(launcher.Commands, 'run', run), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        status = launcher.main(['--docker', 'mock-docker', '--results-dir', str(tmp_path)])
    assert status == (130 if failure == 'interrupt' else 1 if failure else 0)
    assert any('down' in args for args in calls)
    assert any(args[1:3] == ['image', 'rm'] for args in calls)
    assert not any('prune' in args for args in calls)
    reports = list(tmp_path.glob('*/metadata.json'))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text())
    assert report['dirty'] is True
    assert report['revision'] == 'a' * 40
    assert report['image_ids']['tests'] == 'sha256:' + 'c' * 64
    if failure is None:
        assert report['phase_exit_codes'] == {'login': 0, 'restart_prepare': 0, 'restart_after': 0}
        assert report['component_versions']['skyvern']['chromium_skyvern'] == '145.0.7632.6'
        assert report['component_versions']['runner']['fastapi'] is None
        assert len(report['junit_reports']) == 3
    if failure == 'runtime_mismatch':
        assert report['error_type'] == 'BrowserRuntimeMismatch'
        assert launcher.BrowserRuntimeMismatch.message in output.getvalue()
        assert not any('restart' in args for args in calls)
    assert not list(tmp_path.rglob('*.zip'))
    assert secret not in output.getvalue()
    for path in tmp_path.rglob('*'):
        if path.is_file():
            assert secret not in path.read_text()


def test_environment_ignores_personal_compose_and_provider_settings():
    with patch.dict(launcher.os.environ, {'COMPOSE_FILE': 'personal.yml', 'COMPOSE_PROJECT_NAME': 'personal',
                    'SKYVERN_API_KEY': 'secret', 'OPENAI_API_KEY': 'secret', 'DOCKER_CONTEXT': 'desktop'}):
        env = launcher.environment()
    assert 'COMPOSE_FILE' not in env and 'COMPOSE_PROJECT_NAME' not in env
    assert 'SKYVERN_API_KEY' not in env and 'OPENAI_API_KEY' not in env
    assert env['COMPOSE_DISABLE_ENV_FILE'] == '1'
    assert env['DOCKER_CONTEXT'] == 'desktop'


@pytest.mark.parametrize('component,key,value', [
    ('runner', 'patchright', None), ('skyvern', 'patchright', None),
    ('runner', 'chromium_patchright', None), ('skyvern', 'chromium_skyvern', None),
    ('skyvern', 'patchright', '1.50.0'), ('skyvern', 'chromium_skyvern', '132.0.0.0'),
])
def test_browser_runtime_requires_matching_known_versions(component, key, value):
    versions = {'runner': {'patchright': '1.58.0', 'chromium_patchright': '145.0.7632.6'},
                'skyvern': {'patchright': '1.58.0', 'chromium_skyvern': '145.0.7632.6'}}
    launcher.validate_browser_runtime(versions)
    versions[component][key] = value
    with pytest.raises(launcher.BrowserRuntimeMismatch, match='Browser runtime mismatch'):
        launcher.validate_browser_runtime(versions)


@pytest.mark.parametrize('setting,value', [('ports', ['8000:8000']), ('container_name', 'personal'),
    ('network_mode', 'host'), ('privileged', True), ('volumes', [{'type': 'bind'}])])
def test_refuses_unsafe_services(setting, value):
    document = config('owned')
    document['services']['tests'][setting] = value
    with pytest.raises(launcher.ValidationError):
        launcher.validate_isolation(document)


def test_report_drops_all_untrusted_text(tmp_path):
    source = tmp_path / 'raw.xml'
    target = tmp_path / 'safe.xml'
    source.write_text('<testsuite name="secret"><testcase name="test_secret[param]" time="NaN" secret="value">'
                      '<failure message="secret">secret</failure><system-err>secret</system-err></testcase></testsuite>')
    counts = launcher.sanitized_junit(source, target)
    assert counts == dict(tests=1, failures=1, errors=0, skipped=0)
    assert 'secret' not in target.read_text()
    assert 'redacted-test' in target.read_text()


def test_junit_keeps_only_exception_type_not_query_or_credential(tmp_path):
    source = tmp_path / 'raw.xml'
    target = tmp_path / 'safe.xml'
    source.write_text('<testsuite><testcase name="test_cancel_waiting"><failure type="httpx.HTTPStatusError" '
                      'message="https://fixture.test/account?apikey=PRIVATE-KEY">'
                      'Traceback https://identity.test/authorize?code=PRIVATE-CODE</failure></testcase></testsuite>')
    launcher.sanitized_junit(source, target)
    safe = target.read_text()
    assert 'HTTPStatusError' in safe
    assert 'PRIVATE' not in safe and 'https://' not in safe and 'apikey' not in safe


@pytest.mark.parametrize('tag', ['failure', 'error'])
def test_junit_retains_only_allowlisted_traceback_locations(tmp_path, tag):
    source, target = tmp_path / 'raw.xml', tmp_path / 'safe.xml'
    suite = ET.Element('testsuite')
    case = ET.SubElement(suite, 'testcase', name='test_cancel_waiting')
    problem = ET.SubElement(case, tag, type='AssertionError', message='apikey=PRIVATE-KEY')
    problem.text = '\n'.join([
        '    assert response == "PRIVATE-VALUE"',
        'validation/test_login.py:114: AssertionError: token=PRIVATE-KEY',
        ' /app/validation/test_restart.py:43: in test_after_restart',
        'validation/test_login.py:114: duplicate frame',
        'https://fixture.test/validation/test_login.py:999?apikey=PRIVATE-KEY',
        'validation/test_login.py:888?code=PRIVATE-CODE',
        'validation/test_login.py:777SECRET',
        'validation/test_login.py.bak:666:',
        'validation/test_other.py:555:',
        '/private/credentials.py:444:',
        'E AssertionError: https://identity.test/authorize?code=PRIVATE-CODE',
    ])
    ET.ElementTree(suite).write(source, encoding='utf-8')
    launcher.sanitized_junit(source, target)
    safe = ET.parse(target).find(f'testcase/{tag}')
    assert safe.get('type') == 'AssertionError'
    assert safe.text == 'validation/test_login.py:114\nvalidation/test_restart.py:43'
    rendered = target.read_text()
    for sensitive in ('PRIVATE', 'SECRET', 'https://', 'apikey', 'assert response',
                      'test_other', 'credentials.py', '999', '888', '777', '666', '555', '444'):
        assert sensitive not in rendered


def test_restart_json_allowlists_status_and_timestamp(tmp_path):
    source = tmp_path / 'raw.json'
    target = tmp_path / 'safe.json'
    source.write_text(json.dumps({'status': 'connected', 'verifiedAt': '2026-09-07T12:00:00.123Z',
                                 'apikey': 'SECRET', 'url': 'https://fixture.test/?code=SECRET'}))
    assert launcher.sanitized_restart(source, target) == {
        'status': 'connected', 'verifiedAt': '2026-09-07T12:00:00.123Z',
    }
    assert 'SECRET' not in target.read_text()


@pytest.mark.parametrize('value', [[], {}, {'status': 'connected', 'verifiedAt': 'SECRET'},
                                  {'status': 'SECRET', 'verifiedAt': '2026-09-07T12:00:00Z'}])
def test_restart_json_fails_closed(tmp_path, value):
    source = tmp_path / 'raw.json'
    source.write_text(json.dumps(value))
    with pytest.raises(launcher.ValidationError):
        launcher.sanitized_restart(source, tmp_path / 'safe.json')


def png(width=1, height=1, text=False):
    def chunk(name, body):
        return struct.pack('>I', len(body)) + name + body + struct.pack('>I', zlib.crc32(name + body))
    header = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
    ancillary = chunk(b'tEXt', b'Comment\x00SECRET') if text else b''
    return b'\x89PNG\r\n\x1a\n' + header + ancillary + chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff')) + chunk(b'IEND', b'')


def test_screenshots_are_bounded_and_allowlisted_without_text_metadata(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir()
    target.mkdir()
    (source / 'login-confirmation.png').write_bytes(png())
    (source / 'connected-after-restart.png').write_bytes(png(text=True))
    (source / 'test_cancel_waiting-tab-0.png').write_bytes(png())
    (source / 'test_cancel_waiting-tab-1.png').write_bytes(png(width=99999))
    (source / 'test_cancel_waiting-tab-2.png').write_bytes(png() + b'SECRET')
    (source / 'untrusted-secret.png').write_bytes(png())
    (source / 'trace.zip').write_bytes(b'SECRET')
    assert launcher.collect_screenshots(source, target) == ['login-confirmation.png', 'test_cancel_waiting-tab-0.png']
    assert len(list(target.iterdir())) == 2


@pytest.mark.parametrize('xml', ['<testsuite/>', '<!DOCTYPE x><testsuite/>', '<!ENTITY x "secret"><x/>', '<broken'])
def test_invalid_report_fails_closed(tmp_path, xml):
    source = tmp_path / 'raw.xml'
    source.write_text(xml)
    with pytest.raises(launcher.ValidationError):
        launcher.sanitized_junit(source, tmp_path / 'safe.xml')
