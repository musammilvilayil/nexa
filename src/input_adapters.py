from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from control_plane import RuntimeControlPlane, kernel_response_payload


@dataclass(frozen=True)
class InputEvent:
    text: str
    source: str
    session_id: str | None = None

    def __post_init__(self) -> None:
        text = self.text.strip()
        source = self.source.strip().lower()
        if not text:
            raise ValueError("input text required")
        if not source or len(source) > 64 or "\x00" in source:
            raise ValueError("input source is invalid")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "source", source)


@dataclass(frozen=True)
class RoutedInputResult:
    source: str
    handled_by_kernel: bool
    payload: dict[str, object] | None = None
    fallback_text: str | None = None


class InputAdapter(Protocol):
    def next_event(self) -> InputEvent | None:
        ...


class OutputAdapter(Protocol):
    def emit(self, result: RoutedInputResult) -> None:
        ...


class TextFallback(Protocol):
    """Text-only response fallback. It receives no direct execution capability."""

    def __call__(self, event: InputEvent) -> str:
        ...


class KernelInputRouter:
    """Single permission-preserving route for typed, voice, or other text input.

    Every input is offered to ``NexaKernel`` first. Only a true ``no_match`` may
    reach an optional text-generation fallback. The fallback receives the input
    event, not the runtime, registry, broker, filesystem, or dispatcher, so it
    cannot bypass deterministic execution permissions.
    """

    def __init__(
        self,
        control: RuntimeControlPlane,
        *,
        fallback: TextFallback | None = None,
    ) -> None:
        self.control = control
        self.fallback = fallback

    def route(self, event: InputEvent) -> RoutedInputResult:
        response = self.control.process(event.text)
        if response.status != "no_match":
            return RoutedInputResult(
                source=event.source,
                handled_by_kernel=True,
                payload=kernel_response_payload(response),
            )
        if self.fallback is None:
            return RoutedInputResult(
                source=event.source,
                handled_by_kernel=False,
                payload=kernel_response_payload(response),
            )
        text = self.fallback(event)
        if not isinstance(text, str):
            text = str(text)
        return RoutedInputResult(
            source=event.source,
            handled_by_kernel=False,
            fallback_text=text,
        )

    def run_once(self, adapter: InputAdapter, output: OutputAdapter) -> bool:
        event = adapter.next_event()
        if event is None:
            return False
        output.emit(self.route(event))
        return True


class VoiceTranscriptAdapter:
    """Provider-neutral boundary for already-transcribed speech.

    Microphone capture and speech-to-text are intentionally outside the kernel.
    A reviewed STT integration supplies transcript strings through ``reader``;
    the resulting text still travels through ``KernelInputRouter`` exactly like
    typed input.
    """

    def __init__(
        self,
        reader: Callable[[], str | None],
        *,
        session_id: str | None = None,
    ) -> None:
        self.reader = reader
        self.session_id = session_id

    def next_event(self) -> InputEvent | None:
        transcript = self.reader()
        if transcript is None:
            return None
        text = str(transcript).strip()
        if not text:
            return None
        return InputEvent(text=text, source="voice", session_id=self.session_id)
