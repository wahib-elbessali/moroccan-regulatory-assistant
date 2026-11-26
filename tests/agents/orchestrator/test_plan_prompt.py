# tests/agents/orchestrator/test_plan_prompt.py  (offline)
from src.agents.orchestrator.prompts import PLAN_SYSTEM, plan_messages


def test_plan_prompt_keeps_legal_terms_rule():
    assert "Keep every legal term of the question exactly as written" in PLAN_SYSTEM
    assert "الأرامل" in PLAN_SYSTEM and "وضعية هشة" in PLAN_SYSTEM
    assert "never drop a part" in PLAN_SYSTEM


def test_plan_messages_still_well_formed():
    m = plan_messages("سؤال", 3)
    assert "{max_sub_questions}" not in m[0]["content"] and "at most 3" in m[0]["content"]
    assert m[1]["content"] == "<question>سؤال</question>"
