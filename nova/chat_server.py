#!/usr/bin/env python3
"""Minimal HTTP /chat bridge for Streamline Nova.

Telegram updates arrive at streamline-gateway. The gateway POSTs here, this
server runs a one-shot Hermes/Nova turn, and returns JSON: {"reply": "..."}.
Uses only Python stdlib so it can run inside ghcr.io/streamline/agent:latest
without installing FastAPI/uvicorn.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import json
import os
import re
import subprocess
import sys
import time
import traceback

HOST = os.environ.get("CHAT_SERVER_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", os.environ.get("CHAT_SERVER_PORT", "8443")))
HERMES_BIN = os.environ.get("HERMES_BIN", "/opt/hermes/.venv/bin/hermes")
HERMES_HOME = os.environ.get("HERMES_HOME", "/opt/data")
TIMEOUT = int(os.environ.get("CHAT_TIMEOUT_SECONDS", "150"))
MAX_TEXT = int(os.environ.get("CHAT_MAX_TEXT_CHARS", "6000"))


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    raw_len = handler.headers.get("Content-Length", "0")
    try:
        length = min(int(raw_len), 1024 * 1024)
    except ValueError:
        length = 0
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8") or "{}")


def _clean_reply(output: str) -> str:
    # Hermes one-shot prints a blank line, session_id line, then final text.
    lines = [line.rstrip() for line in output.splitlines()]
    cleaned: list[str] = []
    skip_prefixes = ("session_id:",)
    for line in lines:
        if not line.strip():
            if cleaned:
                cleaned.append("")
            continue
        if any(line.strip().startswith(prefix) for prefix in skip_prefixes):
            continue
        # Drop occasional banners/progress/security-scan noise if present.
        stripped = line.strip()
        if re.match(r"^(Hermes Agent|Model:|Provider:)\b", stripped):
            continue
        if "tirith security scanner enabled but not available" in stripped:
            continue
        cleaned.append(line)
    reply = "\n".join(cleaned).strip()
    return reply or "Done."


def _build_prompt(payload: dict) -> str:
    text = str(payload.get("text") or "").strip()[:MAX_TEXT]
    client_name = str(payload.get("client_name") or "Streamline client")
    chat_id = payload.get("chat_id")
    sender = ((payload.get("raw_update") or {}).get("message") or {}).get("from") or {}
    sender_name = " ".join(
        part for part in [str(sender.get("first_name") or ""), str(sender.get("last_name") or "")] if part
    ).strip() or str(sender.get("username") or "Client")
    remaining = payload.get("free_messages_remaining")
    limit = payload.get("free_messages_limit")
    balance_line = ""
    if isinstance(remaining, int) and isinstance(limit, int) and limit > 0:
        balance_line = f"\nDaily free-message balance: {remaining}/{limit} remaining. Do not mention this unless remaining is 3 or fewer, and keep it to one short sentence."

    return f"""You are Samantha, a practical business-streamlining partner replying in Telegram.

Context for routing only — do not mention unless directly needed:
Client workspace: {client_name}
Telegram chat_id: {chat_id}
Sender: {sender_name}{balance_line}

Rules:
- Speak as Samantha first, not as a company brochure.
- The intro line is optional and should be used once only for greeting-only first messages like "hi", "hello", "start", or "what do you do?". Vary it naturally.
- Never repeat "I'm Samantha — I help streamline your business" after the user has given any business context, pain point, or task.
- Do not say "Streamline setup" in greetings.
- Do not start with a long intro, credentials, company background, pricing, platform details, or details about the person.
- Mention Streamline only lightly as the team/product behind Samantha when it helps; never make the message about Streamline.
- Be short, warm, direct, and useful.
- Ask one sharp question at a time only when truly needed.
- IMPORTANT: If the user asks to make/design/build/write/create HTML, a landing page, website, copy, plan, or asset, DO THE WORK immediately. Do not loop back to discovery questions. Use reasonable assumptions from the message and provide a usable deliverable.
- For simple HTML/landing-page requests, create/send a complete single-file HTML artifact the user can open and preview. Do not paste raw HTML as normal chat text unless file delivery is unavailable.
- If the user provides business context such as "I don't have a site or marketing plan", treat it as the pain point and propose/build the next step; do not ask for the pain point again.
- Do not mention Fly.io, OpenRouter, Paperclip, Hermes, DeepSeek, Vercel, Supabase, tokens, webhooks, or infrastructure.
- If the message is about connecting/setup/status, acknowledge and give the next practical step.
- If the user asks for work, proceed if obvious; otherwise ask one clarifying question.

