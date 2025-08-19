import os
import re
import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://sberworks.ru/wiki"
SPACE_KEY = "ISE"
MAX_PAGES = 2000  # ограничение на количество выгруженных страниц для тестов

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
        url = f"{BASE_URL}/rest/api/content?spaceKey={SPACE_KEY}&limit={limit}&start={start}&expand=body.view,ancestors"
        r = session.get(url)
        r.raise_for_status()
        data = r.json()
        results = data["results"]
        if not results:
            break
        pages.extend(results)
        if len(pages) >= MAX_PAGES:
            pages = pages[:MAX_PAGES]
            break
        if "_links" in data and "next" in data["_links"]:
            start += limit
        else:
            break
    return pages

def get_page_path(page):
    parts = [a["title"].replace("/", "_") for a in page.get("ancestors", [])]
    parts.append(page["title"].replace("/", "_"))
    return os.path.join("export", *parts)

def download_attachments(session, page, page_dir):
    url = f"{BASE_URL}/rest/api/content/{page['id']}/child/attachment?limit=1000"
    r = session.get(url)
    r.raise_for_status()
    attachments = r.json().get("results", [])

    attach_dir = os.path.join(page_dir, "attachments")
    os.makedirs(attach_dir, exist_ok=True)

    mapping = {}  # {original_download_url: relative_local_path}

    for att in attachments:
        fname = att["title"].replace("/", "_")
        download_link = BASE_URL + att["_links"]["download"]

        local_path = os.path.join("attachments", fname)
        full_path = os.path.join(page_dir, "attachments", fname)

        if not os.path.exists(full_path):
            resp = session.get(download_link, stream=True)
            resp.raise_for_status()
            with open(full_path, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)

        mapping[att["_links"]["download"]] = local_path

    return mapping

def rewrite_links(html, pageid_to_path, attachments_map, current_path):
    soup = BeautifulSoup(html, "html.parser")

    # Переписываем ссылки на страницы
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"pageId=(\d+)", href)
        if m:
            pid = m.group(1)
            if pid in pageid_to_path:
                a["href"] = os.path.relpath(pageid_to_path[pid], os.path.dirname(current_path))

    # Переписываем ссылки на вложения
    for tag in soup.find_all(["img", "a"]):
        for attr in ["src", "href"]:
            if tag.has_attr(attr):
                val = tag[attr]
                for orig, new in attachments_map.items():
                    if val.endswith(orig):
                        tag[attr] = new

    return str(soup)

# ---------- ЛОКАЛЬНОЕ МЕНЮ СЛЕВА ДЛЯ КАЖДОЙ СТРАНИЦЫ ----------

def menu_build_tree(node, pages, pageid_to_path, current_page_id=None, relroot="export"):
    """Строит HTML-дерево (<details>/<summary>) с ссылками, относительными к relroot."""
    html = ""
    for pid, children in node.items():
        title = next(p["title"] for p in pages if p["id"] == pid)
        link = os.path.relpath(pageid_to_path[pid], relroot)
        if pid == current_page_id:
            link_html = f"<b>{title}</b>"
        else:
            link_html = f"<a href='{link}'>{title}</a>"

        if children:
            html += f"<details><summary>{link_html}</summary>{menu_build_tree(children, pages, pageid_to_path, current_page_id, relroot)}</details>"
        else:
            html += f"<li>{link_html}</li>"
    return html

def build_menu_html(pages, pageid_to_path, current_page_id=None, relroot="export"):
    """Возвращает HTML меню для вставки в каждую страницу."""
    tree = {}
    for p in pages:
        ancestors = [a["id"] for a in p.get("ancestors", [])]
        node = tree
        for aid in ancestors:
            node = node.setdefault(aid, {})
        node[p["id"]] = {}

    return f"""
    <div id="menu">
      <h2>Навигация</h2>
      {menu_build_tree(tree, pages, pageid_to_path, current_page_id, relroot)}
    </div>
    """

def save_page_html(session, page, pageid_to_path, pages):
    path = get_page_path(page)
    page_dir = os.path.dirname(path)
    os.makedirs(page_dir, exist_ok=True)

    # Скачиваем вложения
    attachments_map = download_attachments(session, page, page_dir)

    html_content = page["body"]["view"]["value"]

    current_path = path + ".html"

    # Переписываем ссылки
    html_content = rewrite_links(html_content, pageid_to_path, attachments_map, current_path)

    # Добавляем локальное меню слева (ссылки относительно текущей страницы)
    menu_html = build_menu_html(
        pages, pageid_to_path,
        current_page_id=page["id"],
        relroot=os.path.dirname(current_path)
    )

    # Оборачиваем в двухколоночный layout с меню слева
    wrapped = f"""
    <html>
      <head>
        <meta charset="utf-8">
        <title>{page['title']}</title>
        <style>
          body {{
            margin: 0;
            font-family: sans-serif;
            display: flex;
          }}
          #menu {{
            width: 400px;
            background: #f4f4f4;
            padding: 10px;
            height: 100vh;
            overflow-y: auto;
            border-right: 1px solid #ccc;
          }}
          #content {{
            flex-grow: 1;
            padding: 20px;
          }}
          a {{ text-decoration: none; color: #0645AD; }}
          details {{ margin-left: 10px; }}
        </style>
      </head>
      <body>
        {menu_html}
        <div id="content">
          {html_content}
        </div>
      </body>
    </html>
    """

    with open(current_path, "w", encoding="utf-8") as f:
        f.write(wrapped)

    return current_path

def generate_index(pages, pageid_to_path):
    tree = {}
    for p in pages:
        ancestors = [a["id"] for a in p.get("ancestors", [])]
        node = tree
        for aid in ancestors:
            node = node.setdefault(aid, {})
        node[p["id"]] = {}

    def build_tree(node):
        html = ""
        for pid, children in node.items():
            title = next(p["title"] for p in pages if p["id"] == pid)
            link = os.path.relpath(pageid_to_path[pid], "export")
            if children:
                html += f"<details><summary><a href='{link}'>{title}</a></summary>{build_tree(children)}</details>"
            else:
                html += f"<li><a href='{link}'>{title}</a></li>"
        return html

    html = """
    <html>
      <head>
        <meta charset="utf-8">
        <style>
          body { font-family: sans-serif; }
          details { margin-left: 15px; }
          a { text-decoration: none; color: #0645AD; }
        </style>
      </head>
      <body>
        <h1>Confluence Export Index</h1>
        {}
      </body>
    </html>
    """.format(build_tree(tree))

    with open("export/index.html", "w", encoding="utf-8") as f:
        f.write(html)

def main():
    session = get_session()
    pages = get_all_pages(session)

    print(f"Всего страниц (ограничено): {len(pages)}")

    pageid_to_path = {}
    for page in pages:
        file_path = get_page_path(page) + ".html"
        pageid_to_path[page["id"]] = file_path

    for page in pages:
        file_path = save_page_html(session, page, pageid_to_path, pages)
        print(f"Сохранил: {file_path}")

    generate_index(pages, pageid_to_path)
    print("Индекс сгенерирован: export/index.html")

if __name__ == "__main__":
    main()
