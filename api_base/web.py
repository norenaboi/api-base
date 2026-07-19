from __future__ import annotations

import hmac
import json
import os
import secrets
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from api_base.exchange import (
    DataFormatError,
    export_json_data,
    import_json_data,
    normalize_record,
)
from api_base.refresh import refresh_all, refresh_key
from api_base.vault import DuplicateKeyError, Vault, VaultError, VaultKeyMaterial


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    default_database = Path.home() / ".local" / "share" / "api-base" / "vault.sqlite3"
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("API_BASE_SESSION_SECRET", secrets.token_hex(32)),
        DATABASE=os.environ.get("API_BASE_DATABASE", str(default_database)),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
    )
    if test_config:
        app.config.update(test_config)

    app.extensions["vault"] = Vault(app.config["DATABASE"])
    app.extensions["vault_keys"] = None

    def vault() -> Vault:
        return app.extensions["vault"]

    def unlocked_keys() -> VaultKeyMaterial | None:
        return app.extensions.get("vault_keys")

    def csrf_token() -> str:
        token = session.get("csrf_token")
        if not isinstance(token, str):
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def protect_post_requests() -> None:
        if request.method != "POST":
            return
        expected = session.get("csrf_token")
        supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not isinstance(expected, str) or not isinstance(supplied, str):
            abort(400, "Missing CSRF token.")
        if not hmac.compare_digest(expected, supplied):
            abort(400, "Invalid CSRF token.")

    @app.after_request
    def set_security_headers(response: Any) -> Any:
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    def require_unlocked(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if unlocked_keys() is None:
                flash("Unlock the vault first.", "error")
                return redirect(url_for("index"))
            return view(*args, **kwargs)

        return wrapped

    def wants_json() -> bool:
        return request.accept_mimetypes.best == "application/json"

    def row_data(record_id: int) -> dict[str, Any]:
        record = vault().get_key(record_id)
        return {
            "record_id": record_id,
            "html": render_template("_key_rows.html", record=record),
        }

    def row_payload(record_id: int, *, message: str = "") -> Any:
        return jsonify({**row_data(record_id), "message": message})

    def mutation_error(error: Exception, status: int = 400) -> Any:
        if wants_json():
            return jsonify({"error": str(error)}), status
        flash(str(error), "error")
        return redirect(url_for("index"))

    @app.get("/healthz")
    def healthz() -> Any:
        return jsonify({"status": "ok"})

    @app.get("/")
    def index() -> str:
        if not vault().is_initialized():
            return render_template("index.html", state="setup")
        if unlocked_keys() is None:
            return render_template("index.html", state="locked")

        sort_by = request.args.get("sort", "id")
        direction = request.args.get("direction", "asc")
        model = request.args.get("model") or None
        include_trashed = request.args.get("trashed", "") == "1"
        try:
            records = vault().list_keys(
                sort_by=sort_by, direction=direction, model=model,
                include_trashed=include_trashed,
            )
        except ValueError:
            records = vault().list_keys(include_trashed=include_trashed)
            sort_by = "id"
            direction = "asc"
        all_models = vault().list_models()
        return render_template(
            "index.html",
            state="unlocked",
            records=records,
            all_models=all_models,
            selected_model=model or "",
            sort_by=sort_by,
            direction=direction,
            include_trashed=include_trashed,
        )

    @app.post("/setup")
    def setup() -> Any:
        if vault().is_initialized():
            abort(409, "Vault is already initialized.")
        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirm", "")
        if password != confirmation:
            flash("The passwords do not match.", "error")
            return redirect(url_for("index"))
        try:
            vault().initialize(password)
            app.extensions["vault_keys"] = vault().unlock(password)
        except VaultError as error:
            flash(str(error), "error")
            return redirect(url_for("index"))
        session.clear()
        flash("Vault created and unlocked.", "success")
        return redirect(url_for("index"))

    @app.post("/unlock")
    def unlock() -> Any:
        if not vault().is_initialized():
            return redirect(url_for("index"))
        try:
            app.extensions["vault_keys"] = vault().unlock(request.form.get("password", ""))
        except VaultError as error:
            flash(str(error), "error")
        else:
            session.clear()
            flash("Vault unlocked.", "success")
        return redirect(url_for("index"))

    @app.post("/lock")
    def lock() -> Any:
        app.extensions["vault_keys"] = None
        session.clear()
        flash("Vault locked.", "success")
        return redirect(url_for("index"))

    @app.post("/keys")
    @require_unlocked
    def add_key() -> Any:
        try:
            raw_record = {
                "name": request.form.get("name"),
                "typeofkey": request.form.get("typeofkey"),
                "key": request.form.get("key"),
                "status_code": _optional_status(request.form.get("status_code")),
                "models": request.form.get("models", ""),
                "user_comment": request.form.get("user_comment", ""),
                "check_model": request.form.get("check_model", "") or None,
            }
            record = normalize_record(raw_record)
            record_id = vault().create_key(unlocked_keys(), **record)  # type: ignore[arg-type]
        except (DuplicateKeyError, TypeError, ValueError) as error:
            return mutation_error(error)
        if wants_json():
            return row_payload(record_id, message="API key added.")
        flash("API key added.", "success")
        return redirect(url_for("index"))

    @app.post("/keys/<int:record_id>/edit")
    @require_unlocked
    def edit_key(record_id: int) -> Any:
        replacement_key = request.form.get("key", "").strip()
        try:
            raw_record = {
                "name": request.form.get("name"),
                "typeofkey": request.form.get("typeofkey"),
                "key": replacement_key or "unchanged-key-placeholder",
                "status_code": _optional_status(request.form.get("status_code")),
                "models": request.form.get("models", ""),
                "user_comment": request.form.get("user_comment", ""),
                "check_model": request.form.get("check_model", "") or None,
            }
            record = normalize_record(raw_record)
            vault().update_key(
                unlocked_keys(),  # type: ignore[arg-type]
                record_id,
                name=record["name"],
                key_type=record["key_type"],
                api_key=replacement_key or None,
                status_code=record["status_code"],
                models=record["models"],
                user_comment=record["user_comment"],
                check_model=record["check_model"],
            )
        except (VaultError, TypeError, ValueError) as error:
            return mutation_error(error)
        if wants_json():
            return row_payload(record_id, message="API key updated.")
        flash("API key updated.", "success")
        return redirect(url_for("index"))

    @app.post("/keys/<int:record_id>/reveal")
    @require_unlocked
    def reveal_key(record_id: int) -> Any:
        try:
            api_key = vault().reveal_key(unlocked_keys(), record_id)  # type: ignore[arg-type]
        except VaultError as error:
            return jsonify({"error": str(error)}), 404
        return jsonify({"key": api_key})

    @app.post("/keys/<int:record_id>/delete")
    @require_unlocked
    def delete_key(record_id: int) -> Any:
        try:
            vault().delete_key(record_id)
        except VaultError as error:
            return mutation_error(error, 404)
        if wants_json():
            return jsonify(
                {"record_id": record_id, "removed": True, "message": "API key deleted."}
            )
        flash("API key deleted.", "success")
        return redirect(url_for("index"))

    @app.post("/keys/<int:record_id>/trash")
    @require_unlocked
    def trash_key(record_id: int) -> Any:
        trashed = request.form.get("trashed", "1") == "1"
        try:
            vault().set_trashed(record_id, trashed)
        except VaultError as error:
            return mutation_error(error, 404)
        message = "API key moved to trash." if trashed else "API key restored."
        if wants_json():
            if trashed and request.form.get("include_trashed", "0") != "1":
                return jsonify({"record_id": record_id, "removed": True, "message": message})
            return row_payload(record_id, message=message)
        flash(message, "success")
        return redirect(url_for("index"))

    @app.post("/keys/<int:record_id>/refresh")
    @require_unlocked
    def refresh_one(record_id: int) -> Any:
        try:
            result = refresh_key(
                vault(),
                unlocked_keys(),  # type: ignore[arg-type]
                record_id,
                transport=app.config.get("HTTP_TRANSPORT"),
            )
        except VaultError as error:
            return mutation_error(error, 404)
        message = result.error or f"Refreshed key; found {len(result.models)} models."
        if wants_json():
            return row_payload(record_id, message=message)
        flash(message, "warning" if result.error else "success")
        return redirect(url_for("index"))

    @app.post("/refresh-all")
    @require_unlocked
    def refresh_every_key() -> Any:
        record_ids: list[int] | None = None
        raw_ids = request.form.get("record_ids", "").strip()
        if raw_ids:
            try:
                record_ids = [int(part) for part in raw_ids.split(",") if part.strip()]
            except ValueError:
                return mutation_error(ValueError("Invalid record ids for refresh."))
        try:
            results = refresh_all(
                vault(),
                unlocked_keys(),  # type: ignore[arg-type]
                record_ids=record_ids,
                transport=app.config.get("HTTP_TRANSPORT"),
            )
        except VaultError as error:
            flash(str(error), "error")
            return redirect(url_for("index"))
        failures = sum(result.error is not None for result in results.values())
        message = f"Refreshed {len(results)} keys; {failures} returned errors."
        if wants_json():
            return jsonify(
                {
                    "rows": [row_data(record_id) for record_id in results],
                    "message": message,
                    "failures": failures,
                }
            )
        category = "warning" if failures else "success"
        flash(message, category)
        return redirect(url_for("index"))

    @app.post("/import")
    @require_unlocked
    def import_json() -> Any:
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            flash("Choose a JSON file to import.", "error")
            return redirect(url_for("index"))
        try:
            payload = json.load(upload.stream)
            summary = import_json_data(vault(), unlocked_keys(), payload)  # type: ignore[arg-type]
        except (DataFormatError, UnicodeDecodeError, json.JSONDecodeError) as error:
            flash(f"Import failed: {error}", "error")
            return redirect(url_for("index"))

        duplicate_word = "duplicate" if summary["duplicates_skipped"] == 1 else "duplicates"
        flash(
            f"Imported {summary['imported']}; skipped {summary['duplicates_skipped']} "
            f"{duplicate_word}; {summary['error_count']} errors.",
            "success" if not summary["errors"] else "warning",
        )
        return redirect(url_for("index"))

    @app.post("/export/json")
    @require_unlocked
    def export_json() -> Response:
        payload = export_json_data(vault(), unlocked_keys())  # type: ignore[arg-type]
        body = json.dumps(payload, indent=2, ensure_ascii=False)
        return Response(
            body,
            mimetype="application/json",
            headers={"Content-Disposition": 'attachment; filename="api-base-keys.json"'},
        )

    @app.post("/export/database")
    @require_unlocked
    def export_database() -> Any:
        return send_file(
            vault().database_path,
            as_attachment=True,
            download_name="api-base-vault.sqlite3",
            mimetype="application/vnd.sqlite3",
            conditional=False,
        )

    return app


def _optional_status(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError as error:
        raise ValueError("Status code must be an integer from 100 through 599.") from error
