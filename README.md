python wiki_saver.py https://sberworks.ru/wiki 410061476 ~/PycharmProjects/wikiSaver

fetch_page() ---> теперь использует body.view вместо body.storage, чтобы получать уже отрендеренный HTML от Confluence.

rewrite_html_links() ---> упрощена: обрабатывает только обычные <img> и <a>, т.к. body.view уже содержит нормальный HTML (без ac:* тегов).

build_sidebar_html() ---> переписана: теперь генерирует корректную иерархию /'<ul><li><a>...</a></li></ul>/', с выделением текущей страницы через класс current.