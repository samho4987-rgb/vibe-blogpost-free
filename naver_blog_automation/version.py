"""앱 버전과 온라인 업데이트 설정.

- APP_VERSION: 새 릴리스를 낼 때마다 올린다(예: "1.0.1"). GitHub 릴리스 태그와 맞춘다.
- GITHUB_REPO: 공개 GitHub 저장소 'user/repo'. 비어 있으면 업데이트 확인이 꺼진다.

업데이트 흐름:
  1) 앱 시작 시 백그라운드로 이 저장소의 최신 릴리스를 확인한다(공개 저장소=토큰 불필요).
  2) 새 버전이 있으면 릴리스에 첨부한 zip을 받아둔다.
  3) 재시작하면 앱 로딩 전에 자동으로 교체된다(사용자 설정·데이터는 보존).

새 버전 배포 방법:
  1) 이 파일의 APP_VERSION을 올린다(예: 1.0.1).
  2) scripts/build_release.py로 배포용 zip을 만든다.
  3) GitHub에서 같은 버전 태그(예: v1.0.1)로 Release를 만들고 그 zip을 첨부한다.
"""

APP_VERSION = "1.0.1"
GITHUB_REPO = "samho4987-rgb/vibe-blogpost-free"
