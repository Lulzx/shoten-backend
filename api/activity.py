# -*- coding: utf-8 -*-

from pydantic.dataclasses import dataclass
from dataclasses import asdict
from urllib.parse import urlencode
import httpx


@dataclass
class GoogleBooks:
    q: str


async def check_title(query: str):
    params = GoogleBooks(q=query)
    query_string = urlencode(asdict(params), doseq=True)
    url = f"https://www.googleapis.com/books/v1/volumes?{query_string}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    data = response.json()
    if data["totalItems"] != 0:
        query = data["items"][0]["volumeInfo"]["title"]
        return query
