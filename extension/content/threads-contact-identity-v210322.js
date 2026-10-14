"use strict";

/*
 * JUBAOPEN_THREADS_CONTACT_IDENTITY_210_3_22
 *
 * 联系人领域身份规范化边界：
 *
 * 页面识别原始类型：
 *   threads_username
 *
 * 联系人领域规范类型：
 *   username
 *
 * 原始类型保存在：
 *   metadata.sourceIdentityType
 */
(() => {
if (
  window.__jubaThreadsContactIdentity210322
) {
  return;
}

window.__jubaThreadsContactIdentity210322 =
  true;

const VERSION = "210.3.22";

const clean = (
  value,
  max = 4096
) =>
  String(value ?? "")
    .replace(/\u0000/g, "")
    .replace(
      /[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF]/g,
      ""
    )
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, max);

function normalizeConversation(raw) {
  if (
    !raw ||
    typeof raw !== "object"
  ) {
    return raw || null;
  }

  const metadata =
    raw.metadata &&
    typeof raw.metadata === "object"
      ? raw.metadata
      : {};

  const sourceIdentityType =
    clean(
      metadata.sourceIdentityType ||
      raw.identityType ||
      metadata.identityType,
      64
    ).toLowerCase();

  const identityType =
    sourceIdentityType ===
    "threads_username"
      ? "username"
      : sourceIdentityType;

  return {
    ...raw,

    platform:
      "threads",

    identityType,

    metadata: {
      ...metadata,

      platform:
        "threads",

      identityType,

      sourceIdentityType:
        sourceIdentityType ||
        identityType,

      contactIdentityContractVersion:
        VERSION
    }
  };
}

function install() {
  const adapter =
    window.JubaAdapters?.threads;

  if (!adapter) {
    return false;
  }

  if (
    adapter.__jubaContactIdentity210322
  ) {
    return true;
  }

  const originalConversation =
    typeof adapter.conversation === "function"
      ? adapter.conversation.bind(adapter)
      : null;

  const originalDiagnostics =
    typeof adapter.diagnostics === "function"
      ? adapter.diagnostics.bind(adapter)
      : null;

  if (!originalConversation) {
    return false;
  }

  adapter.conversation = () =>
    normalizeConversation(
      originalConversation()
    );

  adapter.diagnostics = () => {
    let original = {};

    if (originalDiagnostics) {
      try {
        const value =
          originalDiagnostics();

        if (
          value &&
          typeof value === "object"
        ) {
          original = value;
        }
      } catch (error) {
        return {
          platform:
            "threads",

          version:
            VERSION,

          accepted:
            false,

          ok:
            false,

          blocked:
            true,

          canRegister:
            false,

          canCreateContact:
            false,

          code:
            "DIAGNOSTICS_THROW",

          reason:
            String(
              error?.message ||
              error
            ),

          error:
            String(
              error?.stack ||
              error
            )
        };
      }
    }

    let conversation = null;

    try {
      conversation =
        adapter.conversation();
    } catch (error) {
      return {
        platform:
          "threads",

        version:
          VERSION,

        accepted:
          false,

        ok:
          false,

        blocked:
          true,

        canRegister:
          false,

        canCreateContact:
          false,

        code:
          "CONVERSATION_THROW",

        reason:
          String(
            error?.message ||
            error
          ),

        error:
          String(
            error?.stack ||
            error
          )
      };
    }

    const accepted =
      Boolean(
        conversation &&
        conversation.identityType ===
          "username" &&
        clean(
          conversation.identityValue,
          512
        ) &&
        clean(
          conversation.externalConversationId,
          512
        ) &&
        conversation.stable === true &&
        conversation.writable === true &&
        conversation.readonly !== true
      );

    /*
     * 不展开旧 diagnostics。
     * ACCEPTED 状态创建一份干净对象，
     * 避免旧负面字段继续影响 Chat Panel。
     */
    if (accepted) {
      return {
        platform:
          "threads",

        version:
          VERSION,

        installed:
          true,

        accepted:
          true,

        ok:
          true,

        code:
          "ACCEPTED",

        diagnosticCode:
          "ACCEPTED",

        reason:
          "CONTACT_IDENTITY_ACCEPTED",

        conversation,

        finalConversation:
          conversation,

        panelConversation:
          conversation,

        externalConversationId:
          conversation
            .externalConversationId,

        identityType:
          conversation
            .identityType,

        identityValue:
          conversation
            .identityValue,

        stable:
          true,

        writable:
          true,

        readonly:
          false,

        finalStable:
          true,

        finalWritable:
          true,

        finalReadonly:
          false,

        stableContactIdentity:
          true,

        stableContactIdentityMissing:
          false,

        contactIdentityMissing:
          false,

        identityMissing:
          false,

        identityAccepted:
          true,

        panelIdentityAccepted:
          true,

        panelIdentityCode:
          "ACCEPTED",

        blocked:
          false,

        canRegister:
          true,

        canCreateContact:
          true,

        errors:
          [],

        warnings:
          [],

        reasons:
          [],

        conversationReasons:
          [],

        diagnosticsReasons:
          [],

        contactIdentityContractVersion:
          VERSION
      };
    }

    return {
      platform:
        "threads",

      version:
        VERSION,

      installed:
        true,

      accepted:
        false,

      ok:
        false,

      code:
        "CONTACT_IDENTITY_NOT_WRITABLE",

      diagnosticCode:
        "CONTACT_IDENTITY_NOT_WRITABLE",

      reason:
        "CONTACT_IDENTITY_NOT_WRITABLE",

      conversation,

      blocked:
        true,

      canRegister:
        false,

      canCreateContact:
        false,

      stableContactIdentity:
        false,

      stableContactIdentityMissing:
        true,

      contactIdentityMissing:
        true,

      identityMissing:
        true,

      errors: [
        "CONTACT_IDENTITY_NOT_WRITABLE"
      ],

      warnings:
        [],

      reasons: [
        "CONTACT_IDENTITY_NOT_WRITABLE"
      ],

      contactIdentityContractVersion:
        VERSION,

      upstreamCode:
        clean(
          original.code ||
          original.diagnosticCode,
          128
        ),

      upstreamReason:
        clean(
          original.reason,
          512
        )
    };
  };

  adapter.__jubaContactIdentity210322 =
    true;

  return true;
}

if (!install()) {
  let attempts = 0;

  const timer = setInterval(
    () => {
      attempts += 1;

      if (
        install() ||
        attempts >= 100
      ) {
        clearInterval(timer);
      }
    },
    50
  );
}
})();
