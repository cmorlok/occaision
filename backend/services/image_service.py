import io
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import pillow_heif
from PIL import Image, ImageFilter, ImageOps

from backend.config import get_logger
from backend.models import DraftImage, ImageVariantMode, validate_identifier
from backend.path_utils import resolve_safe_path

pillow_heif.register_heif_opener()
Image.MAX_IMAGE_PIXELS = 50_000_000

logger = get_logger("occaision.image")


class ImageService:
    def __init__(
        self,
        data_dir: Path,
        mask_extractor: Optional[Callable[[Image.Image], Image.Image]] = None,
        rembg_model: str = "u2netp",
    ):
        self.data_dir = Path(data_dir)
        self.images_dir = self.data_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._mask_extractor = mask_extractor
        self._rembg_model = rembg_model
        self._rembg_session = None

    def clean_and_orient(self, raw_bytes: bytes) -> Image.Image:
        """Open, orient according to EXIF, convert to RGB, and discard all metadata."""
        try:
            with Image.open(io.BytesIO(raw_bytes)) as loaded_img:
                if loaded_img.width * loaded_img.height > Image.MAX_IMAGE_PIXELS:
                    raise ValueError(
                        f"Bildabmessungen zu gross ({loaded_img.width}x{loaded_img.height}px). Limit: 50 MP."
                    )
                oriented = ImageOps.exif_transpose(loaded_img)
                if oriented is None:
                    oriented = loaded_img
                rgb_conv = oriented.convert("RGB")
                # Create a completely fresh image with pixel copy to guarantee no EXIF tags survive
                clean_img = Image.new("RGB", rgb_conv.size)
                clean_img.paste(rgb_conv, (0, 0))
                return clean_img
        except Image.DecompressionBombError as e:
            raise ValueError(f"Bildabmessungen überschreiten das Sicherheitslimit: {e}") from e

    def create_optimized_variant(self, clean_img: Image.Image) -> Image.Image:
        """Auto-contrast and downscale max dimension to 2048px."""
        opt = ImageOps.autocontrast(clean_img.copy(), cutoff=0.5)
        opt.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        return opt

    def create_ai_input_variant(self, clean_img: Image.Image) -> Image.Image:
        """Downscale max dimension to 1024px for AI input to preserve privacy and tokens."""
        ai_img = clean_img.copy()
        ai_img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        return ai_img

    def extract_foreground(self, img: Image.Image) -> Image.Image:
        """Extract RGBA image with foreground using rembg or injected mask extractor."""
        if self._mask_extractor is not None:
            return self._mask_extractor(img)

        import rembg
        if self._rembg_session is None:
            logger.info(f"[ImageService] Initialisiere rembg KI-Modell '{self._rembg_model}'...")
            t_sess = time.time()
            self._rembg_session = rembg.new_session(self._rembg_model)
            logger.info(f"[ImageService] rembg KI-Modell initialisiert in {time.time() - t_sess:.2f}s.")

        logger.info(f"[ImageService] Berechne KI-Maske (rembg) für Bild ({img.width}x{img.height}px)...")
        t_rem = time.time()
        rgba = rembg.remove(img, session=self._rembg_session)
        logger.info(f"[ImageService] KI-Maske erfolgreich berechnet in {time.time() - t_rem:.2f}s.")
        return rgba

    def _get_draft_image_dir(self, draft_id: str) -> Path:
        validate_identifier(draft_id, "draft_id")
        dir_path = resolve_safe_path(self.images_dir, draft_id)
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def process_upload(
        self, draft_id: str, raw_bytes: bytes, original_filename: str
    ) -> DraftImage:
        logger.info(f"[ImageService] Verarbeite Bild-Upload '{original_filename}' für Draft {draft_id}...")
        t0 = time.time()
        draft_img_dir = self._get_draft_image_dir(draft_id)
        image_id = f"img_{uuid.uuid4().hex[:12]}"

        clean_img = self.clean_and_orient(raw_bytes)
        opt_img = self.create_optimized_variant(clean_img)
        ai_img = self.create_ai_input_variant(clean_img)

        opt_path = draft_img_dir / f"{image_id}_optimized.jpg"
        ai_path = draft_img_dir / f"{image_id}_ai.jpg"

        opt_img.save(opt_path, format="JPEG", quality=90, optimize=True)
        ai_img.save(ai_path, format="JPEG", quality=85, optimize=True)

        variants = {
            ImageVariantMode.OPTIMIZED: f"/api/drafts/{draft_id}/images/{image_id}/optimized"
        }

        draft_img = DraftImage(
            id=image_id,
            original_filename=original_filename,
            active_mode=ImageVariantMode.OPTIMIZED,
            variants=variants,
            width=opt_img.width,
            height=opt_img.height,
            exif_stripped=True,
        )
        logger.info(
            f"[ImageService] Upload '{original_filename}' erfolgreich gespeichert ({opt_img.width}x{opt_img.height}px, EXIF entfernt) in {time.time() - t0:.2f}s -> {image_id}"
        )
        return draft_img

    def get_or_create_cutout(self, draft_id: str, image_id: str) -> Path:
        validate_identifier(draft_id, "draft_id")
        validate_identifier(image_id, "image_id")
        draft_img_dir = self._get_draft_image_dir(draft_id)
        cutout_path = resolve_safe_path(draft_img_dir, f"{image_id}_cutout.jpg")
        if cutout_path.exists():
            logger.info(f"[ImageService] Freigestelltes Bild existiert bereits im Cache: {cutout_path.name}")
            return cutout_path

        opt_path = resolve_safe_path(draft_img_dir, f"{image_id}_optimized.jpg")
        if not opt_path.exists():
            raise FileNotFoundError(f"Optimized image not found: {opt_path}")

        logger.info(f"[ImageService] Starte Hintergrundentfernung für Bild {image_id} (Draft: {draft_id})...")
        t0 = time.time()
        with Image.open(opt_path) as opt_img:
            rgba = self.extract_foreground(opt_img)
            # Composite foreground onto clean neutral light-gray/white (#F8F9FA) canvas
            bg = Image.new("RGB", rgba.size, (248, 249, 250))
            bg.paste(rgba, mask=rgba.split()[3])
            bg.save(cutout_path, format="JPEG", quality=90, optimize=True)
            elapsed = time.time() - t0
            logger.info(f"[ImageService] Hintergrund erfolgreich entfernt in {elapsed:.2f}s -> {cutout_path.name}")
            return cutout_path

    def get_or_create_blurred(self, draft_id: str, image_id: str) -> Path:
        validate_identifier(draft_id, "draft_id")
        validate_identifier(image_id, "image_id")
        draft_img_dir = self._get_draft_image_dir(draft_id)
        blurred_path = resolve_safe_path(draft_img_dir, f"{image_id}_blurred.jpg")
        if blurred_path.exists():
            logger.info(f"[ImageService] Weichgezeichnetes Bild existiert bereits im Cache: {blurred_path.name}")
            return blurred_path

        opt_path = resolve_safe_path(draft_img_dir, f"{image_id}_optimized.jpg")
        if not opt_path.exists():
            raise FileNotFoundError(f"Optimized image not found: {opt_path}")

        logger.info(f"[ImageService] Starte Weichzeichnen (Blur) für Bild {image_id} (Draft: {draft_id})...")
        t0 = time.time()
        with Image.open(opt_path) as opt_img:
            rgba = self.extract_foreground(opt_img)
            blurred_bg = opt_img.filter(ImageFilter.GaussianBlur(radius=18))
            composited = Image.composite(opt_img, blurred_bg, rgba.split()[3])
            composited.save(blurred_path, format="JPEG", quality=90, optimize=True)
            elapsed = time.time() - t0
            logger.info(f"[ImageService] Hintergrund erfolgreich weichgezeichnet in {elapsed:.2f}s -> {blurred_path.name}")
            return blurred_path

    def delete_image(self, draft_id: str, image_id: str) -> bool:
        validate_identifier(draft_id, "draft_id")
        validate_identifier(image_id, "image_id")
        logger.info(f"[ImageService] Lösche Bilddateien für {image_id} (Draft: {draft_id})...")
        draft_img_dir = self._get_draft_image_dir(draft_id)
        deleted_any = False
        known_suffixes = ["optimized.jpg", "ai.jpg", "cutout.jpg", "blurred.jpg"]
        for suffix in known_suffixes:
            p = resolve_safe_path(draft_img_dir, f"{image_id}_{suffix}")
            if p.exists() and p.is_file() and not p.is_symlink():
                try:
                    p.unlink()
                    deleted_any = True
                except OSError:
                    pass
        return deleted_any
