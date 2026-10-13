"use strict";

/*
 * JUBAOPEN_THREADS_MANUAL_CONTACT_ADAPTER_210_3_5
 *
 * 在扩展隔离环境中读取 MAIN world 写入的 DOM 桥接节点。
 * 只有当前 threadId 完全匹配时才使用手动联系人身份。
 */
(() => {
  if (
    window.__jubaThreadsManualContactAdapter210305
  ) {
    return;
  }

  window.__jubaThreadsManualContactAdapter210305 =
    true;

  const BRIDGE_ID =
    "jubaopen-threads-manual-contact-v210305";

  const MAX_AGE = 5000;

  const clean = (value, max = 4096) =>
    String(value ?? "")
      .replace(/\u0000/g, "")
      .trim()
      .slice(0, max);

  function currentThreadId() {
    const match = location.pathname.match(
      /^\/messages\/t\/([^/?#]+)/
    );

    if (!match) return "";

    try {
      return clean(
        decodeURIComponent(match[1]),
        256
      );
    } catch (_) {
      return clean(match[1], 256);
    }
  }

  function readManualIdentity() {
    const node =
      document.getElementById(BRIDGE_ID);

    if (!node) return null;

    let value;

    try {
      value = JSON.parse(
        node.getAttribute("content") || "{}"
      );
    } catch (_) {
      return null;
    }

    const at = Number(value.at);

    if (
      value?.v !== 1 ||
      value?.platform !== "threads" ||
      !Number.isFinite(at) ||
      Date.now() - at > MAX_AGE ||
      at - Date.now() > 5000
    ) {
      return null;
    }

    const current = currentThreadId();
    const bridged = clean(
      value.threadId,
      256
    );

    if (
      !current ||
      !bridged ||
      current !== bridged
    ) {
      return null;
    }

    const identity = value.identity;

    if (
      !identity ||
      identity.role !== "IS_PARTICIPANT" ||
      identity.stable !== true ||
      identity.confidence !== "high" ||
      identity.confirmedByUser !== true ||
      identity.threadId !== current
    ) {
      return null;
    }

    const type = clean(
      identity.identityType,
      64
    );

    const raw = clean(
      identity.identityValue,
      100
    ).toLowerCase();

    if (
      type !== "threads_username" ||
      !/^[a-z0-9._]{1,64}$/.test(raw)
    ) {
      return null;
    }

    return {
      identityType: "threads_username",
      identityValue: raw,
      displayName: clean(
        identity.displayName ||
        `@${raw}`,
        200
      ),
      avatarUrl: clean(
        identity.avatarUrl,
        4096
      ),
      role: "IS_PARTICIPANT",
      stable: true,
      confidence: "high",
      source:
        "threads-user-confirmed-manual-contact",
      threadId: current
    };
  }

  function install() {
    const adapter =
      window.JubaAdapters?.threads;

    if (
      !adapter ||
      typeof adapter.conversation !==
        "function"
    ) {
      setTimeout(install, 50);
      return;
    }

    if (
      adapter.__manualContact210305 === true
    ) {
      return;
    }

    const originalConversation =
      adapter.conversation.bind(adapter);

    adapter.conversation = () => {
      let original = null;

      try {
        original = originalConversation();
      } catch (_) {}

      /*
       * 可靠的自动参与者身份优先。
       */
      if (
        original &&
        original.readonly !== true &&
        original.identityType &&
        original.identityValue
      ) {
        return original;
      }

      const manual = readManualIdentity();

      if (!manual) {
        return original;
      }

      const threadId = manual.threadId;

      return {
        externalConversationId:
          "threads:" + threadId,
        identityType:
          manual.identityType,
        identityValue:
          manual.identityValue,
        displayName:
          manual.displayName,
        avatarUrl:
          manual.avatarUrl,
        readonly: false,
        metadata: {
          source: manual.source,
          confidence: "high",
          manuallyConfirmed: true,
          threadId
        }
      };
    };

    const originalDiagnostics =
      typeof adapter.diagnostics === "function"
        ? adapter.diagnostics.bind(adapter)
        : () => ({ platform: "threads" });

    adapter.diagnostics = () => {
      const manual = readManualIdentity();

      return {
        ...originalDiagnostics(),
        adapterVersion: "210.3.5",
        manualContactFound:
          Boolean(manual),
        manualContactIdentityValue:
          clean(
            manual?.identityValue,
            100
          ),
        manualContactSource:
          clean(
            manual?.source,
            80
          )
      };
    };

    adapter.__manualContact210305 = true;
  }

  install();
})();
