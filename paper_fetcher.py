"""
paper_fetcher.py
OpenAlex 검색 → 인용수/연도 필터 → PDF 자동 다운로드 → _inbox/ 저장

OpenAlex: 완전 무료, API 키 불필요, 인용수 필터 지원
arXiv   : PDF 다운로드 (API 키 불필요)

사용법:
  python paper_fetcher.py diffusion time series
  python paper_fetcher.py diffusion time series --min-citations 50 --year-from 2023
  python paper_fetcher.py transformer forecasting --max 15
  python paper_fetcher.py diffusion model finance --dry
"""
import re
import sys
import io
import csv
import time
import requests
import arxiv
from pathlib import Path
from datetime import date

from config import VAULT_PATH, OPENALEX_EMAIL

# Windows cp949 콘솔 UTF-8 강제
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

INBOX    = Path(VAULT_PATH).parent / "_inbox"
ARCHIVE  = Path(VAULT_PATH).parent / "_archive"
PAPER_LOG = Path(VAULT_PATH).parent / "_paper_log.csv"

CSV_FIELDS = ["title", "year", "citations", "arxiv_id", "status", "query", "date_found", "filename"]
# status: downloaded / manual_needed / skipped(중복)

OPENALEX_URL = "https://api.openalex.org/works"
USER_EMAIL   = OPENALEX_EMAIL      # config.py에서 설정

# 기본값
DEFAULT_MIN_CITATIONS = 30
DEFAULT_YEAR_FROM     = 2022
DEFAULT_MAX_RESULTS   = 20


def log(msg: str):
    print(msg, flush=True)


