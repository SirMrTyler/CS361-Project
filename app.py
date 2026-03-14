"""
Workout Logger - Milestone #1 (CS361)

This is a small monolith (no microservices yet) that supports:
- Log workout session (create)
- View workout history (list + details)
- Edit workout entry (update)
- Delete workout entry (optional, but included)

Data persists in a local SQLite database file (instance/workouts.sqlite3).
"""

from __future__ import annotations

import os
import re
import dotenv
import sqlite3
import time
from functools import wraps
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, jsonify, render_template, request
from flask import redirect, session, url_for

# ----------------------------
# App + DB setup
# ----------------------------

def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

    # Store DB in instance/ so it doesn't get accidentally committed.
    os.makedirs(app.instance_path, exist_ok=True)
    app.config["DATABASE_PATH"] = os.path.join(app.instance_path, "workouts.sqlite3")
    print(f"DATABASE_PATH: {app.config['DATABASE_PATH']}")
    app.config["AUTH_BASE_URL"] = dotenv.dotenv_values().get("AUTH_BASE_URL")
    print(f"AUTH_BASE_URL from .env: {app.config['AUTH_BASE_URL']}")
    
    app.config["AUTH_APP_ID"] = dotenv.dotenv_values().get("AUTH_APP_ID")
    print(f"AUTH_APP_ID from .env: {app.config['AUTH_APP_ID']}")
    app.config["AUTH_APP_SECRET"] = dotenv.dotenv_values().get("AUTH_APP_SECRET")
    print(f"AUTH_APP_SECRET from .env: {app.config['AUTH_APP_SECRET']}")
    app.config["EMAIL_SENDER_BASE_URL"] = dotenv.dotenv_values().get("EMAIL_SENDER_BASE_URL", "http://127.0.0.1:8000")
    app.config["EMAIL_VERIFY_BASE_URL"] = dotenv.dotenv_values().get("EMAIL_VERIFY_BASE_URL", "http://127.0.0.1:8001")
    app.config["BUDDHA_QUOTES_URL"] = dotenv.dotenv_values().get("BUDDHA_QUOTES_URL", "https://buddha-quote-gen.onrender.com/")

    init_db(app.config["DATABASE_PATH"])

    def auth_headers() -> Dict[str, str]:
        return {
            "X-App-Id": app.config["AUTH_APP_ID"],
            "X-App-Secret": app.config["AUTH_APP_SECRET"],
            "Content-Type": "application/json",
        }

    def auth_post(path: str, payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        url = f"{app.config['AUTH_BASE_URL']}{path}"
        try:
            resp = requests.post(url, headers=auth_headers(), json=payload, timeout=5)
        except requests.RequestException:
            return None, "Authentication service unavailable. Please try again shortly."

        try:
            data = resp.json()
        except ValueError:
            data = {}

        if not resp.ok:
            message = data.get("error", {}).get("message") or f"Authentication failed ({resp.status_code})."
            return None, message

        return data, None

    def service_post(
        base_url: str,
        path: str,
        payload: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int]]:
        url = f"{base_url.rstrip('/')}{path}"
        print(f"[microservice] POST {url} payload_keys={list(payload.keys())}")
        try:
            resp = requests.post(url, json=payload, timeout=8)
        except requests.RequestException as exc:
            print(f"[microservice] request failed for {url}: {exc}")
            return None, f"Microservice unavailable ({url}). Ensure the service is running and base URL is correct.", None

        try:
            data = resp.json()
        except ValueError:
            data = {}

        if not resp.ok:
            print(f"[microservice] {url} -> {resp.status_code} body={data or resp.text}")
            return data, f"Microservice request failed ({resp.status_code}).", resp.status_code
        print(f"[microservice] {url} -> {resp.status_code} body={data}")
        return data, None, resp.status_code

    def verify_email_address(email: str) -> Tuple[bool, Optional[str]]:
        # Always enforce basic format locally.
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return False, "Please enter a valid email address."

        data, err, status_code = service_post(app.config["EMAIL_VERIFY_BASE_URL"], "/email/verify", {"email": email})
        if err:
            if status_code is None:
                # Do not block account creation only when the verification microservice cannot be reached.
                print(f"Email verification service unavailable at {app.config['EMAIL_VERIFY_BASE_URL']}: {err}; allowing signup with format-only validation.")
                return True, None

            detail_parts: List[str] = []
            if isinstance(data, dict):
                provider_error = data.get("error")
                if isinstance(provider_error, dict):
                    provider_code = str(provider_error.get("code") or "").strip()
                    provider_message = str(provider_error.get("message") or "").strip()
                    if provider_code:
                        detail_parts.append(provider_code)
                    if provider_message:
                        detail_parts.append(provider_message)
                elif provider_error:
                    detail_parts.append(str(provider_error).strip())

                provider_message = str(data.get("message") or "").strip()
                if provider_message:
                    detail_parts.append(provider_message)

            detail = " — ".join(part for part in detail_parts if part)
            message = detail or f"Email verification service returned {status_code}."
            return False, f"Email verification failed: {message}"

        if not data:
            return True, None

        if data.get("isDeliverable") is False:
            reason = data.get("reason") or "not_deliverable"
            return False, f"Email could not be verified ({reason})."

        return True, None

    def send_email_notification(to_email: str, subject: str, body: str) -> bool:
        _, err, _ = service_post(
            app.config["EMAIL_SENDER_BASE_URL"],
            "/email/send",
            {"to": to_email, "subject": subject, "body": body},
        )
        if err:
            print(f"Email sender request failed for {to_email} via {app.config['EMAIL_SENDER_BASE_URL']}: {err}")
        else:
            print(f"Email sender request succeeded for {to_email}.")
        return err is None

    def fetch_buddha_quote() -> Optional[Dict[str, str]]:
        try:
            resp = requests.post(app.config["BUDDHA_QUOTES_URL"], json={}, timeout=8)
            data = resp.json() if resp.ok else {}
        except (requests.RequestException, ValueError):
            return None

        if not isinstance(data, dict) or not data.get("text"):
            return None
        return {
            "text": str(data.get("text", "")).strip(),
            "byName": str(data.get("byName", "Buddha")).strip(),
            "byImage": str(data.get("byImage", "")).strip(),
        }

    def require_login(api: bool = False):
        def decorator(view_func):
            @wraps(view_func)
            def wrapped(*args, **kwargs):
                user = session.get("auth_user")
                if not user:
                    if api:
                        return jsonify({"ok": False, "error": "Authentication required."}), 401
                    return redirect(url_for("login_page"))

                data, err = auth_post("/introspect", {"sessionId": user.get("sessionId")})
                if err or not data or not data.get("active"):
                    session.pop("auth_user", None)
                    if api:
                        return jsonify({"ok": False, "error": "Session expired. Please log in again."}), 401
                    return redirect(url_for("login_page"))
                return view_func(*args, **kwargs)

            return wrapped

        return decorator

    def get_current_user_id() -> Optional[str]:
        user = session.get("auth_user") or {}
        user_id = user.get("userId")
        if user_id is None:
            return None
        return str(user_id)

    # ----------------------------
    # UI routes
    # ----------------------------

    @app.get("/")
    @require_login()
    def home() -> str:
        return render_template("history.html", quote=fetch_buddha_quote())

    @app.get("/api/buddha-quote")
    @require_login(api=True)
    def api_buddha_quote():
        quote = fetch_buddha_quote()
        if not quote:
            return jsonify({"ok": False, "error": "Could not load quote right now."}), 503
        return jsonify({"ok": True, "quote": quote})

    @app.get("/login")
    def login_page() -> str:
        if session.get("auth_user"):
            return redirect(url_for("home"))
        return render_template("login.html")

    @app.post("/login")
    def login_action():
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        email = (request.form.get("email") or "").strip().lower()
        mode = (request.form.get("mode") or "login").strip().lower()

        if not username or not password:
            return render_template("login.html", error="Username and password are required."), 400
        
        if mode == "signup":
            if not email:
                return render_template("login.html", error="Email is required for signup.", username=username), 400
            is_valid_email, email_error = verify_email_address(email)
            if not is_valid_email:
                return render_template("login.html", error=email_error, username=username, email=email), 400

        endpoint = "/signup" if mode == "signup" else "/login"
        data, err = auth_post(endpoint, {"username": username, "password": password})
        if err:
            return render_template("login.html", error=err, username=username), 401

        session["auth_user"] = {
            "username": username,
            "userId": data.get("userId"),
            "sessionId": data.get("sessionId"),
            "token": data.get("token"),
        }

        user_id = str(data.get("userId") or "")
        if mode == "signup" and user_id:
            upsert_user_email(app.config["DATABASE_PATH"], user_id, username, email)
            send_email_notification(
                email,
                "Welcome to Workout Logger",
                "<p>Your account was created successfully.</p>",
            )
        elif mode != "signup" and user_id:
            saved_email = get_user_email(app.config["DATABASE_PATH"], user_id, username)
            if saved_email:
                send_email_notification(
                    saved_email,
                    "New Workout Logger login",
                    f"<p>Hi {username}, a login to your account was detected.</p>",
                )
        return redirect(url_for("home"))

    @app.get("/logout")
    @require_login()
    def logout_action():
        user = session.get("auth_user") or {}
        if user.get("sessionId"):
            auth_post("/logout", {"sessionId": user["sessionId"]})
        session.pop("auth_user", None)
        return redirect(url_for("login_page"))


    @app.get("/new")
    @require_login()
    def new_workout_page() -> str:
        return render_template("workout_form.html", mode="create", workout_id=None)

    @app.get("/workout/<int:workout_id>")
    @require_login()
    def view_workout_page(workout_id: int) -> str:
        return render_template("workout_view.html", workout_id=workout_id)

    @app.get("/workout/<int:workout_id>/edit")
    @require_login()
    def edit_workout_page(workout_id: int) -> str:
        return render_template("workout_form.html", mode="edit", workout_id=workout_id)

    # ----------------------------
    # API routes
    # ----------------------------

    @app.get("/api/workouts")
    @require_login(api=True)
    def api_list_workouts():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"ok": False, "error": "User identity missing from session."}), 401
        t0 = time.perf_counter()
        workouts = list_workouts(app.config["DATABASE_PATH"], user_id)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        return jsonify({"ok": True, "workouts": workouts, "timing_ms": elapsed_ms})

    @app.get("/api/workouts/<int:workout_id>")
    @require_login(api=True)
    def api_get_workout(workout_id: int):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"ok": False, "error": "User identity missing from session."}), 401
        t0 = time.perf_counter()
        workout = get_workout(app.config["DATABASE_PATH"], workout_id, user_id)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        if workout is None:
            return jsonify({"ok": False, "error": "Workout not found."}), 404
        return jsonify({"ok": True, "workout": workout, "timing_ms": elapsed_ms})

    @app.post("/api/workouts")
    @require_login(api=True)
    def api_create_workout():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"ok": False, "error": "User identity missing from session."}), 401
        payload = request.get_json(silent=True) or {}
        errors = validate_workout_payload(payload)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400

        workout_id = create_workout(app.config["DATABASE_PATH"], payload, user_id)
        workout = get_workout(app.config["DATABASE_PATH"], workout_id, user_id)
        return jsonify({"ok": True, "workout_id": workout_id, "workout": workout}), 201

    @app.put("/api/workouts/<int:workout_id>")
    @require_login(api=True)
    def api_update_workout(workout_id: int):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"ok": False, "error": "User identity missing from session."}), 401
        payload = request.get_json(silent=True) or {}
        errors = validate_workout_payload(payload)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400

        updated = update_workout(app.config["DATABASE_PATH"], workout_id, payload, user_id)
        if not updated:
            return jsonify({"ok": False, "error": "Workout not found."}), 404

        workout = get_workout(app.config["DATABASE_PATH"], workout_id, user_id)
        return jsonify({"ok": True, "workout": workout})

    @app.delete("/api/workouts/<int:workout_id>")
    @require_login(api=True)
    def api_delete_workout(workout_id: int):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"ok": False, "error": "User identity missing from session."}), 401

        deleted = delete_workout(app.config["DATABASE_PATH"], workout_id, user_id)
        if not deleted:
            return jsonify({"ok": False, "error": "Workout not found."}), 404
        return jsonify({"ok": True})

    @app.delete("/api/workouts")
    @require_login(api=True)
    def api_bulk_delete_workouts():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"ok": False, "error": "User identity missing from session."}), 401

        payload = request.get_json(silent=True) or {}
        delete_all = bool(payload.get("all"))
        ids_raw = payload.get("ids")

        if delete_all:
            deleted_count = delete_all_workouts(app.config["DATABASE_PATH"], user_id)
            return jsonify({"ok": True, "deleted_count": deleted_count, "scope": "all"})

        if not isinstance(ids_raw, list) or len(ids_raw) == 0:
            return jsonify({"ok": False, "error": "Provide a non-empty list of workout IDs or set all=true."}), 400

        ids: List[int] = []
        for item in ids_raw:
            try:
                workout_id = int(item)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "Workout IDs must be integers."}), 400
            if workout_id < 1:
                return jsonify({"ok": False, "error": "Workout IDs must be positive integers."}), 400
            if workout_id not in ids:
                ids.append(workout_id)

        deleted_count = delete_workouts_by_ids(app.config["DATABASE_PATH"], ids, user_id)
        return jsonify({"ok": True, "deleted_count": deleted_count, "scope": "selected"})

    # Helpful for demonstrating responsiveness with 200 workouts (Issue #12)
    @app.post("/api/debug/seed")
    @require_login(api=True)
    def api_debug_seed():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"ok": False, "error": "User identity missing from session."}), 401
        payload = request.get_json(silent=True) or {}
        count = int(payload.get("count", 200))
        count = max(1, min(count, 2000))  # keep bounded
        created = seed_sample_data(app.config["DATABASE_PATH"], user_id=user_id, count=count)
        return jsonify({"ok": True, "created": created})
    
    @app.context_processor
    def inject_auth_user() -> Dict[str, Any]:
        return {"auth_user": session.get("auth_user")}

    return app


