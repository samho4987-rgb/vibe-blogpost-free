# 다른 AI·개발자 인수인계 문서

## 목표

이 저장소는 부동산 매물 기초자료를 모아 네이버 블로그 원고와 로컬 대표 이미지를
만들고, Playwright로 **임시저장까지만** 수행하는 데스크톱 앱이다. 사용자의 최신 요구는
4단계 흐름, 비용 0 운영, 모든 텍스트 복사, 프로그램 내부 Kakao 지도·로드뷰, 계정·키
통합 환경설정이다.

## 현재 구현 상태

완료:

1. `BlogAutomationWorkflow.preview()`
   - Gemini 호출 없음
   - 네이버 매물, Kakao/Daum, 건축물대장, 면적 분석
   - `property.json`, `enrichment.json`, `research.md`, `run.json`
2. `generate_content()`
   - 기존 미리보기 자료 재사용
   - Kakao·Daum 조사자료 재사용, Google Search grounding 추가 호출 없음
   - 게시물당 Gemini 텍스트 생성 1회 또는 오프라인 초안
   - `output/contents/blog_[매물번호].md`
3. `generate_image()`
   - Pillow 전용, 외부 이미지 API 호출 없음
   - `output/thumbnails/thumbnail_[매물번호].png`, 1080×1080
4. `save_draft()`
   - 실제 입력 ID로 블로그 URL 계산
   - 필요 시 같은 창에서 로그인
   - 고정 Markdown을 H2/H3/굵게/구분선/HTML 표로 변환
   - 대표 이미지, 전화 배너, 거래상태 확인 이미지 첨부
   - 임시저장 후 Chrome 유지, 사용자가 닫으면 정상 종료
5. UI
   - 4개 순번 버튼
   - `blog자료`, 병합된 `매물 조사 메모`, `이미지`, `지도·로드뷰`,
     `문제 해결·고급 설정`, 프롬프트, 환경설정, 로그 탭
   - Text/Entry/Tree의 Ctrl+C·Command+C
6. 보안
   - 네이버·이실장 비밀번호는 OS keyring 선택 저장
   - API 키는 `.env`
   - cURL·쿠키는 메모리 전용

## 핵심 파일

- `app.py`: Tkinter UI와 작업 스레드
- `naver_blog_automation/workflow.py`: 4단계 오케스트레이션
- `property_fetcher.py`: httpx 쿠키 갱신, 429, cURL, 숨은 브라우저 대체 수집
- `enrichment.py`: Kakao Local·Daum 웹검색·건축물대장
- `ai_agent.py`: Gemini 호출 간격·quota 분류·오프라인 원고
- `thumbnail.py`: 로컬 1:1 이미지와 지원 배너
- `content_writer.py`: 고정 Markdown 구조
- `post_format.py`: 플레이스홀더용 안전한 HTML 표
- `naver_blog.py`: Playwright 로그인·스마트에디터 입력·임시저장
- `embedded_map.py`, `kakao_map_server.py`: 앱 내부 지도·로드뷰
- `config/blog_selectors.yaml`: 네이버 UI 셀렉터 단일 기준
- `README.md`: 사용자 매뉴얼

## 중요한 설계 판단

- 미리보기는 `run()`이 아니라 반드시 `preview()`를 호출한다. `run()`은 기존 테스트와
  외부 호출 호환용으로 전체 단계를 실행한다.
- 미리보기는 `blog자료`를 덮어쓰지 않는다. `WorkflowResult.preview_only=True`가 기준이다.
- 이미지 API는 코드 경로에서 사용하지 않는다. `workflow._agent()`도 `image_model=""`로
  강제한다.
- 건축물대장의 `0`, 빈 값, `정보 없음`은 `enrichment._has_meaningful_value()`와
  `post_format._meaningful()`에서 생략한다.
- Naver의 `SE-UUID` ID는 매번 바뀌므로 셀렉터에 고정하지 않는다.
- 네이버 임시저장 실계정 성공은 서비스 UI와 계정 보안 상태에 의존한다. CAPTCHA 우회는
  구현하지 않는다.
- 남은 Gemini 호출 수는 부정확하므로 표시하지 않고 공식 사용량 링크만 제공한다.

## 제공된 코중사 원본 반영 내역

