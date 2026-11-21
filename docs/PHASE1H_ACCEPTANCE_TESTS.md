# Phase 1H — Focused Soak Acceptance Tests

## Automated tests

1. Two-hour duration divides into three 2,400-second sessions.
2. Four-hour duration divides into three 4,800-second sessions.
3. Durations outside 7,200–14,400 seconds are rejected.
4. Prefix hashing reads exactly the requested number of prior bytes and detects a shortened file.
5. Runner CLI validates restart pause, stale threshold and recovery-window limits.
6. The test suite does not require network access, exchange credentials or a real recorder process.

## User-run Windows soak

From the repository root:

```powershell
git fetch origin
git switch phase1h-focused-soak-runner
git pull
python -m pip install -e ".[market-data,dev]"
python -m pytest -q
```

Start the default two-hour run:

```powershell
python scripts/run_btcusd_soak.py
```

For a four-hour active recording:

```powershell
python scripts/run_btcusd_soak.py --total-recording-seconds 14400
```

Optional read-only REST gap checks after each segment:

```powershell
python scripts/run_btcusd_soak.py --total-recording-seconds 7200 --check-rest-gaps
```

The runner uses three sequential recorder processes, the same JSONL output path, two clean stop/start boundaries and a default 15-second pause. It writes a run-level JSON/Markdown manifest plus per-session Phase 1G reports under `data/reports/`.

## Review the output

Confirm the run-level report shows:

- `status = PASS`
- `sessions = 3/3`
- Both restart boundaries have `unchanged_prefix = true`
- All recorder exit codes are 0
- Every post-session audit passed
- No unexplained gaps, duplicates, malformed records, ordering defects or unresolved recovery intervals
- Safety metadata remains unauthenticated, public-read-only, no private account data and no orders

A transient feed disconnect/error must be visible in the report and JSONL. Do not suppress or reinterpret it as a pass. If no actual missing interval occurs, REST recovery is **not exercised by the live soak**; report that honestly.

## Safety and handling

- Do not run a second recorder against the same file while the soak is running.
- Do not delete, edit, rename or truncate the source JSONL during the test.
- Keep `data/` local and git-ignored; do not commit recordings or reports.
- If the runner exits nonzero, share the run-level JSON report and console output before attempting a rerun.
- No credentials, private channels, account endpoints, Testnet, live endpoints or order routes are used.
- The short soak validates only this 2–4-hour window and two restart boundaries; it is not a long-term reliability certification.