# ── CSV 로그 ──────────────────────────────────────────────────────
def load_paper_log() -> dict[str, dict]:
    """CSV 로드 → {title_lower: row_dict} 반환"""
    if not PAPER_LOG.exists():
        return {}
    rows = {}
    with open(PAPER_LOG, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows[row["title"].lower().strip()] = row
    return rows


def save_paper_log(log_dict: dict[str, dict]):
    """dict → CSV 저장 (인용수 내림차순)"""
    rows = sorted(log_dict.values(), key=lambda r: int(r.get("citations") or 0), reverse=True)
    with open(PAPER_LOG, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def upsert_log(log_dict: dict, title: str, year: int, citations: int,
               arxiv_id: str, status: str, query: str, filename: str):
    """CSV에 논문 추가 or 업데이트 (인용수·상태 갱신)"""
    key = title.lower().strip()
    existing = log_dict.get(key)
    today = date.today().isoformat()

    if existing:
        # 인용수 업데이트, 상태는 downloaded 우선
        existing["citations"] = citations
        if status == "downloaded":
            existing["status"] = "downloaded"
            existing["filename"] = filename
        elif existing["status"] != "downloaded":
            existing["status"] = status
    else:
        log_dict[key] = {
            "title":      title,
            "year":       year,
            "citations":  citations,
            "arxiv_id":   arxiv_id or "",
            "status":     status,
            "query":      query,
            "date_found": today,
            "filename":   filename,
        }


# ── 파일명 생성 ───────────────────────────────────────────────────
def make_pdf_filename(title: str, year: int) -> str:
    clean = re.sub(r"[^\w\s]", " ", title)
    clean = re.sub(r"\s+", "_", clean.strip())
    clean = clean[:55].rstrip("_")
    return f"{year}_{clean}.pdf"


# ── 중복 확인 ─────────────────────────────────────────────────────
def existing_stems() -> set[str]:
    stems = set()
    for folder in [ARCHIVE, INBOX]:
        if folder.exists():
            for f in folder.iterdir():
                stems.add(f.stem.lower())
    return stems


# ── OpenAlex 검색 ────────────────────────────────────────────────
def search_openalex(
    query: str,
    min_citations: int,
    year_from: int,
    max_results: int,
) -> list[dict]:
    """
    OpenAlex 검색:
    - title.search + abstract.search 병합으로 커버리지 확대
    - 최근 연도(올해 포함)는 인용수 필터 자동 완화
    """
    from datetime import date
    current_year = date.today().year

    # 최근 1년 이내 검색이면 인용수 필터 자동 제거 (발표 직후라 인용수 적음)
    skip_citation_filter = (year_from >= current_year)
    if skip_citation_filter:
        log(f"  ※ {year_from}년 이후 검색 — 최신 논문은 인용수가 낮으므로 인용수 필터 해제")

    # title + abstract 양쪽 검색 (OR) → 커버리지 확대
    filters_title = [
        f"title.search:{query}",
        f"publication_year:>{year_from - 1}",
    ]
    filters_abstract = [
        f"abstract.search:{query}",
        f"publication_year:>{year_from - 1}",
    ]
    if not skip_citation_filter:
        filters_title.append(f"cited_by_count:>{min_citations - 1}")
        filters_abstract.append(f"cited_by_count:>{min_citations - 1}")

    # 최근 연도(올해)는 날짜순, 과거는 인용수순
    sort_by = "publication_date:desc" if skip_citation_filter else "cited_by_count:desc"

    all_results = {}   # title_lower → work (중복 제거)

    for filters in [filters_title, filters_abstract]:
        params = {
            "filter":   ",".join(filters),
            "sort":     sort_by,
            "per-page": 100,          # OpenAlex 최대 100 (키 없을 때)
            "select":   "title,publication_year,cited_by_count,ids,open_access,authorships",
            "mailto":   USER_EMAIL,
        }
        try:
            resp = requests.get(OPENALEX_URL, params=params, timeout=20)
            if resp.status_code == 200:
                for w in resp.json().get("results", []):
                    key = (w.get("title") or "").lower().strip()
                    if key and key not in all_results:
                        all_results[key] = w
        except Exception as e:
            log(f"  [OpenAlex 오류] {e}")

    # 정렬: 최근 연도는 연도+인용수, 과거는 인용수만
    results = list(all_results.values())
    if skip_citation_filter:
        results.sort(key=lambda w: (
            w.get("publication_year") or 0,
            w.get("cited_by_count") or 0
        ), reverse=True)
    else:
        results.sort(key=lambda w: w.get("cited_by_count") or 0, reverse=True)

    return results


# ── arXiv ID 추출 ─────────────────────────────────────────────────
def get_arxiv_id(work: dict) -> str | None:
    """OpenAlex work 딕셔너리에서 arXiv ID 추출"""
    ids = work.get("ids") or {}
    arxiv_url = ids.get("arxiv", "")
    if arxiv_url:
        # "https://arxiv.org/abs/2401.03006" → "2401.03006"
        m = re.search(r"arxiv\.org/abs/([^\s/v]+)", arxiv_url)
        if m:
            return m.group(1)
    return None


def get_oa_pdf_url(work: dict) -> str | None:
    """OpenAlex open_access 필드에서 PDF URL 추출"""
    oa = work.get("open_access") or {}
    return oa.get("oa_url") or None


# ── PDF 다운로드 ──────────────────────────────────────────────────
def download_via_arxiv(arxiv_id: str, dest: Path) -> bool:
    try:
        client = arxiv.Client()
        search = arxiv.Search(id_list=[arxiv_id.split("v")[0]])
        result = next(client.results(search), None)
        if result is None:
            return False
        result.download_pdf(dirpath=str(dest.parent), filename=dest.name)
        return dest.exists() and dest.stat().st_size > 1000
    except Exception as e:
        log(f"    [arXiv 오류] {e}")
        return False


def download_via_url(url: str, dest: Path) -> bool:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (research paper downloader)"}
        resp = requests.get(url, timeout=40, headers=headers, allow_redirects=True)
        if resp.status_code == 200 and b"%PDF" in resp.content[:20]:
            dest.write_bytes(resp.content)
            return dest.stat().st_size > 1000
    except Exception as e:
        log(f"    [URL 오류] {e}")
    return False


def find_arxiv_by_title(title: str, year: int) -> str | None:
    """제목으로 arXiv 검색해서 같은 논문의 preprint 버전 찾기"""
    try:
        # 제목에서 핵심 키워드만 추출 (괄호·콜론 뒤 제거)
        short_title = re.split(r"[:(]", title)[0].strip()
        client = arxiv.Client()
        search = arxiv.Search(
            query=f'ti:"{short_title}"',
            max_results=5,
            sort_by=arxiv.SortCriterion.Relevance,
        )
        for result in client.results(search):
            # 연도가 같거나 1년 차이 이내인 경우만 매칭
            if abs(result.published.year - year) <= 1:
                arxiv_id = result.entry_id.split("/")[-1].split("v")[0]
                log(f"    [arXiv 제목검색] 발견: {result.title[:50]} ({arxiv_id})")
                return arxiv_id
    except Exception as e:
        log(f"    [arXiv 제목검색 오류] {e}")
    return None


# ── 메인 ─────────────────────────────────────────────────────────
def fetch_papers(
    query: str,
    min_citations: int = DEFAULT_MIN_CITATIONS,
    year_from: int     = DEFAULT_YEAR_FROM,
    max_results: int   = DEFAULT_MAX_RESULTS,
    dry_run: bool      = False,
):
    log(f"\n{'='*62}")
    log(f"검색어  : '{query}'")
    log(f"필터    : 인용수 >= {min_citations}  |  연도 >= {year_from}  |  최대 {max_results}편")
    log(f"소스    : OpenAlex (무료, 키 불필요)")
    log(f"{'='*62}\n")

    log("OpenAlex 검색 중...")
    works = search_openalex(query, min_citations, year_from, max_results)

    if not works:
        log("검색 결과가 없습니다. 검색어나 필터를 조정해보세요.")
        return

    total_found = len(works)
    works = works[:max_results]
    log(f"검색 완료: 전체 {total_found}편 발견 → 상위 {len(works)}편 처리\n")
    if total_found > max_results:
        log(f"  (더 보려면 --max {min(total_found, 100)} 옵션 추가)\n")

    INBOX.mkdir(parents=True, exist_ok=True)
    existing  = existing_stems()
    paper_log = load_paper_log()   # CSV 로드

    downloaded, skipped, no_pdf_list = 0, 0, []

    for i, w in enumerate(works, 1):
        title     = (w.get("title") or "Unknown").strip()
        year      = w.get("publication_year") or 0
        citations = w.get("cited_by_count") or 0

        # 저자
        authorships = w.get("authorships") or []
        author_names = [
            (a.get("author") or {}).get("display_name", "")
            for a in authorships[:3]
        ]
        authors = ", ".join(n for n in author_names if n)
        if len(authorships) > 3:
            authors += " et al."

        arxiv_id = get_arxiv_id(w)
        oa_url   = get_oa_pdf_url(w)

        filename      = make_pdf_filename(title, year)
        filename_stem = Path(filename).stem.lower()

        log(f"[{i:02d}/{len(works)}] {title[:65]}")
        log(f"         {year}  |  인용 {citations:,}  |  {authors}")

        # 중복 체크 (_archive / _inbox 파일 기준)
        if filename_stem in existing:
            log(f"   ⏭  이미 존재 — 건너뜀\n")
            upsert_log(paper_log, title, year, citations, arxiv_id, "skipped", query, filename)
            skipped += 1
            continue

        if dry_run:
            src = f"arXiv:{arxiv_id}" if arxiv_id else ("OA URL" if oa_url else "없음")
            has = "✅" if (arxiv_id or oa_url) else "❌"
            log(f"   [DRY] {has} PDF:{src} → {filename}\n")
            upsert_log(paper_log, title, year, citations, arxiv_id, "manual_needed", query, filename)
            continue

        dest    = INBOX / filename
        success = False

        # 1순위: arXiv ID 직접 다운로드
        if arxiv_id:
            log(f"   📥 arXiv 다운로드... ({arxiv_id})")
            success = download_via_arxiv(arxiv_id, dest)

        # 2순위: OpenAlex OA URL
        if not success and oa_url:
            log(f"   📥 오픈액세스 다운로드...")
            success = download_via_url(oa_url, dest)

        # 3순위: arXiv 제목 검색으로 preprint 버전 탐색
        if not success and not arxiv_id:
            log(f"   🔍 arXiv 제목 검색 중...")
            found_id = find_arxiv_by_title(title, year)
            if found_id:
                success = download_via_arxiv(found_id, dest)

        if success:
            size_kb = dest.stat().st_size // 1024
            log(f"   ✅ 저장: {filename}  ({size_kb} KB)\n")
            existing.add(filename_stem)
            upsert_log(paper_log, title, year, citations, arxiv_id, "downloaded", query, filename)
            downloaded += 1
        else:
            log(f"   ❌ PDF 없음 — 수동 다운 필요\n")
            no_pdf_list.append(f"[{year}] {title[:60]}  (인용 {citations:,})")
            upsert_log(paper_log, title, year, citations, arxiv_id, "manual_needed", query, filename)

        time.sleep(0.3)

    # 요약
    log(f"{'='*62}")
    log(f"  다운로드  : {downloaded}편")
    log(f"  Skip(중복): {skipped}편")
    log(f"  PDF 없음  : {len(no_pdf_list)}편")
    log(f"{'='*62}")

    if no_pdf_list:
        log("\n수동 다운로드 필요:")
        for item in no_pdf_list:
            log(f"  - {item}")

    if downloaded > 0:
        log(f"\n저장 위치: {INBOX}")
        log("확인 후 '논문처리.bat' 실행하세요.")

    # CSV 저장 (항상)
    save_paper_log(paper_log)
    total_in_log = len(paper_log)
    log(f"\n📋 논문 로그 저장: {PAPER_LOG}  (누적 {total_in_log}편)")


# ── 인수 파싱 ─────────────────────────────────────────────────────
def parse_args():
    args    = sys.argv[1:]
    dry_run = "--dry" in args
    if "--dry" in args:
        args.remove("--dry")

    query_parts = []
    min_cit     = DEFAULT_MIN_CITATIONS
    year_from   = DEFAULT_YEAR_FROM
    max_res     = DEFAULT_MAX_RESULTS

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--min-citations" and i + 1 < len(args):
            min_cit = int(args[i + 1]); i += 2
        elif a == "--year-from" and i + 1 < len(args):
            year_from = int(args[i + 1]); i += 2
        elif a == "--max" and i + 1 < len(args):
            max_res = int(args[i + 1]); i += 2
        elif not a.startswith("--"):
            query_parts.append(a); i += 1
        else:
            i += 1

    return " ".join(query_parts), min_cit, year_from, max_res, dry_run


if __name__ == "__main__":
    query, min_cit, year_from, max_res, dry_run = parse_args()

    if not query:
        log("사용법: python paper_fetcher.py 검색어 [옵션]")
        log("")
        log("옵션:")
        log("  --min-citations N   최소 인용수  (기본: 30)")
        log("  --year-from YYYY    최소 연도    (기본: 2022)")
        log("  --max N             최대 결과 수 (기본: 20)")
        log("  --dry               다운로드 없이 목록만 출력")
        log("")
        log("예시:")
        log("  python paper_fetcher.py diffusion model time series")
        log("  python paper_fetcher.py heavy tailed distribution --min-citations 50")
        log("  python paper_fetcher.py transformer forecasting --year-from 2023 --dry")
        sys.exit(0)

    fetch_papers(query, min_cit, year_from, max_res, dry_run)
