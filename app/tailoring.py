"""Resume parsing + Claude-powered tailoring + docx writing."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from anthropic import Anthropic
from docx import Document

from . import config

# --------------------------------------------------------------------------
# Resume structure
# --------------------------------------------------------------------------

@dataclass
class JobBlock:
    title_idx: int
    company_idx: int
    title_text: str
    company_text: str
    bullet_indices: list = field(default_factory=list)
    bullets: list = field(default_factory=list)


@dataclass
class SkillBlock:
    category_idx: int
    items_idx: int
    category: str
    items: str


@dataclass
class ResumeStruct:
    summary_idx: int           # -1 if no summary block found
    summary: str
    jobs: list
    skills: list

    @property
    def has_summary(self) -> bool:
        return self.summary_idx >= 0


def _style_name(p) -> str:
    try:
        return p.style.name or ""
    except Exception:
        return ""


# --------------------------------------------------------------------------
# AI-based resume structure analysis (adapts to any base-resume layout)
# --------------------------------------------------------------------------

_STRUCTURE_SYSTEM = """You analyze the structure of a resume document to identify which paragraphs belong to which section. You are given a numbered list of non-empty paragraphs; return a JSON document that maps indices to sections.

Output STRICT JSON only, with this exact shape:

{
  "summary_indices": [<paragraph indices making up the Summary / Profile / Objective block, in order>],
  "jobs": [
    {
      "title_idx": <index of the paragraph containing the role/company line>,
      "bullet_indices": [<indices of bullet points under this job, in order>]
    },
    ...
  ],
  "skills": [
    {
      "category_idx": <index of the skill category label>,
      "items_idx": <index of the paragraph listing items in that category>
    },
    ...
  ]
}

