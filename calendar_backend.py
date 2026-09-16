"""Calendar integrations: Local simulation and Cal.com API v2."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
import json
import os
import sqlite3
import uuid

TZ = ZoneInfo('America/Sao_Paulo')


def parse_time(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Informe data ISO com fuso, por exemplo 2026-09-24T14:00:00-03:00.')
    return dt.astimezone(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def window(start, end):
    start, end = parse_time(start), parse_time(end)
    now = datetime.now(timezone.utc) + timedelta(seconds=5)
    start = max(start, now)
    if end <= start or end - start > timedelta(days=7):
        raise ValueError('Intervalo deve terminar no futuro e ter no máximo 7 dias.')
    return start, end


class CalendarError(Exception):
    pass


class LocalCalendar:
    mode = 'local'

    def __init__(self, db='data/bookings.sqlite3', scenario='normal'):
        self.db = db
        self.scenario = scenario
        os.makedirs(os.path.dirname(os.path.abspath(db)), exist_ok=True)
        with sqlite3.connect(db) as con:
            con.execute('CREATE TABLE IF NOT EXISTS bookings (id TEXT PRIMARY KEY, session TEXT UNIQUE, start TEXT UNIQUE)')

    def candidates(self):
        tomorrow = datetime.now(TZ).date() + timedelta(days=1)
        return [iso(datetime.combine(tomorrow + timedelta(days=d), datetime.min.time(), TZ).replace(hour=h))
                for d in range(6) for h in (14, 16)]

    def availability(self, start, end):
        start, end = window(start, end)
        if self.scenario == 'timeout':
            raise CalendarError('Timeout simulado na consulta de horários.')
        with sqlite3.connect(self.db) as con:
            taken = {r[0] for r in con.execute('SELECT start FROM bookings')}
        slots = [{'start_time': s, 'local_time': parse_time(s).astimezone(TZ).isoformat()}
                 for s in self.candidates() if start <= parse_time(s) < end and s not in taken]
        return {'status': 'ok', 'source': 'local_simulation', 'slots': slots, 'timezone': str(TZ),
                'reservation_created': False}

    def book(self, session, start_time):
        value = iso(parse_time(start_time))
        with sqlite3.connect(self.db) as con:
            con.execute('BEGIN IMMEDIATE')
            existing = con.execute('SELECT id,start FROM bookings WHERE session=?', (session,)).fetchone()
            if existing:
                return {'status': 'confirmed', 'reservation_created': True,
                        'booking_id': existing[0], 'start_time': existing[1], 'idempotent_replay': True}
            if self.scenario == 'conflict' or value not in self.candidates():
                return {'status': 'conflict', 'reservation_created': False, 'message': 'Horário indisponível.'}
            booking_id = 'demo-' + uuid.uuid4().hex[:12]
            try:
                con.execute('INSERT INTO bookings VALUES (?,?,?)', (booking_id, session, value))
            except sqlite3.IntegrityError:
                return {'status': 'conflict', 'reservation_created': False}
        return {'status': 'confirmed', 'reservation_created': True, 'booking_id': booking_id,
                'start_time': value, 'source': 'local_simulation'}

    def state(self, session):
        with sqlite3.connect(self.db) as con:
            row = con.execute('SELECT id,start FROM bookings WHERE session=?', (session,)).fetchone()
        return {'booking_id': row[0], 'start_time': row[1]} if row else None


class CalCom:
    mode = 'calcom'

    def __init__(self, token=None, event_type_id=None, transport=None):
        self.token = os.getenv('CALCOM_API_KEY', '') if token is None else token
        self.event_type_id = os.getenv('CALCOM_EVENT_TYPE_ID', '') if event_type_id is None else event_type_id
        self.transport = transport
        self._bookings = {}

    def request(self, method, path, params=None, payload=None, version='2024-08-13'):
        if not self.token:
            raise CalendarError('Configure CALCOM_API_KEY no .env.')
        if not path.startswith('/event-types') and not self.event_type_id:
            raise CalendarError('Configure CALCOM_EVENT_TYPE_ID no .env.')

        url = 'https://api.cal.com/v2' + path
        if params:
            url += '?' + urlencode(params)

        headers = {
            'Authorization': f'Bearer {self.token}',
            'cal-api-version': version,
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
        }

        data = None
        if payload:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(payload).encode('utf-8')

        req = Request(url, headers=headers, data=data, method=method)
        if self.transport:
            try:
                return self.transport(req)
            except TypeError:
                return self.transport(url)

        try:
            with urlopen(req, timeout=12) as response:
                return json.load(response)
        except HTTPError as exc:
            err_body = ''
            try:
                err_body = exc.read().decode('utf-8')
            except Exception:
                pass
            messages = {
                401: 'Token Cal.com inválido.',
                403: 'Acesso negado: confira permissões da chave Cal.com.',
                404: 'Recurso Cal.com não encontrado.',
                409: 'Horário já reservado ou em conflito no Cal.com.',
                429: 'Limite de consultas atingido; tente mais tarde.'
            }
            msg = messages.get(exc.code, f'Cal.com retornou HTTP {exc.code}.')
            if err_body and exc.code not in (401, 429):
                try:
                    err_json = json.loads(err_body)
                    if 'message' in err_json:
                        msg += f" {err_json['message']}"
                    elif 'error' in err_json:
                        msg += f" {err_json['error']}"
                except Exception:
                    pass
            raise CalendarError(msg) from None
        except (URLError, TimeoutError, json.JSONDecodeError):
            raise CalendarError('Cal.com indisponível ou falha na rede.') from None

    def availability(self, start, end):
        start, end = window(start, end)
        params = {
            'eventTypeId': self.event_type_id,
            'start': iso(start),
            'end': iso(end)
        }

        # Fetch slots from Cal.com API v2
        data = self.request('GET', '/slots', params=params, version='2024-09-04')

        slots = []
        raw_data = data.get('data', {}) if isinstance(data, dict) else {}
        if isinstance(raw_data, dict):
            # Grouped by date: {"2026-09-16": [{"time": "2026-09-16T09:00:00Z"}]}
            for date_str, daily_slots in raw_data.items():
                if isinstance(daily_slots, list):
                    for slot in daily_slots:
                        time_str = slot.get('time') or slot.get('start') if isinstance(slot, dict) else str(slot)
                        if time_str:
                            parsed = parse_time(time_str)
                            if start <= parsed < end:
                                slots.append({
                                    'start_time': time_str,
                                    'local_time': parsed.astimezone(TZ).isoformat()
                                })
        elif isinstance(raw_data, list):
            for slot in raw_data:
                time_str = slot.get('time') or slot.get('start') if isinstance(slot, dict) else str(slot)
                if time_str:
                    parsed = parse_time(time_str)
                    if start <= parsed < end:
                        slots.append({
                            'start_time': time_str,
                            'local_time': parsed.astimezone(TZ).isoformat()
                        })

        # Sort slots chronologically
        slots.sort(key=lambda s: s['start_time'])

        return {'status': 'ok', 'source': 'calcom', 'timezone': str(TZ), 'slots': slots,
                'checked_at': iso(datetime.now(timezone.utc)), 'reservation_created': False}

    def book_direct(self, start_time, name='Cliente', email='cliente@exemplo.com', session=None):
        start = parse_time(start_time)
        if start <= datetime.now(timezone.utc) + timedelta(seconds=10):
            return {'status': 'conflict', 'reservation_created': False, 'message': 'Horário expirado.'}

        value = iso(start)

        # Idempotency check: return existing booking if session was already booked
        if session and session in self._bookings:
            existing = self._bookings[session]
            return {
                'status': 'confirmed',
                'reservation_created': True,
                'booking_id': existing['booking_id'],
                'start_time': existing['start_time'],
                'source': 'calcom',
                'idempotent_replay': True
            }

        try:
            event_type_id_num = int(self.event_type_id)
        except (ValueError, TypeError):
            event_type_id_num = self.event_type_id

        payload = {
            "start": value,
            "eventTypeId": event_type_id_num,
            "attendee": {
                "name": name,
                "email": email,
                "timeZone": "America/Sao_Paulo",
                "language": "pt-BR"
            }
        }

        try:
            res = self.request('POST', '/bookings', payload=payload, version='2024-08-13')
        except CalendarError as exc:
            if any(term in str(exc).lower() for term in ['conflito', 'já reservado', '409']):
                return {'status': 'conflict', 'reservation_created': False, 'message': 'Horário indisponível.'}
            raise

        if isinstance(res, dict) and (res.get('status') == 'success' or 'data' in res):
            data = res.get('data', {}) if isinstance(res.get('data'), dict) else {}
            uid = data.get('uid') or str(data.get('id', '')) or uuid.uuid4().hex[:12]
            booking_info = {
                'status': 'confirmed',
                'reservation_created': True,
                'booking_id': str(uid),
                'start_time': value,
                'source': 'calcom'
            }
            if session:
                self._bookings[session] = booking_info
            return booking_info

        return {'status': 'error', 'reservation_created': False, 'message': 'Falha ao reservar no Cal.com.'}

    def book(self, session, start_time, name='Cliente', email='cliente@exemplo.com'):
        return self.book_direct(start_time, name, email, session=session)

    def state(self, session):
        return self._bookings.get(session)

    def get_event_types(self):
        data = self.request('GET', '/event-types', version='2024-06-11')
        raw = data.get('data', {}) if isinstance(data, dict) else {}
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            event_types = []
            for group in raw.get('eventTypeGroups', []):
                event_types.extend(group.get('eventTypes', []))
            if not event_types and 'eventTypes' in raw:
                event_types = raw.get('eventTypes', [])
            return event_types
        return []