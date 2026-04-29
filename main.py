from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
import httpx, os, hashlib, jwt
from datetime import datetime, timedelta
from typing import Optional

app = FastAPI(title="Arleelines Logistics API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
BITRIX_WEBHOOK = os.environ["BITRIX24_WEBHOOK"]
JWT_SECRET = os.environ.get("JWT_SECRET", "arleelines-secret-2024")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 168


def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()


def create_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email,
               "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")
    try:
        return jwt.decode(authorization.split(" ")[1], JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    phone: str = ""
    company: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class CalcRequest(BaseModel):
    origin: str
    destination: str
    weight: float
    volume: float = 0.0
    cargo_type: str = "general"


@app.post("/auth/register")
async def register(req: RegisterRequest):
    if supabase.table("users").select("id").eq("email", req.email).execute().data:
        raise HTTPException(400, "Email already registered")
    user = supabase.table("users").insert({
        "email": req.email, "password_hash": hash_password(req.password),
        "name": req.name, "phone": req.phone, "company": req.company
    }).execute().data[0]
    return {"token": create_token(str(user["id"]), user["email"]),
            "user": {"id": user["id"], "name": user["name"], "email": user["email"]}}


@app.post("/auth/login")
async def login(req: LoginRequest):
    rows = supabase.table("users").select("*").eq("email", req.email)                    .eq("password_hash", hash_password(req.password)).execute().data
    if not rows:
        raise HTTPException(401, "Invalid credentials")
    user = rows[0]
    return {"token": create_token(str(user["id"]), user["email"]),
            "user": {"id": user["id"], "name": user["name"], "email": user["email"]}}


@app.get("/auth/me")
async def me(user: dict = Depends(verify_token)):
    rows = supabase.table("users").select("id,name,email,phone,company,created_at")                    .eq("id", user["sub"]).execute().data
    if not rows:
        raise HTTPException(404, "User not found")
    return rows[0]


@app.get("/orders/my")
async def get_orders(user: dict = Depends(verify_token)):
    async with httpx.AsyncClient() as c:
        contacts = (await c.post(
            f"{BITRIX_WEBHOOK}/crm.contact.list",
            json={"filter": {"EMAIL": user["email"]}, "select": ["ID"]},
            timeout=30
        )).json().get("result", [])
        if not contacts:
            return {"orders": [], "total": 0}
        deals = (await c.post(
            f"{BITRIX_WEBHOOK}/crm.deal.list",
            json={"filter": {"CONTACT_ID": contacts[0]["ID"]},
                  "select": ["ID","TITLE","STAGE_ID","OPPORTUNITY","CURRENCY_ID","DATE_CREATE","CLOSEDATE","COMMENTS"],
                  "order": {"DATE_CREATE": "DESC"}},
            timeout=30
        )).json().get("result", [])
        stages_raw = (await c.post(
            f"{BITRIX_WEBHOOK}/crm.dealcategory.stage.list",
            json={"id": 0}, timeout=30
        )).json().get("result", [])
        stages = {s["STATUS_ID"]: s["NAME"] for s in stages_raw}
        orders = [{"id": d["ID"], "title": d.get("TITLE",""),
                   "status": stages.get(d.get("STAGE_ID",""), d.get("STAGE_ID","")),
                   "amount": d.get("OPPORTUNITY", 0),
                   "currency": d.get("CURRENCY_ID", "RUB"),
                   "created_at": d.get("DATE_CREATE",""),
                   "comments": d.get("COMMENTS","")} for d in deals]
        return {"orders": orders, "total": len(orders)}


@app.get("/orders/{deal_id}")
async def get_order(deal_id: str, user: dict = Depends(verify_token)):
    async with httpx.AsyncClient() as c:
        deal = (await c.post(
            f"{BITRIX_WEBHOOK}/crm.deal.get",
            json={"id": deal_id}, timeout=30
        )).json().get("result", {})
        if not deal:
            raise HTTPException(404, "Order not found")
        return {"order": deal}


@app.post("/calculator/estimate")
async def calculate(req: CalcRequest):
    eff_w = max(req.weight, req.volume * 333)
    cn_kw = ["shanghai","beijing","guangzhou","shenzhen","ningbo",
             "china","китай","шанхай","пекин","гуанчжоу"]
    is_cn = any(k in req.origin.lower() for k in cn_kw)
    rate, cur, transit = (0.30, "USD", "25-35 дней") if is_cn else (0.38, "EUR", "12-18 дней")
    mults = {"general":1.0,"dangerous":1.8,"temperature":1.5,
             "oversized":1.4,"documents":0.5,"fragile":1.2}
    cost = round(eff_w * rate * mults.get(req.cargo_type, 1.0), 2)
    return {"estimated_cost": cost, "currency": cur, "transit_days": transit,
            "effective_weight_kg": round(eff_w, 2),
            "disclaimer": "Предварительный расчёт. Уточните у менеджера."}


@app.get("/news")
async def get_news(limit: int = 10, offset: int = 0):
    data = supabase.table("news").select("*").order("published_at", desc=True)                    .range(offset, offset + limit - 1).execute().data
    return {"news": data, "total": len(data)}


@app.get("/news/{news_id}")
async def get_news_item(news_id: int):
    rows = supabase.table("news").select("*").eq("id", news_id).execute().data
    if not rows:
        raise HTTPException(404, "Not found")
    return rows[0]


@app.get("/")
async def root():
    return {"status": "ok", "service": "Arleelines Logistics API",
            "version": "1.0.0", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "healthy", "ts": datetime.utcnow().isoformat()}
