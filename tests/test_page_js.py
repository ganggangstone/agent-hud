"""페이지에 실린 자바스크립트가 문법적으로 성립하는지 본다.
   여기가 깨지면 대시보드는 200을 돌려주고 헤더만 그린 채 아무것도 안 나온다 --
   파이썬 테스트도 curl도 전부 통과하므로 이 검사가 없으면 아무도 못 잡는다.
   python3 tests/test_page_js.py"""
import importlib.util, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("hud", os.path.join(ROOT, "server.py"))
hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hud)


WT_HARNESS = r"""
class El {
  constructor(tag){ this.tag = tag; this.children = []; this.style = {}; this.dataset = {}; this.className = ''; this._text = ''; this.open = false; this.disabled = false; }
  appendChild(c){ this.children.push(c); return c; }
  set textContent(v){ this.children = []; this._text = String(v); }
  get textContent(){ return this._text + this.children.map(c => c.textContent).join(''); }
  find(pred, out = []){ for(const c of this.children){ if(pred(c)) out.push(c); c.find(pred, out); } return out; }
  querySelectorAll(tag){ return this.find(c => c.tag === tag); }
}
const document = { createElement: tag => new El(tag), createTextNode: s => { const e = new El('#text'); e._text = s; return e; } };
const assert = require('assert');
const alert = () => {}, confirm = () => true, fetch = async () => ({json: async () => ({})});
async function rerender(){}
__T__
let lang = 'en'; function t(){ return T[lang]; }
__STATE__
__FNS__
const PROJECT = '/repo';
const states = [['a','.agents/skills','linked'],['a','.claude/skills','conflict'],
  ['b','.agents/skills','original'],['b','.claude/skills','missing']];
const mkW = () => ({
  can_apply: true, enabled: false, poll_seconds: 5, query_failed: false,
  config: {skills: [{name:'a',source:'/s1/a'},{name:'b',source:'/s1/b'}], dirs: ['.agents/skills','.claude/skills']},
  skills: [{name:'a',source:'/s1/a'},{name:'a',source:'/s2/a'},{name:'b',source:'/s1/b'},{name:'c',source:'/s1/c'}],
  rows: [{path:'/wt1', branch:'x', mode:'inherit', available:true, result:{at:1, error:'boom'},
          skills: states.map(([name,dir,state]) => ({name,dir,state}))}]
});
const render = (w = mkW(), project = PROJECT) => { const c = new El('div'); renderWorktrees(c, w, project); return c; };
const btn = (c, text) => c.find(e => e.tag === 'button' && e.textContent === text)[0];
const skillRow = (c, name) => c.find(e => e.className === 'wt-skill' && e.dataset.name === name)[0];
const detailOf = c => c.find(e => e.tag === 'details' && e.className === 'wt-detail')[0];

let c = render();
// 1. 접힌 상태: 폴더별 개수 요약, 경고 상태는 스킬/폴더/상태가 보인다
const line = c.find(e => e.className === 'wt-row')[0];
const dim = line.find(e => e.className === 'dim')[0];
assert(dim.textContent.includes('.agents/skills: Connected 1, Source folder 1'), dim.textContent);
assert(dim.textContent.includes('.claude/skills: Different source 1, Missing 1'), dim.textContent);
assert(!dim.textContent.includes('a (.agents/skills)'), 'old per-skill list remains');
assert(dim.textContent.includes('boom'), 'result error lost');
const details = detailOf(line);
const warn = line.find(e => e.className === 'wt-warn')[0];
assert(warn && !details.find(e => e === warn).length, 'warning must be outside details');
assert(warn.textContent.includes('a') && warn.textContent.includes('.claude/skills') && warn.textContent.includes('Different source'), warn.textContent);
assert(!warn.textContent.includes('Missing') && !warn.textContent.includes('Connected'), warn.textContent);
// 2. 상세 표: 스킬 한 행, 폴더별 상태 열, 처음엔 접힘
assert.strictEqual(details.open, false);
const rows = details.find(e => e.tag === 'tr').map(tr => tr.children.map(td => td.textContent));
assert.deepStrictEqual(rows, [[T.en.wt_skill_col, '.agents/skills', '.claude/skills'],
  ['a','Connected','Different source'], ['b','Source folder','Missing']]);
// 3. 폴링 재렌더 뒤에도 프로젝트+워크트리별 펼침 유지
details.open = true; details.ontoggle();
assert.strictEqual(detailOf(render()).open, true);
assert.strictEqual(detailOf(render(mkW(), '/other')).open, false);
// 3b. 원본 경로 details: 처음엔 접힘, 열면 재렌더 뒤에도 유지, 다른 project는 접힘. 표 머리는 th scope=col
const srcOf = cc => skillRow(cc, 'c').find(e => e.tag === 'details')[0];
assert.strictEqual(srcOf(c).open, false);
const src = srcOf(render()); src.open = true; src.ontoggle();
assert.strictEqual(srcOf(render()).open, true);
assert.strictEqual(srcOf(render(mkW(), '/other')).open, false);
const ths = details.find(e => e.tag === 'th');
assert.strictEqual(ths.length, 3);
assert(ths.every(th => th.scope === 'col'));
// 4. 저장 구성 기준 문구
assert(T.en.wt_state_note && T.ko.wt_state_note);
assert.strictEqual(c.find(e => e.className === 'note' && e.textContent === T.en.wt_state_note).length, 1);
// 5. 같은 이름 다른 원본: 한 행, select로 원본 선택, draft 유지, 이름당 하나
assert.deepStrictEqual(c.find(e => e.className === 'wt-skill').map(e => e.dataset.name), ['a','b','c']);
const sel = skillRow(c, 'a').find(e => e.tag === 'select')[0];
assert.deepStrictEqual(sel.children.map(o => o.value), ['/s1/a','/s2/a']);
assert.strictEqual(sel.value, '/s1/a');
assert(!skillRow(c, 'c').find(e => e.tag === 'select').length, 'single source needs no select');
assert(skillRow(c, 'c').find(e => e.tag === 'details')[0].textContent.includes('/s1/c'), 'full source in details');
const draft = worktreeDrafts[PROJECT];
draft.preview = {ok: true, rows: []};
sel.value = '/s2/a'; sel.onchange();
assert.deepStrictEqual(draft.skills.filter(s => s.name === 'a'), [{name:'a',source:'/s2/a'}]);
assert.strictEqual(draft.preview, null, 'select change must invalidate preview');
assert.strictEqual(btn(c, T.en.wt_apply).disabled, true);
assert.strictEqual(skillRow(render(), 'a').find(e => e.tag === 'select')[0].value, '/s2/a');
// 체크 변경도 미리보기를 무효화하고 이름당 하나만 남긴다
draft.preview = {ok: true, rows: []};
const cb = skillRow(c, 'b').find(e => e.tag === 'input')[0];
cb.checked = false; cb.onchange();
assert(!draft.skills.some(s => s.name === 'b') && draft.preview === null);
cb.checked = true; cb.onchange();
assert.deepStrictEqual(draft.skills.filter(s => s.name === 'b'), [{name:'b',source:'/s1/b'}]);
// 6. 인덱스에 없는 저장된 원본도 한 행 안에서 유지
worktreeDrafts[PROJECT].skills = [{name:'a',source:'/gone/a'}];
const gone = skillRow(render(), 'a').find(e => e.tag === 'select')[0];
assert.deepStrictEqual(gone.children.map(o => o.value), ['/s1/a','/s2/a','/gone/a']);
assert.strictEqual(gone.value, '/gone/a');
// ko에서도 키 누락 없이 그려진다
lang = 'ko'; render(); lang = 'en';
"""


