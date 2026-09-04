#!/usr/bin/env python3
"""orchestrator.py のテスト。

requests をモックするため実 API は呼ばず、APIキーも不要。

  python3 -m unittest discover -s orchestrator/tests -v
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-ant")
os.environ.setdefault("GOOGLE_API_KEY", "test-goog")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-oai")

import orchestrator as O  # noqa: E402

O.ANTHROPIC_API_KEY = "sk-test-ant"
O.GOOGLE_API_KEY = "test-goog"
O.OPENAI_API_KEY = "sk-test-oai"

GEMINI_OK = {"candidates": [{"finishReason": "STOP",
                             "content": {"parts": [{"text": "Geminiの回答本文"}]}}]}
GPT_OK = {"choices": [{"finish_reason": "stop",
                       "message": {"content": "GPTの回答本文"}}]}
CLAUDE_OK = {"stop_reason": "end_turn",
             "content": [{"type": "thinking", "thinking": "内部思考"},
                         {"type": "text", "text": "Claudeの統合結果"}]}


class FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise O.requests.HTTPError(f"HTTP {self.status_code}", response=self)


def fake_request(responses, calls=None):
    """URL ごとに返すレスポンスを決める requests.request の代役。

    responses の値が list ならば呼び出しごとに先頭から消費する。
    """
    def _request(method, url, **kwargs):
        if calls is not None:
            calls.append({"method": method, "url": url, **kwargs})
        for key, value in responses.items():
            if key in url:
                if isinstance(value, list):
                    return value.pop(0) if len(value) > 1 else value[0]
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"想定外のURL: {url}")
    return _request


ALL_OK = {
    "generativelanguage": FakeResponse(GEMINI_OK),
    "openai.com": FakeResponse(GPT_OK),
    "anthropic.com": FakeResponse(CLAUDE_OK),
}


class RequestShapeTest(unittest.TestCase):
    """各プロバイダに送るリクエストの形を検証する。"""

    def test_request_shapes(self):
        calls = []
        with mock.patch.object(O.requests, "request", fake_request(dict(ALL_OK), calls)):
            O.orchestrate("テストタスク")

        by_host = {c["url"]: c for c in calls}
        gem = next(c for u, c in by_host.items() if "generativelanguage" in u)
        gpt = next(c for u, c in by_host.items() if "openai.com" in u)
        cla = next(c for u, c in by_host.items() if "anthropic.com" in u)

        # Gemini: キーは URL ではなくヘッダに載せる
        self.assertNotIn("key=", gem["url"])
        self.assertEqual(gem["headers"]["x-goog-api-key"], "test-goog")
        self.assertEqual(gem["json"]["contents"][0]["parts"][0]["text"], "テストタスク")

        # GPT
        self.assertEqual(gpt["headers"]["Authorization"], "Bearer sk-test-oai")
        self.assertEqual(gpt["json"]["messages"][0]["content"], "テストタスク")

        # Claude: 監督者としての設定
        self.assertEqual(cla["headers"]["x-api-key"], "sk-test-ant")
        self.assertEqual(cla["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(cla["json"]["thinking"], {"type": "adaptive"})
        self.assertEqual(cla["json"]["fallbacks"], "default")
        self.assertEqual(cla["json"]["max_tokens"], O.CLAUDE_MAX_TOKENS)

        prompt = cla["json"]["messages"][0]["content"]
        for expected in ("テストタスク", "Geminiの回答本文", "GPTの回答本文"):
            self.assertIn(expected, prompt)


class WorkerFailureTest(unittest.TestCase):
    """ワーカーが失敗しても全体は止まらないこと(元の実装のバグ)。"""

    def test_gpt_http_500_does_not_abort_run(self):
        responses = dict(ALL_OK, **{"openai.com": FakeResponse({"error": "boom"}, 500)})
        with mock.patch.object(O.requests, "request", fake_request(responses)), \
                mock.patch.object(O.time, "sleep"):
            result = O.orchestrate("テスト")

        self.assertIn("GPT呼び出し失敗", result["gpt"])
        self.assertIn("HTTP 500", result["gpt"])
        # Gemini の結果と Claude の統合は失われない
        self.assertEqual(result["gemini"], "Geminiの回答本文")
        self.assertEqual(result["claude_review"], "Claudeの統合結果")

    def test_gemini_connection_error_is_contained(self):
        responses = dict(ALL_OK,
                         **{"generativelanguage": O.requests.ConnectionError("接続失敗")})
        with mock.patch.object(O.requests, "request", fake_request(responses)), \
                mock.patch.object(O.time, "sleep"):
            result = O.orchestrate("テスト")

        self.assertIn("Gemini呼び出し失敗", result["gemini"])
        self.assertEqual(result["gpt"], "GPTの回答本文")

    def test_unparseable_response_falls_back(self):
        responses = dict(ALL_OK,
                         **{"generativelanguage": FakeResponse({"promptFeedback": {"blockReason": "SAFETY"}})})
        with mock.patch.object(O.requests, "request", fake_request(responses)):
            self.assertIn("Gemini応答解析失敗", O.call_gemini("x"))

    def test_missing_keys_are_skipped(self):
        with mock.patch.object(O, "GOOGLE_API_KEY", None), \
                mock.patch.object(O, "OPENAI_API_KEY", None):
            self.assertIn("GOOGLE_API_KEY未設定", O.call_gemini("x"))
            self.assertIn("OPENAI_API_KEY未設定", O.call_gpt("x"))

    def test_claude_requires_key(self):
        with mock.patch.object(O, "ANTHROPIC_API_KEY", None):
            with self.assertRaises(RuntimeError):
                O.call_claude("x")


class RetryTest(unittest.TestCase):
    def test_retries_429_then_succeeds(self):
        responses = dict(ALL_OK, **{
            "openai.com": [FakeResponse({}, 429, {"Retry-After": "0"}), FakeResponse(GPT_OK)]
        })
        with mock.patch.object(O.requests, "request", fake_request(responses)), \
                mock.patch.object(O.time, "sleep") as slept:
            self.assertEqual(O.call_gpt("x"), "GPTの回答本文")
        self.assertTrue(slept.called)

    def test_gives_up_after_max_retries(self):
        responses = dict(ALL_OK, **{"openai.com": FakeResponse({}, 503)})
        with mock.patch.object(O.requests, "request", fake_request(responses)), \
                mock.patch.object(O.time, "sleep"):
            self.assertIn("HTTP 503", O.call_gpt("x"))


class TruncationTest(unittest.TestCase):
    def test_claude_max_tokens_warns(self):
        payload = dict(CLAUDE_OK, stop_reason="max_tokens")
        with mock.patch.object(O.requests, "request",
                               fake_request({"anthropic.com": FakeResponse(payload)})):
            self.assertIn("警告", O.call_claude("x"))

    def test_claude_refusal_raises(self):
        payload = {"stop_reason": "refusal",
                   "stop_details": {"type": "refusal", "category": "cyber",
                                    "explanation": "declined"},
                   "content": []}
        with mock.patch.object(O.requests, "request",
                               fake_request({"anthropic.com": FakeResponse(payload)})):
            with self.assertRaises(RuntimeError):
                O.call_claude("x")

    def test_gpt_length_finish_reason_warns(self):
        payload = {"choices": [{"finish_reason": "length",
                                "message": {"content": "途中まで"}}]}
        with mock.patch.object(O.requests, "request",
                               fake_request({"openai.com": FakeResponse(payload)})):
            self.assertIn("finish_reason=length", O.call_gpt("x"))

    def test_gpt_empty_content(self):
        payload = {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}
        with mock.patch.object(O.requests, "request",
                               fake_request({"openai.com": FakeResponse(payload)})):
            self.assertIn("GPT応答が空", O.call_gpt("x"))


class ParallelismTest(unittest.TestCase):
    def test_workers_run_concurrently(self):
        import threading
        barrier = threading.Barrier(2, timeout=5)

        def slow_request(method, url, **kwargs):
            if "anthropic.com" not in url:
                barrier.wait()  # 両ワーカーが同時に到達しなければタイムアウトする
            return fake_request(dict(ALL_OK))(method, url, **kwargs)

        with mock.patch.object(O.requests, "request", slow_request):
            result = O.orchestrate("テスト")  # BrokenBarrierError なら直列実行
        self.assertEqual(result["claude_review"], "Claudeの統合結果")


class MarkdownTest(unittest.TestCase):
    def test_horizontal_rule_in_output_is_escaped(self):
        text = "前段\n---\n後段"
        self.assertEqual(O.sanitize_block(text), "前段\n\\---\n後段")

    def test_code_fence_contents_are_preserved(self):
        text = "```\n---\n```\n---"
        self.assertEqual(O.sanitize_block(text), "```\n---\n```\n\\---")

    def test_markdown_contains_all_sections(self):
        md = O.to_markdown({
            "task": "T", "gemini": "G", "gpt": "P", "claude_review": "C",
            "models": {"claude": "claude-opus-5", "gemini": "g", "gpt": "p"},
            "timestamp": "2026-01-01T00:00:00",
        })
        for expected in ("## タスク", "## Gemini の回答", "## GPT の回答",
                         "## Claude(監督者)によるレビュー・統合", "claude-opus-5"):
            self.assertIn(expected, md)


class CliTest(unittest.TestCase):
    def test_file_and_out_and_json(self):
        with TemporaryDirectory() as d:
            task_path = os.path.join(d, "task.txt")
            md_path = os.path.join(d, "report.md")
            json_path = os.path.join(d, "result.json")
            with open(task_path, "w", encoding="utf-8") as f:
                f.write("ファイルから読んだタスク")

            with mock.patch.object(O.requests, "request", fake_request(dict(ALL_OK))), \
                    redirect_stdout(io.StringIO()):
                code = O.main(["--file", task_path, "--out", md_path, "--json", json_path])

            self.assertEqual(code, 0)
            self.assertIn("ファイルから読んだタスク",
                          open(md_path, encoding="utf-8").read())
            saved = json.load(open(json_path, encoding="utf-8"))
            self.assertEqual(saved["claude_review"], "Claudeの統合結果")

    def test_missing_file_exits_cleanly(self):
        with self.assertRaises(SystemExit):
            O.main(["--file", "/nonexistent/task.txt"])

    def test_no_task_exits_cleanly(self):
        with self.assertRaises(SystemExit):
            O.main([])

    def test_claude_failure_returns_exit_code_1(self):
        responses = dict(ALL_OK, **{"anthropic.com": FakeResponse({"error": "x"}, 400)})
        with mock.patch.object(O.requests, "request", fake_request(responses)), \
                mock.patch.object(O.time, "sleep"), redirect_stdout(io.StringIO()):
            self.assertEqual(O.main(["タスク"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