Rules:
- Every index you return MUST appear in the input.
- If a section doesn't exist in the resume, return an empty list for it.
- NEVER include section-header paragraphs (like "EXPERIENCE", "SKILLS", "SUMMARY") in any of the output arrays.
- For jobs: `title_idx` points to the paragraph identifying the role/company (not date lines, not location lines, not sub-headers).
- For bullets: include only actual responsibility/achievement bullets, not title/company/date lines.
- For skills: if a skill category and its items share a single paragraph (e.g. "Languages: Python, Go"), set category_idx == items_idx and the tailoring step will treat the whole line as rewrite-target.
- Never invent indices; only use indices present in the input.
- Omit education, certifications, awards, hobbies — they are not tailored.
"""


def _analyze_structure_with_claude(items: list[tuple[int, str, str]]) -> dict:
    """Send paragraphs to Claude-Haiku and get structured section indices back."""
    payload = [{"i": i, "style": s, "text": t[:280]} for i, s, t in items]
    user = "Paragraphs:\n" + json.dumps(payload, ensure_ascii=False)

    client = _client()
    resp = client.messages.create(
        model=config.EXTRACT_MODEL,
        max_tokens=3000,
        system=_STRUCTURE_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise RuntimeError(f"Structure analyzer returned no JSON: {text[:400]}")
    return json.loads(m.group(0))


# In-memory cache: { sha256(file) -> structure dict }. Avoids re-calling
# Claude for every URL in a batch since the base resume doesn't change.
_structure_cache: dict[str, dict] = {}


def _docx_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def parse_resume_from_path(path: Path) -> ResumeStruct:
    """Parse the base resume, using AI to detect layout. Cached by file hash."""
    digest = _docx_sha256(path)
    doc = Document(str(path))
    paras = doc.paragraphs

    # Collect non-empty paragraphs with style info
    triples: list[tuple[int, str, str]] = []
    for i, p in enumerate(paras):
        text = p.text.strip()
        if text:
            triples.append((i, _style_name(p), text))
    if not triples:
        raise RuntimeError("The base resume has no text.")

    analysis = _structure_cache.get(digest)
    if analysis is None:
        try:
            analysis = _analyze_structure_with_claude(triples)
            _structure_cache[digest] = analysis
        except Exception:
            # Fallback to the legacy heuristic parser (Heading 1/Normal styles).
            analysis = _heuristic_analyze(triples)
            _structure_cache[digest] = analysis

    return _build_struct_from_analysis(paras, analysis)


def parse_resume(doc: Document) -> ResumeStruct:
    """Back-compat entry point — no cache, AI analyzes every call."""
    paras = doc.paragraphs
    triples: list[tuple[int, str, str]] = []
    for i, p in enumerate(paras):
        text = p.text.strip()
        if text:
            triples.append((i, _style_name(p), text))
    if not triples:
        raise RuntimeError("The base resume has no text.")
    try:
        analysis = _analyze_structure_with_claude(triples)
    except Exception:
        analysis = _heuristic_analyze(triples)
    return _build_struct_from_analysis(paras, analysis)


def _build_struct_from_analysis(paras: list, analysis: dict) -> ResumeStruct:
    valid_idx = {i for i in range(len(paras))}

    summary_indices = [i for i in (analysis.get("summary_indices") or []) if i in valid_idx]
    summary_idx = summary_indices[0] if summary_indices else -1
    summary_text = paras[summary_idx].text if summary_idx >= 0 else ""

    jobs: list = []
    for ja in (analysis.get("jobs") or []):
        t = ja.get("title_idx")
        b = [i for i in (ja.get("bullet_indices") or []) if i in valid_idx]
        if t is None or t not in valid_idx:
            continue
        jobs.append(JobBlock(
            title_idx=t, company_idx=-1,
            title_text=paras[t].text, company_text="",
            bullet_indices=b,
            bullets=[paras[i].text for i in b],
        ))

    skills: list = []
    for sa in (analysis.get("skills") or []):
        c = sa.get("category_idx")
        it = sa.get("items_idx")
        if c is None or it is None or c not in valid_idx or it not in valid_idx:
            continue
        skills.append(SkillBlock(
            category_idx=c, items_idx=it,
            category=paras[c].text, items=paras[it].text,
        ))

    if summary_idx < 0 and not jobs and not skills:
        raise RuntimeError(
            "Could not identify any resume sections to tailor. "
            "Make sure the resume has at least a summary, experience bullets, or skills."
        )
    return ResumeStruct(
        summary_idx=summary_idx, summary=summary_text,
        jobs=jobs, skills=skills,
    )


def _heuristic_analyze(items: list[tuple[int, str, str]]) -> dict:
    """Fallback when the AI analyzer is unavailable: style-based heuristic."""
    section = None
    summary_indices: list[int] = []
    jobs: list = []
    cur_job: Optional[dict] = None
    skills: list = []
    pending_cat: Optional[tuple[int, str]] = None

    for i, style, text in items:
        low = text.lower().strip(":").strip()
        if style == "Heading 1" or low in ("summary", "profile", "objective", "professional summary",
                                             "experience", "work experience", "professional experience",
                                             "skills", "technical skills", "core skills",
                                             "education"):
            if "summary" in low or "profile" in low or "objective" in low:
                section = "summary"
            elif "experience" in low:
                section = "experience"
                cur_job = None
            elif "skill" in low:
                section = "skills"
            elif "education" in low:
                section = "education"
            else:
                section = None
            continue

        if section == "summary":
            summary_indices.append(i)
        elif section == "experience":
            if style == "Heading 2":
                if re.search(r"\b(19|20)\d{2}\b", text) or "Present" in text:
                    cur_job = {"title_idx": i, "bullet_indices": []}
                    jobs.append(cur_job)
                elif cur_job is None:
                    cur_job = {"title_idx": i, "bullet_indices": []}
                    jobs.append(cur_job)
            elif style == "List Bullet" and cur_job:
                cur_job["bullet_indices"].append(i)
            elif text.lstrip().startswith(("•", "-", "·", "*")) and cur_job:
                cur_job["bullet_indices"].append(i)
        elif section == "skills":
            if style == "List Paragraph":
                pending_cat = (i, text)
            elif pending_cat is not None:
                skills.append({"category_idx": pending_cat[0], "items_idx": i})
                pending_cat = None
            elif ":" in text:
                skills.append({"category_idx": i, "items_idx": i})

    return {"summary_indices": summary_indices, "jobs": jobs, "skills": skills}


def set_paragraph_text(p, new_text: str) -> None:
    """Replace paragraph text, keep paragraph style + first-run formatting."""
    runs = list(p.runs)
    if not runs:
        p.add_run(new_text)
        return
    runs[0].text = new_text
    for r in runs[1:]:
        r._element.getparent().remove(r._element)


# --------------------------------------------------------------------------
# Claude calls
# --------------------------------------------------------------------------

def _client() -> Anthropic:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Edit .env and restart the server."
        )
    return Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _extract_tagged_json(text: str) -> dict:
    m = re.search(r"<json>\s*(\{.*?\})\s*</json>", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise ValueError(f"No JSON in response: {text[:400]}")


def normalize_job_info(raw: dict, url: str = "") -> dict:
    """Clean thin scrapes by asking Haiku to extract company/title/description."""
    desc = (raw.get("description") or "").strip()
    if len(desc) >= 400 and raw.get("company") and raw.get("title"):
        return raw

    client = _client()
    prompt = f"""Clean up and normalize this job posting metadata. The raw extraction may contain navigation text, boilerplate, or truncation. Preserve all actual job-description content.

