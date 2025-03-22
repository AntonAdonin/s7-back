import logging
import os
from enum import Enum
from typing import Optional, Union, List, Dict

from aio_overpass import Client, Query
from aio_overpass.element import collect_elements
from fastapi import APIRouter
from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.api.service.flight import get_flight_info
from app.api.service.poi import make_poly_str

api = Client(url=os.environ.get("OSM_OVERPASS_API_URL"))
router = APIRouter(prefix="/poi", tags=["poi"])


# --- Общие модели и перечисления ---

class Operator(str, Enum):
    EQ = "="     # равенство
    NEQ = "!="   # не равенство
    REGEX = "~"  # регулярное выражение
    LT = "<"     # меньше
    GT = ">"     # больше
    LTE = "<="   # меньше или равно
    GTE = ">="   # больше или равно

class FilterCondition(BaseModel):
    """
    Условие фильтрации, например:
      - "place"="city"
      - "historic" (без значения, просто наличие тега)
    """
    key: str
    operator: Operator | None = Operator.EQ
    value: Union[str, int, float] | None = None

class FilterRequest(BaseModel):
    distance: int = Field(default=400, ge=0)
    # Фильтры, применяемые для формирования запроса Overpass API
    overpass_filters: List[FilterCondition] = [
        FilterCondition(key="place", operator=Operator.EQ, value="city"),
        FilterCondition(key="place", operator=Operator.EQ, value="village"),
        FilterCondition(key="nature", operator=Operator.EQ, value="water"),
        FilterCondition(key="nature", operator=Operator.EQ, value="mountain"),
    ]
    with_summarization: bool = Field(default=False)

class POI(BaseModel):
    id: int
    name: str
    type: str

class SummarizationResponse(BaseModel):
    about_flight: str


class FlightPOIResponse(BaseModel):
    aggregations: Dict[str, int]
    pois: List[POI]

# --- Эндпойнт для получения минимальной информации по POI с агрегацией ---
@router.post("/flight/{icao24}/pois", response_model=FlightPOIResponse)
async def get_aggregated_pois(icao24: str, filter: FilterRequest):
    """
    Получает информацию о полёте для построения полигона поиска, затем
    формирует запрос к Overpass API по заданным фильтрам и возвращает:
      - список POI с минимальными данными (id, name, type)
      - агрегированную информацию (например, количество городов, деревень и т.д.)
    """
    # Получение информации о полёте (функция должна быть реализована отдельно)
    flight = await get_flight_info(icao24)
    if flight is None:
        raise HTTPException(status_code=404, detail="Flight not found")

    # Формирование полигона поиска (расширяем область, например, на 1000 метров)
    poly_str = make_poly_str(flight, filter.distance)

    # Формирование динамического запроса для каждого условия фильтра
    query_parts = []
    for cond in filter.overpass_filters:
        if cond.value is not None:
            query_parts.append(f'node["{cond.key}"="{cond.value}"](poly:"{poly_str}");')
        else:
            query_parts.append(f'node["{cond.key}"](poly:"{poly_str}");')

    # Объединяем условия через OR
    query_str = "[out:json];\n(\n" + "\n".join(query_parts) + "\n);\nout body;"
    query = Query(query_str)
    await api.run_query(query)

    # Сбор элементов из ответа
    elems = collect_elements(query)

    # Формирование списка POI и агрегированных данных по типам (приоритет тегов: place, historic, natural, tourism)
    pois = []
    aggregations = {}
    for node in elems:
        poi_type = node.tags.get("place") or node.tags.get("historic") or node.tags.get("natural") or node.tags.get("tourism")
        if not poi_type:
            continue
        pois.append(POI(id=node.id, name=node.tags.get("name", "Unknown"), type=poi_type))
        aggregations[poi_type] = aggregations.get(poi_type, 0) + 1
    return FlightPOIResponse(aggregations=aggregations, pois=pois)


class PoiIdsRequest(BaseModel):
    poi_ids: List[int]


# --- Схемы для ответа ---

class Coordinates(BaseModel):
    latitude: float
    longitude: float


class PoiDetail(BaseModel):
    id: int
    name: str
    tags: Dict[str, Union[str, int, float]]
    details: Dict[str, str]
    coordinates: Coordinates | None = None


# --- Эндпойнт для получения подробной информации по списку POI id ---

@router.post("/pois/details", response_model=Dict[int, PoiDetail])
async def get_pois_details(poi_ids_request: PoiIdsRequest):
    """
    Получает подробную информацию по списку идентификаторов POI.
    Возвращается словарь, где ключ — poi_id, а значение — объект PoiDetail.
    """
    poi_ids = poi_ids_request.poi_ids
    if not poi_ids:
        raise HTTPException(status_code=400, detail="No POI IDs provided")

    # Формирование запроса к Overpass API для нескольких узлов сразу
    ids_str = " ".join(f"node({poi_id});" for poi_id in poi_ids)
    query_str = f"""
    [out:json];
    (
      {ids_str}
    );
    out body;
    """
    query = Query(query_str)
    await api.run_query(query)

    elems = collect_elements(query)
    if not elems:
        raise HTTPException(status_code=404, detail="POIs not found")

    # Собираем подробности для каждого POI, формируя читаемую структуру
    result: Dict[int, PoiDetail] = {}
    for node in elems:
        details = {}
        # Добавляем описание, если есть
        if "description" in node.tags:
            details["Описание"] = node.tags["description"]
        # Формирование адреса
        if "addr:full" in node.tags:
            details["Полный адрес"] = node.tags["addr:full"]
        else:
            addr_parts = []
            if "addr:street" in node.tags:
                addr_parts.append(node.tags["addr:street"])
            if "addr:housenumber" in node.tags:
                addr_parts.append(node.tags["addr:housenumber"])
            if addr_parts:
                details["Адрес"] = " ".join(addr_parts)
        # Дополнительные поля
        if "website" in node.tags:
            details["Веб-сайт"] = node.tags["website"]
        if "phone" in node.tags:
            details["Телефон"] = node.tags["phone"]
        if "opening_hours" in node.tags:
            details["Часы работы"] = node.tags["opening_hours"]

        poi_detail = PoiDetail(
            id=node.id,
            name=node.tags.get("name", "Unknown"),
            tags=node.tags,
            details=details,
            coordinates=Coordinates(latitude=node.lat, longitude=node.lon)
            if hasattr(node, "lat") and hasattr(node, "lon") else None
        )
        result[node.id] = poi_detail

    return result