/**
 * PulseForge — app.js
 * Full client-side logic: auth-aware, auto-refresh polling,
 * topic filters, article cards, bookmark system, saved panel, modal, toasts.
 */

/* ─────────────────────────────────────────────
   STATE
───────────────────────────────────────────── */
const state = {
    activeTab:      'news',          // 'news' | 'viral'
    topic:          'All Topics',
    sortBy:         'score',
    page:           1,
    totalPages:     1,
    totalArticles:  0,
    perPage:        12,
    loading:        false,
    lastRefreshCount: -1,
    savedIds:       new Set(),
    videoPlatform:  'all',
    videoLoading:   false,
    videos:         [],
};

/* ─────────────────────────────────────────────
   DOM REFS
───────────────────────────────────────────── */
const $  = id  => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);

// Views & Tabs
const tabNewsFeed      = $('tabNewsFeed');
const tabViralHits     = $('tabViralHits');
const newsFeedSection  = $('newsFeedSection');
const viralHitsSection = $('viralHitsSection');
const heroEyebrow      = $('heroEyebrow');
const heroTitle        = $('heroTitle');
const heroSubtitle     = $('heroSubtitle');

// News Feed Elements
const loader          = $('loader');
const newsGrid        = $('newsGrid');
const emptyState      = $('emptyState');
const paginationBar   = $('paginationBar');
const topicList       = $('topicList');
const prevBtn         = $('prevBtn');
const nextBtn         = $('nextBtn');
const pagePills       = $('pagePills');
const statTotal       = $('statTotal');
const statNew         = $('statNew');
const statPage        = $('statPage');
const refreshBtn      = $('refreshBtn');
const refreshPill     = $('refreshPill');
const refreshPillText = $('refreshPillText');
const pulseDot        = $('pulseDot');
const refreshBanner   = $('refreshBanner');
const refreshBannerTxt= $('refreshBannerText');
const navbar          = $('navbar');
const toastContainer  = $('toastContainer');

// Viral Hits Elements
const videoLoader     = $('videoLoader');
const videoGrid       = $('videoGrid');
const videoStatTotal  = $('videoStatTotal');
const platformList    = $('platformList');

// Saved panel
const savedPanelToggle = $('savedPanelToggle');
const savedPanel       = $('savedPanel');
const savedOverlay     = $('savedOverlay');
const savedPanelClose  = $('savedPanelClose');
const savedPanelBody   = $('savedPanelBody');
const savedBadgeCount  = $('savedBadgeCount');

// Sidebar stats
const ssTotalArticles  = $('ssTotalArticles');
const ssTopics         = $('ssTopics');
const ssLastRefresh    = $('ssLastRefresh');

// Modal
const modalOverlay     = $('modalOverlay');
const modalTitle       = $('modalTitle');
const modalTags        = $('modalTags');
const modalBody        = $('modalBody');
const modalOpenLink    = $('modalOpenLink');
const modalClose       = $('modalClose');
const modalMediaBanner = $('modalMediaBanner');
const modalImg         = $('modalImg');

// Empty refresh btn
const emptyRefreshBtn = $('emptyRefreshBtn');

