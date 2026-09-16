from __future__ import annotations
from contextlib import nullcontext
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import datetime
from pathlib import Path
from typing import Literal, Any
import json
import os
import random
import uuid

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Instrumentation
from pydantic_ai.models.instrumented import InstrumentationSettings
from opentelemetry.sdk.trace import TracerProvider
from pydantic_ai.usage import UsageLimits
from langfuse import Langfuse, propagate_attributes

from calendar_backend import LocalCalendar, CalCom, CalendarError, TZ, parse_time
from evaluators import checks
from service_area import GoogleServiceArea

try:
    from pydantic_ai.capabilities import Thinking
except ImportError:
    Thinking = None

try:
    from pydantic_ai.messages import ThinkingPart
except ImportError:
    ThinkingPart = None


def extract_reasoning(messages: list[Any]) -> list[str]:
    """Extract model thinking/reasoning blocks from Pydantic AI message history."""
    thoughts = []
    for msg in messages:
        parts = getattr(msg, 'parts', [])
        for part in parts:
            part_kind = getattr(part, 'part_kind', None)
            if part_kind == 'thinking' or type(part).__name__ == 'ThinkingPart':
                content = getattr(part, 'content', '')
                if content:
                    thoughts.append(content)
            elif hasattr(part, 'reasoning') and part.reasoning:
                thoughts.append(str(part.reasoning))
            elif part_kind == 'text' or type(part).__name__ == 'TextPart':
                content = getattr(part, 'content', '')
                if '<think>' in content and '</think>' in content:
                    extracted = content.split('<think>')[1].split('</think>')[0].strip()
                    if extracted:
                        thoughts.append(extracted)
    return thoughts

load_dotenv()
BASE = Path(__file__).parent
DATA = BASE / 'data'
DATA.mkdir(exist_ok=True)

# Configuração do modelo: respeita a variável de ambiente MODEL do .env
DEFAULT_MODEL = os.getenv('MODEL', 'openrouter:openai/gpt-5.4-mini')
FACTS = {'company': 'ClimaCasa (fictícia)', 'visit_price_brl': 120,
         'includes': 'Visita diagnóstica de ar-condicionado',
         'excludes': 'Reparo e peças: orçamento após diagnóstico',
         'emergency_service': False, 'source': 'catalogo-demo-v1'}


class Reply(BaseModel):
    answer: str
    booking_claim: Literal['none', 'pending', 'confirmed'] = 'none'
    booking_id: str | None = None


@dataclass
class Deps:
    calendar: Any
    session: str
    offered: set[str] = field(default_factory=set)
    evidence: list[dict] = field(default_factory=list)
    history_evidence: list[dict] = field(default_factory=list)
    service_area: Any = None


@lru_cache(maxsize=1)
def trace_provider():
    return TracerProvider()


@lru_cache(maxsize=1)
def telemetry():
    if os.getenv('LANGFUSE_PUBLIC_KEY') and os.getenv('LANGFUSE_SECRET_KEY'):
        return Langfuse(tracer_provider=trace_provider())
    return None


def record(deps, name, arguments, fn):
    try:
        value = fn()
    except (CalendarError, ValueError) as exc:
        value = {'status': 'error', 'message': str(exc), 'reservation_created': False}
    deps.evidence.append({'tool': name, 'arguments': arguments, 'result': value})
    return value


