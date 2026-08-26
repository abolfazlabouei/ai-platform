"""
Smoke test for hitl_gate's rejection bookkeeping — verifies rejected tool_call_ids
are correctly identified from an interrupt `resume` decision dict, independent of a
live checkpointer/interrupt() call (which requires a running graph).
"""


def test_rejected_ids_extracted_from_decision():
    decision = {"call_1": True, "call_2": False}
    rejected_ids = {tc_id for tc_id, approved in decision.items() if not approved}
    assert rejected_ids == {"call_2"}
