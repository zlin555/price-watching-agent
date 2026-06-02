const submitButton = document.querySelector(".submit-button");
const statusPill = document.querySelector(".form-header .status-pill");

submitButton.addEventListener("click", () => {
  statusPill.textContent = "已保存";
  statusPill.classList.add("success");
  submitButton.textContent = "已加入追踪列表";

  window.setTimeout(() => {
    statusPill.textContent = "Demo";
    statusPill.classList.remove("success");
    submitButton.textContent = "保存到我的 Profile";
  }, 2200);
});

