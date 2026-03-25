"""
Guardrails — Multi-layer security module for trio.

Provides code-level filtering for inputs and outputs across all bot platforms.
All checks are regex/keyword/heuristic-based (no external ML dependencies).

Layers:
    2. Output Filtering  — filter_output()
    3. Input Filtering    — filter_input()
    4. Content Safety     — check_content_safety()
    5. Operational        — sanitize_for_logging(), enforce_length_limit()
"""

import re
import time
import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

# ===================================================================
# Data Structures
# ===================================================================

@dataclass
class FilterResult:
    filtered_text: str
    violations: List[Tuple[str, str]] = field(default_factory=list)
    was_modified: bool = False

@dataclass
class InputFilterResult:
    is_safe: bool
    threat_level: str = "none"  # none | low | medium | high
    detected_attacks: List[str] = field(default_factory=list)
    should_warn: bool = False
    warning_message: Optional[str] = None

@dataclass
class SafetyResult:
    is_safe: bool
    violations: List[str] = field(default_factory=list)
    severity: str = "none"  # none | low | medium | high | critical


# ===================================================================
# Constants
# ===================================================================

SAFE_FALLBACK = (
    "I'm sorry, but I can't provide that information. "
    "How can I help you with something else?"
)

INPUT_BLOCKED_MESSAGE = (
    "I can't process that request. If you have a legitimate question, "
    "please rephrase it and I'll be happy to help."
)

CONTENT_BLOCKED_MESSAGE = (
    "I'm not able to help with that kind of request. "
    "Please ask me something constructive and I'll do my best to assist you."
)

MAX_INPUT_LENGTHS = {
    "message": 4000,
    "search_query": 200,
    "command_arg": 500,
}

# Rate limiting: {user_id: {"timestamps": [float], "blocked_until": float}}
_probe_tracker = {}
PROBE_WINDOW = 600       # 10 minutes
PROBE_THRESHOLD = 3       # 3 attempts in window
PROBE_BLOCK_DURATION = 1800  # 30 minutes


# ===================================================================
# Layer 2: Output Filtering
# ===================================================================

# --- Patterns for internal architecture leakage ---

_INTERNAL_MODEL_NAMES = re.compile(
    r'\b(ollama|llama[\s-]?3(\.\d)?|deepseek[\s-]?r1|qwen[\s-]?\d*[\s-]?coder|'
    r'mistral|codellama|phi[\s-]?\d|gemma[\s-]?\d|vicuna|wizardlm)\b',
    re.IGNORECASE
)

_INTERNAL_FRAMEWORKS = re.compile(
    r'\b(discord\.py|pyTelegramBotAPI|telebot|signal[\s-]?cli|'
    r'aiohttp|yt[\s-]?dlp|ollama_handler|context_analyzer|think_parser|'
    r'web_search\.py|guardrails\.py)\b',
    re.IGNORECASE
)

_INTERNAL_API_PATHS = re.compile(
    r'(/api/(generate|chat|tags|embeddings)|stream_generate|stream_chat|'
    r'stream_to_discord|stream_to_telegram|get_mode_config|build_context_prompt)\b',
    re.IGNORECASE
)

_INFRA_URLS = re.compile(
    r'(https?://)?(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?(/\S*)?',
    re.IGNORECASE
)

_FILE_PATHS = re.compile(
    r'([A-Za-z]:\\[^\s"\'<>|]+\.py|/[^\s"\'<>|]+\.py)\b'
)

_ENV_VARS = re.compile(
    r'\b(OLLAMA_[A-Z_]+|DISCORD_BOT_TOKEN|TELEGRAM_BOT_TOKEN|'
    r'SIGNAL_PHONE_NUMBER|SIGNAL_CLI_HOST|SIGNAL_CLI_PORT|'
    r'DEFAULT_MODEL|OLLAMA_BASE_URL)\b'
)

_DOTENV_REF = re.compile(r'\b\.env\b')

# --- PII patterns ---

_EMAIL = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
)

_PHONE = re.compile(
    r'(?<!\d)(\+?\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,9})(?!\d)'
)

_CREDIT_CARD = re.compile(
    r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'
)

_SSN = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')

# --- Token / secret patterns ---

_API_KEY_PATTERN = re.compile(
    r'(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*["\']?[A-Za-z0-9_\-]{20,}["\']?',
    re.IGNORECASE
)

_JWT = re.compile(
    r'\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b'
)

# --- Code block detection (for skipping false positives) ---
_CODE_BLOCK = re.compile(r'```[\s\S]*?```')
_INLINE_CODE = re.compile(r'`[^`]+`')

