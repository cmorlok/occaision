import io
from pathlib import Path
import pytest
from PIL import Image
from PIL.ExifTags import Base, GPS
import pillow_heif

pillow_heif.register_heif_opener()

@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "images").mkdir(parents=True, exist_ok=True)
    return data_dir

@pytest.fixture
def synthetic_exif_jpeg() -> bytes:
    img = Image.new("RGB", (3000, 2000), color=(120, 150, 180))
    exif = img.getexif()
    exif[Base.Make] = "TestCamera"
    exif[Base.Model] = "ModelPro"
    gps_ifd = exif.get_ifd(Base.GPSInfo)
    gps_ifd[GPS.GPSLatitude] = (47, 22, 0)
    gps_ifd[GPS.GPSLatitudeRef] = "N"
    gps_ifd[GPS.GPSLongitude] = (8, 33, 0)
    gps_ifd[GPS.GPSLongitudeRef] = "E"
    
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif, quality=95)
    return buf.getvalue()

@pytest.fixture
def synthetic_heic_image() -> bytes:
    img = Image.new("RGB", (400, 300), color=(40, 180, 90))
    heif_file = pillow_heif.from_pillow(img)
    buf = io.BytesIO()
    heif_file.save(buf, format="HEIF")
    return buf.getvalue()
