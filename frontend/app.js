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
const TAX_TYPE_LABELS = {
  wages: "Wages (salary, self-employment)",
  ordinary: "Other taxable (pension, rental, annuity)",
  social_security: "Social Security",
  tax_free: "Tax-free (gifts, inheritance)",
};
const CATEGORY_LABELS = {
  general: "General spending", housing: "Housing (rent, property tax, HOA)", home_maintenance: "Home maintenance",
  utilities: "Utilities", food: "Food & groceries", transportation: "Cars & transportation", healthcare: "Healthcare",
  insurance: "Insurance", travel: "Travel", hobbies: "Hobbies & entertainment", kids: "Kids", education: "Education",
  giving: "Giving", other: "Other",
};
const FILING_LABELS = { single: "Single", married_joint: "Married filing jointly" };
const TAX_MODE_LABELS = { progressive: "2026 federal brackets + payroll tax", flat: "Single flat rate" };
const PALETTE = [
  "#2f6fde", "#1f9d55", "#c98a00", "#d64545", "#7b4fd6", "#0f9bb5", "#e0752d", "#6b7385",
  "#b8418f", "#4a8f2a", "#8a6d3b", "#3d5a99", "#c4572b", "#2a9d8f",
];

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

async function api(path, { method = "GET", body } = {}, retried = false) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (res.status === 401 && data?.detail === "Sign in required" && !retried) {
    await signIn();
    return api(path, { method, body }, true);
  }
  if (!res.ok) throw new Error(formatError(data) || `${res.status} ${res.statusText}`);
  return data;
}

let signInPromise = null;
function signIn() {
  signInPromise ??= new Promise((resolve) => {
    const dialog = $("#login-dialog");
    $("#login-error").textContent = "";
    $("#login-password").value = "";
    $("#login-form").onsubmit = async (e) => {
      e.preventDefault();
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: $("#login-password").value, remember: $("#login-remember").checked }),
      });
      if (!res.ok) {
        $("#login-error").textContent = formatError(await res.json().catch(() => null)) || "Could not sign in";
        return;
      }
      dialog.close();
      signInPromise = null;
      resolve();
    };
    dialog.addEventListener("cancel", (e) => e.preventDefault(), { once: true });
    dialog.showModal();
  });
  return signInPromise;
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
      input.value = String(values[f.name] ?? f.default ?? Object.keys(f.options)[0]);
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
      else if (f.type === "number" || f.numeric) out[name] = input.value === "" ? null : Number(input.value);
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
  spending: loadSpending,
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
  const [nw, alloc, plans, sample] = await Promise.all([
    api("/api/net-worth"), api("/api/allocation"), api("/api/plans"), api("/api/sample-data"),
  ]);
  $("#welcome").hidden = !sample.empty;
  $("#sample-banner").hidden = !sample.loaded;
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

$("#sample-load").addEventListener("click", guard(async () => {
  await api("/api/sample-data", { method: "POST" });
  state.planId = null;
  toast("Loaded a sample household. Look around, then start fresh when you're ready.");
  await loadDashboard();
}));

$("#sample-clear").addEventListener("click", guard(async () => {
  if (!confirm("Remove the sample household, and anything you added alongside it, so you can enter your own numbers?")) return;
  await api("/api/sample-data", { method: "DELETE" });
  state.planId = null;
  toast("Sample data removed.");
  await loadDashboard();
}));

$("#welcome-accounts").addEventListener("click", () => showTab("accounts"));

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
  { name: "annual_contribution", label: "Yearly contribution", type: "number", default: 0, help: "Planned yearly savings into this account until its owner retires" },
  { name: "owner", label: "Owner", type: "select", options: { self: "You", spouse: "Spouse" }, help: "Contributions stop when this person retires" },
  { name: "cost_basis", label: "Cost basis", type: "number", help: "Taxable brokerage: what you paid in total. Blank = no gains" },
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
  await Promise.all([loadPlaid(), loadSecurity()]);
}

// ---------- security ----------

async function loadSecurity() {
  const s = await api("/api/auth/status");
  const keys = s.bank_links
    ? `Bank logins are encrypted, with the key kept in your ${esc(s.key_location)}.`
    : "Bank logins are encrypted when you connect an institution, with the key kept in your system keychain.";
  $("#security-status").innerHTML = (s.password_enabled
    ? "A password is required to open the app in a browser. "
    : "Anyone using this computer can open the app in a browser. Set a password to require signing in. ") +
    `${keys} The app only accepts connections from this computer. Turn on FileVault (System Settings →
    Privacy &amp; Security) so the database is encrypted on disk.`;
  $("#pw-set").textContent = s.password_enabled ? "Change password" : "Set password";
  $("#pw-remove").hidden = !s.password_enabled;
  $("#pw-signout").hidden = !s.password_enabled;
}

$("#pw-set").addEventListener("click", guard(async () => {
  const { password_enabled: enabled } = await api("/api/auth/status");
  openForm({
    title: enabled ? "Change password" : "Set a password",
    fields: [
      ...(enabled ? [{ name: "current_password", label: "Current password", type: "password", required: true, full: true }] : []),
      { name: "new_password", label: "New password (at least 8 characters)", type: "password", required: true, full: true },
      { name: "confirm", label: "Repeat new password", type: "password", required: true, full: true,
        help: "If you forget it, double-click scripts/reset-password.command (Mac) or reset-password.bat (Windows). Your data is not encrypted with it, so nothing is lost." },
    ],
    onSubmit: async (v) => {
      if (v.new_password !== v.confirm) throw new Error("The new passwords don't match");
      await api("/api/auth/password", { method: "PUT", body: { current_password: v.current_password, new_password: v.new_password } });
      toast(enabled ? "Password changed. Other browsers are signed out." : "Password set");
      await loadSecurity();
    },
  });
}));

$("#pw-remove").addEventListener("click", () =>
  openForm({
    title: "Remove password",
    fields: [{ name: "current_password", label: "Current password", type: "password", required: true, full: true }],
    onSubmit: async (v) => {
      await api("/api/auth/password", { method: "PUT", body: { current_password: v.current_password, new_password: null } });
      toast("Password removed");
      await loadSecurity();
    },
  })
);

$("#pw-signout").addEventListener("click", guard(async () => {
  await api("/api/auth/logout", { method: "POST" });
  location.reload();
}));

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

$("#restore").addEventListener("click", () => $("#restore-file").click());
$("#restore-file").addEventListener("change", guard(async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  let backup;
  try {
    backup = JSON.parse(await file.text());
  } catch {
    throw new Error("That file is not valid JSON.");
  }
  const counts = `${backup.accounts?.length ?? 0} account(s) and ${backup.plans?.length ?? 0} plan(s)`;
  const when = backup.exported_at ? ` from ${backup.exported_at.replace("T", " ")}` : "";
  if (!confirm(`Replace ALL accounts and plans here with the backup${when} (${counts})? This cannot be undone.`)) return;
  const r = await api("/api/restore", { method: "POST", body: { backup, replace: true } });
  toast(`Restored ${r.accounts} account(s) and ${r.plans} plan(s)`);
  await Promise.all([loadAccounts(), loadPlans()]);
}));

$("#import-csv").addEventListener("click", () => $("#csv-file").click());
$("#csv-file").addEventListener("change", guard(async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const r = await api("/api/import/balances", { method: "POST", body: { csv: await file.text() } });
  const box = $("#import-result");
  box.hidden = false;
  box.innerHTML =
    `Imported ${r.imported} balance(s)` +
    (r.created_accounts.length ? `; created ${r.created_accounts.map(esc).join(", ")}` : "") +
    (r.errors.length
      ? `. <span class="bad">${r.errors.length} row(s) skipped:</span><br>` +
        r.errors.slice(0, 10).map((err) => `Line ${err.line}: ${esc(err.message)}`).join("<br>")
      : ".");
  await loadAccounts();
}));
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

