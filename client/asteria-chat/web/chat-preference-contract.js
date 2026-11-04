'use strict';

/* Existing TLS response shapes. A readable response and a confirmed write differ. */
window.ChatPreferenceContract = (() => {
  const object = value => !!value && typeof value === 'object' && !Array.isArray(value);
  const revision = value => Number.isSafeInteger(value) && value >= 0;
  const replyOptions = {
    reply_style: ['inherit', 'natural', 'warm', 'direct'],
    reply_length: ['inherit', 'short', 'balanced', 'detailed'],
    rp_intensity: ['inherit', 'light', 'balanced', 'immersive'],
    reply_format: ['auto', 'text', 'structured'],
  };
  const expressionFields = ['frequency', 'per_unit', 'cooldown_seconds', 'fragment_display', 'mode_policies'];
  const modes = ['chat', 'roleplay', 'technical'];
  const sameField = (left, right, key) => key === 'mode_policies'
    ? modes.every(mode => left?.[mode] === right?.[mode]) : left === right;
  function expressionValue(key, value) {
    if (key === 'frequency') return ['off', 'low', 'balanced', 'expressive'].includes(value);
    if (key === 'per_unit') return typeof value === 'boolean';
    if (key === 'cooldown_seconds') return Number.isInteger(value) && value >= 0 && value <= 86400;
    if (key === 'fragment_display') return ['semantic', 'compact'].includes(value);
    return object(value) && modes.every(mode => ['semantic', 'paragraph', 'single', 'text_only'].includes(value[mode]));
  }
  function reply(value, session) {
    if (!object(value) || value.session_id !== session || !revision(value.revision)
      || Object.entries(replyOptions).some(([key, options]) => !options.includes(value[key])))
      throw new Error('会话偏好返回不完整、格式不兼容或会话不匹配。');
    return value;
  }
  function expression(value, session) {
    // The current endpoint does not echo a session ID. Its HTTP request remains scope-bound.
    if (!object(value) || ('session_id' in value && value.session_id !== session)
      || !revision(value.session_revision) || !object(value.session) || !object(value.effective) || !object(value.sources)
      || expressionFields.some(key => !expressionValue(key, value.effective[key])
        || !['session', 'role', 'default'].includes(value.sources[key])
        || (key in value.session && (!expressionValue(key, value.session[key])
          || value.sources[key] !== 'session' || !sameField(value.session[key], value.effective[key], key)))
        || (!(key in value.session) && value.sources[key] === 'session')))
      throw new Error('表情策略返回不完整、格式不兼容或会话不匹配。');
    return value;
  }
  function confirmReply(value, session, previous, expected) {
    reply(value, session);
    if (value.revision <= previous || Object.keys(replyOptions).some(key => value[key] !== expected[key]))
      throw new Error('服务器返回未确认本次回复偏好。');
    return value;
  }
  function confirmExpression(value, session, previous, expected) {
    expression(value, session);
    if (value.session_revision <= previous || (expected === null
      ? Object.keys(value.session).length !== 0
      : expressionFields.some(key => !(key in value.session)
        || !sameField(value.session[key], expected[key], key))))
      throw new Error('服务器返回未确认本次表情策略。');
    return value;
  }
  return Object.freeze({ reply, expression, confirmReply, confirmExpression });
})();
