"""crisis_resources.py — a LIGHT, offline, honest "human bridge" for the SAFETY/harm path.

A curated Thailand emergency contact list, adapted from prior internal design work: when a query
signals harm/self-harm, a referral is only useful if it points to REAL human help. This module ships a
small static directory of crisis resources (Thailand + an international fallback) so the choice-first
SAFETY path can be a genuine bridge, not a vague "see a hotline".

HONESTY: numbers can change and AI is NOT an emergency service. Every rendering carries a
verify-and-this-is-not-emergency-services disclaimer. No network is used — this is static data
an org can override. readout-not-truth.
"""
from __future__ import annotations

# Thailand resources, adapted from prior internal design work. Verify periodically.
_THAILAND = [
    ("เหตุฉุกเฉิน / ตำรวจ", "191"),
    ("การแพทย์ฉุกเฉิน", "1669"),
    ("สายด่วนสุขภาพจิต กรมสุขภาพจิต", "1323"),
    ("Samaritans Thailand (รับฟัง ไม่ตัดสิน)", "02-713-6793"),
    ("OSCC ศูนย์ช่วยเหลือสังคม (ความรุนแรงในครอบครัว)", "1300"),
    ("สายด่วนคุ้มครองเด็ก", "1387"),
]

# International fallback — no fabricated numbers; point to local emergency + a real directory service.
_INTERNATIONAL = {
    "en": [
        ("If you are in immediate danger", "call your local emergency number now"),
        ("Find a free helpline in your country", "https://findahelpline.com"),
    ],
    "th": [
        ("ถ้าตกอยู่ในอันตรายเฉพาะหน้า", "โทรเบอร์ฉุกเฉินในพื้นที่ของคุณทันที"),
        ("ค้นหาสายด่วนฟรีในประเทศของคุณ", "https://findahelpline.com"),
    ],
}

_HEADER = {
    "th": "ถ้าต้องการความช่วยเหลือเร่งด่วน ติดต่อได้ที่:",
    "en": "If you need urgent help, here are real people you can reach:",
}
_DISCLAIMER = {
    "th": "(ผมไม่ใช่บริการฉุกเฉิน ข้อมูลติดต่ออาจเปลี่ยนแปลง โปรดตรวจสอบ — แต่การติดต่อขอความช่วยเหลือนั้นคุ้มค่าเสมอ)",
    "en": "(I am not an emergency service and these details may change — please verify. Reaching out is always worth it.)",
}


def resources(lang: str = "en", region: str = "TH") -> list:
    """Return a list of (label, contact) crisis resources for the language/region (static, offline)."""
    out = []
    if (region or "").upper() == "TH":
        out += _THAILAND
    out += _INTERNATIONAL.get(lang, _INTERNATIONAL["en"])
    return out


def render(lang: str = "en", region: str = "TH") -> str:
    """Render the crisis resources as an honest, plain block in the given language."""
    lines = [_HEADER.get(lang, _HEADER["en"])]
    for label, contact in resources(lang, region):
        lines.append(f"  • {label}: {contact}")
    lines.append(_DISCLAIMER.get(lang, _DISCLAIMER["en"]))
    return "\n".join(lines)