def check_worktrees(js):
    """renderWorktrees를 최소 DOM 위에서 실제로 실행한다."""
    fns = js[js.index("function wtState"):js.index("async function tick()")]
    state = js[js.index("const worktreeDrafts"):js.index("let worktreeOpen = false;")] + "let worktreeOpen = false;"
    table = re.search(r"const T = \{.*?\n\};", js, re.S).group(0)
    script = WT_HARNESS.replace("__T__", table).replace("__STATE__", state).replace("__FNS__", fns)
    r = subprocess.run([shutil.which("node"), "-"], input=script, capture_output=True, text=True)
    assert r.returncode == 0, f"renderWorktrees 실행 검사 실패:\n{r.stderr}"


TOK_CHECKS = r"""
const AGENTS = ['Claude Code', 'Gemini CLI', 'Codex'];
const full = {state: 'ok', encoding: 'o200k_base', setup: 'x', skills: 8, measured: 8, total: 1234,
  agents: {'Claude Code': {skills: 4, measured: 4, tokens: 17}, 'Gemini CLI': {skills: 3, measured: 3, tokens: 19}, 'Codex': {skills: 0, measured: 0, tokens: 0}}};
const ok = full;
const part = {...full, measured: 7, agents: {'Claude Code': {skills: 4, measured: 3, tokens: 17},
  'Gemini CLI': {skills: 3, measured: 0, tokens: 0}, 'Codex': {skills: 1, measured: 1, tokens: 5}}};
const draw = (tk, agents = AGENTS) => { const c = new El('div'); renderTokens(c, tk, agents); return c.children[0]; };
// 1. 전부 센 경우: 이름+설명 기준임을 밝히고, 에이전트별 수를 보여준다. "부분 합계"라는 말은 없다
let box = draw(full);
assert(box.textContent.includes('o200k_base') && box.textContent.includes('name + description only'), box.textContent);
assert(box.textContent.includes('1,234 across 8 discovered skills'), box.textContent);
assert(box.textContent.includes('Claude Code 17 tokens (4 skills)') && box.textContent.includes('Gemini 19 tokens (3 skills)') && box.textContent.includes('Codex 0 tokens (0 skills)'), box.textContent);
assert(!box.textContent.includes('subtotal') && !box.textContent.includes('Not counted'), box.textContent);
assert(box.textContent.includes('not live session usage'), box.textContent);
assert(box.title.includes('reference count') && box.title.includes('not any provider'), box.title);
// 1b. 일부만 센 경우: 전체 합계가 아니라 센 것의 합이라고 전체와 에이전트마다 밝힌다
box = draw(part);
assert(box.textContent.includes('Measured subtotal') && box.textContent.includes('1,234 in 7 of 8 discovered skills') && box.textContent.includes('not a full total'), box.textContent);
assert(!box.textContent.includes('across 8'), box.textContent);
assert(box.textContent.includes('Not counted: 1'), box.textContent);
assert(box.textContent.includes('Claude Code 17 tokens measured (3 of 4)'), box.textContent);
assert(box.textContent.includes('Gemini not measured (0 of 3)') && !/Gemini 0/.test(box.textContent), box.textContent);
assert(box.textContent.includes('Codex 5 tokens (1 skill)'), box.textContent);
// 1c. 볼 수 있는 스킬이 있는데 하나도 못 셌으면 0이 아니라 "측정 안 함". 정말 0개일 때만 0
box = draw({...full, skills: 1, measured: 0, total: 0, agents: {'Claude Code': {skills: 1, measured: 0, tokens: 0}, 'Gemini CLI': {skills: 0, measured: 0, tokens: 0}, 'Codex': {skills: 0, measured: 0, tokens: 0}}});
assert(box.textContent.includes('none of the 1 discovered skills could be counted'), box.textContent);
assert(!/across|subtotal|Claude Code 0 tokens/.test(box.textContent) && box.textContent.includes('Claude Code not measured (0 of 1)') && box.textContent.includes('Gemini 0 tokens (0 skills)'), box.textContent);
box = draw({...full, skills: 0, measured: 0, total: 0, agents: {}});
assert(box.textContent.includes('0 across 0 discovered skills'), box.textContent);
// 2. 측정 안 함: 숫자를 지어내지 않고 setup 명령을 그대로 보여준다
for(const state of ['setup', 'import', 'cache', 'download', 'error', 'weird']){
  box = draw({...ok, state, total: null, setup: 'agent-hud tokens setup'});
  assert(box.textContent.includes('not measured') && !/\b0 tokens|1,234|17/.test(box.textContent), box.textContent);
  assert.strictEqual(box.find(e => e.tag === 'code')[0].textContent, 'agent-hud tokens setup');
}
assert.strictEqual(draw(null), undefined);
// 3. 스킬 뱃지: 숫자는 숫자로, 못 센 스킬은 n/a, 측정이 꺼져 있으면 아무것도 안 붙인다
assert.strictEqual(tokTag({tokens: 1502}, ok).textContent, '1,502 tok');
assert.strictEqual(tokTag({tokens: null}, ok).textContent, T.en.tok_skill_na);
assert.strictEqual(tokTag({tokens: null}, {state: 'setup'}), null);
assert.strictEqual(tokTag({tokens: 5}, null), null);
// 4. ko에서도 키 누락 없이 그려진다
lang = 'ko';
assert(draw(ok).textContent.includes('이름+설명만'));
box = draw(part);
assert(box.textContent.includes('전체 합계가 아닙니다') && box.textContent.includes('8개 중 7개') && !box.textContent.includes('합계 1,234'), box.textContent);
assert(box.textContent.includes('Claude Code 17토큰 · 4개 중 3개만 측정') && box.textContent.includes('Gemini 미측정 (3개 중 0개)'), box.textContent);
box = draw({...full, skills: 1, measured: 0, total: 0, agents: {'Claude Code': {skills: 1, measured: 0, tokens: 0}}});
assert(box.textContent.includes('찾은 스킬 1개를 하나도 세지 못했습니다') && !box.textContent.includes('합계'), box.textContent);
for(const state of ['setup', 'import', 'cache', 'download', 'error']) draw({...ok, state, total: null});
assert(tokTag({tokens: 3}, ok).textContent.includes('3'));
"""


