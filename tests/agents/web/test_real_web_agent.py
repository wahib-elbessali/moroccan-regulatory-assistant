import pytest

from src.agents import web
from src.core.contracts.errors import LeakBlocked, ServiceError
from src.core.contracts.models import WebResult


class StubLLM:
    def __init__(self, reply="fiscalité des entreprises marocaines"):
        self.reply = reply
        self.messages = None
        self.kwargs = None

    def chat(self, messages, **kwargs):
        self.messages = messages
        self.kwargs = kwargs
        return self.reply


class StubSearch:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.calls = []

    def search(self, query, max_results=5, request_id=None):
        self.calls.append((query, max_results, request_id))
        if self.error:
            raise self.error
        return self.results


def enabled_context(lecteur_ctx):
    return lecteur_ctx.model_copy(update={"web_enabled": True})


def test_lookup_skipped_when_global_web_disabled(monkeypatch, lecteur_ctx):
    monkeypatch.setattr(web.cfg.web, "enabled", False)

    def unexpected_call():
        pytest.fail("Le LLM ne doit pas être appelé si le web est désactivé")

    monkeypatch.setattr(web, "get_llm", unexpected_call)

    result = web.RealWebAgent().lookup(
        "Question fiscale", enabled_context(lecteur_ctx), "fr"
    )

    assert result.status == "skipped"
    assert result.results == []


def test_lookup_skipped_when_user_web_disabled(monkeypatch, lecteur_ctx):
    monkeypatch.setattr(web.cfg.web, "enabled", True)

    def unexpected_call():
        pytest.fail("Le LLM ne doit pas être appelé")

    monkeypatch.setattr(web, "get_llm", unexpected_call)

    result = web.RealWebAgent().lookup(
        "Question fiscale",
        lecteur_ctx.model_copy(update={"web_enabled": False}),
        "fr",
    )

    assert result.status == "skipped"
    assert result.results == []


def test_lookup_skipped_when_use_web_false(monkeypatch, lecteur_ctx):
    monkeypatch.setattr(web.cfg.web, "enabled", True)

    def unexpected_call():
        pytest.fail("Le LLM ne doit pas être appelé")

    monkeypatch.setattr(web, "get_llm", unexpected_call)

    result = web.RealWebAgent().lookup(
        "Question fiscale", enabled_context(lecteur_ctx), "fr", use_web=False
    )

    assert result.status == "skipped"
    assert result.results == []


def test_lookup_reformulates_and_limits_results(monkeypatch, lecteur_ctx):
    monkeypatch.setattr(web.cfg.web, "enabled", True)
    monkeypatch.setattr(web.cfg.web, "max_query_words", 3)
    monkeypatch.setattr(web.cfg.web, "max_results", 2)
    monkeypatch.setattr(web.cfg.web, "max_snippet_chars", 8)

    llm = StubLLM("fiscalité entreprises Maroc réglementation supplémentaire")
    results = [
        WebResult(url="https://example.com/1", title="Source 1", snippet="1234567890"),
        WebResult(url="https://example.com/2", title="Source 2", snippet="abcdefghij"),
        WebResult(url="https://example.com/3", title="Source 3", snippet="troisième"),
    ]
    search = StubSearch(results=results)

    monkeypatch.setattr(web, "get_llm", lambda: llm)
    monkeypatch.setattr(web, "get_web_search", lambda: search)

    ctx = enabled_context(lecteur_ctx)
    question = "Quelles sont les obligations fiscales des entreprises ?"
    result = web.RealWebAgent().lookup(question, ctx, "fr")

    assert result.status == "done"
    assert len(result.results) == 2
    assert result.results[0].snippet == "12345678"
    assert result.results[1].snippet == "abcdefgh"

    query, max_results, request_id = search.calls[0]
    assert query == "fiscalité entreprises Maroc"
    assert max_results == 2
    assert request_id == ctx.request_id

    assert llm.messages[1]["content"] == question
    assert "French" in llm.messages[0]["content"]
    assert "3 words" in llm.messages[0]["content"]
    assert llm.kwargs["max_tokens"] == 40


