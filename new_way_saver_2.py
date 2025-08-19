import os
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://sberworks.ru/wiki"
SPACE_KEY = "ISE"

def get_session():
    s = requests.Session()
    s.auth = (os.environ['UNAME'], os.environ['PASSWD'])
    s.verify = False
    s.cert = os.environ['CERT_PATH']
    return s

def get_all_pages(session):
    pages = []
    start = 0
    limit = 50
    while True:
        url = f"{BASE_URL}/rest/api/content?spaceKey={SPACE_KEY}&limit={limit}&start={start}&expand=body.storage,ancestors"
        r = session.get(url)
        r.raise_for_status()
        data = r.json()
        results = data["results"]
        if not results:
            break
        pages.extend(results)
        if "_links" in data and "next" in data["_links"]:
            start += limit
        else:
            break
    return pages

def get_page_path(page):
    parts = [a["title"].replace("/", "_") for a in page.get("ancestors", [])]
    parts.append(page["title"].replace("/", "_"))
    return os.path.join("export", *parts)

def save_page_html(page):
    path = get_page_path(page)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    html_content = page["body"]["storage"]["value"]
    file_path = path + ".html"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return file_path

def main():
    session = get_session()
    pages = get_all_pages(session)

    print(f"Всего страниц: {len(pages)}")

    for page in pages:
        file_path = save_page_html(page)
        print(f"Сохранил: {file_path}")

if __name__ == "__main__":
    main()
