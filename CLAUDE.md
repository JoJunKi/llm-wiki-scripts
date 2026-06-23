# LLM Wiki — Claude Code 지시 파일

## 역할
논문 분석 및 Obsidian Wiki 자동화 에이전트입니다.

## 작업 분담
- **Ollama (로컬 LLM)**: PDF 파싱, 섹션 분리, 메타데이터 추출
- **Claude Code**: 핵심 기여 분석, 논문 간 연결 관계, Insight 생성, 파일 저장

## 주요 명령어

### `/wiki <pdf_경로>`
논문 PDF를 완전 처리합니다:
1. `python ollama_processor.py <pdf>` 실행 (Ollama 전처리)
2. 결과를 분석하여 상세 요약 생성 → `papers/detailed/`
3. 결과를 분석하여 전체 요약본 생성 → `papers/brief/`

실제 실행: `python run_wiki.py <pdf_경로>`

### `/analyze <data_json_파일> <파일명>`
Ollama 전처리가 완료된 JSON 데이터를 받아 Claude가 직접 분석합니다.

실제 실행: `python claude_analyzer.py <json_파일> <파일명.md>`

### `/connect`
현재 Vault의 논문들을 스캔하여 연결 관계([[링크]])를 업데이트합니다.

## 파일 저장 경로
- 상세 요약: `~/Documents/ResearchWiki/papers/detailed/`
- 전체 요약: `~/Documents/ResearchWiki/papers/brief/`
- 개념 노트: `~/Documents/ResearchWiki/concepts/`
- PDF 입력: `~/Documents/ResearchWiki/_inbox/`

## 출력 규칙
- 모든 파일은 한국어로 작성
- Obsidian [[링크]] 형식 사용
- 각 섹션 끝에 💡 Insight 포함 (상세 요약)
- frontmatter YAML 필수 포함

## 스크립트 구조
```
run_wiki.py          ← 메인 진입점 (PDF 경로 하나로 전체 실행)
ollama_processor.py  ← Ollama: PDF 파싱, 섹션 분리
claude_analyzer.py   ← Claude API: 핵심 분석 및 파일 저장
prompts.py           ← 분석 프롬프트 템플릿
config.py            ← Vault 경로 및 모델 설정
```
