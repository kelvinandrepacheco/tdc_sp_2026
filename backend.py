"""UI adapter; agent execution and telemetry remain in agent_app.py."""
from __future__ import annotations
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from agent_app import Deps, LocalCalendar, CalCom, DATA, run_turn
from service_area import GoogleServiceArea

logger = logging.getLogger(__name__)


class ChatBackend:
    def __init__(
        self,
        calendar_mode: str | None = None,
        local_scenario: str | None = None,
        maps_enabled: bool | None = None,
        prompt_label: str | None = None,
    ):
        self.session_id = uuid.uuid4().hex
        self.calendar_mode = calendar_mode or os.getenv('CALENDAR_MODE', 'calcom')
        if self.calendar_mode not in ('local', 'calcom'):
            raise ValueError('CALENDAR_MODE must be local or calcom')

        self.local_scenario = local_scenario or os.getenv('LOCAL_SCENARIO', 'normal')
        if maps_enabled is not None:
            self.maps_enabled = bool(maps_enabled)
        else:
            self.maps_enabled = os.getenv('MAPS_ENABLED', 'true').lower() == 'true'

        self.prompt_label = prompt_label or os.getenv('PROMPT_LABEL', 'production')

        if self.calendar_mode == 'calcom':
            calendar = CalCom()
        else:
            calendar = LocalCalendar(
                str(DATA / 'bookings.sqlite3'), self.local_scenario
            )

        self.deps = Deps(calendar, self.session_id)
        self.deps.service_area = GoogleServiceArea() if self.maps_enabled else None
        self.messages: list[Any] = []
        self.conversation: list[dict[str, str]] = []
        self.turn_payloads: list[dict[str, Any]] = []

    def answer_turn(self, text: str, label: str | None = None) -> tuple[str, dict[str, Any]]:
        """Run a single conversational turn and return both the text answer and full telemetry payload."""
        effective_label = label or self.prompt_label
        result, messages = run_turn(
            text,
            self.deps,
            self.messages,
            label=effective_label,
            conversation=self.conversation,
        )
        answer = result['output']['answer']
        self.messages = messages
        self.conversation.extend([
            {'role': 'user', 'content': text},
            {'role': 'assistant', 'content': answer},
        ])
        self.turn_payloads.append(result)
        return answer, result

    def answer(self, text: str) -> str:
        """Backward-compatible text-only answer method."""
        answer, _ = self.answer_turn(text)
        return answer

    def get_turn_payload(self, turn_id: str) -> dict[str, Any] | None:
        """Retrieve latest state of a turn payload, reading from disk if judge updated it."""
        path = DATA / 'runs' / f'{turn_id}.json'
        if path.exists():
            try:
                return json.loads(path.read_text(encoding='utf-8'))
            except Exception as exc:
                logger.warning('Failed reading turn file %s: %s', path, exc)
        for payload in self.turn_payloads:
            if payload.get('turn_id') == turn_id:
                return payload
        return None

    def evaluate_turn_now(self, turn_id: str) -> dict[str, Any] | None:
        """Evaluate a turn on-demand using worker.process (useful for live presentation)."""
        path = DATA / 'runs' / f'{turn_id}.json'
        if not path.exists():
            return None
        try:
            from worker import process
            process(path)
            updated = json.loads(path.read_text(encoding='utf-8'))
            # Update in-memory copy
            for i, p in enumerate(self.turn_payloads):
                if p.get('turn_id') == turn_id:
                    self.turn_payloads[i] = updated
            return updated
        except Exception as exc:
            logger.error('On-demand evaluation failed for %s: %s', turn_id, exc)
            return None
