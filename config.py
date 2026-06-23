import os

# Obsidian Vault 경로
VAULT_PATH = os.path.join(os.path.expanduser("~"), "Documents", "ResearchWiki", "Papaer")

# Ollama 모델 — 논문 처리용
OLLAMA_MODEL = "exaone3.5:7.8b"

# Ollama 모델 — 세션 요약용 (한국어 특화)
OLLAMA_SESSION_MODEL = "exaone3.5:7.8b"

# 출력 언어 ("korean" 또는 "english")
OUTPUT_LANG = "korean"

# 임시 파일 경로 (Windows용)
TEMP_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp", "llm-wiki")
os.makedirs(TEMP_DIR, exist_ok=True)

# Semantic Scholar API Key (선택사항 — 없어도 동작하나 rate limit 강함)
# 무료 발급: https://www.semanticscholar.org/product/api
SEMANTIC_SCHOLAR_API_KEY = ""

# OpenAlex polite pool 이메일 (선택사항 — 있으면 응답 빠름)
# 본인 이메일 입력, 없으면 빈 문자열 ""
OPENALEX_EMAIL = ""
