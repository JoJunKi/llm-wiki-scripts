"""
save_session.py
Claude Code 세션을 Obsidian sessions/ 폴더에 저장.
Ollama만 사용 — Claude 토큰 없음.

사용법:
  python save_session.py                         # 가장 최근 세션 자동 감지
  python save_session.py <session.jsonl>         # 특정 JSONL 파일
  python save_session.py --title "제목" [파일]   # 제목 직접 지정
"""
import sys
import io
import os
import re
import json
import ollama
from pathlib import Path
from datetime import date, datetime

from config import VAULT_PATH, OLLAMA_SESSION_MODEL
from prompts import OLLAMA_SESSION_PROMPT, OLLAMA_CHUNK_SUMMARY_PROMPT
from vault_indexer import vault_context_for_prompt
from normalize_vault import normalize_concept_name

# Windows UTF-8 출력
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

SESSIONS_DIR = Path(VAULT_PATH) / "sessions"
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"


# ─── JSONL 파싱 ───────────────────────────────────────────────

def extract_conversation(jsonl_path: Path) -> str:
    """JSONL → 순수 대화 텍스트 (tool_result/tool_use/thinking 제외)"""
    lines = []
    try:
        for raw in jsonl_path.read_bytes().splitlines():
            try:
                obj = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:
                continue

            msg_type = obj.get("type", "")
            if msg_type not in ("user", "assistant"):
                continue

            msg = obj.get("message", obj)
            content = msg.get("content", "")

            if isinstance(content, str):
                # user 단순 텍스트
                text = content.strip()
            elif isinstance(content, list):
                # text 블록만 추출 (tool_result / tool_use / thinking 제외)
                parts = [
                    c.get("text", "")
                    for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                text = " ".join(parts).strip()
            else:
                continue

            if not text or "[Request interrupted" in text:
                continue

            lines.append(f"[{msg_type.upper()}] {text}")

    except Exception as e:
        print(f"  [경고] JSONL 파싱 오류: {e}", file=sys.stderr)

    return "\n\n".join(lines)


def find_latest_jsonl() -> Path:
    """~/.claude/projects/ 에서 가장 최근 수정된 JSONL 반환"""
    if not CLAUDE_PROJECTS.exists():
        raise FileNotFoundError(f"Claude projects 폴더 없음: {CLAUDE_PROJECTS}")
    candidates = list(CLAUDE_PROJECTS.rglob("*.jsonl"))
    if not candidates:
        raise FileNotFoundError("저장된 세션 파일이 없습니다.")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def find_today_jsonls() -> list[Path]:
    """오늘 수정된 JSONL 파일 전부 반환 (오래된 순)"""
    if not CLAUDE_PROJECTS.exists():
        raise FileNotFoundError(f"Claude projects 폴더 없음: {CLAUDE_PROJECTS}")
    today = date.today()
    candidates = [
        p for p in CLAUDE_PROJECTS.rglob("*.jsonl")
        if datetime.fromtimestamp(p.stat().st_mtime).date() == today
    ]
    if not candidates:
        raise FileNotFoundError("오늘 수정된 세션 파일이 없습니다.")
    return sorted(candidates, key=lambda p: p.stat().st_mtime)


def is_already_saved(jsonl_path: Path) -> bool:
    """이미 sessions/에 저장된 세션인지 확인"""
    if not SESSIONS_DIR.exists():
        return False
    for existing in SESSIONS_DIR.glob("*.md"):
        if existing.name.startswith("_"):
            continue
        try:
            if jsonl_path.name in existing.read_text(encoding="utf-8", errors="ignore"):
                return True
        except Exception:
            continue
    return False


# ─── Ollama 구조화 (Map-Reduce) ───────────────────────────────

CHUNK_SIZE = 5000  # 청크당 글자 수


def chunk_text(text: str) -> list[str]:
    """대화 텍스트를 CHUNK_SIZE 단위로 분할 (메시지 경계 기준)"""
    messages = text.split("\n\n")
    chunks, current = [], ""
    for msg in messages:
        if len(current) + len(msg) > CHUNK_SIZE and current:
            chunks.append(current.strip())
            current = msg
        else:
            current += ("\n\n" if current else "") + msg
    if current.strip():
        chunks.append(current.strip())
    return chunks


def summarize_chunk(chunk: str, idx: int, total: int) -> str:
    """청크 하나 요약 (Map 단계) — exaone 사용"""
    prompt = OLLAMA_CHUNK_SUMMARY_PROMPT.format(chunk=chunk, idx=idx, total=total)
    response = ollama.chat(model=OLLAMA_SESSION_MODEL, messages=[{"role": "user", "content": prompt}])
    return response["message"]["content"].strip()


def reduce_with_ollama(chunk_summaries: list[str], vault_context: str) -> str:
    """Ollama로 청크 요약 → 최종 JSON (Reduce 단계)"""
    prompt = OLLAMA_SESSION_PROMPT.format(
        chunk_summaries="\n\n".join(chunk_summaries),
        vault_context=vault_context,
    )
    response = ollama.chat(model=OLLAMA_SESSION_MODEL, messages=[{"role": "user", "content": prompt}])
    return response["message"]["content"].strip()


def reduce_with_claude(chunk_summaries: list[str], vault_context: str) -> str:
    """Claude CLI로 청크 요약 → 최종 JSON (Reduce 단계, 옵션)"""
    import subprocess, tempfile
    prompt = OLLAMA_SESSION_PROMPT.format(
        chunk_summaries="\n\n".join(chunk_summaries),
        vault_context=vault_context,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            ["claude", "-p", "--model", "sonnet"],
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=120,
            cwd=tmpdir,
        )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return result.stdout.decode("utf-8", errors="replace").strip()


def parse_json_response(raw: str) -> dict:
    """LLM 응답에서 JSON 파싱.
    모델이 JSON 앞뒤에 설명 텍스트를 붙여도 {…} 블록만 추출해서 파싱.
    """
    # 코드 펜스 제거
    if "```" in raw:
        raw = re.sub(r"```[a-z]*\n?", "", raw).replace("```", "").strip()
    # {…} 블록 추출 (앞뒤 설명 텍스트 무시)
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        raw = match.group(0)
    try:
        return json.loads(raw)
    except Exception:
        print(f"  [경고] JSON 파싱 실패 — 기본 구조 사용\n  원본: {raw[:200]}", file=sys.stderr)
        return {
            "title": "세션 요약",
            "summary": raw[:300],
            "key_decisions": [],
            "ideas": [],
            "related_concepts": [],
            "related_papers": [],
            "tags": [],
        }


def structure_session(conversation: str, use_claude: bool = False) -> dict:
    """Map-Reduce로 긴 대화 → 구조화된 dict.
    use_claude=True이면 Reduce 단계만 Claude 사용.
    """
    # 1) Map: 청크별 요약 (항상 Ollama)
    chunks = chunk_text(conversation)
    total = len(chunks)
    print(f"  [Ollama/{OLLAMA_SESSION_MODEL}] 대화를 {total}개 청크로 분할해서 요약 중...", flush=True)

    chunk_summaries = []
    for i, chunk in enumerate(chunks, 1):
        print(f"    청크 {i}/{total} 요약 중...", end=" ", flush=True)
        summary = summarize_chunk(chunk, i, total)
        chunk_summaries.append(f"[{i}/{total}]\n{summary}")
        print("완료", flush=True)

    # 청크 요약 임시 저장 (검토용)
    chunks_log = Path(VAULT_PATH) / "sessions" / "_last_chunks.txt"
    chunks_log.parent.mkdir(parents=True, exist_ok=True)
    chunks_log.write_text("\n\n" + "="*50 + "\n\n".join(chunk_summaries), encoding="utf-8")
    print(f"  청크 요약 저장됨 (검토용): {chunks_log}", flush=True)

    # 2) Reduce: 청크 요약 → 최종 구조화 JSON
    vault_context = vault_context_for_prompt()
    if use_claude:
        print("  [Claude] 최종 구조화 중...", flush=True)
        raw = reduce_with_claude(chunk_summaries, vault_context)
    else:
        print(f"  [Ollama/{OLLAMA_SESSION_MODEL}] 최종 구조화 중...", flush=True)
        raw = reduce_with_ollama(chunk_summaries, vault_context)

    return parse_json_response(raw)


# ─── Vault 저장 ───────────────────────────────────────────────

def make_session_filename(title: str, dt: datetime) -> str:
    date_str = dt.strftime("%Y-%m-%d")
    clean = "".join(c for c in title if c.isalnum() or c in " _-")
    clean = clean.strip().replace(" ", "_")[:40]
    return f"{date_str}_{clean}.md"


def build_markdown(info: dict, jsonl_path: Path) -> str:
    today = date.today().isoformat()
    mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime)

    concepts = [normalize_concept_name(c) for c in info.get("related_concepts", [])]
    concept_links = " | ".join(f"[[{c}]]" for c in concepts) if concepts else "(없음)"
    paper_links = "\n".join(f"- [[{p}]]" for p in info.get("related_papers", [])) or "- (없음)"
    decisions = "\n".join(f"- {d}" for d in info.get("key_decisions", [])) or "- (없음)"
    ideas = "\n".join(f"- {i}" for i in info.get("ideas", [])) or "- (없음)"
    session_type = info.get("session_type", "mixed")
    tags = info.get("tags", []) + ["session", session_type]

    return f"""---
title: "{info.get('title', '세션 요약')}"
date: {today}
session_time: "{mtime.strftime('%Y-%m-%d %H:%M')}"
type: session
session_type: {session_type}
tags: {json.dumps(list(dict.fromkeys(tags)), ensure_ascii=False)}
related_concepts: {json.dumps(concepts, ensure_ascii=False)}
related_papers: {json.dumps(info.get('related_papers', []), ensure_ascii=False)}
source_jsonl: "{jsonl_path.name}"
---

## 요약
{info.get('summary', '')}

## 핵심 결정사항
{decisions}

## 아이디어 / 인사이트
{ideas}

## 관련 개념
{concept_links}

## 관련 논문
{paper_links}
"""


