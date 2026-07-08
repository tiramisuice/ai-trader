"""FastAPI application entry point for the AI Trading Simulator."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.db.sqlite import db
from api.routes import decision, health, performance, portfolio, trading
from api.trading.scheduler import trading_scheduler

# Load environment variables from .env
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    # Startup
    logger.info("Initializing AI Trading Simulator backend...")
    db.init_db()
    trading_scheduler.initialize()
    # Auto-start trading scheduler on boot
    trading_scheduler.start()
    logger.info("Backend ready. Trading scheduler auto-started for US + TW markets.")

    yield

    # Shutdown
    logger.info("Shutting down...")
    trading_scheduler.stop()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="AI Trading Simulator",
    description="5 AI strategies compete with $10K each in simulated stock trading.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Next.js dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://ai-trader-web.fly.dev",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount route modules
app.include_router(health.router)
app.include_router(trading.router)
app.include_router(portfolio.router)
app.include_router(performance.router)
app.include_router(decision.router)
