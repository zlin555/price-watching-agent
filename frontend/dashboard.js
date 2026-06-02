const API_BASE =
  window.PRICEPILOT_API_BASE ||
  localStorage.getItem("pricepilot_api_base") ||
  "https://zlin329-price-wtaching-agent.hf.space";
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
const previewPriceButton = document.querySelector("#preview-price");
const previewStatus = document.querySelector("#preview-status");
const priceCandidates = document.querySelector("#price-candidates");
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
let selectedPriceCandidate = null;
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
  if (prices.length === 0) {
    detailTitle.textContent = watch.title;
    detailStatus.textContent = watch.last_error ? "检索失败" : "等待检索";
    detailChart.innerHTML = "";
    detailMeta.innerHTML = `
      <span>当前价 待抓取</span>
      <span>目标价 $${watch.target_price}</span>
      <span>${watch.check_interval_minutes || 60} 分钟检索一次</span>
      <span>${watch.last_error || watch.target}</span>
    `;
    const intervalInput = document.querySelector("#detail-interval");
    if (intervalInput) {
      intervalInput.value = watch.check_interval_minutes || 60;
    }
    renderWatches();
    return;
  }
  const maxPrice = Math.max(...prices, watch.target_price, 1);

  detailTitle.textContent = watch.title;
  detailStatus.textContent = describeDirection(watch.direction, watch.target_price);
  detailStatus.classList.add("success");
  const intervalInput = document.querySelector("#detail-interval");
  if (intervalInput) {
    intervalInput.value = watch.check_interval_minutes || 60;
  }
  detailChart.innerHTML = prices
    .map((price) => `<span style="height: ${Math.max((price / maxPrice) * 92, 14)}%" title="$${price}"></span>`)
    .join("");
  detailMeta.innerHTML = `
    <span>当前价 ${watch.current_price ? `$${watch.current_price}` : "待抓取"}</span>
    <span>目标价 $${watch.target_price}</span>
    <span>${watch.check_interval_minutes || 60} 分钟检索一次</span>
    <span>下次检索 ${formatTime(watch.next_check_at)}</span>
    <span>来源 ${watch.extraction_key || watch.extraction_strategy || "自动选择"}</span>
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

previewPriceButton.addEventListener("click", async () => {
  const target = document.querySelector("#watch-target").value.trim();
  selectedPriceCandidate = null;
  previewStatus.textContent = "正在识别页面里的价格...";
  priceCandidates.classList.add("hidden");
  priceCandidates.innerHTML = "<legend>候选价格</legend>";

  let candidates = getLocalPriceCandidates(target);
  let error = "";

  if (!usingLocalDemo) {
    try {
      const response = await fetch(`${API_BASE}/extract/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target }),
      });
      const data = await response.json();
      candidates = data.candidates || [];
      error = data.error || "";
    } catch {
      usingLocalDemo = true;
    }
  }

  if (candidates.length === 0) {
    previewStatus.textContent = error || "没有识别到候选价格，可以换链接或直接保存为待检索任务";
    return;
  }

  priceCandidates.classList.remove("hidden");
  candidates.forEach((candidate, index) => {
    const option = document.createElement("label");
    option.className = "candidate-option";
    option.innerHTML = `
      <input type="radio" name="price-candidate" value="${index}" ${index === 0 ? "checked" : ""}>
      <span>
        <strong>$${candidate.price}</strong>
        <b>${Math.round((candidate.confidence || 0) * 100)}% confidence</b>
        <em>${candidate.strategy}${candidate.selector ? ` · ${candidate.selector}` : ""}</em>
        <em>刷新来源 ${candidate.key || "auto"}</em>
        <small>${candidate.snippet || candidate.label}</small>
      </span>
    `;
    option.querySelector("input").addEventListener("change", () => {
      selectedPriceCandidate = candidate;
      document.querySelector("#watch-price").value = candidate.price;
    });
    priceCandidates.appendChild(option);
  });

  selectedPriceCandidate = candidates[0];
  document.querySelector("#watch-price").value = candidates[0].price;
  previewStatus.textContent = `识别到 ${candidates.length} 个候选价格，请确认要追踪哪一个`;
});

newWatchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  watchMessage.textContent = "正在添加...";

  const payload = {
    title: document.querySelector("#watch-title").value.trim(),
    target: document.querySelector("#watch-target").value.trim(),
    target_price: Number(document.querySelector("#watch-price").value),
    direction: document.querySelector("#watch-direction").value,
    check_interval_minutes: Number(document.querySelector("#watch-interval").value),
    extraction_key: selectedPriceCandidate?.key || null,
    extraction_strategy: selectedPriceCandidate?.strategy || null,
    extraction_selector: selectedPriceCandidate?.selector || null,
    extraction_label: selectedPriceCandidate?.label || null,
    extraction_confidence: selectedPriceCandidate?.confidence || null,
  };

  if (usingLocalDemo) {
    const localWatches = getLocalWatches();
    const watch = {
      ...payload,
      id: Date.now(),
      owner_phone: phone,
      contact: phone,
      current_price: selectedPriceCandidate ? Number(selectedPriceCandidate.price) : null,
      extraction_key: payload.extraction_key,
      extraction_strategy: payload.extraction_strategy,
      extraction_selector: payload.extraction_selector,
      extraction_label: payload.extraction_label,
      extraction_confidence: payload.extraction_confidence,
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

document.querySelectorAll(".panel-action-button").forEach((button) => {
  button.addEventListener("click", () => {
    const sectionId = button.dataset.panelSection;
    document.querySelectorAll(".panel-form").forEach((section) => {
      section.classList.toggle("hidden", section.id !== sectionId);
    });
    document.querySelectorAll(".panel-action-button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
  });
});

document.querySelector("#phone-section").addEventListener("submit", async (event) => {
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

document.querySelector("#password-section").addEventListener("submit", async (event) => {
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
  if (usingLocalDemo) {
    const updated = getLocalWatches().map((watch) => {
      if (watch.id !== selectedWatchId) {
        return watch;
      }
      const candidates = getLocalPriceCandidates(watch.target);
      const candidate =
        candidates.find((item) => item.key === watch.extraction_key) ||
        candidates.find((item) => item.strategy === watch.extraction_strategy && item.selector === watch.extraction_selector) ||
        candidates[0];
      return {
        ...watch,
        current_price: candidate ? Number(candidate.price) : watch.current_price,
        last_checked_at: new Date().toISOString(),
        next_check_at: new Date(Date.now() + (watch.check_interval_minutes || 60) * 60 * 1000).toISOString(),
        status: candidate ? "ok" : "failed",
        last_error: candidate ? null : "No matching candidate found",
        last_candidates: candidates,
      };
    });
    localStorage.setItem("pricepilot_watches", JSON.stringify(updated));
  } else {
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

const detailIntervalInput = document.querySelector("#detail-interval");
const priceIntervalForm = document.querySelector("#price-interval-form");
const storeWatchForm = document.querySelector("#store-watch-form");
const storeWatchList = document.querySelector("#store-watch-list");
const storeMessage = document.querySelector("#store-message");
const storeDetailTitle = document.querySelector("#store-detail-title");
const storeDetailStatus = document.querySelector("#store-detail-status");
const storeDetailMeta = document.querySelector("#store-detail-meta");
const storeDetailIntervalInput = document.querySelector("#store-detail-interval");
const storeIntervalForm = document.querySelector("#store-interval-form");
const refreshStoreButton = document.querySelector("#refresh-store-watch");
const productList = document.querySelector("#product-list");

let storeWatches = [];
let selectedStoreWatchId = null;

priceIntervalForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedWatchId) {
    return;
  }
  const minutes = Number(detailIntervalInput.value);
  if (usingLocalDemo) {
    const updated = getLocalWatches().map((watch) =>
      watch.id === selectedWatchId
        ? {
            ...watch,
            check_interval_minutes: minutes,
            next_check_at: new Date(Date.now() + minutes * 60 * 1000).toISOString(),
          }
        : watch
    );
    localStorage.setItem("pricepilot_watches", JSON.stringify(updated));
    await loadWatches();
    return;
  }
  await fetch(apiUrl(`/watches/${selectedWatchId}/interval`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ check_interval_minutes: minutes }),
  });
  await loadWatches();
});

async function loadStoreWatches() {
  if (usingLocalDemo) {
    storeWatches = getLocalStoreWatches();
    renderStoreWatches();
    if (storeWatches.length > 0) {
      selectStoreWatch(selectedStoreWatchId || storeWatches[0].id);
    }
    return;
  }

  const response = await fetch(apiUrl("/store-watches"));
  storeWatches = await response.json();
  renderStoreWatches();
  if (storeWatches.length > 0) {
    selectStoreWatch(selectedStoreWatchId || storeWatches[0].id);
  }
}

function renderStoreWatches() {
  storeWatchList.innerHTML = "";
  storeWatches.forEach((watch) => {
    const item = document.createElement("li");
    item.className = watch.id === selectedStoreWatchId ? "active" : "";

    const infoButton = document.createElement("button");
    infoButton.className = "watch-select";
    infoButton.type = "button";
    infoButton.innerHTML = `
      <strong>${watch.title}</strong>
      <span>${watch.store_url}</span>
      <span>${watch.check_interval_minutes} 分钟扫描一次 · ${watch.status}</span>
    `;
    infoButton.addEventListener("click", () => selectStoreWatch(watch.id));

    const score = document.createElement("b");
    score.textContent = `${watch.min_score}+`;

    const deleteButton = document.createElement("button");
    deleteButton.className = "delete-button";
    deleteButton.type = "button";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => deleteStoreWatch(watch.id));

    item.append(infoButton, score, deleteButton);
    storeWatchList.appendChild(item);
  });
}

async function selectStoreWatch(watchId) {
  selectedStoreWatchId = watchId;
  const watch = storeWatches.find((item) => item.id === watchId);
  if (!watch) {
    return;
  }

  let products = getLocalProducts(watch);
  if (!usingLocalDemo) {
    const response = await fetch(apiUrl(`/store-watches/${watchId}/products`));
    products = await response.json();
  }

  storeDetailTitle.textContent = watch.title;
  storeDetailStatus.textContent = `${watch.min_score}+ 分触发提醒`;
  storeDetailStatus.classList.add("success");
  storeDetailIntervalInput.value = watch.check_interval_minutes;
  storeDetailMeta.innerHTML = `
    <span>关键词 ${watch.keywords || "用户画像"}</span>
    <span>下次扫描 ${formatTime(watch.next_check_at)}</span>
    <span>${watch.store_url}</span>
  `;
  productList.innerHTML = products
    .map(
      (product) => `
        <li class="${product.matched ? "matched" : ""}">
          <div class="product-thumb">${product.image_url ? `<img src="${product.image_url}" alt="">` : "No image"}</div>
          <strong>${product.title}</strong>
          <span>${product.price ? `$${product.price}` : "价格待识别"}</span>
          <b>${product.score}/100</b>
          <a href="${product.url}" target="_blank" rel="noreferrer">打开商品</a>
        </li>
      `
    )
    .join("");
  renderStoreWatches();
}

async function deleteStoreWatch(watchId) {
  if (usingLocalDemo) {
    localStorage.setItem(
      "pricepilot_store_watches",
      JSON.stringify(getLocalStoreWatches().filter((watch) => watch.id !== watchId))
    );
    selectedStoreWatchId = null;
    await loadStoreWatches();
    return;
  }
  await fetch(apiUrl(`/store-watches/${watchId}`), { method: "DELETE" });
  selectedStoreWatchId = null;
  await loadStoreWatches();
}

storeWatchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  storeMessage.textContent = "正在创建并扫描...";
  const payload = {
    title: document.querySelector("#store-title").value.trim(),
    store_url: document.querySelector("#store-url").value.trim(),
    keywords: document.querySelector("#store-keywords").value.trim(),
    min_score: Number(document.querySelector("#store-score").value),
    check_interval_minutes: Number(document.querySelector("#store-interval").value),
  };

  if (usingLocalDemo) {
    const watches = getLocalStoreWatches();
    const watch = {
      ...payload,
      id: Date.now(),
      owner_phone: phone,
      created_at: new Date().toISOString(),
      last_checked_at: new Date().toISOString(),
      next_check_at: new Date(Date.now() + payload.check_interval_minutes * 60 * 1000).toISOString(),
      status: "ok",
      last_error: null,
    };
    watches.push(watch);
    localStorage.setItem("pricepilot_store_watches", JSON.stringify(watches));
    selectedStoreWatchId = watch.id;
    storeMessage.textContent = "已创建商品发现任务";
    await loadStoreWatches();
    return;
  }

  const response = await fetch(apiUrl("/store-watches"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const watch = await response.json();
  selectedStoreWatchId = watch.id;
  storeMessage.textContent = "已创建商品发现任务";
  await loadStoreWatches();
});

storeIntervalForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedStoreWatchId) {
    return;
  }
  const minutes = Number(storeDetailIntervalInput.value);
  if (usingLocalDemo) {
    const updated = getLocalStoreWatches().map((watch) =>
      watch.id === selectedStoreWatchId
        ? {
            ...watch,
            check_interval_minutes: minutes,
            next_check_at: new Date(Date.now() + minutes * 60 * 1000).toISOString(),
          }
        : watch
    );
    localStorage.setItem("pricepilot_store_watches", JSON.stringify(updated));
    await loadStoreWatches();
    return;
  }
  await fetch(apiUrl(`/store-watches/${selectedStoreWatchId}/interval`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ check_interval_minutes: minutes }),
  });
  await loadStoreWatches();
});