URL: {url}

RAW:
{json.dumps(raw, ensure_ascii=False)[:12000]}

Return <json>{{"company": "...", "title": "...", "location": "...", "description": "..."}}</json>."""

    resp = client.messages.create(
        model=config.EXTRACT_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    txt = resp.content[0].text
    cleaned = _extract_tagged_json(txt)
    return {
        "company": cleaned.get("company") or raw.get("company", ""),
        "title": cleaned.get("title") or raw.get("title", ""),
        "location": cleaned.get("location") or raw.get("location", ""),
        "description": cleaned.get("description") or desc,
    }


TAILOR_SYSTEM = """You are an expert resume editor. Tailor the candidate's resume to a specific job posting by surfacing relevant existing experience as aggressively as the facts support — never by inventing anything.

WORKFLOW (think through internally before writing output):
1. Extract from the JD: required technologies, years of experience, domain/industry, role seniority, and the 5–7 top "must-have" keywords in the order the posting emphasizes them.
2. For each JD requirement, find the matching content in the resume. A match can be:
   - An exact match (same tech/domain word appears verbatim).
   - An adjacent match (the candidate did something equivalent — e.g. they built a "publisher dashboard" and the JD wants "content management").
   Prefer exact matches when ordering; use adjacent matches when exact ones don't exist.
3. If the JD has a hard requirement the resume doesn't support (e.g. "Strong Java" when Java appears only in skills), DO NOT fabricate. Surface whatever truthful Java-adjacent signal exists (e.g. the one bullet where Spring Boot was used) by moving it forward.
4. Rewrite the summary, reorder bullets, and reorder skill categories per the rules below.

HARD RULES — any violation invalidates the output:
1. NEVER invent technologies, companies, projects, metrics, titles, dates, or responsibilities not already present.
2. Preserve EXACTLY the same number of bullets per job. Same number of skill categories.
3. Preserve every metric (percentages, latencies, team sizes, user counts, revenue) verbatim. You may move them; you cannot change or remove them.
4. Preserve every tech-stack term, company name, and product name that appears in a bullet. Rewording the verbs and structure is allowed; the nouns that carry facts are NOT.
5. Third-person / action-verb voice throughout. No "I", "we", "my", "our".
6. Do NOT mention the target company or target job title inside the resume body.
7. Keep the output grounded in the input's truth. Paraphrasing is fine; shifting the claim is not.

