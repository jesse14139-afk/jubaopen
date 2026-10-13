"use strict";
window.JubaAdapters=window.JubaAdapters||{};
window.JubaAdapters.facebook={
 code:"facebook",
 capabilities:window.JubaMessageProtocol.capabilities.facebook,
 matches:()=>location.hostname.endsWith("facebook.com")&&location.pathname.startsWith("/messages"),
 account:()=>window.JubaMeta.account("facebook"),
 context:()=>window.JubaMeta.context("facebook"),
 conversation:()=>window.JubaMeta.conversation("facebook","facebook:"),
 messages:()=>window.JubaMeta.messages("facebook","facebook:"),
 diagnostics:()=>window.JubaMeta.diagnostics("facebook")
};
