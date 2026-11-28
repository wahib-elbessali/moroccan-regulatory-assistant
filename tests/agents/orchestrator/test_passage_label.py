"""How a kept passage is named in the thinking stream (grade event)."""

from src.agents.orchestrator.graph import passage_label


def test_label_with_article() -> None:
    assert (
        passage_label("مرسوم رقم 2.04.88", "المادة الأولى") == "مرسوم رقم 2.04.88 — المادة الأولى"
    )


def test_label_without_article_has_no_dangling_dash() -> None:
    assert passage_label("Note de service 7/2026", None) == "Note de service 7/2026"
    assert passage_label("Note de service 7/2026", "") == "Note de service 7/2026"
