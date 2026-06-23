"""
normalize_vault.py
기존 Vault의 개념 이름을 표준(Title Case + 공백)으로 통일하고,
주제(topic)와 중복되는 개념 노트를 제거하며, 모든 위키 링크를 갱신한다.

일회성 정리 + 재실행해도 안전(idempotent).
  python normalize_vault.py
"""
import re
from pathlib import Path
from config import VAULT_PATH


def normalize_concept_name(name: str) -> str:
    """개념 이름을 표준형(Title Case + 공백)으로 변환.

    규칙:
      - 이미 공백이 있으면 그대로 (복합어, 예: 'Heavy-Tailed Distribution')
      - 비ASCII 포함 시 그대로 (예: 'γ-Divergence')
      - 공백 없고 하이픈으로 단어가 구분되면 하이픈→공백 (예: 'Sentiment-Analysis'→'Sentiment Analysis')
      - 그 외(단일 토큰/약어: 'FinBERT', 'LSTM')는 그대로
    """
    name = name.strip()
    if " " in name:
        return name
    if not name.isascii():
        return name
    if "-" in name:
        return name.replace("-", " ")
    return name


def collect_md_files() -> list[Path]:
    vault = Path(VAULT_PATH)
    files = []
    for sub in [
        "papers/brief", "papers/detailed", "concepts", "topics",
        "sessions", "gaps", "study-logs", "writing", "journals", "my_notes",
    ]:
        d = vault / sub
        if d.exists():
            files.extend(p for p in d.glob("*.md") if not p.name.startswith("_"))
    return files


def rewrite_links_in_file(path: Path, topic_names: set[str]):
    """파일 내 [[link]] 중 경로 없는 개념 링크를 정규화."""
    text = path.read_text(encoding="utf-8", errors="ignore")

    def repl(m):
        target = m.group(1)
        alias = m.group(2) or ""
        if "/" in target:  # 경로 링크(papers/...)는 건드리지 않음
            return m.group(0)
        norm = normalize_concept_name(target)
        return f"[[{norm}{alias}]]"

    new_text = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", repl, text)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def normalize_concept_files(topic_names_lower: set[str]):
    """concepts/ 파일명을 정규화하고, 주제와 겹치면 삭제(병합)."""
    concepts_dir = Path(VAULT_PATH) / "concepts"
    if not concepts_dir.exists():
        return
    for p in list(concepts_dir.glob("*.md")):
        norm = normalize_concept_name(p.stem)

        # 주제와 이름이 겹치는 개념 → 삭제 (주제 MOC가 대신 hub 역할)
        if norm.lower() in topic_names_lower:
            p.unlink()
            print(f"  - 개념 삭제(주제와 중복): {p.name}")
            continue

        # 이름이 바뀌어야 하면 rename (대상이 이미 있으면 원본 삭제로 병합)
        if norm != p.stem:
            target = concepts_dir / f"{norm}.md"
            if target.exists():
                p.unlink()
                print(f"  - 개념 병합: {p.name} → {target.name}")
            else:
                p.rename(target)
                print(f"  ~ 개념 이름변경: {p.name} → {target.name}")


def main():
    topics_dir = Path(VAULT_PATH) / "topics"
    topic_names = {p.stem for p in topics_dir.glob("*.md")} if topics_dir.exists() else set()
    topic_names_lower = {t.lower() for t in topic_names}

    print("[1/2] 모든 파일의 위키 링크 정규화...")
    changed = 0
    for f in collect_md_files():
        if rewrite_links_in_file(f, topic_names):
            changed += 1
    print(f"  링크 갱신된 파일: {changed}개")

    print("[2/2] 개념 파일명 정규화 및 주제 중복 제거...")
    normalize_concept_files(topic_names_lower)

    print("\n완료. Obsidian Graph View를 새로고침하세요.")


if __name__ == "__main__":
    main()
