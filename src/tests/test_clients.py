from types import SimpleNamespace

from locoagent.providers.clients import OpenAICompatibleModelClient


def test_complete_returns_output_text(monkeypatch):
    client = OpenAICompatibleModelClient(
        model="gpt-5.4",
        base_url="https://example.com/v1",
        api_key="fake-key",
    )

    def fake_create(**kwargs):
        assert kwargs["model"] == "gpt-5.4"
        assert kwargs["input"] == "hi"
        assert kwargs["max_output_tokens"] == 4096

        return SimpleNamespace(output_text="hello")

    monkeypatch.setattr(
        client.client.responses,
        "create",
        fake_create,
    )

    result = client.complete("hi")

    assert result == "hello"