SUMMARY (3–5 sentences, ~60–110 words, matches input length ±20%):
- Sentence 1: years of experience + role identity + DOMAIN signal that matches the JD (pull the JD's domain word when possible, e.g. "fintech", "healthtech", "developer tools", "e-commerce").
- Sentence 2: 2–3 of the JD's top required technologies that the candidate actually has, with a real employer or project as proof ("shipped X at Walmart", not "worked with X").
- Sentence 3: most relevant current/recent work with scope (users / scale / latency / team).
- Optional sentence 4: leadership / cross-functional / team-size signal, if the JD values it and the candidate has it.
- Do NOT use filler ("passionate about...", "proven ability to..."). Every sentence must add a concrete fact.

BULLETS — reorder and reword:
- Reorder each job's bullets by JD-relevance: highest-relevance bullet first.
- Rewording should be BOLDER than "synonym swap". If JD language fits and the fact supports it:
  - Shift the verb ("built" → "shipped", "designed" → "architected", "developed" → "engineered") when it changes emphasis.
  - Promote the JD-relevant noun earlier in the sentence.
  - Collapse weak connectives; lead with the outcome.
- You MAY NOT: add a new technology, change a metric, swap the employer, or claim a different scope.

SKILLS:
- Reorder categories so the most JD-relevant ones come first.
- Within a category, reorder items so the JD-relevant ones lead.
- You MAY slightly rename a category label to match common vocabulary (e.g. "Cloud / DevOps" → "Cloud & Infrastructure") if it aids scannability.

OUTPUT FORMAT — emit ONLY the XML below, nothing else. No prose, no markdown, no JSON, no explanation. Include a section only if the corresponding section was present in the input.

<summary>Your rewritten summary here.</summary>           ← only if the input had a <summary>

<job index="0">
  <b>First bullet for job 0 (highest JD-relevance)</b>
  <b>Second bullet for job 0</b>
  ... (exactly the same number of <b> tags as the input had for this job) ...
</job>
<job index="1">
  ...
</job>
... (one <job> block per input job, in input order by index) ...

<skill><category>Category name</category><items>item1, item2, item3</items></skill>
... (one <skill> block per input category, in your chosen order) ...

XML RULES:
- Straight ASCII double-quotes for attributes.
- Do NOT HTML-escape text inside <b>, <category>, <items>, <summary> — emit the final text as it should appear in the resume.
- <job index="N"> MUST match the input job_index exactly.
- No nested tags inside <b>, <category>, <items>, or <summary>."""



def tailor_resume(resume: ResumeStruct, job: dict) -> dict:
    client = _client()

    input_parts: list[str] = []
    if resume.has_summary:
        input_parts += [f"<summary>{_xml_escape(resume.summary.strip())}</summary>", ""]
    for i, j in enumerate(resume.jobs):
        input_parts.append(
            f'<job index="{i}" title="{_xml_escape(j.title_text.strip())}" '
            f'bullet_count="{len(j.bullets)}">'
        )
        for b in j.bullets:
            input_parts.append(f"  <b>{_xml_escape(b.strip())}</b>")
        input_parts.append("</job>")
    if resume.jobs:
        input_parts.append("")
    for s in resume.skills:
        input_parts.append(
            f"<skill><category>{_xml_escape(s.category.strip())}</category>"
            f"<items>{_xml_escape(s.items.strip())}</items></skill>"
        )
    resume_xml = "\n".join(input_parts)

    user_msg = [
        {
            "type": "text",
            "text": "Candidate resume:\n<resume>\n" + resume_xml + "\n</resume>",
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": (
                "Target job posting:\n<jd>\n"
                f"Company: {job.get('company','')}\n"
                f"Title: {job.get('title','')}\n"
                f"Location: {job.get('location','')}\n\n"
                f"Description:\n{(job.get('description') or '')[:15000]}\n"
                "</jd>\n\n"
                "Before writing the output, silently work through these steps "
                "(do NOT include them in the output):\n"
                "  1) List the JD's top 5-7 must-have requirements in priority order.\n"
                "  2) For each, decide if the resume has an exact match, an adjacent match, or no support.\n"
                "  3) Decide the summary's domain word from the JD.\n"
                "  4) Rank each job's bullets by relevance before writing.\n"
                "Then emit ONLY the XML format from the system prompt. "
                "Be bold in rewording while staying 100% truthful to the input facts."
            ),
        },
    ]

    resp = client.messages.create(
        model=config.TAILOR_MODEL,
        max_tokens=4000,
        temperature=0,
        system=TAILOR_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(
        b.text for b in resp.content if getattr(b, "type", None) == "text"
    )
    out = _parse_xml_output(text, resume)
    _validate_tailored(out, resume)
    return out


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def _xml_unescape(s: str) -> str:
    return (
        s.replace("&quot;", '"')
         .replace("&lt;", "<")
         .replace("&gt;", ">")
         .replace("&amp;", "&")
    )


def _parse_xml_output(text: str, resume: ResumeStruct) -> dict:
    """Parse the model's XML response into the canonical dict."""
    summary_m = re.search(r"<summary>(.*?)</summary>", text, re.DOTALL)
    summary = _xml_unescape(summary_m.group(1).strip()) if summary_m else ""

    jobs_by_index: dict = {}
    for m in re.finditer(
        r'<job[^>]*\bindex="(\d+)"[^>]*>(.*?)</job>', text, re.DOTALL
    ):
        idx = int(m.group(1))
        body = m.group(2)
        bullets = [
            _xml_unescape(b.strip())
            for b in re.findall(r"<b>(.*?)</b>", body, re.DOTALL)
        ]
        jobs_by_index[idx] = bullets
    bullets_per_job = [jobs_by_index.get(i, []) for i in range(len(resume.jobs))]

    skill_cats: list = []
    skill_items: list = []
    for m in re.finditer(
        r"<skill>\s*<category>(.*?)</category>\s*<items>(.*?)</items>\s*</skill>",
        text,
        re.DOTALL,
    ):
        skill_cats.append(_xml_unescape(m.group(1).strip()))
        skill_items.append(_xml_unescape(m.group(2).strip()))

    return {
        "summary": summary,
        "bullets": bullets_per_job,
        "skill_categories": skill_cats,
        "skill_items": skill_items,
    }


def _validate_tailored(out: dict, resume: ResumeStruct) -> None:
    if resume.has_summary:
        if not isinstance(out.get("summary"), str) or not out["summary"].strip():
            raise ValueError("Tailored output missing summary.")

    bullets = out.get("bullets")
    if not isinstance(bullets, list) or len(bullets) != len(resume.jobs):
        raise ValueError(
            f"'bullets' must be a list of {len(resume.jobs)} inner lists."
        )
    for i, (inner, rj) in enumerate(zip(bullets, resume.jobs)):
        if not isinstance(inner, list) or len(inner) != len(rj.bullets):
            raise ValueError(
                f"bullets[{i}] must have {len(rj.bullets)} strings."
            )

    if resume.skills:
        sc = out.get("skill_categories")
        si = out.get("skill_items")
        if not isinstance(sc, list) or len(sc) != len(resume.skills):
            raise ValueError(
                f"'skill_categories' must be a list of {len(resume.skills)} strings."
            )
        if not isinstance(si, list) or len(si) != len(resume.skills):
            raise ValueError(
                f"'skill_items' must be a list of {len(resume.skills)} strings."
            )


def apply_tailoring(
    src_docx: Path, resume: ResumeStruct, tailored: dict, dst_docx: Path
) -> None:
    doc = Document(str(src_docx))
    paras = doc.paragraphs

    if resume.has_summary and tailored.get("summary", "").strip():
        set_paragraph_text(paras[resume.summary_idx], tailored["summary"].strip())

    for job, inner_bullets in zip(resume.jobs, tailored.get("bullets", [])):
        for idx, new_bullet in zip(job.bullet_indices, inner_bullets):
            set_paragraph_text(paras[idx], new_bullet.strip())

    if resume.skills:
        for skill, cat, items in zip(
            resume.skills,
            tailored.get("skill_categories", []),
            tailored.get("skill_items", []),
        ):
            set_paragraph_text(paras[skill.category_idx], cat.strip())
            set_paragraph_text(paras[skill.items_idx], items.strip())

    dst_docx.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst_docx))
