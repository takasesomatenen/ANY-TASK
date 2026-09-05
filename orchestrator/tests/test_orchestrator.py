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

O.BACKENDS.update({role: "api" for role in O.ROLES})
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
            "engines": {"claude": "claude-opus-5", "gemini": "g", "gpt": "p"},
            "backends": {"claude": "api", "gemini": "api", "gpt": "api"},
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


# ==========================================================================
# CLI バックエンド
# ==========================================================================

class FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def fake_run(result, calls=None):
    """subprocess.run の代役。result は FakeProc か送出する例外。"""
    def _run(argv, **kwargs):
        if calls is not None:
            calls.append({"argv": argv, **kwargs})
        if isinstance(result, Exception):
            raise result
        return result
    return _run


class CliArgvTest(unittest.TestCase):
    def test_default_commands(self):
        self.assertEqual(O.build_cli_argv("gemini", "やあ"), ["gemini", "-p", "やあ"])
        self.assertEqual(O.build_cli_argv("gpt", "やあ"), ["codex", "exec", "やあ"])
        self.assertEqual(O.build_cli_argv("claude", "やあ"), ["claude", "-p", "やあ"])

    def test_env_override_with_placeholder(self):
        with mock.patch.dict(os.environ, {"GEMINI_CLI_CMD": "mygem run --text={prompt} --json"}):
            self.assertEqual(
                O.build_cli_argv("gemini", "やあ"),
                ["mygem", "run", "--text=やあ", "--json"],
            )

    def test_env_override_without_placeholder_appends(self):
        with mock.patch.dict(os.environ, {"GPT_CLI_CMD": "mygpt ask"}):
            self.assertEqual(O.build_cli_argv("gpt", "やあ"), ["mygpt", "ask", "やあ"])

    def test_prompt_is_never_shell_interpreted(self):
        # プロンプトはあくまで1個の argv 要素であり、分割されない
        argv = O.build_cli_argv("gemini", "; rm -rf / && echo $HOME")
        self.assertEqual(argv[-1], "; rm -rf / && echo $HOME")
        self.assertEqual(len(argv), 3)

    def test_empty_command_rejected(self):
        with mock.patch.dict(os.environ, {"GPT_CLI_CMD": "   "}):
            with self.assertRaises(O.CliError):
                O.build_cli_argv("gpt", "x")


class CliInvocationTest(unittest.TestCase):
    def test_success_strips_ansi_and_whitespace(self):
        proc = FakeProc(stdout="\x1b[32m回答本文\x1b[0m\n\n")
        with mock.patch.object(O.subprocess, "run", fake_run(proc)):
            self.assertEqual(O.call_cli("gemini", "x"), "回答本文")

    def test_shell_is_not_used_and_stdin_is_closed(self):
        calls = []
        with mock.patch.object(O.subprocess, "run", fake_run(FakeProc("ok"), calls)):
            O.call_cli("gemini", "x")
        kwargs = calls[0]
        # 対話待ちでハングしないよう stdin を塞ぐ
        self.assertEqual(kwargs["stdin"], O.subprocess.DEVNULL)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], O.CLI_TIMEOUT)

    def test_command_not_found(self):
        with mock.patch.object(O.subprocess, "run", fake_run(FileNotFoundError())):
            with self.assertRaises(O.CliError) as cm:
                O.call_cli("gemini", "x")
        self.assertIn("コマンドが見つかりません", str(cm.exception))

    def test_non_zero_exit(self):
        proc = FakeProc(stdout="", stderr="not logged in", returncode=1)
        with mock.patch.object(O.subprocess, "run", fake_run(proc)):
            with self.assertRaises(O.CliError) as cm:
                O.call_cli("gemini", "x")
        self.assertIn("exit=1", str(cm.exception))
        self.assertIn("not logged in", str(cm.exception))

    def test_timeout(self):
        exc = O.subprocess.TimeoutExpired(cmd="gemini", timeout=1)
        with mock.patch.object(O.subprocess, "run", fake_run(exc)):
            with self.assertRaises(O.CliError) as cm:
                O.call_cli("gemini", "x", timeout=1)
        self.assertIn("タイムアウト", str(cm.exception))

    def test_empty_output(self):
        with mock.patch.object(O.subprocess, "run", fake_run(FakeProc("  \n"))):
            with self.assertRaises(O.CliError):
                O.call_cli("gemini", "x")


