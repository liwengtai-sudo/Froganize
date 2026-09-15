const token = document.querySelector('meta[name="dropnest-token"]').content;

const elements = {
  healthPill: document.getElementById("health-pill"),
  healthLabel: document.getElementById("health-label"),
  desktopPath: document.getElementById("desktop-path"),
  timelinePath: document.getElementById("timeline-path"),
  configHealth: document.getElementById("config-health"),
  historyHealth: document.getElementById("history-health"),
  assess: document.getElementById("assess"),
  openDesktop: document.getElementById("open-desktop"),
  openTimeline: document.getElementById("open-timeline"),
  metrics: {
    recent: document.getElementById("metric-recent"),
    archive: document.getElementById("metric-archive"),
    unsafe: document.getElementById("metric-unsafe"),
  },
  assessmentTime: document.getElementById("assessment-time"),
  loadingState: document.getElementById("loading-state"),
  emptyState: document.getElementById("empty-state"),
  groups: document.getElementById("groups"),
  groupLists: {
    recent: document.getElementById("group-recent"),
    archive: document.getElementById("group-archive"),
    cleanup: document.getElementById("group-cleanup"),
    unsafe: document.getElementById("group-unsafe"),
  },
  cleanupCount: document.getElementById("cleanup-count"),
  selectionCount: document.getElementById("selection-count"),
  clearSelection: document.getElementById("clear-selection"),
  archiveSelected: document.getElementById("archive-selected"),
  trashSelected: document.getElementById("trash-selected"),
  undo: document.getElementById("undo"),
  activityPanel: document.getElementById("activity-panel"),
  activityTitle: document.getElementById("activity-title"),
  activityLines: document.getElementById("activity-lines"),
  problemPanel: document.getElementById("problem-panel"),
  problemList: document.getElementById("problem-list"),
  dialog: document.getElementById("confirm-dialog"),
  dialogTitle: document.getElementById("dialog-title"),
  dialogMessage: document.getElementById("dialog-message"),
  dialogList: document.getElementById("dialog-list"),
  dialogConfirm: document.getElementById("dialog-confirm"),
  toast: document.getElementById("toast"),
};

let currentAssessment = null;
let pendingConfirmation = null;
let toastTimer = null;

async function request(path, options = {}) {
  const method = options.method || "GET";
  const headers = { Accept: "application/json" };
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    headers["X-DropNest-Token"] = token;
  }
  const response = await fetch(path, {
    method,
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`本机服务返回了无法读取的响应（HTTP ${response.status}）。`);
  }
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || `操作失败（HTTP ${response.status}）。`);
  }
  return payload;
}

function createElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined && text !== null) {
    node.textContent = text;
  }
  return node;
}

function setBusy(button, busy, busyLabel) {
  if (!button.dataset.originalLabel) {
    button.dataset.originalLabel = button.textContent.trim();
  }
  button.disabled = busy;
  button.textContent = busy ? busyLabel : button.dataset.originalLabel;
}

function showToast(message, error = false) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", error);
  elements.toast.classList.add("visible");
  toastTimer = window.setTimeout(() => {
    elements.toast.classList.remove("visible");
  }, 3600);
}

function renderProblems(problems) {
  elements.problemList.replaceChildren();
  elements.problemPanel.hidden = problems.length === 0;
  for (const problem of problems) {
    elements.problemList.append(createElement("li", "", problem));
  }
}

function renderStatus(status) {
  elements.desktopPath.textContent = status.desktop;
  elements.timelinePath.textContent = `${status.workspace}/Timeline`;
  elements.configHealth.textContent = status.config_valid ? "正常" : "异常";
  elements.historyHealth.textContent = status.history_valid ? "正常" : "异常";
  elements.healthPill.dataset.state = status.valid ? "healthy" : "error";
  elements.healthLabel.textContent = status.valid ? "本机服务正常" : "工作区需要检查";
  elements.assess.disabled = !status.valid;
  elements.undo.disabled = !status.valid || !status.latest_batch_id;
  renderProblems(status.problems);
}

