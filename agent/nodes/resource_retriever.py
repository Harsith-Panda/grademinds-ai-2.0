"""
agent/nodes/resource_retriever.py
Node 5 — Resource Retriever
GradeMinds AI — Milestone 2

For each topic in today's plan, queries Tavily for curated external resources,
checks Chroma to avoid repetition across sessions, and returns a deduplicated,
course-isolated resource list.

Patterns followed:
- node signature: def resource_retriever_node(state: dict) -> dict
- Pydantic output schema with validators
- MAX_RETRIES = 2 retry loop with _correction_prompt() on LLM fallback
- Safe fallback return on total failure (never crashes the graph)
- LLM loaded once at module level (ChatGroq)
- JSON parsing strips markdown fences before json.loads()
- Chroma isolation: every query filters by course_id (matches app.py pattern)
  student_id also stored in metadata for reference
- All secrets via os.getenv() with load_dotenv()
- Print statements: [resource_retriever] prefix on every major step
"""

import os
import json
import chromadb
from datetime import datetime
from typing import List, Optional

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, field_validator, ValidationError
from tavily import TavilyClient

load_dotenv()

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------
llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.2)

_tavily_api_key = os.getenv("TAVILY_API_KEY", "")
tavily_client = TavilyClient(api_key=_tavily_api_key) if _tavily_api_key else None

chroma_client = chromadb.PersistentClient(path="./grademinds_db")
resources_collection = chroma_client.get_or_create_collection("saved_resources")

MAX_RETRIES = 2

# ---------------------------------------------------------------------------
# Trusted domains for resource filtering
# ---------------------------------------------------------------------------
TRUSTED_DOMAINS = [
    "khanacademy.org",
    "youtube.com",
    "youtu.be",
    "docs.python.org",
    "developer.mozilla.org",
    "w3schools.com",
    "geeksforgeeks.org",
    "medium.com",
    "towardsdatascience.com",
    "realpython.com",
    "coursera.org",
    "edx.org",
    "mit.edu",
    "stanford.edu",
    "arxiv.org",
    "wikipedia.org",
    "github.com",
    "stackoverflow.com",
    "freecodecamp.org",
    "tutorialspoint.com",
    "scikit-learn.org",
    "tensorflow.org",
    "pytorch.org",
    "numpy.org",
    "pandas.pydata.org",
]

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ResourceLink(BaseModel):
    title: str
    url: str
    source: str  # "tavily" | "chroma_cache" | "llm_fallback"

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        return v

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"url must start with http(s)://: {v!r}")
        return v

    @field_validator("source")
    @classmethod
    def valid_source(cls, v: str) -> str:
        if v not in ("tavily", "chroma_cache", "llm_fallback"):
            raise ValueError(f"Unknown source: {v!r}")
        return v


class TopicResources(BaseModel):
    topic: str
    links: List[ResourceLink]

    @field_validator("topic")
    @classmethod
    def topic_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("topic must not be empty")
        return v

    @field_validator("links")
    @classmethod
    def at_least_one_link(cls, v: List[ResourceLink]) -> List[ResourceLink]:
        if not v:
            raise ValueError("links list must contain at least one resource")
        return v


class ResourceRetrieverOutput(BaseModel):
    resources: List[TopicResources]

    @field_validator("resources")
    @classmethod
    def resources_not_empty(cls, v: List[TopicResources]) -> List[TopicResources]:
        if not v:
            raise ValueError("resources list must not be empty")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Strip markdown code fences LLMs frequently emit."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        text = "\n".join(lines).strip()
    return text


def _is_trusted(url: str) -> bool:
    """Return True if the URL belongs to a trusted domain."""
    return any(domain in url for domain in TRUSTED_DOMAINS)


