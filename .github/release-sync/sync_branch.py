"""Merge reviewed upstream changes while reapplying the unrestricted policy."""
from pathlib import Path
import shutil
import subprocess
import sys

from sync import POLICY, ROOT, run, verify_policy


def merge(source, upstream):
    verify_policy(source, upstream)
    expected = run('git', 'hash-object', str(ROOT / 'RestrictedFeaturePolicy.cs'))
    if run('git', 'rev-parse', f'HEAD:{POLICY}', cwd=source) != expected:
        raise RuntimeError('Custom policy changed; review before synchronizing')
    if subprocess.run(['git', 'merge-base', '--is-ancestor', upstream, 'HEAD'], cwd=source).returncode == 0:
        print('Already up to date; policy verified.')
        return False
    result = subprocess.run(['git', 'merge', '--no-ff', '--no-commit', upstream], cwd=source)
    try:
        # A failed merge without MERGE_HEAD is not a resolvable content conflict.
        run('git', 'rev-parse', '--verify', 'MERGE_HEAD', cwd=source)
        conflicts = run('git', 'diff', '--name-only', '--diff-filter=U', cwd=source).splitlines()
        if any(path != POLICY and not path.startswith('.github/workflows/') for path in conflicts) or (result.returncode and not conflicts):
            raise RuntimeError('Upstream merge conflicted outside the reviewed policy and fork workflows')
        # The Actions token cannot push changes to workflow files.
        run('git', 'restore', '--source=HEAD', '--staged', '--worktree', '--',
            '.github/workflows', cwd=source)
        shutil.copyfile(ROOT / 'RestrictedFeaturePolicy.cs', source / POLICY)
        run('git', 'add', '--', POLICY, cwd=source)
        if run('git', 'rev-parse', f':{POLICY}', cwd=source) != expected:
            raise RuntimeError('Unrestricted policy verification failed')
        run('git', 'commit', '-m', f'Merge upstream dev at {upstream}; preserve unrestricted policy', cwd=source)
    except Exception:
        subprocess.run(['git', 'merge', '--abort'], cwd=source)
        raise
    return True


if __name__ == '__main__':
    merge(Path.cwd(), sys.argv[1])
