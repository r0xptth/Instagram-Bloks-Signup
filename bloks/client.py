"""
Mobile Safari CAA Bloks signup client.

Reverse-engineered from Stream HAR ``Stream-2026-07-24 220559.har``
(iPhone Safari → www.instagram.com /async/wbloks/fetch CAA reg flow).

Source of truth for appids / reg_info / machine_id / create.account.async:
``MOBILE_HAR_FILE`` below (same capture as ``har_mobile_bloks.py``).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import random
import re
import string
import struct
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import names
from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)

# Phone Safari CAA Bloks capture used to freeze this client.
MOBILE_HAR_FILE = Path(__file__).resolve().parent / "Stream-2026-07-24 220559.har"

# Captured from Stream HAR (live scrape overrides __bkv).
DEFAULT_BKV = (
    "e6c910efb6dfff3473968638858dc4405e6c00c66386d0569e239460ac9c2309"
)
# HAR machine_id examples from contactpoint_email.async → confirmation:
#   EidkauWQHSu3Dp0mpUqXdyts, EidkanwuXKkoEDfJzGzer_Bp  (both exactly 24 chars)
#
# The boundaries matter: reg_context is a ~10KB AV…|regm blob that contains its
# own longer "Eid…" substrings (e.g. Eid1C9wFkrXUFUTBDZTGbphqW7vtgxn3Nx…), so an
# unanchored pattern happily scrapes one of those as the machine_id and sends
# garbage to create.account.async.
_MACHINE_ID_TOKEN = r"(?<![A-Za-z0-9_-])Eid[A-Za-z0-9_-]{18,32}(?![A-Za-z0-9_-])"
_MACHINE_ID_RE = re.compile(_MACHINE_ID_TOKEN)
_MACHINE_ID_NEAR_KEY_RE = re.compile(
    r"machine_id.{0,40}?(" + _MACHINE_ID_TOKEN + r")"
)
# Present our own device machine_id when the server never issues one, instead
# of aborting and burning an already-verified email. BLOKS_SYNTH_MACHINE_ID=0
# restores the old hard-fail.
SYNTH_MACHINE_ID = os.environ.get("BLOKS_SYNTH_MACHINE_ID", "1").strip() not in (
    "0",
    "false",
    "no",
)

IG_APP_ID = "1217981644879628"
FLOW_INFO = '{"flow_name":"new_to_family_ig_mweb_default","flow_type":"ntf"}'
CRN = "comet.igweb.PolarisWebBloksRegRoute"

APP = {
    "contactpoint_email": "com.bloks.www.bloks.caa.reg.contactpoint_email",
    "confirmation": "com.bloks.www.bloks.caa.reg.confirmation",
    "password": "com.bloks.www.bloks.caa.reg.password",
    "birthday": "com.bloks.www.bloks.caa.reg.birthday",
    "name": "com.bloks.www.bloks.caa.reg.name.ig.and.soap",
    "username": "com.bloks.www.bloks.caa.reg.username",
    "tos": "com.bloks.www.bloks.caa.reg.tos",
}
ACTION = {
    "contactpoint_email": "com.bloks.www.bloks.caa.reg.async.contactpoint_email.async",
    "confirmation": "com.bloks.www.bloks.caa.reg.confirmation.async",
    "password": "com.bloks.www.bloks.caa.reg.password.async",
    "birthday": "com.bloks.www.bloks.caa.reg.birthday.async",
    "name": "com.bloks.www.bloks.caa.reg.name_ig_and_soap.async",
    "username": "com.bloks.www.bloks.caa.reg.username.async",
    # Embedded in TOS app Bloks payload (missing as a live POST in the HAR).
    "create_account": "com.bloks.www.bloks.caa.reg.create.account.async",
    # HAR TOS on_success after create.account.async → session cookies.
    "send_login": "com.bloks.www.bloks.caa.login.async.send_login_request",
}

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5.2 "
    "Mobile/15E148 Safari/604.1"
)


class MobileBloksSignupError(Exception):
    """Raised when the mobile Bloks CAA signup flow fails."""


def _find(pattern: str, text: str, flags: int = 0) -> Optional[str]:
    m = re.search(pattern, text or "", flags)
    return m.group(1) if m else None


def _empty_reg_info(device_id: str) -> Dict[str, Any]:
    """Skeleton reg_info matching the HAR contactpoint_email boot payload."""
    return {
        "first_name": None,
        "last_name": None,
        "full_name": None,
        "contactpoint": None,
        "ar_contactpoint": None,
        "attempted_empty_last_name": None,
        "contactpoint_type": None,
        "is_using_unified_cp": False,
        "unified_cp_screen_variant": "control",
        "is_cp_auto_confirmed": False,
        "is_cp_auto_confirmable": False,
        "is_cp_claimed": False,
        "confirmation_code": None,
        "birthday": None,
        "birthday_derived_from_age": None,
        "age_range": None,
        "did_use_age": False,
        "os_shared_age_range": None,
        "gender": None,
        "use_custom_gender": False,
        "custom_gender": None,
        "encrypted_password": None,
        "username": None,
        "username_prefill": None,
        "accounts_list_client": [],
        "fb_conf_source": None,
        "device_id": device_id,
        "ig4a_qe_device_id": None,
        "family_device_id": None,
        "fdid_available_on_start": None,
        "fdid_rid_available_on_start": None,
        "asdid_available_on_start": None,
        "user_id": None,
        "safetynet_token": None,
        "skip_slow_rel_check": False,
        "safetynet_response": None,
        "machine_id": None,
        "profile_photo": None,
        "profile_photo_id": None,
        "profile_photo_upload_id": None,
        "avatar": None,
        "email_oauth_token_no_contact_perm": None,
        "email_oauth_token": None,
        "email_oauth_tokens": [],
        "sign_in_with_google_email": None,
        "should_skip_two_step_conf": None,
        "openid_tokens_for_testing": None,
        "opt_out_source_account_reg_info_logging_only": None,
        "encrypted_msisdn": None,
        "encrypted_msisdn_for_safetynet": None,
        "cached_headers_safetynet_info": None,
        "should_skip_headers_safetynet": None,
        "headers_last_infra_flow_id": None,
        "headers_last_infra_flow_id_safetynet": None,
        "headers_flow_id": None,
        "was_headers_prefill_available": None,
        "sso_enabled": None,
        "existing_accounts": None,
        "used_ig_birthday": None,
        "create_new_to_app_account": None,
        "skip_session_info": None,
        "ck_error": None,
        "ck_id": None,
        "ck_nonce": None,
        "should_save_password": None,
        "fb_access_token": None,
        "is_msplit_reg": None,
        "is_spectra_reg": None,
        "dema_account_consent_given": None,
        "spectra_entry_source": None,
        "spectra_reg_token": None,
        "spectra_reg_guardian_id": None,
        "spectra_reg_guardian_logged_in_context": None,
        "spectra_requester_user_id": None,
        "user_id_of_msplit_creator": None,
        "msplit_creator_nonce": None,
        "dma_data_combination_consent_given": None,
        "xapp_accounts": None,
        "fb_device_id": None,
        "fb_machine_id": None,
        "ig_device_id": None,
        "ig_machine_id": None,
        "should_skip_nta_upsell": None,
        "big_blue_token": None,
        "caa_reg_flow_source": None,
        "ig_authorization_token": None,
        "full_sheet_flow": False,
        "crypted_user_id": None,
        "is_ca_late_teen": None,
        "is_early_teen": None,
        "is_caa_perf_enabled": False,
        "is_preform": True,
        # Present on later HAR steps / create.account.async reg_info.
        "should_show_spi_before_conf": True,
        "screen_visited": [
            "CAA_REG_CONTACT_POINT_PHONE",
            "CAA_REG_CONTACT_POINT_EMAIL",
        ],
        "suma_on_conf_threshold": -1,
        "should_show_error_msg": True,
        "ig_footer_variant": "control",
        "force_sessionless_nux_experience": False,
        "has_seen_suma_landing_page_pre_conf": False,
        "has_seen_suma_candidate_page_pre_conf": False,
        "has_seen_confirmation_screen": False,
        "fb_email_login_upsell_skip_suma_post_tos": False,
        "fb_suma_is_from_email_login_upsell": False,
        "fb_suma_is_from_phone_login_upsell": False,
        "ig_partially_created_account_user_id": None,
        "ig_partially_created_account_nonce": None,
        "ig_partially_created_account_nonce_expiry": None,
    }


def _unescape_layers(text: str, rounds: int = 6) -> List[str]:
    """Yield progressively unescaped views of a Bloks body (\\\" → \")."""
    views = [text]
    cur = text
    for _ in range(rounds):
        if "\\" not in cur:
            break
        # One JSON/JS escape layer at a time (safer than unicode_escape on whole body).
        nxt = re.sub(r"\\(.)", r"\1", cur)
        if nxt == cur:
            break
        views.append(nxt)
        cur = nxt
    return views


def _find_escaped_string_field(text: str, key: str) -> Optional[str]:
    """
    Match key/value pairs under heavy Bloks escaping.

    Live/HAR bodies use 1–3 backslashes before quotes, e.g.
    ``\\\\\\"confirmation_code\\\\\\":\\\\\\"wTyVB56C\\\\\\"``.
    """
    if not text or not key:
        return None
    # Reject sibling keys like confirmation_code_acquired / _send_error.
    pat = (
        rf'(?<![A-Za-z0-9_]){re.escape(key)}'
        rf'\\*"\s*:\s*\\*"([^\\"\s]{{2,128}})\\*"'
    )
    m = re.search(pat, text)
    if not m:
        # After partial unescape: "confirmation_code":"wTyVB56C"
        m = re.search(
            rf'(?<![A-Za-z0-9_]){re.escape(key)}"\s*:\s*"([^"\s]{{2,128}})"',
            text,
        )
    if not m:
        return None
    val = m.group(1)
    if val in ("null", "None", "true", "false"):
        return None
    # Bloks often encodes '@' as \\u0040 inside nested JSON strings.
    if "\\u" in val or "\\/" in val:
        try:
            val = json.loads(f'"{val}"')
        except Exception:
            val = val.replace("\\/", "/")
    return val


def _reg_info_score(obj: Dict[str, Any]) -> int:
    """Prefer HAR-shaped reg_info blobs that already carry create-critical fields."""
    score = 0
    for key in (
        "machine_id",
        "confirmation_code",
        "encrypted_password",
        "username",
        "birthday",
        "full_name",
        "contactpoint",
    ):
        if obj.get(key):
            score += 1
    if isinstance(obj.get("screen_visited"), list) and obj["screen_visited"]:
        score += 1
    return score


def _extract_reg_info_dict(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort parse of a full reg_info object embedded in Bloks JSON."""
    if not text:
        return None
    needle = '{"first_name":'
    best: Optional[Dict[str, Any]] = None
    best_score = -1
    for view in _unescape_layers(text):
        start = 0
        while True:
            idx = view.find(needle, start)
            if idx < 0:
                break
            try:
                obj, _ = json.JSONDecoder().raw_decode(view[idx:])
            except Exception:
                start = idx + 1
                continue
            if (
                isinstance(obj, dict)
                and "device_id" in obj
                and ("confirmation_code" in obj or "contactpoint" in obj)
            ):
                score = _reg_info_score(obj)
                if score > best_score:
                    best = obj
                    best_score = score
            start = idx + 1
        if best_score >= 4:
            break
    return best


def _extract_machine_id(text: str) -> Optional[str]:
    """
    Pull Bloks ``machine_id`` from a response.

    In ``Stream-2026-07-24 220559.har``, contactpoint_email.async returns
    values like ``EidkanwuXKkoEDfJzGzer_Bp``; confirmation/password/tos
    requests then send that same token inside ``reg_info.machine_id``.
    """
    if not text:
        return None
    # Prefer key-associated value (any escape depth).
    for view in _unescape_layers(text):
        val = _find_escaped_string_field(view, "machine_id")
        if val and _MACHINE_ID_RE.fullmatch(val):
            return val
        # Key nearby then Eid… token (handles odd nesting).
        m = _MACHINE_ID_NEAR_KEY_RE.search(view)
        if m:
            return m.group(1)
    # Last resort: a standalone Eid… token in the body. Scan the reg_context
    # blob out first so its embedded Eid… substrings can't win.
    stripped = re.sub(r"AV[A-Za-z0-9_\-]{80,}\|regm", "", text)
    hits = _MACHINE_ID_RE.findall(stripped)
    return hits[-1] if hits else None


def _synthesize_machine_id(max_age_days: float = 21.0) -> str:
    """
    Build a structurally valid CAA ``machine_id``.

    The two tokens in the HAR decode to 18 bytes with a fixed 2-byte header, a
    big-endian unix creation timestamp, and 12 random bytes::

        EidkanwuXKkoEDfJzGzer_Bp -> 1227 646a7c2e 5ca9281037c9cc6cdeaff069
        EidkauWQHSu3Dp0mpUqXdyts -> 1227 646ae590 1d2bb70e9d26a54a97772b6c

    Re-encoding those timestamps reproduces the ``Eidkan`` / ``Eidkau``
    prefixes exactly, which is what pins the layout down.

    This is a persistent *device* value that a real browser replays from local
    storage, so it is never returned in a signup response — a fresh automated
    session has nothing to scrape and must present its own.
    """
    created = int(time.time() - random.uniform(3600, max_age_days * 86400))
    raw = b"\x12\x27" + struct.pack(">I", created) + os.urandom(12)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _absorb_reg_info_fields(reg: Dict[str, Any], text: str) -> None:
    """Pull updated reg_info scalars / blobs out of a Bloks response body."""
    if not text:
        return
    prior_machine = reg.get("machine_id")
    # Prefer a full reg_info object when Bloks embeds one (keeps schema parity).
    full = _extract_reg_info_dict(text)
    if full:
        # Never clobber secrets / fields we already set locally with nulls/empties.
        for k, v in full.items():
            if v in (None, "", [], {}) and reg.get(k) not in (None, "", [], {}):
                continue
            if k == "encrypted_password" and reg.get("encrypted_password"):
                continue
            if k == "username" and reg.get("username") and not v:
                continue
            # HAR: once machine_id is issued (Eid…), later screens may echo
            # null/"" — never drop it (name app request in the HAR even sends null).
            if k == "machine_id" and reg.get("machine_id") and (
                not v or not _MACHINE_ID_RE.fullmatch(str(v))
            ):
                continue
            reg[k] = v
    keys = (
        "confirmation_code",
        "machine_id",
        "username_prefill",
        "username",
        "age_range",
        "contactpoint",
        "contactpoint_type",
        "full_name",
    )
    for view in _unescape_layers(text):
        for key in keys:
            if reg.get(key):
                continue
            val = _find_escaped_string_field(view, key)
            if not val:
                continue
            if key == "username" and not re.fullmatch(r"[A-Za-z0-9._]{3,30}", val):
                continue
            if key == "confirmation_code" and len(val) < 4:
                continue
            if key == "machine_id" and not _MACHINE_ID_RE.fullmatch(val):
                continue
            reg[key] = val
    if not reg.get("machine_id"):
        mid = _extract_machine_id(text)
        if mid:
            reg["machine_id"] = mid
    # Never drop a previously captured HAR-shaped machine_id.
    if prior_machine and not reg.get("machine_id"):
        reg["machine_id"] = prior_machine


def _extract_reg_context(text: str) -> Optional[str]:
    if not text:
        return None
    for view in _unescape_layers(text):
        m = re.search(
            r'reg_context\\*"\s*:\s*\\*"(AV[^"\\]{80,}?\|regm)\\*"',
            view,
        )
        if m:
            return m.group(1)
        m = re.search(r'"reg_context"\s*:\s*"(AV[^"]{80,}?\|regm)"', view)
        if m:
            return m.group(1)
        m = re.search(r"(AV[A-Za-z0-9_\-]{80,}\|regm)", view)
        if m:
            return m.group(1)
    return None


def _parse_create_failure(text: str) -> Optional[str]:
    """
    Extract create_failure / exception_category from Bloks create responses.

    Live integrity denials look like empty ``data:[]`` payloads but embed:
      state=create_failure, exception_category=integrity_block
    (not a #PWD_BROWSER version mismatch).
    """
    if not text:
        return None
    # Work across escape layers (\\\"state\\\" etc.).
    cat = None
    state = None
    for view in _unescape_layers(text, rounds=4):
        if cat is None:
            m = re.search(
                r'exception_category["\\\s:]+([A-Za-z0-9_]+)',
                view,
                re.I,
            )
            if m:
                cat = m.group(1)
        if state is None:
            m = re.search(
                r'(?<![A-Za-z_])state["\\\s:]+(create_failure|create_attempt|create_success)',
                view,
                re.I,
            )
            if m:
                state = m.group(1).lower()
        if cat or state == "create_failure":
            break
    if cat:
        return f"create_failure exception_category={cat}"
    if state == "create_failure":
        return "create_failure (no exception_category)"
    if "integrity_block" in text.lower():
        return "create_failure exception_category=integrity_block"
    return None


def _bloks_error(text: str) -> Optional[str]:
    if not text:
        return "empty response"
    create_fail = _parse_create_failure(text)
    if create_fail:
        return create_fail
    low = text.lower()
    for needle in (
        "something went wrong",
        "try again",
        "not allowed",
        "rate limit",
        "suspicious",
        "checkpoint",
        "invalid confirmation",
        "incorrect code",
        "code you entered",
        "already associated",
        "not available",
    ):
        if needle in low:
            # snip a short context
            idx = low.find(needle)
            return text[max(0, idx - 40) : idx + 80].replace("\n", " ")
    if '"error"' in low and "1357001" in text.replace(" ", ""):
        return "bloks not-logged-in / session error"
    return None


class MobileBloksCAASignupClient:
    """
    iPhone Safari CAA Bloks registration (mobile web).

    Flow (from HAR):
      bootstrap → contactpoint_email → confirmation(code) → password →
      birthday → name → username → tos/create → session cookies
    """

    SIGNUP_URL = "https://www.instagram.com/accounts/signup/email/"
    SIGNUP_PHONE_URL = "https://www.instagram.com/accounts/signup/phone/"

    def __init__(
        self,
        proxies: Optional[Dict] = None,
        email_client: Optional[Any] = None,
        country: str = "US",
        language: str = "en",
        timezone: str = "America/Chicago",
    ):
        self.proxies = proxies
        self.email_client = email_client
        self.country = country
        self.language = language
        self.timezone = timezone or "America/Chicago"

        # Safari UA; TLS via chrome impersonate (curl_cffi has no Safari JA3).
        self.impersonate = "chrome142"
        self.session = curl_requests.Session(impersonate=self.impersonate)
        self.user_agent = IPHONE_UA

        self.csrf_token: Optional[str] = None
        self.mid: Optional[str] = None
        self.lsd: Optional[str] = None
        self.datr: Optional[str] = None
        self.ig_did: Optional[str] = None
        self.enc_key_id: Optional[int] = None
        self.enc_pub_key: Optional[str] = None
        self.enc_version: str = "5"
        self.bkv: str = DEFAULT_BKV
        self.hs: Optional[str] = None
        self.hsi: Optional[str] = None
        self.spin_t: Optional[str] = None
        self.rev: Optional[str] = None
        self.dyn: Optional[str] = None
        self.csr: Optional[str] = None
        self.hsdp: Optional[str] = None
        self.hblp: Optional[str] = None
        self.sjsp: Optional[str] = None
        self.reg_context: Optional[str] = None
        self.reg_info: Dict[str, Any] = {}
        self.waterfall_id = str(uuid.uuid4())
        self._req_n = 1
        self.last_text: str = ""
        self.current_step: int = 0
        self.password: str = ""
        self.enc_password: str = ""

        self.stats: Dict[str, Any] = {
            "stages": [],
            "egress_ip": None,
            "egress_geo": None,
            "email": None,
            "username": None,
            "current_stage": None,
            "failed_stage": None,
            "error_category": None,
            "error_hint": None,
            "auth": "mobile_bloks",
        }
        self.log_request_ip = os.environ.get("LOG_REQUEST_IP", "1").strip() not in (
            "0", "false", "False",
        )

    # --- shared helpers (mirror CAASignupClient stats / egress) ---------------

    def _record(self, name: str, ok: bool, detail: str = "", seconds: float = 0.0) -> None:
        self.stats["stages"].append({
            "name": name, "ok": ok, "detail": detail, "seconds": round(seconds, 1),
        })

    def _resolve_egress(self) -> str:
        from .util import get_egress_geo, get_egress_ip

        ip = get_egress_ip(self.proxies)
        self.stats["egress_ip"] = ip
        if ip and not str(ip).startswith("unknown"):
            self.stats["egress_geo"] = get_egress_geo(ip)
            logger.info(
                "Mobile Bloks egress IP: %s country=%s",
                ip,
                (self.stats["egress_geo"] or {}).get("country") or "?",
            )
        return str(ip)

    @staticmethod
    def _human_pause(lo: float = 0.6, hi: float = 1.6) -> None:
        time.sleep(random.uniform(lo, hi))

    def _jazoest(self) -> str:
        return "2" + str(sum(ord(c) for c in (self.lsd or "")))

    def _next_req(self) -> str:
        n = self._req_n
        self._req_n += 1
        return format(n, "x")

    def _nav_headers(self) -> Dict[str, str]:
        return {
            "accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "*/*;q=0.8"
            ),
            "accept-language": "en-US,en;q=0.9",
            "user-agent": self.user_agent,
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "upgrade-insecure-requests": "1",
        }

    def _bloks_headers(self, *, action: bool) -> Dict[str, str]:
        h = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
            "origin": "https://www.instagram.com",
            "referer": self.SIGNUP_URL,
            "user-agent": self.user_agent,
            "x-asbd-id": "359341",
            "x-csrftoken": self.csrf_token or "",
            "x-fb-lsd": self.lsd or "",
            "x-ig-app-id": IG_APP_ID,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        if action:
            h["x-root-field-name"] = "bloks_action"
        return h

    def _form_base(self) -> Dict[str, str]:
        body: Dict[str, str] = {
            "__d": "www",
            "__user": "0",
            "__a": "1",
            "__req": self._next_req(),
            "dpr": "3",
            "__ccg": "EXCELLENT",
            "__comet_req": "7",
            "__crn": CRN,
            "lsd": self.lsd or "",
            "jazoest": self._jazoest(),
        }
        if self.rev:
            body["__rev"] = self.rev
            body["__spin_r"] = self.rev
            body["__spin_b"] = "trunk"
        if self.spin_t:
            body["__spin_t"] = self.spin_t
        if self.hs:
            body["__hs"] = self.hs
        if self.hsi:
            body["__hsi"] = self.hsi
        if self.hsdp:
            body["__hsdp"] = self.hsdp
        if self.hblp:
            body["__hblp"] = self.hblp
        if self.sjsp:
            body["__sjsp"] = self.sjsp
        body["__dyn"] = self.dyn or (
            "7xeUjG1mwt8K2Wmh0no6u5U4e0yoW3q32360CEbo1nEhw2nVE4W0qa0FE2awt81s8hwGw"
            "QwoEcE7O2l0Fwqo31w9O0H8jwae4UaEW2G0AEco5G0zK5o4q0HU1IEGdwtU662O0Lo6-"
            "3u2WE15E6O1FwlAcwnJ6goK1sAwHxW1ow8q0EoK9x60ma1XwqU1eUdo"
        )
        body["__csr"] = self.csr or ""
        body.setdefault(
            "__s",
            f"{os.urandom(3).hex()}:{os.urandom(3).hex()}:{os.urandom(3).hex()}",
        )
        return body

    def wbloks(
        self,
        appid: str,
        *,
        action: bool,
        server_params: Dict[str, Any],
        client_input_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """POST /async/wbloks/fetch with HAR-shaped double-encoded params."""
        typ = "action" if action else "app"
        url = (
            f"https://www.instagram.com/async/wbloks/fetch/"
            f"?appid={quote(appid, safe='.')}&type={typ}&__bkv={self.bkv}"
        )
        # reg_info must be a JSON string inside server_params (HAR shape).
        sp = dict(server_params)
        reg = sp.get("reg_info")
        if isinstance(reg, dict):
            sp["reg_info"] = json.dumps(reg, separators=(",", ":"))
        elif reg is None and self.reg_info:
            sp["reg_info"] = json.dumps(self.reg_info, separators=(",", ":"))

        inner: Dict[str, Any] = {
            "server_params": sp,
            "client_input_params": client_input_params or {},
        }
        body = self._form_base()
        body["params"] = json.dumps(
            {"params": json.dumps(inner, separators=(",", ":"))},
            separators=(",", ":"),
        )

        if self.log_request_ip:
            logger.info(
                "[%s] POST wbloks %s type=%s",
                self.stats.get("egress_ip") or "?",
                appid.split("caa.reg.")[-1],
                typ,
            )
        resp = self.session.post(
            url,
            headers=self._bloks_headers(action=action),
            data=body,
            proxies=self.proxies,
            timeout=50,
        )
        text = resp.text or ""
        self.last_text = text
        logger.info(
            "wbloks %s → HTTP %s (%d bytes)",
            appid.split(".")[-1],
            resp.status_code,
            len(text),
        )
        if resp.status_code >= 400:
            raise MobileBloksSignupError(
                f"wbloks HTTP {resp.status_code} for {appid}: {text[:200]!r}"
            )

        # Refresh tokens / context from response.
        bkv = _find(r"__bkv=([0-9a-f]{32,})", text) or _find(
            r'"bloks_version(?:_id)?"\s*:\s*"([0-9a-f]+)"', text
        )
        if bkv:
            self.bkv = bkv
        ctx = _extract_reg_context(text)
        if ctx:
            self.reg_context = ctx
        _absorb_reg_info_fields(self.reg_info, text)

        # Set-Cookie may arrive on create.
        if resp.cookies.get("csrftoken"):
            self.csrf_token = resp.cookies.get("csrftoken")
        return text

    # --- bootstrap -----------------------------------------------------------

    def bootstrap(self) -> None:
        """Load mobile signup page and scrape tokens / __bkv / enc keys."""
        # HAR entered via phone URL then switched to email; email URL is enough.
        for url in (self.SIGNUP_URL, self.SIGNUP_PHONE_URL):
            resp = self.session.get(
                url,
                headers=self._nav_headers(),
                proxies=self.proxies,
                timeout=40,
            )
            html = resp.text or ""
            if resp.status_code == 200 and len(html) > 500:
                break
        else:
            raise MobileBloksSignupError(
                f"Could not load mobile signup page (status={resp.status_code})"
            )

        self.csrf_token = resp.cookies.get("csrftoken") or _find(
            r'"csrf_token"\s*:\s*"([^"]+)"', html
        )
        self.mid = resp.cookies.get("mid") or _find(
            r'"mid"\s*:\s*\{\s*"value"\s*:\s*"([^"]+)"', html
        )
        self.datr = resp.cookies.get("datr")
        self.ig_did = resp.cookies.get("ig_did") or str(uuid.uuid4()).upper()
        self.lsd = _find(r'"LSD",\[\],\{"token":"([^"]+)"', html) or self.lsd
        self.hs = _find(r'"haste_session"\s*:\s*"([^"]+)"', html)
        self.hsi = _find(r'"hsi"\s*:\s*"(\d+)"', html)
        self.spin_t = _find(r'"__spin_t"\s*:\s*(\d+)', html)
        self.rev = (
            _find(r'"server_revision"\s*:\s*(\d+)', html)
            or _find(r'"__spin_r"\s*:\s*(\d+)', html)
            or _find(r'"rollout_hash"\s*:\s*"(\d+)"', html)
        )
        self.dyn = _find(r'"__dyn"\s*:\s*"([^"]+)"', html)
        self.csr = _find(r'"__csr"\s*:\s*"([^"]+)"', html)
        self.hsdp = _find(r'"__hsdp"\s*:\s*"([^"]+)"', html)
        self.hblp = _find(r'"__hblp"\s*:\s*"([^"]+)"', html)
        self.sjsp = _find(r'"__sjsp"\s*:\s*"([^"]+)"', html)
        bkv = _find(r"__bkv=([0-9a-f]{32,})", html) or _find(
            r'"bloks_version(?:_id)?"\s*:\s*"([0-9a-f]+)"', html
        )
        if bkv:
            self.bkv = bkv
        key_id = _find(r'"key_id"\s*:\s*"?(\d+)"?', html)
        self.enc_pub_key = _find(r'"public_key"\s*:\s*"([0-9a-f]{64})"', html)
        # HAR capture used #PWD_BROWSER:5 with that day's key. Live pages advertise
        # the current scheme (usually 10) — mismatch yields empty create responses.
        page_ver = _find(r'"version"\s*:\s*"(\d+)"', html)
        self.enc_version = (
            os.environ.get("MOBILE_BLOKS_PWD_VERSION") or page_ver or "5"
        )
        if page_ver and page_ver != self.enc_version:
            logger.info(
                "Mobile Bloks enc version: using %s (page advertised %s)",
                self.enc_version,
                page_ver,
            )
        elif page_ver:
            logger.info("Mobile Bloks enc version: %s (from page)", self.enc_version)
        self.enc_key_id = int(key_id) if key_id else None

        if not self.mid:
            # Some boots set mid only via Set-Cookie after a follow-up.
            self.session.get(
                "https://www.instagram.com/data/manifest.json",
                headers={"user-agent": self.user_agent, "referer": self.SIGNUP_URL},
                proxies=self.proxies,
                timeout=20,
            )
            self.mid = self.session.cookies.get("mid") or self.mid

        missing = [
            n for n, v in {
                "csrf": self.csrf_token,
                "mid": self.mid,
                "lsd": self.lsd,
                "pub_key": self.enc_pub_key,
                "key_id": self.enc_key_id,
            }.items()
            if not v
        ]
        if missing:
            raise MobileBloksSignupError(
                f"Mobile bootstrap missing {missing}. Body preview: {html[:220]!r}"
            )

        self.reg_info = _empty_reg_info(self.mid)
        # Ensure ig_did cookie exists (HAR always had it).
        try:
            self.session.cookies.set("ig_did", self.ig_did, domain=".instagram.com")
            self.session.cookies.set("wd", "390x699", domain=".instagram.com")
        except Exception:
            pass

        logger.info(
            "Mobile Bloks tokens loaded (mid=%s…, bkv=%s…, key_id=%s, pwd_ver=%s)",
            self.mid[:12],
            self.bkv[:12],
            self.enc_key_id,
            self.enc_version,
        )

    def _base_server_params(
        self,
        *,
        current_step: int,
        screen_id: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        sp: Dict[str, Any] = {
            "device_id": self.mid,
            "is_platform_login": 0,
            "is_from_logged_out": 0,
            "access_flow_version": "pre_mt_behavior",
            "flow_info": FLOW_INFO,
            "current_step": current_step,
            "reg_info": self.reg_info,
            "INTERNAL_INFRA_screen_id": screen_id,
        }
        if self.reg_context:
            sp["reg_context"] = self.reg_context
        if extra:
            sp.update(extra)
        return sp

    def _action_server_params(
        self,
        *,
        current_step: int,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        sp: Dict[str, Any] = {
            "event_request_id": str(uuid.uuid4()),
            "flow_info": FLOW_INFO,
            "current_step": current_step,
            "INTERNAL__latency_qpl_marker_id": 36707139,
            # HAR uses bk.action.i64.Const — send a JSON number, not a string.
            "INTERNAL__latency_qpl_instance_id": int(
                f"{int(time.time() * 1000)}{random.randint(10, 99):02d}"
            ),
            "device_id": self.mid,
            "family_device_id": None,
            "waterfall_id": self.waterfall_id,
            "offline_experiment_group": None,
            "layered_homepage_experiment_group": None,
            "is_platform_login": False,
            "is_from_logged_in_switcher": False,
            "is_from_logged_out": False,
            "access_flow_version": "pre_mt_behavior",
            "login_surface": "unknown",
            "reg_info": self.reg_info,
        }
        if self.reg_context:
            sp["reg_context"] = self.reg_context
        if extra:
            sp.update(extra)
        return sp

    def _lois_cip(self, **extra: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "lois_settings": {"lois_token": ""},
            "aac": "",
            "cloud_trust_token": None,
            "block_store_machine_id": "",
        }
        base.update(extra)
        return base

    def _visit_screen(self, screen_id: str) -> None:
        visited = self.reg_info.setdefault("screen_visited", [])
        if not isinstance(visited, list):
            visited = []
            self.reg_info["screen_visited"] = visited
        if screen_id and screen_id not in visited:
            visited.append(screen_id)

    # --- steps ---------------------------------------------------------------

    def open_contactpoint_email(self) -> None:
        self.current_step = 0
        self._visit_screen("CAA_REG_CONTACT_POINT_EMAIL")
        text = self.wbloks(
            APP["contactpoint_email"],
            action=False,
            server_params=self._base_server_params(
                current_step=0,
                screen_id="CAA_REG_CONTACT_POINT_EMAIL",
                extra={"root_screen_id": "bloks.caa.reg.contactpoint_phone"},
            ),
            client_input_params=self._lois_cip(zero_balance_state=""),
        )
        err = _bloks_error(text)
        if err and "try again" in (err or "").lower() and len(text) < 200:
            raise MobileBloksSignupError(f"contactpoint_email app failed: {err}")

    def submit_email(self, email: str) -> None:
        self.current_step = 0
        self.reg_info["contactpoint"] = None  # HAR: still null on action
        text = self.wbloks(
            ACTION["contactpoint_email"],
            action=True,
            server_params=self._action_server_params(
                current_step=0,
                extra={
                    "cp_funnel": 0,
                    "cp_source": 0,
                    "text_input_id": f"s{random.randint(10000, 99999)}:73",
                },
            ),
            client_input_params=self._lois_cip(
                device_id=self.mid,
                family_device_id="",
                zero_balance_state="",
                email=email,
                email_prefilled=0,
                accounts_list=[],
                fb_ig_device_id=[],
                confirmed_cp_and_code={},
                is_from_device_emails=0,
                msg_previous_cp="",
                switch_cp_first_time_loading=1,
                switch_cp_have_seen_suma=0,
                has_rejected_rel=0,
                seen_login_upsell=0,
                network_bssid=None,
            ),
        )
        self.reg_info["contactpoint"] = email
        self.reg_info["contactpoint_type"] = "email"
        # HAR: machine_id is present on every request from confirmation onward.
        # Real Safari mints it client-side (local storage) — never returns it in
        # a response — so we synthesize here if the server didn't echo one.
        _absorb_reg_info_fields(self.reg_info, text)
        if not self.reg_info.get("machine_id"):
            mid_m = _extract_machine_id(text)
            if mid_m:
                self.reg_info["machine_id"] = mid_m
        if not self.reg_info.get("machine_id") and SYNTH_MACHINE_ID:
            self.reg_info["machine_id"] = _synthesize_machine_id()
            logger.info(
                "Bloks machine_id minted for session (%s…)",
                str(self.reg_info["machine_id"])[:8],
            )
        elif self.reg_info.get("machine_id"):
            logger.info(
                "Bloks machine_id acquired (%s…)",
                str(self.reg_info["machine_id"])[:8],
            )
        err = _bloks_error(text)
        if err and "already" in err.lower():
            raise MobileBloksSignupError(f"email rejected: {err}")

        # Load confirmation screen.
        self.current_step = 2
        self._visit_screen("CAA_REG_CONFIRMATION_SCREEN")
        self.wbloks(
            APP["confirmation"],
            action=False,
            server_params=self._base_server_params(
                current_step=2,
                screen_id="CAA_REG_CONFIRMATION_SCREEN",
                extra={"confirmed_cp_and_code": {}},
            ),
            client_input_params=self._lois_cip(
                machine_id="",
                gms_incoming_call_retriever_eligibility="client_not_supported",
            ),
        )
        if not self.reg_info.get("machine_id"):
            mid_m = _extract_machine_id(self.last_text or "")
            if mid_m:
                self.reg_info["machine_id"] = mid_m
                logger.info(
                    "Bloks machine_id acquired on confirmation app (%s…)",
                    mid_m[:8],
                )

    def submit_code(self, code: str) -> None:
        self.current_step = 2
        text = self.wbloks(
            ACTION["confirmation"],
            action=True,
            server_params=self._action_server_params(
                current_step=2,
                extra={
                    "text_input_id": f"s{random.randint(10000, 99999)}:50",
                    "sms_retriever_started_prior_step": 0,
                    "wa_timer_id": "wa_retriever",
                },
            ),
            client_input_params=self._lois_cip(
                family_device_id="",
                code=str(code).strip(),
                fb_ig_device_id=[],
                confirmed_cp_and_code={},
                network_bssid=None,
            ),
        )
        err = _bloks_error(text)
        if err and ("code" in err.lower() or "invalid" in err.lower()):
            raise MobileBloksSignupError(f"confirmation code rejected: {err}")
        # OTP server token (HAR: wTyVB56C) is buried in multi-escaped Bloks JSON —
        # re-absorb from the confirmation.async body before it is overwritten.
        _absorb_reg_info_fields(self.reg_info, text)
        conf_token = self.reg_info.get("confirmation_code")
        if conf_token:
            logger.info("Bloks confirmation_code token acquired (%s…)", conf_token[:4])

        self.current_step = 3
        self._visit_screen("CAA_REG_PASSWORD")
        self.wbloks(
            APP["password"],
            action=False,
            server_params=self._base_server_params(
                current_step=3,
                screen_id="CAA_REG_PASSWORD",
            ),
            client_input_params=self._lois_cip(machine_id=""),
        )
        if not self.reg_info.get("confirmation_code"):
            raise MobileBloksSignupError(
                "No confirmation_code in Bloks state after OTP "
                f"(preview={text[:180]!r})"
            )

    def submit_password(self, password: str) -> None:
        from .crypto import encrypt_password_browser

        assert self.enc_pub_key and self.enc_key_id is not None
        self.password = password
        enc = encrypt_password_browser(
            password,
            self.enc_pub_key,
            self.enc_key_id,
            version=str(self.enc_version or "10"),
        )
        self.enc_password = enc
        logger.info("Password encrypted as %s", ":".join(enc.split(":")[:3]) + ":…")
        self.current_step = 3
        self.wbloks(
            ACTION["password"],
            action=True,
            server_params=self._action_server_params(
                current_step=3,
                extra={
                    "spi_action": 0,
                    "flow_modifier": FLOW_INFO,
                },
            ),
            client_input_params=self._lois_cip(
                machine_id="",
                zero_balance_state="",
                encrypted_password=enc,
                safetynet_token="",
                safetynet_response="",
                email_oauth_token_map={},
                whatsapp_installed_on_client=0,
                encrypted_msisdn_for_safetynet="",
                headers_last_infra_flow_id_safetynet="",
                fb_ig_device_id=[],
                caa_play_integrity_attestation_result="",
                client_known_key_hash="",
                has_rejected_rel=0,
                network_bssid=None,
            ),
        )
        self.reg_info["encrypted_password"] = enc
        self.current_step = 4
        self._visit_screen("bloks.caa.reg.birthday")
        self.wbloks(
            APP["birthday"],
            action=False,
            server_params=self._base_server_params(
                current_step=4,
                screen_id="bloks.caa.reg.birthday",
            ),
            client_input_params=self._lois_cip(machine_id=""),
        )

    def submit_birthday(self, day: int, month: int, year: int) -> None:
        bday = f"{day:02d}-{month:02d}-{year}"
        self.current_step = 4
        self.wbloks(
            ACTION["birthday"],
            action=True,
            server_params=self._action_server_params(current_step=4),
            client_input_params=self._lois_cip(
                zero_balance_state="",
                birthday_timestamp=int(time.time()),
                birthday_or_current_date_string=bday,
                should_skip_youth_tos=0,
                is_youth_regulation_flow_complete=0,
                client_timezone=self.timezone,
                os_age_range="",
                accounts_list=[],
                network_bssid=None,
            ),
        )
        self.reg_info["birthday"] = bday
        self.reg_info["age_range"] = "o18" if year <= 2007 else "u18"
        self.reg_info["did_use_age"] = False
        self.current_step = 5
        self._visit_screen("CAA_REG_IG_NAME_SCREEN")
        self.wbloks(
            APP["name"],
            action=False,
            server_params=self._base_server_params(
                current_step=5,
                screen_id="CAA_REG_IG_NAME_SCREEN",
            ),
            client_input_params={},
        )

    def submit_name(self, full_name: str) -> None:
        self.current_step = 5
        self.wbloks(
            ACTION["name"],
            action=True,
            server_params=self._action_server_params(current_step=5),
            client_input_params=self._lois_cip(
                zero_balance_state="",
                name=full_name,
                accounts_list=[],
                network_bssid=None,
            ),
        )
        self.reg_info["full_name"] = full_name
        self.current_step = 6
        self._visit_screen("CAA_REG_IG_USERNAME")
        self.wbloks(
            APP["username"],
            action=False,
            server_params=self._base_server_params(
                current_step=6,
                screen_id="CAA_REG_IG_USERNAME",
                extra={"post_tos": 0},
            ),
            client_input_params=self._lois_cip(machine_id=""),
        )
        if self.reg_info.get("username_prefill"):
            logger.info("Username prefill: %s", self.reg_info["username_prefill"])

    def submit_username(self, username: str) -> None:
        self.current_step = 6
        text = self.wbloks(
            ACTION["username"],
            action=True,
            server_params=self._action_server_params(
                current_step=6,
                extra={
                    "screen_id": "sacxwo:0",
                    "input_id": "sacxwo:12",
                    "suggestions_container_id": "sacxwo:11",
                    "text_input_id": "sacxwo:13",
                    "action": 1,
                    "post_tos": 0,
                },
            ),
            client_input_params=self._lois_cip(
                device_id=self.mid,
                qe_device_id="",
                family_device_id="",
                zero_balance_state="",
                validation_text=username,
                network_bssid=None,
            ),
        )
        err = _bloks_error(text)
        if err and ("not available" in err.lower() or "username" in err.lower()):
            raise MobileBloksSignupError(f"username rejected: {err}")
        self.reg_info["username"] = username
        self.reg_info["username_prefill"] = (
            self.reg_info.get("username_prefill") or username
        )
        self.current_step = 7
        self._visit_screen("CAA_REG_TERMS_OF_SERVICE")
        tos_text = self.wbloks(
            APP["tos"],
            action=False,
            server_params=self._base_server_params(
                current_step=7,
                screen_id="CAA_REG_TERMS_OF_SERVICE",
                extra={"tos_type": "standard"},
            ),
            client_input_params=self._lois_cip(machine_id=""),
        )
        # TOS app embeds create.account.async — absorb any fresher reg_info.
        _absorb_reg_info_fields(self.reg_info, tos_text)

    def _ensure_machine_id(self) -> None:
        """
        machine_id must be in reg_info before create (HAR tos / create payloads).

        Re-scan the latest Bloks body, then re-open the confirmation screen —
        that is where the HAR first echoes the token back, so a fresh fetch is
        the one cheap chance to recover it before we burn a verified email.
        """
        if self.reg_info.get("machine_id"):
            return
        mid_m = _extract_machine_id(self.last_text or "")
        if mid_m:
            self.reg_info["machine_id"] = mid_m
            logger.info("Bloks machine_id recovered from last response (%s…)", mid_m[:8])
            return

        logger.warning("machine_id absent after full flow; re-opening confirmation screen")
        try:
            self.wbloks(
                APP["confirmation"],
                action=False,
                server_params=self._base_server_params(
                    current_step=2,
                    screen_id="CAA_REG_CONFIRMATION_SCREEN",
                    extra={"confirmed_cp_and_code": {}},
                ),
                client_input_params=self._lois_cip(
                    machine_id="",
                    gms_incoming_call_retriever_eligibility="client_not_supported",
                ),
            )
        except MobileBloksSignupError as exc:
            logger.warning("machine_id recovery fetch failed: %s", exc)
        finally:
            self.current_step = 7
        if self.reg_info.get("machine_id"):
            logger.info(
                "Bloks machine_id recovered on retry (%s…)",
                str(self.reg_info["machine_id"])[:8],
            )
            return

        if not SYNTH_MACHINE_ID:
            return
        synthetic = _synthesize_machine_id()
        self.reg_info["machine_id"] = synthetic
        logger.info(
            "Bloks machine_id minted late (%s…)",
            synthetic[:8],
        )

    def _create_server_params(self) -> Dict[str, Any]:
        """Exact create.account.async server_params keys from the mobile HAR TOS app."""
        return {
            "event_request_id": str(uuid.uuid4()),
            "should_ignore_suma_check": False,
            "app_id": 0,
            "bloks_controller_source": "bk_caa_reg_tos_screen",
            "sa_prefetch_callback_id": "",
            "reg_info": self.reg_info,
            "flow_info": FLOW_INFO,
            "current_step": 7,
            "INTERNAL__latency_qpl_marker_id": 36707139,
            "INTERNAL__latency_qpl_instance_id": int(
                f"{int(time.time() * 1000)}{random.randint(10, 99):02d}"
            ),
            "device_id": self.mid,
            "family_device_id": None,
            # Must match every earlier step: create is the only request that
            # ties the whole waterfall together for integrity scoring.
            "waterfall_id": self.waterfall_id,
            "offline_experiment_group": None,
            "layered_homepage_experiment_group": None,
            "is_platform_login": False,
            "is_from_logged_in_switcher": False,
            "is_from_logged_out": False,
            "access_flow_version": "pre_mt_behavior",
            "login_surface": "unknown",
        }

    def _create_client_input_params(self) -> Dict[str, Any]:
        """Exact create.account.async CIP keys from the mobile HAR TOS app."""
        return {
            "device_id": self.mid,
            "waterfall_id": self.waterfall_id,
            "machine_id": self.reg_info.get("machine_id") or "",
            "zero_balance_state": "",
            "ck_error": self.reg_info.get("ck_error"),
            "ck_id": self.reg_info.get("ck_id"),
            "ck_nonce": self.reg_info.get("ck_nonce"),
            "has_dismissed_suma_pre_conf": False,
            "should_ignore_existing_login": False,
            "encrypted_msisdn": "",
            "headers_last_infra_flow_id": "",
            "reached_from_tos_screen": True,
            "no_contact_perm_email_oauth_token": "",
            "failed_birthday_year_count": 0,
            "ig_partially_created_account_user_id": self.reg_info.get(
                "ig_partially_created_account_user_id"
            ),
            "ig_partially_created_account_nonce": self.reg_info.get(
                "ig_partially_created_account_nonce"
            )
            or "",
            "ig_partially_created_account_nonce_expiry": self.reg_info.get(
                "ig_partially_created_account_nonce_expiry"
            )
            or 0,
            "force_sessionless_nux_experience": bool(
                self.reg_info.get("force_sessionless_nux_experience") or False
            ),
            "passkey_eligible_device": False,
            "cloud_trust_token": None,
            "network_bssid": None,
            "lois_settings": {"lois_token": ""},
            "aac": "",
        }

    def _send_login_after_create(self) -> str:
        """
        HAR TOS on_success → com.bloks.www.bloks.caa.login.async.send_login_request
        (this is what typically sets sessionid / ds_user_id).
        """
        enc = self.enc_password or self.reg_info.get("encrypted_password") or ""
        email = self.reg_info.get("contactpoint") or ""
        if not enc or not email:
            return ""
        server_params = {
            "disable_error_modals": True,
            "credential_type": "password",
            "login_source": "Login",
            "login_credential_type": "none",
            "server_login_source": "login",
            "ar_event_source": "login_home_page",
            "reg_flow_source": "login_home_native_integration_point",
            "caller": "gslr",
            "is_from_landing_page": False,
            "should_show_nested_nta_from_aymh": False,
            "is_from_empty_password": False,
            "is_from_aymh": False,
            "is_from_password_entry_page": False,
            "is_from_assistive_id": False,
            "two_step_login_type": "one_step_login",
            "INTERNAL__latency_qpl_marker_id": 36707139,
            "INTERNAL__latency_qpl_instance_id": int(
                f"{int(time.time() * 1000)}{random.randint(10, 99):02d}"
            ),
            "device_id": self.mid,
            "family_device_id": None,
            "waterfall_id": self.waterfall_id,
            "offline_experiment_group": None,
            "layered_homepage_experiment_group": None,
            "is_platform_login": False,
            "is_from_logged_in_switcher": False,
            "is_from_logged_out": False,
            "access_flow_version": "pre_mt_behavior",
            "login_surface": "unknown",
        }
        client_input_params = {
            "next_uri": "/",
            "cloud_trust_token": None,
            "block_store_machine_id": "",
            "contact_point": email,
            "password": enc,
            "login_attempt_count": 1,
            "has_granted_read_contacts_permissions": False,
            "has_granted_read_phone_permissions": False,
            "network_bssid": None,
            "lois_settings": {"lois_token": ""},
            "aac": "",
        }
        return self.wbloks(
            ACTION["send_login"],
            action=True,
            server_params=server_params,
            client_input_params=client_input_params,
        )

    def _cookies_from_text_or_jar(self, text: str = "") -> Dict[str, str]:
        cookies = self._session_cookies()
        if cookies.get("sessionid") and cookies.get("ds_user_id"):
            return cookies
        if text:
            body_sid = _find_escaped_string_field(text, "sessionid") or _find(
                r'"sessionid"\s*:\s*"([^"]+)"', text
            )
            body_uid = (
                _find_escaped_string_field(text, "ds_user_id")
                or _find(r'"ds_user_id"\s*:\s*"?(\d+)"?', text)
                or _find(r'"user_id"\s*:\s*"?(\d+)"?', text)
            )
            if body_sid and body_uid:
                try:
                    self.session.cookies.set(
                        "sessionid", body_sid, domain=".instagram.com"
                    )
                    self.session.cookies.set(
                        "ds_user_id", str(body_uid), domain=".instagram.com"
                    )
                except Exception:
                    pass
                cookies = self._session_cookies()
        return cookies

    def accept_tos_create(self) -> Dict[str, str]:
        """
        Final create step from ``Stream-2026-07-24 220559.har`` TOS app:

        1) create.account.async (button action)
        2) send_login_request (on_success — sets session cookies)
        """
        self.current_step = 7
        self._ensure_machine_id()
        required = (
            "contactpoint",
            "confirmation_code",
            "encrypted_password",
            "birthday",
            "full_name",
            "username",
            "machine_id",
        )
        missing = [k for k in required if not self.reg_info.get(k)]
        if missing:
            raise MobileBloksSignupError(
                f"Cannot create account; reg_info missing {missing} "
                f"(see {MOBILE_HAR_FILE.name} contactpoint_email.async / tos)"
            )

        self.reg_info["should_show_error_msg"] = False
        # Keep encrypted_password on reg_info (HAR create payload includes it).
        if self.enc_password:
            self.reg_info["encrypted_password"] = self.enc_password

        appid = ACTION["create_account"]
        text = self.wbloks(
            appid,
            action=True,
            server_params=self._create_server_params(),
            client_input_params=self._create_client_input_params(),
        )

        # Persist create body for debugging empty/soft failures.
        try:
            dump = Path(__file__).resolve().parent / "_last_create_bloks.txt"
            dump.write_text(text, encoding="utf-8")
        except Exception:
            pass

        create_fail = _parse_create_failure(text)
        emptyish = (
            len(text) < 12000
            and '"data":[]' in text.replace(" ", "")
            and "sessionid" not in text
        )
        if create_fail:
            logger.warning(
                "create.account.async denied: %s (%d bytes)",
                create_fail,
                len(text),
            )
        elif emptyish:
            logger.warning(
                "create.account.async returned empty Bloks payload (%d bytes) — "
                "check for integrity_block in _last_create_bloks.txt "
                "(or #PWD_BROWSER mismatch)",
                len(text),
            )

        # Hard deny from Meta — don't bother send_login / homepage warm.
        if create_fail and "integrity_block" in create_fail.lower():
            self.stats["error_category"] = "blocked"
            raise MobileBloksSignupError(
                f"Could not finalize create.account.async ({create_fail}) — "
                f"Instagram integrity_block on this IP/email/fingerprint. "
                f"Retry with a new sticky session."
            )

        cookies = self._cookies_from_text_or_jar(text)
        if cookies.get("sessionid") and cookies.get("ds_user_id"):
            logger.info("Account create OK via %s", appid)
            # Always warm / — catches immediate suspend before we call it a mint.
            self._warm_homepage()
            return self._session_cookies() or cookies

        # HAR: create success triggers send_login_request for session cookies.
        try:
            login_text = self._send_login_after_create()
            cookies = self._cookies_from_text_or_jar(login_text)
            if cookies.get("sessionid") and cookies.get("ds_user_id"):
                logger.info("Account create OK via send_login_request after create")
                self._warm_homepage()
                return self._session_cookies() or cookies
        except MobileBloksSignupError as e:
            logger.warning("send_login_request after create failed: %s", e)

        warm = self._warm_homepage()
        if warm.get("sessionid") and warm.get("ds_user_id"):
            logger.info("Account create OK (homepage) via %s", appid)
            return warm

        err = (
            create_fail
            or _bloks_error(text)
            or _bloks_error(self.last_text or "")
        )
        if emptyish and not err:
            err = (
                f"empty create payload ({len(text)} bytes; "
                f"pwd={':'.join((self.enc_password or '').split(':')[:3])})"
            )
        err = err or "no session cookies after create+login"
        if "integrity_block" in (err or "").lower() or "create_failure" in (err or "").lower():
            self.stats["error_category"] = "blocked"
        preview = text[:400].replace("\n", " ")
        raise MobileBloksSignupError(
            f"Could not finalize create.account.async ({err[:220]}; "
            f"preview={preview!r})"
        )

    def _session_cookies(self) -> Dict[str, str]:
        jar = self.session.cookies
        out = {
            "sessionid": jar.get("sessionid") or "",
            "csrftoken": jar.get("csrftoken") or self.csrf_token or "",
            "ds_user_id": jar.get("ds_user_id") or "",
            "ig_did": jar.get("ig_did") or self.ig_did or "",
            "rur": jar.get("rur") or "",
            "mid": jar.get("mid") or self.mid or "",
            "datr": jar.get("datr") or self.datr or "",
        }
        return out

    def _warm_homepage(self) -> Dict[str, str]:
        try:
            resp = self.session.get(
                "https://www.instagram.com/",
                headers={
                    **self._nav_headers(),
                    "sec-fetch-site": "same-origin",
                    "referer": self.SIGNUP_URL,
                },
                proxies=self.proxies,
                timeout=40,
                allow_redirects=True,
            )
            final = str(getattr(resp, "url", "") or "")
            if "suspended" in final.lower() or "checkpoint" in final.lower():
                self.stats["post_login"] = "suspended"
                logger.error(
                    "Post-create home redirected to checkpoint/suspend: %s",
                    final[:120],
                )
            else:
                self.stats["post_login"] = "ok"
        except Exception as e:
            logger.error("homepage warm failed: %s", e)
            self.stats["post_login"] = f"error:{e}"
        return self._session_cookies()

    @staticmethod
    def _make_password(first_name: str) -> str:
        sym = random.choice("!@#$%")
        num = str(random.randint(1000, 99999))
        return f"{first_name[:6].capitalize()}{sym}{num}aA"

    @staticmethod
    def _make_username(first_name: str, avoid: Optional[set] = None) -> str:
        avoid = avoid or set()
        for _ in range(40):
            mid = "".join(random.choices(string.ascii_lowercase, k=random.randint(2, 4)))
            num = str(random.randint(10, 99999))
            u = f"{first_name.lower()[:8]}{mid}{num}"
            if u.lower() not in avoid and 6 <= len(u) <= 28:
                return u
        return f"user{uuid.uuid4().hex[:10]}"

    def print_stats(self) -> None:
        s = self.stats
        print()
        print("=" * 60)
        print("  MOBILE BLOKS SIGNUP STATS")
        print("=" * 60)
        print(f"  Egress IP : {s.get('egress_ip') or 'n/a'}")
        geo = s.get("egress_geo") or {}
        if geo.get("country") or geo.get("org"):
            print(
                f"  Egress geo: {geo.get('country') or '?'} / "
                f"{geo.get('city') or '?'} / {(geo.get('org') or '?')[:50]}"
            )
        print(f"  Email     : {s.get('email') or 'n/a'}")
        print(f"  Username  : {s.get('username') or 'n/a'}")
        print("-" * 60)
        for st in s.get("stages") or []:
            mark = "OK" if st.get("ok") else "FAIL"
            print(
                f"  {st.get('name', '?'):<22}{mark:<8}"
                f"{st.get('seconds', 0):<7}{str(st.get('detail') or '')[:50]}"
            )
        print("-" * 60)
        if s.get("failed_stage"):
            print(f"  FAILED AT : {s['failed_stage']} [{s.get('error_category')}]")
            if s.get("error_hint"):
                print(f"  WHY       : {s['error_hint']}")
        print("=" * 60)

    def run(
        self, email: Optional[str] = None, order_attempt: int = 0
    ) -> Optional[Dict[str, str]]:
        """
        Full mobile Bloks signup. Returns credential dict for Acc_Gen to wrap
        as AccountCredentials, or None on failure.
        """
        order_id = None
        try:
            self._resolve_egress()
            self.stats["current_stage"] = "load_tokens"
            t0 = time.time()
            self.bootstrap()
            self._record("load_tokens", True, f"bkv={self.bkv[:12]}…", time.time() - t0)
            self._human_pause(0.5, 1.2)

            self.stats["current_stage"] = "order_email"
            if not email:
                if not self.email_client:
                    raise MobileBloksSignupError("No email and no email client")
                t0 = time.time()
                order_id, email = self.email_client.create_order(
                    site="instagram.com", attempt=order_attempt
                )
                self._record("order_email", True, email, time.time() - t0)
            self.stats["email"] = email

            first_name = names.get_first_name()
            password = self._make_password(first_name)
            day = random.randint(1, 28)
            month = random.randint(1, 12)
            year = random.randint(1991, 2003)

            self.stats["current_stage"] = "submit_email"
            t0 = time.time()
            self.open_contactpoint_email()
            self._human_pause(0.4, 1.0)
            self.submit_email(email)
            self._record("submit_email", True, email, time.time() - t0)

            self.stats["current_stage"] = "verification_code"
            t0 = time.time()
            if self.email_client and order_id:
                code = self.email_client.wait_for_code(order_id)
                if not code:
                    raise MobileBloksSignupError("No verification code received")
            else:
                from .util import prompt_input

                code = prompt_input("Enter the verification code sent to your email: ")
                if not code:
                    raise MobileBloksSignupError("No verification code entered")
            self._record("verification_code", True, f"code={code}", time.time() - t0)
            self._human_pause(0.5, 1.2)

            self.stats["current_stage"] = "submit_code"
            t0 = time.time()
            self.submit_code(code)
            self._record("submit_code", True, "ok", time.time() - t0)
            self._human_pause(0.5, 1.2)

            self.stats["current_stage"] = "submit_password"
            t0 = time.time()
            self.submit_password(password)
            self._record("submit_password", True, "ok", time.time() - t0)
            self._human_pause(0.4, 1.0)

            self.stats["current_stage"] = "submit_birthday"
            t0 = time.time()
            self.submit_birthday(day, month, year)
            self._record("submit_birthday", True, f"{day}-{month}-{year}", time.time() - t0)
            self._human_pause(0.4, 1.0)

            self.stats["current_stage"] = "submit_name"
            t0 = time.time()
            self.submit_name(first_name)
            self._record("submit_name", True, first_name, time.time() - t0)
            self._human_pause(0.4, 1.0)

            # Username: prefer server prefill, else generate.
            self.stats["current_stage"] = "submit_username"
            t0 = time.time()
            tried: set = set()
            username = ""
            cookies: Dict[str, str] = {}
            for try_i in range(1, 8):
                cand = (self.reg_info.get("username_prefill") or "").strip()
                if not cand or cand.lower() in tried:
                    cand = self._make_username(first_name, avoid=tried)
                tried.add(cand.lower())
                self.stats["username"] = cand
                try:
                    self.submit_username(cand)
                    username = cand
                    break
                except MobileBloksSignupError as e:
                    if "username" in str(e).lower() and try_i < 7:
                        logger.warning("username try failed: %s", e)
                        self.reg_info["username_prefill"] = None
                        continue
                    raise
            if not username:
                raise MobileBloksSignupError("Could not pick a username")
            self._record("submit_username", True, username, time.time() - t0)
            self._human_pause(0.5, 1.2)

            self.stats["current_stage"] = "accept_tos_create"
            t0 = time.time()
            cookies = self.accept_tos_create()
            self._record("accept_tos_create", True, "session ok", time.time() - t0)

            return {
                "username": username,
                "password": password,
                "email": email,
                "session_id": cookies.get("sessionid") or "",
                "csrf_token": cookies.get("csrftoken") or "",
                "ds_user_id": cookies.get("ds_user_id") or "",
                "ig_did": cookies.get("ig_did") or "",
                "rur": cookies.get("rur") or "",
                "mid": cookies.get("mid") or "",
                "datr": cookies.get("datr") or "",
            }
        except Exception as e:
            from .util import classify_error

            cat, hint = classify_error(e)
            self.stats["failed_stage"] = self.stats.get("current_stage")
            self.stats["error_category"] = cat
            self.stats["error_hint"] = hint
            self._record(str(self.stats.get("current_stage") or "run"), False, str(e)[:120])
            logger.error("Mobile Bloks signup failed at %s: %s", self.stats.get("current_stage"), e)
            return None
        finally:
            # Always try cancel so Kopechka pending slots free when possible.
            if order_id and self.email_client:
                try:
                    self.email_client.cancel_order(order_id)
                except Exception:
                    try:
                        self.email_client.release_order_slot()
                    except Exception:
                        pass