def _chroma_resource_key(course_id: str, topic: str, url: str) -> str:
    """
    Stable Chroma document ID for a saved resource.
    Keyed by course_id — matches how app.py isolates all data:
    get_topics_for_course(course_id), load_roadmap(course_id), etc.
    One student can have multiple courses; course_id is the correct scope.
    """
    safe_topic = topic.replace(" ", "_").lower()[:40]
    safe_url = url[-30:].replace("/", "_").replace(":", "")
    return f"{course_id}_{safe_topic}_{safe_url}"


def _get_cached_resources(course_id: str, topic: str) -> List[ResourceLink]:
    """Query Chroma for previously saved resources for this topic + course."""
    print(f"[resource_retriever] Checking Chroma cache for '{topic}' (course: {course_id})")
    try:
        results = resources_collection.get(
            where={"$and": [{"course_id": {"$eq": course_id}}, {"topic": {"$eq": topic}}]}
        )
        links = []
        for doc, meta in zip(results.get("documents", []), results.get("metadatas", [])):
            try:
                links.append(
                    ResourceLink(
                        title=meta.get("title", doc),
                        url=meta.get("url", ""),
                        source="chroma_cache",
                    )
                )
            except ValidationError:
                continue
        print(f"[resource_retriever] Found {len(links)} cached resource(s) for '{topic}'")
        return links
    except Exception as e:
        print(f"[resource_retriever] Chroma cache lookup failed for '{topic}': {e}")
        return []


def _save_resources_to_chroma(
    course_id: str, student_id: str, topic: str, links: List[ResourceLink]
) -> None:
    """Persist new Tavily resources into Chroma for future deduplication."""
    print(f"[resource_retriever] Saving {len(links)} resource(s) to Chroma for '{topic}'")
    ids, documents, metadatas = [], [], []
    for link in links:
        if link.source != "tavily":
            continue
        doc_id = _chroma_resource_key(course_id, topic, link.url)
        ids.append(doc_id)
        documents.append(link.title)
        metadatas.append(
            {
                "course_id": course_id,
                "student_id": student_id,   # stored for audit/reference
                "topic": topic,
                "title": link.title,
                "url": link.url,
                "saved_at": datetime.now().isoformat(),
            }
        )
    if ids:
        try:
            resources_collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
            print(f"[resource_retriever] Upserted {len(ids)} resource(s) into Chroma")
        except Exception as e:
            print(f"[resource_retriever] Failed to save resources to Chroma: {e}")


def _tavily_search(topic: str, max_results: int = 3) -> List[ResourceLink]:
    """Run a Tavily search for the given topic and return filtered ResourceLinks."""
    if tavily_client is None:
        print("[resource_retriever] Tavily client not initialised (missing API key) — skipping web search")
        return []

    query = f"learn {topic} tutorial beginner guide"
    print(f"[resource_retriever] Tavily query: '{query}'")
    try:
        response = tavily_client.search(
            query=query,
            search_depth="basic",
            max_results=max_results + 3,  # fetch extra to allow trust filtering
            include_answer=False,
        )
        raw_results = response.get("results", [])
        links = []
        seen_urls: set = set()
        for r in raw_results:
            url = r.get("url", "").strip()
            title = r.get("title", "").strip()
            if not url or not title:
                continue
            if url in seen_urls:
                continue
            if not _is_trusted(url):
                continue
            seen_urls.add(url)
            try:
                links.append(ResourceLink(title=title, url=url, source="tavily"))
            except ValidationError:
                continue
            if len(links) >= max_results:
                break

        print(f"[resource_retriever] Tavily returned {len(links)} trusted result(s) for '{topic}'")
        return links
    except Exception as e:
        print(f"[resource_retriever] Tavily search failed for '{topic}': {e}")
        return []


# ---------------------------------------------------------------------------
# LLM fallback: used when Tavily returns nothing
# ---------------------------------------------------------------------------

_FALLBACK_SYSTEM = (
    "You are a learning resource curator. "
    "Output ONLY valid JSON. No preamble, no explanation, no markdown fences."
)

