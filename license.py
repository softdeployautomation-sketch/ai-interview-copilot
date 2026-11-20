"""
AI Interview Copilot — License System
HMAC-signed license keys with hardware (machine ID) binding.

Reuses the same architecture as Lead Extractor Pro.
Buyers receive a license key tied to their email + machine.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# ── Configuration ─────────────────────────────────────────────────────────
# In production, change this secret. Store it ONLY on your machine.
LICENSE_SECRET = os.environ.get(
    "LICENSE_SECRET",
    "buildwithai-ai-interview-copilot-v1-secret-change-me"
)

LICENSE_FILE = Path(os.environ.get("LICENSE_FILE", str(Path(__file__).parent / ".license"))).expanduser()


# ── Machine ID ────────────────────────────────────────────────────────────
def _macos_hwid() -> Optional[str]:
    try:
        out = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            for line in out.stdout.splitlines():
                if "IOPlatformUUID" in line:
                    parts = line.split('"')
                    if len(parts) >= 4:
                        return parts[3]
    except Exception:
        pass
    return None


def _linux_hwid() -> Optional[str]:
    for p in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
        try:
            with open(p) as f:
                v = f.read().strip()
                if v:
                    return v
        except Exception:
            pass
    return None


def _windows_hwid() -> Optional[str]:
    try:
        out = subprocess.run(
            ["wmic", "csproduct", "get", "uuid"],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            for line in out.stdout.strip().splitlines():
                line = line.strip()
                if line and line.upper() != "UUID" and len(line) > 10:
                    return line.upper()
    except Exception:
        pass
    return None


def get_machine_id() -> str:
    """Return a stable hardware ID for this machine (16 hex chars)."""
    system = platform.system()
    hwid = None
    if system == "Darwin":
        hwid = _macos_hwid()
    elif system == "Linux":
        hwid = _linux_hwid()
    elif system == "Windows":
        hwid = _windows_hwid()

    if not hwid:
        # Fallback: use MAC + hostname (less stable but works on weird systems)
        mac = ":".join(f"{(uuid.getnode() >> i) & 0xff:02x}" for i in range(0, 48, 8)[::-1])
        hwid = f"{platform.node()}|{mac}|{platform.system()}"

    return hashlib.sha256(hwid.encode()).hexdigest()[:16]


# ── Key generation (admin only) ───────────────────────────────────────────
def generate_license_key(
    licensee_name: str,
    machine_id: str = "",
    plan: str = "pro",
    days_valid: int = 36500,  # 100 years = effectively lifetime
) -> str:
    """Generate an HMAC-signed license key. Run by admin only."""
    now = datetime.utcnow()
    payload = {
        "licensee": licensee_name,
        "plan": plan,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(days=days_valid)).isoformat(),
    }
    if machine_id:
        payload["machine_id"] = machine_id.replace("-", "").replace(" ", "").lower()

    payload_json = json.dumps(payload, sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode()

    signature = hmac.new(
        LICENSE_SECRET.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()

    return f"{payload_b64}.{signature}"


# ── Validation ────────────────────────────────────────────────────────────
@dataclass
class LicenseInfo:
    valid: bool
    licensee: str = ""
    plan: str = ""
    expires_at: str = ""
    error: str = ""


def validate_license(license_key: str) -> LicenseInfo:
    """Verify a license key. Returns LicenseInfo with status."""
    if not license_key or not license_key.strip():
        return LicenseInfo(valid=False, error="No license key provided")

    key = license_key.strip().replace(" ", "").replace("\n", "")

    try:
        parts = key.split(".")
        if len(parts) != 2:
            return LicenseInfo(valid=False, error="Invalid license format")

        payload_b64, provided_sig = parts

        expected_sig = hmac.new(
            LICENSE_SECRET.encode(),
            payload_b64.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(provided_sig, expected_sig):
            return LicenseInfo(valid=False, error="Invalid signature — key may be tampered or wrong product")

        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()))

        # Check expiry
        expires_at = datetime.fromisoformat(payload["expires_at"])
        if datetime.utcnow() > expires_at:
            return LicenseInfo(valid=False, error="License expired", expires_at=payload["expires_at"])

        # Check machine binding
        bound_machine = payload.get("machine_id")
        if bound_machine:
            current = get_machine_id().lower()
            if bound_machine.lower() != current:
                return LicenseInfo(
                    valid=False,
                    error="License is not valid for this computer. Contact support if you've changed machines.",
                )

        return LicenseInfo(
            valid=True,
            licensee=payload.get("licensee", ""),
            plan=payload.get("plan", "pro"),
            expires_at=payload.get("expires_at", ""),
        )

    except Exception as e:
        return LicenseInfo(valid=False, error=f"License read error: {str(e)}")


# ── Persistent license storage ────────────────────────────────────────────
def save_license(license_key: str) -> None:
    """Save license key to disk for future launches."""
    LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_FILE.write_text(license_key.strip())


def load_license() -> Optional[str]:
    """Load license key from disk if exists."""
    try:
        if LICENSE_FILE.exists():
            return LICENSE_FILE.read_text().strip()
    except Exception:
        pass
    return None


def is_activated() -> tuple[bool, LicenseInfo]:
    """Check if a valid license exists on this machine."""
    key = load_license()
    if not key:
        return False, LicenseInfo(valid=False, error="Not activated")
    info = validate_license(key)
    return info.valid, info


# ── CLI: generate a key as admin ──────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="License management CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_gen = sub.add_parser("generate", help="Generate a new license key")
    p_gen.add_argument("--name", required=True, help="Customer name or email")
    p_gen.add_argument("--hwid", default="", help="Machine ID (optional, locks to machine)")
    p_gen.add_argument("--plan", default="pro")
    p_gen.add_argument("--days", type=int, default=36500)

    p_hwid = sub.add_parser("hwid", help="Print this machine's hardware ID")

    p_check = sub.add_parser("check", help="Validate the saved license")

    args = parser.parse_args()

    if args.cmd == "generate":
        key = generate_license_key(args.name, args.hwid, args.plan, args.days)
        print("\n═══ LICENSE KEY ═══\n")
        print(key)
        print("\n═══════════════════\n")
        print(f"Licensee: {args.name}")
        print(f"Plan:     {args.plan}")
        print(f"Valid:    {args.days} days")
        if args.hwid:
            print(f"Bound to machine: {args.hwid}")
        else:
            print("⚠️  Not bound to a machine — anyone with this key can use it")

    elif args.cmd == "hwid":
        print(f"Hardware ID: {get_machine_id()}")

    elif args.cmd == "check":
        ok, info = is_activated()
        if ok:
            print(f"✅ Activated for: {info.licensee} ({info.plan})")
            print(f"   Expires: {info.expires_at}")
        else:
            print(f"❌ Not activated: {info.error}")

    else:
        parser.print_help()
