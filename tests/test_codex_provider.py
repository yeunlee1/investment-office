# Codex 정액제 provider의 격리 실행과 실패 경계를 검증한다
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from investment_office.services.codex_provider import (
    CodexExecutableNotFoundError,
    CodexInputError,
    CodexOutputLimitError,
    CodexProcessError,
    CodexProvider,
    CodexResponseValidationError,
    CodexTimeoutError,
)


class FakeStdin:
    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def is_closing(self) -> bool:
        return self.closed


def make_stream(data: bytes) -> asyncio.StreamReader:
    stream = asyncio.StreamReader()
    stream.feed_data(data)
    stream.feed_eof()
    return stream


class FakeProcess:
    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        wait_forever: bool = False,
    ) -> None:
        self.stdin = FakeStdin()
        self.stdout = make_stream(stdout)
        self.stderr = make_stream(stderr)
        self.returncode: int | None = None
        self.target_returncode = returncode
        self.killed = False
        self.wait_event = asyncio.Event()
        if not wait_forever:
            self.wait_event.set()

    async def wait(self) -> int:
        await self.wait_event.wait()
        self.returncode = self.target_returncode
        return self.target_returncode

    def kill(self) -> None:
        self.killed = True
        self.wait_event.set()


@pytest.fixture
def snapshot() -> dict[str, Any]:
    return {
        "price": 123.45,
        "source_url": "https://example.com/filing",
        "published_at": "2026-07-10",
    }


@pytest.fixture
def valid_result() -> dict[str, Any]:
    return {
        "role": "technical",
        "ticker": "AAPL",
        "stance": "neutral",
        "confidence": 0.72,
        "summary": "추세 확인에 필요한 기간별 데이터가 부족하다.",
        "key_points": ["현재 가격은 123.45로 제공되었다."],
        "evidence": [
            {
                "claim": "입력에 현재 가격이 포함되어 있다.",
                "source_url": "https://example.com/filing",
                "published_at": "2026-07-10",
            }
        ],
        "risks": ["단일 시점 가격만으로 추세를 판단할 수 없다."],
        "recommendation": "추가 시계열 데이터가 들어올 때까지 관찰한다.",
        "data_gaps": ["가격 시계열과 거래량이 없다."],
        "invalidations": ["충분한 시계열이 추가되면 현재 판단을 다시 평가한다."],
    }


def install_fake_spawn(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: dict[str, Any] | str | None,
    stdout: bytes = b'{"type":"turn.started"}\n{"type":"turn.completed"}\n',
    stderr: bytes = b"",
    returncode: int = 0,
    wait_forever: bool = False,
) -> tuple[dict[str, Any], FakeProcess]:
    captured: dict[str, Any] = {}
    process = FakeProcess(
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        wait_forever=wait_forever,
    )

    async def fake_spawn(*command: str, **options: Any) -> FakeProcess:
        captured["command"] = list(command)
        captured["options"] = options
        if result is not None:
            result_path = Path(command[command.index("--output-last-message") + 1])
            content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            result_path.write_text(content, encoding="utf-8")
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    return captured, process


