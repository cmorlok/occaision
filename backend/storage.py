from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Dict, List, Optional
import uuid

from backend.models import Draft, PresetSettings

logger = logging.getLogger("occaision.storage")


class StorageError(Exception):
    pass


class StorageCorruptedError(StorageError):
    pass


class DraftNotFoundError(StorageError):
    pass


class RevisionConflictError(StorageError):
    pass


class StorageService:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir = self.data_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        
        self.drafts_file = self.data_dir / "drafts.json"
        self.settings_file = self.data_dir / "settings.json"
        self._lock = threading.Lock()

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
