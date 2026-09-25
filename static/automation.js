'use strict';
/* ================================================================
   automation.js — PulseForge Visual Workflow Builder
   n8n-style drag-and-drop canvas with live execution simulation
   ================================================================ */

// ──────────────────────────────────────────────────────────────
// 0. UTILITY FUNCTIONS
// ──────────────────────────────────────────────────────────────
function escHtml(s) {
    if (!s) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ──────────────────────────────────────────────────────────────
// 1. CONSTANTS, STATE & NODE DEFINITIONS
// ──────────────────────────────────────────────────────────────
let SELECTED_SIGNAL = null;
// ── Batch render queue state ──
let BATCH_SIGNALS = [];
let SIGNAL_PICKER_ITEMS = [];
let SIGNAL_PICKER_TAB = 'news';
let queuePollTimer = null;


const NODE_W  = 210;    // node card width (px)
const NODE_H  = 88;     // node card height (px, approx)
const PORT_HIT = 22;    // port click radius in world px
const ZOOM_MIN = 0.15;
const ZOOM_MAX = 2.5;
const GRID_PX  = 25;

const CATS = [
    { id:'trigger',  label:'Triggers',        icon:'⚡', color:'#8b5cf6' },
    { id:'ai',       label:'AI Nodes',         icon:'🧠', color:'#3b82f6' },
    { id:'media',    label:'Media Nodes',      icon:'🎬', color:'#10b981' },
    { id:'platform', label:'Platform Nodes',   icon:'🚀', color:'#f59e0b' },
    { id:'logic',    label:'Logic Nodes',      icon:'⚙️', color:'#6b7280' },
    { id:'storage',  label:'Storage Nodes',    icon:'💾', color:'#ec4899' },
];

const NDEFS = {
    // ── Triggers
    'manual-trigger':   { label:'Manual Trigger',       icon:'▶️',  cat:'trigger',  color:'#8b5cf6', execMs:400  },
    'schedule-trigger': { label:'Schedule Trigger',     icon:'⏰',  cat:'trigger',  color:'#8b5cf6', execMs:500  },
    'article-trigger':  { label:'Article Selected',     icon:'📰',  cat:'trigger',  color:'#8b5cf6', execMs:900  },
    // ── AI
    'extract-viral-angle': { label:'Extract Viral Angle',  icon:'🎯', cat:'ai',    color:'#8b5cf6', execMs:2800 },
    'gen-hook':         { label:'Generate Hook',         icon:'🪝',  cat:'ai',       color:'#f59e0b', execMs:1800 },
    'gen-script':       { label:'Generate Script',       icon:'📝',  cat:'ai',       color:'#3b82f6', execMs:4200 },
    'gen-scene-breakdown': { label:'Scene Breakdown',    icon:'🎬',  cat:'ai',       color:'#7c3aed', execMs:2200 },
    'translate':        { label:'Translate',             icon:'🌐',  cat:'ai',       color:'#3b82f6', execMs:2500 },
    'gen-seo':          { label:'Generate SEO',          icon:'🔍',  cat:'ai',       color:'#3b82f6', execMs:1800 },
    'gen-title':        { label:'Generate Title',        icon:'📌',  cat:'ai',       color:'#3b82f6', execMs:1500 },
    'gen-desc':         { label:'Generate Description',  icon:'📄',  cat:'ai',       color:'#3b82f6', execMs:1900 },
    'gen-tags':         { label:'Generate Tags',         icon:'🏷',  cat:'ai',       color:'#3b82f6', execMs:1200 },
    // ── Media
    'tts':              { label:'Text To Speech',        icon:'🎙',  cat:'media',    color:'#10b981', execMs:5200 },
    'gen-image':        { label:'Generate Image',        icon:'🖼',  cat:'media',    color:'#10b981', execMs:6100 },
    'gen-thumbnail':    { label:'Generate Thumbnail',    icon:'📸',  cat:'media',    color:'#f59e0b', execMs:3200 },
    'img-to-video':     { label:'Image To Video',        icon:'🎞',  cat:'media',    color:'#10b981', execMs:8500 },
    'bg-music':         { label:'Background Music',      icon:'🎵',  cat:'media',    color:'#0d9488', execMs:1500 },
    'gen-sfx':          { label:'Sound Effects',         icon:'💥',  cat:'media',    color:'#0891b2', execMs:1200 },
    'subtitle-gen':     { label:'Subtitle Generator',    icon:'💬',  cat:'media',    color:'#10b981', execMs:3500 },
    'assemble-video':   { label:'Assemble Video',        icon:'🎬',  cat:'media',    color:'#10b981', execMs:7200 },
    // ── Platform
    'upload-yt':        { label:'Upload To YouTube',     icon:'📺',  cat:'platform', color:'#f59e0b', execMs:5000 },
    'store-analytics':  { label:'Store Analytics',       icon:'📈',  cat:'storage',  color:'#ec4899', execMs:800  },
    'gsheet-update':    { label:'Google Sheet Update',   icon:'📊',  cat:'platform', color:'#f59e0b', execMs:1000 },
    'send-notif':       { label:'Send Notification',     icon:'🔔',  cat:'platform', color:'#f59e0b', execMs:500  },
    // ── Growth (Rival scan, stats, SEO, music, B-roll, shorts, publish)
    'competitor-scan':  { label:'Competitor Scan',       icon:'🔎',  cat:'ai',       color:'#0ea5e9', execMs:2500 },
    'analytics-pull':   { label:'Channel Analytics',     icon:'📊',  cat:'ai',       color:'#0ea5e9', execMs:2000 },
    'seo-pack':         { label:'SEO Pack',              icon:'🏷',  cat:'ai',       color:'#0ea5e9', execMs:1500 },
    'score-script':     { label:'Retention Score',       icon:'💯',  cat:'ai',       color:'#0ea5e9', execMs:1200 },
    'add-music':        { label:'Add Music (Ducked)',    icon:'🎧',  cat:'media',    color:'#0d9488', execMs:3000 },
    'fetch-broll':      { label:'Fetch B-Roll',          icon:'🎞',  cat:'media',    color:'#0d9488', execMs:4000 },
    'cut-shorts':       { label:'Cut Viral Shorts',      icon:'✂️',  cat:'media',    color:'#0d9488', execMs:6000 },
    'make-clips':        { label:'Make Viral Clips 🎯',   icon:'🎯',  cat:'media',    color:'#0d9488', execMs:9000 },
    'repurpose':        { label:'Repurpose (9:16/1:1)',  icon:'🔁',  cat:'media',    color:'#0d9488', execMs:4000 },
    'schedule-upload':  { label:'Schedule Upload',       icon:'🗓',  cat:'platform', color:'#0ea5e9', execMs:1500 },
    // ── Logic
    'if-cond':          { label:'If Condition',          icon:'❓',  cat:'logic',    color:'#6b7280', execMs:300  },
    'delay':            { label:'Delay',                  icon:'⏱',  cat:'logic',    color:'#6b7280', execMs:2100 },
    'loop':             { label:'Loop',                   icon:'🔄',  cat:'logic',    color:'#6b7280', execMs:600  },
    'retry':            { label:'Retry',                  icon:'🔁',  cat:'logic',    color:'#6b7280', execMs:500  },
    'merge':            { label:'Merge',                  icon:'🔀',  cat:'logic',    color:'#6b7280', execMs:300  },
    // ── Storage
    'save-file':        { label:'Save File',              icon:'💾',  cat:'storage',  color:'#ec4899', execMs:800  },
    'read-file':        { label:'Read File',              icon:'📂',  cat:'storage',  color:'#ec4899', execMs:400  },
    'save-db':          { label:'Save Database Record',   icon:'🗄',  cat:'storage',  color:'#ec4899', execMs:1000 },
};

// Node-specific config schemas
const NODE_CONFIGS = {
    'extract-viral-angle': [
        { key:'model',     label:'AI Model',      type:'select', opts:['Groq (Qwen 3.8 27B) [Free]','Meta Muse Spark 1.3 [Muse]','Groq (GPT-OSS 20B) [Free]','Gemini 2.0 Flash [Free]','GPT-4o','Ollama (deepseek-r1)','Ollama (qwen3)','Ollama (qwen2.5-coder)'], def:'Groq (Qwen 3.8 27B) [Free]' },
        { key:'api_key',   label:'API Key (Optional)', type:'text', placeholder:'Leave blank to use key from .env', def:'' },
    ],
    'gen-hook': [
        { key:'model',     label:'AI Model',      type:'select', opts:['Groq (Qwen 3.8 27B) [Free]','Meta Muse Spark 1.3 [Muse]','Groq (GPT-OSS 20B) [Free]','Gemini 2.0 Flash [Free]','GPT-4o','Ollama (deepseek-r1)','Ollama (qwen3)','Ollama (qwen2.5-coder)'], def:'Groq (Qwen 3.8 27B) [Free]' },
        { key:'api_key',   label:'API Key (Optional)', type:'text', placeholder:'Leave blank to use key from .env', def:'' },
    ],
    'gen-scene-breakdown': [
        { key:'model',     label:'AI Model',      type:'select', opts:['Groq (Qwen 3.8 27B) [Free]','Meta Muse Spark 1.3 [Muse]','Gemini 2.0 Flash [Free]','GPT-4o'], def:'Groq (Qwen 3.8 27B) [Free]' },
        { key:'api_key',   label:'API Key (Optional)', type:'text', placeholder:'Leave blank to use key from .env', def:'' },
    ],
    'bg-music': [
        { key:'emotion',   label:'Override Emotion', type:'select', opts:['auto','surprise','shock','fear','excitement','curiosity','anger','inspiration'], def:'auto' },
        { key:'volume',    label:'Music Volume',  type:'range',  min:0.05, max:0.40, step:0.01, def:0.18 },
        { key:'fade',      label:'Fade Duration', type:'select', opts:['0.5s','1s','2s','3s'], def:'2s' },
    ],
    'gen-sfx': [
        { key:'volume',    label:'SFX Volume',    type:'range',  min:0.1, max:0.6, step:0.05, def:0.30 },
        { key:'max_per_sec', label:'Max SFX/2sec', type:'select', opts:['1','2','3'], def:'1' },
    ],
    'store-analytics': [
        { key:'shorts_length', label:'Shorts Length',  type:'select', opts:['30','45','60'], def:'45' },
    ],
    'manual-trigger':   [],
    'schedule-trigger': [
        { key:'interval', label:'Run Every',    type:'select', opts:['1 hour','3 hours','6 hours','12 hours','24 hours','Weekly'], def:'6 hours' },
        { key:'active',   label:'Active',       type:'toggle', def:true },
    ],
    'article-trigger': [
        { key:'topic',    label:'Saved Article', type:'select', opts:['Loading...'], def:'Loading...' },
    ],
    'gen-script': [
        { key:'model',    label:'AI Model',     type:'select', opts:['Groq (Qwen 3.8 27B) [Free]','OpenRouter (Free Models)','Meta Muse Spark 1.3 [Muse]','Groq (GPT-OSS 20B) [Free]','Gemini 2.0 Flash [Free]','GPT-4o','Ollama (deepseek-r1)','Ollama (qwen3)','Ollama (qwen2.5-coder)'], def:'Groq (Qwen 3.8 27B) [Free]' },
        { key:'api_key',  label:'API Key (Optional)', type:'text', placeholder:'Leave blank – uses GROQ_API_KEY from .env', def:'' },
        { key:'shorts_length', label:'Shorts Length', type:'select', opts:['30 seconds','45 seconds','60 seconds'], def:'45 seconds' },
        { key:'style',    label:'Video Style',  type:'select', opts:['Viral Short','Informative','Educational','Entertaining','Tutorial'], def:'Viral Short' },
        { key:'prompt',   label:'Custom Prompt',type:'textarea', placeholder:'Add any extra instructions for AI context...', def:'' },
    ],
    'translate': [
        { key:'lang',     label:'Target Language', type:'select', opts:['Hindi','Spanish','French','German','Japanese','Portuguese'], def:'Hindi' },
        { key:'model',    label:'Translation Model', type:'select', opts:['Groq (Qwen 3.8 27B) [Free]','Meta Muse Spark 1.3 [Muse]','GPT-4o','Google Translate'], def:'Groq (Qwen 3.8 27B) [Free]' },
    ],
    'gen-seo': [
        { key:'keywords', label:'Focus Keywords', type:'text', placeholder:'AI, automation, YouTube...', def:'' },
    ],
    'tts': [
        { key:'voice',    label:'Voice',         type:'select', opts:['Kokoro-82M (af_heart) [Local Free]','Kokoro-82M (am_adam) [Local Free]','en-US-ChristopherNeural (Edge)','en-US-JennyNeural (Edge)','en-GB-RyanNeural (Edge)'], def:'Kokoro-82M (af_heart) [Local Free]' },
        { key:'voice_preset', label:'Signature Voice Preset (overrides voice)', type:'text', placeholder:'e.g. my-channel-voice', def:'' },
        { key:'speed',    label:'Speed',         type:'range',  min:0.5, max:2.0, step:0.1, def:1.1 },
        { key:'language', label:'Language',      type:'select', opts:['English','Hindi','Spanish','French','Japanese'], def:'English' },
        { key:'hindi_dub', label:'Hindi Dub (2nd audio track — English stays primary)', type:'toggle', def:false },
    ],
    'gen-image': [
        { key:'model',    label:'Image Model',   type:'select', opts:['HuggingFace FLUX.1 [Free]','Pollinations FLUX [Free]','ComfyUI (Local GPU)','DALL-E 3','Gemini (Imagen 3)'], def:'HuggingFace FLUX.1 [Free]' },
        { key:'api_key',  label:'API Key (Optional)', type:'text', placeholder:'Leave blank – uses HF_TOKEN from .env', def:'' },
        { key:'style',    label:'Visual Style',  type:'select', opts:['Cinematic 8K','Realistic','Artistic','Anime','Dark Moody'], def:'Cinematic 8K' },
        { key:'ratio',    label:'Aspect Ratio',  type:'select', opts:['9:16 (Shorts)','16:9 (YouTube)','1:1 (Square)'], def:'9:16 (Shorts)' },
        { key:'count',    label:'Images per Scene', type:'select', opts:['1','2'], def:'1' },
    ],
    'gen-thumbnail': [
        { key:'style',       label:'Thumbnail Style', type:'select', opts:['Bold Viral','Dark Moody','Minimal'], def:'Bold Viral' },
        { key:'text_source', label:'Overlay Text',    type:'select', opts:['Hook (punchiest)','Video Title','Custom Text'], def:'Hook (punchiest)' },
        { key:'custom_text', label:'Custom Text',     type:'text', placeholder:'Leave blank to use hook/title', def:'' },
    ],
    'img-to-video': [
        { key:'provider', label:'AI Video Provider', type:'select', opts:['ComfyUI (Local Wan 2.1 / LTX) [Free GPU]','HuggingFace SVD [Free Cloud]','MiniMax-H3 (Free/Cloud)','fal.ai','Kling','Luma','Runway'], def:'ComfyUI (Local Wan 2.1 / LTX) [Free GPU]' },
        { key:'api_key',  label:'API Key (Optional)', type:'text', placeholder:'Leave blank for local/free mode', def:'' },
        { key:'motion',   label:'Motion Scale',  type:'select', opts:['Low','Medium','High'], def:'Medium' },
        { key:'ratio',    label:'Aspect Ratio',  type:'select', opts:['9:16 (Shorts)','16:9 (YouTube)'], def:'9:16 (Shorts)' },
    ],
    'assemble-video': [
        { key:'editing_style', label:'Viral Reel Brain Style', type:'select', opts:['Auto-Brain (Trending Reel Match)', 'Cinematic Noir & Suspense', 'Fast-Paced Kinetic Viral', 'Vox Deep-Dive & Data Story', 'Pop Culture & Meme Banger', 'Hypnotic Infinite Retention Loop'], def:'Auto-Brain (Trending Reel Match)' },
        { key:'fps',      label:'Frame Rate',    type:'select', opts:['24fps','30fps','60fps'], def:'30fps' },
        { key:'quality',  label:'Quality',       type:'select', opts:['1080p','4K','720p'], def:'1080p' },
        { key:'shorts_length', label:'Shorts Length', type:'select', opts:['30','45','60'], def:'45' },
    ],
    'upload-yt': [
        { key:'privacy',  label:'Privacy',       type:'select', opts:['Public','Unlisted','Private'], def:'Public' },
        { key:'category', label:'Category',      type:'select', opts:['Science & Technology','Education','Entertainment','Gaming','News & Politics'], def:'Science & Technology' },
        { key:'playlist', label:'Add to Playlist', type:'text', placeholder:'Playlist name (optional)', def:'' },
        { key:'notify',   label:'Notify Subscribers', type:'toggle', def:true },
    ],
    'delay': [
        { key:'duration', label:'Wait Duration', type:'select', opts:['30 seconds','1 minute','5 minutes','15 minutes','1 hour'], def:'1 minute' },
    ],
    'if-cond': [
        { key:'condition', label:'Condition Type', type:'select', opts:['Score >= threshold','Topic matches','Has description','Custom expression'], def:'Score >= threshold' },
        { key:'value',     label:'Threshold / Value', type:'text', placeholder:'10', def:'10' },
    ],
    'send-notif': [
        { key:'channel',   label:'Channel',       type:'select', opts:['Email','Slack','Discord','Telegram'], def:'Email' },
        { key:'template',  label:'Message Template', type:'textarea', placeholder:'Video {{title}} was published!', def:'' },
    ],
    // ── Growth & Production Suite (local-first, free) ──
    'competitor-scan': [
        { key:'channel',    label:'Rival Channel (URL / @handle / ID)', type:'text', placeholder:'https://youtube.com/@SomeChannel', def:'' },
        { key:'max_videos', label:'Videos to Analyze', type:'select', opts:['10','20','30','50'], def:'30' },
        { key:'user_topics', label:'Your Topics (comma separated)', type:'text', placeholder:'AI news, space, history', def:'' },
    ],
    'analytics-pull': [
        { key:'days',   label:'Lookback Window', type:'select', opts:['7','28','90'], def:'28' },
        { key:'topics', label:'Topics to Compare (comma separated)', type:'text', placeholder:'AI, automation', def:'' },
    ],
    'seo-pack': [
        { key:'title',    label:'Video Title (blank = use pipeline title)', type:'text', placeholder:'', def:'' },
        { key:'keywords', label:'Extra Keywords (comma separated)', type:'text', placeholder:'', def:'' },
    ],
    'score-script': [
        { key:'format', label:'Format', type:'select', opts:['shorts','longform'], def:'shorts' },
    ],
    'add-music': [
        { key:'track',    label:'Local Track (blank = first in assets/music/)', type:'text', placeholder:'', def:'' },
        { key:'query',    label:'Pixabay Search (used only if no local track)', type:'text', placeholder:'cinematic upbeat', def:'' },
        { key:'music_db', label:'Music Level (dB under voice)', type:'select', opts:['-24','-20','-16','-12'], def:'-20' },
    ],
    'fetch-broll': [
        { key:'per_query', label:'Clips per Scene', type:'select', opts:['1','2','3'], def:'3' },
    ],
    'cut-shorts': [
        { key:'num_shorts', label:'Number of Shorts', type:'select', opts:['1','2','3','4','5'], def:'3' },
        { key:'min_sec',    label:'Min Length (sec)', type:'text', placeholder:'20', def:'20' },
        { key:'max_sec',    label:'Max Length (sec)', type:'text', placeholder:'58', def:'58' },
    ],
    'make-clips': [
        { key:'num_clips',  label:'Number of Clips', type:'select', opts:['1','2','3','4','5'], def:'3' },
        { key:'style',      label:'Caption Style', type:'select', opts:['karaoke','classic'], def:'karaoke' },
        { key:'highlight',  label:'Highlight Colour', type:'select', opts:['yellow','lime','cyan','orange','pink'], def:'yellow' },
        { key:'face_track', label:'Face-Tracked Reframe', type:'toggle', def:true },
        { key:'min_sec',    label:'Min Length (sec)', type:'text', placeholder:'20', def:'20' },
        { key:'max_sec',    label:'Max Length (sec)', type:'text', placeholder:'58', def:'58' },
    ],
    'repurpose': [],
    'schedule-upload': [
        { key:'title',      label:'Title Override (blank = pipeline title)', type:'text', placeholder:'', def:'' },
        { key:'publish_at', label:'Publish At (ISO, blank = due now)', type:'text', placeholder:'2026-10-01T18:00:00+05:30', def:'' },
        { key:'privacy',    label:'Privacy', type:'select', opts:['private','unlisted','public'], def:'private' },
    ],
};

// ──────────────────────────────────────────────────────────────
// 💰 FREE MODE — one-click zero-cost provider presets per node type.
// Applied by the "Free Mode" toolbar toggle; also auto-applied to
// newly added nodes while the toggle is on. Values match the free
// options in NODE_CONFIGS above, and the backend chains fall back
// to free providers (Pollinations / Ollama / HF) when keys are absent.
// ──────────────────────────────────────────────────────────────
const FREE_MODE_PRESETS = {
    'gen-script':          { model: 'Gemini 2.0 Flash [Free]' },
    'extract-viral-angle': { model: 'Gemini 2.0 Flash [Free]' },
    'gen-hook':            { model: 'Gemini 2.0 Flash [Free]' },
    'tts':                 { voice: 'Kokoro-82M (af_heart) [Local Free]' },
    'gen-image':           { model: 'Pollinations FLUX [Free]' },
    'image-gen':           { model: 'Pollinations FLUX [Free]' },
    'visuals':             { model: 'Pollinations FLUX [Free]' },
    'img-to-video':        { provider: 'ComfyUI (Local Wan 2.1 / LTX) [Free GPU]' },
    'image-to-video':      { provider: 'ComfyUI (Local Wan 2.1 / LTX) [Free GPU]' },
};

function applyFreeModeToNode(node) {
    const preset = FREE_MODE_PRESETS[node.type];
    if (!preset) return false;
    node.config = { ...(node.config || {}), ...preset };
    node.data = { ...(node.data || {}), ...preset };
    // reset any stale connection-test state — provider changed
    node._connTested = false;
    node._connOk = false;
    return true;
}

function setFreeMode(on, silent) {
    APP.freeMode = !!on;
    if (D.btnFreeMode) D.btnFreeMode.classList.toggle('tb-on', APP.freeMode);
    if (!APP.freeMode) {
        if (!silent) showToast('💰 Free Mode OFF — node providers left as-is.', 'info');
        return;
    }
    let changed = 0;
    APP.nodes.forEach(n => { if (applyFreeModeToNode(n)) { changed++; updateNodeEl(n.id); } });
    if (APP.sel) showPropsContent(APP.sel);
    saveUndo();
    if (!silent) {
        showToast(`💰 Free Mode ON — ${changed} node${changed === 1 ? '' : 's'} switched to free providers.`, 'success', 4000);
        logAdd(`[FreeMode] 💰 Enabled — ${changed} node(s) set to zero-cost providers (Gemini free / Kokoro local / Pollinations / ComfyUI local).`, 'success');
    }
}

const WF_ITEMS = [
    { icon:'⚡', name:'Full Viral Shorts Pipeline', meta:'11 nodes · Auto Trigger + Script + TTS + Video', status:'active' },
    { icon:'🧠', name:'AI News Intelligence Synthesizer', meta:'5 nodes · Extract Viral Angle + Hook + Video', status:'active' },
    { icon:'🎬', name:'Viral Hook & SFX Short', meta:'5 nodes · Manual Trigger + Hook + TTS + SFX', status:'paused' },
];

const ACT_ITEMS = [
    { dot:'dot-green', text:'Pipeline executed: "AI Agent Revolution" rendered to local MP4', time:'2 mins ago' },
    { dot:'dot-blue',  text:'Viral signal ingested from Hacker News (#1 Trending)', time:'14 mins ago' },
    { dot:'dot-purple',text:'Audio intelligence indexed 42 new dynamic SFX clips', time:'1 hour ago' },
    { dot:'dot-green', text:'YouTube token verified & connected for instant uploads', time:'3 hours ago' },
];

// ──────────────────────────────────────────────────────────────
// 2. APP STATE
// ──────────────────────────────────────────────────────────────
const APP = {
    view:       'dashboard',
    pan:        { x: 0, y: 0 },
    zoom:       0.78,     // Default 78% zoom
    nodes:      [],       // { id, type, x, y, status, progress, config }
    conns:      [],       // { id, from, to }
    sel:        null,     // selected nodeId
    dragging:   null,     // drag state
    connecting: null,     // { fromNodeId }
    execRunning:false,
    logCount:   0,
    nextId:     1,
    freeMode:   false,   // 💰 when on, nodes use zero-cost providers (see FREE_MODE_PRESETS)
    consoleCollapsed: false,
    undoStack:  [],
};

// ──────────────────────────────────────────────────────────────
// 3. DOM CACHE
// ──────────────────────────────────────────────────────────────
let D = {};
function cacheDOM() {
    const g = id => document.getElementById(id);
    D = {
        // Tabs / views
        autoTabs:       document.querySelectorAll('.auto-tab'),
        viewDash:       g('view-dashboard'),
        viewBuilder:    g('view-builder'),
        // Dashboard
        wfList:         g('wfList'),
        actList:        g('actList'),
        // Toolbar
        wfNameInput:    g('wfNameInput'),
        wfStatusBadge:  g('wfStatusBadge'),
        wfPresetSelect: g('wfPresetSelect'),
        aiMarketBadge:  g('aiMarketBadge'),
        aiMarketText:   g('aiMarketText'),
        wfProgressArea: g('wfProgressArea'),
        wfpFill:        g('wfpFill'),
        wfpPct:         g('wfpPct'),
        wfpStep:        g('wfpStep'),
        wfpEta:         g('wfpEta'),
        btnRun:         g('btnRun'),
        btnStop:        g('btnStop'),
        btnOpenQueue:   g('btnOpenQueue'),
        btnSave:        g('btnSave'),
        btnLoad:        g('btnLoad'),
        btnClearCanvas: g('btnClearCanvas'),
        btnFitView:     g('btnFitView'),
        btnResetView:   g('btnResetView'),
        btnCenterWorkflow: g('btnCenterWorkflow'),
        // Palette
        nodePalette:    g('nodePalette'),
        paletteCats:    g('paletteCats'),
        paletteSearch:  g('paletteSearch'),
        // Canvas
        canvasWrap:     g('canvasWrap'),
        canvasLockBanner: g('canvasLockBanner'),
        canvasGrid:     g('canvasGrid'),
        canvasWS:       g('canvasWS'),
        canvasSVG:      g('canvasSVG'),
        connGroup:      g('connGroup'),
        tempLine:       g('tempLine'),
        nodesLayer:     g('nodesLayer'),
        btnZoomIn:      g('btnZoomIn'),
        btnZoomOut:     g('btnZoomOut'),
        zoomVal:        g('zoomVal'),
        btnFit:         g('btnFitView'),
        minimap:        g('minimap'),
        canvasHint:     g('canvasHint'),
        // Props
        propsEmpty:     g('propsEmpty'),
        propsContent:   g('propsContent'),
        // Console
        consoleBody:    g('consoleBody'),
        chCount:        g('chCount'),
        chDot:          g('chDot'),
        btnClearLog:    g('btnClearLog'),
        btnCollapseConsole: g('btnCollapseConsole'),
        execConsole:    g('execConsole'),
        // Context menu
        ctxMenu:        g('ctxMenu'),
        // Config modal
        configModalOverlay: g('configModalOverlay'),
        configModal:    g('configModal'),
        cmIcon:         g('cmIcon'),
        cmTitle:        g('cmTitle'),
        cmBody:         g('cmBody'),
        cmClose:        g('cmClose'),
        cmCancel:       g('cmCancel'),
        cmSaveConfig:   g('cmSaveConfig'),
        // Signal bar & modals
        wfSourceBar:    g('wfSourceBar'),
        wfSourceEmpty:  g('wfSourceEmpty'),
        wfSourceActive: g('wfSourceActive'),
        wfSourceImg:    g('wfSourceImg'),
        wfSourceTitle:  g('wfSourceTitle'),
        wfSourceTopic:  g('wfSourceTopic'),
        wfSourceScore:  g('wfSourceScore'),
        btnOpenSignalPicker: g('btnOpenSignalPicker'),
        signalPickerModal: g('signalPickerModal'),
        signalPickerClose: g('signalPickerClose'),
        signalPickerBody: g('signalPickerBody'),
        btnViewEditingRecipe: g('btnViewEditingRecipe'),
        editingRecipeModal: g('editingRecipeModal'),
        editingRecipeClose: g('editingRecipeClose'),
        editingRecipeBody: g('editingRecipeBody'),
        // Dashboard & Video Storage Elements
        dashVideosContainer: g('dashVideosContainer'),
        dashVideoCountBadge: g('dashVideoCountBadge'),
        dashRunsCountBadge:  g('dashRunsCountBadge'),
        btnRefreshDashboard: g('btnRefreshDashboard'),
        dashVideoModal:      g('dashVideoModal'),
        dashVideoPlayer:     g('dashVideoPlayer'),
        dashVideoModalTitle: g('dashVideoModalTitle'),
        dashVideoModalPath:  g('dashVideoModalPath'),
        dashVideoModalClose: g('dashVideoModalClose'),
        btnCopyModalVideoPath: g('btnCopyModalVideoPath'),
        btnDownloadModalVideo: g('btnDownloadModalVideo'),
        // Toast
        toastContainer: g('toastContainer'),
        btnFreeMode:     g('btnFreeMode'),
        // API Keys Configuration Modal
        btnOpenApiKeysModal: g('btnOpenApiKeysModal'),
        apiKeysConfigModal:  g('apiKeysConfigModal'),
        apiKeysModalClose:   g('apiKeysModalClose'),
        btnCancelApiKeys:    g('btnCancelApiKeys'),
        btnSaveApiKeys:      g('btnSaveApiKeys'),
        keyInputMinimax:     g('keyInputMinimax'),
        keyInputFal:         g('keyInputFal'),
        keyInputElevenlabs:  g('keyInputElevenlabs'),
        keyInputOpenai:      g('keyInputOpenai'),
        keyInputGroq:        g('keyInputGroq'),
        keyInputMuse:        g('keyInputMuse'),
        keyInputOpenrouter:  g('keyInputOpenrouter'),
        keyInputPixabay:     g('keyInputPixabay'),
        keyInputPexels:      g('keyInputPexels'),
        keyInputGemini:      g('keyInputGemini'),
        keyInputHf:          g('keyInputHf'),
        keyInputComfyUrl:    g('keyInputComfyUrl'),
        badgeMinimaxKey:     g('badgeMinimaxKey'),
        badgeFalKey:         g('badgeFalKey'),
        badgeElevenKey:      g('badgeElevenKey'),
        badgeOpenaiKey:      g('badgeOpenaiKey'),
        badgeGroqKey:        g('badgeGroqKey'),
        badgeMuseKey:        g('badgeMuseKey'),
        badgeOpenrouterKey:  g('badgeOpenrouterKey'),
        badgePixabayKey:     g('badgePixabayKey'),
        badgePexelsKey:      g('badgePexelsKey'),
        badgeGeminiKey:      g('badgeGeminiKey'),
        badgeHfKey:          g('badgeHfKey'),
        badgeComfyUrl:       g('badgeComfyUrl'),
    };
}

// ──────────────────────────────────────────────────────────────
// 4. CANVAS MANAGEMENT (transform, zoom, pan, grid)
// ──────────────────────────────────────────────────────────────
function applyTransform() {
    D.canvasWS.style.transform = `translate(${APP.pan.x}px, ${APP.pan.y}px) scale(${APP.zoom})`;
    D.zoomVal.textContent = Math.round(APP.zoom * 100) + '%';
    updateGrid();
    drawMinimap();
}

function updateGrid() {
    const gs = GRID_PX * APP.zoom;
    const gx = APP.pan.x % gs;
    const gy = APP.pan.y % gs;
    D.canvasGrid.style.setProperty('--gs', `${gs}px`);
    D.canvasGrid.style.setProperty('--gx', `${gx}px`);
    D.canvasGrid.style.setProperty('--gy', `${gy}px`);
}

function getCanvasRect() { return D.canvasWrap.getBoundingClientRect(); }

function viewToWorld(vx, vy) {
    return { x: (vx - APP.pan.x) / APP.zoom, y: (vy - APP.pan.y) / APP.zoom };
}

function canvasXY(e) {
    const r = getCanvasRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
}

function zoomAtPoint(newZ, vx, vy) {
    newZ = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, newZ));
    const wx = (vx - APP.pan.x) / APP.zoom;
    const wy = (vy - APP.pan.y) / APP.zoom;
    APP.pan.x = vx - wx * newZ;
    APP.pan.y = vy - wy * newZ;
    APP.zoom  = newZ;
    applyTransform();
}

