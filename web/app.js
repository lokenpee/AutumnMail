import { categoryMeta, companies, emails } from "./data.js";

const root = document.getElementById("app");
const toastRoot = document.getElementById("toast-root");
const companyMap = new Map(companies.map((company) => [company.id, company]));
const emailMap = new Map(emails.map((email) => [email.id, email]));
const completedStorageKey = "agent-mail.completed";
const dateRangeStorageKey = "agent-mail.dateRange";
const providerPresets = {
  deepseek: {label: "DeepSeek", baseUrl: "https://api.deepseek.com"},
  siliconflow: {label: "硅基流动 SiliconFlow", baseUrl: "https://api.siliconflow.cn/v1"},
  openai: {label: "OpenAI", baseUrl: "https://api.openai.com/v1"},
  dashscope: {label: "阿里云百炼 / Qwen", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1"},
  moonshot: {label: "月之暗面 Kimi", baseUrl: "https://api.moonshot.cn/v1"},
  zhipu: {label: "智谱 BigModel", baseUrl: "https://open.bigmodel.cn/api/paas/v4"},
  openrouter: {label: "OpenRouter", baseUrl: "https://openrouter.ai/api/v1"},
  groq: {label: "Groq", baseUrl: "https://api.groq.com/openai/v1"},
  together: {label: "Together AI", baseUrl: "https://api.together.xyz/v1"},
  xai: {label: "xAI / Grok", baseUrl: "https://api.x.ai/v1"},
  mistral: {label: "Mistral AI", baseUrl: "https://api.mistral.ai/v1"},
  ollama: {label: "Ollama 本地", baseUrl: "http://127.0.0.1:11434/v1"},
  lmstudio: {label: "LM Studio 本地", baseUrl: "http://127.0.0.1:1234/v1"},
  custom: {label: "自定义 OpenAI 兼容接口", baseUrl: ""},
};

function renderProviderOptions(selectedProvider) {
  return Object.entries(providerPresets)
    .map(([value, preset]) => `<option value="${value}" ${selectedProvider === value ? "selected" : ""}>${escapeHtml(preset.label)}</option>`)
    .join("");
}

let pendingMailScrollId = null;
let pendingMailScrollRestore = false;
let searchComposing = false;

function getInitialPage() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  return ["home", "mail", "calendar", "settings"].includes(hash) ? hash : "home";
}

function loadCompleted() {
  try {
    const raw = window.localStorage.getItem(completedStorageKey);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set();
  }
}

function defaultDateRange() {
  const now = new Date();
  return {
    start: formatDate(new Date(now.getFullYear(), now.getMonth(), 1)),
    end: formatDate(new Date(now.getFullYear(), now.getMonth() + 1, 0)),
  };
}

function loadDateRange() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(dateRangeStorageKey) || "null");
    if (stored?.start && stored?.end) return stored;
  } catch {}
  return defaultDateRange();
}

const initialDateRange = loadDateRange();
const state = {
  page: getInitialPage(),
  dateStart: initialDateRange.start,
  dateEnd: initialDateRange.end,
  scope: "job",
  selectedCompany: "all",
  search: "",
  category: "all",
  selectedMailId: "mail-01",
  mailListScrollTop: 0,
  calendarMonth: currentMonthStart(),
  selectedCalendarDate: currentDateKey(),
  companyDrawerId: null,
  completed: loadCompleted(),
  settings: {
    bodyToModel: false,
    notifications: true,
    dailyBrief: true,
  },
  correctionModal: {
    open: false,
    emailId: null,
    field: null,
    value: null,
  },
  batchState: {
    screening: false,
    analyzing: false,
    screeningJobId: null,
    analysisJobId: null,
    screeningPaused: false,
    analysisPaused: false,
    screeningUpdateCount: 0,
    analysisUpdateCount: 0,
    screeningMode: "pending",
    analysisMode: "pending",
    screeningProgress: 0,
    analysisProgress: 0,
    screeningCompleted: 0,
    screeningTotal: 0,
    analysisCompleted: 0,
    analysisTotal: 0,
    screeningResult: null,
    analysisResult: null,
    error: null,
  },
  rerunningEmailId: null,
  logState: {
    events: [],
    cursor: 0,
    timer: null,
  },
  accountState: {
    loaded: false,
    connected: false,
    account: null,
    folders: [],
    error: null,
    connecting: false,
    syncing: false,
    syncResult: null,
  },
  aiState: {
    loaded: false,
    provider: "deepseek",
    config: {
      enabled: true,
      provider: "deepseek",
      base_url: "https://api.deepseek.com",
      model: "deepseek-flash",
      max_chars: 8000,
      max_tokens: 1500,
      timeout: 60,
      temperature: 0,
      concurrency: 2,
    },
    models: [],
    fetchingModels: false,
    apiKeyConfigured: false,
    draftApiKey: "",
    dirty: false,
    saving: false,
    testing: false,
    connectionStatus: null,
    connectionError: null,
    error: null,
    testError: null,
    testResults: null,
  },
  screeningState: {
    loaded: false,
    provider: "siliconflow",
    config: {
      enabled: true,
      provider: "siliconflow",
      base_url: "https://api.siliconflow.cn/v1",
      model: "",
      max_chars: 2000,
      max_tokens: 300,
      timeout: 30,
      temperature: 0,
      concurrency: 4,
    },
    models: [],
    fetchingModels: false,
    apiKeyConfigured: false,
    draftApiKey: "",
    dirty: false,
    saving: false,
    connectionStatus: null,
    connectionError: null,
    sampleTesting: false,
    sampleResults: null,
    error: null,
  },
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const allowedEmailTags = new Set([
  "a", "b", "blockquote", "br", "center", "code", "div", "em", "font", "h1", "h2", "h3", "h4",
  "h5", "h6", "hr", "i", "img", "li", "ol", "p", "pre", "s", "small", "span", "strong",
  "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
]);
const blockedEmailTags = new Set([
  "audio", "base", "button", "canvas", "embed", "form", "iframe", "input", "link", "math",
  "meta", "object", "option", "script", "select", "source", "style", "svg", "textarea", "video",
]);
const allowedEmailAttrs = new Set([
  "align", "alt", "border", "cellpadding", "cellspacing", "color", "colspan", "datetime", "face",
  "height", "href", "rowspan", "size", "src", "start", "style", "title", "type", "valign", "width",
]);
const allowedEmailStyles = new Set([
  "background-color", "border", "border-bottom", "border-collapse", "border-left", "border-right",
  "border-top", "color", "display", "font-family", "font-size", "font-style", "font-weight", "height",
  "line-height", "margin", "max-height", "max-width", "min-height", "min-width", "overflow-wrap",
  "padding", "text-align", "text-decoration", "vertical-align", "white-space", "width", "word-break",
]);

function safeEmailUrl(value) {
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:", "mailto:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

function sanitizeEmailStyle(value) {
  return String(value || "")
    .split(";")
    .map((part) => {
      const separator = part.indexOf(":");
      if (separator < 1) return "";
      const property = part.slice(0, separator).trim().toLowerCase();
      const styleValue = part.slice(separator + 1).trim();
      if (!allowedEmailStyles.has(property)) return "";
      if (/url\s*\(|expression\s*\(|javascript:/i.test(styleValue)) return "";
      return `${property}:${styleValue}`;
    })
    .filter(Boolean)
    .join(";");
}

function unwrapEmailElement(element) {
  const parent = element.parentNode;
  if (!parent) return;
  while (element.firstChild) parent.insertBefore(element.firstChild, element);
  element.remove();
}

function sanitizeEmailHtml(html) {
  const documentFragment = new DOMParser().parseFromString(String(html || ""), "text/html");
  if (!documentFragment.body) return "";
  for (const element of [...documentFragment.body.querySelectorAll("*")]) {
    if (!element.isConnected) continue;
    const tag = element.tagName.toLowerCase();
    if (blockedEmailTags.has(tag)) {
      element.remove();
      continue;
    }
    if (!allowedEmailTags.has(tag)) {
      unwrapEmailElement(element);
      continue;
    }
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on") || !allowedEmailAttrs.has(name)) {
        element.removeAttribute(attribute.name);
        continue;
      }
      if (name === "style") {
        const sanitizedStyle = sanitizeEmailStyle(attribute.value);
        if (sanitizedStyle) element.setAttribute("style", sanitizedStyle);
        else element.removeAttribute("style");
      }
    }
    if (tag === "a") {
      const href = safeEmailUrl(element.getAttribute("href") || "");
      if (href) {
        element.setAttribute("href", href);
        element.setAttribute("target", "_blank");
        element.setAttribute("rel", "noopener noreferrer");
      } else {
        element.removeAttribute("href");
      }
    }
    if (tag === "img") {
      const src = safeEmailUrl(element.getAttribute("src") || "");
      if (src) {
        element.setAttribute("src", src);
        element.setAttribute("referrerpolicy", "no-referrer");
        element.setAttribute("loading", "lazy");
      } else {
        element.remove();
      }
    }
  }
  return documentFragment.body.innerHTML;
}

function linkifyPlainEmailText(text) {
  return escapeHtml(text)
    .replace(/(https?:\/\/[^\s<]+|mailto:[^\s<]+)/gi, (url) => (
      `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`
    ))
    .replace(new RegExp(String.fromCharCode(10), "g"), "<br>");
}

function currentDateKey() {
  return formatDate(new Date());
}

function currentMonthStart() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1);
}

function parseDateTime(value) {
  return new Date(value.includes("T") ? value : `${value}T00:00:00+08:00`);
}