사용자가 제공한 macOS `post_blog.py`, 코중사 원본 `post_blog(코중사원본).py`,
`fetch_with_curl.py`의 유용한 구조를 분석해 다음만 현재 코드에 이식했다.

- 고정 Markdown 플레이스홀더와 HTML 표 치환 개념
- H2/H3, 굵은 글씨, 구분선, 이미지 배너를 포함한 스마트에디터 입력
- Copy as cURL의 헤더·쿠키를 사용하는 비상 수집 경로
- 대표 이미지와 하단 안내 이미지 첨부

평문 비밀번호, 고정 계정 ID, 계정별 `SE-UUID`, 허위 기본 매물값, 완료 후 브라우저
강제 종료는 이식하지 않았다. macOS 전용 `osascript` 클립보드 대신 브라우저 에디터의
HTML 삽입과 일반 텍스트 대체 경로를 사용해 Windows도 같은 코드로 동작하게 했다.

## 비용 관련 사실

앱에는 유료 모델/이미지 API 자동 전환이 없다. 그러나 외부 프로젝트의 결제 상태는
앱이 통제할 수 없다. 절대 0원 보장이 필요하면 Gemini 키를 비워 로컬 초안만 사용하거나,
결제가 연결되지 않은 무료 프로젝트 키만 사용한다. 이 제한을 숨기거나 “무조건 무료”라고
과장하면 안 된다.

## 이 버전에서 발생했던 실패와 해결 내역

### 1. Google API 키 인증 실패

증상:

- 화면에 `API Key 인증에 실패했습니다. 키를 다시 확인해 주세요.`가 표시됨
- 초기 화면과 안내 일부가 Google AI Studio 키를 일반적인 “Open API Key”처럼
  표현해 사용자가 어떤 키를 넣어야 하는지 불명확했음
- macOS에서 마스킹된 키 입력칸에 붙여넣기가 정상 동작하지 않는 경우가 있었음

원인:

- 이 프로그램이 요구하는 키는 OpenAI 키가 아니라
  `https://aistudio.google.com/app/apikey`에서 발급한 Gemini API 키임
- 클립보드에 `GEMINI_API_KEY=...`, 따옴표, `Bearer ` 접두어가 함께 들어오는 경우
  그대로 검증하면 인증에 실패할 수 있음
- 유효한 키라도 프로젝트 권한, API 활성화, 네트워크 문제로 모델 목록 조회가
  실패할 수 있음

현재 대응:

- 화면 명칭을 `Google AI Studio API Key`로 통일
- Google 키 발급 페이지 버튼 추가
- `Ctrl+V`, `Command+V`, `Shift+Insert`, 우클릭과 붙여넣기 버튼 지원
- 환경변수 표기, 따옴표, `Bearer `, 보이지 않는 문자를 제거한 뒤 검증
- 생성 요청이 아닌 모델 목록 조회로 키 인증을 확인하고, 성공한 키만 `.env`에 저장

주의:

- 검증 성공은 “키가 유효하다”는 뜻일 뿐, 해당 모델의 남은 RPM·TPM·RPD,
  무료 할당량 또는 결제 상태를 보장하지 않는다.
- AI Studio 화면의 표시 이름과 실제 API 모델 ID가 달라지면
  `gemini-3.5-flash` 기본값도 다시 확인해야 한다.

### 2. 콘텐츠 생성 중 `429 RESOURCE_EXHAUSTED`

대표 오류:

```text
429 RESOURCE_EXHAUSTED
You exceeded your current quota, please check your plan and billing details.
```

확인된 무료 등급 화면에서는 Gemini 3.5 Flash가 대략 RPM 5, TPM 250K,
RPD 20의 제한으로 표시됐다. 제한값은 시점·계정·프로젝트별로 달라질 수 있다.

실패 원인:

- 한 게시물을 만들면서 입지 조사, Google Search grounding, 본문 작성, 이미지 생성
  등 여러 Gemini 요청을 연속 실행했음
- RPM 5라면 요청 시작 간격이 평균 12초 이상이어야 하므로 `sleep(3)`~`sleep(5)`만
  추가하는 조언은 충분하지 않았음
- 일일 RPD 소진, 무료 할당량 0, 결제·모델 제한은 기다려도 같은 날 바로 회복되지 않음
- 이미지 모델은 무료 프로젝트에서 할당량이 0일 수 있어 텍스트 모델과 별도로
  429가 발생할 수 있음

현재 대응:

