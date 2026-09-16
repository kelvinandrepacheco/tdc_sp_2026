"""Creates both labels for testing. Does not promote production implicitly."""
import argparse
from agent_app import BASE, telemetry

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--initialize-production', action='store_true', help='Atribui production à versão melhorada criada nesta execução.')
    args = parser.parse_args()
    lf = telemetry()
    if not lf:
        raise SystemExit('Configure as chaves Langfuse no .env.')
    for filename, label in [('baseline', 'baseline'), ('improved', 'candidate')]:
        labels = [label]
        if filename == 'improved' and args.initialize_production:
            labels.append('production')
        p = lf.create_prompt(name='climacasa-agent', type='text',
                             prompt=(BASE / 'prompts' / f'{filename}.txt').read_text(), labels=labels)
        print(f'{label}: versão {p.version}; labels {labels}')
    lf.flush()
