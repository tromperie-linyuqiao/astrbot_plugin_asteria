'use strict';
/* Entries reuse the existing settings hub and each feature's own lifecycle. */
document.addEventListener('DOMContentLoaded', () => {
  const menu = document.getElementById('more-menu');
  for (const [id, label, open] of [
    ['menu-notification-center', '通知中心', () => window.ChatNotificationCenter?.open()],
    ['menu-model-route', '本会话模型', () => window.ChatModelRoute?.open()],
    ['menu-memory-search', '查找相关记忆', () => window.ChatMessageMemory?.openSearch()],
    ['menu-delivery-center', '主动消息送达中心', () => window.ChatDeliveryCenter?.openDelivery()],
    ['menu-session-preferences', '本会话偏好', () => window.ChatSessionPreferences?.open()],
    ['menu-connection-center', '连接与缓存状态', () => window.ChatDeliveryCenter?.openConnection()]
  ]) {
    const button = document.createElement('button'); button.type = 'button'; button.id = id;
    button.className = 'menu-item'; button.textContent = label;
    button.addEventListener('click', () => { hideMoreMenu(); window.ChatSettingsHub?.close(); open(); });
    menu.append(button);
  }
}, { once: true });
