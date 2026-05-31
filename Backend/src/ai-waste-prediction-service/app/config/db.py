import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

client = MongoClient(MONGO_URI)

db = client["dry_fish_db"]

batches_collection = db["batches"]
notifications_collection = db["notifications"]