Incoming message:
{text}
"""


def is_html_landing_request(text: str) -> bool:
    lower = text.lower()
    wants_html = "html" in lower or "landing page" in lower or "website" in lower
    action = any(word in lower for word in ("design", "make", "build", "create", "write", "draft"))
    return wants_html and action


def is_payment_request(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in ("pay", "paid", "payment", "checkout", "upgrade", "top up", "top-up", "billing"))


def is_settings_request(text: str) -> bool:
    lower = text.lower()
    settings_words = ("settings", "setting", "dashboard", "portal", "login", "log in", "sign in", "account")
    action_words = ("open", "show", "send", "link", "login", "log in", "access")
    return any(word in lower for word in settings_words) and any(word in lower for word in action_words)


def is_vague_business_automation_request(text: str) -> bool:
    lower = text.lower()
    has_business = any(word in lower for word in ("salon", "barber", "barbería", "business", "restaurant", "clinic", "studio"))
    has_automation = any(word in lower for word in ("automate", "automation", "automatizar", "streamline"))
    vague = any(phrase in lower for phrase in ("not sure", "where to start", "qué sigue", "what next", "dónde empezar"))
    return has_business and has_automation and vague


def vague_business_reply(text: str) -> dict:
    lower = text.lower()
    if any(word in lower for word in ("barbería", "automatizar", "qué sigue", "reservas")):
        return {"reply": "Perfecto — empezaría por reservas y recordatorios, porque reduce no-shows rápido y te ahorra mensajes manuales. ¿Hoy tus clientes agendan por WhatsApp, Instagram o llamadas?"}
    return {"reply": "Best first move: automate bookings and follow-ups, because that saves time fast and reduces no-shows. What’s the main way customers book with you today?"}


def payment_reply() -> dict:
    checkout_url = os.environ.get("STRIPE_STARTER_URL") or os.environ.get("STARTER_CHECKOUT_URL") or "https://sammm.app"
    return {
        "reply": (
            "Yep — use this secure Stripe checkout link to keep going:\n"
            f"{checkout_url}\n\n"
            "Once it’s done, come back here and I’ll continue from where we left off."
        )
    }


def settings_reply() -> dict:
    settings_url = os.environ.get("SAMMM_SETTINGS_URL") or os.environ.get("SAMMM_PORTAL_URL") or "https://sammm.app/settings"
    return {
        "reply": (
            "Open your Samantha settings here:\n"
            f"{settings_url}\n\n"
            "Use Telegram login so I can match it to this chat."
        )
    }


def domain_from_text(text: str) -> str:
    match = re.search(r"\b([a-z0-9-]+\.(?:com|com\.au|net|org|ai|app|io|co|dev))\b", text.lower())
    return match.group(1) if match else "yourbusiness.com"


def html_landing_artifact(text: str) -> dict:
    domain = domain_from_text(text)
    brand = domain.split(".")[0].replace("-", " ").title()
    filename = f"{domain.replace('.', '-')}-landing-page.html"
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{brand} | Websites, Apps & AI</title>
  <style>
    *{{box-sizing:border-box}} body{{margin:0;font-family:Inter,Arial,sans-serif;background:#08080c;color:white}}
    .wrap{{max-width:1080px;margin:auto;padding:48px 22px}} nav{{display:flex;justify-content:space-between;align-items:center}}
    .logo{{font-weight:800;font-size:22px}} .pill{{border:1px solid #2a2a35;border-radius:999px;padding:8px 14px;color:#b8b8c7}}
    .hero{{padding:92px 0 70px}} h1{{font-size:clamp(42px,8vw,82px);line-height:.95;margin:0;letter-spacing:-.06em}}
    .grad{{background:linear-gradient(90deg,#8b5cf6,#22d3ee);-webkit-background-clip:text;color:transparent}}
    p{{color:#b8b8c7;font-size:19px;line-height:1.6;max-width:680px}} .cta{{display:inline-block;margin-top:18px;background:#8b5cf6;color:#fff;text-decoration:none;padding:15px 22px;border-radius:14px;font-weight:800}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px;margin-top:34px}}
    .card{{background:#12121a;border:1px solid #242434;border-radius:20px;padding:22px}} .card h3{{margin:0 0 8px}}
    footer{{border-top:1px solid #20202c;margin-top:70px;padding-top:28px;color:#777}}
  </style>
</head>
<body>
  <main class="wrap">
    <nav><div class="logo">{brand}</div><div class="pill">Digital consulting + build partner</div></nav>
    <section class="hero">
      <h1>Build better systems.<br><span class="grad">Get more clients.</span></h1>
      <p>{brand} helps businesses turn messy digital operations into clear, high-performing websites, apps, migrations and AI-powered workflows.</p>
      <a class="cta" href="mailto:hello@{domain}">Start a project →</a>
    </section>
    <section class="grid">
      <div class="card"><h3>Consulting</h3><p>Strategy, audits and roadmaps so you know exactly what to build next.</p></div>
      <div class="card"><h3>Websites</h3><p>Fast landing pages and websites designed to convert visitors into leads.</p></div>
      <div class="card"><h3>Apps</h3><p>Custom tools, dashboards and client portals built around your workflow.</p></div>
      <div class="card"><h3>Migration</h3><p>Move from old platforms to better systems without losing momentum.</p></div>
      <div class="card"><h3>AI Integration</h3><p>Automations and AI assistants that save time and improve customer experience.</p></div>
    </section>
    <footer>{domain} — replace the email/CTA with your booking link when ready.</footer>
  </main>
</body>
</html>
"""
    return {
        "reply": f"Done — I made a first-draft HTML landing page for {domain}. Open the attached file to preview it.",
        "files": [
            {
                "filename": filename,
                "mime_type": "text/html",
                "caption": f"{brand} landing page draft",
                "content": html,
            }
        ],
    }


