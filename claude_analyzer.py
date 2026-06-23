"""
claude_analyzer.py

두 가지 실행 모드:
  1. API 키 모드 (ANTHROPIC_API_KEY 환경변수 설정 시)
     python claude_analyzer.py <data_json> <filename.md>

  2. Claude Code 대화 모드 (API 키 없을 때)
     python claude_analyzer.py --print <data_json>
     → 분석할 데이터를 출력합니다. Claude Code 대화창에 붙여넣기하세요.
"""
import sys
import io
import re
import json
import os
import subprocess
from pathlib import Path
from datetime import date
from config import VAULT_PATH, TEMP_DIR
from prompts import DETAILED_SUMMARY_PROMPT, BRIEF_SUMMARY_PROMPT
from vault_indexer import (
    vault_context_for_prompt,
    extract_wiki_links,
    extract_frontmatter_field,
)
from normalize_vault import normalize_concept_name

# Windows cp949 콘솔에서도 UTF-8로 출력
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


def call_claude_cli(prompt: str) -> str:
    """Claude Code CLI(`claude -p`)를 통해 응답 받기. 구독 인증 사용.

    프롬프트는 stdin으로 전달 (셸 인자 길이 제한 회피).
    CLAUDE.md 컨텍스트 간섭을 피하기 위해 임시 디렉토리에서 실행.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            ["claude", "-p", "--model", "sonnet"],
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=600,
            cwd=tmpdir
        )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI 오류: {result.stderr.decode('utf-8', errors='replace')}")
    return result.stdout.decode("utf-8", errors="replace").strip()


def strip_markdown_fence(text: str) -> str:
    """응답에 ```markdown ... ``` 펜스가 있으면 제거"""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        # 첫 줄 (```markdown 등) 제거
        lines = lines[1:]
        # 마지막 ``` 제거
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return t


def normalize_brief_links(text: str) -> str:
    """brief 본문의 [[개념]] 링크를 표준형(Title Case + 공백)으로 정규화.
    경로 링크(papers/...)는 건드리지 않는다."""
    def repl(m):
        target = m.group(1)
        alias = m.group(2) or ""
        if "/" in target:
            return m.group(0)
        return f"[[{normalize_concept_name(target)}{alias}]]"

    return re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", repl, text)


def save_to_vault(content: str, subfolder: str, filename: str) -> str:
    output_path = Path(VAULT_PATH) / subfolder / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return str(output_path)


def make_filename(title: str, year: int) -> str:
    clean = "".join(c for c in title if c.isalnum() or c in " _-")
    clean = clean.strip().replace(" ", "_")[:50]
    return f"{year}_{clean}.md"


def analyze_with_api(data: dict, filename: str):
    """ANTHROPIC_API_KEY가 있을 때 직접 API 호출"""
    import anthropic

    meta = data["metadata"]
    sections_raw = data["sections"]
    today = date.today().isoformat()
    tags = meta.get("keywords", []) + [meta.get("domain", "")]
    # sections가 list[dict] 형식이면 읽기 좋은 텍스트로 변환
    if isinstance(sections_raw, list):
        sections_str = "\n\n".join(
            f"## {s['header']}\n{s['content'][:800]}"
            for s in sections_raw
        )
    else:
        sections_str = json.dumps(sections_raw, ensure_ascii=False, indent=2)

    client = anthropic.Anthropic()

    filename_noext = filename.rsplit(".", 1)[0]

    # detailed는 Ollama 생성 초안 저장
    detailed_content = data.get("detailed_markdown", "")
    detailed_path = ""
    if detailed_content:
        detailed_path = save_to_vault(detailed_content, "papers/detailed", filename)
        print(f"저장(Ollama): {detailed_path}")
    else:
        print("  [경고] detailed_markdown 없음 — detailed 저장 스킵")

    print("\n[Claude API] brief 요약본 생성 중...")
    brief_prompt = BRIEF_SUMMARY_PROMPT.format(
        metadata=json.dumps(meta, ensure_ascii=False),
        sections=sections_str,
        title=meta.get("title", ""),
        authors=meta.get("authors", []),
        year=meta.get("year", ""),
        tags=tags,
        filename=filename_noext,
        vault_context=vault_context_for_prompt()
    )
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": brief_prompt}]
    )
    brief_content = normalize_brief_links(resp.content[0].text)
    brief_path = save_to_vault(brief_content, "papers/brief", filename)
    print(f"저장: {brief_path}")

    postprocess_brief(brief_content, filename_noext)

    return detailed_path, brief_path


def analyze_with_cli(data: dict, filename: str):
    """Claude Code CLI(`claude -p`)를 사용해 분석. 구독 인증으로 동작."""
    meta = data["metadata"]
    sections_raw = data["sections"]
    today = date.today().isoformat()
    tags = meta.get("keywords", []) + [meta.get("domain", "")]
    if isinstance(sections_raw, list):
        sections_str = "\n\n".join(
            f"## {s['header']}\n{s['content'][:800]}"
            for s in sections_raw
        )
    else:
        sections_str = json.dumps(sections_raw, ensure_ascii=False, indent=2)
    filename_noext = filename.rsplit(".", 1)[0]

    # detailed는 Ollama가 생성한 초안을 그대로 저장 (Claude 토큰 없음)
    detailed_content = data.get("detailed_markdown", "")
    detailed_path = ""
    if detailed_content:
        detailed_path = save_to_vault(detailed_content, "papers/detailed", filename)
        print(f"저장(Ollama): {detailed_path}", flush=True)
    else:
        print("  [경고] detailed_markdown 없음 — detailed 저장 스킵", flush=True)

    print("\n[Claude CLI] brief 요약본 생성 중...", flush=True)
    vault_context = vault_context_for_prompt()
    brief_prompt = BRIEF_SUMMARY_PROMPT.format(
        metadata=json.dumps(meta, ensure_ascii=False),
        sections=sections_str,
        title=meta.get("title", ""),
        authors=meta.get("authors", []),
        year=meta.get("year", ""),
        tags=tags,
        filename=filename_noext,
        vault_context=vault_context
    )
    brief_prompt = (
        f"아래 메타데이터의 논문 제목/저자/년도를 절대 바꾸지 마세요. "
        f"제공된 데이터 외의 정보는 추측하거나 만들어내지 마세요.\n"
        f"실제 논문 제목: {meta.get('title', '')}\n"
        f"실제 저자: {meta.get('authors', [])}\n"
        f"실제 년도: {meta.get('year', '')}\n\n"
        + brief_prompt
        + "\n\n출력 규칙: 마크다운 본문만 출력하세요. 설명이나 코드 펜스(```)는 포함하지 마세요. frontmatter ---로 시작하세요."
    )
    brief_content = normalize_brief_links(strip_markdown_fence(call_claude_cli(brief_prompt)))
    brief_path = save_to_vault(brief_content, "papers/brief", filename)
    print(f"저장: {brief_path}", flush=True)

    # 후처리: MOC 생성/업데이트 + 신규 개념 stub 생성
    postprocess_brief(brief_content, filename_noext)

    return detailed_path, brief_path


def postprocess_brief(brief_content: str, filename_noext: str):
    """brief 분석 결과로부터 MOC 노트 및 신규 개념 stub 자동 생성"""
    vault = Path(VAULT_PATH)

    # 1) primary_topic 추출 → topics/{topic}.md MOC 생성/업데이트
    topic = extract_frontmatter_field(brief_content, "primary_topic")
    if topic:
        topic_clean = topic.strip().strip('"').strip("'")
        moc_path = vault / "topics" / f"{topic_clean}.md"
        moc_path.parent.mkdir(parents=True, exist_ok=True)
        if not moc_path.exists():
            moc_path.write_text(
                f"""---
