# Deployment auf Proxmox mit Cloudflare Tunnel

Ziel: Die App läuft als Docker-Compose-Stack in einer Debian-13-VM und ist unter
`https://finanzen.rxf-sys.de` erreichbar (Annahme, anpassbar). Am Router wird kein Port geöffnet.

## 1. VM anlegen

- Debian 13 (netinst), 2 vCPU, 4 GB RAM, 32 GB Disk; Disk auf verschlüsseltem Storage oder mit LUKS.
- QEMU Guest Agent aktivieren, feste IP im LAN.
- Eigener Benutzer, SSH nur mit Key, `unattended-upgrades` aktivieren.
- Docker Engine und Compose-Plugin aus dem offiziellen Docker-Repository installieren.

## 2. Cloudflare Access (zuerst!)

Access muss stehen, bevor der Tunnel den Hostnamen veröffentlicht, sonst ist die App kurz offen.

1. Zero Trust → Access → Applications → *Add an application* → *Self-hosted*.
2. Hostname: `finanzen.rxf-sys.de`. Session Duration z. B. 24 h.
3. Policy *Allow*: Include → Emails → die E-Mail-Adressen aller Haushaltsmitglieder.
4. Login-Methode: One-time PIN oder ein vorhandener Identity Provider.
5. Nach dem Speichern unter *Additional settings* den **Application Audience (AUD) Tag** kopieren.
6. Die Team-Domain notieren (`<team>.cloudflareaccess.com`, steht in den Zero-Trust-Einstellungen).

## 3. Tunnel

1. Zero Trust → Networks → Tunnels → *Create a tunnel* → Typ *Cloudflared*.
2. Den Token aus dem angezeigten Docker-Befehl kopieren (nur den Teil nach `--token`).
3. *Public Hostname*: `finanzen.rxf-sys.de` → Service `http://web:8080`.

## 4. Stack einrichten

```sh
git clone git@github.com:rxf-sys/finance-app.git && cd finance-app
cp .env.example .env            # Werte aus Schritt 2 und 3 eintragen

# Secrets: Ordner nur für deinen Benutzer, Dateien lesbar für die Container-Benutzer
chmod 700 secrets
openssl rand -base64 32 > secrets/fa_db_password
openssl rand -base64 32 > secrets/fa_encryption_key
openssl rand -base64 32 > secrets/restic_password
chmod 644 secrets/fa_db_password secrets/fa_encryption_key secrets/restic_password
```

`fa_encryption_key` und `restic_password` zusätzlich offline sichern (Passwortmanager). Ohne den
Schlüssel lassen sich TOTP-Geheimnisse nicht mehr entschlüsseln, ohne das restic-Passwort keine Backups lesen.

Images kommen aus der GitHub Container Registry (gebaut von der CI auf `main`). Ist das Repo privat,
einmalig anmelden: `echo <PAT mit read:packages> | docker login ghcr.io -u rxf-sys --password-stdin`.

```sh
docker compose pull
docker compose up -d
docker compose exec api python -m app.cli create-owner --email <deine-mail> --name "Robin" --household "Zuhause"
```

## 5. Prüfen

- `https://finanzen.rxf-sys.de` zeigt zuerst die Cloudflare-Anmeldung, danach den App-Login.
- `docker compose ps`: alle Dienste `healthy`.
- Nach dem ersten Login unter *Sicherheit* einen Passkey anlegen.
- Haushaltsmitglieder unter *Haushalt* einladen; ihre E-Mail muss auch in der Access-Policy stehen.

## Backups

Der `backup`-Dienst sichert täglich um 02:30 (`BACKUP_SCHEDULE`) per `pg_dump` in ein restic-Repository
unter `BACKUP_DIR` (Standard `./backups`). Für ein NAS den Share auf der VM mounten und `BACKUP_DIR`
darauf zeigen lassen. Aufbewahrung: 7 täglich, 4 wöchentlich, 12 monatlich.

Wiederherstellung testen (einmal pro Quartal):

```sh
docker compose exec backup restic snapshots
docker compose exec backup sh -c 'restic dump latest finance.dump > /backups/restore-test.dump'
docker compose exec -T db pg_restore --list < backups/restore-test.dump | head
```