const STATE_LABELS = { "": "Not chosen: use a flat rate" };

const RETURN_MODEL_LABELS = {
  allocation: "Stocks & bonds, gliding to a retirement mix",
  simple: "Single return before and after retirement",
};

const planFields = [
  { name: "name", label: "Plan name", required: true, full: true },
  { name: "birth_year", label: "Birth year", type: "number", step: 1, required: true, default: new Date().getFullYear() - 35 },
  { name: "retirement_age", label: "Retirement age", type: "number", step: 1, default: 65 },
  { name: "life_expectancy", label: "Plan until age", type: "number", step: 1, default: 95 },
  { name: "inflation", label: "Inflation", type: "percent", default: 0.025 },
  { name: "return_model", label: "Investment returns", type: "select", options: RETURN_MODEL_LABELS, full: true },
  { name: "stock_allocation_now", label: "Stocks today", type: "percent", default: 0.9, help: "Rest is bonds; glides to the retirement mix" },
  { name: "stock_allocation_retired", label: "Stocks once retired", type: "percent", default: 0.6, help: "Reached when the first of you retires" },
  { name: "stock_return", label: "Stock return", type: "percent", default: 0.085, help: "Average yearly, before inflation" },
  { name: "bond_return", label: "Bond return", type: "percent", default: 0.045 },
  { name: "stock_volatility", label: "Stock volatility", type: "percent", default: 0.17, help: "Std. deviation per year" },
  { name: "bond_volatility", label: "Bond volatility", type: "percent", default: 0.06 },
  { name: "stock_bond_correlation", label: "Stock–bond correlation", type: "number", step: 0.05, default: 0.1, help: "−1 to 1" },
  { name: "expected_return", label: "Return before retirement", type: "percent", default: 0.07, help: "Single-return model only" },
  { name: "retirement_return", label: "Return in retirement", type: "percent", default: 0.05, help: "Single-return model only" },
  { name: "return_volatility", label: "Return volatility", type: "percent", default: 0.15, help: "Single-return model only" },
  { name: "cash_return", label: "Cash interest", type: "percent", default: 0.03 },
  { name: "withdrawal_rate", label: "Safe withdrawal rate", type: "percent", default: 0.04, help: "Used for the FI number" },
  { name: "guardrails", label: "Spending guardrails (Guyton-Klinger)", type: "checkbox", full: true,
    help: "Once retired, cut flexible spending after bad markets and raise it after good ones. Housing, utilities, insurance, healthcare, and kids stay fixed." },
  { name: "guardrail_band", label: "Guardrail width", type: "percent", default: 0.2, help: "How far the withdrawal rate may drift from its starting level" },
  { name: "guardrail_adjustment", label: "Adjustment size", type: "percent", default: 0.1, help: "Cut or raise per trigger" },
  { name: "guardrail_floor", label: "Lowest flexible spending", type: "percent", default: 0.7, help: "Share of planned flexible spending you'd accept" },
  { name: "filing_status", label: "Filing status", type: "select", options: FILING_LABELS },
  { name: "spouse_birth_year", label: "Spouse birth year", type: "number", step: 1, help: "Blank if planning alone" },
  { name: "spouse_retirement_age", label: "Spouse retires at age", type: "number", step: 1, help: "Spouse's age. Blank = same year as you" },
  { name: "spouse_life_expectancy", label: "Plan until spouse's age", type: "number", step: 1, default: 95, help: "The plan runs until the second death" },
  { name: "survivor_spending", label: "Spending after one spouse dies", type: "percent", default: 0.75, help: "Share of household spending that continues (kids and education excluded)" },
  { name: "tax_mode", label: "Tax model", type: "select", options: TAX_MODE_LABELS },
  { name: "state", label: "State of residence", type: "select", options: STATE_LABELS,
    help: "2026 brackets, deductions, and Social Security and retirement-income rules for that state" },
  { name: "state_tax_rate", label: "State income tax", type: "percent", default: 0, help: "Only when no state is chosen: flat rate on taxable income" },
  { name: "effective_tax_rate", label: "Flat tax rate", type: "percent", default: 0.15, help: "Only used by the flat model" },
];

const timingFields = (growthHelp) => [
  { name: "start_age", label: "Start age", type: "number", step: 1, help: "Blank = now" },
  { name: "starts_at_retirement", label: "Starts at retirement", type: "checkbox" },
  { name: "end_age", label: "End age", type: "number", step: 1, help: "Blank = end of plan" },
  { name: "ends_at_retirement", label: "Ends at retirement", type: "checkbox" },
  { name: "real_growth", label: "Growth above inflation", type: "percent", default: 0, help: growthHelp },
];

const FLOW_FORMS = {
  income: [
    { name: "name", label: "Name", required: true, full: true },
    { name: "amount", label: "Amount per year", type: "number", required: true, help: "Today's dollars, before tax" },
    { name: "tax_type", label: "Tax treatment", type: "select", options: TAX_TYPE_LABELS },
    ...timingFields("e.g. raises above inflation"),
  ],
  expense: [
    { name: "name", label: "Name", required: true, full: true },
    { name: "category", label: "Category", type: "select", options: CATEGORY_LABELS },
    { name: "amount", label: "Amount", type: "number", required: true, help: "Today's dollars, each time it occurs" },
    { name: "every_n_years", label: "Repeats every N years", type: "number", step: 1, default: 1, help: "1 = every year; 8 = a car every 8 years" },
    ...timingFields("e.g. healthcare rising faster than inflation"),
  ],
  goal: [
    { name: "name", label: "Name", required: true, full: true },
    { name: "amount", label: "Amount", type: "number", required: true, help: "Today's dollars" },
    { name: "start_age", label: "At age", type: "number", step: 1, required: true },
    { name: "end_age", label: "Repeat yearly until age", type: "number", step: 1, help: "Blank = one-time" },
    { name: "real_growth", label: "Growth above inflation", type: "percent", default: 0 },
  ],
};

const childFields = [
  { name: "name", label: "Name", required: true },
  { name: "birth_year", label: "Birth year", type: "number", step: 1, required: true, default: new Date().getFullYear() },
  { name: "cost_early", label: "Ages 0–5, per year", type: "number", default: 18000, help: "Include childcare" },
  { name: "cost_middle", label: "Ages 6–12, per year", type: "number", default: 15000 },
  { name: "cost_teen", label: "Ages 13–17, per year", type: "number", default: 18000 },
  { name: "college_cost", label: "College, per year", type: "number", default: 30000, help: "0 = none" },
  { name: "college_start_age", label: "College starts at age", type: "number", step: 1, default: 18 },
  { name: "college_years", label: "Years of college", type: "number", step: 1, default: 4 },
];

const ssFields = [
  { name: "ss_monthly_benefit", label: "Your monthly benefit at full retirement age", type: "number", default: 0, full: true, help: "From your statement at ssa.gov/myaccount, today's dollars" },
  { name: "ss_claim_age", label: "You claim at age", type: "number", step: 1, default: 67, help: "62–70" },
  { name: "spouse_ss_monthly_benefit", label: "Spouse's monthly benefit at FRA", type: "number", default: 0, help: "0 if no work history: a spousal benefit (up to half of yours) still applies" },
  { name: "spouse_ss_claim_age", label: "Spouse claims at age", type: "number", step: 1, default: 67, help: "Set your spouse's birth year under Assumptions" },
];