type: moc
topic: "{topic_clean}"
---

# {topic_clean} — MOC

## Papers
- [[{filename_noext}]]

## Dataview 자동 목록 (Dataview 플러그인 설치 시 활성화)
```dataview
TABLE year, primary_topic
FROM "papers/brief"
WHERE primary_topic = "{topic_clean}"
SORT year DESC
```
""",
                encoding="utf-8"
            )
            print(f"  + MOC 생성: {moc_path.name}", flush=True)
        else:
            # 이미 있으면 Papers 섹션에 링크 추가 (중복 방지)
            existing = moc_path.read_text(encoding="utf-8")
            if f"[[{filename_noext}]]" not in existing:
                updated = existing.replace(
                    "## Papers\n",
                    f"## Papers\n- [[{filename_noext}]]\n",
                    1
                )
                moc_path.write_text(updated, encoding="utf-8")
                print(f"  + MOC 업데이트: {moc_path.name}", flush=True)

    # 2) [[Concept]] 위키 링크 → 신규 개념 stub 생성
    topic_names_lower = {p.stem.lower() for p in (vault / "topics").glob("*.md")}
    # 현재 논문의 primary_topic도 concept 생성 제외 (topics/에서 관리)
    if topic:
        topic_names_lower.add(topic_clean.lower())
    links = extract_wiki_links(brief_content)
    concepts_dir = vault / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)
    created = 0
    seen = set()
    for raw_link in links:
        link = normalize_concept_name(raw_link)  # 표준형으로 통일
        if link in seen:
            continue
        seen.add(link)
        # 경로 포함 링크(관련 논문) 스킵
        if "/" in raw_link:
            continue
        # 논문 파일명(연도 prefix) 스킵
        if re.match(r"^\d{4}[_-]", link):
            continue
        # 기존 paper나 주제(MOC)와 겹치면 개념 생성 스킵 (대소문자 무시)
        if (vault / "papers" / "brief" / f"{link}.md").exists():
            continue
        if link.lower() in topic_names_lower:
            continue
        concept_path = concepts_dir / f"{link}.md"
        if not concept_path.exists():
            concept_path.write_text(
                f"""---
