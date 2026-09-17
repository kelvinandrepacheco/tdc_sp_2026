import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, ToolCallPart
from agent_app import run_turn, Deps, LocalCalendar


class TracingTests(unittest.TestCase):
    def test_agent_children_and_prompt_link(self):
        exporter = InMemorySpanExporter()
        provider = TracerProvider(sampler=ALWAYS_ON)
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={'successes': [], 'errors': []}))
        original_async = httpx.AsyncClient
        def make_async(**kwargs):
            return original_async(**{**kwargs, 'transport': transport})
        with patch('httpx.AsyncClient', side_effect=make_async):
            client = Langfuse(public_key='pk-local-tracing-test', secret_key='sk-local-test',
                tracer_provider=provider, span_exporter=exporter,
                httpx_client=httpx.Client(transport=transport))
        calls = 0
        def model(messages, info):
            nonlocal calls
            calls += 1
            if calls == 1:
                return ModelResponse(parts=[ToolCallPart('search_service_info', {})])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'answer': 'Visita custa R$ 120.'})])
        try:
            with tempfile.TemporaryDirectory() as folder:
                with patch('agent_app.telemetry', return_value=client), patch('agent_app.trace_provider', return_value=provider), patch('agent_app.prompt_for', return_value=(
                    'Teste', {'name': 'climacasa-agent', 'version': 2, 'label': 'candidate'})), patch('agent_app.DATA', Path(folder)):
                    result, _ = run_turn('Preço?', Deps(LocalCalendar(str(Path(folder) / 'db')), 'test'), model=FunctionModel(model))
                client.flush()
                spans = exporter.get_finished_spans()
                self.assertGreaterEqual(len(spans), 4)
                self.assertEqual(len({s.context.trace_id for s in spans}), 1)
                self.assertTrue(any(s.name == 'maintenance-request' for s in spans))
                self.assertTrue(any('search_service_info' in str(dict(s.attributes)) for s in spans))
                self.assertTrue(any(s.attributes.get('langfuse.observation.prompt.name') == 'climacasa-agent' for s in spans))
                self.assertTrue(result['trace_id'])
        finally:
            client.shutdown()
