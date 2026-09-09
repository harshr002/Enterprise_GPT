/* ============================================================
   Enterprise GPT — frontend logic (vanilla JS, no build step)
   ============================================================ */
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const state = { mode: "hybrid", department: "all", lastSources: {}, user: null };

const TOKEN_KEY = "eg_token";
function getToken() { try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return null; } }
function setToken(t) { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch (e) {} }

/* ---------- helpers ---------- */
async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers["Authorization"] = "Bearer " + token;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    // Session expired or missing — send the user back to the login screen.
    setToken(null);
    showAuth();
    let msg = "Please sign in.";
    try { msg = (await res.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try { const j = await res.json(); msg = j.detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return res.json();
}

function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* Minimal, safe markdown -> HTML (bold, italic, code, lists, [n] citations) */
function renderMarkdown(md) {
  const lines = escapeHtml(md).split("\n");
  let html = "", inUl = false, inOl = false;
  const closeLists = () => {
    if (inUl) { html += "</ul>"; inUl = false; }
    if (inOl) { html += "</ol>"; inOl = false; }
  };
  for (let raw of lines) {
    let line = raw.trim();
    if (!line) { closeLists(); continue; }
    const ul = line.match(/^[-*]\s+(.*)/);
    const ol = line.match(/^\d+\.\s+(.*)/);
    if (ul) {
      if (!inUl) { closeLists(); html += "<ul>"; inUl = true; }
      html += `<li>${inline(ul[1])}</li>`;
    } else if (ol) {
      if (!inOl) { closeLists(); html += "<ol>"; inOl = true; }
      html += `<li>${inline(ol[1])}</li>`;
    } else {
      closeLists();
      html += `<p>${inline(line)}</p>`;
    }
  }
  closeLists();
  return html;
}
function inline(s) {
  return s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/\[(\d+)\]/g, '<a class="cite" data-cite="$1">$1</a>');
}

/* ---------- view switching ---------- */
$$(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    $$(".nav-item").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const view = btn.dataset.view;
    $$(".view").forEach(v => v.classList.add("hidden"));
    $(`#view-${view}`).classList.remove("hidden");
    if (view === "knowledge") loadDocs();
    if (view === "analytics") loadAnalytics();
  });
});

/* ---------- mode & department ---------- */
const MODE_HINTS = {
  hybrid: "Uses your documents first, then falls back to general knowledge — with clear labels.",
  docs_only: "Answers strictly from your indexed documents, with citations. No outside knowledge.",
  general: "Answers anything from general knowledge, like a web search. Ignores your documents.",
};
$$("#modeToggle button").forEach(b => {
  b.addEventListener("click", () => {
    $$("#modeToggle button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    state.mode = b.dataset.mode;
    $("#modeHint").textContent = MODE_HINTS[state.mode];
  });
});
$("#department").addEventListener("change", e => { state.department = e.target.value; });

/* ---------- chat ---------- */
const chat = $("#chat");
const input = $("#queryInput");

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
});
input.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
$("#sendBtn").addEventListener("click", send);
$("#clearChat").addEventListener("click", () => location.reload());
$$("#suggestions button").forEach(b =>
  b.addEventListener("click", () => { input.value = b.textContent; send(); })
);

function addUserMsg(text) {
  $("#chatEmpty")?.remove();
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML = `<div class="avatar">You</div>
    <div class="body"><div class="who">You</div>
    <div class="bubble"><p>${escapeHtml(text)}</p></div></div>`;
  chat.appendChild(el);
  scroll();
}

function addTyping() {
  const el = document.createElement("div");
  el.className = "msg bot";
  el.id = "typing";
  el.innerHTML = `<div class="avatar">EG</div>
    <div class="body"><div class="who">Enterprise GPT</div>
    <div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div></div>`;
  chat.appendChild(el);
  scroll();
}

function sourceTypePill(type) {
  if (type === "documents")        return `<span class="pill docs">📎 From your documents</span>`;
  if (type === "mixed")            return `<span class="pill docs">📎 Documents + general</span>`;
  if (type === "general_knowledge")return `<span class="pill general">🌐 General knowledge</span>`;
  if (type === "insufficient" || type === "none")
                                   return `<span class="pill none">⚠ No strong match</span>`;
  return "";
}

