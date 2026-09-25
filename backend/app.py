import json
import os
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

from rules import judge

SECRET = os.environ.get("JWT_SECRET", "herb-process-dev-secret")
DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54393/herb")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
USERS = {
    "processor": {"role": "writer", "password_hash": pwd.hash("herb123456")},
    "checker": {"role": "reader", "password_hash": pwd.hash("check123456")},
}


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


class LoginIn(BaseModel):
    username: str
    password: str


class StepIn(BaseModel):
    name: str
    temp_c: float
    minutes: float


class BatchIn(BaseModel):
    herb: str = Field(min_length=1, max_length=80)
    steps: list[StepIn]


class MergeIn(BaseModel):
    batch_ids: list[int] = Field(min_length=2)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=401, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


def require_writer(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "writer":
        raise HTTPException(status_code=403, detail="仅炮制员可写入记录")
    return user


app = FastAPI(title="饮片炮制记录台")


@app.on_event("startup")
def startup():
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS batches (
                id serial PRIMARY KEY,
                herb text NOT NULL,
                doc jsonb NOT NULL,
                verdict text NOT NULL,
                reason text NOT NULL,
                created_by text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS merge_batches (
                id serial PRIMARY KEY,
                code text NOT NULL UNIQUE,
                status text NOT NULL DEFAULT 'active',
                created_by text NOT NULL,
                created_at timestamptz NOT NULL,
                split_by text,
                split_at timestamptz
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS merge_batch_members (
                merge_id integer NOT NULL REFERENCES merge_batches (id),
                batch_id integer NOT NULL REFERENCES batches (id),
                PRIMARY KEY (merge_id, batch_id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS merge_events (
                id serial PRIMARY KEY,
                merge_id integer NOT NULL REFERENCES merge_batches (id),
                action text NOT NULL,
                actor text NOT NULL,
                detail jsonb NOT NULL DEFAULT '{}'::jsonb,
                at timestamptz NOT NULL
            )"""
        )
        count = conn.execute("SELECT COUNT(*) AS n FROM batches").fetchone()["n"]
        if count == 0:
            now = datetime.now(timezone.utc)
            samples = [
                ("甘草", {"steps": [{"name": "清炒", "temp_c": 120, "minutes": 12}]}),
                ("黄芩", {"steps": [{"name": "清炒", "temp_c": 40, "minutes": 12}]}),
            ]
            for herb, doc in samples:
                verdict, reason = judge(doc)
                conn.execute(
                    """INSERT INTO batches (herb, doc, verdict, reason, created_by, created_at)
                       VALUES (%s, %s::jsonb, %s, %s, %s, %s)""",
                    (herb, json.dumps(doc, ensure_ascii=False), verdict, reason, "processor", now),
                )
        conn.commit()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "herb-process-record"}


@app.post("/api/auth/login")
def login(body: LoginIn):
    user = USERS.get(body.username.strip())
    if not user or not pwd.verify(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode({"sub": body.username.strip(), "role": user["role"], "exp": exp}, SECRET, algorithm="HS256")
    return {"access_token": token, "username": body.username.strip(), "role": user["role"]}


@app.get("/api/batches")
def list_batches(merge_code: str | None = None, _user: dict = Depends(current_user)):
    with connect() as conn:
        if merge_code and merge_code.strip():
            rows = conn.execute(
                """SELECT b.id, b.herb, b.doc, b.verdict, b.reason, b.created_by, mb.code AS merge_code
                   FROM batches b
                   JOIN merge_batch_members m ON m.batch_id = b.id
                   JOIN merge_batches mb ON mb.id = m.merge_id AND mb.status = 'active'
                   WHERE mb.code = %s
                   ORDER BY b.id DESC""",
                (merge_code.strip(),),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT b.id, b.herb, b.doc, b.verdict, b.reason, b.created_by, am.code AS merge_code
                   FROM batches b
                   LEFT JOIN (
                       SELECT m.batch_id, mb.code
                       FROM merge_batch_members m
                       JOIN merge_batches mb ON mb.id = m.merge_id
                       WHERE mb.status = 'active'
                   ) am ON am.batch_id = b.id
                   ORDER BY b.id DESC"""
            ).fetchall()
    return rows


@app.post("/api/batches", status_code=201)
def create_batch(body: BatchIn, user: dict = Depends(require_writer)):
    doc = {"steps": [s.model_dump() for s in body.steps]}
    verdict, reason = judge(doc)
    with connect() as conn:
        row = conn.execute(
            """INSERT INTO batches (herb, doc, verdict, reason, created_by, created_at)
               VALUES (%s, %s::jsonb, %s, %s, %s, %s)
               RETURNING id, herb, doc, verdict, reason, created_by""",
            (body.herb.strip(), json.dumps(doc, ensure_ascii=False), verdict, reason, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
    return row


def fetch_merge(conn, merge_id: int) -> dict:
    merge = conn.execute(
        """SELECT id, code, status, created_by, created_at, split_by, split_at
           FROM merge_batches WHERE id = %s""",
        (merge_id,),
    ).fetchone()
    members = conn.execute(
        """SELECT b.id, b.herb, b.verdict, b.reason
           FROM merge_batch_members m JOIN batches b ON b.id = m.batch_id
           WHERE m.merge_id = %s ORDER BY b.id""",
        (merge_id,),
    ).fetchall()
    return {**merge, "members": members}


@app.get("/api/merge-batches")
def list_merges(_user: dict = Depends(current_user)):
    with connect() as conn:
        merges = conn.execute(
            """SELECT id, code, status, created_by, created_at, split_by, split_at
               FROM merge_batches ORDER BY id DESC"""
        ).fetchall()
        members = conn.execute(
            """SELECT m.merge_id, b.id, b.herb, b.verdict, b.reason
               FROM merge_batch_members m JOIN batches b ON b.id = m.batch_id
               ORDER BY b.id"""
        ).fetchall()
    by_merge: dict[int, list] = {}
    for m in members:
        by_merge.setdefault(m["merge_id"], []).append(
            {"id": m["id"], "herb": m["herb"], "verdict": m["verdict"], "reason": m["reason"]}
        )
    return [{**merge, "members": by_merge.get(merge["id"], [])} for merge in merges]


@app.post("/api/merge-batches", status_code=201)
def create_merge(body: MergeIn, user: dict = Depends(require_writer)):
    ids = sorted(set(body.batch_ids))
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="至少选择两条放行记录")
    with connect() as conn:
        rows = conn.execute("SELECT id, verdict FROM batches WHERE id = ANY(%s)", (ids,)).fetchall()
        if len(rows) != len(ids):
            raise HTTPException(status_code=400, detail="存在无效的记录编号")
        if any(r["verdict"] != "放行" for r in rows):
            raise HTTPException(status_code=400, detail="仅放行记录可钉入合并批")
        taken = conn.execute(
            """SELECT m.batch_id FROM merge_batch_members m
               JOIN merge_batches mb ON mb.id = m.merge_id
               WHERE mb.status = 'active' AND m.batch_id = ANY(%s)""",
            (ids,),
        ).fetchall()
        if taken:
            raise HTTPException(status_code=400, detail="有记录已在其他合并批中")
        now = datetime.now(timezone.utc)
        merge = conn.execute(
            """INSERT INTO merge_batches (code, status, created_by, created_at)
               VALUES ('', 'active', %s, %s) RETURNING id""",
            (user["username"], now),
        ).fetchone()
        code = f"HB-{now:%Y%m%d}-{merge['id']:04d}"
        conn.execute("UPDATE merge_batches SET code = %s WHERE id = %s", (code, merge["id"]))
        for bid in ids:
            conn.execute(
                "INSERT INTO merge_batch_members (merge_id, batch_id) VALUES (%s, %s)",
                (merge["id"], bid),
            )
        conn.execute(
            """INSERT INTO merge_events (merge_id, action, actor, detail, at)
               VALUES (%s, 'merge', %s, %s::jsonb, %s)""",
            (merge["id"], user["username"], json.dumps({"batch_ids": ids}), now),
        )
        result = fetch_merge(conn, merge["id"])
        conn.commit()
    return result


@app.post("/api/merge-batches/{merge_id}/split")
def split_merge(merge_id: int, user: dict = Depends(require_writer)):
    with connect() as conn:
        merge = conn.execute("SELECT id, status FROM merge_batches WHERE id = %s", (merge_id,)).fetchone()
        if merge is None:
            raise HTTPException(status_code=404, detail="合并批不存在")
        if merge["status"] != "active":
            raise HTTPException(status_code=400, detail="该合并批已拆回")
        now = datetime.now(timezone.utc)
        member_ids = [
            r["batch_id"]
            for r in conn.execute(
                "SELECT batch_id FROM merge_batch_members WHERE merge_id = %s ORDER BY batch_id",
                (merge_id,),
            ).fetchall()
        ]
        conn.execute(
            "UPDATE merge_batches SET status = 'split', split_by = %s, split_at = %s WHERE id = %s",
            (user["username"], now, merge_id),
        )
        conn.execute(
            """INSERT INTO merge_events (merge_id, action, actor, detail, at)
               VALUES (%s, 'split', %s, %s::jsonb, %s)""",
            (merge_id, user["username"], json.dumps({"batch_ids": member_ids}), now),
        )
        result = fetch_merge(conn, merge_id)
        conn.commit()
    return result


@app.get("/api/merge-events")
def list_merge_events(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute(
            """SELECT e.id, e.action, e.actor, e.detail, e.at, mb.code
               FROM merge_events e JOIN merge_batches mb ON mb.id = e.merge_id
               ORDER BY e.id DESC"""
        ).fetchall()
    return rows