async function refreshStatus() {
  try {
    const payload = await request("/api/status");
    renderStatus(payload.status);
  } catch (error) {
    elements.healthPill.dataset.state = "error";
    elements.healthLabel.textContent = "无法连接本机服务";
    showToast(error.message, true);
  }
}

function ageLabel(entry) {
  if (entry.age_days === null || entry.age_days === undefined) {
    return "无法计算时间";
  }
  if (entry.age_days === 0) {
    return "今天修改";
  }
  return `${entry.age_days} 天前修改`;
}

function typeLabel(entry) {
  if (entry.item_type === "directory") {
    return "完整文件夹";
  }
  if (entry.item_type === "file") {
    return "文件";
  }
  return "不可处理";
}

function cleanupReasonLabel(entry) {
  const labels = {
    cleanup_system_junk: "macOS 可以自动重新生成的桌面元数据",
    cleanup_temporary: "名称或扩展名表明它是临时文件",
    cleanup_partial_download: "未完成下载留下的临时文件",
  };
  return labels[entry.reason_code] || "明确的临时残留";
}

function shortTarget(target) {
  if (!target) {
    return "";
  }
  const marker = "/Timeline/";
  const index = target.indexOf(marker);
  return index >= 0 ? `Timeline/${target.slice(index + marker.length)}` : target;
}

function selectedCheckboxes(group = null, action = null) {
  let selector = "input.item-checkbox";
  if (group) {
    selector += `[data-group="${group}"]`;
  }
  if (action) {
    selector += `[data-action="${action}"]`;
  }
  selector += ":checked";
  return Array.from(document.querySelectorAll(selector));
}

function selectableCheckboxes(group = null, action = null) {
  let selector = "input.item-checkbox";
  if (group) {
    selector += `[data-group="${group}"]`;
  }
  if (action) {
    selector += `[data-action="${action}"]`;
  }
  selector += ":not(:disabled)";
  return Array.from(document.querySelectorAll(selector));
}

function selectedNames(action) {
  return selectedCheckboxes(null, action).map(
    (checkbox) => checkbox.dataset.name,
  );
}

function updateSelection() {
  const archiveCount = selectedCheckboxes(null, "archive").length;
  const trashCount = selectedCheckboxes(null, "trash").length;
  elements.selectionCount.textContent = archiveCount;
  elements.archiveSelected.disabled = !currentAssessment || archiveCount === 0;
  elements.trashSelected.disabled = !currentAssessment || trashCount === 0;
  elements.clearSelection.disabled = archiveCount === 0;

  for (const button of document.querySelectorAll(".group-select")) {
    const group = button.dataset.group;
    const choices = selectableCheckboxes(group);
    const selected = selectedCheckboxes(group);
    button.disabled = choices.length === 0;
    button.textContent =
      choices.length > 0 && selected.length === choices.length
        ? "取消本组"
        : "全选本组";
  }
}

async function revealItem(name, button) {
  if (!currentAssessment) {
    return;
  }
  setBusy(button, true, "正在定位…");
  try {
    await request("/api/reveal", {
      method: "POST",
      body: {
        assessment_id: currentAssessment.assessment_id,
        name,
      },
    });
    showToast(`已在 Finder 中显示 ${name}。`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false, "");
  }
}

