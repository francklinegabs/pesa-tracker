"use strict";

// ---- helpers ---------------------------------------------------------------

const $ = (sel, root = document) => root.querySelector(sel);
const SVG_NS = "http://www.w3.org/2000/svg";

const kes = (n) =>
  "KES " + Number(n).toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const shortKes = (n) => {
  const abs = Math.abs(n);
  if (abs >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (abs >= 1e3) return (n / 1e3).toFixed(abs >= 1e4 ? 0 : 1) + "k";
  return String(Math.round(n));
};

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v);
  }
  for (const c of children) node.append(c instanceof Node ? c : String(c));
  return node;
}

function svg(tag, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 401) {
    location.href = "/login";
    throw new Error("Please log in");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

const state = { month: "", accounts: [], categories: [], editingId: null };

function todayLocal() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

// ---- dashboard -------------------------------------------------------------

async function loadDashboard() {
  const [summary, flow] = await Promise.all([
    api(`/api/summary?month=${state.month}`),
    api(`/api/cashflow?month=${state.month}&months=6`),
  ]);

  $("#stat-income").textContent = kes(summary.income);
  $("#stat-expense").textContent = kes(summary.expense);
  const net = $("#stat-net");
  net.textContent = kes(summary.net);
  net.className = "value " + (summary.net >= 0 ? "income" : "expense");

  renderAccounts(summary.accounts);
  renderBudgets(summary.categories.filter((c) => c.budget));
  renderCategoryChart(summary.categories.filter((c) => c.amount > 0));
  renderCashFlow(flow);
  renderGoals(summary.goals);
}

function renderAccounts(accounts) {
  const list = $("#accounts");
  list.replaceChildren(
    ...accounts.map((a) =>
      el("li", {}, el("span", {}, a.name, el("span", { class: "kind" }, a.kind)),
         el("span", { class: "amount" }, kes(a.balance)))),
    el("li", {}, el("span", {}, "Total"),
       el("span", { class: "amount" }, kes(accounts.reduce((s, a) => s + a.balance, 0)))),
  );
}

function progressRow(label, detail, ratio) {
  const level = ratio > 1 ? "over" : ratio >= 0.8 ? "warn" : "";
  return el("div", { class: "bar-row" },
    el("div", { class: "top" }, el("span", {}, label), el("span", { class: "muted" }, detail)),
    el("div", { class: "track" },
      el("div", { class: `fill ${level}`, style: `width:${Math.min(ratio, 1) * 100}%` })));
}

function renderBudgets(rows) {
  const box = $("#budgets");
  if (!rows.length) {
    box.replaceChildren(el("p", { class: "empty" }, "No budgets yet. Add one with: pesa budget set food 8000"));
    return;
  }
  box.replaceChildren(...rows.map((r) => {
    const ratio = r.amount / r.budget;
    const left = r.budget - r.amount;
    const detail = `${kes(r.amount)} of ${kes(r.budget)} · ` +
      (left >= 0 ? `${kes(left)} left` : `over by ${kes(-left)}`);
    return progressRow(r.category, detail, ratio);
  }));
}

function renderGoals(goals) {
  const box = $("#goals");
  if (!goals.length) {
    box.replaceChildren(el("p", { class: "empty" }, 'No goals yet. Add one with: pesa goal add "laptop" 60000'));
    return;
  }
  box.replaceChildren(...goals.map((g) => {
    let detail = `${kes(g.saved)} of ${kes(g.target)}`;
    if (g.per_month) detail += ` · ${kes(g.per_month)}/month to finish by ${g.deadline}`;
    return progressRow(g.name, detail, g.progress);
  }));
}

function renderCategoryChart(rows) {
  const box = $("#chart-categories");
  if (!rows.length) {
    box.replaceChildren(el("p", { class: "empty" }, "No spending this month."));
    return;
  }
  const width = 640, rowH = 30, labelW = 120, valueW = 110;
  const height = rows.length * rowH + 4;
  const max = Math.max(...rows.map((r) => r.amount));
  const chart = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
                             "aria-label": "Spending by category" });
  rows.forEach((r, i) => {
    const y = i * rowH + 4;
    const w = Math.max(((width - labelW - valueW) * r.amount) / max, 2);
    chart.append(
      svg("text", { x: 0, y: y + 15 }, r.category),
      svg("rect", { class: "bar", x: labelW, y: y + 3, width: w, height: 16, rx: 3 }),
      svg("text", { class: "value-label", x: labelW + w + 8, y: y + 15 }, kes(r.amount)),
    );
  });
  box.replaceChildren(chart);
}

