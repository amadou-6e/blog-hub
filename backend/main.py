import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.routers import articles, connections, dev, jobs, platforms

app = FastAPI(
    title="BlogHub API",
    description="Backend for the BlogHub publishing dashboard.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(articles.router)
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
