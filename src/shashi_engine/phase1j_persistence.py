"""Durable local Phase 1J safety persistence.

This module is deliberately offline. It contains no networking, exchange SDK,
credential handling, order submission, or order mutation code. SQLite is used
with WAL + FULL synchronous durability, transactional writes, append-only
hash-chained audit events, and persisted session kill-switches/order intents.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping


DAILY_LOSS_LIMIT_USD = Decimal("2.50")
_SCHEMA_VERSION = 1
_SECRET_KEY_PARTS = (
    "api_key", "api_secret", "secret", "signature", "authorization",
    "password", "token", "credential", "private_key",
)
_CLIENT_ID_RE = re.compile(r"^[a-f0-9]{32}$")


class PersistenceError(RuntimeError):
    """Durable safety state could not be trusted or written."""


class IntentConflict(PersistenceError):
    """An existing deterministic client ID was reused with different intent data."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized for part in _SECRET_KEY_PARTS):
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = _redact(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"Unsupported audit value type: {type(value).__name__}")


def deterministic_client_order_id(
    session_id: str,
    strategy_instance: str,
    signal_identity: str,
    order_role: str,
    revision: int,
) -> str:
    """Stable 32-hex ID; this does not imply exchange acceptance/idempotency."""
    parts = (session_id, strategy_instance, signal_identity, order_role)
    if any(not part or not part.strip() for part in parts):
        raise ValueError("all client-order ID components must be non-empty")
    if revision < 0:
        raise ValueError("revision must be non-negative")
    material = _canonical_json([*parts, revision]).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class PersistedSessionRisk:
    session_id: str
    limit_usd: Decimal
    latched: bool
    reason: str | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class PersistedIntent:
    client_order_id: str
    session_id: str
    intent_key: str
    payload_json: str
    status: str
    created_at: str


