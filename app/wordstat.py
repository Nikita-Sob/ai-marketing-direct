"""Wordstat через Yandex Search API (REST v2).

Проверено живым запросом 15.11.2026:
POST https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests
body: {"phrase", "numPhrases", "regions", "devices", "folderId"}
auth: "Api-key <YANDEX_SEARCH_API_KEY>" из env.

Ключи: YANDEX_SEARCH_API_KEY, YANDEX_FOLDER_ID (в /root/.hermes/.env).
"""

import os
import time

import requests

ENDPOINT = "https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests"
REGION_RUSSIA = "225"
DEVICES_ALL = "DEVICE_ALL"


class WordstatError(Exception):
    pass


def available() -> bool:
    key, folder = _credentials()
    return bool(key and folder)


def _credentials():
    key = os.environ.get("YANDEX_SEARCH_API_KEY")
    folder = os.environ.get("YANDEX_FOLDER_ID")
    return key, folder


def get_top(phrase: str, region_id: str = REGION_RUSSIA, num_phrases: int = 50,
            timeout: int = 30, retries: int = 3) -> dict:
    """Топ запросов по фразе за 30 дней.

    Возвращает {"totalCount": int, "results": [(phrase, count)],
                 "associations": [(phrase, count)]}.
    """
    key, folder = _credentials()
    if not (key and folder):
        raise WordstatError("нет YANDEX_SEARCH_API_KEY / YANDEX_FOLDER_ID в env")

    body = {
        "phrase": phrase,
        "numPhrases": num_phrases,
        "regions": [region_id],
        "devices": [DEVICES_ALL],
        "folderId": folder,
    }
    headers = {"Authorization": "Api-key %s" % key}
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.post(ENDPOINT, headers=headers, json=body, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                return {
                    "totalCount": int(data.get("totalCount", 0)),
                    "results": [(x.get("phrase", ""), int(x.get("count", 0)))
                                for x in data.get("results", [])],
                    "associations": [(x.get("phrase", ""), int(x.get("count", 0)))
                                     for x in data.get("associations", [])],
                }
            last_err = WordstatError("HTTP %s: %s" % (r.status_code, r.text[:200]))
            if r.status_code in (400, 401, 403):
                break
        except requests.RequestException as e:
            last_err = WordstatError(str(e)[:200])
        time.sleep(1.5 * (attempt + 1))
    raise last_err or WordstatError("wordstat: неизвестная ошибка")
