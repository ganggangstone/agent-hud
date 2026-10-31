# Agent HUD에서 되는 것과 안 되는 것

Agent HUD를 쓰는 사람과, 사람 대신 HUD를 다루는 에이전트를 위한 문서입니다. v0.6.2 기준입니다.

근거 표시: **[실측]** 직접 실행, **[문서]** 공식 문서, **[미확인]** 확인하지 못함.

## 먼저 알아 둘 것

HUD가 켜고 끌 수 있는 것은 **Claude Code뿐**입니다. 다른 에이전트에는 프로젝트 폴더에 스킬 링크를 놓거나 빼는 일만 합니다.

- **스위치**(항상, /이름 칠 때만 사용, 제외)는 Claude Code의 `skillOverrides`만 씁니다.
- **그룹**은 Claude Code의 플러그인과 스킬을 켜고 끄고, 스킬 링크를 `.claude/skills`와 `.agents/skills`에 놓습니다.
- **머리글의 수**는 HUD의 계산값입니다. 세션에서 실제로 올라간 양을 잰 값이 아닙니다.
- 스위치와 플러그인 변경은 **다음 세션부터** 적용됩니다.

## 에이전트별 표

| 에이전트 | HUD로 스킬 끄기 | 그룹 링크로 스킬 추가 | 지침 집계 |
|---|---|---|---|
| Claude Code | 됨 [실측] | 됨 [실측] | 됨. `claudeMdExcludes`와 `@` 가져오기 반영 [실측]. 상위 폴더, `.claude/CLAUDE.md`, `.claude/rules/`는 아직 안 셈 ([#30](../../../issues/30)) |
| Codex | 안 됨 ([#28](../../../issues/28)) | 됨 (`.agents/skills`) [문서] | 부분. 상위 폴더 탐색 안 함 ([#23](../../../issues/23)), 빈 override 오판 ([#22](../../../issues/22)) |
| Gemini CLI | 안 됨 ([#28](../../../issues/28)) | 됨 (`.agents/skills`) [문서] | 부분. 전역과 루트 `GEMINI.md`만 셈, `@` 가져오기 미반영 |
| Antigravity | 안 됨 | 됨 (`.agents/skills`) [문서] | 안 됨. 항상 0으로 표시 ([#21](../../../issues/21)) |
| Cursor | 안 됨 | 됨. 다만 전역 폴더도 읽어 프로젝트별로 나눌 수 없음 [문서] | 부분. 루트 `AGENTS.md`만 셈 [미확인: 규칙 파일 집계, [#35](../../../issues/35)] |
| Copilot | 안 됨 | 됨. 다만 전역 폴더도 읽어 프로젝트별로 나눌 수 없음 [문서] | 부분. `.github/copilot-instructions.md`와 루트 `AGENTS.md`만 셈 [미확인: [#35](../../../issues/35)] |

## 자주 틀리는 것

| 하려는 일 | 결과 | 대신 할 일 |
|---|---|---|
| 스위치로 Codex 스킬 끄기 | 안 꺼짐 | 그 도구의 설정을 직접 바꾸거나, 프로젝트 링크를 뺌 |
| `claudeMdExcludes`로 Codex 지침 끄기 | Codex는 이 설정을 읽지 않음 | Codex의 파일 구조로 조정 |
| 플러그인 안의 스킬 하나만 끄기 | 안 됨. `permissions.deny`도 토큰을 못 줄임 [실측] | 플러그인을 통째로 끔 |
| 폴더째 링크한 `.agents/skills`에서 "다른 에이전트도 쓰게" 체크 | 쓰기가 막힘 (안전장치) [실측] | 실제 폴더를 두고 스킬별 링크를 사용 |
| 같은 이름의 다른 스킬을 `.claude`와 `.agents`에 두기 | 한 행으로 합쳐져 잘못 표시됨 ([#24](../../../issues/24)) | 이름을 다르게 둠 |
| 전역 스킬과 같은 이름의 프로젝트 스킬 만들기 | Claude Code는 전역 스킬을 먼저 씀 [문서] | 이름을 다르게 둠 |
| `agent-hud --version` | 서버가 뜨고 끝나지 않음 ([#37](../../../issues/37)) | `brew list --versions agent-hud` 또는 `/api/state`의 `version` |

## 에이전트용 안내

HUD 서버는 `http://127.0.0.1:41717`입니다. 없는 경우 임의로 띄우지 말고 사용자에게 알립니다.

**읽기만 하는 것**

```bash
curl -s "http://127.0.0.1:41717/api/state?project=<절대 경로>"   # 패널 전체를 JSON으로
agent-hud groups                                                  # 그룹 목록
agent-hud worktrees [폴더]                                         # worktree의 스킬 상태
agent-hud --help                                                  # 사용법
```

**파일을 바꾸는 것: 사용자가 요청했을 때만**

```bash
agent-hud apply <그룹> [폴더]    # 스킬 링크와 .claude/settings.local.json을 바꿈
agent-hud apply --off [폴더]     # 그룹 스킬 링크를 지움. 플러그인 설정은 그대로
agent-hud worktrees apply [폴더]  # 저장된 스킬 구성을 추가
```

**하지 말 것**

- `agent-hud`, `agent-hud --version`처럼 서버를 띄우는 명령을 확인용으로 실행하지 않습니다. 포그라운드에서 끝나지 않습니다.
- `POST /api/*`로 설정을 바꾸지 않습니다. 화면을 위한 내부 경로이며, 바뀔 수 있습니다.
- 값을 고치려고 `modes.json`이나 `settings.local.json`을 먼저 건드리지 않습니다. 위 명령이 있으면 그 명령을 씁니다.
- 임시 시험에는 실제 데이터 폴더를 쓰지 않습니다. `AGENT_HUD_HOME`과 `AGENT_HUD_PORT`로 분리합니다.

**바꾼 뒤 확인**

1. `/api/state`로 해당 프로젝트의 값을 다시 읽습니다.
2. 스위치와 플러그인 변경은 새 세션을 시작해야 적용된다고 사용자에게 알립니다.
3. 실제 적용 여부가 중요하면 Claude Code 안에서 `/context`로 확인합니다.

## 업데이트

```bash
brew update && brew upgrade agent-hud && brew services restart agent-hud
```

`brew update`를 빼면 tap이 옛 상태로 남아 새 버전을 찾지 못합니다 [실측]. 업데이트 알림은 하루 한 번 확인하므로 릴리스 직후에는 늦게 보일 수 있습니다.

## 확인되지 않은 것

아직 측정이 필요한 동작은 [#35](../../../issues/35)에 모아 둡니다. 이 문서의 내용이 실제 동작과 다르면 이슈로 알려 주세요.
