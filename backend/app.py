import json
import os
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query
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


class UnmergeIn(BaseModel):
    merge_no: str = Field(min_length=1, max_length=40)


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
        raise HTTPException(status_code=403, detail="仅炮制员可钉批或拆回")
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
        conn.execute("ALTER TABLE batches ADD COLUMN IF NOT EXISTS merge_id integer")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS merged_batches (
                id serial PRIMARY KEY,
                merge_no text UNIQUE NOT NULL,
                created_by text NOT NULL,
                created_at timestamptz NOT NULL,
                unmerged_by text,
                unmerged_at timestamptz
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS merged_batch_members (
                merge_id integer NOT NULL REFERENCES merged_batches(id),
                batch_id integer NOT NULL REFERENCES batches(id),
                position integer NOT NULL,
                PRIMARY KEY (merge_id, batch_id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS merge_ledger (
                id serial PRIMARY KEY,
                merge_no text NOT NULL,
                action text NOT NULL,
                operator text NOT NULL,
                member_ids integer[] NOT NULL,
                note text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )
        count = conn.execute("SELECT COUNT(*) AS n FROM batches").fetchone()["n"]
        if count == 0:
            now = datetime.now(timezone.utc)
            samples = [
                ("甘草", {"steps": [{"name": "清炒", "temp_c": 120, "minutes": 12}]}),
                ("黄芩", {"steps": [{"name": "清炒", "temp_c": 40, "minutes": 12}]}),
                ("白芍", {"steps": [{"name": "清炒", "temp_c": 100, "minutes": 10}]}),
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
def list_batches(merge_no: str | None = Query(default=None), _user: dict = Depends(current_user)):
    with connect() as conn:
        if merge_no is not None and merge_no.strip():
            rows = conn.execute(
                """SELECT b.id, b.herb, b.doc, b.verdict, b.reason, b.created_by,
                          m.merge_no AS merge_no
                     FROM batches b
                     JOIN merged_batch_members mbm ON mbm.batch_id = b.id
                     JOIN merged_batches m ON m.id = mbm.merge_id
                    WHERE m.merge_no = %s AND m.unmerged_at IS NULL
                    ORDER BY mbm.position""",
                (merge_no.strip(),),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT b.id, b.herb, b.doc, b.verdict, b.reason, b.created_by,
                          m.merge_no AS merge_no
                     FROM batches b
                     LEFT JOIN merged_batches m ON m.id = b.merge_id
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


@app.get("/api/merges")
def list_merges(_user: dict = Depends(current_user)):
    with connect() as conn:
        return conn.execute(
            """SELECT m.id, m.merge_no, m.created_by, m.created_at,
                      m.unmerged_by, m.unmerged_at,
                      ARRAY_AGG(b.id ORDER BY mbm.position) AS member_ids,
                      COALESCE(jsonb_agg(
                          jsonb_build_object('id', b.id, 'herb', b.herb, 'verdict', b.verdict)
                          ORDER BY mbm.position
                      ) FILTER (WHERE b.id IS NOT NULL), '[]'::jsonb) AS members
                 FROM merged_batches m
                 JOIN merged_batch_members mbm ON mbm.merge_id = m.id
                 JOIN batches b ON b.id = mbm.batch_id
             GROUP BY m.id
             ORDER BY m.id DESC"""
        ).fetchall()


@app.get("/api/merges/{merge_no}")
def get_merge(merge_no: str, _user: dict = Depends(current_user)):
    with connect() as conn:
        merge = conn.execute(
            """SELECT id, merge_no, created_by, created_at, unmerged_by, unmerged_at
                 FROM merged_batches WHERE merge_no = %s""",
            (merge_no,),
        ).fetchone()
        if merge is None:
            raise HTTPException(status_code=404, detail="合并批不存在")
        members = conn.execute(
            """SELECT b.id, b.herb, b.doc, b.verdict, b.reason
                 FROM merged_batch_members mbm
                 JOIN batches b ON b.id = mbm.batch_id
                WHERE mbm.merge_id = %s
                ORDER BY mbm.position""",
            (merge["id"],),
        ).fetchall()
    return {**merge, "members": members}


@app.post("/api/merges", status_code=201)
def create_merge(body: MergeIn, user: dict = Depends(require_writer)):
    batch_ids = list(dict.fromkeys(body.batch_ids))
    if len(batch_ids) < 2:
        raise HTTPException(status_code=422, detail="至少选择两个放行行")
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, herb, verdict FROM batches WHERE id = ANY(%s) FOR UPDATE",
            (batch_ids,),
        ).fetchall()
        by_id = {r["id"]: r for r in rows}
        missing = [i for i in batch_ids if i not in by_id]
        if missing:
            raise HTTPException(status_code=404, detail=f"行不存在: {missing}")
        blocked = [r for r in rows if r["verdict"] != "放行"]
        if blocked:
            raise HTTPException(status_code=422, detail="仅放行行可钉批：" + "、".join(f"#{r['id']} {r['herb']}" for r in blocked))
        busy = [r for r in rows if _is_pinned(conn, r["id"])]
        if busy:
            raise HTTPException(status_code=422, detail="存在已钉在其他合并批的行：" + "、".join(f"#{r['id']}" for r in busy))
        now = datetime.now(timezone.utc)
        merge_no = f"HB{now:%y%m%d%H%M%S}{now:%f}"
        merge = conn.execute(
            """INSERT INTO merged_batches (merge_no, created_by, created_at)
               VALUES (%s, %s, %s) RETURNING id""",
            (merge_no, user["username"], now),
        ).fetchone()
        merge_id = merge["id"]
        for position, batch_id in enumerate(batch_ids):
            conn.execute(
                "INSERT INTO merged_batch_members (merge_id, batch_id, position) VALUES (%s, %s, %s)",
                (merge_id, batch_id, position),
            )
            conn.execute("UPDATE batches SET merge_id = %s WHERE id = %s", (merge_id, batch_id))
        conn.execute(
            """INSERT INTO merge_ledger (merge_no, action, operator, member_ids, note, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (merge_no, "钉批", user["username"], batch_ids, "钉成合并批，成员 " + "、".join(f"#{i}" for i in batch_ids), now),
        )
        conn.commit()
    return {"merge_no": merge_no, "member_ids": batch_ids}


def _is_pinned(conn, batch_id: int) -> bool:
    row = conn.execute(
        """SELECT 1 FROM batches b
            JOIN merged_batches m ON m.id = b.merge_id
           WHERE b.id = %s AND m.unmerged_at IS NULL""",
        (batch_id,),
    ).fetchone()
    return row is not None


@app.post("/api/merges/unmerge", status_code=200)
def unmerge_merge(body: UnmergeIn, user: dict = Depends(require_writer)):
    with connect() as conn:
        merge = conn.execute(
            "SELECT id, merge_no, unmerged_at FROM merged_batches WHERE merge_no = %s FOR UPDATE",
            (body.merge_no,),
        ).fetchone()
        if merge is None:
            raise HTTPException(status_code=404, detail="合并批不存在")
        if merge["unmerged_at"] is not None:
            raise HTTPException(status_code=422, detail="该合并批已拆回")
        member_rows = conn.execute(
            "SELECT batch_id FROM merged_batch_members WHERE merge_id = %s ORDER BY position",
            (merge["id"],),
        ).fetchall()
        member_ids = [r["batch_id"] for r in member_rows]
        now = datetime.now(timezone.utc)
        conn.execute(
            "UPDATE merged_batches SET unmerged_by = %s, unmerged_at = %s WHERE id = %s",
            (user["username"], now, merge["id"]),
        )
        conn.execute("UPDATE batches SET merge_id = NULL WHERE merge_id = %s", (merge["id"],))
        conn.execute(
            """INSERT INTO merge_ledger (merge_no, action, operator, member_ids, note, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (body.merge_no, "拆回", user["username"], member_ids, "拆回合并批，成员回总表 " + "、".join(f"#{i}" for i in member_ids), now),
        )
        conn.commit()
    return {"merge_no": body.merge_no, "member_ids": member_ids}


@app.get("/api/merges/ledger/all")
def merge_ledger(_user: dict = Depends(current_user)):
    with connect() as conn:
        return conn.execute(
            """SELECT id, merge_no, action, operator, member_ids, note, created_at
                 FROM merge_ledger ORDER BY id DESC"""
        ).fetchall()
