# 바뀐 것 / Changelog

각 항목은 한국어 먼저, 영어 다음. Each entry is Korean first, then English.

## v0.2.0

**프로젝트를 왼쪽 사이드바에서 고른다.** 드롭다운이던 것을 즐겨찾기·최근·검색이 있는
사이드바로 바꿨다. 이름이 같은 폴더가 여러 워크스페이스에 있으면 상위 폴더명으로 구분한다.

**Pick a project from the left sidebar.** The dropdown is now a sidebar with favourites,
recents and search. Folders that share a name across workspaces are told apart by their
parent folder.

**헤더에 '앱으로 설치' 버튼이 생겼다.** Chrome과 Edge는 한 번에 설치되고, 그 API가 없는
브라우저(Safari 등)는 버튼을 누르면 직접 하는 방법을 알려준다. 창 테두리 없이 아이콘을 가진
창으로 뜬다.

**An "Install app" button in the header.** Chrome and Edge install it in one step;
browsers without that API (Safari among them) show you where their own manual step is.
You get a window with no browser chrome and its own icon.

**효과가 없던 스킬 차단 스위치를 없앴다.** 직접 돌려보니 `permissions.deny`는 호출만 막고
스킬 목록에서는 빼지 못해 토큰이 줄지 않았다. 이 도구의 목적이 토큰 절감이라 스위치를
없앴고, 예전 버전이 써둔 항목은 서버가 시작할 때 정리한다. 자세한 것은 `docs/ADR.md` 10번.

**The per-skill block switch is gone.** Running it showed that `permissions.deny` blocks
the call but leaves the skill in the list, so it saved no tokens. Saving tokens is the
point of this tool, so the switch went; entries written by older versions are cleaned up
at startup. See section 10 of `docs/ADR.md`.

**Antigravity가 읽는 스킬 폴더를 배지에 반영한다.** `~/.gemini/config/skills/`를 보고
`~/.agents/skills/`는 안 읽는다는 것을 확인해 반영했다.

**Badges now know where Antigravity looks.** It reads `~/.gemini/config/skills/` and not
`~/.agents/skills/`, confirmed by running it.

**색과 마크를 바꿨다.** GitHub 다크모드 같던 파란색을 걷어내고 올리브·머스타드로 옮겼다.
헤더에는 흘수선 마크가 붙었다.

**New colours and mark.** The GitHub-dark-mode blue is gone, replaced by olive and
mustard. The header carries a load-line mark.

### 고친 것 / Fixed

- JSON 객체가 아닌 설정 파일이 있으면 서버가 죽던 문제
  — a settings file that was not a JSON object could kill the server
- 최근 사용 목록이 화면엔 5개만 보이는데 저장은 무한히 쌓이던 문제
  — the recents list showed 5 but stored without limit
- 업데이트 알림이 `install.sh` 재실행과 `brew upgrade`를 함께 안내하도록
  — the update notice now points at both `install.sh` and `brew upgrade`

### 문서 / Docs

랜딩 페이지(영어·한국어)와 결정 기록을 새로 썼다. 검사와 릴리스는 이제 GitHub Actions에서
돈다.

The landing pages (English and Korean) and the decision record were rewritten. Checks and
releases now run on GitHub Actions.

## v0.1.0

첫 공개. / First release.