const healthFields = [
  { name: "pre_medicare_cost", label: "Before Medicare, per person per year", type: "number", default: 12000, help: "Premiums + out-of-pocket from retirement until 65; 0 if covered (e.g. retiree plan)" },
  { name: "medicare_cost", label: "On Medicare, per person per year", type: "number", default: 7000, help: "Part B, Part D, Medigap, out-of-pocket; IRMAA is added automatically" },
  { name: "health_cost_growth", label: "Growth above inflation", type: "percent", default: 0.02, help: "Healthcare costs historically outpace inflation" },
  { name: "aca_subsidies", label: "Apply ACA premium tax credits before Medicare", type: "checkbox", default: true, full: true,
    help: "Marketplace credits for household income up to 400% of the poverty line (2026 rules; the larger pandemic-era credits expired)" },
  { name: "aca_benchmark_premium", label: "Benchmark silver premium, per person per year", type: "number", default: 10000,
    help: "Second-lowest silver plan for your age and ZIP on healthcare.gov; capped at the cost above" },
];

const ROTH_LABELS = {
  "": "No conversions", 0.12: "Fill the 12% bracket", 0.22: "Fill the 22% bracket",
  0.24: "Fill the 24% bracket", 0.32: "Fill the 32% bracket",
};
const rothLabel = (rate) => ROTH_LABELS[rate ?? ""] ?? `Fill the ${pct(rate, 0)} bracket`;

const rothFields = [
  { name: "roth_conversion_rate", label: "Each year, convert enough to", type: "select", numeric: true, options: ROTH_LABELS, full: true },
  { name: "roth_start_age", label: "From age", type: "number", step: 1, help: "Blank = retirement" },
  { name: "roth_end_age", label: "Through age", type: "number", step: 1, help: "Blank = year before RMDs start" },
];

const shortLabel = (label) => label.split(" (")[0];

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
const spouseRetirementAge = (plan) =>
  plan.spouse_retirement_age ?? plan.retirement_age - (plan.spouse_birth_year - plan.birth_year);
const planEndAge = (plan) =>
  plan.spouse_birth_year
    ? Math.max(plan.life_expectancy, plan.spouse_life_expectancy + plan.spouse_birth_year - plan.birth_year)
    : plan.life_expectancy;

async function renderPlan() {
  const plan = currentPlan();
  renderCashFlows(plan);
  renderChildren(plan);
  if (state.ssPlanId !== plan.id) $("#ss-panel").hidden = true;
  if (state.rothPlanId !== plan.id) $("#roth-results").hidden = true;
  const proj = await api(`/api/plans/${plan.id}/projection?simulations=1000`);
  if (state.retirePlanId !== plan.id) $("#retire-results").hidden = true;
  renderSocialSecurity(plan, proj);
  renderRoth(plan, proj);
  renderHealth(plan, proj);
  renderHomes(plan, proj);
  renderSpendingChart(proj.years);
  const years = proj.years;
  const lastRetirement = plan.spouse_birth_year
    ? Math.max(plan.retirement_age, spouseRetirementAge(plan) + plan.spouse_birth_year - plan.birth_year)
    : plan.retirement_age;
  const atRetirement = years.find((y) => y.age === lastRetirement) ?? years[0];
  const rate = proj.monte_carlo?.success_rate ?? 0;

  $("#plan-cards").innerHTML = [
    card("Chance of success", pct(rate, 0), `${proj.monte_carlo.simulations} Monte Carlo runs`, scoreClass(rate)),
    ...(plan.guardrails ? [card("Guardrail cuts", `To ${pct(proj.monte_carlo.lowest_spending_p10, 0)}`,
      `Flexible spending in the worst 10% of markets (median low ${pct(proj.monte_carlo.lowest_spending_p50, 0)})`,
      proj.monte_carlo.lowest_spending_p10 <= plan.guardrail_floor + 1e-9 ? "warn" : "")] : []),
    card("FI number", money(proj.fi_number), `${pct(plan.withdrawal_rate)} of retirement spending`),
    card("FI age", proj.fi_age ?? "Not reached", "Expected path"),
    card(
      lastRetirement === plan.retirement_age ? `At retirement (${lastRetirement})` : `Both retired (your ${lastRetirement})`,
      money(atRetirement?.investable_real), "Investable, today's dollars"),
    card("Money lasts", proj.depletion_age ? `Until ${proj.depletion_age}` : `Past ${proj.end_age}`, "Expected path, your age", proj.depletion_age ? "bad" : "good"),
    card("Lifetime taxes", money(proj.lifetime_taxes_real), "Today's dollars, expected path"),
    card("Left at end, after tax", money(proj.after_tax_ending_real), "Net of taxes heirs would owe, today's dollars"),
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

  renderBacktest(proj.backtest);

  const hasSpouse = years.some((y) => y.spouse_age != null);
  const ageCell = (y) => {
    const fmt = (alive, a) => (alive ? a : `<span class="muted" title="Deceased in this plan">†</span>`);
    return hasSpouse ? `${fmt(y.self_alive, y.age)} / ${fmt(y.spouse_alive, y.spouse_age)}` : y.age;
  };
  $("#years-table").innerHTML = `
    <tr><th>Year</th><th>${hasSpouse ? "Ages (you / spouse)" : "Age"}</th><th class="num">Income</th><th class="num">Taxes</th><th class="num">Expenses</th>
    <th class="num">Goals</th><th class="num">Debt pmts</th><th class="num">Saved</th><th class="num">RMD</th><th class="num">Roth conv.</th><th class="num">Net flow</th><th class="num">Stocks</th><th class="num">Return</th>
    <th class="num">Investable</th><th class="num">Net worth</th><th class="num">Net worth (today's $)</th></tr>
    ${years.map((y) => `
      <tr class="${y.retired ? "retired" : ""}">
        <td>${y.year}</td><td>${ageCell(y)}</td><td class="num">${money(y.income)}</td>
        <td class="num" title="Federal ${money(y.tax_federal)} · State ${money(y.tax_state)} · Payroll ${money(y.tax_fica)} · Early-withdrawal penalty ${money(y.tax_penalty)} · Capital gains realized ${money(y.realized_gains)}">${money(y.taxes)}</td>
        <td class="num ${y.spending_adjustment < 0.999 ? "warn" : ""}" title="${[
          y.irmaa ? `Includes ${money(y.irmaa)} Medicare IRMAA surcharge` : "",
          y.aca_credit ? `After ${money(y.aca_credit)} ACA premium tax credit` : "",
          Math.abs(y.spending_adjustment - 1) > 0.001 ? `Guardrails: flexible spending at ${pct(y.spending_adjustment, 0)} of plan` : "",
        ].filter(Boolean).join(" · ")}">${money(y.expenses)}</td>
        <td class="num" title="${esc(y.goal_names.join(", "))}">${y.goals ? money(y.goals) : "—"}</td>
        <td class="num">${y.debt_payments ? money(y.debt_payments) : "—"}</td>
        <td class="num">${y.contributions ? money(y.contributions) : "—"}</td>
        <td class="num">${y.rmd ? money(y.rmd) : "—"}</td>
        <td class="num">${y.roth_conversion ? money(y.roth_conversion) : "—"}</td>
        <td class="num ${y.shortfall ? "bad" : y.net_cash_flow < 0 ? "warn" : ""}">${money(y.net_cash_flow)}</td>
        <td class="num">${y.stock_allocation == null ? "—" : pct(y.stock_allocation, 0)}</td>
        <td class="num">${pct(y.investment_return)}</td>
        <td class="num">${money(y.investable)}</td>
        <td class="num" title="${y.home_value ? `Includes ${money(y.home_equity)} home equity` : ""}">${money(y.net_worth)}</td>
        <td class="num">${money(y.net_worth_real)}</td>
      </tr>`).join("")}`;
}

