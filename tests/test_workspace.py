from __future__ import annotations

import csv
import io
import json
import os
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

_temp = tempfile.TemporaryDirectory(prefix="commerce-tests-")
os.environ["COMMERCE_HOME"] = _temp.name
os.environ["COMMERCE_SEED_DEMO"] = "0"
# Tests must never use the operator's configured database.
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_temp.name) / "test.db").as_posix()

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
import server
from classification import CATEGORIES, model, predict
from ingestion import MAX_BYTES, normalize, parse_csv
from insights import customer_profiles, opportunities


def csv_data(rows=None, encoding="utf-8-sig"):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["订单编号", "平台", "客户编号", "商品名称", "实付金额", "数量", "下单日期"])
    writer.writerows(rows or [["T-1", "演示店", "CUS-1", "挂耳咖啡", "49", "1", "2025-09-01"]])
    return stream.getvalue().encode(encoding)


class IngestionTests(unittest.TestCase):
    def test_chinese_header_mapping(self):
        parsed = parse_csv(csv_data())
        self.assertEqual(parsed["rows"][0]["order_id"], "T-1")
        self.assertEqual(parsed["mapping"]["实付金额"], "amount")

    def test_gb18030(self):
        self.assertEqual(parse_csv(csv_data(encoding="gb18030"))["invalid"], 0)

    def test_negative_nan_infinite_and_zero_rejected(self):
        for value in ("-1", "nan", "inf", "0", "0.001"):
            with self.subTest(value=value):
                parsed = parse_csv(csv_data([["T", "店", "C", "咖啡", value, 1, "2025-01-01"]]))
                self.assertEqual(parsed["invalid"], 1)

    def test_fractional_and_zero_quantity_rejected(self):
        for value in ("1.2", "0", "NaN"):
            parsed = parse_csv(csv_data([["T", "店", "C", "咖啡", 10, value, "2025-01-01"]]))
            self.assertEqual(parsed["invalid"], 1)

    def test_future_date_rejected(self):
        parsed = parse_csv(csv_data([["T", "店", "C", "咖啡", 10, 1, "2099-01-01"]]))
        self.assertEqual(parsed["invalid"], 1)

    def test_required_values_and_length(self):
        for name, value in (("customer_id", " "), ("product_name", "x" * 241)):
            row = {"order_id":"A", "customer_id":"B", "product_name":"咖啡", "amount":1, "ordered_at":"2025-01-01"}
            row[name] = value
            with self.assertRaises(ValueError):
                normalize(row)

    def test_duplicate_header_rejected(self):
        with self.assertRaises(ValueError):
            parse_csv(b"order_id,order_id\nA,A\n")

    def test_duplicate_file_rows(self):
        row = ["T", "店", "C", "咖啡", 10, 1, "2025-01-01"]
        parsed = parse_csv(csv_data([row, row]))
        self.assertEqual(parsed["duplicates_in_file"], 1)
        self.assertEqual(len(parsed["rows"]), 1)

    def test_size_limit(self):
        with self.assertRaises(ValueError):
            parse_csv(b"x" * (MAX_BYTES + 1))


class ModelTests(unittest.TestCase):
    def test_model_card_and_disjoint_samples(self):
        card = model()[2]
        self.assertEqual(card["training_count"], 96)
        self.assertEqual(card["test_count"], 24)
        corpus = json.loads((Path(server.BASE_DIR) / "data/catalog.json").read_text(encoding="utf-8"))
        train = {s for category in corpus.values() for s in category["train"]}
        test = {s for category in corpus.values() for s in category["test"]}
        self.assertFalse(train & test)

    def test_real_classifier_recognizes_known_categories(self):
        for name, expected in (("快充数据线", "数码配件"), ("婴儿纸尿裤", "母婴用品"), ("保湿面霜", "美妆个护")):
            with self.subTest(name=name):
                self.assertEqual(predict(name)["category"], expected)

    def test_out_of_vocabulary_requires_review(self):
        result = predict("ZZZZXYZ999")
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["category"], "其他")


