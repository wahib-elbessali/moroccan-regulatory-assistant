"""Checks in code on claims the Juge accepted, with real answers of qwen2.5:3b (light mode).

Every case comes from the baseline run of the evaluation on the demo machine: the Juge had
accepted each of these claims, and the source texts are the articles as they are in the corpus.
"""

from __future__ import annotations

import json

import pytest

from src.agents.answer import real_writer
from src.agents.answer.checks import claim_problem
from src.core.contracts import AnswerStatus, Passage
from src.core.contracts.fakes.llm import FakeLLMClient

ART_11_TITLE = (
    "مرسوم رقم 2.14.791 بتحديد شروط ومعايير الاستفادة من الدعم المباشر للنساء الأرامل في وضعية هشة"
)
ART_11 = (
    "المادة 11\n\nمع مراعاة أحكام المادة 2\n أعلاه، يحدد المبلغ الشهري للدعم \n في \n350\n درهما \n"
    " عن \n كل \nطفل \n،يتيم \n على ألا \n يتعدى \n مجموع الدعم \n1050\n درهما عن \n كل شهر"
    " للأسرة الواحدة."
)
P6_03 = "ما هو المبلغ الشهري للدعم المباشر المخصص للنساء الأرامل في وضعية هشة عن كل طفل يتيم؟"

CARE_4 = (
    "المادة الرابعة\nت حدد مدة التكفل بالغير خارج فضاءات مؤسسة الرعاية الاجتماعية في سنة واحدة"
    " على\n.الأكثر"
)
FAMILY_7 = (
    "المادة السابعة\nمهام مجلس العائلة مهام استشارية. \n يقوم مجلس العائلة بالتحكيم لإصلاح ذات"
    " البين، وبإبداء رأيه في كل ما له علاقة بشؤون\nالأسرة."
)
FAMILY_9 = (
    "المادة التاسعة\n ينسخ المرسوم رقم2.94.31\n\n بتاريخ23\n\n من رجب1415\n (\n26\n\n"
    " ديسمبر1994\n ) بشأن\nتكوين مجلس العائلة وتحديد مهامه."
)
ACCOUNTS_23 = (
    "المادة23\n\n يتعين على\nالمدير مسك محاسبة خاصة بمؤسسة الرعاية الا جتماعية، يحدد نظامها"
    " بنص\nتنظيمي. \nيجب الاحتفاظ بجميع الوثائق و\nالمستندات المحاسباتية لمدة عشر سن وات تبتدئ"
    " من\nالتاريخ الذي تحمله."
)


def supported(excerpt: str) -> str:
    return json.dumps(
        {"verdicts": [{"claim": 1, "supported": True, "source": 1, "excerpt": excerpt}]},
        ensure_ascii=False,
    )


def check(claim: str, question: str, text: str, title: str = "", excerpt: str = "") -> str | None:
    return claim_problem(claim, question, f"{title} {text}", excerpt or text)


@pytest.mark.parametrize(
    ("claim", "question", "text", "title"),
    [
        (  # p6-03
            "المبلغ الشهري للدعم المباشر المخصص للنساء الأرامل في وضعية هشة عن كل طفل يتيم هو"
            " 350 درهماً [1].",
            P6_03,
            ART_11,
            ART_11_TITLE,
        ),
        (  # p6-10: numbers glued to words in the PDF text
            "نسخ المرسوم رقم 2.04.88 بشأن تكوين مجلس العائلة وتحديد مهامه المرسوم رقم 2.94.31"
            " بتاريخ 23 من رجب 1415 (26 ديسمبر 1994) [1].",
            "ما هو المرسوم الذي نسخه المرسوم رقم 2.04.88 بشأن تكوين مجلس العائلة وتحديد مهامه؟",
            FAMILY_9,
            "مرسوم رقم 2.04.88 بشأن تكوين مجلس العائلة وتحديد مهامه",
        ),
        (  # p4-08: a French claim against an Arabic source
            "Le décret prévoit un montant mensuel de 350 dirhams par enfant orphelin [1].",
            "Quel montant mensuel le décret prévoit-il par enfant orphelin ?",
            ART_11,
            ART_11_TITLE,
        ),
    ],
)
def test_correct_claims_pass(claim, question, text, title) -> None:
    assert check(claim, question, text, title) is None


def test_wrong_number_is_dropped() -> None:
    claim = "المبلغ الشهري للدعم عن كل طفل يتيم هو 900 درهم [1]."
    assert check(claim, P6_03, ART_11, ART_11_TITLE) == "number_mismatch"


def test_at_least_where_the_article_says_at_most_is_dropped() -> None:  # p2-04
    claim = "المدة القصوى للتكفل بالغير خارج فضاءات مؤسسة الرعاية الاجتماعية هي سنة واحدة على الأقل [1]."
    question = "ما هي المدة القصوى للتكفل بالغير خارج فضاءات مؤسسة الرعاية الاجتماعية؟"
    assert check(claim, question, CARE_4) == "limit_mismatch"