function renderBacktest(bt) {
  $("#backtest-panel").hidden = !bt;
  if (!bt) return;
  const failed = bt.starts.filter((s) => s.depletion_age != null);
  $("#backtest-summary").innerHTML =
    `Your plan replayed through every ${bt.bands.length}-year stretch of actual US stock and 10-year Treasury returns ` +
    `(${bt.first_year}–${bt.last_year}, adjusted for inflation), using your stock/bond mix. ` +
    `<strong class="${scoreClass(bt.success_rate)}">${pct(bt.success_rate, 0)}</strong> of ${bt.simulations} starting years lasted. ` +
    (failed.length
      ? `Hardest start: ${bt.worst_start_year} (money ran out at ${failed.find((s) => s.start_year === bt.worst_start_year)?.depletion_age}).`
      : `Hardest start: ${bt.worst_start_year}.`) +
    ` Source: <a href="https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html" target="_blank" rel="noopener">Damodaran, NYU Stern</a>.`;
  drawChart("backtest-chart", {
    type: "bar",
    data: {
      labels: bt.starts.map((s) => s.start_year),
      datasets: [
        {
          label: "Left at end (today's dollars)",
          data: bt.starts.map((s) => s.ending_real),
          backgroundColor: PALETTE[0],
        },
        {
          type: "scatter",
          label: "Ran out",
          data: bt.starts.map((s) => (s.depletion_age != null ? 0 : null)),
          pointStyle: "crossRot", pointRadius: 6, borderColor: "#d64545", borderWidth: 2,
        },
      ],
    },
    options: moneyChartOptions({
      scales: { x: { title: { display: true, text: "If your plan had started in" } } },
      plugins: {
        legend: { display: false },
        tooltip: { filter: (c) => c.datasetIndex === 0, callbacks: { label: (c) => `${c.dataset.label}: ${money(c.parsed.y)}`, afterLabel: (ctx) => {
          const s = bt.starts[ctx.dataIndex];
          return s.depletion_age != null ? `Ran out at age ${s.depletion_age}` : "Lasted";
        } } },
      },
    }),
  });
}

const OWNER_LABELS = { joint: "Joint / household", self: "You", spouse: "Spouse" };

function openFlowForm(kind, values = {}) {
  const editing = values.id != null;
  const [nameField, ...rest] = FLOW_FORMS[kind];
  const ownerField = {
    name: "owner", label: "Whose", type: "select", options: OWNER_LABELS, default: kind === "income" ? "self" : "joint",
    help: "Ages and “at retirement” follow this person; personal items stop at their death",
  };
  openForm({
    title: editing ? `Edit ${values.name}` : `Add ${FLOW_LABELS[kind].toLowerCase()}`,
    fields: currentPlan().spouse_birth_year ? [nameField, ownerField, ...rest] : FLOW_FORMS[kind],
    values,
    onSubmit: async (v) => {
      if (editing) await api(`/api/cash-flows/${values.id}`, { method: "PATCH", body: v });
      else await api(`/api/plans/${state.planId}/cash-flows`, { method: "POST", body: { ...v, kind } });
      await loadPlans();
    },
  });
}

function flowActions(cf) {
  return `<td><button class="link" data-act="edit" data-id="${cf.id}">Edit</button>
    <button class="link danger" data-act="delete" data-id="${cf.id}">Delete</button></td>`;
}

function bindFlowTable(table, plan) {
  table.onclick = guard(async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const cf = plan.cash_flows.find((c) => c.id === Number(btn.dataset.id));
    if (btn.dataset.act === "delete") {
      await api(`/api/cash-flows/${cf.id}`, { method: "DELETE" });
      await loadPlans();
    } else {
      openFlowForm(cf.kind, cf);
    }
  });
}

function renderCashFlows(plan) {
  const currentAge = new Date().getFullYear() - plan.birth_year;
  const offset = plan.spouse_birth_year ? plan.spouse_birth_year - plan.birth_year : 0;
  const isSpouse = (cf) => plan.spouse_birth_year && cf.owner === "spouse";
  // Ages below are in the item owner's age; `shift` converts spouse ages to yours.
  const shift = (cf) => (isSpouse(cf) ? offset : 0);
  const ret = (cf) => (isSpouse(cf) ? spouseRetirementAge(plan) : plan.retirement_age);
  const startAge = (cf) => (cf.starts_at_retirement ? ret(cf) : cf.start_age ?? currentAge - shift(cf)) + shift(cf);
  const endAge = (cf) => {
    if (cf.ends_at_retirement) return ret(cf) - 1 + shift(cf);
    if (cf.end_age != null) return cf.end_age + shift(cf);
    return cf.kind === "goal" ? startAge(cf) : planEndAge(plan);
  };
  const startText = (cf) => (cf.starts_at_retirement ? `Retirement (${ret(cf)})` : cf.start_age ?? "Now");
  const endText = (cf) => {
    if (cf.ends_at_retirement) return `Retirement (${ret(cf) - 1})`;
    if (cf.end_age != null) return cf.end_age;
    return cf.kind === "goal" ? "One-time" : "End of plan";
  };
  const ownerTag = (cf) =>
    plan.spouse_birth_year && cf.owner !== "joint"
      ? ` <span class="tag" title="Ages are ${cf.owner === "spouse" ? "your spouse's" : "yours"}">${cf.owner === "spouse" ? "Spouse" : "You"}</span>`
      : "";

  const incomeTable = $("#income-table");
  const incomes = plan.cash_flows.filter((cf) => cf.kind !== "expense");
  incomeTable.innerHTML = incomes.length
    ? `<tr><th>Name</th><th>Type</th><th class="num">Amount</th><th>Starts</th><th>Ends</th><th class="num">Real growth</th><th></th></tr>` +
      incomes.map((cf) => `
        <tr><td>${esc(cf.name)}${ownerTag(cf)}</td>
          <td><span class="tag">${cf.kind === "goal" ? "Goal" : shortLabel(TAX_TYPE_LABELS[cf.tax_type])}</span></td>
          <td class="num">${money(cf.amount)}</td><td>${startText(cf)}</td><td>${endText(cf)}</td>
          <td class="num">${cf.real_growth ? pct(cf.real_growth) : "—"}</td>${flowActions(cf)}</tr>`).join("")
    : `<tr><td class="muted">Add your salary, a pension, or rental income, and big goals like a house down payment.</td></tr>`;
  bindFlowTable(incomeTable, plan);

  const spendTable = $("#spending-table");
  const expenses = plan.cash_flows.filter((cf) => cf.kind === "expense");
  const perYearNow = expenses
    .filter((cf) => startAge(cf) <= currentAge && currentAge <= endAge(cf))
    .reduce((sum, cf) => sum + cf.amount / (cf.every_n_years || 1), 0);
  $("#spending-total").textContent = expenses.length ? `About ${money(perYearNow)}/yr today (repeating items averaged)` : "";
  spendTable.innerHTML = expenses.length
    ? `<tr><th>Name</th><th>Category</th><th class="num">Amount</th><th>How often</th><th>Starts</th><th>Ends</th><th class="num">Real growth</th><th></th></tr>` +
      expenses.map((cf) => `
        <tr><td>${esc(cf.name)}${ownerTag(cf)}</td><td><span class="tag">${shortLabel(CATEGORY_LABELS[cf.category])}</span></td>
          <td class="num">${money(cf.amount)}</td>
          <td>${cf.every_n_years > 1 ? `Every ${cf.every_n_years} yrs` : "Yearly"}</td>
          <td>${startText(cf)}</td><td>${endText(cf)}</td>
          <td class="num">${cf.real_growth ? pct(cf.real_growth) : "—"}</td>${flowActions(cf)}</tr>`).join("")
    : `<tr><td class="muted">No spending yet. Start with General spending, or pick categories above.</td></tr>`;
  bindFlowTable(spendTable, plan);
}

