# AI-Calculrator

OpenAI Responses API를 사용하는 `Level4 GUI AI 계산기` 프로젝트입니다.

## 구성

- `Level4/ai_agent_calculator.py`: GUI 기반 AI 계산기 메인 파일
- `Level4/구상.md`: 설계와 구현 방향 정리
- `Level4/requirements.txt`: 추가 설치가 필요 없는 상태를 표시하는 파일

## 특징

- 자연어 질문을 입력하면 AI가 계산식을 만듭니다
- 결과만이 아니라 `식`, `설명`, `결과`를 함께 보여줍니다
- 최근 질문 기록을 다시 눌러 확인할 수 있습니다
- 실제 계산은 파이썬이 안전하게 처리합니다

## 실행 방법

1. `.env/.env` 파일에 API 키를 넣거나 `OPENAI_API_KEY` 환경 변수를 설정합니다.
2. 아래 명령으로 실행합니다.

```bash
python3 Level4/ai_agent_calculator.py
```

CLI 모드로 확인하고 싶다면:

```bash
python3 Level4/ai_agent_calculator.py --cli
```

## 예시 질문

- `64개의 사과를 4명에게 똑같이 나누면 몇 개씩 가져가?`
- `12000원의 15% 할인가는 얼마야?`
- `반지름이 5인 원의 넓이를 구해줘`
