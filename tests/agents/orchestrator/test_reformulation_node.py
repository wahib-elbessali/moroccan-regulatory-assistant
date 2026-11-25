# tests/agents/orchestrator/test_reformulation_node.py  (offline, no Ollama)
from types import SimpleNamespace
from uuid import uuid4

from src.agents.orchestrator import graph
from src.agents.orchestrator.prompts import REFORMULATE_SYSTEM, reformulate_messages

Q1 = "ما هو المبلغ الشهري للدعم المباشر المخصص للنساء الأرامل في وضعية هشة عن كل طفل يتيم؟"
Q1_BAD = "المساعدات المباشرة المخصصة للعوانس في وضعية ضعيفة عن كل أرملة"
Q1_OK = "الدعم المباشر الشهري المخصص للنساء الأرامل في وضعية هشة عن كل طفل يتيم مبلغ"
Q2 = "ما هي الوثائق التي يجب على الأرملة الإدلاء بها لإثبات وضعية الهشاشة، ولمن يقدم طلب الاستفادة من الدعم؟"
Q2_BAD = "ما هي المستندات المطلوبة من الأرملة لإثبات حالة الضعف القانوني؟"


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, max_tokens=0):
        return self.reply

    def count_tokens(self, text):
        return 1


def _run(monkeypatch, question, reply, n_subs=1):
    monkeypatch.setattr(graph, "get_llm", lambda: FakeLLM(reply))
    events = []
    state = {
        "ctx": SimpleNamespace(request_id=uuid4()),
        "sub_questions": [question] * n_subs,
        "current_index": 0,
        "query": question,
        "tried": [question],
        "iteration": 1,
        "unanswered": 0,
        "tokens": 0,
        "emit": events.append,
    }
    return graph.reformulate_node(state), events


def test_prompt_has_the_two_rules():
    assert "never replace a legal term" in REFORMULATE_SYSTEM
    assert "Keep every part of the question" in REFORMULATE_SYSTEM


def test_messages_keep_question_and_tried_in_tags():
    m = reformulate_messages(Q1, ["a"])
    assert m[1]["content"].startswith("<question>") and "<tried>a</tried>" in m[1]["content"]


def test_organizer_example_1_bad_reformulation_is_rejected(monkeypatch):
    out, events = _run(monkeypatch, Q1, Q1_BAD)
    assert out["stop_sub"] is True and out["unanswered"] == 1 and not events


def test_organizer_example_2_bad_reformulation_is_rejected(monkeypatch):
    out, events = _run(monkeypatch, Q2, Q2_BAD)
    assert out["stop_sub"] is True and not events


def test_faithful_reformulation_is_kept(monkeypatch):
    out, events = _run(monkeypatch, Q1, Q1_OK)
    assert out["query"] == Q1_OK and out["iteration"] == 2 and len(events) == 1
