import hashlib
import json
import shutil
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.config import get_logger
from backend.models import (
    Draft,
    DraftImage,
    ImageVariantMode,
    PresetSettings,
    UpdateDraftRequest,
    validate_identifier,
)
from backend.path_utils import PathTraversalError, resolve_safe_path

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
        validate_identifier(draft_id, "draft_id")
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
        validate_identifier(draft.id, "draft_id")
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

    def update_draft_fields(self, draft_id: str, updates: UpdateDraftRequest) -> Draft:
        validate_identifier(draft_id, "draft_id")
        with self._lock:
            raw_list = self._load_drafts_raw()
            found_idx = None
            existing_item = None
            for idx, item in enumerate(raw_list):
                if item.get("id") == draft_id:
                    found_idx = idx
                    existing_item = item
                    break
            if found_idx is None:
                raise DraftNotFoundError(f"Draft {draft_id} does not exist (cannot update)")

            current_draft = Draft.model_validate(existing_item)
            existing_rev = current_draft.revision
            if updates.revision is not None and updates.revision != existing_rev:
                raise RevisionConflictError(
                    f"Conflict updating draft {draft_id}: expected revision {existing_rev}, got {updates.revision}"
                )

            # Apply only user-editable fields
            if updates.user_notes is not None:
                current_draft.user_notes = updates.user_notes
            if updates.identified_product is not None:
                current_draft.identified_product = updates.identified_product
            if updates.status is not None:
                current_draft.status = updates.status
            if updates.missing_photo_hints is not None:
                current_draft.missing_photo_hints = updates.missing_photo_hints
            if updates.price_analysis is not None:
                current_draft.price_analysis = updates.price_analysis
            if updates.ricardo is not None:
                current_draft.ricardo = updates.ricardo
            if updates.tutti is not None:
                current_draft.tutti = updates.tutti
            if updates.ebay_de is not None:
                current_draft.ebay_de = updates.ebay_de
            if updates.kleinanzeigen is not None:
                current_draft.kleinanzeigen = updates.kleinanzeigen

            current_draft.updated_at = datetime.now(timezone.utc).isoformat()
            current_draft.revision = existing_rev + 1

            raw_list[found_idx] = current_draft.model_dump()
            self._write_json_atomic(self.drafts_file, raw_list)
        return current_draft

    def delete_draft(self, draft_id: str) -> bool:
        validate_identifier(draft_id, "draft_id")
        with self._lock:
            raw_list = self._load_drafts_raw()
            initial_len = len(raw_list)
            raw_list = [d for d in raw_list if d.get("id") != draft_id]
            if len(raw_list) == initial_len:
                return False
            self._write_json_atomic(self.drafts_file, raw_list)

        # Cleanup image folder safely
        draft_img_dir = resolve_safe_path(self.images_dir, draft_id)
        if draft_img_dir.exists() and draft_img_dir.is_dir() and not draft_img_dir.is_symlink():
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
        validate_identifier(draft_id, "draft_id")
        validate_identifier(image_id, "image_id")

        allowed_variants = {m.value for m in ImageVariantMode} | {"active", "ai"}
        if variant not in allowed_variants:
            raise ValueError(f"Invalid image variant: {variant!r}. Allowed: {sorted(allowed_variants)}")

        with self._lock:
            draft = self.get_draft(draft_id)
            if not draft:
                raise DraftNotFoundError(f"Draft {draft_id} not found")
            target_img = next((img for img in draft.images if img.id == image_id), None)
            if not target_img:
                raise FileNotFoundError(f"Image {image_id} not found in draft {draft_id}")
            active_mode = target_img.active_mode.value

        var_mode = active_mode if variant == "active" else variant
        img_dir = resolve_safe_path(self.images_dir, draft_id)
        file_path = resolve_safe_path(img_dir, f"{image_id}_{var_mode}.jpg")

        if not file_path.exists():
            if var_mode == ImageVariantMode.CUTOUT.value:
                file_path = self.image_service.get_or_create_cutout(draft_id=draft_id, image_id=image_id)
            elif var_mode == ImageVariantMode.BLURRED.value:
                file_path = self.image_service.get_or_create_blurred(draft_id=draft_id, image_id=image_id)
            elif var_mode == "ai":
                file_path = resolve_safe_path(img_dir, f"{image_id}_ai.jpg")

        if not file_path.exists():
            raise FileNotFoundError(f"Image variant '{variant}' not found for image {image_id}")

        return file_path

    def get_ai_image_paths(self, draft_id: str) -> List[Path]:
        """Return file paths for AI-downscaled image variants for the draft."""
        validate_identifier(draft_id, "draft_id")
        with self._lock:
            draft = self.get_draft(draft_id)
            if not draft:
                raise DraftNotFoundError(f"Draft {draft_id} not found")
            images = list(draft.images)

        img_dir = resolve_safe_path(self.images_dir, draft_id)
        paths = []
        for img in images:
            validate_identifier(img.id, "image_id")
            paths.append(resolve_safe_path(img_dir, f"{img.id}_ai.jpg"))
        return paths

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
        seen_draft_ids = set()
        for item in raw_imported_drafts:
            try:
                draft = Draft.model_validate(item)
            except Exception as e:
                raise ValueError(f"Ungültiger Entwurf im Import: {e}") from e

            if draft.id in seen_draft_ids:
                raise ValueError(f"Doppelte Draft-ID im Import gefunden: {draft.id}")
            seen_draft_ids.add(draft.id)

            seen_img_ids = set()
            for img in draft.images:
                if img.id in seen_img_ids:
                    raise ValueError(f"Doppelte Bild-ID '{img.id}' in Entwurf {draft.id} gefunden.")
                seen_img_ids.add(img.id)

            validated_drafts.append(draft)

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

    def create_backup_archive(self, target_path: Optional[Path] = None) -> Path:
        """Create a complete, photo-inclusive ZIP backup archive containing drafts, settings, images, and manifest with checksums."""
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if target_path is None:
            dest = self.data_dir / f"occaision_backup_{now_str}.zip"
        else:
            dest = Path(target_path)

        with self._lock:
            drafts_raw = self._load_drafts_raw()
            settings = self.get_settings()

            drafts_bytes = json.dumps(drafts_raw, indent=2, ensure_ascii=False).encode("utf-8")
            settings_bytes = json.dumps(settings.model_dump(), indent=2, ensure_ascii=False).encode("utf-8")

            files_map: Dict[str, bytes] = {
                "drafts.json": drafts_bytes,
                "settings.json": settings_bytes,
            }

            checksums: Dict[str, str] = {
                "drafts.json": hashlib.sha256(drafts_bytes).hexdigest(),
                "settings.json": hashlib.sha256(settings_bytes).hexdigest(),
            }

            # Collect all image files
            if self.images_dir.exists():
                for draft_folder in self.images_dir.iterdir():
                    if draft_folder.is_dir() and not draft_folder.is_symlink():
                        try:
                            validate_identifier(draft_folder.name, "draft_id")
                        except ValueError:
                            continue
                        for img_file in draft_folder.iterdir():
                            if img_file.is_file() and not img_file.is_symlink():
                                rel_path = f"images/{draft_folder.name}/{img_file.name}"
                                b = img_file.read_bytes()
                                files_map[rel_path] = b
                                checksums[rel_path] = hashlib.sha256(b).hexdigest()

            manifest = {
                "format": "occaision_backup_v1",
                "version": 1,
                "app_version": "1.1.0",
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "files": checksums,
            }
            manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")

            with tempfile.NamedTemporaryFile("wb", dir=str(self.data_dir), delete=False, suffix=".zip") as tf:
                temp_zip_path = Path(tf.name)
                with zipfile.ZipFile(tf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr("manifest.json", manifest_bytes)
                    for path_str, data_bytes in files_map.items():
                        zf.writestr(path_str, data_bytes)

            temp_zip_path.replace(dest)
            return dest

    def restore_backup_archive(self, archive_path: Path) -> Dict[str, Any]:
        """Validate and restore drafts, settings, and photos from a ZIP backup archive with atomic rollback."""
        archive_path = Path(archive_path)
        if not archive_path.exists() or not zipfile.is_zipfile(archive_path):
            raise ValueError("Ungültige Backup-Datei: Kein gültiges ZIP-Archiv.")

        staging_dir = self.data_dir / ".restore_staging"
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                # 1. Path safety check for zip slip
                for info in zf.infolist():
                    name = info.filename
                    if name.startswith("/") or "\\" in name or ".." in name.split("/"):
                        raise PathTraversalError(f"Gefährlicher Pfad im Backup-Archiv gefunden: {name!r}")
                    if not (
                        name == "manifest.json"
                        or name == "drafts.json"
                        or name == "settings.json"
                        or name.startswith("images/")
                    ):
                        raise ValueError(f"Unerwarteter Dateipfad im Archiv: {name}")

                zf.extractall(staging_dir)

            # 2. Check manifest
            manifest_file = staging_dir / "manifest.json"
            if not manifest_file.exists():
                raise ValueError("Ungültiges Archiv: 'manifest.json' fehlt.")

            try:
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            except Exception as e:
                raise ValueError(f"Korrupte manifest.json: {e}") from e

            if manifest.get("format") != "occaision_backup_v1":
                raise ValueError(f"Nicht unterstütztes Backup-Format: {manifest.get('format')}")

            expected_checksums = manifest.get("files", {})

            # 3. Verify checksums of all files
            for rel_path, expected_hash in expected_checksums.items():
                target_file = staging_dir / rel_path
                if not target_file.exists():
                    raise ValueError(f"Datei '{rel_path}' aus Manifest nicht im Archiv gefunden.")
                computed_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()
                if computed_hash != expected_hash:
                    raise ValueError(f"Prüfsummenfehler für '{rel_path}': Archiv beschädigt oder manipuliert.")

            # 4. Validate drafts.json
            drafts_file = staging_dir / "drafts.json"
            if not drafts_file.exists():
                raise ValueError("drafts.json fehlt im Archiv.")
            try:
                raw_drafts = json.loads(drafts_file.read_text(encoding="utf-8"))
            except Exception as e:
                raise ValueError(f"Ungültiges JSON in drafts.json: {e}") from e

            validated_drafts = []
            seen_draft_ids = set()
            for d in raw_drafts:
                vd = Draft.model_validate(d)
                if vd.id in seen_draft_ids:
                    raise ValueError(f"Doppelte Draft-ID {vd.id} im Backup gefunden.")
                seen_draft_ids.add(vd.id)
                validated_drafts.append(vd)

            # 5. Validate settings.json
            settings_file = staging_dir / "settings.json"
            if settings_file.exists():
                try:
                    PresetSettings.model_validate(json.loads(settings_file.read_text(encoding="utf-8")))
                except Exception as e:
                    raise ValueError(f"Ungültige Einstellungen im Backup: {e}") from e

            # 6. Commit transactionally under lock
            with self._lock:
                # Backup current state for rollback
                pre_restore = self.data_dir / ".pre_restore_backup"
                if pre_restore.exists():
                    shutil.rmtree(pre_restore, ignore_errors=True)
                pre_restore.mkdir(parents=True, exist_ok=True)

                if self.drafts_file.exists():
                    shutil.copy2(self.drafts_file, pre_restore / "drafts.json")
                if self.settings_file.exists():
                    shutil.copy2(self.settings_file, pre_restore / "settings.json")
                if self.images_dir.exists():
                    shutil.copytree(self.images_dir, pre_restore / "images", dirs_exist_ok=True)

                try:
                    # Apply drafts & settings
                    shutil.copy2(drafts_file, self.drafts_file)
                    if settings_file.exists():
                        shutil.copy2(settings_file, self.settings_file)

                    # Apply images
                    staged_images = staging_dir / "images"
                    if staged_images.exists():
                        self.images_dir.mkdir(parents=True, exist_ok=True)
                        for d_dir in staged_images.iterdir():
                            if d_dir.is_dir():
                                dest_d = resolve_safe_path(self.images_dir, d_dir.name)
                                if dest_d.exists():
                                    shutil.rmtree(dest_d, ignore_errors=True)
                                shutil.copytree(d_dir, dest_d)

                    shutil.rmtree(pre_restore, ignore_errors=True)
                except Exception as commit_err:
                    # Rollback
                    logger.error(f"[Storage] Fehler beim Anwenden des Backups, führe Rollback durch: {commit_err}")
                    if (pre_restore / "drafts.json").exists():
                        shutil.copy2(pre_restore / "drafts.json", self.drafts_file)
                    if (pre_restore / "settings.json").exists():
                        shutil.copy2(pre_restore / "settings.json", self.settings_file)
                    if (pre_restore / "images").exists():
                        shutil.rmtree(self.images_dir, ignore_errors=True)
                        shutil.copytree(pre_restore / "images", self.images_dir)
                    shutil.rmtree(pre_restore, ignore_errors=True)
                    raise commit_err

            total_images = sum(len(d.images) for d in validated_drafts)
            return {
                "ok": True,
                "restored_drafts": len(validated_drafts),
                "restored_images": total_images,
            }
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def cleanup_orphaned_images(self, quarantine: bool = True) -> int:
        """Scan self.images_dir and move any folder whose draft ID no longer exists to quarantine."""
        with self._lock:
            existing_ids = {d.id for d in self.list_drafts()}
        cleaned_count = 0
        if not self.images_dir.exists():
            return 0

        quarantine_dir = self.data_dir / "quarantine"
        if quarantine:
            quarantine_dir.mkdir(parents=True, exist_ok=True)

        try:
            for entry in list(self.images_dir.iterdir()):
                if entry.is_dir() and not entry.is_symlink() and entry.name not in existing_ids:
                    try:
                        validate_identifier(entry.name, "draft_id")
                        safe_entry = resolve_safe_path(self.images_dir, entry.name)
                        if quarantine:
                            dest_q = quarantine_dir / entry.name
                            if dest_q.exists():
                                now_tag = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                                dest_q = quarantine_dir / f"{entry.name}_{now_tag}"
                            shutil.move(str(safe_entry), str(dest_q))
                            logger.info(f"[Storage] Moved orphaned image directory to quarantine: {entry.name} -> {dest_q.name}")
                        else:
                            shutil.rmtree(safe_entry, ignore_errors=True)
                            logger.info(f"[Storage] Cleaned up orphaned image directory: {entry.name}")
                        cleaned_count += 1
                    except Exception as err:
                        logger.warning(f"[Storage] Skipping unsafe or invalid orphaned folder {entry.name}: {err}")
        except Exception as e:
            logger.warning(f"[Storage] Error during orphan image cleanup: {e}")
        return cleaned_count


# Backwards compatibility alias
StorageService = DraftStore
