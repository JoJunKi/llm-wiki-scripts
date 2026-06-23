"""
prompts.py
프롬프트 템플릿
  - OLLAMA_SECTION_PROMPT   : Ollama → 섹션별 테이블+Insight 생성
  - SECTION_TEMPLATES       : 섹션 유형별 출력 뼈대
  - OLLAMA_SESSION_PROMPT   : Ollama → 세션 구조화 (JSON 출력)
  - DETAILED_SUMMARY_PROMPT : (미사용, 레거시)
  - BRIEF_SUMMARY_PROMPT    : Claude → brief 요약본 생성
"""

OLLAMA_SECTION_PROMPT = """You are analyzing one section of an academic paper.
Table content and Insight MUST be written in Korean (한국어).
The section header line must be kept exactly as given — do NOT translate it.
Do NOT include [[wikilink]] style links.
Output only markdown. No explanations, no code fences (```).

Section: "{section_header}"

Section content:
{section_text}

Rules:
- Use the EXACT header text as-is for the ## heading (do not translate or add parentheses).
- If the section has explicit subsections (3.1, 3.2, 3.1.1 etc.), use each as one table row with its number and name.
- If no subsections, use logical paragraph labels: P1, P2, P3 ...
- Abstract exception: use bullet points (no table).
- Introduction rows: P1 연구 배경 / P2 문제 정의 / P3 기존 한계 / P4 제안 방법
- Conclusion rows: P1 연구 요약 / P2 한계 / P3 향후 과제

Output this format exactly:

## {section_header}

| 소절/문단 | 주요 내용 |
|----------|----------|
| **(3.1 Subsection Name 또는 P1 — 레이블)** | (한국어 요약) |
| **(3.2 Subsection Name 또는 P2 — 레이블)** | (한국어 요약) |

> 💡 **Insight**: (이 섹션의 서술 방식 중 내 논문 작성에 활용할 수 있는 포인트)
"""

OLLAMA_ABSTRACT_PROMPT = """Summarize the Abstract of this academic paper.
ALL output MUST be in Korean (한국어). Output only markdown. No code fences.

Abstract content:
{section_text}

Output exactly this format:

## Abstract

- **핵심 문제**: (한 줄)
- **제안 방법**: (한 줄)
- **핵심 성과**: (한 줄)
"""

OLLAMA_CHUNK_SUMMARY_PROMPT = """반드시 한국어로 작성하세요.
아래 대화 내용({idx}/{total} 부분)의 핵심을 요약하세요.
결정사항, 구현 내용, 아이디어, 오류 수정 등을 포함하세요.
5-8문장으로 작성하세요. 다른 텍스트 없이 요약만 출력하세요.

## 대화 내용
{chunk}
"""

OLLAMA_SESSION_PROMPT = """당신은 연구 세션 정리 도우미입니다. 반드시 한국어로 작성하세요.
아래는 긴 대화를 여러 부분으로 나눠 요약한 내용입니다.
이를 바탕으로 전체 세션을 구조화하세요.

## 기존 Vault 개념/주제/논문 (링크 재사용용)
{vault_context}

## 각 부분별 요약
{chunk_summaries}

## 세션 타입 판단 기준
- "research": 논문 읽기, 연구 설계, 방법론·이론 논의가 주된 활동
- "dev": 코드 구현, 디버깅, 시스템/툴 설계가 주된 활동
- "mixed": 두 가지가 고르게 섞인 경우

## 타입별 related_concepts 추출 규칙
- research 세션: 논문에서 다룬 연구 개념·방법론·이론 (예: "Diffusion Models", "Sentiment Analysis")
- dev 세션: 직접 사용·구현한 도구·라이브러리·기술 (예: "Ollama", "Obsidian"). 논문 연구 주제는 제외.
- mixed: 두 가지 모두

## related_papers 추출 규칙
- research 세션: 핵심적으로 논의된 논문
- dev 세션: 개발에 직접 참고한 논문만. 단순 언급·처리 과정에서 나온 논문 이름은 제외.

## 출력 규칙
- JSON만 출력하세요. 다른 텍스트나 코드 펜스(```)는 포함하지 마세요.
- related_concepts는 Title Case + 공백으로 명명. 기존 Vault 이름 그대로 재사용.
- related_papers는 파일명에서 .md 제거한 형태.

{{
  "title": "세션 제목 (간결하게, 20자 이내)",
  "session_type": "research | dev | mixed",
  "summary": "전체 세션을 2-3문장으로 요약",
  "key_decisions": ["결정사항1", "결정사항2"],
  "ideas": ["아이디어/인사이트1", "아이디어2"],
  "related_concepts": ["개념1", "개념2"],
  "related_papers": ["파일명_확장자없이"],
  "tags": ["태그1", "태그2"]
}}
"""

