"""43 tests for the retail ops assistant. Stdlib only, seeded, deterministic."""

import os
import sqlite3

import pytest

from retail import audit as audit_mod
from retail import demand as demand_mod
from retail import demo_helpers, sop_rag, text2sql, views
from retail import inventory as inv
from retail import orchestrator as orch_mod
from retail import replenishment as repl

SOPS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "docs", "sops")


@pytest.fixture()
def conn():
    c = inv.connect()
    views.bootstrap(c, seed=42)
    yield c
    c.close()


@pytest.fixture()
def agent(conn):
    return orch_mod.PlannerAgent(conn, SOPS_DIR)


# ---------------------------------------------------------------- inventory
def test_seed_is_deterministic():
    a, b = inv.connect(), inv.connect()
    inv.seed_demo_data(a, seed=42)
    inv.seed_demo_data(b, seed=42)
    assert inv.row_counts(a) == inv.row_counts(b)
    assert inv.row_counts(a)["stores"] == 8


def test_stockout_anchor(conn):
    rows = conn.execute(
        "SELECT store_id, on_hand FROM inventory WHERE sku='SKU-BEANS-001' "
        "AND store_id IN ('S-001','S-002','S-003')"
    ).fetchall()
    assert len(rows) == 3
    assert all(r["on_hand"] == 0 for r in rows)


def test_returns_abuse_anchor(conn):
    row = conn.execute(
        "SELECT * FROM v_returns_watch WHERE customer_id='CUST-ABUSE-99'"
    ).fetchone()
    assert row is not None
    assert row["return_events"] == 14
    assert row["suspicious_events"] == 10


def test_slow_supplier_anchor(conn):
    row = conn.execute(
        "SELECT * FROM suppliers WHERE supplier_id='SUP-SLOW-07'").fetchone()
    assert row["lead_time_days"] == 21
    assert row["on_time_rate"] == pytest.approx(0.82)


def test_overstock_anchor(conn):
    row = conn.execute(
        "SELECT on_hand FROM inventory WHERE store_id='S-004' "
        "AND sku='SKU-PARKA-009'").fetchone()
    assert row["on_hand"] == 400


# --------------------------------------------------------------- gateway
def test_select_over_view_ok(conn):
    rows = views.run_query(conn, "SELECT * FROM v_supplier_risk")
    assert len(rows) == 6
    assert any(r["supplier_id"] == "SUP-SLOW-07" and r["risk_band"] == "HIGH"
               for r in rows)


def test_non_select_denied(conn):
    with pytest.raises(views.SecurityError) as exc:
        views.run_query(conn, "DELETE FROM v_stock_status")
    assert exc.value.rule_id == "SEC-SELECT-01"


def test_write_keyword_denied(conn):
    with pytest.raises(views.SecurityError) as exc:
        views.run_query(conn, "SELECT update FROM v_stock_status")
    assert exc.value.rule_id == "SEC-WRITE-02"


def test_unknown_table_denied(conn):
    with pytest.raises(views.SecurityError) as exc:
        views.run_query(conn, "SELECT * FROM stores")
    assert exc.value.rule_id == "SEC-VIEW-03"


def test_auto_limit_cap(conn):
    rows = views.run_query(conn, "SELECT * FROM v_stock_status")
    assert len(rows) == views.MAX_LIMIT == 100  # 192 rows exist uncapped


def test_string_literal_no_false_positive(conn):
    rows = views.run_query(
        conn, "SELECT * FROM v_stock_status WHERE store_name = 'insert'")
    assert rows == []  # no SecurityError raised for a quoted word


# ---------------------------------------------------------------- text2sql
def test_detect_all_five_intents():
    cases = {
        "which SKUs are at risk of stockout?": "stockout_risk",
        "show me overstock for markdown": "overstock_markdown",
        "flag returns abuse this month": "returns_abuse",
        "did the promotion lift sales?": "promotion_impact",
        "any supplier lead time risk?": "supplier_leadtime",
    }
    for question, expected in cases.items():
        assert expected in text2sql.detect_intents(question), question