const CHIP_DEFAULTS = {
  general: {}, transportation: { name: "Car replacement", every_n_years: 8 },
  home_maintenance: { name: "Home maintenance" }, healthcare: { name: "Healthcare", real_growth: 0.02 },
};

$("#spending-chips").innerHTML = Object.entries(CATEGORY_LABELS)
  .filter(([key]) => key !== "kids" && key !== "education")
  .map(([key, label]) => `<button data-cat="${key}">+ ${esc(shortLabel(label))}</button>`).join("");
$("#spending-chips").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-cat]");
  if (!btn) return;
  const cat = btn.dataset.cat;
  openFlowForm("expense", { category: cat, name: shortLabel(CATEGORY_LABELS[cat]), ...CHIP_DEFAULTS[cat] });
});

function renderChildren(plan) {
  const table = $("#children-table");
  const year = new Date().getFullYear();
  table.innerHTML = plan.children.length
    ? `<tr><th>Name</th><th>Age</th><th class="num">0–5</th><th class="num">6–12</th><th class="num">13–17</th><th>College</th><th></th></tr>` +
      plan.children.map((c) => `
        <tr><td>${esc(c.name)}</td><td>${c.birth_year > year ? `Born ${c.birth_year}` : year - c.birth_year}</td>
          <td class="num">${money(c.cost_early)}</td><td class="num">${money(c.cost_middle)}</td><td class="num">${money(c.cost_teen)}</td>
          <td>${c.college_cost && c.college_years ? `${money(c.college_cost)} × ${c.college_years} yrs` : "—"}</td>
          <td><button class="link" data-act="edit" data-id="${c.id}">Edit</button>
              <button class="link danger" data-act="delete" data-id="${c.id}">Delete</button></td></tr>`).join("")
    : `<tr><td class="muted">No kids in this plan.</td></tr>`;
  table.onclick = guard(async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const child = plan.children.find((c) => c.id === Number(btn.dataset.id));
    if (btn.dataset.act === "delete") {
      await api(`/api/children/${child.id}`, { method: "DELETE" });
      await loadPlans();
      return;
    }
    openForm({
      title: `Edit ${child.name}`,
      fields: childFields,
      values: child,
      onSubmit: async (v) => {
        await api(`/api/children/${child.id}`, { method: "PATCH", body: v });
        await loadPlans();
      },
    });
  });
}

const homeFields = (accounts) => {
  const pick = (liability) => ({
    "": "Not linked",
    ...Object.fromEntries(accounts.filter((a) => a.is_liability === liability).map((a) => [a.id, a.name])),
  });
  return [
    { name: "name", label: "Name", required: true, full: true },
    { name: "purchase_age", label: "Buy at your age", type: "number", step: 1, help: "Blank = you own it now" },
    { name: "value", label: "Value or price (today's $)", type: "number", default: 0, help: "Owned now: what it's worth. Buying later: the price today" },
    { name: "property_account_id", label: "Linked property account", type: "select", numeric: true, options: pick(false), help: "Owned now: uses its balance, and it isn't counted twice" },
    { name: "mortgage_account_id", label: "Linked mortgage account", type: "select", numeric: true, options: pick(true), help: "Owned now: uses its balance, rate, and payment" },
    { name: "cost_basis", label: "Paid plus improvements", type: "number", help: "For tax on a sale. Blank = no gain" },
    { name: "mortgage_balance", label: "Mortgage balance", type: "number", default: 0, help: "Owned now, if not linked" },
    { name: "mortgage_payment", label: "Monthly payment (principal + interest)", type: "number", default: 0, help: "Owned now, if not linked" },
    { name: "mortgage_rate", label: "Mortgage rate", type: "percent", default: 0.065 },
    { name: "mortgage_years", label: "Mortgage term (years)", type: "number", step: 1, default: 30, help: "Buying later" },
    { name: "down_payment", label: "Down payment", type: "percent", default: 0.2, help: "Buying later; comes from savings" },
    { name: "closing_costs", label: "Closing costs", type: "percent", default: 0.03, help: "Buying later" },
    { name: "appreciation", label: "Growth above inflation", type: "percent", default: 0, help: "US homes have averaged roughly 0–1% a year" },
    { name: "carrying_costs", label: "Property tax, insurance, upkeep", type: "percent", default: 0, help: "% of value per year, e.g. 2%. Leave 0 if they're in Spending" },
    { name: "sale_age", label: "Sell at your age", type: "number", step: 1, help: "Blank = keep it. Downsize: sell one home and buy another the same year" },
    { name: "selling_costs", label: "Selling costs", type: "percent", default: 0.06 },
  ];
};

const homeBody = (v) => ({
  ...v,
  value: v.value ?? 0,
  mortgage_balance: v.mortgage_balance ?? 0,
  mortgage_payment: v.mortgage_payment ?? 0,
});

async function openHomeForm(home) {
  const accounts = await api("/api/accounts?include_archived=true");
  openForm({
    title: home ? `Edit ${home.name}` : "Add home",
    fields: homeFields(accounts),
    values: home ?? {},
    onSubmit: async (v) => {
      if (home) await api(`/api/homes/${home.id}`, { method: "PATCH", body: homeBody(v) });
      else await api(`/api/plans/${state.planId}/homes`, { method: "POST", body: homeBody(v) });
      await loadPlans();
    },
  });
}

function renderHomes(plan, proj) {
  const table = $("#homes-table");
  const atRetirement = proj.years.find((y) => y.retired) ?? proj.years.at(-1);
  const deflate = (y) => (1 + plan.inflation) ** (y.age - proj.years[0].age + 1);
  table.innerHTML = plan.homes.length
    ? `<tr><th>Home</th><th>When</th><th class="num">Value</th><th class="num">Mortgage</th><th>Sale</th><th></th></tr>` +
      plan.homes.map((h) => `
        <tr><td>${esc(h.name)}</td>
          <td>${h.purchase_age == null ? "Owned now" : `Buy at ${h.purchase_age}`}</td>
          <td class="num">${h.property_account_id ? "Linked account" : money(h.value)}</td>
          <td class="num">${h.mortgage_account_id ? "Linked account"
            : h.purchase_age != null ? (h.down_payment >= 1 ? "Paid in cash" : `${pct(1 - h.down_payment, 0)} loan at ${pct(h.mortgage_rate, 2)}`)
            : h.mortgage_balance ? money(h.mortgage_balance) : "—"}</td>
          <td>${h.sale_age == null ? "Keep" : `Sell at ${h.sale_age}`}</td>
          <td><button class="link" data-act="edit" data-id="${h.id}">Edit</button>
              <button class="link danger" data-act="delete" data-id="${h.id}">Delete</button></td></tr>`).join("")
    : `<tr><td class="muted">No homes in this plan. Property accounts still count toward net worth.</td></tr>`;
  $("#homes-summary").textContent = plan.homes.length && atRetirement
    ? `Home equity at ${atRetirement.age}: ${money(atRetirement.home_equity / deflate(atRetirement))} in today's dollars.`
    : "";
  table.onclick = guard(async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const home = plan.homes.find((h) => h.id === Number(btn.dataset.id));
    if (btn.dataset.act === "delete") {
      await api(`/api/homes/${home.id}`, { method: "DELETE" });
      await loadPlans();
      return;
    }
    await openHomeForm(home);
  });
}

