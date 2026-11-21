# Runbook: Reach a firewalled service from containers via an SSH-tunnel sidecar

## The problem this solves

You have a service (e.g. an LLM server like vLLM) running on one machine, but that
machine's firewall only allows **SSH (port 22)** — the service's own port is blocked
to the outside. Your application runs in containers on a **different** machine and
needs to call that service. This pattern tunnels the traffic over the one open port
(SSH) using a small helper ("sidecar") container, with **nothing extra exposed** on
the network.

```
your app containers ──► tunnel sidecar :TUNNEL_PORT ──SSH(22)──► GPU_HOST :SERVICE_PORT
   (APP_HOST)                (APP_HOST)                            (the service)
```

## Fill in these values for your environment

| Placeholder    | Meaning                                                   | Example                 |
|----------------|-----------------------------------------------------------|-------------------------|
| `GPU_HOST`     | hostname/IP of the machine running the service            | `gpu01.example.com`     |
| `GPU_HOST_IP`  | IP of GPU_HOST (only if DNS doesn't resolve it)           | `10.0.0.5`              |
| `SERVICE_PORT` | port the service listens on (on GPU_HOST)                 | `8000` (vLLM default)   |
| `APP_HOST`     | machine running your container stack                      | `app01.example.com`     |
| `SSH_USER`     | the login user on GPU_HOST (same on both is simplest)     | `alice`                 |
| `TUNNEL_PORT`  | an unused port the sidecar exposes inside the container net | `18000`               |
| `KEY_PATH`     | path to the SSH private key on APP_HOST                   | `/home/alice/.ssh/id_ed25519` |
| `NET_NAME`     | your container stack's network name                       | `myapp_default`         |

## Prerequisites

- The service is up and listening on `GPU_HOST:SERVICE_PORT`
  (test on GPU_HOST: `curl http://127.0.0.1:SERVICE_PORT/...`).
- `APP_HOST` can reach `GPU_HOST` on **port 22** (`nc -z GPU_HOST 22`).
- A container engine with compose on `APP_HOST` (Docker or rootless Podman).

---

## Step 1 — Passwordless SSH key from APP_HOST -> GPU_HOST

The sidecar logs in unattended, so it needs a key with **no passphrase**.

> WARNING: This creates standing access from APP_HOST into GPU_HOST. Use a dedicated
> key and treat it as a deliberate trust decision.

```bash
# On APP_HOST: create a dedicated key if you don't have one
ssh-keygen -t ed25519 -N "" -f KEY_PATH -C "app-to-gpu-tunnel"

# Authorize that key on GPU_HOST (stdin-pipe avoids quoting issues):
cat KEY_PATH.pub | ssh SSH_USER@GPU_HOST 'umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys'

# Verify it works and the service is reachable locally on GPU_HOST:
ssh -i KEY_PATH SSH_USER@GPU_HOST 'curl -s http://127.0.0.1:SERVICE_PORT/ -o /dev/null -w "service OK: %{http_code}\n"'
```

## Step 2 — Add the sidecar to your compose file

```yaml
  tunnel:
    image: docker.io/library/alpine:latest
    container_name: tunnel
    # Lets the container resolve GPU_HOST. Omit if DNS already resolves it.
    extra_hosts:
      - "GPU_HOST:GPU_HOST_IP"
    volumes:
      - KEY_PATH:/key:ro          # mount the private key read-only
    # IMPORTANT: exec-array form. YAML '>' folding corrupts the ssh args.
    command: ["sh", "-c", "apk add --no-cache openssh-client >/dev/null 2>&1 && exec ssh -N -T -o BatchMode=yes -o StrictHostKeyChecking=no -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -i /key -l SSH_USER -L 0.0.0.0:TUNNEL_PORT:127.0.0.1:SERVICE_PORT GPU_HOST"]
    restart: unless-stopped
```

**What the ssh flags do (so you can adjust them):**

| Flag                                              | Purpose                                                                 |
|---------------------------------------------------|-------------------------------------------------------------------------|
| `-L 0.0.0.0:TUNNEL_PORT:127.0.0.1:SERVICE_PORT`   | listen on TUNNEL_PORT inside the container, forward to the service      |
| `-l SSH_USER`                                     | REQUIRED — container runs as root; without it ssh tries root@GPU_HOST   |
| `-N -T`                                           | no remote command, no terminal — a pure tunnel                          |
| `-i /key`                                         | use the mounted key                                                     |
| `StrictHostKeyChecking=no`                        | accept GPU_HOST's key automatically (unattended)                        |
| `ServerAliveInterval=15` + `ServerAliveCountMax=3`| notice a dead link in ~45s and exit, so `restart` reconnects            |
| `ExitOnForwardFailure=yes`                        | fail fast if the port can't bind                                        |

The `apk add openssh-client` installs ssh into the bare Alpine image at start. To
avoid re-installing on every restart (or if the host has no internet), build a tiny
image with `openssh-client` baked in and use that instead.

## Step 3 — Point your app at the sidecar

Your application reaches the service by the **sidecar's service name + TUNNEL_PORT**,
not the original host/port:

```
http://tunnel:TUNNEL_PORT       # e.g. http://tunnel:18000
```

Set whatever env var your app uses for the service endpoint to that URL, and make sure
the sidecar and your app containers are on the **same compose network** (`NET_NAME`).

## Step 4 — Bring up and verify

```bash
docker compose up -d tunnel <your-app-services>     # or: podman-compose up -d ...

# Sidecar should be Up with restart count staying at 0:
docker inspect tunnel --format '{{.RestartCount}} {{.State.Status}}'

# Reach the service through the tunnel from another container:
docker exec <your-app-container> sh -c 'wget -qO- http://tunnel:TUNNEL_PORT/ | head -c 100'
```

---

## Why a sidecar container (and not a tunnel on the host)?

If you run the SSH tunnel as a plain process on APP_HOST, your containers can't reach
it on `127.0.0.1` — and exposing it on the host's LAN IP would open the service to
your whole subnet (defeating the point). Putting the tunnel **inside the container
network** means only your app's containers can use it; nothing is exposed on the host
or the wider network. (This is especially true with rootless Podman, where the
container bridge lives in a separate network namespace the host cannot bind.)

## Common pitfalls

1. **`command:` must be exec-array `["sh","-c","..."]`.** YAML `>`/`|` folding corrupts
   the ssh arguments and the container crash-loops. Check with
   `docker inspect tunnel --format '{{.RestartCount}}'` — a high number means this.
2. **Forgetting `-l SSH_USER`** -> `Permission denied` (defaults to `root@GPU_HOST`).
3. **Key has a passphrase** -> ssh hangs waiting for input. Use a passphrase-free key.
4. **Mount the key read-only (`:ro`)** and keep it `chmod 600` on the host.
5. **Resilience:** if GPU_HOST reboots, the tunnel reconnects automatically once SSH is
   back (thanks to `restart: unless-stopped` + keepalive).

## Security notes

- The tunneled service is reachable **only** through the sidecar, on the internal
  container network — not on the host or subnet.
- The private key inside the sidecar grants SSH access to GPU_HOST. Use a dedicated
  key, restrict what it can do on GPU_HOST where possible (e.g. `command="..."` /
  `restrict` options in `authorized_keys`), and rotate it like any credential.
