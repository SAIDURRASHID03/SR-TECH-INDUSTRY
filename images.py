"""Image handling: re-upload to the site's Cloudinary so the site never
hotlinks third-party servers (hotlinks break and leak referrers).

On ANY failure, returns the original URL and logs a warning — an image
problem must never break a deal run.
"""

import sys

import requests

CLOUD_NAME = "m7ptgc1f"
UPLOAD_PRESET = "SR PHOTO INDUSTRY"
FOLDER = "site-deals"
UPLOAD_URL = f"https://api.cloudinary.com/v1_1/{CLOUD_NAME}/image/upload"

UA = {"User-Agent": "SRTechIndustryDealBot/1.0 (+https://srtechindustry03.blogspot.com)"}


def upload(url):
    """Download `url` and upload to Cloudinary. Returns secure_url, or `url` on failure."""
    if not url:
        return ""
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "")
        if "image" not in ctype and len(r.content) < 1024:
            raise ValueError(f"not an image (content-type {ctype!r})")
        files = {"file": ("deal.jpg", r.content)}
        data = {"upload_preset": UPLOAD_PRESET, "folder": FOLDER}
        u = requests.post(UPLOAD_URL, data=data, files=files, timeout=30)
        u.raise_for_status()
        secure = u.json().get("secure_url", "")
        if not secure:
            raise ValueError("Cloudinary returned no secure_url")
        return secure
    except Exception as ex:
        print(f"[images] upload failed for {url[:80]}: {ex} — keeping original URL", file=sys.stderr)
        return url
