"""Resume parsing + Claude-powered tailoring + docx writing."""
from __future__ import annotations

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
    summary_idx: int
    summary: str
    jobs: list
    skills: list


def _style_name(p) -> str:
    try:
        return p.style.name or ""
    except Exception:
        return ""


def parse_resume(doc: Document) -> ResumeStruct:
    paras = doc.paragraphs
    summary_idx: Optional[int] = None
    summary_text = ""
    jobs: list = []
    skills: list = []

    section = None
    current_job: Optional[JobBlock] = None
    pending_skill_cat: Optional[tuple] = None

    for i, p in enumerate(paras):
        style = _style_name(p)
        raw = p.text
        text = raw.strip()
        if not text:
            continue

        if style == "Heading 1":
            low = text.lower()
            if "summary" in low:
                section = "summary"
            elif "experience" in low:
                section = "experience"
            elif "skill" in low:
                section = "skills"
            elif "education" in low:
                section = "education"
            else:
                section = None
            continue

        if section == "summary" and style == "Normal" and summary_idx is None:
            summary_idx = i
            summary_text = raw

        elif section == "experience":
            if style == "Heading 2":
                if re.search(r"\b(19|20)\d{2}\b", text) or "Present" in text:
                    current_job = JobBlock(
                        title_idx=i, company_idx=-1,
                        title_text=raw, company_text="",
                    )
                    jobs.append(current_job)
                elif current_job and current_job.company_idx == -1:
                    current_job.company_idx = i
                    current_job.company_text = raw
            elif style == "List Bullet" and current_job:
                current_job.bullet_indices.append(i)
                current_job.bullets.append(raw)

        elif section == "skills":
            if style == "List Paragraph":
                pending_skill_cat = (i, raw)
            elif style == "Normal" and pending_skill_cat:
                cat_i, cat_text = pending_skill_cat
                skills.append(SkillBlock(
                    category_idx=cat_i, items_idx=i,
                    category=cat_text, items=raw,
                ))
                pending_skill_cat = None

    if summary_idx is None:
        raise RuntimeError("Could not locate a Summary section in the resume.")

    return ResumeStruct(
        summary_idx=summary_idx, summary=summary_text,
        jobs=jobs, skills=skills,
    )


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


TAILOR_SYSTEM = """You are an expert resume editor. You will tailor a candidate's resume to a specific job posting without fabricating anything.

HARD RULES — violating any of these invalidates the output:
1. NEVER invent technologies, companies, projects, metrics, titles, dates, or responsibilities that are not already present in the candidate's resume. Only rewording and reordering are allowed.
2. Preserve the EXACT number of bullets for each job. Do not add or drop bullets.
3. Preserve the EXACT number of skill categories and do not drop any of them. You may reorder items inside a category and reword a category label slightly, but do not add items that are not already listed for the candidate.
4. Every bullet must stay TRUE to the original fact: same employer, same tech stack, same outcome, same order of magnitude for metrics. Surface-level rewording only.
5. Keep the candidate's existing action-verb / third-person style. Do not use "I" or "we".

TAILORING OBJECTIVES:
- Rewrite the Summary (3–5 sentences) to front-load the experience most relevant to the target role. Keep total length close to the original.
- Reorder bullets within each job so the most JD-relevant bullet comes first.
- Subtly reword bullets to surface JD keywords WHEN TRUTHFUL.
- Reorder skill categories so the most JD-relevant ones come first.
- Do not mention the target company or job title inside the resume body.

OUTPUT FORMAT — emit ONLY the XML below, nothing else. No JSON, no markdown, no commentary.

<summary>Your rewritten summary here.</summary>

<job index="0">
  <b>First bullet for job 0</b>
  <b>Second bullet for job 0</b>
  ... (exactly the same number of <b> tags as the input had for this job) ...
</job>
<job index="1">
  ...
</job>
... (one <job> block per input job, in input order) ...

<skill><category>Category name</category><items>item1, item2, item3</items></skill>
... (one <skill> block per input category, in your chosen order) ...

Rules for the XML:
- Use straight ASCII double-quotes for attributes.
- Do NOT escape characters inside tags — write bullets exactly as they should appear in the final resume.
- Every <b>...</b> must be on its own line (or contiguous) — no nested tags.
- <job index="N"> MUST match the input job_index exactly."""



def tailor_resume(resume: ResumeStruct, job: dict) -> dict:
    client = _client()

    # Build the input as readable XML so Claude mirrors the output format.
    input_parts = [f"<summary>{resume.summary.strip()}</summary>", ""]
    for i, j in enumerate(resume.jobs):
        input_parts.append(
            f'<job index="{i}" title="{_xml_escape(j.title_text.strip())}" '
            f'bullet_count="{len(j.bullets)}">'
        )
        for b in j.bullets:
            input_parts.append(f"  <b>{_xml_escape(b.strip())}</b>")
        input_parts.append("</job>")
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
                "Produce the tailored resume now, emitting ONLY the XML format "
                "specified in the system prompt."
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

    # Jobs — find each <job index="N">...</job> block and its bullets.
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

    # Skills — keep order as emitted.
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
    if not isinstance(out.get("summary"), str) or not out["summary"].strip():
        raise ValueError("Tailored output missing summary.")

    bullets = out.get("bullets")
    if not isinstance(bullets, list) or len(bullets) != len(resume.jobs):
        raise ValueError(
            f"'bullets' must be a list of {len(resume.jobs)} inner lists, "
            f"got type={type(bullets).__name__} len={len(bullets) if isinstance(bullets, list) else 'n/a'}."
        )
    for i, (inner, rj) in enumerate(zip(bullets, resume.jobs)):
        if not isinstance(inner, list) or len(inner) != len(rj.bullets):
            raise ValueError(
                f"bullets[{i}] must have {len(rj.bullets)} strings, "
                f"got type={type(inner).__name__} "
                f"len={len(inner) if isinstance(inner, list) else 'n/a'}."
            )

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

    set_paragraph_text(paras[resume.summary_idx], tailored["summary"].strip())

    for job, inner_bullets in zip(resume.jobs, tailored["bullets"]):
        for idx, new_bullet in zip(job.bullet_indices, inner_bullets):
            set_paragraph_text(paras[idx], new_bullet.strip())

    for skill, cat, items in zip(
        resume.skills, tailored["skill_categories"], tailored["skill_items"]
    ):
        set_paragraph_text(paras[skill.category_idx], cat.strip())
        set_paragraph_text(paras[skill.items_idx], items.strip())

    dst_docx.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst_docx))