function renderAnswer(data) {
  $("#typing")?.remove();
  state.lastSources[data.answer_id] = data.sources || [];

  let sourcesHtml = "";
  if (data.sources && data.sources.length) {
    sourcesHtml = `<div class="sources"><div class="sources-title">Sources</div>` +
      data.sources.map(s => `
        <div class="source-card" data-src="${s.source}" data-ans="${data.answer_id}">
          <div class="sc-head">
            <span class="source-num">${s.source}</span>
            <span>${escapeHtml(s.document_name)}</span>
            <span class="sc-score">${Math.round((s.score || 0) * 100)}% match</span>
          </div>
          <div class="sc-meta">${escapeHtml(s.section || "—")} · ${escapeHtml(s.department)} ·
            ${escapeHtml(s.confidentiality || "internal")}${s.effective_date ? " · eff. " + escapeHtml(s.effective_date) : ""}</div>
          <div class="sc-snippet">${escapeHtml(s.snippet || "")}</div>
        </div>`).join("") + `</div>`;
  }

  const nextHtml = data.next_action
    ? `<div class="next-action"><strong>Suggested next step:</strong> ${escapeHtml(data.next_action)}</div>` : "";

  const assumHtml = data.assumptions
    ? `<div class="next-action" style="border-color:var(--warn)"><strong>Note:</strong> ${escapeHtml(data.assumptions)}</div>` : "";

  const el = document.createElement("div");
  el.className = "msg bot";
  el.innerHTML = `<div class="avatar">EG</div>
    <div class="body"><div class="who">Enterprise GPT</div>
    <div class="bubble">
      ${renderMarkdown(data.answer || "")}
      ${assumHtml}
      ${nextHtml}
      <div class="answer-meta">
        ${sourceTypePill(data.source_type)}
        <span class="pill conf">Confidence: ${escapeHtml(data.confidence || "—")}</span>
        <span class="pill conf">${data.latency_ms} ms</span>
      </div>
      ${sourcesHtml}
      <div class="feedback" data-ans="${data.answer_id}" data-q="${escapeHtml(data.query)}">
        <button data-r="up" title="Helpful">👍</button>
        <button data-r="down" title="Not helpful">👎</button>
      </div>
    </div></div>`;
  chat.appendChild(el);
  scroll();
}

async function send() {
  const q = input.value.trim();
  if (!q) return;
  input.value = ""; input.style.height = "auto";
  addUserMsg(q);
  addTyping();
  $("#sendBtn").disabled = true;
  try {
    const data = await api("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, department: state.department, mode: state.mode }),
    });
    renderAnswer(data);
  } catch (e) {
    $("#typing")?.remove();
    const el = document.createElement("div");
    el.className = "msg bot";
    el.innerHTML = `<div class="avatar">EG</div><div class="body"><div class="who">Enterprise GPT</div>
      <div class="bubble"><p>⚠ ${escapeHtml(e.message)}</p></div></div>`;
    chat.appendChild(el);
    scroll();
  } finally {
    $("#sendBtn").disabled = false;
  }
}

/* citation click -> open matching source card; feedback clicks (delegated) */
chat.addEventListener("click", e => {
  const cite = e.target.closest(".cite");
  if (cite) {
    const bubble = cite.closest(".bubble");
    const card = bubble.querySelector(`.source-card[data-src="${cite.dataset.cite}"]`);
    if (card) { card.classList.add("open"); card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      card.style.borderColor = "var(--accent)"; }
    return;
  }
  const sc = e.target.closest(".source-card");
  if (sc) { sc.classList.toggle("open"); return; }

  const fb = e.target.closest(".feedback button");
  if (fb) {
    const wrap = fb.closest(".feedback");
    $$("button", wrap).forEach(b => b.classList.remove("done"));
    fb.classList.add("done");
    api("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer_id: wrap.dataset.ans, query: wrap.dataset.q, rating: fb.dataset.r }),
    }).then(() => toast("Thanks for the feedback!")).catch(() => {});
  }
});

function scroll() { $(".main").scrollTo({ top: $(".main").scrollHeight, behavior: "smooth" }); }

