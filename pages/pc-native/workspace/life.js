/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {fetchJson} from './client.js';
import {allBookshelfBooks,bookshelfBookId,ensureCreativeProjectDetail,renderBookCoverInner,renderBookPreferenceEditor,renderCreativeBookPreview,renderCreativeManager,transitionBookshelfPage} from './library.js';
import {donutChart,showToast} from './persona.js';
import {shortName} from './providers.js';
import {displaySettingValue,formatProactiveDailyLabel,formatProactiveDailyQuota,formatProactiveLimit,toBool} from './schema.js';
import {fillForm,markModuleFormClean,moduleWorkbenchCard,renderAccessManager,renderCurrentPersonaStatus,renderExternalAbilities,renderFeatureSwitches,renderPresetCards,renderRoleplaySavedReading} from './settings.js';
import {$,NEED_LAYER_LABELS,asteriaWorkspaceState,state} from './state.js';
import {bookshelfImageTag,escapeHtml,hydrateBookshelfImages,renderAppearanceSettings,renderConfigBackups,renderConfigImportChecks,renderConfigMigrationPreview} from './workspace.js';

export function selectBookshelfBook(bookId) {
  const book = allBookshelfBooks().find((item) => bookshelfBookId(item) === bookId);
  if (!book) return;
  asteriaWorkspaceState.bookshelfReturnFocusBookId = bookId;
  transitionBookshelfPage("detail", {
    mutate: () => {
      state.selectedBook = book;
      state.creativeEditing = false;
      state.selectedBookSpreadIndex = 0;
      if (book.kind === "diary") {
        const entries = Array.isArray(book.entries) ? book.entries : [];
        state.selectedDiaryDate = entries[entries.length - 1]?.date || "";
      }
      if (book.kind === "browsing") {
        const entries = Array.isArray(book.entries) ? book.entries : [];
        state.selectedBrowsingIndex = Math.max(0, entries.length - 1);
      }
    },
    afterCommit: () => {
      if (book.kind === "creative") void ensureCreativeProjectDetail(book);
    },
  });
}

export function renderBookDetailPanel() {
  const panel = $("#bookDetailPanel");
  if (!panel) return;
  panel.dataset.bookshelfView = state.bookshelfPage === "reader" ? "reader" : "detail";
  const book = state.selectedBook;
  if (!book || state.bookshelfPage === "shelf") {
    panel.hidden = true;
    panel.innerHTML = "";
    return;
  }
  const kindLabel = {
    creative: book.work_type || "创作书",
    diary: "日记本",
    browsing: "浏览记录",
    jm_album: "私密阅读",
  }[book.kind] || "书";
  const entryBook = ["diary", "browsing"].includes(book.kind || "");
  const diaryEntries = entryBook && Array.isArray(book.entries) ? book.entries : [];
  const selectedDiaryDate = state.selectedDiaryDate || diaryEntries[diaryEntries.length - 1]?.date || "";
  const diaryEntry = diaryEntries.find((entry) => entry.date === selectedDiaryDate) || diaryEntries[diaryEntries.length - 1] || null;
  if (entryBook && diaryEntry && state.selectedDiaryDate !== diaryEntry.date) {
    state.selectedDiaryDate = diaryEntry.date;
  }
  const displayTitle = entryBook && diaryEntry
    ? (book.kind === "diary" ? `${diaryEntry.date} 的日记` : (diaryEntry.title || diaryEntry.date || "浏览记录"))
    : (book.title || "未命名");
  const displayIntro = entryBook && diaryEntry ? (diaryEntry.intro || book.intro) : (book.intro || book.progress || "这本书还没有简介。");
  const displayContent = entryBook && diaryEntry ? (diaryEntry.content || diaryEntry.intro || book.content) : (book.content || book.intro || "这本书暂时没有正文。");
  const diarySelector = diaryEntries.length
    ? `
      <label class="diary-date-picker">
        <span>${book.kind === "diary" ? "日期" : "记录"}</span>
        <select data-diary-date>
          ${diaryEntries.slice().reverse().map((entry) => `<option value="${escapeHtml(entry.date)}"${entry.date === state.selectedDiaryDate ? " selected" : ""}>${escapeHtml(entry.date)}</option>`).join("")}
        </select>
      </label>
    `
    : "";
  const activeTags = entryBook && diaryEntry ? diaryEntry.tags : book.tags;
  const tags = Array.isArray(activeTags) && activeTags.length
    ? `<div class="book-tags">${activeTags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>`
    : "";
  const preferenceEditor = renderBookPreferenceEditor(book);
  const readingImpressionText = book.kind === "jm_album"
    ? String(book.reading_impression || book.impression || "").replace(/^读后感[:：]\s*/, "").trim()
    : "";
  const pageCommentCount = book.kind === "jm_album"
    ? Number(book.page_comment_count ?? (Array.isArray(book.page_comments) ? book.page_comments.length : 0))
    : 0;
  const botRating = Number(book.rating || 0);
  const userRating = Number(book.user_rating || 0);
  const ratingReason = String(book.user_rating_reason || book.rating_reason || "").trim();
  const ratingMeta = book.kind === "jm_album" && (botRating || userRating || ratingReason)
    ? `
      <div class="book-rating-row">
        ${botRating ? `<span>Bot 评分 <b>${escapeHtml(botRating)}/10</b></span>` : ""}
        ${userRating ? `<span>你的评分 <b>${escapeHtml(userRating)}/10</b></span>` : ""}
        ${ratingReason ? `<small>${escapeHtml(ratingReason)}</small>` : ""}
      </div>
    `
    : "";
  const readingImpression = readingImpressionText
    ? `
      <section class="book-reading-impression">
        <span>Bot 的读后感</span>
        ${ratingMeta}
        <p>${escapeHtml(readingImpressionText)}</p>
      </section>
    `
    : ratingMeta
      ? `<section class="book-reading-impression"><span>读后评分</span>${ratingMeta}</section>`
    : "";
  const manageActions = book.kind === "browsing" ? "" : `
    <div class="book-manage-actions">
      ${book.kind === "jm_album" ? `<button type="button" data-book-reread>让 Bot 重读</button>` : ""}
      <button type="button" class="danger-outline" data-book-delete
        data-book-kind="${escapeHtml(book.kind || "")}"
        data-book-id="${escapeHtml(book.id || "")}"
        data-book-album-id="${escapeHtml(book.album_id || "")}"
        data-book-title="${escapeHtml(book.title || "")}"
        data-book-date="${escapeHtml(book.kind === "diary" ? (state.selectedDiaryDate || "") : "")}">
        ${escapeHtml(book.kind === "diary" ? "删除当前日记" : "从书柜移除")}
      </button>
    </div>
  `;
  panel.hidden = false;
  if (state.bookshelfPage === "reader" && book.kind === "jm_album" && Array.isArray(book.pages) && book.pages.length) {
    panel.innerHTML = renderJmAlbumReader(book, kindLabel, displayTitle, displayIntro, readingImpression);
    void hydrateBookshelfImages(panel);
    return;
  }
  if (state.bookshelfPage === "reader" && book.kind === "diary") {
    panel.innerHTML = renderDiaryBookReader(book, kindLabel, diaryEntries, diaryEntry);
    return;
  }
  if (state.bookshelfPage === "reader" && book.kind === "browsing") {
    panel.innerHTML = renderBrowsingBookReader(book, kindLabel, diaryEntries);
    return;
  }
  if (state.bookshelfPage === "reader" && book.kind === "creative") {
    panel.innerHTML = renderCreativeBookReader(book, kindLabel, displayTitle, displayIntro, displayContent);
    void hydrateBookshelfImages(panel);
    return;
  }
  if (book.kind === "creative" && state.bookshelfPage === "detail") {
    panel.innerHTML = state.creativeEditing
      ? renderCreativeManager(book, kindLabel, displayTitle, displayIntro)
      : renderCreativeBookPreview(book, kindLabel, displayTitle, displayIntro, displayContent);
    void hydrateBookshelfImages(panel);
    return;
  }
  panel.innerHTML = state.bookshelfPage === "reader"
    ? `
      <article class="reader-page subpage ${escapeHtml(book.kind || "book")}">
        <nav class="book-breadcrumb">
          <button type="button" data-book-close>书柜</button>
          <span>/</span>
          <button type="button" data-book-back>${escapeHtml(book.title || "未命名")}</button>
          <span>/ 阅读</span>
        </nav>
        <div class="reader-toolbar">
          <button type="button" data-book-back>返回简介</button>
          <span>${escapeHtml(kindLabel)}</span>
          <button type="button" data-book-close>收回书柜</button>
        </div>
        <div class="reader-book-shell">
          <aside class="reader-cover ${book.cover_src ? "has-cover-image" : ""}">
            ${renderBookCoverInner(book, kindLabel, displayTitle, book.progress || "")}
          </aside>
          <section class="reader-paper">
            <header class="reader-page-head">
              <span>${escapeHtml(kindLabel)}</span>
              <h2>${escapeHtml(displayTitle)}</h2>
              ${displayIntro ? `<p>${escapeHtml(displayIntro)}</p>` : ""}
            </header>
            <div class="reader-content">${formatBookContent(displayContent || "这本书暂时没有正文。")}</div>
            <footer class="reader-page-foot">
              <span>${escapeHtml(book.created || "书柜藏本")}</span>
              <span>${escapeHtml(book.tone || book.status || "")}</span>
            </footer>
          </section>
        </div>
      </article>
    `
    : `
      <article class="book-preview subpage ${escapeHtml(book.kind || "book")}">
        <div class="book-preview-cover ${book.cover_src ? "has-cover-image" : ""}">
          ${renderBookCoverInner(book, kindLabel, book.title || "未命名")}
        </div>
        <div class="book-preview-info">
          <nav class="book-breadcrumb">
            <button type="button" data-book-close>书柜</button>
            <span>/ ${escapeHtml(kindLabel)}</span>
          </nav>
          <div class="reader-toolbar">
            <span>${escapeHtml(kindLabel)}</span>
            <button type="button" data-book-close>收回书柜</button>
          </div>
          <h2>${escapeHtml(book.title || "未命名")}</h2>
          <p>${escapeHtml(displayIntro)}</p>
          ${diarySelector}
          <dl>
            ${book.status ? `<div><dt>状态</dt><dd>${escapeHtml(book.status)}</dd></div>` : ""}
            ${book.author ? `<div><dt>作者</dt><dd>${escapeHtml(book.author)}</dd></div>` : ""}
            ${book.tone ? `<div><dt>气质</dt><dd>${escapeHtml(book.tone)}</dd></div>` : ""}
            ${book.point_of_view ? `<div><dt>视角</dt><dd>${escapeHtml(book.point_of_view)}</dd></div>` : ""}
            ${book.progress ? `<div><dt>进度</dt><dd>${escapeHtml(book.progress)}</dd></div>` : ""}
            ${book.kind === "jm_album" ? `<div><dt>备注</dt><dd>${escapeHtml(pageCommentCount)} 条</dd></div>` : ""}
            ${book.created ? `<div><dt>入柜</dt><dd>${escapeHtml(book.created)}</dd></div>` : ""}
          </dl>
          ${readingImpression}
          ${tags}
          ${preferenceEditor}
          ${manageActions}
          <button type="button" class="read-button" data-book-read>开始阅读</button>
        </div>
      </article>
    `;
  void hydrateBookshelfImages(panel);
}