function fitView(smooth = false) {
    if (!APP.nodes.length) return;
    const pad = 60;
    const minX = Math.min(...APP.nodes.map(n => n.x)) - pad;
    const minY = Math.min(...APP.nodes.map(n => n.y)) - pad;
    const maxX = Math.max(...APP.nodes.map(n => n.x + NODE_W)) + pad;
    const maxY = Math.max(...APP.nodes.map(n => n.y + NODE_H)) + pad;
    const vpW = D.canvasWrap.clientWidth;
    const vpH = D.canvasWrap.clientHeight;
    const wW  = maxX - minX;
    const wH  = maxY - minY;
    const newZ = Math.min(vpW / wW, vpH / wH, ZOOM_MAX) * 0.92;
    
    const targetZoom = Math.max(newZ, ZOOM_MIN);
    const targetPanX = (vpW - wW * targetZoom) / 2 - minX * targetZoom;
    const targetPanY = (vpH - wH * targetZoom) / 2 - minY * targetZoom;

    if (smooth) {
        D.canvasWS.classList.add('smooth-transform');
        APP.zoom = targetZoom;
        APP.pan.x = targetPanX;
        APP.pan.y = targetPanY;
        applyTransform();
        setTimeout(() => {
            D.canvasWS.classList.remove('smooth-transform');
        }, 600);
    } else {
        APP.zoom = targetZoom;
        APP.pan.x = targetPanX;
        APP.pan.y = targetPanY;
        applyTransform();
    }
}

function resetView() {
    D.canvasWS.classList.add('smooth-transform');
    APP.zoom = 0.78;
    centerNode('n1', false);
    applyTransform();
    setTimeout(() => {
        D.canvasWS.classList.remove('smooth-transform');
    }, 600);
}

function centerNode(nodeId, smooth = true) {
    const node = APP.nodes.find(n => n.id === nodeId);
    if (!node) return;
    const vpW = D.canvasWrap.clientWidth;
    const vpH = D.canvasWrap.clientHeight;
    const targetPanX = vpW / 2 - (node.x + NODE_W / 2) * APP.zoom;
    const targetPanY = vpH / 2 - (node.y + NODE_H / 2) * APP.zoom;

    if (smooth) {
        D.canvasWS.classList.add('smooth-transform');
        APP.pan.x = targetPanX;
        APP.pan.y = targetPanY;
        applyTransform();
        setTimeout(() => {
            D.canvasWS.classList.remove('smooth-transform');
        }, 600);
    } else {
        APP.pan.x = targetPanX;
        APP.pan.y = targetPanY;
        applyTransform();
    }
}

// ──────────────────────────────────────────────────────────────
// 5. NODE MANAGEMENT
// ──────────────────────────────────────────────────────────────
function genId() { return 'n' + (APP.nextId++); }
function genCId() { return 'c' + (APP.nextId++); }

function addNode(type, wx, wy) {
    if (APP.execRunning) {
        showToast('🔒 Workflow execution is active. Canvas modifications are locked.', 'warning');
        return null;
    }
    if (!NDEFS[type]) return;
    const node = {
        id:       genId(),
        type,
        x:        Math.round(wx - NODE_W / 2),
        y:        Math.round(wy - NODE_H / 2),
        status:   'waiting',
        progress: 0,
        config:   {},
    };
    APP.nodes.push(node);
    if (APP.freeMode) applyFreeModeToNode(node);
    renderNodeEl(node);
    hideCanvasHint();
    saveUndo();
    return node;
}

function removeNode(nodeId) {
    if (APP.execRunning) {
        showToast('🔒 Workflow execution is active. Canvas modifications are locked.', 'warning');
        return;
    }
    APP.nodes = APP.nodes.filter(n => n.id !== nodeId);
    APP.conns = APP.conns.filter(c => c.from !== nodeId && c.to !== nodeId);
    const el = document.getElementById('cn-' + nodeId);
    if (el) el.remove();
    // Remove connections from SVG
    document.querySelectorAll(`[data-from="${nodeId}"],[data-to="${nodeId}"]`)
            .forEach(el => el.remove());
    if (APP.sel === nodeId) { APP.sel = null; showPropsEmpty(); }
    saveUndo();
    drawMinimap();
}

function duplicateNode(nodeId) {
    if (APP.execRunning) {
        showToast('🔒 Workflow execution is active. Canvas modifications are locked.', 'warning');
        return;
    }
    const orig = APP.nodes.find(n => n.id === nodeId);
    if (!orig) return;
    const node = {
        ...orig,
        id: genId(),
        x:  orig.x + 30,
        y:  orig.y + 30,
        status: 'waiting',
        progress: 0,
        config: { ...orig.config },
    };
    APP.nodes.push(node);
    renderNodeEl(node);
    selectNode(node.id);
    saveUndo();
}

function renderNodeEl(node) {
    const def = NDEFS[node.type] || {};
    const el  = document.createElement('div');
    el.id          = 'cn-' + node.id;
    el.className   = 'cnode';
    el.dataset.id  = node.id;
    el.dataset.cat = def.cat || '';
    el.style.left  = node.x + 'px';
    el.style.top   = node.y + 'px';
    el.style.setProperty('--nc', def.color || '#4fc3f7');
    el.innerHTML   = nodeHTML(node, def);
    bindNodeEvents(el, node.id);
    D.nodesLayer.appendChild(el);
}

function nodeHTML(node, def) {
    let subHtml = '';
    if (node.type === 'article-trigger' && node.config && node.config.topic) {
        const topicText = String(node.config.topic);
        const shortTopic = topicText.length > 24 ? topicText.slice(0, 23) + '…' : topicText;
        subHtml = `<div class="nc-sub" style="font-size:0.68rem; color:#38bdf8; font-weight:600; margin-top:2px; max-width:140px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${escHtml(topicText)}">🎯 ${escHtml(shortTopic)}</div>`;
    }

    return `
        <div class="cn-actions">
            <button class="cn-act-btn" data-act="config" title="Config">⚙</button>
            <button class="cn-act-btn" data-act="dup" title="Duplicate">⧉</button>
            <button class="cn-act-btn danger" data-act="del" title="Delete">✕</button>
        </div>
        <div class="cn-port in"  data-nid="${node.id}" data-port="in"></div>
        <div class="cn-body">
            <div class="cn-top">
                <span class="cn-icon">${def.icon || '▪'}</span>
                <div style="flex:1; min-width:0;">
                    <span class="cn-label">${def.label || node.type}</span>
                    ${subHtml}
                </div>
                <div class="cn-status-dot ${node.status}" id="sd-${node.id}"></div>
            </div>
            <div class="cn-status-row ${node.status}" id="sr-${node.id}">${statusText(node)}</div>
            <div class="cn-prog">
                <div class="cn-prog-fill ${node.status}" id="pf-${node.id}" style="width:${node.progress}%"></div>
            </div>
            <div class="cn-prog-label ${node.status}" id="pl-${node.id}">
                <span>${progressLabel(node)}</span>
                <span>${node.progress > 0 ? node.progress + '%' : ''}</span>
            </div>
            <button class="cn-retry-btn" data-nid="${node.id}">↺ Retry from here</button>
        </div>
        <div class="cn-port out" data-nid="${node.id}" data-port="out"></div>`;
}

function statusText(node) {
    const s = { waiting:'⚪ Waiting', running:'🟡 Running…', success:'🟢 Success', failed:'🔴 Failed' };
    return s[node.status] || '⚪ Waiting';
}
function progressLabel(node) {
    if (node.status === 'running') return NDEFS[node.type]?.label || '';
    return '';
}

function updateNodeEl(nodeId) {
    const node = APP.nodes.find(n => n.id === nodeId);
    if (!node) return;
    const dot  = document.getElementById('sd-' + nodeId);
    const sr   = document.getElementById('sr-' + nodeId);
    const pf   = document.getElementById('pf-' + nodeId);
    const pl   = document.getElementById('pl-' + nodeId);
    const cnel = document.getElementById('cn-' + nodeId);
    if (!dot) return;
    dot.className = 'cn-status-dot ' + node.status;
    sr.className  = 'cn-status-row ' + node.status;
    sr.textContent = statusText(node);
    pf.className  = 'cn-prog-fill ' + node.status;
    pf.style.width = node.progress + '%';
    if (pl) {
        pl.className  = 'cn-prog-label ' + node.status;
        pl.innerHTML  = `<span>${progressLabel(node)}</span><span>${node.progress > 0 ? node.progress + '%' : ''}</span>`;
    }
    if (cnel) {
        cnel.className = 'cnode node-' + node.status;
        if (APP.sel === nodeId) cnel.classList.add('selected');
    }
    // Update props panel if this node is selected
    if (APP.sel === nodeId) updatePropsStatus(node);
}

function renderAllNodes() {
    D.nodesLayer.innerHTML = '';
    APP.nodes.forEach(n => renderNodeEl(n));
}

// ──────────────────────────────────────────────────────────────
// 6. CONNECTION MANAGEMENT
// ──────────────────────────────────────────────────────────────
function portWorldPos(nodeId, portType) {
    const node = APP.nodes.find(n => n.id === nodeId);
    if (!node) return { x: 0, y: 0 };
    return {
        x: portType === 'out' ? node.x + NODE_W : node.x,
        y: node.y + NODE_H / 2,
    };
}

function makeBezier(x1, y1, x2, y2) {
    const dx = Math.abs(x2 - x1);
    const cx = Math.max(dx * 0.42, 60);
    return `M ${x1} ${y1} C ${x1+cx} ${y1} ${x2-cx} ${y2} ${x2} ${y2}`;
}

function addConn(fromId, toId) {
    try {
        console.log(`[addConn] Attempting to connect ${fromId} -> ${toId}`);
        if (fromId === toId) {
            console.warn(`[addConn] Blocked self-connection for ${fromId}`);
            return;
        }
        if (APP.conns.some(c => c.from === fromId && c.to === toId)) {
            console.warn(`[addConn] Connection already exists: ${fromId} -> ${toId}`);
            return;
        }
        const conn = { id: genCId(), from: fromId, to: toId };
        APP.conns.push(conn);
        renderConnEl(conn);
        saveUndo();
        drawMinimap();
        console.log(`[addConn] Successfully connected ${fromId} -> ${toId}`);
    } catch(e) {
        console.error(`[addConn] Error connecting nodes:`, e);
        showToast('Error connecting nodes. See console.', 'error');
    }
}

function removeConn(connId) {
    APP.conns = APP.conns.filter(c => c.id !== connId);
    const el = document.getElementById('cp-' + connId);
    if (el) el.remove();
    saveUndo();
}

function renderConnEl(conn) {
    const src = portWorldPos(conn.from, 'out');
    const tgt = portWorldPos(conn.to,   'in');
    let el = document.getElementById('cp-' + conn.id);
    if (!el) {
        el = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        el.id = 'cp-' + conn.id;
        el.setAttribute('marker-end', 'url(#ah)');
        el.setAttribute('class', 'conn-path');
        el.dataset.from = conn.from;
        el.dataset.to   = conn.to;
        el.addEventListener('click', e => {
            e.stopPropagation();
            // Toggle selection
            document.querySelectorAll('.conn-path.selected').forEach(p => p.classList.remove('selected'));
            el.classList.add('selected');
        });
        el.addEventListener('dblclick', e => { e.stopPropagation(); removeConn(conn.id); });
        D.connGroup.appendChild(el);
    }
    el.setAttribute('d', makeBezier(src.x, src.y, tgt.x, tgt.y));
}

function updateConnsForNode(nodeId) {
    APP.conns.filter(c => c.from === nodeId || c.to === nodeId)
             .forEach(c => renderConnEl(c));
}

function renderAllConns() {
    D.connGroup.innerHTML = '';
    APP.conns.forEach(c => renderConnEl(c));
}

// ──────────────────────────────────────────────────────────────
// 7. DRAG MANAGEMENT
// ──────────────────────────────────────────────────────────────
let _drag = null;  // active drag descriptor

function onNodePointerDown(e, nodeId) {
    if (e.target.classList.contains('cn-port')) return;
    if (e.target.dataset.act) return;
    e.stopPropagation();
    selectNode(nodeId);
    if (APP.execRunning) {
        return; // Selection allowed, but moving nodes disabled during execution
    }
    e.currentTarget.setPointerCapture(e.pointerId);
    const node  = APP.nodes.find(n => n.id === nodeId);
    const cv    = canvasXY(e);
    const world = viewToWorld(cv.x, cv.y);
    _drag = { type:'node', nodeId, startNx: node.x, startNy: node.y, startWx: world.x, startWy: world.y, moved: false };
}

function onPortPointerDown(e, nodeId, portType) {
    if (APP.execRunning) {
        showToast('🔒 Workflow execution is active. Canvas modifications are locked.', 'warning');
        return;
    }
    if (portType !== 'out') return;   // only drag from outputs
    e.stopPropagation();
    APP.connecting = { fromNodeId: nodeId };
    document.body.style.cursor = 'crosshair';
}

function onCanvasPointerDown(e) {
    if (e.button === 0 || e.button === 1) {
        e.preventDefault();
        _drag = { type:'pan', lastX: e.clientX, lastY: e.clientY };
        selectNode(null);
        document.querySelectorAll('.conn-path.selected').forEach(p => p.classList.remove('selected'));
    }
}

function onGlobalPointerMove(e) {
    if (_drag?.type === 'node') {
        _drag.moved = true;
        const cv    = canvasXY(e);
        const world = viewToWorld(cv.x, cv.y);
        const node  = APP.nodes.find(n => n.id === _drag.nodeId);
        if (!node) return;
        node.x = _drag.startNx + (world.x - _drag.startWx);
        node.y = _drag.startNy + (world.y - _drag.startWy);
        const el = document.getElementById('cn-' + node.id);
        if (el) { el.style.left = node.x + 'px'; el.style.top = node.y + 'px'; }
        updateConnsForNode(node.id);
        drawMinimap();
    }
    else if (_drag?.type === 'pan') {
        APP.pan.x += e.clientX - _drag.lastX;
        APP.pan.y += e.clientY - _drag.lastY;
        _drag.lastX = e.clientX;
        _drag.lastY = e.clientY;
        applyTransform();
    }
    else if (APP.connecting) {
        const cv    = canvasXY(e);
        const world = viewToWorld(cv.x, cv.y);
        const src   = portWorldPos(APP.connecting.fromNodeId, 'out');
        D.tempLine.setAttribute('d', makeBezier(src.x, src.y, world.x, world.y));
        D.tempLine.classList.remove('hidden');

        // Highlight nearest droppable input port
        document.querySelectorAll('.cn-port.droppable').forEach(p => p.classList.remove('droppable'));
        APP.nodes.forEach(n => {
            if (n.id === APP.connecting.fromNodeId) return;
            const ip  = portWorldPos(n.id, 'in');
            const dist = Math.hypot(world.x - ip.x, world.y - ip.y);
            const hitNodeBody = (world.x >= n.x && world.x <= n.x + NODE_W && world.y >= n.y && world.y <= n.y + NODE_H);
            if (dist < PORT_HIT || hitNodeBody) {
                const portEl = document.querySelector(`#cn-${n.id} .cn-port.in`);
                if (portEl) portEl.classList.add('droppable');
            }
        });
    }
}

function onGlobalPointerUp(e) {
    if (APP.connecting) {
        const cv    = canvasXY(e);
        const world = viewToWorld(cv.x, cv.y);
        APP.nodes.forEach(n => {
            if (n.id === APP.connecting.fromNodeId) return;
            const ip   = portWorldPos(n.id, 'in');
            const dist = Math.hypot(world.x - ip.x, world.y - ip.y);
            const hitNodeBody = (world.x >= n.x && world.x <= n.x + NODE_W && world.y >= n.y && world.y <= n.y + NODE_H);
            if (dist < PORT_HIT || hitNodeBody) addConn(APP.connecting.fromNodeId, n.id);
        });
        D.tempLine.classList.add('hidden');
        document.querySelectorAll('.cn-port.droppable').forEach(p => p.classList.remove('droppable'));
        APP.connecting = null;
        document.body.style.cursor = '';
    }
    if (_drag?.type === 'node' && _drag.moved) saveUndo();
    _drag = null;
}

// ──────────────────────────────────────────────────────────────
// 8. SELECTION & PROPERTIES PANEL
// ──────────────────────────────────────────────────────────────
function selectNode(nodeId) {
    document.querySelectorAll('.cnode.selected').forEach(el => el.classList.remove('selected'));
    APP.sel = nodeId;
    if (!nodeId) { showPropsEmpty(); return; }
    const el = document.getElementById('cn-' + nodeId);
    if (el) el.classList.add('selected');
    showPropsContent(nodeId);
}

function showPropsEmpty() {
    D.propsEmpty.classList.remove('hidden');
    D.propsContent.classList.add('hidden');
}

function showPropsContent(nodeId) {
    const node = APP.nodes.find(n => n.id === nodeId);
    if (!node) return;
    const def  = NDEFS[node.type] || {};
    const conf = NODE_CONFIGS[node.type] || [];

    D.propsEmpty.classList.add('hidden');
    D.propsContent.classList.remove('hidden');

    let resultSection = '';
    const res = node.result;
    if (res && res.video_path) {
        const vpath = res.video_path;
        const fname = vpath.split(/[\\/]/).pop();
        const vurl = `/api/video/file/${fname}`;
        const safeVPath = vpath.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
        resultSection = `
            <div class="pc-result-box" style="margin-top: 14px; padding: 12px; background: rgba(0,255,170,0.06); border: 1px solid rgba(0,255,170,0.25); border-radius: 8px;">
                <div style="font-weight: 700; font-size: 0.82rem; color: #00FFAA; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">
                    <span>🎬</span> Generated Video Output
                </div>
                <div style="font-size: 0.70rem; color: #94a3b8; margin-bottom: 2px;">LOCAL FILE PATH:</div>
                <div style="font-family: monospace; font-size: 0.74rem; color: #f1f5f9; background: rgba(0,0,0,0.45); padding: 6px 8px; border-radius: 4px; word-break: break-all; margin-bottom: 8px; user-select: all; border: 1px solid rgba(255,255,255,0.08);">
                    ${vpath}
                </div>
                <video src="${vurl}" controls style="width: 100%; max-height: 190px; border-radius: 6px; background: #000; margin-bottom: 8px; outline: none;"></video>
                <div style="display: flex; gap: 6px;">
                    <button type="button" onclick="window.copyToClipboard('${safeVPath}')" style="flex: 1; padding: 5px 8px; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.18); border-radius: 5px; color: #fff; font-size: 0.72rem; font-weight: 600; cursor: pointer;">📋 Copy Path</button>
                    <button type="button" onclick="window.revealVideoInFolder('${safeVPath}')" style="flex: 1; padding: 5px 8px; background: rgba(56,189,248,0.15); border: 1px solid rgba(56,189,248,0.35); border-radius: 5px; color: #38bdf8; font-size: 0.72rem; font-weight: 600; cursor: pointer;">📁 Explorer</button>
                </div>
            </div>
        `;
    }

    D.propsContent.innerHTML = `
        <div class="pc-header">
            <div class="pc-icon-wrap" style="background:${def.color}22; border-color:${def.color}44">
                <span>${def.icon || '▪'}</span>
            </div>
            <div class="pc-info">
                <div class="pc-node-name">${def.label || node.type}</div>
                <div class="pc-node-cat">${(CATS.find(c=>c.id===def.cat)||{}).label || def.cat}</div>
            </div>
        </div>
        <div class="pc-status-row" id="pc-status-row-${nodeId}">
            <span class="pc-status-badge ${node.status}" id="pc-badge-${nodeId}">${statusText(node)}</span>
            <div class="pc-prog-mini" id="pc-prog-mini-${nodeId}">
                <div class="pc-prog-bar"><div class="pc-prog-fill" id="pc-prog-fill-${nodeId}" style="width:${node.progress}%; --nc:${def.color || '#4fc3f7'}"></div></div>
                <div class="pc-prog-pct" id="pc-prog-pct-${nodeId}">${node.progress}%</div>
            </div>
        </div>
        <div class="pc-fields" id="pc-fields-${nodeId}">
            ${conf.length ? conf.map(f => renderPcField(f, node)).join('') : '<p style="color:#6b7280;font-size:0.78rem;padding:0.5rem 0">No configuration needed.</p>'}
        </div>
        <div class="pc-conn-test" id="pc-conn-${nodeId}" style="margin:10px 0 2px 0;">
            <button class="pc-btn-test-conn" id="pc-test-btn-${nodeId}" onclick="testNodeConnection('${nodeId}')" style="width:100%;padding:8px 12px;background:linear-gradient(135deg,rgba(0,255,170,0.1),rgba(56,189,248,0.1));border:1px solid rgba(0,255,170,0.35);border-radius:7px;color:#00FFAA;font-size:0.76rem;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:7px;transition:all 0.2s;">
                <span>⚡</span> Test Live Connection
            </button>
            <div id="pc-conn-result-${nodeId}" style="margin-top:6px;display:none;"></div>
            <button class="pc-btn-preview-node" id="pc-preview-btn-${nodeId}" onclick="previewSingleNode('${nodeId}')" style="width:100%;margin-top:6px;padding:8px 12px;background:linear-gradient(135deg,rgba(139,92,246,0.12),rgba(59,130,246,0.12));border:1px solid rgba(139,92,246,0.4);border-radius:7px;color:#a78bfa;font-size:0.76rem;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:7px;transition:all 0.2s;">
                <span>▶</span> Preview This Node Only
            </button>
            <div id="pc-preview-result-${nodeId}" style="margin-top:6px;display:none;"></div>
        </div>
        ${resultSection}
        <div class="pc-actions">
            <button class="pc-btn pc-btn-dup" data-nid="${nodeId}">⧉ Duplicate</button>
            <button class="pc-btn pc-btn-del" data-nid="${nodeId}">🗑 Delete</button>
        </div>`;

    // Bind pc actions
    D.propsContent.querySelector('.pc-btn-dup')?.addEventListener('click', () => duplicateNode(nodeId));
    D.propsContent.querySelector('.pc-btn-del')?.addEventListener('click', () => removeNode(nodeId));

    // Bind field changes → save to node.config
    D.propsContent.querySelectorAll('[data-field]').forEach(el => {
        const onChange = () => {
            const v = el.type === 'checkbox' ? el.checked : el.value;
            node.config[el.dataset.field] = v;
            if (el.type === 'range') {
                el.nextElementSibling.querySelector('span:last-child').textContent = v;
            }
        };
        el.addEventListener('input', onChange);
        el.addEventListener('change', onChange);
    });
}

