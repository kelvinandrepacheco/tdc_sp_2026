import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from service_area import GoogleServiceArea, MapsError
from agent_app import make_agent, Deps, LocalCalendar
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, ToolCallPart


class CoverageTests(unittest.TestCase):
    def provider(self, seconds='3600s', geo=None, routes=None):
        def transport(req):
            if 'geocode' in req.full_url:
                return geo if geo is not None else {'status': 'OK', 'results': [{
                    'formatted_address': 'Santos, SP, Brasil', 'place_id': 'test',
                    'types': ['locality'], 'address_components': [
                        {'short_name': 'SP', 'types': ['administrative_area_level_1']}]}]}
            body = json.loads(req.data)
            self.assertEqual(body['travelMode'], 'DRIVE')
            self.assertEqual(body['routingPreference'], 'TRAFFIC_AWARE')
            return routes if routes is not None else {'routes': [{'duration': seconds, 'distanceMeters': 50000}]}
        with patch.dict(os.environ, {'GOOGLE_MAPS_API_KEY': 'test', 'COMPANY_ORIGIN_ADDRESS': 'Base teste, SP'}):
            return GoogleServiceArea(transport)

    def test_threshold_unrounded(self):
        for duration, expected in [('3599s', True), ('3600s', True), ('3600.001s', False), ('4200s', False)]:
            value = self.provider(duration).check('Santos')
            self.assertEqual(value['served'], expected)
            self.assertEqual(value['distance_km'], 50)
            self.assertEqual(value['location_precision'], 'approximate')

    def test_unknown_not_rejection(self):
        for kwargs in [{'geo': {'status': 'ZERO_RESULTS', 'results': []}},
                       {'routes': {'routes': []}}, {'seconds': 'bad'},
                       {'routes': {'fallbackInfo': {'routingMode': 'FALLBACK_TRAFFIC_UNAWARE'}, 'routes': []}}]:
            result = self.provider(**kwargs).check('Santos')
            self.assertIsNone(result['served'])
            self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(self.provider().check('Santos', 'RJ')['served'])
        self.assertIsNone(self.provider().check('')['served'])

    def test_api_failure(self):
        provider = self.provider()
        provider.transport = lambda req: (_ for _ in ()).throw(MapsError('Timeout'))
        self.assertIsNone(provider.check('Santos')['served'])

    def test_booking_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            calendar = LocalCalendar(str(Path(folder) / 'db'))
            deps = Deps(calendar, 'guard', service_area=self.provider('4200s'))
            slot = calendar.candidates()[0]
            count = 0
            def model(messages, info):
                nonlocal count
                count += 1
                if count == 1:
                    return ModelResponse(parts=[ToolCallPart('book_visit', {'start_time': slot, 'destination': 'Santos'})])
                return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'answer': 'Fora da área.'})])
            make_agent('Teste', FunctionModel(model)).run_sync('Agende em Santos', deps=deps)
            self.assertEqual(deps.evidence[-1]['result']['status'], 'coverage_not_approved')
            self.assertIsNone(calendar.state('guard'))
