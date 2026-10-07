"""
Voice ordering: record speech -> transcribe -> extract "product + quantity"
-> match against the real product catalog -> add to cart.

Two paid AI calls are involved, both optional and both gracefully
degraded if not configured (the rest of the app works fine either way):

1. Speech-to-text: OpenAI's Whisper API (`OPENAI_API_KEY`). There's no
   free tier for this one - https://platform.openai.com/api-keys, then
   `pip install openai`.

2. Text -> structured items: Google's Gemini API (`GEMINI_API_KEY`).
   Gemini has a genuinely free tier (no credit card needed) - grab a key
   at https://aistudio.google.com/apikey, then
   `pip install google-generativeai`.
   Without a Gemini key, a much dumber regex-based extractor is used
   instead (handles "2 cheese burgers" style single-item phrases fine;
   multi-item sentences need the real AI step).

Both imports are deferred into the functions below so that the rest of
the app runs fine even if these optional packages were never
installed.
"""

import os
import re
import json
import difflib


def voice_ordering_enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def gemini_enabled() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def transcribe_audio(file_bytes: bytes, filename: str = "voice.webm") -> str:
    """Returns the transcript, or raises RuntimeError with a friendly
    message if Whisper isn't configured/available."""
    if not voice_ordering_enabled():
        raise RuntimeError(
            "Voice ordering needs an OpenAI API key. Add OPENAI_API_KEY to your "
            ".env file - see README for setup steps."
        )
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("Run 'pip install openai' to enable voice ordering.")

    import io
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    audio_file = io.BytesIO(file_bytes)
    audio_file.name = filename  # the SDK reads this to infer the format
    result = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
    return result.text.strip()


_QTY_WORD_RE = re.compile(r"\b(\d+)\b")


def _naive_extract(text: str):
    """Fallback used when Gemini isn't configured: treats the whole
    utterance as a request for ONE product, with an optional leading
    quantity number. Good enough for "2 cheese burgers"; sentences with
    multiple different items need the real Gemini step below."""
    m = _QTY_WORD_RE.search(text)
    qty = int(m.group(1)) if m else 1
    name_part = _QTY_WORD_RE.sub("", text, count=1).strip() if m else text.strip()
    name_part = re.sub(r"^(x|pcs?|pieces?|of)\b", "", name_part, flags=re.IGNORECASE).strip()
    return [{"query": name_part or text, "qty": max(1, qty)}]


def extract_order_items(text: str):
    """Returns a list of {"query": str, "qty": int} dicts describing what
    the customer asked for. Uses Gemini if configured, else falls back
    to `_naive_extract`."""
    if not gemini_enabled():
        return _naive_extract(text)

    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = (
            "Extract the products and quantities the customer wants to order from this "
            "sentence. Reply with ONLY a JSON array like "
            '[{"item_name": "cheese burger", "quantity": 2}] - no other text.\n\n'
            f"Sentence: {text!r}"
        )
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(response_mime_type="application/json"),
        )
        parsed = json.loads(response.text)
        items = [
            {"query": str(item.get("item_name", "")).strip(), "qty": max(1, int(item.get("quantity", 1)))}
            for item in parsed
            if item.get("item_name")
        ]
        return items or _naive_extract(text)
    except Exception as e:
        print(f"[SHADOW Voice AI] Gemini extraction failed, using fallback: {e}")
        return _naive_extract(text)


def match_products(items, candidate_products, cutoff: float = 0.45):
    """items: [{"query": str, "qty": int}], candidate_products: [Product].
    Returns [{"product": Product, "qty": int}] for each item that found a
    reasonable match, plus a separate list of queries with no match."""
    matched, unmatched = [], []
    for item in items:
        query = item["query"].lower()
        best_product, best_score = None, 0.0
        for product in candidate_products:
            score = difflib.SequenceMatcher(None, query, product.name.lower()).ratio()
            # Give a boost when the query is a clean substring of the name
            # (or vice versa) - handles "burger" matching "Cheese Burger Combo".
            if query in product.name.lower() or product.name.lower() in query:
                score = max(score, 0.7)
            if score > best_score:
                best_product, best_score = product, score
        if best_product and best_score >= cutoff:
            matched.append({"product": best_product, "qty": item["qty"]})
        else:
            unmatched.append(item["query"])
    return matched, unmatched