function renderEntry(entry, index) {
  const row = createElement(
    "article",
    `item-row${entry.selectable ? "" : " disabled"}`,
  );
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.className = "item-checkbox";
  checkbox.id = `desktop-item-${index}`;
  checkbox.dataset.name = entry.name;
  checkbox.dataset.group = entry.group;
  checkbox.dataset.action = entry.action || "";
  checkbox.checked = entry.default_selected && entry.selectable;
  checkbox.disabled = !entry.selectable;
  checkbox.addEventListener("change", updateSelection);

  const label = document.createElement("label");
  label.className = "item-check";
  label.htmlFor = checkbox.id;
  label.append(checkbox, createElement("span", "check-visual"));

  const icon = createElement(
    "span",
    `item-icon ${entry.item_type || "unknown"}`,
    entry.item_type === "directory" ? "▰" : "▤",
  );
  icon.setAttribute("aria-hidden", "true");

  const main = createElement("div", "item-main");
  const titleLine = createElement("div", "item-title-line");
  titleLine.append(
    createElement("strong", "item-name", entry.name),
    createElement("span", "item-type", typeLabel(entry)),
  );
  main.append(titleLine);

  if (entry.action === "trash") {
    const exactTime = new Date(entry.classification_time).toLocaleString("zh-CN");
    main.append(
      createElement(
        "span",
        "item-meta",
        `${ageLabel(entry)} · 使用时间 ${exactTime}`,
      ),
      createElement(
        "span",
        "item-cleanup-reason",
        `建议原因：${cleanupReasonLabel(entry)}`,
      ),
      createElement(
        "span",
        "item-target cleanup-target",
        "可移入 macOS 废纸篓，并可在 Finder 中恢复",
      ),
    );
  } else if (entry.selectable) {
    const exactTime = new Date(entry.classification_time).toLocaleString("zh-CN");
    const rename = entry.renamed_from ? " · 目标已自动避让重名" : "";
    const meta = createElement(
      "span",
      "item-meta",
      `${ageLabel(entry)} · 使用时间 ${exactTime}${rename}`,
    );
    const target = createElement(
      "span",
      "item-target",
      `收进 ${shortTarget(entry.target)}`,
    );
    main.append(meta, target);
  } else {
    main.append(
      createElement(
        "span",
        "item-reason",
        entry.reason || "Froganize 无法安全评估这个项目。",
      ),
    );
  }

  const reveal = createElement("button", "reveal-button", "在 Finder 中显示");
  reveal.type = "button";
  reveal.addEventListener("click", () => revealItem(entry.name, reveal));

  row.append(label, icon, main, reveal);
  return row;
}

function renderGroupEmpty(group) {
  const labels = {
    recent: "最近 7 天没有修改过的项目。",
    archive: "没有超过一周未修改的项目。",
    cleanup: "没有发现高置信度的临时残留。",
    unsafe: "没有需要暂不处理的项目。",
  };
  return createElement("p", "group-empty", labels[group]);
}

function renderAssessment(assessment) {
  currentAssessment = assessment;
  elements.loadingState.hidden = true;
  elements.assessmentTime.textContent = `评估于 ${new Date(
    assessment.generated_at,
  ).toLocaleString("zh-CN")}`;
  elements.desktopPath.textContent = assessment.desktop;
  elements.timelinePath.textContent = assessment.archive;

  for (const [group, metric] of Object.entries(elements.metrics)) {
    metric.textContent = assessment.summary[group];
  }
  elements.cleanupCount.textContent = assessment.summary.cleanup;
  for (const list of Object.values(elements.groupLists)) {
    list.replaceChildren();
  }

  if (assessment.entries.length === 0) {
    elements.emptyState.hidden = false;
    elements.groups.hidden = true;
    updateSelection();
    return;
  }

  elements.emptyState.hidden = true;
  elements.groups.hidden = false;
  assessment.entries.forEach((entry, index) => {
    const list = elements.groupLists[entry.group] || elements.groupLists.recent;
    list.append(renderEntry(entry, index));
  });
  for (const [group, list] of Object.entries(elements.groupLists)) {
    if (!list.children.length) {
      list.append(renderGroupEmpty(group));
    }
  }
  updateSelection();
}