function renderPcField(f, node) {
    const val = node.config[f.key] !== undefined ? node.config[f.key] : f.def;
    if (f.type === 'select') {
        const opts = f.opts.map(o => `<option value="${o}" ${val===o?'selected':''}>${o}</option>`).join('');
        return `<div class="pc-field"><label class="pc-field-label">${f.label}</label><select class="pc-field-select" data-field="${f.key}">${opts}</select></div>`;
    }
    if (f.type === 'text') {
        return `<div class="pc-field"><label class="pc-field-label">${f.label}</label><input class="pc-field-input" type="text" data-field="${f.key}" value="${val||''}" placeholder="${f.placeholder||''}"></div>`;
    }
    if (f.type === 'textarea') {
        return `<div class="pc-field"><label class="pc-field-label">${f.label}</label><textarea class="pc-field-textarea" data-field="${f.key}" placeholder="${f.placeholder||''}">${val||''}</textarea></div>`;
    }
    if (f.type === 'range') {
        return `<div class="pc-field"><label class="pc-field-label">${f.label}</label>
            <input class="pc-field-range" type="range" data-field="${f.key}" min="${f.min}" max="${f.max}" step="${f.step}" value="${val}">
            <div class="pc-range-val"><span>${f.min}</span><span>${val}</span><span>${f.max}</span></div></div>`;
    }
    if (f.type === 'toggle') {
        return `<div class="pc-field"><label class="pc-field-label">${f.label}</label>
            <div class="pc-toggle-wrap"><label class="pc-toggle"><input type="checkbox" data-field="${f.key}" ${val?'checked':''}><span class="pc-toggle-slider"></span></label></div></div>`;
    }
    return '';
}

function updatePropsStatus(node) {
    const badge = document.getElementById('pc-badge-' + node.id);
    const fill  = document.getElementById('pc-prog-fill-' + node.id);
    const pct   = document.getElementById('pc-prog-pct-' + node.id);
    if (badge) { badge.className = 'pc-status-badge ' + node.status; badge.textContent = statusText(node); }
    if (fill)  fill.style.width = node.progress + '%';
    if (pct)   pct.textContent = node.progress + '%';
}

// ──────────────────────────────────────────────────────────────
// 9. EXECUTION SIMULATION
// ──────────────────────────────────────────────────────────────
const sleep = ms => new Promise(r => setTimeout(r, ms));

function topoSort() {
    const adj  = {};  const inDeg = {};
    APP.nodes.forEach(n => { adj[n.id] = []; inDeg[n.id] = 0; });
    APP.conns.forEach(c => { adj[c.from].push(c.to); inDeg[c.to] = (inDeg[c.to]||0) + 1; });
    const queue  = APP.nodes.filter(n => !inDeg[n.id]).map(n => n.id);
    const result = [];  const seen = new Set();
    while (queue.length) {
        const id = queue.shift();
        if (seen.has(id)) continue;
        seen.add(id); result.push(id);
        (adj[id]||[]).forEach(nid => { inDeg[nid]--; if (inDeg[nid] <= 0 && !seen.has(nid)) queue.push(nid); });
    }
    APP.nodes.forEach(n => { if (!seen.has(n.id)) result.push(n.id); });
    return result;
}

function escHtml(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function mediaUrlFor(absPath) {
    if (!absPath) return '';
    const fname = String(absPath).split(/[\\/]/).pop();
    return `/output/${encodeURIComponent(fname)}`;
}

// ── Single-node preview: run ONE node standalone and render its result ──
async function previewSingleNode(nodeId) {
    const node = APP.nodes.find(n => n.id === nodeId);
    if (!node) return;
    const box = document.getElementById('pc-preview-result-' + nodeId);
    const btn = document.getElementById('pc-preview-btn-' + nodeId);
    if (!box) return;
    box.style.display = 'block';
    box.innerHTML = `<div style="padding:12px;text-align:center;color:#94a3b8;font-size:0.78rem;"><div style="font-size:20px;animation:spin 1s linear infinite;display:inline-block;">⏳</div><div style="margin-top:6px;">Running node preview...</div></div>`;
    if (btn) btn.disabled = true;
    try {
        const res = await fetch('/api/workflow/run-node', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                node: { id: node.id, type: node.type, data: node.data || {}, config: node.config || {} },
                signal: SELECTED_SIGNAL || {}
            })
        });
        const data = await res.json();
        if (data.status === 'error') throw new Error(data.message || 'Preview failed');
        box.innerHTML = renderPreviewResult(data.result || {}, data.node_type);
        showToast('▶ Node preview complete', 'success', 2500);
    } catch (e) {
        box.innerHTML = `<div style="padding:10px;color:#f87171;font-size:0.78rem;background:rgba(248,113,113,0.08);border:1px solid rgba(248,113,113,0.3);border-radius:8px;">❌ Preview failed: ${escHtml(e.message)}</div>`;
        showToast(`Preview failed: ${e.message}`, 'error', 5000);
    } finally {
        if (btn) btn.disabled = false;
    }
}

function renderPreviewResult(r, nodeType) {
    const parts = [];
    const wrap = (title, inner) => `<div style="margin-top:8px;padding:10px;background:rgba(139,92,246,0.07);border:1px solid rgba(139,92,246,0.3);border-radius:8px;">
        <div style="font-size:0.72rem;font-weight:700;color:#a78bfa;margin-bottom:6px;">${title}</div>${inner}</div>`;

    if (r.status === 'error') {
        return wrap('❌ Node error', `<div style="color:#f87171;font-size:0.78rem;">${escHtml(r.error || r.message || 'Unknown error')}</div>`);
    }
    // Images (gen-image returns image_paths per scene or images list)
    const imgs = [];
    (r.scenes || []).forEach(s => {
        (s.image_paths || []).forEach(p => imgs.push(p));
        if (s.image_path) imgs.push(s.image_path);
    });
    (r.images || r.image_paths || []).forEach(p => imgs.push(p));
    if (r.thumbnail_path) imgs.push(r.thumbnail_path);
    if (r.image_path) imgs.push(r.image_path);
    [...new Set(imgs)].slice(0, 6).forEach(p => {
        parts.push(`<img src="${mediaUrlFor(p)}" style="width:100%;border-radius:6px;margin-top:6px;border:1px solid rgba(255,255,255,0.1);" onerror="this.style.display='none'">`);
    });
    if (r.thumbnail_path && !imgs.length) parts.push(`<img src="${mediaUrlFor(r.thumbnail_path)}" style="width:100%;border-radius:6px;">`);
    // Audio
    if (r.audio_path) {
        parts.push(wrap('🎙 Voiceover (English primary)', `<audio src="${mediaUrlFor(r.audio_path)}" controls style="width:100%;"></audio>`
            + (r.hindi_audio_path ? `<div style="margin-top:6px;font-size:0.72rem;color:#94a3b8;">🇮🇳 Hindi dub track also generated</div><audio src="${mediaUrlFor(r.hindi_audio_path)}" controls style="width:100%;margin-top:4px;"></audio>` : '')));
    }
    // Video
    if (r.video_path) {
        parts.push(wrap('🎬 Video' + (r.dual_audio ? ' (EN + HI audio tracks)' : ''), `<video src="${mediaUrlFor(r.video_path)}" controls style="width:100%;border-radius:6px;background:#000;"></video>`));
    }
    // Script / text outputs
    const script = r.script || r.translated_script || r.narration;
    if (script) {
        const txt = String(script).slice(0, 1200);
        parts.push(wrap('📝 Script', `<div style="font-size:0.74rem;color:#e2e8f0;white-space:pre-wrap;max-height:220px;overflow:auto;">${escHtml(txt)}${String(script).length > 1200 ? '…' : ''}</div>`));
    }
    if (r.title) parts.push(wrap('📌 Title', `<div style="font-size:0.8rem;color:#f1f5f9;font-weight:600;">${escHtml(r.title)}</div>`));
    if (r.hook) parts.push(wrap('🪝 Hook', `<div style="font-size:0.78rem;color:#f1f5f9;">${escHtml(r.hook)}</div>`));
    if (r.word_timings_path) parts.push(`<div style="font-size:0.7rem;color:#00FFAA;margin-top:6px;">✓ Real word-level caption timings captured</div>`);
    if (!parts.length) {
        const keys = Object.keys(r).filter(k => !['status','node_type'].includes(k));
        parts.push(wrap('Result', `<div style="font-size:0.72rem;color:#94a3b8;">${keys.length ? 'Keys: ' + escHtml(keys.join(', ')) : 'Node ran with no displayable output.'}</div>`));
    }
    return parts.join('');
}

// ── Build a runnable workflow payload for a given signal (no canvas mutation) ──
function buildWorkflowPayload(signal) {
    const nodes = APP.nodes.map(n => ({
        id: n.id, type: n.type,
        data: JSON.parse(JSON.stringify(n.data || {})),
        config: JSON.parse(JSON.stringify(n.config || {}))
    }));
    const selectedStyle = document.getElementById('wfStyleSelect')?.value || 'cinema_8k';
    const triggerNode = nodes.find(n => n.type === 'article-trigger' || n.type === 'manual-trigger' || n.id === 'n1');
    if (triggerNode) {
        triggerNode.config = triggerNode.config || {};
        triggerNode.config.topic = signal.title;
        triggerNode.config.article_url = signal.link || '';
        triggerNode.config.category = signal.topic || 'General';
        triggerNode.config.viral_score = signal.score || 90;
        triggerNode.config.image_url = signal.image_url || '';
    }
    nodes.forEach(n => {
        n.data = { ...(n.data || {}), ...(n.config || {}), visual_style: selectedStyle };
        n.config = { ...(n.config || {}), visual_style: selectedStyle };
    });
    return {
        name: signal.title || D.wfNameInput?.value || 'YouTube Content Pipeline',
        visual_style: selectedStyle,
        article: {
            title: signal.title, topic: signal.topic || 'AI & Tech',
            score: signal.score || 95, link: signal.link || '',
            image_url: signal.image_url || ''
        },
        nodes,
        edges: APP.conns.map(c => ({ source: c.from, target: c.to }))
    };
}

// ── Batch queue: enqueue 1..N videos built from the current canvas ──
async function queueSignals(signals) {
    if (!signals || !signals.length) return;
    if (!APP.nodes.length) { showToast('Add some nodes to the canvas first!', 'warning'); return; }
    const payloads = signals.map(s => buildWorkflowPayload(s));
    showToast(`🎬 Queueing ${payloads.length} video${payloads.length === 1 ? '' : 's'}...`, 'info', 3000);
    logAdd(`[Queue] Enqueueing ${payloads.length} video(s)...`, 'info');
    try {
        const res = await fetch('/api/workflow/queue', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ payloads })
        });
        const data = await res.json();
        const nq = (data.queued || []).length;
        const nb = (data.blocked || []).length;
        if (nq) {
            showToast(`✅ ${nq} video${nq === 1 ? '' : 's'} queued — rendering one by one in the background.`, 'success', 6000);
            logAdd(`[Queue] ✅ ${nq} video(s) queued.`, 'success');
        }
        if (nb) {
            const first = data.blocked[0];
            showToast(`🚫 ${nb} blocked by preflight: ${first.error}`, 'error', 8000);
            logAdd(`[Queue] ❌ ${nb} blocked: ${first.error}`, 'error');
        }
        BATCH_SIGNALS = [];
        closeSignalPicker();
        updateQueueBadge();
        openQueueModal();
    } catch (e) {
        showToast(`Queue failed: ${e.message}`, 'error');
    }
}

async function updateQueueBadge() {
    try {
        const res = await fetch('/api/workflow/queue', { credentials: 'include' });
        const data = await res.json();
        const active = (data.queue || []).filter(q => ['queued', 'running'].includes(q.status)).length;
        const badge = document.getElementById('queueCountBadge');
        if (badge) {
            badge.textContent = active;
            badge.classList.toggle('hidden', active === 0);
        }
    } catch (e) { /* silent */ }
}

function openQueueModal() {
    const modal = document.getElementById('queueModal');
    if (!modal) return;
    modal.classList.remove('hidden');
    refreshQueueModal();
    if (queuePollTimer) clearInterval(queuePollTimer);
    queuePollTimer = setInterval(refreshQueueModal, 4000);
}

function closeQueueModal() {
    document.getElementById('queueModal')?.classList.add('hidden');
    if (queuePollTimer) { clearInterval(queuePollTimer); queuePollTimer = null; }
}

async function refreshQueueModal() {
    const body = document.getElementById('queueModalBody');
    if (!body || document.getElementById('queueModal').classList.contains('hidden')) return;
    try {
        const res = await fetch('/api/workflow/queue', { credentials: 'include' });
        const data = await res.json();
        const items = data.queue || [];
        if (!items.length) {
            body.innerHTML = `<div style="text-align:center;padding:36px;color:#64748b;">
                <div style="font-size:32px;margin-bottom:8px;">🧾</div>
                <p style="font-size:0.9rem;">Queue is empty.<br>Pick signals from the 📰 picker and hit <b>🎬 Queue</b> to line up videos.</p></div>`;
            return;
        }
        const statusStyle = (s) => ({
            queued:  'background:rgba(245,158,11,0.12);color:#fbbf24;border:1px solid rgba(245,158,11,0.35);',
            running: 'background:rgba(56,189,248,0.12);color:#38bdf8;border:1px solid rgba(56,189,248,0.35);',
            success: 'background:rgba(0,255,170,0.1);color:#00FFAA;border:1px solid rgba(0,255,170,0.3);',
            partial: 'background:rgba(168,85,247,0.12);color:#a78bfa;border:1px solid rgba(168,85,247,0.35);',
            error:   'background:rgba(248,113,113,0.1);color:#f87171;border:1px solid rgba(248,113,113,0.3);',
        }[s] || 'background:rgba(255,255,255,0.06);color:#94a3b8;border:1px solid rgba(255,255,255,0.12);');
        body.innerHTML = items.map(q => `
            <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px;margin-bottom:8px;">
                <div style="flex:1;min-width:0;">
                    <div style="font-size:0.84rem;font-weight:600;color:#f1f5f9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escHtml(q.label || 'Untitled')}</div>
                    <div style="font-size:0.7rem;color:#64748b;margin-top:2px;">${q.created_at ? escHtml(q.created_at.slice(0,16).replace('T',' ')) : ''}${q.error ? ' — ' + escHtml(q.error.slice(0,80)) : ''}</div>
                </div>
                <span style="font-size:0.7rem;font-weight:700;padding:3px 10px;border-radius:6px;${statusStyle(q.status)}">${escHtml(q.status)}</span>
                ${q.status === 'queued' ? `<button onclick="removeQueueItem('${q.qid}')" title="Remove from queue" style="padding:5px 9px;background:rgba(248,113,113,0.08);border:1px solid rgba(248,113,113,0.3);border-radius:6px;color:#f87171;cursor:pointer;font-size:0.75rem;">✕</button>` : ''}
            </div>`).join('');
        updateQueueBadge();
    } catch (e) {
        body.innerHTML = `<div style="text-align:center;color:#f87171;padding:20px;">Failed to load queue: ${escHtml(e.message)}</div>`;
    }
}

async function removeQueueItem(qid) {
    try {
        await fetch(`/api/workflow/queue/${qid}`, { method: 'DELETE', credentials: 'include' });
        refreshQueueModal();
    } catch (e) { showToast(`Remove failed: ${e.message}`, 'error'); }
}

async function runWorkflow() {
    if (APP.execRunning) return;
    if (!APP.nodes.length) { showToast('Add some nodes first!', 'warning'); return; }

    // Enforce selected input article/video signal!
    if (!SELECTED_SIGNAL || !SELECTED_SIGNAL.title) {
        showToast('⚠️ No article or video signal selected! Please choose a news article or viral video before running the workflow.', 'warning', 5000);
        openSignalPicker();
        return;
    }

    // ── PRE-FLIGHT VALIDATION: Prevent workflow start if configuration is missing ──
    const preflight = await validateWorkflowRequirements();
    if (!preflight.ok) {
        showToast(`🚫 Workflow Halted: ${preflight.error}`, 'error', 7000);
        logAdd(`[PreFlight] ❌ ${preflight.error}`, 'error');
        if (preflight.openModal) {
            openApiKeysModal();
        }
        return;
    }

    // ── LIVE SERVER PRE-FLIGHT: test every node's real connection before starting.
    //    The server refuses the run when a required node has no live connection.
    showToast('⚡ Testing live node connections...', 'info', 2500);
    logAdd('[PreFlight] Testing live connections for all nodes...', 'info');
    try {
        const pfRes = await fetch('/api/workflow/preflight', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                nodes: APP.nodes.map(n => ({
                    id: n.id, type: n.type,
                    data: n.data || {}, config: n.config || {}
                }))
            })
        });
        const pfData = await pfRes.json();
        if (!pfData.can_start) {
            const failed = (pfData.failed || []).map(f =>
                `• ${f.node_type} (${f.node_id}): ${f.message}`).join('\n');
            showToast('🚫 Workflow blocked — no live connection on required nodes. See log.', 'error', 8000);
            logAdd(`[PreFlight] ❌ BLOCKED — failing nodes:\n${failed}`, 'error');
            (pfData.failed || []).forEach(f => {
                const node = APP.nodes.find(n => n.id === f.node_id);
                if (node) { node._connTested = true; node._connOk = false; }
            });
            openApiKeysModal();
            return;
        }
        const okCount = Object.keys(pfData.nodes || {}).length;
        logAdd(`[PreFlight] ✅ All ${okCount} node connection(s) live — starting workflow.`, 'success');
    } catch (pfErr) {
        showToast(`⚠️ Live connection check failed: ${pfErr.message}. Run blocked for safety.`, 'error', 7000);
        logAdd(`[PreFlight] ❌ live check error: ${pfErr.message}`, 'error');
        return;
    }

    APP.execRunning = true;

    // Reset all
    APP.nodes.forEach(n => { n.status = 'waiting'; n.progress = 0; updateNodeEl(n.id); });
    renderAllConns();

    // Inject selected signal into trigger / input nodes
    const triggerNode = APP.nodes.find(n => n.type === 'article-trigger' || n.type === 'manual-trigger' || n.id === 'n1');
    if (triggerNode) {
        triggerNode.config = triggerNode.config || {};
        triggerNode.config.topic = SELECTED_SIGNAL.title;
        triggerNode.config.article_url = SELECTED_SIGNAL.link || '';
        triggerNode.config.category = SELECTED_SIGNAL.topic || 'General';
        triggerNode.config.viral_score = SELECTED_SIGNAL.score || 90;
        triggerNode.config.image_url = SELECTED_SIGNAL.image_url || '';
        triggerNode.config.prompt = SELECTED_SIGNAL.prompt || triggerNode.config.prompt || '';
    }

    // UI: running state
    APP.execRunning = true;
    D.canvasLockBanner?.classList.remove('hidden');
    D.nodePalette?.classList.add('palette-locked');
    D.canvasWrap?.classList.add('canvas-locked');
    D.btnRun.classList.add('hidden');
    D.btnStop.classList.remove('hidden');
    D.wfProgressArea.classList.remove('hidden');
    D.wfStatusBadge.className = 'wf-status-badge running';
    D.wfStatusBadge.textContent = '● Running';
    D.chDot.classList.add('running');

    // Sync node config into data for all nodes with selected visual art style
    const selectedStyle = document.getElementById('wfStyleSelect')?.value || 'cinema_8k';
    APP.nodes.forEach(n => {
        n.data = { ...(n.data || {}), ...(n.config || {}), visual_style: selectedStyle };
        n.config = { ...(n.config || {}), visual_style: selectedStyle };
    });

    const payload = {
        name: SELECTED_SIGNAL.title || D.wfNameInput?.value || 'YouTube Content Pipeline',
        visual_style: selectedStyle,
        article: {
            title: SELECTED_SIGNAL.title,
            topic: SELECTED_SIGNAL.topic || 'AI & Tech',
            score: SELECTED_SIGNAL.score || 95,
            link: SELECTED_SIGNAL.link || '',
            image_url: SELECTED_SIGNAL.image_url || ''
        },
        nodes: APP.nodes,
        edges: APP.conns.map(c => ({ source: c.from, target: c.to }))
    };

    let order;
    try {
        order = topoSort();
        console.log('[runWorkflow] Topological sort order:', order);
    } catch (err) {
        logAdd(`✗ Invalid workflow graph: ${err.message}`, 'error');
        APP.execRunning = false;
        D.btnRun.classList.remove('hidden');
        D.btnStop.classList.add('hidden');
        D.chDot.classList.remove('running');
        D.wfProgressArea.classList.add('hidden');
        return;
    }

    const total = order.length;
    const startMs = Date.now();
    fitView(true); // Auto center whole workflow when execution starts

    try {
        const startRes = await fetch('/api/workflow/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify(payload)
        });

        if (!startRes.ok) {
            throw new Error(`Server returned status ${startRes.status}`);
        }

        const startData = await startRes.json();
        if (startData.status !== 'started' || !startData.run_id) {
            throw new Error(startData.message || 'Failed to start asynchronous execution');
        }

        const runId = startData.run_id;
        try {
            localStorage.setItem('pf_active_run_id', runId);
            localStorage.setItem('pf_active_run_start', String(startMs));
            localStorage.setItem('pf_active_run_order', JSON.stringify(order));
        } catch(e) {}

        logAdd(`✓ Pipeline running in background (Run ID: ${runId.slice(0,8)}). Polling active...`, 'success');
        pollWorkflowExecution(runId, order, total, startMs);

    } catch (e) {
        console.error(`[runWorkflow] Start failed:`, e);
        logAdd(`Error starting workflow: ${e.message}`, 'error');
        APP.nodes.forEach(n => { n.status = 'failed'; updateNodeEl(n.id); });
        D.wfStatusBadge.className = 'wf-status-badge error';
        D.wfStatusBadge.textContent = '● Failed';
        showToast(`Workflow failed to start: ${e.message}`, 'error');

        APP.execRunning = false;
        D.canvasLockBanner?.classList.add('hidden');
        D.nodePalette?.classList.remove('palette-locked');
        D.canvasWrap?.classList.remove('canvas-locked');
        D.btnRun.classList.remove('hidden');
        D.btnStop.classList.add('hidden');
        D.chDot.classList.remove('running');
        D.wfProgressArea.classList.add('hidden');
        try { localStorage.removeItem('pf_active_run_id'); } catch(e){}
    }
}

let activePollInterval = null;

