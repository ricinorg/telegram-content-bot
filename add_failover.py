"""Add independent-account failover to the previously built fixed project ZIP.
Usage: python add_failover.py telegram-content-bot-fixed.zip
Output: telegram-content-bot-failover.zip. Python 3.10+.
No API calls. Does not overwrite source ZIP. Run tests before deployment.
"""
import argparse
import ast
import zipfile
from pathlib import Path, PurePosixPath

MODULE = r'''import logging
import os
import threading
import time
from types import SimpleNamespace
from openai import OpenAI
from ai import AIService as BaseAIService, AIServiceError

logger = logging.getLogger("telegram-content-bot.failover")


class AIService(BaseAIService):
    """All inherited generation methods dispatch through this shared _call.
    Cooldowns are process-local and expire automatically; restart clears them.
    Model switching does not guarantee identical output quality.
    """
    def __init__(self, key, text_model, base_url="https://cleanapis.com/v1"):
        super().__init__(key, text_model, base_url)
        self._lock = threading.Lock()
        self._clock = time.monotonic
        self._sleep = time.sleep
        self.active_model = self.text_model
        self._endpoints = [SimpleNamespace(
            name="deepseek", model=self.text_model, client=self.client,
            blocked_until=0.0, reason=None)]
        for name, model, variable in (
            ("gemma", "gemma-2-2b", "GEMMA_API_KEY"),
            ("gpt", "gpt-5.6-luna", "GPT_API_KEY"),
            ("qwen", "qwen3.8-27b", "QWEN_API_KEY"),
        ):
            secret = os.getenv(variable, "").strip()
            if not secret:
                logger.info("Fallback not configured: %s", name)
                continue
            client = OpenAI(api_key=secret, base_url="https://cleanapis.com/v1",
                            timeout=60.0, max_retries=0)
            self._endpoints.append(SimpleNamespace(
                name=name, model=model, client=client,
                blocked_until=0.0, reason=None))

    def close(self):
        for endpoint in self._endpoints:
            endpoint.client.close()

    def _block(self, endpoint, seconds, reason):
        with self._lock:
            endpoint.blocked_until = max(endpoint.blocked_until,
                                         self._clock() + seconds)
            endpoint.reason = reason

    @staticmethod
    def _error_kind(exc):
        status = getattr(exc, "status_code", None)
        body = getattr(exc, "body", None)
        code = ""
        if isinstance(body, dict):
            error = body.get("error", body)
            if isinstance(error, dict):
                code = str(error.get("code", "")).lower()
        if status == 402 or code in {"insufficient_quota", "insufficient_balance"}:
            return "quota", 3600
        if status in {401, 403}:
            return "access", 3600
        if status == 404 or code in {"model_not_found", "model_not_available", "unsupported_model"}:
            return "model", 3600
        if status == 429:
            delay = 60.0
            response = getattr(exc, "response", None)
            headers = getattr(response, "headers", {}) or {}
            try:
                delay = max(1.0, min(float(headers.get("retry-after", 60)), 3600.0))
            except (TypeError, ValueError):
                pass
            return "rate", delay
        if status is not None and status >= 500:
            return "temporary", 30
        if isinstance(exc, (TimeoutError, ConnectionError)) or type(exc).__name__ in {
            "APITimeoutError", "APIConnectionError"}:
            return "temporary", 30
        # Bad payload/context size and local programming errors must not
        # silently trigger a sequence of paid requests to other models.
        return "invalid", 0

    def _call(self, prompt, temperature=0.8, max_output_tokens=2048, retries=3):
        if not prompt or not prompt.strip():
            raise AIServiceError("Prompt ط®ط§ظ„غŒ ط§ط³طھ.")
        attempts = max(1, min(int(retries), 3))
        for endpoint in self._endpoints:
            with self._lock:
                blocked = endpoint.blocked_until > self._clock()
            if blocked:
                continue
            for attempt in range(attempts):
                kind, delay = "temporary", 30
                try:
                    logger.info("AI request: account=%s model=%s attempt=%s",
                                endpoint.name, endpoint.model, attempt + 1)
                    response = endpoint.client.chat.completions.create(
                        model=endpoint.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=temperature, max_tokens=max_output_tokens)
                    text = self._extract_text(response)
                    if text:
                        with self._lock:
                            self.active_model = endpoint.model
                        return text
                    logger.warning("Empty AI response: account=%s", endpoint.name)
                except Exception as exc:
                    kind, delay = self._error_kind(exc)
                    # Never log provider bodies, exception strings, keys or prompts.
                    logger.warning("AI failure: account=%s category=%s status=%s",
                                   endpoint.name, kind, getattr(exc, "status_code", None))
                    if kind == "invalid":
                        raise AIServiceError(
                            "ط¯ط±ط®ظˆط§ط³طھ AI ط±ط¯ ط´ط¯ غŒط§ ط®ط·ط§غŒ ط¯ط§ط®ظ„غŒ ط±ط® ط¯ط§ط¯ط› ظ‚ط§ظ„ط¨ ط¯ط±ط®ظˆط§ط³طھ ظˆ ط§ظ†ط¯ط§ط²ظ‡ ظ…طھظ† ط±ط§ ط¨ط±ط±ط³غŒ ع©ظ†غŒط¯."
                        ) from None
                if kind == "temporary" and attempt + 1 < attempts:
                    self._sleep(min(2 ** attempt, 4))
                    continue
                self._block(endpoint, delay, kind)
                break
        raise AIServiceError(
            "ظ‡غŒع† ط­ط³ط§ط¨ AI ط¢ظ…ط§ط¯ظ‡ ظ¾ط§ط³ط® ظ†غŒط³طھط› ط§ط¹طھط¨ط§ط±طŒ ط¯ط³طھط±ط³غŒ ظˆ ظ…ط­ط¯ظˆط¯غŒطھ ط¯ط±ط®ظˆط§ط³طھ ط­ط³ط§ط¨â€Œظ‡ط§ ط±ط§ ط¨ط±ط±ط³غŒ ع©ظ†غŒط¯. "
            "ط­ط³ط§ط¨ ط¨غŒâ€Œط§ط¹طھط¨ط§ط± غŒع© ط³ط§ط¹طھ ظˆ ط­ط³ط§ط¨ ظ…ظˆظ‚طھط§ظ‹ ط®ط·ط§ط¯ط§ط± ظ…ط¯طھ ع©ظˆطھط§ظ‡â€Œطھط±غŒ ع©ظ†ط§ط± ع¯ط°ط§ط´طھظ‡ ظ…غŒâ€Œط´ظˆط¯."
        ) from None
'''


