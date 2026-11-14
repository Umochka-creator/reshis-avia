"""Решись Авиа: FastAPI + SQLite.

Источники данных: пользовательский my_forecast.csv из ML-блока и
оригинальный routes.csv организаторов (параметры спроса, цены и затрат).
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import math
import os
import re
import secrets
import sqlite3
import time
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASE / "users.sqlite3")))
SECRET = os.getenv("APP_SECRET", secrets.token_hex(32)).encode("utf-8")
HTTPS_COOKIE = os.getenv("HTTPS_COOKIE", "0") == "1"
QUANTILES = [f"{i / 10:.1f}" for i in range(1, 10)]
CITIES = {
    "MOW-AER": "Сочи",
    "MOW-KGD": "Калининград",
    "MOW-LED": "Санкт-Петербург",
    "MOW-MRV": "Минеральные Воды",
    "MOW-OVB": "Новосибирск",
}
DATE_START = date(2026, 6, 1)
DATE_END = date(2026, 7, 1)
LOGIN_RE = re.compile(r"^[\w.-]{3,32}$", re.ASCII)


def load_forecast() -> dict[tuple[str, str], dict]:
    path = DATA / "my_forecast.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        required = {"route", "date", "seats"} | {
            f"{q}_{field}" for q in QUANTILES
            for field in ("base_demand", "price", "price_demand")
        }
        if not required.issubset(set(rd.fieldnames or [])):
            raise RuntimeError("Неверный формат my_forecast.csv")
        records = {}
        for line in rd:
            key = (line["route"], line["date"])
            if key in records:
                raise RuntimeError(f"Повтор рейса: {key}")
            record = {k: float(v) for k, v in line.items() if k not in ("route", "date")}
            if any(not math.isfinite(v) for v in record.values()):
                raise RuntimeError("Некорректные числовые значения в CSV")
            record["seats"] = int(record["seats"])
            if not all(record[f"{a}_base_demand"] <= record[f"{b}_base_demand"]
                       for a, b in zip(QUANTILES, QUANTILES[1:])):
                raise RuntimeError(f"Пересечение квантилей: {key}")
            records[key] = record
    if len(records) != 155 or {k[0] for k in records} != set(CITIES):
        raise RuntimeError("Неполный CSV: ожидается 5 маршрутов x 31 день = 155 строк")
    return records


def load_route_metadata(records: dict) -> dict:
    """Загрузить только исходные параметры организаторов, без реконструкции."""
    path = DATA / "routes.csv"
    if not path.is_file():
        raise RuntimeError("Не найден официальный data/routes.csv")
    meta = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        required = {"route", "name", "base_price", "cost_per_passenger",
                    "price_sensitivity", "price_min", "price_max"}
        if not required.issubset(set(rd.fieldnames or [])):
            raise RuntimeError("routes.csv: отсутствуют обязательные столбцы")
        for row in rd:
            route = row.get("route", "").strip()
            if route not in CITIES:
                raise RuntimeError(f"routes.csv: неизвестный маршрут {route!r}")
            if route in meta:
                raise RuntimeError(f"routes.csv: дублирующийся маршрут {route}")
            try:
                config = {name: float(row[name]) for name in (
                    "base_price", "cost_per_passenger", "price_sensitivity",
                    "price_min", "price_max")}
            except (ValueError, KeyError, TypeError) as exc:
                raise RuntimeError(f"routes.csv: неполные значения для {route}") from exc
            if not all(math.isfinite(val) for val in config.values()):
                raise RuntimeError(f"routes.csv: нечисловые параметры для {route}")
            if not (config["price_sensitivity"] > 0 and config["base_price"] > 0
                    and config["cost_per_passenger"] >= 0
                    and 0 < config["price_min"] <= config["base_price"] <= config["price_max"]):
                raise RuntimeError(f"routes.csv: недопустимые параметры для {route}")
            config["name"] = row["name"]
            config["source"] = "official"
            meta[route] = config
    if set(meta) != set(CITIES) or {r for r, _ in records} != set(meta):
        raise RuntimeError("routes.csv должен содержать ровно пять маршрутов прогноза")
    return meta

FORECAST = load_forecast()
ROUTES = load_route_metadata(FORECAST)


def db_connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def db_init():
    with db_connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            salt TEXT NOT NULL,
            hash TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )""")


db_init()
app = FastAPI(title="Решись Авиа · Аналитика спроса", version="1.0.0", docs_url="/api/docs")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260000).hex()


def issue_token(uid: int):
    deadline = int(time.time()) + 7 * 86400
    payload = f"{uid}.{deadline}"
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def decode_token(token: str | None) -> int | None:
    if not token:
        return None
    try:
        user, expires, sig = token.split(".")
        text = f"{user}.{expires}"
        expected = hmac.new(SECRET, text.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected) or int(expires) < time.time():
            return None
        return int(user)
    except (ValueError, TypeError):
        return None


