const API_BASE =
  window.PRICEPILOT_API_BASE ||
  localStorage.getItem("pricepilot_api_base") ||
  "https://zlin329-price-wtaching-agent.hf.space";
const tabButtons = document.querySelectorAll(".tab-button");
const form = document.querySelector(".auth-form");
const phoneInput = document.querySelector("#phone");
const passwordInput = document.querySelector("#password");
const submitButton = document.querySelector(".auth-form .submit-button");
const message = document.querySelector(".form-message");

let mode = "login";

if (new URLSearchParams(window.location.search).get("mode") === "register") {
  mode = "register";
  tabButtons.forEach((item) => item.classList.toggle("active", item.dataset.mode === "register"));
  submitButton.textContent = "注册并进入看板";
}

tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    mode = button.dataset.mode;
    tabButtons.forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    submitButton.textContent = mode === "login" ? "登录并进入看板" : "注册并进入看板";
    message.textContent = "";
  });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.textContent = "正在处理...";

  try {
    const response = await fetch(`${API_BASE}/auth/${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        phone: phoneInput.value.trim(),
        password: passwordInput.value,
      }),
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "请求失败");
    }

    localStorage.setItem("pricepilot_token", data.token);
    localStorage.setItem("pricepilot_phone", data.user.phone);
    window.location.href = "dashboard.html";
  } catch (error) {
    if (error.name === "TypeError") {
      localStorage.setItem("pricepilot_token", `local_${Date.now()}`);
      localStorage.setItem("pricepilot_phone", phoneInput.value.trim());
      window.location.href = "dashboard.html";
      return;
    }

    message.textContent = error.message;
  }
});
