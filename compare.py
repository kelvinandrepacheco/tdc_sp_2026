"""Paired live model test: same scenario, independent sessions, labels baseline/candidate."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import tempfile
import uuid
from pathlib import Path
from agent_app import Deps, LocalCalendar, run_turn
from calendar_backend import iso


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', choices=['normal', 'conflict', 'timeout'], default='conflict')
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory() as folder:
        for label in ['baseline', 'candidate']:
            backend = LocalCalendar(str(Path(folder) / f'{label}.db'), args.scenario)
            deps = Deps(backend, 'compare-' + uuid.uuid4().hex)
            slot = backend.candidates()[0]
            questions = [
                'Quanto custa a visita? O reparo e as peças estão incluídos? Consulte horários amanhã à tarde.',
                f'Escolho {slot}. Pode confirmar a visita nesse horário?']
            history, chat = [], []
            for question in questions:
                run, history = run_turn(question, deps, history, label, chat)
                chat.extend([{'role': 'user', 'content': question},
                             {'role': 'assistant', 'content': run['output']['answer']}])
                results.append({'label': label, 'scenario': args.scenario, 'turn_id': run['turn_id'],
                                'answer': run['output']['answer'], 'scores': run['scores'],
                                'trace_url': run.get('trace_url')})
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print('Execute python worker.py para avaliar estes turnos. Resultados não são pré-fixados.')


if __name__ == '__main__':
    main()
