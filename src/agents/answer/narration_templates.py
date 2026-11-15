"""Deterministic bilingual process narration templates shared by P4 narrators."""

from __future__ import annotations

from typing import Any

from src.core.contracts.models import ProcessEvent


def _number(data: dict[str, Any], key: str) -> int:
    value = data.get(key, 0)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _items(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def render_template(event: ProcessEvent, language: str) -> str:
    """Render one allowed process event without exposing passage text or skip reasons."""
    if language not in {"fr", "ar"}:
        raise ValueError("language must be 'fr' or 'ar'")

    data = event.data
    step = str(event.step)

    if step == "plan":
        count = len(_items(data, "sub_questions"))
        return (
            f"Je découpe la question en {count} recherche(s)."
            if language == "fr"
            else f"أقسم السؤال إلى {count} استعلامات بحث."
        )

    if step == "search":
        query = str(data.get("query", ""))
        count = _number(data, "count")
        titles = _items(data, "titles")
        if language == "fr":
            sentence = f"Recherche « {query} » : {count} passage(s) trouvé(s)."
            return sentence + (f" Sources : {', '.join(titles)}." if titles else "")
        sentence = f"البحث « {query} »: عُثر على {count} مقطعًا."
        return sentence + (f" المصادر: {'، '.join(titles)}." if titles else "")

    if step == "grade":
        relevant = _number(data, "relevant")
        total = _number(data, "total")
        kept = _items(data, "kept")
        if language == "fr":
            sentence = f"{relevant} passage(s) pertinent(s) sur {total}."
            return sentence + (f" Retenus : {', '.join(kept)}." if kept else "")
        sentence = f"{relevant} مقطعًا ذا صلة من أصل {total}."
        return sentence + (f" المقاطع المعتمدة: {'، '.join(kept)}." if kept else "")

    if step == "reformulate":
        query = str(data.get("new_query", ""))
        return (
            f"Rien d'utile ; je reformule : « {query} »."
            if language == "fr"
            else f"لم أجد ما يفيد؛ أعيد صياغة البحث: « {query} »."
        )

    if step == "web":
        if data.get("status") == "done":
            count = _number(data, "count")
            return (
                f"Recherche web : {count} résultat(s)."
                if language == "fr"
                else f"البحث عبر الويب: {count} نتيجة."
            )
        if data.get("by_user") is True:
            return (
                "Recherche web désactivée, à votre demande."
                if language == "fr"
                else "تم إيقاف البحث عبر الويب بناءً على اختيارك."
            )
        return "Recherche web non effectuée." if language == "fr" else "لم يُجرَ البحث عبر الويب."

    if step == "write":
        return "Je rédige la réponse." if language == "fr" else "أُعدّ الإجابة."

    if step == "verify":
        supported = _number(data, "supported")
        total = _number(data, "total")
        return (
            f"{total} affirmation(s) vérifiée(s) : {supported} appuyée(s) par une source."
            if language == "fr"
            else f"تم التحقق من {total} ادعاءً؛ {supported} منها مدعوم بمصدر."
        )

    raise ValueError(f"unsupported process event: {step}")
