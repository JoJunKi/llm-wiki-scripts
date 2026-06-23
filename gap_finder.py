"""
gap_finder.py
topic별 논문 brief를 분석해서 Research Gap을 찾아 gaps/ 폴더에 저장.

실행:
  python gap_finder.py              # 모든 topic 분석
  python gap_finder.py --topic "Diffusion Models"  # 특정 topic만
  python gap_finder.py --dry        # Claude 호출 없이 논문 목록만 출력
"""
import re
import sys
import io
import json
import subprocess
import ollama
from pathlib import Path
from datetime import date
from config import VAULT_PATH, OLLAMA_MODEL

# Windows cp949 콘솔 UTF-8 강제
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

VAULT = Path(VAULT_PATH)
TOPICS_DIR = VAULT / "topics"
BRIEF_DIR  = VAULT / "papers" / "brief"
GAPS_DIR   = VAULT / "gaps"

DRY_RUN    = "--dry"   in sys.argv
TOPIC_ARG  = None
if "--topic" in sys.argv:
    idx = sys.argv.index("--topic")
    if idx + 1 < len(sys.argv):
        TOPIC_ARG = sys.argv[idx + 1]


def log(msg: str):
    print(msg, flush=True)


# ── brief 파일 섹션 추출 ─────────────────────────────────────────

SECTION_RE = re.compile(r'^#{1,3}\s+(.+)', re.MULTILINE)

def extract_brief_sections(brief_path: Path) -> dict:
    """brief.md에서 핵심 섹션들을 추출"""
    text = brief_path.read_text(encoding="utf-8", errors="ignore")
    sections = {}

    # frontmatter에서 title, year 추출
    fm_title = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', text, re.MULTILINE)
    fm_year  = re.search(r'^year:\s*(\d+)', text, re.MULTILINE)
    sections["title"] = fm_title.group(1).strip() if fm_title else brief_path.stem
    sections["year"]  = fm_year.group(1) if fm_year else ""
    sections["stem"]  = brief_path.stem

    # 마크다운 섹션별 내용 추출
    target_sections = {
        "한 줄 요약": "summary",
        "핵심 기여": "contributions",
        "한계점": "limitations",
        "연구 활용 가능성": "potential",
    }
    headers = [(m.start(), m.group(1)) for m in SECTION_RE.finditer(text)]
    for i, (pos, header) in enumerate(headers):
        for ko, key in target_sections.items():
            if ko in header:
                end = headers[i+1][0] if i+1 < len(headers) else len(text)
                content = text[pos:end].strip()
                # 헤더 줄 제거
                content = "\n".join(content.split("\n")[1:]).strip()
                sections[key] = content[:600]  # 너무 길면 자름
    return sections


# ── topic MOC에서 논문 목록 파싱 ─────────────────────────────────

def get_papers_for_topic(topic_path: Path) -> list[Path]:
    """MOC 파일에서 [[링크]] 파싱 → 실제 brief 파일 경로 반환"""
    text = topic_path.read_text(encoding="utf-8", errors="ignore")
    links = re.findall(r'\[\[([^\]|]+)\]\]', text)
    paths = []
    for link in links:
        stem = link.strip()
        p = BRIEF_DIR / f"{stem}.md"
        if p.exists():
            paths.append(p)
    return paths


# ── Ollama: 논문 목록 압축 (논문 많을 때) ───────────────────────

def compress_one_paper(p: dict, idx: int, total: int) -> str:
    """논문 한 편을 Ollama로 압축"""
    title_short = p['title'][:50]
    log(f"  [{idx}/{total}] {title_short}...")

    prompt = f"""Summarize this paper in 3-4 Korean sentences. Focus on: method, key result, limitation.
Output ONLY the summary in Korean. No title, no label.

Title: {p['title']} ({p['year']})
Summary: {p.get('summary', '')}
Contributions: {p.get('contributions', '')}
Limitations: {p.get('limitations', '')}
Potential: {p.get('potential', '')}
"""
    resp = ollama.chat(model=OLLAMA_MODEL, messages=[{"role": "user", "content": prompt}])
    return resp["message"]["content"].strip()


def compress_papers_ollama(papers_info: list[dict], topic: str) -> str:
    """논문별로 개별 Ollama 호출 → 진행률 표시 + 압축 요약"""
    total = len(papers_info)
    compressed = []
    for i, p in enumerate(papers_info, 1):
        summary = compress_one_paper(p, i, total)
        compressed.append(f"[{p['year']}] {p['title']}\n{summary}")
    return "\n\n".join(compressed)


# ── Claude CLI: gap 분석 ─────────────────────────────────────────