def save_session(info: dict, jsonl_path: Path, title_override: str = "") -> str:
    title = title_override or info.get("title", "세션 요약")
    mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime)
    filename = make_session_filename(title, mtime)

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SESSIONS_DIR / filename

    # 같은 source_jsonl로 저장된 기존 파일 삭제 (재실행 시 덮어쓰기)
    for existing in SESSIONS_DIR.glob("*.md"):
        if existing.name.startswith("_"):
            continue
        if jsonl_path.name in existing.read_text(encoding="utf-8", errors="ignore"):
            existing.unlink()
            print(f"  기존 파일 교체: {existing.name} → {out_path.name}")

    content = build_markdown(info, jsonl_path)
    out_path.write_text(content, encoding="utf-8")
    return str(out_path)


# ─── 개념 stub 자동 생성 ──────────────────────────────────────

def create_concept_stubs(info: dict, session_filename_noext: str):
    vault = Path(VAULT_PATH)
    topic_names_lower = {p.stem.lower() for p in (vault / "topics").glob("*.md")}
    concepts_dir = vault / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)
    created = 0
    for raw in info.get("related_concepts", []):
        concept = normalize_concept_name(raw)
        if concept.lower() in topic_names_lower:
            continue
        if (vault / "papers" / "brief" / f"{concept}.md").exists():
            continue
        cpath = concepts_dir / f"{concept}.md"
        if not cpath.exists():
            cpath.write_text(
                f"---\ntype: concept\n---\n\n# {concept}\n\n"
                f"(자동 생성된 stub)\n\n## 등장 세션\n- [[{session_filename_noext}]]\n",
                encoding="utf-8"
            )
            created += 1
        else:
            existing = cpath.read_text(encoding="utf-8")
            if session_filename_noext not in existing:
                section = "## 등장 세션\n" if "## 등장 세션" not in existing else ""
                if section:
                    existing += f"\n{section}- [[{session_filename_noext}]]\n"
                else:
                    existing = existing.replace(
                        "## 등장 세션\n",
                        f"## 등장 세션\n- [[{session_filename_noext}]]\n",
                        1
                    )
                cpath.write_text(existing, encoding="utf-8")
    if created:
        print(f"  + 신규 개념 stub {created}개 생성", flush=True)


