from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings
from app.creator import create_campaign
from app.database import make_engine, make_sessions
from app.editor import campaign_view, cancel_stream, edit_offer, publish_stream, sync_campaign
from app.editor_schemas import AddOffer, EditOffer, Revision
from app.errors import DomainError
from app.keitaro import KeitaroClient
from app.models import CreationOperation
from app.schemas import CreateCampaign

STATIC = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None, client: KeitaroClient | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    sessions = make_sessions(engine)
    remote = client or KeitaroClient(
        settings.keitaro_url, settings.keitaro_api_key.get_secret_value(), settings.keitaro_timeout
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            if client is None:
                remote.close()
            engine.dispose()

    application = FastAPI(
        title="Adrobot Keitaro wrapper", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @application.middleware("http")
    async def local_origin(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if (
                origin is not None and origin != str(request.base_url).rstrip("/")
            ) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(
                    {
                        "error": {
                            "code": "unsafe_origin",
                            "message": "Запрос с другого сайта запрещён.",
                        }
                    },
                    status_code=403,
                )
            if (
                request.headers.get("content-type", "").split(";")[0].strip().lower()
                != "application/json"
            ):
                return JSONResponse(
                    {
                        "error": {
                            "code": "json_required",
                            "message": "Ожидается Content-Type: application/json.",
                        }
                    },
                    status_code=415,
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(DomainError)
    def domain_error(_request: Request, error: DomainError):
        return JSONResponse(
            {"error": {"code": error.code, "message": error.message, "details": error.details}},
            status_code=error.status,
        )

    @application.exception_handler(RequestValidationError)
    def validation_error(_request: Request, error: RequestValidationError):
        fields = [
            {"loc": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
        return JSONResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Проверьте введённые данные.",
                    "fields": fields,
                }
            },
            status_code=422,
        )

    @application.exception_handler(SQLAlchemyError)
    def database_error(_request: Request, error: SQLAlchemyError):
        conflict = isinstance(error, IntegrityError)
        return JSONResponse(
            {
                "error": {
                    "code": "state_conflict" if conflict else "database_unavailable",
                    "message": "Состояние изменилось параллельно. Обновите экран."
                    if conflict
                    else "База данных недоступна. Проверьте подключение и миграции.",
                }
            },
            status_code=409 if conflict else 503,
        )

    def session() -> Iterator[Session]:
        with sessions() as db:
            yield db

    @application.get("/api/health")
    def health():
        return {"status": "ok"}

    @application.get("/api/catalogs")
    def catalogs():
        return remote.catalogs()

    @application.get("/api/offers")
    def offers(q: str = Query("", max_length=200)):
        return remote.search_offers(q)

    @application.get("/api/campaigns")
    def campaigns(q: str = Query("", max_length=200)):
        query = q.strip().casefold()
        return [
            {"id": row["id"], "name": row["name"], "state": row.get("state", "active")}
            for row in remote.campaigns()
            if row.get("state") != "deleted"
            and (not query or query in str(row["id"]) or query in row["name"].casefold())
        ][:100]

    @application.post("/api/campaigns", status_code=201)
    def create(
        body: CreateCampaign,
        db: Annotated[Session, Depends(session)],
        idempotency_key: Annotated[str, Header()],
    ):
        return create_campaign(db, remote, body, idempotency_key)

    @application.get("/api/operations/{key}")
    def operation(key: str, db: Annotated[Session, Depends(session)]):
        op = db.get(CreationOperation, key)
        if op is None:
            raise DomainError("Операция не найдена.", 404, "operation_missing")
        return {
            "key": op.key,
            "phase": op.phase,
            "campaign_id": op.campaign_id,
            "error": op.error,
            "result": op.result,
        }

    @application.get("/api/campaigns/{campaign_id}")
    def local_campaign(campaign_id: int, db: Annotated[Session, Depends(session)]):
        return campaign_view(db, campaign_id)

    @application.post("/api/campaigns/{campaign_id}/sync")
    def sync(campaign_id: int, db: Annotated[Session, Depends(session)]):
        return sync_campaign(db, remote, campaign_id)

    @application.post("/api/streams/{stream_id}/offers")
    def add(stream_id: int, body: AddOffer, db: Annotated[Session, Depends(session)]):
        return edit_offer(db, remote, stream_id, body.revision, body.offer_id, "add")

    @application.patch("/api/streams/{stream_id}/offers/{offer_id}")
    def edit(
        stream_id: int, offer_id: int, body: EditOffer, db: Annotated[Session, Depends(session)]
    ):
        return edit_offer(db, remote, stream_id, body.revision, offer_id, body.action, body.pin)

    @application.post("/api/streams/{stream_id}/cancel")
    def cancel(stream_id: int, body: Revision, db: Annotated[Session, Depends(session)]):
        return cancel_stream(db, stream_id, body.revision)

    @application.post("/api/streams/{stream_id}/publish")
    def publish(stream_id: int, body: Revision, db: Annotated[Session, Depends(session)]):
        return publish_stream(db, remote, stream_id, body.revision)

    if STATIC.is_dir():
        application.mount("/static", StaticFiles(directory=STATIC), name="static")

    @application.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    return application


app = create_app()