async function assessDesktop(options = {}) {
  setBusy(elements.assess, true, "正在检查…");
  elements.loadingState.hidden = false;
  elements.emptyState.hidden = true;
  elements.groups.hidden = true;
  elements.archiveSelected.disabled = true;
  elements.trashSelected.disabled = true;
  try {
    const payload = await request("/api/assess", { method: "POST" });
    renderAssessment(payload.assessment);
    if (!options.silent) {
      showToast(
        `检查完成：${payload.assessment.summary.archive} 项建议收起。`,
      );
    }
  } catch (error) {
    currentAssessment = null;
    elements.loadingState.hidden = true;
    elements.assessmentTime.textContent = "评估失败";
    renderActivity("桌面检查失败", [error.message], true);
    showToast(error.message, true);
  } finally {
    setBusy(elements.assess, false, "");
  }
}

function renderActivity(title, lines, error = false) {
  elements.activityTitle.textContent = title;
  elements.activityLines.replaceChildren();
  elements.activityPanel.classList.toggle("error", error);
  for (const line of lines) {
    elements.activityLines.append(createElement("p", "", line));
  }
  elements.activityPanel.hidden = false;
}

function askConfirmation(
  title,
  message,
  items,
  action,
  confirmLabel,
  confirmTone = "primary",
) {
  pendingConfirmation = action;
  elements.dialogTitle.textContent = title;
  elements.dialogMessage.textContent = message;
  elements.dialogConfirm.textContent = confirmLabel;
  elements.dialogConfirm.classList.toggle(
    "button-primary",
    confirmTone !== "trash",
  );
  elements.dialogConfirm.classList.toggle(
    "button-trash",
    confirmTone === "trash",
  );
  elements.dialogList.replaceChildren();
  const shown = items.slice(0, 8);
  for (const item of shown) {
    elements.dialogList.append(createElement("span", "", item));
  }
  if (items.length > shown.length) {
    elements.dialogList.append(
      createElement("span", "more", `以及另外 ${items.length - shown.length} 项`),
    );
  }
  elements.dialog.showModal();
}

async function archiveSelection() {
  if (!currentAssessment) {
    return;
  }
  const names = selectedNames("archive");
  setBusy(elements.archiveSelected, true, "正在收起…");
  try {
    const payload = await request("/api/archive", {
      method: "POST",
      body: {
        assessment_id: currentAssessment.assessment_id,
        selected: names,
      },
    });
    const summary = payload.batch.summary;
    renderActivity(
      "桌面整理完成",
      [
        `成功收起 ${summary.moved} 项，失败 ${summary.failed} 项。`,
        `批次：${payload.batch.batch_id || "无"}`,
      ],
      summary.failed > 0,
    );
    currentAssessment = null;
    showToast(
      `已安全收起 ${summary.moved} 项。`,
      summary.failed > 0,
    );
    await Promise.all([refreshStatus(), assessDesktop({ silent: true })]);
  } catch (error) {
    currentAssessment = null;
    renderActivity("收起失败", [error.message], true);
    showToast(error.message, true);
    await assessDesktop({ silent: true });
  } finally {
    setBusy(elements.archiveSelected, false, "");
  }
}

async function trashSelection() {
  if (!currentAssessment) {
    return;
  }
  const names = selectedNames("trash");
  setBusy(elements.trashSelected, true, "正在移入废纸篓…");
  try {
    const payload = await request("/api/trash", {
      method: "POST",
      body: {
        assessment_id: currentAssessment.assessment_id,
        selected: names,
      },
    });
    const summary = payload.batch.summary;
    renderActivity(
      "桌面清理完成",
      [
        `移入废纸篓 ${summary.trashed} 项，失败 ${summary.failed} 项。`,
        "这些项目没有被永久删除，可在 Finder 的废纸篓中恢复。",
      ],
      summary.failed > 0,
    );
    currentAssessment = null;
    showToast(
      `清理完成：${summary.trashed} 项已移入废纸篓。`,
      summary.failed > 0,
    );
    await Promise.all([refreshStatus(), assessDesktop({ silent: true })]);
  } catch (error) {
    currentAssessment = null;
    renderActivity("清理失败", [error.message], true);
    showToast(error.message, true);
    await assessDesktop({ silent: true });
  } finally {
    setBusy(elements.trashSelected, false, "");
  }
}