refreshStoreButton.addEventListener("click", async () => {
  if (!selectedStoreWatchId) {
    return;
  }
  refreshStoreButton.textContent = "扫描中...";
  if (!usingLocalDemo) {
    await fetch(apiUrl(`/store-watches/${selectedStoreWatchId}/refresh`), { method: "POST" });
  }
  await loadStoreWatches();
  refreshStoreButton.textContent = "立即扫描店铺";
});

function getLocalStoreWatches() {
  const saved = localStorage.getItem("pricepilot_store_watches");
  if (saved) {
    return JSON.parse(saved);
  }
  const seed = [
    {
      id: 1,
      owner_phone: phone,
      title: "Tech accessories discovery",
      store_url: "https://example.com/store",
      keywords: "laptop sleeve keyboard usb-c charger",
      min_score: 80,
      check_interval_minutes: 360,
      created_at: new Date().toISOString(),
      last_checked_at: new Date().toISOString(),
      next_check_at: new Date(Date.now() + 360 * 60 * 1000).toISOString(),
      status: "ok",
      last_error: null,
    },
  ];
  localStorage.setItem("pricepilot_store_watches", JSON.stringify(seed));
  return seed;
}

function getLocalProducts(watch) {
  return [
    {
      id: 1,
      store_watch_id: watch.id,
      title: "USB-C travel charger with compact cable kit",
      url: "https://example.com/product/charger",
      image_url: "",
      price: 39,
      score: 88.5,
      matched: true,
      discovered_at: new Date().toISOString(),
    },
    {
      id: 2,
      store_watch_id: watch.id,
      title: "Minimal laptop sleeve for 13 inch notebooks",
      url: "https://example.com/product/sleeve",
      image_url: "",
      price: 28,
      score: 83.2,
      matched: true,
      discovered_at: new Date().toISOString(),
    },
    {
      id: 3,
      store_watch_id: watch.id,
      title: "Desk organizer tray",
      url: "https://example.com/product/tray",
      image_url: "",
      price: 18,
      score: 41.9,
      matched: false,
      discovered_at: new Date().toISOString(),
    },
  ];
}

