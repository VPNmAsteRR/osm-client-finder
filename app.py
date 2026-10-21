#!/usr/bin/env python3
"""Local browser GUI for searching OpenStreetMap business listings."""

from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
USER_AGENT = "LocalOSMClientFinder/1.0 (desktop prospecting tool)"
MAX_RESULTS = 500
MAX_WIKIDATA_ENTITIES = 50
CATEGORY_TAGS = {
    "all_shops": ("shop", None),
    "flowers": ("shop", "florist"),
    "groceries": ("shop", "supermarket|convenience|greengrocer|deli"),
    "clothes": ("shop", "clothes|fashion"),
    "shoes": ("shop", "shoes"),
    "electronics": ("shop", "electronics|mobile_phone|computer"),
    "cosmetics": ("shop", "beauty|cosmetics|perfumery"),
    "furniture": ("shop", "furniture|interior_decoration"),
    "toys": ("shop", "toys"),
    "pets": ("shop", "pet"),
    "bakery": ("shop", "bakery"),
    "pharmacy": ("amenity", "pharmacy"),
    "cafe": ("amenity", "cafe"),
    "restaurant": ("amenity", "restaurant"),
    "beauty_salon": ("shop", "hairdresser|beauty"),
    "optician": ("shop", "optician"),
    "gifts": ("shop", "gift|florist|stationery"),
    "custom_name": ("name", None),
}
GEOCODE_LOCK = threading.Lock()
LAST_GEOCODE_AT = 0.0
GEOCODE_CACHE: dict[str, tuple[float, float]] = {}
WIKIDATA_CACHE: dict[str, dict] = {}
WIKIDATA_LOCK = threading.Lock()


def geocode_city(city: str) -> tuple[float, float]:
    global LAST_GEOCODE_AT
    cache_key = city.casefold()
    if cache_key in GEOCODE_CACHE:
        return GEOCODE_CACHE[cache_key]

    with GEOCODE_LOCK:
        if cache_key in GEOCODE_CACHE:
            return GEOCODE_CACHE[cache_key]
        wait = 1.05 - (time.monotonic() - LAST_GEOCODE_AT)
        if wait > 0:
            time.sleep(wait)
        params = urllib.parse.urlencode({"q": city, "format": "jsonv2", "limit": 1})
        request = urllib.request.Request(
            f"{NOMINATIM_URL}?{params}",
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ru"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                results = json.loads(response.read().decode("utf-8"))
        finally:
            LAST_GEOCODE_AT = time.monotonic()
        if not results:
            raise ValueError(f"Город «{city}» не найден в OpenStreetMap.")
        center = (float(results[0]["lat"]), float(results[0]["lon"]))
        GEOCODE_CACHE[cache_key] = center
        return center


def get_tag(tags: dict, *keys: str) -> str:
    for key in keys:
        value = tags.get(key)
        if value:
            return str(value).strip()
    return ""


def find_telegram_reference(tags: dict) -> str:
    for key, value in tags.items():
        if "telegram" not in key.casefold() or not value:
            continue
        candidate = str(value).strip().split()[0].strip(".,;()[]{}<>")
        if candidate.startswith("@"):
            return f"https://t.me/{candidate[1:]}"
        if re.fullmatch(r"[A-Za-z0-9_]{5,32}", candidate):
            return f"https://t.me/{candidate}"
        if candidate.startswith("t.me/") or candidate.startswith("telegram.me/"):
            return f"https://{candidate}"
        if candidate.startswith(("https://t.me/", "http://t.me/", "https://telegram.me/", "http://telegram.me/")):
            return candidate
    return ""


def is_public_bot_link(url: str) -> bool:
    match = re.search(r"(?:t\.me|telegram\.me)/([^/?#]+)", url, re.IGNORECASE)
    if not match:
        return False
    username = match.group(1).lstrip("@")
    if username.casefold() in {"share", "joinchat", "s", "addstickers", "proxy", "iv"}:
        return False
    return username.casefold().endswith("bot")


def normalize_element(element: dict) -> dict:
    tags = element.get("tags") or {}
    name = get_tag(tags, "name", "brand", "operator") or "Без названия"
    street = " ".join(filter(None, (tags.get("addr:street"), tags.get("addr:housenumber"))))
    address = ", ".join(filter(None, (
        street,
        tags.get("addr:city") or tags.get("addr:suburb"),
        tags.get("addr:postcode"),
    )))
    category = ", ".join(
        f"{key}: {tags[key]}"
        for key in ("shop", "amenity", "craft", "office", "tourism", "leisure")
        if tags.get(key) and tags[key] != "yes"
    ) or "Организация"
    telegram_url = find_telegram_reference(tags)
    bot_found = is_public_bot_link(telegram_url)
    telegram_status = (
        "Публичный бот найден" if bot_found else
        "Telegram указан, бот не подтверждён" if telegram_url else
        "Публичный Telegram-бот не найден"
    )

    latitude = element.get("lat") or (element.get("center") or {}).get("lat")
    longitude = element.get("lon") or (element.get("center") or {}).get("lon")
    osm_type = {"node": "node", "way": "way", "relation": "relation"}.get(element.get("type"), "node")
    osm_id = element.get("id", "")
    maps_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
    if latitude is not None and longitude is not None:
        maps_url = f"https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}#map=18/{latitude}/{longitude}"

    return {
        "id": f"{osm_type}/{osm_id}",
        "name": name,
        "category": category,
        "address": address,
        "phone": get_tag(tags, "contact:phone", "phone", "contact:mobile", "mobile"),
        "website": get_tag(tags, "contact:website", "website", "url"),
        "email": get_tag(tags, "contact:email", "email"),
        "opening_hours": get_tag(tags, "opening_hours", "opening_hours:covid19"),
        "description": get_tag(tags, "description", "description:ru", "note"),
        "brand": get_tag(tags, "brand", "operator"),
        "socials": {
            label: get_tag(tags, f"contact:{key}", key)
            for label, key in (
                ("Telegram", "telegram"), ("ВКонтакте", "vk"), ("Instagram", "instagram"),
                ("Facebook", "facebook"), ("WhatsApp", "whatsapp"), ("YouTube", "youtube"),
            )
            if get_tag(tags, f"contact:{key}", key)
        },
        "telegram_url": telegram_url,
        "bot_found": bot_found,
        "telegram_status": telegram_status,
        "maps_url": maps_url,
        "latitude": latitude,
        "longitude": longitude,
        "wikidata": {},
        "all_tags": tags,
    }


def make_overpass_query(category: str, latitude: float, longitude: float, radius: int, custom_name: str = "") -> str:
    if category not in CATEGORY_TAGS:
        raise ValueError("Выберите категорию из списка.")
    key, value = CATEGORY_TAGS[category]
    if category == "custom_name":
        if not custom_name.strip():
            raise ValueError("Введите название компании для поиска.")
        value = re.escape(custom_name.strip())
        selector = f'[{json.dumps(key)}~{json.dumps(value)},i]'
    elif value is None:
        selector = f'[{json.dumps(key)}]'
    elif "|" in value:
        selector = f'[{json.dumps(key)}~{json.dumps("^(" + value + ")$")}]'
    else:
        selector = f'[{json.dumps(key)}={json.dumps(value)}]'
    return (
        f"[out:json][timeout:60];"
        f"nwr(around:{radius},{latitude},{longitude}){selector};"
        f"out center tags {MAX_RESULTS};"
    )


def claim_values(entity: dict, property_id: str) -> list[str]:
    values = []
    for claim in entity.get("claims", {}).get(property_id, []):
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, dict):
            value = value.get("text") or value.get("amount") or value.get("time") or value.get("id")
        if value is not None:
            values.append(str(value))
    return values


