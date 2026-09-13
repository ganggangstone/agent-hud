<p align="center">
  <img src="assets/banner.svg" alt="Agent HUD" width="100%">
</p>

<p align="center">코딩 에이전트의 스킬·지침·플러그인 상태를 한 화면에 보여주는 로컬 대시보드</p>

<p align="center"><a href="README.md">English</a> | <b>한국어</b></p>

<p align="center">
  <img src="assets/screenshot-ko.png" alt="플러그인 & 스킬 탭: 스킬마다 에이전트 뱃지가 붙어 있다" width="640">
</p>

## 목차

- [배경](#배경)
- [화면 구성](#화면-구성)
- [개념](#개념)
- [그룹 설정하기](#그룹-설정하기)
- [설치 (macOS)](#설치-macos)
- [여러 프로젝트·세션에서의 동작](#여러-프로젝트세션에서의-동작)
- [서비스 관리](#서비스-관리)
- [업데이트 확인](#업데이트-확인)
- [확장하기](#확장하기)
- [피드백](#피드백)
- [설계 근거](#설계-근거)
- [라이선스](#라이선스)

## 배경

프로젝트마다 쓰는 스킬이 다르다. 글쓰기, 앱 개발, 인프라는 겹치는 게 거의 없는데,
설치한 스킬은 쓰든 안 쓰든 전부 세션에 올라간다. 스킬의 이름과 설명이 시작할 때
컨텍스트에 들어가기 때문이다.

내 컴퓨터만 해도 플러그인 3개에 스킬이 60개 들어 있었다(커맨드와 훅은 빼고).
[명세](https://agentskills.io/specification) 기준 스킬당 100토큰쯤으로 잡으면
세션마다 5,000~9,000토큰이 나가는데, 대부분은 그 프로젝트와 상관없는 스킬 몫이다.

플러그인을 끌 수는 있지만 설정이 컴퓨터 전체에 하나뿐이라, 이 작업에서만 켜고
다른 데선 끄는 게 안 된다. 세션마다 손으로 바꾸다 보면 금방 질린다.

Agent HUD는 이 프로젝트가 지금 무엇을 로드하는지 보여주고, 작업 종류별로 묶음을
저장해 프로젝트마다 적용할 수 있게 한다. 로컬 파일을 읽어서 그리는 게 전부다.
계정도 외부 서비스도 없다.

## 화면 구성

탭은 세 개고, 한 번에 하나만 보인다.

- **플러그인 & 스킬**: 이 컴퓨터에 있는 스킬 전부. 플러그인별로 묶이고, 어느
  플러그인에도 속하지 않은 스킬은 따로 모인다. 스킬마다 에이전트 뱃지(Claude
  Code·Codex·Cursor·Copilot·Gemini CLI)가 붙어서, 선택한 프로젝트에서 **어느
  에이전트가 그 스킬을 볼 수 있는지** 바로 보인다. 플러그인 켜고 끄기와 스킬 차단도
  여기서 하는데, 둘 다 선택한 프로젝트에만 적용되고, 다른 에이전트에는 그런 개념이
  없어서 `Claude Code 전용`이라고 표시된다
- **그룹**: 같이 쓰는 플러그인과 스킬 묶음. 프로젝트에 적용하면 스킬은 그
  프로젝트에 링크되고, 그룹의 플러그인은 켜지고 나머지는 꺼진다. 그 프로젝트에만
  해당한다
- **에이전트 지침**: `CLAUDE.md`, `AGENTS.md`, `.clinerules`, `.cursor/rules/` 등
  29종을 크기·수정시각과 함께 보여준다. 서로 내용이 어긋난 파일을 찾기 위한 것이다.
  등록된 서브에이전트 목록도 여기 나온다

기본은 다크모드이고(☀/☾로 전환) EN/한국어 전환도 있다. 둘 다 `localStorage`에 저장된다.

## 개념

아래 개념은 따로 표시한 것 말고는 모두 Claude Code 자체의 구조다.

**플러그인(Plugin)**: 마켓플레이스에 올라와 있고 `claude plugin install`로
설치하는 스킬·에이전트·커맨드 묶음. Claude Code는 설정 파일의 `enabledPlugins`로
플러그인을 켜고 끈다. Agent HUD에서 플러그인 옆의 점(dot)을 누르면 그 값을
프로젝트의 `.claude/settings.local.json`에 쓰기 때문에 그 프로젝트에만 적용된다.
다음 세션부터 반영된다.

**마켓플레이스(Marketplace)**: 플러그인을 받아오는 곳. git 저장소나 로컬 경로를
`claude marketplace add`로 등록한다. 플러그인 줄마다 어느 마켓플레이스에서 왔는지
경로가 같이 나오니 따로 찾아볼 필요가 없다. Agent HUD는 보여주기만 하고
마켓플레이스를 추가하거나 관리하지는 않는다. 어떤 출처를 믿을지는 사용자가
`claude` CLI로 직접 정할 일이다.

**스킬(Skill)**: 플러그인 안에 `SKILL.md`로 정의된 기능 하나. Claude Code는
플러그인 단위로만 켜고 끌 수 있고 스킬 하나만 따로 끄는 기능은 없다. 그건 아래
권한 오버라이드로 한다. Agent HUD에서 플러그인 이름을 누르면 스킬 목록이
펼쳐지고, `SKILL.md`에서 읽어온 설명이 각각 붙어 있다.

**권한 오버라이드(Permission override)**: 프로젝트 안의 `.claude/settings.json`에서
`permissions.deny`에 넣는 `"Skill(플러그인:스킬)"` 같은 항목. Claude Code에서 스킬
하나만 끄는 방법이 이것이다. 같은 플러그인의 다른 스킬은 그대로 두고, 그 프로젝트에만
적용된다. Agent HUD의 스킬 점을 누르면 이 항목을 바로 쓰고 지우기 때문에, 플러그인
켜고 끄기와 달리 즉시 반영된다.

**그룹(Group)**: Agent HUD가 추가한 개념으로, Claude Code엔 없다. 같이 쓰는
플러그인과 스킬 묶음에 붙인 이름이다. "글쓰기"용, "영상"용 하는 식이다.
`modes.json`에 저장되며, 파일을 직접 고치거나 그룹 탭에서 관리한다.

**지침(`CLAUDE.md`)**: 전역(`~/.claude/CLAUDE.md`)과 프로젝트별
(`<프로젝트>/CLAUDE.md`) 마크다운이다. Claude Code가 매 세션 상시 지침으로 읽는다.

## 그룹 설정하기

그룹 탭에서 "+ 새 그룹 만들기"를 누르고 이름을 정한 다음 처음 넣을 플러그인 하나를
고른다. 플러그인과 스킬은 그룹 줄에서 더 넣을 수 있다. 프로젝트를 고르고 "이
프로젝트에 적용"을 누르면 그룹의 스킬이 그 프로젝트에 링크되고, 그룹의 플러그인은
켜지고 나머지 플러그인은 꺼진다. 그 프로젝트에만 해당한다. 플러그인 변경은 다음
세션부터 반영된다.

터미널에서도 할 수 있다:

```bash
python3 ~/.claude/tools/agent-hud/server.py groups          # 그룹 목록
python3 ~/.claude/tools/agent-hud/server.py apply dev       # 지금 폴더에 "dev" 적용
python3 ~/.claude/tools/agent-hud/server.py apply --off     # 이 폴더에서 그룹 해제
```

`modes.json`을 직접 고쳐도 된다. 값이 그냥 목록이면 플러그인만 있는 그룹이다:

```json
{
  "dev": {
    "plugins": ["some-plugin@some-marketplace"],
    "skills": ["some-skill"]
  },
  "video": ["video-tools@local"]
}
```

플러그인 이름은 플러그인 & 스킬 탭에 나오는 이름과 `@마켓플레이스` 부분까지 정확히
일치해야 한다. 스킬 이름은 스킬 폴더 이름이다. 저장하면 대시보드가 다음 폴링 때
알아서 반영한다. 재시작할 필요 없다.

## 설치 (macOS)

```bash
git clone https://github.com/ganggangstone/agent-hud.git agent-hud && cd agent-hud
./install.sh
```

설치 스크립트를 실행하면 `server.py`가 `~/.claude/tools/agent-hud/`에 복사되고,
예제로 `modes.json`이 만들어지고, `launchd` 서비스로 등록된다. 이후 대시보드는
터미널이나 Claude Code 세션과 무관하게 계속 떠 있고, 죽으면 자동으로 다시 켜진다.

`~/.claude/settings.json`에 넣을 훅 스니펫은 화면에 출력만 하고 자동으로 넣어주지는
않는다. 이미 다른 훅이 들어 있을 수 있는 파일을 스크립트가 건드리지 않기 위해서다.
출력된 내용을 직접 붙여 넣는다.

`launchd`가 필요해서 이 패키징은 macOS 전용이다. `server.py` 자체엔 OS 종속 코드가
없다. 리눅스에서는 `install.sh` 대신 `systemd --user` 유닛의 `ExecStart`가
`server.py`를 가리키게 하면 된다.

## 여러 프로젝트·세션에서의 동작

서버는 컴퓨터에 하나만 뜨고, 모든 프로젝트가 같이 쓴다. 세션이 시작되면 훅이 서버가
이미 떠 있는지 확인해서, 있으면 지금 프로젝트 경로만 등록하고 없을 때만 새로 띄운다.
같은 프로젝트에서 터미널을 열고 닫아도 서버는 그대로고 포트도 바뀌지 않는다. 등록된
프로젝트가 둘 이상이면 패널에 드롭다운이 생겨 골라 볼 수 있다.

## 서비스 관리

```bash
launchctl list | grep agent-hud                               # 상태
launchctl kickstart -k gui/$(id -u)/com.agent-hud             # server.py 고친 뒤 재시작
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.agent-hud.plist  # 중지
tail -f ~/.claude/tools/agent-hud/launchd.err.log             # 로그
```

세션 훅이 실행되기 전에 `CLAUDE_HUD_DISABLE=1`을 설정하면 새 서버를 띄우지 않는다.
이미 떠 있는 서버에는 영향이 없다.

## 업데이트 확인

대시보드가 12시간마다 GitHub Releases에 새 태그가 있는지 확인하고, 있으면 배너를
띄운다. 다운로드나 설치는 하지 않는다. 업데이트는 클론한 폴더에서 `git pull` 하고
서비스를 재시작하면 된다.

## 확장하기

새 패널: `def collect_x(ctx) -> dict` 함수를 쓰고 `PANELS`에 넣는다.

## 피드백

버그 제보와 제안은 [Issues](../../issues)로 받는다. 대시보드의 "문제 신고하기"
링크를 누르면 버전이 미리 채워진 짧은 폼이 열린다. 영어든 한국어든 편한 쪽으로
쓰면 된다.

## 설계 근거

대안이 있었던 결정들(의존성 없는 단일 파일, 플러그인·스킬 상태를 읽고 쓰는 방식,
웹소켓 대신 폴링인 이유)은 [docs/ADR.md](docs/ADR.md)에 있다.

## 라이선스

MIT. [LICENSE](LICENSE) 참고.