def test_run_stockout_includes_anchor(conn):
    result = text2sql.run(conn, "stockout_risk")
    skus = {r["sku"] for r in result["rows"]}
    assert "SKU-BEANS-001" in skus
    assert all(r["days_of_cover"] < r["lead_time_days"] for r in result["rows"])


def test_run_overstock_includes_parka(conn):
    result = text2sql.run(conn, "overstock_markdown")
    assert any(r["sku"] == "SKU-PARKA-009" and r["days_of_cover"] > 90
               for r in result["rows"])


def test_run_returns_abuse_flags_customer(conn):
    result = text2sql.run(conn, "returns_abuse")
    assert any(r["customer_id"] == "CUST-ABUSE-99" for r in result["rows"])


def test_run_promo_impact(conn):
    result = text2sql.run(conn, "promotion_impact")
    assert any(r["sku"] == "SKU-HEADPH-014" and r["on_promo"] == 1
               for r in result["rows"])


def test_run_supplier_leadtime(conn):
    result = text2sql.run(conn, "supplier_leadtime")
    assert result["rows"][0]["supplier_id"] == "SUP-SLOW-07"  # worst on-time first


def test_unknown_intent_raises(conn):
    with pytest.raises(text2sql.UnknownIntent):
        text2sql.run_question(conn, "explain quantum chromodynamics")


def test_build_sql_unknown_intent():
    with pytest.raises(text2sql.UnknownIntent):
        text2sql.build_sql("nope_not_an_intent")


def test_retry_succeeds_after_one_failure(conn, monkeypatch):
    original = views.run_query
    calls = {"n": 0}

    def flaky(c, sql, params=()):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("boom")
        return original(c, sql, params)

    monkeypatch.setattr(views, "run_query", flaky)
    result = text2sql.run(conn, "supplier_leadtime")
    assert "simplified retry" in result["sql"]
    assert len(result["rows"]) == 6


def test_escalation_after_retry_fails(conn, monkeypatch):
    def always_fail(c, sql, params=()):
        raise sqlite3.OperationalError("down")

    monkeypatch.setattr(views, "run_query", always_fail)
    with pytest.raises(text2sql.EscalationNeeded):
        text2sql.run(conn, "stockout_risk")


# ------------------------------------------------------------------ sop rag
@pytest.fixture()
def sop_index():
    return sop_rag.SopIndex(sop_rag.load_chunks(SOPS_DIR))


def test_returns_query_cites_sop01(sop_index):
    answer = sop_index.answer("what are the returns abuse thresholds?")
    assert answer["found"]
    assert any("sop-01-returns-policy.md" in c for c in answer["citations"])


def test_markdown_query_cites_sop02(sop_index):
    answer = sop_index.answer("when should we mark down overstock?")
    assert answer["found"]
    assert any("sop-02-markdown-playbook.md" in c for c in answer["citations"])


def test_unrelated_query_not_found(sop_index):
    answer = sop_index.answer("quantum chromodynamics banana")
    assert not answer["found"]
    assert "could not find" in answer["message"].lower()


def test_chunks_carry_source_and_section(sop_index):
    assert len(sop_index.chunks) >= 8
    assert all(c["source"].endswith(".md") and c["section"] for c in sop_index.chunks)


# -------------------------------------------------------------------- demand
def test_fake_demand_deterministic():
    a = demand_mod.FakeDemand().get_signal("S-001", "SKU-BEANS-001")
    b = demand_mod.FakeDemand().get_signal("S-001", "SKU-BEANS-001")
    assert a == b
    assert a["ok"] is True
    assert 0.5 <= a["demand_index"] <= 2.0
    assert a["drivers"]


def test_live_backend_failure_is_gap():
    backend = demand_mod.LiveDemandBackend("http://127.0.0.1:1/feed", timeout=2)
    signal = backend.get_signal("S-001", "SKU-BEANS-001")
    assert signal["ok"] is False
    assert signal["demand_index"] is None
    assert "unavailable" in signal["gap"]


