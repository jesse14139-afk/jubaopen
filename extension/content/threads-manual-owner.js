"use strict";

/*
 * JUBAOPEN_THREADS_MANUAL_OWNER_210_3_3
 *
 * 当 Threads DOM 自动识别本人失败时，允许用户明确输入并确认
 * 当前登录账号本人的 Threads 用户名。
 *
 * 不读取密码、Cookie、Token 或其他登录凭据。
 */
(() => {
  if (window.__jubaThreadsManualOwner210303) {
    return;
  }

  window.__jubaThreadsManualOwner210303 = true;

  const VERSION = "210.3.5";

  /*
   * 与 210.3.1 Probe 保持兼容。
   */
  const OWNER_SESSION_KEY =
    "jubaopen.threads.ownerIdentity.v210301";

  const PENDING_SESSION_KEY =
    "jubaopen.threads.pendingOwner.v210301";

  /*
   * 用户手动确认后的长期存储。
   */
  const MANUAL_LOCAL_KEY =
    "jubaopen.threads.manualOwner.v210303";

  const HOST_ID =
    "jubaopen-threads-manual-owner-host";

  const SNAPSHOT_ID =
    "jubaopen-threads-page-snapshot-v1";

  const blockedNames = new Set([
    "messages",
    "activity",
    "search",
    "settings",
    "privacy",
    "accounts",
    "login",
    "signup",
    "explore",
    "following",
    "followers",
    "notifications",
    "about",
    "help"
  ]);

  let host = null;
  let shadow = null;
  let statusButton = null;
  let missingSince = 0;
  let lastStatus = "";

  const clean = (value, max = 4096) =>
    String(value ?? "")
      .replace(/\u0000/g, "")
      .replace(
        /[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF]/g,
        ""
      )
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, max);

  function normalizeUsername(value) {
    let result = clean(value, 512);

    /*
     * 支持直接粘贴 Threads 个人资料网址。
     */
    if (/^https?:\/\//i.test(result)) {
      try {
        const url = new URL(result);

        if (
          !/^(?:www\.)?threads\.com$/i.test(
            url.hostname
          )
        ) {
          return "";
        }

        result =
          url.pathname
            .split("/")
            .filter(Boolean)[0] || "";
      } catch (_) {
        return "";
      }
    }

    result = result
      .replace(/^@/, "")
      .replace(/^\/+|\/+$/g, "")
      .toLowerCase();

    if (
      !/^[a-z0-9._]{1,64}$/.test(result) ||
      blockedNames.has(result)
    ) {
      return "";
    }

    return result;
  }

  function readJson(storage, key) {
    try {
      const raw = storage.getItem(key);

      if (!raw) return null;

      const parsed = JSON.parse(raw);

      return (
        parsed &&
        typeof parsed === "object"
      ) ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  function writeJson(storage, key, value) {
    try {
      storage.setItem(
        key,
        JSON.stringify(value)
      );

      return true;
    } catch (_) {
      return false;
    }
  }

  function removeKey(storage, key) {
    try {
      storage.removeItem(key);
    } catch (_) {}
  }

  function readManualRecord() {
    const record = readJson(
      localStorage,
      MANUAL_LOCAL_KEY
    );

    if (!record) return null;

    const identityValue =
      normalizeUsername(
        record.identityValue
      );

    if (
      !identityValue ||
      record.confirmedByUser !== true
    ) {
      removeKey(
        localStorage,
        MANUAL_LOCAL_KEY
      );

      return null;
    }

    return {
      identityValue,
      displayName: clean(
        record.displayName ||
        `@${identityValue}`,
        200
      ),
      savedAt: Number(record.savedAt) || 0
    };
  }

  function makeStableOwner(
    identityValue,
    displayName
  ) {
    const normalized =
      normalizeUsername(identityValue);

    if (!normalized) return null;

    return {
      identityType: "threads_username",
      identityValue: normalized,
      displayName: clean(
        displayName || `@${normalized}`,
        200
      ),
      profileUrl:
        `https://www.threads.com/@${normalized}`,
      avatarUrl: "",
      role: "IS_OWNER",
      stable: true,
      confidence: "high",
      source:
        "threads-user-confirmed-manual",
      verifiedAt: Date.now(),
      manual: true,
      manualVersion: VERSION
    };
  }

  function synchronizeManualOwner() {
    const record = readManualRecord();

    if (!record) return null;

    const owner = makeStableOwner(
      record.identityValue,
      record.displayName
    );

    if (!owner) return null;

    /*
     * 210.3.1 Probe 会读取这个 sessionStorage 键。
     * 周期性刷新 verifiedAt，避免旧版 30 分钟有效期清除身份。
     */
    writeJson(
      sessionStorage,
      OWNER_SESSION_KEY,
      owner
    );

    return owner;
  }

  function saveManualOwner(value) {
    const identityValue =
      normalizeUsername(value);

    if (!identityValue) return null;

    const record = {
      identityType: "threads_username",
      identityValue,
      displayName: `@${identityValue}`,
      profileUrl:
        `https://www.threads.com/@${identityValue}`,
      confirmedByUser: true,
      savedAt: Date.now(),
      version: VERSION
    };

    if (
      !writeJson(
        localStorage,
        MANUAL_LOCAL_KEY,
        record
      )
    ) {
      return null;
    }

    const owner = makeStableOwner(
      identityValue,
      record.displayName
    );

    writeJson(
      sessionStorage,
      OWNER_SESSION_KEY,
      owner
    );

    /*
     * 同时写入旧 Probe 兼容的 pending 数据。
     */
    writeJson(
      sessionStorage,
      PENDING_SESSION_KEY,
      {
        ...owner,
        at: Date.now()
      }
    );

    try {
      window.dispatchEvent(
        new CustomEvent(
          "jubaopen:threads-manual-owner",
          {
            detail: {
              identityValue,
              confirmed: true
            }
          }
        )
      );
    } catch (_) {}

    return owner;
  }

  function clearManualOwner() {
    removeKey(
      localStorage,
      MANUAL_LOCAL_KEY
    );

    const owner = readJson(
      sessionStorage,
      OWNER_SESSION_KEY
    );

    if (
      owner?.manual === true ||
      owner?.source ===
        "threads-user-confirmed-manual"
    ) {
      removeKey(
        sessionStorage,
        OWNER_SESSION_KEY
      );
    }

    removeKey(
      sessionStorage,
      PENDING_SESSION_KEY
    );
  }

  function readSnapshot() {
    const node =
      document.getElementById(SNAPSHOT_ID);

    if (!node) return null;

    try {
      const value = JSON.parse(
        node.getAttribute("content") || "{}"
      );

      if (
        value?.v !== 1 ||
        value?.platform !== "threads"
      ) {
        return null;
      }

      return value;
    } catch (_) {
      return null;
    }
  }

  function validStableOwner(value) {
    if (
      !value ||
      value.role !== "IS_OWNER" ||
      value.stable !== true ||
      value.confidence !== "high"
    ) {
      return null;
    }

    const identityValue =
      normalizeUsername(
        value.identityValue
      );

    if (!identityValue) return null;

    return {
      ...value,
      identityValue
    };
  }

  function currentOwner() {
    const snapshotOwner =
      validStableOwner(
        readSnapshot()?.ownIdentity
      );

    if (snapshotOwner) {
      return snapshotOwner;
    }

    return validStableOwner(
      readJson(
        sessionStorage,
        OWNER_SESSION_KEY
      )
    );
  }

  function isThreadsPage() {
    return /^(?:www\.)?threads\.com$/i.test(
      location.hostname
    );
  }

  function isMessagePage() {
    return (
      isThreadsPage() &&
      location.pathname.startsWith(
        "/messages"
      )
    );
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(
      /[&<>"']/g,
      character => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      })[character]
    );
  }

  function bringToFront() {
    if (
      host &&
      host.isConnected &&
      document.body &&
      host.parentElement !== document.body
    ) {
      document.body.appendChild(host);
    } else if (
      host &&
      host.isConnected &&
      document.body &&
      document.body.lastElementChild !== host
    ) {
      /*
       * 移到最后，避免被晚加载的 JubaOpen 面板遮挡。
       */
      document.body.appendChild(host);
    }
  }

  function createInterface() {
    if (
      host ||
      !document.body
    ) {
      return;
    }

    host = document.createElement("div");
    host.id = HOST_ID;

    Object.assign(host.style, {
      position: "fixed",
      right: "16px",
      top: "48px",
      zIndex: "2147483647",
      width: "auto",
      height: "auto",
      margin: "0",
      padding: "0"
    });

    shadow = host.attachShadow({
      mode: "open"
    });

    shadow.innerHTML = `
      <style>
        :host {
          all: initial;
        }

        * {
          box-sizing: border-box;
        }

        .status {
          min-height: 34px;
          max-width: 330px;
          padding: 7px 12px;
          border: 1px solid #d94d89;
          border-radius: 18px;
          background: #fff5fa;
          color: #8c2754;
          box-shadow:
            0 7px 24px rgba(76, 17, 44, .26);
          font: 700 12px/1.35
            system-ui,
            -apple-system,
            "Segoe UI",
            "Microsoft YaHei",
            sans-serif;
          cursor: pointer;
        }

        .status:hover {
          background: #ffe5f1;
        }

        .status.ok {
          border-color: #329565;
          background: #effff6;
          color: #17613d;
        }

        .overlay {
          position: fixed;
          inset: 0;
          z-index: 2147483647;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 18px;
          background: rgba(22, 8, 15, .55);
        }

        .dialog {
          width: 410px;
          max-width: calc(100vw - 30px);
          padding: 20px;
          border: 1px solid #e094b6;
          border-radius: 16px;
          background: #fffafd;
          color: #39232e;
          box-shadow:
            0 24px 80px rgba(35, 8, 22, .42);
          font: 13px/1.55
            system-ui,
            -apple-system,
            "Segoe UI",
            "Microsoft YaHei",
            sans-serif;
        }

        h2 {
          margin: 0 0 10px;
          color: #8d2d58;
          font-size: 18px;
        }

        p {
          margin: 8px 0;
        }

        .warning {
          padding: 9px 10px;
          border-radius: 8px;
          background: #fff0f6;
          color: #77334f;
        }

        label.title {
          display: block;
          margin-top: 14px;
          font-weight: 700;
        }

        input[type="text"] {
          width: 100%;
          height: 39px;
          margin-top: 6px;
          padding: 0 11px;
          border: 1px solid #d486aa;
          border-radius: 8px;
          outline: none;
          background: #fff;
          color: #2e1a24;
          font: 14px
            system-ui,
            -apple-system,
            "Segoe UI",
            sans-serif;
        }

        input[type="text"]:focus {
          border-color: #bd3b76;
          box-shadow:
            0 0 0 3px rgba(189, 59, 118, .13);
        }

        .confirm {
          display: flex;
          gap: 8px;
          align-items: flex-start;
          margin-top: 12px;
        }

        .confirm input {
          flex: none;
          width: 16px;
          height: 16px;
          margin: 2px 0 0;
        }

        .error {
          min-height: 20px;
          margin-top: 5px;
          color: #bf234e;
          font-size: 12px;
        }

        .buttons {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
          margin-top: 16px;
        }

        button {
          min-height: 34px;
          padding: 0 13px;
          border: 1px solid #d387a9;
          border-radius: 8px;
          background: #fff;
          color: #823052;
          font: 700 12px
            system-ui,
            -apple-system,
            "Segoe UI",
            "Microsoft YaHei",
            sans-serif;
          cursor: pointer;
        }

        button:hover {
          background: #fff0f7;
        }

        button.primary {
          border-color: #bd3b76;
          background: #bd3b76;
          color: #fff;
        }

        button.primary:hover {
          background: #a82f66;
        }

        button.danger {
          margin-right: auto;
          border-color: #d25868;
          color: #a32134;
        }

        button:disabled {
          opacity: .48;
          cursor: not-allowed;
        }
      </style>

      <button
        id="statusButton"
        type="button"
        class="status"
      >
        设置 Threads 本人身份
      </button>

      <div id="dialogContainer"></div>
    `;

    statusButton =
      shadow.getElementById(
        "statusButton"
      );

    statusButton.addEventListener(
      "click",
      openDialog
    );

    document.body.appendChild(host);
    renderStatus();
  }

  function closeDialog() {
    const container =
      shadow?.getElementById(
        "dialogContainer"
      );

    if (container) {
      container.textContent = "";
    }
  }

  function openDialog() {
    if (!shadow) return;

    const container =
      shadow.getElementById(
        "dialogContainer"
      );

    const manual = readManualRecord();
    const owner = currentOwner();

    const defaultValue =
      manual?.identityValue ||
      owner?.identityValue ||
      "";

    container.innerHTML = `
      <div
        id="overlay"
        class="overlay"
      >
        <div
          class="dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="manualOwnerTitle"
        >
          <h2 id="manualOwnerTitle">
            设置 Threads 本人稳定身份
          </h2>

          <p>
            自动识别失败时，请输入当前登录账号本人的
            Threads 用户名。
          </p>

          <p class="warning">
            请确保输入的是你本人当前登录的账号。
            错误身份可能导致客户消息关联到错误账号。
            本功能不会读取密码、Cookie 或登录令牌。
          </p>

          <label
            class="title"
            for="manualUsername"
          >
            Threads 用户名
          </label>

          <input
            id="manualUsername"
            type="text"
            autocomplete="off"
            spellcheck="false"
            placeholder="@your_name 或个人资料网址"
            value="${escapeHtml(defaultValue)}"
          >

          <div
            id="manualError"
            class="error"
          ></div>

          <label class="confirm">
            <input
              id="manualConfirm"
              type="checkbox"
            >
            <span>
              我确认这是当前登录账号本人的
              Threads 用户名。
            </span>
          </label>

          <div class="buttons">
            <button
              id="manualClear"
              type="button"
              class="danger"
            >
              清除手动身份
            </button>

            <button
              id="manualCancel"
              type="button"
            >
              取消
            </button>

            <button
              id="manualSave"
              type="button"
              class="primary"
            >
              保存并重新识别
            </button>
          </div>
        </div>
      </div>
    `;

    const input =
      shadow.getElementById(
        "manualUsername"
      );

    const confirmation =
      shadow.getElementById(
        "manualConfirm"
      );

    const error =
      shadow.getElementById(
        "manualError"
      );

    const save =
      shadow.getElementById(
        "manualSave"
      );

    const clear =
      shadow.getElementById(
        "manualClear"
      );

    clear.disabled = !manual;

    shadow
      .getElementById("manualCancel")
      .addEventListener(
        "click",
        closeDialog
      );

    shadow
      .getElementById("overlay")
      .addEventListener(
        "click",
        event => {
          if (
            event.target?.id === "overlay"
          ) {
            closeDialog();
          }
        }
      );

    clear.addEventListener(
      "click",
      () => {
        if (
          !window.confirm(
            "确定清除手动设置的 Threads 本人身份吗？"
          )
        ) {
          return;
        }

        clearManualOwner();
        closeDialog();

        setTimeout(
          () => location.reload(),
          100
        );
      }
    );

    save.addEventListener(
      "click",
      () => {
        error.textContent = "";

        const identityValue =
          normalizeUsername(input.value);

        if (!identityValue) {
          error.textContent =
            "用户名格式无效。请输入 @用户名，" +
            "或者完整的 Threads 个人资料网址。";

          input.focus();
          return;
        }

        if (!confirmation.checked) {
          error.textContent =
            "请先勾选确认，这是当前登录账号本人。";

          confirmation.focus();
          return;
        }

        const ownerValue =
          saveManualOwner(identityValue);

        if (!ownerValue) {
          error.textContent =
            "保存失败，浏览器可能禁止了本地存储。";
          return;
        }

        save.disabled = true;
        save.textContent =
          "已保存，正在刷新……";

        setTimeout(
          () => location.reload(),
          150
        );
      }
    );

    setTimeout(
      () => {
        input.focus();
        input.select();
      },
      0
    );
  }

  function renderStatus() {
    if (!statusButton) return;

    const owner = currentOwner();
    const manual = readManualRecord();

    if (owner) {
      missingSince = 0;

      const isManual =
        owner.source ===
          "threads-user-confirmed-manual" ||
        Boolean(manual);

      const text = isManual
        ? `本人：@${owner.identityValue}（手动）· 点击修改`
        : `本人：@${owner.identityValue} · 点击设置`;

      if (lastStatus !== text) {
        statusButton.textContent = text;
        statusButton.className =
          "status ok";
        lastStatus = text;
      }

      statusButton.hidden = false;
      return;
    }

    if (!isMessagePage()) {
      statusButton.hidden = true;
      missingSince = 0;
      return;
    }

    if (!missingSince) {
      missingSince = Date.now();
    }

    /*
     * 先给原自动探针 2.5 秒识别时间。
     */
    if (
      Date.now() - missingSince < 2500
    ) {
      statusButton.hidden = true;
      return;
    }

    const text =
      "未识别本人身份 · 点击手动设置";

    if (lastStatus !== text) {
      statusButton.textContent = text;
      statusButton.className = "status";
      lastStatus = text;
    }

    statusButton.hidden = false;
  }

  function startInterface() {
    if (!isThreadsPage()) return;

    synchronizeManualOwner();

    if (document.body) {
      createInterface();
    } else {
      document.addEventListener(
        "DOMContentLoaded",
        createInterface,
        { once: true }
      );
    }

    setInterval(
      () => {
        synchronizeManualOwner();

        if (!host || !host.isConnected) {
          host = null;
          shadow = null;
          statusButton = null;
          createInterface();
        }

        renderStatus();
      },
      1000
    );

    /*
     * 确保按钮显示在晚加载的 JubaOpen 面板上方。
     */
    setInterval(
      bringToFront,
      5000
    );
  }

  startInterface();
})();
