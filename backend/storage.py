import json
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple
import uuid
from datetime import datetime, timezone

from backend.config import get_logger
from backend.models import Draft, DraftImage, ImageVariantMode, PresetSettings

logger = get_logger("occaision.storage")

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
MAX_FILES_PER_BATCH = 15


class StorageError(Exception):
    pass


class StorageCorruptedError(StorageError):
    pass


class DraftNotFoundError(StorageError):
    pass


class RevisionConflictError(StorageError):
    pass


class FileTooLargeError(StorageError):
    pass


class BatchLimitExceededError(StorageError):
    pass


class DraftStore:
    def __init__(self, data_dir: Path, image_service: Optional[Any] = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir = self.data_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)

        self.drafts_file = self.data_dir / "drafts.json"
        self.settings_file = self.data_dir / "settings.json"
        self._lock = threading.RLock()

        if image_service is not None:
            self.image_service = image_service
        else:
            from backend.services.image_service import ImageService
            self.image_service = ImageService(data_dir=self.data_dir)

        if not self.drafts_file.exists():
            self._write_json_atomic(self.drafts_file, [])
        if not self.settings_file.exists():
            default_settings = PresetSettings()
            self._write_json_atomic(self.settings_file, default_settings.model_dump())

    def _write_json_atomic(self, file_path: Path, data: any) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=str(file_path.parent), delete=False, encoding="utf-8") as tf:
            json.dump(data, tf, indent=2, ensure_ascii=False)
            temp_name = tf.name
        Path(temp_name).replace(file_path)

    def get_settings(self) -> PresetSettings:
        with self._lock:
            if not self.settings_file.exists():
                settings = PresetSettings()
                self._write_json_atomic(self.settings_file, settings.model_dump())
                return settings
            with open(self.settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PresetSettings.model_validate(data)

    def update_settings(self, settings: PresetSettings) -> PresetSettings:
        with self._lock:
            self._write_json_atomic(self.settings_file, settings.model_dump())
            return settings

    def _load_drafts_raw(self) -> List[Dict]:
        if not self.drafts_file.exists():
            return []
        try:
            with open(self.drafts_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            now_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            backup_path = self.data_dir / f"drafts.json.corrupt.{now_str}"
            try:
                shutil.copy2(self.drafts_file, backup_path)
                logger.error(f"[Storage] Corrupt drafts.json backed up to {backup_path}: {e}")
            except Exception as copy_err:
                logger.error(f"[Storage] Failed to back up corrupt drafts.json: {copy_err}")
            raise StorageCorruptedError(f"Corrupted drafts.json: {e}") from e
        except FileNotFoundError:
            return []

    def list_drafts(self) -> List[Draft]:
        with self._lock:
            raw_list = self._load_drafts_raw()
            drafts = [Draft.model_validate(d) for d in raw_list]
            drafts.sort(key=lambda d: d.updated_at, reverse=True)
            return drafts

    def get_draft(self, draft_id: str) -> Optional[Draft]:
        with self._lock:
            raw_list = self._load_drafts_raw()
            for d in raw_list:
                if d.get("id") == draft_id:
                    return Draft.model_validate(d)
            return None

    def create_draft(self, user_notes: str = "", identified_product: str = "") -> Draft:
        settings = self.get_settings()
        now_iso = datetime.now(timezone.utc).isoformat()
        draft_id = f"draft_{uuid.uuid4().hex[:12]}"

        draft = Draft(
            id=draft_id,
            created_at=now_iso,
            updated_at=now_iso,
            user_notes=user_notes,
            identified_product=identified_product,
        )
        draft.ricardo.offer_type = settings.default_offer_type
        draft.ricardo.shipping_preset_id = settings.default_shipping_preset_id
        draft.ebay_de.offer_type = settings.default_offer_type
        draft.ebay_de.shipping_preset_id = settings.default_de_shipping_preset_id
        draft.kleinanzeigen.shipping_preset_id = settings.default_de_shipping_preset_id

        with self._lock:
            raw_list = self._load_drafts_raw()
            raw_list.append(draft.model_dump())
            self._write_json_atomic(self.drafts_file, raw_list)
        return draft

    def update_draft(self, draft: Draft) -> Draft:
        draft.updated_at = datetime.now(timezone.utc).isoformat()

        with self._lock:
            raw_list = self._load_drafts_raw()
            found_idx = None
            existing_item = None
            for idx, item in enumerate(raw_list):
                if item.get("id") == draft.id:
                    found_idx = idx
                    existing_item = item
                    break
            if found_idx is None:
                raise DraftNotFoundError(f"Draft {draft.id} does not exist (cannot update)")

            existing_rev = existing_item.get("revision", 1)
            if draft.revision != existing_rev:
                raise RevisionConflictError(
                    f"Conflict updating draft {draft.id}: expected revision {existing_rev}, got {draft.revision}"
                )

            draft.revision = existing_rev + 1
            raw_list[found_idx] = draft.model_dump()
            self._write_json_atomic(self.drafts_file, raw_list)
        return draft

    def delete_draft(self, draft_id: str) -> bool:
        with self._lock:
            raw_list = self._load_drafts_raw()
            initial_len = len(raw_list)
            raw_list = [d for d in raw_list if d.get("id") != draft_id]
            if len(raw_list) == initial_len:
                return False
            self._write_json_atomic(self.drafts_file, raw_list)

        # Cleanup image folder
        draft_img_dir = self.images_dir / draft_id
        if draft_img_dir.exists():
            shutil.rmtree(draft_img_dir, ignore_errors=True)

        return True

    def add_images(self, draft_id: str, files: List[Tuple[str, bytes]]) -> Draft:
        """Process and append image uploads to a draft with batch limits and atomic rollback."""
        if len(files) > MAX_FILES_PER_BATCH:
            raise BatchLimitExceededError(
                f"Maximal {MAX_FILES_PER_BATCH} Bilder pro Upload erlaubt (erhalten: {len(files)})."
            )

        with self._lock:
            draft = self.get_draft(draft_id)
            if not draft:
                raise DraftNotFoundError(f"Draft {draft_id} not found")

        processed_images: List[DraftImage] = []
        try:
            for filename, content in files:
                if len(content) > MAX_FILE_SIZE:
                    raise FileTooLargeError(
                        f"Datei '{filename}' überschreitet das Limit von 25 MB."
                    )
                draft_image = self.image_service.process_upload(
                    draft_id=draft_id,
                    raw_bytes=content,
                    original_filename=filename or "upload.jpg",
                )
                processed_images.append(draft_image)
        except Exception as e:
            # Atomic rollback on any processing or validation failure
            for img in processed_images:
                try:
                    self.image_service.delete_image(draft_id, img.id)
                except Exception:
                    pass
            raise e

        with self._lock:
            current_draft = self.get_draft(draft_id)
            if not current_draft:
                for img in processed_images:
                    try:
                        self.image_service.delete_image(draft_id, img.id)
                    except Exception:
                        pass
                raise DraftNotFoundError("Draft was deleted during upload")

            current_draft.images.extend(processed_images)
            return self.update_draft(current_draft)

    def delete_image(self, draft_id: str, image_id: str) -> Draft:
        """Remove image from draft and delete underlying files."""
        with self._lock:
            draft = self.get_draft(draft_id)
            if not draft:
                raise DraftNotFoundError(f"Draft {draft_id} not found")

            initial_len = len(draft.images)
            draft.images = [img for img in draft.images if img.id != image_id]
            if len(draft.images) == initial_len:
                raise FileNotFoundError(f"Image {image_id} not found in draft {draft_id}")

            self.image_service.delete_image(draft_id=draft_id, image_id=image_id)
            return self.update_draft(draft)

    def set_image_mode(self, draft_id: str, image_id: str, mode: ImageVariantMode) -> Draft:
        """Switch active image mode, pre-generating cutout or blurred variant if needed."""
        with self._lock:
            draft = self.get_draft(draft_id)
            if not draft:
                raise DraftNotFoundError(f"Draft {draft_id} not found")
            target_img = next((img for img in draft.images if img.id == image_id), None)
            if not target_img:
                raise FileNotFoundError(f"Image {image_id} not found in draft {draft_id}")

        # Pre-generate variant outside write lock
        variant_url = None
        if mode == ImageVariantMode.CUTOUT:
            self.image_service.get_or_create_cutout(draft_id=draft_id, image_id=image_id)
            variant_url = f"/api/drafts/{draft_id}/images/{image_id}/cutout"
        elif mode == ImageVariantMode.BLURRED:
            self.image_service.get_or_create_blurred(draft_id=draft_id, image_id=image_id)
            variant_url = f"/api/drafts/{draft_id}/images/{image_id}/blurred"

        with self._lock:
            current_draft = self.get_draft(draft_id)
            if not current_draft:
                raise DraftNotFoundError(f"Draft {draft_id} not found")
            target_img = next((img for img in current_draft.images if img.id == image_id), None)
            if not target_img:
                raise FileNotFoundError(f"Image {image_id} not found in draft {draft_id}")

            if variant_url and mode in (ImageVariantMode.CUTOUT, ImageVariantMode.BLURRED):
                target_img.variants[mode] = variant_url

            target_img.active_mode = mode
            return self.update_draft(current_draft)

    def get_image_file_path(self, draft_id: str, image_id: str, variant: str) -> Path:
        """Resolve variant file path, lazily generating cached cutout/blur if missing."""
        with self._lock:
            draft = self.get_draft(draft_id)
            if not draft:
                raise DraftNotFoundError(f"Draft {draft_id} not found")
            target_img = next((img for img in draft.images if img.id == image_id), None)
            if not target_img:
                raise FileNotFoundError(f"Image {image_id} not found in draft {draft_id}")
            active_mode = target_img.active_mode.value

        var_mode = active_mode if variant == "active" else variant
        img_dir = self.images_dir / draft_id
        file_path = img_dir / f"{image_id}_{var_mode}.jpg"

        if not file_path.exists():
            if var_mode == ImageVariantMode.CUTOUT.value:
                file_path = self.image_service.get_or_create_cutout(draft_id=draft_id, image_id=image_id)
            elif var_mode == ImageVariantMode.BLURRED.value:
                file_path = self.image_service.get_or_create_blurred(draft_id=draft_id, image_id=image_id)
            elif var_mode == "ai":
                file_path = img_dir / f"{image_id}_ai.jpg"

        if not file_path.exists():
            raise FileNotFoundError(f"Image variant '{variant}' not found for image {image_id}")

        return file_path

    def get_ai_image_paths(self, draft_id: str) -> List[Path]:
        """Return file paths for AI-downscaled image variants for the draft."""
        with self._lock:
            draft = self.get_draft(draft_id)
            if not draft:
                raise DraftNotFoundError(f"Draft {draft_id} not found")
            images = list(draft.images)

        img_dir = self.images_dir / draft_id
        return [img_dir / f"{img.id}_ai.jpg" for img in images]

    def export_drafts_data(self) -> Dict[str, Any]:
        """Export all drafts and settings into a serializable backup payload."""
        with self._lock:
            raw_drafts = self._load_drafts_raw()
            settings = self.get_settings()
            return {
                "version": 1,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "drafts": raw_drafts,
                "settings": settings.model_dump(),
            }

    def import_drafts_data(self, data: Dict[str, Any], overwrite: bool = False) -> Dict[str, int]:
        """Validate and import drafts and settings from a backup payload.
        If overwrite is False (default), drafts are merged by ID; if True, existing drafts are replaced.
        """
        if not isinstance(data, dict):
            raise ValueError("Ungültiges Import-Format: JSON-Objekt erwartet.")

        raw_imported_drafts = data.get("drafts", [])
        if not isinstance(raw_imported_drafts, list):
            raise ValueError("Ungültiges Format: 'drafts' muss eine Liste sein.")

        # Validate each draft through Draft model
        validated_drafts: List[Draft] = []
        for item in raw_imported_drafts:
            try:
                validated_drafts.append(Draft.model_validate(item))
            except Exception as e:
                raise ValueError(f"Ungültiger Entwurf im Import: {e}") from e

        imported_settings_data = data.get("settings")
        with self._lock:
            if imported_settings_data and isinstance(imported_settings_data, dict):
                try:
                    valid_settings = PresetSettings.model_validate(imported_settings_data)
                    self._write_json_atomic(self.settings_file, valid_settings.model_dump())
                except Exception:
                    pass

            if overwrite:
                merged_list = [d.model_dump() for d in validated_drafts]
                imported_count = len(validated_drafts)
            else:
                current_raw = self._load_drafts_raw()
                by_id = {d.get("id"): d for d in current_raw if d.get("id")}
                imported_count = 0
                for d in validated_drafts:
                    d_dump = d.model_dump()
                    imported_count += 1
                    by_id[d.id] = d_dump
                merged_list = list(by_id.values())

            self._write_json_atomic(self.drafts_file, merged_list)
            return {"imported_count": imported_count, "total_count": len(merged_list)}

    def cleanup_orphaned_images(self) -> int:
        """Scan self.images_dir and delete any folder whose draft ID no longer exists."""
        with self._lock:
            existing_ids = {d.id for d in self.list_drafts()}
        cleaned_count = 0
        if not self.images_dir.exists():
            return 0
        try:
            for entry in list(self.images_dir.iterdir()):
                if entry.is_dir() and entry.name not in existing_ids:
                    shutil.rmtree(entry, ignore_errors=True)
                    cleaned_count += 1
                    logger.info(f"[Storage] Cleaned up orphaned image directory: {entry.name}")
        except Exception as e:
            logger.warning(f"[Storage] Error during orphan image cleanup: {e}")
        return cleaned_count


# Backwards compatibility alias
StorageService = DraftStore
