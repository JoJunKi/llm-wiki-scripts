# LLM Wiki 사용법

Obsidian + Claude Code + Ollama 로 연구 DB를 자동 구축하는 시스템.
모든 지식 활동(논문 읽기, 직접 작성, 대화)이 하나의 그래프로 연결된다.

---

## 전체 흐름

```
논문 PDF         →  run_wiki.py      →  papers/brief/ + papers/detailed/
직접 작성 노트   →  Obsidian에서 직접  →  concepts/ or my_notes/
세션 대화        →  자동 (Stop Hook)  →  sessions/
                                          ↓ ↓ ↓
                              모두 [[개념]] 링크로 연결
                              Obsidian Graph View에서 시각화
```

---

## Flow 1: 논문 PDF → 자동 요약

### 기본 사용

```powershell
cd C:\Users\USER\llm-wiki-scripts

# PDF 하나 처리
python run_wiki.py "C:\경로\논문.pdf"

# _inbox 폴더에 넣고 일괄 처리 (권장)
python run_wiki.py --all
```

### _inbox 활용 (권장 루틴)

```
1. PDF를 _inbox 폴더에 복사
   경로: C:\Users\USER\Documents\ResearchWiki\_inbox\

2. 명령어 한 줄 실행
   python run_wiki.py --all

3. Obsidian Graph View 새로고침
```

### 자동으로 생성되는 것

| 생성 파일 | 위치 | 담당 |
|-----------|------|------|
| 상세 요약 | `papers/detailed/` | Ollama (무료) |
| 핵심 요약 | `papers/brief/` | Claude (구독) |
| 주제 MOC | `topics/` | 자동 (없으면 신규 생성) |
| 개념 stub | `concepts/` | 자동 (없으면 신규 생성) |
| 처리 기록 | `_processed_log.json` | 자동 |

- 중복 논문은 자동 스킵
- 처리된 PDF는 `_archive/`로 자동 이동

---

## Flow 2: 세션 대화 → 자동 저장

### 자동 저장 (Stop Hook)

**Claude Code 세션이 끝날 때마다 자동으로 실행됩니다.**
별도로 명령어를 실행할 필요 없음.

- 저장 위치: `sessions/날짜_제목.md`
- Ollama만 사용 (무료, 빠름)
- 같은 세션 재실행 시 자동 덮어쓰기

### 고품질 저장 (중요한 세션일 때)

```powershell
# Ollama Map + Claude Reduce (품질 높음, 구독 사용)
python save_session.py --claude

# 제목 직접 지정
python save_session.py --claude --title "Diffusion 모델 연구 방향 논의"

# 세션 타입 지정 (자동 감지가 틀렸을 때)
python save_session.py --claude --type research   # 논문·이론 논의
python save_session.py --claude --type dev        # 코드·구현 작업
python save_session.py --claude --type mixed      # 혼합

# 특정 JSONL 파일 지정
python save_session.py --claude "C:\Users\USER\.claude\projects\프로젝트\세션ID.jsonl"
```

### 세션 파일에 포함되는 내용

```yaml
title: "세션 제목"
session_type: research / dev / mixed
summary: "전체 대화 2-3문장 요약"
key_decisions:
  - 결정사항
ideas:
  - 아이디어 / 인사이트
related_concepts: [[Diffusion Models]] | [[Heavy-Tailed Distribution]]
related_papers:
  - [[2025_Cauchy_Diffusion_...]]
```

중간 청크 요약 확인: `sessions/_last_chunks.txt`

---

## Flow 3: 직접 작성 노트 → 그래프 연결

Obsidian에서 직접 작성한 노트도 `[[링크]]`만 쓰면 자동으로 그래프에 연결됩니다.

### 작성 규칙

```markdown
# 내 생각 노트

[[Diffusion Models]] 관련해서 오늘 새로운 아이디어가 생겼다.
[[Heavy-Tailed Distribution]]을 금융 데이터에 적용하면...

관련 논문: [[2025_Cauchy_Diffusion_A_Heavy-tailed_Denoising_Diffusio]]
```

- 개념 이름: Title Case + 공백 (`Diffusion Models`, `Time Series`)
- 약어·고유명은 원형 유지 (`FinBERT`, `LSTM`)

### 저장 위치 권장

