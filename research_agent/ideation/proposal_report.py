"""Allowlisted, atomic exports of proposal drafts; no raw abstracts or workspace dump."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import shutil
from tempfile import mkdtemp
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED
import json

from research_agent.core.paths import safe_child
from research_agent.retrieval.index import _write, _fsync_directory
from research_agent.retrieval.report import _text


def _only(value, fields):
    if not isinstance(value, dict):
        raise ValueError("Expected report object")
    return {key: deepcopy(value[key]) for key in fields if key in value}


def export_payload(result: dict) -> dict:
    if result.get("schema_version") == "research-package-v1":
        result = result.get("proposal_set", {})
    if result.get("schema_version") != "idea-proposal-set-v1" or result.get("status") != "completed":
        raise ValueError("A completed proposal set is required")
    out = _only(result, ("schema_version", "status", "generation_method", "limitations"))
    out["source_search"] = _only(result["source_search"], ("index_id", "snapshot_id", "snapshot_checksum"))
    out["evidence_cards"] = []
    for item in result["evidence_cards"]:
        card = _only(item, ("evidence_id", "record_key", "paper_id", "title", "conference", "year", "abstract_status", "abstract_excerpt", "support_relation", "lexical_themes"))
        card["abstract_excerpt"] = card.get("abstract_excerpt", "")[:320]
        card["provenance"] = _only(item["provenance"], ("shard_path", "shard_sha256", "record_number", "record_sha256"))
        out["evidence_cards"].append(card)
    evidence_ids = {c["evidence_id"] for c in out["evidence_cards"]}
    out["proposals"] = []
    for item in result["proposals"]:
        if item.get("epistemic_status") != "HYPOTHESIS" or not item.get("evidence_ids") or not set(item["evidence_ids"]) <= evidence_ids:
            raise ValueError("Proposal hypothesis or evidence references are invalid")
        proposal = _only(item, ("id", "theme", "title", "epistemic_status", "evidence_ids", "evidence_relation", "research_question", "mechanism", "predictions", "competing_explanations", "risks", "verification_steps"))
        proposal["experiment_blueprint"] = _only(item["experiment_blueprint"], ("baseline", "data_requirements", "primary_measurement", "ablations", "failure_criteria"))
        out["proposals"].append(proposal)
    if not out["proposals"]:
        raise ValueError("No proposals to export")
    return out


def markdown(result: dict) -> str:
    result = export_payload(result)
    lines = ["# 研究方向与实验方案草案", "", "以下为离线规则生成的研究假设；引用论文提供背景，尚未证明所提机制有效。", "",
             f"快照：{_text(result['source_search']['snapshot_id'])}", ""]
    labels = (("research_question", "研究问题"), ("mechanism", "机制假设"), ("predictions", "可检验预测"),
              ("competing_explanations", "竞争性解释"), ("risks", "风险"), ("verification_steps", "验证顺序"))
    def field(label, value):
        lines.extend([f"### {label}", ""])
        if isinstance(value, list):
            lines.extend("- " + _text(x) for x in value)
        else:
            lines.append(_text(value))
        lines.append("")
    for i, proposal in enumerate(result["proposals"], 1):
        lines.extend([f"## {i}. {_text(proposal['title'])}", "", "状态：HYPOTHESIS / 待验证", "",
                      "背景证据：" + ", ".join(_text(x) for x in proposal["evidence_ids"]), ""])
        for name, label in labels[:4]:
            field(label, proposal[name])
        for name, label in (("baseline", "实验：基线"), ("data_requirements", "实验：数据要求"), ("primary_measurement", "实验：主指标"), ("ablations", "实验：消融"), ("failure_criteria", "实验：证伪条件")):
            field(label, proposal["experiment_blueprint"][name])
        for name, label in labels[4:]:
            field(label, proposal[name])
    lines.extend(["## 证据卡", ""])
    for card in result["evidence_cards"]:
        p = card["provenance"]
        lines.extend([f"### {_text(card['evidence_id'])} · {_text(card['title'])}", "",
                      f"{_text(card['conference'])} / {card['year']} · 摘要：{_text(card['abstract_status'])}", "",
                      _text(card["abstract_excerpt"]) or "摘要缺失；当前只核对了标题和来源定位。", "",
                      f"来源：{_text(p['shard_path'])}，非空记录 {p['record_number']}；记录 SHA256：{_text(p['record_sha256'])}", ""])
    field("目前证据边界", result["limitations"])
    return "\n".join(lines)


def html_dashboard(result: dict) -> str:
    """Render a self-contained editorial research dashboard."""
    payload = export_payload(result)
    embedded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # Prevent an excerpt or title from terminating the data script element.
    embedded = embedded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Idea Atlas · 研究提案工作台</title>
<style>
:root {{ --paper:#f4f3ef; --ink:#1f2422; --muted:#707773; --rule:#d7d9d3; --panel:#fbfbf8; --accent:#b4472f; --accent-soft:#f1ddd5; --teal:#3b7770; --shadow:0 14px 40px rgba(31,36,34,.07); }}
* {{ box-sizing:border-box }} body {{ margin:0; color:var(--ink); background:var(--paper); font:16px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }}
button {{ font:inherit }} .shell {{ max-width:1480px; margin:auto; padding:24px 34px 64px }}
.topbar {{ display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid var(--ink); padding-bottom:14px; letter-spacing:.04em }}
.brand {{ display:flex; gap:12px; align-items:center; font-size:13px; font-weight:800; letter-spacing:.16em }} .brand-mark {{ width:24px;height:24px;border:1.5px solid var(--ink);display:grid;place-items:center;font-size:11px }}
.topmeta {{ color:var(--muted); font-size:12px; display:flex; gap:16px; align-items:center }} .toggle {{ border:1px solid var(--rule); background:transparent; padding:4px 9px; cursor:pointer; color:var(--muted) }}
.masthead {{ display:grid; grid-template-columns:minmax(0,1fr) 340px; gap:40px; padding:48px 0 34px; border-bottom:1px solid var(--rule) }}
.kicker {{ color:var(--accent); font-size:12px; font-weight:800; letter-spacing:.16em; text-transform:uppercase }} h1 {{ font:500 clamp(36px,5.2vw,78px)/.98 Georgia,"Times New Roman",serif; letter-spacing:-.045em; margin:13px 0 18px; max-width:850px }}
.lede {{ max-width:700px; color:var(--muted); font-size:17px }} .snapshot {{ align-self:end; border-left:2px solid var(--accent); padding-left:18px; color:var(--muted); font-size:13px }} .snapshot strong {{ display:block;color:var(--ink);font-size:15px;margin-bottom:4px }}
.stats {{ display:grid; grid-template-columns:repeat(3,1fr); gap:1px; background:var(--rule); border-bottom:1px solid var(--rule) }} .stat {{ background:var(--paper); padding:22px 20px 18px }} .stat b {{ display:block; font:500 42px/1 Georgia,serif; letter-spacing:-.04em }} .stat span {{ color:var(--muted); font-size:12px; letter-spacing:.08em }}
.workspace {{ display:grid; grid-template-columns:250px minmax(0,1fr); gap:42px; padding-top:34px }} .rail {{ position:sticky; top:16px; align-self:start }} .rail-title {{ font-size:11px; letter-spacing:.14em; color:var(--muted); text-transform:uppercase; margin-bottom:12px }}
.proposal-nav {{ display:grid; gap:7px }} .proposal-nav button {{ text-align:left; cursor:pointer; background:transparent; border:0; border-left:2px solid transparent; padding:10px 12px; color:var(--muted) }} .proposal-nav button.active {{ border-left-color:var(--accent); background:var(--accent-soft); color:var(--ink) }} .proposal-nav small {{ display:block; font-size:11px; margin-top:3px; color:var(--muted) }}
.rail-note {{ margin-top:36px; border-top:1px solid var(--rule); padding-top:14px; font-size:12px; color:var(--muted) }} .rail-note b {{ color:var(--ink); display:block; margin-bottom:5px }}
.content {{ min-width:0 }} .section-label {{ display:flex;align-items:baseline;justify-content:space-between;border-bottom:1px solid var(--ink);padding-bottom:9px;margin-bottom:20px }} .section-label h2 {{ font:500 25px Georgia,serif; margin:0 }} .section-label span {{ color:var(--muted);font-size:12px }}
.proposal {{ background:var(--panel); border:1px solid var(--rule); box-shadow:var(--shadow); padding:28px 30px 30px; position:relative; overflow:hidden }} .proposal:before {{ content:""; position:absolute; inset:0 auto 0 0; width:5px; background:var(--accent) }} .proposal-head {{ display:flex; justify-content:space-between; gap:20px; align-items:flex-start }} .proposal h3 {{ font:500 clamp(25px,3vw,42px)/1.08 Georgia,serif; letter-spacing:-.035em; margin:0 0 10px; max-width:760px }} .tag {{ white-space:nowrap; border:1px solid var(--accent); color:var(--accent); padding:5px 9px; font-size:11px; letter-spacing:.12em }}
.question {{ font-size:19px; max-width:850px; margin:20px 0 24px }} .label {{ color:var(--muted); font-size:11px; letter-spacing:.12em; text-transform:uppercase; margin-bottom:5px }}
.twocol {{ display:grid; grid-template-columns:1.1fr .9fr; gap:26px; border-top:1px solid var(--rule); padding-top:22px }} .mechanism {{ font-size:15px }} .evidence-chips {{ display:flex;flex-wrap:wrap;gap:6px }} .chip {{ border:1px solid var(--rule);padding:4px 7px;color:var(--teal);font-size:12px;background:#f3f7f4 }}
.blueprint {{ margin-top:28px; border-top:1px solid var(--ink); padding-top:18px }} .blueprint h4 {{ font:500 21px Georgia,serif; margin:0 0 14px }} .blueprint-grid {{ display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--rule);border:1px solid var(--rule) }} .blueprint-cell {{ background:var(--panel);padding:15px 17px;min-height:108px }} .blueprint-cell ul {{ margin:6px 0 0;padding-left:18px }}
.lower {{ display:grid;grid-template-columns:1fr 1fr;gap:28px;margin-top:38px }} .panel {{ border-top:1px solid var(--ink);padding-top:14px }} .panel h3 {{ font:500 23px Georgia,serif;margin:0 0 13px }} .evidence-list {{ display:grid;gap:1px;background:var(--rule);border:1px solid var(--rule) }} .evidence-row {{ display:grid;grid-template-columns:38px 1fr auto;gap:10px;align-items:start;text-align:left;border:0;background:var(--panel);padding:12px 13px;cursor:pointer;color:var(--ink) }} .evidence-row:hover,.evidence-row.selected {{ background:#edf3f0 }} .evidence-no {{ color:var(--accent);font:500 18px Georgia,serif }} .evidence-title {{ font-weight:600;font-size:13px;line-height:1.35 }} .evidence-meta {{ color:var(--muted);font-size:11px;margin-top:3px }} .evidence-theme {{ color:var(--teal);font-size:11px }}
.detail {{ background:var(--panel);border:1px solid var(--rule);padding:18px;min-height:220px }} .detail h4 {{ font:500 22px Georgia,serif;margin:0 0 8px }} .detail p {{ color:var(--muted);font-size:14px;margin:8px 0 16px }} .provenance {{ border-top:1px solid var(--rule);padding-top:11px;color:var(--muted);font-size:11px;word-break:break-word }}
.bounds {{ margin-top:38px; border-top:1px solid var(--ink);padding-top:15px;display:flex;gap:25px;align-items:flex-start }} .bounds strong {{ font:500 24px Georgia,serif;min-width:170px }} .bounds ul {{ color:var(--muted);margin:0;padding-left:20px }} footer {{ margin-top:46px;border-top:1px solid var(--ink);padding-top:12px;color:var(--muted);font-size:11px;display:flex;justify-content:space-between }}
body.dark {{ --paper:#1d211f;--ink:#f0f0e9;--muted:#a3aaa4;--rule:#424945;--panel:#252a27;--accent:#e27c5d;--accent-soft:#4a3029;--teal:#8cc0b6;--shadow:0 14px 40px rgba(0,0,0,.18) }} body.dark .chip {{ background:#243934 }}
@media(max-width:900px) {{ .shell{{padding:18px 18px 44px}}.masthead{{grid-template-columns:1fr;gap:20px;padding-top:32px}}.workspace{{grid-template-columns:1fr;gap:22px}}.rail{{position:static}}.proposal-nav{{grid-template-columns:repeat(3,1fr)}}.proposal-nav button{{border-left:0;border-bottom:2px solid transparent}}.proposal-nav button.active{{border-bottom-color:var(--accent)}}.lower,.twocol{{grid-template-columns:1fr}}.stats{{grid-template-columns:repeat(3,1fr)}} }}
@media(max-width:560px) {{ .stats{{grid-template-columns:1fr}}.stat{{padding:13px 15px;display:flex;align-items:baseline;gap:12px}}.stat b{{font-size:31px}}.proposal{{padding:22px 20px}}.proposal-head{{display:block}}.tag{{display:inline-block;margin-top:12px}}.blueprint-grid{{grid-template-columns:1fr}}.bounds{{display:block}}.bounds strong{{display:block;margin-bottom:12px}}footer{{display:block}}footer span{{display:block;margin-top:5px}} }}
</style></head><body>
<div class="shell"><header class="topbar"><div class="brand"><span class="brand-mark">IA</span><span>IDEA ATLAS / 研究工作台</span></div><div class="topmeta"><span>OFFLINE RULES · V1</span><button class="toggle" id="theme">切换深色</button></div></header>
<section class="masthead"><div><div class="kicker">Research opportunity map</div><h1>从论文线索，到<br><em>可验证的方向。</em></h1><p class="lede">围绕“二维医学图像扩散生成”的词法召回结果，整理出可以继续核查、对照和实验化的研究假设。</p></div><div class="snapshot"><strong>当前证据边界</strong>词法检索与短摘要摘录只提供背景线索。所有方向仍是 HYPOTHESIS，尚未完成语义相关性、新颖性或科学有效性判断。<br><br><span id="snapshot"></span></div></section>
<section class="stats"><div class="stat"><b id="evidence-count">—</b><span>证据卡 / EVIDENCE CARDS</span></div><div class="stat"><b id="proposal-count">—</b><span>研究假设 / HYPOTHESES</span></div><div class="stat"><b id="missing-count">—</b><span>缺失摘要 / MISSING ABSTRACTS</span></div></section>
<div class="workspace"><aside class="rail"><div class="rail-title">提案目录 / PROPOSALS</div><nav class="proposal-nav" id="proposal-nav"></nav><div class="rail-note"><b>阅读顺序</b>先比较研究问题与机制，再展开实验蓝图；证据卡可追溯到快照中的原始记录。</div></aside><main class="content"><div class="section-label"><h2>方向详读</h2><span id="proposal-index"></span></div><section class="proposal" id="proposal"></section><div class="lower"><section class="panel"><h3>证据账本</h3><div class="evidence-list" id="evidence-list"></div></section><section class="panel"><h3>证据详情</h3><div class="detail" id="detail"><div class="label">选择一张证据卡</div><p>提案中的每个引用都可以回到原始记录定位。这里不会展示完整摘要。</p></div></section></div><section class="bounds"><strong>证据边界</strong><ul id="limitations"></ul></section></main></div><footer><span>IDEA ATLAS · evidence-bound proposal viewer</span><span id="footer-source"></span></footer></div>
<script>const DATA = {embedded};
const $=s=>document.querySelector(s), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':'&quot;',"'":"&#39;"}}[c]));
const proposals=DATA.proposals||[], cards=DATA.evidence_cards||[]; let active=0;
function renderNav(){{$('#proposal-nav').innerHTML=proposals.map((p,i)=>`<button class="${{i===active?'active':''}}" data-i="${{i}}">0${{i+1}} · ${{esc(p.theme)}}<small>${{esc(p.title)}}</small></button>`).join('');document.querySelectorAll('[data-i]').forEach(b=>b.onclick=()=>{{active=+b.dataset.i;render()}})}}
function list(v){{return (v||[]).map(x=>`<li>${{esc(x)}}</li>`).join('')}}
function renderProposal(){{const p=proposals[active]; if(!p) return; const bp=p.experiment_blueprint||{{}}; $('#proposal-index').textContent=`${{String(active+1).padStart(2,'0')}} / ${{String(proposals.length).padStart(2,'0')}}`;$('#proposal').innerHTML=`<div class="proposal-head"><div><div class="kicker">${{esc(p.theme)}} · evidence-bound hypothesis</div><h3>${{esc(p.title)}}</h3></div><span class="tag">HYPOTHESIS</span></div><div class="label">研究问题</div><div class="question">${{esc(p.research_question)}}</div><div class="twocol"><div><div class="label">机制假设</div><div class="mechanism">${{esc(p.mechanism)}}</div></div><div><div class="label">背景证据</div><div class="evidence-chips">${{(p.evidence_ids||[]).map(id=>`<span class="chip">${{esc(id)}}</span>`).join('')}}</div></div></div><div class="blueprint"><h4>实验蓝图 / Experiment blueprint</h4><div class="blueprint-grid"><div class="blueprint-cell"><div class="label">基线</div>${{esc(bp.baseline)}}</div><div class="blueprint-cell"><div class="label">主指标</div>${{esc(bp.primary_measurement)}}</div><div class="blueprint-cell"><div class="label">消融</div><ul>${{list(bp.ablations)}}</ul></div><div class="blueprint-cell"><div class="label">失败条件</div><ul>${{list(bp.failure_criteria)}}</ul></div></div></div>`;}}
function renderEvidence(){{const p=proposals[active]||{{}};const ids=new Set(p.evidence_ids||[]);const shown=cards.filter(c=>ids.has(c.evidence_id));$('#evidence-list').innerHTML=shown.length?shown.map((c,i)=>`<button class="evidence-row ${{i===0?'selected':''}}" data-e="${{esc(c.evidence_id)}}"><span class="evidence-no">${{String(i+1).padStart(2,'0')}}</span><span><span class="evidence-title">${{esc(c.title)}}</span><span class="evidence-meta">${{esc(c.conference)}} · ${{esc(c.year)}} · ${{esc(c.paper_id)}}</span></span><span class="evidence-theme">${{esc((c.lexical_themes||[]).join(' / '))}}</span></button>`).join(''):'<div class="evidence-row">暂无可用证据卡</div>';document.querySelectorAll('[data-e]').forEach((b,i)=>b.onclick=()=>{{document.querySelectorAll('[data-e]').forEach(x=>x.classList.remove('selected'));b.classList.add('selected');showDetail(shown.find(c=>c.evidence_id===b.dataset.e))}});showDetail(shown[0])}}
function showDetail(c){{if(!c){{$('#detail').innerHTML='<div class="label">暂无详情</div>';return}}const p=c.provenance||{{}};$('#detail').innerHTML=`<div class="label">${{esc(c.evidence_id)}} · ${{esc(c.abstract_status)}}</div><h4>${{esc(c.title)}}</h4><p>${{esc(c.abstract_excerpt)||'摘要缺失；当前只核对标题和来源定位。'}}</p><div class="provenance">${{esc(c.conference)}} / ${{esc(c.year)}} · record_key ${{esc(c.record_key)}}<br>来源：${{esc(p.shard_path)}} · 非空记录 ${{esc(p.record_number)}}<br>record SHA256：${{esc(p.record_sha256)}}</div>`}}
function render(){{renderNav();renderProposal();renderEvidence()}} $('#evidence-count').textContent=cards.length;$('#proposal-count').textContent=proposals.length;$('#missing-count').textContent=DATA.source_search?.coverage?.missing_abstract_in_union??'—';$('#snapshot').textContent=`快照 ${{DATA.source_search?.snapshot_id||'—'}} · 索引 ${{DATA.source_search?.index_id||'—'}}`;$('#footer-source').textContent=`${{DATA.source_search?.returned_records??cards.length}} 条候选 · ${{DATA.generation_method||'offline_rules_v1'}}`;$('#limitations').innerHTML=(DATA.limitations||[]).map(x=>`<li>${{esc(x)}}</li>`).join('');render();$('#theme').onclick=()=>{{document.body.classList.toggle('dark');$('#theme').textContent=document.body.classList.contains('dark')?'切换浅色':'切换深色'}};</script></body></html>'''


def write_proposal_report(repo_root: Path, result: dict) -> dict:
    payload = export_payload(result)
    reports = safe_child(Path(repo_root), "indexes/reports")
    reports.mkdir(parents=True, exist_ok=True)
    staging = Path(mkdtemp(prefix=".proposal-writing-", dir=reports))
    run_id = "proposal_" + uuid4().hex
    destination = safe_child(reports, run_id)
    try:
        _write(staging / "proposals.json", payload)
        with (staging / "report.md").open("x", encoding="utf-8") as f:
            f.write(markdown(payload)); f.flush(); os.fsync(f.fileno())
        with (staging / "dashboard.html").open("x", encoding="utf-8") as f:
            f.write(html_dashboard(payload)); f.flush(); os.fsync(f.fileno())
        with ZipFile(staging / "return_bundle.zip", "x", ZIP_DEFLATED) as z:
            for name in ("proposals.json", "report.md"):
                z.write(staging / name, name)
        with (staging / "return_bundle.zip").open("rb") as f:
            os.fsync(f.fileno())
        _fsync_directory(staging)
        safe_child(Path(repo_root), "indexes/reports")
        os.rename(staging, destination)
        _fsync_directory(reports)
        return {"run_id": run_id, "json_path": str(destination / "proposals.json"), "report_path": str(destination / "report.md"), "dashboard_path": str(destination / "dashboard.html"), "bundle_path": str(destination / "return_bundle.zip")}
    finally:
        if staging.exists():
            shutil.rmtree(staging)