function formatDate(value) {
  if (!value) return "";
  const date = typeof value === "string" ? parseDateTime(value) : value;
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatShortDate(value) {
  if (!value) return "";
  const date = typeof value === "string" ? parseDateTime(value) : value;
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${month}-${day}`;
}

function formatDateTime(value) {
  if (!value) return "";
  const date = parseDateTime(value);
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${month}-${day} ${hour}:${minute}`;
}

function formatMonthTitle(date) {
  return `${date.getFullYear()} 年 ${date.getMonth() + 1} 月`;
}

function formatChineseDate(dateKey) {
  const date = parseDateTime(dateKey);
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
}

function dateKey(date) {
  return formatDate(date);
}

function addDays(value, days) {
  const date = typeof value === "string" ? parseDateTime(value) : new Date(value);
  date.setDate(date.getDate() + days);
  return dateKey(date);
}

function diffDays(from, to) {
  const a = parseDateTime(`${from}T00:00:00+08:00`).getTime();
  const b = parseDateTime(`${to}T00:00:00+08:00`).getTime();
  return Math.round((b - a) / 86400000);
}

function isDateInRange(value) {
  const key = formatDate(value);
  return key >= state.dateStart && key <= state.dateEnd;
}

function categoryInfo(category) {
  return categoryMeta[category] || categoryMeta.unclassified;
}

function pill(text, tone = "slate", extraClass = "") {
  return `<span class="pill tone-${tone} ${extraClass}">${escapeHtml(text)}</span>`;
}

function emailCategoryPill(email, correctionField = "") {
  const meta = categoryInfo(email.category);
  if (!correctionField) return pill(meta.label, meta.tone);
  return `<span class="pill tone-${meta.tone} correctable" data-correct-field="${correctionField}" data-mail-id="${email.id}" title="双击修改">${escapeHtml(meta.label)}</span>`;
}

function deadlinePill(email) {
  if (!email.deadline) {
    return `<button class="pill tone-muted correctable" data-action="edit-deadline" data-mail-id="${email.id}" title="设置 DDL">+ 设置 DDL</button>`;
  }
  return `<button class="pill tone-amber correctable" data-action="edit-deadline" data-mail-id="${email.id}" title="修改 DDL">DDL ${escapeHtml(formatShortDate(email.deadline))}</button>`;
}

function emailCompanyPill(email, correctionField = "") {
  const tone = email.isOther ? "muted" : "slate";
  const rawCompany = email.company || "";
  const label = (!rawCompany || rawCompany === "待分类") ? "公司未识别" : rawCompany;
  if (!correctionField) return pill(label, tone);
  return `<span class="pill tone-${tone} correctable" data-correct-field="${correctionField}" data-mail-id="${email.id}" title="双击修改">${escapeHtml(label)}</span>`;
}

function eventPill(email) {
  if (!email.eventDate) return "";
  return `<span class="pill tone-blue correctable" data-correct-field="eventDate" data-mail-id="${email.id}" title="双击修改">面试 ${escapeHtml(formatShortDate(email.eventDate))}</span>`;
}

function isCompleted(emailId) {
  return state.completed.has(emailId);
}

function canComplete(email) {
  return Boolean(email?.canComplete);
}

function needsReview(email) {
  return Boolean(email?.needsReview);
}

function reviewPill(email) {
  return needsReview(email) ? pill("待复核", "amber") : "";
}

function isExcludedFromJobSearch(email) {
  return Boolean(email.isOther || email.companyIsOther || ["other", "unclassified"].includes(email.category));
}

function isVisibleByScope(email) {
  return state.scope === "all" || !isExcludedFromJobSearch(email);
}

function mailMatchesFilters(email) {
  if (!isDateInRange(email.receivedAt)) return false;
  if (!isVisibleByScope(email)) return false;
  if (state.selectedCompany !== "all" && email.companyId !== state.selectedCompany) return false;
  if (state.category !== "all" && email.category !== state.category) return false;
  if (state.search.trim()) {
    const query = state.search.trim().toLowerCase();
    if (!email.company.toLowerCase().includes(query)) return false;
  }
  return true;
}

function getFilteredEmails() {
  return emails
    .filter(mailMatchesFilters)
    .sort((a, b) => parseDateTime(b.receivedAt) - parseDateTime(a.receivedAt));
}

function getJobEmails() {
  return emails.filter((email) => !isExcludedFromJobSearch(email) && isDateInRange(email.receivedAt));
}

function getStats() {
  const scoped = getJobEmails();
  const companyIds = new Set(
    scoped
      .map((email) => email.companyId)
      .filter((companyId) => companyId && companyId !== "unassigned"),
  );
  const countBy = (category) => scoped.filter((email) => email.category === category).length;

  return [
    { label: "公司数", value: companyIds.size, category: null, tone: "#eef2ff" },
    { label: "测评数", value: countBy("assessment_invite"), category: "assessment_invite", tone: "#fffbeb" },
    { label: "面试数", value: countBy("interview_invite"), category: "interview_invite", tone: "#eff6ff" },
    { label: "Offer 数", value: countBy("offer"), category: "offer", tone: "#ecfdf5" },
    { label: "拒绝数", value: countBy("rejected"), category: "rejected", tone: "#fef2f2" },
  ];
}

function isPending(email) {
  return !canComplete(email) || !isCompleted(email.id);
}

function getDashboardSummary() {
  const active = getJobEmails();
  const today = currentDateKey();
  const todayDue = active.filter(
    (email) => email.deadline === today && isPending(email),
  );
  const nextThreeDays = active
    .filter((email) => {
      const date = email.deadline || email.eventDate;
      if (!date || !isPending(email)) return false;
      const delta = diffDays(today, date);
      return delta > 0 && delta <= 3;
    })
    .sort((a, b) => (a.deadline || a.eventDate).localeCompare(b.deadline || b.eventDate));
  const newOffers = active.filter((email) => email.category === "offer" && diffDays(email.receivedAt.slice(0, 10), today) <= 7);
  const overdue = active.filter(
    (email) => email.deadline && email.deadline < today && isPending(email),
  );

  return { todayDue, nextThreeDays, newOffers, overdue };
}

function saveCompleted() {
  window.localStorage.setItem(completedStorageKey, JSON.stringify([...state.completed]));
}

function saveDateRange() {
  window.localStorage.setItem(
    dateRangeStorageKey,
    JSON.stringify({start: state.dateStart, end: state.dateEnd}),
  );
}

function showToast(message, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  toastRoot.appendChild(toast);
  window.setTimeout(() => toast.remove(), 2200);
}

function captureMailListScroll() {
  const list = document.querySelector(".mail-list");
  if (list) state.mailListScrollTop = list.scrollTop;
}

function navigate(page, options = {}) {
  captureMailListScroll();
  const enteringMail = page === "mail" && state.page !== "mail";
  window.scrollTo({top: 0, behavior: "auto"});
  state.page = page;
  if (options.companyId !== undefined) state.selectedCompany = options.companyId;
  if (options.category !== undefined) state.category = options.category;
  if (options.mailId !== undefined) {
    state.selectedMailId = options.mailId;
    pendingMailScrollId = options.mailId;
    pendingMailScrollRestore = false;
  } else if (enteringMail) {
    pendingMailScrollRestore = true;
  }
  if (options.scope !== undefined) state.scope = options.scope;
  if (options.calendarMonth !== undefined) state.calendarMonth = options.calendarMonth;
  if (options.selectedCalendarDate !== undefined) state.selectedCalendarDate = options.selectedCalendarDate;
  const nextHash = `#/${page}`;
  if (window.location.hash !== nextHash) {
    window.location.hash = nextHash;
  } else {
    render();
  }
}

function restoreMailListScroll() {
  window.requestAnimationFrame(() => {
    const list = document.querySelector(".mail-list");
    if (list) list.scrollTop = state.mailListScrollTop;
  });
}

function scrollSelectedMailIntoView(mailId) {
  if (!mailId) return;
  window.requestAnimationFrame(() => {
    const list = document.querySelector(".mail-list");
    const row = [...document.querySelectorAll(".mail-row")].find(
      (item) => item.dataset.mailId === mailId,
    );
    if (!list || !row) return;
    const listRect = list.getBoundingClientRect();
    const rowRect = row.getBoundingClientRect();
    const centeredTop = list.scrollTop + rowRect.top - listRect.top - Math.max(8, (list.clientHeight - rowRect.height) / 2);
    list.scrollTo({top: Math.max(0, centeredTop), behavior: "auto"});
  });
}

function render() {
  const existingList = document.querySelector(".mail-list");
  if (existingList && state.page === "mail") {
    state.mailListScrollTop = existingList.scrollTop;
  }

  root.innerHTML = `
    ${renderTopbar()}
    <main class="page">
      ${renderCurrentPage()}
    </main>
    ${renderCompanyDrawer()}
    ${renderCorrectionModal()}
  `;

  if (state.page === "mail" && pendingMailScrollId) {
    const mailId = pendingMailScrollId;
    pendingMailScrollId = null;
    pendingMailScrollRestore = false;
    scrollSelectedMailIntoView(mailId);
  } else if (state.page === "mail") {
    pendingMailScrollRestore = false;
    restoreMailListScroll();
  }
}

function renderCurrentPage() {
  if (state.page === "mail") return renderMailPage();
  if (state.page === "calendar") return renderCalendarPage();
  if (state.page === "settings") return renderSettingsPage();
  return renderHomePage();
}

function renderTopbar() {
  const tabs = [
    ["home", "首页"],
    ["mail", "邮件"],
    ["calendar", "日历"],
    ["settings", "设置"],
  ];
  return `
    <header class="topbar">
      <div class="brand">
        <span class="brand-mark">秋</span>
        <span>秋招邮件管家</span>
      </div>
      <nav class="nav-tabs" aria-label="主导航">
        ${tabs
          .map(
            ([page, label]) => `
              <button class="nav-tab ${state.page === page ? "is-active" : ""}"
                data-action="navigate" data-page="${page}"
                aria-current="${state.page === page ? "page" : "false"}">
                ${label}
              </button>
            `,
          )
          .join("")}
      </nav>
      <div class="topbar-actions">
        <span class="sync-status"><span class="sync-dot"></span>已同步 09:30</span>
      </div>
    </header>
  `;
}

function renderDateRange() {
  return `
    <div class="toolbar-group">
      <span class="toolbar-label">日期范围</span>
      <input class="input" id="date-start" type="date" value="${state.dateStart}" aria-label="开始日期" />
      <span class="toolbar-label">至</span>
      <input class="input" id="date-end" type="date" value="${state.dateEnd}" aria-label="结束日期" />
    </div>
  `;
}

function renderHomePage() {
  const stats = getStats();
  const summary = getDashboardSummary();

  return `
    <div class="page-header">
      <div>
        <p class="page-kicker">Overview</p>
        <h1 class="page-title">秋招总览</h1>
        <p class="page-subtitle">当前日期范围内，先看整体进展，再处理今天和即将到期的事情。</p>
      </div>
    </div>

    <section class="section">
      <div class="section-heading">
        <div>
          <h2 class="section-title">统计</h2>
          <p class="section-caption">只统计秋招相关邮件，不包含广告和无关邮件。</p>
        </div>
        <div class="toolbar">${renderDateRange()}</div>
      </div>
      <div class="stats-grid">
        ${stats.map(renderStatCard).join("")}
      </div>
    </section>

    <section class="section">
      <div class="section-heading">
        <div>
          <h2 class="section-title">摘要</h2>
          <p class="section-caption">今天、未来 3 天、新 Offer 和逾期任务。</p>
        </div>
      </div>
      <div class="summary-grid">
        ${renderSummaryCard("今日到期", summary.todayDue)}
        ${renderSummaryCard("未来 3 天事项", summary.nextThreeDays)}
        ${renderSummaryCard("新 Offer", summary.newOffers)}
        ${renderSummaryCard("逾期任务", summary.overdue)}
      </div>
    </section>
  `;
}

function renderStatCard(stat) {
  const clickable = stat.category ? `data-action="filter-category" data-category="${stat.category}"` : "";
  return `
    <button class="stat-card" style="--card-accent:${stat.tone}" ${clickable}>
      <span class="stat-label">${escapeHtml(stat.label)}</span>
      <strong class="stat-value">${stat.value}</strong>
    </button>
  `;
}

function renderSummaryCard(title, items) {
  const visibleItems = items.slice(0, 4);
  return `
    <article class="summary-card panel">
      <header class="summary-card-header">
        <h3 class="summary-card-title">${title}</h3>
        <span class="summary-card-count">${items.length}</span>
      </header>
      <div class="summary-list">
        ${
          visibleItems.length
            ? visibleItems
                .map((email) => {
                  const timeText = email.deadline
                    ? `截止 ${formatShortDate(email.deadline)}`
                    : email.eventDate
                      ? `面试 ${formatShortDate(email.eventDate)}`
                      : `收到 ${formatShortDate(email.receivedAt)}`;
                  return `
                    <button class="summary-item" data-action="open-mail" data-mail-id="${email.id}">
                      <span>
                        <span class="summary-item-title">${emailCategoryPill(email, "category")} ${escapeHtml(email.company)}</span>
                        <span class="summary-item-meta">${escapeHtml(timeText)}</span>
                      </span>
                      <span class="mail-company">${isCompleted(email.id) ? "已完成" : "打开邮件"}</span>
                    </button>
                  `;
                })
                .join("")
            : `<div class="empty-state"><div><strong>当前没有事项</strong><span>可以切换日期范围查看其他时间。</span></div></div>`
        }
      </div>
    </article>
  `;
}

function renderMailPage() {
  const filtered = getFilteredEmails();
  if (!filtered.some((email) => email.id === state.selectedMailId)) {
    state.selectedMailId = filtered[0]?.id || null;
  }
  const selected = emailMap.get(state.selectedMailId) || null;

  return `
    <div class="page-header">
      <div>
        <p class="page-kicker">Inbox workspace</p>
        <h1 class="page-title">邮件</h1>
        <p class="page-subtitle">左侧浏览邮件，右侧查看详情；点击公司名称打开公司时间线。</p>
      </div>
    </div>

    <section class="mail-filter-bar panel">
      <div class="filter-row">
        ${renderDateRange()}
      </div>
      <div class="filter-row">
        <button class="filter-chip ${state.scope === "job" ? "is-active" : ""}"
          data-action="set-scope" data-scope="job">只看秋招</button>
        <button class="filter-chip ${state.scope === "all" ? "is-active" : ""}"
          data-action="set-scope" data-scope="all">全部邮件</button>
        <span class="toolbar-label">公司</span>
        ${renderCompanyQuickFilters()}
        <input class="input" id="company-search" type="search" value="${escapeHtml(state.search)}"
          placeholder="搜索公司" aria-label="搜索公司" />
        <select class="select" id="category-filter" aria-label="邮件类别">
          <option value="all">全部类别</option>
          ${Object.entries(categoryMeta)
            .filter(([key]) => key !== "unclassified")
            .map(
              ([key, meta]) =>
                `<option value="${key}" ${state.category === key ? "selected" : ""}>${escapeHtml(meta.label)}</option>`,
            )
            .join("")}
        </select>
      </div>
    </section>

    <section class="mail-workspace panel">
      <div class="mail-list-pane">
        <header class="mail-list-header">
          <h2>邮件列表</h2>
          <div class="mail-list-actions">
            <span class="mail-list-count">共 ${filtered.length} 封，最新优先</span>
            <button class="button ghost mail-scroll-top" data-action="mail-scroll-top">回顶</button>
          </div>
        </header>
        <div class="mail-list">
          ${
            filtered.length
              ? filtered.map(renderMailRow).join("")
              : `<div class="empty-state"><div><strong>当前筛选条件下没有邮件</strong><span>尝试切换日期范围、公司或“全部邮件”。</span></div></div>`
          }
        </div>
      </div>
      <div class="mail-detail-pane">
        ${renderMailDetail(selected)}
      </div>
    </section>
  `;
}

function getRecognizedCompanyCounts() {
  const counts = new Map();
  for (const email of emails) {
    if (!isDateInRange(email.receivedAt) || isExcludedFromJobSearch(email)) continue;
    const companyId = String(email.companyId || "");
    const companyName = String(email.company || "").trim();
    if (!companyId || companyId === "unassigned") continue;
    if (!companyName || ["公司未识别", "待分类", "其他"].includes(companyName)) continue;
    const current = counts.get(companyId) || {id: companyId, name: companyName, count: 0};
    current.count += 1;
    counts.set(companyId, current);
  }
  return [...counts.values()]
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "zh-CN"))
    .slice(0, 5);
}

