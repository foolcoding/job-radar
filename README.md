# job-radar

한국 채용 사이트(점핏·원티드·랠릿·잡코리아)에서 **신입 개발자 공고**를 모아
**신입 여부까지 자동 판정**하고, 매일 **새로 뜬 공고만** 골라주는 개인 학습용 CLI 도구입니다.

> 표준 라이브러리만 사용합니다. 별도 설치(pip) 없이 Python 3.8+ 에서 바로 실행됩니다.

---

## 만들게 된 계기

취업 준비 중 매일 네 곳의 채용 사이트를 돌며 "신입 가능한가?"를 일일이 확인하는 게 비효율적이었습니다.
그래서 공고 수집과 신입 여부 판정을 자동화했습니다. 핵심 과제는 **사이트마다 데이터를 얻는 방법이 다르다**는 점이었습니다.

## 동작 원리

| 사이트 | 수집 방법 | 신입 여부 판정 근거 |
|--------|-----------|---------------------|
| 점핏 | 프론트엔드가 호출하는 공개 JSON API 직접 조회 | `newcomer` 플래그 / `minCareer == 0` |
| 원티드 | 공개 JSON API (`years=0`) | `years` 파라미터 |
| 랠릿 | 공개 JSON API (`careers=NEWCOMER`) | API 필터 |
| 잡코리아 | **공개 API가 없어** 검색 페이지 HTML 파싱 + 상세페이지 조회 | 상세페이지의 `경력 : 신입·경력` 필드 파싱 |

- **API 역분석**: 브라우저 개발자도구 Network 탭에서 화면이 호출하는 내부 JSON 엔드포인트를 찾아 직접 호출합니다.
- **스크래핑 폴백**: 잡코리아는 React 기반으로 바뀌어 깔끔한 API가 없어, 검색 결과 HTML에서 공고를 추출하고 각 상세페이지의 경력 필드를 읽어 **추정이 아니라 정확하게** 신입 여부를 가립니다(경력 공고는 자동 제외).
- **누적 중복제거**: 본 적 있는 공고 URL을 `seen_urls_*.txt`에 누적 저장 → 실행할 때마다 **🆕 오늘 새로 뜬 공고**만 따로 보여줍니다.

## 사용법

```bash
# 백엔드(Java/Spring) 신입 공고 수집
python job_monitor.py --track backend

# 프론트엔드(React/Next) 신입 공고, 특정 지역 우선 표시
python job_monitor.py --track frontend --prefer 부산

# 결과 저장 폴더 지정 (또는 환경변수 JOBRADAR_OUT)
python job_monitor.py --out ./output --sleep 0.4
```

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--track` | `backend` 또는 `frontend` | `backend` |
| `--out` | 결과 저장 폴더 | `./output` |
| `--prefer` | 우선 표시할 지역명 (예: 부산). 비우면 지역 섹션 생략 | (없음) |
| `--sleep` | 요청 사이 간격(초) — 정중한 호출용 | `0.4` |

### 출력물 (`output/`)

- `live_jobs_<track>.md` : 맨 위 "마지막 실행" 시각 + 🆕 새 공고 + 전체 목록
- `monitor_log.txt` : 실행 이력 한 줄씩 누적 (스케줄러가 매일 도는지 추적)
- `seen_urls_<track>.txt` : 누적 중복제거용 (본 공고 URL 저장)

## 매일 자동 실행 (스케줄러)

**Windows (작업 스케줄러)** — 매일 21:00 실행:

```powershell
$action  = New-ScheduledTaskAction -Execute 'python' -Argument 'C:\path\to\job_monitor.py --track backend'
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00pm
Register-ScheduledTask -TaskName 'JobRadar' -Action $action -Trigger $trigger -Description '신입 공고 모니터' -Force
```

**Linux/macOS (cron)** — 매일 21:00 실행 (`crontab -e`):

```
0 21 * * * /usr/bin/python3 /path/to/job_monitor.py --track backend
```

## 배운 점

- 공개 API가 없을 때, 프론트엔드가 호출하는 **내부 엔드포인트를 역분석**해 구조화된 데이터를 얻는 방법
- API가 막힌 사이트는 **HTML 파싱 + 상세페이지 조회**로 폴백하되, 추정이 아니라 원본 필드를 읽어 정확도를 확보하는 설계
- 매일 도는 작업에서 **누적 상태(본 공고)** 를 파일로 관리해 증분(새 공고)만 뽑아내는 방식
- 외부 의존성 없이(stdlib만) 스케줄러에 얹기 좋은 작은 도구로 만드는 것

## ⚠️ 면책 / 사용 시 주의

- 이 프로젝트는 **개인 학습 및 포트폴리오 목적**의 예제입니다.
- 각 사이트의 **이용약관과 `robots.txt`를 반드시 확인·존중**하세요. `--sleep` 으로 요청 간격을 두어 서버에 부담을 주지 않도록 정중하게 호출합니다.
- 상업적 이용이나 대량 수집 용도가 아닙니다.
- 사용된 내부 엔드포인트는 각 사이트 사정에 따라 **예고 없이 변경되거나 중단**될 수 있습니다.

## 라이선스

MIT
