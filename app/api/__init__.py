from .flights import routers as flight_routers
from .poi import routers as poi_routers

routers = (*poi_routers, *flight_routers)
