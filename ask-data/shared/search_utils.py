"""
Module: shared/search_utils
===========================
Enterprise-grade scoring, normalization, and lexical matching utilities
for Text-to-SQL RAG pipelines. Includes temporal scrubbing to separate
retrieval intents from SQL filter entities.
"""

import os
import math
import re
from typing import Set, List, Tuple, Optional

# --- ENTERPRISE WEIGHT CONFIGURATION (Convex Combination: sum = 1.0) ---
DEFAULT_WEIGHT_LEXICAL = 0.50
DEFAULT_WEIGHT_RERANK = 0.35
DEFAULT_WEIGHT_VECTOR = 0.15

# --- INDONESIAN DOMAIN & TEMPORAL STOP WORDS ---
INDONESIAN_STOP_WORDS: Set[str] = {
    # Spoken Commands & Politeness
    "tampilkan", "tolong", "berikan", "cari", "carikan", "sebutkan", "sertakan",
    "daftar", "daftarkan", "lihat", "lihatlah", "dapatkan", "keluarkan", "tunjukkan",
    "sajikan", "bantu", "mohon", "minta", "proses", "infokan", "informasikan",
    
    # Question Interrogatives
    "apa", "apakah", "mana", "manakah", "dimana", "dimanakah", "kemana", "siapa",
    "siapakah", "kapan", "kapankah", "kenapa", "mengapa", "berapa", "berapakah",
    "bagaimana", "bagaimanakah",
    
    # Prepositions & Locatives
    "di", "ke", "dari", "pada", "untuk", "bagi", "guna", "demi", "dengan", "secara",
    "oleh", "tentang", "terhadap", "dalam", "atas", "bawah", "antara", "kepada",
    "daripada", "melalui", "lewat", "hingga", "sampai", "sejak", "seputar",
    
    # Conjunctions & Connectives
    "yang", "atau", "dan", "serta", "bahwa", "karena", "sebab", "sehingga", "maka",
    "jika", "kalau", "apabila", "bila", "meskipun", "walaupun", "tetapi", "namun",
    "melainkan", "sedangkan", "lalu", "kemudian", "yakni", "yaitu", "adalah", "ialah",
    
    # Pronouns & Auxiliaries
    "ini", "itu", "tersebut", "berikut", "demikian", "nya", "saya", "kami", "kita",
    "anda", "dia", "ia", "mereka", "ada", "adanya", "tidak", "tak", "bukan", "belum",
    "sudah", "telah", "sedang", "akan", "dapat", "bisa", "harus", "mesti", "perlu",
    "saja", "hanya", "cuma", "paling", "sangat", "amat",
    
    # TEMPORAL & CALENDAR SCRUBBING
    # Prevents Query Token Dilution by dropping dates from schema matching logic
    "januari", "februari", "maret", "april", "mei", "juni", "juli", "agustus", 
    "september", "oktober", "november", "desember", "jan", "feb", "mar", "apr",
    "aug", "sep", "oct", "nov", "dec", "hari", "bulan", "tahun", "tanggal", "tgl"
}

def sigmoid(x: float) -> float:
    """
    Scales raw Cross-Encoder logit scores (-inf, +inf) into a bounded [0.0, 1.0] probability.
    """
    try:
        if x > 30.0:
            return 1.0
        if x < -30.0:
            return 0.0
        return 1.0 / (1.0 + math.exp(-x))
    except (OverflowError, ValueError):
        return 0.0 if x < 0 else 1.0

def normalize_text(text: Optional[str]) -> str:
    """
    Cleans special characters, punctuation, and standardizes text to lowercase.
    """
    if not text or not isinstance(text, str):
        return ""
    clean = text.lower()
    clean = re.sub(r"[?!.,:;/\\_\-\(\)\[\]{}|'\"`]", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()

def extract_tokens_and_phrases(text: Optional[str]) -> Tuple[Set[str], List[str]]:
    """
    Extracts filtered meaningful tokens and contiguous 2-word natural phrases (bigrams).
    Strips purely numeric strings to preserve overlap ratios.
    """
    clean_text = normalize_text(text)
    if not clean_text:
        return set(), []

    # Filter out short words, stop words, and pure numbers (e.g. "2026")
    words = [
        w for w in clean_text.split() 
        if len(w) > 2 
        and not w.isnumeric() 
        and w not in INDONESIAN_STOP_WORDS
    ]
    
    tokens = set(words)
    phrases = [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]

    return tokens, phrases

def compute_lexical_score(description: Optional[str], user_query: str) -> float:
    """
    Calculates a continuous lexical match score S_lex in range [0.0, 1.0].
    Rewards multiple phrase matches (0.40 each) and token overlaps (up to 0.60).
    """
    if not description or not user_query:
        return 0.0

    query_tokens, query_phrases = extract_tokens_and_phrases(user_query)
    desc_tokens, _ = extract_tokens_and_phrases(description)

    if not query_tokens:
        return 0.0

    clean_desc = normalize_text(description)

    # 1. Additive Phrase Scoring (Reward density of multi-word matches)
    phrase_matches = sum(1 for phrase in query_phrases if phrase in clean_desc)

    # 2. Token Overlap Ratio
    token_overlap = len(query_tokens.intersection(desc_tokens))
    overlap_ratio = token_overlap / len(query_tokens) if query_tokens else 0.0

    # 3. Additive Fusion: Phrases dominate, tokens provide baseline
    raw_lex_score = (phrase_matches * 0.40) + (overlap_ratio * 0.60)

    # Cap strictly at 1.00
    return min(round(raw_lex_score, 4), 1.00)

def calculate_unified_score(
    raw_vector_score: float,
    raw_rerank_score: float,
    description: Optional[str],
    user_query: str,
    w_lex: Optional[float] = None,
    w_rerank: Optional[float] = None,
    w_vec: Optional[float] = None
) -> float:
    """
    Computes a strictly bounded [0.0, 1.0] enterprise score using weighted linear fusion.
    S_final = (w_lex * S_lex) + (w_rerank * S_rerank) + (w_vec * S_vec)
    """
    w_lex = w_lex if w_lex is not None else float(os.getenv("RAG_WEIGHT_LEXICAL", DEFAULT_WEIGHT_LEXICAL))
    w_rerank = w_rerank if w_rerank is not None else float(os.getenv("RAG_WEIGHT_RERANK", DEFAULT_WEIGHT_RERANK))
    w_vec = w_vec if w_vec is not None else float(os.getenv("RAG_WEIGHT_VECTOR", DEFAULT_WEIGHT_VECTOR))

    total_w = w_lex + w_rerank + w_vec
    if total_w <= 0 or not math.isclose(total_w, 1.0):
        w_lex, w_rerank, w_vec = w_lex / total_w, w_rerank / total_w, w_vec / total_w

    s_vec = max(0.0, min(float(raw_vector_score or 0.0), 1.0))
    
    r_val = float(raw_rerank_score or 0.0)
    s_rerank = r_val if 0.0 <= r_val <= 1.0 else sigmoid(r_val)
    
    s_lex = compute_lexical_score(description, user_query)

    final_score = (w_lex * s_lex) + (w_rerank * s_rerank) + (w_vec * s_vec)

    return round(max(0.0, min(final_score, 1.0)), 4)