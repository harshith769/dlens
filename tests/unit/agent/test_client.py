import pytest

from dlens.agent.llm import InputTooLarge, QuotaExceeded, make_client
from dlens.agent.llm.ollama import OllamaProvider

from .conftest import user


def test_miss_then_hit_makes_one_call_and_one_quota_unit(make):
    client, prov = make()
    first = client.chat(user("hi"))
    second = client.chat(user("hi"))
    assert (first.cached, second.cached) == (False, True)
    assert second.text == first.text
    assert prov.calls == 1
    assert client.quota.used("gemini") == 1


def test_cache_hit_works_with_quota_exhausted(make):
    client, prov = make(budget=1)
    client.chat(user("hi"))
    assert client.chat(user("hi")).cached  # no QuotaExceeded
    with pytest.raises(QuotaExceeded):
        client.chat(user("different"))
    assert prov.calls == 1


def test_oversize_rejected_before_anything_is_consumed(make):
    client, prov = make()
    with pytest.raises(InputTooLarge):
        client.chat(user("x" * 20000))
    assert prov.calls == 0
    assert client.quota.used("gemini") == 0


def test_quota_exceeded_raised_before_send(make):
    client, prov = make(budget=2)
    client.chat(user("a"))
    client.chat(user("b"))
    with pytest.raises(QuotaExceeded):
        client.chat(user("c"))
    assert prov.calls == 2


def test_make_client_defaults_to_ollama(tmp_path):
    env = {"DLENS_CACHE_DIR": str(tmp_path / "c"), "DLENS_STATE_DIR": str(tmp_path / "s")}
    client = make_client(env=env)
    assert isinstance(client.provider, OllamaProvider)
    assert client.provider.model == "qwen3:4b"


def test_make_client_unknown_and_groq(tmp_path):
    env = {"DLENS_CACHE_DIR": str(tmp_path / "c"), "DLENS_STATE_DIR": str(tmp_path / "s")}
    with pytest.raises(ValueError, match="Unknown"):
        make_client("nope", env)
    with pytest.raises(ValueError, match="Groq"):
        make_client("groq", env)


def test_failed_send_still_counts_and_is_not_cached(make):
    client, prov = make()

    def boom(*a, **k):
        raise RuntimeError("down")

    prov.send = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        client.chat(user("hi"))
    assert client.quota.used("gemini") == 1
    prov.send = type(prov).send.__get__(prov)  # type: ignore[method-assign]
    assert not client.chat(user("hi")).cached  # nothing was stored by the failure
