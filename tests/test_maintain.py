"""Tool fixtures only: report statuses here do NOT prove model behavior improvement."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('maintain', SOURCE / 'scripts/maintain.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        # Preserve generated fixture directories; no cleanup/deletion of user content.
        self.temp = Path(tempfile.mkdtemp(prefix='life-director-tools-', dir='/private/tmp'))
        self.root, self.state = self.temp / 'source', self.temp / 'state'
        for k, v in m.inventory(SOURCE).items():
            m.write(self.root / k, v)
        m.init_state(self.state)
        self.output = self.temp / '人生导师.skill'
        self.before = m.inventory(self.root)

    def cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            m.main(['--source', str(self.root), *map(str, args)])
        return json.loads(out.getvalue())

    def candidate(self, level='patch'):
        candidate = self.state / 'candidates' / level
        blobs = dict(self.before)
        blobs['SKILL.md'] += b'\n'
        ver = json.loads(blobs['version.json'])
        ver['version'] = {'patch':'1.0.1', 'method':'1.1.0', 'expansion':'2.0.0'}[level]
        blobs['version.json'] = json.dumps(ver, ensure_ascii=False).encode()
        blobs['CHANGELOG.md'] += ('\n## ' + ver['version'] + ' — 2026-10-13\n\n- TOOL FIXTURE ONLY\n').encode()
        for k, v in blobs.items():
            m.write(candidate / k, v)
        evidence = self.state / 'evaluations' / 'synthetic-tool-fixture.txt'
        m.write(evidence, b'TOOL FIXTURE ONLY. NOT A REAL BEHAVIOR EVALUATION.')
        report = dict(baseline_sha256=m.fingerprint(self.before), candidate_sha256=m.fingerprint(blobs),
                      attempt=1, level=level, reviewer='tool-fixture', target_cases=['short_missing'],
                      results=[dict(id=k, baseline='fail' if k=='short_missing' else 'pass', candidate='pass',
                                    baseline_evidence='evaluations/synthetic-tool-fixture.txt',
                                    candidate_evidence='evaluations/synthetic-tool-fixture.txt',
                                    reason='Fixture to verify gate branching, not behavior evidence') for k in m.cases(blobs)])
        path = self.state / 'evaluations' / 'fixture-report.json'
        m.write(path, json.dumps(report).encode())
        return candidate, path, report

    def gate(self, candidate, path, approval=None):
        return m.gate(self.root, candidate, path, self.state, approval)

    def test_structure(self):
        self.assertEqual(m.validate(self.before)['cases'], 18)

    def test_package_allowlist_and_privacy(self):
        m.write(self.root / 'feedback.jsonl', b'PRIVATE FIXTURE')
        m.write(self.root / 'notes.md', b'PRIVATE FIXTURE')
        m.write(self.root / '._SKILL.md', b'APPLEDOUBLE FIXTURE')
        self.cli('package', '--output', self.output)
        self.assertEqual(set(m.archive_read(self.output, [m.NAME+'/'+k for k in m.FILES])),
                         {m.NAME+'/'+k for k in m.FILES})
        self.assertTrue(self.cli('inspect', '--archive', self.output)['verified'])

    def test_snapshot_idempotent(self):
        a = m.snapshot(self.before, self.state)
        self.assertEqual(a, m.snapshot(self.before, self.state))
        self.assertEqual(m.read_snapshot(a), self.before)

    def test_release_and_restore(self):
        candidate, path, _ = self.candidate()
        old = m.snapshot(self.before, self.state)
        self.cli('release', '--candidate', candidate, '--report', path,
                 '--state-root', self.state, '--output', self.output)
        self.assertEqual(m.validate(m.inventory(self.root))['version'], '1.0.1')
        self.cli('restore', '--snapshot', old, '--state-root', self.state, '--output', self.output)
        self.assertEqual(m.inventory(self.root), self.before)
        self.assertTrue(self.cli('inspect', '--archive', self.output)['verified'])
        self.assertGreaterEqual(len(list((self.state / 'versions').glob('*.zip'))), 2)

    def test_tampered_snapshot_refused(self):
        original = m.snapshot(self.before, self.state)
        data = m.archive_read(original, ['manifest.json', *('payload/'+k for k in m.FILES)])
        data['payload/SKILL.md'] += b'\n'
        bad = self.state / 'versions' / 'tampered.zip'
        m.archive_write(bad, data)
        with self.assertRaises(ValueError):
            self.cli('restore', '--snapshot', bad, '--state-root', self.state, '--output', self.output)
        self.assertEqual(m.inventory(self.root), self.before)

    def mutate_report(self, report_path, report):
        m.write(report_path, json.dumps(report).encode())

    def test_regression_refused(self):
        c, p, r = self.candidate()
        r['results'][1]['candidate'] = 'fail'
        self.mutate_report(p, r)
        with self.assertRaises(ValueError): self.gate(c, p)

    def test_no_improvement_refused(self):
        c, p, r = self.candidate()
        for row in r['results']: row['baseline'] = 'pass'
        self.mutate_report(p, r)
        with self.assertRaises(ValueError): self.gate(c, p)

    def test_stale_report_refused(self):
        c, p, r = self.candidate()
        r['candidate_sha256'] = '0'*64
        self.mutate_report(p, r)
        with self.assertRaises(ValueError): self.gate(c, p)

    def test_missing_evidence_refused(self):
        c, p, r = self.candidate()
        r['results'][0]['baseline_evidence'] = 'evaluations/missing.txt'
        self.mutate_report(p, r)
        with self.assertRaises(ValueError): self.gate(c, p)

    def test_method_approval_required_and_bound(self):
        c, p, r = self.candidate('method')
        with self.assertRaises(ValueError): self.gate(c, p)
        approval = self.state / 'evaluations' / 'approval.json'
        m.write(approval, json.dumps(dict(candidate_sha256=r['candidate_sha256'], level='method',
                                         confirmation='FIXTURE CONSENT, NOT A HUMAN AUTHORIZATION')).encode())
        self.assertEqual(self.gate(c, p, approval)[2]['level'], 'method')
        m.write(approval, json.dumps(dict(candidate_sha256='0'*64, level='method', confirmation='fixture')).encode())
        with self.assertRaises(ValueError): self.gate(c, p, approval)

    def test_retry_limit(self):
        c, p, r = self.candidate()
        r['attempt'] = 3
        self.mutate_report(p, r)
        with self.assertRaises(ValueError): self.gate(c, p)

    def test_old_cases_cannot_be_weakened(self):
        c, p, r = self.candidate()
        data = m.read_json(c / 'evals/cases.json')
        data['cases'][0]['expectations'] = ['relaxed fixture']
        m.write(c / 'evals/cases.json', json.dumps(data, ensure_ascii=False).encode())
        r['candidate_sha256'] = m.fingerprint(m.inventory(c))
        self.mutate_report(p, r)
        with self.assertRaises(ValueError): self.gate(c, p)

    def test_symlink_source_refused(self):
        refs = self.root / 'references'
        refs.rename(self.root / 'actual-references')
        refs.symlink_to(self.root / 'actual-references', target_is_directory=True)
        with self.assertRaises(ValueError): m.inventory(self.root)

    def test_packaging_failure_restores_source(self):
        c, p, _ = self.candidate()
        m.write(self.output, b'UNRELATED EXISTING FILE')
        with self.assertRaises(Exception):
            self.cli('release', '--candidate', c, '--report', p,
                     '--state-root', self.state, '--output', self.output)
        self.assertEqual(m.inventory(self.root), self.before)
        self.assertEqual(self.output.read_bytes(), b'UNRELATED EXISTING FILE')

    def test_archive_injection_refused(self):
        data = {m.NAME+'/'+k: v for k, v in self.before.items()}
        data['../private.txt'] = b'FIXTURE'
        m.archive_write(self.output, data)
        with self.assertRaises(ValueError): self.cli('inspect', '--archive', self.output)

    def test_state_cannot_overlap_source(self):
        with self.assertRaises(ValueError): m.state_path(self.root, self.root / 'state')

    def test_log_directory_fails_before_application(self):
        c, p, _ = self.candidate()
        (self.state / 'operations.jsonl').mkdir()
        with self.assertRaises(OSError):
            self.cli('release', '--candidate', c, '--report', p,
                     '--state-root', self.state, '--output', self.output)
        self.assertEqual(m.inventory(self.root), self.before)
        self.assertFalse(self.output.exists())

    def test_late_journal_failure_rolls_back_new_package(self):
        c, p, _ = self.candidate()
        with patch.object(m, 'journal', side_effect=OSError('fixture log write failure')):
            with self.assertRaises(OSError):
                self.cli('release', '--candidate', c, '--report', p,
                         '--state-root', self.state, '--output', self.output)
        self.assertEqual(m.inventory(self.root), self.before)
        self.assertFalse(self.output.exists())
        self.assertEqual(len(list((self.state / 'versions').glob('aborted-package-*.skill'))), 1)

    def test_late_journal_failure_restores_existing_package(self):
        c, p, _ = self.candidate()
        self.cli('package', '--output', self.output)
        old_package = self.output.read_bytes()
        with patch.object(m, 'journal', side_effect=OSError('fixture log write failure')):
            with self.assertRaises(OSError):
                self.cli('release', '--candidate', c, '--report', p,
                         '--state-root', self.state, '--output', self.output)
        self.assertEqual(m.inventory(self.root), self.before)
        self.assertEqual(self.output.read_bytes(), old_package)

    def test_source_change_after_gate_is_preserved(self):
        c, p, _ = self.candidate()
        original_gate = m.gate
        edit = self.before['SKILL.md'] + b'\nUNREVIEWED CONCURRENT FIXTURE\n'
        def change_after_gate(*args, **kwargs):
            result = original_gate(*args, **kwargs)
            m.write(self.root / 'SKILL.md', edit)
            return result
        with patch.object(m, 'gate', side_effect=change_after_gate):
            with self.assertRaises(ValueError):
                self.cli('release', '--candidate', c, '--report', p,
                         '--state-root', self.state, '--output', self.output)
        self.assertEqual((self.root / 'SKILL.md').read_bytes(), edit)
        self.assertFalse(self.output.exists())

    def test_backup_collision_refused(self):
        self.cli('package', '--output', self.output)
        old_package = self.output.read_bytes()
        collision = self.state / 'versions' / ('life-director-package-' + m.sha(old_package)[:16] + '.skill')
        m.write(collision, old_package)
        c, _, _ = self.candidate()
        with self.assertRaises(ValueError):
            m.package(m.inventory(c), self.root, collision, self.state)
        self.assertEqual(collision.read_bytes(), old_package)

    def test_output_cannot_enter_state(self):
        c, p, _ = self.candidate()
        with self.assertRaises(ValueError):
            self.cli('release', '--candidate', c, '--report', p,
                     '--state-root', self.state, '--output', self.state / 'versions' / 'out.skill')
        self.assertEqual(m.inventory(self.root), self.before)

if __name__ == '__main__':
    unittest.main(verbosity=2)
