"""Unit tests for ``OllamaClient``, against a mock ``llm`` service (P6-08, P6-11, P6-15, P6-16)."""

import json
from pathlib import Path

import httpx
import pytest
from tokenizers import Tokenizer, models, pre_tokenizers

from src.core.contracts.errors import ServiceError
from src.core.llm.ollama import OllamaClient, find_tokenizer

MODEL = "qwen2.5:7b"
NUM_CTX = 16384
MESSAGES = [{"role": "user", "content": "ما هي شروط الكفالة؟"}]
ANSWER = "شروط الكفالة محددة في القانون."


class Recorder:
    """A mock Ollama: records every request and answers with ``response``."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self.response = response or httpx.Response(
            200, json={"message": {"role": "assistant", "content": ANSWER}, "done": True}
        )
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


def _client(handler: object, **kwargs: object) -> OllamaClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return OllamaClient(
        "http://llm:11434",
        model=MODEL,
        num_ctx=NUM_CTX,
        client=httpx.Client(base_url="http://llm:11434", transport=transport),
        async_client=httpx.AsyncClient(base_url="http://llm:11434", transport=transport),
        **kwargs,  # type: ignore[arg-type]
    )


def _ndjson(*chunks: dict) -> httpx.Response:
    return httpx.Response(200, content="\n".join(json.dumps(c) for c in chunks).encode())


# --- chat -------------------------------------------------------------------------------------


def test_chat_returns_the_answer() -> None:
    assert _client(Recorder()).chat(MESSAGES) == ANSWER


def test_chat_passes_num_ctx_and_a_zero_temperature_by_default() -> None:
    """P6-08, P6-15."""
    llm = Recorder()
    _client(llm).chat(MESSAGES)
    [request] = llm.requests
    assert (request.method, request.url.path) == ("POST", "/api/chat")
    body = json.loads(request.content)
    assert body["model"] == MODEL
    assert body["messages"] == MESSAGES
    assert body["stream"] is False
    assert body["options"] == {"num_ctx": NUM_CTX, "temperature": 0.0}


def test_chat_passes_max_tokens_as_num_predict() -> None:
    """P6-15."""
    llm = Recorder()
    _client(llm).chat(MESSAGES, max_tokens=50, temperature=0.3)
    options = json.loads(llm.requests[0].content)["options"]
    assert options == {"num_ctx": NUM_CTX, "temperature": 0.3, "num_predict": 50}


def test_chat_can_use_another_model() -> None:
    llm = Recorder()
    _client(llm).chat(MESSAGES, model="qwen2.5:1.5b")
    assert json.loads(llm.requests[0].content)["model"] == "qwen2.5:1.5b"


@pytest.mark.parametrize("status", [400, 404, 500, 503])
def test_chat_error_answer_is_a_service_error(status: int) -> None:
    with pytest.raises(ServiceError):
        _client(Recorder(httpx.Response(status, json={"error": "model not found"}))).chat(MESSAGES)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"done": True}),
        httpx.Response(200, json={"message": {"content": None}}),
    ],
)
def test_chat_invalid_answer_is_a_service_error(response: httpx.Response) -> None:
    with pytest.raises(ServiceError):
        _client(Recorder(response)).chat(MESSAGES)


def test_chat_unreachable_service_is_a_service_error() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ServiceError):
        _client(down).chat(MESSAGES)


def test_num_ctx_below_one_is_refused() -> None:
    with pytest.raises(ValueError):
        OllamaClient("http://llm:11434", model=MODEL, num_ctx=0)


# --- stream -----------------------------------------------------------------------------------


async def _collect(client: OllamaClient, **kwargs: object) -> list[str]:
    return [piece async for piece in client.stream(MESSAGES, **kwargs)]  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_stream_yields_the_pieces_in_order() -> None:
    llm = Recorder(
        _ndjson(
            {"message": {"content": "شروط "}, "done": False},
            {"message": {"content": "الكفالة"}, "done": False},
            {"message": {"content": ""}, "done": True},
        )
    )
    assert await _collect(_client(llm)) == ["شروط ", "الكفالة"]


@pytest.mark.asyncio
async def test_stream_passes_num_ctx_and_max_tokens() -> None:
    llm = Recorder(_ndjson({"message": {"content": "x"}, "done": True}))
    await _collect(_client(llm), max_tokens=20)
    body = json.loads(llm.requests[0].content)
    assert body["stream"] is True
    assert body["options"] == {"num_ctx": NUM_CTX, "temperature": 0.0, "num_predict": 20}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        _ndjson({"message": {"content": "x"}, "done": False}, {"error": "out of memory"}),
        _ndjson({"message": {"content": "x"}, "done": False}),  # ends without done
        httpx.Response(200, content=b"not json\n"),
    ],
)
async def test_stream_failure_is_a_service_error(response: httpx.Response) -> None:
    with pytest.raises(ServiceError):
        await _collect(_client(Recorder(response)))


@pytest.mark.asyncio
async def test_stream_unreachable_service_is_a_service_error() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ServiceError):
        await _collect(_client(down))


# --- count_tokens -----------------------------------------------------------------------------


@pytest.fixture
def tiny_tokenizer(tmp_path: Path) -> Path:
    """A character-level tokenizer: each character of "abc" is one token."""
    vocab = {"[UNK]": 0, "a": 1, "b": 2, "c": 3}
    tokenizer = Tokenizer(models.WordLevel(vocab, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Split("", behavior="isolated")
    path = tmp_path / "tokenizer.json"
    tokenizer.save(str(path))
    return path


def test_count_tokens_uses_the_tokenizer_not_words(tiny_tokenizer: Path) -> None:
    """P6-16: one word, three tokens."""
    client = OllamaClient("http://llm:11434", model=MODEL, num_ctx=1, tokenizer_path=tiny_tokenizer)
    assert client.count_tokens("abc") == 3
    assert client.count_tokens("") == 0


def test_count_tokens_without_tokenizer_files_is_a_service_error(tmp_path: Path) -> None:
    client = OllamaClient(
        "http://llm:11434", model=MODEL, num_ctx=1, tokenizer_path=tmp_path / "missing.json"
    )
    with pytest.raises(ServiceError):
        client.count_tokens("abc")


def test_find_tokenizer_reads_the_hugging_face_cache(tmp_path: Path) -> None:
    snapshot = tmp_path / "hub" / "models--Qwen--Qwen2.5-7B-Instruct" / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")
    assert find_tokenizer(tmp_path) == snapshot / "tokenizer.json"


def test_find_tokenizer_without_make_models_is_a_service_error(tmp_path: Path) -> None:
    with pytest.raises(ServiceError):
        find_tokenizer(tmp_path)