async function executeUndo() {
  setBusy(elements.undo, true, "正在撤销…");
  try {
    const payload = await request("/api/undo", { method: "POST" });
    const summary = payload.batch.summary;
    if (!payload.batch.batch_id) {
      renderActivity("无需撤销", ["最近一次整理没有待恢复项目。"]);
      showToast("没有需要撤销的项目。");
    } else {
      renderActivity(
        "撤销完成",
        [
          `恢复到桌面 ${summary.restored} 项，失败 ${summary.failed} 项。`,
          `撤销批次：${payload.batch.batch_id}`,
        ],
        summary.failed > 0,
      );
      showToast(
        `撤销完成：恢复 ${summary.restored} 项。`,
        summary.failed > 0,
      );
    }
    currentAssessment = null;
    await Promise.all([refreshStatus(), assessDesktop({ silent: true })]);
  } catch (error) {
    renderActivity("撤销失败", [error.message], true);
    showToast(error.message, true);
  } finally {
    setBusy(elements.undo, false, "");
  }
}

async function openFolder(target, button) {
  setBusy(button, true, "正在打开…");
  try {
    await request("/api/open", {
      method: "POST",
      body: { target },
    });
    showToast(target === "desktop" ? "已打开桌面。" : "已打开月度存档。");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(button, false, "");
  }
}

elements.assess.addEventListener("click", () => assessDesktop());
elements.openDesktop.addEventListener("click", () => {
  openFolder("desktop", elements.openDesktop);
});
elements.openTimeline.addEventListener("click", () => {
  openFolder("timeline", elements.openTimeline);
});

for (const button of document.querySelectorAll(".group-select")) {
  button.addEventListener("click", () => {
    const choices = selectableCheckboxes(button.dataset.group);
    const allSelected =
      choices.length > 0 && selectedCheckboxes(button.dataset.group).length === choices.length;
    for (const checkbox of choices) {
      checkbox.checked = !allSelected;
    }
    updateSelection();
  });
}

elements.clearSelection.addEventListener("click", () => {
  for (const checkbox of selectableCheckboxes(null, "archive")) {
    checkbox.checked = false;
  }
  updateSelection();
});

elements.archiveSelected.addEventListener("click", () => {
  const names = selectedNames("archive");
  askConfirmation(
    `确认收起这 ${names.length} 项？`,
    "Froganize 只会移动下面选中的桌面顶层项目到月度存档。文件夹会保持完整，目标被占用时不会覆盖。",
    names,
    archiveSelection,
    "确认收起",
  );
});

elements.trashSelected.addEventListener("click", () => {
  const names = selectedNames("trash");
  askConfirmation(
    `将这 ${names.length} 项移入废纸篓？`,
    "Froganize 只处理下面选中的高置信度临时残留。不会永久删除；完成后仍可在 Finder 的废纸篓中恢复。",
    names,
    trashSelection,
    "移入废纸篓",
    "trash",
  );
});

elements.undo.addEventListener("click", () => {
  askConfirmation(
    "撤销最近一次整理？",
    "Froganize 会把最近成功批次中尚未恢复的项目移回桌面，不会覆盖桌面上的同名项目。",
    [],
    executeUndo,
    "确认撤销",
  );
});

elements.dialogConfirm.addEventListener("click", (event) => {
  event.preventDefault();
  elements.dialog.close("confirm");
  if (pendingConfirmation) {
    const action = pendingConfirmation;
    pendingConfirmation = null;
    action();
  }
});

elements.dialog.addEventListener("close", () => {
  if (elements.dialog.returnValue !== "confirm") {
    pendingConfirmation = null;
  }
});

Promise.all([refreshStatus(), assessDesktop({ silent: true })]);
