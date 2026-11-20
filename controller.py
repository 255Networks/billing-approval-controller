"""Local SQLite simulation of a billing correction and its approval.

The demo reviewer is a typed label. The receipt is generated locally.
A person with filesystem access can edit the SQLite audit history.
"""
import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path

STEPS = ['intake', 'classify', 'verify-sop', 'gather-evidence', 'diagnose',
         'flag-risk', 'stage-for-review']
ROOT = Path(__file__).resolve().parent

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

class Workflow:
    def __init__(self, path='demo.sqlite3'):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY, case_id TEXT, event TEXT, at REAL)')

    def read(self, case_id):
        row = self.db.execute('SELECT data FROM cases WHERE id=?', (case_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown case')
        return json.loads(row[0])

    def _write(self, case, event):
        self.db.execute('INSERT OR REPLACE INTO cases VALUES (?,?)', (case['id'], json.dumps(case)))
        self.db.execute('INSERT INTO audit(case_id,event,at) VALUES (?,?,?)', (case['id'], event, time.time()))

    def start(self, case_id, scenario='success'):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute('SELECT 1 FROM cases WHERE id=?', (case_id,)).fetchone():
                return self.read(case_id)  # Same intake key never creates a second case.
            case = dict(id=case_id, state='intake', scenario=scenario, evidence=[],
                        approval=None, risk=None, proposal=None, outcome=None)
            self._write(case, 'intake accepted; synthetic fixture only')
        return case

    def act(self, case_id, action='next', reviewer=None):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            c = self.read(case_id)
            scenario, state = c['scenario'], c['state']
            record = json.loads((ROOT / 'fixtures' / 'records.json').read_text())
            if action in ('auth-failure', 'validation-failure') and state in STEPS:
                c['state'] = 'reauth' if action == 'auth-failure' else 'halt'
                c['exception_owner'] = 'Demo Access Owner' if c['state'] == 'reauth' else 'Demo Case Owner'
                c['reason'] = 'T-01: reconnect outside chat' if c['state'] == 'reauth' else 'T-02: validate with owner'
            elif action == 'next' and state in STEPS[:-1]:
                target = STEPS[STEPS.index(state) + 1]
                if scenario == 'auth' and target == 'verify-sop':
                    c.update(state='reauth', reason='T-01: authentication expired', exception_owner='Demo Access Owner')
                elif target == 'classify' and scenario == 'unmapped':
                    c.update(state='halt', reason='T-02: no fixed taxonomy match', exception_owner='Demo Case Owner')
                elif target == 'gather-evidence' and scenario == 'missing':
                    c.update(state='halt', reason='T-02: invoice record absent', exception_owner='Demo Case Owner')
                else:
                    c['state'] = target
                    if target == 'classify':
                        c['category'] = record['invoice']['category']  # Never task prefill.
                        if c['category'] not in ('duplicate-charge', 'wrong-entity'):
                            raise ValueError('Unmapped authoritative category')
                        c['evidence'].append('fixture:invoice/INV-DEMO-01@1')
                    elif target == 'verify-sop':
                        c['evidence'].append('fixture:sop/SOP-DEMO-01@1')
                    elif target == 'gather-evidence':
                        c['evidence'].append('fixture:ledger/LEDGER-DEMO-01@1')
                        c['amount_minor'] = record['invoice']['amount_minor']
                    elif target == 'diagnose':
                        if len(c['evidence']) < 3:
                            raise ValueError('Required canonical evidence missing')
                        c['diagnosis'] = {
                            'Root Cause': 'Synthetic ledger repeats INV-DEMO-01 [fixture:ledger/LEDGER-DEMO-01@1]',
                            "What's Blocked": 'Correction requires review [fixture:sop/SOP-DEMO-01@1]',
                            'What Needs to Happen': 'Review proposed correction; do not issue credit [fixture:sop/SOP-DEMO-01@1]',
                            'Recommended Owner': 'Demo Billing Reviewer [fixture:sop/SOP-DEMO-01@1]'}
                    elif target == 'flag-risk':
                        c['risk'] = 'Financial correction proposed; review mandatory'
                    elif target == 'stage-for-review':
                        if not c['risk'] or not c.get('diagnosis'):
                            raise ValueError('Incomplete review packet')
                        c['proposal'] = dict(case_id=case_id, action='mock-correction',
                                             invoice='INV-DEMO-01', amount_minor=c['amount_minor'],
                                             currency='USD', record_version=1, evidence=c['evidence'])
            elif action in ('approve', 'reject') and state == 'stage-for-review':
                if reviewer != 'Demo Billing Reviewer':
                    raise ValueError('Demo reviewer mismatch')
                c['approval'] = dict(decision=action, reviewer=reviewer, hash=digest(c['proposal']),
                                     expires=time.time() + 300)
            elif action == 'change' and state == 'stage-for-review':
                c['proposal']['amount_minor'] += 100
            elif action == 'expire' and state == 'stage-for-review' and c['approval']:
                c['approval']['expires'] = 0
            elif action == 'execute' and state == 'stage-for-review':
                a = c['approval']
                if not a or a['decision'] != 'approve' or a['expires'] < time.time() or a['hash'] != digest(c['proposal']):
                    raise ValueError('No valid approval for this exact payload')
                c['idempotency_key'] = digest(c['proposal'])
                # No external request is sent. Timeout models an uncertain external outcome.
                c['state'] = 'uncertain' if scenario == 'timeout' else 'mock-executed'
                c['outcome'] = 'unknown: reconcile before retry' if scenario == 'timeout' else dict(receipt='MOCK-01', payload_hash=a['hash'])
            elif action == 'verify' and state == 'mock-executed':
                if c['outcome']['payload_hash'] != digest(c['proposal']):
                    raise ValueError('Mock readback mismatch')
                c['state'] = 'resolved'
            else:
                raise ValueError('Unauthorized transition: ' + state + ' / ' + action)
            self._write(c, action + ' -> ' + c['state'])
        return c

    def events(self, case_id):
        return self.db.execute('SELECT seq,event FROM audit WHERE case_id=? ORDER BY seq', (case_id,)).fetchall()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['start', 'next', 'show', 'audit', 'approve', 'reject', 'execute', 'verify', 'change', 'expire', 'auth-failure', 'validation-failure'])
    p.add_argument('--case', default='CASE-DEMO-01')
    p.add_argument('--db', default='demo.sqlite3')
    p.add_argument('--scenario', default='success', choices=['success', 'missing', 'auth', 'unmapped', 'timeout', 'injection'])
    args = p.parse_args()
    w = Workflow(args.db)
    try:
        if args.command == 'start': out = w.start(args.case, args.scenario)
        elif args.command == 'show': out = w.read(args.case)
        elif args.command == 'audit': out = w.events(args.case)
        else:
            reviewer = None
            if args.command in ('approve', 'reject'):
                print(json.dumps(w.read(args.case)['proposal'], indent=2))
                reviewer = input('Local DEMO ONLY. Type Demo Billing Reviewer to record this decision: ')
            out = w.act(args.case, args.command, reviewer)
        print(json.dumps(out, indent=2))
    except ValueError as e:
        p.exit(2, 'BLOCKED: ' + str(e) + '\n')
    finally:
        w.db.close()

if __name__ == '__main__': main()