Zusätzlich einen Proxmox-Backup-Job für die ganze VM anlegen.

## Bankabruf mit Enable Banking einrichten

Optional. Ohne diese Einrichtung antworten alle `/api/bank-connections`-Endpunkte mit 503 „Bank sync is not configured“,
die App läuft normal weiter (CSV-Import bleibt).

1. Im [Enable-Banking-Control-Panel](https://enablebanking.com/cp/applications) eine Anwendung anlegen
   (Umgebung *Production*). Den privaten Schlüssel im Browser erzeugen lassen und als PEM herunterladen;
   die angezeigte *Application ID* notieren.
2. **Redirect-URL** der Anwendung eintragen, exakt (HTTPS, siehe `FA_PUBLIC_ORIGIN`):
   `https://finanzen.rxf-sys.de/api/bank-connections/callback`
3. Schlüssel als Secret ablegen (die Datei nicht committen, `secrets/` ist ignoriert):

   ```sh
   cp ~/Downloads/<application-id>.pem secrets/fa_enablebanking_private_key
   chmod 644 secrets/fa_enablebanking_private_key
   ```

   Die Application ID kommt in `.env`: `FA_ENABLEBANKING_APP_ID=<application-id>`.
4. In `compose.yaml` ergänzen (api und worker brauchen beides, beide haben bereits Zugang zum `edge`-Netz):

   ```yaml
   x-app-env: &app-env
     # ... bestehende Einträge ...
     FA_ENABLEBANKING_APP_ID: ${FA_ENABLEBANKING_APP_ID:-}

   x-app-secrets: &app-secrets
     - fa_db_password
     - fa_encryption_key
     - fa_enablebanking_private_key

   secrets:
     fa_enablebanking_private_key:
       file: ./secrets/fa_enablebanking_private_key
   ```

   Danach `docker compose up -d`. Weitere Einstellungen (optional): `FA_ENABLEBANKING_API_BASE`
   (Standard `https://api.enablebanking.com`). Statt der Secret-Datei geht auch `FA_ENABLEBANKING_PRIVATE_KEY`
   mit dem PEM-Inhalt, das ist für Produktion aber nicht empfohlen.
5. **Eingeschränkter Modus (restricted mode):** Eine nicht vertraglich aktivierte Anwendung darf nur Konten
   abrufen, die im Control Panel mit der Anwendung *verknüpft* wurden („Activate by linking accounts“).
   Jedes Konto, das du in der App verbinden willst, musst du daher zuerst dort verknüpfen und beim Bank
   autorisieren; ein nicht verknüpftes Konto liefert in der App keine Umsätze. Das gilt auch für Konten
   weiterer Haushaltsmitglieder (ungeklärt, ob diese selbst verknüpfen dürfen: im Zweifel macht es der Inhaber der Anwendung).
6. In der App unter *Bank* die Bank wählen und die Freigabe erteilen. Danach die Konten mit lokalen Konten
   verknüpfen. Für ein Konto mit CSV-Historie startet der Abruf standardmäßig am Tag nach der letzten Buchung,
   sonst 90 Tage zurück; das Datum lässt sich beim Verknüpfen ändern.

**Abruflimit:** Viele Banken erlauben nur etwa **4 automatische Abrufe pro Tag** ohne Anwesenheit des Nutzers.
Der Worker ruft deshalb stündlich nur Verbindungen ab, deren letzter Abruf mehr als 6 Stunden zurückliegt
(sieben Tage Überlappung gegen Nachbuchungen). Der manuelle Abruf ist auf einmal pro 15 Minuten begrenzt.
Meldet die Bank ein Limit (429), versucht der Worker es später erneut. Die Freigabe läuft je nach Bank nach
höchstens 90 bis 180 Tagen ab; dann erscheint eine Benachrichtigung und die Verbindung muss erneuert werden.

## Push-Benachrichtigungen einrichten

Optional. Ohne diese Einrichtung zeigt die Karte *Push-Benachrichtigungen* unter *Sicherheit* „auf dem Server nicht
eingerichtet“, `/api/push/subscriptions` und `/api/push/test` antworten mit 503 „Push is not configured“.
Die Benachrichtigungen in der App funktionieren unverändert.

1. VAPID-Schlüssel erzeugen und als Secret ablegen (die Datei nicht committen, `secrets/` ist ignoriert):

   ```sh
   docker compose run --rm api python -m app.cli generate-vapid-key > secrets/fa_vapid_private_key
   chmod 644 secrets/fa_vapid_private_key
   ```

2. In `compose.yaml` ergänzen (api und worker brauchen das Secret; die api liefert den öffentlichen Schlüssel an
   die Browser, der worker versendet die Nachrichten):

   ```yaml
   x-app-env: &app-env
     # ... bestehende Einträge ...
     FA_VAPID_SUBJECT: ${FA_VAPID_SUBJECT:-}   # optional

   x-app-secrets: &app-secrets
     - fa_db_password
     - fa_encryption_key
     - fa_vapid_private_key

   secrets:
     fa_vapid_private_key:
       file: ./secrets/fa_vapid_private_key
   ```

   `FA_VAPID_SUBJECT` ist die Kontaktadresse für die Push-Dienste der Browser (`mailto:du@example.com` oder
   `https://...`). Ohne Angabe gilt `FA_PUBLIC_ORIGIN`, sofern es mit `https://` beginnt. Danach
   `docker compose up -d`.
3. In der App unter *Sicherheit* bei *Push-Benachrichtigungen* den Schalter *Auf diesem Gerät* einschalten und die
   Berechtigung des Browsers erteilen. Jedes Gerät und jeder Browser schaltet sich selbst ein.
4. Prüfen: *Test senden* drücken. Es erscheint „Testbenachrichtigung“ auf dem Gerät. Bleibt sie aus, meldet die
   Karte, ob der Push-Dienst die Nachricht abgelehnt hat oder das Gerät dort nicht mehr bekannt war (es wird dann
   entfernt und muss neu eingeschaltet werden).

**Neuer Schlüssel:** Abos sind an den öffentlichen Schlüssel gebunden. Wird `fa_vapid_private_key` ausgetauscht,
werden alle bestehenden Geräte-Abos ungültig; jedes Gerät muss den Schalter aus- und wieder einschalten
(die App ersetzt dabei das alte Abo). Den Schlüssel deshalb wie die anderen Secrets sichern.

**iPhone und iPad:** Push funktioniert dort nur in der installierten App. In Safari über *Teilen* →
*Zum Home-Bildschirm* hinzufügen und die App von dort öffnen; im normalen Safari-Tab ist der Schalter gesperrt.

**Versand:** Der worker prüft alle 2 Minuten auf neue Hinweise und schickt sie an die Geräte des jeweiligen
Mitglieds. Hinweise, die älter als 24 Stunden sind, werden nicht mehr gepusht. Im Log stehen bei Fehlern nur
Statuscode und Push-Dienst, nie Inhalte.

**Ruhezeiten:** Zwischen 22 und 7 Uhr (Europe/Berlin) wird nichts gepusht. Hinweise aus der Nacht gehen mit dem
ersten Lauf nach 7 Uhr raus. *Test senden* gilt nicht als Hinweis und funktioniert auch nachts.

**Abmelden:** Beim Abmelden über die App wird das Abo dieses Geräts entfernt; nach der nächsten Anmeldung muss
der Schalter wieder eingeschaltet werden. Die Abos anderer Geräte bleiben bestehen.

## Updates

```sh
git pull
docker compose pull && docker compose up -d   # Migrationen laufen beim Start des api-Dienstes
```

## Fehlerbilder

- **403 „Cloudflare Access token missing“**: Aufruf ging am Tunnel vorbei, oder die Access-App fehlt.
- **403 „token invalid“**: `FA_CF_ACCESS_AUD` oder `FA_CF_ACCESS_TEAM_DOMAIN` in `.env` prüfen.
- **Passkey-Fehler**: `FA_WEBAUTHN_RP_ID` muss genau der Hostname sein, `FA_PUBLIC_ORIGIN` die volle URL.
- **TOTP-Gerät verloren**: `docker compose exec api python -m app.cli reset-totp --email <mail>`.
