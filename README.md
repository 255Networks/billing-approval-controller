# Billing Approval Controller

A fictional ledger lists the same USD 120 invoice twice. This Python controller stages a proposed correction, records exactly what a reviewer approved and allows one simulated execution for that case. A changed amount requires a fresh approval. An uncertain result sends the case to reconciliation.

## Run a correction

Use Python 3.10 or later and a fresh case ID. From this directory, run these commands in a POSIX shell:

```sh
python3 controller.py start --case DEMO-001
for step in 1 2 3 4 5 6; do python3 controller.py next --case DEMO-001; done
python3 controller.py approve --case DEMO-001
```

Read the proposal and type `Demo Billing Reviewer` at the prompt. It is a simulated reviewer identity. Complete the run:

```sh
python3 controller.py execute --case DEMO-001
python3 controller.py verify --case DEMO-001
python3 controller.py audit --case DEMO-001
```

The first command produces a local mock receipt. The second compares its payload hash with the staged correction and moves the case to `resolved`. The third shows the ordered audit events. The fixture stores currency amounts in minor units, so `12000` represents USD 120.00.

## Try a failure

| Experiment | What to do | Expected result |
| --- | --- | --- |
| Repeat the request | Run `start` twice with the same case ID. | The second call returns the existing case. Only one intake event is recorded. |
| Change the amount | Stage and approve a fresh case, run `change`, then run `execute` with that case ID. | Execution is blocked because the approval describes the earlier amount. |
| Repeat an execution | Run `execute` again after a successful run. | The state transition is rejected. The case keeps its first receipt. |
| Simulate an uncertain outcome | Start a fresh case with `--scenario timeout`, stage it, approve it, then execute. | The case enters `uncertain`. Another execution is blocked pending reconciliation. |

## Run the tests

```sh
python3 -m unittest -v
```

The 16 tests also cover missing evidence, an expired approval, a rejected proposal, a restart and conflicting intake text. `fixtures/records.json` contains the fictional invoice, ledger, task and review rule.

## Operating assumptions

Each command uses the local `demo.sqlite3` database by default. Pass the same `--db` path to every command to use a different database. The sample diagnosis is scripted for the supplied fixture. Duplicate protection is scoped to the case ID in that database. The receipt and readback are both simulated. Production identity verification, payment settlement and resolution of an uncertain external transaction are outside the scope of this demo.
