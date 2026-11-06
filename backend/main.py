import asyncio
import inspect
import json
import logging
import os
import secrets
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import Settings, get_logger
from backend.config import settings as default_settings
from backend.models import (
    DEFAULT_PRICE_SOURCES,
    Draft,
    ImageVariantMode,
    PresetSettings,
    UpdateDraftRequest,
)
from backend.path_utils import PathTraversalError
from backend.services.ai_service import AIService
from backend.services.image_service import ImageService
from backend.storage import (
    BatchLimitExceededError,
    DraftNotFoundError,
    DraftStore,
    FileTooLargeError,
    RevisionConflictError,
    StorageCorruptedError,
    StorageService,
)

logger = get_logger("occaision.api")


def configure_logging(level_name: Optional[str] = None):
    """Set log level on all occaision.* loggers based on CLI args, env var, or config."""
    cli_level = None
    for i, arg in enumerate(sys.argv):
        if arg in ("--log-level", "-l") and i + 1 < len(sys.argv):
            cli_level = sys.argv[i + 1].upper()
            break
        elif arg.startswith("--log-level="):
            cli_level = arg.split("=", 1)[1].upper()
            break

    effective_name = (
        cli_level
        or os.environ.get("LOG_LEVEL")
        or level_name
        or "INFO"
    ).upper()

    level = getattr(logging, effective_name, logging.INFO)

    for name in ["occaision", "occaision.api", "occaision.image", "occaision.ai", "occaision.ebay"]:
        named_logger = logging.getLogger(name)
        named_logger.setLevel(level)

    if level == logging.DEBUG:
        logger.info("[Logging] Debug-Logging ist AKTIV (vollständige Prompts und Antworten werden ausgegeben).")


def get_or_create_auth_token(data_dir: Path) -> str:
    """Read or generate local auth token stored in data_dir."""
    data_dir.mkdir(parents=True, exist_ok=True)
    token_path = data_dir / "auth_token.txt"
    if token_path.exists():
        t = token_path.read_text(encoding="utf-8").strip()
        if t:
            return t
    token = secrets.token_urlsafe(32)
    token_path.write_text(token, encoding="utf-8")
    try:
        token_path.chmod(0o600)
    except OSError:
        pass
    return token


def load_persisted_config(data_dir: Path) -> dict:
    config_path = data_dir / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[Config] Error reading {config_path}: {e}")
            return {}
    return {}


