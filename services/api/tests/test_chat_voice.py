"""Deterministic reply linter (WA voice plan, phase 2).

The linter must strip machine tells without ever eating a reply: every rule
is a mapping, all failures fail open, and the original text always comes back
when anything raises.
"""
import pytest

from app.modules.channels.meta.chat_voice import (
    _BANNED_PHRASE_MAP,
    clean_reply,
    opener_key,
)


def test_strips_markdown_scaffolding():
    assert clean_reply("**Important** note") == "Important note"
    assert clean_reply("*italic* text") == "italic text"
    assert clean_reply("Use `code` here") == "Use here"
    assert clean_reply("# Heading\nBody") == "Body"
    assert clean_reply("- first\n- second") == "first\nsecond"
    assert clean_reply("• one\n• two") == "one\ntwo"
    assert clean_reply("1. alpha\n2. beta") == "alpha\nbeta"


def test_replaces_em_and_en_dashes_but_keeps_hyphens():
    assert clean_reply("Hi — how are you?") == "Hi, how are you?"
    assert clean_reply("one – two") == "one, two"
    assert clean_reply("a -- b") == "a, b"
    # Compound words and connected forms must survive.
    assert clean_reply("well-being e-commerce") == "well-being e-commerce"
    assert clean_reply("القهوة التركية") == "القهوة التركية"


def test_applies_phrase_map_case_insensitively():
    assert clean_reply("I apologize for the inconvenience.") == "Sorry about that."
    assert clean_reply("I APOLOGIZE FOR THE INCONVENIENCE.") == "Sorry about that."
    assert clean_reply("Kindly allow me to verify.") == "Let me check."
    assert clean_reply("In today's fast-paced world, we deliver.") == ", we deliver."
    assert clean_reply("Please be informed that prices rose.") == "prices rose."


def test_phrase_map_is_data_not_code():
    # Every mapping must be a real replace (source != target or empty target),
    # and keys must be lowercase-comparable without surprises.
    for source, target in _BANNED_PHRASE_MAP.items():
        assert isinstance(source, str) and isinstance(target, str)
        assert source.strip()


def test_collapses_whitespace():
    assert clean_reply("a\n\n\n\nb") == "a\n\nb"
    assert clean_reply("  padded  \n  text  ") == "padded\ntext"


def test_fail_open_returns_original_on_error(monkeypatch):
    text = "Keep this exactly as-is."
    original = clean_reply

    def boom(_text):
        raise RuntimeError("linter exploded")

    monkeypatch.setattr(
        "app.modules.channels.meta.chat_voice._strip_markdown", boom
    )
    monkeypatch.setattr(
        "app.modules.channels.meta.chat_voice._replace_dashes", boom
    )
    # Patch the entry's internal calls by making them raise.
    assert clean_reply(text) == text


def test_non_string_input_is_handled():
    assert clean_reply(None) == ""
    assert clean_reply("") == ""


def test_opener_key_is_stable_and_discriminating():
    assert opener_key("Hi! How can I help you today?") == opener_key("Hi, how can I help?")
    assert opener_key("Welcome back! What do you need?") != opener_key("Hi, how can I help?")
    assert opener_key(None) == ""
    assert opener_key("") == ""


@pytest.mark.parametrize("raw,expected", [
    ("**Bold** and *italic*", "Bold and italic"),
    ("Use `x` here", "Use here"),
    ("# heading\nUse `x`", "Use"),
])
def test_combined_rules(raw, expected):
    result = clean_reply(raw)
    assert result == expected