class CliBackendBehaviourTest(unittest.TestCase):
    def test_worker_cli_failure_is_contained(self):
        # ワーカーの CLI が失敗しても実行は止まらない
        with mock.patch.object(O.subprocess, "run", fake_run(FileNotFoundError())):
            out = O.call_gpt("x", backend="cli")
        self.assertIn("GPT CLI失敗", out)
        self.assertIn("コマンドが見つかりません", out)

    def test_cli_backend_needs_no_api_key(self):
        with mock.patch.object(O, "GOOGLE_API_KEY", None), \
                mock.patch.object(O.subprocess, "run", fake_run(FakeProc("CLIの回答"))):
            self.assertEqual(O.call_gemini("x", backend="cli"), "CLIの回答")

    def test_supervisor_cli_failure_is_fatal(self):
        # 監督者の失敗は封じ込めず送出する
        with mock.patch.object(O.subprocess, "run", fake_run(FileNotFoundError())):
            with self.assertRaises(O.CliError):
                O.call_claude("x", backend="cli")

    def test_mixed_backends(self):
        """Gemini は CLI、GPT と Claude は API、という混在構成。"""
        with mock.patch.object(O.requests, "request", fake_request(dict(ALL_OK))), \
                mock.patch.object(O.subprocess, "run", fake_run(FakeProc("Gemini CLIの回答"))):
            result = O.orchestrate("テスト", {"gemini": "cli", "gpt": "api", "claude": "api"})

        self.assertEqual(result["gemini"], "Gemini CLIの回答")
        self.assertEqual(result["gpt"], "GPTの回答本文")
        self.assertEqual(result["claude_review"], "Claudeの統合結果")
        self.assertEqual(result["backends"], {"gemini": "cli", "gpt": "api", "claude": "api"})
        self.assertEqual(result["engines"]["gemini"], "gemini (CLI)")
        self.assertEqual(result["engines"]["claude"], O.CLAUDE_MODEL)

    def test_all_cli(self):
        outputs = {"gemini": "G-CLI", "codex": "P-CLI", "claude": "C-CLI"}

        def by_command(argv, **kwargs):
            return FakeProc(outputs[argv[0]])

        with mock.patch.object(O.subprocess, "run", by_command):
            result = O.orchestrate("テスト", {r: "cli" for r in O.ROLES})

        self.assertEqual(result["gemini"], "G-CLI")
        self.assertEqual(result["gpt"], "P-CLI")
        self.assertEqual(result["claude_review"], "C-CLI")
        self.assertIn("gemini (CLI)", O.to_markdown(result))

    def test_unknown_backend_rejected(self):
        with self.assertRaises(ValueError):
            O.call_gemini("x", backend="carrier-pigeon")

    def test_workers_run_concurrently_on_cli(self):
        import threading
        barrier = threading.Barrier(2, timeout=5)

        def slow_run(argv, **kwargs):
            barrier.wait()  # 直列なら BrokenBarrierError
            return FakeProc("ok")

        with mock.patch.object(O.subprocess, "run", slow_run), \
                mock.patch.object(O.requests, "request", fake_request(dict(ALL_OK))):
            result = O.orchestrate("テスト", {"gemini": "cli", "gpt": "cli", "claude": "api"})
        self.assertEqual(result["gemini"], "ok")


class CliCliArgsTest(unittest.TestCase):
    def test_backend_flag_applies_to_all_roles(self):
        outputs = {"gemini": "G", "codex": "P", "claude": "C"}
        with mock.patch.object(O.subprocess, "run",
                               lambda argv, **kw: FakeProc(outputs[argv[0]])), \
                redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(O.main(["タスク", "--backend", "cli"]), 0)
        self.assertIn("gemini (CLI) [cli]", buf.getvalue())

    def test_per_role_flag_overrides_global(self):
        with mock.patch.object(O.requests, "request", fake_request(dict(ALL_OK))), \
                mock.patch.object(O.subprocess, "run",
                                  lambda argv, **kw: FakeProc("G-CLI")), \
                redirect_stdout(io.StringIO()) as buf:
            code = O.main(["タスク", "--gemini-backend", "cli"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("G-CLI", out)
        self.assertIn("GPTの回答本文", out)

    def test_cli_timeout_flag(self):
        original = O.CLI_TIMEOUT
        calls = []
        try:
            with mock.patch.object(O.subprocess, "run", fake_run(FakeProc("ok"), calls)), \
                    redirect_stdout(io.StringIO()):
                O.main(["タスク", "--backend", "cli", "--cli-timeout", "5"])
            self.assertEqual(calls[0]["timeout"], 5)
        finally:
            O.CLI_TIMEOUT = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
