import asyncio
from contextlib import asynccontextmanager
import datetime
import logging
import os
import secrets
from pathlib import Path
from fastapi import FastAPI, Request, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from app.availability import resource_snapshot
from app.collector import MetricsCollector
from app.models import DashboardResponse
from app.security import IPAccessMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("main")

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = os.environ.get("COMPUTE_DASHBOARD_CONFIG", str(BASE_DIR / ("config.yaml" if (BASE_DIR / "config.yaml").exists() else "config.example.yaml")))

collector = MetricsCollector(CONFIG_PATH)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Compute Dashboard service...")
    collector.start_background_loop()
    yield
    logger.info("Shutting down Compute Dashboard service...")
    await collector.stop()

app = FastAPI(
    title="Compute Dashboard",
    description="Monitoring for configured compute resources",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=collector.config.get("security", {}).get("cors_origins", []),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Network access Middleware
security_cfg = collector.config.get("security", {})
app.add_middleware(
    IPAccessMiddleware,
    allowed_networks=security_cfg.get("allowed_networks", ["127.0.0.1/32", "::1/128"]),
    trusted_proxies=security_cfg.get("trusted_proxies", []),
    enabled=security_cfg.get("enabled", True)
)

# Static directory
STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    return FileResponse(STATIC_DIR / "favicon.ico", media_type="image/vnd.microsoft.icon")


@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>Dashboard UI loading...</h1>")

@app.get("/node/{node_id}", response_class=HTMLResponse)
async def serve_node_page(request: Request, node_id: str):
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>Dashboard UI loading...</h1>")

@app.get("/api/metrics", response_model=DashboardResponse)
async def get_metrics(request: Request):
    data = await collector.get_latest_metrics()
    client_ip = getattr(request.state, "client_ip", request.client.host if request.client else "127.0.0.1")
    data.client_ip = client_ip
    return data

@app.post("/api/refresh", response_model=DashboardResponse)
async def force_refresh(request: Request):
    data = await collector.refresh_all()
    client_ip = getattr(request.state, "client_ip", request.client.host if request.client else "127.0.0.1")
    data.client_ip = client_ip
    return data

@app.get("/api/events")
async def sse_events(request: Request):
    queue = collector.subscribe()

    async def event_generator():
        try:
            while True:
                # Disconnect if client leaves
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield {"event": "metrics", "data": data}
                except asyncio.TimeoutError:
                    # Keepalive ping
                    yield {"event": "ping", "data": "keepalive"}
        finally:
            collector.unsubscribe(queue)

    return EventSourceResponse(event_generator())

@app.get("/api/health")
async def health_check(request: Request):
    client_ip = getattr(request.state, "client_ip", request.client.host if request.client else "127.0.0.1")
    return {
        "status": "healthy",
        "client_ip": client_ip,
        "access_granted": getattr(request.state, "is_allowed", True),
        "server_time": datetime.datetime.now().isoformat()
    }

@app.get("/api/v1/resources", tags=["Assistant integration"])
async def available_resources(
    authorization: str = Header(default=""),
    resource_type: str | None = Query(default=None, pattern="^(gpu|cpu|workstation|kaggle)$"),
    min_free_vram_gb: float = Query(default=0, ge=0, le=100000),
    min_available_ram_gb: float = Query(default=0, ge=0, le=1000000),
    max_gpu_util_pct: float = Query(default=20, ge=0, le=100),
):
    """Read cached resource observations; no remote execution or reservation."""
    token = os.environ.get("COMPUTE_DASHBOARD_API_TOKEN", "")
    if token and not secrets.compare_digest(authorization, f"Bearer {token}"):
        raise HTTPException(status_code=401, detail="Invalid API token", headers={"WWW-Authenticate": "Bearer"})
    data = await collector.get_latest_metrics()
    return resource_snapshot(data, collector._last_refresh_time,
                             max(30, collector.refresh_interval * 3),
                             resource_type=resource_type, min_free_vram_gb=min_free_vram_gb,
                             min_available_ram_gb=min_available_ram_gb, max_gpu_util_pct=max_gpu_util_pct)


if __name__ == "__main__":
    import uvicorn
    server_cfg = collector.config.get("server", {})
    host = server_cfg.get("host", "127.0.0.1")
    port = server_cfg.get("port", 8080)
    uvicorn.run("app.main:app", host=host, port=port, reload=False, proxy_headers=False)
