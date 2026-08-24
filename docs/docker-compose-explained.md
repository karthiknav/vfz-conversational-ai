# docker-compose.yml — `db` service explained

This covers the `db` service's `volumes` section:

```yaml
db:
  image: postgres:16-alpine
  volumes:
    - db-data:/var/lib/postgresql/data
    - ./db/init:/docker-entrypoint-initdb.d:ro
```

## `db-data:/var/lib/postgresql/data`

- `/var/lib/postgresql/data` is Postgres's default `PGDATA` directory *inside the container* — where the server stores all its actual data (tables, indexes, WAL logs, `postgresql.conf`, etc.).
- Container filesystems are ephemeral: if the container is removed, anything not in a volume is lost.
- `db-data` is a **named volume** (declared at the bottom of the file under `volumes:`), managed by Docker rather than a specific folder you choose. Mounting it here makes the database's data persist across container restarts/recreations.
- Docker also uses whether this directory is empty to decide first-run behavior (see below).

### Where does `db-data` actually live on the host?

Since it's a named volume (not a bind mount), Docker controls the location. Inspecting it:

```
docker volume inspect vfz-conversational-ai_db-data
```

resolves to:

```
/var/lib/docker/volumes/vfz-conversational-ai_db-data/_data
```

On Linux this is a real path on the host. **On Windows/Mac with Docker Desktop**, containers run inside a Linux VM (WSL2 backend), so this path is inside that VM — not directly browsable from `C:\...`. You generally don't need to touch it directly; that's the point of using a named volume instead of a bind mount. If you ever need to look inside, use `docker exec -it <container> bash` rather than reaching for the host path.

## `./db/init:/docker-entrypoint-initdb.d:ro`

- `/docker-entrypoint-initdb.d` is a convention baked into the official `postgres` image's entrypoint script. On container startup, **if the data directory is empty** (fresh database, no existing data), the script automatically runs every `.sh`, `.sql`, and `.sql.gz` file it finds in this directory, in alphabetical order.
- It only runs on that first initialization — once the volume has data, this directory is ignored on subsequent restarts.
- `./db/init` on the host is mounted here, so any init scripts placed in that folder (e.g., schema creation, seed data, role setup) run automatically the first time the container starts against a fresh volume.
- `:ro` mounts it **read-only** — the container can read and execute these scripts but can't write back to `./db/init` on the host. Since these are one-shot input scripts, read-only is just least-privilege; it isn't required for the init mechanism itself to work.

## Summary

| Mount | Purpose | Persistence |
|---|---|---|
| `db-data:/var/lib/postgresql/data` | Postgres's live data directory | Persists across restarts (named volume) |
| `./db/init:/docker-entrypoint-initdb.d:ro` | One-time init scripts (schema/seed) | Runs only when the data dir is empty |
