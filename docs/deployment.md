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
