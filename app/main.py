import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import motor.motor_asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import orders

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [ORDER-SERVICE] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    # Startup: connect to MongoDB with retries
    max_retries = 10
    retry_delay = 5

    for attempt in range(1, max_retries + 1):
        try:
            client = motor.motor_asyncio.AsyncIOMotorClient(settings.mongo_uri)
            # Test the connection
            await client.admin.command("ping")
            app.state.db = client[settings.db_name]
            logger.info(f"Connected to MongoDB at {settings.mongo_uri}")

            # Create indexes
            await app.state.db.orders.create_index("user_id")
            await app.state.db.orders.create_index("status")
            await app.state.db.orders.create_index("created_at")
            logger.info("MongoDB indexes created")
            break
        except Exception as e:
            logger.error(f"MongoDB connection failed (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("Max retries reached. Exiting.")
                sys.exit(1)

    yield

    # Shutdown
    logger.info("Order service shutting down...")


app = FastAPI(
    title="Order Service",
    description="E-Commerce Order Management Microservice",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])


@app.get("/health")
async def health_check():
    return {
        "status": "OK",
        "service": "order-service",
    }