def get_db_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str) -> None:
    """Create tables if they don't exist (idempotent)."""
    conn = get_db_connection(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                workout_date TEXT NOT NULL, -- ISO date YYYY-MM-DD
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workout_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                sort_order INTEGER NOT NULL,
                FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exercise_id INTEGER NOT NULL,
                set_number INTEGER NOT NULL,
                reps INTEGER NOT NULL CHECK (reps >= 1),
                weight REAL NOT NULL CHECK (weight >= 0),
                FOREIGN KEY (exercise_id) REFERENCES exercises(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL UNIQUE,
                username TEXT NOT NULL,
                email TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_exercises_workout ON exercises(workout_id, sort_order);
            CREATE INDEX IF NOT EXISTS idx_sets_exercise ON sets(exercise_id, set_number);
            """
        )
        # Backfill/migrate older databases that predate user-scoped workouts.
        cols = [row["name"] for row in conn.execute("PRAGMA table_info(workouts);").fetchall()]
        if "user_id" not in cols:
            conn.execute("ALTER TABLE workouts ADD COLUMN user_id TEXT;")
            conn.execute("UPDATE workouts SET user_id = ? WHERE user_id IS NULL OR user_id = '';", ("legacy",))
            conn.commit()

        conn.execute("CREATE INDEX IF NOT EXISTS idx_workouts_user_date ON workouts(user_id, workout_date DESC);")
        conn.commit()
    finally:
        conn.close()


# ----------------------------
# Validation helpers
# ----------------------------

def _parse_iso_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        # Accept YYYY-MM-DD
        try:
            dt = datetime.strptime(value, "%Y-%m-%d").date()
            return dt.isoformat()
        except ValueError:
            return None
    return None


def validate_workout_payload(payload: Dict[str, Any]) -> List[str]:
    """
    Expected payload:
    {
      "workout_date": "YYYY-MM-DD",
      "title": "optional",
      "exercises": [
        {
          "name": "Bench Press",
          "sets": [{"reps": 5, "weight": 135}, ...]
        }, ...
      ]
    }
    """
    errors: List[str] = []

    workout_date = _parse_iso_date(payload.get("workout_date"))
    if not workout_date:
        errors.append("Workout date is required (YYYY-MM-DD).")

    exercises = payload.get("exercises")
    if not isinstance(exercises, list) or len(exercises) == 0:
        errors.append("At least one exercise is required.")
        return errors  # other checks depend on exercises structure

    for ei, ex in enumerate(exercises):
        if not isinstance(ex, dict):
            errors.append(f"Exercise #{ei+1} is invalid.")
            continue

        name = str(ex.get("name") or "").strip()
        if not name:
            errors.append(f"Exercise #{ei+1}: name is required.")

        sets_ = ex.get("sets")
        if not isinstance(sets_, list) or len(sets_) == 0:
            errors.append(f"Exercise '{name or ei+1}': at least one set is required.")
            continue

        for si, s in enumerate(sets_):
            if not isinstance(s, dict):
                errors.append(f"Exercise '{name or ei+1}' set #{si+1} is invalid.")
                continue

            reps = s.get("reps")
            weight = s.get("weight")

            try:
                reps_int = int(reps)
            except (TypeError, ValueError):
                reps_int = None

            try:
                weight_num = float(weight)
            except (TypeError, ValueError):
                weight_num = None

            if reps_int is None or reps_int < 1:
                errors.append(f"Exercise '{name or ei+1}' set #{si+1}: reps must be >= 1.")
            if weight_num is None or weight_num < 0:
                errors.append(f"Exercise '{name or ei+1}' set #{si+1}: weight must be >= 0.")

    return errors


# ----------------------------
# DB operations
# ----------------------------

def get_user_email(db_path: str, user_id: str, username: str) -> Optional[str]:
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT email FROM user_emails WHERE user_id = ? OR username = ? ORDER BY id DESC LIMIT 1;",
            (user_id, username),
        ).fetchone()
        if not row:
            return None
        return str(row["email"])
    finally:
        conn.close()


def upsert_user_email(db_path: str, user_id: str, username: str, email: str) -> None:
    conn = get_db_connection(db_path)
    now = datetime.now(UTC).isoformat()
    try:
        conn.execute(
            """
            INSERT INTO user_emails (user_id, username, email, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                email = excluded.email,
                updated_at = excluded.updated_at;
            """,
            (user_id, username, email, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def list_workouts(db_path: str, user_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                w.id,
                w.workout_date,
                COALESCE(w.title, '') AS title,
                w.created_at,
                w.updated_at,
                COUNT(DISTINCT e.id) AS exercise_count,
                COUNT(s.id) AS set_count
            FROM workouts w
            LEFT JOIN exercises e ON e.workout_id = w.id
            LEFT JOIN sets s ON s.exercise_id = e.id
            WHERE w.user_id = ?
            GROUP BY w.id
            ORDER BY w.workout_date DESC, w.id DESC;
            """,
            (user_id,),
        ).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_workout(db_path: str, workout_id: int, user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        w = conn.execute(
            """
            SELECT id, workout_date, COALESCE(title, '') AS title, created_at, updated_at
            FROM workouts
            WHERE id = ? AND user_id = ?;
            """,
            (workout_id, user_id),
        ).fetchone()

        if w is None:
            return None

        exercises_rows = conn.execute(
            """
            SELECT id, name, sort_order
            FROM exercises
            WHERE workout_id = ?
            ORDER BY sort_order ASC, id ASC;
            """,
            (workout_id,),
        ).fetchall()

        exercises: List[Dict[str, Any]] = []
        for ex in exercises_rows:
            sets_rows = conn.execute(
                """
                SELECT id, set_number, reps, weight
                FROM sets
                WHERE exercise_id = ?
                ORDER BY set_number ASC, id ASC;
                """,
                (ex["id"],),
            ).fetchall()

            exercises.append(
                {
                    "id": ex["id"],
                    "name": ex["name"],
                    "sort_order": ex["sort_order"],
                    "sets": [dict(sr) for sr in sets_rows],
                }
            )

        return {
            "id": w["id"],
            "workout_date": w["workout_date"],
            "title": w["title"],
            "created_at": w["created_at"],
            "updated_at": w["updated_at"],
            "exercises": exercises,
        }
    finally:
        conn.close()


def create_workout(db_path: str, payload: Dict[str, Any], user_id: str) -> int:
    conn = get_db_connection(db_path)
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO workouts (user_id, workout_date, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (user_id, _parse_iso_date(payload["workout_date"]), (payload.get("title") or "").strip() or None, now, now),
            )
            workout_id = int(cur.lastrowid)

            exercises = payload["exercises"]
            for sort_order, ex in enumerate(exercises, start=1):
                ex_cur = conn.execute(
                    """
                    INSERT INTO exercises (workout_id, name, sort_order)
                    VALUES (?, ?, ?);
                    """,
                    (workout_id, str(ex["name"]).strip(), sort_order),
                )
                exercise_id = int(ex_cur.lastrowid)
                for set_number, s in enumerate(ex["sets"], start=1):
                    conn.execute(
                        """
                        INSERT INTO sets (exercise_id, set_number, reps, weight)
                        VALUES (?, ?, ?, ?);
                        """,
                        (exercise_id, set_number, int(s["reps"]), float(s["weight"])),
                    )
        return workout_id
    finally:
        conn.close()


def update_workout(db_path: str, workout_id: int, payload: Dict[str, Any], user_id: str) -> bool:
    """
    Update by rewriting the workout's exercises+sets inside a transaction.
    This is simple, reliable, and avoids partial update states.
    """
    conn = get_db_connection(db_path)
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    try:
        with conn:
            exists = conn.execute("SELECT 1 FROM workouts WHERE id = ? AND user_id = ?;", (workout_id, user_id)).fetchone()
            if exists is None:
                return False

            conn.execute(
                """
                UPDATE workouts
                SET workout_date = ?, title = ?, updated_at = ?
                WHERE id = ? AND user_id = ?;
                """,
                (_parse_iso_date(payload["workout_date"]), (payload.get("title") or "").strip() or None, now, workout_id, user_id),
            )

            # Delete existing children (CASCADE handles sets)
            conn.execute("DELETE FROM exercises WHERE workout_id = ?;", (workout_id,))

            exercises = payload["exercises"]
            for sort_order, ex in enumerate(exercises, start=1):
                ex_cur = conn.execute(
                    """
                    INSERT INTO exercises (workout_id, name, sort_order)
                    VALUES (?, ?, ?);
                    """,
                    (workout_id, str(ex["name"]).strip(), sort_order),
                )
                exercise_id = int(ex_cur.lastrowid)
                for set_number, s in enumerate(ex["sets"], start=1):
                    conn.execute(
                        """
                        INSERT INTO sets (exercise_id, set_number, reps, weight)
                        VALUES (?, ?, ?, ?);
                        """,
                        (exercise_id, set_number, int(s["reps"]), float(s["weight"])),
                    )
        return True
    finally:
        conn.close()


def delete_workout(db_path: str, workout_id: int, user_id: str) -> bool:
    conn = get_db_connection(db_path)
    try:
        with conn:
            cur = conn.execute("DELETE FROM workouts WHERE id = ? AND user_id = ?;", (workout_id, user_id))
            return cur.rowcount > 0
    finally:
        conn.close()

def delete_workouts_by_ids(db_path: str, workout_ids: List[int], user_id: str) -> int:
    unique_ids = sorted(set(int(i) for i in workout_ids if int(i) > 0))
    if not unique_ids:
        return 0

    placeholders = ", ".join(["?"] * len(unique_ids))
    conn = get_db_connection(db_path)
    try:
        with conn:
            cur = conn.execute(f"DELETE FROM workouts WHERE user_id = ? AND id IN ({placeholders});", (user_id, *tuple(unique_ids)))
            return int(cur.rowcount)
    finally:
        conn.close()


def delete_all_workouts(db_path: str, user_id: str) -> int:
    conn = get_db_connection(db_path)
    try:
        with conn:
            cur = conn.execute("DELETE FROM workouts WHERE user_id = ?;", (user_id,))
            return int(cur.rowcount)
    finally:
        conn.close()


# ----------------------------
# Demo data (for responsiveness demo)
# ----------------------------

def seed_sample_data(db_path: str, user_id: str, count: int = 200) -> int:
    """
    Inserts 'count' fake workouts quickly for demonstrating responsiveness.
    """
    import random

    exercises_pool = [
        "Bench Press", "Squat", "Deadlift", "Overhead Press",
        "Barbell Row", "Lat Pulldown", "Pull-up", "Dumbbell Curl",
        "Tricep Pushdown", "Leg Press", "Calf Raise",
    ]

    def random_workout_payload(d: date) -> Dict[str, Any]:
        ex_count = random.randint(1, 4)
        picked = random.sample(exercises_pool, ex_count)
        exercises: List[Dict[str, Any]] = []
        for ex_name in picked:
            set_count = random.randint(1, 5)
            sets = []
            for _ in range(set_count):
                reps = random.randint(3, 12)
                weight = round(random.uniform(0, 315), 1)
                sets.append({"reps": reps, "weight": weight})
            exercises.append({"name": ex_name, "sets": sets})
        return {"workout_date": d.isoformat(), "title": None, "exercises": exercises}

    created = 0
    start_day = date.today()
    conn = get_db_connection(db_path)
    try:
        with conn:
            for i in range(count):
                d = start_day.fromordinal(start_day.toordinal() - i)
                payload = random_workout_payload(d)
                # reuse create_workout logic but inline for speed
                now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                cur = conn.execute(
                    "INSERT INTO workouts (user_id, workout_date, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
                    (user_id, payload["workout_date"], None, now, now),
                )
                workout_id = int(cur.lastrowid)
                for sort_order, ex in enumerate(payload["exercises"], start=1):
                    ex_cur = conn.execute(
                        "INSERT INTO exercises (workout_id, name, sort_order) VALUES (?, ?, ?);",
                        (workout_id, ex["name"], sort_order),
                    )
                    ex_id = int(ex_cur.lastrowid)
                    for set_number, s in enumerate(ex["sets"], start=1):
                        conn.execute(
                            "INSERT INTO sets (exercise_id, set_number, reps, weight) VALUES (?, ?, ?, ?);",
                            (ex_id, set_number, int(s["reps"]), float(s["weight"])),
                        )
                created += 1
        return created
    finally:
        conn.close()


# ----------------------------
# Main entrypoint
# ----------------------------

app = create_app()

if __name__ == "__main__":
    # Debug=True for local use. Do not enable in production.
    app.run(host="127.0.0.1", port=5000, debug=True)
