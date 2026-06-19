#!/usr/bin/env python3
"""Samantha V2 product-behavior eval runner.

Runs lightweight regression checks against either:
- local: imports /opt/data/streamline-agent/nova/chat_server.py and calls run_hermes()
- URL: posts JSON to <target>/chat

Output is JSON so it can be used in deploy gates or cron checks.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import urllib.request
from typing import Any

NOVA_MODULE_PATH = "/opt/data/streamline-agent/nova/chat_server.py"

DEFAULT_CASES: list[dict[str, Any]] = [
    {
        "id": "html_artifact_file",
        "prompt": "can u design an HTML landing page for moretape.com",
        "checks": ["no_raw_html_reply", "has_html_file", "short_reply"],
    },
    {
        "id": "stripe_payment_link",
        "prompt": "i need to pay / upgrade now",
        "checks": ["has_stripe_or_portal_link", "no_infra_words", "short_reply"],
    },
    {
        "id": "settings_telegram_login",
        "prompt": "open my settings",
        "checks": ["has_settings_link", "mentions_telegram_login", "no_infra_words"],
    },
    {
        "id": "vague_business_idea_one_question",
        "prompt": "I want to automate my salon but not sure where to start",
        "checks": ["no_brochure", "asks_at_most_one_question", "short_reply"],
    },
    {
        "id": "spanish_input_spanish_reply",
        "prompt": "quiero automatizar mi barbería, qué sigue?",
        "checks": ["likely_spanish", "no_infra_words", "short_reply"],
    },
]


def case_by_id(case_id: str) -> dict[str, Any]:
    for case in DEFAULT_CASES:
        if case["id"] == case_id:
            return case
    raise KeyError(case_id)


def load_nova_module():
    spec = importlib.util.spec_from_file_location("nova_chat_server", NOVA_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {NOVA_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call_local(prompt: str) -> dict[str, Any]:
    nova = load_nova_module()
    return normalize_response(nova.run_hermes({"text": prompt, "chat_id": 6551476547, "client_name": "Nova-Streamline"}))


def call_url(base_url: str, prompt: str) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat"
    body = json.dumps({"text": prompt, "chat_id": 6551476547, "client_name": "Nova-Streamline"}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as resp:
        return normalize_response(json.loads(resp.read().decode("utf-8")))


def normalize_response(response: dict[str, Any]) -> dict[str, Any]:
    response = dict(response or {})
    if "reply" not in response and response.get("replies"):
        response["reply"] = "\n".join(str(x) for x in response.get("replies") or [])
    response.setdefault("reply", "")
    response.setdefault("files", [])
    return response


def _files(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (response.get("files") or response.get("documents") or []) if isinstance(item, dict)]


def check_response(check: str, response: dict[str, Any]) -> bool:
    reply = str(response.get("reply") or "")
    lower = reply.lower()
    files = _files(response)

    if check == "no_raw_html_reply":
        return "<!doctype html" not in lower and "<html" not in lower
    if check == "has_html_file":
        return any(
            str(f.get("filename", "")).endswith(".html")
            and str(f.get("mime_type", "")).lower() in {"text/html", "application/html"}
            and str(f.get("content", "")).lower().lstrip().startswith("<!doctype html")
            for f in files
        )
    if check == "has_stripe_or_portal_link":
        return "checkout.stripe.com" in lower or "sammm.app" in lower
    if check == "has_settings_link":
        return "sammm.app" in lower and ("setting" in lower or "dashboard" in lower or "portal" in lower)
    if check == "mentions_telegram_login":
        return "telegram" in lower and ("login" in lower or "log in" in lower or "match" in lower)
    if check == "no_infra_words":
        banned = ("fly.io", "openrouter", "paperclip", "hermes", "deepseek", "vercel", "supabase", "token")
        return not any(word in lower for word in banned)
    if check == "no_brochure":
        brochure_phrases = ("streamline is", "our platform", "we offer", "pricing tiers", "company background")
        return not any(phrase in lower for phrase in brochure_phrases)
    if check == "asks_at_most_one_question":
        return reply.count("?") <= 1
    if check == "short_reply":
        return len(reply) <= 900
    if check == "likely_spanish":
        spanish_markers = ("qué", "sí", "para", "con", "por", "negocio", "barber", "siguiente", "pregunta", "automatizar", "reservas", "clientes")
        return any(marker in lower for marker in spanish_markers)
    raise KeyError(f"Unknown check: {check}")


def evaluate_response(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    failed = [check for check in case.get("checks", []) if not check_response(check, response)]
    return {
        "id": case["id"],
        "passed": not failed,
        "failed_checks": failed,
        "reply_preview": str(response.get("reply") or "")[:300],
        "file_count": len(_files(response)),
    }


def run_suite(target: str = "local", cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    selected = cases or DEFAULT_CASES
    results = []
    for case in selected:
        if target == "local":
            response = call_local(case["prompt"])
        else:
            response = call_url(target, case["prompt"])
        results.append(evaluate_response(case, response))
    return {
        "target": target,
        "total": len(results),
        "passed_count": sum(1 for item in results if item["passed"]),
        "failed_count": sum(1 for item in results if not item["passed"]),
        "passed": all(item["passed"] for item in results),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Samantha V2 behavior evals")
    parser.add_argument("--target", default="local", help="local or base URL, e.g. https://nova-streamline.fly.dev")
    parser.add_argument("--case", action="append", help="Run one case id; repeatable")
    args = parser.parse_args(argv)

    cases = [case_by_id(case_id) for case_id in args.case] if args.case else DEFAULT_CASES
    report = run_suite(args.target, cases)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