def run_hermes(payload: dict) -> dict:
    text = str(payload.get("text") or "")
    if is_html_landing_request(text):
        return html_landing_artifact(text)
    if is_payment_request(text):
        return payment_reply()
    if is_settings_request(text):
        return settings_reply()
    if is_vague_business_automation_request(text):
        return vague_business_reply(text)
    prompt = _build_prompt(payload)
    env = os.environ.copy()
    env["HERMES_HOME"] = HERMES_HOME
    env["HERMES_PROFILE"] = env.get("HERMES_PROFILE", "default")
    env["HERMES_SKIP_CONFIG_MIGRATION"] = "1"
    # This machine is now HTTP-backed. Never let child chat accidentally poll Telegram.
    env.pop("HERMES_SESSION_CHAT_ID", None)

    cmd = [HERMES_BIN, "chat", "-Q", "-q", prompt]
    proc = subprocess.run(
        cmd,
        cwd=HERMES_HOME,
        env=env,
        text=True,
        capture_output=True,
        timeout=TIMEOUT,
    )
    combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        raise RuntimeError(f"Hermes exited {proc.returncode}: {combined[-2000:]}")
    return {"reply": _clean_reply(combined)}


class Handler(BaseHTTPRequestHandler):
    server_version = "StreamlineNovaChat/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), fmt % args))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            _json_response(self, 200, {"status": "ok", "app": "nova-chat", "hermes_home": HERMES_HOME})
            return
        _json_response(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/chat":
            _json_response(self, 404, {"ok": False, "error": "not_found"})
            return
        try:
            payload = _read_json(self)
            result = run_hermes(payload)
            _json_response(self, 200, result)
        except subprocess.TimeoutExpired:
            _json_response(self, 504, {"reply": "I’m still processing that. Try again in a moment."})
        except Exception as exc:
            traceback.print_exc()
            _json_response(self, 500, {"reply": "I hit a temporary issue. Streamline has been notified.", "error": str(exc)[:500]})


if __name__ == "__main__":
    os.makedirs(HERMES_HOME, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Nova /chat server listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()
