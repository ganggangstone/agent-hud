# 바뀐 것 / Changelog

각 항목은 한국어 먼저, 영어 다음. Each entry is Korean first, then English.

## v0.3.0

**플러그인 밖 스킬도 프로젝트마다 켜고 끈다.** `~/.claude/skills`나 프로젝트에 직접 둔 스킬에
켜짐/꺼짐 스위치가 생겼다. 프로젝트의 `.claude/settings.local.json`에 `skillOverrides`로 쓰고,
Claude Code에만 적용된다. 그룹을 적용하면 그룹에 없는 플러그인 밖 스킬도 꺼진다. 플러그인에 든
스킬은 전처럼 플러그인째 켜고 끈다.

**Skills outside a plugin can be switched per project.** Skills in `~/.claude/skills` or in
the project now have an ON/OFF switch, written as `skillOverrides` in the project's
`.claude/settings.local.json`; it applies to Claude Code only. Applying a group also turns
off skills outside a plugin that aren't in the group. Skills inside a plugin still go on
and off with their plugin.

### 문서 / Docs

README의 그룹 절에 그룹이 어느 에이전트에 적용되는지, 여러 에이전트를 쓸 때 스킬을 어느 폴더에
두면 프로젝트마다 나뉘는지를 적었다.

The README's groups section now says which agents a group applies to, and which folder to
keep skills in so they split per project across agents.

## v0.2.1

**업데이트 확인을 하루에 한 번만 한다.** 12시간마다 하던 확인을 하루에 한 번으로 줄였다.
서버가 다시 켜져도(로그인, 재시작) 마지막 확인에서 하루가 지나기 전에는 확인하지 않는다.

**Update checks run once a day.** Down from every 12 hours, and a restarted server (login,
relaunch) no longer checks again until a day has passed since the last check.

### 고친 것 / Fixed

- `.claude/settings.json`이 `[]`처럼 JSON 객체가 아니면 그 프로젝트 화면 전체가 비던 문제
  — a settings file that wasn't a JSON object (such as `[]`) blanked the whole project view
- Homebrew 설치 안내의 훅이 서비스가 꺼져 있을 때 세션 시작을 붙잡던 문제. 이미 넣어 둔
  훅은 명령 앞에 `nohup `, 끝에 ` & disown`을 붙이면 된다
  — the hook printed by the Homebrew install could hold up session start while the service
  was stopped; for a hook you already added, prefix the command with `nohup ` and end it
  with ` & disown`

### 문서 / Docs

README 빠른 시작을 세 단계로 줄이고 Homebrew를 기본 설치로 두었다. 훅은 선택 사항이다.
README와 랜딩 맨 위에 데모 GIF를 넣고, 코드와 다르던 문장을 고쳤다.

The README quickstart is down to three steps with Homebrew as the default install, and the
hook is optional. The README and landing pages open with a demo GIF, and sentences that
didn't match the code were corrected.

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

- 업데이트 알림이 `install.sh` 재실행과 `brew upgrade`를 함께 안내하도록
  — the update notice now points at both `install.sh` and `brew upgrade`

### 문서 / Docs

랜딩 페이지(영어·한국어)와 결정 기록을 새로 썼다. 검사와 릴리스는 이제 GitHub Actions에서
돈다.

The landing pages (English and Korean) and the decision record were rewritten. Checks and
releases now run on GitHub Actions.

## v0.1.0

첫 공개. / First release.
