"""UI adapter; agent execution and telemetry remain in agent_app.py."""
import os
import uuid
from agent_app import Deps, LocalCalendar, CalCom, DATA, run_turn
from service_area import GoogleServiceArea


class ChatBackend:
    def __init__(self):
        self.session_id = uuid.uuid4().hex
        mode = os.getenv('CALENDAR_MODE', 'calcom')
        if mode not in ('local', 'calcom'):
            raise ValueError('CALENDAR_MODE must be local or calcom')
        if mode == 'calcom':
            calendar = CalCom()
        else:
            calendar = LocalCalendar(
                str(DATA / 'bookings.sqlite3'), os.getenv('LOCAL_SCENARIO', 'normal'))
        self.deps = Deps(calendar, self.session_id)
        self.deps.service_area = GoogleServiceArea() if os.getenv('MAPS_ENABLED', 'true').lower() == 'true' else None
        self.messages = []
        self.conversation = []

    def answer(self, text: str) -> str:
        result, messages = run_turn(
            text, self.deps, self.messages,
            label=os.getenv('PROMPT_LABEL', 'production'),
            conversation=self.conversation,
        )
        answer = result['output']['answer']
        self.messages = messages
        self.conversation.extend([{'role': 'user', 'content': text},
                                  {'role': 'assistant', 'content': answer}])
        return answer
