"""
run_wiki.py
메인 실행 스크립트 — PDF로 Wiki 문서 두 개를 생성합니다.

사용법:
  python run_wiki.py <pdf_경로>      # PDF 하나 처리
  python run_wiki.py --all            # _inbox 폴더의 모든 PDF 일괄 처리

처리 완료된 PDF는 _archive 폴더로 이동됩니다.
이미 분석된 논문(같은 제목)은 자동으로 건너뜁니다.
"""
import sys
import io
import json
import shutil
import subprocess
from pathlib import Path
from datetime import date, datetime
from config import VAULT_PATH, TEMP_DIR

# Windows cp949 콘솔에서도 UTF-8로 출력
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# _inbox는 vault 상위 폴더(ResearchWiki)에 위치
INBOX = Path(VAULT_PATH).parent / "_inbox"
ARCHIVE = Path(VAULT_PATH).parent / "_archive"
LOG_FILE = Path(VAULT_PATH).parent / "_processed_log.json"


def make_filename(title: str, year: int) -> str:
    clean = "".join(c for c in title if c.isalnum() or c in " _-")
    clean = clean.strip().replace(" ", "_")[:50]
    return f"{year}_{clean}.md"


def run_ollama_preprocessing(pdf_path: str) -> dict:
    print("  [Step 1] Ollama 전처리 중...")
    result = subprocess.run(
        [sys.executable, "ollama_processor.py", pdf_path],
        capture_output=True,
        cwd=Path(__file__).parent
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return json.loads(result.stdout.decode("utf-8"))


def run_claude_analysis(data_file: str, filename: str):
    print("  [Step 2] Claude 분석 중...")
    result = subprocess.run(
        [sys.executable, "claude_analyzer.py", data_file, filename],
        cwd=Path(__file__).parent
    )
    if result.returncode != 0:
        raise RuntimeError("Claude 분석 실패")


def is_duplicate(filename: str) -> bool:
    """같은 제목의 brief 요약본이 이미 있으면 중복으로 판단"""
    return (Path(VAULT_PATH) / "papers" / "brief" / filename).exists()


def archive_pdf(pdf_path: Path):
    """처리 완료된 PDF를 _archive로 이동"""
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE / pdf_path.name
    # 동일 이름 존재 시 덮어쓰기
    if dest.exists():
        dest.unlink()
    shutil.move(str(pdf_path), str(dest))


def log_processed(title: str, filename: str, status: str):
    """처리 기록을 _processed_log.json에 추가"""
    log = []
    if LOG_FILE.exists():
        try:
            log = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            log = []
    log.append({
        "date": datetime.now().isoformat(timespec="seconds"),
        "title": title,
        "filename": filename,
        "status": status,
    })
    LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def process_one(pdf_path: Path, move_to_archive: bool = True) -> str:
    """PDF 하나 처리. 반환: 'ok' | 'duplicate' | 'error'"""
    print(f"\n📄 {pdf_path.name}")
    try:
        preprocessed = run_ollama_preprocessing(str(pdf_path))
    except Exception as e:
        print(f"  ❌ 전처리 실패: {e}")
        log_processed(pdf_path.name, "", "error")
        return "error"

    meta = preprocessed["metadata"]
    title = meta.get("title", "paper")
    filename = make_filename(title, meta.get("year", date.today().year))
    print(f"  제목: {title}")

    if is_duplicate(filename):
        print(f"  ⏭️  이미 분석됨 → 건너뜀 ({filename})")
        if move_to_archive:
            archive_pdf(pdf_path)
        log_processed(title, filename, "duplicate")
        return "duplicate"

    tmp_data_file = str(Path(TEMP_DIR) / "paper_preprocessed.json")
    Path(tmp_data_file).write_text(
        json.dumps(preprocessed, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    try:
        run_claude_analysis(tmp_data_file, filename)
    except Exception as e:
        print(f"  ❌ 분석 실패: {e}")
        log_processed(title, filename, "error")
        return "error"

    if move_to_archive:
        archive_pdf(pdf_path)
    log_processed(title, filename, "ok")
    print(f"  ✅ 완료 → {filename}")
    return "ok"


def process_all_inbox():
    """_inbox의 모든 PDF 일괄 처리"""
    if not INBOX.exists():
        print(f"_inbox 폴더가 없습니다: {INBOX}")
        sys.exit(1)
    pdfs = sorted(INBOX.glob("*.pdf"))
    if not pdfs:
        print(f"_inbox에 처리할 PDF가 없습니다: {INBOX}")
        return

    print(f"총 {len(pdfs)}개 PDF 발견. 일괄 처리 시작...\n" + "=" * 60)
    counts = {"ok": 0, "duplicate": 0, "error": 0}
    for pdf in pdfs:
        counts[process_one(pdf)] += 1

    print("\n" + "=" * 60)
    print(f"일괄 처리 완료: 성공 {counts['ok']} / 중복 {counts['duplicate']} / 실패 {counts['error']}")
    print(f"처리된 PDF는 _archive로 이동되었습니다: {ARCHIVE}")


def main():
    if len(sys.argv) < 2:
        print("사용법:")
        print("  python run_wiki.py <pdf_경로>   # PDF 하나 처리")
        print("  python run_wiki.py --all        # _inbox 전체 일괄 처리")
        sys.exit(1)

    if sys.argv[1] == "--all":
        process_all_inbox()
        return

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"파일을 찾을 수 없습니다: {pdf_path}")
        sys.exit(1)
    process_one(pdf_path)


if __name__ == "__main__":
    main()