function renderCashFlow(rows) {
  const box = $("#chart-cashflow");
  const width = 640, height = 220, left = 44, bottom = 24, top = 10;
  const plotH = height - bottom - top;
  const max = Math.max(1, ...rows.flatMap((r) => [r.income, r.expense]));
  const groupW = (width - left) / rows.length;
  const barW = Math.min(28, groupW / 3);
  const chart = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
                             "aria-label": "Income and spending per month" });

  for (let i = 0; i <= 4; i++) {
    const value = (max * i) / 4;
    const y = top + plotH - (plotH * i) / 4;
    chart.append(
      svg("line", { class: "axis", x1: left, x2: width, y1: y, y2: y }),
      svg("text", { x: left - 6, y: y + 4, "text-anchor": "end" }, shortKes(value)),
    );
  }
  rows.forEach((r, i) => {
    const cx = left + groupW * i + groupW / 2;
    const bar = (value, cls, x) => {
      const h = (plotH * value) / max;
      const rect = svg("rect", { class: cls, x, y: top + plotH - h, width: barW, height: h, rx: 2 });
      rect.append(svg("title", {}, `${r.month}: ${kes(value)}`));
      return rect;
    };
    const [y, m] = r.month.split("-");
    const label = new Date(+y, +m - 1, 1).toLocaleString("en", { month: "short" });
    chart.append(
      bar(r.income, "bar-income", cx - barW - 1),
      bar(r.expense, "bar", cx + 1),
      svg("text", { x: cx, y: height - 6, "text-anchor": "middle" }, label),
    );
  });
  box.replaceChildren(chart);
}

// ---- transactions ----------------------------------------------------------

function filterParams() {
  const params = new URLSearchParams();
  for (const input of $("#filters").querySelectorAll("input, select")) {
    if (input.value) params.set(input.name, input.value);
  }
  return params;
}

async function loadTransactions() {
  const rows = await api(`/api/transactions?${filterParams()}`);
  const body = $("#tx-body");
  if (!rows.length) {
    body.replaceChildren(el("tr", {}, el("td", { colspan: 7, class: "empty" }, "No transactions match.")));
  } else {
    body.replaceChildren(...rows.map(txRow));
  }
  const totalIn = rows.filter((t) => t.kind === "income").reduce((s, t) => s + t.amount, 0);
  const totalOut = rows.filter((t) => t.kind === "expense").reduce((s, t) => s + t.amount, 0);
  $("#tx-count").textContent =
    `${rows.length} transaction(s) · in ${kes(totalIn)} · out ${kes(totalOut)}`;
}

function txRow(t) {
  const sign = t.kind === "income" ? "+" : t.kind === "expense" ? "−" : "";
  const account = t.kind === "transfer" ? `${t.account} → ${t.to_account}` : t.account;
  return el("tr", { class: state.editingId === t.id ? "editing" : "" },
    el("td", {}, t.occurred_on),
    el("td", {}, t.kind),
    el("td", {}, t.category),
    el("td", {}, account),
    el("td", { class: `amount ${t.kind}` }, sign + kes(t.amount)),
    el("td", {}, t.note),
    el("td", { class: "actions" },
      el("button", { type: "button", onclick: () => startEdit(t) }, "Edit"),
      el("button", { type: "button", onclick: () => removeTx(t) }, "Delete")),
  );
}

function fillSelects() {
  for (const select of document.querySelectorAll(".account-select")) {
    const current = select.value;
    select.replaceChildren(...state.accounts.map((a) => el("option", { value: a.name }, a.name)));
    if (current) select.value = current;
  }
  const filter = $(".account-filter");
  const chosen = filter.value;
  filter.replaceChildren(el("option", { value: "" }, "All accounts"),
    ...state.accounts.map((a) => el("option", { value: a.name }, a.name)));
  filter.value = chosen;

  const catFilter = $("#filter-category");
  const chosenCat = catFilter.value;
  catFilter.replaceChildren(el("option", { value: "" }, "All categories"),
    ...state.categories.map((c) => el("option", { value: c }, c)));
  catFilter.value = chosenCat;
  $("#category-list").replaceChildren(...state.categories.map((c) => el("option", { value: c })));
}

async function loadLookups() {
  [state.accounts, state.categories] = await Promise.all([api("/api/accounts"), api("/api/categories")]);
  fillSelects();
}

