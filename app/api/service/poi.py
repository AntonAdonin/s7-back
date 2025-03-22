import pyproj
from shapely.geometry import LineString
from shapely.ops import transform

from app.api.service.flight import Flight


def make_poly_str(flight: Flight, meters=500) -> str:
    route = []
    for waypoint in flight.waypoints:
        route.append((waypoint.lat, waypoint.lon))
    # 2. Создаём линию маршрута
    line = LineString(route)

    # Переходим из WGS84 в метрическую проекцию (EPSG:3857) для корректного расчёта буфера
    project = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
    line_metric = transform(project, line)

    # Задаём радиус буфера (например, 500 метров)
    buffer_distance = meters  # метры
    buffer_metric = line_metric.buffer(buffer_distance)

    # Обратно преобразуем буфер в WGS84
    project_back = pyproj.Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform
    buffer_wgs84 = transform(project_back, buffer_metric)

    # 3. Извлекаем координаты внешней оболочки буфера
    # Overpass ожидает координаты в формате "широта долгота"
    poly_coords = list(buffer_wgs84.exterior.coords)
    poly_str = " ".join(f"{lat} {lon}" for lat, lon in poly_coords)
    return poly_str
