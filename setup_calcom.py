"""Lê sua conta no Cal.com e lista os tipos de eventos disponíveis para configuração."""
import json
import os
from calendar_backend import CalCom, CalendarError

# Tentar carregar .env usando python-dotenv ou parser embutido
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

if __name__ == '__main__':
    token = os.getenv('CALCOM_API_KEY')
    if not token or token.startswith('your_'):
        print('Erro: Configure CALCOM_API_KEY no arquivo .env antes de executar.')
        exit(1)

    print('Consultando tipos de eventos no Cal.com API v2...')
    client = CalCom(token=token, event_type_id='placeholder')
    try:
        event_types = client.get_event_types()
    except CalendarError as exc:
        print(f'Erro ao consultar Cal.com: {exc}')
        exit(1)

    if not event_types:
        print('Nenhum tipo de evento encontrado na sua conta Cal.com.')
        print('Crie um evento no dashboard do Cal.com (ex: Visita Técnica - 30 min) e execute novamente.')
        exit(0)

    print(f'\nEncontrados {len(event_types)} tipos de evento:\n' + '-' * 60)
    for et in event_types:
        info = {
            'id': et.get('id'),
            'title': et.get('title'),
            'slug': et.get('slug'),
            'duration_minutes': et.get('lengthInMinutes') or et.get('length')
        }
        print(json.dumps(info, ensure_ascii=False, indent=2))
        print('-' * 60)

    print('\nCopie o id numérico do evento desejado para CALCOM_EVENT_TYPE_ID no .env.')
