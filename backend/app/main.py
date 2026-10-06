from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_secrets()  # refuse to start with missing or weak secrets
    yield


# The schema is managed exclusively by Alembic. Interactive docs AND the OpenAPI document are
# disabled so unauthenticated callers cannot list the API surface.
app = FastAPI(
    title="OPSEC Monitor",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
