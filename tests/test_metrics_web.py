"""Тесты метрик качества (STP, F1, экономика) и веб-API (TestClient, без сети)."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import metrics, web


class TestPhraseMatch(unittest.TestCase):
    def test_stems_strip_operators(self):
        s = metrics.phrase_stems("рации +для охоты -рыбалки")
        self.assertIn("раци", s)
        self.assertIn("охот", s)
        self.assertNotIn("для", s)          # стоп-слово исключено
        self.assertIn("рыба", s)            # минус-слово остаётся в стемах

    def test_match_forms(self):
        self.assertTrue(metrics.phrases_match("рации для охоты", "рация +для охоты"))
        self.assertTrue(metrics.phrases_match("варочная панель", "варочные панели"))
        self.assertFalse(metrics.phrases_match("рации для охоты", "антенны для авто"))

    def test_f1_math(self):
        gen = ["рации для охоты", "рации для рыбалки", "антенны"]
        eta = ["рация для охоты", "рация для рыбалки"]
        r = metrics.compare_semantics(gen, eta)
        # покрыты обе эталонные, наша третья фраза лишняя
        self.assertEqual(r["matched"], 2)
        self.assertAlmostEqual(r["precision"], 2 / 3, places=3)
        self.assertEqual(r["recall"], 1.0)
        self.assertAlmostEqual(r["f1"], 2 * (2 / 3) * 1 / (2 / 3 + 1), places=3)

    def test_etalon_phrases_from_template(self):
        ph = metrics.etalon_phrases()
        self.assertGreater(len(ph), 10)
        self.assertNotIn("---autotargeting", ph)
        self.assertTrue(all(p.strip() for p in ph))

    def test_demand_coverage_weighted(self):
        gen = ["рации для охоты"]
        eta = ["рация для охоты", "рации для рыбалки"]
        cov = metrics.demand_coverage(gen, eta, {"рация для охоты": 900,
                                                 "рации для рыбалки": 100})
        self.assertEqual(cov["coverage"], 0.9)
        self.assertEqual(cov["covered_freq"], 900)
        self.assertEqual(cov["total_freq"], 1000)

    def test_economic_effect(self):
        cov = {"coverage": 0.9, "covered_freq": 1000, "total_freq": 1100}
        e = metrics.economic_effect(cov)
        # медиа: 1000*0.85*0.07*60*1.2 = 4284
        self.assertEqual(e["media_value_rub"], 4284)
        # экономия труда: (2.5-0.15)*750 = 1762
        self.assertEqual(e["labor_saving_per_campaign_rub"], 1762)
        self.assertGreater(e["roi_percent"], 0)
        self.assertIn("fte_now", e)


class TestSTP(unittest.TestCase):
    def test_stp_from_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "runs.jsonl"
            recs = [
                {"ok": True, "err": 0, "warn": 1},
                {"ok": True, "err": 0, "warn": 0},
                {"ok": False, "err": 2, "warn": 0},
                {"ok": True, "err": 0, "warn": 0, "manual_fixes": 1},
            ]
            log.write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
            stp = metrics.stp_from_log(str(log))
            self.assertEqual(stp["total"], 4)
            self.assertEqual(stp["clean"], 2)
            self.assertEqual(stp["stp"], 0.5)

    def test_stp_empty(self):
        self.assertIsNone(metrics.stp_from_log("/nonexistent/path.jsonl")["stp"])


class TestWeb(unittest.TestCase):
    def setUp(self):
        # тесты ходят без ключа доступа: временно убираем WEB_TOKEN из env
        self._saved_token = os.environ.pop("WEB_TOKEN", None)
        self.client = TestClient(web.app)
        web.JOBS.clear()

    def tearDown(self):
        if self._saved_token is not None:
            os.environ["WEB_TOKEN"] = self._saved_token

    def test_index_page(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Генератор маркетинга", r.text)

    def test_run_rejects_bad_url(self):
        r = self.client.post("/api/run", json={"mode": "campaign", "url": "не сайт"})
        self.assertEqual(r.status_code, 400)

    def test_job_not_found(self):
        r = self.client.get("/api/job/abc")
        self.assertEqual(r.status_code, 404)

    def test_run_and_poll(self):
        # джоба должна запуститься и завершиться (duplex-shop без Wordstat)
        r = self.client.post("/api/run", json={"mode": "forecast",
                                               "url": "https://example.com"})
        self.assertEqual(r.status_code, 200)
        job_id = r.json()["job_id"]
        # ждём завершения воркера
        import time
        for _ in range(120):
            with web.JOBS_LOCK:
                st = web.JOBS.get(job_id, {}).get("status")
            if st in ("done", "error"):
                break
            time.sleep(0.5)
        with web.JOBS_LOCK:
            st = web.JOBS.get(job_id, {})
        self.assertIn(st["status"], ("done", "error"))
        if st["status"] == "done":
            self.assertTrue(st["files"] or st["data"])
            fl = self.client.get("/api/files/%s" % job_id).json()
            self.assertTrue(fl["files"])
            data = self.client.get("/api/job/%s" % job_id).json()
            self.assertEqual(data["status"], "done")
            self.assertEqual(data["data"]["title"], "Медиапрогноз готов")
            self.assertTrue(data["data"]["metrics"])
            self.assertIn("Бюджет", data["data"]["metrics"][2]["label"])

    def test_run_campaign_data_shape(self):
        r = self.client.post("/api/run", json={"mode": "campaign",
                                               "url": "https://example.com"})
        job_id = r.json()["job_id"]
        import time
        for _ in range(120):
            with web.JOBS_LOCK:
                st = web.JOBS.get(job_id, {}).get("status")
            if st in ("done", "error"):
                break
            time.sleep(0.5)
        with web.JOBS_LOCK:
            st = dict(web.JOBS.get(job_id, {}))
        if st["status"] == "done":
            self.assertEqual(st["data"]["title"], "Кампания готова")
            self.assertEqual([m["label"] for m in st["data"]["metrics"][:3]],
                             ["Групп", "Фраз", "Ошибок"])
            self.assertTrue(st["data"]["table"]["head"])


if __name__ == "__main__":
    unittest.main()