TESTS = r'''from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from ai import AIServiceError
from ai_failover import AIService


class APIError(Exception):
    def __init__(self, status, code=""):
        self.status_code = status
        self.body = {"error": {"code": code}}


def response(text):
    return NS(choices=[NS(message=NS(content=text))])


def endpoint(name, outcomes):
    create = Mock(side_effect=outcomes)
    return NS(name=name, model=name, blocked_until=0, reason=None,
              client=NS(chat=NS(completions=NS(create=create)), close=Mock()))


@pytest.fixture
def service(monkeypatch):
    for key in ("GEMMA_API_KEY", "GPT_API_KEY", "QWEN_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    instance = AIService("test-placeholder", "deepseek", "https://example.invalid/v1")
    primary_client = instance.client
    instance._clock = lambda: 100
    instance._sleep = lambda seconds: None
    yield instance
    primary_client.close()


def test_quota_switch_and_cooldown(service):
    first = endpoint("deepseek", [APIError(402)])
    second = endpoint("gemma", [response("ظ¾ط§ط³ط®"), response("ط¨ط¹ط¯غŒ")])
    service._endpoints = [first, second]
    assert service.generate_text("ظ…ظˆط¶ظˆط¹") == "ظ¾ط§ط³ط®"
    assert service.active_model == "gemma"
    assert first.blocked_until == 3700
    assert service.edit_text("ظ…ظˆط¶ظˆط¹", "ظ…طھظ†", "ع©ظˆطھط§ظ‡ ع©ظ†") == "ط¨ط¹ط¯غŒ"
    assert first.client.chat.completions.create.call_count == 1


def test_all_accounts_exhausted(service):
    service._endpoints = [endpoint("first", [APIError(402)]), endpoint("second", [APIError(429, "insufficient_quota")])]
    with pytest.raises(AIServiceError, match="ظ‡غŒع† ط­ط³ط§ط¨"):
        service.generate_text("ظ…ظˆط¶ظˆط¹")
    assert all(item.reason == "quota" for item in service._endpoints)


def test_invalid_payload_does_not_spend_on_next_model(service):
    first = endpoint("first", [APIError(400)])
    second = endpoint("second", [response("unused")])
    service._endpoints = [first, second]
    with pytest.raises(AIServiceError):
        service.generate_text("ظ…ظˆط¶ظˆط¹")
    second.client.chat.completions.create.assert_not_called()


def test_temporary_retries_then_switch(service):
    first = endpoint("first", [APIError(503), APIError(503)])
    second = endpoint("second", [response("OK")])
    service._endpoints = [first, second]
    assert service._call("test", retries=2) == "OK"
    assert first.client.chat.completions.create.call_count == 2


def test_expired_cooldown_recovers_priority(service):
    first = endpoint("first", [response("restored")])
    first.blocked_until = 99
    second = endpoint("second", [response("unused")])
    service._endpoints = [first, second]
    assert service._call("test") == "restored"
    second.client.chat.completions.create.assert_not_called()
'''

