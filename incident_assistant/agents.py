"""The two agents of the assistant (Incident Analyzer and Investigation Agent) and the
query rewriting step. Each one is a prompt + an LLM with a Pydantic structured output."""
import math
import re
import time
from functools import lru_cache
from typing import Literal

import groq
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from incident_assistant import config


@lru_cache
def get_llm(model: str = config.LLM_MODEL, max_retries: int = 8) -> ChatGroq:
    if not config.GROQ_API_KEY:
        raise LLMUnavailable("configuration", "GROQ_API_KEY is missing: copy .env.example to .env and set your key.")
    # The free Groq tier allows about 8,000 tokens per minute: low reasoning effort keeps
    # each call small. The agents use max_retries=0 and retry themselves with call_llm.
    extra = {"reasoning_effort": "low"} if model.startswith("openai/gpt-oss") else {}
    return ChatGroq(model=model, api_key=config.GROQ_API_KEY, temperature=0, max_retries=max_retries, **extra)


# ---------------------------------------------------------------- LLM errors and retries

class LLMUnavailable(RuntimeError):
    """The LLM service cannot answer now. The message is written for the user (no internal detail)."""

    def __init__(self, kind: str, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.kind = kind                # daily_quota, rate_limit, network, service or configuration
        self.retry_after = retry_after  # seconds, only when Groq gave the delay


RETRYABLE = {"rate_limit", "network", "service"}
MAX_RETRIES = 8


def groq_delay(error: Exception) -> float | None:
    """Delay given by Groq: the retry-after header, or "try again in 29m1.8s" in the message."""
    response = getattr(error, "response", None)
    header = response.headers.get("retry-after") if response is not None else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = re.search(r"try again in ((?:[\d.]+(?:ms|h|m|s))+)", str(error))
    if not match:
        return None
    units = {"h": 3600, "m": 60, "s": 1, "ms": 0.001}
    return sum(float(value) * units[unit] for value, unit in re.findall(r"([\d.]+)(ms|h|m|s)", match.group(1)))


def wait_text(seconds: float | None) -> str:
    if seconds is None:
        return "later"
    return f"in about {round(seconds / 60)} min" if seconds >= 90 else f"in about {math.ceil(seconds)} s"


def classify_llm_error(error: Exception, model: str) -> LLMUnavailable | None:
    """Turn a known Groq error into an LLMUnavailable; None for any other error."""
    if isinstance(error, LLMUnavailable):
        return error
    if isinstance(error, groq.RateLimitError):
        delay = groq_delay(error)
        if "per day" in str(error):   # tokens per day (TPD) or requests per day (RPD)
            return LLMUnavailable("daily_quota", f"The LLM service is temporarily unavailable: the daily quota "
                                                 f"of model {model} is used up. Try again {wait_text(delay)}.", delay)
        return LLMUnavailable("rate_limit", f"The LLM service is busy (per-minute limit of model {model}). "
                                            f"Try again {wait_text(delay)}.", delay)
    if isinstance(error, groq.APIConnectionError):
        return LLMUnavailable("network", "The LLM service cannot be reached. Check the internet connection and try again.")
    if isinstance(error, (groq.AuthenticationError, groq.PermissionDeniedError, groq.NotFoundError)):
        return LLMUnavailable("configuration", f"LLM configuration problem: check GROQ_API_KEY and the model name "
                                               f"({model}) in the .env file.")
    if isinstance(error, groq.InternalServerError):
        return LLMUnavailable("service", "The LLM service had a temporary error. Try again in a moment.")
    return None


def call_llm(chain, values: dict, model: str, sleep=time.sleep):
    """Invoke a chain. Temporary errors are retried, waiting the delay given by Groq when known;
    a used-up daily quota or a configuration problem stops at once (retrying cannot help)."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return chain.invoke(values)
        except Exception as error:
            problem = classify_llm_error(error, model)
            if problem is None:
                raise
            if problem.kind not in RETRYABLE or attempt == MAX_RETRIES:
                raise problem from error
            sleep(problem.retry_after if problem.retry_after is not None else min(2 ** attempt, 8))


# ---------------------------------------------------------------- Incident Analyzer

class IncidentAnalysis(BaseModel):
    summary: str = Field(description="One-sentence technical summary of the incident")
    technologies: list[str] = Field(description="Technologies explicitly involved, lowercase (e.g. kubernetes, docker, terraform)")
    symptoms: list[str] = Field(description="Observable symptoms described by the user")
    error_messages: list[str] = Field(description="Error messages or status values copied exactly as written by the user")
    recent_changes: list[str] = Field(description="Recent changes mentioned by the user (deployment, config change...)")
    search_queries: list[str] = Field(description="2 or 3 short search queries for a DevOps troubleshooting knowledge base")
    missing_information: list[str] = Field(description="Information that would help the diagnosis but is not given")
    needs_clarification: bool = Field(description="True only if no technology and no usable symptom can be identified")
    clarification_questions: list[str] = Field(description="Questions to ask the user when needs_clarification is true, else empty")


ANALYZER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are the Incident Analyzer of a DevOps troubleshooting assistant.
Your job is to understand and structure the incident described by the user. You do not solve it.

Rules:
- Only list technologies that the user mentions or that are unambiguous from the description.
- Copy error messages and status values exactly (e.g. CrashLoopBackOff, 502, "Permission denied (publickey)").
- Write search queries in English, short and specific, using the technical vocabulary of the problem.
- Set needs_clarification to true only when the description is too vague to search anything
  (for example "my app is broken"). Otherwise it must be false, even if information is missing."""),
    ("human", "Incident description:\n{incident}"),
])


