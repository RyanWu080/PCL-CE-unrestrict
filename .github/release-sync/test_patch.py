from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import sync
from sync_branch import merge


class PolicyPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        self.git('init', '-b', 'base')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.com')
        self.policy = self.source / sync.POLICY
        self.policy.parent.mkdir(parents=True)
        self.reviewed = (ROOT / 'reviewed-policy-current.cs').read_bytes()
        self.patch = (ROOT / 'RestrictedFeaturePolicy.cs').read_bytes()
        self.policy.write_bytes(self.reviewed)
        (self.source / 'other.txt').write_text('base\n')
        self.commit('base')
        self.git('branch', 'upstream')
        self.git('checkout', '-b', 'custom')
        self.policy.write_bytes(self.patch)
        self.commit('unrestrict')

    def git(self, *args):
        return sync.run('git', *args, cwd=self.source)

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-m', message)

    def upstream(self, policy=None, other='upstream\n'):
        self.git('checkout', 'upstream')
        if policy is not None:
            self.policy.write_bytes(policy)
        (self.source / 'other.txt').write_text(other)
        self.commit('upstream change')
        self.git('checkout', 'custom')

    def test_release_patch_accepts_reviewed_policy_and_rejects_unknown(self):
        self.policy.write_bytes(self.reviewed)
        self.assertEqual(sync.patch_source(self.source), 'policy-disabled')
        self.assertEqual(self.policy.read_bytes(), self.patch)
        self.policy.write_bytes(self.reviewed + b'// unreviewed\n')
        with self.assertRaises(RuntimeError):
            sync.patch_source(self.source)

    def test_merge_preserves_patch_and_upstream_changes(self):
        self.upstream()
        self.assertTrue(merge(self.source, 'upstream'))
        self.assertEqual(self.policy.read_bytes(), self.patch)
        self.assertEqual((self.source / 'other.txt').read_text(), 'upstream\n')
        self.assertFalse(merge(self.source, 'upstream'))

    def test_policy_conflict_is_resolved(self):
        # Both sides modify the same line from a common ancestor.
        self.git('checkout', 'base')
        self.policy.write_bytes(self.reviewed.replace(b'LauncherCommon.Log', b'ModBase.Log'))
        self.commit('older upstream')
        self.git('branch', '-f', 'upstream')
        self.git('checkout', '-B', 'custom')
        self.policy.write_bytes(self.patch)
        self.commit('unrestrict')
        self.upstream(policy=self.reviewed)
        self.assertTrue(merge(self.source, 'upstream'))
        self.assertEqual(self.policy.read_bytes(), self.patch)

    def test_unknown_upstream_stops_before_merge(self):
        self.upstream(policy=self.reviewed + b'// new policy\n')
        before = self.git('rev-parse', 'HEAD')
        with self.assertRaises(RuntimeError):
            merge(self.source, 'upstream')
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)

    def test_other_conflicts_abort_without_changing_head(self):
        (self.source / 'other.txt').write_text('custom\n')
        self.commit('custom other change')
        before = self.git('rev-parse', 'HEAD')
        self.upstream()
        with self.assertRaises(RuntimeError):
            merge(self.source, 'upstream')
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual(self.git('status', '--porcelain'), '')


if __name__ == '__main__':
    unittest.main()
