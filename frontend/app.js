"use strict";

const $ = (sel) => document.querySelector(sel);

const KIND_LABELS = {
  cash: "Cash", brokerage: "Brokerage", retirement: "Retirement", property: "Property",
  other_asset: "Other asset", credit_card: "Credit card", loan: "Loan", mortgage: "Mortgage",
  other_liability: "Other liability",
};
const LIABILITY_KINDS = new Set(["credit_card", "loan", "mortgage", "other_liability"]);
const TAX_LABELS = {
  taxable: "Taxable", tax_deferred: "Tax-deferred (401k / IRA)", tax_free: "Tax-free (Roth / HSA)", none: "None",
};
const FLOW_LABELS = { income: "Income", expense: "Expense", goal: "Goal" };
const ASSET_CLASS_LABELS = {
  cash: "Cash", stocks: "Stocks", funds: "Funds", bonds: "Bonds", crypto: "Crypto",
  real_estate: "Real estate", unclassified_investments: "Investments (no holdings)", other: "Other",
};
const PALETTE = ["#2f6fde", "#1f9d55", "#c98a00", "#d64545", "#7b4fd6", "#0f9bb5", "#e0752d", "#6b7385"];

const state = { planId: null, plans: [], charts: {} };

// ---------- helpers ----------

const moneyFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const compactFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 });
const money = (v) => (v == null ? "—" : moneyFmt.format(v));
const compact = (v) => compactFmt.format(v);
const pct = (v, digits = 1) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const today = () => new Date().toISOString().slice(0, 10);

function formatError(data) {
  if (!data) return null;
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d) => `${d.loc.at(-1)}: ${d.msg}`).join("; ");
  return null;
}

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(formatError(data) || `${res.status} ${res.statusText}`);
  return data;
}

let toastTimer;
function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 3500);
}

function drawChart(id, config) {
  state.charts[id]?.destroy();
  if (typeof Chart === "undefined") return;
  state.charts[id] = new Chart(document.getElementById(id), config);
}

function card(label, value, sub = "", cls = "") {
  return `<div class="card"><div class="label">${esc(label)}</div><div class="value ${cls}">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
}

function guard(fn) {
  return async (...args) => {
    try {
      await fn(...args);
    } catch (err) {
      toast(err.message);
    }
  };
}

// ---------- form dialog ----------

function openForm({ title, fields, values = {}, onSubmit }) {
  const dialog = $("#form-dialog");
  const box = $("#dialog-fields");
  $("#dialog-title").textContent = title;
  $("#dialog-error").textContent = "";
  box.innerHTML = "";
  const inputs = {};

  for (const f of fields) {
    const label = document.createElement("label");
    if (f.full) label.classList.add("full");
    let input;
    if (f.type === "select") {
      input = document.createElement("select");
      for (const [value, text] of Object.entries(f.options)) input.add(new Option(text, value));
      input.value = values[f.name] ?? f.default ?? Object.keys(f.options)[0];
    } else if (f.type === "checkbox") {
      label.classList.add("check");
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(values[f.name] ?? f.default);
    } else {
      input = document.createElement("input");
      input.type = f.type === "percent" ? "number" : f.type || "text";
      if (f.type === "number" || f.type === "percent") input.step = f.step ?? "any";
      let v = values[f.name] ?? f.default;
      if (f.type === "percent" && v != null) v = +(v * 100).toFixed(4);
      if (v != null) input.value = v;
      if (f.required) input.required = true;
    }
    input.name = f.name;
    inputs[f.name] = [f, input];
    const text = document.createElement("span");
    text.textContent = f.type === "percent" ? `${f.label} (%)` : f.label;
    if (f.type === "checkbox") label.append(input, text);
    else label.append(text, input);
    if (f.help) {
      const help = document.createElement("span");
      help.className = "help";
      help.textContent = f.help;
      label.append(help);
    }
    box.append(label);
  }

  const collect = () => {
    const out = {};
    for (const [name, [f, input]] of Object.entries(inputs)) {
      if (f.type === "checkbox") out[name] = input.checked;
      else if (f.type === "number") out[name] = input.value === "" ? null : Number(input.value);
      else if (f.type === "percent") out[name] = input.value === "" ? null : Number(input.value) / 100;
      else out[name] = input.value === "" ? null : input.value;
    }
    return out;
  };

  $("#dialog-form").onsubmit = async (e) => {
    e.preventDefault();
    if (e.submitter?.value === "cancel") return dialog.close();
    try {
      await onSubmit(collect());
      dialog.close();
    } catch (err) {
      $("#dialog-error").textContent = err.message;
    }
  };
  dialog.showModal();
}

// ---------- tabs ----------

const loaders = {
  dashboard: loadDashboard,
  accounts: loadAccounts,
  plan: loadPlans,
  compare: loadCompare,
  debt: loadDebt,
};

function showTab(name) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${name}`));
  history.replaceState(null, "", `#${name}`);
  guard(loaders[name])();
}

