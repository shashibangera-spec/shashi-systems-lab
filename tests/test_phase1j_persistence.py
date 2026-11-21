from decimal import Decimal
import sqlite3

import pytest

from shashi_engine.phase1j_persistence import (
    DAILY_LOSS_LIMIT_USD,
    DurableSafetyStore,
    IntentConflict,
    PersistenceError,
    deterministic_client_order_id,
)


def store(tmp_path):
    return DurableSafetyStore(tmp_path / "state" / "phase1j.sqlite3")


def test_database_created_only_when_store_explicitly_constructed(tmp_path):
    path = tmp_path / "not-created.sqlite3"
    assert not path.exists()
    DurableSafetyStore(path)
    assert path.exists()


def test_daily_loss_threshold_is_fixed():
    assert DAILY_LOSS_LIMIT_USD == Decimal("2.50")


def test_latched_session_persists_after_store_reopen(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    first = DurableSafetyStore(db_path)
    latched = first.latch_daily_loss("2026-11-22", "DAILY_LOSS_LIMIT_REACHED")
    assert latched.latched
    reopened = DurableSafetyStore(db_path)
    restored = reopened.get_session_risk("2026-11-22")
    assert restored is not None
    assert restored.latched
    assert restored.limit_usd == Decimal("2.50")
    assert restored.reason == "DAILY_LOSS_LIMIT_REACHED"


def test_latch_is_idempotent_and_cannot_be_cleared_by_second_call(tmp_path):
    db = store(tmp_path)
    first = db.latch_daily_loss("session", "LIMIT")
    second = db.latch_daily_loss("session", "OTHER")
    assert second.latched
    assert second.reason == first.reason
    assert db.get_session_risk("session").latched


@pytest.mark.parametrize("limit", [Decimal("0"), Decimal("2.49"), Decimal("2.51")])
def test_cannot_override_approved_loss_limit(tmp_path, limit):
    with pytest.raises(ValueError):
        store(tmp_path).latch_daily_loss("session", "reason", limit)


def test_different_session_ids_have_separate_latches(tmp_path):
    db = store(tmp_path)
    db.latch_daily_loss("day-1", "LIMIT")
    assert db.get_session_risk("day-2") is None


def test_deterministic_client_order_id_is_stable_and_role_specific():
    args = ("session", "strategy", "signal", "entry", 0)
    assert deterministic_client_order_id(*args) == deterministic_client_order_id(*args)
    assert deterministic_client_order_id(*args) != deterministic_client_order_id(
        "session", "strategy", "signal", "stop", 0
    )


@pytest.mark.parametrize(
    "parts",
    [
        ("", "strategy", "signal", "entry", 0),
        ("session", "", "signal", "entry", 0),
        ("session", "strategy", "", "entry", 0),
        ("session", "strategy", "signal", "", 0),
        ("session", "strategy", "signal", "entry", -1),
    ],
)
def test_client_order_id_rejects_missing_components_or_negative_revision(parts):
    with pytest.raises(ValueError):
        deterministic_client_order_id(*parts)


def test_order_intent_persists_and_reloads_with_same_client_id(tmp_path):
    db_path = tmp_path / "intent.sqlite3"
    first = DurableSafetyStore(db_path)
    created = first.register_intent(
        "session", "signal-001", {"order_role": "entry", "side": "buy", "lots": 2}
    )
    second = DurableSafetyStore(db_path)
    loaded = second.list_intents("session")
    assert len(loaded) == 1
    assert loaded[0].client_order_id == created.client_order_id
    assert loaded[0].status == "INTENT_RECORDED"


def test_duplicate_intent_is_idempotent(tmp_path):
    db = store(tmp_path)
    payload = {"order_role": "entry", "side": "buy", "lots": 2}
    one = db.register_intent("session", "signal", payload)
    two = db.register_intent("session", "signal", payload)
    assert one.client_order_id == two.client_order_id
    assert len(db.list_intents("session")) == 1


def test_same_deterministic_id_with_different_payload_is_blocked(tmp_path):
    db = store(tmp_path)
    db.register_intent("session", "signal", {"order_role": "entry", "side": "buy"})
    with pytest.raises(IntentConflict):
        db.register_intent("session", "signal", {"order_role": "entry", "side": "sell"})


def test_intent_status_changes_are_audited(tmp_path):
    db = store(tmp_path)
    intent = db.register_intent("session", "signal", {"order_role": "entry"})
    db.update_intent_status(intent.client_order_id, "SUBMISSION_UNKNOWN")
    assert db.list_intents("session")[0].status == "SUBMISSION_UNKNOWN"
    ok, count = db.verify_audit_chain()
    assert ok and count == 2


@pytest.mark.parametrize(
    "status",
    ["", "OPEN", "SUBMIT", "CANCEL_PENDING", "whatever"],
)
def test_unknown_intent_status_is_rejected(tmp_path, status):
    db = store(tmp_path)
    intent = db.register_intent("session", "signal", {"order_role": "entry"})
    with pytest.raises(ValueError):
        db.update_intent_status(intent.client_order_id, status)


def test_audit_log_is_append_only_at_sqlite_layer(tmp_path):
    db = store(tmp_path)
    db.append_audit("BOOT", {"safe": "value"})
    with sqlite3.connect(db.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE audit_events SET event_type='ALTERED' WHERE sequence=1")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM audit_events WHERE sequence=1")


def test_audit_hash_chain_verifies_across_restart(tmp_path):
    path = tmp_path / "audit.sqlite3"
    DurableSafetyStore(path).append_audit("BOOT", {"sequence": 1})
    DurableSafetyStore(path).append_audit("RECONCILIATION", {"positions": []})
    ok, count = DurableSafetyStore(path).verify_audit_chain()
    assert ok and count == 2


def test_audit_payload_redacts_secret_fields_recursively(tmp_path):
    db = store(tmp_path)
    db.append_audit(
        "AUTH_DIAGNOSTIC",
        {"api_key": "do-not-store", "nested": {"api_secret": "also-secret", "ok": True}},
    )
    with sqlite3.connect(db.path) as conn:
        payload = conn.execute("SELECT payload_json FROM audit_events").fetchone()[0]
    assert "do-not-store" not in payload
    assert "also-secret" not in payload
    assert payload.count("[REDACTED]") == 2


def test_audit_rejects_unsupported_objects_instead_of_stringifying(tmp_path):
    with pytest.raises(PersistenceError):
        store(tmp_path).append_audit("BAD", {"object": object()})


def test_audit_chain_detects_tampered_payload_if_trigger_is_removed(tmp_path):
    db = store(tmp_path)
    db.append_audit("BOOT", {"value": "original"})
    with sqlite3.connect(db.path) as conn:
        conn.execute("DROP TRIGGER audit_events_no_update")
        conn.execute("UPDATE audit_events SET payload_json='{}' WHERE sequence=1")
    ok, count = db.verify_audit_chain()
    assert not ok and count == 1


def test_store_rejects_directory_as_database_path(tmp_path):
    with pytest.raises(PersistenceError):
        DurableSafetyStore(tmp_path)


def test_intent_records_do_not_contain_credentials(tmp_path):
    db = store(tmp_path)
    intent = db.register_intent(
        "session", "signal",
        {"order_role": "entry", "api_key": "key-secret", "api_secret": "secret-value"},
    )
    assert "key-secret" not in intent.payload_json
    assert "secret-value" not in intent.payload_json
