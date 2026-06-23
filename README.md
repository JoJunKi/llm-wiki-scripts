# LLM Wiki — 논문 PDF → Obsidian 자동 정리 시스템

PDF 논문을 넣으면 자동으로 Obsidian 위키 노트 2개(요약본 brief + 상세본 detailed)를 만들고,
주제·개념별로 분류·연결해주는 시스템.

## 1. 개요

**파이프라인:**
```
PDF → [Ollama(로컬): 텍스트추출·메타데이터·섹션분리] → JSON
    → [Claude Code: 핵심분석·개념연결] → brief.md + detailed.md → Obsidian Vault
```

**역할 분담:**
- **Ollama (로컬, 무료)** = 잡일(PDF 파싱·구조화)
- **Claude Code (구독)** = 핵심 분석. **API 키 불필요** — `claude -p` CLI가 구독 인증으로 동작

---

## 2. 빠른 시작

### Step 1 — LLM 백엔드 선택 후 설치

먼저 어떤 LLM을 쓸지 결정:

| 상황 | 선택 |
|------|------|
| 로컬 GPU 있음 (VRAM 8GB+) | **Ollama** (무료, 오프라인) |
| 노트북 / GPU 없음 | **Claude Code 구독** 또는 **OpenAI API** |

---

#### 공통 필수 설치

