"""
ollama_processor.py
역할: PDF 텍스트 추출 + 실제 목차 구조 보존 + 섹션별 Ollama 요약
"""
import re
import pymupdf4llm
import ollama
import json
import sys
import os
from pathlib import Path


def log(msg: str):
    print(msg, file=sys.stderr, flush=True)


def extract_text_from_pdf(pdf_path: str) -> str:
    log(f"[PDF] 텍스트 추출 중: {pdf_path}")
    saved_stdout_fd = os.dup(1)
    try:
        os.dup2(2, 1)
        result = pymupdf4llm.to_markdown(pdf_path)
    finally:
        os.dup2(saved_stdout_fd, 1)
        os.close(saved_stdout_fd)
    return result


# ── 메타데이터 추출 ───────────────────────────────────────────────

def _extract_title_from_header(text: str) -> str | None:
    """PDF 앞 2000자에서 제목 정규식 추출."""
    header = text[:2000]
    for pattern in [
        r"^#\s+\**(.+?)\**\s*$",                      # # 제목 or # **제목**
        r"^\*\*(.{10,}?)\*\*\s*$",                     # **제목**
        r"^([A-Z][A-Za-z0-9 :,\-–]{15,})\s*$",        # ALL CAPS 또는 첫 글자 대문자 긴 줄
    ]:
        for line in header.split("\n"):
            line = line.strip()
            m = re.match(pattern, line, re.IGNORECASE)
            if m:
                title = m.group(1).strip().strip("*").strip()
                if len(title) > 10:
                    return title
    return None


def _extract_year_from_header(text: str) -> int | None:
    """논문 앞 1500자에서 발행연도 정규식 추출."""
    header = text[:1500]
    date_pattern = re.compile(
        r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?'
        r'|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
        r'\s+(20[12]\d)\b'
        r'|©\s*(20[12]\d)'
        r'|\b(20[12]\d)\b(?!\s*[)\]])',
        re.IGNORECASE,
    )
    for m in date_pattern.finditer(header):
        year_str = m.group(1) or m.group(2) or m.group(3)
        if year_str:
            return int(year_str)
    return None


def extract_metadata(text: str, model: str, pdf_path: str = "") -> dict:
    log(f"[Ollama:{model}] 메타데이터 추출 중...")
    regex_year = _extract_year_from_header(text)

    prompt = f"""Extract metadata from the academic paper below.
Reply with JSON only. No other text.
IMPORTANT: "year" must be the paper's own publication year near the title — NOT from citations.

{{
  "title": "paper title",
  "authors": ["Author1", "Author2"],
  "year": 2024,
  "journal": "journal or conference name, or empty string",
  "keywords": ["keyword1", "keyword2", "keyword3"],
  "domain": "research domain"
}}

Paper text (header):
{text[:3000]}
"""
    response = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
    try:
        raw = response['message']['content'].strip()
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()
        meta = json.loads(raw)
    except Exception:
        meta = {"title": "", "authors": [], "year": 0,
                "journal": "", "keywords": [], "domain": ""}

    # ── 제목 보정 3단계 ──
    if not meta.get("title") or "실패" in str(meta.get("title", "")):
        # 1) 정규식 헤더 추출
        fallback = _extract_title_from_header(text)
        if fallback:
            log(f"  [제목 보정] regex: {fallback[:60]}")
            meta["title"] = fallback
        elif pdf_path:
            # 2) PDF 파일명 → Title Case
            stem = Path(pdf_path).stem
            fallback = stem.replace("_", " ").replace("-", " ")
            # 전체 대문자면 Title Case로 변환
            if fallback == fallback.upper():
                fallback = fallback.title()
            log(f"  [제목 보정] 파일명: {fallback[:60]}")
            meta["title"] = fallback

    # ── 연도 보정 ──
    if regex_year:
        if meta.get("year") != regex_year:
            log(f"  [연도 보정] Ollama:{meta.get('year')} → regex:{regex_year}")
        meta["year"] = regex_year

    return meta


# ── 섹션 파싱: 실제 목차 구조 그대로 보존 ────────────────────────

