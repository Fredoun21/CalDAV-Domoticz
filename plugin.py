"""
<plugin key="CalDAVHeater" name="CalDAV Heater Control" author="fredw" version="1.0.0">
    <description>
        <h2>Contrôle des radiateurs via CalDAV</h2>
        <p>Lit un calendrier CalDAV et applique le bon niveau de chauffage selon l'événement en cours.</p>
    </description>
    <params>
        <param field="Mode1" label="Intervalle (min)" width="120px" default="5" />
        <param field="Mode2" label="IP Domoticz" width="150px" default="192.168.1.100" />
        <param field="Mode3" label="Port Domoticz" width="100px" default="8080" />
        <param field="Mode4" label="Nom du calendrier" width="200px" default="Domoticz" />
        <param field="Mode5" label="URL CalDAV" width="300px" default="https://lawachefamilyhome.synology.me:65001/caldav/Fredoun" />
        <param field="Mode6" label="Debug" width="150px">
            <options>
                <option label="None" value="0" default="true" />
                <option label="Python only" value="2" />
                <option label="Basic debug" value="62" />
                <option label="All" value="-1" />
            </options>
        </param>
        <param field="Mode7" label="CalDAV login" width="150px" default="" />
        <param field="Mode8" label="CalDAV password" width="150px" default="" />
    </params>
</plugin>
"""

import json
import os
import sys
import traceback
from datetime import datetime, time

try:
    import DomoticzEx as Domoticz
except ImportError:  # pragma: no cover
    Domoticz = None

plugin_dir = os.path.dirname(os.path.abspath(__file__))
venv_dir = os.path.join(plugin_dir, ".venv")

if os.path.isdir(venv_dir):
    package_roots = []

    lib_dir = os.path.join(venv_dir, "lib")
    if os.path.isdir(lib_dir):
        for entry in os.listdir(lib_dir):
            candidate = os.path.join(lib_dir, entry, "site-packages")
            if os.path.isdir(candidate):
                package_roots.append(candidate)

    win_lib_dir = os.path.join(venv_dir, "Lib")
    if os.path.isdir(win_lib_dir):
        site_packages = os.path.join(win_lib_dir, "site-packages")
        if os.path.isdir(site_packages):
            package_roots.append(site_packages)

    for site_pkg in package_roots:
        if site_pkg not in sys.path:
            sys.path.insert(0, site_pkg)

try:
    import caldav
except ImportError:  # pragma: no cover
    caldav = None

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

RADIATEUR_LEVEL = {
    "OFF": 0,
    "HORS GEL": 10,
    "ECO": 20,
    "CONFORT 2": 30,
    "CONFORT 1": 40,
    "CONFORT": 50,
}

