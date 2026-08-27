# CalDAV Heater Control

Plugin Domoticz pour piloter des radiateurs à partir d’un calendrier CalDAV.

## Description

Le plugin lit les événements du calendrier CalDAV du jour et applique automatiquement le bon niveau de chauffage pour chaque radiateur Domoticz.

La logique est la suivante :

- si un événement actif correspond au radiateur et contient un mode explicite, on applique ce mode ;
- si un événement actif correspond au radiateur sans mode explicite, on applique `CONFORT` ;
- si aucun événement n’est actif pour un radiateur, on applique son mode par défaut configuré.

## Structure du dépôt

- `plugins/CalDAVHeater/plugin.py` : plugin Domoticz principal
- `plugins/CalDAVHeater/radiators.json` : configuration des radiateurs
- `plugins/CalDAVHeater/plugin_settings.json` : paramètres locaux sensibles (login/password)
- `.gitignore` : fichiers à ne pas versionner

## Installation

1. Copier le dossier `plugins/CalDAVHeater` dans le répertoire des plugins Domoticz.
2. Vérifier que le virtualenv local est bien présent dans le dossier du plugin.
3. Vérifier que les dépendances Python nécessaires sont installées dans ce virtualenv.
4. Redémarrer Domoticz ou stopper/démarrer le plugin.

## Configuration

### Type de périphérique Domoticz attendu

Le plugin pilote des appareils Domoticz de type interrupteur dimmable (`switchlight`).

Il attend donc dans Domoticz des dispositifs qui supportent :

- `Set Level`
- un niveau de 0 à 100
- un nom commençant par `Radiateur`

Exemple de configuration Domoticz :

- type : `Switch` / `Light`
- sous-type : `Dimmer`
- nom : `Radiateur Maximilien`
- niveau de commande : `Set Level`

Le plugin envoie ensuite des commandes du type :

```text
switchlight
idx=<idx>
switchcmd=Set Level
level=<niveau>
```

### Paramètres Domoticz du plugin

Les paramètres visibles dans l’interface Domoticz sont les suivants :

- Intervalle (min)
- IP Domoticz
- Port Domoticz
- Nom du calendrier
- URL CalDAV
- Debug
- CalDAV login
- CalDAV password

### Fichier `plugin_settings.json`

Ce fichier contient les identifiants sensibles et doit rester hors du dépôt Git.

Exemple :

```json
{
  "domoticz": {
    "login": "fredoun21",
    "password": "votre_mot_de_passe_domoticz"
  },
  "caldav": {
    "login": "fredoun",
    "password": "votre_mot_de_passe_caldav"
  }
}
```

### Fichier `radiators.json`

La configuration des radiateurs est séparée du code Python.

Exemple :

```json
{
  "radiators": {
    "cuisine": {
      "default_mode": "ECO",
      "domoticz_device": "Radiateur cuisine"
    },
    "maximilien": {
      "default_mode": "ECO",
      "domoticz_device": "Radiateur maximilien"
    },
    "sdb etage": {
      "default_mode": "HORS GEL",
      "domoticz_device": "Radiateur sdb etage"
    }
  }
}
```

## Modes supportés

Les modes reconnus sont :

- `OFF`
- `HORS GEL`
- `ECO`
- `CONFORT 1`
- `CONFORT 2`
- `CONFORT`

Les niveaux Domoticz associés sont :

- `OFF` → 0
- `HORS GEL` → 10
- `ECO` → 20
- `CONFORT 2` → 30
- `CONFORT 1` → 40
- `CONFORT` → 50

## Débogage

Le mode Debug peut être activé dans les paramètres du plugin. En mode debug, le plugin affiche :

- les événements trouvés
- les comparaisons entre événements et radiateurs
- le mode sélectionné
- le niveau appliqué

En mode normal, les logs sont plus compacts.

## Sécurité

- Ne jamais committer les identifiants dans le code Python.
- Garder `plugin_settings.json` hors du dépôt Git.
- Vérifier les droits du fichier JSON sur le serveur.

## Licence

Voir le fichier `License.txt` du dossier principal du projet.