function syncKind() {
  const form = $("#tx-form");
  const isTransfer = form.kind.value === "transfer";
  $(".for-transfer", form).hidden = !isTransfer;
  $(".for-category", form).hidden = isTransfer;
  if (isTransfer && form.to_account.value === form.account.value) {
    const other = state.accounts.find((a) => a.name !== form.account.value);
    if (other) form.to_account.value = other.name;
  }
}

function resetForm() {
  const form = $("#tx-form");
  form.reset();
  state.editingId = null;
  form.date.value = todayLocal();
  if (state.accounts.some((a) => a.name === "mpesa")) form.account.value = "mpesa";
  $("#form-title").textContent = "Add a transaction";
  $("#save-btn").textContent = "Add";
  $("#cancel-edit").hidden = true;
  $("#form-error").textContent = "";
  syncKind();
}

function startEdit(t) {
  const form = $("#tx-form");
  state.editingId = t.id;
  form.kind.value = t.kind;
  form.amount.value = t.amount;
  form.category.value = t.category;
  form.account.value = t.account;
  form.to_account.value = t.to_account || "";
  form.date.value = t.occurred_on;
  form.note.value = t.note;
  $("#form-title").textContent = `Edit transaction #${t.id}`;
  $("#save-btn").textContent = "Save changes";
  $("#cancel-edit").hidden = false;
  syncKind();
  form.scrollIntoView({ behavior: "smooth" });
  loadTransactions();
}

async function saveTx(event) {
  event.preventDefault();
  const form = event.target;
  const body = {
    kind: form.kind.value,
    amount: form.amount.value,
    category: form.kind.value === "transfer" ? "transfer" : form.category.value,
    account: form.account.value,
    to_account: form.kind.value === "transfer" ? form.to_account.value : null,
    date: form.date.value,
    note: form.note.value,
  };
  try {
    if (state.editingId) {
      await api(`/api/transactions/${state.editingId}`, { method: "PUT", body });
    } else {
      await api("/api/transactions", { method: "POST", body });
    }
    resetForm();
    await refresh();
  } catch (err) {
    $("#form-error").textContent = err.message;
  }
}

async function removeTx(t) {
  if (!confirm(`Delete ${t.kind} of ${kes(t.amount)} (${t.category}) on ${t.occurred_on}?`)) return;
  try {
    await api(`/api/transactions/${t.id}`, { method: "DELETE" });
    if (state.editingId === t.id) resetForm();
    await refresh();
  } catch (err) {
    alert(err.message);
  }
}

async function pasteSms(event) {
  event.preventDefault();
  const form = event.target;
  const status = $("#sms-result");
  try {
    const result = await api("/api/sms/paste", { method: "POST", body: { text: form.text.value } });
    const parts = [`${result.added.length} added`];
    if (result.skipped.length) parts.push(`${result.skipped.length} already recorded`);
    if (result.unreadable) parts.push(`${result.unreadable} not recognised`);
    status.textContent = parts.join(" · ");
    if (result.added.length) {
      form.reset();
      await refresh();
    }
  } catch (err) {
    status.textContent = err.message;
  }
}

// ---- wiring ----------------------------------------------------------------

function showView(name) {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.classList.toggle("active", tab.dataset.view === name);
  }
  $("#view-dashboard").hidden = name !== "dashboard";
  $("#view-transactions").hidden = name !== "transactions";
  location.hash = name;
}

async function refresh() {
  await loadLookups();
  await Promise.all([loadDashboard(), loadTransactions()]);
}

let filterTimer;
function onFilterChange() {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(loadTransactions, 200);
}

function init() {
  const now = new Date();
  state.month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const monthInput = $("#month");
  monthInput.value = state.month;
  monthInput.addEventListener("change", () => {
    if (!monthInput.value) return;
    state.month = monthInput.value;
    loadDashboard().catch(showFatal);
  });

  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => showView(tab.dataset.view));
  }
  $("#filters").addEventListener("input", onFilterChange);
  const form = $("#tx-form");
  form.addEventListener("submit", saveTx);
  $("#sms-form").addEventListener("submit", pasteSms);
  form.kind.addEventListener("change", syncKind);
  form.account.addEventListener("change", syncKind);
  $("#cancel-edit").addEventListener("click", () => { resetForm(); loadTransactions(); });

  showView(location.hash === "#transactions" ? "transactions" : "dashboard");
  refresh().then(resetForm).catch(showFatal);
}

function showFatal(err) {
  document.querySelector("main").prepend(
    el("div", { class: "card form-error" }, `Could not load data: ${err.message}`));
}

init();
