# pyrefly: ignore [missing-import]
from pymongo import MongoClient
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
import os
import sys

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

try:
    client = MongoClient(MONGO_URI)

    # Test connection
    client.admin.command("ping")

    print("MongoDB connected")

    db = client["dryfishdb"]

    batches_collection = db["batches"]
    notifications_collection = db["notifications"]

except Exception as error:
    print(f"Database connection error: {error}")
    sys.exit(1)