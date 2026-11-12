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


def test_prompt_is_sarah_a_female_team_member():
    prompt = _system_prompt(_user())
    assert "You are Sarah" in prompt
    assert "You are a woman" in prompt
    assert "bringing in a colleague from the team" in prompt
    # The old honesty clause invited the model to announce that it is an AI.
    assert "answer honestly" not in prompt


def test_prompt_has_the_conversation_flow_rules():
    prompt = _system_prompt(_user())
    assert "a question is not a lead" in prompt
    assert "Opening a new conversation" in prompt
    assert "English, Arabic and Urdu" in prompt
    assert "Use the customer's name occasionally" in prompt
    assert "At most one emoji" in prompt
    assert "Voice notes may contain filler words" in prompt
    assert "either/or question" in prompt
    assert "Never promise a time frame" in prompt


def test_prompt_kills_scripted_openers_and_form_style_requirements():
    prompt = _system_prompt(_user())
    # No canned first line / welcome-back script to paste.
    assert "Hi — how can I help?" not in prompt
    assert "Welcome back — what can I do for you?" not in prompt
    # The old comma-separated requirements demand is gone (form-like).
    assert "separated by commas" not in prompt
    assert "products page, cart, online payments, reviews" not in prompt
    # Positive voice block present.
    assert "how we talk" in prompt or "Mirror the customer's register" in prompt
    assert "open like a person who read the thread" in prompt


def test_prompt_has_the_few_shot_voice_bank():
    prompt = _system_prompt(_user())
    assert "SAMPLE EXCHANGES" in prompt
    assert "Happy inquiry:" in prompt
    assert "Complaint:" in prompt
    assert "Price question:" in prompt
    assert "Ambiguous request:" in prompt
    assert "Goodbye:" in prompt
    assert "Arabic style reference:" in prompt


def test_prompt_keeps_honesty_and_tool_contracts_with_voice_bank():
    prompt = _system_prompt(_user(), platform="WhatsApp")
    # Honesty rails still intact alongside the new voice layer.
    assert "Never invent prices, stock, opening hours" in prompt
    assert "Never promise a time frame" in prompt
    assert "You answer 24/7" in prompt
    assert "Business facts tool" in prompt
    assert "Never use an em dash or an en dash" in prompt
    assert "Never describe yourself as a bot" in prompt


def test_sticker_markers_are_offered_only_where_the_pipeline_can_send_them():
    whatsapp = _system_prompt(_user(), platform="WhatsApp")
    assert "[[sticker:ok]]" in whatsapp
    assert "[[sticker:thanks]]" in whatsapp
    assert "[[sticker:done]]" in whatsapp
    # Instagram has no sticker message type; the prompt must not promise one.
    instagram = _system_prompt(_user(), platform="Instagram")
    assert "[[sticker:" not in instagram


def test_human_request_is_detected_in_english_arabic_and_urdu():
    from app.modules.channels.meta.lead_escalation import detect_human_request

    assert detect_human_request("I want to talk to a human")
    assert detect_human_request("can I speak to a real person?")
    assert detect_human_request("أريد التحدث مع موظف")
    assert detect_human_request("kisi insaan se baat karni hai")
    assert not detect_human_request("what are your hours?")


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
