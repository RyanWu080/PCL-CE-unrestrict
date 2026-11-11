"""Mirror official release metadata and rebuild exact tags with a guarded policy patch."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

UPSTREAM = 'PCL-Community/PCL-CE'
DEST = 'RyanWu080/PCL-CE-unrestrict'
MIN_VERSION = (2, 15, 1)
POLICY = 'Plain Craft Launcher 2/Modules/Minecraft/RestrictedFeaturePolicy.cs'
# Exact upstream policies reviewed for the unrestricted replacement.
EXPECTED_BLOBS = {
    '252e4bb09b017285ca93cf3ccda5f177b2c2913a',  # Original restricted releases.
    '3808741c26e439789086dcf3ad3c83867d53eaf7',  # WPF/Core split.
    'cef7848c68a122660c17eee07a614008d2cc91a4',  # dev 16207f9: simplified region hint.
}
MARKER = 'unrestrict-build.json'
ROOT = Path(__file__).resolve().parent

def api(path, method='GET', data=None):
    payload = None if data is None else json.dumps(data, ensure_ascii=False).encode()
    headers = {'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
               'X-GitHub-Api-Version': '2022-11-28'}
    if os.environ.get('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    req = urllib.request.Request('https://api.github.com/' + path, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and method == 'GET':
            return None
        raise

def releases(repo):
    result = []
    for page in range(1, 101):
        batch = api(f'repos/{repo}/releases?per_page=100&page={page}')
        if batch is None:
            raise RuntimeError('Cannot read release list')
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise RuntimeError('Release pagination limit exceeded')

def metadata(release):
    return {'name': release['name'], 'body': release.get('body') or '',
            'prerelease': release['prerelease']}

def eligible_release(release):
    match = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)(?:([-\.])[A-Za-z0-9.-]+)?', release['tag_name'])
    if not match or release['draft']:
        return False
    version = tuple(int(match[i]) for i in (1, 2, 3))
    if version > MIN_VERSION:
        return True
    return version == MIN_VERSION and match[4] is None and not release['prerelease']

def select_candidates(items):
    # v2.15.1 stable is the first restricted release. Never backfill its older betas.
    return sorted((r for r in items if eligible_release(r)),
                  key=lambda r: r['published_at'])

def scan():
    existing = {r['tag_name']: r for r in releases(DEST)}
    pending = []
    for release in select_candidates(releases(UPSTREAM)):
        tag = release['tag_name']
        if not re.fullmatch(r'v\d+\.\d+\.\d+(?:[-.][A-Za-z0-9]+)*', tag):
            raise RuntimeError(f'Unexpected release tag: {tag!r}')
        local = existing.get(tag)
        names = {a['name'] for a in (local or {}).get('assets', [])}
        config = 'Beta' if release['prerelease'] else 'Release'
        required = {MARKER, *(f'PCL2_CE_{config}_{a}_unrestrict.exe' for a in ('x64', 'ARM64'))}
        if local and not local['draft']:
            if not required.issubset(names):
                raise RuntimeError(f'Refusing to overwrite unmanaged/incomplete release {tag}')
            if metadata(local) != metadata(release):
                api(f'repos/{DEST}/releases/{local["id"]}', 'PATCH', metadata(release))
        else:
            pending.append({'id': str(release['id']), 'tag': tag})
    # Excess releases stay pending for the next scheduled run.
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write('matrix=' + json.dumps({'include': pending[:10]}) + '\n')
        output.write('has_work=' + str(bool(pending)).lower() + '\n')
    print('Pending official releases:', [r['tag'] for r in pending])

def run(*args, cwd=None, env=None):
    return subprocess.check_output(args, cwd=cwd, env=env, text=True).strip()

def verify_policy(source, ref='HEAD'):
    blob = run('git', 'rev-parse', f'{ref}:{POLICY}', cwd=source)
    if blob not in EXPECTED_BLOBS:
        raise RuntimeError(f'Upstream region policy changed ({blob}); review patch before publishing')

def patch_source(source):
    path = source / POLICY
    if path.exists():
        if run('git', 'hash-object', POLICY, cwd=source) not in EXPECTED_BLOBS:
            raise RuntimeError('Upstream region policy changed; review patch before publishing')
        shutil.copyfile(ROOT / 'RestrictedFeaturePolicy.cs', path)
        return 'policy-disabled'
    raise RuntimeError('Region policy is missing; review upstream before publishing')

def official_release(release_id):
    if not release_id.isdigit():
        raise ValueError('Release ID must be numeric')
    release = api(f'repos/{UPSTREAM}/releases/{release_id}')
    if not release or not eligible_release(release):
        raise RuntimeError('Official release no longer published')
    tag = release['tag_name']
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:[-.][A-Za-z0-9]+)*', tag):
        raise ValueError('Unexpected tag')
    return release


def checkout_release(release_id):
    tag = official_release(release_id)['tag_name']
    source = Path('source').resolve()
    run('git', 'clone', '--filter=blob:none', '--no-checkout', 'https://github.com/' + UPSTREAM + '.git', str(source))
    run('git', 'checkout', '--detach', 'refs/tags/' + tag, cwd=source)



def build(release_id):
    release = official_release(release_id)
    tag = release['tag_name']
    config = 'Beta' if release['prerelease'] else 'Release'
    source = Path('source').resolve()
    output = Path('release-assets').resolve()
    commit = run('git', 'rev-parse', 'HEAD', cwd=source)
    if commit != run('git', 'rev-parse', f'refs/tags/{tag}^{{commit}}', cwd=source):
        raise RuntimeError('Checked-out commit does not match the official release tag')
    patch_mode = patch_source(source)
    output.mkdir()
    build_env = dict(os.environ, PCL_GITHUB_SHA=commit, describe=tag, PCL_WRITE_SECRET='1')
    for key in ('GH_TOKEN', 'GITHUB_TOKEN'):
        build_env.pop(key, None)
    for arch in ('x64', 'ARM64'):
        artifact = Path('publish-' + arch).resolve()
        subprocess.run(['dotnet', 'publish', 'Plain Craft Launcher 2/Plain Craft Launcher 2.csproj',
            '-p:Configuration=' + config, '-p:Platform=' + arch, '-p:DeleteExistingFiles=true',
            '-o', str(artifact), '--no-self-contained'], cwd=source, env=build_env, check=True)
        binary = artifact / 'Plain Craft Launcher 2.exe'
        if not binary.is_file() or binary.read_bytes()[:2] != b'MZ':
            raise RuntimeError('Missing Windows executable')
        shutil.copyfile(binary, output / f'PCL2_CE_{config}_{arch}_unrestrict.exe')
    manifest = {'upstream': UPSTREAM, 'release_id': release['id'], 'tag': tag,
        'upstream_commit': commit, 'configuration': config, 'patch_mode': patch_mode,
        'patch_sha256': hashlib.sha256((ROOT / 'RestrictedFeaturePolicy.cs').read_bytes()).hexdigest(),
        'notice': 'Unofficial unrestricted rebuild. Original release notes are copied verbatim; upstream signatures and download links do not apply to these modified binaries.',
        'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob('*.exe')}}
    (output / MARKER).write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Built', tag, 'at', commit)

def publish(release_id):
    if not release_id.isdigit():
        raise ValueError('Invalid release ID')
    output = Path('release-assets').resolve()
    manifest = json.loads((output / MARKER).read_text(encoding='utf-8'))
    tag = manifest['tag']
    commit = manifest['upstream_commit']
    config = manifest['configuration']
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:[-.][A-Za-z0-9]+)*', tag) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid manifest')
    # Use metadata afresh, but reject a changed release channel during the build.
    current = api(f'repos/{UPSTREAM}/releases/{release_id}')
    if not current or not eligible_release(current) or current['tag_name'] != tag or ('Beta' if current['prerelease'] else 'Release') != config:
        raise RuntimeError('Official release changed during build; retry')
    upstream_commit = api(f'repos/{UPSTREAM}/commits/{urllib.parse.quote(tag, safe="")}')['sha']
    if commit != upstream_commit or str(manifest['release_id']) != release_id:
        raise RuntimeError('Manifest does not match official source')
    expected_names = {MARKER, *(f'PCL2_CE_{config}_{a}_unrestrict.exe' for a in ('x64', 'ARM64'))}
    if {p.name for p in output.iterdir()} != expected_names:
        raise RuntimeError('Unexpected or missing release assets')
    for name, digest in manifest['sha256'].items():
        if name not in expected_names or hashlib.sha256((output / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Artifact checksum mismatch')
    # Inherited tags remain at upstream source; never move or force-update a tag.
    ref = api(f'repos/{DEST}/git/ref/tags/{urllib.parse.quote(tag, safe="")}')
    if ref:
        obj = ref['object']
        while obj['type'] == 'tag':
            obj = api(f'repos/{DEST}/git/tags/{obj["sha"]}')['object']
        if obj['sha'] != commit:
            raise RuntimeError('Existing fork tag differs from official tag')
    else:
        api(f'repos/{DEST}/git/refs', 'POST', {'ref': 'refs/tags/' + tag, 'sha': commit})
    local = api(f'repos/{DEST}/releases/tags/{urllib.parse.quote(tag, safe="")}')
    if local and not local['draft']:
        raise RuntimeError('Release already published; refusing to overwrite assets')
    if not local:
        local = next((r for r in releases(DEST) if r['tag_name'] == tag), None)
    if local:
        if not local['draft']:
            raise RuntimeError('Release already published')
        api(f'repos/{DEST}/releases/{local["id"]}', 'PATCH', metadata(current))
    else:
        local = api(f'repos/{DEST}/releases', 'POST', dict(metadata(current), tag_name=tag, draft=True))
    subprocess.run(['gh', 'release', 'upload', tag, '--repo', DEST, '--clobber',
                    *[str(p) for p in sorted(output.iterdir())]], check=True)
    latest = api(f'repos/{UPSTREAM}/releases/latest')
    is_latest = latest is not None and latest['id'] == current['id']
    api(f'repos/{DEST}/releases/{local["id"]}', 'PATCH',
        dict(metadata(current), draft=False, make_latest='true' if is_latest else 'false'))
    print('Published', local['html_url'])

if __name__ == '__main__':
    if sys.argv[1] == 'scan':
        scan()
    elif sys.argv[1] == 'checkout':
        checkout_release(os.environ['UPSTREAM_RELEASE_ID'])
    elif sys.argv[1] == 'build':
        build(os.environ['UPSTREAM_RELEASE_ID'])
    elif sys.argv[1] == 'publish':
        publish(os.environ['UPSTREAM_RELEASE_ID'])
    else:
        raise ValueError('Unknown command')