| 노트 종류 | 권장 폴더 |
|-----------|-----------|
| Research Gap 아이디어 | `gaps/` |
| 글쓰기 초안 (블로그·초록) | `writing/` |
| 스터디 발표 기록 | `study-logs/` |
| 저널 분석 | `journals/` |
| 자유 메모 | `my_notes/` (없으면 직접 생성) |

### 링크 정규화 (케밥-case 등 정리할 때)

```powershell
python normalize_vault.py
```

- 모든 `[[kebab-case]]` → `[[Title Case]]` 변환
- 주제(topic)와 중복되는 개념 노트 자동 제거
- 평소엔 불필요 — 수동 편집을 많이 한 후에만 실행

---

## Flow 4: 직접 작성 / 외부 파일 투입 → 연결

### Obsidian에서 직접 노트 작성 후

```powershell
python connect_vault.py
```

- `gaps/`, `study-logs/`, `writing/`, `journals/` 등 **전체 vault 스캔**
- `[[링크]]`가 있는 개념 중 stub 없는 것 자동 생성
- 기존 concept 노트에 "등장 노트" 섹션 자동 추가
- 링크 이름 정규화 (kebab-case → Title Case)

### 스터디원 파일을 폴더에 복사했을 때

```
1. 파일을 해당 폴더에 복사
   - 논문 brief/detailed → papers/brief/, papers/detailed/
   - 개념 노트 → concepts/
   - 스터디 발표 기록 → study-logs/

2. python connect_vault.py
   → 복사된 파일의 [[링크]]를 그래프에 연결
```

### 변경 없이 미리 확인만 할 때

```powershell
python connect_vault.py --dry
```

---

## 폴더 구조

```
C:\Users\USER\Documents\ResearchWiki\
├── _inbox\              ← PDF 여기에 넣기
├── _archive\            ← 처리 완료 PDF (자동 이동)
├── _processed_log.json  ← 처리 기록
└── Papaer\              ← Obsidian Vault
    ├── papers\
    │   ├── brief\       ← 핵심 요약 (그래프 허브) ★
    │   └── detailed\    ← 섹션별 상세 분석
    ├── concepts\        ← 개념 카드 (자동 생성 + 직접 작성)
    ├── topics\          ← 주제 MOC (자동 생성)
    ├── sessions\        ← 세션 대화 요약 (자동 생성)
    ├── gaps\            ← Research Gap 모음
    ├── journals\        ← 타겟 저널 분석
    ├── study-logs\      ← 스터디 발표 기록
    ├── writing\         ← 글쓰기 초안
    └── HOME.md          ← 전체 진입점
```

---

## 스크립트 역할 요약

| 스크립트 | 역할 | 언제 |
|----------|------|------|
| `run_wiki.py` | PDF → brief + detailed + MOC + 개념 stub | 논문 추가할 때 |
| `save_session.py` | 세션 대화 → sessions/ | 배치파일 / 23:30 예약 |
| `connect_vault.py` | 전체 vault 스캔 → 누락 링크 연결 | 직접 작성 / 외부 파일 복사 후 |
| `normalize_vault.py` | 링크 이름 일괄 정규화 + 중복 개념 제거 | 대규모 정리가 필요할 때 |
| `vault_indexer.py` | 기존 Vault 스캔 (내부용) | 직접 실행 불필요 |

---

## 일상 루틴

```
논문 PDF가 생겼을 때:
  PDF → _inbox → python run_wiki.py --all

Obsidian에서 직접 글 쓰거나 외부 파일 복사했을 때:
  python connect_vault.py

중요한 Claude Code 세션이 끝났을 때:
  바탕화면 '세션저장.bat' 더블클릭  (또는: python save_session.py --today --claude)

평상시 세션은:
  23:30 예약 작업이 자동으로 Ollama 저장

Obsidian:
  Graph View → 개념·논문·세션·갭 노트 연결 확인
  HOME.md   → Dataview로 전체 논문 목록 확인
```

---

## 모델 설정 (`config.py`)

```python
VAULT_PATH          = "C:/Users/USER/Documents/ResearchWiki/Papaer"
OLLAMA_MODEL        = "qwen2.5:7b"       # 논문 처리용
OLLAMA_SESSION_MODEL = "exaone3.5:7.8b"  # 세션 요약용 (한국어 특화)
```

모델 교체 시 `config.py`만 수정하면 됩니다.
