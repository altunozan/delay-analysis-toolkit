"""AI narrative report generation — multi-provider (Claude / ChatGPT / Gemini).

Builds a forensic-analyst prompt from the deterministic DCMA check results
and streams a professional narrative report back from the selected LLM
provider. UI-independent: exposes a text-chunk generator per provider behind
one dispatch function.

API keys are supplied by the caller (UI field or environment variable); they
are never persisted by this module. Provider SDKs are imported lazily so a
missing optional SDK only affects that provider.
"""

from __future__ import annotations

from collections.abc import Iterator

from .checks import CheckResult
from .rationale import CHECK_RATIONALE
from .xer_parser import XerData

# Provider registry: display name, default model, env var for the key.
PROVIDERS: dict[str, dict[str, str]] = {
    "anthropic": {
        "label": "Anthropic (Claude)",
        "default_model": "claude-opus-4-8",
        "env_var": "ANTHROPIC_API_KEY",
        "key_hint": "console.anthropic.com",
    },
    "openai": {
        "label": "OpenAI (ChatGPT)",
        "default_model": "gpt-5.1",
        "env_var": "OPENAI_API_KEY",
        "key_hint": "platform.openai.com",
    },
    "gemini": {
        "label": "Google (Gemini)",
        "default_model": "gemini-2.5-pro",
        "env_var": "GEMINI_API_KEY",
        "key_hint": "aistudio.google.com",
    },
}

SYSTEM_PROMPT = """\
You are an expert Forensic Delay Analyst and Project Controls Engineer
specializing in schedule diagnostics and delay analytics. Your role is to
analyze structured schedule metadata and generate high-quality, professional,
and contractually sound narratives.

Adhere strictly to the following principles:
1. Objectivity: Base all insights purely on the provided metrics. Do not
   extrapolate facts not supported by the numbers.
2. Technical Precision: Use correct project controls terminology (e.g.,
   driving logic, total float, constraints, critical path, out-of-sequence
   progress).
3. Strategic Insight: Focus on how schedule quality impacts project risk,
   critical path integrity, and potential claims exposure.
4. Balance: Report strengths with the same rigor as weaknesses. Where a
   metric passes its target, state what that soundness supports (e.g., a
   credible critical path, defensible float values); do not write a
   deficiencies-only account.
"""


# --------------------------------------------------------------------------- #
# Unified error type so the UI handles all providers the same way
# --------------------------------------------------------------------------- #
class NarrativeError(Exception):
    """Provider-agnostic failure with a user-facing message."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --------------------------------------------------------------------------- #
# Prompt assembly (provider-independent)
# --------------------------------------------------------------------------- #
# Default report-section template. The UI lets the analyst edit this before
# generation; the objectivity rules in SYSTEM_PROMPT are not editable.
DEFAULT_TEMPLATE = """\
### 1. Executive Summary
- High-level overview of the health of this schedule — both what it does
well and where it falls short.
- The single greatest risk to the project's completion date based on these
metrics.

### 2. Schedule Strengths
- Analyze the passed checks: what each sound metric supports (e.g., dense
logic → credible network; few constraints → float values that can be relied
on; healthy relationship mix → realistic sequencing).
- State which analytical conclusions these strengths make defensible.

### 3. Schedule Quality & Integrity Diagnostics (DCMA Focus)
- Analyze each failed check: what the number means for THIS schedule, why the
DCMA target exists, and what structural weakness it exposes.
- Identify where weaknesses (missing logic, constraints, high float) may be
masking true critical-path visibility or distorting float.
- Name the specific affected activities where relevant.

### 4. Critical Issues & Interactions
- Identify the most critical issues in the programme and how the individual
failures compound each other (e.g., hard constraints + negative float,
dangling logic + high float).
- Evaluate the negative-float activities and what they imply for the
completion commitment.

