"""Evaluate after response. Run once, or --watch for continuous local traffic."""
import argparse
import json
import os
import time
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.capabilities import Instrumentation
from pydantic_ai.models.instrumented import InstrumentationSettings
from pydantic_ai.usage import UsageLimits
from agent_app import DATA, telemetry, trace_provider
from evaluators import JUDGE_INSTRUCTIONS


class Verdict(BaseModel):
    confirmation_supported: bool
    price_accurate: bool
    constraints_respected: bool
    coverage_accurate: bool
    reason: str


DEFAULT_JUDGE_MODEL = os.getenv('JUDGE_MODEL', 'openrouter:anthropic/claude-3.5-sonnet')


def process(path, model=None):
    payload = json.loads(path.read_text())
    lf = telemetry()
    judge_model_to_use = model or DEFAULT_JUDGE_MODEL
    judge = Agent(judge_model_to_use,
                  instructions=JUDGE_INSTRUCTIONS, output_type=Verdict,
                  name='maintenance-judge', capabilities=[Instrumentation(settings=InstrumentationSettings(
                      tracer_provider=trace_provider()))] if lf else [], retries=1)
    evidence = {k: payload[k] for k in ['input', 'conversation', 'output', 'evidence', 'state', 'facts', 'calendar_mode']}
    verdict = judge.run_sync(json.dumps(evidence, ensure_ascii=False),
                            usage_limits=UsageLimits(request_limit=3)).output.model_dump()
    if lf and payload.get('trace_id'):
        for name in ['confirmation_supported', 'price_accurate', 'constraints_respected', 'coverage_accurate']:
            lf.create_score(score_id=payload['turn_id'] + '-' + name, trace_id=payload['trace_id'],
                            observation_id=payload['observation_id'], name=name,
                            value=int(verdict[name]), data_type='BOOLEAN', comment=verdict['reason'])
        lf.flush()
    payload.update(judge=verdict, judge_status='completed')
    payload.pop('judge_error', None)
    temp = path.with_suffix('.judge-tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--retry-errors', action='store_true')
    args = parser.parse_args()
    while True:
        for path in sorted((DATA / 'runs').glob('*.json')):
            payload = json.loads(path.read_text())
            allowed = ['pending', 'error'] if args.retry_errors else ['pending']
            if payload.get('judge_status') not in allowed:
                continue
            try:
                process(path)
                print('Avaliado:', path.stem, flush=True)
            except Exception as exc:
                payload.update(judge_status='error', judge_error=type(exc).__name__)
                temp = path.with_suffix('.error-tmp')
                temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
                temp.replace(path)
                print('Falha no judge:', path.stem, type(exc).__name__, flush=True)
        if not args.watch:
            break
        time.sleep(3)


if __name__ == '__main__':
    main()