$("#home-add").addEventListener("click", guard(() => openHomeForm(null)));

$("#child-add").addEventListener("click", () =>
  openForm({
    title: "Add child",
    fields: childFields,
    onSubmit: async (v) => {
      await api(`/api/plans/${state.planId}/children`, { method: "POST", body: v });
      await loadPlans();
    },
  })
);

function renderSocialSecurity(plan, proj) {
  $("#ss-compare").disabled = !plan.ss_monthly_benefit;
  const box = $("#ss-summary");
  if (!proj.social_security.length) {
    box.innerHTML = `<p class="muted">Not set. Find your monthly benefit at full retirement age on your
      <a href="https://www.ssa.gov/myaccount/" target="_blank" rel="noopener">ssa.gov statement</a>, then click Edit.</p>`;
    return;
  }
  box.innerHTML = `<table>${proj.social_security.map((s) => `
    <tr><td>${esc(s.name)}</td><td class="num">${money(s.annual / 12)}/mo</td><td>from your age ${s.start_age}</td></tr>`).join("")}
    </table><p class="muted">Today's dollars, adjusted for claiming age. Benefits rise with inflation (COLA).</p>`;
}

$("#ss-edit").addEventListener("click", () =>
  openForm({
    title: "Social Security",
    fields: ssFields,
    values: currentPlan(),
    onSubmit: async (v) => {
      await api(`/api/plans/${state.planId}`, { method: "PATCH", body: v });
      await loadPlans();
    },
  })
);

$("#ss-compare").addEventListener("click", guard(async () => {
  const plan = currentPlan();
  const panel = $("#ss-panel");
  panel.hidden = false;
  state.ssPlanId = plan.id;
  $("#ss-table").innerHTML = `<tr><td class="muted">Running the plan for each claiming age…</td></tr>`;
  const r = await api(`/api/plans/${plan.id}/social-security`);
  const fra = Number.isInteger(r.full_retirement_age) ? r.full_retirement_age : r.full_retirement_age.toFixed(1);
  $("#ss-note").textContent = `Full retirement age: ${fra}. Each row reruns your whole plan with the same simulated markets, so differences come only from the claiming age.`;
  $("#ss-table").innerHTML =
    `<tr><th>Claim at</th><th class="num">Monthly benefit</th><th class="num">Total through age ${plan.life_expectancy}</th>
     <th class="num">Chance of success</th><th class="num">Median left at end</th><th></th></tr>` +
    r.options.map((o) => `
      <tr class="${o.claim_age === r.best_claim_age ? "best" : ""}">
        <td>${o.claim_age}${o.claim_age === r.best_claim_age ? ' <span class="tag linked">best</span>' : ""}</td>
        <td class="num">${money(o.monthly_benefit)}</td><td class="num">${money(o.lifetime_benefits)}</td>
        <td class="num ${scoreClass(o.success_rate)}">${pct(o.success_rate, 0)}</td>
        <td class="num">${money(o.median_ending_real)}</td>
        <td>${o.claim_age === r.current_claim_age ? '<span class="tag">current</span>'
          : `<button class="link" data-age="${o.claim_age}">Use this age</button>`}</td>
      </tr>`).join("");
  $("#ss-table").onclick = guard(async (e) => {
    const btn = e.target.closest("button[data-age]");
    if (!btn) return;
    await api(`/api/plans/${plan.id}`, { method: "PATCH", body: { ss_claim_age: Number(btn.dataset.age) } });
    await loadPlans();
    $("#ss-compare").click();
  });
}));

function renderRoth(plan, proj) {
  const converted = proj.years.reduce((sum, y) => sum + y.roth_conversion, 0);
  const box = $("#roth-summary");
  $("#roth-explore").disabled = plan.tax_mode === "flat";
  if (plan.tax_mode === "flat") {
    box.innerHTML = `<p class="warn">Roth conversions need the bracket tax model (Assumptions → Tax model).</p>`;
    return;
  }
  box.innerHTML = plan.roth_conversion_rate == null
    ? `<p>Current strategy: <strong>No conversions</strong>.</p>`
    : `<p>Current strategy: <strong>${rothLabel(plan.roth_conversion_rate)}</strong> each year
        ${plan.roth_start_age != null ? `from ${plan.roth_start_age}` : "from retirement"}
        ${plan.roth_end_age != null ? `through ${plan.roth_end_age}` : "until RMDs start"},
        converting ${money(converted)} in total (expected path, nominal).</p>`;
}

$("#roth-edit").addEventListener("click", () =>
  openForm({
    title: "Roth conversions",
    fields: rothFields,
    values: currentPlan(),
    onSubmit: async (v) => {
      await api(`/api/plans/${state.planId}`, { method: "PATCH", body: v });
      await loadPlans();
    },
  })
);

$("#roth-explore").addEventListener("click", guard(async () => {
  const plan = currentPlan();
  state.rothPlanId = plan.id;
  $("#roth-results").hidden = false;
  $("#roth-table").innerHTML = `<tr><td class="muted">Running the plan for each strategy…</td></tr>`;
  const r = await api(`/api/plans/${plan.id}/roth-conversions`);
  $("#roth-note").textContent =
    `Conversions run from age ${r.window[0]} through ${r.window[1]} on ${money(r.tax_deferred_balance)} of 401k/IRA money. ` +
    `"After-tax at end" counts 401k/IRA money at ${pct(1 - r.heir_tax_rate, 0)} of face value (taxes your heirs would owe) ` +
    `and taxes unrealized brokerage gains at ${pct(r.embedded_gains_rate, 0)}, so strategies compare fairly.`;
  $("#roth-table").innerHTML =
    `<tr><th>Strategy</th><th class="num">Converted</th><th class="num">Lifetime taxes</th>
     <th class="num">After-tax at end</th><th class="num">Chance of success</th><th></th></tr>` +
    r.options.map((o) => `
      <tr class="${o.rate === r.best_rate ? "best" : ""}">
        <td>${rothLabel(o.rate)}${o.rate === r.best_rate ? ' <span class="tag linked">best</span>' : ""}</td>
        <td class="num">${money(o.total_converted_real)}</td><td class="num">${money(o.lifetime_taxes_real)}</td>
        <td class="num">${money(o.after_tax_ending_real)}</td>
        <td class="num ${scoreClass(o.success_rate)}">${pct(o.success_rate, 0)}</td>
        <td>${o.rate === r.current_rate ? '<span class="tag">current</span>'
          : `<button class="link" data-rate="${o.rate ?? ""}">Use this</button>`}</td>
      </tr>`).join("") +
    `<tr><td colspan="6" class="muted">All amounts in today's dollars.</td></tr>`;
  $("#roth-table").onclick = guard(async (e) => {
    const btn = e.target.closest("button[data-rate]");
    if (!btn) return;
    const rate = btn.dataset.rate === "" ? null : Number(btn.dataset.rate);
    await api(`/api/plans/${plan.id}`, { method: "PATCH", body: { roth_conversion_rate: rate } });
    await loadPlans();
    $("#roth-explore").click();
  });
}));

