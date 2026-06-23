"""
connect_vault.py
Vault 전체를 스캔해서 [[링크]] 연결을 완성한다.

실행:
  python connect_vault.py          # 스캔 + 개념 스텁 생성
  python connect_vault.py --dry    # 변경 없이 결과만 출력
  python connect_vault.py --enrich # 빈 concept 스텁을 Ollama로 채우기
"""
import re
import sys
import ollama
from pathlib import Path
from normalize_vault import normalize_concept_name
from config import VAULT_PATH, OLLAMA_MODEL

VAULT = Path(VAULT_PATH)

SCAN_DIRS = [
    "papers/brief",
    "concepts",
    "topics",
    "sessions",
    "gaps",
    "study-logs",
    "writing",
    "journals",
    "my_notes",
]

DRY_RUN  = "--dry"    in sys.argv
ENRICH   = "--enrich" in sys.argv

# 개념으로 만들면 안 되는 링크 패턴
PAPER_RE   = re.compile(r"^\d{4}_")          # 2024_DIFFUSION-TS...
SESSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_")  # 2026-06-07_세션...


def log(msg: str):
    print(msg, flush=True)


def collect_all_md() -> list[Path]:
    files = []
    for sub in SCAN_DIRS:
        d = VAULT / sub
        if d.exists():
            files.extend(p for p in d.glob("*.md") if not p.name.startswith("_"))
    return files


def extract_concept_links(text: str) -> list[str]:
    """[[Concept]] 링크 중 순수 개념명만 추출 (경로 포함·연도 prefix 제외)"""
    raw = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", text)
    result = []
    for l in raw:
        l = l.strip()
        if "/" in l:          # [[papers/brief/...]] 등 경로 포함 → 스킵
            continue
        if PAPER_RE.match(l): # 논문 파일명
            continue
        if SESSION_RE.match(l):  # 세션 파일명
            continue
        result.append(normalize_concept_name(l))
    return result


def get_topic_names() -> set[str]:
    d = VAULT / "topics"
    return {p.stem for p in d.glob("*.md")} if d.exists() else set()


def get_existing_concepts() -> set[str]:
    d = VAULT / "concepts"
    return {p.stem for p in d.glob("*.md")} if d.exists() else set()


def get_existing_briefs() -> set[str]:
    d = VAULT / "papers" / "brief"
    return {p.stem for p in d.glob("*.md")} if d.exists() else set()


def read_brief_excerpt(brief_stem: str, concept: str) -> str:
    """brief 파일에서 concept 관련 핵심 내용 추출 (최대 400자)"""
    brief_path = VAULT / "papers" / "brief" / f"{brief_stem}.md"
    if not brief_path.exists():
        return ""
    text = brief_path.read_text(encoding="utf-8", errors="ignore")
    # concept 주변 문맥 우선, 없으면 방법론 핵심 섹션
    lines = text.split("\n")
    relevant = []
    for i, line in enumerate(lines):
        if concept.lower() in line.lower():
            start = max(0, i - 1)
            end   = min(len(lines), i + 3)
            relevant.extend(lines[start:end])
    if relevant:
        return " ".join(relevant)[:400]
    # fallback: 방법론 섹션
    in_method = False
    method_lines = []
    for line in lines:
        if "방법론" in line or "핵심 기여" in line:
            in_method = True
        if in_method and line.strip():
            method_lines.append(line)
        if len(method_lines) > 6:
            break
    return " ".join(method_lines)[:400]


def ollama_concept_definition(concept: str, referencing_papers: list[str]) -> str:
    """Ollama로 개념 정의 + 논문별 활용 테이블 생성"""

    # 각 논문의 관련 내용 수집
    paper_contexts = []
    for stem in referencing_papers[:8]:
        excerpt = read_brief_excerpt(stem, concept)
        if excerpt:
            paper_contexts.append(f"- [[{stem}]]: {excerpt}")

    papers_block = "\n".join(paper_contexts) if paper_contexts else \
        "\n".join(f"- [[{s}]]" for s in referencing_papers[:5])

    prompt = f"""You are an academic knowledge base assistant. Write a Korean explanation for the concept "{concept}".

Context — papers in the vault that use this concept:
{papers_block}

Output ONLY the following markdown. No explanations, no code fences. ALL text in Korean.

## 개념 정의
(이 개념을 2-3문장으로 명확하게 설명. 한국어.)

## 핵심 특징
- (특징 1)
- (특징 2)
- (특징 3)

## Vault 논문 활용
| 논문 | 활용 방식 |
|------|----------|
(위 논문 목록에서 각 논문이 이 개념을 어떻게 쓰는지 한 줄씩. [[논문파일명]] 형식 유지.)

## 관련 개념
(이 개념과 연관된 다른 학술 개념을 [[개념명]] 형식으로 3-5개. Title Case.)
"""
    try:
        resp = ollama.chat(model=OLLAMA_MODEL, messages=[{"role": "user", "content": prompt}])
        return resp["message"]["content"].strip()
    except Exception as e:
        return f"(Ollama 정의 생성 실패: {e})"