def analyze_incident(incident: str) -> IncidentAnalysis:
    chain = ANALYZER_PROMPT | get_llm(config.ANALYZER_MODEL, max_retries=0).with_structured_output(IncidentAnalysis)
    return call_llm(chain, {"incident": incident}, config.ANALYZER_MODEL)


# ---------------------------------------------------------------- Query rewriting

class RewrittenQueries(BaseModel):
    queries: list[str] = Field(description="2 or 3 new search queries")


REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """The previous searches in a DevOps troubleshooting knowledge base did not return
relevant passages. Write new, different search queries in English: use synonyms, the underlying
technology, the exact error code, or a more general formulation. Do not answer the incident."""),
    ("human", "Incident: {summary}\nError messages: {errors}\nPrevious queries: {previous}"),
])


def rewrite_queries(analysis: IncidentAnalysis, previous_queries: list[str]) -> list[str]:
    chain = REWRITE_PROMPT | get_llm(config.ANALYZER_MODEL, max_retries=0).with_structured_output(RewrittenQueries)
    result = call_llm(chain, {
        "summary": analysis.summary,
        "errors": ", ".join(analysis.error_messages) or "none",
        "previous": "; ".join(previous_queries),
    }, config.ANALYZER_MODEL)
    return result.queries


# ---------------------------------------------------------------- Investigation Agent

class Cause(BaseModel):
    cause: str = Field(description="Short name of the possible cause")
    explanation: str = Field(description="Why this cause matches the incident")
    evidence: list[str] = Field(description="Identifiers of the passages supporting it, e.g. ['S1', 'S3']")
    status: Literal["documented", "hypothesis"] = Field(
        description="documented if at least one passage explicitly supports it, otherwise hypothesis")


class Step(BaseModel):
    action: str = Field(description="What to check")
    command: str | None = Field(description="Diagnostic command taken from the passages, or null")
    interpretation: str = Field(description="What the result tells and what to do next")
    evidence: list[str] = Field(description="Identifiers of the supporting passages")


class Solution(BaseModel):
    solution: str
    for_cause: str = Field(description="Name of the cause this solution addresses")
    evidence: list[str] = Field(description="Identifiers of the supporting passages")


class Investigation(BaseModel):
    possible_causes: list[Cause]
    investigation_steps: list[Step]
    possible_solutions: list[Solution]
    missing_information: list[str] = Field(description="What the user should collect to confirm the cause")
    confidence_note: str = Field(description="One sentence on how solid the analysis is")


INVESTIGATOR_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are the Investigation Agent of a DevOps troubleshooting assistant.
You receive an analysed incident and numbered passages [S1], [S2]... from a documentation base.

Rules:
- Base causes, steps and solutions on the passages. Cite them with their identifiers in the evidence fields.
- Only use identifiers that appear in the passages. Never invent a source. Markers such as [R2]
  inside a passage are that guide's own bibliography, not passage identifiers: do not cite them.
- Mark a cause "documented" when a cited passage lists or explains this cause (for example in a
  "Possible Causes" section). Mark it "hypothesis" when it is your own reasoning that no passage
  states; in that case leave its evidence empty.
- Take diagnostic commands from the passages; do not invent options.
- Cite a passage for a step or a solution only if that passage itself states it. A passage on the
  same topic is not enough. If no passage states it, leave its evidence empty: it will be shown
  to the user as not sourced.
- You have no access to the user's environment: never claim that something was checked or confirmed.
- Order investigation steps from the quickest and most informative to the slowest.
- Be concise: at most 4 causes, 6 investigation steps and 4 solutions.
- If the passages do not cover the incident, say so in confidence_note and list what is missing
  instead of guessing.{insufficient_note}"""),
    ("human", """Incident summary: {summary}
Technologies: {technologies}
Symptoms: {symptoms}
Error messages: {errors}
Recent changes: {changes}

Passages:
{passages}"""),
])

INSUFFICIENT_NOTE = """
- WARNING: the retrieval step found little relevant evidence. Be explicit that the documentation
  is insufficient, keep causes as hypotheses unless a passage clearly supports them."""


def format_passages(passages: list[dict]) -> str:
    blocks = []
    for number, passage in enumerate(passages, start=1):
        blocks.append(f"[S{number}] ({reference_label(passage)})\n{passage['text']}")
    return "\n\n".join(blocks)


def reference_label(passage: dict) -> str:
    if passage.get("page"):
        return f"{passage['title']}, PDF p. {passage['page']}"
    return f"{passage['title']} - section {passage.get('section')}"


def investigate(analysis: IncidentAnalysis, passages: list[dict], evidence_insufficient: bool) -> Investigation:
    chain = INVESTIGATOR_PROMPT | get_llm(config.INVESTIGATOR_MODEL, max_retries=0).with_structured_output(Investigation)
    return call_llm(chain, {
        "insufficient_note": INSUFFICIENT_NOTE if evidence_insufficient else "",
        "summary": analysis.summary,
        "technologies": ", ".join(analysis.technologies) or "not specified",
        "symptoms": "; ".join(analysis.symptoms) or "not specified",
        "errors": "; ".join(analysis.error_messages) or "none",
        "changes": "; ".join(analysis.recent_changes) or "none mentioned",
        "passages": format_passages(passages) or "(no passage found)",
    }, config.INVESTIGATOR_MODEL)
