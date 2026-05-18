"""
ForgeX AI — FastAPI Application
Entry point: uvicorn app:app --reload
Dashboard: http://localhost:8000/docs
"""

from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import dashboard, trades, agents, analytics
from core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 60)
    print("  ForgeX AI — Multi-Agent Trading System")
    print(f"  Firm: {settings.ACTIVE_PROP_FIRM} | Account: {settings.ACTIVE_ACCOUNT_ID}")
    print(f"  Model: {settings.CLAUDE_MODEL}")
    print(f"  Docs: http://{settings.APP_HOST}:{settings.APP_PORT}/docs")
    print("=" * 60)
    yield
    print("[ForgeX] Shutting down.")


app = FastAPI(
    title="ForgeX AI — Trading System",
    description=(
        "Multi-agent autonomous trading system. "
        "8 agents · 9 MCP servers · 11 instruments · 6 prop firms."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(dashboard.router)
app.include_router(trades.router)
app.include_router(agents.router)
app.include_router(analytics.router)


@app.get("/", tags=["Root"])
def root():
    return {
        "system": "ForgeX AI",
        "version": "1.0.0",
        "status": "online",
        "endpoints": {
            "dashboard":  "/dashboard",
            "trades":     "/trades",
            "agents":     "/agents/status",
            "analytics":  "/analytics/performance",
            "docs":       "/docs",
        },
    }


@app.get("/health", tags=["Root"])
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_DEBUG,
    )
