import asyncio
import logging
import os
from enum import Enum
from typing import Union, List, Dict

from SPARQLWrapper import SPARQLWrapper, JSON
from aio_overpass import Client, Query
from aio_overpass.element import collect_elements, Node
from fastapi import APIRouter
from fastapi import HTTPException
from openai import OpenAI, AsyncOpenAI
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse, Response

from app.api.service.flight import get_flight_info
from app.api.service.poi import make_poly_str

api = Client(url=os.environ.get("OSM_OVERPASS_API_URL"))
router = APIRouter(prefix="/poi", tags=["poi"])
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# --- Общие модели и перечисления ---

class Operator(str, Enum):
    EQ = "="  # равенство
    NEQ = "!="  # не равенство
    REGEX = "~"  # регулярное выражение
    LT = "<"  # меньше
    GT = ">"  # больше
    LTE = "<="  # меньше или равно
    GTE = ">="  # больше или равно


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


class POI(BaseModel):
    id: int = Field(default=0)
    name: str = Field(default="")
    type: str = Field(default="")
    description: str = Field(default="")
    image_url: str = Field(
        default=None)
    website: str = Field(default="https://s7.ru")
    lat: float | None = Field(default=None)
    lon: float | None = Field(default=None)


class FlightPOIResponse(BaseModel):
    aggregations: Dict[str, int]
    pois: List[POI]


def get_entities_data(q_ids, lang="ru"):
    """
    Принимает список Q-идентификаторов и возвращает данные сущностей, включая:
      - Название (itemLabel)
      - Описание (description)
      - Изображение (P18)
      - Тип объекта (instance of, P31)
      - Географические координаты (P625)
      - Административное деление (P131)
      - Официальный сайт (P856)
      - Дата основания (P571)

    :param q_ids: список идентификаторов (например, ["Q42", "Q5", "Q64"])
    :param lang: язык для меток и описаний (по умолчанию "ru")
    :return: список словарей с данными сущностей
    """
    sparql = SPARQLWrapper("https://query.wikidata.org/sparql")

    # Формируем часть VALUES для SPARQL запроса
    values_clause = " ".join(f"wd:{qid}" for qid in q_ids)

    # SPARQL-запрос с дополнительными опциональными свойствами
    query = f"""
    SELECT ?item ?itemLabel ?description ?image ?instanceOf ?instanceOfLabel ?coordinates ?admin ?adminLabel ?website ?inception WHERE {{
      VALUES ?item {{ {values_clause} }}

      OPTIONAL {{
        ?item schema:description ?description .
        FILTER(LANG(?description) = "{lang}")
      }}
      OPTIONAL {{ ?item wdt:P18 ?image. }}          # Изображение
      OPTIONAL {{ ?item wdt:P31 ?instanceOf. }}      # Тип объекта (instance of)
      OPTIONAL {{ ?item wdt:P625 ?coordinates. }}    # Географические координаты
      OPTIONAL {{ ?item wdt:P131 ?admin. }}          # Административное деление
      OPTIONAL {{ ?item wdt:P856 ?website. }}        # Официальный сайт
      OPTIONAL {{ ?item wdt:P571 ?inception. }}      # Дата основания

      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{lang},en". }}
    }}
    """

    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)

    results = sparql.query().convert()
    return results["results"]["bindings"]


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
    elems: list[Node] = collect_elements(query)

    # Формирование списка POI и агрегированных данных по типам (приоритет тегов: place, historic, natural, tourism)
    pois = []
    aggregations = {}
    poi_dict = {}
    for node in elems:
        poi_type = node.tags.get("place") or node.tags.get("historic") or node.tags.get("natural") or node.tags.get(
            "tourism")
        if not poi_type:
            continue
        kwargs = {'id': node.id, "name": node.tags.get("name", "Unknown"), "type": poi_type}
        if node.base_geometry:
            kwargs["lat"] = node.base_geometry.x
            kwargs["lon"] = node.base_geometry.y
        poi = POI(**kwargs)
        poi_dict[node.wikidata_id] = poi
        pois.append(poi)
        aggregations[poi_type] = aggregations.get(poi_type, 0) + 1

    entities = get_entities_data(poi_dict.keys())
    for entity in entities:
        # Извлекаем ID из URL сущности
        entity_id = entity["item"]["value"].split("/")[-1]
        cur_poi = poi_dict.get(entity_id)
        if cur_poi is None:
            continue

        label = entity.get("itemLabel", {}).get("value", None)
        if label is not None:
            cur_poi.name = label
        description = entity.get("description", {}).get("value", None)
        if description is not None:
            cur_poi.description = description
        image = entity.get("image", {}).get("value", None)
        if image is not None:
            cur_poi.image_url = image
    result = []
    for i in pois:
        if i.image_url is not None:
            result.append(i)
    result.sort(key=lambda poi: (poi.description, poi.image_url, poi.name), reverse=True)
    return FlightPOIResponse(aggregations=aggregations, pois=result)


