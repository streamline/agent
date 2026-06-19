import importlib.util
import os


def load_nova_module():
    path = "/opt/data/streamline-agent/nova/chat_server.py"
    spec = importlib.util.spec_from_file_location("nova_chat_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_html_landing_requests_return_viewable_file_not_raw_html_reply(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    nova = load_nova_module()

    result = nova.run_hermes({"text": "can u design an HTML landing page for moretape.com"})

    assert result["reply"]
    assert "<!doctype html" not in result["reply"].lower()
    assert result["files"][0]["filename"] == "moretape-com-landing-page.html"
    assert result["files"][0]["mime_type"] == "text/html"
    assert result["files"][0]["content"].lower().startswith("<!doctype html")


def test_landing_revision_request_with_domain_returns_file_without_hermes(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    nova = load_nova_module()

    result = nova.run_hermes({"text": "it’s missing content and needs to convert leads. fix it using the logo and colours from moretape.com"})

    assert result["files"][0]["filename"] == "moretape-com-landing-page.html"
    assert result["files"][0]["mime_type"] == "text/html"


def test_reply_to_landing_page_context_turns_this_one_into_artifact(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    nova = load_nova_module()

    result = nova.run_hermes({
        "text": "this one",
        "raw_update": {
            "message": {
                "reply_to_message": {
                    "caption": "Moretape landing page draft",
                    "document": {"file_name": "moretape-com-landing-page.html", "mime_type": "text/html"},
                }
            }
        },
    })

    assert result["files"][0]["filename"] == "moretape-com-landing-page.html"
    assert "attached file" in result["reply"].lower()
    assert result["usage"]["input_tokens"] > 0
    assert result["usage"]["output_tokens"] > 0
    assert result["usage"]["model"] == nova.DETERMINISTIC_REPLY_MODEL


def test_payment_requests_return_stripe_checkout_link_with_free_model_fallback(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    nova = load_nova_module()
    monkeypatch.setenv("STRIPE_STARTER_URL", "https://checkout.stripe.com/pay/test_123")

    result = nova.run_hermes({"text": "i need to pay / upgrade now"})

    assert "checkout.stripe.com" in result["reply"]
    assert "token" not in result["reply"].lower()
    assert "openrouter" not in result["reply"].lower()


def test_settings_requests_return_sammm_portal_link_with_free_model_fallback(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    nova = load_nova_module()
    monkeypatch.setenv("SAMMM_SETTINGS_URL", "https://sammm.app/settings")

    result = nova.run_hermes({"text": "open my settings"})

    assert "https://sammm.app/settings" in result["reply"]
    assert "telegram" in result["reply"].lower()


def test_vague_business_idea_asks_one_sharp_question_not_brochure():
    nova = load_nova_module()

    prompt = nova._build_prompt({"text": "I want to automate my salon but not sure where to start"})

    assert "Ask one sharp question" in prompt
    assert "not as a company brochure" in prompt
    assert "Do not start with a long intro" in prompt


def test_deterministic_intents_use_model_shaped_reply_when_valid(monkeypatch):
    nova = load_nova_module()
    monkeypatch.setenv("STRIPE_STARTER_URL", "https://checkout.stripe.com/pay/test_123")

    def fake_short_reply(system_prompt, user_prompt):
        assert "Intent: payment" in user_prompt
        assert "https://checkout.stripe.com/pay/test_123" in user_prompt
        return "All good — finish checkout here and I’ll pick up where we left off: https://checkout.stripe.com/pay/test_123"

    monkeypatch.setattr(nova, "_openrouter_short_reply", fake_short_reply)

    result = nova.run_hermes({"text": "upgrade me"})

    assert result["reply"].startswith("All good")
    assert "https://checkout.stripe.com/pay/test_123" in result["reply"]


def test_model_shaped_reply_rejects_missing_required_terms(monkeypatch):
    nova = load_nova_module()
    monkeypatch.setattr(nova, "_openrouter_short_reply", lambda *_: "Sure, I can help with that.")

    reply = nova.model_shaped_reply("settings", "open settings", "fallback with link", required_terms=("https://sammm.app/settings",))

    assert reply == "fallback with link"


def test_attach_usage_preserves_existing_provider_usage():
    nova = load_nova_module()

    result = nova.attach_usage(
        {"reply": "ok", "usage": {"input_tokens": 12, "output_tokens": 3, "provider": "openrouter", "model": "exact"}},
        "long input that would estimate differently",
        "ok",
        provider="fallback-provider",
        model="fallback-model",
    )

    assert result["usage"]["input_tokens"] == 12
    assert result["usage"]["output_tokens"] == 3
    assert result["usage"]["model"] == "exact"