GAP_PROMPT = """당신은 학술 연구 분석 전문가입니다.
아래는 '{topic}' 분야의 논문 {count}편에 대한 요약입니다.
이 논문들을 분석하여 Research Gap을 찾아주세요.

## 논문 요약
{papers_summary}

## 출력 형식 (Obsidian 마크다운, 한국어)

---
type: gap
topic: "{topic}"
papers_analyzed: {count}
date_created: {today}
---

# Research Gap: {topic}

## 분석 논문 ({count}편)
{paper_list}

## 현재 연구 현황
(이 분야 논문들이 공통적으로 집중하는 문제와 접근법을 3-5문장으로 서술)

## 발견된 Research Gap

### Gap 1: (제목)
(설명: 어떤 부분이 다뤄지지 않았는가, 왜 중요한가)

### Gap 2: (제목)
(설명)

### Gap 3: (제목)
(설명)

## 제안 가능한 연구 방향
1. **연구 방향 1**: (구체적인 연구 아이디어)
2. **연구 방향 2**: (구체적인 연구 아이디어)
3. **연구 방향 3**: (구체적인 연구 아이디어)

## 주목할 만한 연구 조합
(두 편 이상의 논문을 결합하면 가능한 새로운 연구를 1-3개 제시)
예: [[논문A]]의 방법 + [[논문B]]의 데이터셋 → 새로운 가능성

출력 규칙:
- 마크다운 본문만 출력. 설명이나 코드 펜스 금지.
- frontmatter ---로 시작.
- 모든 내용 한국어.
- 논문 링크는 [[papers/brief/파일명]] 형식 사용.
"""


def call_claude_gap(topic: str, papers_info: list[dict], papers_summary: str) -> str:
    paper_list = "\n".join([
        f"- [[papers/brief/{p['stem']}]] ({p['year']}) — {p.get('summary','').split(chr(10))[0][:80]}"
        for p in papers_info
    ])
    today = date.today().isoformat()

    prompt = GAP_PROMPT.format(
        topic=topic,
        count=len(papers_info),
        papers_summary=papers_summary,
        paper_list=paper_list,
        today=today,
    )
    prompt = (
        "Research Gap 분석을 수행합니다. frontmatter ---로 시작하는 마크다운만 출력하세요.\n\n"
        + prompt
    )

    log(f"  [Claude CLI] '{topic}' gap 분석 중...")
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            ["claude", "-p", "--model", "sonnet"],
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=300,
            cwd=tmpdir,
        )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))

    raw = result.stdout.decode("utf-8", errors="replace").strip()
    if raw.startswith("```"):
        lines = raw.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw


# ── 저장 ────────────────────────────────────────────────────────

def save_gap(topic: str, content: str):
    GAPS_DIR.mkdir(parents=True, exist_ok=True)
    safe = topic.replace(" ", "_").replace("/", "-")
    path = GAPS_DIR / f"Gap_{safe}.md"
    path.write_text(content, encoding="utf-8")
    log(f"  저장: {path}")


# ── 메인 ────────────────────────────────────────────────────────

def analyze_topic(topic_path: Path):
    topic = topic_path.stem
    log(f"\n{'='*60}")
    log(f"Topic: {topic}")

    papers = get_papers_for_topic(topic_path)
    log(f"  논문 수: {len(papers)}편")
    if len(papers) < 2:
        log("  → 논문이 2편 미만, 건너뜀")
        return

    papers_info = [extract_brief_sections(p) for p in papers]

    if DRY_RUN:
        log("  [DRY] 논문 목록:")
        for p in papers_info:
            log(f"    - [{p['year']}] {p['title'][:60]}")
        return

    # 논문이 많으면 Ollama로 먼저 압축
    if len(papers_info) > 8:
        log(f"  [Ollama] {len(papers_info)}편 압축 중...")
        papers_summary = compress_papers_ollama(papers_info, topic)
    else:
        # 적으면 그냥 직접 텍스트로 조합
        papers_summary = "\n\n".join([
            f"[{p['year']}] {p['title']}\n"
            f"요약: {p.get('summary', '').strip()}\n"
            f"기여: {p.get('contributions', '').strip()}\n"
            f"한계: {p.get('limitations', '').strip()}\n"
            f"활용: {p.get('potential', '').strip()}"
            for p in papers_info
        ])

    gap_content = call_claude_gap(topic, papers_info, papers_summary)
    save_gap(topic, gap_content)


def main():
    topic_files = sorted(TOPICS_DIR.glob("*.md"))
    if not topic_files:
        log("topics/ 폴더에 MOC 파일이 없습니다.")
        sys.exit(1)

    if TOPIC_ARG:
        topic_files = [t for t in topic_files if TOPIC_ARG.lower() in t.stem.lower()]
        if not topic_files:
            log(f"'{TOPIC_ARG}'와 일치하는 topic이 없습니다.")
            sys.exit(1)

    log(f"분석할 topic: {[t.stem for t in topic_files]}")
    for tf in topic_files:
        try:
            analyze_topic(tf)
        except Exception as e:
            log(f"  [ERROR] {e}")

    log(f"\n{'='*60}")
    log(f"완료. gaps/ 폴더를 확인하세요: {GAPS_DIR}")


if __name__ == "__main__":
    main()