export function renderJmAlbumReader(book, kindLabel, displayTitle, displayIntro, readingImpression = "") {
  const pages = Array.isArray(book.pages) ? book.pages : [];
  const pageCommentCount = Number(book.page_comment_count ?? (Array.isArray(book.page_comments) ? book.page_comments.length : pages.filter((page) => String(page.comment || "").trim()).length));
  const maxStart = Math.max(0, pages.length - (pages.length % 2 === 0 ? 2 : 1));
  const start = Math.min(Math.max(0, Number(state.selectedBookSpreadIndex || 0)), maxStart);
  state.selectedBookSpreadIndex = start % 2 === 0 ? start : start - 1;
  const spread = pages.slice(state.selectedBookSpreadIndex, state.selectedBookSpreadIndex + 2);
  const firstPage = spread[0]?.index || state.selectedBookSpreadIndex + 1;
  const lastPage = spread[spread.length - 1]?.index || firstPage;
  const isLastSpread = state.selectedBookSpreadIndex + 2 >= pages.length;
  const progressPage = Math.max(0, Number(book.reading_progress_page || 0));
  const progressTotal = Math.max(0, Number(book.reading_progress_total || pages.length)) || pages.length;
  const progressLabel = progressPage > 0 ? (progressPage >= progressTotal ? "已读完" : `上次读到 ${progressPage}/${progressTotal}`) : "尚未开始";
  const bookmark = String(book.reading_bookmark || "").trim();
  const userRating = Number(book.user_rating || 0);
  const userRatingReason = String(book.user_rating_reason || "").trim();
  const ratingPanel = isLastSpread
    ? `
      <section class="manga-rating-panel">
        <div>
          <span>读完评分</span>
          <b>${userRating ? `你给了 ${escapeHtml(userRating)}/10` : "读完后给它打个分"}</b>
          ${userRatingReason ? `<p>${escapeHtml(userRatingReason)}</p>` : ""}
        </div>
        <div class="manga-rating-buttons" data-book-rating-album="${escapeHtml(book.album_id || "")}">
          ${Array.from({ length: 10 }, (_, index) => {
            const value = index + 1;
            return `<button type="button" data-book-rating="${value}" class="${userRating === value ? "is-active" : ""}">${value}</button>`;
          }).join("")}
        </div>
      </section>
    `
    : "";
  return `
    <article class="reader-page subpage jm_album image-reader">
      <nav class="book-breadcrumb">
        <button type="button" data-book-close>书柜</button>
        <span>/</span>
        <button type="button" data-book-back>${escapeHtml(book.title || "未命名")}</button>
        <span>/ 阅读</span>
      </nav>
      <div class="reader-toolbar">
        <button type="button" data-book-back>返回简介</button>
        <span>${escapeHtml(kindLabel)} · ${escapeHtml(firstPage)}-${escapeHtml(lastPage)} / ${escapeHtml(pages.length)} · ${escapeHtml(progressLabel)} · 备注 ${escapeHtml(pageCommentCount)} 条</span>
        <button type="button" data-book-close>收回书柜</button>
      </div>
      <div class="manga-reader-shell">
        <header class="manga-reader-head">
          <div>
            <span>${escapeHtml(kindLabel)}</span>
            <h2>${escapeHtml(displayTitle)}</h2>
            ${displayIntro ? `<p>${escapeHtml(displayIntro)}</p>` : ""}
          </div>
          <div class="manga-reader-actions">
            <button type="button" data-book-prev ${state.selectedBookSpreadIndex <= 0 ? "disabled" : ""}>上一页</button>
            <button type="button" data-book-next ${state.selectedBookSpreadIndex + 2 >= pages.length ? "disabled" : ""}>下一页</button>
            <button type="button" data-book-reread>让 Bot 重读</button>
            <button type="button" class="danger-outline" data-book-delete
              data-book-kind="${escapeHtml(book.kind || "")}"
              data-book-id="${escapeHtml(book.id || "")}"
              data-book-album-id="${escapeHtml(book.album_id || "")}"
              data-book-title="${escapeHtml(book.title || "")}">从书柜移除</button>
          </div>
        </header>
        ${readingImpression}
        <section class="manga-reading-state">
          <span>${escapeHtml(progressLabel)}</span>
          <label>书签 <input type="text" maxlength="120" value="${escapeHtml(bookmark)}" placeholder="留一句只给自己看的标记" data-book-bookmark></label>
          <button type="button" data-book-save-progress>保存书签</button>
        </section>
        <div class="manga-spread">
          ${spread.map((page, spreadIndex) => {
            const comment = String(page.comment || "").trim();
            const note = comment
              ? `<details class="manga-page-note ${spreadIndex === 0 ? "left" : "right"}"><summary>Bot 批注</summary><p>${escapeHtml(comment)}</p></details>`
              : "";
            return `
            <figure class="manga-page ${comment ? `has-note ${spreadIndex === 0 ? "note-left" : "note-right"}` : ""}">
              ${spreadIndex === 0 ? note : ""}
              <div class="manga-page-image">
                ${bookshelfImageTag(page.src, `${book.title || "私密阅读"} 第 ${page.index} 页`)}
                <figcaption>${escapeHtml(page.index)} / ${escapeHtml(pages.length)}</figcaption>
              </div>
              ${spreadIndex !== 0 ? note : ""}
            </figure>
          `; }).join("")}
          ${spread.length < 2 ? `<figure class="manga-page blank"><span>末页</span></figure>` : ""}
        </div>
        ${ratingPanel}
      </div>
    </article>
  `;
}

export function renderDiaryBookReader(book, kindLabel, entries, selectedEntry) {
  const rows = Array.isArray(entries) ? entries : [];
  const current = selectedEntry || rows[rows.length - 1] || {};
  const currentDate = current.date || state.selectedDiaryDate || "";
  const tags = Array.isArray(current.tags) && current.tags.length
    ? `<div class="book-tags">${current.tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>`
    : "";
  return `
    <article class="reader-page subpage diary diary-reader-page">
      <nav class="book-breadcrumb">
        <button type="button" data-book-close>书柜</button>
        <span>/</span>
        <button type="button" data-book-back>${escapeHtml(book.title || "日记本")}</button>
        <span>/ 阅读</span>
      </nav>
      <div class="reader-toolbar">
        <button type="button" data-book-back>返回简介</button>
        <span>${escapeHtml(kindLabel)} · ${escapeHtml(rows.length)} 天</span>
        <button type="button" data-book-close>收回书柜</button>
      </div>
      <div class="diary-reader-shell">
        <aside class="diary-date-rail">
          <header>
            <span>日期</span>
            <b>${escapeHtml(rows.length)}</b>
          </header>
          <div class="diary-date-list">
            ${rows.slice().reverse().map((entry) => `
              <button type="button" data-diary-jump="${escapeHtml(entry.date || "")}" class="${entry.date === currentDate ? "is-active" : ""}">
                <b>${escapeHtml(entry.date || "某天")}</b>
                <span>${escapeHtml(shortName(entry.intro || entry.content || "没有摘要", 34))}</span>
              </button>
            `).join("")}
          </div>
        </aside>
        <section class="reader-paper diary-paper">
          <header class="reader-page-head">
            <span>${escapeHtml(current.generated_at || "日记")}</span>
            <h2>${escapeHtml(currentDate ? `${currentDate} 的日记` : "日记")}</h2>
            ${current.intro ? `<p>${escapeHtml(current.intro)}</p>` : ""}
          </header>
          ${tags}
          <div class="reader-content diary-reader-content">${formatBookContent(current.content || current.intro || "这一天的日记暂时没有正文。")}</div>
          <footer class="reader-page-foot">
            <span>${escapeHtml(book.created || "夹层日记")}</span>
            <button type="button" class="danger-outline" data-book-delete
              data-book-kind="diary"
              data-book-id="${escapeHtml(book.id || "")}"
              data-book-title="${escapeHtml(book.title || "")}"
              data-book-date="${escapeHtml(currentDate)}">删除当前日记</button>
          </footer>
        </section>
      </div>
    </article>
  `;
}

export function renderBrowsingBookReader(book, kindLabel, entries) {
  const rows = Array.isArray(entries) ? entries : [];
  const safeIndex = rows.length ? Math.max(0, Math.min(rows.length - 1, Number(state.selectedBrowsingIndex || 0))) : 0;
  state.selectedBrowsingIndex = safeIndex;
  const current = rows[safeIndex] || {};
  const tags = Array.isArray(current.tags) && current.tags.length
    ? `<div class="book-tags">${current.tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>`
    : "";
  const url = String(current.source_url || "").trim();
  const href = browsingSourceHref(url);
  const addressText = url || current.query || current.title || "about:blank";
  return `
    <article class="reader-page subpage browsing browsing-reader-page">
      <nav class="book-breadcrumb">
        <button type="button" data-book-close>书柜</button>
        <span>/</span>
        <button type="button" data-book-back>${escapeHtml(book.title || "浏览记录")}</button>
        <span>/ 阅读</span>
      </nav>
      <div class="browser-shell">
        <header class="browser-chrome">
          <div class="browser-dots"><i></i><i></i><i></i></div>
          <div class="browser-address">
            <span>${escapeHtml(current.source_label || kindLabel)}</span>
            <b title="${escapeHtml(addressText)}">${escapeHtml(addressText)}</b>
          </div>
          <button type="button" data-book-close>收回书柜</button>
        </header>
        <div class="browser-body">
          <aside class="browser-history-sidebar">
            <header>
              <b>历史记录</b>
              <span>${escapeHtml(rows.length)} 条</span>
            </header>
            <div class="browser-history-list">
              ${rows.slice().reverse().map((entry) => {
                const originalIndex = rows.indexOf(entry);
                const entrySource = entry.source_label || "记录";
                const entryTitle = entry.title || entry.query || "未命名记录";
                const entryTime = entry.generated_at || entry.date || "时间未知";
                const isCurrent = originalIndex === safeIndex;
                return `
                  <button type="button" data-browsing-index="${escapeHtml(originalIndex)}" class="${isCurrent ? "is-active" : ""}" aria-current="${isCurrent ? "true" : "false"}" title="${escapeHtml(entryTitle)}">
                    <span class="browser-history-meta">
                      <span>${escapeHtml(entrySource)}</span>
                      <small>${escapeHtml(entryTime)}</small>
                    </span>
                    <b>${escapeHtml(entryTitle)}</b>
                  </button>
                `;
              }).join("")}
            </div>
          </aside>
          <section class="browser-page-view">
            <header>
              <span>${escapeHtml(current.source_label || "浏览记录")}</span>
              <h2>${escapeHtml(current.title || current.query || "未命名记录")}</h2>
              ${current.query ? `<p>搜索词：${escapeHtml(current.query)}</p>` : ""}
            </header>
            ${tags}
            <div class="browser-note-content">${formatBookContent(current.content || current.intro || "这条浏览记录暂时没有正文。")}</div>
            <footer>
              <span>${escapeHtml(current.generated_at || current.date || "未知时间")}</span>
              ${url ? `<button type="button" class="browser-source-copy" data-copy-source-url="${escapeHtml(href)}">复制链接</button>` : ""}
            </footer>
          </section>
        </div>
      </div>
    </article>
  `;
}

export function browsingSourceHref(url) {
  const text = String(url || "").trim();
  if (!text) return "";
  if (/^(https?:|mailto:)/i.test(text)) return text;
  return `https://${text.replace(/^\/+/, "")}`;
}

