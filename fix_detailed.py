"""
fix_detailed.py
brief는 정상이지만 detailed가 비어있는 논문들을 찾아서 Ollama로 재생성.

기존 ollama_processor.py는 섹션 감지 실패 시 내용이 없는 파일을 생성합니다.
이 스크립트는 섹션 감지 없이 전체 PDF 텍스트를 Ollama에 직접 넣어 상세 요약을 생성합니다.

사용법:
  python fix_detailed.py           # 자동 감지 (3KB 미만 파일 대상)
  python fix_detailed.py --dry     # 대상 목록만 출력, 실제 처리 안 함
  python fix_detailed.py --size 5  # 5KB 미만을 기준으로 감지 (기본 3)

동작:
  1. detailed/ 폴더에서 크기가 작은(내용 없는) 파일 자동 감지
  2. 각 파일 frontmatter의 source_pdf 경로로 PDF 텍스트 추출
  3. 전체 텍스트를 Ollama에 직접 전달 → 상세 요약 생성
  4. 기존 파일 frontmatter 유지하고 본문만 교체
  5. brief는 절대 건드리지 않음
"""
import re
import sys
import io
import os
import json
import ollama
import pymupdf4llm
from pathlib import Path

from config import VAULT_PATH, OLLAMA_MODEL

# Windows cp949 콘솔 UTF-8 강제
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

VAULT        = Path(VAULT_PATH)
DETAILED_DIR = VAULT / "papers" / "detailed"

DRY_RUN = "--dry" in sys.argv

# 크기 임계값 파싱 (기본 3KB)
SIZE_KB = 3
for i, arg in enumerate(sys.argv):
    if arg == "--size" and i + 1 < len(sys.argv):
        try:
            SIZE_KB = int(sys.argv[i + 1])
        except ValueError:
            pass

# 생성할 상세 요약 프롬프트
DETAILED_PROMPT = """다음 학술 논문의 전체 내용을 한국어로 상세하게 요약하세요.

논문 텍스트:
{text}

아래 형식으로 출력하세요. 코드 펜스(```) 없이 마크다운만 출력하세요.

## Abstract

- **핵심 문제**: (논문이 해결하려는 주요 문제)
- **제안 방법**: (사용된 방법론 또는 접근법)
- **핵심 성과**: (주요 발견 사항이나 결과 요약)

---

## Introduction

| 항목 | 내용 |
|------|------|
| 연구 배경 | (왜 이 연구가 필요한가) |
| 기존 한계 | (기존 방법의 문제점) |
| 핵심 기여 | (이 논문의 새로운 점) |

💡 **Insight**: (Introduction에서 얻을 수 있는 핵심 시사점)

---

## Methodology

| 항목 | 내용 |
|------|------|
| 핵심 방법 | (제안하는 방법의 핵심) |
| 아키텍처 | (모델/시스템 구조) |
| 학습 방식 | (학습 목적함수, 알고리즘 등) |

💡 **Insight**: (방법론에서 얻을 수 있는 핵심 시사점)

---

## Experiments & Results

| 항목 | 내용 |
|------|------|
| 데이터셋 | (사용한 데이터) |
| 비교 기준 | (베이스라인 방법들) |
| 주요 결과 | (핵심 수치나 성능 비교) |

💡 **Insight**: (실험 결과에서 얻을 수 있는 핵심 시사점)

---

## Conclusion

| 항목 | 내용 |
|------|------|
| 핵심 결론 | (논문의 결론 요약) |
| 한계점 | (논문이 인정하는 한계) |
| 향후 연구 | (제안하는 미래 연구 방향) |

💡 **Insight**: (결론에서 얻을 수 있는 핵심 시사점)
"""


def log(msg: str):
    print(msg, flush=True)


# ── frontmatter 파싱 ─────────────────────────────────────────────
def get_frontmatter_block(text: str) -> str:
    """원본 frontmatter 블록 전체 반환 (--- ... --- 포함)"""
    m = re.match(r"^(---\n.*?\n---)", text, re.DOTALL)
    return m.group(1) if m else ""