function renderHealth(plan, proj) {
  const years = proj.years;
  const real = (y, v) => v / (1 + plan.inflation) ** (y.age - years[0].age);
  const total = years.reduce((s, y) => s + (y.expenses_by_category_real.healthcare ?? 0), 0);
  const irmaa = years.reduce((s, y) => s + real(y, y.irmaa), 0);
  const irmaaYears = years.filter((y) => y.irmaa > 0).length;
  const aca = years.reduce((s, y) => s + real(y, y.aca_credit), 0);
  const acaYears = years.filter((y) => y.aca_credit > 0).length;
  const people = plan.spouse_birth_year ? "each of you" : "you";
  $("#health-summary").innerHTML = `
    <table>
      <tr><td>Before Medicare</td><td class="num">${money(plan.pre_medicare_cost)}/yr for ${people}</td></tr>
      <tr><td>On Medicare</td><td class="num">${money(plan.medicare_cost)}/yr for ${people}</td></tr>
      <tr><td>Growth above inflation</td><td class="num">${pct(plan.health_cost_growth)}</td></tr>
      <tr><td>ACA premium credits</td><td class="num ${aca ? "good" : ""}">${!plan.aca_subsidies ? "Off" : aca ? `−${money(aca)} over ${acaYears} yrs` : "None (income too high or no gap before 65)"}</td></tr>
      <tr><td>IRMAA surcharges</td><td class="num ${irmaa ? "warn" : ""}">${irmaa ? `${money(irmaa)} over ${irmaaYears} yrs` : "None"}</td></tr>
      <tr class="subtotal"><td>Lifetime healthcare</td><td class="num">${money(total)}</td></tr>
    </table>
    <p class="muted">Today's dollars, expected path. Lifetime total includes any Healthcare spending items.</p>`;
}

$("#health-edit").addEventListener("click", () =>
  openForm({
    title: "Healthcare in retirement",
    fields: healthFields,
    values: currentPlan(),
    onSubmit: async (v) => {
      await api(`/api/plans/${state.planId}`, { method: "PATCH", body: v });
      await loadPlans();
    },
  })
);

$("#retire-explore").addEventListener("click", guard(async () => {
  const plan = currentPlan();
  state.retirePlanId = plan.id;
  $("#retire-results").hidden = false;
  $("#retire-note").textContent = "";
  $("#retire-table").innerHTML = `<tr><td class="muted">Running the plan for each retirement age…</td></tr>`;
  const r = await api(`/api/plans/${plan.id}/retirement-ages`);
  const first = r.options[0]?.retirement_age;
  $("#retire-note").innerHTML = r.earliest_age == null
    ? `<span class="bad">No age in this range reaches a ${pct(r.target, 0)} chance of success.</span>`
    : `Earliest age with at least a ${pct(r.target, 0)} chance of success: <strong>${r.earliest_age}${r.earliest_age === first && first > new Date().getFullYear() - plan.birth_year ? " or earlier" : ""}</strong>.`;
  $("#retire-table").innerHTML =
    `<tr><th>Retire at</th><th class="num">Investable then</th><th class="num">Chance of success</th>
     <th class="num">After-tax at end</th><th></th></tr>` +
    r.options.map((o) => `
      <tr class="${o.retirement_age === r.earliest_age ? "best" : ""}">
        <td>${o.retirement_age}</td>
        <td class="num">${money(o.investable_at_retirement_real)}</td>
        <td class="num ${scoreClass(o.success_rate)}">${pct(o.success_rate, 0)}</td>
        <td class="num">${money(o.after_tax_ending_real)}</td>
        <td>${o.retirement_age === r.current_retirement_age ? '<span class="tag">current</span>'
          : `<button class="link" data-age="${o.retirement_age}">Use this</button>`}</td>
      </tr>`).join("") +
    `<tr><td colspan="5" class="muted">Today's dollars.</td></tr>`;
  $("#retire-table").onclick = guard(async (e) => {
    const btn = e.target.closest("button[data-age]");
    if (!btn) return;
    await api(`/api/plans/${plan.id}`, { method: "PATCH", body: { retirement_age: Number(btn.dataset.age) } });
    await loadPlans();
    $("#retire-explore").click();
  });
}));

