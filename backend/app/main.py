import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import require_auth
from .db import init_db
from .routers import accounts, auth, data, insights, plaid, plans, spending

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
# Rejecting other Host headers stops web pages from reading the API through DNS rebinding.
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"] + [
    h.strip() for h in os.getenv("PFT_ALLOWED_HOSTS", "").split(",") if h.strip()
]
# The browser may only talk to this app, plus Plaid Link when the user connects a bank.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://cdn.plaid.com",
    "frame-src https://cdn.plaid.com",
    "connect-src 'self' https://*.plaid.com",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Personal Finance Tool", lifespan=lifespan)


@app.middleware("http")
async def privacy_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response


app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.include_router(auth.router)
for module in (accounts, plans, insights, plaid, data, spending):
    app.include_router(module.router, dependencies=[Depends(require_auth)])


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
