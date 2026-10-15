"use strict";
/*
 * JubaOpen Threads Adapter 210.3.4
 *
 * 读取 MAIN world threads-page-probe.js 写入的 DOM 快照。
 * 无可靠 ownIdentity 时 account() 返回 null，保持安全只读状态。
 */
(() => {
  const NODE_ID = "jubaopen-threads-page-snapshot-v1";
  const MAX_AGE = 30000;

  window.JubaAdapters = window.JubaAdapters || {};

  const clean = (value, max = 65536) =>
    String(value ?? "")
      .replace(/\u0000/g, "")
      .trim()
      .slice(0, max);

  function snapshot() {
    const node = document.getElementById(NODE_ID);
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

      const at = Number(value.at);
      if (
        !Number.isFinite(at) ||
        Date.now() - at > MAX_AGE ||
        at - Date.now() > 5000
      ) {
        return null;
      }

      return value;
    } catch (_) {
      return null;
    }
  }

  function context() {
    const value = snapshot();
    if (!value) return null;

    const route = clean(value.route, 2048);
    const threadId = clean(
      value.conversation?.threadId,
      256
    );
    const sequence = Number(value.sequence);
    const generation = Number(value.generation) || 0;

    if (
      !route ||
      !Number.isSafeInteger(sequence) ||
      sequence < 0
    ) {
      return null;
    }

    return {
      platform: "threads",
      route,
      threadId,
      sequence,
      generation,
      at: Number(value.at),
      signature:
        `threads|${route}|${threadId}`
    };
  }

  function account() {
    const value = snapshot();
    const identity = value?.ownIdentity;

    if (
      !identity ||
      identity.role !== "IS_OWNER" ||
      identity.stable !== true ||
      identity.confidence !== "high"
    ) {
      return null;
    }

    const type = clean(identity.identityType, 64);
    const raw = clean(identity.identityValue, 100);
    let normalized = "";

    if (type === "threads_user_id") {
      normalized = /^[0-9]{5,30}$/.test(raw)
        ? raw
        : "";
    } else if (type === "threads_username") {
      normalized = /^[a-z0-9._]{1,64}$/i.test(raw)
        ? raw.toLowerCase()
        : "";
    }

    if (!normalized) return null;

    return {
      identityType: type,
      identityValue: normalized,
      displayName: clean(identity.displayName, 200),
      metadata: {
        source: clean(
          identity.source || "threads-page-probe",
          80
        ),
        confidence: "high"
      }
    };
  }

  function conversation() {
    const value = snapshot();
    const item = value?.conversation;

    if (!item) return null;

    const threadId = clean(item.threadId, 256);
    if (!threadId) return null;

    const identity = item.identity;
    const base = {
      externalConversationId: "threads:" + threadId
    };

    if (
      item.writable !== true ||
      !identity ||
      identity.role !== "IS_PARTICIPANT"
    ) {
      return {
        ...base,
        readonly: true,
        reason: clean(
          item.readonlyReason ||
          "Threads 会话身份正在核验",
          300
        )
      };
    }

    const type = clean(identity.identityType, 64);
    const raw = clean(identity.identityValue, 100);

    if (
      type !== "threads_user_id" &&
      type !== "threads_username"
    ) {
      return {
        ...base,
        readonly: true,
        reason: "Threads 参与者身份类型无效"
      };
    }

    return {
      ...base,
      identityType: type,
      identityValue: raw,
      displayName: clean(identity.displayName, 200),
      avatarUrl: clean(identity.avatarUrl, 4096),
      metadata: {
        source: "threads-page-probe",
        confidence: clean(
          item.confidence || "medium",
          16
        )
      }
    };
  }

  function messages() {
    const value = snapshot();
    const list = Array.isArray(value?.messages)
      ? value.messages
      : [];

    return list.slice(-500).map(message =>
      window.JubaMessageProtocol.normalize({
        ...message,
        platform: "threads"
      })
    );
  }

  function diagnostics() {
    const value = snapshot();

    return {
      platform: "threads",
      adapterVersion: "210.3.4",
      snapshotAvailable: Boolean(value),
      ...(value?.diagnostics || {})
    };
  }


  /*
   * JUBAOPEN_3_5_3_IDENTITY_PROTOCOL_COMPAT
   *
   * Threads Adapter 原始接口使用扁平身份字段：
   *
   *   identityType
   *   identityValue
   *
   * 部分 Bootstrap/同步消费者同时读取嵌套身份结构。
   * 在 Adapter 输出边界补充兼容字段，保留原始扁平协议。
   *
   * 此处只对已经具有合法 identityType 和 identityValue 的
   * 可写会话或已就绪账号补充结构，不会把 readonly/null
   * 会话强制转换为可写状态。
   */

  function normalizeConversationIdentity(value) {
    if (!value || typeof value !== "object") {
      return value;
    }

    const identityType = clean(
      value.identityType ||
      value.identity?.identityType ||
      value.contact?.identityType ||
      value.contactIdentity?.identityType ||
      "",
      64
    );

    const identityValue = clean(
      value.identityValue ||
      value.identity?.identityValue ||
      value.contact?.identityValue ||
      value.contactIdentity?.identityValue ||
      "",
      100
    );

    if (!identityType || !identityValue) {
      return value;
    }

    const identity = {
      identityType,
      identityValue,
      displayName: clean(value.displayName, 200),
      avatarUrl: clean(value.avatarUrl, 4096),
      metadata: {
        ...(value.metadata || {})
      }
    };

    return {
      ...value,

      // 当前扁平身份协议
      identityType,
      identityValue,

      // Bootstrap/旧消费者兼容协议
      identity,

      contact: {
        ...(value.contact || {}),
        ...identity,
        identity
      },

      contactIdentity: {
        ...(value.contactIdentity || {}),
        ...identity
      },

      participant: {
        ...(value.participant || {}),
        ...identity,
        identity
      },

      identityState: "writable",
      writable: true,
      hasStableIdentity: true,

      metadata: {
        ...(value.metadata || {}),
        identityType,
        identityValue,
        stableIdentity: true,
        writable: true
      }
    };
  }

  function normalizeAccountIdentity(value) {
    if (!value || typeof value !== "object") {
      return value;
    }

    const identityType = clean(
      value.identityType ||
      value.identity?.identityType ||
      value.accountIdentity?.identityType ||
      "",
      64
    );

    const identityValue = clean(
      value.identityValue ||
      value.identity?.identityValue ||
      value.accountIdentity?.identityValue ||
      "",
      100
    );

    if (!identityType || !identityValue) {
      return value;
    }

    const identity = {
      identityType,
      identityValue,
      displayName: clean(value.displayName, 200),
      avatarUrl: clean(value.avatarUrl, 4096),
      metadata: {
        ...(value.metadata || {})
      }
    };

    return {
      ...value,

      // 当前扁平身份协议
      identityType,
      identityValue,

      // Bootstrap/旧消费者兼容协议
      identity,
      accountIdentity: identity,

      identityState: "ready",
      ready: true,

      metadata: {
        ...(value.metadata || {}),
        identityType,
        identityValue,
        stableIdentity: true,
        ready: true
      }
    };
  }

  function compatibleConversation() {
    return normalizeConversationIdentity(
      conversation()
    );
  }

  function compatibleAccount() {
    return normalizeAccountIdentity(
      account()
    );
  }

  window.JubaAdapters.threads = {
    code: "threads",
    capabilities:
      window.JubaMessageProtocol.capabilities.threads,
    matches: () =>
      /^(?:www\.)?threads\.com$/i.test(
        location.hostname
      ) &&
      location.pathname.startsWith("/messages"),
    account: compatibleAccount,
    context,
    conversation: compatibleConversation,
    messages,
    diagnostics
  };
})();

