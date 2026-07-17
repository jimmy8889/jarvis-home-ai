# Pilot Core production operations

Pilot Core 0.7 provides a repeatable central deployment without enabling any
audible room action. The production Compose definition uses a read-only root
filesystem, drops all Linux capabilities, prevents privilege escalation, limits
process count and log growth, and stores persistent data in one named volume.

## 1. Initialize secrets

Secrets are individual ignored files, not Compose environment values. Initialize
them once on the central host:

```bash
deploy/scripts/pilot-secrets init
```

The generated administrator and legacy-bootstrap secrets are random. Home
Assistant and Music Assistant tokens are deliberately empty until supplied over
standard input:

```bash
printf '%s' "$HOME_ASSISTANT_LONG_LIVED_TOKEN" | \
  deploy/scripts/pilot-secrets set home_assistant_token
printf '%s' "$MUSIC_ASSISTANT_TOKEN" | \
  deploy/scripts/pilot-secrets set music_assistant_token
deploy/scripts/pilot-secrets check
```

When run as root on the central Linux host, the secret tool stores files as
`root:10001` with mode `0640`; Pilot Core is pinned to UID/GID `10001`. The
containing directory remains `0700`, so host users cannot traverse it while the
non-root container process can read only the individually mounted files. On a
non-root development machine the files remain mode `0600`.

Do not place token values in shell command arguments, `infra/.env`, Git, or
room configuration. `infra/.env` contains only the bind address, port, and local
image tag. Bind to a trusted LAN or private overlay address; place a TLS reverse
proxy in front before crossing an untrusted network.

## 2. Deploy silently

```bash
cp infra/.env.example infra/.env
# Set PILOT_CORE_BIND_ADDRESS to the central host's trusted address.
deploy/scripts/pilot-core-deploy \
  --core-url http://PILOT_CORE_BIND_ADDRESS:8770
```

The deployment command:

1. validates secret ownership and modes;
2. validates the Compose definition;
3. takes a cold pre-deployment backup when Pilot Core already exists;
4. builds an image tagged with the current Git commit;
5. starts the new image and waits for readiness;
6. runs read-only integration diagnostics.

It does not synthesize speech, send room commands, change endpoint activation,
or start media.

## 3. Run diagnostics

```bash
deploy/scripts/pilot-core-diagnose \
  --core-url http://PILOT_CORE_HOST:8770 \
  --require-home-assistant \
  --require-music-assistant
```

The diagnostic calls only health, readiness, joined state, Home Assistant's API
root, and Music Assistant's `players/all` command. It never invokes the
conversation API, TTS, playback, volume, or home-control services.

After the Office endpoint is enrolled and connected, add
`--require-room office`. After supervised audio acceptance, use
`--require-armed-room office` to verify the endpoint has reported the matching
activation marker.

## 4. Enroll a device once

Reusable bootstrap registration is disabled in the container configuration.
An administrator first issues a room- and device-bound grant with a maximum
one-hour lifetime:

```bash
deploy/scripts/pilot-bootstrap-device \
  --core-url http://PILOT_CORE_HOST:8770 \
  --device-id pilot-office \
  --room-id office \
  --name "Office N150" \
  --capability audio \
  --capability voice \
  --output /secure/path/office-bootstrap.json
```

Redeem it exactly once and write the resulting device credential without
printing it:

```bash
deploy/scripts/pilot-register-device \
  --core-url http://PILOT_CORE_HOST:8770 \
  --grant-file /secure/path/office-bootstrap.json \
  --device-token-file /secure/path/office-device-token
```

The grant cannot be replayed. Store the device token in Ansible Vault, remove
the grant file, and deploy it to the endpoint as `/etc/pilot/device-token`.
During initial enrollment, the room endpoint role also accepts a mode-`0600`
controller file through `room_endpoint_core_device_token_source_file`. This
keeps the token out of inventory and command-line extra variables; move it into
Ansible Vault before treating the controller as a durable deployment host.
Once installed, routine Ansible upgrades preserve the endpoint credential if no
replacement token is supplied. New installations still require an explicit
credential source.

## 5. Back up and restore

Create a consistent cold backup:

```bash
deploy/scripts/pilot-core-backup --label before-office-enrollment
```

Pilot Core stops briefly, a manifest records every persistent file's size and
SHA-256 digest, and the service returns to its previous running state. The
archive and checksum sidecar are mode `0600` under ignored `infra/backups/` by
default. Copy them to the encrypted backup system after creation.

Restore requires the checksum sidecar and an explicit confirmation:

```bash
deploy/scripts/pilot-core-restore \
  --archive infra/backups/pilot-core-TIMESTAMP-LABEL.tar.gz \
  --yes
```

Restore first creates a new `pre-restore` backup. Archive paths, entry types,
the manifest, sizes, and hashes are validated before current data is replaced.
The pre-restore archive is the immediate rollback path.

## Rotation

```bash
deploy/scripts/pilot-secrets rotate pilot_core_admin_token
docker compose -f infra/docker-compose.yml up -d --force-recreate pilot-core
```

Rotating a device credential uses a new one-time grant for the same device ID.
The previous credential becomes invalid when the new grant is redeemed.