# ------------------------------------------------------------- orchestrator
def test_ask_stockout(agent):
    result = agent.ask("Which SKUs are at risk of stockout?")
    assert result["intents"] == ["stockout_risk"]
    assert result["row_counts"]["stockout_risk"] >= 3
    assert result["tier"] == "T4"  # beans at zero cover
    assert "SKU-BEANS-001" in result["answer"] or "stockout_risk" in result["answer"]


def test_ask_multi_intent_fanout(agent):
    result = agent.ask("Show stockout risk and returns abuse.")
    assert set(result["intents"]) == {"stockout_risk", "returns_abuse"}
    assert set(result["row_counts"]) == {"stockout_risk", "returns_abuse"}
    assert "CUST-ABUSE-99" in result["answer"]


def test_ask_sop_cited(agent):
    result = agent.ask("What are the returns abuse thresholds in the SOP?")
    assert result["citations"], "expected SOP citations"
    assert any("sop-01-returns-policy.md" in c for c in result["citations"])


def test_ask_markdown_is_gated(agent):
    result = agent.ask("Mark down the overstocked parkas.")
    assert result["gate_token"] and result["gate_token"].startswith("GATE-")
    pending = agent.gate.pending()
    assert any(g["token"] == result["gate_token"] and g["action"] == "markdown"
               for g in pending)
    assert "confirmation" in result["answer"].lower()


def test_ask_purchase_order_gates_high_value(agent):
    result = agent.ask("Raise a purchase order for the SKUs at risk of stockout.")
    assert result["gate_token"] and result["gate_token"].startswith("GATE-")
    pending = agent.gate.pending()
    assert any(g["token"] == result["gate_token"] and g["action"] == "purchase_order"
               for g in pending)


def test_ask_unknown_graceful(agent):
    result = agent.ask("Explain quantum chromodynamics.")
    assert result["intents"] == []
    assert "couldn't map" in result["answer"]
    assert result["audit_events"] >= 2


def test_ask_audits_everything(agent):
    result = agent.ask("Any supplier lead time risk?")
    assert result["audit_events"] >= 3
    assert agent.audit.verify_chain()
    actions = {e["action"] for e in agent.audit.events()}
    assert {"question_received", "tool.inventory", "answer_synthesized"} <= actions


def test_ask_demand_gap_reported(agent, monkeypatch):
    monkeypatch.setattr(
        agent.demand, "get_signal",
        lambda s, k: {"ok": False, "gap": "demand signal unavailable: timeout",
                      "drivers": [], "demand_index": None,
                      "store_id": s, "sku": k},
    )
    result = agent.ask("Which SKUs are at risk of stockout?")
    assert "gap" in result["answer"].lower()


# ------------------------------------------------------------ replenishment
def test_tier_boundaries():
    assert repl.assess_tier([{"days_of_cover": 1.0}]) == "T4"
    assert repl.assess_tier([{"days_of_cover": 5.0}]) == "T3"
    assert repl.assess_tier([{"days_of_cover": 30.0}]) == "T2"
    assert repl.assess_tier([]) == "T1"


def test_tier_returns_suspicious():
    assert repl.assess_tier([], [{"suspicious_events": 12}]) == "T3"
    assert repl.assess_tier([], [{"suspicious_events": 5}]) == "T2"


def test_requires_gate_thresholds():
    assert repl.ConfirmationGate.requires_gate("purchase_order", 5000.01)
    assert not repl.ConfirmationGate.requires_gate("purchase_order", 4999.99)
    assert repl.ConfirmationGate.requires_gate("markdown")
    assert not repl.ConfirmationGate.requires_gate("question")


def test_gate_approve_flow():
    gate = repl.ConfirmationGate()
    token = gate.request("purchase_order", "PO for beans", {"value": 9000})
    assert len(gate.pending()) == 1
    record = gate.approve(token)
    assert record["status"] == "approved"
    assert gate.pending() == []
    assert gate.get(token)["status"] == "approved"


