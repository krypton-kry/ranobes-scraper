import json
import shutil
from time import sleep
import requests
from bs4 import BeautifulSoup
import os
from shutil import rmtree
from tqdm import tqdm
import sys
from ebooklib import epub
from natsort import natsorted

# is this a good idea ?
from concurrent.futures import ThreadPoolExecutor, as_completed

# TODO: add novel name to temp path
TEMP = "./temp/"

if not os.path.isdir(TEMP):
    os.mkdir(TEMP)

# figure a way to bypass this if possible
session = requests.Session()
session.headers = {
    "__cf_bm": "g9FZtenZTfwCMxWHAAc6br.M1Q4I5uq.aaCxbG7G500-1657466898-0-Adnod7hPjE6ZzgCvUHx25SPEKURd1+D5dwXdzkH7jw/TOijW6eragCFJ/9dbYMGFDTAFHfDXO2zLAHaP/XfNbjU=",
    "User-Agent": "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:100.0) Gecko/20100101 Firefox/100.0",
}


def write_file(title: str, content: str):
    with open(TEMP + get_chapter_number_from_title(title) + ".html", "wb") as fd:
        fd.write(
            (
                f"<html><body><h3>{title}</h3>" + str(content) + "<hr></body></html>"
            ).encode()
        )


def get_content(chapter) -> None:
    filename = TEMP + get_chapter_number_from_title(chapter["title"]) + ".html"
    # return if file exists & filesize is greater then 5 kb atleast
    if (os.path.isfile(filename)) and (int(os.path.getsize(filename)) > 5120):
        print(f"[INFO]: File '{filename}' seems to be valid and exists")
        return
    # sleep just for safety
    sleep(2)
    content = session.get(chapter["link"]).text
    # TODO: clean before returning
    # antibot
    if "Hello, dear visitor of our website!" in content:
        sleep(5)
        get_content(chapter)

    soup = BeautifulSoup(content, "lxml")
    article = soup.find("div", {"id": "arrticle"})

    # clean <script> and <ins> tags
    if len(article(["script", "ins"])) != 0:
        for i in article(["script", "ins"]):
            i.decompose()

    write_file(chapter["title"], article)


def get_id_from_url(url: str) -> int:
    r = session.get(url)
    s = BeautifulSoup(r.text, "lxml")
    return s.select("a.uppercase:nth-child(3)")[0]["href"].split("/")[2]


def extract_json(contents: str):
    soup = BeautifulSoup(contents, "lxml")
    for script in soup.findAll("script"):
        if "window.__DATA__" in script.text:
            return json.loads(script.text.split("window.__DATA__ = ")[-1])


# should work but if the entire program crashes this one most definitly has a role to play
def get_chapter_number_from_title(title: str) -> str:
    return str("".join(filter(str.isdigit, title.split(":")[0])))


# instead of this write everything to a json and read
def read_file(filename):
    with open(TEMP + filename, "r") as fd:
        file = str(fd.read())
        soup = BeautifulSoup(file, "lxml")
        return str(soup.find("h3").text), str(file)


def get_chapters(url: str) -> list:
    book_id = get_id_from_url(url)
    toc_url = f"https://ranobes.net/chapters/{book_id}"
    res = session.get(toc_url)

    if "Access Denied" in res.text:
        print("cloudflare error!")
        print(res.text)
        exit(-1)

    res_json = extract_json(res.text)
    # paginate
    pages_count: int = int(res_json["pages_count"])
    chapter_list = []

    for chapter in res_json["chapters"]:
        chapter_list.append(
            {
                "title": chapter["title"],
                "link": chapter["link"],
            }
        )

    for i in range(2, pages_count + 1):
        resp = session.get(f"{toc_url}/page/{i}")
        resp_json = extract_json(resp.text)

        for chapter in resp_json["chapters"]:
            chapter_list.append(
                {
                    "title": chapter["title"],
                    "link": chapter["link"],
                }
            )
    return chapter_list


def create_epub(book_name: str, folder: str, author_name: str, cover: str):
    ebook = epub.EpubBook()
    ebook.set_title(book_name)
    ebook.add_author(author_name)
    ebook.set_cover("image.jpg", open("cover.jpg", "rb").read())

    # get html in folder
    html_list = natsorted(os.listdir(TEMP))
    chapters = []

    for chapter in html_list:
        title, content = read_file(chapter)
        chap = epub.EpubHtml(
            title=title,
            file_name="chapter_%s.xhtml" % chapter.split(".")[0],
        )
        chap.content = content
        ebook.add_item(chap)
        chapters.append(chap)

    # toc
    ebook.toc = chapters

    # navigation
    ebook.add_item(epub.EpubNcx())
    ebook.add_item(epub.EpubNav())

    ebook.spine = ["cover"] + chapters
    epub.write_epub(book_name + ".epub", ebook, {})


# rename this one
def download_cover(url: str):
    r = session.get(url)
    s = BeautifulSoup(r.text, "lxml")

    novel_details = s.select_one("h1.title")

    for child in novel_details.find_all("span"):
        child.decompose()

    for i in s.findAll("img"):
        if novel_details.text in i.text:
            with open("cover.jpg", "wb") as fd:
                fd.write(session.get("https://ranobes.net" + i["src"]).content)


    novel_title = novel_details.text.strip().replace(" ", "_")
    author = s.select_one(".tag_list > a:nth-child(1)").text
    return novel_title, author


def main():
    if len(sys.argv) < 2:
        print(f"[INFO]: Usage: {sys.argv[0]} url of novel")
        exit(-1)

    url = sys.argv[1]

    if (not "http" in url) and (not "ranobes.net" in url):
        print("[ERROR] : Not a valid ranobes.net Url!")
        exit(-1)

    print("\n[INFO] : Downloading Cover ...\n")
    novel_tile, author = download_cover(url)

    print("\n[INFO] : Getting Chapter list ...\n")
    chapters: list = get_chapters(url)

    pbar = tqdm(total=len(chapters), desc="Downloading Chapters : ")

    # seems to accept 3-5!
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(get_content, chapter) for chapter in chapters]

        for task in as_completed(futures):
            pbar.update(n=1)

    pbar.close()
    create_epub(novel_tile, TEMP, author, "cover.jpg")
    shutil.rmtree(TEMP)
    print("[INFO]: Done.")

if __name__ == "__main__":
    main()