function getLocalPriceCandidates(target) {
  if (target.includes("robinhood.com") || target.includes("/stocks/")) {
    return [
      {
        price: 226.06,
        label: "Visible page headline price",
        strategy: "selector",
        key: "selector:headline-stock-price-demo",
        selector: "h1 + price text",
        confidence: 0.86,
        snippet: "NVIDIA $226.06 +$1.70 Today",
      },
      {
        price: 1.7,
        label: "Daily movement amount",
        strategy: "text",
        key: "text:daily-change-demo",
        selector: "prominent-text",
        confidence: 0.38,
        snippet: "+$1.70 (+0.76%) Today",
      },
      {
        price: 0,
        label: "Estimated cost in order panel",
        strategy: "selector",
        key: "selector:estimated-cost-demo",
        selector: "[class*='order']",
        confidence: 0.25,
        snippet: "Estimated Cost $0.00",
      },
    ];
  }

  if (/^[A-Z]{2,6}$/i.test(target)) {
    const symbol = target.toUpperCase();
    return [
      {
        price: symbol === "NVDA" ? 226.06 : 143.2,
        label: `${symbol} market price`,
        strategy: "stock_api",
        key: `stock_api:${symbol}`,
        selector: symbol,
        confidence: 0.98,
        snippet: `Demo market quote for ${symbol}`,
      },
    ];
  }

  return [
    {
      price: 89.99,
      label: "Structured product price",
      strategy: "json_ld",
      key: "json_ld:0:0",
      selector: "script[type='application/ld+json']",
      confidence: 0.92,
      snippet: "Product schema price",
    },
    {
      price: 99.99,
      label: "Visible sale price",
      strategy: "selector",
      key: "selector:[class*='price' i]:0:0",
      selector: "[class*='price' i]",
      confidence: 0.72,
      snippet: "Sale price $99.99",
    },
  ];
}

loadStoreWatches().catch(() => {
  usingLocalDemo = true;
  loadStoreWatches();
});
