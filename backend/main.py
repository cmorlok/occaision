from pathlib import Path
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


class CreateDraftRequest(BaseModel):
    user_notes: str = ""


class PatchImageModeRequest(BaseModel):
    active_mode: ImageVariantMode


def create_app(
    settings: Optional[Settings] = None,
    storage_service: Optional[StorageService] = None,
    image_service: Optional[ImageService] = None,
    ai_service: Optional[AIService] = None,
    ebay_service: Optional[EbayService] = None,
) -> FastAPI:
    cfg = settings or default_settings
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

        for f in files:
            content = await f.read()
            draft_image = img_svc.process_upload(
                draft_id=draft_id,
                raw_bytes=content,
                original_filename=f.filename or "upload.jpg",
            )
            draft.images.append(draft_image)

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
        return storage.update_draft(draft)

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
        analyzed_draft = await ai_svc.analyze_draft(
            draft=draft,
            image_paths=ai_image_paths,
            ebay_stats=ebay_stats,
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
