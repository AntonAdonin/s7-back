import logging

import tqdm
from pymongo import MongoClient, ASCENDING

logging.basicConfig(level=logging.INFO)

# Подключение к MongoDB
client = MongoClient("mongodb://localhost:27017/")
db = client["flights"]
positions = db["positions"]
flight_metadata = db["flight_metadata"]

pipeline = [
    { "$sort": { "icao24": 1, "time": 1 } },
    { "$group": {
        "_id": "$icao24",
        "count": { "$sum": 1 },
        "startTime": { "$first": "$time" },
        "endTime": { "$last": "$time" },
        "flightDistance": {
            "$accumulator": {
                "init": "function() { return { prev: null, total: 0 }; }",
                "accumulate": """
                    function(state, lon, lat) {
                        function toRad(deg) { return deg * Math.PI / 180; }
                        if (state.prev !== null) {
                            var dlon = toRad(lon - state.prev.lon);
                            var dlat = toRad(lat - state.prev.lat);
                            var a = Math.sin(dlat / 2) * Math.sin(dlat / 2) +
                                    Math.cos(toRad(state.prev.lat)) * Math.cos(toRad(lat)) *
                                    Math.sin(dlon / 2) * Math.sin(dlon / 2);
                            var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
                            state.total += 6371 * c;
                        }
                        state.prev = { lon: lon, lat: lat };
                        return state;
                    }
                """,
                "accumulateArgs": [ "$lon", "$lat" ],
                "merge": "function(state1, state2) { return { prev: state2.prev, total: state1.total + state2.total }; }",
                "finalize": "function(state) { return state.total; }",
                "lang": "js"
            }
        }
    }},
    { "$project": {
        "icao24": "$_id",
        "count": 1,
        "flightDuration": { "$subtract": ["$endTime", "$startTime"] },
        "flightDistance": 1
    }}
]

logging.info("Запуск агрегатного запроса...")
aggregation_cursor = positions.aggregate(pipeline, allowDiskUse=True)

# Перед вставкой очищаем коллекцию, если требуется
flight_metadata.drop()

batch_size = 1000
batch = []
count_docs = 0

# Обработка курсора по батчам
for doc in tqdm.tqdm(aggregation_cursor):
    batch.append(doc)
    count_docs += 1
    if len(batch) >= batch_size:
        flight_metadata.insert_many(batch)
        logging.info(f"Вставлено {len(batch)} документов...")
        batch = []

# Вставляем остаток документов
if batch:
    flight_metadata.insert_many(batch)
    logging.info(f"Вставлено {len(batch)} документов...")


flight_metadata.create_index([("icao24", ASCENDING)])
flight_metadata.create_index([("count", ASCENDING)])
flight_metadata.create_index([("flightDuration", ASCENDING)])
logging.info("Созданы индексы для коллекции flight_metadata.")
logging.info(f"Обработано {count_docs} документов агрегации.")
