# WhatsApp 左侧列表倒计时专项诊断 v2

## 用途
定位“只有当前打开会话显示倒计时，其他有跟进计划的可见客户不显示”的具体断点。

## 运行步骤
1. 使用 JubaOpen 210.1.12，打开 `https://web.whatsapp.com/`。
2. 让后台已设置倒计时的 3 个客户尽量同时出现在左侧可见区域。
3. 按 F12，打开 **Console/控制台**。
4. 打开 `wa_list_followup_probe_v2.js`，复制全部内容到控制台并回车。若 Chrome 阻止粘贴，按其提示手动输入 `allow pasting` 后再粘贴。
5. 在 30 秒检测期间，缓慢上下滚动左侧会话列表一次，不要快速切换账号。
6. 检测结束后浏览器会自动下载 `juba-wa-list-followup-v2-*.json`。
7. 将 JSON 文件发回进行分析。

## 隐私
报告包含左侧可见名称及 WA JID/LID，用于逐行关联；不包含聊天正文、Cookie、Token、本地存储、头像或网络请求正文。

## 判定字段
- `visibleRowCount`：实际可见列表行数。
- `identifiedByBridgeAttr`：被页面探针写入可靠身份的行数。
- `identifiedByReact`：从 React 结构发现原生 JID/LID 的行数。
- `finalExternalIdCount`：进入 bootstrap 批量查询候选的行数。
- `followupBoundRowCount`：后端结果已绑定的行数。
- `badgeCount`：实际显示的倒计时数量。
