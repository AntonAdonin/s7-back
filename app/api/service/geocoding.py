import asyncio

from geopy.geocoders import Nominatim


async def get_locality(lat, lon):
    geolocator = Nominatim(user_agent="my_geopy_app")
    # Выполняем блокирующий вызов в отдельном потоке, чтобы не блокировать event loop.
    location = await asyncio.to_thread(geolocator.reverse, (lat, lon), language="ru")

    if location is None:
        return None

    address = location.raw.get("address", {})
    locality = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or "Населённый пункт не найден"
    )
    return locality