- 동일 텍스트 모델의 기본 요청 시작 간격을 12.5초로 설정
- `RetryInfo.retryDelay`가 있는 일시적 제한만 최대 2회 제한적으로 재시도
- RPD, daily, billing, `limit: 0` 등 회복되지 않는 제한은 반복 호출하지 않음
- 1단계 조사에서 Kakao Local과 Daum 웹검색을 사용하고, 워크플로우에서는
  Google Search grounding 추가 호출을 제거
- 게시물 한 건의 Gemini 텍스트 생성 요청을 최대 1회로 축소
- 대표 이미지는 Gemini 이미지 API 대신 Pillow 로컬 생성으로 완전히 교체
- 429가 계속되면 이미 수집한 자료로 오프라인 초안을 만들고 작업을 종료

### 3. 호출 간격만 늘리면 모든 429가 해결된다는 오해

`time.sleep()`은 순간적인 RPM 제한에는 도움이 되지만 다음 문제는 해결하지 못한다.

- 하루 요청 수 RPD 소진
- 모델별 무료 할당량이 0인 프로젝트
- 결제·프로젝트 정책 제한
- 사용할 수 없는 모델 ID
- 다른 프로그램이나 API 키가 같은 프로젝트 할당량을 이미 사용한 경우

따라서 현재 코드는 무한 대기나 무한 재시도를 하지 않는다. 짧은 일시 제한과
일일·정책 제한을 구분하고 후자는 로컬 초안으로 전환한다.

### 4. 남은 호출 수 표시 검토 결과

앱에 `남은 호출 12회` 같은 숫자는 표시하지 않기로 했다.

- Gemini 한도는 API 키가 아니라 Google Cloud 프로젝트 단위로 합산될 수 있음
- RPM, TPM, RPD 중 어느 제한이 먼저 걸릴지 로컬 앱은 알 수 없음
- 다른 기기·프로그램의 사용량을 로컬 카운터가 반영할 수 없음
- 신뢰할 수 있는 단일 “남은 무료 호출 수” 응답을 현재 앱이 받지 않음

대신 환경설정의 `사용량 확인` 버튼으로 Google 공식 할당량 화면을 연다.

### 5. 비용 0과 Google API의 한계

프로그램 내부에서는 유료 모델 자동 전환, 유료 이미지 생성, 자동 결제 전환을 하지
않는다. 하지만 사용자가 넣은 Google Cloud 프로젝트에 결제가 연결되어 있는지는
프로그램이 통제할 수 없다.

절대적인 0원 운영이 필요하면:

1. Google 키를 비워 2단계도 로컬 초안으로 사용하거나
2. 결제가 연결되지 않은 무료 등급 프로젝트의 키만 사용하고
3. AI Studio 공식 사용량 화면에서 프로젝트 상태를 확인한다.

### 6. Google API 관련 전달 시 핵심 결론

- 키 인증 실패와 quota 429는 다른 문제다.
- 키 검증 성공만으로 생성 가능 여부를 판단하면 안 된다.
- 5 RPM에서 3~5초 대기는 부족하며 최소 약 12초 간격이 필요하다.
- RPD·billing·limit 0 오류는 대기로 해결하지 말고 즉시 로컬 대체로 전환한다.
- Google Search grounding과 이미지 생성은 현재 기본 워크플로우에서 호출하지 않는다.
- 현재 Google 호출은 사용자가 키를 제공한 2단계 본문 생성 최대 1회뿐이다.

### 7. Google 외에 함께 발생했던 주요 실패

- **네이버 매물 API 429**: 기본 GET만 반복하면 차단됐다. 현재는 브라우저형 헤더,
  상세 페이지 세션 쿠키, 제한적 쿠키 갱신, 숨은 공개 화면 수집, 마지막 수단인
  Copy as cURL 순서로 처리한다. 네이버 제한을 무한 재시도하거나 우회하지 않는다.
- **고정 블로그 계정 오류**: `agent-kang`, `green-core` 같은 예시 ID가 실제 사용자
  계정처럼 사용됐다. 현재는 로그인 ID와 별도 블로그 ID 입력값으로 URL을 매번 계산한다.
- **동적 `#SE-UUID` 셀렉터 실패**: 화면을 다시 열 때 제목·본문 ID가 바뀌었다.
  현재는 의미 기반 클래스와 `data-a11y-title` 후보를 YAML에서 관리한다.
