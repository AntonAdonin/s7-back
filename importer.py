import os
import shutil
import tempfile
import zipfile

import ijson
import requests
import json

from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, GEOSPHERE
import logging

from tqdm import tqdm

logging.basicConfig(level=logging.INFO)

SKIP_DOWNLOAD = False
CLEAN_UP = False
UNZIP = True

load_dotenv()
# Получаем переменные окружения
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_DB = os.getenv("MONGO_DB", "flights")
DATA_ARCHIVE_URL = os.getenv("DATA_ARCHIVE_URL", None)

ARCHIVE_DIR = "./archive/"
DATA_ARCHIVE_FILE = ARCHIVE_DIR + "Archive.zip"
EXTRACT_DIR_PATH = "./extracted_files/"  # Название папки внутри проекта
os.makedirs(EXTRACT_DIR_PATH, exist_ok=True)  # Создаст папку, если её нет

logging.info("Подключаемся к бд")
# Подключаемся к MongoDB
client = MongoClient(f"mongodb://{MONGO_HOST}:27017/")
db = client[MONGO_DB]
collection = db["positions"]

logging.info("Подключились")

# # Проверка: если база уже заполнена, импорт не требуется
# if collection.estimated_document_count() > 0:
#     logging.info("База данных уже инициализирована. Импорт пропущен.")
#     exit(0)

# Скачиваем архив
if DATA_ARCHIVE_URL is not None and not SKIP_DOWNLOAD:
    logging.info("Скачиваем архив с данными...")
    response = requests.get(DATA_ARCHIVE_URL)
    with open(DATA_ARCHIVE_FILE, "wb") as f:
        f.write(response.content)
else:
    logging.info("Загрузка архива пропущена")
    logging.info(f"{SKIP_DOWNLOAD=}")
    logging.info(f"{DATA_ARCHIVE_URL=}")

# Распаковываем архив
if UNZIP:
    logging.info("Распаковываем архив...")
    logging.info(f"{UNZIP=}")
    os.makedirs(EXTRACT_DIR_PATH, exist_ok=True)
    with zipfile.ZipFile(DATA_ARCHIVE_FILE, 'r') as zip_ref:
        file_list = zip_ref.infolist()  # Получаем список файлов с их размерами

        for file_info in tqdm(file_list, desc="Распаковка", unit="файл"):
            if not file_info.is_dir():  # Пропускаем папки
                file_path = os.path.join(EXTRACT_DIR_PATH, file_info.filename)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)  # Создаём родительские папки

                with zip_ref.open(file_info.filename) as src, open(file_path, "wb") as dest:
                    shutil.copyfileobj(src, dest)  # Копируем содержимое файла
else:
    logging.info("НЕ Распаковываем архив...")
    logging.info(f"{UNZIP=}")


import decimal

def convert_decimals(obj):
    if isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals(item) for item in obj]
    elif isinstance(obj, decimal.Decimal):
        return float(obj)
    else:
        return obj


# Обрабатываем все JSON файлы в распакованной директории
for filename in os.listdir(EXTRACT_DIR_PATH):
    if filename.endswith(".json"):
        # Путь к JSON файлу (пример)
        filepath = os.path.join(EXTRACT_DIR_PATH, filename)
        logging.info(f"Импорт данных из файла: {filepath}")
        batch_size = 1000  # Размер пакета для вставки, можно настроить
        batch = []
        with open(filepath, "r", encoding="utf-8") as f:
            # Парсим элементы верхнего уровня (предполагается, что файл содержит JSON-массив)
            for record in tqdm(ijson.items(f, 'item')):
                if "lon" in record and "lat" in record:
                    record["location"] = {
                        "type": "Point",
                        "coordinates": [record["lon"], record["lat"]]
                    }
                if record["lon"] is None or record["lat"] is None:
                    continue
                record = convert_decimals(record)
                batch.append(record)
                if len(batch) >= batch_size:
                    collection.insert_many(batch)
                    batch.clear()  # очищаем пакет после вставки
        # Если остались записи, вставляем их
        if batch:
            collection.insert_many(batch)

        logging.info("Обработка файла завершена.")

# Создаём индексы
logging.info("Создаём индексы в коллекции...")
collection.create_index([("icao24", ASCENDING)])
collection.create_index([("time", ASCENDING)])
collection.create_index([("location", GEOSPHERE)])

logging.info("Импорт данных завершён.")

if CLEAN_UP:
    shutil.rmtree(EXTRACT_DIR_PATH)
    logging.info("Очистили темп папку")
else:
    logging.info("tmp не очищен")
    logging.info(f"{CLEAN_UP=}")
