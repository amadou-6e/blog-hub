import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.routers import agent, agent_sessions, articles, comments, connections, dev, jobs, patches, platforms
from backend.routers import auth as auth_router
from backend.middleware.auth import AuthMiddleware
from backend.security import install_secret_redaction

install_secret_redaction()

import backend.store as store

app = FastAPI(
    title="BlogHub API",
    description="Backend for the BlogHub publishing dashboard.",
    version="0.1.0",
)

# CORS: default to localhost only (any port, for dev with dynamic port selection).
# In production set BLOGHUB_ALLOWED_ORIGINS to a comma-separated list of exact origins,
# e.g. "https://bloghub.example.com" — this disables the localhost regex.
_env_origins = os.environ.get("BLOGHUB_ALLOWED_ORIGINS", "")
if _env_origins:
    _allowed_origins = [o.strip() for o in _env_origins.split(",") if o.strip()]
    _origin_regex = None
else:
    _allowed_origins = []
    _origin_regex = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=_origin_regex,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(AuthMiddleware)


@app.on_event("startup")
def startup_cleanup():
    store.delete_expired_sessions()
    store.recover_agent_sessions()
    store.cleanup_agent_sessions(
        retention_days=int(os.environ.get("BLOGHUB_AGENT_SESSION_RETENTION_DAYS", "90"))
    )


app.include_router(auth_router.router)
app.include_router(agent.router)
app.include_router(agent_sessions.router)
app.include_router(articles.router)
app.include_router(comments.router)
app.include_router(patches.router)
app.include_router(connections.router)
app.include_router(jobs.router)
app.include_router(platforms.router)
app.include_router(dev.router)


@app.get("/health")
def health():
    return {"status": "ok"}


# Serve static HTML screens at /screens/...
_screens_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "screens"))
app.mount("/screens", StaticFiles(directory=_screens_dir), name="screens")

_generated_previews_dir = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "generated_previews"))
os.makedirs(_generated_previews_dir, exist_ok=True)
app.mount(
    "/generated-previews",
    StaticFiles(directory=_generated_previews_dir),
    name="generated-previews",
)