_FALLBACK_USER_TEMPLATE = """\
Suggest {n} high-quality, free learning resources for the topic: "{topic}"

Return a JSON array:
[
  {{"title": "resource title", "url": "https://...", "source": "llm_fallback"}},
  ...
]

Rules:
- Only include real, well-known URLs (Khan Academy, YouTube, official docs, etc.)
- Do NOT invent URLs — only use URLs you are highly confident exist
- Each object must have exactly the three keys: title, url, source
- source must always be "llm_fallback"
"""

_FALLBACK_CORRECTION_TEMPLATE = """\
Your previous response could not be parsed as valid JSON.
Error: {error}

Return ONLY a valid JSON array of resource objects with keys: title, url, source.
No markdown, no explanation.
"""


def _llm_fallback_resources(topic: str, n: int = 2) -> List[ResourceLink]:
    """Ask the LLM to suggest resources when Tavily returns nothing useful."""
    print(f"[resource_retriever] Using LLM fallback for '{topic}'")
    messages = [
        SystemMessage(content=_FALLBACK_SYSTEM),
        HumanMessage(content=_FALLBACK_USER_TEMPLATE.format(topic=topic, n=n)),
    ]

    last_error = ""
    for attempt in range(MAX_RETRIES):
        if attempt > 0:
            print(f"[resource_retriever] LLM fallback retry {attempt}/{MAX_RETRIES - 1} for '{topic}'")
            messages.append(
                HumanMessage(content=_FALLBACK_CORRECTION_TEMPLATE.format(error=last_error))
            )
        try:
            response = llm.invoke(messages)
            raw = _strip_fences(response.content)
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError("Expected a JSON array at top level")

            links = []
            for item in parsed:
                try:
                    links.append(ResourceLink(**item))
                except (ValidationError, TypeError):
                    continue
            if links:
                print(f"[resource_retriever] LLM fallback produced {len(links)} resource(s) for '{topic}'")
                return links
            last_error = "All items failed Pydantic validation"
        except Exception as e:
            last_error = str(e)
            print(f"[resource_retriever] LLM fallback parse error (attempt {attempt}): {e}")

    print(f"[resource_retriever] LLM fallback exhausted for '{topic}' — returning empty list")
    return []


# ---------------------------------------------------------------------------
# Core per-topic resource resolution
# ---------------------------------------------------------------------------

def _resolve_resources_for_topic(
    course_id: str,
    student_id: str,
    topic: str,
    cached_links: List[ResourceLink],
    max_links: int = 3,
) -> List[ResourceLink]:
    """
    Build the final resource list for one topic:
    1. Pull from Chroma cache (course-isolated) to avoid session repetition
    2. Fill remaining slots with fresh Tavily results
    3. If still empty, fall back to LLM suggestions
    4. Deduplicate by URL across all sources
    5. Persist fresh Tavily links back to Chroma
    """
    seen_urls: set = {lnk.url for lnk in cached_links}
    final_links: List[ResourceLink] = list(cached_links[:max_links])

    slots_needed = max_links - len(final_links)
    if slots_needed > 0:
        tavily_links = _tavily_search(topic, max_results=slots_needed + 2)
        for lnk in tavily_links:
            if lnk.url not in seen_urls:
                final_links.append(lnk)
                seen_urls.add(lnk.url)
            if len(final_links) >= max_links:
                break

    if not final_links:
        print(f"[resource_retriever] No Tavily results — triggering LLM fallback for '{topic}'")
        fallback_links = _llm_fallback_resources(topic, n=max_links)
        for lnk in fallback_links:
            if lnk.url not in seen_urls:
                final_links.append(lnk)
                seen_urls.add(lnk.url)

    new_tavily = [lnk for lnk in final_links if lnk.source == "tavily"]
    if new_tavily:
        _save_resources_to_chroma(course_id, student_id, topic, new_tavily)

    return final_links[:max_links]


# ---------------------------------------------------------------------------
# Main node function
# ---------------------------------------------------------------------------

