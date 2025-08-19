import os
import requests
import time

BASE_URL = "https://sberworks.ru/wiki"
SPACE_KEY = "ISE"


def get_session():
    s = requests.Session()
    s.auth = (os.environ['UNAME'], os.environ['PASSWD'])
    s.verify = False
    s.cert = os.environ['CERT_PATH']
    return s


def get_children(session, page_id):
    url = f"{BASE_URL}/rest/api/content/{page_id}/child/page?limit=100&expand=body.storage"
    r = session.get(url)
    r.raise_for_status()
    return r.json().get("results", [])


def save_page_html(page):
    title = page["title"].replace("/", "_")
    html_content = page["body"]["storage"]["value"]
    with open(f"export/{title}.html", "w", encoding="utf-8") as f:
        f.write(html_content)


def export_page_and_children(session, page_id):
    children = get_children(session, page_id)
    for child in children:
        save_page_html(child)
        export_page_and_children(session, child["id"])
        time.sleep(0.5)  # чтобы не перегрузить сервер


def main():
    session = get_session()
    url = f"{BASE_URL}/rest/api/content?spaceKey={SPACE_KEY}&limit=100&expand=body.storage,ancestors"
    r = session.get(url)
    r.raise_for_status()
    pages = r.json()["results"]

    # Находим только корневые страницы
    root_pages = [p for p in pages if not p["ancestors"]]

    for page in root_pages:
        save_page_html(page)
        export_page_and_children(session, page["id"])


if __name__ == "__main__":
    main()