def normalize_wikidata_entity(entity: dict) -> dict:
    labels = entity.get("labels", {})
    descriptions = entity.get("descriptions", {})
    sitelinks = entity.get("sitelinks", {})
    socials = {
        label: value
        for label, property_id in (
            ("X / Twitter", "P2002"), ("Instagram", "P2003"),
            ("Facebook", "P2013"), ("YouTube", "P2397"),
        )
        if (value := ", ".join(claim_values(entity, property_id)))
    }
    return {
        "id": entity.get("id", ""),
        "label": (labels.get("ru") or labels.get("en") or {}).get("value", ""),
        "description": (descriptions.get("ru") or descriptions.get("en") or {}).get("value", ""),
        "official_name": ", ".join(claim_values(entity, "P1448")),
        "website": ", ".join(claim_values(entity, "P856")),
        "phone": ", ".join(claim_values(entity, "P1329")),
        "email": ", ".join(claim_values(entity, "P968")),
        "founded": ", ".join(claim_values(entity, "P571")),
        "logo": ", ".join(claim_values(entity, "P154")),
        "image": ", ".join(claim_values(entity, "P18")),
        "industry": ", ".join(claim_values(entity, "P452")),
        "country": ", ".join(claim_values(entity, "P17")),
        "socials": socials,
        "wikipedia_ru": (sitelinks.get("ruwiki") or {}).get("url", ""),
        "wikipedia_en": (sitelinks.get("enwiki") or {}).get("url", ""),
        "entity_url": f"https://www.wikidata.org/wiki/{entity.get('id', '')}",
    }