def extract_source_pdf(text: str) -> str:
    """frontmatter에서 source_pdf 경로 추출"""
    m = re.search(r'^source_pdf:\s*["\']?(.+?)["\']?\s*$', text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def extract_brief_stem(text: str) -> str:
    """frontmatter에서 brief 파일명(stem) 추출"""
    m = re.search(r'brief:\s*"\[\[papers/brief/([^\]]+)\]\]"', text)
    return m.group(1) if m else ""


# ── PDF 텍스트 추출 ──────────────────────────────────────────────
def extract_pdf_text(pdf_path: str) -> str:
    """pymupdf4llm으로 PDF → 마크다운 텍스트 추출"""
    # pymupdf4llm이 stdout에 로그를 출력하므로 임시 리다이렉트
    saved_stdout_fd = os.dup(1)
    try:
        os.dup2(2, 1)
        text = pymupdf4llm.to_markdown(pdf_path)
    finally:
        os.dup2(saved_stdout_fd, 1)
        os.close(saved_stdout_fd)
    return text


# ── Ollama 상세 요약 생성 ────────────────────────────────────────
def generate_detailed_with_ollama(pdf_path: str) -> str:
    """PDF 전체 텍스트 → Ollama로 상세 요약 생성"""
    log(f"    PDF 텍스트 추출 중...")
    text = extract_pdf_text(pdf_path)

    if not text or len(text) < 100:
        log(f"    ⚠️  PDF 텍스트 추출 실패 또는 너무 짧음 ({len(text)}자)")
        return ""

    # References 이후 제거
    ref_pos = re.search(r'\n#{1,2}\s*References?\s*\n', text, re.IGNORECASE)
    if ref_pos:
        text = text[:ref_pos.start()]

    # 최대 12000자로 제한 (Ollama 컨텍스트 고려)
    text_trimmed = text[:12000]
    if len(text) > 12000:
        log(f"    텍스트 {len(text):,}자 → 12,000자로 트리밍")

    log(f"    Ollama 상세 요약 생성 중... ({len(text_trimmed):,}자 입력)")
    prompt = DETAILED_PROMPT.format(text=text_trimmed)

    resp = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp["message"]["content"].strip()


# ── detailed 파일 재생성 ─────────────────────────────────────────
def rebuild_detailed(detail_path: Path) -> bool:
    """기존 frontmatter 유지하고 Ollama 생성 본문으로 교체"""
    original = detail_path.read_text(encoding="utf-8", errors="ignore")
    fm_block   = get_frontmatter_block(original)
    pdf_path   = extract_source_pdf(original)
    brief_stem = extract_brief_stem(original) or detail_path.stem

    if not pdf_path:
        log("    ⚠️  source_pdf 없음 → 건너뜀")
        return False

    if not Path(pdf_path).exists():
        log(f"    ⚠️  PDF 파일 없음: {pdf_path}")
        return False

    body = generate_detailed_with_ollama(pdf_path)
    if not body:
        return False

    # 새 파일 조립: 기존 frontmatter + brief 링크 + Ollama 생성 본문 + 하단 링크
    source_pdf_uri = pdf_path.replace("\\", "/").replace(" ", "%20")
    new_content = (
        fm_block
        + f"\n\n> 개념·논문 연결은 [[papers/brief/{brief_stem}|brief 요약본]] 참고"
        + f"\n> 📄 원본 PDF: [열기](file:///{source_pdf_uri})"
        + "\n\n"
        + body
        + f"\n\n---\n\n> 관련 논문·개념 연결은 [[papers/brief/{brief_stem}|brief 요약본]]에서 확인하세요.\n"
    )

    if not DRY_RUN:
        detail_path.write_text(new_content, encoding="utf-8")
    return True


# ── 메인 ─────────────────────────────────────────────────────────
def main():
    if not DETAILED_DIR.exists():
        log(f"detailed 폴더 없음: {DETAILED_DIR}")
        return

    threshold_bytes = SIZE_KB * 1024
    candidates = [
        p for p in sorted(DETAILED_DIR.glob("*.md"))
        if p.stat().st_size < threshold_bytes
    ]

    if not candidates:
        log(f"✅  {SIZE_KB}KB 미만 파일 없음 — 모든 detailed 정상입니다.")
        return

    log(f"{'[DRY RUN] ' if DRY_RUN else ''}broken detailed 파일 {len(candidates)}개 발견 (기준: {SIZE_KB}KB 미만)\n")

    ok = 0
    skip = 0
    fail = 0

    for i, detail_path in enumerate(candidates, 1):
        log(f"[{i}/{len(candidates)}] {detail_path.name}")

        if DRY_RUN:
            pdf_path = extract_source_pdf(
                detail_path.read_text(encoding="utf-8", errors="ignore")
            )
            log(f"    [DRY] PDF: {Path(pdf_path).name if pdf_path else '없음'}")
            ok += 1
            log("")
            continue

        success = rebuild_detailed(detail_path)
        if success:
            size_kb = round(detail_path.stat().st_size / 1024, 1)
            log(f"    ✅  재생성 완료 ({size_kb}KB)")
            ok += 1
        else:
            fail += 1

        log("")

    log("=" * 55)
    log(f"{'[DRY RUN] ' if DRY_RUN else ''}완료: 성공 {ok} / 건너뜀 {skip} / 실패 {fail}")
    if not DRY_RUN and ok > 0:
        log("\n💡 brief는 변경되지 않았습니다.")


if __name__ == "__main__":
    main()