NOTES = '''# Independent-account AI failover

Order: DeepSeek -> Gemma -> GPT -> Qwen.
Render environment variables:
DEEPSEEK_API_KEY (existing, required)
GEMMA_API_KEY (optional)
GPT_API_KEY (optional)
QWEN_API_KEY (optional)

Additional models use https://cleanapis.com/v1.
No key is embedded in these files. Unconfigured backups are skipped.
Each key must belong to the intended independently funded account.
Quota/access/model errors use a one-hour process-local cooldown; numeric Retry-After
is respected for 429 (bounded to one hour); temporary errors use bounded retries.
Cooldown expiry re-enables an account for a probe. Restart clears cooldowns.
Do not run multiple copies expecting these in-memory cooldowns to be shared.
No tokens/balance are inferred from local counting. Actual API errors trigger switching.
Bad payloads or unexpected internal errors stop rather than silently spending on backups.
Model quality and context limits differ; switching does not guarantee identical output.
active_model shows the most recent successful request, not a permanently selected provider.
All inherited AI methods use the same dispatcher, including topic extraction and chat.
Existing DB and queue logic is not changed by this patch.
Run: python -m pip install -r requirements.txt; python -m pytest -q
Tests are offline tests; authoring assistant has NOT run them or real API requests.
Secrets should remain only in Render environment variables.
See README.md for the prior additive database migration and remaining limitations.
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_zip', type=Path)
    parser.add_argument('--output', type=Path, default=Path('telegram-content-bot-failover.zip'))
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError('Output exists; choose another --output')
    with zipfile.ZipFile(args.source_zip) as z:
        entries = z.infolist()
        candidates = [e for e in entries if PurePosixPath(e.filename).name == 'bot.py']
        if len(candidates) != 1:
            raise RuntimeError('Expected exactly one bot.py in the fixed project ZIP')
        root = PurePosixPath(candidates[0].filename).parent
        files = {}
        for e in entries:
            path = PurePosixPath(e.filename)
            if e.is_dir() or path.is_absolute() or '..' in path.parts:
                continue
            if path.parent != root:
                continue
            if path.name == '.env' or path.name.endswith(('.db', '.sqlite', '.sqlite3')) or '.db-' in path.name:
                continue
            files[path.name] = z.read(e)
    required = {'bot.py','ai.py','admin_panel.py','test_stage1.py','test_tree.py'}
    if not required.issubset(files):
        raise RuntimeError('Use the fixed ZIP built by build_fixed_bot.py, not the original ZIP')
    bot = files['bot.py'].decode('utf-8')
    original = 'from ai import AIService, AIServiceError'
    if bot.count(original) != 1:
        raise RuntimeError('Source mismatch or failover already installed')
    bot = bot.replace(original, 'from ai import AIServiceError\nfrom ai_failover import AIService')
    bot = bot.replace('{ai.text_model}', '{ai.active_model}')
    panel = files['admin_panel.py'].decode('utf-8')
    panel = panel.replace('{settings.deepseek_model}', '{ai.active_model}')
    panel = panel.replace('{settings.deepseek_base_url}', '{ai.base_url}')
    panel = panel.replace('f"Base URL: {ai.base_url}\\n"',
                          'f"Base URL ط§طµظ„غŒ: {ai.base_url}\\n"')
    files.update({'bot.py':bot.encode('utf-8'), 'admin_panel.py':panel.encode('utf-8'),
                  'ai_failover.py':MODULE.encode('utf-8'),
                  'test_failover.py':TESTS.encode('utf-8'),
                  'FAILOVER.md':NOTES.encode('utf-8')})
    if '.env.example' in files:
        example = files['.env.example'].decode('utf-8')
        example += '\n# Independent-account backups; leave blank to disable.\nGEMMA_API_KEY=\nGPT_API_KEY=\nQWEN_API_KEY=\n'
        files['.env.example'] = example.encode('utf-8')
    for name, payload in files.items():
        if name.endswith('.py'):
            compile(payload.decode('utf-8'), name, 'exec')
    with zipfile.ZipFile(args.output, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, payload in sorted(files.items()):
            z.writestr('telegram-content-bot-failover/' + name, payload)
    print('Created:', args.output)
    print('Syntax checked by builder. Tests and actual API calls have NOT been run.')


if __name__ == '__main__':
    main()
