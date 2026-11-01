import logging
import os
from pathlib import Path
import sys
from typing import List, Optional
from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import Settings, settings as default_settings
from backend.models import (
    Draft,
    DraftImage,
    DraftStatus,
    ImageVariantMode,
    PresetSettings,
)
from backend.services.ai_service import AIService
from backend.services.ebay_service import EbayService
from backend.services.image_service import ImageService
from backend.storage import StorageService

logger = logging.getLogger("seller.api")
if not logger.handlers:
    _api_handler = logging.StreamHandler(sys.stdout)
    _api_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(_api_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def configure_logging(level_name: Optional[str] = None):
    """Set log level on all seller.* loggers based on CLI args, env var, or config."""
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

    for name in ["seller", "seller.api", "seller.image", "seller.ai"]:
        l = logging.getLogger(name)
        l.setLevel(level)

    if level == logging.DEBUG:
        logger.info("[Logging] Debug-Logging ist AKTIV (vollständige Prompts und Antworten werden ausgegeben).")


class CreateDraftRequest(BaseModel):
    user_notes: str = ""


class PatchImageModeRequest(BaseModel):
    active_mode: ImageVariantMode


class UpdateSystemConfigRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None


def create_app(
    settings: Optional[Settings] = None,
    storage_service: Optional[StorageService] = None,
    image_service: Optional[ImageService] = None,
    ai_service: Optional[AIService] = None,
    ebay_service: Optional[EbayService] = None,
) -> FastAPI:
    cfg = settings or default_settings
    configure_logging(cfg.log_level)
    storage = storage_service or StorageService(data_dir=cfg.data_dir)
    img_svc = image_service or ImageService(
        data_dir=cfg.data_dir,
        rembg_model=cfg.rembg_model,
    )
    ebay_svc = ebay_service or EbayService(default_eur_to_chf=cfg.eur_to_chf_rate)
    ai_svc = ai_service or AIService(
        api_key=cfg.gemini_api_key,
        model_name=cfg.gemini_model,
        enable_search_grounding=cfg.enable_search_grounding,
        eur_to_chf=cfg.eur_to_chf_rate,
    )

    app = FastAPI(
        title="Seller Assistant",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_no_cache_for_static(request, call_next):
        response = await call_next(request)
        if request.url.path.endswith((".css", ".js", ".html")) or request.url.path == "/":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    # 1. Health
    @app.get("/api/health")
    def health():
        return {"status": "ok", "model": cfg.gemini_model}

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

        # Auto-upgrade deprecated gemini-2.5-flash / gemini-2.0-flash to gemini-3.8-flash
        if cfg.gemini_model in ["gemini-2.5-flash", "gemini-2.0-flash"]:
            cfg.gemini_model = "gemini-3.8-flash"
            ai_svc.model_name = "gemini-3.8-flash"

        available_models = ai_svc.get_available_models()

        return {
            "gemini_api_key_configured": has_key,
            "gemini_model": cfg.gemini_model,
            "masked_key": masked,
            "eur_to_chf_rate": cfg.eur_to_chf_rate,
            "available_models": available_models,
        }

    @app.get("/api/models")
    def get_models():
        return ai_svc.get_available_models()

    @app.post("/api/config")
    def update_system_config(body: UpdateSystemConfigRequest):
        if body.gemini_model:
            cfg.gemini_model = body.gemini_model
            ai_svc.model_name = body.gemini_model

        if body.gemini_api_key is not None and body.gemini_api_key.strip():
            new_key = body.gemini_api_key.strip()
            cfg.gemini_api_key = new_key
            ai_svc.set_api_key(new_key, model_name=cfg.gemini_model)
            # Update .env (do not overwrite during test runs)
            env_path = Path(".env")
            if env_path.exists() and "pytest" not in sys.modules:
                try:
                    lines = env_path.read_text(encoding="utf-8").splitlines()
                    updated = []
                    found_key = False
                    found_model = False
                    for l in lines:
                        if l.startswith("GEMINI_API_KEY="):
                            updated.append(f"GEMINI_API_KEY={new_key}")
                            found_key = True
                        elif l.startswith("GEMINI_MODEL="):
                            updated.append(f"GEMINI_MODEL={cfg.gemini_model}")
                            found_model = True
                        else:
                            updated.append(l)
                    if not found_key:
                        updated.append(f"GEMINI_API_KEY={new_key}")
                    if not found_model:
                        updated.append(f"GEMINI_MODEL={cfg.gemini_model}")
                    env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
                    logger.info("[Config] GEMINI_API_KEY und GEMINI_MODEL in .env gespeichert.")
                except Exception as e:
                    logger.warning(f"Fehler beim Speichern in .env: {e}")
        elif body.gemini_model:
            # Model-only update in .env (do not overwrite during test runs)
            env_path = Path(".env")
            if env_path.exists() and "pytest" not in sys.modules:
                try:
                    lines = env_path.read_text(encoding="utf-8").splitlines()
                    updated = []
                    found_model = False
                    for l in lines:
                        if l.startswith("GEMINI_MODEL="):
                            updated.append(f"GEMINI_MODEL={cfg.gemini_model}")
                            found_model = True
                        else:
                            updated.append(l)
                    if not found_model:
                        updated.append(f"GEMINI_MODEL={cfg.gemini_model}")
                    env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
                except Exception as e:
                    logger.warning(f"Fehler beim Speichern in .env: {e}")

        return get_system_config()

    # 3. Drafts CRUD
    @app.get("/api/drafts", response_model=List[Draft])
    def list_drafts():
        return storage.list_drafts()

    @app.post("/api/drafts", response_model=Draft)
    def create_draft(req: Optional[CreateDraftRequest] = None):
        user_notes = req.user_notes if req else ""
        return storage.create_draft(user_notes=user_notes)

    @app.get("/api/drafts/{draft_id}", response_model=Draft)
    def get_draft(draft_id: str):
        draft = storage.get_draft(draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        return draft

    @app.put("/api/drafts/{draft_id}", response_model=Draft)
    def update_draft(draft_id: str, updated_draft: Draft):
        if draft_id != updated_draft.id:
            raise HTTPException(status_code=400, detail="Draft ID mismatch")
        existing = storage.get_draft(draft_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Draft not found")
        return storage.update_draft(updated_draft)

    @app.delete("/api/drafts/{draft_id}")
    def delete_draft(draft_id: str):
        success = storage.delete_draft(draft_id)
        if not success:
            raise HTTPException(status_code=404, detail="Draft not found")
        return {"ok": True, "message": "Draft deleted"}

    # 4. Images
    @app.post("/api/drafts/{draft_id}/images", response_model=Draft)
    async def upload_images(draft_id: str, files: List[UploadFile] = File(...)):
        draft = storage.get_draft(draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        logger.info(f"[API] Empfange {len(files)} Bild(er) für Draft {draft_id}...")
        for f in files:
            content = await f.read()
            draft_image = img_svc.process_upload(
                draft_id=draft_id,
                raw_bytes=content,
                original_filename=f.filename or "upload.jpg",
            )
            draft.images.append(draft_image)
            logger.info(f"[API] Bild {draft_image.id} ({f.filename}) zu Draft hinzugefügt.")

        return storage.update_draft(draft)

    @app.delete("/api/drafts/{draft_id}/images/{image_id}", response_model=Draft)
    def delete_image(draft_id: str, image_id: str):
        draft = storage.get_draft(draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        initial_len = len(draft.images)
        draft.images = [img for img in draft.images if img.id != image_id]
        if len(draft.images) == initial_len:
            raise HTTPException(status_code=404, detail="Image not found")

        logger.info(f"[API] Lösche Bild {image_id} aus Draft {draft_id}...")
        img_svc.delete_image(draft_id=draft_id, image_id=image_id)
        return storage.update_draft(draft)

    @app.patch("/api/drafts/{draft_id}/images/{image_id}", response_model=Draft)
    def patch_image_mode(draft_id: str, image_id: str, body: PatchImageModeRequest):
        draft = storage.get_draft(draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        target_img: Optional[DraftImage] = None
        for img in draft.images:
            if img.id == image_id:
                target_img = img
                break

        if not target_img:
            raise HTTPException(status_code=404, detail="Image not found")

        mode = body.active_mode
        logger.info(f"[API] Moduswechsel für Bild {image_id} auf '{mode.value}' angefordert (Draft: {draft_id})...")
        # Pre-generate variant if needed
        if mode == ImageVariantMode.CUTOUT:
            img_svc.get_or_create_cutout(draft_id=draft_id, image_id=image_id)
            target_img.variants[ImageVariantMode.CUTOUT] = (
                f"/api/drafts/{draft_id}/images/{image_id}/cutout"
            )
        elif mode == ImageVariantMode.BLURRED:
            img_svc.get_or_create_blurred(draft_id=draft_id, image_id=image_id)
            target_img.variants[ImageVariantMode.BLURRED] = (
                f"/api/drafts/{draft_id}/images/{image_id}/blurred"
            )

        target_img.active_mode = mode
        updated = storage.update_draft(draft)
        logger.info(f"[API] Bild {image_id} Modus erfolgreich auf '{mode.value}' gesetzt.")
        return updated

    @app.get("/api/drafts/{draft_id}/images/{image_id}/{variant}")
    def get_image_file(draft_id: str, image_id: str, variant: str):
        draft = storage.get_draft(draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        target_img: Optional[DraftImage] = None
        for img in draft.images:
            if img.id == image_id:
                target_img = img
                break

        if not target_img:
            raise HTTPException(status_code=404, detail="Image not found")

        var_mode = variant
        if variant == "active":
            var_mode = target_img.active_mode.value

        img_dir = cfg.data_dir / "images" / draft_id
        file_path = img_dir / f"{image_id}_{var_mode}.jpg"

        if not file_path.exists():
            if var_mode == ImageVariantMode.CUTOUT.value:
                file_path = img_svc.get_or_create_cutout(draft_id=draft_id, image_id=image_id)
            elif var_mode == ImageVariantMode.BLURRED.value:
                file_path = img_svc.get_or_create_blurred(draft_id=draft_id, image_id=image_id)
            elif var_mode == "ai":
                file_path = img_dir / f"{image_id}_ai.jpg"

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Image variant not found")

        return FileResponse(file_path, media_type="image/jpeg")

    # 5. Analysis
    @app.post("/api/drafts/{draft_id}/analyze", response_model=Draft)
    async def analyze_draft(draft_id: str):
        logger.info(f"[API] Starte KI- und Preisanalyse für Draft {draft_id}...")
        draft = storage.get_draft(draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        # 1. Fetch eBay stats if we have query notes/title
        search_query = (draft.user_notes or draft.identified_product or "").strip()
        ebay_stats = None
        if search_query:
            ebay_stats = await ebay_svc.fetch_sold_stats(search_query)

        # 2. Gather AI input images
        img_dir = cfg.data_dir / "images" / draft_id
        ai_image_paths = [img_dir / f"{img.id}_ai.jpg" for img in draft.images]

        # 3. Run AI analysis
        try:
            analyzed_draft = await ai_svc.analyze_draft(
                draft=draft,
                image_paths=ai_image_paths,
                ebay_stats=ebay_stats,
            )
        except Exception as e:
            logger.error(f"[API] KI-Analyse fehlgeschlagen: {e}")
            err_str = str(e)
            if "API_KEY_INVALID" in err_str or "API key not valid" in err_str or "API key" in err_str:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Ungültiger oder fehlender Google Gemini API-Key. Bitte trage deinen API-Key in den Einstellungen (⚙️) oder in der .env-Datei ein.",
                )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Fehler bei der KI-Analyse: {err_str}",
            )

        # 4. If user provided no initial text notes, fetch eBay stats using AI-identified product
        if ebay_stats is None and analyzed_draft.identified_product:
            analyzed_draft.price_analysis.ebay_stats = await ebay_svc.fetch_sold_stats(
                analyzed_draft.identified_product
            )

        return storage.update_draft(analyzed_draft)

    # 6. Static files frontend
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_app()
