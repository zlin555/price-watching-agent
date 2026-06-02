const API_BASE = "http://127.0.0.1:8000";
const token = localStorage.getItem("pricepilot_token");
const phone = localStorage.getItem("pricepilot_phone");

const watchList = document.querySelector("#watch-list");
const detailTitle = document.querySelector("#detail-title");
const detailStatus = document.querySelector("#detail-status");
const detailChart = document.querySelector("#detail-chart");
const detailMeta = document.querySelector("#detail-meta");
const userPhone = document.querySelector("#user-phone");
const panelPhone = document.querySelector("#panel-phone");
const panelWatchCount = document.querySelector("#panel-watch-count");
const panelStatus = document.querySelector("#panel-status");
const newWatchForm = document.querySelector("#new-watch-form");
const watchMessage = document.querySelector("#watch-message");
const userMenuButton = document.querySelector("#user-menu-button");
const userPanel = document.querySelector("#user-panel");
const notificationPhoneInput = document.querySelector("#notification-phone");
const settingsMessage = document.querySelector("#settings-message");
const passwordMessage = document.querySelector("#password-message");
const headerAvatar = document.querySelector("#header-avatar");
const panelAvatar = document.querySelector("#panel-avatar");
const refreshButton = document.querySelector("#refresh-watch");

let watches = [];
let selectedWatchId = null;
let usingLocalDemo = token && token.startsWith("local_");

if (!token) {
  window.location.href = "auth.html";
}

userPhone.textContent = phone || "已登录用户";
panelPhone.textContent = phone || "已登录用户";
notificationPhoneInput.value = localStorage.getItem("pricepilot_notification_phone") || phone || "";
loadSavedAvatar();
loadProfile();

function apiUrl(path) {
  const separator = path.includes("?") ? "&" : "?";
  return `${API_BASE}${path}${separator}token=${encodeURIComponent(token)}`;
}

async function loadWatches() {
  if (usingLocalDemo) {
    watches = getLocalWatches();
    renderWatches();
    if (watches.length > 0) {
      selectWatch(selectedWatchId || watches[0].id);
    } else {
      renderEmptyDetail();
    }
    return;
  }

  const response = await fetch(apiUrl("/watches"));
  watches = await response.json();
  renderWatches();

  if (watches.length > 0) {
    selectWatch(selectedWatchId || watches[0].id);
  } else {
    renderEmptyDetail();
  }
}

function renderWatches() {
  panelWatchCount.textContent = watches.length;
  panelStatus.textContent = watches.some((watch) => watch.status === "failed") ? "Needs attention" : "Active";
  watchList.innerHTML = "";

  watches.forEach((watch) => {
    const item = document.createElement("li");
    item.className = watch.id === selectedWatchId ? "active" : "";

    const infoButton = document.createElement("button");
    infoButton.className = "watch-select";
    infoButton.type = "button";
    infoButton.innerHTML = `
      <strong>${watch.title}</strong>
      <span>${watch.target}</span>
      <span>${watch.check_interval_minutes || 60} 分钟检索一次 · ${watch.status || "idle"}</span>
    `;
    infoButton.addEventListener("click", () => selectWatch(watch.id));

    const deleteButton = document.createElement("button");
    deleteButton.className = "delete-button";
    deleteButton.type = "button";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => deleteWatch(watch.id));

    const price = document.createElement("b");
    price.textContent = watch.current_price ? `$${watch.current_price}` : "待抓取";

    item.append(infoButton, price, deleteButton);
    watchList.appendChild(item);
  });
}

async function selectWatch(watchId) {
  selectedWatchId = watchId;
  const watch = watches.find((item) => item.id === watchId);
  if (!watch) {
    renderEmptyDetail();
    return;
  }

  let history = getLocalHistory(watch);
  if (!usingLocalDemo) {
    const response = await fetch(apiUrl(`/watches/${watchId}/history`));
    history = await response.json();
  }
  const prices = history.map((item) => item.price);
  const maxPrice = Math.max(...prices, watch.target_price, 1);

  detailTitle.textContent = watch.title;
  detailStatus.textContent = describeDirection(watch.direction, watch.target_price);
  detailStatus.classList.add("success");
  detailChart.innerHTML = prices
    .map((price) => `<span style="height: ${Math.max((price / maxPrice) * 92, 14)}%" title="$${price}"></span>`)
    .join("");
  detailMeta.innerHTML = `
    <span>当前价 ${watch.current_price ? `$${watch.current_price}` : "待抓取"}</span>
    <span>目标价 $${watch.target_price}</span>
    <span>${watch.check_interval_minutes || 60} 分钟检索一次</span>
    <span>下次检索 ${formatTime(watch.next_check_at)}</span>
    <span>${watch.target}</span>
  `;
  renderWatches();
}

