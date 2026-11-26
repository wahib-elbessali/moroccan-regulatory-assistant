import pytest

from src.agents.orchestrator.reformulation_guard import (
    keeps_meaning,
    question_parts,
)

Q1 = "ما هو المبلغ الشهري للدعم المباشر المخصص للنساء الأرامل في وضعية هشة عن كل طفل يتيم؟"
Q1_BAD = "المساعدات المباشرة المخصصة للعوانس في وضعية ضعيفة عن كل أرملة"
Q1_OK = "الدعم المباشر الشهري المخصص للنساء الأرامل في وضعية هشة عن كل طفل يتيم مبلغ"

Q2 = "ما هي الوثائق التي يجب على الأرملة الإدلاء بها لإثبات وضعية الهشاشة، ولمن يقدم طلب الاستفادة من الدعم؟"
Q2_BAD = "ما هي المستندات المطلوبة من الأرملة لإثبات حالة الضعف القانوني؟"
Q2_OK = (
    "الوثائق المطلوبة من الأرملة لإثبات وضعية الهشاشة والجهة التي يقدم لها طلب الاستفادة من الدعم"
)


@pytest.mark.parametrize("q,bad", [(Q1, Q1_BAD), (Q2, Q2_BAD)])
def test_organizer_bad_reformulations_are_rejected(q, bad):
    assert not keeps_meaning(q, bad)


@pytest.mark.parametrize("q,ok", [(Q1, Q1_OK), (Q2, Q2_OK)])
def test_faithful_reformulations_are_accepted(q, ok):
    assert keeps_meaning(q, ok)


def test_two_part_question_is_split():
    assert len(question_parts(Q2)) == 2


def test_one_part_question_with_a_question_word_is_not_split():
    q = (
        "حسب المادة 16 من مشروع القانون الافتراضي بشأن حماية المعطيات الشخصية، "
        "ما هو الأجل الأقصى لإعداد خطة التصحيح؟"
    )
    assert len(question_parts(q)) == 1