export function setBookshelfUnlockMessage(text, tone = "") {
  const message = $("#bookshelfUnlockMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("ok", tone === "ok");
  message.classList.toggle("error", tone === "error");
}

export function formatBookContent(value) {
  const parts = String(value || "")
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean);
  return parts.length
    ? parts.map((part) => `<p>${escapeHtml(part)}</p>`).join("")
    : `<p>这本书暂时没有正文。</p>`;
}

export function creativeReadingMode(book) {
  const type = String(book?.work_type || book?.category || "").toLowerCase();
  if (/诗|歌词|歌/.test(type)) return "poetry";
  if (/剧本|短剧|脚本|对白|分镜/.test(type)) return "script";
  if (/设定|世界观|角色|图鉴|怪谈|档案/.test(type)) return "lore";
  if (/随笔|散文|札记|观察|影评|读后感/.test(type)) return "essay";
  return "prose";
}

export function creativeModeLabel(mode) {
  return {
    poetry: "诗页",
    script: "剧本",
    lore: "设定册",
    essay: "札记",
    prose: "正文",
  }[mode] || "正文";
}

export function splitCreativeChunks(book, fallbackContent) {
  const chunks = Array.isArray(book?.chunks) ? book.chunks : [];
  const rows = chunks
    .map((chunk, index) => ({
      index: Number.isInteger(Number(chunk.index)) && Number(chunk.index) >= 0 ? Number(chunk.index) + 1 : index + 1,
      text: String(chunk.text || "").trim(),
      created: String(chunk.created || "").trim(),
    }))
    .filter((chunk) => chunk.text);
  if (rows.length) return rows;
  return [{ index: 1, text: String(fallbackContent || "").trim() || "这本书还没有正文。", created: "" }];
}

export function formatCreativeScript(text) {
  const lines = String(text || "").split(/\n+/).map((line) => line.trim()).filter(Boolean);
  return lines.length
    ? lines.map((line) => {
      const match = line.match(/^([^：:]{1,14})[：:]\s*(.+)$/);
      if (match) {
        return `<p class="script-line"><b>${escapeHtml(match[1])}</b><span>${escapeHtml(match[2])}</span></p>`;
      }
      return `<p class="script-stage">${escapeHtml(line)}</p>`;
    }).join("")
    : `<p class="script-stage">这段剧本还没有正文。</p>`;
}

export function formatCreativeLore(text) {
  const blocks = String(text || "").split(/\n{2,}/).map((part) => part.trim()).filter(Boolean);
  return blocks.length
    ? blocks.map((block) => {
      const lines = block.split(/\n+/).map((line) => line.trim()).filter(Boolean);
      const head = lines[0] || "设定条目";
      const body = lines.slice(1).join("\n") || block;
      return `
        <section class="lore-entry">
          <b>${escapeHtml(head.replace(/^#+\s*/, ""))}</b>
          <p>${escapeHtml(body)}</p>
        </section>
      `;
    }).join("")
    : `<section class="lore-entry"><b>空白条目</b><p>这本设定册还没有正文。</p></section>`;
}

export function formatCreativeContentByMode(text, mode) {
  if (mode === "poetry") {
    const lines = String(text || "").split(/\n+/).map((line) => line.trim()).filter(Boolean);
    return `<div class="poem-lines">${(lines.length ? lines : ["这首诗还没有正文。"]).map((line) => `<p>${escapeHtml(line)}</p>`).join("")}</div>`;
  }
  if (mode === "script") return formatCreativeScript(text);
  if (mode === "lore") return formatCreativeLore(text);
  return formatBookContent(text);
}

export function renderCreativeBookReader(book, kindLabel, displayTitle, displayIntro, displayContent) {
  const mode = creativeReadingMode(book);
  const chunks = splitCreativeChunks(book, displayContent);
  const chunkNav = chunks.length > 1
    ? `<aside class="creative-chapter-rail">
        <span>片段</span>
        ${chunks.map((chunk) => `<a href="#creative-chunk-${escapeHtml(chunk.index)}">${escapeHtml(chunk.index)}</a>`).join("")}
      </aside>`
    : "";
  const contentHtml = chunks.map((chunk) => `
    <section class="creative-reader-chunk" id="creative-chunk-${escapeHtml(chunk.index)}">
      <header>
        <span>${escapeHtml(creativeModeLabel(mode))} ${escapeHtml(chunk.index)}</span>
        ${chunk.created ? `<small>${escapeHtml(chunk.created)}</small>` : ""}
      </header>
      <div class="reader-content creative-content ${escapeHtml(mode)}">${formatCreativeContentByMode(chunk.text, mode)}</div>
    </section>
  `).join("");
  return `
    <article class="reader-page subpage creative creative-reader ${escapeHtml(mode)}">
      <nav class="book-breadcrumb">
        <button type="button" data-book-close>书柜</button>
        <span>/</span>
        <button type="button" data-book-back>${escapeHtml(book.title || "未命名")}</button>
        <span>/ 阅读</span>
      </nav>
      <div class="reader-toolbar">
        <button type="button" data-book-back>返回简介</button>
        <span>${escapeHtml(kindLabel)} · ${escapeHtml(creativeModeLabel(mode))}</span>
        <button type="button" data-book-close>收回书柜</button>
      </div>
      <div class="reader-book-shell creative-shell ${escapeHtml(mode)}">
        <aside class="reader-cover creative-cover ${escapeHtml(mode)} ${book.cover_src ? "has-cover-image" : ""}">
          ${renderBookCoverInner(book, kindLabel, displayTitle, book.progress || "")}
        </aside>
        <section class="reader-paper creative-paper ${escapeHtml(mode)}">
          <header class="reader-page-head">
            <span>${escapeHtml(kindLabel)} · ${escapeHtml(book.point_of_view || "无固定叙事视角")}</span>
            <h2>${escapeHtml(displayTitle)}</h2>
            ${displayIntro ? `<p>${escapeHtml(displayIntro)}</p>` : ""}
          </header>
          <div class="creative-reader-body">
            ${chunkNav}
            <div class="creative-reader-main">${contentHtml}</div>
          </div>
          <footer class="reader-page-foot">
            <span>${escapeHtml(book.created || "书柜藏本")}</span>
            <span>${escapeHtml(book.tone || book.status || "")}</span>
          </footer>
        </section>
      </div>
    </article>
  `;
}

export function proactiveSemanticLabel(kind) {
  const labels = {
    greeting: "问候",
    care: "关心",
    self_share: "自我分享",
    external_share: "外界分享",
    continuation: "续话",
    reminder: "提醒",
    observation: "观察",
    light_touch: "轻触碰",
    check_in: "确认一下",
  };
  return labels[kind] || kind || "";
}

export function proactiveAnchorLabel(anchor) {
  const labels = {
    recent_context: "近期上下文",
    group_context: "群聊上下文",
    inner_life: "内在状态",
    current_activity: "当前活动",
    important_date: "重要日期",
    external_info: "外界信息",
    time_ritual: "时间仪式",
    environment: "环境",
    topic_hint: "话题线索",
    vague: "由头偏弱",
  };
  return labels[anchor] || anchor || "";
}

export function proactivePercent100(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num) || num <= 0) return "";
  return `${Math.round(num)}%`;
}

export function proactiveScore01(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num) || num <= 0) return "";
  return `${Math.round(num * 100)}%`;
}

export function needLayerLabel(raw) {
  return NEED_LAYER_LABELS[raw] || (raw ? raw : "未分类");
}

export function proactiveSemanticMeta(item) {
  const meta = [];
  if (item.semantic_kind) meta.push(`语义：${proactiveSemanticLabel(item.semantic_kind)}`);
  if (item.semantic_anchor_type) meta.push(`锚点：${proactiveAnchorLabel(item.semantic_anchor_type)}`);
  const semanticScore = proactivePercent100(item.semantic_score);
  if (semanticScore) meta.push(`贴合：${semanticScore}`);
  const pressure = proactivePercent100(item.semantic_pressure);
  if (pressure) meta.push(`压力：${pressure}`);
  const risk = proactivePercent100(item.semantic_risk);
  if (risk) meta.push(`风险：${risk}`);
  if (item.semantic_note) meta.push(`语义说明：${item.semantic_note}`);
  const needLayer = item.need_layer || item.need_level || item.maslow_level;
  if (needLayer) meta.push(`需求：${needLayerLabel(needLayer)}`);
  if (item.need_drive) meta.push(`驱动：${item.need_drive}`);
  if (item.need_note) meta.push(`需求说明：${item.need_note}`);
  return meta;
}

export function proactiveWindowPhaseLabel(phase) {
  const labels = {
    before: "还没到点",
    best: "最佳表达期",
    tail: "余温期",
    expired: "已过期",
    unknown: "未记录",
  };
  return labels[phase] || phase || "";
}

export function proactiveWindowMeta(item) {
  const meta = [];
  if (item.window_phase) meta.push(`窗口：${proactiveWindowPhaseLabel(item.window_phase)}`);
  if (item.window_detail) meta.push(item.window_detail);
  const value = proactivePercent100(item.impulse_value);
  if (value) meta.push(`念头强度：${value}`);
  if (item.best_until_ts) meta.push(`最佳到：${item.best_until || "-"}`);
  if (item.expire_ts) meta.push(`过期：${item.expire || "-"}`);
  if (item.planned_impulse_id) meta.push(`impulse：${item.planned_impulse_id}`);
  return meta;
}

export function proactiveReadinessMeta(item) {
  const readiness = item?.inner_readiness || {};
  const meta = [];
  const score = proactiveScore01(readiness.score);
  if (score) meta.push(`开口欲：${score}${readiness.label ? ` · ${readiness.label}` : ""}`);
  if (readiness.drive_label || readiness.drive_detail) {
    meta.push(`状态：${[readiness.drive_label, readiness.drive_detail].filter(Boolean).join(" · ")}`);
  }
  if (readiness.temperature_label || readiness.temperature_detail) {
    meta.push(`关系温度：${[readiness.temperature_label, readiness.temperature_detail].filter(Boolean).join(" · ")}`);
  }
  const motivation = readiness.motivation || {};
  if (motivation.label || motivation.detail || motivation.score) {
    const parts = [
      proactiveScore01(motivation.score),
      motivation.label,
      motivation.detail,
    ].filter(Boolean);
    meta.push(`动机调度：${parts.join(" · ")}`);
  }
  return meta;
}

export function proactiveAfterglowHtml(source) {
  const afterglow = source?.afterglow || {};
  if (!afterglow.label && !afterglow.next_tendency) return "";
  const meta = [
    afterglow.time ? `记录：${afterglow.time}` : "",
    afterglow.status ? `结果：${afterglow.status}` : "",
    afterglow.semantic_kind ? `语义：${proactiveSemanticLabel(afterglow.semantic_kind)}` : "",
    afterglow.next_tendency ? `下次倾向：${afterglow.next_tendency}` : "",
  ].filter(Boolean);
  return `
    <div class="proactive-afterglow">
      <b>主动余韵</b>
      <span>${escapeHtml(afterglow.label || "有一条主动余韵")}</span>
      ${meta.length ? `<div class="proactive-meta">${meta.map((value) => `<span>${escapeHtml(value)}</span>`).join("")}</div>` : ""}
    </div>
  `;
}