function renderEmptyDetail() {
  selectedWatchId = null;
  detailTitle.textContent = "暂无追踪任务";
  detailStatus.textContent = "等待添加";
  detailChart.innerHTML = "";
  detailMeta.innerHTML = "<span>请先新增一个跟踪链接或股票代码。</span>";
}

function describeDirection(direction, targetPrice) {
  const labels = {
    below: `低于 $${targetPrice} 提醒`,
    above: `高于 $${targetPrice} 提醒`,
    change: "明显波动提醒",
  };
  return labels[direction] || "提醒已开启";
}

async function deleteWatch(watchId) {
  if (usingLocalDemo) {
    localStorage.setItem("pricepilot_watches", JSON.stringify(getLocalWatches().filter((watch) => watch.id !== watchId)));
    if (selectedWatchId === watchId) {
      selectedWatchId = null;
    }
    await loadWatches();
    return;
  }

  await fetch(apiUrl(`/watches/${watchId}`), { method: "DELETE" });
  if (selectedWatchId === watchId) {
    selectedWatchId = null;
  }
  await loadWatches();
}

newWatchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  watchMessage.textContent = "正在添加...";

  const payload = {
    title: document.querySelector("#watch-title").value.trim(),
    target: document.querySelector("#watch-target").value.trim(),
    target_price: Number(document.querySelector("#watch-price").value),
    direction: document.querySelector("#watch-direction").value,
    check_interval_minutes: Number(document.querySelector("#watch-interval").value),
  };

  if (usingLocalDemo) {
    const localWatches = getLocalWatches();
    const watch = {
      ...payload,
      id: Date.now(),
      owner_phone: phone,
      contact: phone,
      current_price: Number((payload.target_price * 1.08).toFixed(2)),
      created_at: new Date().toISOString(),
      last_checked_at: new Date().toISOString(),
      next_check_at: new Date(Date.now() + payload.check_interval_minutes * 60 * 1000).toISOString(),
      status: "ok",
    };
    localWatches.push(watch);
    localStorage.setItem("pricepilot_watches", JSON.stringify(localWatches));
    selectedWatchId = watch.id;
    watchMessage.textContent = "已添加到价格看板";
    await loadWatches();
    return;
  }

  const response = await fetch(apiUrl("/watches"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const watch = await response.json();
  selectedWatchId = watch.id;
  watchMessage.textContent = "已添加到价格看板";
  await loadWatches();
});

document.querySelectorAll(".side-link").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".side-link").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll("[data-view-panel]").forEach((panel) => panel.classList.add("hidden"));
    button.classList.add("active");
    document.querySelector(`[data-view-panel="${button.dataset.view}"]`).classList.remove("hidden");
  });
});

document.querySelector(".logout-button").addEventListener("click", () => {
  localStorage.removeItem("pricepilot_token");
  localStorage.removeItem("pricepilot_phone");
  window.location.href = "index.html";
});

loadWatches().catch(() => {
  usingLocalDemo = true;
  loadWatches();
});

function getLocalWatches() {
  const saved = localStorage.getItem("pricepilot_watches");
  if (saved) {
    return JSON.parse(saved);
  }

  const seed = [
    {
      id: 1,
      owner_phone: phone,
      title: "MacBook Air",
      target: "https://example.com/product/macbook-air",
      target_price: 899,
      direction: "below",
      check_interval_minutes: 60,
      contact: phone,
      current_price: 849,
      created_at: new Date().toISOString(),
      last_checked_at: new Date().toISOString(),
      next_check_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
      status: "ok",
    },
    {
      id: 2,
      owner_phone: phone,
      title: "ORD 到 SFO 机票",
      target: "https://example.com/flights/ord-sfo",
      target_price: 280,
      direction: "below",
      check_interval_minutes: 120,
      contact: phone,
      current_price: 318,
      created_at: new Date().toISOString(),
      last_checked_at: new Date().toISOString(),
      next_check_at: new Date(Date.now() + 120 * 60 * 1000).toISOString(),
      status: "ok",
    },
    {
      id: 3,
      owner_phone: phone,
      title: "NVDA",
      target: "NVDA",
      target_price: 150,
      direction: "above",
      check_interval_minutes: 30,
      contact: phone,
      current_price: 143.2,
      created_at: new Date().toISOString(),
      last_checked_at: new Date().toISOString(),
      next_check_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
      status: "ok",
    },
  ];
  localStorage.setItem("pricepilot_watches", JSON.stringify(seed));
  return seed;
}

