# Grocy Recipe Import

Diese App verbindet sich per API-Key mit Grocy, sucht nach Rezepten, deren Titel eine HTTP- oder HTTPS-URL ist, scraped die Rezeptdaten mit `recipe-scrapers` und importiert sie in Grocy.

Standardverhalten:

- Ein Grocy-Rezept mit einem Titel wie `https://example.com/rezept` wird als Import-Quelle behandelt.
- Das Rezept wird gescraped und standardmaessig direkt in diesem Grocy-Rezept ersetzt (`IMPORT_MODE=replace`).
- Die Zutaten werden als echte Grocy-Rezeptzutaten (`recipes_pos`) angelegt, damit sie in der Zutatenliste des Rezepts erscheinen.
- Wenn ein passendes Produkt in Grocy noch nicht existiert, wird es automatisch angelegt.
- Automatisch angelegte Produkte koennen optional in eine eigene Produktgruppe einsortiert werden.
- Fehlende, aber erkennbare Mengeneinheiten werden automatisch in Grocy angelegt (abgekürzt, z. B. `g`, `dl`, `tl`).
- Nicht messbare Zutaten (z. B. "wenig Pfeffer" oder "Salzwasser, siedend") werden nicht als Rezeptzutat angelegt, sondern als Hinweis im Rezepttext vermerkt.
- Wenn das direkte Scraping fehlschlaegt, wird die HTML-Seite geladen und ueber `scrape_html(...)` als Fallback verarbeitet.
- Wenn auch der Fallback fehlschlaegt, wird die Fehlermeldung direkt in die Beschreibung des bestehenden Grocy-Rezepts geschrieben.
- Optional koennen per Best-Effort passende Grocy-Produkte als Zutatenpositionen angelegt werden (`MATCH_PRODUCTS=true`).
- Bilder werden in Grocy als `recipepictures` hochgeladen.

## Voraussetzungen

- Ein laufendes Grocy mit aktivierter API.
- Ein Grocy API-Key.
- Docker und Docker Compose.

## Konfiguration

Am einfachsten ueber eine `.env`-Datei auf Basis von `.env.example`.

Wichtige Variablen:

- `GROCY_BASE_URL`: Basis-URL von Grocy, zum Beispiel `http://grocy:9283` oder `https://grocy.example.com`.
- `GROCY_API_KEY`: API-Key aus Grocy.
- `IMPORT_MODE`: `replace` oder `copy`.
- `POLL_INTERVAL_SECONDS`: Intervall fuer den Dauerbetrieb.
- `MATCH_PRODUCTS`: `true` oder `false`.
- `AUTO_CREATED_PRODUCTS_GROUP_NAME`: Optionaler Name einer Produktgruppe fuer automatisch angelegte Zutatenprodukte. Wenn die Gruppe nicht existiert, wird sie automatisch angelegt.

## Nutzung

1. In Grocy ein neues Rezept anlegen.
2. Als Rezeptname die Rezept-URL eintragen, zum Beispiel `https://www.allrecipes.com/recipe/...`.
3. Importer starten.

Mit Make:

```bash
make build
make up
make logs
```

Einmaliger Lauf:

```bash
make run-once
```

## Docker Compose

```bash
docker compose up -d --build
```

## Import-Modi

- `replace`: Das URL-Platzhalter-Rezept wird mit den importierten Daten ueberschrieben.
- `copy`: Es wird ein neues Rezept erzeugt. Das Quellrezept bleibt bestehen und wird mit einem Import-Marker versehen, damit es nicht erneut importiert wird.

## Hinweise

- `recipe-scrapers` liefert nicht fuer jede Website gleich strukturierte Zutaten. Fuer nicht exakt bestimmbare Zutaten werden Best-Effort-Produktnamen erzeugt und die Originalzeile als Notiz an die Rezeptzutat geschrieben.
- Die Rezeptbeschreibung enthaelt den Quelllink und die Zubereitung. Die eigentlichen Zutaten sollen primär ueber die Grocy-Zutatenliste sichtbar sein.

## GitHub Actions

Ein Workflow unter [.github/workflows/docker-publish.yml](.github/workflows/docker-publish.yml) baut bei jedem Push den Docker-Container und pushed ihn nach GitHub Container Registry (`ghcr.io`) mit den Tags `latest` und dem kurzen Commit-SHA.
