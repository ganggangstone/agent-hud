# 바뀐 것 / Changelog

각 항목은 한국어 먼저, 영어 다음. Each entry is Korean first, then English.

## v0.5.0

**같은 저장소의 다른 작업 폴더(Git worktree)에도 스킬을 공유할 수 있다.** 전에는 worktree를 새로
만들 때마다 스킬을 다시 공유해야 했다. **플러그인 & 스킬** 탭에서 **같은 저장소의 worktree**를 펼치면
작업 폴더마다 스킬이 있는지 보이고, 고른 스킬을 고른 폴더에 추가할 수 있다. 이미 있는 폴더와 링크는
바꾸지 않고 없는 것만 채운다.

**새 worktree에 자동으로 적용할 수 있다.** 스킬을 고르고 **저장하고 새 worktree에 자동 적용**을 누르면,
HUD가 떠 있는 동안 15초마다 새 worktree를 찾아 같은 스킬을 넣는다. 첫 세션을 열기 전에 바로 넣으려면
그 폴더에서 `agent-hud worktrees apply`를 실행한다. `agent-hud worktrees`는 상태만 보여준다.

스킬 파일만 공유한다. 플러그인의 훅, MCP, 설정과 그룹의 플러그인 스위치는 옮기지 않는다.

**Share skills with other worktrees of the same repository.** You used to share skills again
for every new worktree. Open **Worktrees in this repository** on the **Plugins & skills** tab
to see which skills each worktree has, and add the ones you pick to the worktrees you pick.
Existing folders and links are left alone; only missing ones are added.

**Apply to new worktrees automatically.** Pick skills and click **Save and enable for new
worktrees**: while HUD is running it checks for new worktrees every 15 seconds and adds the
same skills. To add them before the first session starts, run `agent-hud worktrees apply` in
that folder. `agent-hud worktrees` only prints the state.

Only skill files are shared. Plugin hooks, MCP servers, settings and a group's plugin switches
are not moved.

## v0.4.3

**사이드바에서 프로젝트를 목록에서 뺄 수 있다.** 전에는 한 번 올라간 프로젝트를 뺄 방법이 없었다.
프로젝트 줄에 마우스를 올리면 × 버튼이 보인다. 목록에서만 빼고 폴더와 그 안의 설정은 그대로 둔다.
그 폴더에서 세션을 다시 열면 목록에 다시 올라온다.

**그룹에 플러그인이나 스킬을 추가하면 바로 목록에 보인다.** 전에는 저장은 됐는데 화면의 다른 곳을
누르기 전까지 새 줄이 나타나지 않아서, 추가가 안 된 것처럼 보였다.

**You can remove a project from the sidebar.** There was no way to take a project off the list
once it was there. Hover over a project and click ×. It only leaves the list; the folder and
its settings stay as they are. Opening a session in that folder adds it back.

**Adding a plugin or skill to a group shows it right away.** It was saved, but the new row
didn't appear until you clicked somewhere else on the page, so it looked like nothing happened.

## v0.4.2

**설치본이 마지막으로 확인한 최신 버전보다 새것이면 업데이트 알림이 뜨지 않는다.** 최신 버전은 하루에
한 번만 확인한다. 그 사이에 `brew upgrade`로 먼저 올리면 "새 버전이 나왔습니다: v0.4.0 (지금은 v0.4.1)"처럼
옛 버전을 권했고, 버튼을 누르면 "Homebrew does not have the new version yet"으로 실패했다.

**No update notice when the installed version is newer than the last one checked.** The
latest version is checked once a day. Upgrading with `brew upgrade` in between made the notice
offer the older version ("v0.4.0 is out, you're on v0.4.1"), and its button failed with
"Homebrew does not have the new version yet".

## v0.4.1

**세션 여러 개를 한꺼번에 열면 사이드바의 프로젝트 목록이 비던 문제를 고쳤다.** 두 곳이 동시에
목록 파일을 쓰면 파일이 깨졌고, 그다음 읽는 쪽이 빈 목록으로 알고 그 위에 새로 써서 그전까지
쌓인 프로젝트가 전부 사라졌다. 그룹 파일도 같은 방식으로 쓰도록 고쳤다. 이미 사라진 프로젝트는
세션을 다시 열거나 "+ 폴더 추가"로 넣으면 돌아온다.