- **도움말이 임시저장 버튼을 가림**: `subtree intercepts pointer events`가 발생했다.
  도움말·팝업을 먼저 닫고 한 번만 강제 클릭으로 재시도한다.
- **사용자가 Chrome을 닫은 뒤 Playwright 원문 오류 표시**:
  `Target page, context or browser has been closed`가 그대로 노출됐다. 현재는 저장 전
  종료와 저장 후 정상 종료를 구분해 사용자용 메시지로 처리한다.
- **키·매물번호 붙여넣기 실패**: macOS/Windows 단축키, 우클릭, 붙여넣기 버튼과
  URL에서 매물번호만 추출하는 정규화를 추가했다.
- **이미지 API 실패·비용 위험**: 외부 생성 모델 사용을 없애고 로컬 Pillow 1:1 이미지로
  교체했다.

## 실환경에서 추가 확인할 항목

코드·단위 테스트는 완료됐지만 다음은 실제 계정에서 한 번 확인해야 한다.

1. 최신 Naver SmartEditor에서 `document.execCommand('insertHTML')`로 표가 들어가는지
2. 사진 업로드 뒤 본문 커서 위치가 대표 이미지 아래에 놓이는지
3. 전화 배너 선택 후 `image_link` 셀렉터로 `tel:` 링크가 적용되는지
4. 거래상태 확인 이미지가 글 맨 아래에 놓이는지
5. 해당 블로그 계정의 카테고리·에디터 도움말이 임시저장 버튼을 가리지 않는지

실패 시 `config/blog_selectors.yaml`만 먼저 갱신한다. 동작 코드를 계정 고유 UUID
셀렉터로 바꾸지 않는다. HTML 표가 거부되면 현재 코드는 동일 정보를 일반 텍스트로
대체한다.

## 검증 명령과 현재 결과

```bash
.venv/bin/python -m compileall -q app.py naver_blog_automation
PYTHONPATH=.:.venv/lib/python3.14/site-packages pytest -q
```

2026-07-25 기준: `72 passed`, Google SDK 내부 deprecation warning 1건.

간이 흐름 검증도 완료:

- `preview(sample=True)`에서 AI 없이 빈 blog자료 결과 생성
- `generate_content()`로 고정 Markdown 생성
- `generate_image()`로 1080×1080 PNG 및 고정 파일명 생성

## 비밀정보 취급

`.env`, `config/user_settings.json`, `config/settings.yaml`, `data/browser-profile/`,
실행 `output/`에는 사용자 정보가 있을 수 있다. 다른 AI에게 전달할 때 파일 내용을
복사하지 말고 구조만 설명한다. 비밀번호·API 키·쿠키·전화번호를 로그나 답변에 노출하지
않는다.

## 권장 다음 작업

새 기능을 더하기 전에 실계정의 임시저장 한 건으로 위 다섯 항목을 확인한다. 셀렉터
문제가 확인되면 스크린샷과 DOM의 의미 기반 클래스만 수집해 YAML 후보를 보강한다.
자동 발행, CAPTCHA 우회, 네이버 차단 우회 강화를 임의로 추가하지 않는다.

---

## ⚠️ 건축물대장 표제부 선택 필수 규칙 (반복 함정)

같은 지번에 부속동·업무시설·노후 건물 표제부가 섞여 있어, 주거용 매물인데
건축물대장에 엉뚱한 건물(예: 1976 업무시설 3층)이 들어가는 문제가 반복 발생.

규칙(enrichment.py에 구현):
1. 주거용 매물이면 주거용 표제부(공동주택 등)로만 후보를 좁힌다(업무시설 등 제외).
2. 대표 동 선택: 주거여부 → 이름일치 → 연면적 → 세대수 → 필드수.
3. 주거용인데 주거 표제부가 없으면 건축물대장 정보를 통째로 생략(가드).
구현: `_is_residential_property`, `_is_residential_building`, `_select_building`,
`_building_register`(가드). 표는 post_format `[TABLE_COMPLEX]`가 기본행+대장필드 병합.
캐시(last_result.enrichment_data/enrichment.json)에 옛 값이 남으면 재조회 전까지
그대로 표시되니, 수정 후 반드시 '매물 조사하기' 재실행으로 확인.
자세히: 프로젝트 문서 `claude/건축물대장_표제부선택_필수규칙.md`.