/* ---------- knowledge base ---------- */
async function loadDocs() {
  const list = $("#docList");
  list.innerHTML = `<p class="muted-note">Loading…</p>`;
  try {
    const { documents } = await api("/api/documents");
    if (!documents.length) {
      list.innerHTML = `<div class="doc-empty"><div class="de-ic">📚</div>
        <p>No documents yet. Upload SOPs, policies, manuals or runbooks to build your knowledge base.</p></div>`;
      return;
    }
    list.innerHTML = documents.map(d => `
      <div class="doc-card">
        <div class="doc-icon">📄</div>
        <div class="doc-info">
          <div class="dn">${escapeHtml(d.name)}</div>
          <div class="doc-tags">
            <span class="tag dept">${escapeHtml(d.department)}</span>
            <span class="tag">${escapeHtml(d.doc_type)}</span>
            ${d.confidentiality === "restricted" ? `<span class="tag restricted">restricted</span>` : `<span class="tag">${escapeHtml(d.confidentiality)}</span>`}
            <span class="tag">${d.chunk_count} chunks</span>
            ${d.owner ? `<span class="tag">owner: ${escapeHtml(d.owner)}</span>` : ""}
          </div>
        </div>
        <div class="doc-actions">
          <span class="status-chip">indexed</span>
          <button class="icon-btn" data-del="${d.id}" title="Remove">🗑</button>
        </div>
      </div>`).join("");
  } catch (e) {
    list.innerHTML = `<p class="muted-note">${escapeHtml(e.message)}</p>`;
  }
}
$("#docList").addEventListener("click", async e => {
  const del = e.target.closest("[data-del]");
  if (!del) return;
  try { await api(`/api/documents/${del.dataset.del}`, { method: "DELETE" }); toast("Document removed"); loadDocs(); }
  catch (err) { toast(err.message); }
});

/* ---------- upload modal ---------- */
const modal = $("#uploadModal");
$("#openUpload").addEventListener("click", () => modal.classList.remove("hidden"));
$("#closeUpload").addEventListener("click", () => modal.classList.add("hidden"));
$("#cancelUpload").addEventListener("click", () => modal.classList.add("hidden"));
modal.addEventListener("click", e => { if (e.target === modal) modal.classList.add("hidden"); });

const drop = $("#drop"), fileInput = $("#fileInput");
drop.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  $("#fileLabel").textContent = fileInput.files[0]?.name || "Click to choose a file";
});
["dragover", "dragenter"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("hot"); }));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("hot"); }));
drop.addEventListener("drop", e => {
  if (e.dataTransfer.files.length) { fileInput.files = e.dataTransfer.files; $("#fileLabel").textContent = e.dataTransfer.files[0].name; }
});

$("#uploadForm").addEventListener("submit", async e => {
  e.preventDefault();
  const status = $("#uploadStatus");
  if (!fileInput.files.length) { status.className = "upload-status err"; status.textContent = "Please choose a file."; return; }
  const fd = new FormData(e.target);
  fd.append("file", fileInput.files[0]);
  status.className = "upload-status busy"; status.textContent = "Parsing, chunking & embedding…";
  $("#uploadBtn").disabled = true;
  try {
    const r = await api("/api/documents/upload", { method: "POST", body: fd });
    status.className = "upload-status ok";
    status.textContent = `✓ Indexed "${r.name}" — ${r.chunk_count} chunks.`;
    toast("Document indexed");
    e.target.reset(); $("#fileLabel").textContent = "Click to choose a file"; fileInput.value = "";
    setTimeout(() => { modal.classList.add("hidden"); status.textContent = ""; }, 1400);
  } catch (err) {
    status.className = "upload-status err"; status.textContent = err.message;
  } finally { $("#uploadBtn").disabled = false; }
});

/* ---------- analytics ---------- */
$("#refreshAnalytics").addEventListener("click", loadAnalytics);
async function loadAnalytics() {
  try {
    const a = await api("/api/analytics/quality");
    $("#statGrid").innerHTML = `
      ${stat(a.total_queries, "Total queries", "primary")}
      ${stat(a.citation_coverage + "%", "Answered from documents", "accent")}
      ${stat(a.no_answer_rate + "%", "No-answer rate")}
      ${stat(a.avg_latency_ms + " ms", "Avg response time")}
      ${stat(a.total_documents, "Documents indexed")}
      ${stat(a.total_chunks, "Knowledge chunks")}
      ${stat(a.feedback_up, "👍 Helpful", "accent")}
      ${stat(a.feedback_down, "👎 Not helpful")}`;

    const dept = a.queries_by_department || [];
    const max = Math.max(1, ...dept.map(d => d.c));
    $("#byDept").innerHTML = dept.length ? dept.map(d => `
      <div class="bar-row"><div class="bl">${escapeHtml(d.department)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(d.c / max) * 100}%"></div></div>
      <div class="bv">${d.c}</div></div>`).join("") : `<p class="muted-note">No queries yet.</p>`;

    const rep = a.repeated_questions || [];
    $("#repeated").innerHTML = rep.length ? rep.map(r => `
      <div class="rep-row"><span>${escapeHtml(r.query)}</span><span class="rc">×${r.c}</span></div>`).join("")
      : `<p class="muted-note">No repeated questions yet — a healthy sign, or just early days.</p>`;
  } catch (e) { toast(e.message); }
}
function stat(val, lab, cls = "") {
  return `<div class="stat"><div class="val ${cls}">${val}</div><div class="lab">${lab}</div></div>`;
}