**"+ 폴더 추가"가 Finder의 폴더 고르기 창을 띄운다.** 전에는 경로를 직접 입력해야 했다. Finder 창을
띄울 수 없는 환경에서는 전처럼 경로를 입력받는다.

**Opening several sessions at once no longer empties the sidebar's project list.** Two writes
to the list at the same moment could corrupt the file, and the next reader took it as empty
and wrote over it, dropping every project added before. Group files are now written the same
safe way. Projects already lost come back when you open a session there again or add them
with "+ add a folder".

**"+ add a folder" opens the Finder folder picker.** You used to type the path. Where the
picker can't open, it still asks for the path.

## v0.4.0

**Homebrew로 설치했다면 업데이트 알림의 버튼 하나로 업데이트된다.** "지금 업데이트"를 누르면
대시보드가 `brew update`와 `brew upgrade agent-hud`를 실행하고 새 코드로 다시 뜬다. git으로
설치했다면 AI 에이전트에게 보낼 업데이트 요청 문장을 복사해 준다. README에 에이전트가 따라 할
설치·열기·업데이트 절차를 적었다.

**With a Homebrew install, one button in the update notice updates it.** "Update now" runs
`brew update` and `brew upgrade agent-hud`, then restarts the dashboard on the new code.
A cloned install gets a button that copies an update request for your AI agent. The README
now has install, open, and update steps written for an agent to follow.

**주소가 `127.0.0.1:41717`로 고정된다.** 전에는 7717에서 시작해 자리가 차 있으면 다음 번호로
밀려서, 북마크와 앱으로 설치한 아이콘이 다른 프로그램을 열 수 있었다. 이제 다른 프로그램이
41717을 쓰고 있으면 비기를 기다리고 로그에 알린다. `AGENT_HUD_PORT`로 바꿀 수 있다. 또 그 포트에
응답하는 게 Agent HUD일 때만 이미 떠 있다고 본다. 전에는 열려 있기만 하면 떠 있다고 보고 끝내서,
다른 프로그램이 그 포트를 쓰면 서버가 뜨자마자 끝나기를 반복했다.

**한 프로젝트 안에만 있는 스킬도 그룹에 넣는다.** 전에는 플러그인과 사용자 스킬 폴더의 스킬만
그룹 후보였다. 이제 사이드바의 프로젝트 안에 실제 폴더로 놓인 스킬도 목록에
나오고, 그룹을 적용한 다른 프로젝트에는 그 폴더를 가리키는 링크가 걸린다.

**그룹의 "플러그인 또는 스킬 추가" 목록이 몇 초 만에 닫히던 문제를 고쳤다.** 화면이 주기마다 탭을
통째로 다시 그리면서 펼쳐 둔 목록도 새로 만들었다. 이제 탭 안의 목록이나 입력 칸을 쓰는 동안에는
다시 그리지 않는다.

**`agent-hud open`으로 대시보드를 연다.** 떠 있으면 브라우저 탭을 열고, 꺼져 있으면 띄운 뒤 연다.

**응용 프로그램 폴더에 Agent HUD 앱이 생긴다.** `brew install --cask ganggangstone/tap/agent-hud-app`로
설치하면 Launchpad에서 누를 수 있는 앱 아이콘과 `agent-hud` 명령이 함께 깔린다. 앱은 `agent-hud open`을
실행한다.

**The address is fixed at `127.0.0.1:41717`.** It used to start at 7717 and move up when
that port was taken, so bookmarks and the installed app could open another program. Now, if
another program holds 41717, the dashboard waits for it and says so in the log;
`AGENT_HUD_PORT` changes the port. It also treats the port as its own only when Agent HUD
answers there. Before, any open port counted, so another program on it made the server exit
on every start.

**Skills that live inside one project can go into a group.** Only plugin skills and user
skill folders used to be candidates. A skill kept as a real folder inside a project in the
sidebar now appears in the list, and other projects the group is applied to get a
link to that folder.

**The "add a plugin or skill" list in a group no longer closes after a few seconds.** The
page redrew the whole tab on every refresh, replacing the open list. It now skips the redraw
while you are using a list or text field in the tab.

**`agent-hud open` opens the dashboard,** starting it first if it is not running.

**An Agent HUD app in Applications.** `brew install --cask ganggangstone/tap/agent-hud-app`
installs an app icon you can click in Launchpad along with the `agent-hud` command. The app
runs `agent-hud open`.

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
