"""analyzer.py - the GEMMA part of BillSaathi.

Two jobs only:
  1. extract_bill()  : bill photo -> JSON of numbers (Gemma READS, never calculates)
  2. explain_bill()  : numbers + check results -> explanation in a language

Gemma is called through the Gemini API (google-genai). Set MOCK_MODEL=1 in .env
to run the whole app without a key or internet (backup for demo day).
"""
import io
import json
import os
import re
import time

from dotenv import load_dotenv
from PIL import Image, ImageOps

load_dotenv()

MODELS = {
    "Gemma 4 31B (best reading)": "gemma-4-31b-it",
    "Gemma 4 26B (faster)": "gemma-4-26b-a4b-it",
}
LANGUAGES = {"English": "English", "Roman Urdu": "Roman Urdu", "اردو": "Urdu"}
MAX_IMAGE_SIDE = 2000
MAX_UPLOAD_MB = 10


class BillSaathiError(Exception):
    """An error with a message that is safe to show the user."""


def mock_enabled():
    return os.getenv("MOCK_MODEL", "").strip() == "1"


# ---------------------------------------------------------------- prompts
EXTRACT_PROMPT = """You read a photo of a Pakistani electricity bill (FESCO, LESCO, IESCO, MEPCO, K-Electric etc).
Return ONE JSON object and nothing else (no markdown, no commentary).

RULES
- COPY numbers exactly as printed. NEVER calculate, guess or fix a number.
- If a value is not visible or not readable, use null and add the field name to "unreadable".
- Do NOT read or return: name, address, phone, CNIC, reference number, meter number.
- Amounts have no decimals unless printed. Ignore commas in numbers.
- If the image is NOT an electricity bill, return {"is_electricity_bill": false}.

LAYOUT HINTS
- "Previous reading" is the older, smaller number. "Present reading" is the newer one.
- "Units" / "Units consumed" is the billed number of units.
- The history table lists earlier months with the units used in each.

JSON SHAPE
{
  "is_electricity_bill": true,
  "company": "FESCO",
  "billing_month": "OCT 25",
  "due_date": "15 NOV 25",
  "tariff_category": "A-1a",
  "protected_status": "protected" | "non-protected" | null,
  "previous_reading": 10250,
  "present_reading": 10662,
  "units_consumed": 412,
  "billing_days": 33,
  "export_units": null,
  "total_payable": 18500,
  "payable_after_due": 19400,
  "arrears": 0,
  "unit_history": [{"month": "SEP 25", "units": 230}],
  "unreadable": []
}"""

STRICTER_SUFFIX = "\n\nYour last reply was not valid JSON. Reply with ONE valid JSON object only."

EXPLAIN_PROMPT = """You help an ordinary Pakistani household understand its electricity bill.
Write in {language}. Use short, simple sentences.

BILL FACTS (already read from the photo):
{facts}

CHECKS DONE BY CODE (use these exact numbers):
{checks}

RULES
- NEVER say the bill is wrong or that the user was overcharged. Say what is "worth verifying" and why.
- Use only the numbers given above. Do not invent or calculate new numbers.
- Do not mention names, addresses, CNIC or reference numbers.
- The draft request must be polite, ask the sub-division office to REVIEW the points, and not accuse anyone.
  Keep placeholders like [Name], [Reference No.] for the user to fill in.

Return ONE JSON object only:
{{
  "summary": "2-3 sentences: why this amount",
  "what_to_check": ["point 1", "point 2"],
  "next_steps": ["step 1", "step 2"],
  "draft_request": "a short polite letter to the sub-division office"
}}"""


# ---------------------------------------------------------------- helpers
def prepare_image(raw_bytes):
    """Fix phone rotation, shrink to MAX_IMAGE_SIDE, re-encode as JPEG. Nothing is saved to disk."""
    if len(raw_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
        raise BillSaathiError(f"Photo is bigger than {MAX_UPLOAD_MB} MB. Please send a smaller one.")
    try:
        image = Image.open(io.BytesIO(raw_bytes))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception:
        raise BillSaathiError("This file could not be opened as an image.")
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


def parse_json_object(text):
    """Pull a JSON object out of a reply, even if wrapped in ``` fences or extra words."""
    if not text:
        raise ValueError("empty reply")
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found")
    return json.loads(text[start:end + 1])


def _friendly_api_error(exc):
    msg = str(exc)
    low = msg.lower()
    if "429" in msg or "quota" in low or "rate" in low:
        return "Rate limit reached (free tier). Wait a minute and try again, or open the result from the sidebar."
    if "401" in msg or "403" in msg or "api key" in low or "permission" in low:
        return "The API key was rejected. Check GEMINI_API_KEY in your .env file."
    if "404" in msg or "not found" in low:
        return "Model name not found for your key. Check the model list in Google AI Studio and update MODELS in analyzer.py."
    if "400" in msg:
        return f"The API rejected the request: {msg[:200]}"
    return f"Could not reach the Gemini API: {msg[:200]}"


def _call_gemma(model, contents, temperature):
    if not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
        raise BillSaathiError("No API key. Put GEMINI_API_KEY=your_key in the .env file (or set MOCK_MODEL=1).")
    from google import genai
    from google.genai import types
    client = genai.Client()  # picks up GEMINI_API_KEY from the environment
    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(temperature=temperature),
        )
    except Exception as exc:
        raise BillSaathiError(_friendly_api_error(exc))
    if not response.text:
        raise BillSaathiError("The model returned an empty reply. Please try again.")
    return response.text