function renderCompanyQuickFilters() {
  return getRecognizedCompanyCounts()
    .map(
      (company) => `
        <button class="filter-chip ${state.selectedCompany === company.id ? "is-active" : ""}"
          data-action="set-company" data-company-id="${company.id}">
          ${escapeHtml(company.name)} <span class="filter-count">${company.count}</span>
        </button>
      `,
    )
    .join("");
}

function renderMailRow(email) {
  const completed = isCompleted(email.id);
  const canMarkComplete = canComplete(email);
  return `
    <article class="mail-row ${state.selectedMailId === email.id ? "is-selected" : ""} ${email.unread ? "is-unread" : ""}" data-mail-id="${email.id}">
      <div class="mail-row-body" data-action="select-mail" data-mail-id="${email.id}" role="button" tabindex="0">
        <strong class="mail-subject">${escapeHtml(email.subject)}</strong>
        <span class="mail-snippet">${escapeHtml(email.snippet).slice(0, 20)}</span>
        <span class="mail-row-tags">
          ${emailCompanyPill(email, "company")}
          ${emailCategoryPill(email, "category")}
          ${reviewPill(email)}
          ${deadlinePill(email)}
          ${eventPill(email)}
          ${
            canMarkComplete
              ? `
                <button class="completion-pill ${completed ? "is-completed" : ""}"
                  data-action="toggle-complete" data-mail-id="${email.id}">
                  ${completed ? "✓ 已完成" : "○ 标记完成"}
                </button>
              `
              : `<span class="completion-pill is-disabled">无需完成标记</span>`
          }
          <button class="rerun-button ${state.rerunningEmailId === email.id ? "is-running" : ""}"
            data-action="rerun-email" data-mail-id="${email.id}"
            aria-label="重新识别" title="重新识别">
            ↻ 重roll
          </button>
        </span>
      </div>
      <time class="mail-row-time" datetime="${escapeHtml(email.receivedAt)}">${escapeHtml(formatDateTime(email.receivedAt))}</time>
    </article>
  `;
}

function renderMailDetail(email) {
  if (!email) {
    return `
      <div class="empty-state" style="min-height:650px">
        <div><strong>请选择一封邮件</strong><span>左侧列表中的数据会显示在这里。</span></div>
      </div>
    `;
  }

  const completed = isCompleted(email.id);
  const senderName = email.fromName || "未知发件人";
  const senderEmail = email.fromEmail || "";

  return `
    <header class="mail-detail-header">
      <h2 class="mail-detail-title">${escapeHtml(email.subject)}</h2>
    </header>
    <div class="mail-detail-body">
      <div class="mail-sender-line">
        <strong>${escapeHtml(senderName)}</strong>
        ${senderEmail ? `<span>${escapeHtml(senderEmail)}</span>` : ""}
        <time>${escapeHtml(formatDateTime(email.receivedAt))}</time>
      </div>

      ${needsReview(email)
        ? `
          <section class="review-notice">
            <div>
              <strong>这封邮件需要人工复核</strong>
              <span>${escapeHtml(email.reviewReason || "模型对部分字段不确定，请检查公司和日期。")}</span>
            </div>
            <button class="button" data-action="mark-reviewed" data-mail-id="${email.id}">完成复核</button>
          </section>
        `
        : ""}

      <section class="detail-section email-body-section">
        <div class="detail-copy email-html-body">${
          email.bodyHtml ? sanitizeEmailHtml(email.bodyHtml) : linkifyPlainEmailText(email.body)
        }</div>
      </section>

      <div class="detail-actions">
        ${
          canComplete(email)
            ? `
              <button class="completion-control ${completed ? "is-completed" : ""}"
                data-action="toggle-complete" data-mail-id="${email.id}">
                <span>${completed ? "✓" : "○"}</span>
                ${completed ? "已完成" : "标记完成"}
              </button>
            `
            : ""
        }
        <button class="button" data-action="open-original">打开 163 原文</button>
      </div>
    </div>
  `;
}

function selectMailInPlace(mailId) {
  const list = document.querySelector(".mail-list");
  const scrollTop = list?.scrollTop || 0;
  state.selectedMailId = mailId;
  document.querySelectorAll(".mail-row.is-selected").forEach((row) => row.classList.remove("is-selected"));
  const selectedRow = [...document.querySelectorAll(".mail-row")].find(
    (row) => row.dataset.mailId === mailId,
  );
  selectedRow?.classList.add("is-selected");
  const pane = document.querySelector(".mail-detail-pane");
  if (pane) pane.innerHTML = renderMailDetail(emailMap.get(mailId) || null);
  if (list) list.scrollTop = scrollTop;
}

function getCalendarEvents() {
  const events = [];
  for (const email of emails) {
    if (isCompleted(email.id)) continue;
    if (
      ["assessment_invite", "written_test_invite"].includes(email.category) &&
      email.deadline
    ) {
      events.push({
        id: `deadline-${email.id}`,
        type: email.category === "assessment_invite" ? "assessment" : "written_test",
        date: email.deadline,
        email,
        completed: isCompleted(email.id),
      });
    }
    if (email.category === "interview_invite" && email.eventDate) {
      events.push({
        id: `interview-${email.id}`,
        type: "interview",
        date: email.eventDate,
        email,
        completed: isCompleted(email.id),
      });
    }
  }
  return events;
}

function getCalendarDays(year, month) {
  const first = new Date(year, month, 1);
  const startOffset = (first.getDay() + 6) % 7;
  const start = new Date(year, month, 1 - startOffset);
  return Array.from({ length: 42 }, (_, index) => {
    return new Date(start.getFullYear(), start.getMonth(), start.getDate() + index);
  });
}

function eventLabel(type) {
  if (type === "assessment") return "测评";
  if (type === "written_test") return "笔试";
  return "面试";
}

function renderCalendarPage() {
  const year = state.calendarMonth.getFullYear();
  const month = state.calendarMonth.getMonth();
  const days = getCalendarDays(year, month);
  const selectedEvents = getCalendarEvents().filter((event) => event.date === state.selectedCalendarDate);

  return `
    <div class="page-header">
      <div>
        <p class="page-kicker">Timeline</p>
        <h1 class="page-title">日历</h1>
        <p class="page-subtitle">日历使用独立的月份切换，顶部邮件日期范围不会影响这里。</p>
      </div>
    </div>

    <section class="calendar-layout">
      <div class="panel">
        <div class="calendar-header">
          <div class="calendar-title">${formatMonthTitle(state.calendarMonth)}</div>
          <div class="filter-row">
            <button class="button ghost" data-action="calendar-prev">‹ 上月</button>
            <button class="button" data-action="calendar-today">回到本月</button>
            <button class="button ghost" data-action="calendar-next">下月 ›</button>
          </div>
          <div class="calendar-legend">
            ${pill("测评", "amber")}
            ${pill("笔试", "violet")}
            ${pill("面试", "blue")}
          </div>
        </div>
        <div class="calendar-grid">
          ${["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            .map((day) => `<div class="calendar-weekday">${day}</div>`)
            .join("")}
          ${days.map((day) => renderCalendarDay(day, month)).join("")}
        </div>
      </div>

      <aside class="calendar-side panel">
        <h2>${formatChineseDate(state.selectedCalendarDate)} 详情</h2>
        <p class="calendar-side-date">当天的测评、笔试和面试事项</p>
        ${renderCalendarEventList(selectedEvents)}
      </aside>
    </section>
  `;
}

