import importlib.util


def load_eval_module():
    path = "/opt/data/streamline-agent/nova/samantha_v2_eval.py"
    spec = importlib.util.spec_from_file_location("samantha_v2_eval", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_eval_suite_contains_core_product_cases():
    mod = load_eval_module()

    case_ids = {case["id"] for case in mod.DEFAULT_CASES}

    assert "html_artifact_file" in case_ids
    assert "stripe_payment_link" in case_ids
    assert "settings_telegram_login" in case_ids
    assert "vague_business_idea_one_question" in case_ids


def test_validators_catch_raw_html_reply_and_missing_file():
    mod = load_eval_module()
    result = mod.evaluate_response(
        {
            "id": "html_artifact_file",
            "prompt": "design HTML for moretape.com",
            "checks": ["no_raw_html_reply", "has_html_file"],
        },
        {"reply": "<!doctype html><html></html>", "files": []},
    )

    assert result["passed"] is False
    assert "no_raw_html_reply" in result["failed_checks"]
    assert "has_html_file" in result["failed_checks"]


def test_runner_can_execute_against_local_nova_function():
    mod = load_eval_module()

    report = mod.run_suite(target="local", cases=[mod.case_by_id("html_artifact_file")])

    assert report["passed"] is True
    assert report["total"] == 1
    assert report["results"][0]["passed"] is True
