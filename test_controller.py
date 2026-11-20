import tempfile
import unittest
from pathlib import Path
from controller import Workflow

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'case.sqlite3')
        self.w = Workflow(self.path)
    def tearDown(self):
        self.w.db.close()
        self.temp.cleanup()
    def staged(self, scenario='success'):
        self.w.start('A', scenario)
        for _ in range(6): self.w.act('A')
    def approve(self): self.w.act('A', 'approve', 'Demo Billing Reviewer')
    def test_success_requires_readback(self):
        self.staged(); self.approve()
        self.assertEqual(self.w.act('A', 'execute')['state'], 'mock-executed')
        self.assertEqual(self.w.act('A', 'verify')['state'], 'resolved')
    def test_missing(self):
        self.w.start('A', 'missing')
        for _ in range(3): self.w.act('A')
        self.assertEqual(self.w.read('A')['state'], 'halt')
    def test_auth(self):
        self.w.start('A', 'auth'); self.w.act('A'); self.w.act('A')
        self.assertEqual(self.w.read('A')['state'], 'reauth')
    def test_unmapped(self):
        self.w.start('A', 'unmapped')
        self.assertEqual(self.w.act('A')['state'], 'halt')
    def test_no_approval(self):
        self.staged()
        with self.assertRaises(ValueError): self.w.act('A', 'execute')
    def test_rejection(self):
        self.staged(); self.w.act('A', 'reject', 'Demo Billing Reviewer')
        with self.assertRaises(ValueError): self.w.act('A', 'execute')
    def test_wrong_reviewer(self):
        self.staged()
        with self.assertRaises(ValueError): self.w.act('A', 'approve', 'agent')
    def test_expiry(self):
        self.staged(); self.approve(); self.w.act('A', 'expire')
        with self.assertRaises(ValueError): self.w.act('A', 'execute')
    def test_changed_payload(self):
        self.staged(); self.approve(); self.w.act('A', 'change')
        with self.assertRaises(ValueError): self.w.act('A', 'execute')
    def test_skip(self):
        self.w.start('A')
        with self.assertRaises(ValueError): self.w.act('A', 'execute')
    def test_duplicate_intake(self):
        self.w.start('A'); self.w.start('A')
        self.assertEqual(len(self.w.events('A')), 1)
    def test_duplicate_execution(self):
        self.staged(); self.approve(); self.w.act('A', 'execute')
        with self.assertRaises(ValueError): self.w.act('A', 'execute')
    def test_uncertain(self):
        self.staged('timeout'); self.approve()
        self.assertEqual(self.w.act('A', 'execute')['state'], 'uncertain')
        with self.assertRaises(ValueError): self.w.act('A', 'execute')
    def test_restart(self):
        self.staged(); self.w.db.close(); self.w = Workflow(self.path)
        self.assertEqual(self.w.read('A')['state'], 'stage-for-review')
        self.assertEqual(len(self.w.events('A')), 7)
    def test_injection_ignored_and_prefill_rederived(self):
        self.staged('injection'); c = self.w.read('A')
        self.assertEqual(c['category'], 'duplicate-charge')
        self.assertIsNone(c['approval'])
        self.assertEqual(len(c['evidence']), 3)
    def test_exceptions_at_all_workflow_states(self):
        for i in range(7):
            for action, expected in [('auth-failure','reauth'), ('validation-failure','halt')]:
                key = str(i) + action; self.w.start(key)
                for _ in range(i): self.w.act(key)
                self.assertEqual(self.w.act(key, action)['state'], expected)

if __name__ == '__main__': unittest.main()
