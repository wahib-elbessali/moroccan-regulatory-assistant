from uuid import uuid4

import pytest

from src.core.contracts.errors import LeakBlocked, ServiceError
from src.core.contracts.fakes.web import FakeWebAgent, FakeWebSearch
from src.core.contracts.models import UserContext


@pytest.fixture
def user_context():
    return UserContext(
        user_id=uuid4(),
        username="test-user",
        role="lecteur",
        web_enabled=True,
        request_id=uuid4(),
    )


def test_fake_web_search_returns_two_fixed_results():
    search = FakeWebSearch()

    results = search.search("Moroccan tax regulations")

    assert len(results) == 2
    assert all(result.url.startswith("https://") for result in results)
    assert all(result.title for result in results)
    assert all(result.snippet for result in results)


def test_fake_web_search_returns_fresh_results():
    search = FakeWebSearch()

    first = search.search("tax")
    second = search.search("tax")

    assert first == second
    assert first is not second


def test_fake_web_search_respects_max_results():
    search = FakeWebSearch()

    assert len(search.search("tax", max_results=1)) == 1
    assert search.search("tax", max_results=0) == []


def test_fake_web_search_raises_leak_blocked():
    search = FakeWebSearch()

    with pytest.raises(LeakBlocked) as exc_info:
        search.search("LEAK protected content")

    assert exc_info.value.hits == 1


def test_fake_web_agent_returns_done_with_two_results(user_context):
    agent = FakeWebAgent()

    result = agent.lookup(
        question="What are the Moroccan VAT rules?",
        ctx=user_context,
        language="fr",
    )

    assert result.status == "done"
    assert len(result.results) == 2


def test_fake_web_agent_skips_when_web_is_globally_disabled(user_context):
    agent = FakeWebAgent(web_enabled=False)

    result = agent.lookup("Tax regulations", user_context, "fr")

    assert result.status == "skipped"
    assert result.results == []


def test_fake_web_agent_skips_when_user_web_is_disabled(user_context):
    context = user_context.model_copy(update={"web_enabled": False})
    agent = FakeWebAgent()

    result = agent.lookup("Tax regulations", context, "fr")

    assert result.status == "skipped"
    assert result.results == []


def test_fake_web_agent_skips_when_user_opts_out(user_context):
    agent = FakeWebAgent()

    result = agent.lookup(
        "Tax regulations",
        user_context,
        "fr",
        use_web=False,
    )

    assert result.status == "skipped"
    assert result.results == []


def test_fake_web_agent_skips_question_containing_leak(user_context):
    agent = FakeWebAgent()

    result = agent.lookup("LEAK protected content", user_context, "fr")

    assert result.status == "skipped"
    assert result.results == []


def test_fake_web_agent_skips_when_search_raises_leak_blocked(user_context):
    class BlockedSearch:
        def search(self, query, max_results=5, request_id=None):
            raise LeakBlocked("blocked", hits=2)

    agent = FakeWebAgent(web_search=BlockedSearch())

    result = agent.lookup("Tax regulations", user_context, "fr")

    assert result.status == "skipped"
    assert result.results == []


@pytest.mark.parametrize(
    "error",
    [
        ServiceError("service unavailable"),
        TimeoutError("request timed out"),
        RuntimeError("unexpected failure"),
    ],
)
def test_fake_web_agent_never_propagates_search_errors(user_context, error):
    class FailingSearch:
        def search(self, query, max_results=5, request_id=None):
            raise error

    agent = FakeWebAgent(web_search=FailingSearch())

    result = agent.lookup("Tax regulations", user_context, "fr")

    assert result.status == "skipped"
    assert result.results == []
