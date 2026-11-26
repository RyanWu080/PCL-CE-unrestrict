"""Merge reviewed upstream changes while reapplying the unrestricted policy."""
from pathlib import Path
import shutil
import subprocess
import sys

from sync import policy_path, ROOT, run, verify_policy


def merge(source, upstream):
    target = verify_policy(source, upstream)
    current = policy_path(source, 'HEAD')
    expected = run('git', 'hash-object', str(ROOT / Path(current).name))
    if run('git', 'rev-parse', f'HEAD:{current}', cwd=source) != expected:
        raise RuntimeError('Custom policy changed; review before synchronizing')
    if subprocess.run(['git', 'merge-base', '--is-ancestor', upstream, 'HEAD'], cwd=source).returncode == 0:
        print('Already up to date; policy verified.')
        return False
    result = subprocess.run(['git', 'merge', '--no-ff', '--no-commit', upstream], cwd=source)
    try:
        # A failed merge without MERGE_HEAD is not a resolvable content conflict.
        run('git', 'rev-parse', '--verify', 'MERGE_HEAD', cwd=source)
        conflicts = run('git', 'diff', '--name-only', '--diff-filter=U', cwd=source).splitlines()
        if any(path not in (current, target) and not path.startswith('.github/workflows/') for path in conflicts) or (result.returncode and not conflicts):
            raise RuntimeError('Upstream merge conflicted outside the reviewed policy and fork workflows')
        # The Actions token cannot push changes to workflow files.
        if run('git', 'ls-files', '--', '.github/workflows', cwd=source) or run(
                'git', 'ls-tree', 'HEAD', '.github/workflows', cwd=source):
            run('git', 'restore', '--source=HEAD', '--staged', '--worktree', '--',
            '.github/workflows', cwd=source)
        if current != target:
            run('git', 'rm', '-f', '--ignore-unmatch', '--', current, cwd=source)
        template = ROOT / Path(target).name
        expected = run('git', 'hash-object', str(template))
        shutil.copyfile(template, source / target)
        run('git', 'add', '--', target, cwd=source)
        if run('git', 'rev-parse', f':{target}', cwd=source) != expected:
            raise RuntimeError('Unrestricted policy verification failed')
        run('git', 'commit', '-m', f'Merge upstream dev at {upstream}; preserve unrestricted policy', cwd=source)
    except Exception:
        subprocess.run(['git', 'merge', '--abort'], cwd=source)
        raise
    return True


if __name__ == '__main__':
    merge(Path.cwd(), sys.argv[1])
