# 저장된 ChatGPT 로그인을 재사용해 Codex 구조화 분석을 실행한다
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from investment_office.services.prompts import ANALYSIS_OUTPUT_SCHEMA, build_analysis_prompt

type CallbackResult = Awaitable[None] | None
type EventCallback = Callable[[dict[str, Any]], CallbackResult]
type NonEmptyString = Annotated[str, Field(min_length=1)]


class CodexProviderError(RuntimeError):
    """Base error for every explicit Codex provider failure."""


class CodexConfigurationError(CodexProviderError):
    """Raised when provider configuration is invalid."""


class CodexInputError(CodexProviderError):
    """Raised when analysis input cannot be represented safely."""


class CodexExecutableNotFoundError(CodexProviderError):
    """Raised when the configured Codex executable is unavailable."""


class CodexLaunchError(CodexProviderError):
    """Raised when the Codex child process cannot be started or fed."""


class CodexTimeoutError(CodexProviderError):
    """Raised when a Codex invocation exceeds its deadline."""


class CodexOutputLimitError(CodexProviderError):
    """Raised when a child-process stream exceeds its configured bound."""


class CodexProtocolError(CodexProviderError):
    """Raised when JSONL progress output violates the documented protocol."""


class CodexProcessError(CodexProviderError):
    """Raised when Codex exits unsuccessfully."""

    def __init__(self, returncode: int, detail: str) -> None:
        self.returncode = returncode
        self.detail = detail
        super().__init__(f"Codex 실행이 종료 코드 {returncode}로 실패했습니다. {detail}")


class CodexResponseValidationError(CodexProviderError):
    """Raised when the final response is missing, malformed, or ungrounded."""


class EvidenceItem(BaseModel):
    """A claim with only source metadata already present in the input."""

    model_config = ConfigDict(extra="forbid", strict=True)

    claim: NonEmptyString
    source_url: str | None
    published_at: str | None


class AnalysisResult(BaseModel):
    """Runtime validation model matching the schema supplied to Codex."""

    model_config = ConfigDict(extra="forbid", strict=True)

    role: NonEmptyString
    ticker: NonEmptyString
    stance: Literal["bullish", "neutral", "bearish"]
    confidence: float = Field(ge=0, le=1)
    summary: NonEmptyString
    key_points: list[NonEmptyString]
    evidence: list[EvidenceItem]
    risks: list[NonEmptyString]
    recommendation: NonEmptyString
    data_gaps: list[NonEmptyString]
    invalidations: list[NonEmptyString]


