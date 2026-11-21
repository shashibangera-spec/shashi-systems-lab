"""Run a 2-4 hour public BTCUSD recorder soak with two clean restarts.

The runner launches three bounded recorder processes against the same append-only
JSONL file. It audits after each process exits and verifies that each prior byte
prefix is unchanged. Public unauthenticated market data only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

MIN_RECORDING_SECONDS = 2 * 60 * 60
MAX_RECORDING_SECONDS = 4 * 60 * 60
RESTART_CYCLES = 2
SESSION_COUNT = RESTART_CYCLES + 1


def split_recording_duration(total_seconds: int) -> list[int]:
    if not MIN_RECORDING_SECONDS <= total_seconds <= MAX_RECORDING_SECONDS:
        raise ValueError("total recording duration must be between 7200 and 14400 seconds")
    base, remainder = divmod(total_seconds, SESSION_COUNT)
    return [base] * (SESSION_COUNT - 1) + [base + remainder]


def sha256_prefix(path: Path, byte_count: int) -> str:
    """Hash exactly the first byte_count bytes without loading the file into memory."""
    if byte_count < 0:
        raise ValueError("byte_count cannot be negative")
    digest = hashlib.sha256()
    remaining = byte_count
    with path.open("rb") as handle:
        while remaining:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("file became shorter than the recorded prefix")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def _prefix_snapshot(path: Path) -> dict[str, Any]:
    size = path.stat().st_size if path.exists() else 0
    return {"bytes": size, "sha256": sha256_prefix(path, size) if size else hashlib.sha256(b"").hexdigest()}


def _run(command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False,
    )


def run_soak(
    *,
    output_path: str,
    total_recording_seconds: int,
    restart_pause_seconds: int = 15,
    stale_after_seconds: int = 120,
    max_recovery_intervals: int = 48,
    check_rest_gaps: bool = False,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = _run,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if not 0 <= restart_pause_seconds <= 300:
        raise ValueError("restart pause must be between 0 and 300 seconds")
    if stale_after_seconds <= 0 or max_recovery_intervals <= 0:
        raise ValueError("stale threshold and recovery limit must be positive")

    root = Path(__file__).resolve().parents[1]
    source = Path(output_path)
    if not source.is_absolute():
        source = root / source
    source.parent.mkdir(parents=True, exist_ok=True)
    report_dir = root / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = report_dir / f"phase1h_soak_{run_id}.json"
    markdown_path = report_dir / f"phase1h_soak_{run_id}.md"
    durations = split_recording_duration(total_recording_seconds)
    recorder_script = root / "scripts" / "record_btcusd_market_data.py"
    audit_script = root / "scripts" / "audit_btcusd_history.py"

    manifest: dict[str, Any] = {
        "phase": "1H",
        "run_id": run_id,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_path": str(source),
        "requested_active_recording_seconds": total_recording_seconds,
        "restart_cycles": RESTART_CYCLES,
        "session_durations_seconds": durations,
        "restart_pause_seconds": restart_pause_seconds,
        "sessions": [],
        "prefix_integrity": [],
        "safety": {
            "public_read_only": True,
            "authenticated": False,
            "private_account_data_accessed": False,
            "orders_submitted": False,
            "input_history_rewritten": False,
        },
    }

    def audit(session_number: int) -> tuple[bool, str]:
        json_report = report_dir / f"phase1h_{run_id}_audit_{session_number}.json"
        md_report = report_dir / f"phase1h_{run_id}_audit_{session_number}.md"
        command = [
            sys.executable, str(audit_script), "--input", str(source),
            "--restart-check", "--json-report", str(json_report),
            "--markdown-report", str(md_report),
        ]
        if check_rest_gaps:
            command.append("--check-rest-gaps")
        result = command_runner(command, cwd=root, timeout=300)
        return result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]

    # Fail closed if the existing file is already invalid. A new file is allowed.
    if source.exists():
        preflight_ok, preflight_output = audit(0)
        manifest["preflight_audit_passed"] = preflight_ok
        if not preflight_ok:
            manifest["failure"] = "preflight history audit failed"
            manifest["preflight_output"] = preflight_output
            _write_report(manifest, manifest_path, markdown_path)
            return 1

    overall_ok = True
    for index, duration in enumerate(durations, start=1):
        before = _prefix_snapshot(source)
        command = [
            sys.executable, str(recorder_script), "--output", str(source),
            "--duration-seconds", str(duration),
            "--stale-after-seconds", str(stale_after_seconds),
            "--max-recovery-intervals", str(max_recovery_intervals),
        ]
        try:
            result = command_runner(command, cwd=root, timeout=duration + 180)
            session = {
                "session": index,
                "duration_seconds": duration,
                "recorder_exit_code": result.returncode,
                "stdout_tail": result.stdout[-4000:],
                "stderr_tail": result.stderr[-2000:],
            }
        except subprocess.TimeoutExpired as exc:
            session = {
                "session": index, "duration_seconds": duration,
                "recorder_exit_code": None, "error": "recorder process exceeded bounded timeout",
                "stdout_tail": str(exc.stdout or "")[-4000:],
                "stderr_tail": str(exc.stderr or "")[-2000:],
            }
            manifest["sessions"].append(session)
            overall_ok = False
            manifest["failure"] = f"session {index} exceeded bounded timeout"
            break
        except OSError as exc:
            manifest["sessions"].append({
                "session": index, "duration_seconds": duration, "error": str(exc),
            })
            overall_ok = False
            manifest["failure"] = f"could not launch session {index}"
            break

        manifest["sessions"].append(session)
        after = _prefix_snapshot(source) if source.exists() else {"bytes": 0, "sha256": None}
        prefix_ok = after["bytes"] >= before["bytes"] and (
            before["bytes"] == 0 or sha256_prefix(source, before["bytes"]) == before["sha256"]
        )
        manifest["prefix_integrity"].append({
            "after_session": index,
            "bytes_before": before["bytes"],
            "bytes_after": after["bytes"],
            "sha256_prefix_before": before["sha256"],
            "unchanged_prefix": prefix_ok,
        })
        session_ok = result.returncode == 0 and prefix_ok
        overall_ok = overall_ok and session_ok

        audit_ok, audit_output = audit(index)
        session["post_session_audit_passed"] = audit_ok
        session["audit_output_tail"] = audit_output
        overall_ok = overall_ok and audit_ok
        if not prefix_ok or not audit_ok:
            manifest["failure"] = f"integrity gate failed after session {index}"
            break
        if index < SESSION_COUNT:
            sleep(restart_pause_seconds)

    manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["status"] = "PASS" if overall_ok and len(manifest["sessions"]) == SESSION_COUNT else "FAIL"
    _write_report(manifest, manifest_path, markdown_path)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"JSON report: {manifest_path}")
    print(f"Markdown report: {markdown_path}")
    return 0 if manifest["status"] == "PASS" else 1


def _write_report(manifest: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    manifest.setdefault("finished_at_utc", datetime.now(timezone.utc).isoformat())
    manifest["json_report"] = str(json_path)
    manifest["markdown_report"] = str(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Phase 1H Focused Recorder Soak",
        "",
        f"- Status: **{manifest.get('status', 'INCOMPLETE')}**",
        f"- Active recording target: {manifest['requested_active_recording_seconds']} seconds",
        f"- Sessions: {len(manifest['sessions'])}/3",
        f"- Controlled restart cycles: {manifest['restart_cycles']}",
        f"- Output: `{manifest['output_path']}`",
        "",
        "## Session results",
        "",
    ]
    for session in manifest["sessions"]:
        lines.append(
            f"- Session {session['session']}: exit={session.get('recorder_exit_code')}; "
            f"audit={session.get('post_session_audit_passed', 'not run')}"
        )
    lines += ["", "## Append-prefix integrity", ""]
    for check in manifest["prefix_integrity"]:
        lines.append(
            f"- After session {check['after_session']}: "
            f"{check['bytes_before']} prior bytes preserved={check['unchanged_prefix']}"
        )
    lines += [
        "", "## Safety", "",
        "- Public unauthenticated market data only.",
        "- No private account access or order submission.",
        "- Existing JSONL history is append-only; each prior byte prefix is checked after a session.",
    ]
    if manifest.get("failure"):
        lines += ["", f"Failure: {manifest['failure']}"]
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/market_data/btcusd_30m.jsonl")
    parser.add_argument("--total-recording-seconds", type=int, default=7200,
                        help="active recorder time, 7200-14400 seconds; split across three processes")
    parser.add_argument("--restart-pause-seconds", type=int, default=15,
                        help="clean stop/start pause at each of two boundaries (0-300)")
    parser.add_argument("--stale-after-seconds", type=int, default=120)
    parser.add_argument("--max-recovery-intervals", type=int, default=48)
    parser.add_argument("--check-rest-gaps", action="store_true",
                        help="also run Phase 1G's read-only REST check during each audit")
    args = parser.parse_args()
    try:
        return run_soak(
            output_path=args.output,
            total_recording_seconds=args.total_recording_seconds,
            restart_pause_seconds=args.restart_pause_seconds,
            stale_after_seconds=args.stale_after_seconds,
            max_recovery_intervals=args.max_recovery_intervals,
            check_rest_gaps=args.check_rest_gaps,
        )
    except ValueError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