document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

// ---------- dashboard ----------

async function loadDashboard() {
  const [nw, alloc, plans] = await Promise.all([api("/api/net-worth"), api("/api/allocation"), api("/api/plans")]);
  const cards = [
    card("Net worth", money(nw.net_worth), "", nw.net_worth < 0 ? "bad" : ""),
    card("Assets", money(nw.assets)),
    card("Liabilities", money(nw.liabilities)),
  ];
  if (plans.length) {
    const proj = await api(`/api/plans/${plans[0].id}/projection?simulations=500`);
    const rate = proj.monte_carlo.success_rate;
    cards.push(card("Plan success", pct(rate, 0), esc(plans[0].name), scoreClass(rate)));
  } else {
    cards.push(card("Plan success", "—", "Create a plan on the Plan tab"));
  }
  $("#summary-cards").innerHTML = cards.join("");

  $("#nw-empty").hidden = nw.history.length > 0;
  drawChart("nw-chart", {
    type: "line",
    data: {
      labels: nw.history.map((h) => h.date),
      datasets: [
        { label: "Net worth", data: nw.history.map((h) => h.net_worth), borderColor: PALETTE[0], backgroundColor: "rgba(47,111,222,0.1)", fill: true, tension: 0.2 },
        { label: "Liabilities", data: nw.history.map((h) => h.liabilities), borderColor: PALETTE[3], borderDash: [4, 4], pointRadius: 0 },
      ],
    },
    options: moneyChartOptions(),
  });

  $("#alloc-empty").hidden = alloc.length > 0;
  drawChart("alloc-chart", {
    type: "doughnut",
    data: {
      labels: alloc.map((a) => ASSET_CLASS_LABELS[a.asset_class] ?? a.asset_class),
      datasets: [{ data: alloc.map((a) => a.value), backgroundColor: PALETTE }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { tooltip: { callbacks: { label: (c) => `${c.label}: ${money(c.raw)} (${pct(alloc[c.dataIndex].share)})` } } },
    },
  });
}

function scoreClass(rate) {
  if (rate >= 0.85) return "good";
  if (rate >= 0.7) return "warn";
  return "bad";
}

function moneyChartOptions(extra = {}) {
  return {
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    scales: { y: { ticks: { callback: (v) => compact(v) } }, ...(extra.scales || {}) },
    plugins: {
      tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${money(c.parsed.y)}` } },
      ...(extra.plugins || {}),
    },
  };
}

// ---------- accounts ----------

const accountFields = (isNew) => [
  { name: "name", label: "Name", required: true, full: true },
  { name: "institution", label: "Institution" },
  { name: "kind", label: "Type", type: "select", options: KIND_LABELS },
  { name: "tax_treatment", label: "Tax treatment", type: "select", options: TAX_LABELS, help: "Only matters for investment accounts" },
  ...(isNew ? [{ name: "balance", label: "Current balance", type: "number", help: "Debts: enter the amount owed" }] : []),
  { name: "interest_rate", label: "Interest rate / APR", type: "percent", default: 0, help: "For debts" },
  { name: "monthly_payment", label: "Monthly payment", type: "number", default: 0, help: "For debts" },
  { name: "annual_contribution", label: "Yearly contribution", type: "number", default: 0, help: "Planned yearly savings into this account until retirement" },
];

async function loadAccounts() {
  const includeArchived = $("#show-archived").checked;
  const accounts = await api(`/api/accounts?include_archived=${includeArchived}`);
  const table = $("#accounts-table");
  if (!accounts.length) {
    table.innerHTML = `<tr><td class="muted">No accounts yet. Add one manually or connect an institution below.</td></tr>`;
  } else {
    table.innerHTML = `
      <tr><th>Name</th><th>Type</th><th>Tax</th><th class="num">Balance</th><th>As of</th>
      <th class="num">Rate</th><th class="num">Payment/mo</th><th class="num">Contrib/yr</th><th></th></tr>
      ${accounts.map((a) => `
        <tr class="${a.archived ? "archived" : ""}">
          <td>${esc(a.name)} ${a.linked ? '<span class="tag linked">linked</span>' : ""}
            ${a.institution ? `<div class="muted">${esc(a.institution)}</div>` : ""}</td>
          <td>${KIND_LABELS[a.kind]}</td>
          <td>${a.is_liability ? "—" : TAX_LABELS[a.tax_treatment].split(" (")[0]}</td>
          <td class="num ${a.is_liability ? "bad" : ""}">${a.is_liability ? "−" : ""}${money(a.latest_balance)}</td>
          <td>${a.latest_as_of ?? "—"}</td>
          <td class="num">${a.interest_rate ? pct(a.interest_rate, 2) : "—"}</td>
          <td class="num">${a.monthly_payment ? money(a.monthly_payment) : "—"}</td>
          <td class="num">${a.annual_contribution ? money(a.annual_contribution) : "—"}</td>
          <td>
            <button class="link" data-act="balance" data-id="${a.id}">Update balance</button>
            <button class="link" data-act="edit" data-id="${a.id}">Edit</button>
            <button class="link" data-act="archive" data-id="${a.id}">${a.archived ? "Unarchive" : "Archive"}</button>
            ${a.linked ? "" : `<button class="link danger" data-act="delete" data-id="${a.id}">Delete</button>`}
          </td>
        </tr>`).join("")}`;
  }
  table.onclick = guard(async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const acct = accounts.find((a) => a.id === Number(btn.dataset.id));
    await accountAction(btn.dataset.act, acct);
  });
  await loadPlaid();
}

async function accountAction(act, acct) {
  if (act === "balance") {
    openForm({
      title: `Update balance: ${acct.name}`,
      fields: [
        { name: "balance", label: acct.is_liability ? "Amount owed" : "Balance", type: "number", required: true },
        { name: "as_of", label: "As of", type: "date", default: today() },
      ],
      values: { balance: acct.latest_balance },
      onSubmit: async (v) => {
        await api(`/api/accounts/${acct.id}/balances`, { method: "POST", body: v });
        await loadAccounts();
      },
    });
  } else if (act === "edit") {
    openForm({
      title: `Edit ${acct.name}`,
      fields: accountFields(false),
      values: acct,
      onSubmit: async (v) => {
        await api(`/api/accounts/${acct.id}`, { method: "PATCH", body: v });
        await loadAccounts();
      },
    });
  } else if (act === "archive") {
    await api(`/api/accounts/${acct.id}`, { method: "PATCH", body: { archived: !acct.archived } });
    await loadAccounts();
  } else if (act === "delete") {
    if (!confirm(`Delete "${acct.name}" and its balance history?`)) return;
    await api(`/api/accounts/${acct.id}`, { method: "DELETE" });
    await loadAccounts();
  }
}

$("#show-archived").addEventListener("change", guard(loadAccounts));
$("#add-account").addEventListener("click", () =>
  openForm({
    title: "Add account",
    fields: accountFields(true),
    onSubmit: async (v) => {
      if (LIABILITY_KINDS.has(v.kind)) v.tax_treatment = "none";
      await api("/api/accounts", { method: "POST", body: v });
      await loadAccounts();
    },
  })
);

// ---------- plaid ----------

let plaidScript;
function loadPlaidScript() {
  plaidScript ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://cdn.plaid.com/link/v2/stable/link-initialize.js";
    s.onload = resolve;
    s.onerror = () => reject(new Error("Could not load Plaid Link. Check your internet connection."));
    document.head.append(s);
  });
  return plaidScript;
}

async function loadPlaid() {
  const status = await api("/api/plaid/status");
  $("#plaid-connect").disabled = !status.enabled;
  $("#plaid-sync").disabled = !status.enabled;
  $("#plaid-status").innerHTML = status.enabled
    ? `Environment: <strong>${esc(status.environment)}</strong>.` +
      (status.environment === "sandbox" ? " Sandbox login: <code>user_good</code> / <code>pass_good</code>." : "")
    : "Plaid isn't configured. Add <code>PLAID_CLIENT_ID</code> and <code>PLAID_SECRET</code> to <code>.env</code> and restart the server. Manual accounts work without it.";

  const items = await api("/api/plaid/items");
  const table = $("#plaid-items");
  table.innerHTML = items.length
    ? `<tr><th>Institution</th><th class="num">Accounts</th><th>Last synced</th><th></th></tr>` +
      items.map((i) => `
        <tr><td>${esc(i.institution_name ?? "Unknown")}</td><td class="num">${i.accounts}</td>
        <td>${i.last_synced_at ? new Date(i.last_synced_at).toLocaleString() : "—"}</td>
        <td><button class="link danger" data-id="${i.id}">Disconnect</button></td></tr>`).join("")
    : "";
  table.onclick = guard(async (e) => {
    const btn = e.target.closest("button[data-id]");
    if (!btn || !confirm("Disconnect this institution? Its accounts stay, but stop syncing.")) return;
    await api(`/api/plaid/items/${btn.dataset.id}`, { method: "DELETE" });
    await loadAccounts();
  });
}

$("#plaid-connect").addEventListener("click", guard(async () => {
  await loadPlaidScript();
  const { link_token } = await api("/api/plaid/link-token", { method: "POST" });
  window.Plaid.create({
    token: link_token,
    onSuccess: guard(async (public_token, metadata) => {
      const r = await api("/api/plaid/exchange", {
        method: "POST",
        body: { public_token, institution_name: metadata?.institution?.name ?? null },
      });
      toast(`Linked ${r.accounts_created} new account(s).`);
      await loadAccounts();
    }),
    onExit: (err) => err && toast(err.display_message || err.error_message || "Plaid Link closed with an error."),
  }).open();
}));

$("#plaid-sync").addEventListener("click", guard(async () => {
  const results = await api("/api/plaid/sync", { method: "POST" });
  const total = results.reduce((n, r) => n + r.accounts_created + r.accounts_updated, 0);
  toast(`Synced ${total} account(s).`);
  await loadAccounts();
}));

// ---------- plans ----------

const planFields = [
  { name: "name", label: "Plan name", required: true, full: true },
  { name: "birth_year", label: "Birth year", type: "number", step: 1, required: true, default: new Date().getFullYear() - 35 },
  { name: "retirement_age", label: "Retirement age", type: "number", step: 1, default: 65 },
  { name: "life_expectancy", label: "Plan until age", type: "number", step: 1, default: 95 },
  { name: "inflation", label: "Inflation", type: "percent", default: 0.025 },
  { name: "expected_return", label: "Return before retirement", type: "percent", default: 0.07, help: "Average yearly, before inflation" },
  { name: "retirement_return", label: "Return in retirement", type: "percent", default: 0.05 },
  { name: "return_volatility", label: "Return volatility", type: "percent", default: 0.15, help: "Std. deviation used by Monte Carlo" },
  { name: "cash_return", label: "Cash interest", type: "percent", default: 0.03 },
  { name: "effective_tax_rate", label: "Effective tax rate", type: "percent", default: 0.15 },
  { name: "withdrawal_rate", label: "Safe withdrawal rate", type: "percent", default: 0.04, help: "Used for the FI number" },
];

const flowFields = [
  { name: "name", label: "Name", required: true, full: true },
  { name: "kind", label: "Type", type: "select", options: FLOW_LABELS },
  { name: "amount", label: "Amount per year", type: "number", required: true, help: "Today's dollars" },
  { name: "start_age", label: "Start age", type: "number", step: 1, help: "Blank = now" },
  { name: "starts_at_retirement", label: "Starts at retirement", type: "checkbox" },
  { name: "end_age", label: "End age", type: "number", step: 1, help: "Blank = end of plan (goals: one-time)" },
  { name: "ends_at_retirement", label: "Ends at retirement", type: "checkbox" },
  { name: "real_growth", label: "Growth above inflation", type: "percent", default: 0, help: "e.g. raises" },
  { name: "taxable", label: "Taxable income", type: "checkbox", default: true },
];

async function loadPlans() {
  state.plans = await api("/api/plans");
  const select = $("#plan-select");
  select.innerHTML = state.plans.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  const has = state.plans.length > 0;
  $("#plan-empty").hidden = has;
  $("#plan-body").hidden = !has;
  ["#plan-select", "#plan-dup", "#plan-edit", "#plan-delete"].forEach((s) => ($(s).disabled = !has));
  if (!has) return;
  if (!state.plans.some((p) => p.id === state.planId)) state.planId = state.plans[0].id;
  select.value = state.planId;
  await renderPlan();
}

const currentPlan = () => state.plans.find((p) => p.id === state.planId);

async function renderPlan() {
  const plan = currentPlan();
  renderCashFlows(plan);
  const proj = await api(`/api/plans/${plan.id}/projection?simulations=1000`);
  const years = proj.years;
  const atRetirement = years.find((y) => y.age === plan.retirement_age) ?? years[0];
  const rate = proj.monte_carlo?.success_rate ?? 0;

  $("#plan-cards").innerHTML = [
    card("Chance of success", pct(rate, 0), `${proj.monte_carlo.simulations} Monte Carlo runs`, scoreClass(rate)),
    card("FI number", money(proj.fi_number), `${pct(plan.withdrawal_rate)} of retirement spending`),
    card("FI age", proj.fi_age ?? "Not reached", "Expected path"),
    card(`At retirement (${plan.retirement_age})`, money(atRetirement?.investable_real), "Investable, today's dollars"),
    card("Money lasts", proj.depletion_age ? `Until ${proj.depletion_age}` : `Past ${plan.life_expectancy}`, "Expected path", proj.depletion_age ? "bad" : "good"),
  ].join("");

  const warn = $("#plan-warnings");
  warn.hidden = proj.warnings.length === 0;
  warn.innerHTML = proj.warnings.map((w) => `<div class="warn">⚠ ${esc(w)}</div>`).join("");

  const bands = proj.monte_carlo.bands;
  const band = (key) => bands.map((b) => b[key]);
  drawChart("plan-chart", {
    type: "line",
    data: {
      labels: years.map((y) => y.age),
      datasets: [
        { label: "10th percentile", data: band("p10"), borderWidth: 0, pointRadius: 0, fill: false },
        { label: "90th percentile", data: band("p90"), borderWidth: 0, pointRadius: 0, fill: "-1", backgroundColor: "rgba(47,111,222,0.12)" },
        { label: "25th percentile", data: band("p25"), borderWidth: 0, pointRadius: 0, fill: false },
        { label: "75th percentile", data: band("p75"), borderWidth: 0, pointRadius: 0, fill: "-1", backgroundColor: "rgba(47,111,222,0.2)" },
        { label: "Median", data: band("p50"), borderColor: PALETTE[0], borderDash: [5, 4], pointRadius: 0, borderWidth: 2 },
        { label: "Expected path", data: years.map((y) => y.investable_real), borderColor: PALETTE[1], pointRadius: 0, borderWidth: 2 },
      ],
    },
    options: moneyChartOptions({
      scales: { x: { title: { display: true, text: "Age" } } },
      plugins: { legend: { labels: { filter: (item) => !item.text.includes("percentile") } } },
    }),
  });

  $("#years-table").innerHTML = `
    <tr><th>Year</th><th>Age</th><th class="num">Income</th><th class="num">Taxes</th><th class="num">Expenses</th>
    <th class="num">Goals</th><th class="num">Debt pmts</th><th class="num">Saved</th><th class="num">Net flow</th>
    <th class="num">Investable</th><th class="num">Net worth</th><th class="num">Net worth (today's $)</th></tr>
    ${years.map((y) => `
      <tr class="${y.retired ? "retired" : ""}">
        <td>${y.year}</td><td>${y.age}</td><td class="num">${money(y.income)}</td><td class="num">${money(y.taxes)}</td>
        <td class="num">${money(y.expenses)}</td>
        <td class="num" title="${esc(y.goal_names.join(", "))}">${y.goals ? money(y.goals) : "—"}</td>
        <td class="num">${y.debt_payments ? money(y.debt_payments) : "—"}</td>
        <td class="num">${y.contributions ? money(y.contributions) : "—"}</td>
        <td class="num ${y.shortfall ? "bad" : y.net_cash_flow < 0 ? "warn" : ""}">${money(y.net_cash_flow)}</td>
        <td class="num">${money(y.investable)}</td><td class="num">${money(y.net_worth)}</td>
        <td class="num">${money(y.net_worth_real)}</td>
      </tr>`).join("")}`;
}

function renderCashFlows(plan) {
  const ret = plan.retirement_age;
  const startText = (cf) => (cf.starts_at_retirement ? `Retirement (${ret})` : cf.start_age ?? "Now");
  const endText = (cf) => {
    if (cf.ends_at_retirement) return `Retirement (${ret - 1})`;
    if (cf.end_age != null) return cf.end_age;
    return cf.kind === "goal" ? "One-time" : "End of plan";
  };
  const table = $("#cf-table");
  table.innerHTML = plan.cash_flows.length
    ? `<tr><th>Name</th><th>Type</th><th class="num">Per year</th><th>Starts</th><th>Ends</th><th class="num">Real growth</th><th></th></tr>` +
      plan.cash_flows.map((cf) => `
        <tr><td>${esc(cf.name)}</td>
          <td><span class="tag">${FLOW_LABELS[cf.kind]}</span>${cf.kind === "income" && !cf.taxable ? ' <span class="tag">untaxed</span>' : ""}</td>
          <td class="num">${money(cf.amount)}</td><td>${startText(cf)}</td><td>${endText(cf)}</td>
          <td class="num">${cf.real_growth ? pct(cf.real_growth) : "—"}</td>
          <td><button class="link" data-act="edit" data-id="${cf.id}">Edit</button>
              <button class="link danger" data-act="delete" data-id="${cf.id}">Delete</button></td></tr>`).join("")
    : `<tr><td class="muted">Add your salary, living expenses, Social Security, and big goals like a house or college.</td></tr>`;
  table.onclick = guard(async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const cf = plan.cash_flows.find((c) => c.id === Number(btn.dataset.id));
    if (btn.dataset.act === "delete") {
      await api(`/api/cash-flows/${cf.id}`, { method: "DELETE" });
      await loadPlans();
    } else {
      openForm({
        title: `Edit ${cf.name}`,
        fields: flowFields,
        values: cf,
        onSubmit: async (v) => {
          await api(`/api/cash-flows/${cf.id}`, { method: "PATCH", body: v });
          await loadPlans();
        },
      });
    }
  });
}

$("#plan-select").addEventListener("change", guard(async (e) => {
  state.planId = Number(e.target.value);
  await renderPlan();
}));

$("#plan-new").addEventListener("click", () =>
  openForm({
    title: "New plan",
    fields: planFields,
    values: { name: state.plans.length ? "New scenario" : "My plan" },
    onSubmit: async (v) => {
      const plan = await api("/api/plans", { method: "POST", body: v });
      state.planId = plan.id;
      await loadPlans();
    },
  })
);

$("#plan-edit").addEventListener("click", () =>
  openForm({
    title: "Plan assumptions",
    fields: planFields,
    values: currentPlan(),
    onSubmit: async (v) => {
      await api(`/api/plans/${state.planId}`, { method: "PATCH", body: v });
      await loadPlans();
    },
  })
);

$("#plan-dup").addEventListener("click", guard(async () => {
  const copy = await api(`/api/plans/${state.planId}/duplicate`, { method: "POST" });
  state.planId = copy.id;
  await loadPlans();
  toast("Plan duplicated. Edit its assumptions to explore a scenario.");
}));

$("#plan-delete").addEventListener("click", guard(async () => {
  if (!confirm(`Delete plan "${currentPlan().name}"?`)) return;
  await api(`/api/plans/${state.planId}`, { method: "DELETE" });
  state.planId = null;
  await loadPlans();
}));

$("#cf-add").addEventListener("click", () =>
  openForm({
    title: "Add income, expense, or goal",
    fields: flowFields,
    onSubmit: async (v) => {
      await api(`/api/plans/${state.planId}/cash-flows`, { method: "POST", body: v });
      await loadPlans();
    },
  })
);

// ---------- compare ----------

async function loadCompare() {
  const plans = await api("/api/plans");
  const pick = $("#compare-pick");
  if (!plans.length) {
    pick.innerHTML = `<span class="muted">No plans yet.</span>`;
    $("#compare-table").innerHTML = "";
    drawChart("compare-chart", { type: "line", data: { datasets: [] } });
    return;
  }
  pick.innerHTML = plans.map((p, i) =>
    `<label class="inline"><input type="checkbox" value="${p.id}" ${i < 4 ? "checked" : ""}/> ${esc(p.name)}</label>`).join("");
  pick.onchange = guard(() => runCompare(plans));
  await runCompare(plans);
}

async function runCompare(plans) {
  const ids = [...document.querySelectorAll("#compare-pick input:checked")].map((i) => Number(i.value));
  const chosen = plans.filter((p) => ids.includes(p.id));
  const results = await Promise.all(chosen.map((p) => api(`/api/plans/${p.id}/projection?simulations=500`)));

  $("#compare-table").innerHTML = chosen.length
    ? `<tr><th>Plan</th><th class="num">Retire at</th><th class="num">Chance of success</th><th class="num">FI age</th>
        <th class="num">At retirement (today's $)</th><th class="num">Median at end</th></tr>` +
      chosen.map((p, i) => {
        const r = results[i];
        const atRet = r.years.find((y) => y.age === p.retirement_age);
        const rate = r.monte_carlo.success_rate;
        return `<tr><td>${esc(p.name)}</td><td class="num">${p.retirement_age}</td>
          <td class="num ${scoreClass(rate)}">${pct(rate, 0)}</td><td class="num">${r.fi_age ?? "—"}</td>
          <td class="num">${money(atRet?.investable_real)}</td><td class="num">${money(r.monte_carlo.bands.at(-1)?.p50)}</td></tr>`;
      }).join("")
    : "";

  drawChart("compare-chart", {
    type: "line",
    data: {
      datasets: chosen.map((p, i) => ({
        label: `${p.name} (median)`,
        data: results[i].monte_carlo.bands.map((b) => ({ x: b.age, y: b.p50 })),
        borderColor: PALETTE[i % PALETTE.length],
        pointRadius: 0,
        borderWidth: 2,
      })),
    },
    options: moneyChartOptions({ scales: { x: { type: "linear", title: { display: true, text: "Age" } } } }),
  });
}

// ---------- debt ----------

async function loadDebt() {
  const body = { extra_monthly: Number($("#debt-extra").value) || 0, strategy: $("#debt-strategy").value };
  const r = await api("/api/debt/payoff", { method: "POST", body });
  if (!r.debts.length) {
    $("#debt-cards").innerHTML = "";
    $("#debt-table").innerHTML = `<tr><td class="muted">No debts with a balance. Add credit cards or loans on the Accounts tab.</td></tr>`;
    drawChart("debt-chart", { type: "line", data: { datasets: [] } });
    return;
  }
  const duration = (m) => (m == null ? "Never at this payment" : `${Math.floor(m / 12)} yr ${m % 12} mo`);
  const alt = r.comparison;
  const diff = alt.total_interest - r.total_interest;
  $("#debt-cards").innerHTML = [
    card("Debt-free in", duration(r.months), "", r.paid_off ? "" : "bad"),
    card("Total interest", money(r.total_interest)),
    card("Monthly budget", money(r.monthly_budget), "Minimums + extra"),
    card(`vs. ${alt.strategy}`, diff >= 0 ? `Saves ${money(diff)}` : `Costs ${money(-diff)}`, duration(alt.months)),
  ].join("");
  $("#debt-table").innerHTML =
    `<tr><th>Debt</th><th class="num">Balance</th><th class="num">APR</th><th class="num">Interest paid</th><th>Paid off</th></tr>` +
    r.debts.map((d) => `<tr><td>${esc(d.name)}</td><td class="num">${money(d.starting_balance)}</td>
      <td class="num">${pct(d.apr, 2)}</td><td class="num">${money(d.interest_paid)}</td>
      <td>${d.paid_off_month ? duration(d.paid_off_month) : "—"}</td></tr>`).join("");
  drawChart("debt-chart", {
    type: "line",
    data: {
      labels: r.timeline.map((t) => t.month),
      datasets: [{ label: "Total debt", data: r.timeline.map((t) => t.total_balance), borderColor: PALETTE[3], pointRadius: 0, fill: true, backgroundColor: "rgba(214,69,69,0.1)" }],
    },
    options: moneyChartOptions({ scales: { x: { title: { display: true, text: "Month" } } } }),
  });
}

$("#debt-run").addEventListener("click", guard(loadDebt));

// ---------- init ----------

showTab(loaders[location.hash.slice(1)] ? location.hash.slice(1) : "dashboard");