def current_user(session: Annotated[str | None, Cookie()] = None):
    uid = decode_token(session)
    if uid is None:
        raise HTTPException(401, "Авторизуйтесь для расчёта")
    with db_connect() as db:
        user = db.execute("SELECT id,username FROM users WHERE id=?", (uid,)).fetchone()
    if user is None:
        raise HTTPException(401, "Пользователь не найден")
    return {"id": user["id"], "username": user["username"]}


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def valid_name(cls, val: str):
        name = val.strip().lower()
        if not LOGIN_RE.fullmatch(name):
            raise ValueError("Логин: 3–32 латинских символа, цифры, точка, дефис или _")
        return name


def set_session(response: Response, uid: int):
    response.set_cookie("session", issue_token(uid), max_age=7 * 86400,
                        httponly=True, secure=HTTPS_COOKIE, samesite="lax", path="/")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "records": len(FORECAST), "routes": len(ROUTES)}


@app.get("/api/options")
def options():
    return {
        "origin": "Москва", "date_min": DATE_START.isoformat(), "date_max": DATE_END.isoformat(),
        "routes": [
            {"code": r, "destination": city, "base_price": int(ROUTES[r]["base_price"]),
             "source": ROUTES[r]["source"],
             "price_min": ROUTES[r]["price_min"], "price_max": ROUTES[r]["price_max"]}
            for r, city in CITIES.items()
        ],
    }


@app.post("/api/auth/register", status_code=201)
def register(form: Credentials, response: Response):
    salt = secrets.token_bytes(16)
    hashed = hash_password(form.password, salt)
    try:
        with db_connect() as db:
            cursor = db.execute(
                "INSERT INTO users (username,salt,hash,created_at) VALUES (?,?,?,?)",
                (form.username, salt.hex(), hashed, int(time.time())))
            uid = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Этот логин занят")
    set_session(response, uid)
    return {"username": form.username}


@app.post("/api/auth/login")
def login(form: Credentials, response: Response):
    with db_connect() as db:
        user = db.execute("SELECT * FROM users WHERE username=?", (form.username,)).fetchone()
    if user is None or not hmac.compare_digest(
        hash_password(form.password, bytes.fromhex(user["salt"])), user["hash"]
    ):
        raise HTTPException(401, "Неправильный логин или пароль")
    set_session(response, user["id"])
    return {"username": user["username"]}


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return user


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie("session", path="/")
    return {"ok": True}


class Calculation(BaseModel):
    route: str
    date: date
    price: float = Field(gt=0, le=100000)
    quantile: float = Field(default=0.5, ge=0.1, le=0.9)

    @field_validator("price")
    @classmethod
    def finite(cls, val: float):
        if not math.isfinite(val):
            raise ValueError("Цена должна быть конечным числом")
        return val


@app.post("/api/calculate")
def calculate(request: Calculation):
    day = request.date.isoformat()
    key = (request.route, day)
    if key not in FORECAST:
        raise HTTPException(404, "Рейс не найден в прогнозе (01.06–01.07.2026)")
    settings = ROUTES[request.route]
    if settings.get("price_min") and request.price < settings["price_min"]:
        raise HTTPException(422, f"Минимальная разрешённая цена: {settings['price_min']:g} ₽")
    if settings.get("price_max") and request.price > settings["price_max"]:
        raise HTTPException(422, f"Максимальная разрешённая цена: {settings['price_max']:g} ₽")
    row = FORECAST[key]
    seats = row["seats"]
    quantiles = []
    for q in QUANTILES:
        base_demand = row[f"{q}_base_demand"]
        want = max(0.0, base_demand - settings["price_sensitivity"] *
                   (request.price - settings["base_price"]))
        sales = min(seats, want)
        quantiles.append({
            "quantile": float(q), "demand": round(want, 2),
            "sales": round(sales, 2), "unsold_seats": round(seats - sales, 2),
            "recommended_price": int(row[f"{q}_price"]),
            "base_demand": int(row[f"{q}_base_demand"]),
        })
    median = quantiles[4]
    target_q = f"{request.quantile:.1f}"
    if target_q not in QUANTILES:
        raise HTTPException(422, "Допустимые квантили: 0.1, 0.2, …, 0.9")
    target = quantiles[QUANTILES.index(target_q)]
    return {
        "route": request.route, "origin": "Москва", "destination": CITIES[request.route],
        "date": day, "input_price": request.price, "seats": seats,
        "base_price": settings["base_price"], "price_sensitivity": settings["price_sensitivity"],
        "price_min": settings["price_min"], "price_max": settings["price_max"],
        "params_source": settings["source"], "recommended_price": target["recommended_price"],
        "chosen_quantile": request.quantile,
        "predicted_demand": target["demand"], "predicted_sales": target["sales"],
        "predicted_free": target["unsold_seats"],
        "median_demand": median["demand"], "median_sales": median["sales"],
        "median_free": median["unsold_seats"],
        "occupancy_pct": round(100 * median["sales"] / seats, 1),
        "quantiles": quantiles,
        "explanation": "Спрос = max(0, базовый спрос − чувствительность × (цена − базовая цена)); "
                       "продажи = min(мест, спрос). Это сценарный прогноз, не фактические бронирования.",
    }