export function proactiveHesitationMeta(item) {
  const hesitation = item?.hesitation || {};
  const meta = [];
  if (hesitation.note) meta.push(`犹豫：${hesitation.note}`);
  if (hesitation.count) meta.push(`收住次数：${hesitation.count}`);
  if (hesitation.time) meta.push(`犹豫记录：${hesitation.time}`);
  if (hesitation.topic) meta.push(`原话题：${hesitation.topic}`);
  return meta;
}

export function proactiveModelJudgeMeta(item) {
  const judge = item?.model_judge || {};
  const meta = [];
  if (judge.decision) meta.push(`模型判定：${judge.decision}${judge.score ? ` · ${judge.score}` : ""}`);
  if (judge.reason) meta.push(`判定原因：${judge.reason}`);
  if (judge.judged_ts) meta.push(`判定时间：${judge.judged || "-"}`);
  return meta;
}

export function renderProactiveCandidates() {
  const data = state.overview?.proactive_candidates || {};
  const tasks = state.overview?.proactive_tasks || {};
  const counts = data.counts || {};
  const runtime = tasks.runtime || {};
  $("#proactiveSummary").innerHTML = [
    proactiveSummaryCard("已登记任务", tasks.total ?? 0, "计划不代表已经发送"),
    proactiveSummaryCard("候选触发", data.total ?? 0, `${data.record_total ?? 0} 条原始记录，可能合并显示`),
    proactiveSummaryCard("候选发送记录", counts.sent ?? 0, "不代表客户端已接收或已读"),
    proactiveSummaryCard("执行记录", tasks.audit_total ?? 0, "发送、延后与失败分别记录"),
    proactiveSummaryCard("运行观察", runtime.healthy ? "近期有记录" : "待确认", runtime.last_tick_started || "尚无心跳"),
  ].join("");
  $("#proactiveSourceChart").innerHTML = donutChart(data.source_counts || {}, {
    emptyText: "暂无来源数据", labelFormatter: label => data.source_labels?.[label] || proactiveCandidateSourceLabel(label),
    maxSegments: 6, mergeBelowPercent: 0.035, otherLabel: "其他来源",
  });
  $("#proactiveStatusChart").innerHTML = donutChart(counts, {emptyText: "暂无状态数据", labelFormatter: proactiveStatusLabel});
  renderProactiveTasks();
}

export function renderProactiveTasks() {
  const data = state.overview?.proactive_tasks || {};
  $("#proactiveRuntimeDetails").innerHTML = proactiveRuntimeHtml(data.runtime || {})
    + proactiveUserStateHtml(Array.isArray(data.user_states) ? data.user_states : []);
  renderProactiveRecords();
}

export function proactiveRecordRows(view) {
  const data = state.overview || {};
  const rows = view === "candidates" ? data.proactive_candidates?.items
    : view === "audit" ? data.proactive_tasks?.audit_items : data.proactive_tasks?.items;
  return Array.isArray(rows) ? rows.filter(row => row && typeof row === "object") : [];
}

export function proactiveRecordLabel(view, row, kind) {
  if (kind === "status") return (view === "candidates" ? proactiveStatusLabel : view === "audit" ? proactiveAuditStatusLabel : proactiveTaskStatusLabel)(row.status);
  return view === "tasks" ? proactiveTaskSourceLabel(row.source, row.has_timer_event)
    : row.source_label || proactiveCandidateSourceLabel(row.source);
}

export function renderProactiveRecords() {
  const view = state.proactiveRecordView;
  const rows = proactiveRecordRows(view);
  const users = new Map();
  for (const type of ["tasks", "candidates", "audit"]) for (const row of proactiveRecordRows(type)) {
    if (row.user_id) users.set(String(row.user_id), row.user_label || row.user_id);
  }
  for (const row of state.overview?.proactive_candidates?.users || []) {
    if (row.user_id) users.set(String(row.user_id), row.label || row.user_id);
  }
  const fill = (selector, values, selected, label) => {
    const value = selected === "all" || values.has(selected) ? selected : "all";
    $(selector).innerHTML = `<option value="all">${label}</option>` + [...values].map(([key, text]) =>
      `<option value="${escapeHtml(key)}">${escapeHtml(text)}</option>`).join("");
    $(selector).value = value;
    return value;
  };
  state.proactiveCandidateFilter = fill("#proactiveRecordUser", users, state.proactiveCandidateFilter, "全部用户");
  state.proactiveRecordStatus = fill("#proactiveRecordStatus", new Map(rows.map(row => [String(row.status || "unknown"), proactiveRecordLabel(view, row, "status")])), state.proactiveRecordStatus, "全部状态");
  state.proactiveRecordSource = fill("#proactiveRecordSource", new Map(rows.map(row => [String(row.source || "unknown"), proactiveRecordLabel(view, row, "source")])), state.proactiveRecordSource, "全部来源");
  const query = state.proactiveRecordQuery.trim().toLocaleLowerCase();
  const filtered = rows.filter(row => {
    if (state.proactiveCandidateFilter !== "all" && String(row.user_id || "") !== state.proactiveCandidateFilter) return false;
    if (state.proactiveRecordStatus !== "all" && String(row.status || "unknown") !== state.proactiveRecordStatus) return false;
    if (state.proactiveRecordSource !== "all" && String(row.source || "unknown") !== state.proactiveRecordSource) return false;
    const text = [row.id, row.user_id, row.user_label, row.topic, row.motive, row.reason, row.reason_label,
      row.reason_detail, row.note, row.text_preview, row.final_text_preview, row.original_text_preview,
      row.job_id, row.planned_candidate_id, proactiveRecordLabel(view, row, "status"), proactiveRecordLabel(view, row, "source")].join(" ").toLocaleLowerCase();
    return !query || text.includes(query);
  });
  if (view === "tasks") filtered.sort((a, b) => Number(["due", "overdue"].includes(b.status)) - Number(["due", "overdue"].includes(a.status)));
  const size = 12, pages = Math.max(1, Math.ceil(filtered.length / size));
  state.proactiveRecordPage = Math.max(0, Math.min(state.proactiveRecordPage, pages - 1));
  const page = filtered.slice(state.proactiveRecordPage * size, (state.proactiveRecordPage + 1) * size);
  const roots = {tasks: "#proactiveTaskList", candidates: "#proactiveCandidateList", audit: "#proactiveAuditList"};
  for (const [type, selector] of Object.entries(roots)) {
    $(selector).hidden = type !== view;
    if (type !== view) $(selector).innerHTML = "";
  }
  const empty = rows.length ? "没有符合当前筛选的记录。可清除筛选查看本次返回资料。" : "本次未返回这类记录。没有记录不能推断消息已发送。";
  $(roots[view]).innerHTML = !page.length ? `<div class="empty small">${empty}</div>`
    : view === "tasks" ? page.map(proactiveTaskMarkup).join("")
    : view === "audit" ? proactiveAuditHtml(page) : page.map(proactiveCandidateMarkup).join("");
  $("#proactiveRecordCoverage").textContent = `本次载入 ${rows.length} 条 · 符合筛选 ${filtered.length} 条 · 第 ${state.proactiveRecordPage + 1} / ${pages} 页。仅筛选服务端返回的近期窗口，不代表全部历史。`;
  $("#proactiveRecordPrevious").disabled = state.proactiveRecordPage === 0;
  $("#proactiveRecordNext").disabled = state.proactiveRecordPage + 1 >= pages;
  document.querySelectorAll('[data-proactive-view]').forEach(button => {
    const type = button.dataset.proactiveView;
    button.setAttribute("aria-pressed", String(type === view));
    button.querySelector('span').textContent = proactiveRecordRows(type).length;
  });
}

export function proactiveCandidateMarkup(item) {
  const status = proactiveStatusLabel(item.status), repeat = Number(item.repeat_count || 1);
  const user = item.user_label || item.user_id || "-";
  const source = item.source_label || proactiveCandidateSourceLabel(item.source);
  const meta = [`用户：${user}`, `ID：${item.user_id || "-"}`, `计划：${item.scheduled || "-"}`,
    `创建：${item.created || "-"}`, `最近：${item.last_seen || "-"}`, `评分：${item.score || 0}`,
    item.reason_detail, item.note, ...proactiveSemanticMeta(item)].filter(Boolean);
  return `<details class="proactive-candidate aw-proactive-record ${escapeHtml(item.status || "unknown")}">
    <summary><div><b>${escapeHtml(item.topic || item.reason_label || item.reason || "未命名候选")}</b>
      <span>${escapeHtml(user)} · ${escapeHtml(source)} · ${escapeHtml(item.scheduled || item.created || "未记录时间")}</span></div>
      <span class="badge">${escapeHtml(status)}${repeat > 1 ? ` ×${repeat}` : ""}</span></summary>
    <div class="aw-proactive-detail"><p>${escapeHtml(item.motive || "暂无动机记录")}</p>
      <div class="proactive-meta">${meta.map(value => `<span>${escapeHtml(value)}</span>`).join("")}</div>
      <p class="aw-proactive-note">删除会移除该候选；若仍关联当前计划，后端还会清理关联并重新安排检查。不能撤回已开始或已发送的消息。限额整理会影响该用户的整个未发送候选池，不只当前筛选结果。</p>
      <div class="toolbar">
      ${item.id ? `<button type="button" class="danger-outline" data-proactive-candidate-delete="${escapeHtml(item.id)}" data-proactive-user-id="${escapeHtml(item.user_id || "")}">删除候选…</button>` : ""}
      ${item.user_id ? `<button type="button" data-proactive-candidate-prune="${escapeHtml(item.user_id)}" data-proactive-prune-keep="160">整理该用户候选（保留上限 160）…</button>` : ""}
      </div></div></details>`;
}

export function proactiveTaskMarkup(item) {
  const status = proactiveTaskStatusLabel(item.status);
  const source = proactiveTaskSourceLabel(item.source, item.has_timer_event);
  const title = item.topic || item.reason_label || item.reason || "未命名主动任务";
  const semanticMeta = proactiveSemanticMeta(item);
  const windowMeta = proactiveWindowMeta(item);
  const readinessMeta = proactiveReadinessMeta(item);
  const hesitationMeta = proactiveHesitationMeta(item);
  const modelJudgeMeta = proactiveModelJudgeMeta(item);
  const meta = [
    `用户：${item.user_label || item.user_id || "-"}`,
    `来源：${source}`,
    `动作：${item.action || "message"}`,
    item.reason_label ? `原因：${item.reason_label}` : "",
    item.reason_detail ? `为什么：${item.reason_detail}` : "",
    `计划：${item.scheduled || "-"}`,
    item.last_skip_reason ? `最近${item.last_skip_prefix || "跳过"}：${item.last_skip_reason}` : "",
    item.last_skip_ts ? `记录：${item.last_skip || "-"}` : "",
    item.created_ts ? `登记：${item.created || "-"}` : "",
    item.job_id ? `官方任务：${item.job_id}` : "",
    item.replaced_job_id ? `替换旧任务：${item.replaced_job_id}` : "",
    item.cancelled_job_id ? `取消任务：${item.cancelled_job_id}` : "",
    item.timer_status ? `预约状态：${item.timer_status}` : "",
    item.activity ? `用户动作：${item.activity}` : "",
    Number(item.estimated_minutes || 0) > 0 ? `预计耗时：${item.estimated_minutes} 分钟` : "",
    Number(item.followup_intensity || 0) > 0 ? `查岗强度：${item.followup_intensity}/3` : "",
    item.timer_error ? `错误：${item.timer_error}` : "",
    item.raw_time ? `原始时间：${item.raw_time}` : "",
    item.trigger_message_id ? `触发消息：${item.trigger_message_id}` : "",
    item.planned_candidate_id ? `candidate：${item.planned_candidate_id}` : "",
    item.silence_until_due ? "到点前静默" : "",
  ].filter(Boolean);
  return `
    <details class="proactive-task aw-proactive-record ${escapeHtml(item.status || "scheduled")}">
      <summary class="proactive-task-head">
        <div>
          <b>${escapeHtml(title)}</b>
          <span>${escapeHtml(item.user_label || item.user_id || "-")} · ${escapeHtml(item.user_role_label || "-")} · ${escapeHtml(source)} · ${escapeHtml(item.scheduled || "未记录时间")}</span>
        </div>
        <span class="badge">${escapeHtml(status)}</span>
      </summary>
      <div class="aw-proactive-detail"><p>${escapeHtml(item.motive || "暂无登记动机")}</p>
      <div class="proactive-meta">
        ${semanticMeta.map((value) => `<span class="proactive-semantic-chip">${escapeHtml(value)}</span>`).join("")}
        ${windowMeta.map((value) => `<span class="proactive-window-chip">${escapeHtml(value)}</span>`).join("")}
        ${readinessMeta.map((value) => `<span>${escapeHtml(value)}</span>`).join("")}
        ${hesitationMeta.map((value) => `<span>${escapeHtml(value)}</span>`).join("")}
        ${modelJudgeMeta.map((value) => `<span>${escapeHtml(value)}</span>`).join("")}
        ${meta.map((value) => `<span>${escapeHtml(value)}</span>`).join("")}
      </div>
      ${proactiveAfterglowHtml(item)}
      </div>
    </details>
  `;
}

