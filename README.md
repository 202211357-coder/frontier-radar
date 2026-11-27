# 프런티어 모델 레이더

Gemini · GPT · Claude의 새 모델 출시와 퇴역 공지를 추적하는 독립 시스템입니다. Claude 예약 작업 없이 GitHub만으로 돌아갑니다.

```
GitHub Actions (3시간마다)
  └─ tracker/track.py ── 공식 changelog·릴리스 노트·뉴스 피드 수집
        ├─ 새 항목 판별 (tracker/state.json에 본 항목 기록)
        ├─ (선택) Claude API로 요약·가격·벤치마크 표 추출
        ├─ site/data.json, site/feed.xml 갱신 → 커밋
        └─ 알림: ntfy 푸시 / 텔레그램 / 디스코드·슬랙 웹훅
  └─ GitHub Pages로 site/ 배포
```

## 감시하는 출처

| 회사 | 출처 | 방식 |
|---|---|---|
| Google | Gemini API changelog, Google AI 블로그 RSS, DeepMind 블로그 RSS | 날짜별 항목 / 피드 |
| OpenAI | Model Release Notes, OpenAI News RSS | 날짜별 항목 / 피드 |
| Anthropic | Claude Platform release notes, anthropic.com/news | 날짜별 항목 / 링크 |
| 선택 | 각 사 모델 목록 API (`/v1/models`) | 새 모델 ID 등장 감지 |

모델명(GPT-6.2, Gemini 4 Neon, Claude Opus 5.5 등)과 출시·퇴역 관련 단어가 함께 있을 때만 새 항목으로 봅니다. 여러 출처에서 같은 모델이 4일 안에 다시 보이면 하나로 합칩니다.

## 설치 (10분)

1. GitHub에 새 저장소를 만들고 이 폴더를 올립니다.
   ```bash
   git remote add origin https://github.com/<아이디>/frontier-radar.git
   git push -u origin main
   ```
2. 저장소 **Settings → Pages → Source**를 **GitHub Actions**로 바꿉니다.
3. **Settings → Secrets and variables → Actions**에 값을 넣습니다.

   | 이름 | 종류 | 필수 | 용도 |
   |---|---|---|---|
   | `SITE_URL` | Variable | 권장 | 알림을 누르면 열릴 주소. 예: `https://<아이디>.github.io/frontier-radar/` |
   | `NTFY_TOPIC` | Secret | 알림 쓰려면 | ntfy 앱에서 구독할 토픽 이름. 다른 사람이 추측 못 하게 길고 무작위로 |
   | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Secret | 선택 | 텔레그램 봇 알림 |
   | `WEBHOOK_URL` | Secret | 선택 | 디스코드·슬랙 웹훅 |
   | `ANTHROPIC_API_KEY` | Secret | 선택 | 요약·벤치마크 자동 추출 + Claude 모델 목록 감시 |
   | `OPENAI_API_KEY`, `GEMINI_API_KEY` | Secret | 선택 | 각 사 모델 목록 API 감시 |

4. 휴대폰에 **ntfy** 앱(Android/iOS)을 설치하고 3번의 토픽을 구독합니다.
5. **Actions → track-frontier-models → Run workflow**로 한 번 실행해 봅니다.

`tracker/state.json`에는 지금까지 본 항목이 들어 있으므로 첫 실행에서 알림이 쏟아지지 않습니다.

## 자주 쓰는 명령

```bash
pip install -r tracker/requirements.txt
python tracker/track.py --dry-run --no-llm   # 무엇이 새로 잡히는지만 확인
python tracker/track.py --bootstrap          # 현재 상태를 기준점으로 다시 저장 (알림 없음)
python -m http.server -d site 8000           # 로컬에서 사이트 보기
```

## 데이터 구조 (`site/data.json`)

- `events`: 출시·퇴역·변경 기록. `status`는 `verified`(공식 페이지 직접 확인), `record`(이전 점검 기록), `auto`(추적기가 자동 추가, 검증 전)
- `upcoming`: 퇴역·라우팅·가격 변경 예정일
- `flagships`: 회사별 플래그십과 이전 모델 대비 수치(`pairs`) 또는 변화량(`deltas`)
- `benchTables`: 발표 주체별 벤치마크 표
- `prices`: 가격 비교 막대

자동 추가된 항목은 사이트에 "자동 수집" 표시가 붙습니다. 확인한 뒤 `status`를 `verified`로 바꾸고 커밋하면 됩니다.

## 한계

- 공식 페이지 구조가 바뀌면 해당 출처의 수집이 끊깁니다. 이때 `data.json`의 `errors`에 이유가 남습니다.
- API 키가 없으면 요약은 원문 첫 문장이고 벤치마크 표는 자동으로 채워지지 않습니다.
- 벤치마크는 각 회사 발표 수치이며, effort·하니스 조건이 서로 다를 수 있습니다.
- GitHub 예약 실행은 몇 분에서 수십 분 늦게 돌 수 있고, 60일 동안 저장소 활동이 없으면 일시 중지됩니다.
