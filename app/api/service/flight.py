import asyncio
from typing import List, Optional

from pydantic import BaseModel, Field

from app.api.service.geocoding import get_locality
from app.core.database import get_positions, get_metadata


class Waypoint(BaseModel):
    lat: float
    lon: float
    time: int
    baroaltitude: float | None = None
    __pydantic_extra__ = "ignore"


class FlightBase(BaseModel):
    icao24: str
    count: int | None = Field(default=None, ge=1, alias="count")
    flightDuration: int | None = Field(default=None, alias="flightDuration")
    flightDistance: float | None = Field(default=None, alias="flightDistance")
    departurePlace: str | None = Field(default=None, alias="departurePlace")
    arrivalPlace: str | None = Field(default=None, alias="arrivalPlace")

    async def save_to_db(self):
        meta_col = get_metadata()
        await meta_col.update_one(
            {"icao24": self.icao24},  # Filter to find the document
            {"$set": self.model_dump()},  # Update operator with the new data
            upsert=True  # Optionally, insert if document does not exist
        )


class Flight(FlightBase):
    first_seen: int
    last_seen: int
    waypoints: List[Waypoint]  # Каждый waypoint содержит lat, lon, time, baroalt


async def calculate_departure(full_flight: Flight):
    first = min(full_flight.waypoints[0], full_flight.waypoints[-1], key=lambda w: w.time)
    last = max(full_flight.waypoints[0], full_flight.waypoints[-1], key=lambda w: w.time)
    tasks = [get_locality(first.lat, first.lon), get_locality(last.lat, last.lon)]
    arrival_place, departure_place = await asyncio.gather(*tasks)
    return {"arrivalPlace": arrival_place, "departurePlace": departure_place}


async def read_flight_metadata(flight: Flight) -> Optional[FlightBase]:
    # Получаем все записи по заданному icao24
    collections = get_metadata()
    cursor = await collections.find_one({"_id": flight.icao24})
    res = FlightBase(**cursor) if cursor else None
    if res.arrivalPlace is None and res.departurePlace is None:
        values = await calculate_departure(flight)
        res.arrivalPlace = values["arrivalPlace"]
        res.departurePlace = values["departurePlace"]
        await res.save_to_db()

    return res


async def get_flight_info(icao24: str) -> Optional[Flight]:
    # Получаем все записи по заданному icao24
    collections = get_positions()
    cursor = collections.find({"icao24": icao24}).sort("time", -1)
    waypoints = []
    first_seen = None
    last_seen = None

    async for doc in cursor:
        # Собираем только нужные поля
        waypoints.append(Waypoint(**doc))

        t = doc.get("time")
        if t is not None:
            if first_seen is None or t < first_seen:
                first_seen = t
            if last_seen is None or t > last_seen:
                last_seen = t
    if not waypoints:
        return None

    flight = Flight(icao24=icao24,
                    waypoints=waypoints,
                    first_seen=first_seen,
                    last_seen=last_seen)
    metadata = await read_flight_metadata(flight)
    if metadata is None:
        metadata = {}
    else:
        metadata = metadata.model_dump()
        del metadata['icao24']
    flight = Flight(icao24=icao24,
                    waypoints=waypoints,
                    first_seen=first_seen,
                    last_seen=last_seen, **metadata)
    return flight