export function proactiveUserStateHtml(items) {
  if (!items.length) return "";
  return `
    <div class="proactive-user-state-grid">
      ${items.map((item) => {
        const quota = `${item.sent_today ?? 0}/${item.effective_daily_limit_text || formatProactiveLimit(item.effective_daily_limit, item.effective_daily_limit_unlimited)}`;
        const status = item.proactive_sending ? "发送中" : item.next_proactive_ts ? "已排程" : "未排程";
        const readinessMeta = proactiveReadinessMeta(item);
        const hesitationMeta = proactiveHesitationMeta(item);
        const meta = [
          `今日：${quota}`,
          item.next_proactive_ts ? `下次：${item.next_proactive}` : "下次：-",
          item.last_sent_ts ? `上次主动：${item.last_sent}` : "",
          item.last_skip_reason ? `最近${item.last_skip_prefix || "跳过"}：${item.last_skip_reason}` : "",
          ...readinessMeta,
          ...hesitationMeta,
        ].filter(Boolean);
        return `
          <section class="proactive-user-state ${item.proactive_sending ? "running" : ""}">
            <div>
              <b>${escapeHtml(item.user_label || item.user_id || "-")}</b>
              <span>${escapeHtml(item.user_role_label || "-")} · ${escapeHtml(status)}</span>
            </div>
            <div class="proactive-meta">${meta.map((value) => `<span>${escapeHtml(value)}</span>`).join("")}</div>
            ${proactiveAfterglowHtml(item)}
          </section>
        `;
      }).join("")}
    </div>
  `;
}

export function proactiveRuntimeHtml(runtime) {
  const healthy = Boolean(runtime.healthy);
  const age = Number(runtime.tick_age_seconds || -1);
  const ageText = age >= 0 ? `${Math.round(age)} 秒前` : "尚无记录";
  const items = [
    `最近开始：${runtime.last_tick_started || "-"}`,
    `最近结束：${runtime.last_tick_finished || "-"}`,
    `心跳年龄：${ageText}`,
    `检查间隔：${runtime.expected_interval_seconds || "-"} 秒`,
    runtime.last_tick_error ? `最近异常：${runtime.last_tick_error}` : "",
  ].filter(Boolean);
  return `
    <section class="proactive-runtime ${healthy ? "ok" : "warn"}">
      <div class="proactive-task-head">
        <div>
          <b>主动循环心跳</b>
          <span>${healthy ? "循环最近有运行记录" : "没有近期心跳或等待下一轮记录"}</span>
        </div>
        <span class="badge">${healthy ? "正常" : "待确认"}</span>
      </div>
      <div class="proactive-meta">${items.map((value) => `<span>${escapeHtml(value)}</span>`).join("")}</div>
    </section>
  `;
}

export function proactiveAuditHtml(items) {
  const visibleItems = (Array.isArray(items) ? items : []);
  if (!visibleItems.length) {
    return `<div class="proactive-task-empty"><b>暂无执行审计</b><span>主动真正进入发送链路后，会在这里留下开始、成功、失败、延后或取消记录。</span></div>`;
  }
  return visibleItems.map((item) => {
    const status = proactiveAuditStatusLabel(item.status);
    const title = item.topic || item.reason_label || item.reason || item.note || "主动执行记录";
    const sourceLabel = item.source_label || proactiveCandidateSourceLabel(item.source);
    const semanticMeta = proactiveSemanticMeta(item);
    const meta = [
      `用户：${item.user_label || item.user_id || "-"}`,
      `来源：${sourceLabel}`,
      `动作：${item.action || "message"}`,
      item.reason_label ? `原因：${item.reason_label}` : (item.reason ? `原因：${item.reason}` : ""),
      item.reason_detail ? `为什么：${item.reason_detail}` : "",
      item.note ? `结果：${item.note}` : "",
      item.original_text_preview ? `原候选：${item.original_text_preview}` : "",
      item.final_text_preview ? `最终发送：${item.final_text_preview}` : "",
      item.text_preview && !item.final_text_preview ? `消息：${item.text_preview}` : "",
      item.has_image ? "包含图片" : "",
      item.extra_count ? `组件 ${item.extra_count}` : "",
      Number(item.duplicate_count || 0) > 1 ? `重复 ${item.duplicate_count} 次` : "",
      item.scheduled_ts ? `计划：${item.scheduled || "-"}` : "",
      item.created_ts ? `开始：${item.created || "-"}` : "",
      item.updated_ts ? `更新：${item.updated || "-"}` : "",
    ].filter(Boolean);
    return `
      <details class="proactive-task audit aw-proactive-record ${escapeHtml(item.status || "unknown")}">
        <summary class="proactive-task-head">
          <div>
            <b>${escapeHtml(title)}</b>
            <span>${escapeHtml(item.user_label || item.user_id || "-")} · ${escapeHtml(item.user_role_label || "-")} · ${escapeHtml(sourceLabel)} · ${escapeHtml(item.updated || item.created || "未记录时间")}</span>
          </div>
          <span class="badge">${escapeHtml(status)}</span>
        </summary>
        <div class="aw-proactive-detail"><p>${escapeHtml(item.motive || item.note || "暂无动机记录")}</p>
        <div class="proactive-meta">
          ${semanticMeta.map((value) => `<span class="proactive-semantic-chip">${escapeHtml(value)}</span>`).join("")}
          ${meta.map((value) => `<span>${escapeHtml(value)}</span>`).join("")}
        </div>
        </div>
      </details>
    `;
  }).join("");
}

export function proactiveTaskStatusLabel(status) {
  return {
    scheduled: "已登记",
    due: "已到点",
    overdue: "超时未发",
    handed_off: "已交官方",
    failed: "执行失败",
    cancelled: "已取消",
    cancel_failed: "取消失败",
    cancel_skipped: "无可取消",
  }[status] || status || "未知";
}

export function proactiveAuditStatusLabel(status) {
  return {
    running: "执行中",
    deferred: "已延后",
    cancelled: "已取消",
    dropped: "已放弃",
    failed: "失败",
    sent: "已发送",
    obsolete: "旧记录",
  }[status] || status || "未知";
}

export function proactiveTaskSourceLabel(source, hasTimerEvent = false) {
  if (source === "timer" || hasTimerEvent) return "官方定时计划";
  if (source === "candidate") return "主动候选";
  if (source === "followup" || source === "pending_followup") return "补一句";
  if (source === "state") return "身体小需求";
  if (source === "daily_greeting") return "日常招呼";
  if (source === "external") return "外部主动能力";
  return source || "插件主动";
}

export function proactiveCandidateSourceLabel(source) {
  return {
    random: "轻微想念",
    daily_greeting: "日常招呼",
    pending_followup: "补一句",
    state: "身体小需求",
    event: "生活事件",
    story: "日常剧情",
    habit: "习惯关心",
    bilibili: "B站分享",
    bookshelf_reading: "私密阅读",
    creative_writing: "创作灵感",
    group_share: "群聊见闻",
    web_exploration: "主动搜索",
    news: "新闻阅读",
    environment_change: "环境突变",
    meal_care: "饭点关心",
    group_ignore_complaint: "群内冒泡关心",
    jm_cosmos: "私密阅读",
    personal_goal: "个人目标",
    candidate: "主动候选",
    followup: "补一句",
    external: "外部主动能力",
    timer: "官方定时计划",
    proactive: "插件主动",
    unknown: "未记录来源",
  }[source] || source || "插件主动";
}

export function validProactiveCandidateFilter(data, value) {
  const userIds = new Set((data.users || []).map((item) => String(item.user_id || "")));
  const normalized = String(value || "all");
  return normalized === "all" || userIds.has(normalized) ? normalized : "all";
}

export function countProactiveCandidateItems(items, key) {
  return (items || []).reduce((acc, item) => {
    const name = String(item?.[key] || "unknown");
    acc[name] = (acc[name] || 0) + Number(item?.repeat_count || 1);
    return acc;
  }, {});
}

export function proactiveCandidateIsPending(item) {
  const status = String(item?.status || "").trim().toLowerCase();
  return ["accepted", "deferred", "queued", "pending", "unknown", ""].includes(status);
}

export function sumProactivePendingCandidateItems(items) {
  return (items || []).reduce((sum, item) => {
    if (!proactiveCandidateIsPending(item)) return sum;
    return sum + Number(item?.repeat_count || 1);
  }, 0);
}

export function sumObjectValues(data) {
  return Object.values(data || {}).reduce((sum, value) => sum + Number(value || 0), 0);
}

export function proactiveSummaryCard(label, value, note) {
  return `
    <section class="proactive-summary-card">
      <span>${escapeHtml(label)}</span>
      <b>${escapeHtml(value)}</b>
      <small>${escapeHtml(note)}</small>
    </section>
  `;
}

export function proactiveStatusLabel(status) {
  return {
    accepted: "已计划",
    sent: "已发送",
    blocked: "已拦截",
    deferred: "已延后",
    dropped: "已放弃",
    cancelled: "已取消",
    failed: "失败",
    running: "执行中",
    scheduled: "已登记",
    due: "已到点",
    overdue: "超时未发",
    obsolete: "旧记录",
    expired: "已过期",
  }[status] || status || "未知";
}

export function proactiveActionLabel(action) {
  return {
    message: "文字消息",
    photo_text: "拍照/生图",
    poke: "戳一戳",
    voice: "语音",
    screen_peek: "识屏",
    quote: "引用回复",
  }[action] || action || "文字消息";
}