def load_json_config(filename):
    """Charge un fichier de configuration JSON local au plugin."""
    config_path = os.path.join(plugin_dir, filename)
    if not os.path.isfile(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        if Domoticz is not None:
            Domoticz.Error(f"Impossible de charger {filename}")
        return {}


RADIATOR_CONFIG = load_json_config("radiators.json").get("radiators", {})
PLUGIN_SETTINGS = load_json_config("plugin_settings.json")


class BasePlugin:
    """Plugin Domoticz qui lit un agenda CalDAV et pilote les radiateurs.

    Le flux principal est le suivant :
    - lire les événements du calendrier CalDAV du jour ;
    - identifier le radiateur concerné à partir du nom d'événement ;
    - vérifier si l'événement est actif maintenant ;
    - convertir le mode demandé (ECO, CONFORT, HORS GEL, OFF...) en niveau Domoticz ;
    - envoyer le niveau au bon radiateur.
    """

    enabled = True

    def __init__(self):
        self.last_run = None

    def is_debug_enabled(self):
        """Retourne True si le mode debug Domoticz est actif."""
        try:
            return int(Parameters.get("Mode6", "0")) != 0
        except Exception:
            return False

    def log_debug(self, message):
        """Log détaillé réservé au mode debug."""
        if Domoticz is not None and self.is_debug_enabled():
            Domoticz.Log(message)

    def log_info(self, message):
        """Log compact destiné au mode normal."""
        if Domoticz is not None:
            Domoticz.Log(message)

    @staticmethod
    def normalize_radiator_name(name):
        """Normalise le nom d'un radiateur pour comparer sans tenir compte de la casse."""
        if name is None:
            return ""
        return name.strip().lower().replace("radiateur ", "").replace("radiateur", "").strip()

    def get_radiator_config(self, radiator_name):
        normalized = self.normalize_radiator_name(radiator_name)
        for key, config in RADIATOR_CONFIG.items():
            if normalized == self.normalize_radiator_name(key):
                return config
            if normalized == self.normalize_radiator_name(config.get("domoticz_device", "")):
                return config
        return {"default_mode": "ECO", "domoticz_device": f"Radiateur {normalized}"}

    @staticmethod
    def normalize_mode_name(mode):
        if mode is None:
            return None
        normalized = mode.strip().lower().replace('-', ' ').replace('_', ' ')
        normalized = normalized.replace('arret', 'off').replace('arrêt', 'off')
        normalized = normalized.replace('hors gel', 'hors gel')
        return normalized

    def resolve_radiator_level(self, radiator_name, explicit_mode=None):
        """Convertit un mode de radiateur en niveau Domoticz.

        Règle métier implémentée :
        - mode explicite : on applique exactement ce mode ;
        - mode absent : on applique CONFORT par défaut ;
        - aucune correspondance : on retombe sur CONFORT.
        """
        config = self.get_radiator_config(radiator_name)
        if explicit_mode is None:
            return RADIATEUR_LEVEL.get("CONFORT", 50)

        mode_key = self.normalize_mode_name(explicit_mode)
        canonical_map = {
            'off': 'OFF',
            'hors gel': 'HORS GEL',
            'eco': 'ECO',
            'confort 2': 'CONFORT 2',
            'confort 1': 'CONFORT 1',
            'confort': 'CONFORT',
        }
        canonical = canonical_map.get(mode_key)
        if canonical is None:
            # fallback: try direct normalized uppercase matching
            direct = explicit_mode.strip().upper()
            if direct in RADIATEUR_LEVEL:
                return RADIATEUR_LEVEL[direct]
            return RADIATEUR_LEVEL.get("CONFORT", 50)
        return RADIATEUR_LEVEL[canonical]

    def onStart(self):
        if Domoticz is not None:
            Domoticz.Log("CalDAVHeater plugin started")
            if Parameters.get("Mode6", "0") != "0":
                Domoticz.Debugging(int(Parameters.get("Mode6", "0")))
        self.onHeartbeat()

    def onStop(self):
        if Domoticz is not None:
            Domoticz.Log("CalDAVHeater plugin stopped")

    def onHeartbeat(self):
        interval_minutes = int(Parameters.get("Mode1", "5") or 5)
        now = datetime.now()
        if self.last_run is None or (now - self.last_run).total_seconds() >= interval_minutes * 60:
            try:
                self.process()
            except Exception as exc:
                if Domoticz is not None:
                    Domoticz.Error(f"CalDAVHeater error: {exc}")
                traceback.print_exc()
            self.last_run = now

    def get_domoticz_auth(self):
        settings = PLUGIN_SETTINGS.get("domoticz", {})
        username = settings.get("login", "").strip()
        password = settings.get("password", "").strip()
        if username and password:
            return (username, password)
        if username:
            return (username, "")
        return None

    def get_domoticz_auth_for_target(self, base_url):
        """Retourne les credentials uniquement si le host exige une auth HTTP.

        Domoticz accepte souvent un accès local sans authentification quand le réseau local
        est configuré comme 'no username/password'. Dans ce cas, il faut laisser auth=None.
        """
        auth = self.get_domoticz_auth()
        if auth is None:
            return None

        host = base_url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        if host in ("127.0.0.1", "localhost"):
            return None
        return auth

    def process(self):
        """Méthode principal du plugin.

        Il charge le calendrier, récupère les radiateurs Domoticz, puis applique pour
        chaque radiateur soit le mode de l'événement actif, soit le mode par défaut.
        """
        if caldav is None:
            if Domoticz is not None:
                Domoticz.Error("Module caldav absent dans l'environnement du plugin")
            return

        if requests is None:
            if Domoticz is not None:
                Domoticz.Error("Module requests absent dans l'environnement du plugin")
            return

        calendar_name = Parameters.get("Mode4", "Domoticz")
        calendar_url = Parameters.get("Mode5", "https://lawachefamilyhome.synology.me:65001/caldav/Fredoun")
        domoticz_ip = Parameters.get("Mode2", "192.168.1.100")
        domoticz_port = Parameters.get("Mode3", "8080")

        base_url = f"http://{domoticz_ip}:{domoticz_port}/json.htm?"

        calendar = self.caldav_connect(calendar_name, calendar_url)
        if calendar is None:
            if Domoticz is not None:
                self.log_info("Calendrier CalDAV indisponible")
            return

        events_list = self.caldav_event_search_to_json(calendar, datetime.now())
        self.log_info(f"Agenda: {len(events_list)} événement(s) trouvé(s) aujourd'hui")
        if self.is_debug_enabled():
            for idx, event in enumerate(events_list, start=1):
                self.log_debug(
                    f"Agenda event {idx}: name='{event.get('name')}', "
                    f"start={event.get('start')}, end={event.get('end')}"
                )
        if not events_list:
            self.log_info("Aucun événement trouvé aujourd'hui")
            return

        devices_data = self.domoticz_get_devices(base_url, "light")
        if not devices_data or devices_data.get("status") != "OK":
            if Domoticz is not None:
                Domoticz.Error("Impossible de récupérer les appareils Domoticz")
            return

        radiateurs = [
            device for device in devices_data["result"]
            if device.get("Name", "").lower().startswith("radiateur")
        ]

        final_states = []

        for device in devices_data["result"]:
            if not device.get("Name", "").lower().startswith("radiateur"):
                continue

            raw_device_name = device.get("Name", "")
            device_name = self.normalize_radiator_name(raw_device_name)
            radiator_config = self.get_radiator_config(device_name)
            event_found = False
            chosen_mode = radiator_config.get("default_mode", "ECO")
            chosen_level = self.resolve_radiator_level(device_name, chosen_mode)

            for event in events_list:
                nom_radiateur, mode = self.parse_radiateur_info(event["name"])
                normalized_nom = self.normalize_radiator_name(nom_radiateur)
                current = self.current_event(event)
                matched = normalized_nom == device_name
                self.log_debug(
                    f"comparaison: current_device='{device_name}', event_radiator='{normalized_nom}', "
                    f"event_name='{event.get('name')}', matched={matched}, current={current}, mode='{mode}'"
                )
                if matched and current:
                    chosen_mode = mode if mode is not None else "CONFORT"
                    chosen_level = self.resolve_radiator_level(device_name, chosen_mode)
                    self.domoticz_set_radiateur_level(base_url, radiateurs, device_name, chosen_level)
                    event_found = True
                    self.log_debug(f"événement actif détecté pour {device_name}, mode={chosen_mode}, level={chosen_level}")
                    break

            if not event_found:
                self.log_debug(f"aucun événement actif, application du mode défaut {chosen_mode} pour {device_name}")
                self.domoticz_set_radiateur_level(base_url, radiateurs, device_name, chosen_level)

            final_states.append((raw_device_name, chosen_mode, chosen_level))

        if Domoticz is not None:
            summary = ", ".join(
                f"{name}: {mode} ({level})" for name, mode, level in final_states
            )
            self.log_info(f"Etat radiateurs: {summary}")

    def caldav_connect(self, caldav_name, url):
        settings = PLUGIN_SETTINGS.get("caldav", {})
        caldav_username = settings.get("login", Parameters.get("Mode7", "").strip())
        caldav_password = settings.get("password", Parameters.get("Mode8", "").strip())
        try:
            client = caldav.DAVClient(
                url=url,
                username=caldav_username,
                password=caldav_password,
                timeout=30,
            )
            principal = client.principal()
            my_calendar = principal.calendar(name=caldav_name)
            if Domoticz is not None:
                Domoticz.Log(f"Calendrier CalDAV trouvé: {my_calendar.url}")
            return my_calendar
        except Exception as exc:
            if Domoticz is not None:
                Domoticz.Error(f"Erreur CalDAV connect: {exc}")
            return None

    def caldav_event_search_to_json(self, calendar, target_date):
        try:
            start_date = target_date
            end_date = datetime.combine(target_date.date(), time.max)
            events_fetched = calendar.search(
                start=start_date,
                end=end_date,
                event=True,
                expand=True,
            )

            event_list = []
            for event in events_fetched:
                event_data = {
                    "name": str(event.icalendar_component.get("SUMMARY")),
                    "date": event.icalendar_component.DTSTART.strftime("%Y-%m-%d"),
                    "start": event.icalendar_component.DTSTART.strftime("%H:%M:%S"),
                    "end": event.icalendar_component.DTEND.strftime("%H:%M:%S"),
                    "duration": str(event.get_duration()),
                }
                event_list.append(event_data)
            return event_list
        except Exception as exc:
            if Domoticz is not None:
                Domoticz.Error(f"Erreur lecture calendrier: {exc}")
            return []

    def domoticz_get_devices(self, base_url, devices_filter="light"):
        params = {
            "type": "command",
            "param": "getdevices",
            "filter": devices_filter,
            "used": "true",
            "order": "subtype",
        }
        if requests is None:
            return None

        auth = self.get_domoticz_auth_for_target(base_url)

        try:
            response = requests.get(
                base_url,
                params=params,
                auth=auth,
                timeout=20,
            )
            if response.status_code == 200:
                return response.json()
            if response.status_code == 401 and auth is not None:
                if Domoticz is not None:
                    Domoticz.Log("401 sur Domoticz local : nouvelle tentative sans authentification HTTP")
                response = requests.get(
                    base_url,
                    params=params,
                    auth=None,
                    timeout=20,
                )
                if response.status_code == 200:
                    return response.json()
            if Domoticz is not None:
                Domoticz.Error(f"Erreur getdevices: {response.status_code} - {response.text}")
            return None
        except Exception as exc:
            if Domoticz is not None:
                Domoticz.Error(f"Erreur requête Domoticz: {exc}")
            return None

    def domoticz_set_radiateur_level(self, base_url, devices_data, radiateur_name, level=None):
        """Envoie un niveau Domoticz au radiateur donné, avec log compact."""
        normalized = self.normalize_radiator_name(radiateur_name)
        config = self.get_radiator_config(normalized)
        if level is None:
            level = self.resolve_radiator_level(normalized, config.get("default_mode", "ECO"))

        device_idx = next(
            (
                device for device in devices_data
                if self.normalize_radiator_name(device.get("Name", "")) == normalized
            ),
            None,
        )
        if device_idx is None:
            if Domoticz is not None:
                self.log_debug(f"Radiateur '{radiateur_name}' introuvable dans Domoticz")
            return False

        idx = device_idx.get("idx")
        params = {
            "type": "command",
            "param": "switchlight",
            "idx": idx,
            "switchcmd": "Set Level",
            "level": level,
        }

        auth = self.get_domoticz_auth_for_target(base_url)

        try:
            response = requests.get(
                base_url,
                params=params,
                auth=auth,
                timeout=20,
            )
            if response.status_code == 401 and auth is not None:
                if Domoticz is not None:
                    Domoticz.Log("401 sur commande Domoticz local : nouvelle tentative sans authentification HTTP")
                response = requests.get(
                    base_url,
                    params=params,
                    auth=None,
                    timeout=20,
                )
            if response.status_code == 200 and response.json().get("status") == "OK":
                if Domoticz is not None:
                    self.log_info(f"Radiateur {radiateur_name} => niveau {level}")
                return True
            if Domoticz is not None:
                Domoticz.Error(f"Erreur commande radiateur {radiateur_name}: {response.text}")
            return False
        except Exception as exc:
            if Domoticz is not None:
                Domoticz.Error(f"Erreur setter radiateur: {exc}")
            return False

    def parse_radiateur_info(self, radiateur_info):
        """Extrait le nom du radiateur et son mode depuis une ligne d'événement.

        Exemple : "Radiateur Maximilien: CONFORT" -> ("maximilien", "CONFORT")
        """
        text = (radiateur_info or "").strip().lower()
        if ":" in text:
            parts = text.split(":", 1)
            nom = parts[0].replace("radiateur", "").strip()
            mode = parts[1].strip()
            return nom, mode
        nom = text.replace("radiateur", "").strip()
        return nom, None

    def current_event(self, event):
        """Vérifie si l'événement courant est actif à l'heure actuelle."""
        try:
            start_time = datetime.strptime(event["start"], "%H:%M:%S").time()
            end_time = datetime.strptime(event["end"], "%H:%M:%S").time()
            current_time = datetime.now().time()
            return start_time <= current_time <= end_time
        except Exception:
            return False

    def resolve_level(self, mode):
        """Compatibilité simple avec le mode ancien, redirige vers la logique principale."""
        if mode is not None and mode in RADIATEUR_LEVEL:
            return RADIATEUR_LEVEL[mode]
        return RADIATEUR_LEVEL.get("CONFORT", 50)


global _plugin
_plugin = BasePlugin()


def onStart():
    global _plugin
    _plugin.onStart()


def onStop():
    global _plugin
    _plugin.onStop()


def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()