function renderCalendarDay(day, activeMonth) {
  const date = dateKey(day);
  const events = getCalendarEvents().filter((event) => event.date === date);
  const counts = {
    assessment: events.filter((event) => event.type === "assessment").length,
    written_test: events.filter((event) => event.type === "written_test").length,
    interview: events.filter((event) => event.type === "interview").length,
  };
  const classes = [
    "calendar-day",
    day.getMonth() !== activeMonth ? "is-outside" : "",
    date === currentDateKey() ? "is-today" : "",
    date === state.selectedCalendarDate ? "is-selected" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return `
    <div class="${classes}" data-action="select-calendar-day" data-date="${date}" role="button" tabindex="0">
      <span class="calendar-day-number">${day.getDate()}</span>
      <div class="calendar-chips">
        ${counts.assessment ? `<span class="calendar-chip assessment">测评 ${counts.assessment}</span>` : ""}
        ${counts.written_test ? `<span class="calendar-chip written">笔试 ${counts.written_test}</span>` : ""}
        ${counts.interview ? `<span class="calendar-chip interview">面试 ${counts.interview}</span>` : ""}
      </div>
    </div>
  `;
}

function renderCalendarEventList(events) {
  if (!events.length) {
    return `<div class="empty-state"><div><strong>当天没有事项</strong><span>可以点击其他日期查看。</span></div></div>`;
  }
  return `
    <div class="calendar-event-list">
      ${events
        .sort((a, b) => a.type.localeCompare(b.type))
        .map((event) => {
          const email = event.email;
          const dateText = event.type === "interview" ? `面试 ${formatDate(event.date)}` : `DDL ${formatDate(event.date)}`;
          return `
            <article class="calendar-event">
              <div class="calendar-event-top">
                ${pill(eventLabel(event.type), event.type === "assessment" ? "amber" : event.type === "written_test" ? "violet" : "blue")}
                <button class="button ghost" data-action="calendar-open-mail" data-mail-id="${email.id}">打开邮件</button>
              </div>
              <div class="calendar-event-company">${escapeHtml(email.company)}</div>
              <div class="calendar-event-meta">${dateText}${event.completed ? " · 已完成" : ""}</div>
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderCompanyDrawer() {
  if (!state.companyDrawerId) return "";
  const timeline = emails
    .filter((email) => email.companyId === state.companyDrawerId)
    .sort((a, b) => parseDateTime(b.receivedAt) - parseDateTime(a.receivedAt));
  if (!timeline.length) return "";
  const company = companyMap.get(state.companyDrawerId) || {
    id: state.companyDrawerId,
    name: timeline[0].company || "公司",
    status: "已识别",
  };

  return `
    <div class="drawer-backdrop" data-action="close-company"></div>
    <aside class="company-drawer" aria-label="${escapeHtml(company.name)} 公司详情">
      <header class="drawer-header">
        <div>
          <p class="page-kicker" style="margin-bottom:3px">Company timeline</p>
          <h2>${escapeHtml(company.name)}</h2>
        </div>
        <button class="button ghost" data-action="close-company" aria-label="关闭公司详情">✕</button>
      </header>
      <div class="drawer-summary">
        <div class="drawer-summary-item">
          <span class="drawer-summary-label">当前状态</span>
          <span class="drawer-summary-value">${escapeHtml(company.status)}</span>
        </div>
        <div class="drawer-summary-item">
          <span class="drawer-summary-label">关联邮件</span>
          <span class="drawer-summary-value">${timeline.length}</span>
        </div>
        <div class="drawer-summary-item">
          <span class="drawer-summary-label">最近更新</span>
          <span class="drawer-summary-value">${timeline[0] ? formatShortDate(timeline[0].receivedAt) : "-"}</span>
        </div>
      </div>
      <div class="drawer-timeline">
        ${
          timeline.length
            ? timeline
                .map(
                  (email) => `
                    <button class="drawer-timeline-item" data-action="timeline-mail" data-mail-id="${email.id}">
                      <span class="drawer-timeline-date">${formatShortDate(email.receivedAt)}</span>
                      <span>
                        ${emailCategoryPill(email, "category")}
                        <span class="drawer-timeline-subject">${escapeHtml(email.subject)}</span>
                      </span>
                      <span class="mail-company">打开</span>
                    </button>
                  `,
                )
                .join("")
            : `<div class="empty-state"><div><strong>还没有关联邮件</strong><span>后续同步的邮件会显示在这里。</span></div></div>`
        }
      </div>
    </aside>
  `;
}

async function loadScreeningSettings() {
  try {
    const data = await apiRequest("/api/ai/screening/settings");
    state.screeningState = {
      ...state.screeningState,
      ...data,
      apiKeyConfigured: Boolean(data.api_key_configured ?? data.apiKeyConfigured),
      config: {...state.screeningState.config, ...(data.config || {})},
      loaded: true,
      error: null,
    };
  } catch (error) {
    state.screeningState = {
      ...state.screeningState,
      loaded: true,
      error: error.message || "筛选 API 配置加载失败。",
    };
  }
  render();
}

async function fetchScreeningModels() {
  const baseUrl = document.getElementById("screening-base-url")?.value?.trim() || state.screeningState.config.base_url || "";
  const apiKey = document.getElementById("screening-api-key")?.value?.trim() || "";
  if (!baseUrl) {
    showToast("请先选择服务商或填写筛选 API Base URL。", "error");
    return;
  }
  state.screeningState.fetchingModels = true;
  state.screeningState.error = null;
  render();
  try {
    const data = await apiRequest("/api/ai/screening/models", {
      method: "POST",
      body: JSON.stringify({base_url: baseUrl, api_key: apiKey}),
    });
    state.screeningState.fetchingModels = false;
    state.screeningState.models = data.models || [];
    if (state.screeningState.models.length && !state.screeningState.models.includes(state.screeningState.config.model)) {
      state.screeningState.config.model = state.screeningState.models[0];
    }
    showToast(`筛选模型已获取：${state.screeningState.models.length} 个`);
    render();
  } catch (error) {
    state.screeningState.fetchingModels = false;
    state.screeningState.error = error.message || "获取筛选模型失败。";
    render();
    showToast(state.screeningState.error, "error");
  }
}

async function submitScreeningForm(event) {
  event.preventDefault();
  const payload = {
    enabled: Boolean(document.getElementById("screening-enabled")?.checked),
    provider: document.getElementById("screening-provider")?.value || "siliconflow",
    base_url: document.getElementById("screening-base-url")?.value?.trim() || state.screeningState.config.base_url || "",
    model: document.getElementById("screening-model")?.value || "",
    api_key: document.getElementById("screening-api-key")?.value?.trim() || "",
    max_chars: Number(document.getElementById("screening-max-chars")?.value || 2000),
    max_tokens: Number(document.getElementById("screening-max-tokens")?.value || 300),
    timeout: Number(document.getElementById("screening-timeout")?.value || 30),
    concurrency: Number(document.getElementById("screening-concurrency")?.value || 4),
  };
  state.screeningState.saving = true;
  state.screeningState.error = null;
  render();
  try {
    await apiRequest("/api/ai/screening/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.screeningState.saving = false;
    state.screeningState.dirty = false;
    state.screeningState.providerChanged = false;
    showToast("筛选 API 配置已保存");
    await loadScreeningSettings();
  } catch (error) {
    state.screeningState.saving = false;
    state.screeningState.error = error.message || "筛选 API 配置保存失败。";
    render();
    showToast(state.screeningState.error, "error");
  }
}

function renderScreeningSettingsCard() {
  const screening = state.screeningState;
  const config = screening.config;
  return `
    <article class="settings-card panel ai-settings-card">
      <div class="settings-card-heading">
        <div>
          <h2>筛选 API</h2>
          <p>用低成本的 OpenAI 兼容模型判断邮件是否与秋招相关；支持云端服务或本地模型。</p>
        </div>
        ${screening.apiKeyConfigured ? pill("筛选 Key 已配置", "green") : pill("未配置筛选 Key", "muted")}
      </div>
      <form id="screening-form" class="account-form">
        <label class="checkbox-row">
          <input type="checkbox" id="screening-enabled" ${config.enabled !== false ? "checked" : ""} />
          <span>启用筛选 API</span>
        </label>
        <div class="form-grid-2">
          <label class="form-field">
            <span>服务商</span>
            <select class="select" id="screening-provider">
              ${renderProviderOptions(config.provider)}
            </select>
          </label>
          <label class="form-field">
            <span>筛选模型</span>
            <div class="inline-control">
              <input class="input" id="screening-model" list="screening-model-options" value="${escapeHtml(config.model || "")}" placeholder="获取模型或手动输入模型 ID" />
              <datalist id="screening-model-options">
                ${(screening.models || []).map((model) => `<option value="${escapeHtml(model)}"></option>`).join("")}
              </datalist>
              <button class="button" type="button" data-action="fetch-screening-models" ${screening.fetchingModels ? "disabled" : ""}>
                ${screening.fetchingModels ? "获取中..." : "获取模型"}
              </button>
            </div>
          </label>
        </div>
        <label class="form-field">
          <span>筛选 API Base URL</span>
          <input class="input" id="screening-base-url" type="url" value="${escapeHtml(config.base_url || "")}" placeholder="https://your-provider.example/v1" />
        </label>
        <label class="form-field">
          <span>筛选 API Key</span>
          <input class="input" id="screening-api-key" type="password" value="${escapeHtml(screening.draftApiKey || "")}" placeholder="${screening.apiKeyConfigured ? "••••••••••••••••  已保存，输入新 Key 可替换" : "输入筛选模型 API Key"}" autocomplete="new-password" />
        </label>
        <div class="form-grid-4">
          <label class="form-field"><span>正文最大字符</span><input class="input" id="screening-max-chars" type="number" min="100" max="20000" value="${Number(config.max_chars || 2000)}" /></label>
          <label class="form-field"><span>最大输出 Token</span><input class="input" id="screening-max-tokens" type="number" min="64" max="2048" value="${Number(config.max_tokens || 300)}" /></label>
          <label class="form-field"><span>超时时间（秒）</span><input class="input" id="screening-timeout" type="number" min="5" max="300" value="${Number(config.timeout || 30)}" /></label>
          <label class="form-field"><span>并发数</span><input class="input" id="screening-concurrency" type="number" min="1" max="16" value="${Number(config.concurrency || 4)}" /></label>
        </div>
        <div class="form-actions">
          <button id="screening-save-button" class="button primary" type="submit" ${screening.saving || (!screening.dirty && screening.apiKeyConfigured) ? "disabled" : ""}>
            ${screening.saving ? "正在保存..." : (!screening.dirty && screening.apiKeyConfigured ? "已保存" : "保存筛选配置")}
          </button>
          <button class="button" type="button" data-action="test-screening-connection" ${screening.testing ? "disabled" : ""}>
            ${screening.testing ? "测试中..." : "测试模型"}
          </button>
          ${screening.connectionStatus === "ok" ? pill("模型可用", "green") : screening.connectionStatus === "error" ? pill("模型不可用", "red") : ""}
        </div>
      </form>
      ${screening.error ? `<p class="form-error">${escapeHtml(screening.error)}</p>` : ""}
    </article>
  `;
}

async function loadLogs() {
  try {
    const data = await apiRequest(`/api/logs?after=${state.logState.cursor}`);
    if (data.events?.length) {
      state.logState.events.push(...data.events);
      if (state.logState.events.length > 500) state.logState.events = state.logState.events.slice(-500);
    }
    state.logState.cursor = data.cursor || state.logState.cursor;
    const container = document.getElementById("agent-log-events");
    if (container) {
      container.innerHTML = renderLogEvents();
      container.scrollTop = container.scrollHeight;
    }
  } catch {
    // Log polling must never interrupt the main UI.
  }
}

function renderLogEvents() {
  if (!state.logState.events.length) {
    return `<div class="log-empty">暂无日志</div>`;
  }
  return state.logState.events
    .slice(-200)
    .map((event) => `
      <div class="log-line log-${escapeHtml(event.level || "info")}">
        <span>${escapeHtml(event.timestamp || "")}</span>
        <b>${escapeHtml(event.level || "info")}</b>
        <span>${escapeHtml(event.message || "")}</span>
      </div>
    `)
    .join("");
}

function renderLogWindow() {
  return `
    <article class="settings-card panel log-window-card">
      <div class="settings-card-heading">
        <div>
          <h2>Agent 日志</h2>
          <p>显示连接、同步、筛选、识别和错误步骤。仅用于查看，不会清除任何数据。</p>
        </div>
        <button class="button" type="button" data-action="refresh-logs">刷新日志</button>
      </div>
      <div class="agent-log" id="agent-log-events">${renderLogEvents()}</div>
    </article>
  `;
}

async function loadAiSettings() {
  try {
    const data = await apiRequest("/api/ai/settings");
    state.aiState = {
      ...state.aiState,
      ...data,
      apiKeyConfigured: Boolean(data.api_key_configured ?? data.apiKeyConfigured),
      config: {...state.aiState.config, ...(data.config || {})},
      loaded: true,
      error: null,
    };
  } catch (error) {
    state.aiState = {
      ...state.aiState,
      loaded: true,
      error: error.message || "AI 配置加载失败。",
    };
  }
  render();
}

async function fetchAiModels() {
  const baseUrl = document.getElementById("ai-base-url")?.value?.trim() || state.aiState.config.base_url || "";
  const apiKey = document.getElementById("ai-api-key")?.value?.trim() || "";
  if (!baseUrl) {
    showToast("请先选择服务商或填写主模型 API Base URL。", "error");
    return;
  }
  state.aiState.fetchingModels = true;
  state.aiState.error = null;
  render();
  try {
    const data = await apiRequest("/api/ai/models", {
      method: "POST",
      body: JSON.stringify({base_url: baseUrl, api_key: apiKey}),
    });
    state.aiState.fetchingModels = false;
    state.aiState.models = data.models || [];
    if (state.aiState.models.length && !state.aiState.models.includes(state.aiState.config.model)) {
      state.aiState.config.model = state.aiState.models[0];
    }
    showToast(`获取到 ${state.aiState.models.length} 个模型`);
    render();
  } catch (error) {
    state.aiState.fetchingModels = false;
    state.aiState.error = error.message || "获取模型失败。";
    render();
    showToast(state.aiState.error, "error");
  }
}

function captureAiDraft() {
  const ai = state.aiState;
  ai.config = {
    ...ai.config,
    provider: document.getElementById("ai-provider")?.value || ai.config.provider,
    base_url: document.getElementById("ai-base-url")?.value?.trim() || ai.config.base_url,
    model: document.getElementById("ai-model")?.value || ai.config.model,
    max_chars: Number(document.getElementById("ai-max-chars")?.value || ai.config.max_chars),
    max_tokens: Number(document.getElementById("ai-max-tokens")?.value || ai.config.max_tokens),
    timeout: Number(document.getElementById("ai-timeout")?.value || ai.config.timeout),
    concurrency: Number(document.getElementById("ai-concurrency")?.value || ai.config.concurrency),
  };
  ai.draftApiKey = document.getElementById("ai-api-key")?.value || ai.draftApiKey || "";
  ai.dirty = true;
}

function captureScreeningDraft() {
  const screening = state.screeningState;
  screening.config = {
    ...screening.config,
    enabled: Boolean(document.getElementById("screening-enabled")?.checked),
    provider: document.getElementById("screening-provider")?.value || screening.config.provider,
    base_url: document.getElementById("screening-base-url")?.value?.trim() || screening.config.base_url,
    model: document.getElementById("screening-model")?.value || screening.config.model,
    max_chars: Number(document.getElementById("screening-max-chars")?.value || screening.config.max_chars),
    max_tokens: Number(document.getElementById("screening-max-tokens")?.value || screening.config.max_tokens),
    timeout: Number(document.getElementById("screening-timeout")?.value || screening.config.timeout),
    concurrency: Number(document.getElementById("screening-concurrency")?.value || screening.config.concurrency),
  };
  screening.draftApiKey = document.getElementById("screening-api-key")?.value || screening.draftApiKey || "";
  screening.dirty = true;
}

function updateApiButtonState() {
  const ai = state.aiState;
  const screening = state.screeningState;
  const aiButton = document.getElementById("ai-save-button");
  const screeningButton = document.getElementById("screening-save-button");
  if (aiButton) {
    const saved = !ai.dirty && ai.apiKeyConfigured;
    aiButton.disabled = ai.saving || saved;
    aiButton.textContent = ai.saving ? "正在保存..." : saved ? "已保存" : "保存 AI 配置";
  }
  if (screeningButton) {
    const saved = !screening.dirty && screening.apiKeyConfigured;
    screeningButton.disabled = screening.saving || saved;
    screeningButton.textContent = screening.saving ? "正在保存..." : saved ? "已保存" : "保存筛选配置";
  }
}

async function testScreeningEmails() {
  state.screeningState.sampleTesting = true;
  state.screeningState.sampleResults = null;
  render();
  try {
    const data = await apiRequest("/api/ai/screening/test-emails", {
      method: "POST",
      body: JSON.stringify({limit: 3}),
    });
    state.screeningState.sampleResults = data;
    showToast("筛选测试完成");
  } catch (error) {
    showToast(error.message || "筛选测试失败。", "error");
  } finally {
    state.screeningState.sampleTesting = false;
    render();
  }
}

async function testAnalysisEmails() {
  state.aiState.sampleTesting = true;
  state.aiState.testResults = null;
  render();
  try {
    const data = await apiRequest("/api/ai/test-emails", {
      method: "POST",
      body: JSON.stringify({limit: 3}),
    });
    state.aiState.testResults = {
      ...data,
      results: (data.results || []).map((item) => ({
        ...item,
        status: item.ok ? "ok" : "error",
        email_id: item.email?.id,
        subject: item.email?.subject,
        from_email: item.email?.from_email,
      })),
    };
    showToast("LLM 识别测试完成");
  } catch (error) {
    showToast(error.message || "LLM 识别测试失败。", "error");
  } finally {
    state.aiState.sampleTesting = false;
    render();
  }
}

function renderScreeningSampleResults() {
  const data = state.screeningState.sampleResults;
  if (!data) return "";
  return `
    <div class="ai-result-list">
      ${(data.results || []).map((item) => `
        <article class="ai-result-card">
          <div class="ai-result-header">
            <div>
              <strong>${escapeHtml(item.email?.subject || "无主题")}</strong>
              <span class="ai-result-meta">${escapeHtml(item.email?.from_email || "")}</span>
            </div>
            ${item.ok ? (item.screening?.is_relevant ? pill("相关", "green") : pill("无关", "muted")) : pill("失败", "red")}
          </div>
          ${item.ok
            ? `<p class="ai-result-summary">分类建议：${escapeHtml(item.screening?.category_hint || "unclassified")} · 置信度 ${Number(item.screening?.confidence || 0).toFixed(2)}</p>
               <p class="ai-result-next">${escapeHtml(item.screening?.reason || "")}</p>`
            : `<p class="form-error">${escapeHtml(item.error || "筛选失败")}</p>`}
        </article>
      `).join("")}
    </div>
  `;
}

async function testApiConnection(kind) {
  if (kind === "screening") captureScreeningDraft();
  else captureAiDraft();
  const target = kind === "screening" ? state.screeningState : state.aiState;
  if (target.providerChanged && !target.draftApiKey) {
    target.connectionStatus = "error";
    target.connectionError = "更换服务商后，请输入该服务商的 API Key 并先保存配置。";
    render();
    showToast(target.connectionError, "error");
    return;
  }
  target.testing = true;
  target.connectionStatus = null;
  target.connectionError = null;
  render();
  try {
    const payload = {
      base_url: target.config.base_url,
      model: target.config.model,
      api_key: target.draftApiKey || "",
      timeout: target.config.timeout,
    };
    const path = kind === "screening" ? "/api/ai/screening/test-connection" : "/api/ai/test-connection";
    const data = await apiRequest(path, {method: "POST", body: JSON.stringify(payload)});
    target.testing = false;
    target.connectionStatus = "ok";
    target.connectionError = null;
    showToast(`模型可用：${data.model} (${data.latency_ms} ms)`);
  } catch (error) {
    target.testing = false;
    target.connectionStatus = "error";
    target.connectionError = error.message || "模型不可用。";
    showToast(target.connectionError, "error");
  }
  render();
}

function applyMailUpdate(update) {
  if (!update?.email_id) return;
  const email = emailMap.get(update.email_id);
  if (!email) return;
  Object.assign(email, update.patch || {});
  const row = document.querySelector(`.mail-row[data-mail-id="${update.email_id}"]`);
  if (row) row.outerHTML = renderMailRow(email);
  if (state.selectedMailId === update.email_id) {
    const pane = document.querySelector(".mail-detail-pane");
    if (pane) pane.innerHTML = renderMailDetail(email);
  }
}

function updateBatchProgressUI(kind) {
  const isScreening = kind === "screening";
  const progress = state.batchState[isScreening ? "screeningProgress" : "analysisProgress"];
  const completed = state.batchState[isScreening ? "screeningCompleted" : "analysisCompleted"];
  const total = state.batchState[isScreening ? "screeningTotal" : "analysisTotal"];
  const running = state.batchState[isScreening ? "screening" : "analyzing"];
  const button = document.querySelector(`[data-action="${isScreening ? "run-screening-batch" : "run-analysis-batch"}"]`);
  if (!button) return;
  button.style.setProperty("--progress", `${Math.round(progress * 100)}%`);
  button.textContent = running
    ? (total ? `${isScreening ? "正在筛选" : "正在识别"} ${completed}/${total}` : `${isScreening ? "正在筛选" : "正在识别"}...`)
    : progress >= 1 ? `${isScreening ? "筛选" : "识别"}完成` : isScreening ? "开始筛选" : "开始识别";
}

async function pollAiJob(jobId, kind) {
  const isScreening = kind === "screening";
  const progressKey = isScreening ? "screeningProgress" : "analysisProgress";
  const completedKey = isScreening ? "screeningCompleted" : "analysisCompleted";
  const totalKey = isScreening ? "screeningTotal" : "analysisTotal";
  const updateCountKey = isScreening ? "screeningUpdateCount" : "analysisUpdateCount";
  const pausedKey = isScreening ? "screeningPaused" : "analysisPaused";
  while (true) {
    const job = await apiRequest(`/api/ai/jobs/${jobId}`);
    const updates = job.updates || [];
    for (const update of updates.slice(state.batchState[updateCountKey] || 0)) applyMailUpdate(update);
    state.batchState[updateCountKey] = updates.length;
    state.batchState[completedKey] = job.completed || 0;
    state.batchState[totalKey] = job.total || 0;
    state.batchState[progressKey] = job.total ? Math.max(0.04, Math.min(1, job.completed / job.total)) : 0.04;
    updateBatchProgressUI(kind);
    if (job.status === "completed") return {result: job.result || {}, paused: false};
    if (job.status === "paused") { state.batchState[pausedKey] = true; return {result: job.result || {}, paused: true}; }
    if (job.status === "failed") throw new Error(job.error || "任务失败。");
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}

async function pauseBatch(kind) {
  const jobId = state.batchState[kind === "screening" ? "screeningJobId" : "analysisJobId"];
  if (!jobId) return;
  try {
    await apiRequest(`/api/ai/jobs/${jobId}/pause`, {method: "POST", body: "{}"});
    showToast("已请求暂停，当前邮件完成后会停止");
  } catch (error) {
    showToast(error.message || "暂停失败。", "error");
  }
}

async function runScreeningBatch() {
  state.batchState.screening = true;
  state.batchState.screeningPaused = false;
  state.batchState.screeningProgress = 0.04;
  state.batchState.screeningUpdateCount = 0;
  state.batchState.error = null;
  render();
  try {
    const start = await apiRequest("/api/ai/screen/run", {method: "POST", body: JSON.stringify({mode: state.batchState.screeningMode})});
    state.batchState.screeningJobId = start.job_id;
    const outcome = await pollAiJob(start.job_id, "screening");
    const data = outcome.result;
    state.batchState.screeningResult = data;
    state.batchState.screeningProgress = outcome.paused ? state.batchState.screeningProgress : 1;
    await loadMailFromApi();
    showToast(outcome.paused ? `筛选已暂停，已保存 ${data.screened} 封` : `筛选完成：相关 ${data.relevant}，无关 ${data.irrelevant}`);
    if (!outcome.paused) setTimeout(() => { state.batchState.screeningProgress = 0; render(); }, 1600);
  } catch (error) {
    state.batchState.error = error.message || "筛选失败。";
    showToast(state.batchState.error, "error");
  } finally {
    state.batchState.screening = false;
    state.batchState.screeningJobId = null;
    render();
  }
}

async function runAnalysisBatch() {
  state.batchState.analyzing = true;
  state.batchState.analysisPaused = false;
  state.batchState.analysisProgress = 0.04;
  state.batchState.analysisUpdateCount = 0;
  state.batchState.error = null;
  render();
  try {
    const start = await apiRequest("/api/ai/analyze/run", {method: "POST", body: JSON.stringify({mode: state.batchState.analysisMode})});
    state.batchState.analysisJobId = start.job_id;
    const outcome = await pollAiJob(start.job_id, "analysis");
    const data = outcome.result;
    state.batchState.analysisResult = data;
    state.batchState.analysisProgress = outcome.paused ? state.batchState.analysisProgress : 1;
    await loadMailFromApi();
    showToast(outcome.paused ? `识别已暂停，已保存 ${data.analyzed} 封` : `识别完成：${data.analyzed} 封，失败 ${data.failed} 封`);
    if (!outcome.paused) setTimeout(() => { state.batchState.analysisProgress = 0; render(); }, 1600);
  } catch (error) {
    state.batchState.error = error.message || "识别失败。";
    showToast(state.batchState.error, "error");
  } finally {
    state.batchState.analyzing = false;
    state.batchState.analysisJobId = null;
    render();
  }
}

async function toggleEmailCompleted(mailId) {
  const email = emailMap.get(mailId);
  if (!email || !canComplete(email)) return;
  const nextCompleted = !state.completed.has(email.id);
  if (nextCompleted) state.completed.add(email.id);
  else state.completed.delete(email.id);
  saveCompleted();
  applyMailUpdate({email_id: email.id, patch: {}});
  showToast(nextCompleted ? "已标记完成" : "已取消完成", "success");
  try {
    await apiRequest("/api/emails/complete", {
      method: "POST",
      body: JSON.stringify({email_id: email.id, is_completed: nextCompleted}),
    });
  } catch (error) {
    if (nextCompleted) state.completed.delete(email.id);
    else state.completed.add(email.id);
    saveCompleted();
    applyMailUpdate({email_id: email.id, patch: {}});
    showToast(error.message || "完成状态保存失败。", "error");
  }
}

async function markEmailReviewed(mailId) {
  try {
    await apiRequest("/api/emails/review", {
      method: "POST",
      body: JSON.stringify({email_id: mailId}),
    });
    const email = emailMap.get(mailId);
    if (email) {
      email.needsReview = false;
      email.reviewReason = null;
      applyMailUpdate({email_id: mailId, patch: {}});
    }
    showToast("已标记复核完成");
  } catch (error) {
    showToast(error.message || "复核状态更新失败。", "error");
  }
}

async function rerunEmail(emailId) {
  state.rerunningEmailId = emailId;
  render();
  try {
    await apiRequest("/api/ai/analyze/email", {
      method: "POST",
      body: JSON.stringify({email_id: emailId}),
    });
    await loadMailFromApi();
    showToast("已重新识别这封邮件");
  } catch (error) {
    showToast(error.message || "重新识别失败。", "error");
  } finally {
    state.rerunningEmailId = null;
    render();
  }
}

async function submitAiForm(event) {
  event.preventDefault();
  const config = state.aiState.config;
  const payload = {
    enabled: config.enabled,
    provider: document.getElementById("ai-provider")?.value || "deepseek",
    base_url: document.getElementById("ai-base-url")?.value?.trim() || state.aiState.config.base_url || "",
    model: document.getElementById("ai-model")?.value?.trim() || state.aiState.config.model || "",
    api_key: document.getElementById("ai-api-key")?.value?.trim() || "",
    max_chars: Number(document.getElementById("ai-max-chars")?.value || 8000),
    max_tokens: Number(document.getElementById("ai-max-tokens")?.value || 1500),
    timeout: Number(document.getElementById("ai-timeout")?.value || 60),
    concurrency: Number(document.getElementById("ai-concurrency")?.value || 2),
    temperature: 0,
  };
  state.aiState.saving = true;
  state.aiState.error = null;
  render();
  try {
    await apiRequest("/api/ai/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.aiState.saving = false;
    state.aiState.dirty = false;
    state.aiState.providerChanged = false;
    showToast("AI 配置已保存");
    await loadAiSettings();
  } catch (error) {
    state.aiState.saving = false;
    state.aiState.error = error.message || "AI 配置保存失败。";
    render();
    showToast(state.aiState.error, "error");
  }
}

async function runAiTest() {
  state.aiState.testing = true;
  state.aiState.testError = null;
  state.aiState.testResults = null;
  render();
  try {
    const data = await apiRequest("/api/ai/test", {
      method: "POST",
      body: JSON.stringify({limit: 3}),
    });
    state.aiState.testing = false;
    state.aiState.testResults = data;
    showToast("3 封邮件测试完成");
    render();
  } catch (error) {
    state.aiState.testing = false;
    state.aiState.testError = error.message || "AI 测试失败。";
    render();
    showToast(state.aiState.testError, "error");
  }
}

function renderAiSettingsCard() {
  const ai = state.aiState;
  const config = ai.config;
  return `
    <article class="settings-card panel ai-settings-card">
      <div class="settings-card-heading">
        <div>
          <h2>AI 分析</h2>
          <p>支持 OpenAI、DeepSeek、Qwen、Kimi、智谱、OpenRouter、Groq、Ollama 等 OpenAI 兼容接口。API Key 只保存在 Windows 凭据管理器。</p>
        </div>
        ${ai.apiKeyConfigured ? pill("API Key 已配置", "green") : pill("未配置 API Key", "muted")}
      </div>
      <form id="ai-form" class="account-form">
        <div class="form-grid-2">
          <label class="form-field">
            <span>服务商</span>
            <select class="select" id="ai-provider">
              ${renderProviderOptions(config.provider)}
            </select>
          </label>
          <label class="form-field">
            <span>模型</span>
            <div class="inline-control">
              <input class="input" id="ai-model" list="ai-model-options" value="${escapeHtml(config.model || "")}" placeholder="获取模型或手动输入模型 ID" />
              <datalist id="ai-model-options">
                ${(ai.models || []).map((model) => `<option value="${escapeHtml(model)}"></option>`).join("")}
              </datalist>
              <button class="button" type="button" data-action="fetch-models" ${ai.fetchingModels ? "disabled" : ""}>
                ${ai.fetchingModels ? "获取中..." : "获取模型"}
              </button>
            </div>
          </label>
        </div>
        <label class="form-field">
          <span>API Base URL</span>
          <input class="input" id="ai-base-url" type="url" value="${escapeHtml(config.base_url || "")}" placeholder="https://your-provider.example/v1" />
        </label>
        <label class="form-field">
          <span>API Key</span>
          <input class="input" id="ai-api-key" type="password" value="${escapeHtml(ai.draftApiKey || "")}" placeholder="${ai.apiKeyConfigured ? "••••••••••••••••  已保存，输入新 Key 可替换" : "输入主模型 API Key"}" autocomplete="new-password" />
        </label>
        <div class="form-grid-4">
          <label class="form-field">
            <span>正文最大字符</span>
            <input class="input" id="ai-max-chars" type="number" min="100" max="50000" value="${Number(config.max_chars || 8000)}" />
          </label>
          <label class="form-field">
            <span>最大输出 Token</span>
            <input class="input" id="ai-max-tokens" type="number" min="128" max="8192" value="${Number(config.max_tokens || 1500)}" />
          </label>
          <label class="form-field">
            <span>超时时间（秒）</span>
            <input class="input" id="ai-timeout" type="number" min="5" max="300" value="${Number(config.timeout || 60)}" />
          </label>
          <label class="form-field">
            <span>并发数</span>
            <input class="input" id="ai-concurrency" type="number" min="1" max="8" value="${Number(config.concurrency || 2)}" />
          </label>
        </div>
        <div class="form-actions">
          <button id="ai-save-button" class="button primary" type="submit" ${ai.saving || (!ai.dirty && ai.apiKeyConfigured) ? "disabled" : ""}>
            ${ai.saving ? "正在保存..." : (!ai.dirty && ai.apiKeyConfigured ? "已保存" : "保存 AI 配置")}
          </button>
          <button class="button" type="button" data-action="test-ai-connection" ${ai.testing ? "disabled" : ""}>
            ${ai.testing ? "测试中..." : "测试模型"}
          </button>
          ${ai.connectionStatus === "ok" ? pill("模型可用", "green") : ai.connectionStatus === "error" ? pill("模型不可用", "red") : ""}
        </div>
      </form>
      ${
        ai.error
          ? `<p class="form-error">${escapeHtml(ai.error)}</p>`
          : ""
      }
    </article>
  `;
}

function renderAiTestResults() {
  const ai = state.aiState;
  if (ai.testing) {
    return `
      <article class="settings-card panel ai-test-results">
        <h2>测试结果</h2>
        <div class="skeleton" style="height:88px;margin-top:14px"></div>
        <div class="skeleton" style="height:88px;margin-top:10px"></div>
      </article>
    `;
  }
  if (ai.testError) {
    return `
      <article class="settings-card panel ai-test-results">
        <h2>测试结果</h2>
        <p class="form-error">${escapeHtml(ai.testError)}</p>
      </article>
    `;
  }
  if (!ai.testResults) {
    return `
      <article class="settings-card panel ai-test-results">
        <h2>测试结果</h2>
        <p>只会测试类别不为“未分类”和“广告/垃圾邮件”的最近三封邮件。测试阶段不会写入数据库。</p>
      </article>
    `;
  }

  const results = ai.testResults.results || [];
  return `
    <article class="settings-card panel ai-test-results">
      <div class="settings-card-heading">
        <div>
          <h2>测试结果</h2>
          <p>模型：${escapeHtml(ai.testResults.model || ai.config.model)} · 并发 ${ai.testResults.concurrency || 2} · 共测试 ${results.length} 封 · 未写入数据库</p>
          <p class="form-hint">筛选模型：${ai.testResults.screening_enabled ? escapeHtml(ai.testResults.screening_model || "已启用") : "未配置，直接进入主模型"}</p>

        </div>
      </div>
      <div class="ai-result-list">
        ${results.map(renderAiResult).join("")}
      </div>
    </article>
  `;
}

function renderAiResult(item) {
  if (item.status !== "ok") {
    return `
      <article class="ai-result-card">
        <div class="ai-result-header">
          <div>
            <strong>${escapeHtml(item.subject || "无主题")}</strong>
            <span class="ai-result-meta">${escapeHtml(item.from_email || "")}</span>
          </div>
          ${pill("失败", "red")}
        </div>
        <p class="form-error">${escapeHtml(item.error || "分析失败")}</p>
      </article>
    `;
  }

  const analysis = item.analysis || {};
  const companyName = analysis.company?.name || "公司未识别";
  const deadlineText = analysis.deadline
    ? (analysis.deadline.date || analysis.deadline.raw_date || "有截止时间")
    : "无";
  const interviewText = analysis.interview
    ? (analysis.interview.date || analysis.interview.raw_date || analysis.interview.round || "有面试")
    : "无";
  const linkText = analysis.primary_link?.label || analysis.primary_link?.link_type || "无";
  return `
    <article class="ai-result-card">
      <div class="ai-result-header">
        <div>
          <strong>${escapeHtml(item.subject || "无主题")}</strong>
          <span class="ai-result-meta">${escapeHtml(item.from_email || "")} · ${item.elapsed_ms} ms</span>
        </div>
        ${analysis.needs_review ? pill("需要复核", "amber") : pill("自动通过", "green")}
      </div>
      <div class="ai-result-grid">
        <span><b>分类</b>${emailCategoryPill({category: analysis.email_category})}</span>
        <span><b>公司</b>${escapeHtml(companyName)}</span>
        <span><b>DDL</b>${escapeHtml(deadlineText)}</span>
        <span><b>面试</b>${escapeHtml(interviewText)}</span>
        <span><b>主链接</b>${escapeHtml(linkText)}</span>
      </div>
      ${
        item.screening
          ? `<p class="ai-result-summary">筛选：${item.screening.is_relevant ? "通过" : "丢弃"} · ${escapeHtml(item.screening.reason || "")}</p>`
          : ""
      }
      ${
        analysis.review_reason
          ? `<p class="ai-result-summary">复核原因：${escapeHtml(analysis.review_reason)}</p>`
          : ""
      }
      <details>
        <summary>查看结构化 JSON</summary>
        <pre class="json-preview">${escapeHtml(JSON.stringify(analysis, null, 2))}</pre>
      </details>
    </article>
  `;
}

function renderCorrectionModal() {
  const modal = state.correctionModal;
  if (!modal.open) return "";
  const email = emailMap.get(modal.emailId);
  if (!email) return "";
  const field = modal.field;
  const isCategory = field === "category";
  const isDate = field === "deadline" || field === "eventDate";
  const value = field === "category"
    ? (email.category || "unclassified")
    : field === "deadline"
      ? (email.deadline || "")
      : field === "eventDate"
        ? (email.eventDate || "")
        : field === "position"
          ? (email.position || "")
          : (email.company || "");
  const titleMap = {
    category: "修改邮件类别",
    deadline: "修改截止日期",
    eventDate: "修改面试日期",
    company: "修改公司名称",
    position: "修改岗位名称",
  };
  const valueLabel = field === "company" ? "公司名称" : field === "position" ? "岗位名称" : field === "deadline" ? "截止日期" : "面试日期";
  return `
    <div class="modal-backdrop" data-modal-backdrop="true">
      <section class="correction-modal" role="dialog" aria-modal="true" aria-label="人工纠错">
        <div class="modal-header">
          <div>
            <h2>${escapeHtml(titleMap[field] || "人工纠错")}</h2>
            <p>${escapeHtml(email.subject)}</p>
          </div>
          <button class="button ghost" type="button" data-action="close-correction">✕</button>
        </div>
        <form id="correction-form" class="account-form">
          ${
            isCategory
              ? `
                <label class="form-field">
                  <span>邮件类别</span>
                  <select class="select" id="correction-value">
                    ${Object.entries(categoryMeta)
                      .map(([key, meta]) => `<option value="${key}" ${value === key ? "selected" : ""}>${escapeHtml(meta.label)}</option>`)
                      .join("")}
                  </select>
                </label>
              `
              : isDate
                ? `
                  <label class="form-field">
                    <span>${valueLabel}</span>
                    <input class="input" id="correction-value" type="date" value="${escapeHtml(value)}" />
                    <small class="form-hint">留空并保存可以清除该项。</small>
                  </label>
                `
                : `
                  <label class="form-field">
                    <span>${valueLabel}</span>
                    <input class="input" id="correction-value" type="text" value="${escapeHtml(value)}" placeholder="${field === "company" ? "输入正确的公司名称" : "输入岗位名称"}" />
                  </label>
                `
          }
          <div class="form-actions">
            <button class="button primary" type="submit">保存修改</button>
            <button class="button" type="button" data-action="close-correction">取消</button>
          </div>
        </form>
      </section>
    </div>
  `;
}

async function submitCorrection(event) {
  event.preventDefault();
  const modal = state.correctionModal;
  const value = document.getElementById("correction-value")?.value || "";
  try {
    await apiRequest("/api/emails/correct", {
      method: "POST",
      body: JSON.stringify({
        email_id: modal.emailId,
        field: modal.field,
        value,
      }),
    });
    state.correctionModal = {open: false, emailId: null, field: null, value: null};
    await loadMailFromApi();
    showToast("人工修正已保存，统计和日历已刷新");
    render();
  } catch (error) {
    showToast(error.message || "保存修正失败。", "error");
  }
}

function renderSettingsPage() {
  const accountState = state.accountState;
  const account = accountState.account;
  const connected = accountState.connected && account;

  return `
    <div class="page-header">
      <div>
        <p class="page-kicker">Preferences</p>
        <h1 class="page-title">设置</h1>
        <p class="page-subtitle">授权码只保存在 Windows 凭据管理器，不会进入数据库、日志或模型上下文。</p>
      </div>
    </div>
    <section class="settings-grid">
      <article class="settings-card panel">
        <h2>163 邮箱连接</h2>
        ${
          !accountState.loaded
            ? `<div class="empty-state" style="min-height:180px"><div><strong>正在检查连接状态</strong><span>请稍候。</span></div></div>`
            : connected
              ? `
                <p>当前邮箱已完成连接。同步默认只读取收件箱，不修改邮箱中的原始邮件。</p>
                <div class="settings-row">
                  <span>邮箱账号</span>
                  <span class="detail-meta-value">${escapeHtml(account.email)}</span>
                </div>
                <div class="settings-row">
                  <span>连接状态</span>
                  ${pill("已连接", "green")}
                </div>
                <div class="settings-row">
                  <span>已同步邮件</span>
                  <span class="mail-company">${accountState.syncResult ? accountState.syncResult.fetched : "等待同步"}</span>
                </div>
                <div class="form-actions">
                  <button class="button primary" data-action="sync-now" ${accountState.syncing ? "disabled" : ""}>
                    ${accountState.syncing
                      ? `正在${pipelineStageLabel(accountState.pipelineStage)}${
                          accountState.pipelineTotal
                            ? ` ${accountState.pipelineCompleted}/${accountState.pipelineTotal}`
                            : "..."
                        }`
                      : "同步并自动处理最近 30 天"}
                  </button>
                  <button class="button" data-action="disconnect-account">断开邮箱</button>
                </div>
                ${
                  accountState.syncResult
                    ? `<p class="form-hint">最近一次同步：获取 ${accountState.syncResult.fetched} 封，新增 ${accountState.syncResult.inserted} 封，更新 ${accountState.syncResult.updated} 封。</p>`
                    : ""
                }
              `
              : `
                <p>请输入 163 邮箱地址和客户端授权码。程序会先测试连接，成功后再把授权码保存到 Windows 凭据管理器。</p>
                <form id="account-form" class="account-form">
                  <label class="form-field">
                    <span>邮箱地址</span>
                    <input class="input" id="account-email" type="email" placeholder="yourname@163.com" autocomplete="username" required />
                  </label>
                  <label class="form-field">
                    <span>客户端授权码</span>
                    <input class="input" id="account-auth-code" type="password" placeholder="不会显示或回传授权码" autocomplete="new-password" required />
                  </label>
                  <label class="form-field">
                    <span>显示名称（可选）</span>
                    <input class="input" id="account-display-name" type="text" placeholder="例如：秋招邮箱" />
                  </label>
                  <button class="button primary" type="submit" ${accountState.connecting ? "disabled" : ""}>
                    ${accountState.connecting ? "正在测试连接..." : "测试连接并保存"}
                  </button>
                </form>
              `
        }
        ${
          accountState.error
            ? `<p class="form-error">${escapeHtml(accountState.error)}</p>`
            : ""
        }
      </article>

    <section class="section">
      <div class="panel" style="padding:16px;display:flex;align-items:center;justify-content:space-between;gap:18px">
        <div>
          <h2 class="section-title">AI 处理</h2>
          <p class="section-caption">先筛选是否与秋招相关，再对筛选通过的邮件做结构化识别。默认只处理未成功的邮件；需要重跑时在按钮左侧切换范围。</p>
          ${
            state.batchState.screeningResult
              ? `<p class="form-hint">上次筛选：相关 ${state.batchState.screeningResult.relevant} 封，无关 ${state.batchState.screeningResult.irrelevant} 封</p>`
              : ""
          }
          ${
            state.batchState.analysisResult
              ? `<p class="form-hint">上次识别：成功 ${state.batchState.analysisResult.analyzed} 封，失败 ${state.batchState.analysisResult.failed} 封</p>`
              : ""
          }
        </div>
        <div class="form-actions" style="margin-top:0">
          <select class="select" id="screening-mode" aria-label="筛选范围">
            <option value="pending" ${state.batchState.screeningMode === "pending" ? "selected" : ""}>仅未筛选（推荐）</option>
            <option value="all" ${state.batchState.screeningMode === "all" ? "selected" : ""}>全部重新筛选</option>
          </select>
          <button class="button progress-button" style="--progress:${Math.round(state.batchState.screeningProgress * 100)}%"
            data-action="run-screening-batch" ${state.batchState.screening ? "disabled" : ""}>
            ${state.batchState.screening
              ? (state.batchState.screeningTotal ? `正在筛选 ${state.batchState.screeningCompleted}/${state.batchState.screeningTotal}` : "正在筛选...")
              : state.batchState.screeningPaused ? "继续筛选" : state.batchState.screeningProgress >= 1 ? "筛选完成" : "开始筛选"}
          </button>
          ${state.batchState.screening ? `<button class="button" data-action="pause-screening">暂停</button>` : ""}
          <select class="select" id="analysis-mode" aria-label="识别范围">
            <option value="pending" ${state.batchState.analysisMode === "pending" ? "selected" : ""}>仅待识别（推荐）</option>
            <option value="company_unresolved" ${state.batchState.analysisMode === "company_unresolved" ? "selected" : ""}>仅公司未识别</option>
            <option value="all_relevant" ${state.batchState.analysisMode === "all_relevant" ? "selected" : ""}>全部相关邮件</option>
          </select>
          <button class="button primary progress-button" style="--progress:${Math.round(state.batchState.analysisProgress * 100)}%"
            data-action="run-analysis-batch" ${state.batchState.analyzing ? "disabled" : ""}>
            ${state.batchState.analyzing
              ? (state.batchState.analysisTotal ? `正在识别 ${state.batchState.analysisCompleted}/${state.batchState.analysisTotal}` : "正在识别...")
              : state.batchState.analysisPaused ? "继续识别" : state.batchState.analysisProgress >= 1 ? "识别完成" : "开始识别"}
          </button>
          ${state.batchState.analyzing ? `<button class="button" data-action="pause-analysis">暂停</button>` : ""}
        </div>
      </div>
    </section>


      ${renderScreeningSettingsCard()}
      ${renderAiSettingsCard()}
      ${renderLogWindow()}

      <article class="settings-card panel">
        <h2>关于</h2>
        <p>当前版本：Web UI 原型 v0.1。邮箱连接、最近 30 天同步和本地 SQLite 存储已经进入开发。</p>
      </article>
    </section>
  `;
}
async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
    ...options,
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `请求失败：${response.status}`);
  }
  return payload;
}

async function loadAccountState() {
  try {
    const data = await apiRequest("/api/account");
    state.accountState = {
      ...state.accountState,
      ...data,
      loaded: true,
      error: null,
    };
    await loadMailFromApi();
  } catch (error) {
    state.accountState = {
      ...state.accountState,
      loaded: true,
      connected: false,
      error: error.message || "无法连接本地后端。",
    };
  }
  render();
}

async function loadMailFromApi() {
  try {
    const data = await apiRequest("/api/emails");
    if (!Array.isArray(data.emails) || !data.emails.length) {
      return false;
    }
    const mapped = data.emails.map((mail) => ({
      ...mail,
      companyId: mail.companyId || "unassigned",
      unread: false,
    }));
    emails.splice(0, emails.length, ...mapped);
    emailMap.clear();
    mapped.forEach((mail) => emailMap.set(mail.id, mail));

    const serverCompleted = new Set(
      mapped.filter((mail) => mail.isCompleted).map((mail) => mail.id),
    );
    serverCompleted.forEach((emailId) => state.completed.add(emailId));
    const localOnlyCompleted = mapped
      .filter((mail) => !mail.isCompleted && state.completed.has(mail.id))
      .map((mail) => mail.id);
    saveCompleted();
    if (localOnlyCompleted.length) {
      apiRequest("/api/emails/complete", {
        method: "POST",
        body: JSON.stringify({email_ids: localOnlyCompleted, is_completed: true}),
      }).catch(() => {});
    }
    if (!companies.some((company) => company.id === "unassigned")) {
      companies.push({
        id: "unassigned",
        name: "待分类",
        status: "待分类",
        positionCount: 0,
        tone: "muted",
      });
    }
    return true;
  } catch {
    return false;
  }
}

async function submitAccountForm(event) {
  event.preventDefault();
  const email = document.getElementById("account-email")?.value?.trim() || "";
  const authCode = document.getElementById("account-auth-code")?.value?.trim() || "";
  const displayName = document.getElementById("account-display-name")?.value?.trim() || "";
  state.accountState.connecting = true;
  state.accountState.error = null;
  render();

  try {
    await apiRequest("/api/account/connect", {
      method: "POST",
      body: JSON.stringify({email, auth_code: authCode, display_name: displayName}),
    });
    state.accountState.connecting = false;
    showToast("163 邮箱连接成功");
    await loadAccountState();
  } catch (error) {
    state.accountState.connecting = false;
    state.accountState.error = error.message || "连接失败。";
    render();
    showToast(state.accountState.error, "error");
  }
}

function pipelineStageLabel(stage) {
  if (stage === "screening") return "筛选";
  if (stage === "analysis") return "识别";
  if (stage === "syncing") return "同步";
  return "处理";
}

async function runSyncNow() {
  state.accountState.syncing = true;
  state.accountState.error = null;
  state.accountState.pipelineStage = "syncing";
  state.accountState.pipelineCompleted = 0;
  state.accountState.pipelineTotal = 0;
  state.accountState.syncResult = null;
  render();
  try {
    const start = await apiRequest("/api/pipeline/run", {
      method: "POST",
      body: JSON.stringify({days: 30, limit: 500, chunk_size: 20}),
    });
    state.accountState.pipelineJobId = start.job_id;
    let job = null;
    while (true) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      job = await apiRequest(`/api/ai/jobs/${start.job_id}`);
      state.accountState.pipelineStage = job.stage || "syncing";
      state.accountState.pipelineCompleted = job.completed || 0;
      state.accountState.pipelineTotal = job.total || 0;
      render();
      if (job.status === "completed" || job.status === "paused") break;
      if (job.status === "failed") throw new Error(job.error || "同步处理流水线失败。");
    }
    state.accountState.syncing = false;
    state.accountState.pipelineJobId = null;
    state.accountState.syncResult = job?.result?.sync || null;
    showToast("同步、筛选和识别流水线已完成");
    await loadMailFromApi();
    await loadAccountState();
  } catch (error) {
    state.accountState.syncing = false;
    state.accountState.pipelineJobId = null;
    state.accountState.error = error.message || "同步处理流水线失败。";
    render();
    showToast(state.accountState.error, "error");
  }
}

async function disconnectAccount() {
  if (!window.confirm("确定断开邮箱并删除本机保存的授权码吗？")) return;
  try {
    await apiRequest("/api/account/disconnect", {method: "POST", body: "{}"});
    state.accountState = {
      loaded: true,
      connected: false,
      account: null,
      folders: [],
      error: null,
      connecting: false,
      syncing: false,
      syncResult: null,
    };
    showToast("邮箱已断开");
    render();
  } catch (error) {
    state.accountState.error = error.message || "断开失败。";
    render();
    showToast(state.accountState.error, "error");
  }
}

function handleClick(event) {
  if (event.target.classList?.contains("modal-backdrop")) {
    state.correctionModal = {open: false, emailId: null, field: null, value: null};
    render();
    return;
  }
  if (event.target.closest("[data-correct-field]")) return;
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;

  if (action === "navigate") {
    navigate(target.dataset.page);
    return;
  }

  if (action === "filter-category") {
    navigate("mail", { category: target.dataset.category, selectedCompany: "all" });
    return;
  }

  if (action === "set-scope") {
    state.scope = target.dataset.scope;
    render();
    return;
  }

  if (action === "set-company") {
    state.selectedCompany = state.selectedCompany === target.dataset.companyId ? "all" : target.dataset.companyId;
    render();
    return;
  }

  if (action === "select-mail") {
    selectMailInPlace(target.dataset.mailId);
    return;
  }

  if (action === "mail-scroll-top") {
    const list = document.querySelector(".mail-list");
    if (list) list.scrollTo({top: 0, behavior: "smooth"});
    state.mailListScrollTop = 0;
    return;
  }

  if (action === "open-mail" || action === "calendar-open-mail") {
    navigate("mail", { mailId: target.dataset.mailId });
    return;
  }

  if (action === "toggle-complete") {
    toggleEmailCompleted(target.dataset.mailId);
    return;
  }

  if (action === "open-company") {
    state.companyDrawerId = target.dataset.companyId;
    render();
    return;
  }

  if (action === "close-company") {
    state.companyDrawerId = null;
    render();
    return;
  }

  if (action === "timeline-mail") {
    state.selectedMailId = target.dataset.mailId;
    state.companyDrawerId = null;
    navigate("mail", { mailId: target.dataset.mailId });
    return;
  }

  if (action === "calendar-prev") {
    state.calendarMonth = new Date(state.calendarMonth.getFullYear(), state.calendarMonth.getMonth() - 1, 1);
    render();
    return;
  }

  if (action === "calendar-next") {
    state.calendarMonth = new Date(state.calendarMonth.getFullYear(), state.calendarMonth.getMonth() + 1, 1);
    render();
    return;
  }

  if (action === "calendar-today") {
    const now = new Date();
    state.calendarMonth = new Date(now.getFullYear(), now.getMonth(), 1);
    state.selectedCalendarDate = formatDate(now);
    render();
    return;
  }

  if (action === "select-calendar-day") {
    state.selectedCalendarDate = target.dataset.date;
    render();
    return;
  }

  if (action === "close-correction") {
    state.correctionModal = {open: false, emailId: null, field: null, value: null};
    render();
    return;
  }

  if (action === "edit-deadline") {
    state.correctionModal = {open: true, emailId: target.dataset.mailId, field: "deadline", value: null};
    render();
    return;
  }

  if (action === "test-screening-emails") {
    testScreeningEmails();
    return;
  }

  if (action === "test-analysis-emails") {
    testAnalysisEmails();
    return;
  }

  if (action === "test-ai-connection") {
    testApiConnection("ai");
    return;
  }

  if (action === "test-screening-connection") {
    testApiConnection("screening");
    return;
  }

  if (action === "pause-screening") {
    pauseBatch("screening");
    return;
  }

  if (action === "pause-analysis") {
    pauseBatch("analysis");
    return;
  }

  if (action === "run-screening-batch") {
    runScreeningBatch();
    return;
  }

  if (action === "run-analysis-batch") {
    runAnalysisBatch();
    return;
  }

  if (action === "rerun-email") {
    rerunEmail(target.dataset.mailId);
    return;
  }

  if (action === "mark-reviewed") {
    markEmailReviewed(target.dataset.mailId);
    return;
  }

  if (action === "fetch-screening-models") {
    fetchScreeningModels();
    return;
  }

  if (action === "fetch-models") {
    fetchAiModels();
    return;
  }

  if (action === "test-ai") {
    runAiTest();
    return;
  }

  if (action === "sync-now") {
    runSyncNow();
    return;
  }

  if (action === "disconnect-account") {
    disconnectAccount();
    return;
  }

  if (action === "open-original") {
    showToast("原型阶段暂未接入 163 原文链接", "info");
    return;
  }

  if (action === "refresh-logs") {
    loadLogs();
    return;
  }

  if (action === "backup-database") {
    backupDatabase();
    return;
  }
}

function rerenderPreservingFocus() {
  const active = document.activeElement;
  const activeId = active?.id;
  const selectionStart = active?.selectionStart;
  const selectionEnd = active?.selectionEnd;
  render();
  if (!activeId) return;
  const next = document.getElementById(activeId);
  if (!next) return;
  next.focus();
  if (typeof selectionStart === "number" && next.setSelectionRange) {
    next.setSelectionRange(selectionStart, selectionEnd);
  }
}

function handleChange(event) {
  const target = event.target;
  if (target.id === "date-start") {
    state.dateStart = target.value;
    if (state.dateStart > state.dateEnd) state.dateEnd = state.dateStart;
    saveDateRange();
    render();
    return;
  }
  if (target.id === "date-end") {
    state.dateEnd = target.value;
    if (state.dateEnd < state.dateStart) state.dateStart = state.dateEnd;
    saveDateRange();
    render();
    return;
  }
  if (target.id === "category-filter") {
    state.category = target.value;
    render();
    return;
  }
  if (target.id === "setting-dailyBrief") {
    state.settings.dailyBrief = target.checked;
    showToast("设置已更新");
    return;
  }
  if (target.id === "setting-notifications") {
    state.settings.notifications = target.checked;
    showToast("设置已更新");
    return;
  }
  if (target.id === "ai-provider" || target.id === "screening-provider") {
    const isAi = target.id.startsWith("ai-");
    const targetState = isAi ? state.aiState : state.screeningState;
    const previousProvider = targetState.config.provider;
    if (isAi) captureAiDraft();
    else captureScreeningDraft();
    const preset = providerPresets[target.value];
    if (preset) {
      targetState.config.provider = target.value;
      if (preset.baseUrl) targetState.config.base_url = preset.baseUrl;
      targetState.models = [];
      targetState.dirty = true;
      targetState.providerChanged = previousProvider !== target.value;
      if (targetState.providerChanged) {
        targetState.apiKeyConfigured = false;
        targetState.draftApiKey = "";
      }
    }
    render();
    return;
  }
  if (target.id === "ai-model" || target.id === "screening-model") {
    if (target.id.startsWith("ai-")) captureAiDraft();
    else captureScreeningDraft();
    updateApiButtonState();
    return;
  }
  if (target.id === "screening-mode") {
    state.batchState.screeningMode = target.value;
    return;
  }
  if (target.id === "analysis-mode") {
    state.batchState.analysisMode = target.value;
    return;
  }
  if (target.id === "setting-bodyToModel") {
    state.settings.bodyToModel = target.checked;
    showToast("隐私设置已更新");
  }
}

function handleScroll(event) {
  if (event.target?.classList?.contains("mail-list")) {
    state.mailListScrollTop = event.target.scrollTop;
  }
}

function handleInput(event) {
  if (event.target.id?.startsWith("ai-")) {
    captureAiDraft();
    updateApiButtonState();
    return;
  }
  if (event.target.id?.startsWith("screening-")) {
    captureScreeningDraft();
    updateApiButtonState();
    return;
  }
  if (event.target.id === "company-search") {
    state.search = event.target.value;
    if (!searchComposing) rerenderPreservingFocus();
  }
}

function handleCompositionStart(event) {
  if (event.target?.id === "company-search") {
    searchComposing = true;
  }
}

function handleCompositionEnd(event) {
  if (event.target?.id !== "company-search") return;
  searchComposing = false;
  state.search = event.target.value;
  rerenderPreservingFocus();
}

function handleDoubleClick(event) {
  const target = event.target.closest("[data-correct-field]");
  if (!target) return;
  const email = emailMap.get(target.dataset.mailId);
  if (!email) return;
  state.correctionModal = {
    open: true,
    emailId: email.id,
    field: target.dataset.correctField,
    value: target.dataset.correctField === "category" ? email.category : email.deadline,
  };
  render();
}

function handleKeydown(event) {
  if (event.key === "Escape" && state.companyDrawerId) {
    state.companyDrawerId = null;
    render();
    return;
  }
  if (event.key === "Enter" && event.target?.dataset?.action === "select-calendar-day") {
    state.selectedCalendarDate = event.target.dataset.date;
    render();
    return;
  }
  if (event.key === "Enter" && event.target?.dataset?.action === "select-mail") {
    selectMailInPlace(event.target.dataset.mailId);
  }
}

function handleSubmit(event) {
  if (event.target?.id === "account-form") {
    submitAccountForm(event);
    return;
  }
  if (event.target?.id === "screening-form") {
    submitScreeningForm(event);
    return;
  }
  if (event.target?.id === "ai-form") {
    submitAiForm(event);
    return;
  }
  if (event.target?.id === "correction-form") {
    submitCorrection(event);
  }
}

function startLogPolling() {
  if (state.logState.timer) return;
  loadLogs();
  state.logState.timer = window.setInterval(loadLogs, 1500);
}

async function init() {
  render();
  startLogPolling();
  await loadAccountState();
  await loadScreeningSettings();
  await loadAiSettings();
}

root.addEventListener("click", handleClick);
root.addEventListener("submit", handleSubmit);
root.addEventListener("change", handleChange);
root.addEventListener("input", handleInput);
root.addEventListener("scroll", handleScroll, true);
root.addEventListener("compositionstart", handleCompositionStart);
root.addEventListener("compositionend", handleCompositionEnd);
root.addEventListener("dblclick", handleDoubleClick);
document.addEventListener("keydown", handleKeydown);
window.addEventListener("hashchange", () => {
  window.scrollTo({top: 0, behavior: "auto"});
  state.page = getInitialPage();
  render();
});

window.addEventListener("storage", (event) => {
  if (event.key !== completedStorageKey) return;
  state.completed = loadCompleted();
  render();
});

init();