export function renderCreativeProjectCard(item) {
  const current = Number(item.current_chars || 0);
  const target = Number(item.target_chars || 0);
  const pct = target > 0 ? Math.min(100, Math.round((current / target) * 100)) : 0;
  const statusText = {
    drafting: "慢慢写着",
    finished: "已写完",
    paused: "暂时搁置",
  }[item.status] || item.status || "未知";
  const milestones = Array.isArray(item.milestones) && item.milestones.length
    ? item.milestones.map((name) => `<span>${escapeHtml(creativeMilestoneLabel(name))}</span>`).join("")
    : `<span class="muted">还没提起过</span>`;
  return `
    <article class="creative-card">
      <div class="creative-card-head">
        <div>
          <h3>${escapeHtml(item.title || "未定标题")}</h3>
          <p>${escapeHtml(item.premise || "还没整理出一句设定。")}</p>
        </div>
        <span class="badge">${escapeHtml(statusText)}</span>
      </div>
      <div class="creative-progress">
        <div class="meter"><i style="width:${pct}%"></i></div>
        <b>${escapeHtml(current)} / ${escapeHtml(target || "-")} 字</b>
      </div>
      <div class="creative-meta">
        <span>类型：${escapeHtml(item.work_type || "短篇小说")}</span>
        <span>气质：${escapeHtml(item.tone || "-")}</span>
        <span>视角：${escapeHtml(item.point_of_view || "第三人称有限视角")}</span>
        <span>片段：${escapeHtml(item.chunk_count || 0)}</span>
        <span>创建：${escapeHtml(item.created_at || "-")}</span>
        <span>上次推进：${escapeHtml(item.last_advanced || "-")}</span>
        <span>下次推进：${escapeHtml(item.next_advance || "-")}</span>
      </div>
      ${item.source ? `<p class="creative-source">灵感来源：${escapeHtml(item.source)}</p>` : ""}
      ${item.latest_snippet ? `<blockquote>${escapeHtml(item.latest_snippet)}</blockquote>` : ""}
      <div class="creative-milestones">
        <b>已自然提起节点</b>
        <div>${milestones}</div>
      </div>
    </article>
  `;
}

export function creativeMilestoneLabel(name) {
  return {
    opening: "开头",
    midpoint: "过半",
    finished: "完稿",
    impression_question: "询问观感",
  }[name] || name || "节点";
}

export function renderDailyTimeline() {
  const timeline = state.overview?.daily_timeline || {};
  const segments = timeline.segments || [];
  if (!segments.length) {
    $("#dailyTimeline").innerHTML = `<div class="empty small">暂无细化时间段</div>`;
    return;
  }
  const planQuality = timeline.plan_quality || {};
  const qualityIntro = Number.isFinite(Number(planQuality.score))
    ? `<div class="timeline-quality-summary"><b>全天质量 ${escapeHtml(planQuality.score)}</b><span>${escapeHtml((planQuality.issues || []).slice(0, 2).join(" · ") || "时间与内容检查正常")}</span></div>`
    : "";
  $("#dailyTimeline").innerHTML = qualityIntro + segments.map((segment) => {
    const vars = (segment.state_variables || []).slice(0, 4);
    const events = (segment.today_events || []).slice(0, 5);
    const presence = segment.presence_status || {};
    const statusText = detailSegmentStatusLabel(segment);
    const presenceText = presenceLabel(presence);
    const lifecycleText = scheduleLifecycleLabel(segment.lifecycle);
    const metaText = [...new Set([lifecycleText, statusText, presenceText].filter(Boolean))].join(" · ");
    const errorText = String(segment.regeneration_error || segment.error || "").trim();
    const quality = segment.quality || {};
    const basis = (segment.summary_basis?.length ? segment.summary_basis : segment.basis || []).map(scheduleBasisLabel);
    const confidence = Number(segment.summary_confidence ?? segment.confidence);
    const evidenceText = [
      basis.length ? `依据：${basis.join("、")}` : "",
      Number.isFinite(confidence) ? `置信度 ${Math.round(confidence * 100)}%` : "",
      Number.isFinite(Number(quality.score)) ? `质量 ${quality.score}` : "",
    ].filter(Boolean).join(" · ");
    return `
      <section class="timeline-item">
        <div class="timeline-time">${escapeHtml(segment.window || segment.key)}</div>
        <div class="timeline-body">
          <div class="timeline-head">
            <b>${escapeHtml(segment.summary || "这一段还没有摘要")}</b>
            <div><span>${escapeHtml(metaText)}</span><button type="button" class="timeline-regenerate" data-daily-detail-regenerate="${escapeHtml(segment.key || "")}" title="重新细化这一段" aria-label="重新细化这一段">↻</button>${segment.lifecycle !== "cancelled" ? `<button type="button" class="timeline-regenerate danger" data-daily-detail-cancel="${escapeHtml(segment.key || "")}" title="取消这一段" aria-label="取消这一段">×</button>` : ""}</div>
          </div>
          ${errorText ? `<p class="timeline-error">失败原因：${escapeHtml(errorText)}${segment.retry_after ? `，${escapeHtml(segment.retry_after)} 后重试` : ""}</p>` : ""}
          ${evidenceText ? `<p class="timeline-evidence">${escapeHtml(evidenceText)}</p>` : ""}
          <div class="state-pills">
            ${vars.length ? vars.map((item) => `
              <span title="${escapeHtml(item.note || "")}">
                <b>${escapeHtml(item.name || "-")}</b>${escapeHtml(item.value || "-")}
              </span>
            `).join("") : `<span>暂无状态变量</span>`}
          </div>
          <ul>
            ${events.length ? events.map((item) => `<li><span>${escapeHtml(scheduleLifecycleLabel(item.lifecycle))}</span>${escapeHtml(item.window ? `${item.window} · ${item.text}` : item.text)}</li>`).join("") : `<li>暂无细化事件</li>`}
          </ul>
        </div>
      </section>
    `;
  }).join("");
  document.querySelectorAll("[data-daily-detail-regenerate]").forEach((button) => {
    button.addEventListener("click", () => regenerateDailyDetailSegment(button));
  });
  document.querySelectorAll("[data-daily-detail-cancel]").forEach((button) => {
    button.addEventListener("click", () => cancelDailyDetailSegment(button));
  });
}

export function scheduleLifecycleLabel(value) {
  return {
    planned: "计划中",
    active: "进行中",
    completed: "已完成",
    changed: "已变更",
    cancelled: "已取消",
  }[String(value || "").toLowerCase()] || "";
}

export function scheduleBasisLabel(value) {
  return {
    calendar: "日期",
    persona: "角色设定",
    adjustment: "用户介入",
    state: "当前状态",
    weather: "天气",
    continuity: "连续记忆",
    inspiration: "软灵感",
    coarse_plan: "粗日程",
  }[String(value || "").toLowerCase()] || String(value || "");
}

export async function regenerateDailyDetailSegment(button) {
  const key = String(button?.dataset.dailyDetailRegenerate || "").trim();
  if (!key || button.disabled) return;
  button.disabled = true;
  button.textContent = "…";
  try {
    const result = await fetchJson("/daily/detail/regenerate", {
      method: "POST",
      body: JSON.stringify({ key }),
    });
    state.overview = state.overview || {};
    state.overview.daily_timeline = result.daily_timeline || state.overview.daily_timeline;
    renderDailyTimeline();
    showToast("这一段已重新细化", "success");
  } catch (error) {
    button.disabled = false;
    button.textContent = "↻";
    showToast(error.message || "重新细化失败", "error");
  }
}

export async function cancelDailyDetailSegment(button) {
  const key = String(button?.dataset.dailyDetailCancel || "").trim();
  if (!key || button.disabled || !window.confirm("取消这一段日程？已有细化会保留，但不会再作为待执行事件。")) return;
  button.disabled = true;
  try {
    const result = await fetchJson("/daily/detail/regenerate", {
      method: "POST",
      body: JSON.stringify({ key, action: "cancel" }),
    });
    state.overview = state.overview || {};
    state.overview.daily_timeline = result.daily_timeline || state.overview.daily_timeline;
    renderDailyTimeline();
    showToast("这一段已取消", "success");
  } catch (error) {
    button.disabled = false;
    showToast(error.message || "取消失败", "error");
  }
}

export function detailSegmentStatusLabel(segment) {
  const raw = segment && typeof segment === "object" ? segment : {};
  const value = String(raw.status || "").trim();
  const startedAt = String(raw.started_at || "").trim();
  const label = {
    done: "已细化",
    generating: "生成中",
    failed: "生成失败",
    cancelled: "已取消",
  }[value] || (value ? value : "未生成");
  if (value === "generating" && startedAt) return `${label}（${startedAt} 开始）`;
  return label;
}

export function renderInteractionImpact() {
  const timeline = state.overview?.daily_timeline || {};
  const segmentUpdates = [];
  (timeline.segments || []).forEach((segment) => {
    (segment.interaction_updates || []).forEach((item) => {
      segmentUpdates.push({ ...item, window: segment.window });
    });
  });
  const adjustments = (timeline.adjustments || []).map((item) => ({
    at: item.date || "",
    source: item.source,
    reaction: item.reaction || item.note,
    state_updates: item.state_updates || [],
    window: "全局影响",
  }));
  const items = [...segmentUpdates, ...adjustments].filter((item) => item.reaction || item.state_updates?.length);
  if (!items.length) {
    $("#interactionImpact").innerHTML = `<div class="empty small">暂无用户介入影响</div>`;
    return;
  }
  $("#interactionImpact").innerHTML = items.slice(-12).reverse().map((item) => `
    <section class="impact-item">
      <div>
        <b>${escapeHtml(item.source || "用户影响")}</b>
        <span>${escapeHtml([item.window, item.at].filter(Boolean).join(" · "))}</span>
      </div>
      <p>${escapeHtml(item.reaction || "")}</p>
      <div class="state-pills">
        ${(item.state_updates || []).map((update) => `<span>${escapeHtml(update)}</span>`).join("")}
      </div>
    </section>
  `).join("");
}

export function presenceLabel(presence) {
  const mode = String(presence?.mode || "unchanged");
  const text = presence?.custom_text || presence?.wording || "";
  const duration = Number.parseInt(presence?.duration_minutes, 10);
  const durationText = Number.isFinite(duration) && duration > 0 ? `（约 ${duration} 分钟）` : "";
  if (mode === "custom" && text) return `自定义状态：${text}${durationText}`;
  if (mode === "sleep") return "状态：休息中";
  if (mode === "busy") return "状态：忙碌";
  if (mode === "online") return "状态：在线";
  return "状态：不变";
}

export function renderMemoryComposition() {
  const data = {
    "原始记忆": state.users.reduce((sum, user) => sum + Number(user.memory_items || 0), 0),
    "私聊片段": state.users.reduce((sum, user) => sum + Number(user.dialogue_episode_count || 0), 0),
    "未完话头": state.users.reduce((sum, user) => sum + Number(user.open_loop_count || 0), 0),
    "群聊片段": state.groups.reduce((sum, group) => sum + Number(group.episode_count || 0), 0),
    "群聊话题": state.groups.reduce((sum, group) => sum + Number(group.topic_count || 0), 0),
  };
  $("#memoryComposition").innerHTML = donutChart(data);
}