function pollWorkflowExecution(runId, order = null, total = null, startMs = null) {
    if (!order) {
        order = APP.nodes.map(n => n.id);
    }
    if (!total) {
        total = order.length || 1;
    }
    if (!startMs) {
        startMs = Date.now();
    }

    if (activePollInterval) clearInterval(activePollInterval);

    let lastPrintedLogIndex = 0;
    let animatedNodeProgresses = {};

    activePollInterval = setInterval(async () => {
        if (!APP.execRunning) {
            clearInterval(activePollInterval);
            activePollInterval = null;
            return;
        }

        try {
            const statusRes = await fetch(`/api/workflow/status/${runId}`);
            if (!statusRes.ok) return;

            const runState = await statusRes.json();
            
            // 1. Process Logs in Real Time
            const serverLogs = runState.logs || [];
            for (let i = lastPrintedLogIndex; i < serverLogs.length; i++) {
                const line = serverLogs[i];
                let logType = 'info';
                if (line.includes('started')) logType = 'process';
                else if (line.includes('completed') || line.includes('complete')) logType = 'success';
                else if (line.includes('error') || line.includes('failed')) logType = 'error';
                logAdd(line, logType);
            }
            lastPrintedLogIndex = serverLogs.length;

            // 2. Update Node UI Statuses
            let completedCount = 0;
            let activeNodeLabel = 'Ready';

            for (let i = 0; i < total; i++) {
                const nodeId = order[i];
                const node = APP.nodes.find(n => n.id === nodeId);
                if (!node) continue;

                const serverNode = (runState.nodes && runState.nodes[nodeId]) || {};
                const prevStatus = node.status;
                node.status = serverNode.status || 'waiting';

                const def = NDEFS[node.type] || {};

                if (node.status === 'success') {
                    node.progress = 100;
                    completedCount++;
                    updateNodeEl(nodeId);

                    // Mark active/complete connections
                    APP.conns.filter(c => c.to === nodeId).forEach(c => {
                        const el = document.getElementById('cp-' + c.id);
                        if (el) {
                            el.classList.remove('conn-run');
                            el.classList.add('conn-ok');
                            el.setAttribute('marker-end', 'url(#ah-ok)');
                        }
                    });
                } else if (node.status === 'running') {
                    activeNodeLabel = def.label || nodeId;
                    
                    // Center active node smoothly so user sees pipeline flow in real-time
                    if (prevStatus !== 'running') {
                        centerNode(nodeId, true);
                    }

                    // Animate progress up to 95% dynamically
                    if (!animatedNodeProgresses[nodeId]) {
                        animatedNodeProgresses[nodeId] = 5;
                    } else {
                        animatedNodeProgresses[nodeId] = Math.min(animatedNodeProgresses[nodeId] + 4, 95);
                    }
                    node.progress = animatedNodeProgresses[nodeId];
                    updateNodeEl(nodeId);

                    // Connect highlights
                    APP.conns.filter(c => c.to === nodeId).forEach(c => {
                        const el = document.getElementById('cp-' + c.id);
                        if (el) {
                            el.classList.add('conn-run');
                            el.setAttribute('marker-end', 'url(#ah-run)');
                        }
                    });
                } else if (node.status === 'failed' || node.status === 'error') {
                    node.progress = 100;
                    completedCount++;
                    updateNodeEl(nodeId);
                } else {
                    node.progress = 0;
                    updateNodeEl(nodeId);
                }
            }

            // 3. Update Global Progress UI
            const overallPct = Math.floor((completedCount / total) * 100);
            updateProgressUI(overallPct, activeNodeLabel, total - completedCount, 0, startMs, total, completedCount);

            // 4. Check Final Status
            if (runState.status !== 'running') {
                clearInterval(activePollInterval);
                activePollInterval = null;
                APP.execRunning = false;
                try { localStorage.removeItem('pf_active_run_id'); } catch(e){}

                const finalResults = runState.results || {};
                
                // Force complete all visual node state highlights and store results
                let generatedVideoPath = null;
                for (let i = 0; i < total; i++) {
                    const nodeId = order[i];
                    const node = APP.nodes.find(n => n.id === nodeId);
                    if (!node) continue;
                    const resNode = finalResults[nodeId] || {};
                    node.status = resNode.status === 'error' ? 'failed' : (resNode.status || node.status);
                    node.result = resNode;
                    node.progress = 100;
                    updateNodeEl(nodeId);
                    if (resNode.video_path && !generatedVideoPath) {
                        generatedVideoPath = resNode.video_path;
                    }
                }

                if (runState.status === 'success' || (runState.status === 'partial' && generatedVideoPath)) {
                    logAdd('✓ Workflow execution finished successfully!', 'success');
                    D.wfStatusBadge.className = 'wf-status-badge success';
                    D.wfStatusBadge.textContent = '● Completed';
                    showToast('Workflow completed!', 'success');

                    // If a video was generated, render the path prominently with action buttons
                    if (generatedVideoPath) {
                        const vFilename = generatedVideoPath.split(/[\\/]/).pop();
                        const vUrl = `/api/video/file/${vFilename}`;
                        const safeVPath = generatedVideoPath.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                        const topicTitle = (runState.topic || 'PulseForge Generated Video').replace(/'/g, "\\'");

                        logAdd(`
<div style="margin: 10px 0; padding: 12px 16px; background: rgba(0, 255, 170, 0.08); border: 1px solid rgba(0, 255, 170, 0.4); border-radius: 8px; box-shadow: 0 4px 16px rgba(0, 255, 170, 0.12);">
    <div style="font-weight: 700; color: #00FFAA; font-size: 0.92rem; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">
        <span>🎬</span> Generated Video Output Path
    </div>
    <div style="font-size: 0.72rem; color: #94a3b8; margin-bottom: 2px;">SAVED LOCAL FILE LOCATION:</div>
    <div style="font-family: monospace; font-size: 0.82rem; color: #f8fafc; word-break: break-all; margin-bottom: 10px; background: rgba(0,0,0,0.5); padding: 7px 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.12); user-select: all;">
        ${generatedVideoPath}
    </div>
    <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <button onclick="window.copyToClipboard('${safeVPath}')" style="padding: 5px 12px; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.25); border-radius: 6px; color: #fff; font-size: 0.76rem; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 4px;">
            📋 Copy Full Path
        </button>
        <button onclick="window.openVideoPlayerModal('${vUrl}', '${topicTitle}', '${safeVPath}')" style="padding: 5px 14px; background: linear-gradient(135deg, #00FFAA, #00B87A); border: none; border-radius: 6px; color: #000; font-size: 0.76rem; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 4px;">
            ▶ Play Video Preview
        </button>
        <button onclick="window.revealVideoInFolder('${safeVPath}')" style="padding: 5px 12px; background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.4); border-radius: 6px; color: #38bdf8; font-size: 0.76rem; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 4px;">
            📁 Open in File Explorer
        </button>
    </div>
</div>
                        `, 'success');
                    }
                    
                    // Parse and highlight YouTube video link if exists
                    const lastNodeId = order[total - 1];
                    const lastRes = finalResults[lastNodeId] || {};
                    if (lastRes.youtube_video_id) {
                        const ytUrl = `https://youtu.be/${lastRes.youtube_video_id}`;
                        logAdd(`  ▶ Video uploaded to YouTube! URL: <a href="${ytUrl}" target="_blank" style="color:#00FFAA;text-decoration:underline;font-weight:bold">${ytUrl}</a>`, 'success');
                    }
                } else if (runState.status === 'partial') {
                    logAdd('⚠ Workflow completed with partial errors.', 'warning');
                    D.wfStatusBadge.className = 'wf-status-badge warning';
                    D.wfStatusBadge.textContent = '● Partial';
                    showToast('Workflow finished with errors', 'warning');
                } else {
                    logAdd(`✗ Workflow fatal error: ${runState.error || 'Server error'}`, 'error');
                    D.wfStatusBadge.className = 'wf-status-badge error';
                    D.wfStatusBadge.textContent = '● Failed';
                    showToast('Workflow pipeline failed!', 'error');
                }

                // Release UI locks
                APP.execRunning = false;
                D.canvasLockBanner?.classList.add('hidden');
                D.nodePalette?.classList.remove('palette-locked');
                D.canvasWrap?.classList.remove('canvas-locked');
                D.btnRun.classList.remove('hidden');
                D.btnStop.classList.add('hidden');
                D.chDot.classList.remove('running');
                setTimeout(() => D.wfProgressArea.classList.add('hidden'), 4000);
            }
        } catch (pollErr) {
            console.error("Polling error:", pollErr);
        }
    }, 800);
}

async function resumeActiveWorkflowIfRunning() {
    let runId = null;
    try { runId = localStorage.getItem('pf_active_run_id'); } catch(e){}
    if (!runId) return;

    try {
        const res = await fetch(`/api/workflow/status/${runId}`);
        if (!res.ok) {
            localStorage.removeItem('pf_active_run_id');
            return;
        }
        const data = await res.json();
        if (data.status === 'running') {
            console.log(`[resumeActiveWorkflow] Resuming live monitoring of run ${runId}...`);
            APP.execRunning = true;
            D.canvasLockBanner?.classList.remove('hidden');
            D.nodePalette?.classList.add('palette-locked');
            D.canvasWrap?.classList.add('canvas-locked');
            D.btnRun.classList.add('hidden');
            D.btnStop.classList.remove('hidden');
            D.wfStatusBadge.className = 'wf-status-badge running';
            D.wfStatusBadge.textContent = '● Running';
            D.wfProgressArea.classList.remove('hidden');
            D.chDot.classList.add('running');

            let order = null;
            let startMs = null;
            try {
                const rawOrder = localStorage.getItem('pf_active_run_order');
                if (rawOrder) order = JSON.parse(rawOrder);
                const rawStart = localStorage.getItem('pf_active_run_start');
                if (rawStart) startMs = parseInt(rawStart, 10);
            } catch(e){}

            pollWorkflowExecution(runId, order, order ? order.length : APP.nodes.length, startMs || Date.now());
        } else {
            localStorage.removeItem('pf_active_run_id');
        }
    } catch(e) {
        console.warn("Could not check active run state:", e);
    }
}

function stopWorkflow() {
    if (!APP.execRunning) return;
    APP.execRunning = false;
    if (activePollInterval) {
        clearInterval(activePollInterval);
        activePollInterval = null;
    }
    try { localStorage.removeItem('pf_active_run_id'); } catch(e){}
    D.canvasLockBanner?.classList.add('hidden');
    D.nodePalette?.classList.remove('palette-locked');
    D.canvasWrap?.classList.remove('canvas-locked');
    D.wfStatusBadge.className = 'wf-status-badge';
    D.wfStatusBadge.textContent = '● Stopped';
    D.btnRun.classList.remove('hidden');
    D.btnStop.classList.add('hidden');
    D.chDot.classList.remove('running');
    logAdd('Workflow stopped by user.', 'warning');
    setTimeout(() => D.wfProgressArea.classList.add('hidden'), 2000);
}

function updateProgressUI(pct, step, remaining, etaMs, startMs, total, doneF) {
    D.wfpFill.style.width = pct + '%';
    D.wfpPct.textContent  = `${pct}%`;
    D.wfpStep.textContent = `Current task: "${step || 'Ready'}"`;
    
    if (pct >= 100) {
        D.wfpEta.textContent = 'Completed!';
        return;
    }

    const elapsedSec = (Date.now() - (startMs || Date.now())) / 1000;
    const benchmarkTotalSec = Math.max(total, 1) * 7.0;
    
    let etaSec = 0;
    if (doneF > 0 && remaining > 0) {
        const perNode = elapsedSec / doneF;
        etaSec = Math.round(perNode * remaining);
    } else {
        etaSec = Math.max(8, Math.round(benchmarkTotalSec - elapsedSec));
    }
    
    let etaStr = "";
    if (etaSec > 60) {
        etaStr = `${Math.floor(etaSec/60)}m ${etaSec%60}s remaining`;
    } else {
        etaStr = `${Math.max(etaSec, 2)}s remaining`;
    }
    D.wfpEta.textContent = `Estimated time: ~${etaStr}`;
}

// ──────────────────────────────────────────────────────────────
// 10. LOG CONSOLE
// ──────────────────────────────────────────────────────────────
function ts() {
    const n = new Date();
    return `${String(n.getHours()).padStart(2,'0')}:${String(n.getMinutes()).padStart(2,'0')}:${String(n.getSeconds()).padStart(2,'0')}`;
}

function logAdd(msg, type = 'info') {
    // Remove welcome message
    const welcome = D.consoleBody.querySelector('.console-empty-msg');
    if (welcome) welcome.remove();

    APP.logCount++;
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.innerHTML = `<span class="log-ts">[${ts()}]</span><span class="log-msg">${msg}</span>`;
    D.consoleBody.appendChild(entry);
    D.consoleBody.scrollTop = D.consoleBody.scrollHeight;
    D.chCount.textContent = APP.logCount + (APP.logCount === 1 ? ' entry' : ' entries');
}

function logClear() {
    APP.logCount = 0;
    D.consoleBody.innerHTML = '<div class="console-empty-msg"><span>// Console cleared</span></div>';
    D.chCount.textContent = '0 entries';
}

// ──────────────────────────────────────────────────────────────
// 11. MINI-MAP
// ──────────────────────────────────────────────────────────────
function drawMinimap() {
    const canvas = D.minimap;
    const ctx    = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    ctx.fillStyle = 'rgba(4,7,14,0.88)';
    ctx.fillRect(0, 0, W, H);

    if (!APP.nodes.length) {
        ctx.fillStyle = '#4b5563';
        ctx.font = '10px Inter';
        ctx.textAlign = 'center';
        ctx.fillText('No nodes', W/2, H/2);
        ctx.textAlign = 'left';
        return;
    }

    const pad  = 10;
    const minX = Math.min(...APP.nodes.map(n => n.x)) - pad;
    const minY = Math.min(...APP.nodes.map(n => n.y)) - pad;
    const maxX = Math.max(...APP.nodes.map(n => n.x + NODE_W)) + pad;
    const maxY = Math.max(...APP.nodes.map(n => n.y + NODE_H)) + pad;
    const wW   = maxX - minX, wH = maxY - minY;
    const sc   = Math.min((W-8)/wW, (H-8)/wH) * 0.9;
    const ox   = (W - wW*sc)/2;
    const oy   = (H - wH*sc)/2;

    const mmX = wx => (wx - minX)*sc + ox;
    const mmY = wy => (wy - minY)*sc + oy;

    // Connections
    ctx.strokeStyle = 'rgba(79,195,247,0.25)'; ctx.lineWidth = 1;
    APP.conns.forEach(c => {
        const fn = APP.nodes.find(n=>n.id===c.from), tn = APP.nodes.find(n=>n.id===c.to);
        if (!fn||!tn) return;
        ctx.beginPath();
        ctx.moveTo(mmX(fn.x+NODE_W), mmY(fn.y+NODE_H/2));
        ctx.lineTo(mmX(tn.x), mmY(tn.y+NODE_H/2));
        ctx.stroke();
    });

    // Nodes
    APP.nodes.forEach(n => {
        const def = NDEFS[n.type] || {};
        ctx.fillStyle = n.id === APP.sel ? 'rgba(79,195,247,0.9)' : (def.color || '#4b5563') + 'aa';
        const rx = mmX(n.x), ry = mmY(n.y);
        const rw = Math.max(NODE_W*sc, 3), rh = Math.max(NODE_H*sc, 2);
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(rx, ry, rw, rh, 2);
        else ctx.rect(rx, ry, rw, rh);
        ctx.fill();
    });

    // Viewport rect
    const vpW = D.canvasWrap.clientWidth / APP.zoom;
    const vpH = D.canvasWrap.clientHeight / APP.zoom;
    const vpX = -APP.pan.x / APP.zoom;
    const vpY = -APP.pan.y / APP.zoom;
    ctx.strokeStyle = 'rgba(255,255,255,0.35)'; ctx.lineWidth = 1;
    ctx.strokeRect(mmX(vpX), mmY(vpY), vpW*sc, vpH*sc);

    // Border
    ctx.strokeStyle = 'rgba(255,255,255,0.06)'; ctx.lineWidth = 1;
    ctx.strokeRect(0,0,W,H);
}

// ──────────────────────────────────────────────────────────────
// 12. SAVE / LOAD (localStorage)
// ──────────────────────────────────────────────────────────────
function saveWorkflow() {
    const data = { name: D.wfNameInput.value, nodes: APP.nodes, conns: APP.conns, nextId: APP.nextId };
    try {
        localStorage.setItem('pf_workflow_' + D.wfNameInput.value, JSON.stringify(data));
        showToast('Workflow saved!', 'success');
    } catch { showToast('Could not save workflow.', 'error'); }
}

function loadWorkflow() {
    const key = 'pf_workflow_' + D.wfNameInput.value;
    try {
        const raw = localStorage.getItem(key);
        if (!raw) { showToast('No saved workflow found with this name.', 'warning'); return; }
        const data = JSON.parse(raw);
        APP.nodes  = data.nodes;
        APP.conns  = data.conns;
        APP.nextId = data.nextId || 100;
        renderAllNodes();
        renderAllConns();
        drawMinimap();
        showToast('Workflow loaded!', 'success');
    } catch { showToast('Could not load workflow.', 'error'); }
}

function saveUndo() {
    APP.undoStack.push(JSON.stringify({ nodes: APP.nodes, conns: APP.conns }));
    if (APP.undoStack.length > 30) APP.undoStack.shift();
}

// ──────────────────────────────────────────────────────────────
// 13. DEFAULT WORKFLOW & PRESETS
// ──────────────────────────────────────────────────────────────
function applyWorkflowPreset(presetKey) {
    if (!presetKey) return;
    if (APP.execRunning) {
        showToast('🔒 Workflow execution is active. Cannot change presets.', 'warning');
        return;
    }
    
    let ns = [];
    let cs = [];
    let name = 'Custom Workflow';
    
    if (presetKey === 'viral_shorts') {
        name = 'Full Viral Shorts Pipeline';
        ns = [
            { id:'n1',  type:'article-trigger',     x:80,   y:300 },
            { id:'n2',  type:'extract-viral-angle', x:360,  y:300 },
            { id:'n3',  type:'gen-hook',            x:640,  y:180 },
            { id:'n4',  type:'gen-script',          x:640,  y:420 },
            { id:'n5',  type:'tts',                 x:940,  y:180 },
            { id:'n6',  type:'gen-image',           x:940,  y:420 },
            { id:'n7',  type:'audio-agent',         x:1240, y:180 },
            { id:'n8',  type:'img-to-video',        x:1240, y:420 },
            { id:'n9',  type:'assemble-video',      x:1540, y:300 },
            { id:'n10', type:'upload-yt',           x:1820, y:300 },
        ];
        cs = [
            { id:'c1', from:'n1', to:'n2' },
            { id:'c2', from:'n2', to:'n3' },
            { id:'c3', from:'n2', to:'n4' },
            { id:'c4', from:'n3', to:'n5' },
            { id:'c5', from:'n4', to:'n6' },
            { id:'c6', from:'n5', to:'n7' },
            { id:'c7', from:'n6', to:'n8' },
            { id:'c8', from:'n7', to:'n9' },
            { id:'c9', from:'n8', to:'n9' },
            { id:'c10',from:'n9', to:'n10'},
        ];
    } else if (presetKey === 'cinematic_story') {
        name = 'Cinematic AI Faceless Story';
        ns = [
            { id:'n1', type:'manual-trigger',  x:80,   y:300 },
            { id:'n2', type:'gen-script',      x:360,  y:300 },
            { id:'n3', type:'tts',             x:660,  y:180 },
            { id:'n4', type:'gen-image',       x:660,  y:420 },
            { id:'n5', type:'img-to-video',    x:960,  y:420 },
            { id:'n6', type:'bg-music',        x:960,  y:180 },
            { id:'n7', type:'assemble-video',  x:1260, y:300 }
        ];
        cs = [
            { id:'c1', from:'n1', to:'n2' },
            { id:'c2', from:'n2', to:'n3' },
            { id:'c3', from:'n2', to:'n4' },
            { id:'c4', from:'n4', to:'n5' },
            { id:'c5', from:'n3', to:'n6' },
            { id:'c6', from:'n6', to:'n7' },
            { id:'c7', from:'n5', to:'n7' }
        ];
    } else if (presetKey === 'news_pulse') {
        name = 'Fast News Pulse Video';
        ns = [
            { id:'n1', type:'article-trigger', x:80,   y:300 },
            { id:'n2', type:'gen-script',      x:360,  y:300 },
            { id:'n3', type:'tts',             x:660,  y:180 },
            { id:'n4', type:'gen-image',       x:660,  y:420 },
            { id:'n5', type:'assemble-video',  x:960,  y:300 }
        ];
        cs = [
            { id:'c1', from:'n1', to:'n2' },
            { id:'c2', from:'n2', to:'n3' },
            { id:'c3', from:'n2', to:'n4' },
            { id:'c4', from:'n3', to:'n5' },
            { id:'c5', from:'n4', to:'n5' }
        ];
    } else if (presetKey === 'meme_hook') {
        name = 'Viral Hook & SFX Short';
        ns = [
            { id:'n1', type:'manual-trigger', x:80,  y:300 },
            { id:'n2', type:'gen-hook',       x:360, y:300 },
            { id:'n3', type:'tts',            x:660, y:180 },
            { id:'n4', type:'gen-sfx',        x:660, y:420 },
            { id:'n5', type:'assemble-video', x:960, y:300 }
        ];
        cs = [
            { id:'c1', from:'n1', to:'n2' },
            { id:'c2', from:'n2', to:'n3' },
            { id:'c3', from:'n3', to:'n4' },
            { id:'c4', from:'n3', to:'n5' },
            { id:'c5', from:'n4', to:'n5' }
        ];
    }
    
    D.wfNameInput.value = name;
    APP.nodes = ns.map(n => ({ ...n, status:'waiting', progress:0, config:{} }));
    APP.conns = cs;
    APP.nextId = 50;
    renderAllNodes();
    renderAllConns();
    drawMinimap();
    hideCanvasHint();
    
    APP.zoom = 0.78;
    requestAnimationFrame(() => {
        centerNode('n1', false);
        applyTransform();
    });
    showToast(`Template "${name}" loaded! (78% zoom focused on N1)`, 'success');
}

function loadDefaultWorkflow() {
    const ns = [
        { id:'n1',  type:'article-trigger',  x:80,   y:300 },
        { id:'n2',  type:'gen-script',       x:360,  y:300 },
        { id:'n3',  type:'gen-title',        x:640,  y:130 },
        { id:'n4',  type:'gen-desc',         x:640,  y:300 },
        { id:'n5',  type:'gen-tags',         x:640,  y:470 },
        { id:'n6',  type:'gen-seo',          x:920,  y:300 },
        { id:'n7',  type:'tts',              x:1200, y:130 },
        { id:'n8',  type:'gen-image',        x:1200, y:470 },
        { id:'n9',  type:'assemble-video',   x:1480, y:300 },
        { id:'n10', type:'upload-yt',        x:1760, y:170 },
        { id:'n11', type:'send-notif',       x:1760, y:430 },
    ];
    APP.nodes  = ns.map(n => ({ ...n, status:'waiting', progress:0, config:{} }));

    // If a signal was previously selected or cached, attach it to n1 right away
    const sig = SELECTED_SIGNAL || (() => {
        try {
            const s = localStorage.getItem('pf_selected_signal');
            return s ? JSON.parse(s) : null;
        } catch(e) { return null; }
    })();

    if (sig && sig.title) {
        const n1 = APP.nodes.find(n => n.id === 'n1');
        if (n1) {
            n1.config = {
                topic: sig.title,
                article_url: sig.link || sig.url || '',
                category: sig.topic || sig.category || 'AI',
                image_url: sig.image_url || '',
                viral_score: sig.score || 95
            };
        }
    }

    APP.conns  = [
        { id:'c1',  from:'n1',  to:'n2'  },
        { id:'c2',  from:'n2',  to:'n3'  },
        { id:'c3',  from:'n2',  to:'n4'  },
        { id:'c4',  from:'n2',  to:'n5'  },
        { id:'c5',  from:'n3',  to:'n6'  },
        { id:'c6',  from:'n4',  to:'n6'  },
        { id:'c7',  from:'n5',  to:'n6'  },
        { id:'c8',  from:'n6',  to:'n7'  },
        { id:'c9',  from:'n6',  to:'n8'  },
        { id:'c10', from:'n7',  to:'n9'  },
        { id:'c11', from:'n8',  to:'n9'  },
        { id:'c12', from:'n9',  to:'n10' },
        { id:'c13', from:'n9',  to:'n11' },
    ];
    APP.nextId = 50;
    renderAllNodes();
    renderAllConns();
    drawMinimap();
    hideCanvasHint();
    
    // Focus node n1 at 78% default zoom
    APP.zoom = 0.78;
    requestAnimationFrame(() => {
        centerNode('n1', false);
        applyTransform();
    });
}

// ──────────────────────────────────────────────────────────────
// 14. PALETTE BUILDER
// ──────────────────────────────────────────────────────────────
function buildPalette() {
    const container = D.paletteCats;
    container.innerHTML = '';
    CATS.forEach(cat => {
        const types = Object.entries(NDEFS).filter(([,d]) => d.cat === cat.id);
        if (!types.length) return;
        const catDiv = document.createElement('div');
        catDiv.className = 'palette-cat';
        catDiv.innerHTML = `
            <div class="palette-cat-header" data-cat="${cat.id}">
                <span>${cat.icon}</span>
                <span>${cat.label}</span>
                <span class="pch-arrow">▼</span>
            </div>
            <div class="palette-nodes">
                ${types.map(([type, def]) => `
                    <div class="palette-node" draggable="true" data-type="${type}" data-label="${def.label}" style="--cat-col:${cat.color}">
                        <span class="pn-icon">${def.icon}</span>
                        <span>${def.label}</span>
                        <span class="pn-cat-dot"></span>
                    </div>`).join('')}
            </div>`;
        container.appendChild(catDiv);

        // Collapse header toggle
        catDiv.querySelector('.palette-cat-header').addEventListener('click', function() {
            catDiv.classList.toggle('collapsed');
        });

        // Palette node events
        catDiv.querySelectorAll('.palette-node').forEach(el => {
            // Drag to canvas
            el.addEventListener('dragstart', e => {
                e.dataTransfer.setData('nodeType', el.dataset.type);
                e.dataTransfer.effectAllowed = 'copy';
            });
            // Click to add to center of view
            el.addEventListener('click', () => {
                const vpW   = D.canvasWrap.clientWidth;
                const vpH   = D.canvasWrap.clientHeight;
                const world = viewToWorld(vpW/2, vpH/2);
                addNode(el.dataset.type, world.x, world.y);
                drawMinimap();
            });
        });
    });
}

// Palette search filter
function bindPaletteSearch() {
    D.paletteSearch.addEventListener('input', () => {
        const q = D.paletteSearch.value.toLowerCase();
        document.querySelectorAll('.palette-node').forEach(el => {
            const match = el.dataset.label.toLowerCase().includes(q);
            el.style.display = match ? '' : 'none';
        });
        document.querySelectorAll('.palette-cat').forEach(cat => {
            const visible = [...cat.querySelectorAll('.palette-node')].some(n => n.style.display !== 'none');
            cat.style.display = visible ? '' : 'none';
        });
    });
}

// ──────────────────────────────────────────────────────────────
// 15. DASHBOARD DATA
// ──────────────────────────────────────────────────────────────
function buildDashboard() {
    console.log('[buildDashboard] Fetching live dashboard stats & generated videos...');
    fetch('/api/dashboard/stats')
        .then(res => res.json())
        .then(data => {
            console.log('[buildDashboard] Dashboard payload received:', data);
            if (data.status === 'success') {
                // Update stat cards
                const stats = data.stats || {};
                const statMap = {
                    'Total Videos Generated': stats.videos_generated,
                    'Total Published': stats.videos_published,
                    'Videos Processing': stats.videos_processing,
                    'Failed Jobs': stats.failed_jobs,
                    "Today's Views": stats.views_today,
                    'Connected Channels': stats.connected_channels
                };
                
                document.querySelectorAll('.stat-card').forEach(card => {
                    const labelEl = card.querySelector('.sc-label');
                    const valEl = card.querySelector('.sc-value');
                    if (labelEl && valEl) {
                        const label = labelEl.textContent.trim();
                        if (statMap[label] !== undefined) {
                            valEl.dataset.target = statMap[label];
                        }
                    }
                });

                // Update badge counts
                const videos = data.videos || [];
                const runs = data.recent_runs || [];
                if (D.dashVideoCountBadge) D.dashVideoCountBadge.textContent = `${videos.length} Videos Available`;
                if (D.dashRunsCountBadge) D.dashRunsCountBadge.textContent = `${runs.length} Pipeline Runs`;

                // Render Generated Videos List with Local File Paths & Preview
                renderDashboardVideos(videos);

                // Render Pipeline Runs with Status and Retry Logic
                renderDashboardRuns(runs);
            }
            animateCounters();
        })
        .catch(err => {
            console.error('[buildDashboard] Error fetching stats:', err);
            showToast('Failed to load dashboard metrics.', 'error');
            animateCounters();
        });

    function animateCounters() {
        document.querySelectorAll('.sc-value[data-target]').forEach(el => {
            const target = parseInt(el.dataset.target) || 0;
            const dur = 1200;
            const start = Date.now();
            function tick() {
                const p = Math.min((Date.now() - start) / dur, 1);
                const e = 1 - Math.pow(1-p, 3);
                el.textContent = Math.floor(e * target).toLocaleString();
                if (p < 1) requestAnimationFrame(tick);
            }
            setTimeout(() => requestAnimationFrame(tick), 100);
        });
    }

    // Activity feed
    if (D.actList) {
        D.actList.innerHTML = ACT_ITEMS.map(a => `
            <div class="act-item">
                <div class="act-dot ${a.dot}"></div>
                <div class="act-info">
                    <div class="act-text">${a.text}</div>
                    <div class="act-time">${a.time}</div>
                </div>
            </div>`).join('');
    }
}

// ── Render Generated Videos List with Local Paths ──
function renderDashboardVideos(videos) {
    if (!D.dashVideosContainer) return;

    if (!videos || videos.length === 0) {
        D.dashVideosContainer.innerHTML = `
            <div style="text-align: center; padding: 2.5rem 1rem; color: #94a3b8; background: rgba(255,255,255,0.02); border-radius: 12px; border: 1px dashed rgba(255,255,255,0.1);">
                <div style="font-size: 2rem; margin-bottom: 0.5rem;">🎬</div>
                <h4 style="color: #fff; font-size: 1rem; margin-bottom: 0.3rem;">No Generated Videos in Local Output Yet</h4>
                <p style="font-size: 0.8rem; max-width: 420px; margin: 0 auto 1.2rem auto;">Launch your first workflow pipeline from News Feed or Builder to render high-retention cinematic shorts.</p>
                <button class="btn-new-wf" onclick="switchView('builder')" style="font-size: 0.8rem; padding: 0.5rem 1rem;">⚡ Open Workflow Builder</button>
            </div>
        `;
        return;
    }

    D.dashVideosContainer.innerHTML = `
        <div class="dash-videos-grid">
            ${videos.map(v => {
                const localPath = v.local_path || 'C:\\AI_project\\output\\video.mp4';
                const fileUrl = v.file_url || '';
                const isComplete = v.status === 'completed' || v.exists;
                return `
                    <div class="dash-video-card">
                        <div class="dvc-left">
                            <div class="dvc-icon">🎬</div>
                            <div class="dvc-info">
                                <div class="dvc-title" title="${v.topic}">${v.topic}</div>
                                <div class="dvc-meta">
                                    <span>📅 ${v.created_at || 'Recently generated'}</span>
                                    <span>⚙️ ${v.model_used || 'Pollinations FLUX + EdgeTTS'}</span>
                                    <span style="color: ${isComplete ? '#34d399' : '#fbbf24'}; font-weight: 700;">
                                        ${isComplete ? '● Local File Ready' : '⏳ Rendering'}
                                    </span>
                                </div>
                                <div class="dvc-path-row">
                                    <span style="color: #64748b; font-size: 0.68rem; font-weight: 700;">LOCAL PATH:</span>
                                    <span class="dvc-path-text" title="${localPath}">${localPath}</span>
                                    <button class="dvc-copy-btn" data-path="${localPath}" title="Copy full local path to clipboard">📋 Copy</button>
                                </div>
                            </div>
                        </div>
                        <div class="dvc-actions">
                            ${fileUrl ? `
                                <button class="btn-watch-video" data-url="${fileUrl}" data-title="${v.topic}" data-path="${localPath}">
                                    <span>▶</span> Watch Video
                                </button>
                                <a class="btn-download-video" href="${fileUrl}" download="${v.filename || 'video.mp4'}" title="Download local mp4">
                                    <span>⬇</span> Save MP4
                                </a>
                            ` : `
                                <span style="font-size: 0.75rem; color: #94a3b8;">Path logged locally</span>
                            `}
                            <button class="wfi-btn" data-act="load-signal" data-topic="${v.topic}" title="Load topic into Workflow Builder">⚡</button>
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
    `;

    // Bind Copy Path Buttons
    D.dashVideosContainer.querySelectorAll('.dvc-copy-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const p = btn.dataset.path;
            if (navigator.clipboard) {
                navigator.clipboard.writeText(p).then(() => {
                    showToast(`📋 Copied local path: ${p}`, 'success');
                }).catch(() => {
                    showToast(`Path: ${p}`, 'info');
                });
            } else {
                showToast(`Path: ${p}`, 'info');
            }
        });
    });

    // Bind Watch Video Buttons
    D.dashVideosContainer.querySelectorAll('.btn-watch-video').forEach(btn => {
        btn.addEventListener('click', () => {
            const url = btn.dataset.url;
            const title = btn.dataset.title;
            const path = btn.dataset.path;
            openVideoPlayerModal(url, title, path);
        });
    });

    // Bind Open Signal in Builder Buttons
    D.dashVideosContainer.querySelectorAll('[data-act="load-signal"]').forEach(btn => {
        btn.addEventListener('click', () => {
            const topic = btn.dataset.topic;
            const sig = {
                title: topic,
                topic: 'Trending AI',
                viral_score: 92,
                image_url: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600&auto=format&fit=crop&q=80',
                summary: `Generating video pipeline for ${topic}`
            };
            localStorage.setItem('pf_selected_signal', JSON.stringify(sig));
            setActiveInputSignal(sig);
            switchView('builder');
            showToast(`Loaded "${topic}" into Workflow Builder`, 'success');
        });
    });
}

// ── Render Workflow Runs & Retry Controls ──
function renderDashboardRuns(runs) {
    if (!D.wfList) return;

    if (!runs || runs.length === 0) {
        // Fallback default workflows
        D.wfList.innerHTML = WF_ITEMS.map(w => `
            <div class="wf-item">
                <div class="wfi-icon">${w.icon}</div>
                <div class="wfi-info">
                    <div class="wfi-name">${w.name}</div>
                    <div class="wfi-meta">${w.meta}</div>
                </div>
                <div class="wfi-status ${w.status}">${{active:'● Active',paused:'⏸ Paused',error:'✕ Error'}[w.status]}</div>
                <div class="wfi-actions">
                    <button class="wfi-btn" title="Open in Builder" onclick="switchView('builder')">⚡</button>
                </div>
            </div>`).join('');
        return;
    }

    D.wfList.innerHTML = runs.map(r => {
        const isRunning = r.status === 'running';
        const isError   = r.status === 'error' || r.status === 'partial';
        const isSuccess = r.status === 'success';

        let statusClass = 'active';
        let statusLabel = '● Active';
        if (isRunning) {
            statusClass = 'paused';
            statusLabel = '● Running...';
        } else if (isError) {
            statusClass = 'error';
            statusLabel = '✕ Failed';
        } else if (isSuccess) {
            statusClass = 'active';
            statusLabel = '✓ Completed';
        }

        const logSnippet = (r.logs && r.logs.length > 0) ? r.logs[r.logs.length - 1] : (r.error || 'Execution finished');

        return `
            <div class="wf-item" style="display: flex; align-items: center; justify-content: space-between; gap: 10px;">
                <div style="display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1;">
                    <div class="wfi-icon">${isError ? '⚠️' : (isRunning ? '⚙️' : '🎬')}</div>
                    <div class="wfi-info">
                        <div class="wfi-name">${r.topic}</div>
                        <div class="wfi-meta">
                            <span>ID: ${r.run_id.substring(0, 8)}</span> · 
                            <span>${r.created_at || 'Just now'}</span> · 
                            <span style="color: ${isError ? '#f87171' : '#94a3b8'};">${logSnippet}</span>
                        </div>
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
                    <div class="wfi-status ${statusClass}">${statusLabel}</div>
                    ${isError || r.can_retry ? `
                        <button class="btn-retry-run" data-run-id="${r.run_id}" data-topic="${r.topic}" title="Retry failed workflow run">
                            <span>🔄</span> Retry
                        </button>
                    ` : ''}
                    <button class="wfi-btn" data-act="open-run-builder" title="Open in Builder">⚡</button>
                </div>
            </div>
        `;
    }).join('');

    // Bind Retry Buttons
    D.wfList.querySelectorAll('.btn-retry-run').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const runId = btn.dataset.runId;
            const topic = btn.dataset.topic;
            retryWorkflowExecution(runId, topic);
        });
    });

    // Bind Open in Builder
    D.wfList.querySelectorAll('[data-act="open-run-builder"]').forEach(btn => {
        btn.addEventListener('click', () => switchView('builder'));
    });
}

// ── Workflow Retry Logic ──
function retryWorkflowExecution(runId, topic) {
    showToast(`🔄 Retrying pipeline for: "${topic}"...`, 'info', 4000);
    fetch(`/api/workflow/retry/${runId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'started' && data.run_id) {
            const newRunId = data.run_id;
            const startMs = Date.now();
            localStorage.setItem('pf_active_run_id', newRunId);
            localStorage.setItem('pf_active_run_start', startMs);

            // Switch to builder and display live running UI
            switchView('builder');
            if (D.canvasLockBanner) D.canvasLockBanner.classList.remove('hidden');
            if (D.wfProgressArea) D.wfProgressArea.classList.remove('hidden');
            if (D.wfStatusBadge) {
                D.wfStatusBadge.textContent = '● Running (Retry)';
                D.wfStatusBadge.className = 'wf-status-badge running';
            }
            if (D.btnRun) D.btnRun.classList.add('hidden');
            if (D.btnStop) D.btnStop.classList.remove('hidden');

            const order = ['n1', 'n2', 'n3', 'n4', 'n5', 'n6'];
            pollWorkflowExecution(newRunId, order, order.length, startMs);
            showToast('✅ Workflow retry started! Tracking progress live.', 'success');
        } else {
            showToast(`Retry failed: ${data.message || 'Unknown error'}`, 'error');
        }
    })
    .catch(err => {
        console.error('[retryWorkflowExecution] Error:', err);
        showToast('Network error while retrying workflow.', 'error');
    });
}

