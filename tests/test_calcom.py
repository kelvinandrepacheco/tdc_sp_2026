import json
import unittest
from datetime import datetime, timedelta, timezone
from urllib.request import Request

from calendar_backend import CalCom, CalendarError, iso, parse_time, TZ


class CalComTests(unittest.TestCase):
    def setUp(self):
        self.token = 'test_token_123'
        self.event_type_id = '7085484'

    def test_missing_credentials_raises_calendar_error(self):
        client = CalCom(token='', event_type_id='')
        now = datetime.now(timezone.utc) + timedelta(days=1)
        with self.assertRaises(CalendarError):
            client.availability(iso(now), iso(now + timedelta(days=2)))

    def test_request_sets_headers(self):
        captured_req = []

        def transport(req):
            captured_req.append(req)
            return {'status': 'success', 'data': []}

        client = CalCom(token=self.token, event_type_id=self.event_type_id, transport=transport)
        client.get_event_types()

        self.assertEqual(len(captured_req), 1)
        req = captured_req[0]
        self.assertIsInstance(req, Request)
        self.assertEqual(req.headers.get('Authorization'), f'Bearer {self.token}')
        self.assertEqual(req.headers.get('Cal-api-version'), '2024-06-11')
        self.assertIn('User-agent', req.headers)

    def test_availability_parsing_dict_format(self):
        slot_1 = '2030-05-10T14:00:00.000Z'
        slot_2 = '2030-05-10T16:00:00.000Z'
        mock_response = {
            'status': 'success',
            'data': {
                '2030-05-10': [
                    {'start': slot_1},
                    {'start': slot_2}
                ]
            }
        }

        client = CalCom(token=self.token, event_type_id=self.event_type_id, transport=lambda req: mock_response)
        res = client.availability('2030-05-10T00:00:00Z', '2030-05-11T00:00:00Z')

        self.assertEqual(res['status'], 'ok')
        self.assertEqual(res['source'], 'calcom')
        self.assertEqual(len(res['slots']), 2)
        self.assertEqual(res['slots'][0]['start_time'], slot_1)
        self.assertEqual(res['slots'][1]['start_time'], slot_2)
        self.assertEqual(res['slots'][0]['local_time'], parse_time(slot_1).astimezone(TZ).isoformat())

    def test_availability_parsing_time_key_and_list_format(self):
        slot_1 = '2030-05-10T14:00:00.000Z'
        mock_response = {
            'status': 'success',
            'data': [
                {'time': slot_1}
            ]
        }

        client = CalCom(token=self.token, event_type_id=self.event_type_id, transport=lambda req: mock_response)
        res = client.availability('2030-05-10T00:00:00Z', '2030-05-11T00:00:00Z')

        self.assertEqual(len(res['slots']), 1)
        self.assertEqual(res['slots'][0]['start_time'], slot_1)

    def test_availability_filters_outside_window(self):
        in_window = '2030-05-10T14:00:00.000Z'
        out_window = '2030-05-12T14:00:00.000Z'
        mock_response = {
            'data': {
                '2030-05-10': [{'start': in_window}],
                '2030-05-12': [{'start': out_window}]
            }
        }

        client = CalCom(token=self.token, event_type_id=self.event_type_id, transport=lambda req: mock_response)
        res = client.availability('2030-05-10T00:00:00Z', '2030-05-11T00:00:00Z')

        self.assertEqual(len(res['slots']), 1)
        self.assertEqual(res['slots'][0]['start_time'], in_window)

    def test_book_direct_success_and_state(self):
        slot = '2030-05-10T14:00:00-03:00'
        captured = []

        def transport(req):
            captured.append(req)
            return {
                'status': 'success',
                'data': {
                    'id': 12345,
                    'uid': 'b_uid_abc123'
                }
            }

        client = CalCom(token=self.token, event_type_id=self.event_type_id, transport=transport)
        res = client.book_direct(slot, name='Ana Silva', email='ana@exemplo.com', session='sess-1')

        self.assertEqual(res['status'], 'confirmed')
        self.assertTrue(res['reservation_created'])
        self.assertEqual(res['booking_id'], 'b_uid_abc123')
        self.assertEqual(res['source'], 'calcom')

        # Check payload
        payload = json.loads(captured[0].data.decode('utf-8'))
        self.assertEqual(payload['eventTypeId'], int(self.event_type_id))
        self.assertEqual(payload['attendee']['name'], 'Ana Silva')
        self.assertEqual(payload['attendee']['email'], 'ana@exemplo.com')
        self.assertEqual(payload['attendee']['timeZone'], 'America/Sao_Paulo')

        # Check state lookup
        state = client.state('sess-1')
        self.assertIsNotNone(state)
        self.assertEqual(state['booking_id'], 'b_uid_abc123')

    def test_book_direct_idempotent_replay(self):
        slot = '2030-05-10T14:00:00-03:00'
        call_count = 0

        def transport(req):
            nonlocal call_count
            call_count += 1
            return {'status': 'success', 'data': {'uid': 'b_fixed'}}

        client = CalCom(token=self.token, event_type_id=self.event_type_id, transport=transport)
        first = client.book_direct(slot, name='Ana', email='ana@exemplo.com', session='sess-idem')
        second = client.book_direct(slot, name='Ana', email='ana@exemplo.com', session='sess-idem')

        self.assertEqual(call_count, 1)
        self.assertEqual(second['booking_id'], first['booking_id'])
        self.assertTrue(second.get('idempotent_replay'))

    def test_book_direct_conflict(self):
        slot = '2030-05-10T14:00:00-03:00'

        def transport(req):
            raise CalendarError('Horário já reservado ou em conflito no Cal.com.')

        client = CalCom(token=self.token, event_type_id=self.event_type_id, transport=transport)
        res = client.book_direct(slot, name='Ana', email='ana@exemplo.com', session='sess-conflict')

        self.assertEqual(res['status'], 'conflict')
        self.assertFalse(res['reservation_created'])
        self.assertIsNone(client.state('sess-conflict'))

    def test_book_direct_past_time_rejected(self):
        past_slot = '2020-01-01T10:00:00-03:00'
        client = CalCom(token=self.token, event_type_id=self.event_type_id)
        res = client.book_direct(past_slot, name='Ana', email='ana@exemplo.com')
        self.assertEqual(res['status'], 'conflict')
        self.assertFalse(res['reservation_created'])

    def test_get_event_types_grouped(self):
        mock_response = {
            'status': 'success',
            'data': {
                'eventTypeGroups': [
                    {
                        'eventTypes': [
                            {'id': 1, 'title': 'Visita 30min', 'slug': 'visita-30'},
                            {'id': 2, 'title': 'Visita 60min', 'slug': 'visita-60'}
                        ]
                    }
                ]
            }
        }
        client = CalCom(token=self.token, event_type_id=self.event_type_id, transport=lambda req: mock_response)
        ets = client.get_event_types()
        self.assertEqual(len(ets), 2)
        self.assertEqual(ets[0]['id'], 1)
        self.assertEqual(ets[1]['slug'], 'visita-60')


if __name__ == '__main__':
    unittest.main()