class InsightsTests(unittest.TestCase):
    def orders(self, days):
        return [{"order_id":str(n), "customer_id":"C", "category":"食品饮料", "platform":"店",
                 "product_name":"咖啡", "amount":100, "ordered_at":date(2025,1,1)+timedelta(days=day)} for n,day in enumerate(days)]

    def test_same_day_orders_do_not_create_cycle(self):
        self.assertEqual(opportunities(self.orders([0,0]), date(2025,3,1)), [])

    def test_median_cycle_and_same_day_dedup(self):
        result = opportunities(self.orders([0,0,30,60]), date(2025,4,1))[0]
        self.assertEqual(result["avg_cycle_days"], 30)
        self.assertEqual(result["purchase_days"], 3)

    def test_overdue_decreases_score(self):
        rows = self.orders([0,30])
        near = opportunities(rows, date(2025,3,2))[0]
        overdue = opportunities(rows, date(2025,7,1))[0]
        self.assertLess(overdue["priority_score"], near["priority_score"])
        self.assertEqual(overdue["status"], "需唤回评估")

    def test_customer_segmentation_uses_purchase_days(self):
        profiles = customer_profiles(self.orders([0,0,30]), date(2025,3,1))
        self.assertEqual(profiles[0]["frequency"], 2)
        self.assertEqual(profiles[0]["monetary"], 300)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(server.app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)
        server.engine.dispose()

    def setUp(self):
        with server.SessionLocal() as db:
            for table in (server.Review, server.ImportBatch, server.Order):
                db.execute(delete(table))
            db.commit()

    def post_import(self, raw=None, **data):
        return self.client.post("/api/import/csv", files={"file":("test.csv", raw or csv_data(), "text/csv")}, data={"authorized":"true", "source":"虚构测试", **data})

    def test_preview_does_not_write(self):
        result = self.client.post("/api/import/preview", files={"file":("test.csv",csv_data())})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["new_rows"], 1)
        self.assertEqual(self.client.get("/api/summary").json()["order_count"], 0)

    def test_authorization_required(self):
        result = self.client.post("/api/import/csv", files={"file":("test.csv",csv_data())})
        self.assertEqual(result.status_code, 422)

    def test_invalid_batch_is_atomic(self):
        raw = csv_data([["T1","店","C","咖啡",10,1,"2025-01-01"],["T2","店","C","咖啡","nan",1,"2025-01-02"]])
        self.assertEqual(self.post_import(raw).status_code, 422)
        self.assertEqual(self.client.get("/api/summary").json()["order_count"], 0)
        self.assertEqual(self.client.get("/api/import/batches").json(), [])

    def test_hash_mismatch(self):
        self.assertEqual(self.post_import(expected_sha256="0"*64).status_code, 409)

    def test_repeated_import_dedup_and_audit(self):
        self.assertEqual(self.post_import().json()["imported"], 1)
        result = self.post_import().json()
        self.assertEqual((result["imported"],result["skipped"]), (0,1))
        batches = self.client.get("/api/import/batches").json()
        self.assertEqual(len(batches), 2)
        self.assertEqual(len(batches[0]["sha256"]), 64)

    def test_file_internal_duplicates(self):
        row = ["T", "店", "C", "咖啡", 10, 1, "2025-01-01"]
        result = self.post_import(csv_data([row,row])).json()
        self.assertEqual((result["imported"],result["skipped"]), (1,1))

    def test_page_search_and_full_export(self):
        self.post_import(csv_data([[f"T-{n}","店","C","咖啡",10,1,"2025-01-01"] for n in range(25)]))
        page = self.client.get("/api/orders/page?page=2").json()
        self.assertEqual(len(page["items"]), 12)
        self.assertEqual(page["total"], 25)
        export = self.client.get("/api/export/orders.csv")
        self.assertEqual(len(list(csv.reader(io.StringIO(export.content.decode("utf-8-sig"))))), 26)
        self.assertEqual(self.client.get("/api/orders/page?q=T-24").json()["total"], 1)

    def test_review_preserves_original(self):
        self.post_import()
        before = self.client.get("/api/orders").json()[0]
        result = self.client.patch(f"/api/orders/{before['id']}/category",json={"category":"家居生活","note":"人工核对样例"})
        self.assertEqual(result.status_code, 200)
        after = self.client.get("/api/orders").json()[0]
        self.assertEqual(after["category"], "家居生活")
        self.assertEqual(after["original_category"], before["category"])
        self.assertFalse(after["needs_review"])
        with server.SessionLocal() as db:
            self.assertEqual(db.get(server.Order,before["id"]).category,before["category"])
            self.assertIsNotNone(db.scalar(select(server.Review)))

    def test_invalid_review_rejected(self):
        self.assertEqual(self.client.patch("/api/orders/999/category",json={"category":"随便","note":"x"}).status_code,422)
        self.assertEqual(self.client.patch("/api/orders/999/category",json={"category":"其他","note":"x"}).status_code,404)

    def test_report_escapes_and_export_formula(self):
        self.post_import(csv_data([["=1+1","店","<script>alert(1)</script>","咖啡",10,1,"2025-01-01"],["T2","店","<script>alert(1)</script>","咖啡",10,1,"2025-02-01"]]))
        report = self.client.get("/api/report").text
        self.assertNotIn("<script>alert",report)
        self.assertIn("&lt;script&gt;",report)
        self.assertIn("'=1+1",self.client.get("/api/export/orders.csv").text)

    def test_trend_window_sums_and_zero_fill(self):
        today = date.today()
        rows = [["TODAY","店","C","咖啡",12,1,today.isoformat()],
                ["WEEK","店","C","咖啡",20,1,(today-timedelta(days=6)).isoformat()],
                ["MONTH","店","C","咖啡",30,1,(today-timedelta(days=29)).isoformat()],
                ["OLD","店","C","咖啡",40,1,(today-timedelta(days=30)).isoformat()]]
        self.post_import(csv_data(rows))
        week = self.client.get("/api/trends?days=7").json()
        month = self.client.get("/api/trends?days=30").json()
        self.assertEqual((week["total"], week["orders"], len(week["series"])), (32,2,7))
        self.assertEqual(month["total"], self.client.get("/api/summary").json()["revenue_30d"])
        self.assertEqual(month["total"], 62)
        self.assertEqual(month["series"][-1]["date"], today.isoformat())
        self.assertTrue(any(point["amount"] == 0 for point in month["series"]))

    def test_trend_range_validation(self):
        for days in (0,6,91):
            self.assertEqual(self.client.get(f"/api/trends?days={days}").status_code,422)

    def test_endpoints_and_input_validation(self):
        for path in ("/", "/api/health", "/api/model", "/api/customers", "/api/recommendations"):
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.post("/api/classify",json={"product_name":" "}).status_code,422)
        self.assertEqual(self.client.post("/api/classify",json={"product_name":"耳机"}).status_code,200)
        self.assertEqual(self.client.get("/api/orders/page?page=0").status_code,422)


if __name__ == "__main__":
    unittest.main()
