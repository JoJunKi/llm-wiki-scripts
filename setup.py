"""
setup.py
첫 실행 시 한 번만 수행. 경로 입력 받아 .bat 파일 바탕화면에 생성.

사용법:
  python setup.py
"""
import sys
import os
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.resolve()

BAT_TEMPLATES = {
    "논문검색.bat": """\
@echo off
chcp 65001 >nul 2>&1
echo ========================================
echo  Paper Search - OpenAlex
echo ========================================
echo.
echo Options:
echo   --min-citations N   (default 30)
echo   --year-from YYYY    (default 2022)
echo   --max N             (default 20)
echo   --dry               (list only)
echo.
set /p QUERY=Query + options:
python "{scripts}\\paper_fetcher.py" %QUERY%
echo.
pause
""",
    "논문처리.bat": """\
@echo off
chcp 65001 >nul 2>&1
echo ========================================
echo  PDF to Obsidian Notes
echo ========================================
echo.
echo Put PDFs in _inbox folder, then run.
echo.
python "{scripts}\\run_wiki.py" --all
echo.
pause
""",
    "개념정리.bat": """\
@echo off
chcp 65001 >nul 2>&1
echo ========================================
echo  Concept Notes - connect_vault
echo ========================================
echo.
echo 1. Vault scan + stub creation only
echo 2. Enrich empty stubs with Ollama
echo 3. Dry run
echo.
set /p CHOICE=Select (1/2/3):
if "%CHOICE%"=="1" python "{scripts}\\connect_vault.py"
if "%CHOICE%"=="2" python "{scripts}\\connect_vault.py" --enrich
if "%CHOICE%"=="3" python "{scripts}\\connect_vault.py" --dry
echo.
pause
""",
    "Gap분석.bat": """\
@echo off
chcp 65001 >nul 2>&1
echo ========================================
echo  Research Gap Analysis
echo ========================================
echo.
echo Usage:
echo   (Enter) - all topics
echo   --topic "Diffusion Models" - specific topic
echo   --dry - list only
echo.
python "{scripts}\\gap_finder.py" %*
echo.
pause
""",
    "논문검색(Vault).bat": """\
@echo off
chcp 65001 >nul 2>&1
echo ========================================
echo  Vault Paper Search - Ollama
echo ========================================
echo.
echo Search papers in your Obsidian vault.
echo Index auto-updates on every run.
echo.
python "{scripts}\\vault_search.py"
echo.
pause
""",
    "세션저장.bat": """\
@echo off
chcp 65001 >nul 2>&1
echo ========================================
echo  Save Claude Code Session
echo ========================================
echo.
python "{scripts}\\save_session.py" --today --claude
echo.
pause
""",
    "detailed재생성.bat": """\
@echo off
chcp 65001 >nul 2>&1
echo ========================================
echo  Fix Empty Detailed Files - Ollama
echo ========================================
echo.
echo Finds detailed files under 3KB and regenerates them.
echo Brief files are NOT touched.
echo.
echo 1. Dry run (show targets only)
echo 2. Run (regenerate detailed files)
echo.
set /p CHOICE=Select (1/2):
if "%CHOICE%"=="1" python "{scripts}\\fix_detailed.py" --dry
if "%CHOICE%"=="2" python "{scripts}\\fix_detailed.py"
echo.
pause
""",
}


def main():
    print("=" * 50)
    print(" LLM Wiki Setup")
    print("=" * 50)
    print()

    # 바탕화면 경로
    desktop = Path.home() / "Desktop"
    print(f"바탕화면 경로: {desktop}")
    custom = input("다른 경로 사용? (Enter = 위 경로 사용): ").strip()
    if custom:
        desktop = Path(custom)
    desktop.mkdir(parents=True, exist_ok=True)

    # bat 파일 생성
    created = 0
    for name, template in BAT_TEMPLATES.items():
        content = template.replace("{scripts}", str(SCRIPTS_DIR))
        bat_path = desktop / name
        bat_path.write_text(content, encoding="cp949", errors="replace")
        print(f"  ✅ {bat_path}")
        created += 1

    print()
    print(f"완료: {created}개 bat 파일 생성 → {desktop}")
    print()
    print("다음 단계:")
    print("  1. config.py 열어서 OLLAMA_MODEL, OPENALEX_EMAIL 설정")
    print("  2. Obsidian에서 ResearchWiki/Papaer 폴더 열기")
    print("  3. 논문검색.bat 실행해서 테스트")


if __name__ == "__main__":
    main()
