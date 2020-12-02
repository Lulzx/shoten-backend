# -*- coding: utf-8 -*-
import os
import re
import zipfile
from base64 import b64encode
from os.path import dirname, basename, join, splitext, abspath
from pathlib import Path
from subprocess import Popen
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup as bs
from lxml import etree


class Worker:
    def __init__(self, epub_path: str, output_dir: str, title: str):
        self.epub_path = epub_path
        self.title = title
        script_dir = dirname(abspath(__file__))
        template_path = join(script_dir, "../template.html")
        self.template = Path(template_path).read_text(encoding="utf-8")
        (epub_name_without_ext, _) = splitext(basename(self.epub_path))
        self.epub_name_without_ext = epub_name_without_ext
        self.output_dir = output_dir
        self.root_a_path = join(output_dir, epub_name_without_ext)
        self.unzip()
        opf_r_root_path = self.get_opf_r_root_path()
        self.index_a_path = join(self.root_a_path, "index.html")
        self.opf_a_path = join(self.root_a_path, opf_r_root_path)
        self.opf_a_dir = dirname(join(self.root_a_path, opf_r_root_path))
        self.ncx_r_opf_path, self.css_r_opf_path = self.paths_from_opf()
        self.ncx_a_path = join(self.opf_a_dir, self.ncx_r_opf_path)
        self.css_a_path = join(self.opf_a_dir, self.css_r_opf_path)
        self.already_gen_html = set()

    @staticmethod
    def get_xml_root(path: str):
        contents = Path(path).read_text(encoding="utf-8")
        contents = re.sub(' xmlns="[^"]+"', "", contents, count=1)
        contents = contents.encode("utf-8")
        root_path = etree.fromstring(contents)
        return root_path

    def get_opf_r_root_path(self):
        meta_a_path = join(self.root_a_path, "META-INF/container.xml")
        root_path = self.get_xml_root(meta_a_path)
        for item in root_path.findall(".//rootfiles/"):
            return item.attrib["full-path"]

    def paths_from_opf(self):
        ncx_r_opf_path = None
        css_r_opf_path = None
        root_path = self.get_xml_root(self.opf_a_path)
        for item in root_path.findall(".//manifest/"):
            href = item.attrib["href"]
            if "ncx" in item.attrib["media-type"]:
                ncx_r_opf_path = href
            if "css" in item.attrib["media-type"]:
                css_r_opf_path = href
        return ncx_r_opf_path, css_r_opf_path

    def get_index_loc(self) -> str:
        return self.index_a_path

    def _gen_menu_content(self, node, menus, contents, depth=0):
        for cc in node.findall("."):
            name = cc.find("./navLabel/text").text.strip()
            link = cc.find("./content")
            src = link.attrib["src"]
            unified_src = src
            no_hash_name = src
            if src.find("#") != -1:
                no_hash_name = src[: src.find("#")]
            if "#" not in src:
                unified_src = "#" + self.hash(src)
                anchor = f'<div id="{self.hash(src)}"></div>'
                contents.append(anchor)
            else:
                unified_src = re.sub(r".+html", "", src)
            menus.append(f'<li><a href="{unified_src}">{name}</a></li>')
            if no_hash_name in self.already_gen_html:
                continue
            self.already_gen_html.add(no_hash_name)
            washed_content = self.gen_content(
                join(dirname(self.ncx_a_path), no_hash_name)
            )
            contents.append(washed_content)
            subs = cc.findall("./navPoint")
            if len(subs) > 0:
                for d in subs:
                    menus.append("<ul>")
                    self._gen_menu_content(d, menus, contents, depth + 1)
                    menus.append("</ul>")

    def gen_menu_content(self) -> tuple[str, str]:
        menus = []
        contents = []
        root_path = self.get_xml_root(self.ncx_a_path)
        menus.append('<ul class="nav nav-sidebar ">')
        for c in root_path.findall("./navMap/navPoint"):
            self._gen_menu_content(c, menus, contents, 0)
        menus.append("</ul>")
        return "\n".join(menus), "".join(contents)

    def unzip(self) -> None:
        with zipfile.ZipFile(self.epub_path, "r") as zip_ref:
            zip_ref.extractall(self.root_a_path)

    def gen_content(self, path: str) -> str:
        raw_text_content = Path(path).read_text(encoding="utf-8")
        soup = bs(raw_text_content, "lxml")
        content = str(soup.find("body"))
        washed_content = self.wash_body(content)
        washed_content = self.wash_img_link(path, washed_content)
        return washed_content

    @staticmethod
    def wash_body(sub_content) -> str:
        return sub_content.replace("<body", "<div").replace("</body>", "</div>")

    def wash_img_link(self, content_path, content) -> str:
        content = re.sub(
            '(?<=src=")(.*)(?=")',
            lambda match: os.path.relpath(
                join(dirname(content_path), match.group(1)), self.root_a_path
            ),
            content,
        )
        return content

    @staticmethod
    def hash(s) -> str:
        tag = b64encode(s.encode("ascii"))
        tag = tag.decode("ascii")
        return tag.rstrip("=")

    def gen_r_css(self) -> str:
        css = Path(self.css_a_path).read_text(encoding="utf-8")
        return f"<style>{css}</style>"

    def gen(self) -> None:
        menu, full_content = self.gen_menu_content()
        self.template = self.template.replace("${menu}$", menu)
        self.template = self.template.replace("${title}$", self.title)
        self.template = self.template.replace("${content}$", full_content)
        self.template = self.template.replace("${css}$", self.gen_r_css())
        Path(
            join(self.output_dir, self.epub_name_without_ext, "./index.html")
        ).write_text(self.template, encoding="utf-8")


def parse_url_args(url: str) -> dict:
    query = parse_qs(urlparse(url).query)
    return {k: v[0] if v and len(v) == 1 else v for k, v in query.items()}


async def optimize_images(filename: str):
    directory = f"./static/{filename}/"
    Popen(["python", "-m", "optimize_images", f"{directory}"])


async def replace_links(content: str, filepath: str):
    soup = bs(content, "lxml")
    for src in soup.findAll("a"):
        try:
            src["href"] = src["href"][src["href"].find("#") :]
        except KeyError:
            pass
    for img in soup.findAll("img"):
        img.attrs["loading"] = "lazy"
        img.attrs["src"] = f"{filepath}/{img.attrs['src'].replace('..','')}"
    return str(soup)


async def processor(title: str, filename: str):
    output_dir = "./static/"
    original = output_dir + filename
    if filename[0] != "." and filename[0] != "/":
        filename = "./" + filename
    filename = abspath(filename)
    e = Worker(filename, output_dir, title)
    e.gen()
    path = e.get_index_loc()
    data = Path(path).read_text(encoding="utf-8")
    data = await replace_links(data, original)
    return data