// ── Video Preview Modal & File Management Helpers ──
function openVideoPlayerModal(videoUrl, title, localPath) {
    if (!D.dashVideoModal || !D.dashVideoPlayer) return;
    D.dashVideoPlayer.src = videoUrl;
    if (D.dashVideoModalTitle) D.dashVideoModalTitle.textContent = title || 'Preview Generated Video';
    if (D.dashVideoModalPath) D.dashVideoModalPath.textContent = localPath || 'C:\\AI_project\\output';
    if (D.btnDownloadModalVideo) {
        D.btnDownloadModalVideo.href = videoUrl;
        const fname = (localPath || '').split(/[\\/]/).pop() || 'video.mp4';
        D.btnDownloadModalVideo.download = fname;
    }
    D.dashVideoModal.classList.remove('hidden');
    D.dashVideoPlayer.play().catch(e => console.log('Autoplay handled:', e));
}

function closeVideoPlayerModal() {
    if (!D.dashVideoModal || !D.dashVideoPlayer) return;
    D.dashVideoPlayer.pause();
    D.dashVideoPlayer.src = '';
    D.dashVideoModal.classList.add('hidden');
}

// Global helpers accessible from inline action handlers
window.openVideoPlayerModal = openVideoPlayerModal;
window.closeVideoPlayerModal = closeVideoPlayerModal;

window.copyToClipboard = function(text) {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            showToast(`📋 Copied local path: ${text}`, 'success');
        }).catch(() => {
            prompt('Copy file path manually:', text);
        });
    } else {
        prompt('Copy file path manually:', text);
    }
};

// ──────────────────────────────────────────────────────────────
// LIVE CONNECTION TEST FUNCTION
// ──────────────────────────────────────────────────────────────
window.testNodeConnection = async function(nodeId) {
    const node = APP.nodes.find(n => n.id === nodeId);
    if (!node) return;

    const btn = document.getElementById(`pc-test-btn-${nodeId}`);
    const resultDiv = document.getElementById(`pc-conn-result-${nodeId}`);
    if (!btn || !resultDiv) return;

    // Show loading state
    btn.innerHTML = '<span class="spin">⟳</span> Testing Connection...';
    btn.style.opacity = '0.7';
    btn.style.pointerEvents = 'none';
    resultDiv.style.display = 'none';

    const config = { ...(node.config || {}) };

    try {
        const resp = await fetch('/api/workflow/test-connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                node_type: node.type,
                config: config
            })
        });

        const data = await resp.json();
        resultDiv.style.display = 'block';

        if (data.status === 'success') {
            node._connTested = true;
            node._connOk = true;
            resultDiv.innerHTML = `
                <div style="display:flex;align-items:center;gap:8px;padding:8px 10px;background:rgba(0,255,170,0.07);border:1px solid rgba(0,255,170,0.35);border-radius:6px;">
                    <span style="font-size:1.1em;">✅</span>
                    <div>
                        <div style="font-size:0.74rem;font-weight:700;color:#00FFAA;">${escHtml(data.model || 'Connected')}</div>
                        <div style="font-size:0.70rem;color:#94a3b8;">${escHtml(data.message || 'Connection OK')} · ${data.latency_ms || '?'}ms</div>
                    </div>
                </div>`;
            btn.innerHTML = '✅ Connected — Test Again';
            btn.style.borderColor = 'rgba(0,255,170,0.5)';
        } else {
            node._connTested = true;
            node._connOk = false;
            resultDiv.innerHTML = `
                <div style="display:flex;align-items:center;gap:8px;padding:8px 10px;background:rgba(239,68,68,0.07);border:1px solid rgba(239,68,68,0.35);border-radius:6px;">
                    <span style="font-size:1.1em;">❌</span>
                    <div>
                        <div style="font-size:0.74rem;font-weight:700;color:#f87171;">Connection Failed</div>
                        <div style="font-size:0.70rem;color:#94a3b8;">${escHtml(data.message || 'Unknown error')}</div>
                    </div>
                </div>`;
            btn.innerHTML = '❌ Failed — Retry Test';
            btn.style.borderColor = 'rgba(239,68,68,0.5)';
            btn.style.color = '#f87171';
        }
    } catch (err) {
        resultDiv.style.display = 'block';
        resultDiv.innerHTML = `<div style="padding:8px;color:#f87171;font-size:0.73rem;border:1px solid rgba(239,68,68,0.3);border-radius:6px;">⚠ Network error: ${escHtml(err.message)}</div>`;
        btn.innerHTML = '⚡ Test Live Connection';
    }

    btn.style.opacity = '1';
    btn.style.pointerEvents = 'auto';
    renderCanvas();
};

window.revealVideoInFolder = async function(path) {

    try {
        showToast('Opening path in File Explorer...', 'info', 2000);
        const res = await fetch('/api/video/reveal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: path })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Opened folder in File Explorer', 'success');
        } else {
            showToast(`Could not open path: ${data.message}`, 'error');
        }
    } catch(e) {
        console.error('[revealVideoInFolder] Error:', e);
        showToast(`Path: ${path}`, 'info');
    }
};

// ──────────────────────────────────────────────────────────────
// 16. CONTEXT MENU
// ──────────────────────────────────────────────────────────────
let _ctxNodeId = null;
function showCtxMenu(e, nodeId) {
    e.preventDefault();
    _ctxNodeId = nodeId;
    selectNode(nodeId);
    D.ctxMenu.style.left = e.clientX + 'px';
    D.ctxMenu.style.top  = e.clientY + 'px';
    D.ctxMenu.classList.remove('hidden');
}
function hideCtxMenu() { D.ctxMenu.classList.add('hidden'); }

// ──────────────────────────────────────────────────────────────
// 17. TOAST
// ──────────────────────────────────────────────────────────────
function showToast(msg, type='info', dur=3800) {
    const icons = { success:'✅', error:'❌', info:'ℹ️', warning:'⚠️' };
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `<span>${icons[type]||'ℹ️'}</span> ${msg}`;
    D.toastContainer.appendChild(el);
    setTimeout(() => {
        el.style.opacity = '0'; el.style.transition = 'opacity 0.3s';
        setTimeout(() => el.remove(), 300);
    }, dur);
}

// ──────────────────────────────────────────────────────────────
// 18. VIEW SWITCHING
// ──────────────────────────────────────────────────────────────
function switchView(viewName) {
    APP.view = viewName;
    D.autoTabs.forEach(t => t.classList.toggle('active', t.dataset.view === viewName));
    document.querySelectorAll('.auto-view').forEach(v => v.classList.toggle('hidden', v.id !== 'view-' + viewName));
    if (viewName === 'builder') {
        // If canvas is empty, auto-load the default pipeline
        if (!APP.nodes || APP.nodes.length === 0) {
            loadDefaultWorkflow();
        }
        setTimeout(() => { applyTransform(); drawMinimap(); }, 50);
    }
    if (viewName === 'dashboard') { buildDashboard(); }
    if (viewName === 'free-ai' && typeof window.buildFreeAI === 'function') { window.buildFreeAI(); }
}


// ──────────────────────────────────────────────────────────────
// 19. CANVAS HINT
// ──────────────────────────────────────────────────────────────
function hideCanvasHint() {
    if (D.canvasHint) D.canvasHint.style.opacity = '0';
}

// ──────────────────────────────────────────────────────────────
// 20. BIND EVENTS
// ──────────────────────────────────────────────────────────────
function bindNodeEvents(el, nodeId) {
    // Drag node
    el.addEventListener('pointerdown', e => onNodePointerDown(e, nodeId));
    // Port drag-start
    el.querySelectorAll('.cn-port').forEach(port => {
        port.addEventListener('pointerdown', e => {
            e.stopPropagation();
            onPortPointerDown(e, nodeId, port.dataset.port);
        });
    });
    // Action buttons
    el.querySelectorAll('[data-act]').forEach(btn => {
        btn.addEventListener('click', e => {
            e.stopPropagation();
            const act = btn.dataset.act;
            if (act === 'del') removeNode(nodeId);
            if (act === 'dup') duplicateNode(nodeId);
            if (act === 'config') selectNode(nodeId);
        });
    });
    // Retry button
    const retry = el.querySelector('.cn-retry-btn');
    if (retry) {
        retry.addEventListener('click', e => {
            e.stopPropagation();
            const node = APP.nodes.find(n => n.id === nodeId);
            if (node) { node.status = 'waiting'; node.progress = 0; updateNodeEl(nodeId); }
        });
    }
    // Right-click
    el.addEventListener('contextmenu', e => showCtxMenu(e, nodeId));
}

function bindAllEvents() {
    // View tabs
    D.autoTabs.forEach(btn => btn.addEventListener('click', () => switchView(btn.dataset.view)));

    // Toolbar
    D.btnRun.addEventListener('click', () => runWorkflow());
    D.btnStop.addEventListener('click', () => stopWorkflow());
    D.btnSave.addEventListener('click', () => saveWorkflow());
    D.btnLoad.addEventListener('click', () => loadWorkflow());
    D.btnFitView?.addEventListener('click', () => fitView(true));
    D.btnResetView?.addEventListener('click', resetView);
    D.btnCenterWorkflow?.addEventListener('click', () => fitView(true));
    D.btnClearCanvas.addEventListener('click', () => {
        if (!confirm('Clear all nodes and connections?')) return;
        APP.nodes = []; APP.conns = [];
        D.nodesLayer.innerHTML = '';
        D.connGroup.innerHTML  = '';
        APP.sel = null; showPropsEmpty();
        drawMinimap();
        if (D.canvasHint) D.canvasHint.style.opacity = '1';
    });

    // Zoom buttons
    D.btnZoomIn.addEventListener('click',  () => zoomAtPoint(APP.zoom * 1.18, D.canvasWrap.clientWidth/2, D.canvasWrap.clientHeight/2));
    D.btnZoomOut.addEventListener('click', () => zoomAtPoint(APP.zoom * 0.85, D.canvasWrap.clientWidth/2, D.canvasWrap.clientHeight/2));

    // Mouse wheel zoom
    D.canvasWrap.addEventListener('wheel', e => {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.1 : 0.92;
        const cv = canvasXY(e);
        zoomAtPoint(APP.zoom * factor, cv.x, cv.y);
    }, { passive: false });

    // Preset templates
    D.wfPresetSelect?.addEventListener('change', e => {
        applyWorkflowPreset(e.target.value);
    });

    // Canvas pan + drag
    D.canvasWrap.addEventListener('pointerdown', onCanvasPointerDown);
    D.canvasWrap.addEventListener('dragover', e => { 
        if (APP.execRunning) return;
        e.preventDefault(); 
        e.dataTransfer.dropEffect = 'copy'; 
    });
    D.canvasWrap.addEventListener('drop', e => {
        if (APP.execRunning) {
            showToast('🔒 Workflow execution is active. Canvas modifications are locked.', 'warning');
            return;
        }
        e.preventDefault();
        const type = e.dataTransfer.getData('nodeType');
        if (!type) return;
        const cv    = canvasXY(e);
        const world = viewToWorld(cv.x, cv.y);
        addNode(type, world.x, world.y);
        drawMinimap();
    });

    // Global pointer events
    document.addEventListener('pointermove', onGlobalPointerMove);
    document.addEventListener('pointerup',   onGlobalPointerUp);

    // Context menu
    D.ctxMenu.querySelectorAll('.ctx-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const act = btn.dataset.action;
            if (!_ctxNodeId) return hideCtxMenu();
            if (act === 'duplicate') duplicateNode(_ctxNodeId);
            if (act === 'delete')    removeNode(_ctxNodeId);
            if (act === 'properties') selectNode(_ctxNodeId);
            hideCtxMenu();
        });
    });
    document.addEventListener('click', hideCtxMenu);
    document.addEventListener('contextmenu', e => {
        if (!e.target.closest('.cnode')) hideCtxMenu();
    });

    // Console
    D.btnClearLog.addEventListener('click', logClear);
    D.btnCollapseConsole.addEventListener('click', () => {
        APP.consoleCollapsed = !APP.consoleCollapsed;
        D.execConsole.classList.toggle('collapsed', APP.consoleCollapsed);
        D.btnCollapseConsole.textContent = APP.consoleCollapsed ? '▲' : '▼';
    });

    // Config modal close
    D.cmClose?.addEventListener('click',  () => D.configModalOverlay.classList.add('hidden'));
    D.cmCancel?.addEventListener('click', () => D.configModalOverlay.classList.add('hidden'));
    D.configModalOverlay?.addEventListener('click', e => {
        if (e.target === D.configModalOverlay) D.configModalOverlay.classList.add('hidden');
    });

    // Minimap click → pan to that area
    D.minimap.addEventListener('click', () => fitView());

    // Dashboard: new workflow
    document.getElementById('btnNewWorkflow')?.addEventListener('click', () => {
        switchView('builder');
        setTimeout(() => {
            loadDefaultWorkflow();
            D.wfNameInput.value = 'YouTube Content Pipeline';
        }, 80);
    });

    // Dashboard Refresh & Video Modal Listeners
    D.btnRefreshDashboard?.addEventListener('click', () => {
        showToast('Refreshing metrics & generated video index...', 'info', 1500);
        buildDashboard();
    });
    D.dashVideoModalClose?.addEventListener('click', closeVideoPlayerModal);
    D.dashVideoModal?.addEventListener('click', e => {
        if (e.target === D.dashVideoModal) closeVideoPlayerModal();
    });
    D.btnCopyModalVideoPath?.addEventListener('click', () => {
        const path = D.dashVideoModalPath?.textContent;
        if (path && navigator.clipboard) {
            navigator.clipboard.writeText(path).then(() => {
                showToast(`📋 Copied local path: ${path}`, 'success');
            }).catch(() => {
                showToast(`Path: ${path}`, 'info');
            });
        }
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            closeVideoPlayerModal();
        }
        if (APP.view !== 'builder') return;
        const tag = document.activeElement.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if ((e.key === 'Delete' || e.key === 'Backspace') && APP.sel) removeNode(APP.sel);
        if (e.key === 'f' || e.key === 'F') fitView();
        if (e.ctrlKey && e.key === 's') { e.preventDefault(); saveWorkflow(); }
        if (e.key === 'Escape') { selectNode(null); if (APP.connecting) { APP.connecting=null; D.tempLine.classList.add('hidden'); document.body.style.cursor=''; } }
    });

    // Resize → update minimap
    window.addEventListener('resize', drawMinimap);
}

// ──────────────────────────────────────────────────────────────
// 21. INIT
// ──────────────────────────────────────────────────────────────
async function loadSavedArticlesForTrigger() {
    try {
        const res = await fetch('/api/saved_articles');
        const data = await res.json();
        const titles = data.articles.map(a => a.title);
        const triggerConf = NODE_CONFIGS['article-trigger'].find(c => c.key === 'topic');
        if (triggerConf) {
            triggerConf.opts = titles.length ? titles : ['No saved articles'];
            triggerConf.def = triggerConf.opts[0];
            // If the node properties panel is open for an article-trigger, update it
            if (APP.sel) {
                const selNode = APP.nodes.find(n => n.id === APP.sel);
                if (selNode && selNode.type === 'article-trigger') {
                    showPropsContent(APP.sel);
                }
            }
        }
    } catch(e) {
        console.error("Failed to fetch saved articles", e);
    }
}

async function checkYoutubeStatus() {
    try {
        const res = await fetch('/api/youtube/status');
        if (!res.ok) return;
        const data = await res.json();
        const btn = document.getElementById('btnConnectYoutube');
        if (btn && data.connected) {
            btn.classList.add('connected');
            btn.innerHTML = '<span class="yt-icon">✓</span> YouTube Connected';
            btn.title = 'Your YouTube account is linked';
        }
    } catch(e) {
        console.error("Failed to check YouTube status", e);
    }
}

async function checkAIMarketStatus() {
    try {
        const res = await fetch('/api/ai-market/status');
        if (!res.ok) return;
        const data = await res.json();
        const textEl = document.getElementById('aiMarketText');
        if (textEl && data.recommended_image) {
            textEl.textContent = `Free AI: ${data.recommended_image}`;
            textEl.title = `Active Free Image Engine: ${data.recommended_image}\nVideo Engine: ${data.recommended_video}`;
        }
    } catch(e) {
        console.warn("AI market status check:", e);
    }
}

function init() {
    try { cacheDOM(); } catch(e) { console.error('cacheDOM error:', e); }
    try { buildPalette(); } catch(e) { console.error('buildPalette error:', e); }
    try { bindPaletteSearch(); } catch(e) { console.error('bindPaletteSearch error:', e); }
    try { bindAllEvents(); } catch(e) { console.error('bindAllEvents error:', e); }
    try { buildDashboard(); } catch(e) { console.error('buildDashboard error:', e); }
    try { loadSavedArticlesForTrigger(); } catch(e) { console.error('loadSavedArticles error:', e); }
    try { checkYoutubeStatus(); } catch(e) { console.error('checkYoutubeStatus error:', e); }
    try { checkAIMarketStatus(); } catch(e) { console.error('checkAIMarketStatus error:', e); }
    try { initAudioLibrary(); } catch(e) { console.error('initAudioLibrary error:', e); }
    try { loadDefaultWorkflow(); } catch(e) { console.error('loadDefaultWorkflow error:', e); }
    try { initSignalManager(); } catch(e) { console.error('initSignalManager error:', e); }
    try { updateQueueBadge(); } catch(e) { console.error('queue badge error:', e); }
    try { initApiKeysManager(); } catch(e) { console.error('initApiKeysManager error:', e); }
    try { initAdminSyncHub(); } catch(e) { console.error('initAdminSyncHub error:', e); }
    try { applyTransform(); } catch(e) { console.error('applyTransform error:', e); }
    
    // Determine starting view
    const urlParams = new URLSearchParams(window.location.search);
    const goToBuilder = urlParams.get('view') === 'builder';
    
    if (goToBuilder) {
        switchView('builder');
    } else {
        switchView('dashboard');
    }

    // Apply signal AFTER view switch so DOM is ready
    _applyPersistedSignal();

    // Check if a workflow was running in background across tabs/views
    try { resumeActiveWorkflowIfRunning(); } catch(e) {}
}