export function renderSlangCloud() {
  const counts = new Map();
  state.groups.forEach((group) => {
    (group.slang_terms || []).forEach((item) => {
      const term = slangTermText(item);
      if (!term) return;
      const observedCount = typeof item === "object" && item
        ? Math.max(0, Number(item.count || 0))
        : 0;
      const promoted = Boolean(typeof item === "object" && item && item.promoted === true);
      if (observedCount < 2 && !promoted) return;
      counts.set(term, (counts.get(term) || 0) + Math.max(1, observedCount));
    });
  });
  const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 36);
  if (!entries.length) {
    $("#slangCloud").innerHTML = `<div class="empty small">暂无群聊黑话</div>`;
    return;
  }
  const max = Math.max(1, ...entries.map(([, count]) => count));
  $("#slangCloud").innerHTML = entries.map(([term, count]) => {
    const size = 12 + Math.round((count / max) * 16);
    return `<span style="font-size:${size}px">${escapeHtml(term)}</span>`;
  }).join("");
}

export function slangTermText(item) {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return "";
  return String(
    item.term
      || item.word
      || item.text
      || item.name
      || item.key
      || item.phrase
      || item.slang
      || ""
  ).trim();
}

export function formatSlangTerms(items) {
  const terms = (Array.isArray(items) ? items : [])
    .map(slangTermText)
    .filter(Boolean);
  return terms.length ? terms.join("、") : "暂无";
}

export function renderConfig() {
  const overview = state.overview || {};
  const group = overview.group || {};
  $("#groupAccessMode").value = group.access_mode || "whitelist";
  $("#groupWhitelist").value = (group.whitelist || []).join("\n");
  $("#groupBlacklist").value = (group.blacklist || []).join("\n");
  renderStorageConfig();
  renderAppearanceSettings();
  renderAccessManager(group);
  renderFeatureSwitches();
  renderConfigBackups();
  renderConfigImportChecks();
  renderConfigMigrationPreview();
}

export function renderStorageConfig(options = {}) {
  const overview = state.overview || {};
  const settings = overview.settings || {};
  const plugin = overview.plugin || {};
  const preserveDraft = Boolean(options.preserveDraft);
  const backendSelect = $("#storageBackendSelect");
  const sqliteWrap = $("#storageSqlitePathWrap");
  const sqliteInput = $("#storageSqlitePathInput");
  const safetyToggle = $("#storageSafetyCleanupToggle");
  const summary = $("#storageConfigSummary");
  const selectedBackend = preserveDraft ? (backendSelect?.value || "") : "";
  const backend = String(selectedBackend || settings.storage_backend || plugin.storage_backend || "json").trim().toLowerCase() || "json";
  const sqlitePath = preserveDraft && sqliteInput
    ? String(sqliteInput.value || "").trim()
    : String(settings.storage_sqlite_path || plugin.storage_sqlite_path || "").trim();
  const safetyEnabled = preserveDraft && safetyToggle
    ? safetyToggle.checked
    : toBool(settings.enable_store_control_tag_sanitization ?? plugin.enable_store_control_tag_sanitization ?? true);
  if (backendSelect) backendSelect.value = backend;
  if (sqliteInput) sqliteInput.value = sqlitePath;
  if (safetyToggle) safetyToggle.checked = safetyEnabled;
  if (sqliteWrap) sqliteWrap.hidden = backend !== "sqlite";
  if (summary) {
    summary.innerHTML = `
      <span>当前后端：<b>${escapeHtml(backend)}</b></span>
      <span>当前路径：<b>${escapeHtml(plugin.storage_sqlite_path || sqlitePath || "companions.json / 默认 companions.db")}</b></span>
      <span>当前数据文件：<b>${escapeHtml(plugin.data_file || "-")}</b></span>
      <span>数据安全清理：<b>${safetyEnabled ? "开启" : "关闭"}</b></span>
    `;
  }
}

export function renderPrivateStrategyOverview(selector, info) {
  const total = Number(info.target_count ?? info.user_count ?? info.private_user_count ?? 0);
  const enabled = Number(info.enabled_count ?? info.enabled_user_count ?? total);
  const adminIds = Array.isArray(info.admin_ids) ? info.admin_ids : [];
  const targetIds = Array.isArray(info.target_user_ids) ? info.target_user_ids : [];
  const relationshipOwnerIds = Array.isArray(info.relationship_owner_ids) ? info.relationship_owner_ids : [];
  const manageIds = [...new Set([...adminIds, ...targetIds, ...relationshipOwnerIds])];
  const manageText = manageIds.length ? manageIds.join("、") : "未配置";
  const rows = [
    ["对象", total ? `${enabled}/${total} 启用` : `${enabled || 0} 个启用`],
    ["主动上限", formatProactiveDailyLabel(state.overview?.proactive_intensity?.effective?.max_daily_messages ?? info.max_daily_messages, state.overview?.proactive_intensity?.effective?.max_daily_messages_unlimited, state.overview?.proactive_intensity?.effective?.max_daily_messages_text)],
    ["触达条件", `空闲 ${Number(info.idle_minutes || 0)} 分钟后，最小间隔 ${Number(info.min_interval_minutes || 0)} 分钟`],
    ["管理权限", manageText],
    ["管理命令", toBool(info.require_opt_in ?? info.require_confirm ?? info.require_private_confirm) ? "仅私聊" : "私聊+群聊"],
  ];
  $(selector).innerHTML = compactOverviewList(rows, { columns: 1 });
}

export function renderGroupStrategyOverview(selector, group) {
  const mode = String(group.access_mode || "whitelist");
  const whitelistCount = Array.isArray(group.whitelist) ? group.whitelist.length : 0;
  const blacklistCount = Array.isArray(group.blacklist) ? group.blacklist.length : 0;
  const accessText = mode === "blacklist" ? `黑名单（${blacklistCount} 个群）` : `白名单（${whitelistCount} 个群）`;
  const total = Number(group.group_count || 0);
  const enabled = Number(group.enabled_group_count || 0);
  const rows = [
    ["群聊观察", statusText(group.enabled)],
    ["目标群", total ? `${enabled}/${total} 启用` : `${enabled || 0} 个启用`],
    ["访问范围", accessText],
    ["群主动插话", statusText(group.interjection_enabled)],
    ["复读处理", statusText(group.repeat_follow_enabled)],
  ];
  $(selector).innerHTML = compactOverviewList(rows, { columns: 1 });
}

export function renderLongTermStrategyOverview(selector, { creative = {}, bili = {}, qzone = {}, privateReading = {} } = {}) {
  const cards = [
    {
      title: "B 站",
      tone: bili.enabled ? "ok" : "off",
      meta: [statusText(bili.enabled), bili.boredom_watch_enabled ? "无聊刷视频开启" : "无聊刷视频关闭"],
      text: bili.latest_video?.title || "暂无最新视频",
    },
    {
      title: "QQ 空间",
      tone: qzone.enabled && qzone.available ? (qzone.last_status && qzone.last_status.startsWith("paused:") ? "warn" : "ok") : qzone.enabled ? "warn" : "off",
      meta: [qzone.enabled ? (qzone.available ? "可用" : "待服务") : "关闭", qzone.life_publish_enabled ? "生活说说开启" : "生活说说关闭", qzone.comment_inbox_enabled ? "评论收件箱开启" : ""].filter(Boolean),
      text: qzone.last_status && qzone.last_status.startsWith("paused:") ? `自动说说已暂停：${qzone.auth_failure_reason || qzone.last_status}` : (qzone.last_text || "暂无最近说说"),
    },
    {
      title: "私下创作",
      tone: creative.enabled ? "ok" : "off",
      meta: [statusText(creative.enabled), `项目 ${Number(creative.active_projects || 0)} 个进行中 / ${Number(creative.project_count || 0)} 个总计`],
      text: creative.latest_title || "暂无最新创作",
    },
  ];
  if (privateReading.available) {
    cards.push({
      title: "夹层阅读",
      tone: privateReading.enabled ? "ok" : "off",
      meta: [
        privateReading.enabled ? "可用" : "关闭",
        privateReading.boredom_read_enabled ? "私下阅读开启" : "私下阅读关闭",
        privateReading.ask_recommendation_enabled ? "征求推荐开启" : "征求推荐关闭",
      ],
      text: privateReading.last_album?.title || "暂无最近阅读",
    });
  }
  $(selector).innerHTML = `<div class="longterm-overview-grid">${cards.map(longTermOverviewCard).join("")}</div>`;
}

export function compactOverviewList(rows, { columns = 1 } = {}) {
  const className = columns > 1 ? "compact-overview-list two" : "compact-overview-list";
  return `
    <div class="${className}">
      ${rows.map(([label, value]) => `
        <div class="compact-overview-row">
          <span>${escapeHtml(label)}</span>
          ${overviewValueHtml(value)}
        </div>
      `).join("")}
    </div>
  `;
}

export function overviewValueHtml(value) {
  const text = String(value ?? "").trim() || "未设置";
  if (["开启", "可用", "需要"].includes(text)) {
    return `<b class="overview-pill ok">${escapeHtml(text)}</b>`;
  }
  if (["关闭", "不需要", "待服务", "未设置"].includes(text)) {
    return `<b class="overview-pill ${text === "待服务" ? "warn" : "off"}">${escapeHtml(text)}</b>`;
  }
  return `<b>${escapeHtml(text)}</b>`;
}

export function longTermOverviewCard(item) {
  const meta = Array.isArray(item.meta) ? item.meta.filter(Boolean) : [];
  return `
    <article class="longterm-overview-card ${escapeHtml(item.tone || "info")}">
      <header>
        <b>${escapeHtml(item.title || "长线主动")}</b>
        ${meta[0] ? overviewValueHtml(meta[0]) : ""}
      </header>
      <p>${escapeHtml(item.text || "暂无记录")}</p>
      ${meta.length > 1 ? `<div>${meta.slice(1).map((value) => `<span>${escapeHtml(value)}</span>`).join("")}</div>` : ""}
    </article>
  `;
}

export function statusText(value) {
  return toBool(value) ? "开启" : "关闭";
}

export function renderModuleSettings() {
  const settings = state.overview?.settings || {};
  const formValues = { ...settings, ...(state.featureDraft || {}) };
  renderModuleWorkbench(settings);
  renderCurrentPersonaStatus(settings);
  const newsRaw = $("#newsSourcesRaw");
  if (newsRaw) newsRaw.value = displaySettingValue("news_sources", settings.news_sources);
  fillForm("#roleplayProfileForm", formValues);
  renderRoleplaySavedReading(settings);
  fillForm("#privateAliasForm", formValues);
  fillForm("#quickModuleForm", formValues);
  fillForm("#runtimeSettingsForm", formValues);
  const targetBox = document.querySelector('#quickModuleForm [name="target_user_ids"]');
  if (targetBox) targetBox.value = Array.isArray(settings.target_user_ids) ? settings.target_user_ids.join("\n") : "";
  renderQuickStartStatus(settings);
  document.querySelectorAll(".module-form").forEach((form) => markModuleFormClean(form));
  renderExternalAbilities();
  renderPresetCards();
}