class CodexProvider:
    """Run one isolated, read-only ``codex exec`` analysis per request."""

    def __init__(
        self,
        *,
        command: str | os.PathLike[str] | None = None,
        timeout_seconds: float | None = None,
        max_stdout_bytes: int = 1_048_576,
        max_stderr_bytes: int = 262_144,
        max_result_bytes: int = 262_144,
        status_callback: EventCallback | None = None,
        progress_callback: EventCallback | None = None,
    ) -> None:
        configured_command = (
            os.fspath(command)
            if command is not None
            else os.getenv("INVESTMENT_OFFICE_CODEX_COMMAND", "codex")
        )
        if not configured_command.strip() or "\x00" in configured_command:
            raise CodexConfigurationError("Codex 실행 명령이 비어 있거나 유효하지 않습니다.")

        self.command = configured_command
        self.timeout_seconds = self._resolve_timeout(timeout_seconds)
        self.max_stdout_bytes = self._positive_limit("max_stdout_bytes", max_stdout_bytes)
        self.max_stderr_bytes = self._positive_limit("max_stderr_bytes", max_stderr_bytes)
        self.max_result_bytes = self._positive_limit("max_result_bytes", max_result_bytes)
        self.status_callback = status_callback
        self.progress_callback = progress_callback

    async def analyze(
        self,
        role: str,
        ticker: str,
        snapshot: dict[str, Any],
        context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute a role analysis and return a validated JSON-compatible dictionary."""

        if not isinstance(role, str) or not role.strip():
            raise CodexInputError("role은 비어 있지 않은 문자열이어야 합니다.")
        if not isinstance(ticker, str) or not ticker.strip():
            raise CodexInputError("ticker는 비어 있지 않은 문자열이어야 합니다.")

        expected_role = role.strip()
        expected_ticker = ticker.strip().upper()
        try:
            prompt = build_analysis_prompt(expected_role, expected_ticker, snapshot, context)
        except ValueError as exc:
            raise CodexInputError(str(exc)) from exc

        await self._emit_status("started", expected_role, expected_ticker)
        try:
            result = await self._analyze_in_temporary_directory(
                prompt,
                expected_role,
                expected_ticker,
                snapshot,
                context,
            )
        except BaseException as exc:
            if not isinstance(exc, (KeyboardInterrupt, SystemExit)):
                await self._emit_status("failed", expected_role, expected_ticker, error=str(exc))
            raise

        await self._emit_status("completed", expected_role, expected_ticker)
        return result

    async def _analyze_in_temporary_directory(
        self,
        prompt: str,
        role: str,
        ticker: str,
        snapshot: dict[str, Any],
        context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="investment-office-codex-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            schema_path = temp_dir / "analysis-schema.json"
            result_path = temp_dir / "analysis-result.json"
            schema_path.write_text(
                json.dumps(ANALYSIS_OUTPUT_SCHEMA, ensure_ascii=False),
                encoding="utf-8",
            )

            command = self._build_command(schema_path, result_path)
            await self._run_process(command, prompt, temp_dir)
            return self._read_and_validate_result(
                result_path,
                role,
                ticker,
                snapshot,
                context,
            )

    def _build_command(self, schema_path: Path, result_path: Path) -> list[str]:
        return [
            self.command,
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(result_path),
            "--json",
            "--color",
            "never",
            "-",
        ]

    async def _run_process(self, command: list[str], prompt: str, cwd: Path) -> None:
        child_env = os.environ.copy()
        child_env.pop("OPENAI_API_KEY", None)
        child_env.pop("CODEX_API_KEY", None)
        spawn_options: dict[str, Any] = {
            "stdin": asyncio.subprocess.PIPE,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "cwd": str(cwd),
            "env": child_env,
        }
        if os.name == "nt":
            spawn_options["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            # create_subprocess_exec는 셸을 호출하지 않으므로 shell=False 실행과 같다.
            process = await asyncio.create_subprocess_exec(*command, **spawn_options)
        except FileNotFoundError as exc:
            raise CodexExecutableNotFoundError(
                f"Codex 실행 파일을 찾을 수 없습니다. 설정값은 {self.command!r}입니다."
            ) from exc
        except OSError as exc:
            raise CodexLaunchError(f"Codex 프로세스를 시작하지 못했습니다. {exc}") from exc

        if process.stdin is None or process.stdout is None or process.stderr is None:
            await self._stop_process(process)
            raise CodexLaunchError("Codex 프로세스 파이프를 만들지 못했습니다.")

        stdout_task = asyncio.create_task(
            self._read_limited_stream(
                process.stdout,
                stream_name="stdout",
                limit=self.max_stdout_bytes,
                parse_progress=True,
            )
        )
        stderr_task = asyncio.create_task(
            self._read_limited_stream(
                process.stderr,
                stream_name="stderr",
                limit=self.max_stderr_bytes,
                parse_progress=False,
            )
        )
        wait_task = asyncio.create_task(process.wait())
        tasks = (wait_task, stdout_task, stderr_task)

        try:
            process.stdin.write(prompt.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
            returncode, stdout, stderr = await asyncio.wait_for(
                asyncio.gather(*tasks),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            await self._stop_process(process)
            await self._cancel_tasks(tasks)
            raise CodexTimeoutError(
                f"Codex 분석이 {self.timeout_seconds:g}초 제한을 초과했습니다."
            ) from exc
        except (BrokenPipeError, ConnectionResetError) as exc:
            await self._stop_process(process)
            await self._cancel_tasks(tasks)
            raise CodexLaunchError("Codex 프로세스가 프롬프트 입력 전에 종료되었습니다.") from exc
        except BaseException:
            await self._stop_process(process)
            await self._cancel_tasks(tasks)
            raise
        finally:
            if not process.stdin.is_closing():
                process.stdin.close()

        if returncode != 0:
            detail = self._decode_detail(stderr) or self._decode_detail(stdout)
            raise CodexProcessError(returncode, detail or "세부 오류 출력이 없습니다.")

    async def _read_limited_stream(
        self,
        stream: asyncio.StreamReader,
        *,
        stream_name: str,
        limit: int,
        parse_progress: bool,
    ) -> bytes:
        collected = bytearray()
        pending = bytearray()
        while True:
            chunk = await stream.read(65_536)
            if not chunk:
                break
            if len(collected) + len(chunk) > limit:
                raise CodexOutputLimitError(
                    f"Codex {stream_name} 출력이 {limit}바이트 제한을 초과했습니다."
                )
            collected.extend(chunk)
            if parse_progress:
                pending.extend(chunk)
                while b"\n" in pending:
                    raw_line, _, remainder = pending.partition(b"\n")
                    pending = bytearray(remainder)
                    await self._handle_progress_line(bytes(raw_line))

        if parse_progress and pending.strip():
            await self._handle_progress_line(bytes(pending))
        return bytes(collected)

    async def _handle_progress_line(self, raw_line: bytes) -> None:
        if not raw_line.strip():
            return
        try:
            event = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CodexProtocolError(
                "Codex --json stdout에 유효하지 않은 JSONL 행이 있습니다."
            ) from exc
        if not isinstance(event, dict):
            raise CodexProtocolError("Codex --json 이벤트는 JSON 객체여야 합니다.")
        await self._call_callback(self.progress_callback, event)

    def _read_and_validate_result(
        self,
        result_path: Path,
        expected_role: str,
        expected_ticker: str,
        snapshot: dict[str, Any],
        context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            result_size = result_path.stat().st_size
        except FileNotFoundError as exc:
            raise CodexResponseValidationError(
                "Codex가 최종 JSON 결과 파일을 생성하지 않았습니다."
            ) from exc
        if result_size > self.max_result_bytes:
            raise CodexOutputLimitError(
                f"Codex 최종 JSON이 {self.max_result_bytes}바이트 제한을 초과했습니다."
            )

        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CodexResponseValidationError("Codex 최종 결과가 유효한 JSON이 아닙니다.") from exc
        try:
            validated = AnalysisResult.model_validate(payload)
        except ValidationError as exc:
            detail = json.dumps(exc.errors(include_url=False), ensure_ascii=False)
            raise CodexResponseValidationError(
                f"Codex 최종 JSON이 분석 스키마와 일치하지 않습니다. {detail[:4000]}"
            ) from exc

        if validated.role != expected_role:
            raise CodexResponseValidationError(
                f"Codex 결과 role이 요청값과 다릅니다. {validated.role!r} != {expected_role!r}"
            )
        if validated.ticker != expected_ticker:
            raise CodexResponseValidationError(
                "Codex 결과 ticker가 요청값과 다릅니다. "
                f"{validated.ticker!r} != {expected_ticker!r}"
            )

        input_strings = self._collect_input_strings((snapshot, context))
        input_urls = self._collect_input_urls(input_strings)
        for evidence in validated.evidence:
            if evidence.source_url is not None:
                self._validate_source_url(evidence.source_url, input_urls)
            if evidence.published_at is not None and evidence.published_at not in input_strings:
                raise CodexResponseValidationError(
                    "evidence.published_at이 입력 데이터에 없는 값을 포함합니다."
                )

        return validated.model_dump(mode="json")

    @staticmethod
    def _collect_input_strings(value: Any) -> set[str]:
        strings: set[str] = set()

        def visit(item: Any) -> None:
            if isinstance(item, str):
                strings.add(item)
            elif isinstance(item, Mapping):
                for key, nested in item.items():
                    if isinstance(key, str):
                        strings.add(key)
                    visit(nested)
            elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
                for nested in item:
                    visit(nested)

        visit(value)
        return strings

    @staticmethod
    def _collect_input_urls(input_strings: set[str]) -> set[str]:
        urls: set[str] = set()
        for value in input_strings:
            if value.startswith(("https://", "http://")):
                urls.add(value)
            for match in re.findall(r"https?://[^\s<>\"']+", value):
                urls.add(match.rstrip(".,);]}>"))
        return urls

    @staticmethod
    def _validate_source_url(source_url: str, input_urls: set[str]) -> None:
        parsed = urlsplit(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise CodexResponseValidationError(
                "evidence.source_url이 유효한 HTTP(S) URL이 아닙니다."
            )
        if source_url not in input_urls:
            raise CodexResponseValidationError(
                "evidence.source_url이 입력 데이터에 없는 출처를 포함합니다."
            )

    async def _emit_status(
        self,
        status: str,
        role: str,
        ticker: str,
        *,
        error: str | None = None,
    ) -> None:
        event: dict[str, Any] = {"status": status, "role": role, "ticker": ticker}
        if error is not None:
            event["error"] = error
        await self._call_callback(self.status_callback, event)

    @staticmethod
    async def _call_callback(callback: EventCallback | None, event: dict[str, Any]) -> None:
        if callback is None:
            return
        callback_result = callback(event)
        if inspect.isawaitable(callback_result):
            await callback_result

    @staticmethod
    async def _stop_process(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        with suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=5)

    @staticmethod
    async def _cancel_tasks(tasks: tuple[asyncio.Task[Any], ...]) -> None:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _decode_detail(output: bytes) -> str:
        text = output.decode("utf-8", errors="replace").strip()
        return text[-4000:]

    @staticmethod
    def _positive_limit(name: str, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise CodexConfigurationError(f"{name}은 0보다 큰 정수여야 합니다.")
        return value

    @staticmethod
    def _resolve_timeout(timeout_seconds: float | None) -> float:
        raw_value: object = (
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("INVESTMENT_OFFICE_CODEX_TIMEOUT_SECONDS", "240")
        )
        try:
            resolved = float(raw_value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise CodexConfigurationError("Codex timeout 값이 숫자가 아닙니다.") from exc
        if resolved <= 0:
            raise CodexConfigurationError("Codex timeout은 0보다 커야 합니다.")
        return resolved
