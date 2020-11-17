from base64 import b64encode
from dataclasses import asdict
from typing import List
from urllib.parse import urlencode

import fastapi.middleware.cors
import httpx
from audiobooker.scrappers.librivox import Librivox
from bs4 import BeautifulSoup as bs
from fastapi import FastAPI
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.decorator import cache
from pydantic import AnyUrl, BaseModel
from pydantic.dataclasses import dataclass


@dataclass
class LibGen:
    req: str
    column: str
    page: int


@dataclass
class GoogleBooks:
    q: str


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


def sanitize(row):
    indices = 5, 6
    row = [i for j, i in enumerate(row[:10]) if j not in indices]
    row = [p.replace("'", "'").replace('"', '"') for p in row]
    size = row[-3].split(" ")
    val = size[0]
    ext = size[1]
    if ext == "Kb":
        val = float(val) / 1024
        ext = "Mb"
    size = "{:.2f} {}".format(round(float(val), 2), ext).replace(".00", "")
    row[-3] = size
    return row


async def search(query: str = "", search_type: str = "title", page: int = 0):
    params = LibGen(req=query, column=search_type, page=page)
    query_string = urlencode(asdict(params), doseq=True)
    search_url = f"http://gen.lib.rus.ec/search.php?{query_string}"
    async with httpx.AsyncClient() as client:
        search_page = await client.get(search_url)
    soup = bs(search_page.text, "lxml")
    subheadings = soup.find_all("i")
    for subheading in subheadings:
        subheading.decompose()
    try:
        information_table = soup.find_all("table")[2]
        count = soup.find_all("font")[2].string.split("|")[0].split(" ")[0]
        raw_data = [
            [
                td.a["href"]
                if td.find("a")
                and td.find("a").has_attr("title")
                and td.find("a")["title"] != ""
                else "".join(td.stripped_strings)
                for td in row.find_all("td")
            ]
            for row in information_table.find_all("tr")[1:]
        ]
        cols = [
            "id",
            "author",
            "title",
            "publisher",
            "year",
            "size",
            "extension",
            "download",
        ]
        result = [dict(zip(cols, sanitize(row))) for row in raw_data]
    except:
        count = 0
        result = []
    return dict(results=result, count=count)


def extract_data(soup) -> dict:
    data = {}
    prefix = dict(author="Author", year="Year", description="Description")
    for key, value in prefix.items():
        tag = "p"
        if value == "Description":
            tag = "div"
        raw_data = soup.select_one(f"{tag}:contains({value})")
        data[key] = raw_data.get_text().split(":", 1)[-1].strip() if raw_data else ""
    data.update(year=data["year"].split(":")[-1].strip())
    return data


app = FastAPI()

app.add_middleware(
    fastapi.middleware.cors.CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        params = GoogleBooks(q=query)
        query_string = urlencode(asdict(params), doseq=True)
        url = f"https://www.googleapis.com/books/v1/volumes?{query_string}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
        data = response.json()
        if data["totalItems"] != 0:
            query = data["items"][0]["volumeInfo"]["title"]
            result = await search(query, search_type, page)
    return result


@app.get("/book/{code}", response_model=BookInfo)
@cache(expire=99)
async def book_info(code: str):
    base_url = "http://library.lol"
    link = f"{base_url}/main/{code}"
    client = httpx.AsyncClient()
    response = await client.get(link)
    markup: str = response.text
    soup = bs(markup, "lxml")
    try:
        image = f"{base_url}{soup.find('img')['src']}"
        response = await client.get(image)
        encoded_image_data: str = (
            f"data:image/png;base64,{b64encode(response.content).decode('utf-8')}"
        )
        await client.aclose()
    except:
        encoded_image_data = "NO_IMAGE"
    try:
        direct_url = soup.select_one("a[href*=cloudflare]")["href"]
    except TypeError:
        direct_url = soup.select_one("a[href*=main]")["href"]
    heading = soup.find("h1").text.split(":")
    title = heading[0]
    subtitle = heading[1].strip() if len(heading) > 1 else ""
    data = extract_data(soup)
    result = dict(
        title=title,
        subtitle=subtitle,
        **data,
        image=encoded_image_data,
        direct_url=direct_url,
    )
    return result


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


@app.on_event("startup")
async def startup():
    FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
