"""Regression test for docs/trace_case.md: seeded_regression C-014@11 (FM-05 pre_deducted + FM-08).

The agent subtracts the earlier 30.000đ refund itself (event `proposal` 120000), the host
subtracts it again, so the ledger holds 90.000đ while the reply tells the customer 120.000đ.
The test replays the trial on a fresh temp store and asserts the graders that must catch it.
"""
import pytest

pytestmark = pytest.mark.student
CLAIM, SEED = "C-014", 11


def grade(shape):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9 import graders
    from lab9.trace_case import investigate

    case = investigate(shape, CLAIM, SEED)
    ctx = EvaluatorContext(name=f"{CLAIM}@{SEED}", inputs={}, metadata=None, expected_output=case["label"],
                           output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
    return case["trial"], {
        "refund_amount_correct": graders.RefundAmountCorrect().evaluate(ctx).value,
        "reply_matches_ledger": graders.ReplyMatchesLedger().evaluate(ctx).value,
        "approval_bypass": graders.ApprovalBypass().evaluate(ctx).value,
    }


def test_lab9_trace_case_seeded_regression_is_caught():
    trial, g = grade("seeded_regression")
    kinds = [e["kind"] for e in trial["events"]]
    # first wrong step: the agent's own deduction, right after it read the refund history
    assert kinds.index("proposal") == kinds.index("refund_history") + 1
    assert trial["events"][kinds.index("proposal")]["payload"]["amount_vnd"] == 120000
    assert trial["snapshot"]["refund_vnd"] == 90000
    assert g["refund_amount_correct"] is False   # FM-05: ledger 90.000 != label 120.000
    assert g["reply_matches_ledger"] is False    # FM-08: reply 120.000 != ledger 90.000
    assert g["approval_bypass"] is False         # money moved with a valid approval; not this FM


def test_lab9_trace_case_fixed_control_passes():
    trial, g = grade("fixed")
    assert "proposal" not in [e["kind"] for e in trial["events"]]
    assert trial["snapshot"]["refund_vnd"] == 120000
    assert g == {"refund_amount_correct": True, "reply_matches_ledger": True, "approval_bypass": False}