@pytest.mark.parametrize(
    "claim",
    [
        # p6-11
        "Les conditions pour obtenir un permis de conduire au Maroc ne sont pas explicitement"
        " couvertes par le document source [1].",
        # p1-08
        "لا يذكر القانون من يمكن تفويضه مهام ضابط الحالة المدنية خارج رئيس مجلس الجماعة [1].",
    ],
)
def test_claim_saying_the_information_is_missing_is_dropped(claim) -> None:
    assert check(claim, "?", FAMILY_7) == "no_information"


def test_claim_that_announces_an_answer_it_does_not_give_is_dropped() -> None:  # p5-07
    claim = (
        "الوثيقة المتعلقة بالشخص الذاتي الواجب إرفاقها بطلب الحصول على الترخيص بإحداث مؤسسة"
        " للرعاية الاجتماعية هي [1]."
    )
    question = (
        "ما هي الوثائق المتعلقة بالمؤسس الشخص الذاتي الواجب إرفاقها بطلب الحصول على الترخيص"
        " بإحداث مؤسسة للرعاية الاجتماعية؟"
    )
    assert check(claim, question, FAMILY_7) == "no_new_information"


def test_darija_claim_is_dropped() -> None:  # p3-09
    claim = "مجلس العائلة يقرر ولا غير كيعطي الرأي في الشؤون المتعلقة بشؤون الأسرة استشارياً [1]."
    assert check(claim, "مجلس العائلة واش كيقرر ولا غير كيعطي الرأي؟", FAMILY_7) == "darija"


def test_claim_with_chinese_characters_is_dropped() -> None:  # p2-03
    claim = "المبحث الإداري المسبق ي期限 بثلاثين يوماً من تاريخ تقديم الطلب [1]."
    assert check(claim, "?", FAMILY_7) == "foreign_script"


def test_claim_about_another_document_is_dropped() -> None:  # p1-11
    claim = (
        "المدة المحددة لحفظ الوثائق المثبتة لإجراءات تناسب أنظمة الذكاء الاصطناعي وفق مسودة"
        " مشروع القانون الداخلي هي عشر سنوات، تبدأ من التاريخ الذي تحمله الوثيقة [1]."
    )
    question = (
        "ما هي مدة حفظ الوثائق المثبتة لإجراءات تناسب أنظمة الذكاء الاصطناعي وفق مسودة مشروع"
        " القانون الداخلي؟"
    )
    assert check(claim, question, ACCOUNTS_23) in {"not_in_source", "off_topic"}


def test_claim_adding_facts_the_article_does_not_state_is_dropped() -> None:  # p4-01
    claim = (
        "أما سن الرشد القانوني الذي يحدد سن الإكراه الجنائي، فهو ثمانية عشر سنة شمسية وفق المادة"
        " من المدونة الأسرية [1]."
    )
    assert check(claim, "ما السن الذي تكتمل فيه أهلية الزواج وفق مدونة الأسرة؟", FAMILY_7) == (
        "not_in_source"
    )


def test_writer_returns_unknown_when_the_only_claim_fails_a_check(
    sample_chunks, lecteur_ctx, monkeypatch
) -> None:
    excerpt = "يحدد المبلغ الشهري للدعم في 350 درهما عن كل طفل يتيم"
    llm = FakeLLMClient(
        replies=[
            "المبلغ الشهري للدعم عن كل طفل يتيم هو 900 درهم [1].",
            supported(excerpt),
        ]
    )
    monkeypatch.setattr("src.agents.answer.writer.get_llm", lambda: llm)
    passage = Passage(
        chunk=sample_chunks[0].model_copy(update={"text": excerpt, "title": ART_11_TITLE}),
        score=1.0,
        rank=1,
    )

    answer = real_writer().write(P6_03, [passage], [], lecteur_ctx)

    assert answer.status == AnswerStatus.UNKNOWN


def test_writer_keeps_a_claim_that_passes_the_checks(
    sample_chunks, lecteur_ctx, monkeypatch
) -> None:
    excerpt = "يحدد المبلغ الشهري للدعم في 350 درهما عن كل طفل يتيم"
    llm = FakeLLMClient(
        replies=[
            "المبلغ الشهري للدعم عن كل طفل يتيم هو 350 درهما [1].",
            supported(excerpt),
        ]
    )
    monkeypatch.setattr("src.agents.answer.writer.get_llm", lambda: llm)
    passage = Passage(
        chunk=sample_chunks[0].model_copy(update={"text": excerpt, "title": ART_11_TITLE}),
        score=1.0,
        rank=1,
    )

    answer = real_writer().write(P6_03, [passage], [], lecteur_ctx)

    assert answer.status == AnswerStatus.ANSWERED
    assert "350" in answer.text