def make_agent(instructions, model=None, instrument=False):
    model_to_use = model or DEFAULT_MODEL
    capabilities = []
    if instrument:
        capabilities.append(Instrumentation(settings=InstrumentationSettings(
            tracer_provider=trace_provider())))

    # Only enable Thinking capability if explicitly configured in .env (for models that support it)
    thinking_enabled = os.getenv('THINKING_ENABLED', 'false').lower() in ('true', '1')
    thinking_effort = os.getenv('THINKING_EFFORT', 'medium').lower()
    if (thinking_enabled and 
        Thinking is not None and 
        thinking_effort not in ('false', 'none', 'off', '0') and 
        not (hasattr(model_to_use, '__class__') and 'FunctionModel' in model_to_use.__class__.__name__)):
        effort = thinking_effort if thinking_effort in ('minimal', 'low', 'medium', 'high', 'xhigh') else True
        capabilities.append(Thinking(effort=effort))

    agent = Agent(model_to_use,
                  instructions=instructions, deps_type=Deps, output_type=Reply,
                  name='climacasa-agent', capabilities=capabilities, retries=1)

    @agent.tool
    def search_service_info(ctx: RunContext[Deps]) -> dict:
        """Consultar serviços e condições comerciais, incluindo preço da visita."""
        return record(ctx.deps, 'search_service_info', {}, lambda: FACTS.copy())

    @agent.tool
    def check_service_area(ctx: RunContext[Deps], destination: str, state: str = '') -> dict:
        """Verificar cobertura por Google Maps, até 60 minutos de carro da base.
        destination deve ser a cidade/CEP/endereço informado para o serviço. state é UF.
        Retorna distância, duração e served (true/false/null). Null não significa fora da área.
        """
        provider = ctx.deps.service_area or GoogleServiceArea()
        return record(ctx.deps, 'check_service_area', {'destination': destination, 'state': state},
                      lambda: provider.check(destination, state))

    @agent.tool
    def get_availability(ctx: RunContext[Deps], start_time: str, end_time: str) -> dict:
        """Buscar horários em intervalo de até 7 dias. ISO 8601 com fuso obrigatório."""
        result = record(ctx.deps, 'get_availability', locals_args(start_time, end_time),
                        lambda: ctx.deps.calendar.availability(start_time, end_time))
        for slot in result.get('slots', []):
            ctx.deps.offered.add(parse_time(slot['start_time']).isoformat())
        return result

    @agent.tool
    def book_visit(ctx: RunContext[Deps], start_time: str, name: str = '', email: str = '', destination: str = '', state: str = '') -> dict:
        """Após escolha do horário, solicitar NOME e EMAIL do cliente para criar a reserva."""
        def execute():
            if ctx.deps.service_area is not None:
                coverage = record(ctx.deps, 'check_service_area', {'destination': destination, 'state': state},
                                  lambda: ctx.deps.service_area.check(destination, state))
                if coverage.get('served') is not True:
                    return {'status': 'coverage_not_approved', 'reservation_created': False, 'coverage': coverage}
                if coverage.get('location_precision') != 'address':
                    return {'status': 'address_required', 'reservation_created': False,
                            'message': 'Confirme endereço completo para verificar cobertura exata antes de agendar.'}
            
            if parse_time(start_time).isoformat() not in ctx.deps.offered:
                return {'status': 'not_offered', 'reservation_created': False,
                        'message': 'Consulte este horário antes de encaminhar.'}
            
            if ctx.deps.calendar.mode == 'calcom':
                return ctx.deps.calendar.book_direct(start_time, name, email, session=ctx.deps.session)
                
            return ctx.deps.calendar.book(ctx.deps.session, start_time)
            
        return record(ctx.deps, 'book_visit', 
                     {'start_time': start_time, 'name': name, 'email': email, 'destination': destination, 'state': state}, 
                     execute)

    return agent


def locals_args(start_time, end_time):
    return {'start_time': start_time, 'end_time': end_time}


def prompt_for(label, lf):
    fallback = (BASE / 'prompts' / 'improved.txt').read_text()
    if lf:
        prompt = lf.get_prompt('climacasa-agent', label=label, fallback=fallback, cache_ttl_seconds=0)
        prompt_id = getattr(prompt, 'id', None) or getattr(prompt, 'prompt_id', None)
        return prompt.compile(), {
            'name': prompt.name,
            'version': prompt.version,
            'label': label,
            'id': str(prompt_id) if prompt_id else None,
            'fallback': prompt.is_fallback,
            'prompt_obj': prompt if not prompt.is_fallback else None,
        }
    # Explicit local variants are useful when no Langfuse credentials are configured.
    variant = 'baseline' if label == 'baseline' else 'improved'
    return (BASE / 'prompts' / f'{variant}.txt').read_text(), {
        'name': 'climacasa-agent',
        'version': 'local-' + variant,
        'label': label,
        'id': f'local-{variant}',
        'fallback': True,
        'prompt_obj': None,
    }


