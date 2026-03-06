"""Tests for api/schemas.py — Pydantic model validation and defaults."""

import pytest
from pydantic import ValidationError

from api.schemas import (
    ChatRequest,
    ChatResponse,
    ConfirmationAction,
    ConfirmRequest,
    SetModelRequest,
    SetProjectRequest,
)


class TestChatRequest:
    def test_valid_request(self):
        req = ChatRequest(message="hello")
        assert req.message == "hello"
        assert req.session_id == "default"

    def test_custom_session_id(self):
        req = ChatRequest(message="hi", session_id="user-123")
        assert req.session_id == "user-123"

    def test_missing_message_fails(self):
        with pytest.raises(ValidationError):
            ChatRequest()

    def test_empty_message_fails(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="")

    def test_message_at_max_length(self):
        req = ChatRequest(message="a" * 32_000)
        assert len(req.message) == 32_000

    def test_message_over_max_length_fails(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="a" * 32_001)


class TestChatResponse:
    def test_plain_reply(self):
        resp = ChatResponse(reply="hello", model="ollama/test")
        assert resp.action is None

    def test_with_confirmation(self):
        action = ConfirmationAction(id="abc", preview="Write to file")
        resp = ChatResponse(reply="", model="ollama/test", action=action)
        assert resp.action.type == "confirmation"
        assert resp.action.id == "abc"

    def test_missing_reply_fails(self):
        with pytest.raises(ValidationError):
            ChatResponse(model="ollama/test")


class TestSetModelRequest:
    def test_valid(self):
        req = SetModelRequest(model="llama3.1:8b")
        assert req.model == "llama3.1:8b"

    def test_missing_model_fails(self):
        with pytest.raises(ValidationError):
            SetModelRequest()


class TestSetProjectRequest:
    def test_valid_with_defaults(self):
        req = SetProjectRequest(name="myproject")
        assert req.name == "myproject"
        assert req.session_id == "default"

    def test_custom_session(self):
        req = SetProjectRequest(name="proj", session_id="sess-1")
        assert req.session_id == "sess-1"


class TestConfirmRequest:
    def test_approve(self):
        req = ConfirmRequest(action="approve")
        assert req.action == "approve"

    def test_reject(self):
        req = ConfirmRequest(action="reject")
        assert req.action == "reject"
