#!/usr/bin/env bash
# 어떤 설정이 스킬을 에이전트의 스킬 목록에서 실제로 빼는지 센티널 스킬로 잰다(ADR 10).
# 에이전트 CLI를 실제로 호출하므로 자동 테스트에 넣지 않는다. 조건마다 한 번씩 돈다.
#
#   tests/manual/skill_visibility.sh                  # Claude Code만
#   AGY=1 tests/manual/skill_visibility.sh            # agy 프로젝트 조건도
#   AGY=1 ALLOW_GLOBAL=1 tests/manual/skill_visibility.sh
#       # agy 전역 조건도. ~/.gemini/config/skills에 임시 스킬을 넣고 끝나면 지운다.
#
# 대조군(C0, A0)에서 센티널이 안 보이면 나머지 결과로 결론을 내지 말 것.
set -uo pipefail

W=$(mktemp -d)
GLOBAL_SK="$HOME/.gemini/config/skills/zqg-global-5521"
GLOBAL_DIR_CREATED=""
cleanup() {
  rm -rf "$W"
  rm -rf "$GLOBAL_SK"
  # 우리가 만든 폴더면 비어 있을 때만 지운다 -- 그사이 다른 스킬이 생겼으면 건드리지 않는다.
  [ -n "$GLOBAL_DIR_CREATED" ] && rmdir "$HOME/.gemini/config/skills" 2>/dev/null
}
trap cleanup EXIT

LIST='Without using any tools, list the name of every skill available to you in this session, one per line, exactly as given to you. Output nothing else.'

skill() {  # skill <root> <name>
  mkdir -p "$1/$2"
  printf -- '---\nname: %s\ndescription: Converts ribbon counts into lighthouse schedules (%s).\n---\nWhen invoked, reply with exactly: ACK-%s\n' "$2" "$2" "$2" > "$1/$2/SKILL.md"
}

project() {  # project <name> [settings.local.json 내용] -> 경로 출력
  local d="$W/$1"; mkdir -p "$d/.claude"; (cd "$d" && git init -q)
  skill "$d/.claude/skills" zq-sentinel-7731
  [ -n "${2:-}" ] && printf '%s\n' "$2" > "$d/.claude/settings.local.json"
  echo "$d"
}

seen() { grep -c "$2" "$1" || true; }

echo "== Claude Code: 목록에 남는가 =="
for spec in \
  'C0|' \
  'C_deny|{"permissions":{"deny":["Skill(zq-sentinel-7731)"]}}' \
  'C_off|{"skillOverrides":{"zq-sentinel-7731":"off"}}' \
  'C_userinv|{"skillOverrides":{"zq-sentinel-7731":"user-invocable-only"}}' \
  'C_nameonly|{"skillOverrides":{"zq-sentinel-7731":"name-only"}}' \
  'C_builtin|{"skillOverrides":{"dataviz":"off"}}'; do
  name=${spec%%|*}; conf=${spec#*|}
  d=$(project "$name" "$conf")
  (cd "$d" && claude -p "$LIST" > "$W/$name.out" 2>&1)
  echo "$name sentinel=$(seen "$W/$name.out" zq-sentinel-7731) dataviz=$(grep -cx dataviz "$W/$name.out" || true)"
done

echo "== Claude Code: 호출이 막히는가 =="
for spec in 'I0|' 'I_deny|{"permissions":{"deny":["Skill(zq-sentinel-7731)"]}}'; do
  name=${spec%%|*}; conf=${spec#*|}
  d=$(project "$name" "$conf")
  (cd "$d" && claude -p 'Use the Skill tool to invoke the skill named zq-sentinel-7731 and follow it.' \
     --output-format stream-json --verbose > "$W/$name.json" 2>&1)
  echo "$name launched=$(seen "$W/$name.json" 'Launching skill') blocked=$(seen "$W/$name.json" 'blocked by permission rules')"
done

if [ "${AGY:-}" = 1 ] && command -v agy >/dev/null; then
  echo "== Antigravity (agy) =="
  if [ "${ALLOW_GLOBAL:-}" = 1 ]; then
    [ -d "$HOME/.gemini/config/skills" ] || GLOBAL_DIR_CREATED=1
    skill "$HOME/.gemini/config/skills" zqg-global-5521
  fi
  extra="$W/extra"; skill "$extra" zqj-json-5524; skill "$extra" zqk-json-5525
  for spec in \
    'A0|' \
    "A_exclude|{\"entries\":[{\"path\":\"$extra\",\"exclude\":[\"zqk-json-5525\"]},{\"path\":\"~/.gemini/config/skills\",\"exclude\":[\"zqg-global-5521\"]}]}"; do
    name=${spec%%|*}; conf=${spec#*|}
    d="$W/$name"; mkdir -p "$d/.agents"; (cd "$d" && git init -q)
    skill "$d/.agents/skills" zqw-workspace-5523
    [ -n "$conf" ] && printf '%s\n' "$conf" > "$d/.agents/skills.json"
    (cd "$d" && agy -p "$LIST" --mode plan --add-dir "$d" --print-timeout 5m > "$W/$name.out" 2>&1)
    echo "$name workspace=$(seen "$W/$name.out" zqw-workspace-5523) global=$(seen "$W/$name.out" zqg-global-5521) json_added=$(seen "$W/$name.out" zqj-json-5524) json_excluded=$(seen "$W/$name.out" zqk-json-5525)"
  done
fi