def resource_retriever_node(state: dict) -> dict:
    """
    Node 5 — Resource Retriever

    Reads `todays_plan` from state (produced by Node 4 / spaced_rep_node).
    For every topic in today's plan (new + review), retrieves 2-3 curated
    resource links using Tavily + Chroma deduplication, with an LLM fallback.

    State keys read:  student_id, course_id, todays_plan
    State key written: resources → List[{topic, links: [{title, url, source}]}]

    Isolation key: course_id  (matches app.py pattern — one student can have
    multiple courses; all chroma_ops functions key by course_id throughout)
    """
    print("[resource_retriever] ── Node 5 started ──────────────────────────────")

    student_id: str = state.get("student_id", "unknown_student")
    # course_id is the correct isolation key — matches app.py and chroma_ops
    # e.g. cache_key = f"todays_plan_{course_id}_{str(date.today())}"
    course_id: str = state.get("course_id") or student_id  # graceful fallback
    todays_plan: dict = state.get("todays_plan") or {}

    print(f"[resource_retriever] student_id={student_id}  course_id={course_id}")

    # ── Collect all topics that need resources ──────────────────────────────
    topics_needed: List[str] = []

    new_topic = todays_plan.get("new_topic")
    if new_topic:
        name = (
            new_topic.get("name") or new_topic.get("topic", "")
            if isinstance(new_topic, dict)
            else str(new_topic)
        )
        if name and name.strip():
            topics_needed.append(name.strip())

    review_topics = todays_plan.get("review_topics") or []
    for rt in review_topics:
        name = (
            rt.get("name") or rt.get("topic", "")
            if isinstance(rt, dict)
            else str(rt)
        )
        if name and name.strip() and name.strip() not in topics_needed:
            topics_needed.append(name.strip())

    print(f"[resource_retriever] Topics requiring resources: {topics_needed}")

    # ── Safety fallback: nothing in today's plan ────────────────────────────
    if not topics_needed:
        print("[resource_retriever] No topics in today's plan — returning empty resources list")
        return {**state, "resources": []}

    # ── Retrieve resources per topic ────────────────────────────────────────
    all_topic_resources: List[TopicResources] = []

    for topic in topics_needed:
        print(f"[resource_retriever] Processing topic: '{topic}'")

        cached = _get_cached_resources(course_id, topic)

        final_links = _resolve_resources_for_topic(
            course_id=course_id,
            student_id=student_id,
            topic=topic,
            cached_links=cached,
            max_links=3,
        )

        if not final_links:
            print(f"[resource_retriever] WARNING: Zero resources resolved for '{topic}' — skipping")
            continue

        try:
            topic_resources = TopicResources(topic=topic, links=final_links)
            all_topic_resources.append(topic_resources)
            print(f"[resource_retriever] '{topic}' → {len(final_links)} resource(s) confirmed")
        except ValidationError as ve:
            print(f"[resource_retriever] Pydantic validation failed for '{topic}': {ve} — skipping")

    # ── Full fallback: all topics failed ────────────────────────────────────
    if not all_topic_resources:
        print("[resource_retriever] All topics failed resource resolution — returning safe empty list")
        return {**state, "resources": []}

    # ── Validate overall output ─────────────────────────────────────────────
    try:
        validated_output = ResourceRetrieverOutput(resources=all_topic_resources)
    except ValidationError as ve:
        print(f"[resource_retriever] Output-level Pydantic validation failed: {ve}")
        return {**state, "resources": []}

    # ── Serialise to plain dicts for LangGraph state ────────────────────────
    serialised = [
        {
            "topic": tr.topic,
            "links": [
                {"title": lnk.title, "url": lnk.url, "source": lnk.source}
                for lnk in tr.links
            ],
        }
        for tr in validated_output.resources
    ]

    print(f"[resource_retriever] ── Node 5 complete — {len(serialised)} topic(s) with resources ──")
    return {**state, "resources": serialised}