# Self-referential context: model saying "I am X" vs user asking "use X"
_SELF_REF = re.compile(
    r'\b(I\s+am|I\'m|I\s+use|I\s+run|running\s+on|powered\s+by|built\s+with|'
    r'my\s+model|my\s+architecture|my\s+system|my\s+backend|'
    r'I\s+was\s+built|I\s+was\s+trained|I\s+was\s+created)\b',
    re.IGNORECASE
)


def _get_code_block_spans(text):
    """Return set of character positions inside code blocks."""
    spans = set()
    for m in _CODE_BLOCK.finditer(text):
        spans.update(range(m.start(), m.end()))
    for m in _INLINE_CODE.finditer(text):
        spans.update(range(m.start(), m.end()))
    return spans


def _is_self_referential(text, match_start):
    """Check if a match appears in a self-referential context (bot talking about itself)."""
    window_start = max(0, match_start - 80)
    before = text[window_start:match_start]
    return bool(_SELF_REF.search(before))


def filter_output(response_text):
    """
    Scan complete LLM response for sensitive information before sending to user.

    Returns FilterResult with filtered text and violation details.
    """
    if not response_text:
        return FilterResult(filtered_text=response_text)

    violations = []
    code_spans = _get_code_block_spans(response_text)
    filtered = response_text

    def _check_and_redact(pattern, category, replacement, require_self_ref=False):
        nonlocal filtered
        new_text = filtered
        for m in list(pattern.finditer(filtered)):
            if any(pos in code_spans for pos in range(m.start(), m.end())):
                continue
            if require_self_ref and not _is_self_referential(filtered, m.start()):
                continue
            violations.append((category, m.group()))
            new_text = new_text[:m.start()] + replacement + new_text[m.end():]
        if new_text != filtered:
            filtered = new_text

    # Critical: infrastructure leaks (always redact)
    _check_and_redact(_INFRA_URLS, "infrastructure", "[REDACTED]")
    _check_and_redact(_ENV_VARS, "env_variable", "[REDACTED]")
    _check_and_redact(_FILE_PATHS, "file_path", "[REDACTED]")
    _check_and_redact(_DOTENV_REF, "dotenv", "[REDACTED]")
    _check_and_redact(_API_KEY_PATTERN, "api_key", "[REDACTED]")
    _check_and_redact(_JWT, "jwt_token", "[REDACTED]")

    # Internal terms: only redact in self-referential context
    _check_and_redact(_INTERNAL_MODEL_NAMES, "model_name", "an AI model", require_self_ref=True)
    _check_and_redact(_INTERNAL_FRAMEWORKS, "framework", "the system", require_self_ref=True)
    _check_and_redact(_INTERNAL_API_PATHS, "api_path", "[REDACTED]", require_self_ref=True)

    # PII
    _check_and_redact(_SSN, "ssn", "[REDACTED]")
    _check_and_redact(_CREDIT_CARD, "credit_card", "[REDACTED]")

    was_modified = len(violations) > 0

    if len(violations) > 5:
        logger.warning(f"Output blocked: {len(violations)} violations — {[v[0] for v in violations]}")
        return FilterResult(
            filtered_text=SAFE_FALLBACK,
            violations=violations,
            was_modified=True
        )

    if was_modified:
        logger.info(f"Output filtered: {len(violations)} redactions — {[v[0] for v in violations]}")

    return FilterResult(
        filtered_text=filtered,
        violations=violations,
        was_modified=was_modified
    )


# ===================================================================
# Layer 3: Input Filtering
# ===================================================================

_INJECTION_PATTERNS = {
    "ignore_instructions": [
        re.compile(
            r'\b(ignore|disregard|forget|skip|drop)\s+(all\s+)?(previous|prior|above|earlier|system|initial)\s+'
            r'(instructions?|prompts?|rules?|commands?|guidelines?|constraints?|context)\b',
            re.IGNORECASE
        ),
        re.compile(
            r'\b(override|bypass|disable|turn\s+off|remove|delete)\s+(the\s+)?(system|safety|guardrails?|rules?|filters?|restrictions?)\b',
            re.IGNORECASE
        ),
    ],
    "role_manipulation": [
        re.compile(
            r'\b(you\s+are\s+now|from\s+now\s+on\s+you\s+are|act\s+as\s+if\s+you\s+are|'
            r'pretend\s+(you\s+are|to\s+be)|simulate\s+being|roleplay\s+as|'
            r'switch\s+to\s+.{0,20}mode|enter\s+.{0,20}mode)\b',
            re.IGNORECASE
        ),
        re.compile(r'\bDAN\s+mode\b', re.IGNORECASE),
        re.compile(r'\b(jailbreak|jailbroken|unrestricted\s+mode|unfiltered\s+mode|developer\s+mode)\b', re.IGNORECASE),
    ],
    "system_probing": [
        re.compile(
            r'\b(repeat|print|show|reveal|display|output|dump|list|give\s+me|tell\s+me)\s+'
            r'(your|the)\s+(system\s+)?(instructions?|system\s*prompt|rules?|configuration|guidelines|directives)\b',
            re.IGNORECASE
        ),
        re.compile(
            r'\b(what\s+(are\s+you|is\s+your)\s+(made\s+of|built\s+with|running\s+on|programmed\s+(in|with)|'
            r'architecture|tech\s*stack|backend|infrastructure|source\s*code|framework))\b',
            re.IGNORECASE
        ),
        re.compile(
            r'\b(show|tell|reveal|give)\s+me\s+(your\s+)?(source\s*code|code\s*base|system\s*prompt|internal)\b',
            re.IGNORECASE
        ),
    ],
    "encoded_evasion": [
        re.compile(r'(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{60,}={0,2}(?![A-Za-z0-9+/])'),
        re.compile(r'(\\x[0-9a-fA-F]{2}){4,}'),
        re.compile(r'(&#\d{2,4};){4,}'),
    ],
}

