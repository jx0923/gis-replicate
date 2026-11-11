async function api(path, opts) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}

const TYPE_LABEL = { raster: "影像", vector: "矢量", tiles: "切片" };

function serviceCard(s) {
  const el = document.createElement("div");
  el.className = "service";
  const eps = Object.entries(s.endpoints || {})
    .map(([k, v]) => `<a href="${v}" target="_blank">${k}</a>`).join(" ");
  el.innerHTML = `
    <div class="svc-head">
      <strong>${esc(s.name)}</strong>
      <span class="badge ${s.type}">${TYPE_LABEL[s.type] || s.type}</span>
      <span class="badge ${s.status === "active" ? "ok" : "err"}">${s.status === "active" ? "已发布" : "异常"}</span>
      <span class="muted">${esc(s.created_at || "")}</span>
      <button class="del" data-slug="${esc(s.slug)}">下线</button>
    </div>
    ${s.error ? `<p class="err-text">${esc(s.error)}</p>` : ""}
    ${s.type !== "tiles"
      ? `<img class="preview" src="${s.endpoints.wms_map}" alt="预览图" loading="lazy">`
      : `<img class="preview" src="${s.endpoints.wmts_tile}" alt="瓦片预览" loading="lazy">`}
    <p class="endpoints">${eps}</p>`;
  el.querySelector(".del").onclick = async (e) => {
    if (!confirm("下线服务「" + s.name + "」？数据与缓存会一并删除。")) return;
    e.target.disabled = true;
    try { await api("/api/services/" + encodeURIComponent(s.slug), { method: "DELETE" }); load(); }
    catch (err) { alert("下线失败：" + err.message); e.target.disabled = false; }
  };
  return el;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function load() {
  const list = document.getElementById("service-list");
  try {
    const services = await api("/api/services");
    document.getElementById("count").textContent = "（" + services.length + " 个）";
    list.innerHTML = "";
    if (!services.length) {
      list.innerHTML = '<p class="muted">还没有服务，先发布一个。</p>';
    } else {
      services.forEach((s) => list.appendChild(serviceCard(s)));
    }
    const sel = document.getElementById("source-select");
    const cur = sel.value;
    sel.innerHTML = services
      .filter((s) => s.type !== "tiles" && s.status === "active")
      .map((s) => `<option value="${esc(s.slug)}">${esc(s.name)}（${TYPE_LABEL[s.type]}）</option>`)
      .join("");
    if (cur) sel.value = cur;
  } catch (err) {
    list.innerHTML = '<p class="err-text">加载失败：' + esc(err.message) + "</p>";
  }
}

document.getElementById("type-select").addEventListener("change", (e) => {
  const t = e.target.value;
  document.getElementById("file-label").classList.toggle("hidden", t === "tiles");
  document.getElementById("source-label").classList.toggle("hidden", t !== "tiles");
  document.getElementById("style-row").classList.toggle("hidden", t !== "vector");
  document.getElementById("file-input").required = t !== "tiles";
});
document.getElementById("type-select").dispatchEvent(new Event("change"));

document.getElementById("publish-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("form-msg");
  const btn = document.getElementById("submit-btn");
  btn.disabled = true;
  msg.textContent = "发布中…";
  msg.className = "msg";
  try {
    const data = await api("/api/services", {
      method: "POST",
      body: new FormData(e.target),
    });
    msg.textContent = "发布成功：" + data.name;
    msg.className = "msg ok-text";
    e.target.reset();
    document.getElementById("type-select").dispatchEvent(new Event("change"));
    load();
  } catch (err) {
    msg.textContent = "发布失败：" + err.message;
    msg.className = "msg err-text";
  } finally {
    btn.disabled = false;
  }
});

load();
