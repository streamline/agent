import importlib.util
import os


def load_nova_module():
    path = "/opt/data/streamline-agent/nova/chat_server.py"
    spec = importlib.util.spec_from_file_location("nova_chat_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_html_landing_requests_return_viewable_file_not_raw_html_reply():
    nova = load_nova_module()

    result = nova.run_hermes({"text": "can u design an HTML landing page for moretape.com"})

    assert result["reply"]
    assert "<!doctype html" not in result["reply"].lower()
    assert result["files"][0]["filename"] == "moretape-com-landing-page.html"
    assert result["files"][0]["mime_type"] == "text/html"
    assert result["files"][0]["content"].lower().startswith("<!doctype html")


def test_payment_requests_return_stripe_checkout_link_without_model_call(monkeypatch):
    nova = load_nova_module()
    monkeypatch.setenv("STRIPE_STARTER_URL", "https://checkout.stripe.com/pay/test_123")

    result = nova.run_hermes({"text": "i need to pay / upgrade now"})

    assert "checkout.stripe.com" in result["reply"]
    assert "token" not in result["reply"].lower()
    assert "openrouter" not in result["reply"].lower()


def test_settings_requests_return_sammm_portal_link_without_model_call(monkeypatch):
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
