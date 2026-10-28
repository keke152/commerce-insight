"""Local order workspace with authorized CSV import, offline ML, and review audit."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import random
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from classification import CATEGORIES, classify, model, predict
from ingestion import MAX_BYTES, parse_csv
from insights import customer_profiles, opportunities

VERSION = "1.1.0"
BASE_DIR = Path(__file__).resolve().parent
HOME = Path(os.getenv("COMMERCE_HOME", str(BASE_DIR / "runtime"))).resolve()
HOME.mkdir(parents=True, exist_ok=True)
legacy = BASE_DIR / "demo.db"
default_db = legacy if legacy.exists() and "COMMERCE_HOME" not in os.environ else HOME / "commerce.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{default_db.as_posix()}")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("platform", "order_id", name="uq_platform_order"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(80), index=True)
    platform: Mapped[str] = mapped_column(String(40), index=True)
    customer_id: Mapped[str] = mapped_column(String(80), index=True)
    product_name: Mapped[str] = mapped_column(String(240))
    amount: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    ordered_at: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(60), default="其他")
    category_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    category_reason: Mapped[str] = mapped_column(String(240), default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Review(Base):
    __tablename__ = "category_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_pk: Mapped[int] = mapped_column(Integer, index=True)
    category: Mapped[str] = mapped_column(String(60))
    note: Mapped[str] = mapped_column(String(240))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64))
    imported: Mapped[int] = mapped_column(Integer)
    skipped: Mapped[int] = mapped_column(Integer)
    authorized: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


def seed_demo():
    Base.metadata.create_all(engine)
    if os.getenv("COMMERCE_SEED_DEMO", "1") != "1":
        return
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Order)):
            return
        rng = random.Random(20261022)
        products = [("云南挂耳咖啡礼盒", 39), ("每日坚果混合装", 49), ("低温纯牛奶", 59),
                    ("桂花乌龙茶", 39), ("神经酰胺保湿面霜", 89), ("氨基酸洁面乳", 69),
                    ("轻薄防晒乳", 79), ("厨房收纳盒", 45), ("纯棉毛巾套装", 35),
                    ("无线蓝牙耳机", 199), ("快充数据线", 29), ("婴儿棉柔湿巾", 35),
                    ("成长裤纸尿裤", 99), ("婴儿辅食米粉", 49), ("未知神秘礼物XYZ", 59)]
        for n in range(1, 241):
            name, price = rng.choice(products)
            quantity = rng.choice([1, 1, 1, 2, 3])
            cat, score, reason = classify(name)
            db.add(Order(order_id=f"DEMO-{n:05}", platform=rng.choice(["天猫授权店", "京东自营店", "抖音小店"]),
                         customer_id=f"CUS-{rng.randint(1, 60):03}", product_name=name,
                         amount=price * quantity, quantity=quantity,
                         ordered_at=date.today() - timedelta(days=rng.randint(0, 170)),
                         category=cat, category_confidence=score, category_reason=reason))
        db.commit()


@asynccontextmanager
async def lifespan(_app):
    seed_demo()
    yield


app = FastAPI(title="Commerce Insight · 知购", version=VERSION, lifespan=lifespan,
              description="本地订单分析与文本分类演示；无真实平台账号接入")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def all_orders():
    with SessionLocal() as db:
        orders = db.scalars(select(Order).order_by(Order.ordered_at.desc(), Order.id.desc())).all()
        reviews = {}
        for review in db.scalars(select(Review).order_by(Review.id)):
            reviews[review.order_pk] = review
        result = []
        for order in orders:
            review = reviews.get(order.id)
            is_model = order.category_reason.startswith(("本地文本模型", "没有识别"))
            result.append({"id": order.id, "order_id": order.order_id, "platform": order.platform,
                           "customer_id": order.customer_id, "product_name": order.product_name,
                           "amount": order.amount, "quantity": order.quantity, "ordered_at": order.ordered_at,
                           "category": review.category if review else order.category,
                           "original_category": order.category, "category_confidence": order.category_confidence,
                           "category_reason": f"人工复核：{review.note}" if review else order.category_reason,
                           "classification_source": "人工复核" if review else "本地文本模型" if is_model else "历史记录",
                           "needs_review": False if review else order.category_confidence < .55 or order.category == "其他" or "建议人工复核" in order.category_reason,
                           "reviewed": bool(review)})
        return result


def filtered_orders(q="", category="", platform="", review_only=False):
    q = q.strip().lower()
    return [o for o in all_orders() if (not category or o["category"] == category)
            and (not platform or o["platform"] == platform) and (not review_only or o["needs_review"])
            and (not q or any(q in str(o[key]).lower() for key in ("product_name", "customer_id", "order_id")))]


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": VERSION, "database": "mysql" if DATABASE_URL.startswith("mysql") else "sqlite", "mode": "local-demo"}


@app.get("/api/model")
def model_card():
    return model()[2]


class ProductInput(BaseModel):
    product_name: str = Field(min_length=1, max_length=240)


@app.post("/api/classify")
def classify_preview(body: ProductInput):
    if not body.product_name.strip():
        raise HTTPException(422, "商品名称不能为空")
    return predict(body.product_name)


@app.get("/api/summary")
def summary():
    orders = all_orders()
    today = date.today()
    current = [o for o in orders if today - timedelta(days=29) <= o["ordered_at"] <= today]
    previous = [o for o in orders if today - timedelta(days=59) <= o["ordered_at"] < today - timedelta(days=29)]
    cats = {}
    for order in orders:
        cats[order["category"]] = cats.get(order["category"], 0) + 1
    amount = lambda rows: round(sum(o["amount"] for o in rows), 2)
    change = lambda now, old: round((now / old - 1) * 100, 1) if old else None
    return {"order_count": len(orders), "revenue": amount(orders), "customers": len({o["customer_id"] for o in orders}),
            "orders_30d": len(current), "revenue_30d": amount(current), "categories": cats,
            "platforms": sorted({o["platform"] for o in orders}), "review_count": sum(o["needs_review"] for o in orders),
            "order_growth": change(len(current), len(previous)), "revenue_growth": change(amount(current), amount(previous)),
            "customer_growth": change(len({o["customer_id"] for o in current}), len({o["customer_id"] for o in previous})),
            "refreshed_at": datetime.now().isoformat(timespec="seconds")}


@app.get("/api/orders")
def get_orders(q: str = "", category: str = "", platform: str = "", limit: int = Query(200, ge=1, le=500)):
    return filtered_orders(q, category, platform)[:limit]


@app.get("/api/orders/page")
def order_page(q: str = "", category: str = "", platform: str = "", review_only: bool = False,
               page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=100)):
    rows = filtered_orders(q, category, platform, review_only)
    return {"items": rows[(page-1)*page_size:page*page_size], "total": len(rows), "page": page, "page_size": page_size}


class ReviewInput(BaseModel):
    category: str
    note: str = Field(min_length=1, max_length=240)


@app.patch("/api/orders/{order_pk}/category")
def review_category(order_pk: int, body: ReviewInput):
    if body.category not in CATEGORIES or not body.note.strip():
        raise HTTPException(422, "请选择有效品类并填写复核说明")
    with SessionLocal() as db:
        if not db.get(Order, order_pk):
            raise HTTPException(404, "订单不存在")
        review = Review(order_pk=order_pk, category=body.category, note=body.note.strip())
        db.add(review)
        db.commit()
        return {"message": "已保存人工复核，原模型结果保留；复购分析已使用新分类", "review_id": review.id}


@app.get("/api/recommendations")
def recommendations():
    return opportunities(all_orders())


@app.get("/api/customers")
def customers():
    return customer_profiles(all_orders())


async def read_csv(file):
    if not file.filename or Path(file.filename).suffix.lower() != ".csv":
        raise HTTPException(400, "请上传 CSV 文件")
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "文件最大 8 MB")
    try:
        parsed = parse_csv(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    parsed["sha256"] = hashlib.sha256(raw).hexdigest()
    with SessionLocal() as db:
        existing = set(db.execute(select(Order.platform, Order.order_id)).all())
    parsed["duplicates_existing"] = sum((row["platform"], row["order_id"]) in existing for row in parsed["rows"])
    return parsed


@app.post("/api/import/preview")
async def preview_csv(file: UploadFile = File(...)):
    parsed = await read_csv(file)
    preview = [{**row, "category": predict(row["product_name"])["category"]} for row in parsed["rows"][:8]]
    return {key: value for key, value in parsed.items() if key != "rows"} | {
        "valid": len(parsed["rows"]), "new_rows": len(parsed["rows"]) - parsed["duplicates_existing"],
        "can_import": parsed["invalid"] == 0, "preview": preview}


@app.post("/api/import/csv")
async def import_csv(file: UploadFile = File(...), authorized: bool = Form(False),
                     source: str = Form("", max_length=80), expected_sha256: str = Form("")):
    if not authorized or not source.strip():
        raise HTTPException(422, "请确认已获得数据处理授权，并填写数据来源")
    parsed = await read_csv(file)
    if expected_sha256 and parsed["sha256"] != expected_sha256:
        raise HTTPException(409, "文件与预检内容不一致，请重新预检")
    if parsed["invalid"]:
        raise HTTPException(422, {"message": "存在无效行，本批次未写入，请修正后重试", "errors": parsed["errors"]})
    created = skipped = 0
    try:
        with SessionLocal() as db:
            for row in parsed["rows"]:
                if db.scalar(select(Order.id).where(Order.platform == row["platform"], Order.order_id == row["order_id"])):
                    skipped += 1
                    continue
                category, confidence, reason = classify(row["product_name"])
                db.add(Order(**row, category=category, category_confidence=confidence, category_reason=reason))
                created += 1
            skipped += parsed["duplicates_in_file"]
            batch = ImportBatch(source=source.strip(), sha256=parsed["sha256"], imported=created, skipped=skipped, authorized=1)
            db.add(batch)
            db.commit()
            batch_id = batch.id
    except IntegrityError as exc:
        raise HTTPException(409, "并发导入发生同键冲突，事务已回滚；请重新预检") from exc
    return {"imported": created, "skipped": skipped, "classified": created, "batch_id": batch_id,
            "message": f"导入 {created} 条，重复跳过 {skipped} 条"}


@app.get("/api/import/batches")
def batches():
    with SessionLocal() as db:
        return [{"id": b.id, "source": b.source, "sha256": b.sha256, "imported": b.imported,
                 "skipped": b.skipped, "authorized": bool(b.authorized), "created_at": b.created_at}
                for b in db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()).limit(20))]


def csv_response(rows, fields, filename):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(fields)
    for row in rows:
        values = []
        for field in fields:
            value = row.get(field, "")
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            values.append(value)
        writer.writerow(values)
    return Response(("\ufeff" + stream.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/export/orders.csv")
def export_orders(q: str = "", category: str = "", platform: str = "", review_only: bool = False):
    return csv_response(filtered_orders(q, category, platform, review_only),
                        ["order_id", "platform", "customer_id", "product_name", "category", "amount", "quantity", "ordered_at", "classification_source", "category_reason"], "orders.csv")


@app.get("/api/export/opportunities.csv")
def export_opportunities():
    return csv_response(recommendations(), ["customer_id", "category", "purchase_days", "avg_cycle_days", "predicted_date", "priority_score", "status", "reason", "suggested_action"], "opportunities.csv")


@app.get("/api/report", response_class=HTMLResponse)
def report():
    from html import escape
    stats, candidates, profiles, card = summary(), recommendations(), customers(), model_card()
    keys = ("customer_id", "category", "predicted_date", "priority_score", "reason")
    rows = "".join("<tr>" + "".join(f"<td>{escape(str(o[k]))}</td>" for k in keys) + "</tr>" for o in candidates[:30])
    segments = {segment: sum(p["segment"] == segment for p in profiles) for segment in ("高价值活跃", "成长客户", "新客户", "待唤回")}
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>知购经营分析报告</title>
    <style>body{{font:15px/1.8 system-ui;max-width:1100px;margin:48px auto;padding:24px;color:#243d32}}h1{{color:#23724d}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #dce7df;padding:9px;text-align:left}}small{{color:#667}}@media print{{body{{margin:0}}}}</style>
    <h1>知购 · 订单与复购分析报告</h1><p>生成时间：{datetime.now():%Y-%m-%d %H:%M} · v{VERSION}</p>
    <p>累计订单 {stats['order_count']} 笔；近30天销售额 ¥{stats['revenue_30d']:,.2f}；客户 {stats['customers']} 位；待分类复核 {stats['review_count']} 笔。</p>
    <h2>客户分层</h2><p>{escape('；'.join(f'{key}：{value}位' for key,value in segments.items()))}</p>
    <h2>复购机会</h2><p>共 {len(candidates)} 个客户与品类组合，显示前30项。周期按不同购买日间隔中位数计算；排序分不代表购买概率。</p>
    <table><tr><th>客户</th><th>品类</th><th>预计周期日期</th><th>优先分</th><th>依据</th></tr>{rows}</table>
    <h2>模型与数据说明</h2><p>{escape(card['algorithm'])}，训练 {card['training_count']} 条，独立虚构测试 {card['test_count']} 条；Macro-F1 {card['macro_f1']}。</p>
    <p>{escape(card['limitations'])}</p><small>本地单工作区演示；默认数据为虚构样例；CSV 来自用户自行确认的授权来源。未接真实平台API，无自动触达。不同平台的客户需先映射到商家统一ID；金额是订单金额汇总，未扣退款及成本。</small></html>'''
