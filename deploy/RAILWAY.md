# Deploying on Railway

Railway builds each service from its Dockerfile. Nothing here has been deployed yet; these are the steps.

1. Create a project and add the **PostgreSQL** plugin. Railway exposes `DATABASE_URL`
   (`postgres://...`; the app rewrites it to `postgresql+psycopg://` itself).
2. Add four services from the same repo, each with **Root directory = repo root** and the Dockerfile path set:

   | Service | Dockerfile | Start command (override) | Public? |
   |---|---|---|---|
   | `api` | `backend/Dockerfile` | default (runs `alembic upgrade head`, then uvicorn on `$PORT`) | private is fine |
   | `worker` | `backend/Dockerfile` | `python -m app.worker` | no |
   | `web` | `web/Dockerfile` | default (`node server.js`) | **yes** |
   | `mock-claimcenter` | `mock_claimcenter/Dockerfile` | default | demo only; delete for a real client |

3. Variables
   - `api` and `worker`: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `APP_API_TOKEN`, `FNOL_SECRETS_KEY`,
     `ANTHROPIC_API_KEY` (or OpenAI / Azure vars), `LLM_MODEL`, optional `COMPOSIO_API_KEY`, `STORAGE_DIR=/data/uploads`.
     For the demo stand-in: `MOCK_CLAIMCENTER_URL=http://${{mock-claimcenter.RAILWAY_PRIVATE_DOMAIN}}:8090`.
   - `web`: `API_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}`, `APP_API_TOKEN` (same value as the API).
4. Uploaded files: attach a **Volume** at `/data` to `api` and `worker`. Railway volumes attach to one service,
   so for production either run the worker inside the API service or switch `STORAGE_DIR` to object storage
   (S3/R2). This is the one deployment decision still open.
5. `FNOL_SECRETS_KEY` must never change after integrations are saved; rotating it makes stored credentials unreadable.
6. Put the `web` domain behind your SSO / Railway private networking until real user login is added
   (roles today come from a cookie switch and are meant for demos and the tutorial).