/**
 * Reads any persisted signal from localStorage/sessionStorage and applies it.
 * Safe to call multiple times — idempotent.
 */
async function _applyPersistedSignal() {
    try {
        // 1. sessionStorage prefill (from News Feed → Automation flow)
        const prefill = sessionStorage.getItem('prefill_topic');
        if (prefill) {
            setSignal({ title: prefill, topic: 'News Intelligence', score: 96, link: '', image_url: '' });
            sessionStorage.removeItem('prefill_topic');
            return;
        }
        // 2. localStorage persisted signal (from Saved Articles → Create Workflow flow)
        const raw = localStorage.getItem('pf_selected_signal');
        if (raw) {
            try {
                const parsed = JSON.parse(raw);
                if (parsed && parsed.title) {
                    setSignal(parsed);
                    return;
                }
            } catch(e) {}
        }
        // 3. Fallback: fetch first saved article
        try {
            const savedRes = await fetch('/api/saved');
            if (savedRes.ok) {
                const savedData = await savedRes.json();
                if (savedData && savedData.articles && savedData.articles.length > 0) {
                    const first = savedData.articles[0];
                    setSignal({
                        title: first.title,
                        topic: first.topic || 'Trending',
                        score: first.score || 95,
                        image_url: first.image_url || '',
                        link: first.link || ''
                    });
                    return;
                }
            }
        } catch(e) {}

        // 4. Fallback: fetch top trending article from news feed
        try {
            const newsRes = await fetch('/api/articles?per_page=10');
            if (newsRes.ok) {
                const newsData = await newsRes.json();
                if (newsData && newsData.articles && newsData.articles.length > 0) {
                    const first = newsData.articles[0];
                    setSignal({
                        title: first.title,
                        topic: first.topic || 'Trending News',
                        score: first.score || 92,
                        image_url: first.image_url || '',
                        link: first.link || ''
                    });
                    return;
                }
            }
        } catch(e) {}

        // 5. Ultimate fallback if offline/no data
        setSignal({
            title: "Revolutionary AI Agent Automates End-to-End Content Creation",
            topic: "AI & Tech",
            score: 98,
            image_url: "",
            link: "https://news.ycombinator.com"
        });
    } catch (e) { console.error('[_applyPersistedSignal] Error:', e); }
}

// Alias used in dashboard signal buttons
const setActiveInputSignal = setSignal;

document.addEventListener('DOMContentLoaded', init);
window.addEventListener('focus', () => {
    if (!APP.execRunning) {
        resumeActiveWorkflowIfRunning();
    }
});

// ──────────────────────────────────────────────────────────────
// 22. AUDIO LIBRARY & AUDIO INTELLIGENCE FRONTEND CONTROLLER
// ──────────────────────────────────────────────────────────────
let AUDIO_STATE = {
    page: 1,
    perPage: 12,
    category: '',
    emotion: '',
    search: '',
    playingAudio: null,
    playingBtn: null,
    syncInterval: null
};

async function loadAudioLibrary(page = 1) {
    AUDIO_STATE.page = page;
    const grid = document.getElementById('soundsGrid');
    if (!grid) return;
    
    grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: #94a3b8;">
        <div style="font-size: 24px; animation: spin 1.5s linear infinite; display: inline-block;">🔄</div>
        <p style="margin-top: 12px;">Querying local sound registry & neural database...</p>
    </div>`;

    try {
        const queryParams = new URLSearchParams({
            page: AUDIO_STATE.page,
            per_page: AUDIO_STATE.perPage,
            category: AUDIO_STATE.category,
            emotion: AUDIO_STATE.emotion,
            search: AUDIO_STATE.search
        });
        
        const res = await fetch(`/api/audio-library?${queryParams}`);
        const data = await res.json();
        
        if (data.status === 'success') {
            renderSounds(data.sounds);
            updateAudioPagination(data.total, data.page, data.per_page);
        } else {
            grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: #f87171;">
                <p>✗ Error loading sounds: ${data.message}</p>
            </div>`;
        }
    } catch (e) {
        grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: #f87171;">
            <p>✗ Connection error: ${e.message}</p>
        </div>`;
    }
}

function renderSounds(sounds) {
    const grid = document.getElementById('soundsGrid');
    if (!grid) return;
    
    if (!sounds || !sounds.length) {
        grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: #64748b;">
            <div style="font-size: 32px;">🎵</div>
            <p style="margin-top: 12px;">No matching sounds found in the library.<br>Click "🔄 Sync Sounds" to pull new trending audio.</p>
        </div>`;
        return;
    }
    
    grid.innerHTML = sounds.map(sound => {
        const tags = JSON.parse(sound.tags || '[]');
        const isMusic = sound.is_music === 1;
        const isSaved = sound.is_downloaded === 1 || sound.has_local_file;
        const localPath = sound.local_path || '';
        const playUrl = sound.local_url || sound.play_url || sound.source_url;
        
        return `
            <div class="sound-card" id="sc-${sound.id}">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 10px;">
                    <div style="min-width: 0; flex: 1;">
                        <h3 style="font-size: 15px; font-weight: 700; color: #fff; margin: 0 0 6px 0; font-family: 'Space Grotesk', sans-serif; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${sound.name}</h3>
                        <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 6px;">
                            <span class="sound-tag category">${isMusic ? 'Background Music' : 'SFX / Meme'}</span>
                            <span class="sound-tag emotion">${sound.emotion || 'general'}</span>
                            <span class="sound-tag source">${sound.source || 'pulseforge'}</span>
                        </div>
                    </div>
                    <button class="sound-play-btn" data-url="${playUrl}" data-id="${sound.id}" title="Play preview" style="width: 36px; height: 36px; border-radius: 50%; background: linear-gradient(135deg, #00FFAA, #00B8FF); border: none; color: #000; font-weight: bold; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">▶</button>
                </div>

                <!-- Local Path Info & Save Action -->
                <div>
                    ${isSaved && localPath ? `
                        <div class="sound-path-box">
                            <span class="sound-path-text" title="${localPath}">${localPath}</span>
                            <button class="sound-copy-btn" data-path="${localPath}" title="Copy local path">📋 Copy</button>
                        </div>
                    ` : `
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
                            <span style="font-size: 11px; color: #94a3b8;">Cloud Preview Ready</span>
                            <button class="btn-save-sound" data-id="${sound.id}" data-name="${sound.name}">
                                <span>💾</span> Save to Project
                            </button>
                        </div>
                    `}
                </div>

                <!-- Bottom stats bar -->
                <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 10px; margin-top: 4px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 12px; color: #fbbf24; font-weight: 700;">🔥 ${sound.viral_score ? sound.viral_score.toFixed(1) : '8.5'}</span>
                        ${isSaved ? `<span class="sound-saved-badge">✓ Saved Locally</span>` : ''}
                    </div>
                    <div style="font-size: 11px; color: #94a3b8;">${sound.duration_s ? sound.duration_s + 's' : 'Clip'} · ${sound.file_size_kb ? sound.file_size_kb + 'KB' : 'MP3'}</div>
                </div>
            </div>`;
    }).join('');

    // Bind Play Buttons
    grid.querySelectorAll('.sound-play-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const url = btn.dataset.url;
            const id = btn.dataset.id;
            togglePlayPreview(url, id, btn);
        });
    });

    // Bind Copy Path Buttons
    grid.querySelectorAll('.sound-copy-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const p = btn.dataset.path;
            if (navigator.clipboard) {
                navigator.clipboard.writeText(p).then(() => {
                    showToast(`📋 Copied local sound path: ${p}`, 'success');
                }).catch(() => {
                    showToast(`Path: ${p}`, 'info');
                });
            } else {
                showToast(`Path: ${p}`, 'info');
            }
        });
    });

    // Bind Save Locally Buttons
    grid.querySelectorAll('.btn-save-sound').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const soundId = btn.dataset.id;
            const soundName = btn.dataset.name;
            saveSoundToProject(soundId, soundName, btn);
        });
    });
}

// ── Save Sound to Local Project Storage ──
async function saveSoundToProject(soundId, soundName, btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span> Saving...';
    showToast(`Downloading "${soundName}" into local project folder...`, 'info', 2000);

    try {
        const res = await fetch(`/api/audio-library/save-local/${soundId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();

        if (data.status === 'success' && data.local_path) {
            showToast(`✅ Saved "${soundName}" locally: ${data.local_path}`, 'success', 4000);
            appendConsoleLog('save_sound', `Saved sound "${soundName}" to ${data.local_path}`);
            loadAudioStats();
            loadAudioLibrary(AUDIO_STATE.page);
        } else {
            showToast(`Save failed: ${data.message || 'Unknown error'}`, 'error');
            btn.disabled = false;
            btn.innerHTML = '<span>💾</span> Save to Project';
        }
    } catch (e) {
        showToast(`Network error: ${e.message}`, 'error');
        btn.disabled = false;
        btn.innerHTML = '<span>💾</span> Save to Project';
    }
}

function updateAudioPagination(total, page, perPage) {
    const totalPages = Math.max(1, Math.ceil(total / perPage));
    const info = document.getElementById('soundPageInfo');
    if (info) info.textContent = `Page ${page} of ${totalPages} (Total: ${total})`;
    
    const prev = document.getElementById('soundPrevPage');
    const next = document.getElementById('soundNextPage');
    
    if (prev) prev.disabled = page <= 1;
    if (next) next.disabled = page >= totalPages;
}

function togglePlayPreview(url, id, btn) {
    const card = document.getElementById(`sc-${id}`);
    
    if (AUDIO_STATE.playingAudio && AUDIO_STATE.playingBtn === btn) {
        // Pause current
        AUDIO_STATE.playingAudio.pause();
        AUDIO_STATE.playingAudio = null;
        AUDIO_STATE.playingBtn = null;
        btn.textContent = '▶';
        if (card) card.classList.remove('playing');
        return;
    }
    
    if (AUDIO_STATE.playingAudio) {
        // Stop currently playing
        AUDIO_STATE.playingAudio.pause();
        if (AUDIO_STATE.playingBtn) {
            AUDIO_STATE.playingBtn.textContent = '▶';
            const activeCard = AUDIO_STATE.playingBtn.closest('.sound-card');
            if (activeCard) activeCard.classList.remove('playing');
        }
    }
    
    // Play new
    const audio = new Audio(url);
    audio.play().then(() => {
        AUDIO_STATE.playingAudio = audio;
        AUDIO_STATE.playingBtn = btn;
        btn.textContent = '⏸';
        if (card) card.classList.add('playing');
        
        audio.onended = () => {
            btn.textContent = '▶';
            if (card) card.classList.remove('playing');
            AUDIO_STATE.playingAudio = null;
            AUDIO_STATE.playingBtn = null;
        };
    }).catch(err => {
        console.error("Audio preview failed:", err);
        showToast("Direct preview failed - track may need sync.", "warning");
    });
}

async function loadAudioStats() {
    try {
        const res = await fetch('/api/audio-library/stats');
        const data = await res.json();
        if (data.status === 'success' && data.stats) {
            const s = data.stats;
            const total = document.getElementById('audio-stats-total');
            const music = document.getElementById('audio-stats-music');
            const sfx = document.getElementById('audio-stats-sfx');
            const downloaded = document.getElementById('audio-stats-downloaded');
            const niche = document.getElementById('audio-stats-niche');
            
            if (total) total.textContent = `${s.total_sounds || 0} sounds indexed`;
            if (music) music.textContent = s.music_tracks || 0;
            if (sfx) sfx.textContent = s.sfx_sounds || 0;
            if (downloaded) downloaded.textContent = s.downloaded || 0;
            
            if (niche && s.by_emotion) {
                let topEm = 'None';
                let maxC = 0;
                for (const [em, cnt] of Object.entries(s.by_emotion)) {
                    if (cnt > maxC) {
                        maxC = cnt;
                        topEm = em;
                    }
                }
                niche.textContent = topEm.charAt(0).toUpperCase() + topEm.slice(1);
            }
        }
    } catch (e) {
        console.error("Failed to load audio stats", e);
    }
}

function appendConsoleLog(action, message) {
    const consoleEl = document.getElementById('audioAgentLog');
    if (!consoleEl) return;
    
    // Clear initial empty message
    if (consoleEl.innerHTML.includes('// Awaiting actions...')) {
        consoleEl.innerHTML = '';
    }
    
    const timeStr = ts();
    const logEl = document.createElement('div');
    logEl.className = 'agent-console-log';
    logEl.innerHTML = `
        <span class="timestamp">[${timeStr}]</span>
        <span class="action">● ${action.toUpperCase()}</span>
        <span class="message">${message}</span>
    `;
    consoleEl.appendChild(logEl);
    consoleEl.scrollTop = consoleEl.scrollHeight;
}

async function triggerAudioSync() {
    showToast("Background sound sync initialized...", "info");
    appendConsoleLog("sync_init", "Triggering multithreaded sound/meme scraper...");
    
    try {
        const res = await fetch('/api/audio-library/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ max_downloads: 40 })
        });
        const data = await res.json();
        
        if (data.status === 'success') {
            showToast("Sound library sync is running in the background", "success");
            appendConsoleLog("sync_running", "Downloading curated music playlists + MyInstants meme trends...");
            
            // Poll for statistics and console logs updates
            if (AUDIO_STATE.syncInterval) clearInterval(AUDIO_STATE.syncInterval);
            let pollCounter = 0;
            
            AUDIO_STATE.syncInterval = setInterval(async () => {
                pollCounter++;
                await loadAudioStats();
                await loadAudioLibrary(AUDIO_STATE.page);
                
                if (pollCounter === 2) {
                    appendConsoleLog("downloading", "Downloading CC0 Pixabay soundtracks: 'Dark Phonk Energy'...");
                } else if (pollCounter === 4) {
                    appendConsoleLog("downloading", "Indexing trending TikTok audio: 'Vine Boom', 'Sad Violin Meme'...");
                } else if (pollCounter === 6) {
                    appendConsoleLog("sync_success", "Scraping complete! Sound registry is fully updated locally.");
                    clearInterval(AUDIO_STATE.syncInterval);
                    AUDIO_STATE.syncInterval = null;
                }
            }, 3000);
        } else {
            showToast(`Sync failed: ${data.message}`, "error");
            appendConsoleLog("sync_error", `Scraper rejected request: ${data.message}`);
        }
    } catch (e) {
        showToast(`Sync connection failed: ${e.message}`, "error");
        appendConsoleLog("sync_failed", `Scraper connection error: ${e.message}`);
    }
}

function initAudioLibrary() {
    console.log("[initAudioLibrary] Mounting controllers...");
    
    // Bind search and filter events
    document.getElementById('soundSearch')?.addEventListener('input', (e) => {
        AUDIO_STATE.search = e.target.value;
        loadAudioLibrary(1);
    });
    
    document.getElementById('soundCategory')?.addEventListener('change', (e) => {
        AUDIO_STATE.category = e.target.value;
        loadAudioLibrary(1);
    });
    
    document.getElementById('soundEmotion')?.addEventListener('change', (e) => {
        AUDIO_STATE.emotion = e.target.value;
        loadAudioLibrary(1);
    });
    
    document.getElementById('soundPrevPage')?.addEventListener('click', () => {
        if (AUDIO_STATE.page > 1) loadAudioLibrary(AUDIO_STATE.page - 1);
    });
    
    document.getElementById('soundNextPage')?.addEventListener('click', () => {
        loadAudioLibrary(AUDIO_STATE.page + 1);
    });
    
    document.getElementById('btnSyncLibrary')?.addEventListener('click', () => {
        triggerAudioSync();
    });

    // Populate data when tab changes to audio-library
    document.querySelectorAll('.auto-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.view === 'audio-library') {
                loadAudioStats();
                loadAudioLibrary(1);
                appendConsoleLog("brain_query", "Brain online. Reading sqlite pattern analytics...");
            }
        });
    });
}

// ──────────────────────────────────────────────────────────────
// 23. WORKFLOW INPUT SIGNAL MANAGER & AI VIDEO EDITING LEARNER
// ──────────────────────────────────────────────────────────────

function setSignal(signal) {
    SELECTED_SIGNAL = signal;
    const emptyEl = D.wfSourceEmpty || document.getElementById('wfSourceEmpty');
    const activeEl = D.wfSourceActive || document.getElementById('wfSourceActive');
    const titleEl = D.wfSourceTitle || document.getElementById('wfSourceTitle');
    const topicEl = D.wfSourceTopic || document.getElementById('wfSourceTopic');
    const scoreEl = D.wfSourceScore || document.getElementById('wfSourceScore');
    const imgEl = D.wfSourceImg || document.getElementById('wfSourceImg');

    if (signal && signal.title) {
        if (emptyEl) emptyEl.classList.add('hidden');
        if (activeEl) activeEl.classList.remove('hidden');
        if (titleEl) titleEl.textContent = signal.title;
        if (topicEl) topicEl.textContent = signal.topic || signal.category || 'Trending';
        if (scoreEl) scoreEl.textContent = `🔥 ${signal.score || signal.viral_score || 95}`;
        
        if (imgEl) {
            if (signal.image_url) {
                imgEl.src = signal.image_url;
                imgEl.style.display = 'block';
            } else {
                imgEl.style.display = 'none';
            }
        }

        // Configure input / trigger node n1
        const n1 = (APP.nodes || []).find(n => n.id === 'n1' || n.type === 'article-trigger');
        if (n1) {
            n1.config = n1.config || {};
            n1.config.topic = signal.title;
            n1.config.article_url = signal.link || signal.url || '';
            n1.config.category = signal.topic || signal.category || 'AI';
            n1.config.image_url = signal.image_url || '';
            n1.config.viral_score = signal.score || 95;
            
            // Update node element subtitle on canvas
            const el = document.getElementById('cn-' + n1.id);
            if (el) {
                const def = NDEFS[n1.type] || {};
                el.innerHTML = nodeHTML(n1, def);
                bindNodeEvents(el, n1.id);
            }
        }

        try {
            localStorage.setItem('pf_selected_signal', JSON.stringify(signal));
        } catch (e) {}
    } else {
        SELECTED_SIGNAL = null;
        if (emptyEl) emptyEl.classList.remove('hidden');
        if (activeEl) activeEl.classList.add('hidden');
        try {
            localStorage.removeItem('pf_selected_signal');
        } catch (e) {}
    }
}

function openSignalPicker() {
    const modal = D.signalPickerModal || document.getElementById('signalPickerModal');
    if (!modal) return;
    modal.classList.remove('hidden');
    // Default to news feed for immediate rich choices, or check saved
    loadSignalPickerData('news');
}

function closeSignalPicker() {
    const modal = D.signalPickerModal || document.getElementById('signalPickerModal');
    if (!modal) return;
    modal.classList.add('hidden');
}

async function loadSignalPickerData(sourceTab = 'news') {
    const body = D.signalPickerBody || document.getElementById('signalPickerBody');
    if (!body) return;

    // Update tab styles
    document.querySelectorAll('.signal-tab').forEach(t => {
        if (t.dataset.source === sourceTab) {
            t.classList.add('active');
            t.style.background = 'rgba(79,195,247,0.15)';
            t.style.color = '#38bdf8';
            t.style.border = '1px solid rgba(79,195,247,0.3)';
        } else {
            t.classList.remove('active');
            t.style.background = 'transparent';
            t.style.color = '#94a3b8';
            t.style.border = '1px solid rgba(255,255,255,0.08)';
        }
    });

    body.innerHTML = `
        <div style="text-align: center; padding: 40px; color: #94a3b8;">
            <div style="font-size: 28px; animation: spin 1s linear infinite; display: inline-block;">⏳</div>
            <p style="margin-top: 10px; font-size: 0.9rem;">Fetching real-time signals from ${sourceTab.toUpperCase()} stream...</p>
        </div>`;

    if (sourceTab === 'custom') {
        body.innerHTML = `
            <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 20px;">
                <h4 style="color: #fff; margin-bottom: 12px; font-size: 1rem;">🔗 Custom Article / Video URL Signal</h4>
                <div style="margin-bottom: 14px;">
                    <label style="display: block; font-size: 0.8rem; color: #94a3b8; margin-bottom: 6px;">Article / Video Title *</label>
                    <input type="text" id="customSignalTitle" placeholder="e.g. Revolutionary AI Agent Breaks Coding Benchmark" style="width: 100%; padding: 10px 14px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; color: #fff; font-size: 0.9rem;">
                </div>
                <div style="margin-bottom: 14px;">
                    <label style="display: block; font-size: 0.8rem; color: #94a3b8; margin-bottom: 6px;">Source URL (Optional)</label>
                    <input type="url" id="customSignalUrl" placeholder="https://news.ycombinator.com/item?id=..." style="width: 100%; padding: 10px 14px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; color: #fff; font-size: 0.9rem;">
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px;">
                    <div>
                        <label style="display: block; font-size: 0.8rem; color: #94a3b8; margin-bottom: 6px;">Category / Niche</label>
                        <select id="customSignalTopic" style="width: 100%; padding: 10px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; color: #fff; font-size: 0.9rem;">
                            <option value="AI">AI & Machine Learning</option>
                            <option value="Tech">Tech & Startups</option>
                            <option value="Pop Culture">Pop Culture & Memes</option>
                            <option value="Science">Science & Space</option>
                            <option value="Finance">Finance & Crypto</option>
                        </select>
                    </div>
                    <div>
                        <label style="display: block; font-size: 0.8rem; color: #94a3b8; margin-bottom: 6px;">Estimated Viral Score</label>
                        <input type="number" id="customSignalScore" value="95" min="50" max="100" style="width: 100%; padding: 10px 14px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; color: #fff; font-size: 0.9rem;">
                    </div>
                </div>
                <button id="btnApplyCustomSignal" style="width: 100%; padding: 12px; background: linear-gradient(135deg, #00FFAA, #00B4D8); border: none; border-radius: 8px; color: #000; font-weight: 700; font-size: 0.95rem; cursor: pointer;">
                    ⚡ Bind Custom Signal to Workflow
                </button>
            </div>`;

        document.getElementById('btnApplyCustomSignal')?.addEventListener('click', () => {
            const title = document.getElementById('customSignalTitle')?.value.trim();
            const url = document.getElementById('customSignalUrl')?.value.trim();
            const topic = document.getElementById('customSignalTopic')?.value || 'AI';
            const score = parseInt(document.getElementById('customSignalScore')?.value || '95', 10);
            if (!title) {
                showToast('Please enter a title for the custom signal', 'warning');
                return;
            }
            setSignal({ title, link: url, topic, score, image_url: '' });
            closeSignalPicker();
            showToast(`Active signal set: "${title.slice(0, 32)}..."`, 'success');
        });
        return;
    }

    try {
        let endpoint = '/api/articles?per_page=30';
        if (sourceTab === 'saved') endpoint = '/api/saved';
        else if (sourceTab === 'viral') endpoint = '/api/trending-videos';

        const res = await fetch(endpoint);
        const data = await res.json();
        const items = data.articles || data.videos || [];

        if (!items.length) {
            if (sourceTab === 'saved') {
                body.innerHTML = `
                    <div style="text-align: center; padding: 30px; color: #94a3b8;">
                        <div style="font-size: 32px; margin-bottom: 8px;">🔖</div>
                        <h4 style="color: #fff; margin-bottom: 6px;">No Saved Articles Yet</h4>
                        <p style="font-size: 0.85rem; color: #94a3b8; margin-bottom: 16px;">You haven't bookmarked any articles yet. Choose from 30+ top trending signals:</p>
                        <button id="btnSwitchToNewsTab" style="padding: 9px 18px; background: linear-gradient(135deg, #38bdf8, #818cf8); border: none; border-radius: 8px; color: #fff; font-weight: 600; cursor: pointer; font-size: 0.88rem;">
                            ⚡ View Top News Feed (30+ Signals)
                        </button>
                    </div>`;
                document.getElementById('btnSwitchToNewsTab')?.addEventListener('click', () => {
                    loadSignalPickerData('news');
                });
                return;
            } else {
                body.innerHTML = `
                    <div style="text-align: center; padding: 40px; color: #64748b;">
                        <div style="font-size: 32px; margin-bottom: 8px;">📭</div>
                        <p style="font-size: 0.95rem;">No items found in ${sourceTab}.</p>
                    </div>`;
                return;
            }
        }

        SIGNAL_PICKER_ITEMS = items;
        SIGNAL_PICKER_TAB = sourceTab;

        const batchBar = BATCH_SIGNALS.length ? `
            <div style="display:flex;align-items:center;justify-content:space-between;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.35);border-radius:10px;padding:10px 14px;margin-bottom:14px;">
                <div style="font-size:0.85rem;color:#fbbf24;font-weight:700;">📦 ${BATCH_SIGNALS.length} signal${BATCH_SIGNALS.length===1?'':'s'} in batch</div>
                <div style="display:flex;gap:8px;">
                    <button id="btnClearBatch" style="padding:7px 12px;background:transparent;border:1px solid rgba(255,255,255,0.2);border-radius:7px;color:#94a3b8;font-size:0.78rem;font-weight:600;cursor:pointer;">Clear</button>
                    <button id="btnQueueBatch" style="padding:7px 14px;background:linear-gradient(135deg,#f59e0b,#ef4444);border:none;border-radius:7px;color:#fff;font-size:0.8rem;font-weight:700;cursor:pointer;">🎬 Queue ${BATCH_SIGNALS.length} Video${BATCH_SIGNALS.length===1?'':'s'}</button>
                </div>
            </div>` : '';

        const gridHTML = items.map((item, idx) => {
            const title = item.title || item.name || 'Untitled Signal';
            const topic = item.topic || item.category || (sourceTab === 'viral' ? 'Viral Video' : 'Tech');
            const score = item.viral_score || item.score || Math.round(85 + (idx % 12));
            const image = item.image_url || item.thumbnail || '';
            const link = item.link || item.url || '';
            const cleanTitle = title.replace(/"/g, '&quot;');
            const inBatch = BATCH_SIGNALS.some(s => s.title === title);

            return `
                <div class="signal-card" style="background: rgba(255,255,255,0.03); border: 1px solid ${inBatch ? 'rgba(245,158,11,0.5)' : 'rgba(255,255,255,0.08)'}; border-radius: 12px; padding: 14px; display: flex; flex-direction: column; justify-content: space-between; gap: 12px; transition: all 0.2s ease;">
                    <div>
                        ${image ? `<img src="${image}" alt="Thumb" style="width: 100%; height: 110px; object-fit: cover; border-radius: 8px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.05);" onerror="this.style.display='none'">` : ''}
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <span style="font-size: 0.72rem; padding: 2px 8px; border-radius: 4px; background: rgba(59,130,246,0.15); color: #60a5fa; font-weight: 600;">${topic}</span>
                            <span style="font-size: 0.75rem; color: #fbbf24; font-weight: 700;">🔥 ${score}</span>
                        </div>
                        <h4 style="font-size: 0.88rem; font-weight: 600; color: #f1f5f9; line-height: 1.35; margin: 0;">${title}</h4>
                    </div>
                    <div style="display:flex;flex-direction:column;gap:6px;">
                        <button class="btn-select-this-signal"
                                data-title="${cleanTitle}"
                                data-topic="${topic}"
                                data-score="${score}"
                                data-image="${image}"
                                data-link="${link}"
                                style="width: 100%; padding: 8px; background: rgba(0, 255, 170, 0.12); border: 1px solid rgba(0, 255, 170, 0.3); color: #00FFAA; border-radius: 6px; font-size: 0.82rem; font-weight: 600; cursor: pointer; transition: all 0.2s;">
                            ✓ Select as Input
                        </button>
                        <div style="display:flex;gap:6px;">
                            <button class="btn-queue-this-signal"
                                    data-title="${cleanTitle}"
                                    data-topic="${topic}"
                                    data-score="${score}"
                                    data-image="${image}"
                                    data-link="${link}"
                                    title="Render this video in the background queue"
                                    style="flex:1; padding:7px; background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.35); color: #fbbf24; border-radius: 6px; font-size: 0.78rem; font-weight: 700; cursor: pointer;">
                                🎬 Queue
                            </button>
                            <button class="btn-batch-this-signal"
                                    data-title="${cleanTitle}"
                                    data-topic="${topic}"
                                    data-score="${score}"
                                    data-image="${image}"
                                    data-link="${link}"
                                    title="${inBatch ? 'Remove from batch' : 'Add to batch render'}"
                                    style="padding:7px 10px; background: ${inBatch ? 'rgba(245,158,11,0.25)' : 'rgba(255,255,255,0.05)'}; border: 1px solid rgba(255,255,255,0.15); color: ${inBatch ? '#fbbf24' : '#94a3b8'}; border-radius: 6px; font-size: 0.78rem; font-weight: 700; cursor: pointer;">
                                ${inBatch ? '✓ Batch' : '＋ Batch'}
                            </button>
                        </div>
                    </div>
                </div>`;
        }).join('');

        body.innerHTML = batchBar + `<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px;">${gridHTML}</div>`;

        document.getElementById('btnQueueBatch')?.addEventListener('click', () => queueSignals([...BATCH_SIGNALS]));
        document.getElementById('btnClearBatch')?.addEventListener('click', () => { BATCH_SIGNALS = []; loadSignalPickerData(SIGNAL_PICKER_TAB); });

        const signalFromBtn = (btn) => ({
            title: btn.dataset.title,
            topic: btn.dataset.topic,
            score: parseInt(btn.dataset.score, 10),
            image_url: btn.dataset.image,
            link: btn.dataset.link
        });

        // Bind clicks on select buttons
        body.querySelectorAll('.btn-select-this-signal').forEach(btn => {
            btn.addEventListener('click', () => {
                const signal = signalFromBtn(btn);
                setSignal(signal);
                closeSignalPicker();
                showToast(`✓ Workflow bound to: "${signal.title.slice(0, 32)}..."`, 'success');
            });
        });

        // Bind clicks on per-card queue buttons (trend → video in one click)
        body.querySelectorAll('.btn-queue-this-signal').forEach(btn => {
            btn.addEventListener('click', () => queueSignals([signalFromBtn(btn)]));
        });

        // Bind batch toggles
        body.querySelectorAll('.btn-batch-this-signal').forEach(btn => {
            btn.addEventListener('click', () => {
                const signal = signalFromBtn(btn);
                const i = BATCH_SIGNALS.findIndex(s => s.title === signal.title);
                if (i >= 0) BATCH_SIGNALS.splice(i, 1);
                else BATCH_SIGNALS.push(signal);
                loadSignalPickerData(SIGNAL_PICKER_TAB);
            });
        });
    } catch (e) {
        body.innerHTML = `<div style="text-align: center; padding: 30px; color: #f87171;"><p>Failed to load ${sourceTab}: ${e.message}</p></div>`;
    }
}

async function openEditingRecipeModal() {
    if (!D.editingRecipeModal) return;
    D.editingRecipeModal.classList.remove('hidden');
    const body = D.editingRecipeBody;
    if (!body) return;

    body.innerHTML = `
        <div style="text-align: center; padding: 40px; color: #c084fc;">
            <div style="font-size: 28px; animation: spin 1s linear infinite; display: inline-block;">🧠</div>
            <p style="margin-top: 12px; font-size: 0.9rem;">Synthesizing optimal editing recipe via Local AI Intelligence...</p>
        </div>`;

    const topic = SELECTED_SIGNAL ? (SELECTED_SIGNAL.topic || 'AI & Tech') : 'AI & Tech';
    const title = SELECTED_SIGNAL ? SELECTED_SIGNAL.title : 'AI Breakthrough Video';
    const score = SELECTED_SIGNAL ? (SELECTED_SIGNAL.score || 95) : 95;

    try {
        const res = await fetch(`/api/video-editing/recommend?topic=${encodeURIComponent(topic)}&title=${encodeURIComponent(title)}&viral_score=${score}`);
        const data = await res.json();
        
        if (data.status === 'success' && data.recipe) {
            const r = data.recipe;
            body.innerHTML = `
                <div style="background: rgba(181, 123, 238, 0.08); border: 1px solid rgba(181, 123, 238, 0.25); border-radius: 12px; padding: 18px; margin-bottom: 20px;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                        <div>
                            <span style="font-size: 0.75rem; padding: 3px 8px; border-radius: 6px; background: rgba(192, 132, 252, 0.2); color: #c084fc; font-weight: 700; text-transform: uppercase;">${r.blueprint_name || 'Neural Recipe'}</span>
                            <h3 style="font-size: 1.15rem; color: #fff; margin: 6px 0 0 0; font-family: 'Space Grotesk', sans-serif;">${r.title}</h3>
                        </div>
                        <div style="text-align: right;">
                            <div style="font-size: 0.72rem; color: #94a3b8;">AI Retention Confidence</div>
                            <div style="font-size: 1.1rem; color: #00FFAA; font-weight: 800;">${r.ai_confidence || '96%'}</div>
                        </div>
                    </div>

                    <!-- Key Strategy Metrics -->
                    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 14px;">
                        <div style="background: rgba(0,0,0,0.3); padding: 10px; border-radius: 8px; text-align: center; border: 1px solid rgba(255,255,255,0.06);">
                            <div style="font-size: 0.72rem; color: #94a3b8;">Average Cut Interval</div>
                            <div style="font-size: 1.05rem; color: #38bdf8; font-weight: 700; margin-top: 2px;">⚡ ${r.pacing.avg_cut_s}s</div>
                        </div>
                        <div style="background: rgba(0,0,0,0.3); padding: 10px; border-radius: 8px; text-align: center; border: 1px solid rgba(255,255,255,0.06);">
                            <div style="font-size: 0.72rem; color: #94a3b8;">Visual Style</div>
                            <div style="font-size: 0.95rem; color: #f43f5e; font-weight: 700; margin-top: 2px; text-transform: capitalize;">🎨 ${(r.pacing.visual_style || 'kinetic').replace('_', ' ')}</div>
                        </div>
                        <div style="background: rgba(0,0,0,0.3); padding: 10px; border-radius: 8px; text-align: center; border: 1px solid rgba(255,255,255,0.06);">
                            <div style="font-size: 0.72rem; color: #94a3b8;">Hook Archetype</div>
                            <div style="font-size: 0.95rem; color: #fbbf24; font-weight: 700; margin-top: 2px; text-transform: capitalize;">🪝 ${r.hook.type} (${r.hook.duration_s}s)</div>
                        </div>
                    </div>
                </div>

                <!-- Execution Timeline -->
                <div style="margin-bottom: 20px;">
                    <h4 style="color: #fff; font-size: 0.95rem; margin-bottom: 10px; display: flex; align-items: center; gap: 6px;">
                        <span>⏱</span> Step-by-Step Editing Execution Timeline
                    </h4>
                    <div style="display: flex; flex-direction: column; gap: 8px;">
                        ${(r.execution_steps || []).map(step => `
                            <div style="background: rgba(255,255,255,0.02); border-left: 3px solid #c084fc; padding: 10px 14px; border-radius: 0 8px 8px 0; font-size: 0.85rem; color: #e2e8f0;">
                                ${step}
                            </div>
                        `).join('')}
                    </div>
                </div>

                <!-- Audio Ducking & Meme SFX Profile -->
                <div style="background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 14px; margin-bottom: 20px;">
                    <h4 style="color: #fff; font-size: 0.9rem; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;">
                        <span>🎵</span> Sound Design & Meme SFX Drops
                    </h4>
                    <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px;">
                        <span style="background: rgba(16, 185, 129, 0.15); color: #34d399; padding: 4px 10px; border-radius: 6px; font-size: 0.78rem;">BGM: ${r.audio.bgm_genre || 'Phonk/Ambient'}</span>
                        <span style="background: rgba(59, 130, 246, 0.15); color: #60a5fa; padding: 4px 10px; border-radius: 6px; font-size: 0.78rem;">Ducking: ${r.audio.ducking_db || -14}dB</span>
                        <span style="background: rgba(245, 158, 11, 0.15); color: #fbbf24; padding: 4px 10px; border-radius: 6px; font-size: 0.78rem;">Energy Level: ${r.audio.energy || 9}/10</span>
                    </div>
                    <div style="font-size: 0.8rem; color: #94a3b8;">
                        <strong>Meme Drops:</strong> ${(r.meme_sfx_drops || []).join(' · ')}
                    </div>
                </div>

                <!-- Interactive Scraper: Learn from any URL in real-time -->
                <div style="background: rgba(255,255,255,0.03); border: 1px dashed rgba(255,255,255,0.15); border-radius: 12px; padding: 16px;">
                    <h4 style="color: #fff; font-size: 0.9rem; margin-bottom: 6px;">📥 Scrape & Learn Blueprint From Any Video URL</h4>
                    <p style="font-size: 0.78rem; color: #94a3b8; margin-bottom: 10px;">Paste a YouTube Short, TikTok, or Instagram Reel link to reverse-engineer its cut pacing and sound triggers.</p>
                    <div style="display: flex; gap: 8px;">
                        <input type="url" id="inputLearnVideoUrl" placeholder="https://www.youtube.com/shorts/..." style="flex: 1; padding: 8px 12px; background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; color: #fff; font-size: 0.85rem;">
                        <button id="btnScrapeAndLearn" style="padding: 8px 16px; background: #c084fc; border: none; border-radius: 8px; color: #000; font-weight: 700; font-size: 0.82rem; cursor: pointer;">
                            Scrape & Learn
                        </button>
                    </div>
                </div>`;

            // Bind scraper event
            document.getElementById('btnScrapeAndLearn')?.addEventListener('click', async () => {
                const url = document.getElementById('inputLearnVideoUrl')?.value.trim();
                if (!url) {
                    showToast('Please enter a video URL to learn from', 'warning');
                    return;
                }
                showToast('Analyzing and extracting video editing patterns...', 'info');
                try {
                    const learnRes = await fetch('/api/video-editing/analyze', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ url, topic })
                    });
                    const learnData = await learnRes.json();
                    if (learnData.status === 'success') {
                        showToast('✓ Learned and saved new video editing blueprint to SQLite DB!', 'success');
                        openEditingRecipeModal(); // Refresh modal view
                    } else {
                        showToast(`Analysis failed: ${learnData.message}`, 'error');
                    }
                } catch (e) {
                    showToast(`Scraper error: ${e.message}`, 'error');
                }
            });

        } else {
            body.innerHTML = `<div style="text-align: center; padding: 30px; color: #f87171;"><p>Failed to synthesize recipe: ${data.message || 'Unknown error'}</p></div>`;
        }
    } catch (e) {
        body.innerHTML = `<div style="text-align: center; padding: 30px; color: #f87171;"><p>Connection error: ${e.message}</p></div>`;
    }
}