def test_gate_deny_flow():
    gate = repl.ConfirmationGate()
    token = gate.request("markdown", "Markdown parkas", {})
    record = gate.deny(token, reason="too early")
    assert record["status"] == "denied"
    with pytest.raises(KeyError):
        gate.approve(token)  # already decided


# --------------------------------------------------------------------- audit
def test_audit_chain_verifies():
    log = audit_mod.AuditLog()
    log.record("planner", "question_received", {"q": "hi"})
    log.record("planner", "answer_synthesized", {"tier": "T1"})
    assert log.verify_chain()


def test_audit_tamper_detected():
    log = audit_mod.AuditLog()
    log.record("planner", "gate.requested", {"token": "GATE-0001"})
    log._events[0]["details"]["token"] = "GATE-9999"
    assert not log.verify_chain()


def test_audit_hash_linking():
    log = audit_mod.AuditLog()
    first = log.record("a", "one")
    second = log.record("a", "two")
    assert second["prev_hash"] == first["hash"]
    assert first["prev_hash"] == "GENESIS"


# -------------------------------------------------------------- demo helpers
def _sample_result():
    return {
        "answer": "Worst cover: beans at Downtown LA.",
        "citations": ["sop-01-returns-policy.md §Abuse thresholds"],
        "tier": "T4",
        "gate_token": "GATE-0001",
    }


def test_format_answer():
    text = demo_helpers.format_answer(_sample_result())
    assert "Worst cover" in text
    assert "sop-01-returns-policy.md" in text
    assert "GATE-0001" in text


def test_pending_gates():
    gate = repl.ConfirmationGate()
    token = gate.request("markdown", "Markdown parkas", {})
    pending = demo_helpers.pending_gates(gate)
    assert len(pending) == 1
    assert pending[0]["token"] == token
    assert pending[0]["status"] == "pending"


def test_gate_action_payload():
    gate = repl.ConfirmationGate()
    token = gate.request("purchase_order", "PO", {"value": 9000})
    payload = demo_helpers.gate_action_payload(gate, token)
    assert payload["payload"] == {"value": 9000}
    assert demo_helpers.gate_action_payload(gate, "GATE-9999") is None


def test_recent_audit_rows():
    log = audit_mod.AuditLog()
    log.record("planner", "question_received", {})
    rows = demo_helpers.recent_audit_rows(log, n=5)
    assert len(rows) == 1
    assert set(rows[0]) == {"seq", "actor", "action", "hash"}
    assert len(rows[0]["hash"]) == 12


# --- quote hygiene (added after review: a raw markdown heading leaked into answers) ---
def test_sop_excerpts_have_no_markdown_and_end_on_sentences():
    import os

    from retail import sop_rag
    here = os.path.dirname(os.path.abspath(__file__))
    index = sop_rag.SopIndex(sop_rag.load_chunks(os.path.join(here, "..", "docs", "sops")))
    for q in ["stockout escalation", "returns abuse thresholds", "markdown playbook", "replenishment purchase orders"]:
        ans = index.answer(q)
        assert ans["found"], q
        for ex in ans["excerpts"]:
            assert "#" not in ex["text"], ex
            assert "\n" not in ex["text"], ex
            assert ex["text"].rstrip().endswith((".", "!", "?", ")")), ex


def test_clean_text_strips_markdown():
    from retail.sop_rag import clean_text
    assert clean_text("# Title\n\n- **Bold** item\n  wraps here.") == "Bold item wraps here."


def test_planner_answers_never_cut_a_quote_mid_sentence():
    import os
    import re

    from retail import inventory, orchestrator, views
    here = os.path.dirname(os.path.abspath(__file__))
    conn = inventory.connect()
    views.bootstrap(conn, seed=42)
    agent = orchestrator.PlannerAgent(conn, os.path.join(here, "..", "docs", "sops"))
    for q in ["Who is abusing our returns policy?", "What should we mark down?"]:
        for line in agent.ask(q)["answer"].splitlines():
            if re.match(r"- sop-\d+", line):
                assert line.rstrip().endswith((".", "!", "?", ")")), line
