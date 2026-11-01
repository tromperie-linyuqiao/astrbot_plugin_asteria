/* Administration page layering. All business DOM, forms and handlers are reused. */
(function (global) {
  'use strict';
  if (global.TLSAdminPanels) return;

  const configs = {
    assets: {
      filters: [{list: '#assets-records', title: '筛选本页素材', placeholder: '说明、标签或素材编号'}]
    },
    narrative: {editors: [
      {form: '#narrative-preference-form', title: '互动方式', hint: '当前会话的表达与陪伴偏好'}
    ]},
    phone: {
      filters: [
        {list: '#app-rules-records', title: '筛选本页规则', placeholder: '规则名称、应用或条件'},
        {list: '#phone-library-records', title: '筛选已载入文案', placeholder: '文案内容或来源'}
      ]
    },
    phone_flow: {editors: [
      {form: '#native-flow-preferences', whole: false, title: '会话回复偏好', hint: '风格、篇幅和提问习惯'},
      {form: '#native-flow-quiet-form', whole: false, title: '临时免打扰', hint: '明确设定结束时间'}
    ]},
    personal_goals: {editors: [{panel: '[data-goal-editor]', title: '目标详情与维护',
      triggers: '[data-goal-action="new"], [data-goal-list] button', focus: true, hint: '选择目标后查看来源、进度和记录'}]},
    memo_notes: {editors: [{panel: '.memo-editor', title: '便签详情与提醒',
      triggers: '[data-memo-action="new"], [data-memo-list] button', focus: true, hint: '选择便签后编辑、完成或归档'}]},
    music_library: {editors: [{form: '[data-music-form]', title: '曲目详情与编辑',
      triggers: '[data-music-action="new"], [data-music-list] button', focus: true, hint: '曲目信息、标签、评价与来源'}]},
    dates: {editors: [{panel: '[data-date-editor]', title: '日期详情与维护',
      triggers: '[data-date-action="new"], [data-date-list] button', focus: true, hint: '生日、纪念日和重复规则'}]},
    profile_candidates: {editors: [{panel: '[data-profile-detail]', title: '候选详情与审核',
      triggers: '[data-profile-list] button', focus: true, hint: '先查看原文与证据，再批准或拒绝'}]},
    expression: {filters: [{list: '#expression-records', title: '筛选本页表达规则', placeholder: '原词、替换文本或规则'}]},
    tasks: {filters: [{list: '#task-records', items: ':scope > section.panel > article.record', title: '筛选已载入任务', placeholder: '任务内容或状态'}]}
  };
  const wrappers = new WeakMap();
  const views = new WeakMap();
  const filters = new Set();
  const editorObservers = new Set();
  let mountObserver = null;
  let frame = 0;
  let activeView = null;
  let suspended = false;

  function el(tag, text, cls) {
    const value = document.createElement(tag);
    if (text !== undefined) value.textContent = text;
    if (cls) value.className = cls;
    return value;
  }

  function reveal(element, focus) {
    if (!element || !element.isConnected) return;
    for (let parent = element.closest('details'); parent; parent = parent.parentElement?.closest('details')) parent.open = true;
    if (focus) {
      const target = element.querySelector('h2, h3, summary') || element;
      if (!target.hasAttribute('tabindex')) target.tabIndex = -1;
      target.focus({preventScroll: true});
      element.scrollIntoView({block: 'start', behavior: 'auto'});
    }
  }

  function editorPanel(view, spec) {
    const form = spec.form && view.querySelector(spec.form);
    const panel = spec.panel ? view.querySelector(spec.panel) : spec.whole === false ? form : form?.closest('section.panel');
    if (!panel || panel.closest('dialog') || panel.closest('.ap-editor') || wrappers.has(panel)) return;
    // Existing controller-owned hidden editors and drawers keep their lifecycle.
    if (panel.hidden || panel.closest('[hidden]') !== null) return;
    const details = el('details', undefined, 'ap-editor');
    const summary = el('summary');
    summary.append(el('span', spec.title, 'ap-editor-title'), el('span', spec.hint || '展开查看和维护', 'ap-editor-hint'));
    const body = el('div', undefined, 'ap-editor-body');
    panel.before(details);
    details.append(summary, body);
    body.append(panel);
    panel.parentElement.parentElement.parentElement.classList.add('ap-managed-layout');
    wrappers.set(panel, details);

    if (spec.triggers) {
      // Only clicks in this view's explicit list/new controls reveal its editor.
      view.addEventListener('click', event => {
        const control = event.target.closest(spec.triggers);
        if (!control || !view.contains(control) || control.disabled) return;
        details.open = true;
        if (spec.focus) queueMicrotask(() => {
          if (!suspended && !view.hidden && !document.querySelector('dialog[open]')) reveal(details, true);
        });
      }, true);
    }
    // Global quick-create calls the existing controller directly. A disabled →
    // editable transition reveals that same form without replacing its state.
    const fieldset = panel.querySelector('fieldset');
    if (fieldset) {
      let editable = !fieldset.disabled;
      const observer = new MutationObserver(() => {
        const next = !fieldset.disabled;
        if (next && !editable) details.open = true;
        editable = next;
      });
      observer.observe(fieldset, {attributes: true, attributeFilter: ['disabled']});
      editorObservers.add({observer, fieldset});
      if (editable) details.open = true;
    }
    // Native validation can point at a collapsed field; let it become visible.
    panel.addEventListener('invalid', () => { details.open = true; }, true);
  }

  function installFilter(view, spec) {
    const list = view.querySelector(spec.list);
    if (!list || list.dataset.apFilterReady) return;
    list.dataset.apFilterReady = 'true';
    const tools = el('div', undefined, 'ap-page-tools');
    const label = el('label', spec.title, 'ap-filter-controls');
    const input = el('input', undefined, 'ap-local-filter');
    input.type = 'search'; input.maxLength = 120;
    input.placeholder = spec.placeholder;
    input.setAttribute('aria-label', spec.title);
    const count = el('span', '仅筛选本页已载入记录', 'ap-filter-count');
    count.setAttribute('role', 'status');
    label.append(input);
    const clear = el('button', '清除筛选'); clear.type = 'button';
    const empty = el('p', '本页没有匹配项。可清除筛选，或使用原列表翻页与服务器检索。', 'ap-filter-empty');
    empty.hidden = true;
    tools.append(label, clear, count, empty);
    list.before(tools);
    function apply() {
      const query = input.value.trim().toLocaleLowerCase();
      const cards = spec.items ? Array.from(list.querySelectorAll(spec.items)) :
        Array.from(list.children).filter(child => child.matches('article, .record, .module, .compact-item, [data-task-id]'));
      let matched = 0;
      for (const card of cards) {
        const keep = !query || card.textContent.toLocaleLowerCase().includes(query);
        if (keep) { card.removeAttribute('data-ap-filtered'); matched++; }
        else card.dataset.apFiltered = 'true';
      }
      count.textContent = cards.length ? `本页 ${matched} / ${cards.length} 条 · 仅已载入记录` : '仅筛选本页已载入记录';
      clear.disabled = !input.value;
      empty.hidden = !query || !cards.length || matched > 0;
    }
    input.addEventListener('input', apply);
    clear.addEventListener('click', () => {input.value = ''; apply(); input.focus();});
    const observer = new MutationObserver(apply);
    observer.observe(list, {childList: true, subtree: true, characterData: true});
    filters.add({list, input, apply, observer});
    apply();
  }

  function outline(view) {
    let value = views.get(view);
    if (!value) {value = {}; views.set(view, value);}
    const candidates = Array.from(view.querySelectorAll('section.panel, .ap-editor')).filter(panel => {
      if (panel.closest('dialog') || panel.hidden) return false;
      const ancestor = panel.parentElement.closest('section.panel, .ap-editor');
      return !ancestor || !view.contains(ancestor);
    });
    const entries = candidates.map(panel => ({panel, title: (panel.querySelector('.ap-editor-title, h2, h3')?.textContent || '').trim()})).filter(item => item.title);
    const signature = entries.map(item => item.title).join('|');
    if (value.signature === signature && value.outline?.isConnected) return;
    value.signature = signature;
    if (!value.outline) {
      value.outline = el('nav', undefined, 'ap-page-outline');
      value.outline.setAttribute('aria-label', '本页分区');
      view.prepend(value.outline);
    }
    value.outline.replaceChildren();
    value.outline.hidden = entries.length < 2;
    if (entries.length < 2) return;
    value.outline.append(el('span', '本页分区', 'ap-outline-label'));
    for (const item of entries) {
      const button = el('button', item.title); button.type = 'button';
      button.addEventListener('click', () => {if (item.panel.matches('details')) item.panel.open = true; reveal(item.panel, true);});
      value.outline.append(button);
    }
  }

  function enhance(view) {
    if (!view || view.hidden) return;
    const config = configs[view.id.replace(/^view-/, '')] || {};
    for (const spec of config.editors || []) editorPanel(view, spec);
    for (const spec of config.filters || []) installFilter(view, spec);
    outline(view);
  }

  function activate(viewName) {
    if (suspended) return;
    mountObserver?.disconnect(); mountObserver = null;
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    activeView = viewName ? document.getElementById('view-' + viewName) : document.querySelector('.view:not([hidden])');
    if (!activeView) return;
    enhance(activeView);
    // Watch only the visible view for a late module mount. Text/status updates
    // and mutations inside an already wrapped editor do not re-run layering.
    const observed = activeView;
    const config = configs[observed.id.replace(/^view-/, '')] || {};
    const selectors = [...(config.editors || []).map(spec => spec.panel || spec.form), ...(config.filters || []).map(spec => spec.list)].filter(Boolean);
    if (!selectors.length) return;
    mountObserver = new MutationObserver(records => {
      if (observed !== activeView || observed.hidden || frame) return;
      const matches = records.some(record => Array.from(record.addedNodes).some(added => added.nodeType === 1 && !added.closest('.ap-editor') && selectors.some(selector => added.matches(selector) || added.querySelector(selector))));
      if (!matches) return;
      frame = requestAnimationFrame(() => {frame = 0; if (observed === activeView) enhance(observed);});
    });
    mountObserver.observe(observed, {childList: true, subtree: true});
  }

  document.addEventListener('tls-admin-viewchange', event => activate(event.detail?.view));
  global.addEventListener('tls-admin-viewchange', event => {
    // Shell dispatches on window; document-dispatched events are handled above.
    if (event.target === global) activate(event.detail?.view);
  });
  document.getElementById('scope-select')?.addEventListener('change', () => {
    for (const filter of filters) {filter.input.value = ''; filter.apply();}
  });
  global.addEventListener('pagehide', () => {
    suspended = true;
    mountObserver?.disconnect();
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    for (const filter of filters) filter.observer.disconnect();
    for (const item of editorObservers) item.observer.disconnect();
  });
  global.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    suspended = false;
    for (const filter of filters) filter.observer.observe(filter.list, {childList: true, subtree: true, characterData: true});
    for (const item of editorObservers) item.observer.observe(item.fieldset, {attributes: true, attributeFilter: ['disabled']});
    activate();
  });
  global.TLSAdminPanels = Object.freeze({refresh: () => activate()});
  activate();
})(window);
