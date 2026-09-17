"""Geocoding + Routes API. Decision uses unrounded seconds, never straight-line distance."""
import json
import math
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from dotenv import load_dotenv

load_dotenv()


class MapsError(Exception):
    pass


class GoogleServiceArea:
    def __init__(self, transport=None):
        self.transport = transport
        self.key = os.getenv('GOOGLE_MAPS_API_KEY', '')
        origin = os.getenv('COMPANY_ORIGIN_ADDRESS', '').strip()
        self.origin = re.sub(r'\bXV\b', 'Quinze', origin, flags=re.IGNORECASE)
        self.state = os.getenv('SERVICE_AREA_DEFAULT_STATE', 'SP').strip().upper()
        self.limit = 3600  # inclusive; not controlled by the LLM

    def request(self, req):
        if self.transport:
            return self.transport(req)
        try:
            with urlopen(req, timeout=12) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            # Do not expose URL: Geocoding request carries an API key.
            raise MapsError('Falha ao consultar Google Maps; cobertura não verificada.') from None

    def check(self, destination, state=''):
        result = {'source': 'google_maps', 'status': 'unknown', 'served': None,
                  'destination_requested': destination, 'threshold_seconds': self.limit,
                  'origin': self.origin, 'checked_at': datetime.now(timezone.utc).isoformat(),
                  'routing_preference': 'TRAFFIC_AWARE', 'travel_mode': 'DRIVE'}
        destination = destination.strip()
        state = state.strip().upper() or self.state
        result['state_context'] = state
        if not destination:
            return {**result, 'reason': 'Informe cidade/UF, CEP ou endereço do serviço.'}
        if not self.key or not self.origin:
            return {**result, 'reason': 'Configure GOOGLE_MAPS_API_KEY e COMPANY_ORIGIN_ADDRESS.'}
        if not re.fullmatch('[A-Z]{2}', state):
            return {**result, 'reason': 'Informe UF com duas letras.'}
        try:
            normalized_address = re.sub(r'\bXV\b', 'Quinze', destination, flags=re.IGNORECASE)
            params = urlencode({'address': normalized_address, 'components': 'country:BR',
                                'region': 'br', 'language': 'pt-BR', 'key': self.key})
            geo = self.request(Request('https://maps.googleapis.com/maps/api/geocode/json?' + params))
            candidates = geo.get('results', [])
            if geo.get('status') != 'OK' or len(candidates) != 1 or candidates[0].get('partial_match'):
                return {**result, 'reason': 'Localização não resolvida com segurança. Peça cidade/UF ou endereço completo.'}
            place = candidates[0]
            resolved_states = [c['short_name'] for c in place.get('address_components', [])
                               if 'administrative_area_level_1' in c.get('types', [])]
            if resolved_states != [state]:
                return {**result, 'reason': 'UF resolvida difere da informada/configurada; confirme cidade e UF.'}
            result['resolved_destination'] = place['formatted_address']
            result['location_precision'] = 'address' if any(t in place.get('types', []) for t in ['street_address', 'premise', 'subpremise']) else 'approximate'
            body = {'origin': {'address': self.origin}, 'destination': {'placeId': place['place_id']},
                    'travelMode': 'DRIVE', 'routingPreference': 'TRAFFIC_AWARE',
                    'computeAlternativeRoutes': False, 'languageCode': 'pt-BR', 'units': 'METRIC'}
            routes = self.request(Request('https://routes.googleapis.com/directions/v2:computeRoutes',
                data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
                'X-Goog-Api-Key': self.key,
                'X-Goog-FieldMask': 'routes.duration,routes.distanceMeters,fallbackInfo'}, method='POST'))
            if routes.get('fallbackInfo') or not routes.get('routes'):
                return {**result, 'reason': 'Sem rota compatível com a política de trânsito solicitada.'}
            route = routes['routes'][0]
            duration = route.get('duration', '')
            if not re.fullmatch(r'\d+(?:\.\d+)?s', duration):
                raise MapsError('Google Maps não retornou duração válida.')
            seconds = float(duration[:-1])
            if not math.isfinite(seconds):
                raise MapsError('Google Maps não retornou duração finita.')
            meters = route.get('distanceMeters')
            if not isinstance(meters, (int, float)) or not math.isfinite(meters) or meters < 0:
                raise MapsError('Google Maps não retornou distância válida.')
            return {**result, 'status': 'ok', 'served': seconds <= self.limit,
                    'duration_seconds': seconds, 'duration_minutes': round(seconds / 60, 2),
                    'distance_meters': meters, 'distance_km': round(meters / 1000, 2),
                    'reason': 'Dentro do limite de 60 minutos.' if seconds <= self.limit else 'Acima do limite de 60 minutos.',
                    'qualification': 'Estimativa para saída agora. Cidade/CEP representam um ponto aproximado; confirme endereço antes da visita.'}
        except (MapsError, KeyError, TypeError, ValueError) as exc:
            return {**result, 'reason': str(exc) if isinstance(exc, MapsError) else 'Resposta incompleta do Google Maps.'}
