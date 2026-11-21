"""Read-only audit and optional public REST validation for local BTCUSD JSONL history."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shashi_engine.history_audit import audit_jsonl_history, validate_rest_gap, verify_restart_integrity
from shashi_engine.market_data import fetch_candles


def _markdown(audit: dict[str, Any], restart: dict[str, Any] | None, rest: list[dict[str, Any]]) -> str:
    lines = [
        "# BTCUSD JSONL Data-Quality Report", "",
        f"- File: `{audit['path']}`",
        f"- Bytes: {audit['file_bytes']}",
        f"- Records: {audit['total_records']}",
        f"- Canonical candles: {audit['canonical_candles']}",
        f"- WebSocket candles: {audit['websocket_candles']}",
        f"- REST recovery candles: {audit['rest_recovery_candles']}",
        f"- First candle: {audit['first_candle_start_utc'] or 'N/A'}",
        f"- Last candle: {audit['last_candle_start_utc'] or 'N/A'}",
        f"- Missing intervals: {audit['missing_intervals']}",
        f"- Duplicate starts: {len(audit['duplicate_starts'])}",
        f"- Out-of-order pairs: {len(audit['out_of_order_pairs'])}",
        f"- Unresolved recovery intervals: {audit['unresolved_recovery_intervals']}",
        f"- Audit acceptable: {'YES' if audit['acceptable'] else 'NO'}",
    ]
    if restart is not None:
        lines += ["", "## Restart/append integrity", "",
                  f"- Status: {restart['status']}",
                  f"- Existing bytes unchanged on reopen: {restart['history_unchanged']}",
                  f"- SHA-256: `{restart['sha256_after']}`"]
    if rest:
        lines += ["", "## Read-only REST gap checks", ""]
        for item in rest:
            lines += [
                f"- {item['start_utc']} to {item['end_utc_exclusive']}: "
                f"{len(item['returned'])}/{item['requested_intervals']} returned; "
                f"{len(item['unresolved'])} unresolved; valid={item['valid']}"
            ]
    for key, heading in (
        ("malformed_lines", "Malformed JSONL"),
        ("structural_issues", "Structural issues"),
        ("recovery_report_issues", "Recovery-report issues"),
    ):
        if audit[key]:
            lines += ["", f"## {heading}", ""]
            lines += [f"- {item}" for item in audit[key]]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/market_data/btcusd_30m.jsonl")
    parser.add_argument("--json-report", default="data/reports/btcusd_data_quality.json")
    parser.add_argument("--markdown-report", default="data/reports/btcusd_data_quality.md")
    parser.add_argument("--restart-check", action="store_true",
                        help="reopen the JSONL recorder and verify existing bytes are unchanged")
    parser.add_argument("--check-rest-gaps", action="store_true",
                        help="query public REST for detected gaps without writing returned candles")
    parser.add_argument("--max-recovery-intervals", type=int, default=48)
    args = parser.parse_args()

    source = Path(args.input)
    audit = audit_jsonl_history(source).to_dict()
    restart = verify_restart_integrity(source) if args.restart_check else None
    rest_checks: list[dict[str, Any]] = []
    if args.check_rest_gaps and not audit["malformed_lines"] and not audit["structural_issues"]:
        # Only check explicitly bounded, internal gaps. Never fetch a moving/latest interval.
        first = audit["first_candle_start_utc"]
        last = audit["last_candle_start_utc"]
        if first and last:
            present = set()
            with source.open("r", encoding="utf-8") as handle:
                for line in handle:
                    record = json.loads(line)
                    if record.get("record_type") in ("completed_candle", "rest_recovery"):
                        present.add(int(datetime.fromisoformat(
                            record["candle_start_utc"].replace("Z", "+00:00")
                        ).timestamp()))
            ordered = sorted(present)
            for left, right in zip(ordered, ordered[1:]):
                if right - left <= 1800:
                    continue
                cursor = left + 1800
                while cursor < right:
                    window_end = min(right, cursor + args.max_recovery_intervals * 1800)
                    result = validate_rest_gap(
                        cursor, window_end, fetcher=fetch_candles,
                        max_intervals=args.max_recovery_intervals,
                    )
                    result["start_utc"] = datetime.fromtimestamp(cursor, timezone.utc).isoformat()
                    result["end_utc_exclusive"] = datetime.fromtimestamp(window_end, timezone.utc).isoformat()
                    rest_checks.append(result)
                    cursor = window_end

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit": audit,
        "restart_integrity": restart,
        "rest_gap_checks": rest_checks,
        "safety": {
            "public_read_only": True, "authenticated": False,
            "writes_to_input_history": False, "automatic_gap_filling": False,
        },
    }
    json_path = Path(args.json_report)
    md_path = Path(args.markdown_report)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(audit, restart, rest_checks), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    rest_ok = all(item["valid"] for item in rest_checks)
    return 0 if audit["acceptable"] and rest_ok and (restart is None or restart["status"] == "PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
