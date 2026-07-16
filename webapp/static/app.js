const $ = (s, r = document) => r.querySelector(s);
// 返回一个 fragment，支持模板含多个顶层节点（否则只有第一个会被 append）
const el = (h) => {
  const t = document.createElement("template");
  t.innerHTML = h.trim();
  return t.content.cloneNode(true);
};
const esc = (s) => String(s ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

async function api(path, opts) {
  const r = await fetch(path, opts);
  return r.json();
}
function post(path, body) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

const META = {
  overview:   ["概览", "项目真实状态与能力入口"],
  collect:    ["真实采集", "对 Hacker News / arXiv 官方 API 实时合规采集"],
  pipeline:   ["离线流水线", "解析 → 去重 → 校验 → AI 清洗（样例数据）"],
  signature:  ["签名复现", "x-zse-96 端到端生成（离线、确定性）"],
  clean:      ["AI 清洗", "富文本 → 干净 Markdown + 情感标签"],
  dedup:      ["布隆去重", "海量 URL 去重的内存优势"],
  compliance: ["合规内核", "令牌桶限速 + robots 真实判定"],
  recon:      ["反爬实测", "对知乎发真实请求，记录服务端反应"],
};

const VIEWS = {};

/* ------------------------- Overview ------------------------- */
VIEWS.overview = async (c) => {
  c.innerHTML = `<div class="loading">加载中…</div>`;
  const o = await api("/api/overview");
  $("#provider-tag").textContent = "provider: " + o.ai_provider;
  c.innerHTML = "";
  c.appendChild(el(`
    <div class="metric-row">
      <div class="card"><div class="stat"><span class="num">2</span><span class="lbl">真实数据源(官方API)</span></div></div>
      <div class="card"><div class="stat"><span class="num">${o.ai_provider}</span><span class="lbl">AI provider</span></div></div>
      <div class="card"><div class="stat"><span class="num">${o.storage_backend}</span><span class="lbl">存储后端</span></div></div>
      <div class="card"><div class="stat"><span class="num">${o.rps}</span><span class="lbl">请求/秒 限速</span></div></div>
    </div>`));
  c.appendChild(el(`
    <div class="card">
      <h2>这个界面演示的是真实能力，不是假数据</h2>
      <p class="hint">每个面板都调用项目的真实模块。以下是各能力的诚实说明。</p>
      <table>
        <tr><th>能力</th><th>状态</th><th>说明</th></tr>
        <tr><td>真实采集(HN/arXiv 官方API)</td><td><span class="badge ok">线上可跑</span></td><td>对官方 API 实时合规采集，现场演示</td></tr>
        <tr><td>AI 清洗</td><td><span class="badge ok">可运行</span></td><td>provider=${esc(o.ai_provider)}，缺模型自动降级规则</td></tr>
        <tr><td>布隆去重</td><td><span class="badge ok">可运行</span></td><td>真实位数组，误判率可算</td></tr>
        <tr><td>合规内核</td><td><span class="badge ok">可运行</span></td><td>令牌桶限速 + robots 真实判定</td></tr>
        <tr><td>签名复现(知乎)</td><td><span class="badge warn">能力演示</span></td><td>x-zse-96 逆向复现，方法论展示</td></tr>
        <tr><td>实际爬知乎生产</td><td><span class="badge no">按设计不抓</span></td><td>robots 禁止 + 无授权，合规不抓</td></tr>
      </table>
    </div>`));
  c.appendChild(el(`
    <div class="verdict">这是一个**真实可跑的合规采集系统**：对 Hacker News / arXiv 官方 API 实时采集（「真实采集」面板现场演示）；
    知乎签名逆向作为**能力演示**保留（「签名复现」面板）；对知乎生产环境按设计不抓（robots 禁止且无授权，见「反爬实测」）。</div>`));
};

/* ------------------------- Collect (live) ------------------------- */
VIEWS.collect = (c) => {
  c.innerHTML = "";
  c.appendChild(el(`
    <div class="card">
      <h2>实时合规采集（多源）</h2>
      <p class="hint">经合规客户端(限速+退避)采集 → 布隆去重 → AI 清洗。
      linux.do 用真实浏览器过 Cloudflare 盾(首次启动约 5-10s)；arXiv 遵守 3s/请求条款。</p>
      <div class="row">
        <div class="field" style="flex:1"><label>数据源</label>
          <select id="co-src">
            <option value="linuxdo">linux.do（Discourse，真实浏览器过 CF 盾）</option>
            <option value="hackernews">Hacker News（官方 API）</option>
            <option value="arxiv">arXiv（官方 API）</option>
          </select></div>
        <div class="field" style="flex:1"><label>查询（linux.do: latest/分类slug；HN: top/new；arXiv: cs.AI）</label>
          <input type="text" id="co-q" value="latest"></div>
        <div class="field" style="flex:0 0 120px"><label>条数(≤10)</label>
          <input type="text" id="co-n" value="5"></div>
      </div>
      <button class="btn" id="co-run">开始采集</button>
    </div>
    <div id="co-out"></div>`));
  const run = async () => {
    const out = $("#co-out");
    out.innerHTML = `<div class="loading">向官方 API 发起真实请求中…（arXiv 限速会稍慢）</div>`;
    const r = await post("/api/collect", {
      source: $("#co-src").value, query: $("#co-q").value, limit: parseInt($("#co-n").value),
    });
    if (r.error) { out.innerHTML = `<div class="verdict">${esc(r.error)}</div>`; return; }
    const rows = r.records.map(x => `
      <tr><td>${esc(x.source)}</td>
      <td><a href="${esc(x.url)}" target="_blank" style="color:var(--accent);text-decoration:none">${esc((x.title||"").slice(0,60))}</a></td>
      <td>${esc((x.author||"").slice(0,20))}</td><td>${x.score}</td><td>${x.comment_count}</td>
      <td><span class="badge ${x.sentiment==='positive'?'ok':x.sentiment==='negative'?'no':''}">${esc(x.sentiment)}</span></td></tr>`).join("");
    out.innerHTML = "";
    out.appendChild(el(`
      <div class="metric-row">
        <div class="card"><div class="stat"><span class="num">${r.fetched}</span><span class="lbl">采集</span></div></div>
        <div class="card"><div class="stat"><span class="num">${r.kept}</span><span class="lbl">去重清洗后</span></div></div>
        <div class="card"><div class="stat"><span class="num">${esc(r.source)}</span><span class="lbl">数据源</span></div></div>
        <div class="card"><div class="stat"><span class="num">${esc(r.provider)}</span><span class="lbl">清洗 provider</span></div></div>
      </div>`));
    out.appendChild(el(`<div class="card"><h2>实时采集结果（点标题可跳原文）</h2>
      <table><tr><th>源</th><th>标题</th><th>作者</th><th>分</th><th>评论</th><th>情感</th></tr>${rows}</table>
      <p class="muted" style="margin-top:10px">以上为**刚刚从官方 API 拉取**的真实线上数据，合规采集、限速受控。</p></div>`));
  };
  $("#co-run").onclick = run;
};

/* ------------------------- Pipeline ------------------------- */
VIEWS.pipeline = (c) => {
  c.innerHTML = "";
  c.appendChild(el(`
    <div class="card">
      <h2>端到端流水线（知乎同构样例数据）</h2>
      <p class="hint">走项目真实模块：解析 → 布隆去重 → 字段校验 → AI 清洗。演示完整数据流，
      不依赖抓生产环境。拿到授权测试环境后，把数据源换成真实端点即可。</p>
      <button class="btn" id="pl-run">运行流水线</button>
    </div>
    <div id="pl-out"></div>`));
  const run = async () => {
    const out = $("#pl-out"); out.innerHTML = `<div class="loading">运行中…</div>`;
    const r = await post("/api/pipeline", { limit: 5 });
    const s = r.stages;
    const flow = [
      ["采集", s.fetched], ["解析", s.parsed], ["去重后", s.after_dedup],
      ["校验合格", s.valid], ["AI 清洗", s.cleaned],
    ].map(([k, v]) => `<div class="card"><div class="stat"><span class="num">${v}</span><span class="lbl">${k}</span></div></div>`).join("");
    const rows = r.records.map(x => `
      <tr><td>${esc(x.answer_id)}</td><td>${esc(x.question_title)}</td>
      <td>${esc(x.author)}</td><td>${x.voteup_count}</td>
      <td><span class="badge ${x.sentiment==='positive'?'ok':x.sentiment==='negative'?'no':'warn'}">${esc(x.sentiment)}</span></td></tr>`).join("");
    out.innerHTML = "";
    out.appendChild(el(`<div class="metric-row">${flow}</div>`));
    out.appendChild(el(`<div class="card"><h2>入库记录（provider: ${esc(r.provider)}）</h2>
      <table><tr><th>id</th><th>标题</th><th>作者</th><th>赞</th><th>情感</th></tr>${rows}</table>
      <p class="muted" style="margin-top:10px">注：采集 ${s.fetched} → 去重拦掉重复 → 校验剔除不合格 → 清洗打标入库。全程真实模块。</p>
    </div>`));
  };
  $("#pl-run").onclick = run; run();
};

/* ------------------------- Signature ------------------------- */
VIEWS.signature = (c) => {
  c.innerHTML = "";
  c.appendChild(el(`
    <div class="card">
      <h2>输入</h2>
      <p class="hint">修改请求 path 或设备标识，观察签名如何随内容变化（输入敏感 + 确定性）。</p>
      <div class="field"><label>请求 path + query</label>
        <input type="text" id="sig-path" value="/api/v4/search_v3?t=general&q=python&limit=5"></div>
      <div class="field"><label>d_c0（设备标识 cookie，示例值）</label>
        <input type="text" id="sig-dc0" value="AABxxxxxxxxxxxxxxxxxxxxxxxxxxxx="></div>
      <button class="btn" id="sig-run">生成签名</button>
    </div>
    <div id="sig-out"></div>`));
  const run = async () => {
    const out = $("#sig-out"); out.innerHTML = `<div class="loading">计算中…</div>`;
    const r = await post("/api/signature", { path: $("#sig-path").value, d_c0: $("#sig-dc0").value });
    const steps = r.steps.map(s =>
      `<div class="step ${s.n === 4 ? "final" : ""}"><div class="k">步骤 ${s.n} · ${esc(s.title)}</div><div class="v">${esc(s.value)}</div></div>`).join("");
    const hdr = Object.entries(r.headers).map(([k, v]) =>
      `<div class="k">${esc(k)}</div><div class="v">${esc(v)}</div>`).join("");
    out.innerHTML = "";
    out.appendChild(el(`<div class="card"><h2>生成过程</h2>${steps}
      <div class="muted">确定性校验：${r.deterministic ? '<span class="badge ok">通过</span> 相同输入稳定复现' : '<span class="badge no">异常</span>'}</div></div>`));
    out.appendChild(el(`<div class="card"><h2>最终签名请求头</h2><div class="kv">${hdr}</div></div>`));
  };
  $("#sig-run").onclick = run; run();
};

/* --------------------------- Clean --------------------------- */
VIEWS.clean = (c) => {
  const sample = `<div class="RichText">
<p>Python 很适合做数据采集，requests 和 scrapy 都好用，推荐入门。</p>
<p>加我微信 vx: abc123 领取全套教程福利！</p>
<script>tracker();</script>
<p>关注我的公众号获取更多推广内容。</p>
<p>总体来说体验很棒，值得学习。</p>
</div>`;
  c.innerHTML = "";
  c.appendChild(el(`
    <div class="card">
      <h2>原始富文本（含广告 / script / 灌水）</h2>
      <p class="hint">粘贴任意知乎风格 HTML，点清洗看结构化结果。provider 缺模型时自动降级规则模式。</p>
      <div class="field"><textarea id="cl-in">${esc(sample)}</textarea></div>
      <button class="btn" id="cl-run">清洗</button>
    </div>
    <div id="cl-out"></div>`));
  const run = async () => {
    const out = $("#cl-out"); out.innerHTML = `<div class="loading">清洗中…</div>`;
    const r = await post("/api/clean", { html: $("#cl-in").value });
    out.innerHTML = "";
    out.appendChild(el(`
      <div class="split">
        <div class="card"><h2>清洗后 Markdown</h2><pre class="code">${esc(r.markdown)}</pre></div>
        <div class="card"><h2>结构化标签</h2>
          <div class="kv">
            <div class="k">provider</div><div class="v">${esc(r.provider)}</div>
            <div class="k">情感</div><div class="v"><span class="badge ${r.sentiment==='positive'?'ok':r.sentiment==='negative'?'no':'warn'}">${esc(r.sentiment)}</span></div>
            <div class="k">耗时</div><div class="v">${r.elapsed_ms} ms</div>
          </div>
          <p class="muted" style="margin-top:12px">广告/引流/script 已剔除，正文段落保留。</p>
        </div>
      </div>`));
  };
  $("#cl-run").onclick = run; run();
};

/* --------------------------- Dedup --------------------------- */
VIEWS.dedup = (c) => {
  c.innerHTML = "";
  c.appendChild(el(`
    <div class="card">
      <h2>布隆过滤器参数</h2>
      <p class="hint">按容量与误判率算出位数、哈希个数与内存，对比用 set 存 URL 的开销。</p>
      <div class="row">
        <div class="field" style="flex:1"><label>容量（URL 数）</label><input type="text" id="bf-cap" value="100000000"></div>
        <div class="field" style="flex:1"><label>误判率</label><input type="text" id="bf-err" value="0.01"></div>
      </div>
      <div class="field"><label>试探 URL（每行一个，重复行会被判为已存在）</label>
        <textarea id="bf-urls" style="min-height:90px">https://www.zhihu.com/question/1
https://www.zhihu.com/question/2
https://www.zhihu.com/question/1</textarea></div>
      <button class="btn" id="bf-run">计算</button>
    </div>
    <div id="bf-out"></div>`));
  const run = async () => {
    const out = $("#bf-out"); out.innerHTML = `<div class="loading">计算中…</div>`;
    const urls = $("#bf-urls").value.split("\n").map(s => s.trim()).filter(Boolean);
    const r = await post("/api/dedup", {
      capacity: parseInt($("#bf-cap").value), error_rate: parseFloat($("#bf-err").value), urls,
    });
    const rows = r.results.map(x =>
      `<tr><td>${esc(x.url)}</td><td>${x.duplicate ? '<span class="badge warn">已存在</span>' : '<span class="badge ok">新</span>'}</td></tr>`).join("");
    out.innerHTML = "";
    out.appendChild(el(`
      <div class="metric-row">
        <div class="card"><div class="stat"><span class="num">${r.bloom_mb}</span><span class="lbl">布隆内存 MB</span></div></div>
        <div class="card"><div class="stat"><span class="num">${r.set_mb}</span><span class="lbl">set 存储 MB</span></div></div>
        <div class="card"><div class="stat"><span class="num">${r.saving_x}×</span><span class="lbl">内存节省</span></div></div>
        <div class="card"><div class="stat"><span class="num">${r.hashes}</span><span class="lbl">哈希函数个数 k</span></div></div>
      </div>`));
    out.appendChild(el(`<div class="card"><h2>去重判定</h2>
      <p class="hint">位数 m = ${r.bits.toLocaleString()}，容量 ${r.capacity.toLocaleString()}，误判率 ${r.error_rate}</p>
      <table><tr><th>URL</th><th>结果</th></tr>${rows}</table></div>`));
  };
  $("#bf-run").onclick = run; run();
};

/* ------------------------ Compliance ------------------------ */
VIEWS.compliance = (c) => {
  c.innerHTML = "";
  c.appendChild(el(`
    <div class="card">
      <h2>令牌桶限速（真实阻塞计时）</h2>
      <p class="hint">连发 N 个请求，观察限速器如何把速率平滑到设定值（会真实等待）。</p>
      <div class="row">
        <div class="field" style="flex:1"><label>请求/秒</label><input type="text" id="tb-rps" value="2"></div>
        <div class="field" style="flex:1"><label>请求数（≤10）</label><input type="text" id="tb-n" value="5"></div>
      </div>
      <button class="btn" id="tb-run">运行</button>
    </div>
    <div id="tb-out"></div>
    <div class="card">
      <h2>robots.txt 真实判定</h2>
      <p class="hint">实时读取知乎 robots.txt，判定各路径是否允许抓取。合规内核据此拦截。</p>
      <button class="btn ghost" id="rb-run">查询知乎 robots</button>
      <div id="rb-out" style="margin-top:12px"></div>
    </div>`));
  $("#tb-run").onclick = async () => {
    const out = $("#tb-out"); out.innerHTML = `<div class="loading">限速运行中（会真实等待）…</div>`;
    const r = await post("/api/compliance", { rps: parseFloat($("#tb-rps").value), n: parseInt($("#tb-n").value) });
    const rows = r.timeline.map(t =>
      `<tr><td>#${t.req}</td><td>${t.waited_s}s</td><td>${t.at_s}s</td></tr>`).join("");
    out.innerHTML = "";
    out.appendChild(el(`<div class="card"><h2>请求时间线（速率 ${r.rps}/s）</h2>
      <table><tr><th>请求</th><th>本次等待</th><th>累计时刻</th></tr>${rows}</table></div>`));
  };
  $("#rb-run").onclick = async () => {
    const out = $("#rb-out"); out.innerHTML = `<div class="loading">查询中…</div>`;
    const r = await api("/api/robots");
    out.innerHTML = `<table><tr><th>路径</th><th>是否允许抓取</th></tr>` +
      r.results.map(x => `<tr><td>${esc(x.path)}</td><td>${x.allowed ? '<span class="badge ok">允许</span>' : '<span class="badge no">禁止</span>'}</td></tr>`).join("") +
      `</table>`;
  };
};

/* -------------------------- Recon -------------------------- */
VIEWS.recon = (c) => {
  c.innerHTML = "";
  c.appendChild(el(`
    <div class="card">
      <h2>对知乎发真实请求，记录服务端反应</h2>
      <p class="hint">诚实地展示：无签名 / 带复现签名 / 首页 的真实返回。结果缓存 5 分钟以克制请求（合规）。</p>
      <button class="btn" id="rc-run">运行实测</button>
      <button class="btn ghost" id="rc-force">强制刷新</button>
    </div>
    <div id="rc-out"></div>`));
  const render = (r) => {
    const out = $("#rc-out");
    const rb = r.robots || {};
    const robRows = Object.entries(rb.paths || {}).map(([p, a]) =>
      `<tr><td>${esc(p)}</td><td>${a ? '<span class="badge ok">允许</span>' : '<span class="badge no">禁止</span>'}</td></tr>`).join("");
    const probe = (title, o) => `<div class="card"><h2>${title}</h2><div class="kv">
      <div class="k">HTTP</div><div class="v">${o.status ?? esc(o.error ?? "—")}</div>
      <div class="k">content-type</div><div class="v">${esc(o.content_type ?? "—")}</div>
      <div class="k">bytes</div><div class="v">${o.bytes ?? "—"}</div>
      <div class="k">body 预览</div><div class="v">${esc((o.body_preview ?? "").slice(0,180) || "—")}</div>
      </div></div>`;
    out.innerHTML = "";
    out.appendChild(el(`<div class="verdict">${esc(r.verdict || "")}${r.cached ? " （缓存结果）" : ""}</div>`));
    out.appendChild(el(`<div class="card"><h2>robots.txt 判定</h2>
      <table><tr><th>路径</th><th>结果</th></tr>${robRows}</table></div>`));
    out.appendChild(el(`<div class="split">${probe("无签名直连 API", r.unsigned_api || {})}${probe("带复现签名 API", r.signed_api || {})}</div>`));
    out.appendChild(el(probe("首页连通基线", r.homepage || {})));
  };
  const go = async (force) => {
    $("#rc-out").innerHTML = `<div class="loading">向知乎发起真实请求中…（首次约数秒）</div>`;
    render(await api("/api/recon" + (force ? "?force=1" : "")));
  };
  $("#rc-run").onclick = () => go(false);
  $("#rc-force").onclick = () => go(true);
};

/* --------------------------- Router --------------------------- */
function switchView(name) {
  document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.view === name));
  $("#view-title").textContent = META[name][0];
  $("#view-desc").textContent = META[name][1];
  VIEWS[name]($("#content"));
}
document.querySelectorAll(".nav-item").forEach(b => b.onclick = () => switchView(b.dataset.view));
switchView("overview");

