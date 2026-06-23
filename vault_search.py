"""
vault_search.py
Obsidian vault 논문 검색 — 압축 인덱스 + Ollama (임베딩/DB 불필요)

실행:
  python vault_search.py                          # 인덱스 업데이트 후 검색
  python vault_search.py --update-only            # 인덱스만 갱신
  python vault_search.py "디퓨전 포트폴리오 수익률"  # 바로 검색

동작 원리:
  1. 실행할 때마다 brief.md 스캔 → 새 논문만 _search_index.jsonl에 추가
  2. 인덱스 전체(~1500 토큰)를 Ollama에 넘겨 자연어 검색
"""
import re
import sys
import io
import json
import ollama
from pathlib import Path
from datetime import date

from config import VAULT_PATH, OLLAMA_MODEL

# Windows cp949 콘솔 UTF-8 강제
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

VAULT      = Path(VAULT_PATH)
BRIEF_DIR  = VAULT / "papers" / "brief"
INDEX_FILE = VAULT.parent / "_search_index.jsonl"


def log(msg: str):
    print(msg, flush=True)


# ── 인덱스 로드 / 저장 ────────────────────────────────────────────
def load_index() -> dict[str, dict]:
    """stem → entry"""
    if not INDEX_FILE.exists():
        return {}
    entries = {}
    with open(INDEX_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    e = json.loads(line)
                    entries[e["stem"]] = e
                except Exception:
                    pass
    return entries


def save_index(entries: dict[str, dict]):
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        for e in sorted(entries.values(), key=lambda x: x.get("year", 0), reverse=True):
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


# ── brief.md 파싱 → 한 줄 압축 엔트리 ───────────────────────────
def parse_brief(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")

    # frontmatter
    fm_title = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$',       text, re.MULTILINE)
    fm_year  = re.search(r'^year:\s*(\d+)',                          text, re.MULTILINE)
    fm_topic = re.search(r'^primary_topic:\s*["\']?(.+?)["\']?\s*$',text, re.MULTILINE)

    title = fm_title.group(1).strip() if fm_title else path.stem
    year  = int(fm_year.group(1))     if fm_year  else 0
    topic = fm_topic.group(1).strip() if fm_topic else ""

    def section(keyword: str, chars: int = 200) -> str:
        m = re.search(rf'## [^\n]*{keyword}[^\n]*\n(.*?)(?=\n## |\Z)', text, re.DOTALL)
        if not m:
            return ""
        content = m.group(1).strip()
        content = re.sub(r'^>\s*', '', content, flags=re.MULTILINE)  # 인용블록 제거
        return content[:chars].replace("\n", " ")

    summary       = section("한 줄 요약", 120)
    contributions = section("핵심 기여", 200)
    first_contrib = re.split(r'\n', contributions)[0].lstrip("123. ").strip()[:120]
    methods       = section("방법론", 150)

    # 관련 개념 [[링크]] 추출
    concepts_raw  = section("관련 개념", 300)
    concepts      = re.findall(r'\[\[([^\]|/]+)\]\]', concepts_raw)
    concepts      = [c.strip() for c in concepts if c.strip()][:6]

    return {
        "stem":         path.stem,
        "title":        title,
        "year":         year,
        "topic":        topic,
        "summary":      summary,
        "contribution": first_contrib,
        "methods":      methods,
        "concepts":     concepts,
        "indexed_at":   date.today().isoformat(),
        "mtime":        path.stat().st_mtime,
    }


# ── 인덱스 업데이트 (새 논문만) ──────────────────────────────────
def update_index() -> tuple[int, int]:
    """
    매 실행마다 호출.
    새로 추가되거나 수정된 brief만 재인덱싱.
    반환: (총 논문 수, 신규/갱신 수)
    """
    entries = load_index()
    briefs  = sorted(BRIEF_DIR.glob("*.md")) if BRIEF_DIR.exists() else []

    updated = 0
    for bf in briefs:
        stem  = bf.stem
        mtime = bf.stat().st_mtime
        existing = entries.get(stem)
        # 이미 인덱싱됐고 파일 수정 없으면 skip
        if existing and abs(existing.get("mtime", 0) - mtime) < 1:
            continue
        try:
            entries[stem] = parse_brief(bf)
            updated += 1
        except Exception as e:
            log(f"  [파싱 오류] {bf.name}: {e}")

    # vault에서 삭제된 논문은 인덱스에서도 제거
    current_stems = {bf.stem for bf in briefs}
    removed = [s for s in list(entries.keys()) if s not in current_stems]
    for s in removed:
        del entries[s]
        updated += 1

    if updated > 0:
        save_index(entries)

    return len(entries), updated


# ── Ollama 검색 ───────────────────────────────────────────────────
def keyword_prefilter(query: str, entries: dict[str, dict]) -> dict[str, dict]:
    """
    희귀 키워드 AND 필터 → Ollama 후보 수 최소화.
    전략:
      1. 각 키워드별로 매칭 논문 수 계산
      2. 가장 희귀한 키워드(매칭 수 적은 것)부터 AND 조건 적용
      3. 결과 < 3이면 조건 완화
    """
    words = [w.lower() for w in re.split(r'[\s,]+', query) if len(w) > 2]

    def haystack(e: dict) -> str:
        return " ".join([
            e.get("title", ""), e.get("summary", ""),
            e.get("contribution", ""), e.get("methods", ""),
            " ".join(e.get("concepts", [])), e.get("topic", ""),
        ]).lower()

    haystacks = {stem: haystack(e) for stem, e in entries.items()}

    # 단어별 매칭 수 계산
    word_counts = {w: sum(1 for h in haystacks.values() if w in h) for w in words}
    # 희귀한 단어 순 정렬
    sorted_words = sorted(words, key=lambda w: word_counts[w])

    # AND 필터 (희귀 단어 우선)
    matched = {stem: e for stem, e in entries.items()
               if all(w in haystacks[stem] for w in sorted_words)}

    # 너무 적으면 완화: 희귀한 단어 절반만 AND
    if len(matched) < 3 and sorted_words:
        rare_words = sorted_words[:max(1, len(sorted_words)//2)]
        matched = {stem: e for stem, e in entries.items()
                   if all(w in haystacks[stem] for w in rare_words)}

    # 그래도 없으면 전체
    return matched if len(matched) >= 2 else entries


def build_index_text(entries: dict[str, dict]) -> str:
    """인덱스를 Ollama에 넘길 압축 텍스트 (논문당 2줄)"""
    lines = []
    for i, e in enumerate(
        sorted(entries.values(), key=lambda x: x.get("year", 0), reverse=True), 1
    ):
        concepts_str = ", ".join(e.get("concepts", [])[:4])
        line = (
            f"[{i}] {e['stem']}\n"
            f"    {e['year']} | {e['title'][:70]} | {e.get('summary','')[:80]} | 개념: {concepts_str}"
        )
        lines.append(line)
    return "\n".join(lines)


def search_with_ollama(query: str, entries: dict[str, dict], top_k: int = 5) -> list[dict]:
    # 1차 키워드 필터
    candidates = keyword_prefilter(query, entries)
    log(f"  후보 논문: {len(candidates)}편 (전체 {len(entries)}편 중)\n")

    index_text = build_index_text(candidates)
    stem_by_idx = {
        i: e["stem"]
        for i, e in enumerate(
            sorted(candidates.values(), key=lambda x: x.get("year", 0), reverse=True), 1
        )
    }

    # Step 1: 번호만 출력 (환각 방지)
    prompt_select = f"""논문 목록:

{index_text}

질문: "{query}"

위 목록에서 질문과 관련 있는 논문 번호를 관련도 순으로 최대 {top_k}개 골라주세요.
숫자만 쉼표로 구분해서 출력하세요. 다른 텍스트 없이.
예시: 3,7,12,1"""

    resp1 = ollama.chat(model=OLLAMA_MODEL, messages=[{"role": "user", "content": prompt_select}])
    raw1  = resp1["message"]["content"].strip()

    # 번호 파싱 (숫자만 추출)
    nums = [int(x) for x in re.findall(r'\d+', raw1)
            if x.isdigit() and 1 <= int(x) <= len(stem_by_idx)]
    # 중복 제거, 순서 유지
    seen, unique_nums = set(), []
    for n in nums:
        if n not in seen:
            seen.add(n)
            unique_nums.append(n)
    unique_nums = unique_nums[:top_k]

    if not unique_nums:
        return [{"rank": 0, "stem": "", "title": "", "year": 0,
                 "reason": raw1, "_raw": True}]

    # Step 2: 선택된 논문들에 대해 이유 생성
    selected_titles = "\n".join(
        f"{i+1}. {candidates[stem_by_idx[n]]['title'][:60]}"
        for i, n in enumerate(unique_nums)
        if stem_by_idx.get(n) in candidates
    )
    prompt_reason = f"""다음 논문들이 "{query}" 검색에 선택되었습니다:

{selected_titles}

각 논문이 왜 관련 있는지 한 줄씩 한국어로 설명하세요.
번호. 이유 형식으로만 출력하세요.
예시:
1. 포트폴리오 최적화에 확산 모델을 직접 적용
2. 헤비테일 분포를 활용한 리스크 모델링"""

    resp2 = ollama.chat(model=OLLAMA_MODEL, messages=[{"role": "user", "content": prompt_reason}])
    raw2  = resp2["message"]["content"].strip()

    # 이유 파싱
    reasons = {}
    for line in raw2.split("\n"):
        line = line.strip().replace("**", "")
        m = re.match(r'(\d+)[.\)]\s*(.+)', line)
        if m:
            reasons[int(m.group(1))] = m.group(2).strip()

    # 결과 조합
    results = []
    for i, n in enumerate(unique_nums, 1):
        stem = stem_by_idx.get(n)
        if not stem or stem not in candidates:
            continue
        e = candidates[stem]
        results.append({
            "rank":   i,
            "stem":   stem,
            "title":  e["title"],
            "year":   e["year"],
            "reason": reasons.get(i, ""),
        })

    return results if results else [{"rank": 0, "stem": "", "title": "", "year": 0,
                                     "reason": raw1, "_raw": True}]


# ── 결과 출력 ─────────────────────────────────────────────────────
def display_results(results: list[dict]):
    if results and results[0].get("_raw"):
        log(results[0]["reason"])
        return

    log(f"\n{'='*62}")
    log(f"  검색 결과: {len(results)}편")
    log(f"{'='*62}\n")
    for r in results:
        log(f"  [{r['rank']}] {r['title'][:65]}")
        log(f"       {r['year']}  |  {r['stem']}")
        log(f"       → {r['reason']}")
        log("")


# ── 메인 ─────────────────────────────────────────────────────────
def main():
    args        = sys.argv[1:]
    update_only = "--update-only" in args
    query_parts = [a for a in args if not a.startswith("--")]
    query       = " ".join(query_parts)

    # 매 실행마다 인덱스 갱신
    log("인덱스 갱신 중...")
    total, updated = update_index()
    if updated > 0:
        log(f"  ✅ {total}편 인덱싱됨  ({updated}편 신규/갱신)\n")
    else:
        log(f"  ✅ {total}편 인덱싱됨  (변경 없음)\n")

    if update_only:
        return

    # 검색어
    if not query:
        query = input("검색어 입력: ").strip()
    if not query:
        return

    log(f"🔍  검색: '{query}'")
    entries = load_index()
    if not entries:
        log("인덱스가 비어있습니다. brief 파일을 먼저 생성하세요.")
        return

    results = search_with_ollama(query, entries)
    display_results(results)


if __name__ == "__main__":
    main()