@pytest.mark.asyncio
async def test_analyze_uses_saved_auth_read_only_json_and_callbacks(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict[str, Any],
    valid_result: dict[str, Any],
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-reach-child")
    captured, process = install_fake_spawn(monkeypatch, result=valid_result)
    statuses: list[dict[str, Any]] = []
    progress: list[dict[str, Any]] = []

    async def record_status(event: dict[str, Any]) -> None:
        statuses.append(event)

    provider = CodexProvider(
        command="codex",
        status_callback=record_status,
        progress_callback=progress.append,
    )
    result = await provider.analyze("technical", "aapl", snapshot, [])

    assert result == valid_result
    command = captured["command"]
    assert command[:2] == ["codex", "exec"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--output-schema" in command
    assert "--json" in command
    assert command[-1] == "-"
    assert "shell" not in captured["options"]
    child_env = captured["options"]["env"]
    assert "OPENAI_API_KEY" not in child_env
    assert "CODEX_API_KEY" not in child_env
    prompt = process.stdin.data.decode("utf-8")
    assert "어떤 도구도 사용하지 않는다" in prompt
    assert "입력에 없는 사실, 수치, 날짜, 출처 URL을 만들지 않는다" in prompt
    assert "manual_work_request 또는 committee_directed_request" in prompt
    assert "제목과 질문을 분석 초점으로만 사용한다" in prompt
    assert [event["status"] for event in statuses] == ["started", "completed"]
    assert [event["type"] for event in progress] == ["turn.started", "turn.completed"]


@pytest.mark.asyncio
async def test_analyze_rejects_non_json_result(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict[str, Any],
) -> None:
    install_fake_spawn(monkeypatch, result="not-json")

    with pytest.raises(CodexResponseValidationError, match="유효한 JSON"):
        await CodexProvider().analyze("technical", "AAPL", snapshot, [])


@pytest.mark.asyncio
async def test_analyze_rejects_schema_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict[str, Any],
    valid_result: dict[str, Any],
) -> None:
    invalid_result = valid_result | {"confidence": "high"}
    install_fake_spawn(monkeypatch, result=invalid_result)

    with pytest.raises(CodexResponseValidationError, match="스키마"):
        await CodexProvider().analyze("technical", "AAPL", snapshot, [])


@pytest.mark.asyncio
async def test_analyze_rejects_empty_structured_list_item(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict[str, Any],
    valid_result: dict[str, Any],
) -> None:
    invalid_result = valid_result | {"data_gaps": [""]}
    install_fake_spawn(monkeypatch, result=invalid_result)

    with pytest.raises(CodexResponseValidationError, match="스키마"):
        await CodexProvider().analyze("technical", "AAPL", snapshot, [])


@pytest.mark.asyncio
async def test_analyze_rejects_fabricated_source_url(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict[str, Any],
    valid_result: dict[str, Any],
) -> None:
    invalid_result = json.loads(json.dumps(valid_result))
    invalid_result["evidence"][0]["source_url"] = "https://invented.example/report"
    install_fake_spawn(monkeypatch, result=invalid_result)

    with pytest.raises(CodexResponseValidationError, match="입력 데이터에 없는 출처"):
        await CodexProvider().analyze("technical", "AAPL", snapshot, [])


@pytest.mark.asyncio
async def test_analyze_rejects_fabricated_publication_date(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict[str, Any],
    valid_result: dict[str, Any],
) -> None:
    invalid_result = json.loads(json.dumps(valid_result))
    invalid_result["evidence"][0]["published_at"] = "2025-01-01"
    install_fake_spawn(monkeypatch, result=invalid_result)

    with pytest.raises(CodexResponseValidationError, match="published_at"):
        await CodexProvider().analyze("technical", "AAPL", snapshot, [])


@pytest.mark.asyncio
async def test_analyze_raises_explicit_process_error(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict[str, Any],
) -> None:
    install_fake_spawn(
        monkeypatch,
        result=None,
        stdout=b'{"type":"turn.failed"}\n',
        stderr=b"usage limit exceeded",
        returncode=1,
    )

    with pytest.raises(CodexProcessError, match="usage limit exceeded") as error:
        await CodexProvider().analyze("technical", "AAPL", snapshot, [])

    assert error.value.returncode == 1


@pytest.mark.asyncio
async def test_analyze_kills_process_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict[str, Any],
) -> None:
    _, process = install_fake_spawn(
        monkeypatch,
        result=None,
        stdout=b"",
        wait_forever=True,
    )

    with pytest.raises(CodexTimeoutError, match="제한을 초과"):
        await CodexProvider(timeout_seconds=0.01).analyze("technical", "AAPL", snapshot, [])

    assert process.killed is True


@pytest.mark.asyncio
async def test_analyze_kills_process_when_stdout_exceeds_limit(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict[str, Any],
) -> None:
    _, process = install_fake_spawn(
        monkeypatch,
        result=None,
        stdout=b"x" * 32,
        wait_forever=True,
    )

    with pytest.raises(CodexOutputLimitError, match="stdout"):
        await CodexProvider(max_stdout_bytes=8).analyze("technical", "AAPL", snapshot, [])

    assert process.killed is True


@pytest.mark.asyncio
async def test_analyze_reports_missing_executable(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict[str, Any],
) -> None:
    async def missing_spawn(*command: str, **options: Any) -> FakeProcess:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", missing_spawn)

    with pytest.raises(CodexExecutableNotFoundError, match="찾을 수 없습니다"):
        await CodexProvider(command="missing-codex").analyze("technical", "AAPL", snapshot, [])


@pytest.mark.asyncio
async def test_analyze_rejects_invalid_input_before_spawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def should_not_spawn(*command: str, **options: Any) -> FakeProcess:
        nonlocal called
        called = True
        raise AssertionError("subprocess should not be called")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", should_not_spawn)

    with pytest.raises(CodexInputError, match="지원하지 않는 분석 역할"):
        await CodexProvider().analyze("unknown", "AAPL", {}, [])

    assert called is False
