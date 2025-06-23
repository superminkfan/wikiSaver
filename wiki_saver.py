# confluence_export_html.py
import argparse
import os
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#python wiki_saver.py https://confluence.company.com 123456 ~/wiki-export
def parse_args():
    parser = argparse.ArgumentParser(description="Экспорт Confluence в HTML с вложениями и деревом навигации")
    parser.add_argument("base_url", help="Базовый URL Confluence, например https://your-domain.atlassian.net/wiki")
    parser.add_argument("root_page_id", help="ID корневой страницы")
    parser.add_argument("output_dir", help="Директория для сохранения")
    return parser.parse_args()

def sanitize_filename(name):
    # Ограничение длины имени файла (например, до 100 символов)
    max_length = 100
    safe_name = "".join(c if c.isalnum() or c in " .-_()" else "_" for c in name).strip()
    if len(safe_name) > max_length:
        base, ext = os.path.splitext(safe_name)
        safe_name = base[:max_length - len(ext)] + ext
    return safe_name

def retry_get(session, url, max_retries=5, delay=1):
    for attempt in range(max_retries):
        r = session.get(url)
        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", delay))
            print(f"⚠️ 429 Too Many Requests. Waiting {retry_after} seconds...")
            time.sleep(retry_after)
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r
    raise Exception("Failed after retries")

def fetch_page(session, base_url, page_id):
    url = f"{base_url}/rest/api/content/{page_id}?expand=body.storage,title"
    r = retry_get(session, url)
    return r.json() if r else None

def fetch_children(session, base_url, page_id):
    url = f"{base_url}/rest/api/content/{page_id}/child/page?limit=100"
    r = retry_get(session, url)
    return r.json().get("results", []) if r else []

def fetch_attachments(session, base_url, page_id):
    url = f"{base_url}/rest/api/content/{page_id}/child/attachment?limit=1000"
    r = retry_get(session, url)
    return r.json().get("results", []) if r else []

def download_attachment(session, url, save_path):
    try:
        r = retry_get(session, url)
        if not r:
            print(f"⚠️ Attachment not found (404): {url}")
            return
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)
    except requests.RequestException as e:
        print(f"⚠️ Failed to download {url}: {e}")

def rewrite_html_links(html, attachments_dir, attachments):
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src")
        if src:
            filename = os.path.basename(urlparse(src).path)
            img["src"] = f"{attachments_dir}/{filename}"
    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        for att in attachments:
            download_path = att["_links"]["download"]
            if download_path in href or sanitize_filename(att["title"]) in href:
                filename = sanitize_filename(att["title"])
                ext = os.path.splitext(filename)[1].lower()
                local_path = f"{attachments_dir}/{filename}"
                if ext in [".png", ".jpg", ".jpeg", ".gif", ".svg"]:
                    img_tag = soup.new_tag("img", src=local_path)
                    a.replace_with(img_tag)
                else:
                    a["href"] = local_path
                break
    for macro in soup.find_all("ac:structured-macro", {"ac:name": "drawio"}):
        filename = None
        att = macro.find("ri:attachment")
        if att and att.has_attr("ri:filename"):
            filename = att["ri:filename"]
        elif macro.find("ac:parameter", {"ac:name": "filename"}):
            filename = macro.find("ac:parameter", {"ac:name": "filename"}).text.strip()
        if filename:
            img_tag = soup.new_tag("img", src=f"{attachments_dir}/{sanitize_filename(filename)}")
            macro.replace_with(img_tag)
        else:
            macro.replace_with("<!-- draw.io diagram not found -->")

    for image_macro in soup.find_all("ac:image"):
        ri_attachment = image_macro.find("ri:attachment")
        if ri_attachment and ri_attachment.has_attr("ri:filename"):
            filename = sanitize_filename(ri_attachment["ri:filename"])
            img_tag = soup.new_tag("img", src=f"{attachments_dir}/{filename}")

            # Обработка атрибутов ac:image (например: ac:height, ac:width, ac:alt, ac:align)
            if image_macro.has_attr("ac:height"):
                img_tag["height"] = image_macro["ac:height"]
            if image_macro.has_attr("ac:width"):
                img_tag["width"] = image_macro["ac:width"]
            if image_macro.has_attr("ac:alt"):
                img_tag["alt"] = image_macro["ac:alt"]

            if image_macro.has_attr("ac:align"):
                align_class = f"align-{image_macro['ac:align'].lower()}"
                wrapper = soup.new_tag("div", **{"class": align_class})
                wrapper.append(img_tag)
                image_macro.replace_with(wrapper)
            else:
                image_macro.replace_with(img_tag)

    return str(soup)

