"""
vault_indexer.py
Vault의 기존 개념·주제·논문을 스캔하여 Claude에게 컨텍스트로 전달.
"""
import re
from pathlib import Path
from config import VAULT_PATH


def list_existing_concepts() -> list[str]:
    """concepts/ 폴더의 모든 .md 파일명(확장자 제외) 반환"""
    concepts_dir = Path(VAULT_PATH) / "concepts"
    if not concepts_dir.exists():
        return []
    return sorted(p.stem for p in concepts_dir.glob("*.md"))


def list_existing_topics() -> list[str]:
    """topics/ 폴더의 모든 .md 파일명(확장자 제외) 반환"""
    topics_dir = Path(VAULT_PATH) / "topics"
    if not topics_dir.exists():
        return []
    return sorted(p.stem for p in topics_dir.glob("*.md"))


def list_existing_briefs() -> list[dict]:
    """기존 brief 요약본의 frontmatter 메타데이터 추출"""
    briefs_dir = Path(VAULT_PATH) / "papers" / "brief"
    if not briefs_dir.exists():
        return []
    results = []
    for p in briefs_dir.glob("*.md"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not m:
            continue
        fm = m.group(1)
        title = re.search(r'^title:\s*"?([^"\n]+)"?', fm, re.MULTILINE)
        topic = re.search(r'^primary_topic:\s*"?([^"\n]+)"?', fm, re.MULTILINE)
        results.append({
            "filename": p.stem,
            "title": title.group(1).strip() if title else p.stem,
            "primary_topic": topic.group(1).strip() if topic else ""
        })
    return results


def extract_wiki_links(text: str) -> list[str]:
    """[[Foo]] 또는 [[Foo|bar]] 형식의 위키 링크 대상 추출 (경로 포함 링크는 제외)"""
    links = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", text)
    # 경로(/)가 포함된 링크(papers/brief/... 등)는 제외
    return [link.strip() for link in links if "/" not in link]


def extract_frontmatter_field(text: str, field: str) -> str | None:
    """frontmatter에서 특정 필드 값 추출"""
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None
    fm = m.group(1)
    field_m = re.search(rf'^{field}:\s*"?([^"\n]+)"?', fm, re.MULTILINE)
    return field_m.group(1).strip() if field_m else None


def vault_context_for_prompt() -> str:
    """Claude 프롬프트에 주입할 vault 컨텍스트 문자열"""
    concepts = list_existing_concepts()
    topics = list_existing_topics()
    briefs = list_existing_briefs()

    lines = []
    if concepts:
        lines.append("## 이미 존재하는 개념 노트 (가급적 재사용)")
        lines.append(", ".join(f"[[{c}]]" for c in concepts))
    if topics:
        lines.append("\n## 이미 존재하는 주제 (primary_topic 후보)")
        lines.append(", ".join(topics))
    if briefs:
        lines.append("\n## 기존 논문 목록 (관련 시 [[파일명]] 으로 참조 가능)")
        for b in briefs:
            tag = f" ({b['primary_topic']})" if b["primary_topic"] else ""
            lines.append(f"- {b['filename']}{tag} — {b['title']}")

    return "\n".join(lines) if lines else "(vault가 비어 있음)"