### 5. Claims Exposure & Recommendations
- Assess how the current schedule quality would hold up in a delay claim or
forensic review — which aspects strengthen the position and which weaken it.
- Provide a prioritized, actionable correction list for the planning team."""


def build_report_prompt(
    data: XerData,
    results: list[CheckResult],
    template: str | None = None,
) -> str:
    """Assemble the user prompt from project metadata + check results."""
    proj = data.project
    lines: list[str] = []

    lines.append("<context>")
    lines.append(
        "You have been provided with DCMA 14-Point schedule diagnostic results "
        "for the project below. These metrics were calculated deterministically "
        "by a Python engine from the native Primavera P6 (XER) schedule file. "
        "Generate a comprehensive Schedule Analytics Report."
    )
    lines.append("</context>\n")

    lines.append("<project_metadata>")
    lines.append(f"Project: {proj.short_name if proj else 'Unknown'}")
    if proj and proj.data_date:
        lines.append(f"Data Date: {proj.data_date:%Y-%m-%d}")
    if proj and proj.scheduled_finish:
        lines.append(f"Scheduled Finish: {proj.scheduled_finish:%Y-%m-%d}")
    if proj and proj.must_finish:
        lines.append(f"Must Finish By: {proj.must_finish:%Y-%m-%d}")
    lines.append(f"Total Activities: {len(data.tasks)}")
    lines.append(f"Total Relationships: {len(data.relationships)}")
    lines.append("</project_metadata>\n")

    lines.append("<diagnostic_metrics>")
    for r in results:
        lines.append(f"Check {r.number} — {r.name} [{r.status.value}]")
        lines.append(f"  Metric: {r.metric_label} = {r.metric_value} "
                     f"(target {r.threshold})")
        lines.append(f"  Finding: {r.summary}")
        if r.na_reason:
            lines.append(f"  N/A reason: {r.na_reason}")
        if r.affected_ids:
            shown = ", ".join(r.affected_ids[:25])
            more = f" (+{len(r.affected_ids) - 25} more)" if len(r.affected_ids) > 25 else ""
            lines.append(f"  Affected activities: {shown}{more}")
        rationale = CHECK_RATIONALE.get(r.number)
        if rationale:
            lines.append(f"  DCMA rationale: {rationale}")
        lines.append("")
    lines.append("</diagnostic_metrics>\n")

    lines.append("<instructions>")
    lines.append(
        "Generate the report using the following markdown structure. Keep the "
        "tone professional and authoritative — clear enough for executive "
        "stakeholders while maintaining forensic depth.\n\n"
        + (template or DEFAULT_TEMPLATE) + "\n"
    )
    lines.append("</instructions>")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Provider streaming backends
# --------------------------------------------------------------------------- #
def _stream_anthropic(api_key: str, model: str, prompt: str) -> Iterator[str]:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    try:
        with client.messages.stream(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            yield from stream.text_stream
    except anthropic.AuthenticationError:
        raise NarrativeError("Invalid Anthropic API key. Check the key and try again.")
    except anthropic.RateLimitError:
        raise NarrativeError("Rate limited by Anthropic. Wait a moment and retry.")
    except anthropic.NotFoundError:
        raise NarrativeError(f"Model '{model}' not found on Anthropic.")
    except anthropic.APIConnectionError:
        raise NarrativeError("Could not reach the Anthropic API. Check your connection.")
    except anthropic.APIStatusError as exc:
        raise NarrativeError(f"Anthropic API error ({exc.status_code}): {exc.message}")


def _stream_openai(api_key: str, model: str, prompt: str) -> Iterator[str]:
    try:
        import openai
    except ImportError:
        raise NarrativeError("OpenAI SDK not installed. Run: pip install openai")

    client = openai.OpenAI(api_key=api_key)
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except openai.AuthenticationError:
        raise NarrativeError("Invalid OpenAI API key. Check the key and try again.")
    except openai.RateLimitError:
        raise NarrativeError("Rate limited by OpenAI. Wait a moment and retry.")
    except openai.NotFoundError:
        raise NarrativeError(f"Model '{model}' not found on OpenAI.")
    except openai.APIConnectionError:
        raise NarrativeError("Could not reach the OpenAI API. Check your connection.")
    except openai.APIStatusError as exc:
        raise NarrativeError(f"OpenAI API error ({exc.status_code}): {exc.message}")


def _stream_gemini(api_key: str, model: str, prompt: str) -> Iterator[str]:
    try:
        from google import genai
        from google.genai import errors as genai_errors
        from google.genai import types as genai_types
    except ImportError:
        raise NarrativeError("Gemini SDK not installed. Run: pip install google-genai")

    client = genai.Client(api_key=api_key)
    try:
        stream = client.models.generate_content_stream(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
            ),
        )
        for chunk in stream:
            if chunk.text:
                yield chunk.text
    except genai_errors.APIError as exc:
        code = getattr(exc, "code", None)
        msg = str(getattr(exc, "message", "") or exc)
        # Gemini reports a bad key as 400 with this message, not 401.
        if code in (401, 403) or "API key not valid" in msg:
            raise NarrativeError("Invalid Gemini API key. Check the key and try again.")
        if code == 429:
            raise NarrativeError("Rate limited by Gemini. Wait a moment and retry.")
        if code == 404:
            raise NarrativeError(f"Model '{model}' not found on Gemini.")
        raise NarrativeError(f"Gemini API error ({code}): {getattr(exc, 'message', exc)}")


_BACKENDS = {
    "anthropic": _stream_anthropic,
    "openai": _stream_openai,
    "gemini": _stream_gemini,
}


def stream_narrative(
    provider: str,
    api_key: str,
    prompt: str,
    model: str | None = None,
) -> Iterator[str]:
    """Yield narrative text chunks from the chosen provider.

    Raises NarrativeError with a user-facing message on any failure.
    """
    if provider not in _BACKENDS:
        raise NarrativeError(f"Unknown provider: {provider}")
    model = model or PROVIDERS[provider]["default_model"]
    return _BACKENDS[provider](api_key, model, prompt)


def generate_narrative(
    provider: str,
    api_key: str,
    data: XerData,
    results: list[CheckResult],
    model: str | None = None,
) -> str:
    """Blocking convenience wrapper: returns the full narrative text."""
    prompt = build_report_prompt(data, results)
    return "".join(stream_narrative(provider, api_key, prompt, model))
