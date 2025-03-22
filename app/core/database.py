import os

from motor.motor_asyncio import AsyncIOMotorClient

# Настройка подключения к MongoDB
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_URI = f"mongodb://{MONGO_HOST}:27017"

positions_collection = os.getenv("MONGO_COLLECTION", "positions")


async def connect_to_mongo():
    global client, db
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[os.getenv("MONGO_DB", "flights")]


async def close_mongo_connection():
    global client
    if client:
        client.close()


def get_db():
    global db
    if db is None:
        raise Exception("Database is not initialized")
    return db


def get_positions():
    global db
    return db[positions_collection]

def get_metadata():
    global db
    return db["flight_metadata"]


