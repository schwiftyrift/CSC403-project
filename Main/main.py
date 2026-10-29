import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from service import auth, database, jobs, mailer


def create_app(data_dir=None):
    @asynccontextmanager
    async def lifespan(app):
        mailer.check_settings()
        database.initialize(app.state.data_dir)
        jobs.fingerprint_existing_uploads(app.state.data_dir)
        yield

    app = FastAPI(title="Transcript Service", version="0.2.0", lifespan=lifespan)
    app.state.data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    app.state.max_bytes = int(os.environ.get("MAX_UPLOAD_MB", jobs.DEFAULT_MAX_MB)) * 1024 * 1024
    app.state.cookie_secure = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

    @app.middleware("http")
    async def protect_requests(request: Request, call_next):
        # Browser writes must come from this origin; API clients may omit Origin.
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            # "or": docker-compose passes an empty PUBLIC_ORIGIN when it is not configured.
            expected = (os.environ.get("PUBLIC_ORIGIN") or str(request.base_url)).rstrip("/")
            if (origin and origin != expected) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(status_code=403, content={"error": "cross-origin request rejected"})
        response = await call_next(request)
        if request.url.path.startswith(("/auth", "/jobs")):
            response.headers["Cache-Control"] = "no-store"
        else:
            # Pages and scripts must be revalidated, or browsers keep running stale copies after an update.
            response.headers.setdefault("Cache-Control", "no-cache")
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request, exc):
        return JSONResponse(status_code=400, content={"error": "invalid request; check email, password (12-128 characters), and other fields"})

    @app.get("/app")
    def root():
        return {"service": "Transcript Service", "status": "running"}

    app.include_router(auth.router)
    app.include_router(jobs.router)
    static = Path(__file__).parent / "static"
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app


app = create_app()
