# -*- coding: utf-8 -*-

from typing import List

import fastapi.middleware.cors
import httpx
from hashlib import md5
from pathlib import Path
from audiobooker.scrappers.librivox import Librivox
from brotli_asgi import BrotliMiddleware
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.decorator import cache
from pydantic import AnyUrl, BaseModel
from pydantic.dataclasses import dataclass

from api.epub import processor, parse_url_args, optimize_images
from api.activity import check_title
from api.scraper import search, extract_data


@dataclass
class Result:
    id: int
    author: str
    title: str
    publisher: str
    year: str
    size: str
    extension: str
    download: AnyUrl


@dataclass
class SearchResult:
    results: list[Result]
    count: int


class BookInfo(BaseModel):
    title: str
    subtitle: str
    description: str
    year: str
    author: str
    image: str
    direct_url: AnyUrl


class AudiobookInfo(BaseModel):
    title: str
    description: str
    authors: str
    url: str
    streams: List[str]


app = FastAPI()

app.add_middleware(
    fastapi.middleware.cors.CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    BrotliMiddleware,
    quality=4,
    mode="text",
    lgwin=22,
    lgblock=0,
    minimum_size=400,
    gzip_fallback=True,
)

app.mount("/static", StaticFiles(directory="api/static"), name="static")


@cache()
async def get_cache():
    return True


@app.get("/")
@cache(expire=99)
async def root():
    return {"message": "Hello, World!"}


@app.get("/query/{search_type}/{query}/{page}", response_model=SearchResult)
@cache(expire=99)
async def book_search(search_type: str, query: str, page: int):
    result = await search(query, search_type, page)
    if not result["results"] and search_type == "title":
        query = await check_title(query)
        result = await search(query, search_type, page)
    return result


@app.get("/book/{code}", response_model=BookInfo)
@cache(expire=99)
async def book_info(code: str):
    return await extract_data(code)


@app.get("/vox/{query}", response_model=AudiobookInfo)
@cache(expire=99)
async def audiobook_search(query: str):
    book = Librivox.search_audiobooks(title=query)[0]
    authors = str(book.authors[0]).split(",")[0]
    result = dict(
        title=book.title,
        description=book.description,
        authors=authors,
        url=book.url,
        streams=book.streams,
    )
    return result


@app.get("/epub", response_class=HTMLResponse)
@cache(expire=99)
async def epub(url: str, background: BackgroundTasks):
    if url.endswith(".epub"):
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            filename: str = parse_url_args(url)["filename"]
            if not filename:
                filename = url.split("/")[-1]
            title = filename.replace(".epub", "")
            filename = md5(filename.encode("utf-8")).hexdigest()
            background.add_task(optimize_images, filename=filename)
            epub_data = Path(filename)
            epub_data.write_bytes(response.content)
        return await processor(title=title, filename=filename)
    else:
        return "provide url to epub file."


@app.on_event("startup")
async def startup():
    FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