def create_concept_stub(concept: str, source_stem: str, referencing: list[str]):
    """concepts/ 에 stub 생성. 이미 있으면 등장 노트만 추가."""
    concepts_dir = VAULT / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)
    cpath = concepts_dir / f"{concept}.md"

    if not cpath.exists():
        if ENRICH:
            log(f"  + [{concept}] Ollama 정의 생성 중...")
            body = ollama_concept_definition(concept, referencing)
        else:
            body = "(자동 생성된 stub. --enrich 옵션으로 정의를 채우거나 직접 작성하세요.)"

        content = (
            f"---\ntype: concept\n---\n\n"
            f"# {concept}\n\n"
            f"{body}\n\n"
            f"## 등장 노트\n- [[{source_stem}]]\n"
        )
        if not DRY_RUN:
            cpath.write_text(content, encoding="utf-8")
        log(f"  + 개념 stub 생성: {concept}  ← {source_stem}")
    else:
        existing = cpath.read_text(encoding="utf-8", errors="ignore")
        if f"[[{source_stem}]]" not in existing:
            if not DRY_RUN:
                if "## 등장 노트" in existing:
                    updated = existing.replace(
                        "## 등장 노트\n",
                        f"## 등장 노트\n- [[{source_stem}]]\n",
                        1,
                    )
                else:
                    updated = existing + f"\n## 등장 노트\n- [[{source_stem}]]\n"
                cpath.write_text(updated, encoding="utf-8")
            log(f"  ~ 개념 업데이트: {concept} ← {source_stem}")


def enrich_empty_stubs():
    """--enrich: 내용이 비어있는 concept 스텁을 Ollama로 채우기"""
    concepts_dir = VAULT / "concepts"
    if not concepts_dir.exists():
        return

    stubs = [p for p in sorted(concepts_dir.glob("*.md"))
             if not p.name.startswith("_")]
    targets = []
    for p in stubs:
        text = p.read_text(encoding="utf-8", errors="ignore")
        if "자동 생성된 stub" in text or "Ollama 정의 생성 실패" in text:
            targets.append(p)

    total = len(targets)
    log(f"빈 stub: {total}개 / 전체 {len(stubs)}개")
    if total == 0:
        log("모든 concept에 내용이 있습니다.")
        return

    filled = 0
    for idx, p in enumerate(targets, 1):
        concept = p.stem
        text    = p.read_text(encoding="utf-8", errors="ignore")

        # 등장 논문 목록 파싱
        ref_papers = re.findall(r"\[\[([^\]|/]+)\]\]", text)
        ref_papers  = [r for r in ref_papers if re.match(r"^\d{4}_", r)]

        log(f"\n[{idx}/{total}] {concept}  (등장 논문 {len(ref_papers)}편)")
        definition = ollama_concept_definition(concept, ref_papers)

        updated = re.sub(
            r"\(자동 생성된 stub[^)]*\)",
            definition,
            text,
            flags=re.DOTALL,
        )
        if not DRY_RUN:
            p.write_text(updated, encoding="utf-8")
        filled += 1

    log(f"\n완료: {filled}개 concept 정의 생성")


def normalize_links_in_file(path: Path) -> bool:
    """파일 내 [[link]] 이름을 Title Case로 정규화."""
    text = path.read_text(encoding="utf-8", errors="ignore")

    def repl(m):
        target, alias = m.group(1), m.group(2) or ""
        if "/" in target:
            return m.group(0)
        # 연도 prefix 링크는 정규화 안 함
        if PAPER_RE.match(target) or SESSION_RE.match(target):
            return m.group(0)
        return f"[[{normalize_concept_name(target)}{alias}]]"

    new_text = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", repl, text)
    if new_text != text:
        if not DRY_RUN:
            path.write_text(new_text, encoding="utf-8")
        return True
    return False


def main():
    log(f"{'[DRY RUN] ' if DRY_RUN else ''}Vault 연결 시작: {VAULT}\n")

    if ENRICH:
        log("=== 빈 concept 스텁 Ollama 보강 ===")
        enrich_empty_stubs()
        return

    topic_names_lower  = {t.lower() for t in get_topic_names()}
    existing_concepts  = get_existing_concepts()
    existing_briefs    = get_existing_briefs()

    files = collect_all_md()
    log(f"스캔 대상: {len(files)}개 파일\n")

    # 개념 → 참조 논문 목록 수집 (enrich용)
    concept_sources: dict[str, list[str]] = {}

    link_normalized = 0
    stubs_created   = 0
    stubs_updated   = 0

    for fpath in files:
        text = fpath.read_text(encoding="utf-8", errors="ignore")
        links = extract_concept_links(text)
        source_stem = fpath.stem

        changed = normalize_links_in_file(fpath)
        if changed:
            link_normalized += 1

        for concept in set(links):
            if concept.lower() in topic_names_lower:
                continue
            if concept in existing_briefs:
                continue

            concept_sources.setdefault(concept, []).append(source_stem)
            was_new = concept not in existing_concepts
            create_concept_stub(concept, source_stem, concept_sources.get(concept, []))
            if was_new:
                existing_concepts.add(concept)
                stubs_created += 1
            else:
                stubs_updated += 1

    log(f"\n{'[DRY RUN] ' if DRY_RUN else ''}완료")
    log(f"  링크 정규화된 파일: {link_normalized}개")
    log(f"  새 concept stub:    {stubs_created}개")
    log(f"  concept 업데이트:   {stubs_updated}개")
    if stubs_created > 0 and not ENRICH:
        log(f"\n  💡 빈 스텁에 정의를 채우려면: python connect_vault.py --enrich")


if __name__ == "__main__":
    main()
