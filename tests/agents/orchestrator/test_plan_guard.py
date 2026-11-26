from src.agents.orchestrator.reformulation_guard import (
    complete_sub_questions,
    is_arabic,
    missing_parts,
)

Q2 = "ما هي الوثائق التي يجب على الأرملة الإدلاء بها لإثبات وضعية الهشاشة، ولمن يقدم طلب الاستفادة من الدعم؟"
# What the 7B really returned in the live test: the second part is gone.
PLAN_DROPPED = ["ما هي الوثائق التي يجب على الأرملة الإدلاء بها لإثبات وضعية الهشاشة"]
Q_ONE = "ما هي شروط الاستفادة من الدعم المباشر بموجب المرسوم رقم 2.14.791؟"
Q_FR = "Quels documents la veuve doit-elle fournir, et à qui présenter la demande ?"


def test_dropped_second_part_is_detected():
    assert missing_parts(Q2, PLAN_DROPPED) == ["ولمن يقدم طلب الاستفادة من الدعم"]


def test_dropped_part_is_added_back():
    out = complete_sub_questions(Q2, PLAN_DROPPED, max_n=3)
    assert out[0] == PLAN_DROPPED[0]
    assert len(out) == 2 and "لمن" in out[1] and "طلب" in out[1]


def test_complete_plan_is_untouched():
    plan = [PLAN_DROPPED[0], "لمن يقدم طلب الاستفادة من الدعم؟"]
    assert complete_sub_questions(Q2, plan, max_n=3) == plan


def test_single_part_question_is_untouched():
    plan = ["ما هي شروط الاستفادة من الدعم المباشر بموجب المرسوم رقم 2.14.791؟"]
    assert complete_sub_questions(Q_ONE, plan, max_n=3) == plan


def test_no_room_falls_back_to_original_question():
    assert complete_sub_questions(Q2, PLAN_DROPPED, max_n=1) == [Q2]


def test_french_question_is_not_checked():
    assert not is_arabic(Q_FR)
    assert missing_parts(Q_FR, ["ما هي الوثائق المطلوبة من الأرملة"]) == []


def test_placeholder_plan_for_single_part_question_is_untouched():
    # The existing graph tests use plans like ["q1", "q2"] for "سؤال مركب".
    assert complete_sub_questions("سؤال مركب", ["q1", "q2", "q3"], max_n=3) == ["q1", "q2", "q3"]
    assert missing_parts("سؤال عن القانون", ["q1"]) == []


# --- French questions -------------------------------------------------------------------------
from src.agents.orchestrator.reformulation_guard import (  # noqa: E402
    french_parts,
    is_french,
    missing_french_parts,
)

FR2 = (
    "Quels documents la veuve doit-elle fournir pour prouver sa situation de vulnérabilité, "
    "et à qui présenter la demande de soutien ?"
)
# What the 7B really returned: both parts merged, "to whom" became "how to submit".
FR2_MERGED = [
    "الأرملة ما هي الوثائق التي يجب عليها تقديمها لبرهان وضعية هشتها، وكيفية تقديم طلب الدعم المباشر؟"
]
FR1 = (
    "Quel est le montant mensuel du soutien direct pour les veuves en situation de "
    "vulnérabilité, par enfant orphelin ?"
)


def test_french_question_is_detected_and_split():
    assert is_french(FR2) and not is_french(Q2)
    assert len(french_parts(FR2)) == 2 and french_parts(FR2)[1].startswith("à qui")


def test_french_merged_plan_gets_the_who_part_back():
    out = complete_sub_questions(FR2, FR2_MERGED, max_n=3)
    assert out[0] == FR2_MERGED[0]
    assert len(out) == 2 and "لمن" in out[1] and "طلب" in out[1]


def test_french_plan_that_asks_to_whom_is_untouched():
    plan = ["ما هي الوثائق التي تقدمها الأرملة لإثبات وضعية هشة؟", "لمن تقدم طلب الدعم؟"]
    assert complete_sub_questions(FR2, plan, max_n=3) == plan


def test_french_single_part_question_is_untouched():
    plan = ["ما هو المبلغ الشهري من الدعم المباشر للأرامل في وضعية هشة؟"]
    assert complete_sub_questions(FR1, plan, max_n=3) == plan


def test_french_part_without_known_term_is_not_checked():
    q = "Quelle est la capitale du Maroc, et quel est son drapeau ?"
    assert missing_french_parts(q, ["عاصمة المغرب"]) == []


def test_french_no_room_falls_back_to_original_question():
    assert complete_sub_questions(FR2, FR2_MERGED, max_n=1) == [FR2]


def test_plan_prompt_has_the_who_where_when_rule():
    from src.agents.orchestrator.prompts import PLAN_SYSTEM

    assert "who, where, when or how much" in PLAN_SYSTEM
    assert "veuve = الأرملة" in PLAN_SYSTEM


def test_english_and_latin_darija_are_not_taken_for_french():
    en = "Which documents must the widow provide to prove vulnerability, and to whom should she submit the application?"
    darija = "chno homa l-wra9 li khas l-armla tjib bach t-tbet l-hachacha, w l-men t-9added talab?"
    assert not is_french(en) and not is_french(darija)
    assert complete_sub_questions(en, ["ما هي الوثائق المطلوبة من الأرملة"], max_n=3) == [
        "ما هي الوثائق المطلوبة من الأرملة"
    ]
    assert is_french(FR2) and is_french(FR1)
