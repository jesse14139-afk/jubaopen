"use strict";

/*
 * JUBAOPEN_THREADS_IDENTITY_AUTHORITY_210_3_15
 *
 * 运行环境：Chrome 扩展 ISOLATED world。
 *
 * 权威身份优先级：
 *
 * 1. 核心 Probe 已验证并可写的自动身份；
 * 2. 210.3.15 严格自动验证身份；
 * 3. 210.3.10 人工确认身份；
 * 4. 原始只读结果。
 *
 * 本层同时把身份修订加入 Context signature，并在身份发生
 * 变化时通知 Bootstrap 重新执行 resolve(true)。
 */
(() => {
  if (window.__jubaThreadsIdentityAuthority210315) {
    return;
  }

  window.__jubaThreadsIdentityAuthority210315 = true;

  const VERSION = "210.3.15";

  const SNAPSHOT_ID = "jubaopen-threads-page-snapshot-v1";

  const AUTO_BRIDGE_ID = "jubaopen-threads-auto-contact-v210315";

  const MANUAL_BRIDGE_ID = "jubaopen-threads-manual-contact-v210305";

  const DIAGNOSTIC_ID = "jubaopen-threads-identity-diagnostics-v210315";

  const EVENT_NAME = "jubaopen:threads-authoritative-identity-changed";

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

  let installed = false;
  let installTimer = 0;
  let observer = null;
  let pollTimer = 0;
  let previousSignature = "";
  let eventCount = 0;

  const clean = (value, max = 4096) =>
    String(value ?? "")
      .replace(/\u0000/g, "")
      .replace(
        /[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF]/g,
        ""
      )
      .trim()
      .slice(0, max);

  function normalizeUsername(value) {
    const result = clean(value, 100)
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

  function currentThreadId() {
    const match = location.pathname.match(
      /^\/messages\/t\/([^/?#]+)/
    );

    if (!match) {
      return "";
    }

    try {
      return clean(
        decodeURIComponent(match[1]),
        256
      );
    } catch (_) {
      return clean(match[1], 256);
    }
  }

  function readMeta(id) {
    const node = document.getElementById(id);

    if (!node) {
      return null;
    }

    try {
      const value = JSON.parse(
        node.getAttribute("content") || "{}"
      );

      return (
        value &&
        typeof value === "object"
      ) ? value : null;
    } catch (_) {
      return null;
    }
  }

  function normalizeIdentity(
    identity,
    expectedThreadId,
    mode
  ) {
    if (
      !identity ||
      identity.identityType !==
        "threads_username" ||
      identity.role !== "IS_PARTICIPANT" ||
      identity.stable !== true ||
      identity.confidence !== "high"
    ) {
      return null;
    }

    const identityThreadId = clean(identity.threadId, 256);

    if (
      !identityThreadId ||
      identityThreadId !==
        expectedThreadId
    ) {
      return null;
    }

    if (
      mode === "automatic" &&
      (
        identity.automaticallyVerified !== true ||
        identity.writable !== true
      )
    ) {
      return null;
    }

    if (
      mode === "manual" &&
      identity.confirmedByUser !== true
    ) {
      return null;
    }

    const identityValue = normalizeUsername(
        identity.identityValue
      );

    if (!identityValue) {
      return null;
    }

    return {
      identityType:
        "threads_username",
      identityValue,
      displayName:
        clean(
          identity.displayName ||
          `@${identityValue}`,
          200
        ) || `@${identityValue}`,
      avatarUrl:
        clean(identity.avatarUrl, 4096),
      threadId:
        expectedThreadId,
      source:
        clean(
          identity.source ||
          (
            mode === "automatic"
              ? "threads-auto-verified"
              : "threads-manual-confirmed"
          ),
          200
        ),
      verification:
        mode,
      confirmedByUser:
        identity.confirmedByUser === true,
      automaticallyVerified:
        identity.automaticallyVerified === true,
      evidence:
        identity.evidence &&
        typeof identity.evidence === "object"
          ? identity.evidence
          : {}
    };
  }

  function autoIdentity() {
    const threadId = currentThreadId();

    if (!threadId) {
      return null;
    }

    const payload = readMeta(AUTO_BRIDGE_ID);

    if (
      payload?.v !== 1 ||
      payload?.platform !== "threads" ||
      payload?.verified !== true ||
      clean(payload.threadId, 256) !==
        threadId
    ) {
      return null;
    }

    return normalizeIdentity(
      payload.identity,
      threadId,
      "automatic"
    );
  }

  function manualIdentity() {
    const threadId = currentThreadId();

    if (!threadId) {
      return null;
    }

    const payload = readMeta(MANUAL_BRIDGE_ID);

    if (
      payload?.v !== 1 ||
      payload?.platform !== "threads" ||
      clean(payload.threadId, 256) !==
        threadId
    ) {
      return null;
    }

    return normalizeIdentity(
      payload.identity,
      threadId,
      "manual"
    );
  }

  function rawProbeConversation() {
    const snapshot = readMeta(SNAPSHOT_ID);

    const item = snapshot?.conversation;

    const identity = item?.identity;

    if (
      !item ||
      item.writable !== true ||
      !identity ||
      identity.role !== "IS_PARTICIPANT" ||
      identity.stable !== true ||
      identity.confidence !== "high"
    ) {
      return null;
    }

    const threadId = clean(item.threadId, 256);

    if (
      !threadId ||
      threadId !== currentThreadId()
    ) {
      return null;
    }

    const type = clean(identity.identityType, 64);

    const raw = clean(identity.identityValue, 100);

    let normalized = "";

    if (
      type === "threads_username"
    ) {
      normalized = normalizeUsername(raw);
    } else if (
      type === "threads_user_id" &&
      /^[0-9]{5,30}$/.test(raw)
    ) {
      normalized = raw;
    }

    if (!normalized) {
      return null;
    }

    return {
      externalConversationId:
        "threads:" + threadId,
      identityType:
        type,
      identityValue:
        normalized,
      displayName:
        clean(identity.displayName, 200),
      avatarUrl:
        clean(identity.avatarUrl, 4096),
      readonly:
        false,
      metadata: {
        source:
          "threads-page-probe",
        confidence:
          "high",
        stable:
          true,
        writable:
          true,
        verification:
          "automatic",
        identityResolution:
          "probe-auto-verified",
        threadId,
        authorityVersion:
          VERSION
      }
    };
  }

  function bridgeConversation(identity) {
    if (!identity) {
      return null;
    }

    return {
      externalConversationId:
        "threads:" +
        identity.threadId,
      identityType:
        identity.identityType,
      identityValue:
        identity.identityValue,
      displayName:
        identity.displayName,
      avatarUrl:
        identity.avatarUrl,
      readonly:
        false,
      metadata: {
        source:
          identity.source,
        confidence:
          "high",
        stable:
          true,
        writable:
          true,
        verification:
          identity.verification,
        automaticallyVerified:
          identity.automaticallyVerified,
        confirmedByUser:
          identity.confirmedByUser,
        identityResolution:
          identity.verification === "automatic"
            ? "auto-verified"
            : "manual-confirmed",
        threadId:
          identity.threadId,
        evidence:
          identity.evidence,
        authorityVersion:
          VERSION
      }
    };
  }

  function conversationSignature(
    conversation
  ) {
    return [
      clean(
        conversation?.externalConversationId,
        300
      ),
      clean(
        conversation?.identityType,
        64
      ),
      clean(
        conversation?.identityValue,
        100
      ).toLowerCase(),
      conversation?.readonly === true
        ? "readonly"
        : "writable",
      clean(
        conversation?.metadata
          ?.identityResolution,
        100
      ),
      clean(
        conversation?.reason,
        300
      )
    ].join("|");
  }

  function ensureDiagnosticNode() {
    let node = document.getElementById(
        DIAGNOSTIC_ID
      );

    if (!node) {
      node = document.createElement("meta");

      node.id = DIAGNOSTIC_ID;
      node.hidden = true;

      (
        document.head ||
        document.documentElement
      ).appendChild(node);
    }

    return node;
  }

  function publishDiagnostics(
    reason = ""
  ) {
    const adapter = window.JubaAdapters?.threads;

    let conversation = null;
    let context = null;

    try {
      conversation = adapter?.conversation?.() || null;
    } catch (error) {
      conversation = {
        error: String(error)
      };
    }

    try {
      context = adapter?.context?.() || null;
    } catch (error) {
      context = {
        error: String(error)
      };
    }

    ensureDiagnosticNode().setAttribute(
      "content",
      JSON.stringify({
        v: 1,
        version: VERSION,
        at: Date.now(),
        installed,
        reason,
        eventCount,
        threadId:
          currentThreadId(),
        rawProbeIdentity:
          Boolean(
            rawProbeConversation()
          ),
        autoIdentity:
          autoIdentity(),
        manualIdentity:
          manualIdentity(),
        finalConversation:
          conversation,
        finalContext:
          context,
        finalWritable:
          Boolean(
            conversation &&
            conversation.readonly !== true &&
            conversation.identityType &&
            conversation.identityValue
          )
      })
    );
  }

  function install() {
    const adapter = window.JubaAdapters?.threads;

    if (
      !adapter ||
      typeof adapter.context !== "function" ||
      typeof adapter.conversation !== "function"
    ) {
      clearTimeout(installTimer);

      installTimer = setTimeout(
        install,
        50
      );

      return;
    }

    if (
      adapter.__identityAuthority210315 ===
        true
    ) {
      installed = true;
      return;
    }

    const originalContext = adapter.context.bind(adapter);

    const originalConversation = adapter.conversation.bind(adapter);

    const originalDiagnostics = typeof adapter.diagnostics === "function"
        ? adapter.diagnostics.bind(adapter)
        : () => ({
            platform: "threads"
          });

    adapter.conversation = () => {
      /*
       * 最高优先级：核心 Probe 已经严格验证的身份。
       */
      const probe = rawProbeConversation();

      if (probe) {
        return probe;
      }

      /*
       * 第二优先级：210.3.15 自动验证 Bridge。
       */
      const automatic = bridgeConversation(
          autoIdentity()
        );

      if (automatic) {
        return automatic;
      }

      /*
       * 第三优先级：210.3.10 人工确认 Adapter。
       */
      try {
        return originalConversation();
      } catch (_) {
        return null;
      }
    };

    adapter.context = () => {
      let original = null;

      try {
        original = originalContext();
      } catch (_) {}

      const conversation = adapter.conversation();

      if (
        !original &&
        !conversation
      ) {
        return null;
      }

      const route = clean(
          original?.route ||
          (
            location.pathname +
            location.search +
            location.hash
          ),
          2048
        );

      const threadId = currentThreadId() ||
        clean(original?.threadId, 256);

      const identityRevision = conversationSignature(
          conversation
        );

      return {
        ...(original || {}),
        platform:
          "threads",
        route,
        threadId,
        sequence:
          Number.isSafeInteger(
            Number(original?.sequence)
          )
            ? Number(original.sequence)
            : 0,
        generation:
          Number(original?.generation) ||
          0,
        at:
          Number(original?.at) ||
          Date.now(),
        signature: [
          "threads",
          route,
          threadId,
          identityRevision
        ].join("|"),
        contactIdentityRevision:
          identityRevision
      };
    };

    adapter.diagnostics = () => {
      let original = {};

      try {
        original = originalDiagnostics() || {};
      } catch (_) {}

      const conversation = adapter.conversation();

      return {
        ...original,
        identityAuthorityVersion:
          VERSION,
        rawProbeIdentityAccepted:
          Boolean(
            rawProbeConversation()
          ),
        autoIdentityAccepted:
          Boolean(autoIdentity()),
        manualIdentityAvailable:
          Boolean(manualIdentity()),
        finalIdentityType:
          conversation?.identityType || "",
        finalIdentityValue:
          conversation?.identityValue || "",
        finalReadonly:
          conversation?.readonly === true,
        finalIdentityResolution:
          conversation?.metadata
            ?.identityResolution || ""
      };
    };

    adapter.__identityAuthority210315 = true;
    installed = true;

    previousSignature = conversationSignature(
        adapter.conversation()
      );

    publishDiagnostics("INSTALLED");
  }

  function currentAuthoritySignature() {
    const adapter = window.JubaAdapters?.threads;

    if (!adapter) {
      return "";
    }

    let context = null;
    let conversation = null;

    try {
      context = adapter.context?.() || null;
    } catch (_) {}

    try {
      conversation = adapter.conversation?.() || null;
    } catch (_) {}

    return [
      clean(context?.signature, 4096),
      conversationSignature(
        conversation
      )
    ].join("||");
  }

  function emitIfChanged(
    reason,
    force = false
  ) {
    if (!installed) {
      return;
    }

    const signature = currentAuthoritySignature();

    if (
      !force &&
      signature === previousSignature
    ) {
      return;
    }

    const oldSignature = previousSignature;

    previousSignature = signature;
    eventCount += 1;

    window.dispatchEvent(
      new CustomEvent(
        EVENT_NAME,
        {
          detail: {
            platform: "threads",
            threadId:
              currentThreadId(),
            signature,
            oldSignature,
            reason,
            eventCount
          }
        }
      )
    );

    publishDiagnostics(reason);
  }

  function installObserver() {
    if (
      observer ||
      !document.documentElement
    ) {
      return;
    }

    observer = new MutationObserver(
        mutations => {
          for (
            const mutation of mutations
          ) {
            const target = mutation.target;

            if (
              target?.id === AUTO_BRIDGE_ID ||
              target?.id === MANUAL_BRIDGE_ID ||
              target?.id === SNAPSHOT_ID
            ) {
              emitIfChanged(
                "IDENTITY_BRIDGE_CHANGED"
              );

              return;
            }

            if (
              mutation.type === "childList"
            ) {
              const relevant = Array.from(
                  mutation.addedNodes || []
                ).some(node =>
                  node?.id === AUTO_BRIDGE_ID ||
                  node?.id === MANUAL_BRIDGE_ID ||
                  node?.id === SNAPSHOT_ID
                );

              if (relevant) {
                emitIfChanged(
                  "IDENTITY_NODE_ADDED"
                );

                return;
              }
            }
          }
        }
      );

    observer.observe(
      document.documentElement,
      {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: [
          "content"
        ]
      }
    );
  }

  install();
  installObserver();

  pollTimer = setInterval(() => {
    install();
    installObserver();
    emitIfChanged(
      "IDENTITY_SIGNATURE_POLL"
    );
    publishDiagnostics("POLL");
  }, 700);

  window.addEventListener(
    "pagehide",
    () => {
      clearInterval(pollTimer);
      clearTimeout(installTimer);
      observer?.disconnect();
    },
    {
      once: true
    }
  );
})();
