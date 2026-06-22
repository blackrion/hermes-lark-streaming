"""Feishu client tests — official CardKit request body details."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import hermes_lark_streaming.feishu.client as feishu_client_module
from hermes_lark_streaming.feishu import FeishuClient, FeishuClientConfig


class _SuccessResponse:
    code = 0
    msg = ""

    def success(self) -> bool:
        return True


class _FakeCardElementAPI:
    def __init__(self) -> None:
        self.requests = []

    async def acontent(self, request):
        self.requests.append(request)
        return _SuccessResponse()


@pytest.mark.asyncio
async def test_cardkit_stream_element_sets_official_uuid() -> None:
    client = FeishuClient(FeishuClientConfig(app_id="app", app_secret="secret"))
    card_element = _FakeCardElementAPI()
    client._client = SimpleNamespace(
        cardkit=SimpleNamespace(
            v1=SimpleNamespace(card_element=card_element),
        )
    )
    client._use_async_stream_element = True

    await client.cardkit_stream_element(
        "card_abcdefghijklmnopqrstuvwxyz",
        "answer_content",
        "hello world",
        sequence=7,
    )

    request = card_element.requests[0]
    body = request.request_body
    assert request.card_id == "card_abcdefghijklmnopqrstuvwxyz"
    assert request.element_id == "answer_content"
    assert body.content == "hello world"
    assert body.sequence == 7
    assert body.uuid == FeishuClient._stream_uuid(
        "card_abcdefghijklmnopqrstuvwxyz",
        "answer_content",
        7,
    )


@pytest.mark.asyncio
async def test_cardkit_stream_element_allows_explicit_uuid_and_truncates() -> None:
    client = FeishuClient(FeishuClientConfig(app_id="app", app_secret="secret"))
    card_element = _FakeCardElementAPI()
    client._client = SimpleNamespace(
        cardkit=SimpleNamespace(
            v1=SimpleNamespace(card_element=card_element),
        )
    )
    client._use_async_stream_element = True

    await client.cardkit_stream_element(
        "card_id",
        "answer_content",
        "hello world",
        sequence=8,
        uuid="u" * 80,
    )

    body = card_element.requests[0].request_body
    assert body.uuid == "u" * 64


class _NoUuidContentBody:
    @classmethod
    def builder(cls):
        return _NoUuidContentBodyBuilder()


class _NoUuidContentBodyBuilder:
    def __init__(self) -> None:
        self._content = ""
        self._sequence = 0

    def content(self, value: str):
        self._content = value
        return self

    def sequence(self, value: int):
        self._sequence = value
        return self

    def build(self):
        return SimpleNamespace(content=self._content, sequence=self._sequence)


@pytest.mark.asyncio
async def test_cardkit_stream_element_tolerates_sdk_without_uuid_builder(monkeypatch) -> None:
    client = FeishuClient(FeishuClientConfig(app_id="app", app_secret="secret"))
    card_element = _FakeCardElementAPI()
    client._client = SimpleNamespace(
        cardkit=SimpleNamespace(
            v1=SimpleNamespace(card_element=card_element),
        )
    )
    client._use_async_stream_element = True
    monkeypatch.setattr(feishu_client_module, "ContentCardElementRequestBody", _NoUuidContentBody)

    await client.cardkit_stream_element(
        "card_id",
        "answer_content",
        "hello world",
        sequence=9,
        uuid="uuid-ignored-by-old-sdk",
    )

    body = card_element.requests[0].request_body
    assert body.content == "hello world"
    assert body.sequence == 9
    assert not hasattr(body, "uuid")