_SAFE_INPUT_CONTEXTS = [
    re.compile(r'\b(in\s+)?(git|github|docker|kubernetes|linux|bash|sql|css|html)\b', re.IGNORECASE),
    re.compile(r'\b(how\s+to|tutorial|example|learn|explain)\b.*\b(ignore|disregard|bypass|override)\b', re.IGNORECASE),
]


def _is_rate_limited(user_id):
    user_id = str(user_id)
    if user_id not in _probe_tracker:
        return False
    tracker = _probe_tracker[user_id]
    if tracker.get("blocked_until", 0) > time.time():
        return True
    return False


def _record_probe(user_id):
    user_id = str(user_id)
    now = time.time()

    if user_id not in _probe_tracker:
        _probe_tracker[user_id] = {"timestamps": [], "blocked_until": 0}

    tracker = _probe_tracker[user_id]
    tracker["timestamps"] = [t for t in tracker["timestamps"] if now - t < PROBE_WINDOW]
    tracker["timestamps"].append(now)

    if len(tracker["timestamps"]) >= PROBE_THRESHOLD:
        tracker["blocked_until"] = now + PROBE_BLOCK_DURATION
        logger.warning(f"User {user_id} rate-limited: {len(tracker['timestamps'])} probes in {PROBE_WINDOW}s")
        return True
    return False


def filter_input(user_prompt, user_id="unknown"):
    """
    Check user input for prompt injection and probing patterns.

    Returns InputFilterResult indicating safety and threat level.
    """
    if not user_prompt:
        return InputFilterResult(is_safe=True)

    if _is_rate_limited(user_id):
        return InputFilterResult(
            is_safe=False,
            threat_level="high",
            detected_attacks=["rate_limited"],
            should_warn=True,
            warning_message=INPUT_BLOCKED_MESSAGE
        )

    detected = []

    for category, patterns in _INJECTION_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(user_prompt):
                is_educational = any(sp.search(user_prompt) for sp in _SAFE_INPUT_CONTEXTS)
                if not is_educational:
                    detected.append(category)
                    break

    if not detected:
        return InputFilterResult(is_safe=True)

    high_threat = {"ignore_instructions", "role_manipulation"}
    medium_threat = {"system_probing", "encoded_evasion"}

    has_high = bool(high_threat & set(detected))

    if has_high or len(detected) >= 2:
        threat_level = "high"
    elif medium_threat & set(detected):
        threat_level = "medium"
    else:
        threat_level = "low"

    rate_limited = _record_probe(user_id)

    if threat_level == "high" or rate_limited:
        logger.warning(f"Input BLOCKED [{threat_level}] user={user_id}: {detected}")
        return InputFilterResult(
            is_safe=False,
            threat_level=threat_level,
            detected_attacks=detected,
            should_warn=True,
            warning_message=INPUT_BLOCKED_MESSAGE
        )
    elif threat_level == "medium":
        logger.info(f"Input BLOCKED [{threat_level}] user={user_id}: {detected}")
        return InputFilterResult(
            is_safe=False,
            threat_level=threat_level,
            detected_attacks=detected,
            should_warn=True,
            warning_message=INPUT_BLOCKED_MESSAGE
        )
    else:
        logger.info(f"Input flagged [{threat_level}] user={user_id}: {detected}")
        return InputFilterResult(
            is_safe=True,
            threat_level=threat_level,
            detected_attacks=detected,
            should_warn=False
        )


# ===================================================================
# Layer 4: Content Safety
# ===================================================================

