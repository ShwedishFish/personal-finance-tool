import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import require_auth
from .auto_backup import keep_backing_up
from .db import init_db
from .routers import accounts, auth, data, insights, plaid, plans, spending

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
# Rejecting other Host headers stops web pages from reading the API through DNS rebinding.
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"] + [
    h.strip() for h in os.getenv("PFT_ALLOWED_HOSTS", "").split(",") if h.strip()
]
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
# The browser may only talk to this app, plus Plaid Link when the user connects a bank.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self' https://cdn.plaid.com",
    "script-src 'self' https://cdn.plaid.com",
    "frame-src https://cdn.plaid.com",
    "connect-src 'self' https://*.plaid.com",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https://cdn.plaid.com",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    backups = asyncio.create_task(keep_backing_up())
    yield
    backups.cancel()


app = FastAPI(title="Personal Finance Tool", lifespan=lifespan)


def _cross_site(request: Request) -> bool:
    """True when a browser says the request came from another site (a form or script on a web page)."""
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site not in ("same-origin", "none")
    origin = request.headers.get("origin")
    if origin is None:
        return False  # not sent by a browser page, e.g. curl or the scripts in this repo
    return origin == "null" or urlsplit(origin).hostname not in ALLOWED_HOSTS


@app.middleware("http")
async def privacy_headers(request: Request, call_next):
    # Web pages can submit forms (including file uploads) to 127.0.0.1 without reading the answer; refuse them.
    if request.method not in SAFE_METHODS and _cross_site(request):
        response = JSONResponse({"detail": "Requests from other websites are not allowed."}, status_code=403)
    else:
        response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # Revalidate on every load so an updated app never runs new HTML with a cached old app.js.
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.include_router(auth.router)
for module in (accounts, plans, insights, plaid, data, spending):
    app.include_router(module.router, dependencies=[Depends(require_auth)])


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
