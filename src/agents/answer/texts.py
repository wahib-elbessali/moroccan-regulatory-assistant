"""Fixed user-facing answer notices (P4-answer §3.1)."""

from typing import Final

UNKNOWN: Final[dict[str, str]] = {
    "ar": "لم أجد هذه المعلومة في الوثائق المتاحة لك.",
    "fr": "Je n'ai pas trouvé cette information dans les documents auxquels vous avez accès.",
}

WEB_ONLY: Final[dict[str, str]] = {
    "ar": "تنبيه: هذه الإجابة مصدرها الويب وليس النصوص الرسمية.",
    "fr": "Attention : cette réponse provient du web, pas des textes officiels.",
}

WEB_PART: Final[dict[str, str]] = {
    "ar": "تنبيه: جزء من هذه الإجابة مصدره الويب وليس النصوص الرسمية.",
    "fr": "Attention : une partie de cette réponse provient du web, pas des textes officiels.",
}

TEXTS: Final[dict[str, dict[str, str]]] = {
    "UNKNOWN": UNKNOWN,
    "WEB_ONLY": WEB_ONLY,
    "WEB_PART": WEB_PART,
}
