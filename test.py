import asyncio
import os

from aio_overpass import Client, Query


async def main():

    query = Query('way["addr:housename"]; out geom;')

    client = Client(url='https://maps.mail.ru/osm/tools/overpass/api/interpreter')

    await client.run_query(query)

    print(query.result_set)

asyncio.run(main())