class PoiIdsRequest(BaseModel):
    poi_ids: List[int]


class PoiDetail(POI):
    details: dict
    tags: dict

    inception: str | None = Field(default=None)


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
    poi_dict: Dict[int, PoiDetail] = {}
    pois = []
    for node in elems:
        poi_type = node.tags.get("place") or node.tags.get("historic") or node.tags.get("natural") or node.tags.get(
            "tourism")
        if not poi_type:
            continue
        kwargs = {"details": {}, 'id': node.id, "name": node.tags.get("name", "Unknown"), "type": poi_type,
                  "tags": node.tags}
        if node.base_geometry:
            kwargs["lat"] = node.base_geometry.x
            kwargs["lon"] = node.base_geometry.y
        details = kwargs["details"]
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
        poi_detail = PoiDetail(**kwargs)
        pois.append(poi_detail)
        result[node.id] = poi_detail
    entities = get_entities_data(poi_dict.keys())
    for entity in entities:
        # Извлекаем ID из URL сущности
        entity_id = entity["item"]["value"].split("/")[-1]
        cur_poi: PoiDetail = poi_dict.get(entity_id)
        if cur_poi is None:
            continue
        label = entity.get("itemLabel", {}).get("value", None)
        if label is not None:
            cur_poi.name = label
        description = entity.get("description", {}).get("value", None)
        if description is not None:
            cur_poi.description = description
        image = entity.get("image", {}).get("value", None)
        if image is not None:
            cur_poi.image_url = image
        inception = entity.get("inception", {}).get("value", "Нет даты основания")
        if inception is not None:
            cur_poi.inception = inception
    return result


class CompletionRequest(BaseModel):
    prompt: str = Field(default="")
    max_tokens: int | None = Field(default=300)
    poi_id: int = 10920237687
    icao24: str | None = "ab68f9"
    model: str | None = Field(default="deepseek/deepseek-r1-zero:free")


# Ваш API-ключ для OpenRouter (в случае использования OpenRouter, ключ может отличаться)
@router.post("/summarize", response_class=StreamingResponse)
async def get_poi_summarizations(request: CompletionRequest):
    poi_id = request.poi_id
    try:
        # Одновременное получение данных о POI и информации о полете
        entities, flight = await asyncio.gather(
            get_pois_details(PoiIdsRequest(poi_ids=[poi_id])),
            get_flight_info(icao24=request.icao24)
        )
        flight.waypoints = []
        poi = entities.get(poi_id)
        serialized_flight = flight.model_dump()
        serialized_flight.pop("count")
        serialized_poi = poi.model_dump()

        message = (f"Ты – профессиональный экскурсовод."
                   f"Твоя задача – предоставить краткую, связную и понятную выжимку по объекту,"
                   f"данные о котором содержатся в приведенном JSON\n"
                   f"Текст должен быть написан естественным языком, без технических терминов или метаданных.\n"
                   f"Сфокусируйся на интересных и значимых фактах об объекте, сохраняя ответ лаконичным и точным."
                   f"Выжимку предоставь на русском языке."
                   #f"информация о полете - \n"
                   #f"{serialized_flight}\n"
                   f"информация об объекте - \n"
                   f"{serialized_poi}\n")
        OPEN_AI_API_KEY = os.environ.get("OPEN_ROUTER_API_KEY")
        # client = OpenAI(api_key=OPEN_AI_API_KEY, base_url="https://openrouter.ai/api/v1")
        async_client = AsyncOpenAI(api_key=OPEN_AI_API_KEY, base_url="https://openrouter.ai/api/v1")
        # Используем completions endpoint вместо chat completions
        stream_response = await async_client.completions.create(
            model=request.model,
            prompt=message,
            stream=True,
            temperature=0.2,
            max_tokens=4096,
            stop=["\n\n",],

        )

        full_text = ""
        async for chunk in stream_response:
            # print(chunk.choices[0])
            # print(chunk)
            text_chunk = chunk.choices[0].text
            print(text_chunk)
            full_text += text_chunk
        return Response(full_text, media_type="text/plain; charset=utf-8")

    except Exception as e:
        logger.exception(e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