function renderSpendingChart(years) {
  const cats = Object.keys(CATEGORY_LABELS).filter((c) => years.some((y) => y.expenses_by_category_real[c]));
  drawChart("spending-chart", {
    type: "bar",
    data: {
      labels: years.map((y) => y.age),
      datasets: cats.map((c) => ({
        label: shortLabel(CATEGORY_LABELS[c]),
        data: years.map((y) => y.expenses_by_category_real[c] || 0),
        backgroundColor: PALETTE[Object.keys(CATEGORY_LABELS).indexOf(c) % PALETTE.length],
        stack: "spend",
      })),
    },
    options: moneyChartOptions({
      scales: { x: { stacked: true, title: { display: true, text: "Age" } }, y: { stacked: true, ticks: { callback: (v) => compact(v) } } },
    }),
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

$("#income-add").addEventListener("click", () => openFlowForm("income", { tax_type: "wages", ends_at_retirement: true }));
$("#goal-add").addEventListener("click", () => openFlowForm("goal"));

// ---------- spending ----------

const EXCLUDED_LABELS = {
  income: "Income", transfer: "Transfer between accounts", debt_payment: "Debt payment", taxes: "Taxes", ignore: "Ignore",
};
const TXN_CATEGORY_LABELS = {
  ...Object.fromEntries(Object.entries(CATEGORY_LABELS).filter(([c]) => c !== "general")),
  ...EXCLUDED_LABELS,
};

async function loadSpending() {
  const plans = await api("/api/plans");
  const pick = $("#spend-plan");
  const chosen = pick.value || state.planId || plans[0]?.id || "";
  pick.innerHTML = `<option value="">No plan</option>` +
    plans.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  pick.value = String(chosen);
  const filter = $("#txn-category");
  if (!filter.options.length) {
    filter.innerHTML = `<option value="">All categories</option>` +
      Object.entries(TXN_CATEGORY_LABELS).map(([k, v]) => `<option value="${k}">${esc(shortLabel(v))}</option>`).join("");
  }
  await Promise.all([renderSpendingSummary(), renderTransactions()]);
}

async function renderSpendingSummary() {
  const planId = $("#spend-plan").value;
  const s = await api(`/api/spending/summary?months=${$("#spend-months").value}${planId ? `&plan_id=${planId}` : ""}`);
  const hasPlan = s.planned_annual != null;
  if (!s.transaction_count) {
    $("#spend-cards").innerHTML = "";
    $("#spend-table").innerHTML = `<tr><td class="muted">No transactions in this period. Link a bank on the Accounts tab
      and sync, or import a CSV export from your bank.</td></tr>`;
    $("#spend-note").textContent = "";
    drawChart("spend-chart", { type: "bar", data: { datasets: [] } });
    return;
  }
  const diff = hasPlan ? s.actual_annual - s.planned_annual : null;
  const period = s.partial ? `${s.start} to ${s.end} (this month so far)` : `${s.start} to ${s.end}`;
  $("#spend-cards").innerHTML = [
    card("Actual spending", `${money(s.actual_annual)}/yr`, `${money(s.actual_annual / 12)}/mo · ${period}`),
    hasPlan ? card("Plan this year", `${money(s.planned_annual)}/yr`, "Spending items, kids, healthcare, home costs") : "",
    hasPlan ? card(diff > 0 ? "Over plan" : "Under plan", `${money(Math.abs(diff))}/yr`,
      `${pct(Math.abs(diff) / (s.planned_annual || 1), 0)} ${diff > 0 ? "more" : "less"} than planned`,
      diff > 0.05 * s.planned_annual ? "bad" : "good") : "",
    card("Transactions", s.transaction_count.toLocaleString(), `${+s.months.toFixed(1)} month(s) of data`),
  ].join("");

  const rows = [...s.categories].sort((a, b) => b.actual_annual - a.actual_annual || (b.planned_annual ?? 0) - (a.planned_annual ?? 0));
  $("#spend-table").innerHTML =
    `<tr><th>Category</th><th class="num">Actual per year</th>${hasPlan ? `<th class="num">Plan per year</th><th class="num">Difference</th>` : ""}</tr>` +
    rows.map((c) => {
      const d = hasPlan ? c.actual_annual - c.planned_annual : 0;
      return `<tr><td>${esc(shortLabel(CATEGORY_LABELS[c.category] ?? c.category))}</td>
        <td class="num">${c.actual_annual ? money(c.actual_annual) : "—"}</td>
        ${hasPlan ? `<td class="num">${c.planned_annual ? money(c.planned_annual) : "—"}</td>
          <td class="num ${d > 0 ? "bad" : "good"}">${d > 0 ? "+" : d < 0 ? "−" : ""}${money(Math.abs(d))}</td>` : ""}</tr>`;
    }).join("") +
    `<tr><th>Total</th><th class="num">${money(s.actual_annual)}</th>${hasPlan
      ? `<th class="num">${money(s.planned_annual)}</th><th class="num ${diff > 0 ? "bad" : "good"}">${diff > 0 ? "+" : "−"}${money(Math.abs(diff))}</th>` : ""}</tr>`;

  const excluded = Object.entries(s.excluded).map(([c, v]) => `${EXCLUDED_LABELS[c]} ${money(Math.abs(v))}`);
  const general = s.categories.some((c) => c.category === "general");
  $("#spend-note").textContent = [
    general ? "Your plan uses one General spending item, so compare the totals rather than each category." : "",
    excluded.length ? `Left out over this period: ${excluded.join(", ")}.` : "",
    s.top_merchants.length ? `Biggest merchants: ${s.top_merchants.slice(0, 5).map((m) => `${m.name} ${money(m.total)}`).join(", ")}.` : "",
  ].filter(Boolean).join(" ");

  const cats = Object.keys(CATEGORY_LABELS).filter((c) => s.monthly.some((m) => m.by_category[c]));
  drawChart("spend-chart", {
    type: "bar",
    data: {
      labels: s.monthly.map((m) => m.month),
      datasets: [
        ...cats.map((c) => ({
          label: shortLabel(CATEGORY_LABELS[c]),
          data: s.monthly.map((m) => m.by_category[c] || 0),
          backgroundColor: PALETTE[Object.keys(CATEGORY_LABELS).indexOf(c) % PALETTE.length],
          stack: "spend",
        })),
        ...(hasPlan ? [{
          type: "line", label: "Plan per month", data: s.monthly.map(() => s.planned_annual / 12),
          borderColor: "#111", borderDash: [6, 4], pointRadius: 0, borderWidth: 1.5,
        }] : []),
      ],
    },
    options: moneyChartOptions({ scales: { x: { stacked: true }, y: { stacked: true, ticks: { callback: (v) => compact(v) } } } }),
  });
}

async function renderTransactions() {
  const params = new URLSearchParams({ limit: "300" });
  if ($("#txn-category").value) params.set("category", $("#txn-category").value);
  if ($("#txn-search").value.trim()) params.set("q", $("#txn-search").value.trim());
  const [txns, rules] = await Promise.all([api(`/api/transactions?${params}`), api("/api/spending/rules")]);
  const options = Object.entries(TXN_CATEGORY_LABELS).map(([k, v]) => `<option value="${k}">${esc(shortLabel(v))}</option>`).join("");
  const table = $("#txn-table");
  table.innerHTML = txns.length
    ? `<tr><th>Date</th><th>Description</th><th>Account</th><th class="num">Amount</th><th>Category</th></tr>` +
      txns.map((t) => `<tr>
        <td>${t.date}${t.pending ? ` <span class="muted">pending</span>` : ""}</td>
        <td>${esc(t.merchant || t.description)}${t.merchant && t.merchant !== t.description ? `<br><span class="muted">${esc(t.description)}</span>` : ""}</td>
        <td>${esc(t.account ?? "—")}</td>
        <td class="num ${t.amount < 0 ? "good" : ""}">${t.amount < 0 ? "+" : ""}${money(Math.abs(t.amount))}</td>
        <td><select data-id="${t.id}">${options}</select></td></tr>`).join("") +
      (txns.length >= 300 ? `<tr><td colspan="5" class="muted">Showing the latest 300. Search or filter to find others.</td></tr>` : "")
    : `<tr><td class="muted">No transactions match.</td></tr>`;
  table.querySelectorAll("select").forEach((sel, i) => {
    sel.value = txns[i].category;
    sel.onchange = guard(async () => {
      const r = await api(`/api/transactions/${sel.dataset.id}`, {
        method: "PATCH", body: { category: sel.value, remember: $("#txn-remember").checked },
      });
      if (r.updated > 1) toast(`Updated ${r.updated} transactions from this merchant`);
      await Promise.all([renderSpendingSummary(), r.updated > 1 ? renderTransactions() : null]);
    });
  });

  const list = $("#rules-list");
  list.innerHTML = rules.length
    ? `Merchant rules: ` + rules.map((r) =>
        `<span class="tag">${esc(r.match)} → ${esc(shortLabel(TXN_CATEGORY_LABELS[r.category] ?? r.category))}
          <button class="link" data-rule="${r.id}" title="Forget this rule">×</button></span>`).join(" ")
    : "";
  list.querySelectorAll("[data-rule]").forEach((b) => (b.onclick = guard(async () => {
    await api(`/api/spending/rules/${b.dataset.rule}`, { method: "DELETE" });
    await renderTransactions();
  })));
}

$("#spend-plan").addEventListener("change", guard(renderSpendingSummary));
$("#spend-months").addEventListener("change", guard(renderSpendingSummary));
$("#txn-category").addEventListener("change", guard(renderTransactions));
let searchTimer;
$("#txn-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(guard(renderTransactions), 250);
});
$("#spend-import").addEventListener("click", () => $("#spend-file").click());
$("#spend-file").addEventListener("change", guard(async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const negative = confirm("Are purchases negative numbers in this file (most bank exports)?\n\nOK = purchases are negative\nCancel = purchases are positive");
  const r = await api("/api/import/transactions", { method: "POST", body: { csv: await file.text(), negative_is_spending: negative } });
  const box = $("#spend-import-result");
  box.hidden = false;
  box.innerHTML = `Imported ${r.imported} transaction(s)` +
    (r.duplicates ? `; skipped ${r.duplicates} already imported` : "") +
    (r.errors.length
      ? `. <span class="bad">${r.errors.length} row(s) skipped:</span><br>` +
        r.errors.slice(0, 10).map((err) => `Line ${err.line}: ${esc(err.message)}`).join("<br>")
      : ".");
  await loadSpending();
}));
$("#txn-clear").addEventListener("click", guard(async () => {
  if (!confirm("Delete all transactions imported from CSV files? Bank-synced transactions are kept.")) return;
  await api("/api/transactions/imported", { method: "DELETE" });
  await loadSpending();
}));

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

api("/api/states").then((states) => Object.assign(STATE_LABELS, states)).catch(() => {});
showTab(loaders[location.hash.slice(1)] ? location.hash.slice(1) : "dashboard");