export function weatherConfigStatusText(settings = state.overview?.settings || {}) {
  const overview = state.overview || {};
  const cache = overview.cache?.weather || {};
  const enabled = toBool(settings.enable_weather_context);
  const apiKey = String(settings.weather_api_key || "").trim();
  const city = String(settings.weather_city || "").trim();
  const lat = Number(settings.weather_lat || 0);
  const lon = Number(settings.weather_lon || 0);
  const hasCoordinates = Number.isFinite(lat) && Number.isFinite(lon) && lat !== 0 && lon !== 0;
  const screenAvailable = Boolean(overview.screen_companion?.available);
  const sourceLabels = {
    private_companion: "本插件 OpenWeatherMap",
    screen_companion: "screen_companion 回退",
    disabled: "已关闭",
    none: "暂无可用来源",
  };
  const source = sourceLabels[String(cache.source || "")] || "";
  let status = "";
  if (!enabled) {
    status = "天气上下文已关闭，不会参与日程、日记或主动话题。";
  } else if (apiKey && (city || hasCoordinates)) {
    status = `独立查询已就绪：${city ? `城市 ${city}` : "经纬度定位"}。`;
  } else if (screenAvailable) {
    status = "未完成独立天气配置，当前会尝试复用 screen_companion 的天气能力。";
  } else if (apiKey) {
    status = "已填写 API Key，但还缺少城市或一组经纬度。";
  } else {
    status = "尚未配置独立天气；填写 Key 和城市即可启用，或安装 screen_companion 作为回退。";
  }
  const runtime = source
    ? ` 最近结果：${source}${cache.summary ? `，${cache.summary}` : ""}${cache.age ? `（${cache.age}）` : ""}。`
    : "";
  return status + runtime;
}

export function environmentWeatherStatusHtml() {
  return `
    <section class="feature-param-status" aria-label="天气来源状态">
      <b>天气来源状态</b>
      <span>${escapeHtml(weatherConfigStatusText())}</span>
    </section>
  `;
}

export function renderQuickStartStatus(settings) {
  const box = $("#quickStartStatus");
  if (!box) return;
  const overview = state.overview || {};
  const providers = overview.providers || {};
  const targetUsers = Array.isArray(settings.target_user_ids) ? settings.target_user_ids.filter(Boolean) : [];
  const platform = String(settings.target_platform || "").trim();
  const quietHours = String(settings.quiet_hours || "").trim();
  const aliases = String(settings.private_user_delivery_aliases || "").trim();
  const fastProvider = String(providers.FAST_RESPONSE_PROVIDER_ID || "").trim();
  const complexProvider = String(providers.COMPLEX_REASONING_PROVIDER_ID || "").trim();
  const proactiveMax = overview.proactive_intensity?.effective?.max_daily_messages ?? settings.max_daily_messages ?? 0;
  const chips = [
    {
      label: "目标用户",
      value: targetUsers.length ? `${targetUsers.length} 人` : "未配置",
      ok: Boolean(targetUsers.length),
      tab: null,
    },
    {
      label: "运行平台",
      value: platform || "未配置",
      ok: Boolean(platform),
      tab: null,
    },
    {
      label: "核心模型",
      value: fastProvider && complexProvider ? "快速+复杂" : "未配置",
      ok: Boolean(fastProvider && complexProvider),
      tab: "models",
    },
    {
      label: "私聊主动",
      value: Number(proactiveMax) > 0 ? `${proactiveMax} 条/天` : "未开启",
      ok: Number(proactiveMax) > 0,
      tab: "private",
    },
    {
      label: "免打扰",
      value: quietHours || "未设置",
      ok: Boolean(quietHours),
      tab: null,
    },
    {
      label: "转发映射",
      value: aliases ? "已配置" : "未配置",
      ok: Boolean(aliases),
      tab: null,
    },
  ];
  const doneCount = chips.filter((c) => c.ok).length;
  const pct = Math.round((doneCount / chips.length) * 100);
  box.innerHTML = `
    <div class="quick-start-progress">
      <div class="quick-start-progress-track"><div class="quick-start-progress-fill" style="width:${pct}%"></div></div>
      <span class="quick-start-progress-label">${doneCount}/${chips.length} 项就绪 · ${pct}%</span>
    </div>
    <div class="quick-start-chips">
      ${chips.map((c) => `
        <span class="quick-start-chip ${c.ok ? "ok" : "warn"}" ${c.tab ? `data-jump-tab="${escapeHtml(c.tab)}"` : ""}>
          <i>${c.ok ? "✓" : "○"}</i>
          <small>${escapeHtml(c.label)}</small>
          <b>${escapeHtml(c.value)}</b>
        </span>
      `).join("")}
    </div>
  `;
}

export function renderModuleWorkbench(settings) {
  const box = $("#moduleWorkbench");
  if (!box) return;
  const overview = state.overview || {};
  const features = overview.features || {};
  const group = overview.group || {};
  const worldbook = overview.worldbook || {};
  const external = overview.external_abilities || {};
  const knowledge = overview.knowledge || {};
  const creative = overview.creative || {};
  const bookshelf = overview.bookshelf || {};
  const qzone = overview.qzone || {};
  const privateReading = overview.private_reading || {};
  const intensity = overview.proactive_intensity || {};
  const intensityEnabled = Boolean(intensity.enabled);
  const intensityLabel = intensityEnabled ? (intensity.label || intensity.preset || "预设开启") : "手动参数";
  const proactiveMaxDaily = intensityEnabled ? (intensity.effective?.max_daily_messages ?? settings.max_daily_messages) : settings.max_daily_messages;
  const proactiveMaxDailyText = intensityEnabled
    ? (intensity.effective?.max_daily_messages_text || formatProactiveLimit(proactiveMaxDaily, intensity.effective?.max_daily_messages_unlimited))
    : formatProactiveLimit(proactiveMaxDaily);
  const proactiveIdle = intensityEnabled ? (intensity.effective?.idle_minutes ?? settings.idle_minutes) : settings.idle_minutes;
  const proactiveMinInterval = intensityEnabled ? (intensity.effective?.min_interval_minutes ?? settings.min_interval_minutes) : settings.min_interval_minutes;
  const moduleCards = [
    {
      title: "主动触达",
      kicker: "主动节奏",
      status: Number(proactiveMaxDaily || 0) > 0 ? "运行中" : "已收起",
      tone: intensityEnabled ? "warn" : (Number(proactiveMaxDaily || 0) > 0 ? "ok" : "off"),
      body: `私聊 ${formatProactiveDailyQuota(proactiveMaxDaily, intensity.effective?.max_daily_messages_unlimited, proactiveMaxDailyText)}，空闲 ${proactiveIdle ?? 0} 分钟后进入候选；群聊唤醒和插话按群聊开关参与。`,
      meta: [
        `强度：${intensityLabel}`,
        `最小间隔 ${proactiveMinInterval ?? 0} 分钟`,
        toBool(settings.enable_unanswered_screen_peek_followup) ? "未回应后可轻窥屏" : "未回应不窥屏",
      ],
      actions: [
        ["proactive", "看主动候选"],
        ["private", "管理私聊对象"],
      ],
    },
    {
      title: "群聊观察",
      kicker: "群内理解",
      status: features.enable_group_companion ? "观察中" : "未启用",
      tone: features.enable_group_companion ? "ok" : "off",
      body: `${group.enabled_group_count || 0}/${group.group_count || 0} 个群启用，关系、黑话和片段会作为群聊背景管理。`,
      meta: [
        toBool(settings.enable_group_high_intensity_mode) ? "高强度收口开启" : "高强度收口关闭",
        toBool(settings.enable_forward_message_adaptation) ? "合并消息阅读开启" : "合并消息阅读关闭",
      ],
      actions: [
        ["group", "看群聊"],
        ["memory", "看黑话/片段"],
      ],
    },
    {
      title: "关系网",
      kicker: "身份与称呼",
      status: settings.enable_worldbook_member_recognition ? "启用" : "关闭",
      tone: settings.enable_worldbook_member_recognition ? "ok" : "off",
      body: `${worldbook.enabled_member_count || 0}/${worldbook.member_count || 0} 个节点启用，用来稳定识别昵称、群名片和关系备注。`,
      meta: [
        toBool(settings.worldbook_self_registration) ? "允许群聊自登记" : "自登记关闭",
        `自登记拒绝词 ${worldbook.self_registration_block_word_count || 0} 条`,
        toBool(settings.enable_atrelay_tools) ? "跨群转述工具开启" : "跨群转述关闭",
      ],
      actions: [
        ["worldbook", "管理关系"],
        ["group", "查看群成员"],
      ],
    },
    {
      title: "记忆与能力",
      kicker: "长期沉淀",
      status: settings.enable_skill_growth_simulation ? "成长中" : "记录中",
      tone: settings.enable_skill_growth_simulation ? "ok" : "cost",
      body: `长期画像每 ${settings.memory_refresh_interval_minutes ?? 0} 分钟整理，片段阈值 ${settings.episode_memory_refresh_messages ?? 0} 条消息。`,
      meta: [
        toBool(settings.enable_skill_growth_schedule_influence) ? "技能影响日程" : "技能不影响日程",
        knowledge.selected_count ? `知识库 ${knowledge.selected_count} 项` : "未选知识库",
      ],
      actions: [
        ["memory", "整理记忆"],
        ["tokens", "看成本"],
      ],
    },
    {
      title: "图片与语音",
      kicker: "媒体能力",
      status: toBool(settings.enable_tts_enhancement) || toBool(settings.enable_private_image_self_recognition) ? "可用" : "低干预",
      tone: toBool(settings.enable_tts_enhancement) || toBool(settings.enable_private_image_self_recognition) ? "ok" : "off",
      body: "图片缓存、视觉摘要和 TTS 规则可以在这里快速查看；表情包识别不准时也能直接去缓存页整理。",
      meta: [
        toBool(settings.enable_tts_enhancement) ? `TTS ${settings.tts_voice_language || "默认"}` : "TTS 强化关闭",
        toBool(settings.enable_private_image_self_recognition) ? "图片转述增强开启" : "图片转述增强关闭",
      ],
      actions: [
        ["image-cache", "管理图片缓存"],
        ["models", "看视觉模型"],
      ],
    },
    {
      title: "长线主动",
      kicker: "外部生活线",
      status: settings.enable_creative_writing || settings.enable_bilibili_boredom_watch || settings.enable_qzone_life_publish ? "有长线" : "未展开",
      tone: settings.enable_creative_writing || settings.enable_bilibili_boredom_watch || settings.enable_qzone_life_publish ? "ok" : "off",
      body: [
        creative.latest_title ? `最近创作：${creative.latest_title}` : "",
        qzone.last_status && qzone.last_status.startsWith("paused:") ? `QQ 空间自动说说已暂停：${qzone.auth_failure_reason || ""}` : (qzone.last_text ? `最近说说：${qzone.last_text}` : ""),
        privateReading.last_album?.title ? `最近阅读：${privateReading.last_album.title}` : "",
      ].filter(Boolean).join("；") || "创作、空间、新闻、夹层阅读等外部生活线还没有明显产物。",
      meta: [
        settings.enable_creative_writing ? `创作项目 ${creative.active_projects || 0} 个` : "创作关闭",
        external.enabled_count ? `外部能力 ${external.enabled_count}/${external.total || 0}` : "外部能力未启用",
      ],
      actions: [
        ["bookshelf", "看书柜"],
        ["proactive", "看长线候选"],
      ],
    },
  ];
  box.innerHTML = `
    <section class="module-workbench-hero">
      <div>
        <span>功能与工具</span>
        <h3>常用模块，一眼看到现在的状态。</h3>
        <p>这里适合日常查看、整理和进入对应管理页；如果要细调开关、模型或阈值，可以再去配置和模型页。</p>
      </div>
      <div class="module-workbench-actions">
        <button type="button" data-jump-tab="config">配置页</button>
        <button type="button" data-jump-tab="models">模型页</button>
      </div>
    </section>
    <div class="module-workbench-grid">
      ${moduleCards.map(moduleWorkbenchCard).join("")}
    </div>
  `;
}