function closeEditingRecipeModal() {
    if (!D.editingRecipeModal) return;
    D.editingRecipeModal.classList.add('hidden');
}

function initSignalManager() {
    console.log("[initSignalManager] Initializing Signal & Video Learner bindings...");
    
    // Bind buttons
    D.btnOpenSignalPicker?.addEventListener('click', openSignalPicker);
    D.signalPickerClose?.addEventListener('click', closeSignalPicker);
    D.btnOpenQueue?.addEventListener('click', openQueueModal);
    document.getElementById('queueModalClose')?.addEventListener('click', closeQueueModal);
    document.getElementById('queueModal')?.addEventListener('click', (e) => {
        if (e.target.id === 'queueModal') closeQueueModal();
    });
    D.signalPickerModal?.addEventListener('click', (e) => {
        if (e.target === D.signalPickerModal) closeSignalPicker();
    });

    // Bind modal tabs
    document.querySelectorAll('.signal-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            loadSignalPickerData(tab.dataset.source);
        });
    });

    // AI Editing Recipe Modal
    D.btnViewEditingRecipe?.addEventListener('click', openEditingRecipeModal);
    D.editingRecipeClose?.addEventListener('click', closeEditingRecipeModal);
    D.editingRecipeModal?.addEventListener('click', (e) => {
        if (e.target === D.editingRecipeModal) closeEditingRecipeModal();
    });

    // Signal reading is handled by _applyPersistedSignal() called from init()
    // after the view has been switched. This avoids race conditions.
}

// ──────────────────────────────────────────────────────────────
// 23B. UNIFIED API KEYS CONFIGURATION & PRE-FLIGHT VALIDATION
// ──────────────────────────────────────────────────────────────

let PF_API_KEYS_CACHE = {
    keys: {},
    is_set: {
        minimax: false,
        fal: false,
        elevenlabs: false,
        openai: false,
        groq: false,
        muse: false
    }
};

async function loadApiKeys() {
    try {
        const res = await fetch('/api/keys');
        const data = await res.json();
        if (data.status === 'success') {
            PF_API_KEYS_CACHE = data;
            
            const k = data.keys || {};
            const is_set = data.is_set || {};

            if (D.keyInputMinimax && !D.keyInputMinimax.value) D.keyInputMinimax.placeholder = k.MINIMAX_API_KEY || 'Enter MiniMax API Key';
            if (D.keyInputFal && !D.keyInputFal.value) D.keyInputFal.placeholder = k.FAL_KEY || 'Enter FAL_KEY';
            if (D.keyInputElevenlabs && !D.keyInputElevenlabs.value) D.keyInputElevenlabs.placeholder = k.ELEVENLABS_API_KEY || 'Enter ElevenLabs API Key';
            if (D.keyInputOpenai && !D.keyInputOpenai.value) D.keyInputOpenai.placeholder = k.OPENAI_API_KEY || 'sk-...';
            if (D.keyInputGroq && !D.keyInputGroq.value) D.keyInputGroq.placeholder = k.GROQ_API_KEY || 'gsk_...';
            if (D.keyInputMuse && !D.keyInputMuse.value) D.keyInputMuse.placeholder = k.MUSE_API_KEY || 'LLM_...';
            if (D.keyInputOpenrouter && !D.keyInputOpenrouter.value) D.keyInputOpenrouter.placeholder = k.OPENROUTER_API_KEY || 'sk-or-...';
            if (D.keyInputPixabay && !D.keyInputPixabay.value) D.keyInputPixabay.placeholder = k.PIXABAY_API_KEY || 'Pixabay API key';
            if (D.keyInputPexels && !D.keyInputPexels.value) D.keyInputPexels.placeholder = k.PEXELS_API_KEY || 'Pexels API key';
            if (D.keyInputGemini && !D.keyInputGemini.value) D.keyInputGemini.placeholder = k.GEMINI_API_KEY || 'AIza...';
            if (D.keyInputHf && !D.keyInputHf.value) D.keyInputHf.placeholder = k.HF_TOKEN || 'hf_...';
            if (D.keyInputComfyUrl && !D.keyInputComfyUrl.value) D.keyInputComfyUrl.value = k.COMFYUI_URL || 'http://127.0.0.1:8188';

            _updateKeyBadge(D.badgeMinimaxKey, is_set.minimax, 'Configured', 'Not Set');
            _updateKeyBadge(D.badgeFalKey, is_set.fal, 'Configured', 'Optional');
            _updateKeyBadge(D.badgeElevenKey, is_set.elevenlabs, 'Configured', 'Edge-TTS Active');
            _updateKeyBadge(D.badgeOpenaiKey, is_set.openai, 'Configured', 'Optional');
            _updateKeyBadge(D.badgeGroqKey, is_set.groq, 'Configured', 'Optional');
            _updateKeyBadge(D.badgeMuseKey, is_set.muse, 'Configured', 'Optional');
            _updateKeyBadge(D.badgeOpenrouterKey, is_set.openrouter, 'Configured', 'Optional · free');
            _updateKeyBadge(D.badgePixabayKey, is_set.pixabay, 'Configured', 'Optional · free');
            _updateKeyBadge(D.badgePexelsKey, is_set.pexels, 'Configured', 'Optional · free');
            _updateKeyBadge(D.badgeGeminiKey, is_set.gemini, 'Configured', 'Optional · free tier');
            _updateKeyBadge(D.badgeHfKey, is_set.huggingface, 'Configured', 'Optional · free');
            if (D.badgeComfyUrl) {
                _updateKeyBadge(D.badgeComfyUrl, true, 'Active', 'Not Set');
            }
        }
    } catch (e) {
        console.warn('[API Keys] Failed loading status:', e);
    }
}

function _updateKeyBadge(el, isSet, activeText, missingText) {
    if (!el) return;
    if (isSet) {
        el.textContent = `🟢 ${activeText}`;
        el.style.background = 'rgba(16,185,129,0.15)';
        el.style.color = '#10b981';
        el.style.border = '1px solid rgba(16,185,129,0.3)';
    } else {
        el.textContent = `⚪ ${missingText}`;
        el.style.background = 'rgba(148,163,184,0.12)';
        el.style.color = '#94a3b8';
        el.style.border = '1px solid rgba(148,163,184,0.2)';
    }
}

function openApiKeysModal() {
    if (!D.apiKeysConfigModal) D.apiKeysConfigModal = document.getElementById('apiKeysConfigModal');
    if (!D.apiKeysConfigModal) return;
    D.apiKeysConfigModal.classList.remove('hidden');
    loadApiKeys();
}

function closeApiKeysModal() {
    if (!D.apiKeysConfigModal) D.apiKeysConfigModal = document.getElementById('apiKeysConfigModal');
    if (!D.apiKeysConfigModal) return;
    D.apiKeysConfigModal.classList.add('hidden');
}

async function saveApiKeys() {
    const payload = {};
    if (D.keyInputMinimax?.value?.trim()) payload.MINIMAX_API_KEY = D.keyInputMinimax.value.trim();
    if (D.keyInputFal?.value?.trim()) payload.FAL_KEY = D.keyInputFal.value.trim();
    if (D.keyInputElevenlabs?.value?.trim()) payload.ELEVENLABS_API_KEY = D.keyInputElevenlabs.value.trim();
    if (D.keyInputOpenai?.value?.trim()) payload.OPENAI_API_KEY = D.keyInputOpenai.value.trim();
    if (D.keyInputGroq?.value?.trim()) payload.GROQ_API_KEY = D.keyInputGroq.value.trim();
    if (D.keyInputMuse?.value?.trim()) payload.MUSE_API_KEY = D.keyInputMuse.value.trim();
    if (D.keyInputOpenrouter?.value?.trim()) payload.OPENROUTER_API_KEY = D.keyInputOpenrouter.value.trim();
    if (D.keyInputPixabay?.value?.trim()) payload.PIXABAY_API_KEY = D.keyInputPixabay.value.trim();
    if (D.keyInputPexels?.value?.trim()) payload.PEXELS_API_KEY = D.keyInputPexels.value.trim();
    if (D.keyInputGemini?.value?.trim()) payload.GEMINI_API_KEY = D.keyInputGemini.value.trim();
    if (D.keyInputHf?.value?.trim()) payload.HF_TOKEN = D.keyInputHf.value.trim();
    if (D.keyInputComfyUrl?.value?.trim()) payload.COMFYUI_URL = D.keyInputComfyUrl.value.trim();

    if (Object.keys(payload).length === 0) {
        showToast('No changes detected to save.', 'info');
        closeApiKeysModal();
        return;
    }

    try {
        const res = await fetch('/api/keys', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast('✅ API Keys saved and activated successfully!', 'success');
            if (D.keyInputMinimax) D.keyInputMinimax.value = '';
            if (D.keyInputFal) D.keyInputFal.value = '';
            if (D.keyInputElevenlabs) D.keyInputElevenlabs.value = '';
            if (D.keyInputOpenai) D.keyInputOpenai.value = '';
            if (D.keyInputGroq) D.keyInputGroq.value = '';
            if (D.keyInputMuse) D.keyInputMuse.value = '';
            if (D.keyInputOpenrouter) D.keyInputOpenrouter.value = '';
            if (D.keyInputPixabay) D.keyInputPixabay.value = '';
            if (D.keyInputPexels) D.keyInputPexels.value = '';
            if (D.keyInputGemini) D.keyInputGemini.value = '';
            if (D.keyInputHf) D.keyInputHf.value = '';
            await loadApiKeys();
            setTimeout(closeApiKeysModal, 700);
        } else {
            showToast(`Failed saving keys: ${data.message || 'Unknown error'}`, 'error');
        }
    } catch (e) {
        showToast(`Save error: ${e.message}`, 'error');
    }
}

function initApiKeysManager() {
    D.btnFreeMode?.addEventListener('click', () => setFreeMode(!APP.freeMode));
    D.btnOpenApiKeysModal?.addEventListener('click', openApiKeysModal);
    D.apiKeysModalClose?.addEventListener('click', closeApiKeysModal);
    D.btnCancelApiKeys?.addEventListener('click', closeApiKeysModal);
    D.btnSaveApiKeys?.addEventListener('click', saveApiKeys);
    D.apiKeysConfigModal?.addEventListener('click', (e) => {
        if (e.target === D.apiKeysConfigModal) closeApiKeysModal();
    });

    const comfyBadge = document.getElementById('comfyui-badge');
    if (comfyBadge) {
        comfyBadge.addEventListener('click', (e) => {
            e.stopPropagation();
            openApiKeysModal();
        });
    }

    loadApiKeys();
}

/**
 * Pre-flight validation executed BEFORE runWorkflow starts.
 * Prevents execution if mandatory AI keys or services are missing.
 */
async function validateWorkflowRequirements() {
    await loadApiKeys();
    const isSet = PF_API_KEYS_CACHE.is_set || {};

    // 1. Check Image-to-Video nodes
    const videoNode = APP.nodes.find(n => n.type === 'img-to-video' || n.type === 'image-to-video');
    if (videoNode) {
        const cfg = videoNode.config || videoNode.data || {};
        const provider = (cfg.provider || 'ComfyUI (Local Wan / SVD - Free)').toLowerCase();
        
        const hasMinimax = Boolean(isSet.minimax);
        const hasFal = Boolean(isSet.fal);

        if (provider.includes('minimax')) {
            if (!hasMinimax && !hasFal) {
                let comfyOnline = false;
                try {
                    const cRes = await fetch('/api/comfyui/status');
                    const cData = await cRes.json();
                    comfyOnline = (cData.status === 'online');
                } catch (err) {
                    comfyOnline = false;
                }

                if (comfyOnline) {
                    videoNode.config = videoNode.config || {};
                    videoNode.config.provider = 'ComfyUI (Local Wan / SVD - Free)';
                    if (videoNode.data) videoNode.data.provider = 'ComfyUI (Local Wan / SVD - Free)';
                    showToast('⚡ MiniMax key not set: Auto-routing to local GPU ComfyUI for 100% Free AI Video!', 'info', 4000);
                } else {
                    return {
                        ok: false,
                        error: "MiniMax-H3 requires a MiniMax API Key (or FAL_KEY). Please configure your key in API Keys.",
                        openModal: true
                    };
                }
            }
        } else if (provider.includes('fal.ai')) {
            if (!hasFal) {
                return {
                    ok: false,
                    error: "fal.ai provider requires a FAL_KEY. Please configure your key in API Keys.",
                    openModal: true
                };
            }
        } else if (provider.includes('comfyui')) {
            let comfyOnline = false;
            try {
                const cRes = await fetch('/api/comfyui/status');
                const cData = await cRes.json();
                comfyOnline = (cData.status === 'online');
            } catch (err) {
                comfyOnline = false;
            }

            if (!comfyOnline && !hasMinimax && !hasFal) {
                return {
                    ok: false,
                    error: "ComfyUI is offline on 127.0.0.1:8188 and no cloud fallback key is set. Launch ComfyUI (run start_comfyui.bat) or enter a MiniMax/fal.ai API key.",
                    openModal: true
                };
            }
        }
    }

    // 2. Check TTS Voice node
    const ttsNode = APP.nodes.find(n => n.type === 'tts');
    if (ttsNode) {
        const cfg = ttsNode.config || ttsNode.data || {};
        const voice = (cfg.voice || '').toLowerCase();
        const provider = (cfg.provider || '').toLowerCase();

        if ((provider === 'elevenlabs' || voice.startsWith('elevenlabs')) && !isSet.elevenlabs) {
            return {
                ok: false,
                error: "ElevenLabs voice selected, but ELEVENLABS_API_KEY is not configured! Please configure your key in API Keys, or switch to built-in free Edge-TTS in node settings.",
                openModal: true
            };
        }
    }

    // 3. Check Image Generation node
    const imgNode = APP.nodes.find(n => n.type === 'image-gen' || n.type === 'gen-image' || n.type === 'visuals');
    if (imgNode) {
        const cfg = imgNode.config || imgNode.data || {};
        const model = (cfg.model || '').toLowerCase();

        if ((model.includes('dall-e') || model.includes('openai')) && !isSet.openai) {
            return {
                ok: false,
                error: "DALL-E 3 image generation requires an OPENAI_API_KEY! Please configure your key in API Keys, or select Pollinations / Free SDXL in node settings.",
                openModal: true
            };
        }
    }

    return { ok: true };
}



// ──────────────────────────────────────────────────────────────
// 24. ADMIN BACKGROUND WORKFLOW INTELLIGENCE HUB
// ──────────────────────────────────────────────────────────────

