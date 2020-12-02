# -*- coding: utf-8 -*-

from dataclasses import asdict
from html.parser import HTMLParser
from urllib.parse import urlencode
from pydantic.dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup as bs
from pathlib import Path


@dataclass
class LibGen:
    req: str
    column: str
    page: int


parser = HTMLParser()


async def sanitize(row: list[str]):
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


async def search(query: str = "", search_type: str = "title", page: int = 0) -> dict:
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
        result = [dict(zip(cols, await sanitize(row))) for row in raw_data]
    except:
        count = 0
        result = []
    return dict(results=result, count=count)


async def extract_data(code: str) -> dict:
    data = {}
    base_url = "http://library.lol"
    link = f"{base_url}/main/{code}"
    client = httpx.AsyncClient()
    response = await client.get(link)
    markup: str = response.text
    soup = bs(markup, "lxml")
    image = f"{base_url}{soup.find('img')['src']}"
    if not image:
        filepath = "NO_IMAGE"
    else:
        try:
            response = await client.get(image)
            filepath = "./static/" + image.split("/")[-1]
            image_data = Path(filepath)
            image_data.write_bytes(response.content)
            filepath = "https://lulzx.herokuapp.com/" + filepath[2:]
            await client.aclose()
        except:
            filepath = "NO_IMAGE"
    try:
        direct_url = soup.select_one("a[href*=cloudflare]")["href"]
    except TypeError:
        direct_url = soup.select_one("a[href*=main]")["href"]
    except:
        direct_url = "/404"
    prefix = dict(author="Author", year="Year", description="Description")
    for key, value in prefix.items():
        tag = "div" if value == "Description" else "p"
        raw_data = soup.select_one(f"{tag}:contains({value})")
        data[key] = raw_data.get_text().split(":", 1)[-1].strip() if raw_data else ""
    heading = soup.find("h1").text.split(":")
    title = heading[0]
    subtitle = heading[1].strip() if len(heading) > 1 else ""
    data.update(
        title=title,
        subtitle=subtitle,
        year=data["year"][-4:],
        image=filepath,
        direct_url=direct_url,
    )
    return data