DETAILED_SUMMARY_PROMPT = """당신은 학술 논문 분석 전문가입니다.
아래 논문 데이터를 바탕으로 **상세 정리 파일**을 작성하세요.

목적: 논문을 읽지 않아도 각 문단의 논리를 파악하여 새 논문 작성 시 레퍼런스로 활용

**중요: 이 파일에는 [[개념]] 형식의 위키 링크를 포함하지 마세요.**
모든 개념 연결은 brief 요약본이 hub로 담당합니다.
유일한 링크는 frontmatter의 brief 백링크 하나뿐입니다.

---
## 논문 메타데이터
{metadata}

## 섹션별 내용
{sections}
---

## 출력 형식 (Obsidian 마크다운)

---
title: "{title}"
authors: {authors}
year: {year}
journal: "{journal}"
keywords: {keywords}
tags: {tags}
related: []
date_added: {today}
brief: "[[papers/brief/{filename_noext}]]"
---

> 개념 연결 도식은 [[papers/brief/{filename_noext}|brief 요약본]] 참고

## 논문 개요
| 항목 | 내용 |
|------|------|
| 핵심 문제 | (한 줄 요약) |
| 제안 방법 | (한 줄 요약) |
| 핵심 성과 | (한 줄 요약) |

---

## 1. Introduction (서론)

| 문단/위치 | 주요 내용 요약 |
|-----------|---------------|
| **P1 — 연구 배경** | ... |
| **P2 — 문제 정의** | ... |
| **P3 — 기존 연구 한계** | ... |
| **P4 — 제안 방법 소개** | ... |

> 💡 **Insight**: (이 섹션에서 논문 작성에 활용할 수 있는 핵심 포인트)

---

## 2. Related Works (관련 연구)

| 소절 | 주요 내용 요약 |
|------|---------------|
| **2.1 ...** | ... |
| **2.2 ...** | ... |

> 💡 **Insight**: ...

---

## 3. Methodology (방법론)

| 소절 | 주요 내용 요약 |
|------|---------------|
| **3.1 ...** | ... |

> 💡 **Insight**: ...

---

## 4. Experiments & Results (실험 및 결과)

| 항목 | 주요 내용 요약 |
|------|---------------|
| **데이터셋** | ... |
| **평가 지표** | ... |
| **비교 기법** | ... |
| **핵심 결과** | ... |

> 💡 **Insight**: ...

---

## 5. Conclusion (결론)

| 문단 | 주요 내용 요약 |
|------|---------------|
| **P1 — 연구 요약** | ... |
| **P2 — 한계 및 향후 과제** | ... |

---

> 관련 논문·개념 연결은 [[papers/brief/{filename_noext}|brief 요약본]]에서 확인하세요.

실제 논문 내용을 채워서 완성된 마크다운을 출력하세요.
Insight 칸에 [[ ]] 형식의 위키 링크를 절대 포함하지 마세요.
"""

BRIEF_SUMMARY_PROMPT = """당신은 학술 논문 분석 전문가입니다.
아래 논문 데이터를 바탕으로 **전체 요약본**을 작성하세요.

목적: 학제간 연구, 연구 주제 탐색, 빠른 논문 파악

## Vault 컨텍스트 (기존 노트 — 가급적 재사용해서 그래프 연결성 확보)
{vault_context}

---
## 분석할 논문 데이터
{metadata}
{sections}
---

## 구조 설명 (반드시 숙지)
- **primary_topic** = 이 논문이 속한 **연구 분야** (큰 범주, 1개). topics/ 폴더에 MOC로 관리됨.
- **관련 개념** = primary_topic 안에서 이 논문이 사용한 **세부 기술/방법론** (concepts/ 폴더에 저장됨).
- ⚠️ primary_topic에 쓴 단어는 관련 개념에 절대 중복 포함하지 말 것.

## 출력 형식 (Obsidian 마크다운)

---
title: "{title}"
authors: {authors}
year: {year}
primary_topic: "(이 논문이 속한 연구 분야 1개. 기존 주제 목록에 있으면 그대로 재사용. 예: Diffusion Models, Machine Learning, Sentiment Analysis, Reliability Engineering)"
tags: {tags}
type: brief_summary
detailed: "[[papers/detailed/{filename}]]"
---

## 한 줄 요약
> (논문 전체를 1-2문장으로 압축)

## 핵심 기여 (3가지)
1. **기여1**: ...
2. **기여2**: ...
3. **기여3**: ...

## 방법론 핵심
(방법론을 비전공자도 이해할 수 있도록 3-5문장으로 설명)

## 주요 결과
- 결과1
- 결과2
- 결과3

## 한계점
- 한계1
- 한계2

## 연구 활용 가능성
(이 논문을 내 연구에 어떻게 활용할 수 있는지)

## 관련 개념
(**primary_topic 자체는 절대 포함하지 말 것.** primary_topic 안의 세부 기술/방법론만 [[개념명]] 형식으로 3-5개.
 **선정 기준:**
   - O: 여러 논문에서 공통으로 쓰이는 기법 (예: Data Augmentation, Score Matching, Heavy-Tailed Distribution)
   - X: primary_topic과 동일하거나 상위 개념 (예: primary_topic이 "Diffusion Models"이면 [[Diffusion Models]] 금지)
   - X: 이 논문에만 등장하는 고유 모델명/수식 (예: DDIM, γ-Divergence)
   - 기존 개념 노트 이름은 글자 그대로 재사용. 새 개념은 Title Case + 공백.
[[개념1]] | [[개념2]] | [[개념3]]

## 관련 논문
(위 "기존 논문 목록"에서 이 논문과 동일 주제/기법/도메인 논문을
 [[papers/brief/파일명]] 형식으로 1-5개 나열. 없으면 "(없음)" 으로 표기.)

실제 논문 내용을 채워서 완성된 마크다운을 출력하세요.
"""