| 항목 | 설치 방법 | 확인 |
|------|-----------|------|
| Python 3.10+ | [python.org](https://python.org) | `python --version` |
| Obsidian | [obsidian.md](https://obsidian.md) — Vault 경로: `~/Documents/ResearchWiki/Papaer` | — |

---

#### A. Ollama 사용 (로컬, 무료)

```bash
# 1) Ollama 설치: https://ollama.com
# 2) 모델 다운 (택 1)
ollama pull exaone3.5:7.8b    # 한국어 특화
ollama pull qwen2.5:14b       # 다국어 범용
```

`config.py`:
```python
OLLAMA_MODEL = "exaone3.5:7.8b"   # 다운받은 모델명
```

---

#### B. Claude Code 사용 (구독 필요, Ollama 설치 불필요)

```bash
# Claude Code 설치: https://claude.ai/code
claude -p "hello"   # 로그인 후 응답 오면 OK
```

`claude_analyzer.py`와 Ollama 호출 파일들의 교체 방법 → [섹션 11](#11-다른-llm으로-교체하기)

---

#### C. OpenAI API 사용 (API 키 필요, Ollama 설치 불필요)

```bash
set OPENAI_API_KEY=sk-...
```

`claude_analyzer.py`와 Ollama 호출 파일들의 교체 방법 → [섹션 11](#11-다른-llm으로-교체하기)

### Step 2 — 레포 클론 및 설정

```bash
git clone https://github.com/JoJunKi/llm-wiki-scripts.git
cd llm-wiki-scripts
pip install -r requirements.txt
python setup.py          # 바탕화면에 .bat 파일 자동 생성
```

`config.py` 열어서 모델명 확인/수정:
```python
OLLAMA_MODEL   = "exaone3.5:7.8b"   # 본인이 pull한 모델명
OPENALEX_EMAIL = ""                   # 선택 — 있으면 논문검색 응답 빠름
```

### Step 3 — 동작 확인

```bash
# 바탕화면의 논문검색.bat 실행 후
# Query + options: diffusion time series --dry
# 결과 목록 나오면 OK
```

---

## 3. 폴더 구조

```
~/llm-wiki-scripts/          ← 스크립트 (코드)
   config.py
   ollama_processor.py
   claude_analyzer.py
   prompts.py
   vault_indexer.py
   run_wiki.py
   normalize_vault.py
   CLAUDE.md

~/Documents/ResearchWiki/    ← 데이터
   _inbox/        ← 처리할 PDF를 여기에 넣음
   _archive/      ← 처리 끝난 PDF 자동 이동
   _processed_log.json
   <Vault>/       ← Obsidian Vault
      papers/brief/      ← 요약본 (그래프 hub)
      papers/detailed/   ← 상세본
      topics/            ← 주제 MOC (자동 생성)
      concepts/          ← 개념 노트 (자동 생성)
```

---

## 4. 설정 — `config.py`만 본인 환경에 맞게 수정

```python
VAULT_PATH   = "본인 Obsidian Vault 절대경로"
OLLAMA_MODEL = "qwen2.5:7b"   # 설치한 모델명
OUTPUT_LANG  = "korean"
```
- `_inbox` / `_archive`는 코드가 **Vault 상위 폴더**에 자동 생성 (`VAULT_PATH.parent / "_inbox"`)

---

## 5. 핵심 설계 원칙 (그대로 따라야 그래프가 깔끔함)

1. **brief가 그래프 hub** — `[[개념]]` 링크는 **brief에만** 넣음. detailed는 brief로만 연결.
   (노드가 두 개로 갈라지는 것 방지)
2. **개념 이름 표준 = Title Case + 공백** (`Sentiment Analysis`, `Time Series Forecasting`).
   - 약어·고유명은 원형 유지 (`FinBERT`, `LSTM`, `γ-Divergence`, `Student-t Distribution`)
3. **주제와 개념 중복 금지** — 주제(MOC)가 이미 hub이므로 같은 이름의 개념 노트는 만들지 않음
4. **자동 정규화** — Claude가 kebab-case를 내보내도 저장 직전 `normalize_brief_links()`가
   표준형으로 강제 변환 → 재발 방지

---

## 6. Windows 주의사항 (코드에 이미 반영됨)

- 콘솔 cp949 인코딩 → 모든 출력 UTF-8 강제 (`io.TextIOWrapper`, `stdout.buffer.write`)
- pymupdf4llm이 stdout 오염 → 파일 디스크립터 리다이렉트(`os.dup2(2,1)`)로 차단
- 진행 로그는 stderr로, 데이터(JSON)는 stdout으로 분리

---

## 7. 평소 사용법

```
# 1) PDF를 _inbox에 넣고
cd ~/llm-wiki-scripts
python run_wiki.py --all          # 일괄 처리 (중복 자동 스킵, PDF는 _archive로 이동)

# 또는 하나만
python run_wiki.py "경로/논문.pdf"

# 2) Obsidian Graph View 새로고침
```

처리된 기록은 `_processed_log.json`에 누적됨.

---

## 8. 스크립트 역할 요약

| 파일 | 역할 |
|------|------|
| `config.py` | Vault 경로, Ollama 모델, 임시 폴더 설정 |
| `ollama_processor.py` | PDF 텍스트 추출 + 메타데이터 + 섹션 분리 (로컬) |
| `prompts.py` | Claude에 전달할 brief/detailed 프롬프트 템플릿 |
| `vault_indexer.py` | 기존 개념·주제·논문 인덱싱 (그래프 연결성 확보용 컨텍스트) |
| `claude_analyzer.py` | `claude -p` 호출 → 분석 → 저장 + MOC/개념 stub 자동 생성·정규화 |
| `run_wiki.py` | 메인 실행. 일괄 처리 + 중복 검사 + 아카이브 + 로그 |
| `normalize_vault.py` | (선택) 기존 개념 이름 일괄 정리용. 후처리 자동 정규화가 있어 평소엔 불필요 |

---

## 9. 권장 Obsidian 플러그인

- **Dataview** — 주제 MOC의 자동 논문 목록 쿼리 활성화
- Graph View로 논문 ↔ 개념 ↔ 주제 연결 시각화

---

## 10. 모델 변경 (선택)

기본은 Claude Code 구독의 기본 모델을 따름. 고정하려면 `claude_analyzer.py`의
`call_claude_cli`에서 `--model` 옵션 추가:

```python
["claude", "-p", "--model", "opus"]   # 또는 "sonnet"
```
- 분석 품질 우선: `opus`
- 속도·비용 효율: `sonnet`

---

## 11. 다른 LLM으로 교체하기

이 시스템의 LLM 호출 지점은 두 군데:

| 역할 | 현재 사용 | 호출 위치 |
|------|-----------|-----------|
| brief 핵심 분석 | Claude Code (`claude -p`) | `claude_analyzer.py` → `call_claude_cli()` |
| PDF 파싱·검색·개념정리·Gap 분석 | Ollama (로컬) | `ollama_processor.py`, `vault_search.py`, `connect_vault.py`, `gap_finder.py` → `ollama.chat()` |

**두 군데 모두 독립적으로 교체 가능.** Ollama를 Codex/Claude Code/OpenAI로 바꾸거나,
Claude Code를 Ollama로 바꾸거나, 둘 다 같은 API로 통일하는 것도 가능.

### Ollama 호출 교체 방법

`ollama.chat()` 쓰는 파일들(`ollama_processor.py`, `vault_search.py`, `connect_vault.py`, `gap_finder.py`)에서
아래 함수를 원하는 백엔드로 교체하면 됨:

```python
# 기존 (Ollama)
import ollama
resp = ollama.chat(model=OLLAMA_MODEL, messages=[...])
text = resp["message"]["content"]

# → OpenAI로 교체
from openai import OpenAI
client = OpenAI()
resp = client.chat.completions.create(model="gpt-4o", messages=[...])
text = resp.choices[0].message.content

# → Anthropic API로 교체
import anthropic
client = anthropic.Anthropic()
resp = client.messages.create(model="claude-sonnet-4-6", max_tokens=2048, messages=[...])
text = resp.content[0].text

# → Codex CLI로 교체
result = subprocess.run(["codex", "-p"], input=prompt.encode(), capture_output=True)
text = result.stdout.decode()
```

> **주의:** Ollama는 로컬 무료지만 Claude Code(`claude -p`) 구독이나 OpenAI API는 토큰 비용 발생.
> PDF 파싱은 논문당 수십 회 LLM 호출 → 비용 민감한 작업에는 Ollama 유지 권장.

Claude Code(`claude -p`) 의존 부분은 `claude_analyzer.py`의 `call_claude_cli()` 함수 **하나뿐**.
나머지(Ollama, PDF 파싱, 검색, Gap 분석)는 독립적으로 동작.

### 옵션 A — Anthropic API 직접 사용 (Claude, API 키 방식)

`config.py`에 추가:
```python
# config.py
ANTHROPIC_API_KEY = "sk-ant-..."   # 환경변수로 설정해도 됨
```

환경변수 설정 후 실행하면 자동으로 API 모드로 전환됨:
```
set ANTHROPIC_API_KEY=sk-ant-...
python run_wiki.py --all
```
> `claude_analyzer.py`가 `ANTHROPIC_API_KEY` 유무를 감지해 CLI/API 모드 자동 선택.

---

### 옵션 B — OpenAI API (GPT-4o 등)

`claude_analyzer.py`의 `call_claude_cli()` 교체:

```python
# pip install openai
from openai import OpenAI
client = OpenAI()   # OPENAI_API_KEY 환경변수 자동 인식

def call_claude_cli(prompt: str) -> str:
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2048,
    )
    return resp.choices[0].message.content.strip()
```

---

### 옵션 C — OpenAI Codex CLI

```python
def call_claude_cli(prompt: str) -> str:
    result = subprocess.run(
        ["codex", "-p"],
        input=prompt.encode("utf-8"),
        capture_output=True,
        timeout=600,
    )
    return result.stdout.decode("utf-8").strip()
```
> Codex CLI 출력 형식에 따라 파싱 조정 필요할 수 있음.

---

### 옵션 D — Ollama 전용 (완전 무료·오프라인)

`claude_analyzer.py`의 `call_claude_cli()` 교체:

```python
import ollama
from config import OLLAMA_MODEL

def call_claude_cli(prompt: str) -> str:
    resp = ollama.chat(
        model=OLLAMA_MODEL,   # config.py에서 설정한 모델
        messages=[{"role": "user", "content": prompt}]
    )
    return resp["message"]["content"].strip()
```
> brief 품질은 모델 성능에 따라 차이남. `qwen2.5:14b` 이상 권장.
