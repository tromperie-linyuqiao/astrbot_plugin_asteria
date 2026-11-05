"""Check public release metadata and a source archive using only Python's stdlib."""
from pathlib import Path, PurePosixPath
import argparse
import ast
import hashlib
import io
import json
import re
import subprocess
import zipfile

REPOSITORY = 'https://github.com/tromperie-linyuqiao/astrbot_plugin_asteria'
LIMIT = 16 * 1024 * 1024

def scalar(text, key):
    values = re.findall(r'^' + re.escape(key) + r':\s*(.+?)\s*$', text, re.M)
    if len(values) != 1:
        raise ValueError(f'Expected one {key} field in metadata.yaml')
    return values[0].strip('"\'')

def constant(text, name):
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f'Missing constant: {name}')

def validate(root, archive):
    metadata = (root/'metadata.yaml').read_text(encoding='utf8')
    version = scalar(metadata, 'version')
    assert re.fullmatch(r'\d+\.\d+\.\d+', version), 'Expected a numeric release version'
    assert scalar(metadata, 'name') == 'astrbot_plugin_asteria', 'Canonical plugin name changed'
    assert scalar(metadata, 'repo') == REPOSITORY, 'Repository mismatch'
    assert constant((root/'CONFIG.py').read_text(encoding='utf8'), 'VERSION') == version, 'CONFIG and metadata versions differ'
    market_bytes = (root/'market.json').read_bytes()
    market = json.loads(market_bytes)
    entry = market['tromperie-linyuqiao/astrbot_plugin_asteria']
    assert entry['name'] == 'astrbot_plugin_asteria' and entry['repo'] == REPOSITORY, 'Market identity differs'
    assert entry['version'] == version, 'Market version is stale'
    assert json.loads((root/'market-md5.json').read_bytes())['md5'] == hashlib.md5(market_bytes).hexdigest(), 'Market checksum is stale'
    client = root/'client/asteria-chat'
    build = (client/'build_apk.py').read_text(encoding='utf8')
    client_version, client_code = constant(build, 'VERSION'), constant(build, 'VERSION_CODE')
    assert f'Asteria {version}' in (root/'README.md').read_text(encoding='utf8'), 'README version is stale'
    manifest = (client/'android/AndroidManifest.xml').read_text(encoding='utf8')
    assert 'com.asteria.chat' in manifest, 'Public client package changed'
    # Fail on accidental distribution of a configured private connection.
    for key in ('DEFAULT_SERVER', 'DEFAULT_CERT_SHA256'):
        assert constant(build, key) == '', f'Public client {key} must be empty'
    assert 0 < len(archive) <= LIMIT, 'Source ZIP exceeds the marketplace 16 MiB limit'
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        members = [n for n in z.namelist() if not n.endswith('/')]
        assert len(members) == len(set(members)), 'Duplicate archive member'
        assert {'metadata.yaml', 'main.py', '_conf_schema.json', 'LICENSE'}.issubset(members), 'Archive must be directly installable at its root'
        forbidden = {'.git', '.runtime', 'node_modules', '__pycache__', 'packages'}
        for name in members:
            p = PurePosixPath(name)
            assert not p.is_absolute() and '..' not in p.parts and '\\' not in name, 'Unsafe archive path'
            assert not forbidden.intersection(p.parts), f'Private/build directory in ZIP: {name}'
            assert not name.endswith(('.apk', '.db', '.sqlite3', '.p12', '.jks', '.keystore')), f'Unexpected runtime/binary material: {name}'
            assert '.private.' not in name and '.dpapi.' not in name, f'Private artifact in ZIP: {name}'
            assert z.read(name) == (root/name).read_bytes(), f'Archive differs from checkout: {name}'
    return dict(version=version, client_version=client_version, client_code=client_code,
                source_files=len(members), archive_bytes=len(archive), archive_sha256=hashlib.sha256(archive).hexdigest())

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    archive = args.archive.read_bytes() if args.archive else subprocess.check_output(['git', 'archive', '--format=zip', 'HEAD'], cwd=root)
    print(json.dumps(validate(root, archive), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