def save_persisted_config(data_dir: Path, updates: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    config_path = data_dir / "config.json"
    current = load_persisted_config(data_dir)
    current.update(updates)
    config_path.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        config_path.chmod(0o600)
    except OSError:
        pass


def _save_to_env(updates: dict) -> None:
    env_path = Path(".env")
    if not env_path.exists() or "pytest" in sys.modules:
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
        keys_found = set()
        new_lines = []
        for line in lines:
            matched = False
            for k, v in updates.items():
                if line.startswith(f"{k}="):
                    new_lines.append(f"{k}={v}")
                    keys_found.add(k)
                    matched = True
                    break
            if not matched:
                new_lines.append(line)
        for k, v in updates.items():
            if k not in keys_found:
                new_lines.append(f"{k}={v}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        logger.info(f"[Config] {', '.join(updates.keys())} in .env gespeichert.")
    except Exception as e:
        logger.warning(f"Fehler beim Speichern in .env: {e}")


class CreateDraftRequest(BaseModel):
    user_notes: str = ""
    identified_product: str = ""


class PairRequest(BaseModel):
    pairing_code: Optional[str] = None


class PatchImageModeRequest(BaseModel):
    active_mode: ImageVariantMode


class UpdateSystemConfigRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    enable_search_grounding: Optional[bool] = None
    eur_to_chf_rate: Optional[float] = None


def merge_analysis_results(base: Draft, current: Draft, analyzed: Draft) -> Draft:
    """Merge AI analysis results into current draft preserving any fields modified by the user."""
    # Ricardo
    if current.ricardo.title == base.ricardo.title:
        current.ricardo.title = analyzed.ricardo.title
    if current.ricardo.description == base.ricardo.description:
        current.ricardo.description = analyzed.ricardo.description
    if current.ricardo.condition == base.ricardo.condition:
        current.ricardo.condition = analyzed.ricardo.condition
    if current.ricardo.start_price_chf == base.ricardo.start_price_chf:
        current.ricardo.start_price_chf = analyzed.ricardo.start_price_chf
    if current.ricardo.buynow_price_chf == base.ricardo.buynow_price_chf:
        current.ricardo.buynow_price_chf = analyzed.ricardo.buynow_price_chf

    # Tutti
    if current.tutti.title == base.tutti.title:
        current.tutti.title = analyzed.tutti.title
    if current.tutti.description == base.tutti.description:
        current.tutti.description = analyzed.tutti.description
    if current.tutti.category_suggestion == base.tutti.category_suggestion:
        current.tutti.category_suggestion = analyzed.tutti.category_suggestion
    if current.tutti.condition == base.tutti.condition:
        current.tutti.condition = analyzed.tutti.condition
    if current.tutti.price_vhb_chf == base.tutti.price_vhb_chf:
        current.tutti.price_vhb_chf = analyzed.tutti.price_vhb_chf

    # eBay DE
    if current.ebay_de.title == base.ebay_de.title:
        current.ebay_de.title = analyzed.ebay_de.title
    if current.ebay_de.description == base.ebay_de.description:
        current.ebay_de.description = analyzed.ebay_de.description
    if current.ebay_de.category_suggestion == base.ebay_de.category_suggestion:
        current.ebay_de.category_suggestion = analyzed.ebay_de.category_suggestion
    if current.ebay_de.condition == base.ebay_de.condition:
        current.ebay_de.condition = analyzed.ebay_de.condition
    if current.ebay_de.start_price_eur == base.ebay_de.start_price_eur:
        current.ebay_de.start_price_eur = analyzed.ebay_de.start_price_eur
    if current.ebay_de.buynow_price_eur == base.ebay_de.buynow_price_eur:
        current.ebay_de.buynow_price_eur = analyzed.ebay_de.buynow_price_eur

    # Kleinanzeigen
    if current.kleinanzeigen.title == base.kleinanzeigen.title:
        current.kleinanzeigen.title = analyzed.kleinanzeigen.title
    if current.kleinanzeigen.description == base.kleinanzeigen.description:
        current.kleinanzeigen.description = analyzed.kleinanzeigen.description
    if current.kleinanzeigen.category_suggestion == base.kleinanzeigen.category_suggestion:
        current.kleinanzeigen.category_suggestion = analyzed.kleinanzeigen.category_suggestion
    if current.kleinanzeigen.condition == base.kleinanzeigen.condition:
        current.kleinanzeigen.condition = analyzed.kleinanzeigen.condition
    if current.kleinanzeigen.price_eur == base.kleinanzeigen.price_eur:
        current.kleinanzeigen.price_eur = analyzed.kleinanzeigen.price_eur
    if current.kleinanzeigen.price_type == base.kleinanzeigen.price_type:
        current.kleinanzeigen.price_type = analyzed.kleinanzeigen.price_type

    # Identified product
    if not current.identified_product or current.identified_product == base.identified_product:
        current.identified_product = analyzed.identified_product

    # Hints, Price Analysis & Status
    current.price_analysis = analyzed.price_analysis
    current.missing_photo_hints = analyzed.missing_photo_hints
    current.status = analyzed.status

    return current


def create_app(
    settings: Optional[Settings] = None,
    draft_store: Optional[DraftStore] = None,
    storage_service: Optional[StorageService] = None,
    image_service: Optional[ImageService] = None,
    ai_service: Optional[AIService] = None,
) -> FastAPI:
    cfg = settings or default_settings
    persisted = load_persisted_config(cfg.data_dir)
    if persisted:
        if "gemini_model" in persisted and "GEMINI_MODEL" not in os.environ:
            cfg.gemini_model = persisted["gemini_model"]
        if "enable_search_grounding" in persisted and "ENABLE_SEARCH_GROUNDING" not in os.environ:
            cfg.enable_search_grounding = persisted["enable_search_grounding"]
        if "gemini_api_key" in persisted and "GEMINI_API_KEY" not in os.environ:
            cfg.gemini_api_key = persisted["gemini_api_key"]
        if "eur_to_chf_rate" in persisted and "EUR_TO_CHF_RATE" not in os.environ:
            try:
                cfg.eur_to_chf_rate = float(persisted["eur_to_chf_rate"])
            except (ValueError, TypeError):
                pass

    configure_logging(cfg.log_level)
    img_svc = image_service or getattr(draft_store or storage_service, "image_service", None) or ImageService(
        data_dir=cfg.data_dir,
        rembg_model=cfg.rembg_model,
    )
    storage = draft_store or storage_service or DraftStore(data_dir=cfg.data_dir, image_service=img_svc)
    if image_service is not None:
        storage.image_service = image_service
    storage.cleanup_orphaned_images()
    ai_svc = ai_service or AIService(
        api_key=cfg.gemini_api_key,
        model_name=cfg.gemini_model,
        enable_search_grounding=cfg.enable_search_grounding,
        eur_to_chf=cfg.eur_to_chf_rate,
    )

    app = FastAPI(
        title="OccAIsion",
        version="1.0.0",
    )
    auth_token = get_or_create_auth_token(cfg.data_dir)
    active_analyses: set[str] = set()
    active_analyses_lock = threading.Lock()
    pairing_codes: dict[str, float] = {}
    pairing_lock = threading.Lock()

    def is_trusted_origin(origin: Optional[str]) -> bool:
        if not origin:
            return False
        try:
            parsed = urllib.parse.urlsplit(origin)
        except Exception:
            return False

        if parsed.scheme == "moz-extension":
            return bool(parsed.netloc or parsed.path)
        if parsed.scheme in ("http", "https"):
            host = (parsed.hostname or "").lower()
            return host in {"127.0.0.1", "localhost", "testserver"}
        return False

    @app.middleware("http")
    async def validate_host_header(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0].lower()
        allowed_hosts = {"127.0.0.1", "localhost", "testserver"}
        if host and host not in allowed_hosts:
            return JSONResponse(status_code=403, content={"detail": f"Untrusted Host: {host}"})
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            "http://127.0.0.1",
            "http://localhost",
        ],
        allow_origin_regex=r"^moz-extension://.*",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        # When auth is disabled in settings (e.g. routine pytest suite)
        if not cfg.require_auth:
            return await call_next(request)

        # Public paths
        if (
            path == "/api/health"
            or path == "/health"
            or path == "/api/auth/pair"
            or not path.startswith("/api/")
        ):
            response = await call_next(request)
            if path == "/":
                response.set_cookie(
                    key="occaision_token",
                    value=auth_token,
                    httponly=True,
                    samesite="strict",
                    path="/",
                )
            return response

        # Check Bearer token or session cookie
        auth_header = request.headers.get("authorization", "")
        has_bearer = auth_header.startswith("Bearer ") and secrets.compare_digest(
            auth_header[7:].strip(), auth_token
        )
        cookie_token = request.cookies.get("occaision_token", "")
        has_cookie = bool(cookie_token and secrets.compare_digest(cookie_token, auth_token))

        if not (has_bearer or has_cookie):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication required"},
            )

        return await call_next(request)

    @app.middleware("http")
    async def add_no_cache_for_static(request, call_next):
        response = await call_next(request)
        if request.url.path.endswith((".css", ".js", ".html")) or request.url.path == "/":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "img-src 'self' data: blob:; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; "
                "connect-src 'self' http://127.0.0.1:8000 http://localhost:8000;"
            )
        return response

    @app.exception_handler(StorageCorruptedError)
    def handle_storage_corrupted(request: Request, exc: StorageCorruptedError):
        logger.critical(f"Storage corruption detected: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Speicherdatei beschädigt. Ein automatisches Backup wurde angelegt: {exc}",
                "error_code": "STORAGE_CORRUPTED",
            },
        )

    # 0. Pairing
    @app.post("/api/auth/pairing-code")
    def create_pairing_code(request: Request):
        now = time.time()
        with pairing_lock:
            # Prune expired codes
            expired = [c for c, exp in pairing_codes.items() if exp < now]
            for c in expired:
                del pairing_codes[c]

            code = f"{secrets.randbelow(900000) + 100000:06d}"
            pairing_codes[code] = now + 60.0
        return {"ok": True, "pairing_code": code, "expires_in": 60}

    @app.post("/api/auth/pair")
    def pair_extension(request: Request, body: Optional[PairRequest] = None):
        origin = request.headers.get("origin")
        if not is_trusted_origin(origin):
            raise HTTPException(status_code=403, detail="Untrusted origin")

        # 1. If already authenticated via session cookie or bearer token, pairing succeeds immediately
        auth_header = request.headers.get("authorization", "")
        has_bearer = auth_header.startswith("Bearer ") and secrets.compare_digest(
            auth_header[7:].strip(), auth_token
        )
        cookie_token = request.cookies.get("occaision_token", "")
        has_cookie = bool(cookie_token and secrets.compare_digest(cookie_token, auth_token))

        if has_bearer or has_cookie or not cfg.require_auth:
            return {"ok": True, "token": auth_token}

        # 2. Otherwise, valid single-use pairing code is required
        if not body or not body.pairing_code:
            raise HTTPException(status_code=401, detail="Valid pairing code required")

        code = body.pairing_code.strip()
        now = time.time()
        with pairing_lock:
            exp = pairing_codes.get(code)
            if not exp or exp < now:
                if code in pairing_codes:
                    del pairing_codes[code]
                raise HTTPException(status_code=401, detail="Invalid or expired pairing code")
            # Single-use: consume immediately
            del pairing_codes[code]

        return {"ok": True, "token": auth_token}

    # 1. Health
    @app.get("/api/health")
    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "model": cfg.gemini_model,
            "api_key_configured": bool(cfg.gemini_api_key and cfg.gemini_api_key.strip()),
            "data_dir_writable": os.access(cfg.data_dir, os.W_OK),
            "version": "1.1.0",
        }

    # 2. Settings
    @app.get("/api/settings", response_model=PresetSettings)
    def get_settings():
        return storage.get_settings()

    @app.put("/api/settings", response_model=PresetSettings)
    def update_settings(new_settings: PresetSettings):
        return storage.update_settings(new_settings)

    @app.get("/api/config")
    def get_system_config():
        # If key is missing or default placeholder, re-read directly from .env
        if not cfg.gemini_api_key or cfg.gemini_api_key == "your_google_ai_studio_api_key_here":
            env_file = Path(".env")
            if env_file.exists():
                try:
                    for line in env_file.read_text(encoding="utf-8").splitlines():
                        if line.startswith("GEMINI_API_KEY="):
                            val = line.split("=", 1)[1].strip()
                            if val and val != "your_google_ai_studio_api_key_here":
                                cfg.gemini_api_key = val
                                ai_svc.set_api_key(val, model_name=cfg.gemini_model)
                                break
                except Exception:
                    pass

        key = cfg.gemini_api_key or ""
        has_key = bool(
            key
            and key != "your_google_ai_studio_api_key_here"
            and len(key.strip()) > 15
        )
        masked = ""
        if has_key:
            clean_key = key.strip()
            masked = f"{clean_key[:4]}...{clean_key[-4:]}"

        # Auto-upgrade deprecated gemini-2.5-flash / gemini-2.0-flash to gemini-3.8-flash removed: GET is idempotent and read-only

        available_models = ai_svc.get_available_models()

        return {
            "gemini_api_key_configured": has_key,
            "gemini_model": cfg.gemini_model,
            "enable_search_grounding": cfg.enable_search_grounding,
            "masked_key": masked,
            "eur_to_chf_rate": cfg.eur_to_chf_rate,
            "available_models": available_models,
        }

    @app.get("/api/models")
    def get_models():
        return ai_svc.get_available_models()

    @app.post("/api/config")
    def update_system_config(body: UpdateSystemConfigRequest):
        env_updates = {}
        persisted_updates = {}
        if body.gemini_model:
            cfg.gemini_model = body.gemini_model
            ai_svc.model_name = body.gemini_model
            env_updates["GEMINI_MODEL"] = cfg.gemini_model
            persisted_updates["gemini_model"] = cfg.gemini_model

        if body.enable_search_grounding is not None:
            cfg.enable_search_grounding = body.enable_search_grounding
            ai_svc.enable_search_grounding = body.enable_search_grounding
            env_updates["ENABLE_SEARCH_GROUNDING"] = "true" if cfg.enable_search_grounding else "false"
            persisted_updates["enable_search_grounding"] = cfg.enable_search_grounding

        if body.gemini_api_key is not None and body.gemini_api_key.strip():
            new_key = body.gemini_api_key.strip()
            cfg.gemini_api_key = new_key
            ai_svc.set_api_key(new_key, model_name=cfg.gemini_model)
            env_updates["GEMINI_API_KEY"] = new_key
            persisted_updates["gemini_api_key"] = new_key
            if "GEMINI_MODEL" not in env_updates:
                env_updates["GEMINI_MODEL"] = cfg.gemini_model
                persisted_updates["gemini_model"] = cfg.gemini_model
            if "ENABLE_SEARCH_GROUNDING" not in env_updates:
                env_updates["ENABLE_SEARCH_GROUNDING"] = "true" if cfg.enable_search_grounding else "false"
                persisted_updates["enable_search_grounding"] = cfg.enable_search_grounding

        if body.eur_to_chf_rate is not None and body.eur_to_chf_rate > 0:
            cfg.eur_to_chf_rate = round(float(body.eur_to_chf_rate), 4)
            ai_svc.eur_to_chf = cfg.eur_to_chf_rate
            env_updates["EUR_TO_CHF_RATE"] = str(cfg.eur_to_chf_rate)
            persisted_updates["eur_to_chf_rate"] = cfg.eur_to_chf_rate

        if persisted_updates:
            save_persisted_config(cfg.data_dir, persisted_updates)
        if env_updates:
            _save_to_env(env_updates)

        return get_system_config()

    # 3. Drafts CRUD
    @app.get("/api/drafts", response_model=List[Draft])
    def list_drafts():
        return storage.list_drafts()

    @app.post("/api/drafts", response_model=Draft)
    def create_draft(req: Optional[CreateDraftRequest] = None):
        user_notes = req.user_notes if req else ""
        identified_product = req.identified_product if req else ""
        return storage.create_draft(user_notes=user_notes, identified_product=identified_product)

    @app.get("/api/drafts/export")
    def export_drafts():
        data = storage.export_drafts_data()
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        headers = {
            "Content-Disposition": f'attachment; filename="occaision_backup_{now_str}.json"'
        }
        return JSONResponse(content=data, headers=headers)

    @app.post("/api/drafts/import")
    async def import_drafts(
        request: Request,
        overwrite: bool = False,
        file: Optional[UploadFile] = None,
    ):
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type:
            form = await request.form()
            upload = form.get("file")
            if not upload or not hasattr(upload, "read"):
                raise HTTPException(status_code=400, detail="Keine Datei 'file' im Upload gefunden.")
            content_bytes = await upload.read()
            try:
                payload = json.loads(content_bytes.decode("utf-8"))
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Ungültige JSON-Datei: {e}")
            if form.get("overwrite") in ("true", "1", True):
                overwrite = True
        else:
            try:
                payload = await request.json()
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Ungültiges JSON im Request-Body: {e}")

        try:
            return storage.import_drafts_data(payload, overwrite=overwrite)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/drafts/{draft_id}", response_model=Draft)
    def get_draft(draft_id: str):
        try:
            draft = storage.get_draft(draft_id)
        except (ValueError, PathTraversalError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        return draft

    @app.put("/api/drafts/{draft_id}", response_model=Draft)
    def update_draft(draft_id: str, updated_draft: UpdateDraftRequest):
        if updated_draft.id and updated_draft.id != draft_id:
            raise HTTPException(status_code=400, detail="Draft ID mismatch")
        try:
            return storage.update_draft_fields(draft_id, updated_draft)
        except DraftNotFoundError:
            raise HTTPException(status_code=404, detail="Draft not found")
        except RevisionConflictError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except (ValueError, PathTraversalError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/api/drafts/{draft_id}")
    def delete_draft(draft_id: str):
        try:
            success = storage.delete_draft(draft_id)
        except (ValueError, PathTraversalError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not success:
            raise HTTPException(status_code=404, detail="Draft not found")
        return {"ok": True, "message": "Draft deleted"}

    # 4. Images
    @app.post("/api/drafts/{draft_id}/images", response_model=Draft)
    async def upload_images(draft_id: str, files: List[UploadFile] = File(...)):
        logger.info(f"[API] Empfange {len(files)} Bild(er) für Draft {draft_id}...")
        file_payloads: List[Tuple[str, bytes]] = []
        for f in files:
            content = await f.read()
            file_payloads.append((f.filename or "upload.jpg", content))

        try:
            return await asyncio.to_thread(storage.add_images, draft_id, file_payloads)
        except BatchLimitExceededError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except FileTooLargeError as e:
            raise HTTPException(status_code=413, detail=str(e))
        except DraftNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Fehler beim Verarbeiten der Bilder: {e}")

    @app.delete("/api/drafts/{draft_id}/images/{image_id}", response_model=Draft)
    def delete_image(draft_id: str, image_id: str):
        logger.info(f"[API] Lösche Bild {image_id} aus Draft {draft_id}...")
        try:
            return storage.delete_image(draft_id, image_id)
        except DraftNotFoundError:
            raise HTTPException(status_code=404, detail="Draft not found")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Image not found")

    @app.patch("/api/drafts/{draft_id}/images/{image_id}", response_model=Draft)
    async def patch_image_mode(draft_id: str, image_id: str, body: PatchImageModeRequest):
        mode = body.active_mode
        logger.info(f"[API] Moduswechsel für Bild {image_id} auf '{mode.value}' angefordert (Draft: {draft_id})...")
        try:
            updated = await asyncio.to_thread(storage.set_image_mode, draft_id, image_id, mode)
            logger.info(f"[API] Bild {image_id} Modus erfolgreich auf '{mode.value}' gesetzt.")
            return updated
        except DraftNotFoundError:
            raise HTTPException(status_code=404, detail="Draft not found")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Image not found")

    @app.get("/api/drafts/{draft_id}/images/{image_id}/{variant}")
    def get_image_file(draft_id: str, image_id: str, variant: str):
        try:
            file_path = storage.get_image_file_path(draft_id, image_id, variant)
            return FileResponse(file_path, media_type="image/jpeg")
        except (DraftNotFoundError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Image variant not found")
        except (ValueError, PathTraversalError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    # 5. Analysis
    @app.post("/api/drafts/{draft_id}/analyze", response_model=Draft)
    async def analyze_draft(draft_id: str):
        with active_analyses_lock:
            if draft_id in active_analyses:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Analyse für diesen Entwurf läuft bereits. Bitte warten.",
                )
            active_analyses.add(draft_id)

        try:
            logger.info(f"[API] Starte KI- und Preisanalyse für Draft {draft_id}...")
            draft = storage.get_draft(draft_id)
            if not draft:
                raise HTTPException(status_code=404, detail="Draft not found")

            # 0. Load enabled price sources from settings
            preset_settings = storage.get_settings()
            if hasattr(preset_settings, "enabled_price_sources") and preset_settings.enabled_price_sources is not None:
                enabled_sources = preset_settings.enabled_price_sources
            else:
                enabled_sources = list(DEFAULT_PRICE_SOURCES)

            # 1. Check if extension already fetched market prices
            pa = draft.price_analysis
            ebay_stats = pa.ebay_stats if (pa and "ebay_de_sold" in enabled_sources) else None

            # 2. Gather AI input images
            ai_image_paths = storage.get_ai_image_paths(draft_id)

            # 3. Run AI analysis
            try:
                ai_coro = ai_svc.analyze_draft(
                    draft=draft,
                    image_paths=ai_image_paths,
                    ebay_stats=ebay_stats,
                    enabled_sources=enabled_sources,
                )
                if inspect.isawaitable(ai_coro):
                    analyzed_draft = await asyncio.wait_for(ai_coro, timeout=90.0)
                else:
                    analyzed_draft = ai_coro
            except asyncio.TimeoutError:
                logger.error(f"[API] KI-Analyse für Draft {draft_id} überschritt das Timeout (90s).")
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Zeitüberschreitung bei der KI-Analyse (Timeout nach 90 Sekunden). Bitte erneut versuchen.",
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[API] KI-Analyse fehlgeschlagen: {e}")
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=(
                            "Google Gemini Quota-Limit erreicht (429 RESOURCE_EXHAUSTED).\n\n"
                            "Mögliche Ursachen & Lösungen:\n"
                            "1. Kurzzeitiges Limit: Warte ca. 1 Minute und klicke erneut auf Analyse (Rate-Limit pro Minute im Free Tier).\n"
                            "2. Web-Suche deaktivieren: Schalte in den Einstellungen (⚙️) 'Google Search Grounding (Websuche)' aus, da die Live-Suche im Free Tier oft strenger limitiert ist.\n"
                            "3. Wichtig zum Google One / AI Pro Abo: Ein Google One AI Premium Abo gilt nur für den Consumer-Chat (gemini.google.com), nicht für die Entwickler-API (Google AI Studio). Für unbegrenztes API-Volumen kann auf https://aistudio.google.com ein Pay-As-You-Go Billing-Account hinterlegt werden (für Flash-Modelle fallen meist weniger als 0.001 CHF pro Inserat an)."
                        ),
                    )
                if "API_KEY_INVALID" in err_str or "API key not valid" in err_str or "API key" in err_str:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Ungültiger oder fehlender Google Gemini API-Key. Bitte trage deinen API-Key in den Einstellungen (⚙️) oder in der .env-Datei ein.",
                    )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Fehler bei der KI-Analyse: {err_str}",
                )

            current = storage.get_draft(draft_id)
            if not current:
                raise HTTPException(status_code=404, detail="Draft was deleted during analysis")

            merged = merge_analysis_results(base=draft, current=current, analyzed=analyzed_draft)

            try:
                return storage.update_draft(merged)
            except RevisionConflictError as e:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Konflikt beim Speichern der Analyse: Der Entwurf wurde zwischenzeitlich anderweitig geändert ({e}). Bitte erneut versuchen.",
                )
        finally:
            with active_analyses_lock:
                active_analyses.discard(draft_id)

    # 6. Static files frontend
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_app()
