"""Contract test of the Orchestrator (00-shared §6.5, P3 spec T1, T20, T21, T22).

T1 runs on the fake and on the real implementation; the real one is skipped until it exists.
T22 and T21 go through the /ask route.
"""

import asyncio
import importlib

import pytest

from src.core.contracts.fakes.orchestrator import FakeOrchestrator
from src.core.contracts.lang import detect_language


def _real_orchestrator():
    try:
        module = importlib.import_module("src.agents.orchestrator")
        return module.real_orchestrator()
    except (ImportError, AttributeError):
        pytest.skip("real orchestrator not written yet")


IMPLEMENTATIONS = {
    "fake": lambda: FakeOrchestrator(),
    "real": _real_orchestrator,
}


@pytest.fixture(params=list(IMPLEMENTATIONS))
def orchestrator(request):
    return IMPLEMENTATIONS[request.param]()


def _collect(orchestrator, question, ctx, use_web=True) -> list[dict]:
    async def go():
        return [e async for e in orchestrator.run(question, ctx, use_web)]

    return asyncio.run(go())


# --- T1 -----------------------------------------------------------------------------------------


# Test T1 (Partie 1): Vérifie l'ordre des événements SSE et s'assure que 'done' n'est pas renvoyé
# par l'orchestrateur directement (car il est géré par 'audited_stream').
@pytest.mark.parametrize("question", ["Quel est le délai ?", "ما هو أجل الطعن؟"])
def test_t1_event_order(orchestrator, lecteur_ctx, question):
    events = _collect(orchestrator, question, lecteur_ctx, use_web=False)
    kinds = [e["event"] for e in events]

    assert "done" not in kinds  # `done` belongs to audited_stream
    last = kinds[-1]
    assert last in ("answer", "error")
    assert kinds.count("answer") + kinds.count("error") == 1
    assert all(k == "thinking" for k in kinds[:-1])  # every thinking before the answer
    assert all(isinstance(e["data"].get("text"), str) for e in events if e["event"] == "thinking")


# Test T1 (Partie 2): Vérifie que la langue de la réponse générée correspond bien
# à la langue de la question posée (français ou arabe).
def test_t1_answer_language_follows_question(orchestrator, lecteur_ctx):
    fr = _collect(orchestrator, "Quel est le délai ?", lecteur_ctx, use_web=False)[-1]
    ar = _collect(orchestrator, "ما هو أجل الطعن؟", lecteur_ctx, use_web=False)[-1]
    if fr["event"] == "answer":
        assert fr["data"]["language"] == "fr"
    if ar["event"] == "answer":
        assert ar["data"]["language"] == "ar"


# --- T20 ----------------------------------------------------------------------------------------


# Test T20: Vérifie la robustesse et l'exactitude de la fonction de détection de la langue (detect_language)
# en testant divers cas (arabe, français, dialecte/darija, anglais converti en fr, chaînes vides ou caractères spéciaux).
@pytest.mark.parametrize(
    "text,expected",
    [
        ("ما هو أجل الطعن؟", "ar"),
        ("Quel est le délai ?", "fr"),
        ("شنو هو الأجل؟", "ar"),
        ("What is the deadline?", "fr"),  # English gives "fr" on purpose (§4b)
        ("؟؟ 123", "ar"),  # no letter: must not crash
        ("", "ar"),
    ],
)
def test_t20_detect_language(text, expected):
    assert detect_language(text) == expected


# --- T21 / T22: through the /ask route ----------------------------------------------------------
@pytest.fixture
def client(lecteur_ctx):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.routes.ask import router
    from src.core.contracts import registry
    from src.core.security import get_current_user_context

    registry.reset()
    registry.override("orchestrator", FakeOrchestrator())
    app = FastAPI()
    app.include_router(router, prefix="/ask")
    app.dependency_overrides[get_current_user_context] = lambda: lecteur_ctx

    # Same mapping as P5-05 (AppError -> its http_status), so the bare test app behaves like the real one.
    from fastapi.responses import JSONResponse

    from src.core.contracts.errors import AppError

    @app.exception_handler(AppError)
    async def _app_error(request, exc):
        return JSONResponse({"code": exc.code, "message": str(exc)}, status_code=exc.http_status)

    yield TestClient(app)
    registry.reset()


def _parse_sse(raw: str) -> list[tuple[str, str]]:
    out = []
    for block in raw.strip().split("\n\n"):
        lines = block.split("\n")
        out.append((lines[0].removeprefix("event: "), lines[1].removeprefix("data: ")))
    return out


# Test Flux SSE: Vérifie que l'appel HTTP POST sur /ask renvoie un flux de type text/event-stream
# avec la séquence exacte d'événements (plusieurs 'thinking', suivis de 'answer' puis 'done').
def test_ask_streams_fake_then_done(client):
    r = client.post("/ask", json={"question": "Quel est le délai ?", "use_web": False})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    kinds = [k for k, _ in _parse_sse(r.text)]
    assert kinds == ["thinking"] * 3 + ["answer", "done"]  # nothing after done


# Test T21: Vérifie que les questions invalides (vides, espaces, symboles uniquement, ou trop longues)
# rejettent immédiatement la requête avec un code HTTP 422 sans déclencher le flux de streaming.
@pytest.mark.parametrize("question", ["", "   ", "؟؟", "ا" * 1001])
def test_t21_invalid_question_gives_422_without_stream(client, question):
    r = client.post("/ask", json={"question": question})
    assert r.status_code == 422
    assert not r.headers["content-type"].startswith("text/event-stream")


# Test T22: Vérifie que le système d'audit enregistre correctement chaque requête réussie
# une seule fois (log_query), en incluant le bon request_id et une latence valide (latency_ms >= 0).
def test_t22_log_query_called_once_with_latency(client, lecteur_ctx, monkeypatch):
    from src.core.contracts import registry

    calls = []

    class SpyAudit:
        def log_query(self, request_id, user_id, query, latency_ms):
            calls.append((request_id, user_id, latency_ms))

        def log_action(self, *a, **k):
            pass

    registry.override("audit", SpyAudit())
    client.post("/ask", json={"question": "Quel est le délai ?"})
    assert len(calls) == 1
    assert calls[0][0] == lecteur_ctx.request_id
    assert isinstance(calls[0][2], int) and calls[0][2] >= 0