/* ─────────────────────────────────────────────
   TOPIC → STYLE MAP
───────────────────────────────────────────── */
const TOPIC_MAP = {
    'AI News':       { badge:'badge-ai',   accent:'linear-gradient(135deg,#4fc3f7,#b57bee)', icon:'🤖' },
    'AI & LLMs':     { badge:'badge-ai',   accent:'linear-gradient(135deg,#4fc3f7,#b57bee)', icon:'🧠' },
    'Open Source':   { badge:'badge-hn',   accent:'linear-gradient(135deg,#fb923c,#fbbf24)', icon:'🔓' },
    'AI Tools':      { badge:'badge-ai',   accent:'linear-gradient(135deg,#4fc3f7,#34d399)', icon:'🛠️' },
    'Breakthroughs': { badge:'badge-sci',  accent:'linear-gradient(135deg,#fbbf24,#fb923c)', icon:'⚡' },
    'Pop Culture':   { badge:'badge-pop',  accent:'linear-gradient(135deg,#f472b6,#b57bee)', icon:'🎭' },
    'Entertainment': { badge:'badge-pop',  accent:'linear-gradient(135deg,#f472b6,#fb923c)', icon:'🎬' },
    'Gaming':        { badge:'badge-game', accent:'linear-gradient(135deg,#34d399,#4fc3f7)', icon:'🎮' },
    'Tech':          { badge:'badge-tech', accent:'linear-gradient(135deg,#b57bee,#4fc3f7)', icon:'💻' },
    'Science':       { badge:'badge-sci',  accent:'linear-gradient(135deg,#fbbf24,#34d399)', icon:'🔬' },
    'World News':    { badge:'badge-default', accent:'linear-gradient(135deg,#6b7280,#374151)', icon:'🌍' },
    'Space':         { badge:'badge-sci',  accent:'linear-gradient(135deg,#b57bee,#4fc3f7)', icon:'🚀' },
    'Finance':       { badge:'badge-default', accent:'linear-gradient(135deg,#34d399,#fbbf24)', icon:'📈' },
    'Sports':        { badge:'badge-game', accent:'linear-gradient(135deg,#fb923c,#f472b6)', icon:'⚽' },
};
const DEFAULT_STYLE = { badge:'badge-default', accent:'linear-gradient(135deg,#4fc3f7,#b57bee)', icon:'📡' };
const ts = topic => TOPIC_MAP[topic] || DEFAULT_STYLE;

/* ─────────────────────────────────────────────
   TOAST
───────────────────────────────────────────── */
function showToast(msg, type = 'info', duration = 3800) {
    const icons = { success:'✅', error:'❌', info:'ℹ️', warning:'⚠️' };
    const el    = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `<span>${icons[type]||'ℹ️'}</span> ${msg}`;
    toastContainer.appendChild(el);
    setTimeout(() => {
        el.style.opacity = '0';
        el.style.transition = 'opacity 0.3s ease';
        setTimeout(() => el.remove(), 300);
    }, duration);
}

/* ─────────────────────────────────────────────
   TOPICS
───────────────────────────────────────────── */
async function loadTopics() {
    try {
        const res    = await fetch('/api/topics');
        const topics = await res.json();
        renderTopicPills(topics);
        if (ssTopics) {
            const count = Array.isArray(topics) ? topics.length - 1 : 0;
            ssTopics.textContent = Math.max(0, count);
        }
    } catch (e) {
        console.warn('[Topics] Failed:', e);
    }
}

function renderTopicPills(topics) {
    topicList.innerHTML = '';
    topics.forEach(item => {
        const topicName = typeof item === 'object' ? item.topic : item;
        const count     = typeof item === 'object' ? item.count : null;
        const style     = ts(topicName);
        const btn       = document.createElement('button');
        const isCurrent = topicName.toLowerCase() === state.topic.toLowerCase();
        
        btn.className     = `topic-pill${isCurrent ? ' active' : ''}`;
        btn.dataset.topic = topicName;
        
        const countBadge = count !== null ? `<span class="pill-count">${count}</span>` : '';
        btn.innerHTML   = `<span class="pill-left"><span class="pill-icon">${style.icon}</span><span class="pill-title">${escHtml(topicName)}</span></span>${countBadge}`;
        
        btn.addEventListener('click', () => {
            state.topic = topicName;
            state.page  = 1;
            $$('.topic-pill').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            fetchArticles();
        });
        topicList.appendChild(btn);
    });
}

/* ─────────────────────────────────────────────
   SORT BUTTONS
───────────────────────────────────────────── */
$$('.sort-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        state.sortBy = btn.dataset.sort;
        state.page   = 1;
        $$('.sort-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        fetchArticles();
    });
});