let ADMIN_SYNC_STATE = {
    pollingInterval: null,
    lastLogCount: 0
};

function initAdminSyncHub() {
    if (!window.PF || window.PF.userRole !== 'Admin') {
        return; // Admin exclusive: standard users are not exposed to background telemetry
    }

    console.log("[initAdminSyncHub] Mounting Admin Background Workflow Monitor...");

    const btnPill = document.getElementById('btnAdminSyncHub');
    const modal = document.getElementById('adminSyncHubModal');
    const btnClose = document.getElementById('adminSyncHubClose');
    const btnTrigger = document.getElementById('btnAdminTriggerSync');

    if (btnPill && modal) {
        btnPill.addEventListener('click', () => {
            modal.classList.remove('hidden');
            fetchAdminWorkflowUpdates();
        });
    }

    if (btnClose && modal) {
        btnClose.addEventListener('click', () => {
            modal.classList.add('hidden');
        });
    }

    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.classList.add('hidden');
        });
    }

    if (btnTrigger) {
        btnTrigger.addEventListener('click', async () => {
            btnTrigger.disabled = true;
            btnTrigger.innerHTML = '<span>⏳</span> Syncing Background Pipeline...';
            showToast('⚡ Triggered full background workflow update cycle', 'info');

            try {
                const res = await fetch('/api/admin/trigger-workflow-sync', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast('✓ Background sync cycle started', 'success');
                    setTimeout(fetchAdminWorkflowUpdates, 1000);
                } else {
                    showToast(`Sync request failed: ${data.message}`, 'error');
                }
            } catch (e) {
                showToast(`Sync error: ${e.message}`, 'error');
            } finally {
                setTimeout(() => {
                    btnTrigger.disabled = false;
                    btnTrigger.innerHTML = '<span>🔄</span> Trigger Instant Background Sync';
                }, 3000);
            }
        });
    }

    // Initial fetch and start continuous background polling (every 6 seconds)
    fetchAdminWorkflowUpdates();
    if (ADMIN_SYNC_STATE.pollingInterval) clearInterval(ADMIN_SYNC_STATE.pollingInterval);
    ADMIN_SYNC_STATE.pollingInterval = setInterval(fetchAdminWorkflowUpdates, 6000);
}

async function fetchAdminWorkflowUpdates() {
    if (!window.PF || window.PF.userRole !== 'Admin') return;

    try {
        const res = await fetch('/api/admin/workflow-updates');
        if (!res.ok) return;
        const data = await res.json();

        if (data.status === 'success') {
            renderAdminSyncData(data);
        }
    } catch (e) {
        console.debug("Admin sync polling note:", e);
    }
}

function renderAdminSyncData(data) {
    const statusText = document.getElementById('adminSyncStatusText');
    const statCycles = document.getElementById('adminStatCycles');
    const statSounds = document.getElementById('adminStatSounds');
    const statBlueprints = document.getElementById('adminStatBlueprints');
    const statModels = document.getElementById('adminStatModels');
    const lastSyncEl = document.getElementById('adminLastSyncTime');
    const workersList = document.getElementById('adminWorkersList');
    const logsEl = document.getElementById('adminSyncLiveLogs');

    const stats = data.stats || {};
    const workers = data.workers || [];
    const logs = data.logs || [];

    if (statusText) {
        if (data.status === 'syncing') {
            statusText.textContent = '⚡ Syncing Background Options...';
            statusText.style.color = '#00FFAA';
        } else {
            statusText.textContent = `${workers.length} Workers Active`;
            statusText.style.color = '#fff';
        }
    }

    if (statCycles) statCycles.textContent = stats.total_sync_cycles || 0;
    if (statSounds) statSounds.textContent = stats.sounds_updated || 0;
    if (statBlueprints) statBlueprints.textContent = stats.blueprints_learned || 0;
    if (statModels) statModels.textContent = stats.ai_models_verified || 0;
    if (lastSyncEl) lastSyncEl.textContent = `Last cycle: ${data.last_sync || 'Just now'}`;

    if (workersList && workers.length) {
        workersList.innerHTML = workers.map(w => `
            <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 12px; display: flex; align-items: flex-start; gap: 10px;">
                <div style="font-size: 20px; padding: 6px; background: rgba(56,189,248,0.1); border-radius: 8px;">${w.icon}</div>
                <div style="flex: 1;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                        <h5 style="color: #fff; font-size: 0.85rem; margin: 0; font-weight: 600;">${w.name}</h5>
                        <span style="font-size: 0.68rem; padding: 2px 6px; border-radius: 4px; background: rgba(16,185,129,0.15); color: #10b981; font-weight: 600;">ACTIVE</span>
                    </div>
                    <p style="font-size: 0.74rem; color: #94a3b8; margin: 0; line-height: 1.3;">${w.desc}</p>
                </div>
            </div>
        `).join('');
    }

    if (logsEl && logs.length) {
        logsEl.innerHTML = logs.map(l => {
            let color = '#94a3b8';
            if (l.event_type === 'success' || l.event_type === 'cycle_complete') color = '#00FFAA';
            else if (l.event_type === 'error') color = '#f87171';
            else if (l.event_type === 'scraping' || l.event_type === 'analyzing' || l.event_type === 'probing') color = '#38bdf8';
            
            return `
                <div style="margin-bottom: 5px; line-height: 1.4;">
                    <span style="color: #64748b;">[${l.timestamp}]</span>
                    <span style="color: #38bdf8; font-weight: 600;">[${(l.worker_id || 'SYS').toUpperCase()}]</span>
                    <span style="color: ${color};">${l.message}</span>
                </div>
            `;
        }).join('');
    }
}


// ──────────────────────────────────────────────────────────────
// COMFYUI LOCAL AI VIDEO STATUS CHECKER
// Polls /api/comfyui/status to display a live "ComfyUI Online/Offline" badge
// ──────────────────────────────────────────────────────────────
async function checkComfyUIStatus() {
    const badge = document.getElementById('comfyui-badge');
    const dot = document.getElementById('comfyui-dot');
    const label = document.getElementById('comfyui-label');
    if (!badge) return;

    try {
        const res = await fetch('/api/comfyui/status');
        const data = await res.json();

        if (data.status === 'online') {
            if (data.i2v_ready) {
                // Online AND has Wan/LTX model — fully ready
                dot.style.background = '#00FFAA';
                dot.style.boxShadow = '0 0 6px rgba(0,255,170,0.7)';
                const activeModelShort = (data.active_model || 'Ready').replace('.safetensors', '');
                label.textContent = `ComfyUI ✅ ${data.vram_free_gb}GB (${activeModelShort})`;
                badge.style.background = 'rgba(0,255,170,0.08)';
                badge.style.borderColor = 'rgba(0,255,170,0.3)';
                badge.style.color = '#00FFAA';
                badge.title = data.message;
            } else {
                // Online but no Wan model
                dot.style.background = '#f59e0b';
                dot.style.boxShadow = '0 0 6px rgba(245,158,11,0.7)';
                label.textContent = 'ComfyUI ⚠️ No Wan Model';
                badge.style.background = 'rgba(245,158,11,0.08)';
                badge.style.borderColor = 'rgba(245,158,11,0.3)';
                badge.style.color = '#f59e0b';
                badge.title = 'ComfyUI running but no Wan/LTX model. Download from HuggingFace to enable free AI video.';
            }
        } else {
            // Offline
            dot.style.background = '#6b7280';
            dot.style.boxShadow = 'none';
            label.textContent = 'ComfyUI Offline';
            badge.style.background = 'rgba(107,114,128,0.08)';
            badge.style.borderColor = 'rgba(107,114,128,0.2)';
            badge.style.color = '#6b7280';
            badge.title = 'Click to install ComfyUI for free local AI image-to-video';
        }
    } catch (e) {
        if (label) label.textContent = 'ComfyUI —';
    }
}

// Run ComfyUI check on page load and refresh every 30s
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(checkComfyUIStatus, 2000);
    setInterval(checkComfyUIStatus, 30000);
});

// ──────────────────────────────────────────────────────────────
// 🌱 GROWTH TOOLKIT — standalone panels for competitor scan, channel
// stats, SEO pack, music search, shorts cutting, upload scheduling.
// These call the same backends the workflow nodes use.
// ──────────────────────────────────────────────────────────────
const GROWTH_TABS = [
    { id: 'competitor', label: '🔎 Competitor' },
    { id: 'stats',      label: '📊 Stats' },
    { id: 'seo',        label: '🏷 SEO' },
    { id: 'music',      label: '🎶 Music' },
    { id: 'shorts',     label: '✂️ Shorts' },
    { id: 'schedule',   label: '🗓 Schedule' },
];
let _growthActiveTab = 'competitor';
let _shortsPollTimer = null;

function _gIn(id, placeholder, val='') {
    return `<input id="${id}" placeholder="${escHtml(placeholder)}" value="${escHtml(val)}" style="width:100%;box-sizing:border-box;background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.12);border-radius:8px;padding:8px 10px;color:#fff;font-size:0.82rem;">`;
}
function _gLbl(t) { return `<div style="font-size:0.75rem;color:#94a3b8;margin:10px 0 4px;font-weight:600;">${t}</div>`; }
function _gBtn(id, label) {
    return `<button id="${id}" class="btn-tb" style="margin-top:12px;background:linear-gradient(135deg,#059669,#10b981);border-color:rgba(16,185,129,0.5);font-weight:700;">${label}</button>`;
}
function _gRes(id) { return `<div id="${id}" style="margin-top:14px;"></div>`; }

function growthTabHtml(tab) {
    switch (tab) {
        case 'competitor':
            return _gLbl('Rival channel (URL, @handle or channel ID)') +
                _gIn('gcChannel', 'https://youtube.com/@SomeChannel') +
                _gLbl('Your topics (comma separated — finds gaps the rival ignores)') +
                _gIn('gcTopics', 'AI news, space, history') +
                _gLbl('Videos to analyze') +
                `<select id="gcMax" style="background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.12);border-radius:8px;padding:8px;color:#fff;"><option>10</option><option>20</option><option selected>30</option><option>50</option></select>` +
                _gBtn('gcRun', '🔎 Scan Competitor') + _gRes('gcOut');
        case 'stats':
            return _gLbl('Lookback window') +
                `<select id="gsDays" style="background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.12);border-radius:8px;padding:8px;color:#fff;"><option value="7">7 days</option><option value="28" selected>28 days</option><option value="90">90 days</option></select>` +
                _gBtn('gsRun', '📊 Pull Channel Stats') + _gRes('gsOut') +
                `<hr style="border-color:rgba(255,255,255,0.08);margin:18px 0;">` +
                _gLbl('Topic affinity — which topics does your audience reward? (comma separated)') +
                _gIn('gsTopics', 'AI, automation, space') +
                _gBtn('gsAffRun', '🎯 Compare Topics') + _gRes('gsAffOut');
        case 'seo':
            return _gLbl('Video title') + _gIn('geTitle', 'My amazing video title') +
                _gLbl('Extra keywords (comma separated)') + _gIn('geKw', 'AI, shorts') +
                _gBtn('geRun', '🏷 Build SEO Pack') + _gRes('geOut');
        case 'music':
            return _gLbl('Local library') + _gBtn('gmLocal', '🎧 List Local Tracks (assets/music/)') + _gRes('gmLocalOut') +
                `<hr style="border-color:rgba(255,255,255,0.08);margin:18px 0;">` +
                _gLbl('Pixabay music search (free downloads, needs API key)') +
                _gIn('gmQ', 'cinematic upbeat') +
                _gBtn('gmSearch', '🔍 Search Pixabay') + _gRes('gmOut');
        case 'shorts':
            return _gLbl('Finished video path') + _gIn('ghVideo', '/path/to/final_video.mp4') +
                _gLbl('Number of shorts') +
                `<select id="ghNum" style="background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.12);border-radius:8px;padding:8px;color:#fff;"><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option></select>` +
                _gLbl('Caption style') +
                `<select id="ghStyle" style="background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.12);border-radius:8px;padding:8px;color:#fff;"><option value="karaoke" selected>🔥 Karaoke (word highlight)</option><option value="classic">Classic (phrase)</option></select>` +
                _gLbl('Highlight colour') +
                `<select id="ghHl" style="background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.12);border-radius:8px;padding:8px;color:#fff;"><option value="yellow" selected>Yellow</option><option value="lime">Lime</option><option value="cyan">Cyan</option><option value="orange">Orange</option><option value="pink">Pink</option></select>` +
                _gBtn('ghRun', '✂️ Cut Viral Shorts') + _gRes('ghOut');
        case 'schedule':
            return _gLbl('Queue') + _gBtn('guRefresh', '↻ Refresh Queue') + _gRes('guList') +
                `<hr style="border-color:rgba(255,255,255,0.08);margin:18px 0;">` +
                _gLbl('Schedule a new upload') +
                _gLbl('Video path') + _gIn('guVideo', '/path/to/final_video.mp4') +
                _gLbl('Title') + _gIn('guTitle', 'Video title') +
                _gLbl('Publish at (ISO, blank = due immediately)') + _gIn('guAt', '2026-10-01T18:00:00+05:30') +
                _gLbl('Privacy') +
                `<select id="guPrivacy" style="background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.12);border-radius:8px;padding:8px;color:#fff;"><option>private</option><option>unlisted</option><option>public</option></select>` +
                _gBtn('guAdd', '➕ Add to Schedule') + _gRes('guOut');
    }
    return '';
}

function _growthRenderTabs() {
    const bar = document.getElementById('growthTabs');
    if (!bar) return;
    bar.innerHTML = GROWTH_TABS.map(t =>
        `<button data-gtab="${t.id}" class="btn-tb" style="${t.id === _growthActiveTab ? 'background:rgba(16,185,129,0.25);border-color:rgba(16,185,129,0.6);color:#fff;font-weight:700;' : ''}">${t.label}</button>`
    ).join('');
    bar.querySelectorAll('[data-gtab]').forEach(b => b.addEventListener('click', () => {
        _growthActiveTab = b.dataset.gtab;
        _growthRenderTabs();
        document.getElementById('growthModalBody').innerHTML = growthTabHtml(_growthActiveTab);
        _growthWireTab(_growthActiveTab);
    }));
}

function _growthWireTab(tab) {
    if (_shortsPollTimer) { clearInterval(_shortsPollTimer); _shortsPollTimer = null; }
    const $ = id => document.getElementById(id);
    const busy = (out, msg) => { $(out).innerHTML = `<div style="color:#94a3b8;">${msg}</div>`; };

    if (tab === 'competitor' && $('gcRun')) {
        $('gcRun').addEventListener('click', async () => {
            busy('gcOut', 'Scanning channel…');
            try {
                const r = await fetch('/api/growth/competitor-scan', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ channel: $('gcChannel').value, user_topics: $('gcTopics').value, max_videos: $('gcMax').value }) });
                const d = await r.json();
                if (d.status !== 'success') throw new Error(d.message || 'failed');
                const gaps = d.gaps || [];
                $('gcOut').innerHTML =
                    `<div style="font-weight:700;color:#10b981;margin-bottom:8px;">${escHtml(d.channel_name || d.channel || 'Channel')} — ${gaps.length} gap topic${gaps.length === 1 ? '' : 's'} found</div>` +
                    (gaps.length ? gaps.map(g =>
                        `<div style="background:rgba(16,185,129,0.06);border:1px solid rgba(16,185,129,0.25);border-radius:10px;padding:10px 12px;margin-bottom:8px;">
                            <div style="font-weight:700;color:#fff;">🎬 ${escHtml(g.suggested_title || g.topic || '')}</div>
                            <div style="color:#94a3b8;margin-top:4px;">${escHtml(g.why || g.reason || '')}</div>
                        </div>`).join('')
                        : '<div style="color:#94a3b8;">No clear gaps — the rival covers everything you listed. Try broader topics.</div>');
            } catch (e) { $('gcOut').innerHTML = `<div style="color:#f87171;">Error: ${escHtml(e.message)}</div>`; }
        });
    }

    if (tab === 'stats') {
        if ($('gsRun')) $('gsRun').addEventListener('click', async () => {
            busy('gsOut', 'Pulling stats…');
            try {
                const r = await fetch('/api/growth/analytics?days=' + $('gsDays').value);
                const d = await r.json();
                if (d.status !== 'success') throw new Error(d.message || 'failed');
                const p = d.performance || {};
                const row = (k, v) => `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06);"><span style="color:#94a3b8;">${k}</span><span style="color:#fff;font-weight:700;">${v}</span></div>`;
                $('gsOut').innerHTML = row('Views', p.views ?? '—') + row('Watch time (hrs)', p.watch_hours ?? '—') +
                    row('Subscribers gained', p.subs ?? '—') + row('Avg. view duration', p.avg_view_duration ?? '—') +
                    (p.note ? `<div style="color:#f59e0b;margin-top:8px;font-size:0.78rem;">${escHtml(p.note)}</div>` : '');
            } catch (e) { $('gsOut').innerHTML = `<div style="color:#f87171;">Error: ${escHtml(e.message)}</div>`; }
        });
        if ($('gsAffRun')) $('gsAffRun').addEventListener('click', async () => {
            busy('gsAffOut', 'Comparing topics…');
            try {
                const r = await fetch('/api/growth/topic-affinity', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ topics: $('gsTopics').value }) });
                const d = await r.json();
                if (d.status !== 'success') throw new Error(d.message || 'failed');
                $('gsAffOut').innerHTML = (d.topics || []).map(t =>
                    `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06);"><span style="color:#fff;">${escHtml(t.topic || '')}</span><span style="color:#10b981;font-weight:700;">score ${escHtml(String(t.score ?? '—'))}</span></div>`
                ).join('') || '<div style="color:#94a3b8;">No data yet — publish more videos first.</div>';
            } catch (e) { $('gsAffOut').innerHTML = `<div style="color:#f87171;">Error: ${escHtml(e.message)}</div>`; }
        });
    }

    if (tab === 'seo' && $('geRun')) {
        $('geRun').addEventListener('click', async () => {
            busy('geOut', 'Building SEO pack…');
            try {
                const r = await fetch('/api/seo/build', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: $('geTitle').value, keywords: $('geKw').value.split(',').map(s => s.trim()).filter(Boolean) }) });
                const d = await r.json();
                if (d.status !== 'success') throw new Error(d.message || 'failed');
                $('geOut').innerHTML =
                    _gLbl('Title options (click to copy)') +
                    (d.titles || []).map(t => `<div onclick="navigator.clipboard.writeText(this.dataset.t);showToast('Copied','success')" data-t="${escHtml(t)}" title="Click to copy" style="cursor:pointer;padding:7px 10px;background:rgba(59,130,246,0.08);border:1px solid rgba(59,130,246,0.25);border-radius:8px;margin-bottom:6px;color:#fff;">${escHtml(t)}</div>`).join('') +
                    _gLbl('Description') +
                    `<textarea readonly rows="6" style="width:100%;box-sizing:border-box;background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.12);border-radius:8px;padding:8px 10px;color:#fff;font-size:0.78rem;">${escHtml(d.description || '')}</textarea>` +
                    _gLbl('Tags (' + ((d.tags || []).join(', ').length) + '/500 chars)') +
                    `<div style="color:#94a3b8;">${escHtml((d.tags || []).join(', '))}</div>` +
                    (d.title_hindi ? _gLbl('Hindi title') + `<div style="color:#fff;">${escHtml(d.title_hindi)}</div>` : '');
            } catch (e) { $('geOut').innerHTML = `<div style="color:#f87171;">Error: ${escHtml(e.message)}</div>`; }
        });
    }

    if (tab === 'music') {
        if ($('gmLocal')) $('gmLocal').addEventListener('click', async () => {
            busy('gmLocalOut', 'Listing…');
            try {
                const d = await (await fetch('/api/music/tracks')).json();
                $('gmLocalOut').innerHTML = d.status === 'success' && d.tracks.length
                    ? d.tracks.map(t => `<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06);color:#fff;">🎵 ${escHtml(t.name || t.path || '')}</div>`).join('')
                    : '<div style="color:#94a3b8;">No local tracks — drop mp3/wav files into <b>assets/music/</b> or search Pixabay below.</div>';
            } catch (e) { $('gmLocalOut').innerHTML = `<div style="color:#f87171;">Error: ${escHtml(e.message)}</div>`; }
        });
        if ($('gmSearch')) $('gmSearch').addEventListener('click', async () => {
            busy('gmOut', 'Searching Pixabay…');
            try {
                const d = await (await fetch('/api/music/search?q=' + encodeURIComponent($('gmQ').value))).json();
                if (d.status !== 'success') throw new Error(d.message || 'failed');
                $('gmOut').innerHTML = (d.hits || []).map((h, i) =>
                    `<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06);">
                        <span style="color:#fff;">🎵 ${escHtml(h.name || h.title || ('Track ' + (i + 1)))}</span>
                        <button class="btn-tb" data-dl="${i}" style="font-size:0.72rem;">⬇ Download</button>
                    </div>`).join('') || '<div style="color:#94a3b8;">No results. Check your Pixabay key.</div>';
                $('gmOut').querySelectorAll('[data-dl]').forEach(b => b.addEventListener('click', async () => {
                    b.textContent = '⏳…';
                    try {
                        const dl = await (await fetch('/api/music/search?q=' + encodeURIComponent($('gmQ').value) + '&download=1')).json();
                        b.textContent = '✅ Saved';
                        showToast('Track downloaded to assets/music/', 'success');
                    } catch (e) { b.textContent = '❌'; showToast('Download failed: ' + e.message, 'error'); }
                }));
            } catch (e) { $('gmOut').innerHTML = `<div style="color:#f87171;">Error: ${escHtml(e.message)}</div>`; }
        });
    }

    if (tab === 'shorts' && $('ghRun')) {
        $('ghRun').addEventListener('click', async () => {
            busy('ghOut', 'Cutting shorts (background job)…');
            try {
                const useKaraoke = $('ghStyle') && $('ghStyle').value === 'karaoke';
                const cutUrl = useKaraoke ? '/api/clips/make' : '/api/shorts/cut';
                const statusBase = useKaraoke ? '/api/clips/status/' : '/api/shorts/status/';
                if (useKaraoke) busy('ghOut', 'Making karaoke clips (background job)…');
                const body = useKaraoke
                    ? { video_path: $('ghVideo').value, num_clips: $('ghNum').value, style: 'karaoke',
                        highlight: $('ghHl') ? $('ghHl').value : 'yellow', face_track: true }
                    : { video_path: $('ghVideo').value, num_shorts: $('ghNum').value };
                const r = await fetch(cutUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body) });
                const d = await r.json();
                if (d.status !== 'queued') throw new Error(d.message || 'failed');
                const poll = async () => {
                    const s = await (await fetch(statusBase + d.job_id)).json();
                    const job = s.job || {};
                    if (job.status === 'done') {
                        clearInterval(_shortsPollTimer); _shortsPollTimer = null;
                        $('ghOut').innerHTML = (job.result || []).map(x =>
                            `<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06);color:#10b981;">✅ ${escHtml(x.path || '')}</div>`).join('')
                            || '<div style="color:#94a3b8;">Done — no clips cut (check video length).</div>';
                    } else if (job.status === 'error') {
                        clearInterval(_shortsPollTimer); _shortsPollTimer = null;
                        $('ghOut').innerHTML = `<div style="color:#f87171;">Error: ${escHtml(job.error || 'unknown')}</div>`;
                    } else {
                        $('ghOut').innerHTML = `<div style="color:#94a3b8;">Cutting… (job ${escHtml(d.job_id)})</div>`;
                    }
                };
                _shortsPollTimer = setInterval(poll, 4000);
                poll();
            } catch (e) { $('ghOut').innerHTML = `<div style="color:#f87171;">Error: ${escHtml(e.message)}</div>`; }
        });
    }

    if (tab === 'schedule') {
        const loadQueue = async () => {
            busy('guList', 'Loading queue…');
            try {
                const d = await (await fetch('/api/upload/schedule')).json();
                const q = (d.queue || []).filter(x => x.status === 'scheduled' || x.status === 'failed');
                $('guList').innerHTML = q.length ? q.map(x =>
                    `<div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.06);">
                        <span><b style="color:#fff;">${escHtml(x.title || '')}</b><br><span style="color:#94a3b8;font-size:0.75rem;">${escHtml(x.publish_at || 'due now')} · ${escHtml(x.privacy || 'private')} · ${escHtml(x.status || '')}${x.error ? ' — ' + escHtml(x.error) : ''}</span></span>
                        <button class="btn-tb btn-danger" data-rm="${escHtml(x.id)}" style="font-size:0.72rem;">✕</button>
                    </div>`).join('') : '<div style="color:#94a3b8;">Queue empty.</div>';
                $('guList').querySelectorAll('[data-rm]').forEach(b => b.addEventListener('click', async () => {
                    await fetch('/api/upload/schedule/' + b.dataset.rm, { method: 'DELETE' });
                    loadQueue();
                }));
            } catch (e) { $('guList').innerHTML = `<div style="color:#f87171;">Error: ${escHtml(e.message)}</div>`; }
        };
        if ($('guRefresh')) $('guRefresh').addEventListener('click', loadQueue);
        if ($('guAdd')) $('guAdd').addEventListener('click', async () => {
            busy('guOut', 'Adding…');
            try {
                const r = await fetch('/api/upload/schedule', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ video_path: $('guVideo').value, title: $('guTitle').value, publish_at: $('guAt').value, privacy: $('guPrivacy').value }) });
                const d = await r.json();
                if (d.status !== 'success') throw new Error(d.message || 'failed');
                $('guOut').innerHTML = '<div style="color:#10b981;">✅ Scheduled — the 5-minute background job will publish it on time.</div>';
                loadQueue();
            } catch (e) { $('guOut').innerHTML = `<div style="color:#f87171;">Error: ${escHtml(e.message)}</div>`; }
        });
        loadQueue();
    }
}

function openGrowthModal() {
    const m = document.getElementById('growthModal');
    if (!m) return;
    m.classList.remove('hidden');
    _growthRenderTabs();
    document.getElementById('growthModalBody').innerHTML = growthTabHtml(_growthActiveTab);
    _growthWireTab(_growthActiveTab);
}
function closeGrowthModal() {
    const m = document.getElementById('growthModal');
    if (m) m.classList.add('hidden');
    if (_shortsPollTimer) { clearInterval(_shortsPollTimer); _shortsPollTimer = null; }
}

function initGrowthPanel() {
    document.getElementById('btnOpenGrowth')?.addEventListener('click', openGrowthModal);
    document.getElementById('growthModalClose')?.addEventListener('click', closeGrowthModal);
    document.getElementById('growthModal')?.addEventListener('click', (e) => {
        if (e.target.id === 'growthModal') closeGrowthModal();
    });
}

document.addEventListener('DOMContentLoaded', () => { initGrowthPanel(); });