# 처리 제외 섹션 (참고문헌, 감사의 글 등)
SKIP_HEADERS = {
    "references", "bibliography", "acknowledgments", "acknowledgements",
    "appendix", "about the authors", "author contributions",
    "conflict of interest", "funding", "declaration",
}


def split_sections(text: str, model: str = None) -> list[dict]:
    """
    마크다운 헤더를 파싱해서 실제 목차 구조를 보존.
    레벨 1-2 헤더 = 최상위 섹션 경계.
    레벨 3-4 헤더 = 상위 섹션 내용에 포함 (subsection).
    반환: [{"header": str, "content": str}, ...]
    """
    log("[Parser] 목차 구조 파싱 중...")
    header_re = re.compile(r'^(#{1,4})\s+(.+)', re.MULTILINE)

    # 논문 섹션으로 인정할 헤더인지 판단
    SECTION_KEYWORDS = {
        "abstract", "introduction", "related", "background", "preliminary",
        "method", "approach", "model", "framework", "proposed",
        "experiment", "evaluation", "result", "discussion", "analysis",
        "conclusion", "future", "limitation", "summary",
    }

    def is_valid_section(header_text: str) -> bool:
        clean = re.sub(r'[\*_`#]', '', header_text).strip()
        clean_lower = re.sub(r'^\d+[\.\d]*\s*', '', clean).strip().lower()
        # 숫자로 시작하는 섹션 (1. Introduction, 2.1 Method 등)
        if re.match(r'^\d', clean):
            return True
        # 알려진 섹션 키워드
        if any(clean_lower.startswith(kw) for kw in SECTION_KEYWORDS):
            return True
        return False

    def is_skip_section(header_text: str) -> bool:
        clean = re.sub(r'[\*_`#]', '', header_text).strip()
        clean_lower = re.sub(r'^\d+[\.\d]*\s*', '', clean).strip().lower()
        return any(clean_lower.startswith(s) for s in SKIP_HEADERS)

    lines = text.split('\n')
    sections: list[dict] = []
    current_header: str | None = None
    buffer: list[str] = []
    first_section_found = False  # 첫 유효 섹션 전까지 (제목/저자 등) 무시

    def flush():
        if current_header is not None:
            content = '\n'.join(buffer).strip()
            if content and len(content) > 80:
                sections.append({"header": current_header, "content": content})

    for line in lines:
        m = header_re.match(line)
        if m:
            level = len(m.group(1))
            header_text = m.group(2).strip()

            if level <= 2:
                if is_skip_section(header_text):
                    flush()
                    current_header = None
                    buffer = []
                elif is_valid_section(header_text):
                    flush()
                    current_header = header_text
                    buffer = [line]
                    first_section_found = True
                else:
                    # 논문 제목 등 비섹션 헤더 → 첫 유효 섹션 전이면 무시
                    if not first_section_found:
                        flush()
                        current_header = None
                        buffer = []
                    # 첫 유효 섹션 이후라면 현재 섹션 내용에 포함
                    elif current_header is not None:
                        buffer.append(line)
            else:
                # 서브섹션 → 현재 섹션 내용에 포함
                if current_header is not None:
                    buffer.append(line)
        else:
            if current_header is not None:
                buffer.append(line)

    flush()
    log(f"  → {len(sections)}개 섹션 파싱: {[s['header'] for s in sections]}")
    return sections


# ── 섹션별 Ollama 호출 ────────────────────────────────────────────

CHUNK_SIZE = 4000


def _chunk_text(text: str) -> list[str]:
    if len(text) <= CHUNK_SIZE:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + CHUNK_SIZE])
        start += CHUNK_SIZE
    return chunks


def _summarize_chunk(header: str, chunk: str, idx: int, total: int, model: str) -> str:
    prompt = f"""Summarize part {idx}/{total} of section "{header}" from an academic paper.
Write 5-8 sentences. ALL output MUST be in Korean (한국어).

{chunk}
"""
    resp = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
    return resp["message"]["content"].strip()


ABSTRACT_RE = re.compile(r'abstract', re.IGNORECASE)