type: concept
---

# {link}

(자동 생성된 stub. 직접 정의를 채워 넣으세요.)

## 등장 논문
- [[{filename_noext}]]
""",
                encoding="utf-8"
            )
            created += 1
        else:
            # 이미 있으면 등장 논문에 추가
            existing = concept_path.read_text(encoding="utf-8")
            if f"[[{filename_noext}]]" not in existing:
                if "## 등장 논문" in existing:
                    existing = existing.replace(
                        "## 등장 논문\n",
                        f"## 등장 논문\n- [[{filename_noext}]]\n",
                        1
                    )
                else:
                    existing += f"\n## 등장 논문\n- [[{filename_noext}]]\n"
                concept_path.write_text(existing, encoding="utf-8")
    if created:
        print(f"  + 신규 개념 stub {created}개 생성", flush=True)


def print_for_claude_code(data: dict):
    """Claude Code 대화창에 붙여넣기할 데이터를 출력"""
    meta = data["metadata"]
    sections = data.get("sections", {})
    filename = make_filename(meta.get("title", "paper"), meta.get("year", date.today().year))

    print("\n" + "=" * 70)
    print("아래 내용을 Claude Code 대화창에 붙여넣으세요:")
    print("=" * 70)
    print(f"""
다음 논문 데이터를 분석해서 두 파일을 만들어주세요.

## 메타데이터
{json.dumps(meta, ensure_ascii=False, indent=2)}

## 섹션 데이터 (요약)
{json.dumps({k: v[:600] + "..." if len(str(v)) > 600 else v for k, v in sections.items()}, ensure_ascii=False, indent=2)}

## 요청
1. 상세 요약본(papers/detailed/{filename})과 전체 요약본(papers/brief/{filename})을
   {VAULT_PATH} 경로의 Obsidian Vault에 저장해주세요.
2. 한국어로 작성하고 Obsidian [[링크]] 형식을 사용해주세요.
3. 상세 요약은 섹션별 표 + 💡 Insight 형식으로 작성해주세요.
""")
    print("=" * 70)
    print(f"\n파일명: {filename}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법:")
        print("  python claude_analyzer.py <data.json> <filename.md>   # Claude CLI 자동 모드")
        print("  python claude_analyzer.py --print <data.json>          # 수동 대화 모드")
        sys.exit(1)

    if sys.argv[1] == "--print":
        data = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        print_for_claude_code(data)
        sys.exit(0)

    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    filename = sys.argv[2]

    # API 키 있으면 SDK, 없으면 CLI 자동 사용
    if os.environ.get("ANTHROPIC_API_KEY"):
        detailed_path, brief_path = analyze_with_api(data, filename)
    else:
        detailed_path, brief_path = analyze_with_cli(data, filename)

    print("\n" + "=" * 60)
    print("분석 완료!")
    print(f"  상세 요약: {detailed_path}")
    print(f"  전체 요약: {brief_path}")
    print("=" * 60)