def run_turn(question, deps, messages=None, label='production', conversation=None, model=None):
    lf = telemetry()
    prompt, provenance = prompt_for(label, lf)
    current = datetime.now(TZ).isoformat()
    instructions = prompt + '\nPara cobertura use check_service_area; nunca invente duração/distância. Até 3600 segundos atende; acima não. Unknown exige esclarecer ou tentar depois. Cidade dá estimativa, endereço exato é necessário para agendar. Use localização do pedido atual e explicite a UF resolvida. book_visit recebe destination e state do endereço escolhido.\n' + f'\nAgora: {current}. Fuso: {TZ}. Modo da agenda: {deps.calendar.mode}.'
    deps.evidence = []
    turn_id = uuid.uuid4().hex

    # Determine prompt linking for Langfuse
    prompt_to_link = provenance.get('prompt_obj')
    if prompt_to_link is None and not provenance.get('fallback') and isinstance(provenance.get('version'), int):
        prompt_to_link = {'name': provenance['name'], 'version': provenance['version']}

    trace_version = str(provenance['version']) if not provenance.get('fallback') else None
    trace_tags = ['tdc-2026', deps.calendar.mode]
    if not provenance.get('fallback') and provenance.get('version') is not None:
        trace_tags.append(f"prompt:v{provenance['version']}")
        trace_tags.append(f"prompt-label:{label}")
        if provenance.get('id'):
            trace_tags.append(f"prompt-id:{provenance['id']}")

    metadata = {
        'prompt_label': label,
        'prompt_version': str(provenance['version']),
        'prompt_name': provenance['name'],
        'prompt_fallback': str(provenance.get('fallback', False)),
        'session_id': deps.session,
    }
    if provenance.get('id'):
        metadata['prompt_id'] = str(provenance['id'])

    clean_provenance = {k: v for k, v in provenance.items() if k != 'prompt_obj'}

    context = propagate_attributes(
        session_id=deps.session,
        tags=trace_tags,
        version=trace_version,
        prompt=prompt_to_link,
        metadata=metadata,
    ) if lf else nullcontext()

    with context:
        obs = lf.start_as_current_observation(
            name='maintenance-request',
            as_type='agent',
            input={'question': question, 'conversation': conversation or []},
            metadata={'prompt': clean_provenance, 'calendar_mode': deps.calendar.mode}
        ) if lf else nullcontext()
        with obs as root:
            agent = make_agent(instructions, model, bool(lf))
            result = agent.run_sync(question, deps=deps, message_history=messages or [],
                                    usage_limits=UsageLimits(request_limit=8, total_tokens_limit=16000))
            output = result.output.model_dump()
            state = deps.calendar.state(deps.session) if hasattr(deps.calendar, 'state') else None
            evidence = deps.history_evidence + deps.evidence
            scores = checks(output, state, deps.evidence)
            trace_id = lf.get_current_trace_id() if lf else None
            observation_id = lf.get_current_observation_id() if lf else None
            usage = result.usage

            # Extract reasoning/thinking from Pydantic AI message history
            thoughts = extract_reasoning(result.all_messages())
            reasoning = "\n\n---\n\n".join(thoughts) if thoughts else None

            payload = {
                'turn_id': turn_id,
                'session_id': deps.session,
                'input': question,
                'conversation': conversation or [],
                'output': output,
                'answer': output.get('answer'),
                'booking_claim': output.get('booking_claim'),
                'booking_id': output.get('booking_id'),
                'reasoning': reasoning,
                'evidence': evidence,
                'state': state,
                'facts': FACTS,
                'prompt': clean_provenance,
                'calendar_mode': deps.calendar.mode,
                'trace_id': trace_id,
                'observation_id': observation_id,
                'usage': {'input_tokens': usage.input_tokens, 'output_tokens': usage.output_tokens,
                          'requests': usage.requests},
                'scores': scores,
            }
            if root:
                root.update(output=payload)
                if reasoning:
                    root.update(metadata={'has_reasoning': True, 'reasoning_preview': reasoning[:500]})
                for key, value in scores.items():
                    root.score(name=key, value=value, data_type='BOOLEAN' if key.endswith('supported') else 'NUMERIC')
    # Preserve tool call/return history in memory, not only user-visible messages.
    deps.history_evidence = evidence
    if lf:
        lf.flush()
        try:
            trace_provider().force_flush()
        except Exception:
            pass
        try:
            payload['trace_url'] = lf.get_trace_url(trace_id=trace_id)
        except Exception:
            # A project lookup failure must not discard a completed response/booking.
            payload['trace_url'] = None
            payload['telemetry_notice'] = 'Link indisponível; procure o trace_id no projeto Langfuse.'
    rate = min(1., max(0., float(os.getenv('JUDGE_SAMPLE_RATE', '1'))))
    payload['judge_status'] = 'pending' if random.random() < rate else 'not_sampled'
    path = DATA / 'runs' / f'{turn_id}.json'
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    temporary.replace(path)
    return payload, result.all_messages()