def enrich_from_wikidata(results: list[dict]) -> tuple[int, str]:
    qids = list(dict.fromkeys(
        item["all_tags"].get("wikidata", "").strip()
        for item in results
        if re.fullmatch(r"Q[1-9][0-9]*", item["all_tags"].get("wikidata", "").strip())
    ))
    if not qids:
        return 0, "Wikidata: у найденных объектов нет связанных записей."

    selected = qids[:MAX_WIKIDATA_ENTITIES]
    with WIKIDATA_LOCK:
        missing = [qid for qid in selected if qid not in WIKIDATA_CACHE]
        if missing:
            params = urllib.parse.urlencode({
                "action": "wbgetentities",
                "ids": "|".join(missing),
                "props": "labels|descriptions|claims|sitelinks/urls",
                "languages": "ru|en",
                "sitefilter": "ruwiki|enwiki",
                "format": "json",
            })
            request = urllib.request.Request(
                f"{WIKIDATA_API_URL}?{params}",
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    entities = json.loads(response.read().decode("utf-8")).get("entities", {})
                for qid in missing:
                    entity = entities.get(qid, {})
                    if entity.get("id"):
                        WIKIDATA_CACHE[qid] = normalize_wikidata_entity(entity)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
                return 0, "Wikidata временно недоступна; показаны данные OpenStreetMap."

    enriched = 0
    for item in results:
        qid = item["all_tags"].get("wikidata", "").strip()
        details = WIKIDATA_CACHE.get(qid)
        if details:
            item["wikidata"] = details
            enriched += 1
    note = f"Wikidata: дополнено {enriched} карточек."
    if len(qids) > MAX_WIKIDATA_ENTITIES:
        note += f" Проверены первые {MAX_WIKIDATA_ENTITIES} из {len(qids)} ссылок."
    return enriched, note


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run_app() -> None:
    access_token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/" or urllib.parse.parse_qs(parsed.query).get("access") != [access_token]:
                self.send_error(404)
                return
            try:
                page = (APP_DIR / "index.html").read_text(encoding="utf-8")
            except OSError:
                self.send_error(500, "Не удалось прочитать index.html")
                return
            page = page.replace("__ACCESS_TOKEN__", json.dumps(access_token))
            body = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.headers.get("X-Local-Token") != access_token:
                self.send_json(403, {"error": "Недействительный локальный токен."})
                return
            if urllib.parse.urlparse(self.path).path == "/api/stop":
                self.send_json(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if urllib.parse.urlparse(self.path).path != "/api/search":
                self.send_json(404, {"error": "Маршрут не найден."})
                return
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 32_000)
                request_data = json.loads(self.rfile.read(length))
                category = str(request_data.get("category", "")).strip()
                custom_name = str(request_data.get("custom_name", "")).strip()
                city = str(request_data.get("city", "")).strip()
                radius = int(request_data.get("radius", 5000))
                if category not in CATEGORY_TAGS or not city:
                    self.send_json(400, {"error": "Выберите категорию и укажите город."})
                    return
                if len(custom_name) > 100 or len(city) > 200:
                    self.send_json(400, {"error": "Слишком длинное значение в одном из полей."})
                    return
                if radius not in {2000, 5000, 10000}:
                    self.send_json(400, {"error": "Выберите радиус 2, 5 или 10 км."})
                    return

                latitude, longitude = geocode_city(city)
                overpass_query = make_overpass_query(category, latitude, longitude, radius, custom_name)
                params = urllib.parse.urlencode({"data": overpass_query}).encode("ascii")
                request = urllib.request.Request(
                    OVERPASS_URL,
                    data=params,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                    },
                )
                with urllib.request.urlopen(request, timeout=60) as response:
                    data = json.loads(response.read().decode("utf-8"))
                results = [
                    normalize_element(element)
                    for element in data.get("elements", [])
                    if element.get("tags")
                ]
                _, wikidata_status = enrich_from_wikidata(results)
                results.sort(key=lambda item: item["bot_found"])
                self.send_json(200, {
                    "results": results,
                    "count": len(results),
                    "radius": radius,
                    "city": city,
                    "max_results": MAX_RESULTS,
                    "limited": len(data.get("elements", [])) >= MAX_RESULTS,
                    "wikidata_status": wikidata_status,
                })
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:1000]
                message = "Сервис временно перегружен. Попробуйте немного позже."
                if error.code not in {429, 502, 503, 504}:
                    message = detail or str(error)
                self.send_json(error.code, {"error": f"Ошибка OpenStreetMap: {message}"})
            except urllib.error.URLError as error:
                self.send_json(502, {"error": f"Не удалось подключиться к сервису OpenStreetMap: {error.reason}"})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.send_json(400, {"error": f"Не удалось выполнить поиск: {error}"})
            except Exception as error:
                self.send_json(500, {"error": f"Ошибка приложения: {error}"})

    server = AppServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address
    url = f"http://{host}:{port}/?access={access_token}"
    xdg_open = shutil.which("xdg-open")
    if xdg_open:
        threading.Timer(
            0.5,
            lambda: subprocess.Popen(
                [xdg_open, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            ),
        ).start()
    else:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"Окно поиска открывается в браузере: {url}")
    print("Сервер доступен только на этом компьютере. Для остановки закройте окно приложения.")
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        time.sleep(0.1)
        print("Приложение закрыто.")


if __name__ == "__main__":
    run_app()