def check_tokens(js):
    """renderTokens/tokTag를 같은 최소 DOM 위에서 실제로 실행한다."""
    fns = re.search(r"function tokTag.*?\nfunction renderTokens.*?\n}\n", js, re.S).group(0)
    table = re.search(r"const T = \{.*?\n\};", js, re.S).group(0)
    head = WT_HARNESS.split("__T__")[0]
    script = (head + table + "\nlet lang = 'en'; function t(){ return T[lang]; }\n"
              "const shortAgent = a => a.replace(' CLI','');\n" + fns + TOK_CHECKS)
    r = subprocess.run([shutil.which("node"), "-"], input=script, capture_output=True, text=True)
    assert r.returncode == 0, f"renderTokens 실행 검사 실패:\n{r.stderr}"


def main():
    node = shutil.which("node")
    if not node:
        print("SKIP (node 없음)")
        return
    blocks = re.findall(r"<script>(.*?)</script>", hud.PAGE, re.S)
    assert blocks, "PAGE에 <script>가 없다"
    for i, js in enumerate(blocks):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(js)
            path = f.name
        try:
            r = subprocess.run([node, "--check", path], capture_output=True, text=True)
            assert r.returncode == 0, f"script[{i}] 문법 오류:\n{r.stderr}"
        finally:
            os.unlink(path)
    check_worktrees(max(blocks, key=len))
    check_tokens(max(blocks, key=len))
    print(f"PASS ({len(blocks)} script block)")


if __name__ == "__main__":
    main()