# ---------------------------------------------------------------- main API
def extract_bill(model, image_bytes):
    """Photo -> raw dict (not yet cleaned; checks.normalize_extraction cleans it)."""
    if mock_enabled():
        time.sleep(0.5)
        return dict(MOCK_EXTRACTION)
    from google.genai import types
    image_part = types.Part.from_bytes(data=prepare_image(image_bytes), mime_type="image/jpeg")
    prompt = EXTRACT_PROMPT
    for attempt in range(2):  # one retry if the JSON is broken
        text = _call_gemma(model, [image_part, prompt], temperature=0.1)
        try:
            return parse_json_object(text)
        except ValueError:
            prompt = EXTRACT_PROMPT + STRICTER_SUFFIX
    raise BillSaathiError("The model's answer could not be read as data. Try a clearer photo.")


def _facts_text(data):
    skip = {"is_electricity_bill"}
    return "\n".join(f"- {k}: {v}" for k, v in data.items() if k not in skip and v not in (None, [], ""))


def _checks_text(checks):
    return "\n".join(f"- [{c['severity'].upper()}] {c['title']}: {c['detail']}" for c in checks)


def explain_bill(model, data, checks, language):
    """Numbers + checks -> dict(summary, what_to_check, next_steps, draft_request)."""
    if mock_enabled():
        time.sleep(0.5)
        return MOCK_EXPLANATIONS.get(language, MOCK_EXPLANATIONS["English"])
    prompt = EXPLAIN_PROMPT.format(language=LANGUAGES.get(language, language),
                                   facts=_facts_text(data), checks=_checks_text(checks))
    text = _call_gemma(model, [prompt], temperature=0.3)
    try:
        result = parse_json_object(text)
    except ValueError:
        return {"summary": text.strip(), "what_to_check": [], "next_steps": [], "draft_request": ""}
    return {
        "summary": result.get("summary", ""),
        "what_to_check": result.get("what_to_check") or [],
        "next_steps": result.get("next_steps") or [],
        "draft_request": result.get("draft_request", ""),
    }


# ---------------------------------------------------------------- demo mode data
MOCK_EXTRACTION = {
    "is_electricity_bill": True, "company": "FESCO", "billing_month": "OCT 25",
    "due_date": "15 NOV 25", "tariff_category": "A-1a", "protected_status": "non-protected",
    "previous_reading": 10250, "present_reading": 10662, "units_consumed": 412,
    "billing_days": 33, "export_units": None, "total_payable": 18500,
    "payable_after_due": 19400, "arrears": 0,
    "unit_history": [{"month": "SEP 25", "units": 230}, {"month": "AUG 25", "units": 245},
                     {"month": "JUL 25", "units": 260}, {"month": "JUN 25", "units": 210},
                     {"month": "MAY 25", "units": 190}, {"month": "APR 25", "units": 170}],
    "unreadable": [],
}

MOCK_EXPLANATIONS = {
    "English": {
        "summary": "Your bill is Rs 18,500 for 412 units. The cycle was 33 days and the units are well above your usual average.",
        "what_to_check": ["The billing cycle was 33 days, longer than 31.", "412 units is 1.8x your 6-month average."],
        "next_steps": ["Compare the readings on the bill with your meter.", "Ask the office why the cycle was 33 days."],
        "draft_request": "To the SDO,\n\nI request a review of my bill [Reference No.] for OCT 25. The cycle shows 33 days and units are higher than my usual. Please confirm the meter readings and billing days.\n\nThank you,\n[Name]",
    },
    "Roman Urdu": {
        "summary": "Aap ka bill 412 units ka Rs 18,500 hai. Cycle 33 din ka tha aur units aap ke aam average se kaafi zyada hain.",
        "what_to_check": ["Billing cycle 33 din ka hai, jo 31 se lamba hai.", "412 units aap ke 6 mahine ke average se 1.8 guna hain."],
        "next_steps": ["Bill ki readings apne meter se milayein.", "Office se poochein ke cycle 33 din ka kyun tha."],
        "draft_request": "Janab SDO sahib,\n\nMeri guzarish hai ke mere bill [Reference No.] (OCT 25) ka jaiza liya jaye. Cycle 33 din ka hai aur units aam se zyada hain. Meherbani karke readings aur billing days confirm kar dein.\n\nShukriya,\n[Name]",
    },
    "Urdu": {
        "summary": "آپ کا بل 412 یونٹ کا 18,500 روپے ہے۔ بلنگ سائیکل 33 دن کا تھا اور یونٹ آپ کی عام اوسط سے کافی زیادہ ہیں۔",
        "what_to_check": ["بلنگ سائیکل 33 دن کا ہے، جو 31 دن سے لمبا ہے۔", "412 یونٹ آپ کی چھ ماہ کی اوسط سے 1.8 گنا ہیں۔"],
        "next_steps": ["بل کی ریڈنگ اپنے میٹر سے ملائیں۔", "دفتر سے پوچھیں کہ سائیکل 33 دن کا کیوں تھا۔"],
        "draft_request": "جناب ایس ڈی او صاحب،\n\nگزارش ہے کہ میرے بل [ریفرنس نمبر] (اکتوبر 25) کا جائزہ لیا جائے۔ سائیکل 33 دن کا ہے اور یونٹ معمول سے زیادہ ہیں۔ براہِ کرم ریڈنگ اور بلنگ ڈیز کی تصدیق کر دیں۔\n\nشکریہ،\n[نام]",
    },
}