"""Prompt policy: the assistant speaks as the business, never as software.

The customer-facing model used to be introduced as an "AI customer assistant"
and could offer a voice note on an account where voice is disabled. Both make
the reply read as a bot and promise a capability the pipeline does not have.
"""
from types import SimpleNamespace

from app.modules.channels.meta.consumer import _system_prompt


def _user(**overrides):
    base = {
        "business_name": "Aster Beans",
        "first_name": "Aster",
        "last_name": "Coffee",
        "business_description": "A specialty coffee roaster.",
        "business_sells": "beans, wholesale lots",
        "business_doesnt_sell": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_prompt_never_calls_itself_an_ai_assistant():
    prompt = _system_prompt(_user())
    assert "AI customer assistant" not in prompt
    assert "Never describe yourself as a bot" in prompt
    assert "text-based system" in prompt


def test_prompt_does_not_offer_voice_when_disabled():
    prompt = _system_prompt(_user(), voice_enabled=False)
    assert "Do not offer a voice note" in prompt
    assert "offer to explain by voice note" not in prompt


def test_prompt_offers_voice_only_when_enabled():
    prompt = _system_prompt(_user(), platform="WhatsApp", voice_enabled=True)
    assert "offer to explain by voice note" in prompt


def test_whatsapp_prompt_never_asks_for_the_phone_number():
    prompt = _system_prompt(_user(), platform="WhatsApp")
    assert "NEVER ask for their phone number" in prompt


def test_instagram_prompt_asks_for_the_number_at_most_once():
    prompt = _system_prompt(_user(), platform="Instagram")
    assert "Ask for it at most once" in prompt
    assert "NEVER ask for their phone number" not in prompt


def test_instagram_prompt_only_promises_the_link_when_one_exists():
    """A link promise without a WhatsApp number is the same lie as a voice
    offer on a text-only account."""
    off = _system_prompt(_user(), platform="Instagram", bridge_enabled=False)
    assert "no WhatsApp number connected" in off
    assert "sending the WhatsApp link now" not in off

    on = _system_prompt(_user(), platform="Instagram", bridge_enabled=True)
    assert "sending the WhatsApp link now" in on
    assert "no WhatsApp number connected" not in on
    assert "they have to tap the link" in on, (
        "the model must not promise that we message them first"
    )
