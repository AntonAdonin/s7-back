from typing import List

from fastapi import APIRouter
from fastapi import HTTPException, Query
from pymongo import ASCENDING, DESCENDING

from app.api.flights.schemas import DetailedResponse
from app.api.service.flight import get_flight_info, FlightBase
from app.core.database import get_metadata

router = APIRouter(prefix="/flights", tags=["flights"])


@router.get("/", response_model=List[FlightBase])
async def get_flights(
        page: int = Query(1, ge=1, description="Номер страницы"),
        limit: int = Query(10, ge=1, description="Количество записей на страницу"),
        sort_by: str = Query("icao24", description="Поле для сортировки: icao24, count, flightDuration"),
        order: int = Query(1, description="Порядок сортировки: 1 для ASC, -1 для DESC")
):
    """
    Эндпоинт возвращает список полётов (icao24 и вычисленные метаданные),
    полученных из коллекции `metadata` с пагинацией.
    Позволяет сортировать по количеству точек или длительности полёта.
    """
    # Валидируем поле сортировки
    allowed_sort_fields = {"icao24", "count", "flightDuration"}
    if sort_by not in allowed_sort_fields:
        raise HTTPException(status_code=400, detail=f"Недопустимое поле сортировки. Разрешено: {', '.join(allowed_sort_fields)}")
    # Определяем направление сортировки
    sort_direction = ASCENDING if order == 1 else DESCENDING

    skip = (page - 1) * limit
    pipeline = [
        {"$sort": {sort_by: sort_direction}},  # Сортируем по выбранному полю
        {"$skip": skip},
        {"$limit": limit}
    ]

    metadata_col = get_metadata()
    cursor = metadata_col.aggregate(pipeline)

    results = []
    async for doc in cursor:
        # Предполагаем, что документ уже содержит необходимые поля:
        # icao24, count, flightDuration, flightDistance
        item = FlightBase(**doc)
        results.append(item)

    return results


@router.get("/{icao24}/details", response_model=DetailedResponse)
async def get_flight_details(icao24: str):
    res = await get_flight_info(icao24)

    if not res:
        raise HTTPException(status_code=404, detail="Данные по заданному icao24 не найдены")

    response = DetailedResponse(**res.model_dump())
    return response