class DurableSafetyStore:
    """SQLite-backed safety store; create explicitly at a caller-selected path."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        if self.path.exists() and self.path.is_dir():
            raise PersistenceError("database path points to a directory")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS schema_meta (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        version INTEGER NOT NULL
                    );
                    INSERT OR IGNORE INTO schema_meta(singleton, version) VALUES (1, 1);

                    CREATE TABLE IF NOT EXISTS session_risk (
                        session_id TEXT PRIMARY KEY,
                        limit_usd TEXT NOT NULL CHECK (limit_usd = '2.50'),
                        latched INTEGER NOT NULL CHECK (latched IN (0, 1)),
                        reason TEXT,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS order_intents (
                        client_order_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        intent_key TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(session_id, intent_key)
                    );

                    CREATE TABLE IF NOT EXISTS audit_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        previous_hash TEXT NOT NULL,
                        event_hash TEXT NOT NULL UNIQUE
                    );

                    CREATE TRIGGER IF NOT EXISTS audit_events_no_update
                    BEFORE UPDATE ON audit_events
                    BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

                    CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                    BEFORE DELETE ON audit_events
                    BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
                    """
                )
                version = conn.execute(
                    "SELECT version FROM schema_meta WHERE singleton=1"
                ).fetchone()[0]
                if version != _SCHEMA_VERSION:
                    raise PersistenceError(f"unsupported database schema version: {version}")
        except (sqlite3.Error, OSError) as exc:
            raise PersistenceError(f"could not initialize durable safety store: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level="IMMEDIATE")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _append_audit_tx(
        self, conn: sqlite3.Connection, event_type: str, payload: Mapping[str, Any]
    ) -> int:
        if not event_type.strip():
            raise ValueError("event_type is required")
        payload_json = _canonical_json(_redact(payload))
        previous = conn.execute(
            "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["event_hash"] if previous else "0" * 64
        timestamp = _utc_now()
        material = _canonical_json(
            [timestamp, event_type, payload_json, previous_hash]
        ).encode("utf-8")
        event_hash = hashlib.sha256(material).hexdigest()
        cursor = conn.execute(
            """INSERT INTO audit_events
               (timestamp, event_type, payload_json, previous_hash, event_hash)
               VALUES (?, ?, ?, ?, ?)""",
            (timestamp, event_type, payload_json, previous_hash, event_hash),
        )
        return int(cursor.lastrowid)

    def append_audit(self, event_type: str, payload: Mapping[str, Any]) -> int:
        try:
            with self._connect() as conn:
                return self._append_audit_tx(conn, event_type, payload)
        except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
            raise PersistenceError(f"audit append failed: {exc}") from exc

    def verify_audit_chain(self) -> tuple[bool, int]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT sequence, timestamp, event_type, payload_json, previous_hash, event_hash "
                    "FROM audit_events ORDER BY sequence"
                ).fetchall()
            previous_hash = "0" * 64
            for row in rows:
                if row["previous_hash"] != previous_hash:
                    return False, len(rows)
                material = _canonical_json(
                    [row["timestamp"], row["event_type"], row["payload_json"], previous_hash]
                ).encode("utf-8")
                expected = hashlib.sha256(material).hexdigest()
                if expected != row["event_hash"]:
                    return False, len(rows)
                previous_hash = expected
            return True, len(rows)
        except sqlite3.Error as exc:
            raise PersistenceError(f"audit verification failed: {exc}") from exc

    def latch_daily_loss(
        self, session_id: str, reason: str, limit_usd: Decimal = DAILY_LOSS_LIMIT_USD
    ) -> PersistedSessionRisk:
        if not session_id.strip() or not reason.strip():
            raise ValueError("session_id and reason are required")
        if limit_usd != DAILY_LOSS_LIMIT_USD or not limit_usd.is_finite():
            raise ValueError("daily loss limit is fixed at USD 2.50")
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM session_risk WHERE session_id=?", (session_id,)
                ).fetchone()
                if row is None:
                    conn.execute(
                        """INSERT INTO session_risk
                           (session_id, limit_usd, latched, reason, updated_at)
                           VALUES (?, '2.50', 1, ?, ?)""",
                        (session_id, reason, _utc_now()),
                    )
                    self._append_audit_tx(
                        conn, "DAILY_LOSS_LATCHED",
                        {"session_id": session_id, "limit_usd": "2.50", "reason": reason},
                    )
                elif not row["latched"]:
                    conn.execute(
                        "UPDATE session_risk SET latched=1, reason=?, updated_at=? WHERE session_id=?",
                        (reason, _utc_now(), session_id),
                    )
                    self._append_audit_tx(
                        conn, "DAILY_LOSS_LATCHED",
                        {"session_id": session_id, "limit_usd": "2.50", "reason": reason},
                    )
                row = conn.execute(
                    "SELECT * FROM session_risk WHERE session_id=?", (session_id,)
                ).fetchone()
            return PersistedSessionRisk(
                row["session_id"], Decimal(row["limit_usd"]), bool(row["latched"]),
                row["reason"], row["updated_at"],
            )
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not persist daily loss latch: {exc}") from exc

    def get_session_risk(self, session_id: str) -> PersistedSessionRisk | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM session_risk WHERE session_id=?", (session_id,)
                ).fetchone()
            if row is None:
                return None
            return PersistedSessionRisk(
                row["session_id"], Decimal(row["limit_usd"]), bool(row["latched"]),
                row["reason"], row["updated_at"],
            )
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not read session risk: {exc}") from exc

    def register_intent(
        self,
        session_id: str,
        intent_key: str,
        payload: Mapping[str, Any],
        revision: int = 0,
    ) -> PersistedIntent:
        if not session_id.strip() or not intent_key.strip():
            raise ValueError("session_id and intent_key are required")
        payload_json = _canonical_json(_redact(payload))
        client_id = deterministic_client_order_id(
            session_id, "phase1j", intent_key, str(payload.get("order_role", "entry")), revision
        )
        try:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT * FROM order_intents WHERE client_order_id=?", (client_id,)
                ).fetchone()
                if existing:
                    if existing["payload_json"] != payload_json:
                        raise IntentConflict("client order ID already exists with different payload")
                    row = existing
                else:
                    created = _utc_now()
                    conn.execute(
                        """INSERT INTO order_intents
                           (client_order_id, session_id, intent_key, payload_json, status, created_at)
                           VALUES (?, ?, ?, ?, 'INTENT_RECORDED', ?)""",
                        (client_id, session_id, intent_key, payload_json, created),
                    )
                    self._append_audit_tx(
                        conn, "ORDER_INTENT_RECORDED",
                        {"client_order_id": client_id, "session_id": session_id,
                         "intent_key": intent_key, "payload": json.loads(payload_json)},
                    )
                    row = conn.execute(
                        "SELECT * FROM order_intents WHERE client_order_id=?", (client_id,)
                    ).fetchone()
            return PersistedIntent(
                row["client_order_id"], row["session_id"], row["intent_key"],
                row["payload_json"], row["status"], row["created_at"],
            )
        except IntentConflict:
            raise
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not persist order intent: {exc}") from exc

    def update_intent_status(self, client_order_id: str, status: str) -> None:
        if not _CLIENT_ID_RE.fullmatch(client_order_id):
            raise ValueError("invalid client order ID")
        if status not in {
            "INTENT_RECORDED", "SUBMISSION_UNKNOWN", "EXCHANGE_CONFIRMED",
            "CANCELLED", "FILLED", "REJECTED", "RECONCILIATION_BLOCKED",
        }:
            raise ValueError("unsupported intent status")
        allowed = {
            "INTENT_RECORDED": {"SUBMISSION_UNKNOWN", "EXCHANGE_CONFIRMED", "REJECTED", "RECONCILIATION_BLOCKED"},
            "SUBMISSION_UNKNOWN": {"EXCHANGE_CONFIRMED", "CANCELLED", "FILLED", "REJECTED", "RECONCILIATION_BLOCKED"},
            "EXCHANGE_CONFIRMED": {"CANCELLED", "FILLED", "RECONCILIATION_BLOCKED"},
            "CANCELLED": {"RECONCILIATION_BLOCKED"},
            "FILLED": {"RECONCILIATION_BLOCKED"},
            "REJECTED": {"RECONCILIATION_BLOCKED"},
            "RECONCILIATION_BLOCKED": set(),
        }
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT session_id, status FROM order_intents WHERE client_order_id=?",
                    (client_order_id,),
                ).fetchone()
                if row is None:
                    raise PersistenceError("unknown client order ID")
                if status != row["status"] and status not in allowed[row["status"]]:
                    raise PersistenceError(
                        f"illegal intent status transition: {row['status']} -> {status}"
                    )
                conn.execute(
                    "UPDATE order_intents SET status=? WHERE client_order_id=?",
                    (status, client_order_id),
                )
                self._append_audit_tx(
                    conn, "ORDER_INTENT_STATUS_CHANGED",
                    {"client_order_id": client_order_id, "session_id": row["session_id"],
                     "from_status": row["status"], "to_status": status},
                )
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not update intent status: {exc}") from exc

    def list_intents(self, session_id: str) -> tuple[PersistedIntent, ...]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM order_intents WHERE session_id=? ORDER BY created_at, client_order_id",
                    (session_id,),
                ).fetchall()
            return tuple(
                PersistedIntent(
                    row["client_order_id"], row["session_id"], row["intent_key"],
                    row["payload_json"], row["status"], row["created_at"],
                )
                for row in rows
            )
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not list intents: {exc}") from exc