def _call_section_ollama(header: str, content: str, model: str) -> str:
    """섹션 하나를 Ollama로 분석 → 실제 소절 기반 테이블 + Insight"""
    from prompts import OLLAMA_SECTION_PROMPT, OLLAMA_ABSTRACT_PROMPT

    # 긴 섹션은 먼저 청크 요약
    chunks = _chunk_text(content)
    if len(chunks) > 1:
        log(f"    청킹 {len(chunks)}개...")
        parts = [_summarize_chunk(header, c, i+1, len(chunks), model) for i, c in enumerate(chunks)]
        content = '\n\n'.join(parts)

    # Abstract는 별도 프롬프트 (bullet 형식)
    if ABSTRACT_RE.search(header):
        prompt = OLLAMA_ABSTRACT_PROMPT.format(section_text=content)
    else:
        prompt = OLLAMA_SECTION_PROMPT.format(
            section_header=header,
            section_text=content,
        )
    log(f"  [Ollama:{model}] '{header}' 분석 중...")
    resp = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
    raw = resp["message"]["content"].strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        if raw.strip().endswith("```"):
            raw = raw[:raw.rfind("```")].strip()
    return raw


# ── detailed 마크다운 조립 ────────────────────────────────────────

def _make_filename_noext(metadata: dict) -> str:
    title = metadata.get("title", "paper")
    year = metadata.get("year", 0)
    clean = "".join(c for c in title if c.isalnum() or c in " _-")
    clean = clean.strip().replace(" ", "_")[:50]
    return f"{year}_{clean}"


def generate_detailed_summary(metadata: dict, sections: list[dict], model: str) -> str:
    """섹션마다 Ollama 개별 호출 → 조립해서 detailed 마크다운 반환"""
    from datetime import date

    filename_noext = _make_filename_noext(metadata)
    today = date.today().isoformat()
    tags = list(metadata.get("keywords", [])) + [metadata.get("domain", "")]
    source_pdf = metadata.get("source_pdf", "")
    source_pdf_uri = source_pdf.replace("\\", "/").replace(" ", "%20") if source_pdf else ""

    source_pdf_line = f'source_pdf: "{source_pdf}"' if source_pdf else ""
    source_pdf_link = (
        f'\n> 📄 원본 PDF: [열기](file:///{source_pdf_uri})'
        if source_pdf else ""
    )

    frontmatter = f"""---
title: "{metadata.get('title', '')}"
authors: {metadata.get('authors', [])}
year: {metadata.get('year', '')}
journal: "{metadata.get('journal', '')}"
keywords: {metadata.get('keywords', [])}
tags: {tags}
date_added: {today}
brief: "[[papers/brief/{filename_noext}]]"
{source_pdf_line}
---

> 개념·논문 연결은 [[papers/brief/{filename_noext}|brief 요약본]] 참고{source_pdf_link}
"""

    # 섹션별 Ollama 호출
    section_blocks = []
    for sec in sections:
        block = _call_section_ollama(sec["header"], sec["content"], model)
        section_blocks.append(block)

    separator = "\n\n---\n\n"
    body = separator.join(section_blocks)
    footer = f"\n\n---\n\n> 관련 논문·개념 연결은 [[papers/brief/{filename_noext}|brief 요약본]]에서 확인하세요."

    return frontmatter + "\n" + body + footer


# ── 메인 파이프라인 ───────────────────────────────────────────────

def preprocess_paper(pdf_path: str, model: str) -> dict:
    from config import VAULT_PATH
    text = extract_text_from_pdf(pdf_path)
    metadata = extract_metadata(text, model, pdf_path=pdf_path)

    # archive 경로를 미리 계산해서 metadata에 주입 (detailed frontmatter용)
    archive_path = Path(VAULT_PATH).parent / "_archive" / Path(pdf_path).name
    metadata["source_pdf"] = archive_path.as_posix()

    sections = split_sections(text)
    detailed_markdown = generate_detailed_summary(metadata, sections, model)
    return {
        "raw_text": text,
        "metadata": metadata,
        "sections": sections,
        "pdf_path": pdf_path,
        "detailed_markdown": detailed_markdown,
    }


if __name__ == "__main__":
    from config import OLLAMA_MODEL
    if len(sys.argv) < 2:
        sys.stdout.buffer.write("사용법: python ollama_processor.py <pdf_경로>\n".encode("utf-8"))
        sys.exit(1)
    result = preprocess_paper(sys.argv[1], OLLAMA_MODEL)
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
