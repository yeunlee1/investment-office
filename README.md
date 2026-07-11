# Pixel Investment Office

사용자가 미국 주식 후보를 넣으면 여섯 AI 역할이 의견을 만들고, 위원장이 한 장의 결정 카드로 정리합니다. 사용자가 승인·보류·기각을 선택해야 기록이 확정됩니다. 이 앱은 증권사 주문을 만들거나 전송하지 않습니다.

## 분석 흐름

1. 기본면·기술·뉴스 에이전트가 같은 시점의 입력 데이터를 분석합니다.
2. BULL과 BEAR가 앞선 의견을 반대 방향에서 검토합니다.
3. 위원장이 초안을 만들고 결정론적 리스크 정책이 비중 상한과 무효화 조건을 계산합니다.
4. 사용자가 최종 결정을 저널에 기록합니다.

에이전트 호출은 로컬 Codex CLI에 저장된 ChatGPT 로그인을 사용합니다. API 키는 자식 프로세스에서 제거하며 각 호출은 읽기 전용·임시 세션으로 실행합니다.

## 현재 데이터 범위

가격과 거래량은 Yahoo Finance의 일봉 chart 응답을 사용합니다. 앱은 이동평균, RSI, ATR, 20일 연환산 변동성, 52주 고저를 계산합니다. 입력에 펀더멘털이나 최신 뉴스가 없으면 해당 에이전트가 `data_gaps`에 부족한 항목을 적습니다. 앱은 수치나 출처를 임의로 채우지 않습니다.

## 처음 한 번 실행

Windows PowerShell에서 실행합니다.

```powershell
uv sync
.\scripts\install_mariadb.ps1
uv run python .\scripts\bootstrap_database.py
.\scripts\start.ps1
```

`install_mariadb.ps1`은 관리자 권한 없이 MariaDB 11.8.2 공식 ZIP을 내려받고 SHA-256을 확인합니다. 프로젝트 전용 서버는 `127.0.0.1:3307`을 사용하므로 기존 MySQL 3306과 충돌하지 않습니다. 앱 계정은 `pixel_investment_office` 데이터베이스에만 권한을 갖습니다.

## 접속과 종료

- 2D 사무실은 `http://127.0.0.1:8765/office`에서 엽니다.
- 기존 대시보드는 `http://127.0.0.1:8765`에서 엽니다.
- PC에서는 WASD·방향키로 이동하고 `E` 또는 `Enter`로 가까운 책상과 대화합니다. 에이전트를 마우스로 눌러 보고서를 열 수도 있습니다.
- 모바일에서는 화면 아래 방향 패드와 `확인` 버튼을 사용합니다.
- 웹 서버 종료 명령은 `.\scripts\stop_app.ps1`입니다.
- MariaDB와 앱 로그는 `var\logs`에 남습니다.

## 게임형 업무와 회의

- NPC를 선택하면 역할별 추가 분석 업무를 배정하고 대기열·실행·완료 상태를 확인할 수 있습니다.
- 중간보고 요청은 새 답변을 꾸며내지 않고 DB에 저장된 실제 진행 상태와 결과만 보여줍니다.
- 실패·취소 업무의 재개는 중단된 Codex 세션 복원이 아니라 이전 결과를 문맥으로 사용한 새 시도입니다.
- 투자위원회는 기존 여섯 분석을 실제 발언으로 불러오며, 사람이 특정 역할에 추가 발언을 요청할 때만 Codex를 새로 호출합니다.
- 회의록은 주장·근거·데이터 공백·실패를 결정론적으로 정리하고, 실제 주문 없이 사람 검토 게이트로 끝납니다.

## 검증

```powershell
uv run ruff check src tests scripts
uv run mypy src
uv run pytest
node --check .\src\investment_office\static\app.js
node --check .\src\investment_office\static\office.js
```

## 데이터베이스 범위

앱은 `pixel_investment_office` 안의 다음 테이블만 사용합니다.

- `candidates`
- `analysis_runs`
- `agent_outputs`
- `events`
- `reviews`
- `snapshots`

## 투자 사용 범위

결정 카드는 분석 초안입니다. 슬리피지, 세금, 개인 보유 종목, 유동성 제약을 모두 반영하지 못합니다. 사용자는 주문 전에 가격과 공시를 다시 확인하고 손실 한도를 정해야 합니다.
