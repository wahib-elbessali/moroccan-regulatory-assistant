# Offline tests with the real examples of the organizer's evaluation (p1-02, p3-08, p6-03).
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.agents.orchestrator import graph
from src.agents.orchestrator.prompts import PLAN_SYSTEM
from src.agents.orchestrator.reformulation_guard import merge_needless_split

P1_02 = "ما هي الوضعية القانونية لجنسية الطفل المولود في المغرب من أبوين مجهولين؟"
P6_03 = "ما هو المبلغ الشهري للدعم المباشر المخصص للنساء الأرامل في وضعية هشة عن كل طفل يتيم؟"
P3_08 = (
    "Qui préside la commission chargée de statuer sur les demandes de naturalisation, "
    "et qui en fait partie ?"
)
TWO_PARTS = "ما هي الوثائق التي يجب على الأرملة الإدلاء بها، ولمن يقدم طلب الدعم؟"
FR_ONE = "Quel est le montant mensuel du soutien direct pour les veuves ?"


@pytest.mark.parametrize(
    "question,plan",
    [
        (P1_02, ["ما هي جنسية الطفل المولود في المغرب؟", "ما وضعية الأبوين المجهولين؟"]),
        (
            P6_03,
            ["ما هو المبلغ الشهري للدعم المباشر؟", "من هي الأرملة في وضعية هشة؟", "الطفل اليتيم"],
        ),
    ],
)
def test_simple_arabic_question_is_searched_once_as_typed(question, plan):
    assert merge_needless_split(question, plan) == [question]


def test_simple_french_question_keeps_one_sub_question():
    plan = ["ما هو المبلغ الشهري للدعم؟", "من هي الأرملة؟"]
    assert merge_needless_split(FR_ONE, plan) == plan[:1]


@pytest.mark.parametrize("question", [TWO_PARTS, P3_08, "ما هي شروط الدعم والوثائق المطلوبة؟"])
def test_multi_part_question_stays_split(question):
    plan = ["ما هي الوثائق المطلوبة للدعم؟", "ما هي شروط الدعم؟"]
    assert merge_needless_split(question, plan) == plan


def test_plan_prompt_keeps_acronyms():
    assert "RGPD" in PLAN_SYSTEM and "never translate or expand" in PLAN_SYSTEM


def _passage(cid, score):
    return SimpleNamespace(chunk=SimpleNamespace(chunk_id=cid, title=cid), score=score)


class FakeRetrieval:
    def __init__(self, results):
        self.results, self.queries = results, []

    def search(self, query, ctx, top_k=None):
        self.queries.append((query, ctx))
        return self.results.get(query, [])


def _search(monkeypatch, question, query, results, iteration=1):
    retrieval = FakeRetrieval(results)
    monkeypatch.setattr(graph, "get_retrieval", lambda: retrieval)
    state = {
        "question": question,
        "query": query,
        "ctx": SimpleNamespace(request_id=uuid4()),
        "current_index": 0,
        "iteration": iteration,
        "tokens": 0,
        "emit": lambda e: None,
    }
    return graph.search_node(state)["last_passages"], retrieval


def test_french_question_is_also_searched_as_typed(monkeypatch):
    bad = "طلبات الإقامة"
    results = {bad: [_passage("wrong", 0.9), _passage("both", 0.2)],
               P3_08: [_passage("right", 0.5), _passage("both", 0.7)]}  # fmt: skip
    found, retrieval = _search(monkeypatch, P3_08, bad, results)
    assert [p.chunk.chunk_id for p in found] == ["right", "wrong", "both"]
    assert found[2].score == 0.7
    assert [q for q, _ in retrieval.queries] == [bad, P3_08]
    assert retrieval.queries[0][1] is retrieval.queries[1][1]  # same ctx (P3-03)


@pytest.mark.parametrize("question,iteration", [(P6_03, 1), (P3_08, 2)])
def test_no_extra_search_for_arabic_or_after_reformulation(monkeypatch, question, iteration):
    _, retrieval = _search(monkeypatch, question, "استعلام", {}, iteration)
    assert len(retrieval.queries) == 1