_CONTENT_SAFETY_PATTERNS = {
    "violence_weapons": [
        re.compile(
            r'\b(how\s+to|ways?\s+to|methods?\s+(to|for)|guide\s+(to|for)|steps?\s+to|instructions?\s+(to|for))\s+'
            r'(make|build|create|construct|assemble|manufacture)\s+(a\s+)?(bomb|explosive|weapon|firearm|poison|toxin)\b',
            re.IGNORECASE
        ),
        re.compile(
            r'\b(how\s+to|ways?\s+to|methods?\s+(to|for))\s+'
            r'(kill|murder|assassinate|harm|injure|torture)\s+(a\s+)?(person|someone|people|human)\b',
            re.IGNORECASE
        ),
    ],
    "self_harm": [
        re.compile(
            r'\b(how\s+to|ways?\s+to|methods?\s+(to|for)|best\s+way\s+to)\s+'
            r'(commit\s+suicide|kill\s+(myself|yourself|oneself)|end\s+(my|your|one\'s)\s+life)\b',
            re.IGNORECASE
        ),
        re.compile(
            r'\b(suicide|self[\s-]?harm|cutting|overdose)\s+(method|technique|guide|tutorial|instruction)\b',
            re.IGNORECASE
        ),
    ],
    "csam": [
        re.compile(
            r'\b(child|minor|underage|kid|infant|toddler|boy|girl)\b.{0,30}'
            r'\b(sexual|nude|naked|porn|explicit|erotic|intimate)\b',
            re.IGNORECASE
        ),
    ],
    "illegal_activity": [
        re.compile(
            r'\b(how\s+to|guide\s+to|tutorial\s+(on|for))\s+'
            r'(hack\s+into|crack|breach|exploit)\s+(a\s+)?(bank|account|server|system|network|database)\b',
            re.IGNORECASE
        ),
        re.compile(
            r'\b(how\s+to|where\s+to)\s+(buy|sell|get|obtain|order|purchase)\s+'
            r'(cocaine|heroin|meth|fentanyl|drugs|stolen\s+(credit\s+)?cards?|weapons?|firearms?)\b',
            re.IGNORECASE
        ),
    ],
    "hate_speech": [
        re.compile(
            r'\b(kill|exterminate|eliminate|eradicate|genocide)\s+all\s+'
            r'(jews?|muslims?|christians?|blacks?|whites?|asians?|gays?|lesbians?|trans|women|men)\b',
            re.IGNORECASE
        ),
    ],
}


def check_content_safety(text):
    """Check text for harmful content categories."""
    if not text:
        return SafetyResult(is_safe=True)

    violations = []

    for category, patterns in _CONTENT_SAFETY_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(text):
                violations.append(category)
                break

    if not violations:
        return SafetyResult(is_safe=True)

    critical_categories = {"csam"}
    high_categories = {"violence_weapons", "self_harm"}

    if critical_categories & set(violations):
        severity = "critical"
    elif high_categories & set(violations):
        severity = "high"
    else:
        severity = "medium"

    logger.warning(f"Content safety violation: {violations} (severity={severity})")
    return SafetyResult(is_safe=False, violations=violations, severity=severity)


# ===================================================================
# Layer 5: Operational Security
# ===================================================================

_LOG_REDACT_PATTERNS = [
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'), '[EMAIL]'),
    (re.compile(r'\b[A-Za-z0-9_\-]{30,}\b'), '[TOKEN]'),
    (re.compile(r'\+?\d{10,}'), '[PHONE]'),
    (re.compile(r'(https?://\S+)'), '[URL]'),
]


def sanitize_for_logging(text, max_length=80):
    """Remove sensitive data from text before logging. Truncates to max_length."""
    if not text:
        return ""
    sanitized = text
    for pattern, replacement in _LOG_REDACT_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."
    return sanitized


def enforce_length_limit(text, limit_type="message"):
    """Enforce length limits on user input. Returns (text, was_truncated)."""
    if not text:
        return text, False
    max_len = MAX_INPUT_LENGTHS.get(limit_type, 4000)
    if len(text) <= max_len:
        return text, False
    return text[:max_len], True


# ===================================================================
# Convenience: Combined input check
# ===================================================================

def check_input(user_prompt, user_id="unknown", limit_type="message"):
    """
    Run all input checks: length limit, prompt injection, content safety.

    Returns (is_safe, warning_message_or_None, cleaned_text).
    """
    text, truncated = enforce_length_limit(user_prompt, limit_type)
    injection_result = filter_input(text, user_id)
    if not injection_result.is_safe:
        return False, injection_result.warning_message, text
    safety_result = check_content_safety(text)
    if not safety_result.is_safe:
        return False, CONTENT_BLOCKED_MESSAGE, text
    return True, None, text
