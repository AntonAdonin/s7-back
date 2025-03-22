# Pydantic модели для ответа
from typing import Optional

from pydantic import Field, BaseModel

from app.api.service.flight import Flight



class Position(BaseModel):
    time: int
    icao24: str
    lat: float
    lon: float
    velocity: float
    heading: float
    vertrate: float | None = None
    callsign: str | None = None
    onground: bool
    alert: bool
    spi: bool
    squawk: str | None = None
    baroaltitude: float | None = Field(None, alias="baroalt")
    geoaltitude: float | None = None
    lastposupdate: float | None = None
    lastcontact: int | None = None


class DetailedResponse(Flight):
    pass