function getLocalHistory(watch) {
  const current = Number(watch.current_price || watch.target_price);
  return [1.16, 1.1, 1.04, 0.98, 1.02, 1].map((factor) => ({
    checked_at: new Date().toISOString(),
    price: Number((current * factor).toFixed(2)),
  }));
}

function formatTime(value) {
  if (!value) {
    return "待安排";
  }
  return new Date(value).toLocaleString();
}

userMenuButton.addEventListener("click", (event) => {
  event.stopPropagation();
  userPanel.classList.toggle("hidden");
  userMenuButton.setAttribute("aria-expanded", String(!userPanel.classList.contains("hidden")));
});

userPanel.addEventListener("click", (event) => {
  event.stopPropagation();
});

document.addEventListener("click", () => {
  userPanel.classList.add("hidden");
  userMenuButton.setAttribute("aria-expanded", "false");
});

document.querySelector("#avatar-upload").addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (!file) {
    return;
  }
  const reader = new FileReader();
  reader.addEventListener("load", async () => {
    localStorage.setItem("pricepilot_avatar", reader.result);
    setAvatar(reader.result);
    if (!usingLocalDemo) {
      await fetch(apiUrl("/profile"), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ avatar_data_url: reader.result }),
      });
    }
  });
  reader.readAsDataURL(file);
});

document.querySelector("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  settingsMessage.textContent = "正在保存...";
  localStorage.setItem("pricepilot_notification_phone", notificationPhoneInput.value.trim());
  if (!usingLocalDemo) {
    await fetch(apiUrl("/profile"), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notification_phone: notificationPhoneInput.value.trim() }),
    });
  }
  settingsMessage.textContent = "已保存";
});

document.querySelector("#password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  passwordMessage.textContent = "正在修改...";
  if (usingLocalDemo) {
    passwordMessage.textContent = "Demo 模式已记录修改";
    return;
  }
  const response = await fetch(apiUrl("/profile/password"), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      current_password: document.querySelector("#current-password").value,
      new_password: document.querySelector("#new-password").value,
    }),
  });
  const data = await response.json();
  passwordMessage.textContent = response.ok ? "密码已修改" : data.detail;
});

refreshButton.addEventListener("click", async () => {
  if (!selectedWatchId) {
    return;
  }
  refreshButton.textContent = "检索中...";
  if (!usingLocalDemo) {
    await fetch(apiUrl(`/watches/${selectedWatchId}/refresh`), { method: "POST" });
  }
  await loadWatches();
  refreshButton.textContent = "立即检索";
});

function loadSavedAvatar() {
  const savedAvatar = localStorage.getItem("pricepilot_avatar");
  if (savedAvatar) {
    setAvatar(savedAvatar);
  }
}

function setAvatar(dataUrl) {
  [headerAvatar, panelAvatar].forEach((avatar) => {
    avatar.textContent = "";
    avatar.style.backgroundImage = `url("${dataUrl}")`;
    avatar.style.backgroundSize = "cover";
    avatar.style.backgroundPosition = "center";
  });
}

async function loadProfile() {
  if (usingLocalDemo) {
    return;
  }
  try {
    const response = await fetch(apiUrl("/profile"));
    const profile = await response.json();
    if (!response.ok) {
      return;
    }
    userPhone.textContent = profile.phone;
    panelPhone.textContent = profile.phone;
    notificationPhoneInput.value = profile.notification_phone || profile.phone;
    if (profile.avatar_data_url) {
      setAvatar(profile.avatar_data_url);
    }
  } catch {
    usingLocalDemo = true;
  }
}