def build_sidebar_html(tree, current_path):
    def recurse(node, current_path, level=0):
        rel_path = node["path"]
        title = node["title"]
        href = os.path.relpath(rel_path, os.path.dirname(current_path))
        is_current = (rel_path == current_path)
        item = f'<span class="current">{title}</span>' if is_current else f'<a href="{href}">{title}</a>'
        children_html = "\n".join(recurse(child, current_path, level + 1) for child in node.get("children", []))
        return f"<div>{item}</div>\n{children_html}"
    return recurse(tree, current_path)

def build_html_page(title, content_html, current_node, output_dir, full_tree_root):
    sidebar = build_sidebar_html(full_tree_root, current_node["path"])
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset=\"UTF-8\">
    <title>{title}</title>
    <style>
        body {{ display: flex; font-family: sans-serif; }}
        nav {{ width: 250px; background: #f0f0f0; padding: 1em; height: 100vh; overflow-y: auto; box-shadow: 2px 0 5px rgba(0,0,0,0.1); }}
        main {{ flex-grow: 1; padding: 2em; }}
        .current {{ font-weight: bold; }}
        a {{ text-decoration: none; color: #0366d6; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 1em; }}
        table, th, td {{ border: 1px solid #ccc; }}
        th, td {{ padding: 8px; text-align: left; }}
        th {{ background-color: #f8f8f8; }}
    </style>
</head>
<body>
    <nav>{sidebar}</nav>
    <main><h1>{title}</h1>{content_html}</main>
</body>
</html>"""

def build_tree(session, base_url, page_id, output_dir, rel_path=""):
    page = fetch_page(session, base_url, page_id)
    if not page:
        return None
    title = page["title"]
    sanitized = sanitize_filename(title)
    page_rel_path = os.path.join(rel_path, sanitized)
    children = fetch_children(session, base_url, page_id)
    child_nodes = [
        build_tree(session, base_url, child["id"], output_dir, rel_path=page_rel_path)
        for child in children
    ]
    return {
        "id": page_id,
        "title": title,
        "path": os.path.join(page_rel_path, "index.html"),
        "children": [c for c in child_nodes if c]
    }

def render_tree(session, base_url, node, output_dir, full_tree_root):
    page = fetch_page(session, base_url, node["id"])
    if not page:
        return
    title = page["title"]
    page_dir = os.path.join(output_dir, os.path.dirname(node["path"]))
    page_dir = page_dir.replace(' ', '')
    if len(page_dir.encode('utf-8')) > 200:
        print(page_dir)
    os.makedirs(page_dir, exist_ok=True)
    attachments = fetch_attachments(session, base_url, node["id"])
    attachments_dir = os.path.join(page_dir, "attachments")
    os.makedirs(attachments_dir, exist_ok=True)
    for att in attachments:
        download_link = f"{base_url}{att["_links"]["download"]}"
        filename = sanitize_filename(att["title"])
        save_path = os.path.join(attachments_dir, filename)
        download_attachment(session, download_link, save_path)
    html = page["body"]["storage"]["value"]
    fixed_html = rewrite_html_links(html, "attachments", attachments)
    full_html = build_html_page(title, fixed_html, node, output_dir, full_tree_root)
    with open(os.path.join(page_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(full_html)
    for child in node.get("children", []):
        render_tree(session, base_url, child, output_dir, full_tree_root)

def main():
    args = parse_args()
    session = get_session()
    session.headers.update({"Accept": "application/json"})

    tree = build_tree(session, args.base_url, args.root_page_id, args.output_dir)
    render_tree(session, args.base_url, tree, args.output_dir, full_tree_root=tree)

def get_session():
    s = requests.Session()
    s.auth = (os.environ['UNAME'], os.environ['PASSWD'])
    s.verify = False
    s.cert = os.environ['CERT_PATH']

    return s

if __name__ == "__main__":
    main()