/* ─────────────────────────────────────────────
   FETCH ARTICLES
───────────────────────────────────────────── */
async function fetchArticles(silent = false) {
    if (state.loading) return;
    state.loading = true;

    if (!silent) {
        loader.classList.remove('hidden');
        newsGrid.classList.add('hidden');
        emptyState.classList.add('hidden');
        paginationBar.classList.add('hidden');
    }

    try {
        const url = `/api/articles?topic=${encodeURIComponent(state.topic)}&page=${state.page}&per_page=${state.perPage}&sort_by=${state.sortBy}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        state.totalPages    = data.total_pages;
        state.totalArticles = data.total;

        // Rebuild saved set from returned flags
        data.articles.forEach(a => {
            if (a.is_saved) state.savedIds.add(a.id);
            else            state.savedIds.delete(a.id);
        });

        renderArticles(data.articles);
        updateStatsBar(data);
        renderPagination();
        updateSavedBadge();
    } catch (err) {
        console.error('[Articles]', err);
        emptyState.classList.remove('hidden');
        showToast('Could not load articles.', 'error');
    } finally {
        if (!silent) {
            loader.classList.add('hidden');
        }
        state.loading = false;
    }
}

/* ─────────────────────────────────────────────
   RENDER CARDS
───────────────────────────────────────────── */
function escHtml(s)  { return s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : ''; }
function escAttr(s)  { return s ? s.replace(/"/g,'&quot;') : ''; }

function timeAgo(dateStr) {
    const diff = (Date.now() - new Date(dateStr)) / 1000;
    if (diff < 60)    return 'just now';
    if (diff < 3600)  return `${Math.floor(diff/60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
    return `${Math.floor(diff/86400)}d ago`;
}

function videoLabel(score) {
    if (score >= 60) return `🎬 ${score} 🔥`;
    if (score >= 35) return `🎬 ${score}`;
    return `🎬 ${score}`;
}

function viralLabel(score) {
    if (score >= 25) return `🔥 ${score}`;
    if (score >= 10) return `⚡ ${score}`;
    return `📊 ${score}`;
}

function renderArticles(articles) {
    newsGrid.innerHTML = '';

    if (!articles.length) {
        emptyState.classList.remove('hidden');
        return;
    }
    emptyState.classList.add('hidden');

    articles.forEach((article, i) => {
        const style    = ts(article.topic);
        const isSaved  = state.savedIds.has(article.id);
        const isModel  = (article.source || '').includes('OpenRouter');
        const videoHot = (article.video_score || 0) >= 60;

        const card = document.createElement('div');
        card.className = 'news-card';
        card.style.cssText = `--card-accent:${style.accent}; animation-delay:${i * 0.035}s`;
        card.dataset.link  = article.link;
        card.dataset.title = article.title;
        card.dataset.id    = article.id;

        const imageUrl = article.image_url || 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=800&fit=crop';

        card.innerHTML = `
            <div class="card-media">
                <img src="${escAttr(imageUrl)}" alt="${escAttr(article.title)}" loading="lazy" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=800&fit=crop';">
                <div class="card-media-overlay"></div>
                <div class="card-media-badge">
                    <span class="badge ${style.badge}">${style.icon} ${escHtml(article.topic)}</span>
                </div>
            </div>
            <div class="card-inner">
                <div class="card-top">
                    <div class="card-badges">
                        ${article.is_new ? '<span class="badge badge-new">✨ NEW</span>' : ''}
                        ${isModel ? '<span class="badge badge-model">⚡ Model Drop</span>' : ''}
                    </div>
                    <button class="bookmark-btn ${isSaved ? 'saved' : ''}"
                            data-id="${article.id}" data-saved="${isSaved}"
                            title="${isSaved ? 'Remove bookmark' : 'Save for later'}">
                        ${isSaved ? '🔖' : '🔗'}
                    </button>
                </div>
                <div class="card-title">${escHtml(article.title)}</div>
                <div class="card-desc">${escHtml(article.description || '')}</div>
                <div class="card-scores">
                    <span class="score-tag score-viral">${viralLabel(article.score || 0)}</span>
                    <span class="score-tag score-video ${videoHot ? 'hot' : ''}"
                          title="Video potential score (0–100)">${videoLabel(article.video_score || 0)}</span>
                </div>
                <div class="card-footer">
                    <span class="card-source">${escHtml(article.source || '')}</span>
                    <span>${timeAgo(article.processed_date)}</span>
                </div>
            </div>
            <div class="card-actions">
                <button class="btn-card btn-card-read"
                        data-id="${article.id}"
                        data-url="${escAttr(article.link)}"
                        data-title="${escAttr(article.title)}"
                        data-topic="${escAttr(article.topic)}"
                        data-img="${escAttr(imageUrl)}"
                        data-score="${article.score||0}"
                        data-vscore="${article.video_score||0}">
                    📖 Quick Read
                </button>
                <a class="btn-card btn-card-link" href="${escHtml(article.link)}"
                   target="_blank" rel="noopener" onclick="event.stopPropagation()">
                    ↗ Open
                </a>
            </div>
        `;

        // Quick Read
        card.querySelector('.btn-card-read').addEventListener('click', e => {
            e.stopPropagation();
            const btn = e.currentTarget;
            openModal(+btn.dataset.id, btn.dataset.url, btn.dataset.title, btn.dataset.topic, +btn.dataset.score, +btn.dataset.vscore, btn.dataset.img);
        });

        // Card click
        card.addEventListener('click', e => {
            if (!e.target.closest('.btn-card-link') && !e.target.closest('.bookmark-btn')) {
                openModal(article.id, article.link, article.title, article.topic, article.score||0, article.video_score||0, imageUrl);
            }
        });

        // Bookmark
        card.querySelector('.bookmark-btn').addEventListener('click', e => {
            e.stopPropagation();
            toggleBookmark(article.id, isSaved, e.currentTarget);
        });

        newsGrid.appendChild(card);
    });

    newsGrid.classList.remove('hidden');
}

/* ─────────────────────────────────────────────
   BOOKMARK TOGGLE
───────────────────────────────────────────── */
async function toggleBookmark(articleId, currentlySaved, btnEl) {
    const method = currentlySaved ? 'DELETE' : 'POST';
    try {
        const res  = await fetch(`/api/save/${articleId}`, { method });
        const data = await res.json();
        if (data.ok !== false) {
            const nowSaved = !currentlySaved;
            if (nowSaved) {
                state.savedIds.add(articleId);
                btnEl.textContent = '🔖';
                btnEl.classList.add('saved');
                btnEl.dataset.saved = 'true';
                showToast('Article saved to your list!', 'success');
            } else {
                state.savedIds.delete(articleId);
                btnEl.textContent = '🔗';
                btnEl.classList.remove('saved');
                btnEl.dataset.saved = 'false';
                showToast('Removed from saved.', 'info');
            }
            updateSavedBadge();
            // Refresh saved panel if open
            if (!savedPanel.classList.contains('hidden')) {
                loadSavedPanel();
            }
        }
    } catch (e) {
        showToast('Could not update bookmark.', 'error');
    }
}

function updateSavedBadge() {
    const count = state.savedIds.size;
    if (count > 0) {
        savedBadgeCount.textContent = count > 99 ? '99+' : count;
        savedBadgeCount.classList.remove('hidden');
    } else {
        savedBadgeCount.classList.add('hidden');
    }
}

/* ─────────────────────────────────────────────
   SAVED PANEL
───────────────────────────────────────────── */
savedPanelToggle.addEventListener('click', () => openSavedPanel());
savedPanelClose.addEventListener('click',  () => closeSavedPanel());
savedOverlay.addEventListener('click',     () => closeSavedPanel());

function openSavedPanel() {
    savedPanel.classList.remove('hidden');
    savedOverlay.classList.remove('hidden');
    loadSavedPanel();
}
function closeSavedPanel() {
    savedPanel.classList.add('hidden');
    savedOverlay.classList.add('hidden');
}

async function loadSavedPanel() {
    savedPanelBody.innerHTML = '<div class="modal-loader"><div class="spinner"></div><p>Loading…</p></div>';
    try {
        const res  = await fetch('/api/saved');
        const data = await res.json();
        if (!data.articles.length) {
            savedPanelBody.innerHTML = `
                <div class="saved-empty">
                    <div class="empty-icon">🔖</div>
                    <p>No saved articles yet. Bookmark articles you want to turn into videos.</p>
                </div>`;
            return;
        }
        savedPanelBody.innerHTML = '';
        data.articles.forEach(a => {
            const style    = ts(a.topic);
            const videoHot = (a.video_score||0) >= 60;
            const item     = document.createElement('div');
            item.className = 'saved-item';
            item.style.cssText = `--item-accent:${style.accent}`;
            item.innerHTML = `
                <div class="saved-item-title">${escHtml(a.title)}</div>
                <div class="saved-item-meta">
                    <span class="saved-item-src">${escHtml(a.source||'')} · ${timeAgo(a.processed_date)}</span>
                    <div class="saved-item-scores">
                        <span class="score-tag score-viral" style="font-size:0.65rem;padding:1px 6px">${viralLabel(a.score||0)}</span>
                        <span class="score-tag score-video ${videoHot?'hot':''}" style="font-size:0.65rem;padding:1px 6px">${videoLabel(a.video_score||0)}</span>
                    </div>
                </div>
                <div class="saved-item-actions" style="display: flex; gap: 6px; margin-top: 8px;">
                    <button class="saved-item-create-wf" data-id="${a.id}" style="flex: 1; padding: 5px 8px; background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.35); color: #38bdf8; border-radius: 6px; font-size: 0.76rem; font-weight: 600; cursor: pointer;">⚡ Create Workflow</button>
                    <button class="saved-item-remove" data-id="${a.id}" style="padding: 5px 8px; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.25); color: #f87171; border-radius: 6px; font-size: 0.76rem; cursor: pointer;">🗑</button>
                </div>
            `;
            item.querySelector('.saved-item-create-wf').addEventListener('click', e => {
                e.stopPropagation();
                try {
                    localStorage.setItem('pf_selected_signal', JSON.stringify({
                        title: a.title,
                        topic: a.topic || 'Trending',
                        score: a.score || 95,
                        image_url: a.image_url || '',
                        link: a.link || ''
                    }));
                } catch(err){}
                closeSavedPanel();
                window.location.href = '/automation?view=builder';
            });
            item.querySelector('.saved-item-remove').addEventListener('click', async e => {
                e.stopPropagation();
                await fetch(`/api/save/${a.id}`, { method:'DELETE' });
                state.savedIds.delete(a.id);
                item.remove();
                updateSavedBadge();
                showToast('Removed from saved.', 'info');
                // Refresh card bookmark icons
                fetchArticles(true);
            });
            item.addEventListener('click', e => {
                if (!e.target.closest('.saved-item-remove') && !e.target.closest('.saved-item-create-wf')) {
                    openModal(a.id, a.link, a.title, a.topic, a.score||0, a.video_score||0, a.image_url);
                }
            });
            savedPanelBody.appendChild(item);
        });
    } catch (e) {
        savedPanelBody.innerHTML = '<div class="saved-empty"><p>Failed to load saved articles.</p></div>';
    }
}

/* ─────────────────────────────────────────────
   STATS BAR
───────────────────────────────────────────── */
function updateStatsBar(data) {
    const newCount = data.articles.filter(a => a.is_new).length;
    statTotal.textContent = `📰 ${data.total} articles`;
    statNew.textContent   = `✨ ${newCount} new`;
    statPage.textContent  = `📄 Page ${data.page} of ${data.total_pages}`;
}

/* ─────────────────────────────────────────────
   PAGINATION
───────────────────────────────────────────── */
function renderPagination() {
    if (state.totalPages <= 1) { paginationBar.classList.add('hidden'); return; }
    paginationBar.classList.remove('hidden');
    prevBtn.disabled = state.page <= 1;
    nextBtn.disabled = state.page >= state.totalPages;

    pagePills.innerHTML = '';
    getPageRange(state.page, state.totalPages).forEach(p => {
        const pill = document.createElement('button');
        pill.className   = `page-pill${p === state.page ? ' active' : ''}`;
        pill.textContent = p === '…' ? '…' : p;
        if (p !== '…') pill.addEventListener('click', () => { state.page = p; fetchArticles(); });
        pagePills.appendChild(pill);
    });
}

function getPageRange(cur, total) {
    if (total <= 7) return Array.from({length:total}, (_, i) => i + 1);
    const s = new Set([1, total, cur]);
    for (let d = -2; d <= 2; d++) { const p=cur+d; if(p>=1&&p<=total) s.add(p); }
    const sorted = [...s].sort((a,b) => a-b);
    const out = []; let prev = null;
    for (const p of sorted) { if (prev !== null && p-prev > 1) out.push('…'); out.push(p); prev = p; }
    return out;
}

prevBtn.addEventListener('click', () => { if(state.page>1){ state.page--; fetchArticles(); } });
nextBtn.addEventListener('click', () => { if(state.page<state.totalPages){ state.page++; fetchArticles(); } });

/* ─────────────────────────────────────────────
   MODAL
───────────────────────────────────────────── */
let currentModalArticleId = null;
let currentModalArticleData = null;

async function openModal(id, url, title, topic='', score=0, videoScore=0, imageUrl=null) {
    currentModalArticleId = id;
    currentModalArticleData = {
        id,
        title,
        link: url,
        topic: topic || 'Trending',
        score: score || 95,
        video_score: videoScore || 85,
        image_url: imageUrl || ''
    };
    modalTitle.textContent = title;
    modalOpenLink.href     = url;

    // Featured image banner in modal
    if (imageUrl && modalMediaBanner && modalImg) {
        modalImg.src = imageUrl;
        modalMediaBanner.classList.remove('hidden');
    } else if (modalMediaBanner) {
        modalMediaBanner.classList.add('hidden');
    }

    // Topic + score tags in modal header
    const style    = ts(topic);
    const videoHot = videoScore >= 60;
    modalTags.innerHTML = `
        <span class="badge ${style.badge}">${style.icon} ${escHtml(topic)}</span>
        <span class="score-tag score-viral">${viralLabel(score)}</span>
        <span class="score-tag score-video ${videoHot?'hot':''}" title="Video potential">${videoLabel(videoScore)}</span>
    `;

    modalBody.innerHTML = `<div class="modal-loader"><div class="spinner"></div><p>Fetching article content…</p></div>`;
    modalOverlay.classList.remove('hidden');
    requestAnimationFrame(() => modalOverlay.classList.add('visible'));

    try {
        const res  = await fetch(`/api/scrape?url=${encodeURIComponent(url)}`);
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        const paras = data.content
            .split('\n\n')
            .filter(p => p.trim().length > 25)
            .map(p => `<p>${escHtml(p.trim())}</p>`)
            .join('');
        modalBody.innerHTML = paras || '<p style="color:#6b7280">No readable content found. Click "Open Original" to read the full article.</p>';
    } catch {
        modalBody.innerHTML = `<p style="color:#f472b6">Could not scrape this article. Open it directly using the button below.</p>`;
    }
}

function closeModal() {
    modalOverlay.classList.remove('visible');
    setTimeout(() => modalOverlay.classList.add('hidden'), 250);
}

modalClose.addEventListener('click', closeModal);
modalOverlay.addEventListener('click', e => { if(e.target===modalOverlay) closeModal(); });
document.addEventListener('keydown', e => { if(e.key==='Escape') closeModal(); });

document.getElementById('modalAutoBtn')?.addEventListener('click', async () => {
    if (!currentModalArticleId) return;
    
    // Save the article if it isn't already saved
    if (!state.savedIds.has(currentModalArticleId)) {
        try {
            await fetch(`/api/save/${currentModalArticleId}`, { method: 'POST' });
            state.savedIds.add(currentModalArticleId);
            updateSavedBadge();
            fetchArticles(true);
        } catch (e) {
            console.warn('Failed to auto-save article for automation', e);
        }
    }

    if (currentModalArticleData) {
        try {
            localStorage.setItem('pf_selected_signal', JSON.stringify({
                title: currentModalArticleData.title,
                topic: currentModalArticleData.topic,
                score: currentModalArticleData.score,
                image_url: currentModalArticleData.image_url,
                link: currentModalArticleData.link
            }));
        } catch(e){}
    }
    
    // Close modal and switch tab to automation
    closeModal();
    window.location.href = '/automation?view=builder';
});

/* ─────────────────────────────────────────────
   VIRAL VIDEO HITS
───────────────────────────────────────────── */
async function fetchViralVideos() {
    if (state.videoLoading) return;
    state.videoLoading = true;
    if (videoLoader) videoLoader.classList.remove('hidden');
    if (videoGrid)   videoGrid.classList.add('hidden');

    try {
        const url = `/api/trending-videos?platform=${encodeURIComponent(state.videoPlatform)}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        state.videos = data.videos || [];
        renderViralVideos(state.videos);
        if (videoStatTotal) {
            videoStatTotal.textContent = `🔥 ${state.videos.length} High-Velocity Hits`;
        }
    } catch (err) {
        console.error('[ViralVideos]', err);
        showToast('Could not load trending videos.', 'error');
    } finally {
        if (videoLoader) videoLoader.classList.add('hidden');
        state.videoLoading = false;
    }
}

function renderViralVideos(videos) {
    if (!videoGrid) return;
    videoGrid.innerHTML = '';

    if (!videos.length) {
        videoGrid.innerHTML = `
            <div class="empty-state" style="grid-column: 1 / -1;">
                <div class="empty-icon">🎬</div>
                <h2>No viral videos found for this filter</h2>
                <p>Try switching to All Viral Platforms.</p>
            </div>`;
        videoGrid.classList.remove('hidden');
        return;
    }

    videos.forEach((vid, i) => {
        const card = document.createElement('div');
        card.className = 'video-card';
        card.style.animationDelay = `${i * 0.05}s`;

        const isYt = vid.platform === 'youtube';
        const platformBadge = isYt 
            ? '<span class="badge badge-yt">🔴 YouTube Shorts</span>'
            : '<span class="badge badge-ig">🟣 Instagram Reels</span>';

        card.innerHTML = `
            <div class="video-frame-wrap">
                <iframe src="${escAttr(vid.embed_url)}" 
                        title="${escAttr(vid.title)}" 
                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" 
                        allowfullscreen 
                        loading="lazy"></iframe>
            </div>
            <div class="video-card-body">
                <div class="video-header-row">
                    <div class="video-author-chip">
                        <img src="${escAttr(vid.avatar || 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100&h=100&fit=crop')}" alt="${escAttr(vid.author)}">
                        <div>
                            <div class="video-author-name">${escHtml(vid.author)}</div>
                            <div class="video-author-handle">${escHtml(vid.handle || '')}</div>
                        </div>
                    </div>
                    ${platformBadge}
                </div>

                <div class="video-title">${escHtml(vid.title)}</div>
                <div class="video-caption">${escHtml(vid.caption || '')}</div>

                <div class="video-meta-row">
                    <div class="video-stats">
                        <span class="video-stat-item">👁️ <strong>${vid.views || '1M'}</strong></span>
                        <span class="video-stat-item">❤️ <strong>${vid.likes || '50K'}</strong></span>
                    </div>
                    <span class="score-tag score-viral" style="font-size:0.75rem;">🔥 ${vid.viral_score || 95} Potency</span>
                </div>

                <div class="video-actions">
                    <button class="video-btn-action video-btn-automation" data-title="${escAttr(vid.title)}" data-caption="${escAttr(vid.caption||'')}">
                        🎬 Use as Video Script
                    </button>
                    <a class="video-btn-action video-btn-watch" href="${escHtml(vid.video_url)}" target="_blank" rel="noopener">
                        ↗ Source
                    </a>
                </div>
            </div>
        `;

        // Action: Preload into automation
        card.querySelector('.video-btn-automation').addEventListener('click', () => {
            sessionStorage.setItem('prefill_topic', vid.title);
            sessionStorage.setItem('prefill_prompt', `Create a viral short video script inspired by: ${vid.title}. Hook: ${vid.caption}`);
            showToast('Trending hook transferred to Automation!', 'success');
            setTimeout(() => {
                window.location.href = '/automation';
            }, 600);
        });

        videoGrid.appendChild(card);
    });

    videoGrid.classList.remove('hidden');
}

/* ─────────────────────────────────────────────
   TAB SWITCHING (NEWS FEED vs VIRAL HITS)
───────────────────────────────────────────── */
function initTabs() {
    if (tabNewsFeed && tabViralHits) {
        tabNewsFeed.addEventListener('click', () => {
            state.activeTab = 'news';
            tabNewsFeed.classList.add('active');
            tabViralHits.classList.remove('active');
            if (newsFeedSection)  newsFeedSection.classList.remove('hidden');
            if (viralHitsSection) viralHitsSection.classList.add('hidden');
            if (heroEyebrow) heroEyebrow.textContent = 'Zero-cost · Zero API keys · Real-time intelligence';
            if (heroTitle)   heroTitle.innerHTML = 'Forge Viral Content from<br><span class="gradient-text">Real-Time Signals</span>';
            if (heroSubtitle) heroSubtitle.textContent = 'AI model drops · HackerNews · Pop Culture · Tech · Gaming · Science · Finance';
        });

        tabViralHits.addEventListener('click', () => {
            state.activeTab = 'viral';
            tabViralHits.classList.add('active');
            tabNewsFeed.classList.remove('active');
            if (newsFeedSection)  newsFeedSection.classList.add('hidden');
            if (viralHitsSection) viralHitsSection.classList.remove('hidden');
            if (heroEyebrow) heroEyebrow.textContent = 'High-Velocity Video Intelligence';
            if (heroTitle)   heroTitle.innerHTML = 'Viral Video Hits &<br><span class="gradient-text">Direct Creator Reels</span>';
            if (heroSubtitle) heroSubtitle.textContent = 'Trending YouTube Shorts · Viral Instagram Reels · Instant direct playback and 1-click video synthesis';
            fetchViralVideos();
        });
    }

    // Platform filter buttons in Viral Hits view
    if (platformList) {
        platformList.querySelectorAll('.topic-pill').forEach(btn => {
            btn.addEventListener('click', () => {
                platformList.querySelectorAll('.topic-pill').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                state.videoPlatform = btn.dataset.platform || 'all';
                fetchViralVideos();
            });
        });
    }
}

/* ─────────────────────────────────────────────
   MANUAL REFRESH
───────────────────────────────────────────── */
async function triggerRefresh() {
    if (refreshBtn.classList.contains('spinning')) return;
    refreshBtn.classList.add('spinning');
    showToast('Fetching latest trends in background…', 'info');
    try {
        await fetch('/api/refresh', { method:'POST' });
        if (state.activeTab === 'viral') {
            fetchViralVideos();
        }
    } catch {
        showToast('Refresh request failed.', 'error');
        refreshBtn.classList.remove('spinning');
    }
}

refreshBtn.addEventListener('click', triggerRefresh);
if (emptyRefreshBtn) emptyRefreshBtn.addEventListener('click', triggerRefresh);

/* ─────────────────────────────────────────────
   AUTO-REFRESH POLLING (every 30s)
   Detects completed pipeline runs via refresh_count change
───────────────────────────────────────────── */
async function pollRefreshStatus() {
    try {
        const res  = await fetch('/api/refresh-status');
        const data = await res.json();

        // Update sidebar last refresh
        if (data.last_refresh && ssLastRefresh) {
            ssLastRefresh.textContent = timeAgo(data.last_refresh);
        }
        if (ssTotalArticles && data.total_count > 0) {
            ssTotalArticles.textContent = data.total_count;
        }

        // Update refresh pill
        if (data.running) {
            pulseDot.className        = 'pulse-dot spinning';
            refreshPillText.textContent = '⏳ Fetching…';
            refreshBanner.classList.remove('hidden');
            refreshBannerTxt.textContent = 'Fetching latest trends — new articles coming soon…';
        } else {
            pulseDot.className        = 'pulse-dot';
            refreshPillText.textContent = data.last_refresh
                ? `Updated ${timeAgo(data.last_refresh)}`
                : 'Ready';
            refreshBanner.classList.add('hidden');
            refreshBtn.classList.remove('spinning');
        }

        // Detect a completed refresh cycle
        if (state.lastRefreshCount === -1) {
            state.lastRefreshCount = data.refresh_count;
        } else if (data.refresh_count > state.lastRefreshCount && !data.running) {
            state.lastRefreshCount = data.refresh_count;
            const newCount = data.new_count || 0;
            if (newCount > 0) {
                showToast(`✅ Feed updated! ${newCount} new articles added.`, 'success', 5000);
            } else {
                showToast('✅ Feeds refreshed — no new articles this cycle.', 'info', 4000);
            }
            await loadTopics();
            fetchArticles(true);
            if (state.activeTab === 'viral') fetchViralVideos();
        }

    } catch (e) {
        console.warn('[PollStatus]', e);
    }
}

/* ─────────────────────────────────────────────
   NAVBAR SCROLL SHADOW
───────────────────────────────────────────── */
window.addEventListener('scroll', () => {
    navbar.classList.toggle('scrolled', window.scrollY > 10);
});

/* ─────────────────────────────────────────────
   INIT
───────────────────────────────────────────── */
(async () => {
    initTabs();
    await pollRefreshStatus();
    await loadTopics();
    fetchArticles();

    setInterval(pollRefreshStatus, 30_000);
})();