/* ---------- model status ---------- */
async function loadModelStatus() {
  try {
    const h = await api("/api/health");   // health needs no auth
    const dot = $("#llmDot"), txt = $("#llmStatus");
    if (h.llm_configured) { dot.className = "dot dot-ok"; txt.textContent = `Model ready · ${h.chat_model}`; }
    else { dot.className = "dot dot-err"; txt.textContent = "No API key — set GEMINI_API_KEY"; }
  } catch (e) {
    $("#llmDot").className = "dot dot-err"; $("#llmStatus").textContent = "Backend unreachable";
  }
}

/* ========================================================================
   AUTHENTICATION
   ======================================================================== */
function showAuth() {
  document.body.classList.add("locked");
  $("#authScreen").classList.remove("hidden");
}
function hideAuth() {
  document.body.classList.remove("locked");
  $("#authScreen").classList.add("hidden");
}

function applyUser(user) {
  state.user = user;
  const isAdmin = user.role === "admin";

  // user chip
  $("#userAvatar").textContent = (user.name || user.email)[0] || "?";
  $("#userName").textContent = user.name || user.email;
  $("#userRole").innerHTML = `${user.role}${isAdmin ? "" : " · " + user.department}` +
    `<span class="role-badge ${user.role}">${user.role}</span>`;

  // show/hide admin-only parts
  $$(".admin-only").forEach(el => el.classList.toggle("hidden", !isAdmin));

  // employees are locked to their own department
  if (!isAdmin) {
    state.department = user.department;
    // make sure we're on the chat view (their only view)
    $$(".nav-item").forEach(b => b.classList.remove("active"));
    $('.nav-item[data-view="chat"]').classList.add("active");
    $$(".view").forEach(v => v.classList.add("hidden"));
    $("#view-chat").classList.remove("hidden");
  } else {
    state.department = "all";
    if ($("#department")) $("#department").value = "all";
  }
  hideAuth();
  loadModelStatus();
}

/* --- auth screen interactions --- */
$$(".auth-tab").forEach(tab => tab.addEventListener("click", () => {
  $$(".auth-tab").forEach(t => t.classList.remove("active"));
  tab.classList.add("active");
  const isLogin = tab.dataset.tab === "login";
  $("#loginForm").classList.toggle("hidden", !isLogin);
  $("#registerForm").classList.toggle("hidden", isLogin);
  $("#authError").textContent = "";
}));

$$(".auth-demo button").forEach(b => b.addEventListener("click", () => {
  // switch to login tab and fill the demo credentials
  $('.auth-tab[data-tab="login"]').click();
  $("#loginForm").email.value = b.dataset.email;
  $("#loginForm").password.value = b.dataset.pw;
}));

$("#loginForm").addEventListener("submit", async e => {
  e.preventDefault();
  $("#authError").textContent = "";
  const btn = e.target.querySelector("button"); btn.disabled = true;
  try {
    const data = await api("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: e.target.email.value, password: e.target.password.value }),
    });
    setToken(data.token);
    applyUser(data.user);
    toast(`Welcome back, ${data.user.name || data.user.email}!`);
  } catch (err) {
    $("#authError").textContent = err.message;
  } finally { btn.disabled = false; }
});

$("#registerForm").addEventListener("submit", async e => {
  e.preventDefault();
  $("#authError").textContent = "";
  const btn = e.target.querySelector("button"); btn.disabled = true;
  try {
    const data = await api("/api/auth/register", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: e.target.name.value, email: e.target.email.value,
        password: e.target.password.value, department: e.target.department.value,
      }),
    });
    setToken(data.token);
    applyUser(data.user);
    toast("Account created — you're signed in.");
  } catch (err) {
    $("#authError").textContent = err.message;
  } finally { btn.disabled = false; }
});

$("#logoutBtn").addEventListener("click", () => {
  setToken(null);
  state.user = null;
  showAuth();
  // reset forms
  $("#loginForm").reset(); $("#registerForm").reset();
  toast("Signed out.");
});

/* --- on load: resume session if a valid token exists --- */
(async () => {
  const token = getToken();
  if (!token) { showAuth(); return; }
  try {
    const data = await api("/api/auth/me");
    applyUser(data.user);
  } catch (e) {
    showAuth();   // token invalid/expired
  }
})();
