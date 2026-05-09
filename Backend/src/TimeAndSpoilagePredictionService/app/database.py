import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.config import settings

logger = logging.getLogger(__name__)


class MongoDB:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None


mongodb = MongoDB()


async def connect_to_mongo() -> None:
    try:
        mongodb.client = AsyncIOMotorClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)
        await mongodb.client.admin.command("ping")
        mongodb.db = mongodb.client[settings.MONGO_DB_NAME]
        logger.info("Connected to MongoDB at %s", settings.MONGO_URI)
    except Exception as exc:
        logger.warning("MongoDB connection failed: %s. Persistence disabled.", exc)
        mongodb.client = None
        mongodb.db = None


async def close_mongo_connection() -> None:
    if mongodb.client is not None:
        mongodb.client.close()
        logger.info("MongoDB connection closed.")


def get_predictions_collection() -> Optional[AsyncIOMotorCollection]:
    if mongodb.db is None:
        return None
    return mongodb.db[settings.MONGO_COLLECTION_PREDICTIONS]
