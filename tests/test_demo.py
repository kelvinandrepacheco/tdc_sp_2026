import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from calendar_backend import LocalCalendar, CalCom, CalendarError, window, iso, parse_time
from evaluators import checks
from agent_app import make_agent, Deps, Reply, run_turn
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, ToolCallPart
from worker import process


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local = LocalCalendar(str(Path(self.tmp.name) / 'test.db'))

    def tearDown(self):
        self.tmp.cleanup()

    def test_local_idempotency_and_collision(self):
        slot = self.local.candidates()[0]
        first = self.local.book('a', slot)
        self.assertEqual(first['booking_id'], self.local.book('a', slot)['booking_id'])
        self.assertEqual(self.local.book('b', slot)['status'], 'conflict')
        self.assertEqual(self.local.state('a')['booking_id'], first['booking_id'])

    def test_injected_conflict_has_no_booking(self):
        self.local.scenario = 'conflict'
        self.assertEqual(self.local.book('a', self.local.candidates()[0])['status'], 'conflict')
        self.assertIsNone(self.local.state('a'))

    def test_timezone_and_window(self):
        self.assertEqual(iso(parse_time('2030-01-01T14:00:00-03:00')), '2030-01-01T17:00:00Z')
        with self.assertRaises(ValueError):
            parse_time('2030-01-01T14:00:00')
        now = datetime.now(timezone.utc)
        with self.assertRaises(ValueError):
            window(iso(now), iso(now + timedelta(days=9)))

    def test_confirmation_check(self):
        self.assertEqual(checks({'booking_claim': 'confirmed', 'booking_id': 'fake'}, None, [])['structured_confirmation_supported'], 0)
        self.assertEqual(checks({'booking_claim': 'pending'}, None, [])['structured_confirmation_supported'], 1)

    def test_calcom_confirmation_check(self):
        client = CalCom('token', '123', transport=lambda req: {'status': 'success', 'data': {'uid': 'real_booking_123'}})
        res = client.book_direct('2030-05-10T14:00:00-03:00', name='Test', email='test@test.com', session='sess_calcom')
        state = client.state('sess_calcom')
        self.assertEqual(state['booking_id'], 'real_booking_123')
        # Check passes when claimed booking matches real CalCom state
        self.assertEqual(checks({'booking_claim': 'confirmed', 'booking_id': 'real_booking_123'}, state, [])['structured_confirmation_supported'], 1)
        # Check fails when claimed booking doesn't match CalCom state
        self.assertEqual(checks({'booking_claim': 'confirmed', 'booking_id': 'different_id'}, state, [])['structured_confirmation_supported'], 0)

    def test_agent_tools_and_history(self):
        slot = self.local.candidates()[0]
        calls = []
        def respond(messages, info):
            calls.append(messages)
            if len(calls) == 1:
                return ModelResponse(parts=[ToolCallPart('get_availability', {
                    'start_time': iso(datetime.now(timezone.utc) + timedelta(minutes=1)),
                    'end_time': iso(datetime.now(timezone.utc) + timedelta(days=3))})])
            if len(calls) == 2:
                return ModelResponse(parts=[ToolCallPart('book_visit', {'start_time': slot})])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
                {'answer': 'Reserva local criada.', 'booking_claim': 'confirmed',
                 'booking_id': self.local.state('a')['booking_id']})])
        deps = Deps(self.local, 'a')
        agent = make_agent('Teste de orquestração, sem modelo remoto.', FunctionModel(respond))
        result = agent.run_sync('Reserve o horário escolhido.', deps=deps)
        self.assertEqual(len(deps.evidence), 2)
        self.assertGreater(len(result.all_messages()), 2)
        self.assertEqual(result.output.booking_id, self.local.state('a')['booking_id'])

    def test_no_unqueried_booking(self):
        count = 0
        def respond(messages, info):
            nonlocal count
            count += 1
            if count == 1:
                return ModelResponse(parts=[ToolCallPart('book_visit', {'start_time': self.local.candidates()[0]})])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'answer': 'Vou consultar.'})])
        deps = Deps(self.local, 'a')
        make_agent('Teste', FunctionModel(respond)).run_sync('Reserve', deps=deps)
        self.assertEqual(deps.evidence[0]['result']['status'], 'not_offered')
        self.assertIsNone(self.local.state('a'))

    def test_turn_queue_and_judge(self):
        def respond(messages, info):
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'answer': 'Como posso ajudar?'})])
        with patch('agent_app.DATA', Path(self.tmp.name)), patch('agent_app.telemetry', return_value=None):
            payload, messages = run_turn('Olá', Deps(self.local, 'a'), model=FunctionModel(respond))
        path = Path(self.tmp.name) / 'runs' / (payload['turn_id'] + '.json')
        self.assertTrue(path.exists())
        def judge(messages, info):
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
                'confirmation_supported': True, 'price_accurate': True,
                'constraints_respected': True, 'coverage_accurate': True, 'reason': 'Nenhuma afirmação indevida.'})])
        with patch('worker.telemetry', return_value=None):
            process(path, FunctionModel(judge))
        self.assertEqual(json.loads(path.read_text())['judge_status'], 'completed')

    def test_reasoning_extraction(self):
        from agent_app import extract_reasoning
        from dataclasses import dataclass

        @dataclass
        class MockThinkingPart:
            content: str
            part_kind: str = 'thinking'

        @dataclass
        class MockTextPart:
            content: str
            part_kind: str = 'text'

        @dataclass
        class MockMessage:
            parts: list

        msg1 = MockMessage(parts=[MockThinkingPart(content='Analisando preço da visita de R$120...')])
        msg2 = MockMessage(parts=[MockTextPart(content='<think>Verificando disponibilidade de horários...</think>Resposta final.')])
        
        extracted = extract_reasoning([msg1, msg2])
        self.assertEqual(len(extracted), 2)
        self.assertIn('Analisando preço', extracted[0])
        self.assertIn('Verificando disponibilidade', extracted[1])


if __name__ == '__main__':
    unittest.main()