def test_lookup_uses_arabic_prompt(monkeypatch, lecteur_ctx):
    monkeypatch.setattr(web.cfg.web, "enabled", True)
    llm = StubLLM("الالتزامات الضريبية")
    search = StubSearch()

    monkeypatch.setattr(web, "get_llm", lambda: llm)
    monkeypatch.setattr(web, "get_web_search", lambda: search)

    result = web.RealWebAgent().lookup(
        "ما هي الالتزامات الضريبية؟", enabled_context(lecteur_ctx), "ar"
    )

    assert result.status == "done"
    assert "Modern Standard Arabic" in llm.messages[0]["content"]


def test_lookup_skips_when_llm_returns_empty_query(monkeypatch, lecteur_ctx):
    monkeypatch.setattr(web.cfg.web, "enabled", True)
    monkeypatch.setattr(web, "get_llm", lambda: StubLLM("   \n  "))

    def unexpected_search():
        pytest.fail("La recherche ne doit pas être appelée")

    monkeypatch.setattr(web, "get_web_search", unexpected_search)

    result = web.RealWebAgent().lookup(
        "Question fiscale", enabled_context(lecteur_ctx), "fr"
    )

    assert result.status == "skipped"
    assert result.results == []


def test_lookup_audits_block_without_query_text(
    monkeypatch, lecteur_ctx, fake_audit
):
    monkeypatch.setattr(web.cfg.web, "enabled", True)
    monkeypatch.setattr(web, "get_llm", lambda: StubLLM("requête reformulée"))
    monkeypatch.setattr(
        web, "get_web_search", lambda: StubSearch(error=LeakBlocked(hits=4))
    )

    question = "Question confidentielle qui ne doit pas être journalisée"
    ctx = enabled_context(lecteur_ctx)

    result = web.RealWebAgent().lookup(question, ctx, "fr")

    assert result.status == "skipped"
    assert result.results == []
    assert len(fake_audit.actions) == 1

    action = fake_audit.actions[0]
    assert action["action_type"] == "web_blocked"
    assert action["user_id"] == ctx.user_id
    assert action["details"] == {
        "request_id": str(ctx.request_id),
        "hits": 4,
    }
    assert question not in str(action["details"])


@pytest.mark.parametrize(
    "error",
    [
        ServiceError("service unavailable"),
        TimeoutError("timeout"),
        RuntimeError("unexpected error"),
    ],
)
def test_lookup_skips_on_search_errors(monkeypatch, lecteur_ctx, error):
    monkeypatch.setattr(web.cfg.web, "enabled", True)
    monkeypatch.setattr(web, "get_llm", lambda: StubLLM("requête générale"))
    monkeypatch.setattr(
        web, "get_web_search", lambda: StubSearch(error=error)
    )

    result = web.RealWebAgent().lookup(
        "Question fiscale", enabled_context(lecteur_ctx), "fr"
    )

    assert result.status == "skipped"
    assert result.results == []


def test_lookup_skips_if_block_audit_fails(monkeypatch, lecteur_ctx):
    monkeypatch.setattr(web.cfg.web, "enabled", True)
    monkeypatch.setattr(web, "get_llm", lambda: StubLLM("requête générale"))
    monkeypatch.setattr(
        web, "get_web_search", lambda: StubSearch(error=LeakBlocked(hits=2))
    )

    class BrokenAudit:
        def log_action(self, *args, **kwargs):
            raise RuntimeError("audit unavailable")

    monkeypatch.setattr(web, "get_audit", lambda: BrokenAudit())

    result = web.RealWebAgent().lookup(
        "Question fiscale", enabled_context(lecteur_ctx), "fr"
    )

    assert result.status == "skipped"
    assert result.results == []

def test_real_web_agent_factory():
    assert isinstance(web.real_web_agent(), web.RealWebAgent)


def test_real_web_search_factory(monkeypatch):
    monkeypatch.setenv("LEAK_API_TOKEN", "test-token")

    service = web.real_web_search()

    assert isinstance(service, web.HttpWebSearch)
    assert service.token == "test-token"