# ─── 메인 ─────────────────────────────────────────────────────

def process_one_jsonl(jsonl_path: Path, use_claude: bool, title_override: str, type_override: str):
    """JSONL 하나 처리 — 공통 로직"""
    mode = "Ollama Map-Reduce" if not use_claude else "Ollama Map + Claude Reduce"
    print(f"\n📋 세션 저장 ({mode}): {jsonl_path.name}")
    conversation = extract_conversation(jsonl_path)
    if not conversation.strip():
        print("  대화 내용을 추출할 수 없습니다. 스킵.")
        return

    info = structure_session(conversation, use_claude=use_claude)
    if type_override:
        info["session_type"] = type_override
    out_path = save_session(info, jsonl_path, title_override)
    filename_noext = Path(out_path).stem
    create_concept_stubs(info, filename_noext)

    print(f"  ✅ 저장 완료: {out_path}")
    print(f"     제목: {info.get('title')}")
    print(f"     개념: {info.get('related_concepts')}")


def main():
    title_override = ""
    type_override = ""
    jsonl_path = None
    use_claude = False
    save_today = False

    args = sys.argv[1:]

    if "--claude" in args:
        use_claude = True
        args.remove("--claude")

    if "--today" in args:
        save_today = True
        args.remove("--today")

    if "--type" in args:
        idx = args.index("--type")
        type_override = args[idx + 1]
        args = [a for i, a in enumerate(args) if i != idx and i != idx + 1]

    if "--title" in args:
        idx = args.index("--title")
        title_override = args[idx + 1]
        args = [a for i, a in enumerate(args) if i != idx and i != idx + 1]

    # --today: 오늘치 전부 저장 (이미 저장된 건 스킵)
    if save_today:
        print("오늘 세션 전체 저장 중...")
        jsonls = find_today_jsonls()
        print(f"  오늘 세션 {len(jsonls)}개 발견")
        skipped = 0
        for jpath in jsonls:
            if is_already_saved(jpath):
                print(f"  ⏭️  이미 저장됨: {jpath.name}")
                skipped += 1
                continue
            process_one_jsonl(jpath, use_claude, title_override="", type_override=type_override)
        print(f"\n완료: {len(jsonls) - skipped}개 저장 / {skipped}개 스킵")
        return

    # 특정 파일 지정
    if args:
        jsonl_path = Path(args[0])
        if not jsonl_path.exists():
            print(f"파일을 찾을 수 없습니다: {jsonl_path}")
            sys.exit(1)
    else:
        print("가장 최근 세션 자동 감지 중...")
        jsonl_path = find_latest_jsonl()
        print(f"  세션: {jsonl_path}")

    process_one_jsonl(jsonl_path, use_claude, title_override, type_override)


if __name__ == "__main__":
    main()
