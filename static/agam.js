/**
 * AGAM — Advanced Generative Autonomous Machine
 * Holographic JARVIS Sidebar & 3D Animated Reacting Globe
 */

(function () {
    'use strict';

    // ── Configuration & State ──
    const state = {
        isOpen: false,
        isListening: false,
        isSpeaking: false,
        speechEnabled: true,
        history: [],
        vitals: null,
        currentEmotion: 'focused',
        wakeWordActive: false,
        recognition: null,
        currentAudio: null,
        audioIntensity: 0
    };

    // ── 1. DOM Template Injection (Dockable Sidebar Layout) ──
    function initDOM() {
        if (document.getElementById('agamSidebar')) return;

        // Floating Trigger (Collapsed Orb at bottom right)
        const trigger = document.createElement('div');
        trigger.className = 'agam-floating-trigger';
        trigger.id = 'agamFloatingTrigger';
        trigger.title = 'Call AGAM (Voice / Chat AI Assistant)';
        trigger.innerHTML = `
            <div class="agam-reactor-core">
                <div class="agam-reactor-ring"></div>
                <div class="agam-reactor-inner-pulse"></div>
            </div>
            <div class="agam-trigger-meta">
                <span class="agam-trigger-title">🎙️ Say "Agam"</span>
                <span class="agam-trigger-status"><span class="agam-live-dot"></span> JARVIS READY</span>
            </div>
        `;
        document.body.appendChild(trigger);

        // Sleek Right-Hand Dockable Sidebar (ChatGPT Voice Assistant Structure)
        const sidebar = document.createElement('div');
        sidebar.className = 'agam-sidebar';
        sidebar.id = 'agamSidebar';
        sidebar.innerHTML = `
            <!-- 1. Minimalist ChatGPT Voice Header -->
            <div class="agam-voice-header">
                <div class="agam-voice-brand">
                    <span class="agam-live-dot"></span>
                    <span class="agam-voice-title">AGAM</span>
                    <span class="agam-voice-badge">VOICE AI</span>
                </div>
                <div class="agam-voice-actions">
                    <button class="agam-icon-btn" id="agamToggleVoiceBtn" title="Toggle Voice Output">🔊</button>
                    <button class="agam-icon-btn" id="agamSettingsBtn" title="Settings & Keys">⚙️</button>
                    <button class="agam-icon-btn" id="agamCloseBtn" title="Close Sidebar">✕</button>
                </div>
            </div>

            <!-- 2. Central ChatGPT Voice Stage (Iconic Living Fluid Circle & Live Subtitles) -->
            <div class="agam-voice-stage">
                <canvas class="agam-fluid-canvas" id="agamFluidCanvas" width="380" height="330" title="AGAM Living Voice Circle (Tap to speak / interrupt)"></canvas>
                
                <div class="agam-voice-status-wrap">
                    <div class="agam-voice-status-pill" id="agamVoiceStatusPill">
                        <span class="agam-status-dot"></span>
                        <span id="agamVoiceStatusText">Ready • Tap mic to speak</span>
                    </div>
                </div>

                <div class="agam-live-caption-box" id="agamLiveCaption">
                    "Namaste! Say 'Hey Agam' or tap the microphone to start talking."
                </div>
            </div>

            <!-- 3. Bottom Floating Control Bar (Iconic ChatGPT Voice Controls) -->
            <div class="agam-chatgpt-controls" id="agamChatGPTControls">
                <button class="agam-ctrl-btn secondary" id="agamCtrlClose" title="Close Voice Mode">✕</button>
                
                <button class="agam-ctrl-btn main-mic" id="agamCtrlMic" title="Tap to talk / stop">
                    <div class="agam-ctrl-mic-pulse" id="agamMicRipple" style="display:none;"></div>
                    <span id="agamMicIcon">🎙️</span>
                </button>

                <button class="agam-ctrl-btn secondary" id="agamCtrlTranscript" title="View Transcript & Chat">💬</button>
            </div>

            <!-- 4. Collapsible Transcript & Chat History Drawer -->
            <div class="agam-transcript-drawer" id="agamTranscriptDrawer">
                <div class="agam-drawer-header">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span>💬</span>
                        <span>Conversation Transcript</span>
                    </div>
                    <button class="agam-icon-btn" id="agamCloseDrawerBtn" title="Back to Voice Stage">✕</button>
                </div>

                <!-- Mini Telemetry Strip -->
                <div class="agam-mini-telemetry">
                    <div class="agam-telem-chip" id="chipCpu"><span>⚡ CPU:</span> <span id="vitalCpuVal">--%</span></div>
                    <div class="agam-telem-chip" id="chipRam"><span>🧠 RAM:</span> <span id="vitalRamVal">--%</span></div>
                    <div class="agam-telem-chip" id="chipGpu"><span>🎮 RTX 3060:</span> <span id="vitalGpuVal">--%</span></div>
                    <div class="agam-telem-chip" id="chipComfy"><span>🎬 ComfyUI:</span> <span id="vitalComfyVal" style="font-size:10px;">Checking...</span></div>
                </div>

                <!-- Quick Action Chips -->
                <div class="agam-quick-chips">
                    <button class="agam-chip-btn" id="btnActionVitals">⚡ Stats</button>
                    <button class="agam-chip-btn" id="btnActionInspectApp">📄 app.py</button>
                    <button class="agam-chip-btn" id="btnActionGit">💻 Git</button>
                    <button class="agam-chip-btn" id="btnActionSearch">🔍 Wan 2.1</button>
                    <button class="agam-chip-btn" id="btnActionLaunchComfy">🚀 ComfyUI</button>
                    <button class="agam-chip-btn" id="btnActionOpenFolder">📁 Output</button>
                    <button class="agam-chip-btn" id="btnActionJoke">😄 Joke</button>
                    <button class="agam-chip-btn" id="btnActionClearChat">🧹 Clear</button>
                </div>

                <!-- Brain Skills Panel (AI Brain Transplant) -->
                <div class="agam-skills-panel" id="agamSkillsPanel">
                    <div class="agam-skills-header" id="agamSkillsToggle">
                        <span class="agam-skills-icon">🧠</span>
                        <span class="agam-skills-title">Brain Skills</span>
                        <span class="agam-skills-count" id="agamSkillsCount">...</span>
                        <span class="agam-skills-chevron" id="agamSkillsChevron">▾</span>
                    </div>
                    <div class="agam-skills-body" id="agamSkillsBody">
                        <div class="agam-skills-list" id="agamSkillsList">
                            <div class="agam-skill-loading">Loading brain skills...</div>
                        </div>
                        <button class="agam-forge-btn" id="agamForgeSkillBtn" title="Use GPT-4o to forge a new expert skill module">
                            ✦ Forge New Skill
                        </button>
                    </div>
                </div>

                <!-- Conversational Chat Stream -->
                <div class="agam-sidebar-chat" id="agamChatHistory">
                    <div class="agam-message agam">
                        <div class="agam-msg-avatar">⚡</div>
                        <div class="agam-msg-bubble">
                            <strong>Namaste sir! I am AGAM.</strong><br>
                            Aapka personal Jarvis companion with an authentic Indian touch. I understand Hindi, English and Hinglish fluently.
                            <br><br>
                            <em>Boliye sir! How can I assist you right now?</em>
                        </div>
                    </div>
                </div>

                <!-- Bottom Input Bar in Drawer -->
                <div class="agam-sidebar-input-wrap">
                    <div class="agam-input-bar">
                        <input type="text" class="agam-text-input" id="agamTextInput" placeholder="Boliye ya type kijiye (or say 'Agam')..." autocomplete="off">
                        <button class="agam-send-btn" id="agamSendBtn">TRANSMIT</button>
                    </div>
                </div>
            </div>

            <!-- 5. Settings Modal (Overlaid inside sidebar) -->
            <div class="agam-settings-modal" id="agamSettingsModal">
                <div class="agam-settings-box">
                    <div style="display:flex;align-items:center;justify-content:space-between;">
                        <div style="font-family:'Space Grotesk',sans-serif;font-size:15px;font-weight:800;color:var(--agam-cyan);">
                            ⚙️ AGAM Settings & API Keys
                        </div>
                        <button class="agam-icon-btn" id="agamCloseSettingsBtn">✕</button>
                    </div>

                    <div class="agam-field-group">
                        <label>🤖 OpenAI API Key (Voice & GPT-4o Default)</label>
                        <input type="password" id="cfgOpenAIKey" placeholder="sk-proj-...">
                        <small style="color:var(--agam-cyan);font-size:10px;">Used for OpenAI tts-1 neural voice and GPT-4o intelligence.</small>
                    </div>

                    <div class="agam-field-group">
                        <label>⚡ Groq API Key (Free Ultra-Fast Alternative)</label>
                        <input type="password" id="cfgGroqKey" placeholder="gsk_...">
                        <small style="color:var(--agam-emerald);font-size:10px;">Free instant key from <a href="https://console.groq.com/keys" target="_blank" style="color:var(--agam-cyan);">console.groq.com</a> (800 tokens/sec).</small>
                    </div>

                    <div class="agam-field-group">
                        <label>Default LLM Model</label>
                        <select id="cfgModel">
                            <option value="gpt-4o">GPT-4o (OpenAI Default)</option>
                            <option value="gpt-4o-mini">GPT-4o Mini (OpenAI Fast)</option>
                            <option value="llama-3.3-70b-versatile">Groq Llama 3.3 70B (Ultra-Fast)</option>
                            <option value="llama-3.1-8b-instant">Groq Llama 3.1 8B (Instant)</option>
                            <option value="qwen-2.5-coder:7b">Qwen 2.5 Coder (Local Ollama)</option>
                        </select>
                    </div>

                    <div class="agam-field-group">
                        <label>AGAM Voice Engine</label>
                        <select id="cfgVoice">
                            <option value="indian_male">Indian Male Neural (Madhur - Hindi & English Actor)</option>
                            <option value="indian_male_en">Indian Male Expressive (Prabhat - Hinglish & English)</option>
                            <option value="indian_female">Indian Female Neural (Swara - Hindi & English)</option>
                            <option value="indian_female_en">Indian Female Expressive (Neerja - Hinglish & English)</option>
                            <option value="openai_onyx">OpenAI Onyx (US English Jarvis)</option>
                        </select>
                    </div>

                    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:6px;">
                        <button class="agam-chip-btn" id="btnCancelSettings">Cancel</button>
                        <button class="agam-send-btn" id="btnSaveSettings">SAVE SETTINGS</button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(sidebar);

        bindEvents();
        initFluidCanvas();
        startVitalsPolling();
        initSpeechRecognition();
        // Load brain skills panel
        setTimeout(loadSkillsPanel, 800);
    }

    // ── 2. Event Binding ──
    function bindEvents() {
        const trigger = document.getElementById('agamFloatingTrigger');
        const sidebar = document.getElementById('agamSidebar');
        const closeBtn = document.getElementById('agamCloseBtn');
        const ctrlCloseBtn = document.getElementById('agamCtrlClose');
        const sendBtn = document.getElementById('agamSendBtn');
        const textInput = document.getElementById('agamTextInput');
        const ctrlMicBtn = document.getElementById('agamCtrlMic');
        const ctrlTranscriptBtn = document.getElementById('agamCtrlTranscript');
        const closeDrawerBtn = document.getElementById('agamCloseDrawerBtn');
        const voiceToggleBtn = document.getElementById('agamToggleVoiceBtn');
        const settingsBtn = document.getElementById('agamSettingsBtn');
        const closeSettingsBtn = document.getElementById('agamCloseSettingsBtn');
        const cancelSettingsBtn = document.getElementById('btnCancelSettings');
        const saveSettingsBtn = document.getElementById('btnSaveSettings');
        const navSayAgamBtn = document.getElementById('navSayAgamBtn');

        // Say "Agam" Interactive Triggers (Navbar & Floating Orb)
        if (navSayAgamBtn) {
            navSayAgamBtn.addEventListener('click', (e) => {
                e.preventDefault();
                activateVoiceInteraction();
            });
        }

        trigger.addEventListener('click', () => {
            activateVoiceInteraction();
        });

        // Close actions
        if (closeBtn) closeBtn.addEventListener('click', () => toggleSidebar(false));
        if (ctrlCloseBtn) ctrlCloseBtn.addEventListener('click', () => toggleSidebar(false));

        // Voice mute toggle
        if (voiceToggleBtn) {
            voiceToggleBtn.addEventListener('click', () => {
                state.speechEnabled = !state.speechEnabled;
                voiceToggleBtn.textContent = state.speechEnabled ? '🔊' : '🔇';
                if (!state.speechEnabled) {
                    SpeechQueue.clear();
                }
            });
        }

        // ChatGPT Central Mic Button (Tap to talk / stop)
        if (ctrlMicBtn) {
            ctrlMicBtn.addEventListener('click', toggleVoiceRecognition);
        }

        // Transcript Drawer Toggle
        if (ctrlTranscriptBtn) {
            ctrlTranscriptBtn.addEventListener('click', () => toggleTranscriptDrawer());
        }
        if (closeDrawerBtn) {
            closeDrawerBtn.addEventListener('click', () => toggleTranscriptDrawer(false));
        }

        // Chat send in drawer
        if (sendBtn) sendBtn.addEventListener('click', handleSendMessage);
        if (textInput) {
            textInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') handleSendMessage();
            });
        }

        // Settings modal
        if (settingsBtn) settingsBtn.addEventListener('click', openSettings);
        if (closeSettingsBtn) closeSettingsBtn.addEventListener('click', closeSettings);
        if (cancelSettingsBtn) cancelSettingsBtn.addEventListener('click', closeSettings);
        if (saveSettingsBtn) saveSettingsBtn.addEventListener('click', saveSettings);

        // Quick action chips
        const btnVitals = document.getElementById('btnActionVitals');
        if (btnVitals) {
            btnVitals.addEventListener('click', () => {
                sendMessage("PC hardware stats check karo");
            });
        }
        const btnInspectApp = document.getElementById('btnActionInspectApp');
        if (btnInspectApp) {
            btnInspectApp.addEventListener('click', () => {
                sendMessage("app.py check karo aur port batao");
            });
        }
        const btnGit = document.getElementById('btnActionGit');
        if (btnGit) {
            btnGit.addEventListener('click', () => {
                sendMessage("git status check karo");
            });
        }
        const btnSearch = document.getElementById('btnActionSearch');
        if (btnSearch) {
            btnSearch.addEventListener('click', () => {
                sendMessage("search code for Wan 2.1");
            });
        }
        const btnComfy = document.getElementById('btnActionLaunchComfy');
        if (btnComfy) {
            btnComfy.addEventListener('click', () => {
                sendMessage("ComfyUI launch karo");
            });
        }
        const btnFolder = document.getElementById('btnActionOpenFolder');
        if (btnFolder) {
            btnFolder.addEventListener('click', () => {
                sendMessage("Output folder kholo");
            });
        }
        const btnJoke = document.getElementById('btnActionJoke');
        if (btnJoke) {
            btnJoke.addEventListener('click', () => {
                sendMessage("Ek mazedaar joke sunao");
            });
        }
        const btnClear = document.getElementById('btnActionClearChat');
        if (btnClear) {
            btnClear.addEventListener('click', () => {
                const hist = document.getElementById('agamChatHistory');
                if (hist) {
                    hist.innerHTML = `
                        <div class="agam-message agam">
                            <div class="agam-msg-avatar">⚡</div>
                            <div class="agam-msg-bubble">Conversation cleared. Standing by for commands, boss!</div>
                        </div>
                    `;
                }
                state.history = [];
            });
        }

        // Skills panel toggle
        const skillsToggle = document.getElementById('agamSkillsToggle');
        if (skillsToggle) {
            skillsToggle.addEventListener('click', () => {
                const body = document.getElementById('agamSkillsBody');
                const chevron = document.getElementById('agamSkillsChevron');
                if (body) {
                    const isOpen = body.classList.toggle('open');
                    if (chevron) chevron.textContent = isOpen ? '▴' : '▾';
                }
            });
        }

        // Forge new skill button
        const forgeBtn = document.getElementById('agamForgeSkillBtn');
        if (forgeBtn) {
            forgeBtn.addEventListener('click', forgeNewSkill);
        }
    }

    function toggleTranscriptDrawer(open) {
        const drawer = document.getElementById('agamTranscriptDrawer');
        if (!drawer) return;
        const shouldOpen = open !== undefined ? open : !drawer.classList.contains('open');
        drawer.classList.toggle('open', shouldOpen);
        if (shouldOpen) {
            setTimeout(() => {
                const textInput = document.getElementById('agamTextInput');
                if (textInput) textInput.focus();
            }, 300);
        }
    }

    function updateVoiceStatus(status, label) {
        const pill = document.getElementById('agamVoiceStatusPill');
        const text = document.getElementById('agamVoiceStatusText');
        const ctrlMic = document.getElementById('agamCtrlMic');
        const micIcon = document.getElementById('agamMicIcon');
        const ripple = document.getElementById('agamMicRipple');

        if (pill) {
            pill.className = 'agam-voice-status-pill ' + (status === 'speaking' ? 'talking' : status);
        }
        if (text && label) {
            text.textContent = label;
        }

        if (ctrlMic && micIcon) {
            if (status === 'listening') {
                ctrlMic.classList.add('listening');
                micIcon.textContent = '⏹️';
                if (ripple) ripple.style.display = 'block';
            } else if (status === 'speaking') {
                ctrlMic.classList.remove('listening');
                micIcon.textContent = '⏹️';
                if (ripple) ripple.style.display = 'none';
            } else {
                ctrlMic.classList.remove('listening');
                micIcon.textContent = '🎙️';
                if (ripple) ripple.style.display = 'none';
            }
        }
    }

    function updateLiveCaption(text) {
        const caption = document.getElementById('agamLiveCaption');
        if (!caption) return;
        if (!text) {
            caption.textContent = '"Namaste! Say \'Hey Agam\' or tap the microphone to start talking."';
            return;
        }
        caption.textContent = text;
    }

    // ── Voice Interaction Trigger from "Say Agam" ──
    function activateVoiceInteraction() {
        toggleSidebar(true);
        playActivationChime();

        // If not already talking, greet user with authentic Indian voice actor
        if (!state.isSpeaking) {
            const greetings = [
                "Namaste boss! Agam is active and online. How can I help you?",
                "Haan boss! Agam is listening. All systems operational. Tell me what you need!",
                "Yes boss! All systems ready. What is your command?"
            ];
            const greeting = greetings[Math.floor(Math.random() * greetings.length)];
            appendMessage('agam', greeting);
            updateLiveCaption(greeting);
            playIndianActorVoice(greeting, () => {
                startListeningMode();
            });
        } else {
            startListeningMode();
        }
    }

    function startListeningMode() {
        state.isListening = true;
        state.wakeWordActive = true;
        updateVoiceStatus('listening', 'Listening... Speak now');
        updateLiveCaption("Boliye sir, I'm listening...");
        // Recognition runs continuously — only start if it actually stopped
        if (state.recognition && !state._recRunning) {
            try {
                state.recognition.start();
                state._recRunning = true;
            } catch (e) {
                // Already running — that's fine
                state._recRunning = true;
            }
        }
    }

    function toggleSidebar(open) {
        const sidebar = document.getElementById('agamSidebar');
        state.isOpen = open !== undefined ? open : !state.isOpen;
        sidebar.classList.toggle('active', state.isOpen);
        if (!state.isOpen) {
            SpeechQueue.clear();
            if (state.recognition) {
                try { state.recognition.stop(); } catch (e) {}
            }
            toggleTranscriptDrawer(false);
        } else {
            fetchVitals();
        }
    }

    // ── 3. ChatGPT Iconic Living Morphing Fluid Circle ──
    let fluidAnimId = null;
    let fluidAngle = 0;
    let soundRipples = [];

    function initFluidCanvas() {
        const canvas = document.getElementById('agamFluidCanvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');

        function resize() {
            const rect = canvas.getBoundingClientRect();
            canvas.width = (rect.width || 380) * (window.devicePixelRatio || 1);
            canvas.height = (rect.height || 330) * (window.devicePixelRatio || 1);
        }
        resize();
        window.addEventListener('resize', resize);

        // Click canvas directly to interrupt or toggle voice
        canvas.addEventListener('click', () => {
            toggleVoiceRecognition();
        });

        const numPoints = 120;
        let rippleTimer = 0;

        function render() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            const cx = canvas.width / 2;
            const cy = canvas.height / 2;
            const now = Date.now() * 0.001;

            // Fluid radius responsive to device pixel scale
            const baseR = Math.min(cx, cy) * 0.52;

            // Speed based on active voice state
            const speed = state.isSpeaking ? 3.2 : (state.isListening ? 2.0 : 1.0);
            fluidAngle += 0.02 * speed;

            // Dynamic amplitude scaling
            let waveAmp = 0.04;
            if (state.isSpeaking) {
                waveAmp = 0.18 + Math.sin(now * 8) * 0.05 + Math.cos(now * 14) * 0.04;
            } else if (state.isListening) {
                waveAmp = 0.08 + Math.sin(now * 4) * 0.02;
            }

            // 1. Draw Sound Wave Ripples when SPEAKING
            if (state.isSpeaking) {
                rippleTimer++;
                if (rippleTimer % 12 === 0) {
                    soundRipples.push({ r: baseR * 1.05, alpha: 0.85, maxR: baseR * 1.95 });
                }
            }
            soundRipples.forEach((rp, idx) => {
                rp.r += 2.4;
                rp.alpha -= 0.022;
                if (rp.alpha <= 0 || rp.r >= rp.maxR) {
                    soundRipples.splice(idx, 1);
                    return;
                }
                ctx.save();
                ctx.beginPath();
                ctx.arc(cx, cy, rp.r, 0, Math.PI * 2);
                ctx.strokeStyle = `rgba(0, 255, 170, ${rp.alpha * 0.75})`;
                ctx.lineWidth = 2.5;
                ctx.shadowColor = '#00ffaa';
                ctx.shadowBlur = 18;
                ctx.stroke();
                ctx.restore();
            });

            // 2. Soft Ambient Bloom / Atmospheric Glow
            ctx.save();
            const glowR = baseR * (state.isSpeaking ? 1.7 : 1.4);
            const auraGrad = ctx.createRadialGradient(cx, cy, baseR * 0.4, cx, cy, glowR);
            if (state.isSpeaking) {
                auraGrad.addColorStop(0, 'rgba(0, 255, 170, 0.45)');
                auraGrad.addColorStop(0.5, 'rgba(0, 240, 255, 0.2)');
                auraGrad.addColorStop(1, 'rgba(0, 240, 255, 0)');
            } else if (state.isListening) {
                auraGrad.addColorStop(0, 'rgba(0, 240, 255, 0.38)');
                auraGrad.addColorStop(0.5, 'rgba(0, 119, 255, 0.18)');
                auraGrad.addColorStop(1, 'rgba(0, 240, 255, 0)');
            } else {
                auraGrad.addColorStop(0, 'rgba(0, 240, 255, 0.18)');
                auraGrad.addColorStop(0.5, 'rgba(0, 80, 200, 0.08)');
                auraGrad.addColorStop(1, 'rgba(0, 80, 200, 0)');
            }
            ctx.fillStyle = auraGrad;
            ctx.beginPath();
            ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();

            // 3. Multi-layer Organic Fluid Blob (ChatGPT Living Morphing Circle)
            // Draw background fluid layer with offset
            drawFluidLayer(ctx, cx, cy, baseR * 0.94, numPoints, now * speed, waveAmp * 0.7, 0.6, 1.3);
            // Draw primary fluid layer
            drawFluidLayer(ctx, cx, cy, baseR, numPoints, now * speed, waveAmp, 1.0, 0);

            // 4. Subtle Floating Audio Particles when Speaking
            if (state.isSpeaking) {
                ctx.save();
                const numDots = 14;
                for (let i = 0; i < numDots; i++) {
                    const angle = (i / numDots) * Math.PI * 2 + now * 1.5;
                    const dist = baseR * (1.18 + Math.sin(now * 3 + i) * 0.18);
                    const px = cx + Math.cos(angle) * dist;
                    const py = cy + Math.sin(angle) * dist;
                    ctx.beginPath();
                    ctx.arc(px, py, 2.5, 0, Math.PI * 2);
                    ctx.fillStyle = 'rgba(0, 255, 170, 0.85)';
                    ctx.shadowColor = '#00ffaa';
                    ctx.shadowBlur = 10;
                    ctx.fill();
                }
                ctx.restore();
            }

            fluidAnimId = requestAnimationFrame(render);
        }

        function drawFluidLayer(ctx, cx, cy, r0, count, t, amp, opacity, phaseOffset) {
            const points = [];
            for (let i = 0; i < count; i++) {
                const theta = (i / count) * Math.PI * 2;
                // Harmonic fluid sine/cosine displacement
                let disp = Math.sin(theta * 3 + t * 2.1 + phaseOffset) * 0.5
                         + Math.cos(theta * 2 - t * 1.4 + phaseOffset) * 0.35
                         + Math.sin(theta * 5 + t * 3.3) * 0.15;
                if (state.isSpeaking) {
                    disp += Math.sin(theta * 7 - t * 4.8) * 0.25;
                }
                const r = r0 * (1 + disp * amp);
                points.push({
                    x: cx + Math.cos(theta) * r,
                    y: cy + Math.sin(theta) * r
                });
            }

            ctx.save();
            ctx.beginPath();
            // Cardinal Spline / Midpoint Quadratic curves for ultra-smooth fluid perimeter
            const p0 = points[0];
            const pLast = points[count - 1];
            ctx.moveTo((pLast.x + p0.x) / 2, (pLast.y + p0.y) / 2);

            for (let i = 0; i < count; i++) {
                const pCurr = points[i];
                const pNext = points[(i + 1) % count];
                const midX = (pCurr.x + pNext.x) / 2;
                const midY = (pCurr.y + pNext.y) / 2;
                ctx.quadraticCurveTo(pCurr.x, pCurr.y, midX, midY);
            }
            ctx.closePath();

            // Vibrant ChatGPT Radiant Radial Gradient with Indian Emerald / Cyan Palette
            const blobGrad = ctx.createRadialGradient(cx - r0 * 0.25, cy - r0 * 0.25, r0 * 0.1, cx, cy, r0 * 1.15);
            if (state.isSpeaking) {
                blobGrad.addColorStop(0, `rgba(255, 255, 255, ${0.95 * opacity})`);
                blobGrad.addColorStop(0.25, `rgba(0, 255, 170, ${0.9 * opacity})`);
                blobGrad.addColorStop(0.65, `rgba(0, 240, 255, ${0.85 * opacity})`);
                blobGrad.addColorStop(1, `rgba(0, 68, 170, ${0.8 * opacity})`);
                ctx.shadowColor = '#00ffaa';
                ctx.shadowBlur = 32;
            } else if (state.isListening) {
                blobGrad.addColorStop(0, `rgba(255, 255, 255, ${0.95 * opacity})`);
                blobGrad.addColorStop(0.3, `rgba(0, 240, 255, ${0.9 * opacity})`);
                blobGrad.addColorStop(0.7, `rgba(0, 119, 255, ${0.85 * opacity})`);
                blobGrad.addColorStop(1, `rgba(5, 16, 42, ${0.85 * opacity})`);
                ctx.shadowColor = '#00f0ff';
                ctx.shadowBlur = 24;
            } else {
                blobGrad.addColorStop(0, `rgba(226, 241, 255, ${0.9 * opacity})`);
                blobGrad.addColorStop(0.35, `rgba(0, 190, 255, ${0.8 * opacity})`);
                blobGrad.addColorStop(0.75, `rgba(0, 80, 200, ${0.75 * opacity})`);
                blobGrad.addColorStop(1, `rgba(6, 12, 30, ${0.85 * opacity})`);
                ctx.shadowColor = '#00f0ff';
                ctx.shadowBlur = 14;
            }

            ctx.fillStyle = blobGrad;
            ctx.fill();

            // Clean glowing outer contour line
            ctx.strokeStyle = state.isSpeaking
                ? `rgba(0, 255, 170, ${0.85 * opacity})`
                : (state.isListening ? `rgba(0, 240, 255, ${0.85 * opacity})` : `rgba(0, 240, 255, ${0.55 * opacity})`);
            ctx.lineWidth = 2.0;
            ctx.stroke();
            ctx.restore();
        }

        render();
    }

    // ── 4. Spontaneous Voice & Clean Speech Queue ──
    function cleanTextForSpeech(text) {
        if (!text) return '';
        return text
            .replace(/\[EMOTION:\s*\w+\]/gi, '')
            .replace(/\[AGENT_ACTIVATED:\s*[\w_]+\]/gi, '')
            .replace(/\[ACTION:\s*[\s\S]*?\]/gi, '')
            .replace(/```[\s\S]*?```/g, '')
            .replace(/`[^`]*`/g, '')
            .replace(/https?:\/\/\S+/g, '')
            .replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1')
            .replace(/[*_#~]/g, '')
            // Strip ALL emojis so voice engine never says emoji names
            .replace(/\p{Extended_Pictographic}/gu, '')
            .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F900}-\u{1F9FF}\u{26A1}\u{200D}]/gu, '')
            .replace(/[⚡●•★☆▲▼◆■□✓✕→←↑↓—–/\\|]/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    let cachedVoices = [];
    function refreshVoices() {
        if (window.speechSynthesis) {
            cachedVoices = window.speechSynthesis.getVoices();
        }
    }
    if (window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = refreshVoices;
        refreshVoices();
    }

    const SpeechQueue = {
        queue: [],
        isPlaying: false,
        add(text) {
            if (!state.speechEnabled) return;
            const clean = cleanTextForSpeech(text);
            if (!clean) return;
            this.queue.push(clean);
            if (!this.isPlaying) this.playNext();
        },
        playNext() {
            if (this.queue.length === 0) {
                this.isPlaying = false;
                state.isSpeaking = false;
                // Done speaking — go back to listening (mic already running, just update state)
                state.isListening = true;
                updateVoiceStatus('listening', 'Listening... Speak now');
                updateLiveCaption("Boliye sir, I'm listening...");
                return;
            }
            this.isPlaying = true;
            state.isSpeaking = true;
            const text = this.queue.shift();
            updateVoiceStatus('speaking', 'Agam speaking...');
            updateLiveCaption(text);
            playIndianActorVoice(text, () => {
                this.playNext();
            });
        },
        clear() {
            this.queue = [];
            this.isPlaying = false;
            state.isSpeaking = false;
            // Stop Edge-TTS audio immediately
            if (state.currentAudio) {
                state.currentAudio.pause();
                state.currentAudio.currentTime = 0;
                state.currentAudio = null;
            }
            // Stop browser TTS immediately
            if (window.speechSynthesis) window.speechSynthesis.cancel();
            // Go back to listening (mic is already running continuously)
            state.isListening = true;
            updateVoiceStatus('listening', 'Listening... Speak now');
            updateLiveCaption("Boliye sir, I'm listening...");
        }
    };

    // ── Authentic Indian Voice Actor (Bilingual Hindi & English) ──
    async function playIndianActorVoice(text, onEnd) {
        if (!state.speechEnabled) {
            if (onEnd) onEnd();
            return;
        }

        const clean = cleanTextForSpeech(text);
        if (!clean) {
            if (onEnd) onEnd();
            return;
        }

        state.isSpeaking = true;

        // 1. Fetch authentic studio neural Indian voice actor from Edge-TTS endpoint (/api/agam/tts)
        try {
            const resp = await fetch('/api/agam/tts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text: clean,
                    voice: localStorage.getItem('agam_voice') || 'indian_male'
                })
            });
            if (resp.ok) {
                const data = await resp.json();
                if (data.status === 'success' && data.audio_url) {
                    const audio = new Audio(data.audio_url);
                    state.currentAudio = audio;
                    audio.onended = () => {
                        state.isSpeaking = false;
                        state.currentAudio = null;
                        if (onEnd) onEnd();
                    };
                    audio.onerror = () => {
                        state.currentAudio = null;
                        fallbackBrowserSpeech(clean, onEnd);
                    };
                    await audio.play();
                    return;
                }
            }
        } catch (e) {
            console.warn('[AGAM TTS Network Notice]', e);
        }

        // 2. Fallback to browser SpeechSynthesis with Indian accent priority
        fallbackBrowserSpeech(clean, onEnd);
    }

    function fallbackBrowserSpeech(clean, onEnd) {
        if (!window.speechSynthesis) {
            state.isSpeaking = false;
            if (onEnd) onEnd();
            return;
        }

        state.isSpeaking = true;
        window.speechSynthesis.cancel();

        const utter = new SpeechSynthesisUtterance(clean);
        utter.rate = 1.05;
        utter.pitch = 1.0;

        if (!cachedVoices || cachedVoices.length === 0) {
            refreshVoices();
        }

        // Strict priority for Indian Voice Actor
        const indianVoice = cachedVoices.find(v => v.lang === 'hi-IN' || v.lang === 'en-IN' ||
            v.name.includes('India') || v.name.includes('Prabhat') || v.name.includes('Madhur') ||
            v.name.includes('Swara') || v.name.includes('Heera') || v.name.includes('हिन्दी')) ||
            cachedVoices.find(v => v.lang.startsWith('hi') || v.lang.startsWith('en-IN')) ||
            cachedVoices[0];

        if (indianVoice) utter.voice = indianVoice;

        utter.onend = () => {
            state.isSpeaking = false;
            if (onEnd) onEnd();
        };
        utter.onerror = () => {
            state.isSpeaking = false;
            if (onEnd) onEnd();
        };
        window.speechSynthesis.speak(utter);
    }

    // ── 5. Chat & Streaming Message Handling ──
    async function handleSendMessage() {
        const textInput = document.getElementById('agamTextInput');
        const text = textInput.value.trim();
        if (!text) return;

        textInput.value = '';
        await sendMessage(text);
    }

    function formatMessageText(text) {
        if (!text) return '';
        let formatted = text
            .replace(/\[ACTION:\s*([^\s\]]+)(?:\s+(\{[\s\S]*?\}))?\]/gi, (match, act, args) => {
                return `<div class="agam-action-badge"><span class="agam-live-dot"></span> <strong>EXECUTED:</strong> ${act}</div>`;
            })
            .replace(/\[ACTION_RESULT:\s*([\s\S]*?)\]/gi, (match, res) => {
                return `<pre class="agam-action-result"><code>${res.trim()}</code></pre>`;
            })
            .replace(/```([\s\S]*?)```/g, '<pre class="agam-action-result"><code>$1</code></pre>')
            .replace(/`([^`]+)`/g, '<code style="background:rgba(0,240,255,0.12);color:var(--agam-cyan);padding:1px 5px;border-radius:4px;font-size:12px;">$1</code>')
            .replace(/\n/g, '<br>');
        return formatted;
    }

    async function sendMessage(text) {
        appendMessage('user', text);
        updateVoiceStatus('thinking', 'Thinking...');
        updateLiveCaption('"' + text + '"');

        setEmotion('thoughtful');
        const sendBtn = document.getElementById('agamSendBtn');
        if (sendBtn) {
            sendBtn.disabled = true;
            sendBtn.textContent = 'TRANSMITTING...';
        }

        // Create active live bubble
        const historyEl = document.getElementById('agamChatHistory');
        const msgEl = document.createElement('div');
        msgEl.className = 'agam-message agam';
        msgEl.innerHTML = `
            <div class="agam-msg-avatar">⚡</div>
            <div class="agam-msg-bubble">
                <div class="agam-stream-text"><span class="agam-cursor">▋</span></div>
                <div class="agam-msg-footer" style="display:none;margin-top:8px;"></div>
            </div>
        `;
        historyEl.appendChild(msgEl);
        historyEl.scrollTop = historyEl.scrollHeight;

        const contentEl = msgEl.querySelector('.agam-stream-text');
        const footerEl = msgEl.querySelector('.agam-msg-footer');
        let accumulatedText = '';
        let actionBlocks = '';

        function addActionBlock(act) {
            if (!act) return;
            let actName = act.action || 'Code Execution';
            let target = act.path ? ` [${act.path}]` : (act.command ? ` [${act.command}]` : (act.query ? ` ["${act.query}"]` : ''));
            let outText = '';
            if (act.result) {
                outText = act.result.output || act.result.message || (typeof act.result === 'string' ? act.result : JSON.stringify(act.result, null, 2));
            }
            actionBlocks += `[ACTION: ${actName}${target}]\n` + (outText ? `[ACTION_RESULT: ${outText}]\n\n` : '\n');
            contentEl.innerHTML = formatMessageText(actionBlocks + accumulatedText) + '<span class="agam-cursor">▋</span>';
            historyEl.scrollTop = historyEl.scrollHeight;
        }

        try {
            const resp = await fetch('/api/agam/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    history: state.history,
                    model: localStorage.getItem('agam_model') || 'gpt-4o',
                    api_key: localStorage.getItem('agam_openai_key') || localStorage.getItem('agam_groq_key') || localStorage.getItem('agam_key') || '',
                    base_url: localStorage.getItem('agam_base_url') || ''
                })
            });

            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            const reader = resp.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const parts = buffer.split('\n\n');
                buffer = parts.pop();

                for (const part of parts) {
                    if (part.startsWith('data: ')) {
                        try {
                            const event = JSON.parse(part.slice(6));

                            if (event.type === 'init') {
                                if (event.action) {
                                    addActionBlock(event.action);
                                }
                                // Show active skill brain banner
                                if (event.active_skill) {
                                    showSkillBanner(event.active_skill);
                                }
                            } else if (event.type === 'action') {
                                if (event.action) {
                                    addActionBlock(event.action);
                                }
                            } else if (event.type === 'token') {
                                accumulatedText += event.token;
                                let clean = accumulatedText
                                    .replace(/\[EMOTION:\s*\w+\]/gi, '')
                                    .replace(/\[AGENT_ACTIVATED:\s*\w+\]/gi, '')
                                    .trimStart();
                                contentEl.innerHTML = formatMessageText(actionBlocks + clean) + '<span class="agam-cursor">▋</span>';
                                historyEl.scrollTop = historyEl.scrollHeight;
                            } else if (event.type === 'sentence') {
                                updateLiveCaption('"' + event.text + '"');
                                SpeechQueue.add(event.text);
                            } else if (event.type === 'done') {
                                setEmotion(event.emotion || 'focused');
                                state.history.push({ role: 'user', content: text });
                                state.history.push({ role: 'assistant', content: event.full_text });
                            }
                        } catch (e) {}
                    }
                }
            }

            let finalClean = accumulatedText
                .replace(/\[EMOTION:\s*\w+\]/gi, '')
                .replace(/\[AGENT_ACTIVATED:\s*\w+\]/gi, '')
                .trim();
            contentEl.innerHTML = formatMessageText(actionBlocks + finalClean);

            footerEl.style.display = 'block';
            footerEl.innerHTML = `
                <button class="agam-speech-player" onclick="window.replayMessageVoice(this)">
                    <span>▶ Replay Voice</span>
                </button>
            `;
            historyEl.scrollTop = historyEl.scrollHeight;

        } catch (err) {
            console.warn('[AGAM Stream Error, fallback to chat]', err);
            try {
                const fallbackResp = await fetch('/api/agam/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: text,
                        history: state.history,
                        model: localStorage.getItem('agam_model') || 'gpt-4o',
                        api_key: localStorage.getItem('agam_openai_key') || localStorage.getItem('agam_groq_key') || localStorage.getItem('agam_key') || '',
                        base_url: localStorage.getItem('agam_base_url') || ''
                    })
                });
                if (fallbackResp.ok) {
                    const fallbackData = await fallbackResp.json();
                    if (fallbackData.status === 'success' && fallbackData.response) {
                        contentEl.innerHTML = formatMessageText(fallbackData.response);
                        setEmotion(fallbackData.emotion || 'focused');
                        state.history.push({ role: 'user', content: text });
                        state.history.push({ role: 'assistant', content: fallbackData.response });
                        SpeechQueue.add(fallbackData.response);

                        footerEl.style.display = 'block';
                        footerEl.innerHTML = `
                            <button class="agam-speech-player" onclick="window.replayMessageVoice(this)">
                                <span>▶ Replay Voice</span>
                            </button>
                        `;
                        historyEl.scrollTop = historyEl.scrollHeight;
                        return;
                    }
                }
            } catch (e2) {}

            contentEl.innerHTML = `⚠️ Transmission notice: ${err.message}`;
            setEmotion('alert');
        } finally {
            sendBtn.disabled = false;
            sendBtn.textContent = 'TRANSMITTING';
            setTimeout(() => {
                if (!state.isSpeaking && SpeechQueue.queue.length === 0) {
                    startListeningMode();
                }
            }, 500);
        }
    }

    window.replayMessageVoice = function (btn) {
        const bubble = btn.closest('.agam-msg-bubble');
        if (!bubble) return;
        const text = bubble.querySelector('.agam-stream-text').innerText;
        SpeechQueue.clear();
        playIndianActorVoice(text);
    };

    function appendMessage(sender, text) {
        const historyEl = document.getElementById('agamChatHistory');
        const msgEl = document.createElement('div');
        msgEl.className = `agam-message ${sender}`;

        const avatar = sender === 'agam' ? '⚡' : '👤';
        msgEl.innerHTML = `
            <div class="agam-msg-avatar">${avatar}</div>
            <div class="agam-msg-bubble">
                <div>${formatMessageText(text)}</div>
            </div>
        `;

        historyEl.appendChild(msgEl);
        historyEl.scrollTop = historyEl.scrollHeight;
    }

    function setEmotion(emotion) {
        state.currentEmotion = emotion;
        const pill = document.getElementById('agamEmotionPill');
        if (pill) {
            pill.textContent = emotion.toUpperCase();
        }
    }

    // ── 6. Speech Recognition, Barge-In & Continuous Voice Loop ──
    function initSpeechRecognition() {
        const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRec) {
            console.warn('[AGAM] Web Speech API not supported in this browser.');
            return;
        }

        state.wakeWordActive = true;
        state.recognition = new SpeechRec();
        state.recognition.continuous = true;
        state.recognition.interimResults = true;
        state.recognition.lang = 'en-IN';

        let wakeDebounce = false;
        let silenceTimer = null;

        state.recognition.onresult = (event) => {
            let interimTranscript = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const res = event.results[i];
                const piece = res[0].transcript;
                interimTranscript += piece;

                // ── 1. BARGE-IN INTERRUPTION ──
                // If AGAM is speaking and user starts talking, STOP audio immediately
                if ((state.isSpeaking || SpeechQueue.isPlaying || state.currentAudio) && piece.trim().length > 2) {
                    console.log('[AGAM Barge-In] Interrupting speech...');
                    // Stop audio ONLY — do NOT call startListeningMode() as recognition is already running!
                    SpeechQueue.queue = [];
                    SpeechQueue.isPlaying = false;
                    state.isSpeaking = false;
                    if (state.currentAudio) {
                        state.currentAudio.pause();
                        state.currentAudio.currentTime = 0;
                        state.currentAudio = null;
                    }
                    if (window.speechSynthesis) window.speechSynthesis.cancel();
                    state.isListening = true;
                    updateVoiceStatus('listening', 'Listening... Speak now');
                    updateLiveCaption('"' + piece.trim() + '"');
                    // Do NOT restart recognition — it's already running continuously
                }

                if (interimTranscript.trim()) {
                    updateLiveCaption('"' + interimTranscript.trim() + '"');
                }

                const textInput = document.getElementById('agamTextInput');
                if (textInput && interimTranscript.trim()) {
                    textInput.value = interimTranscript.trim();
                }

                const tLower = interimTranscript.toLowerCase();
                const hasWakeWord = /\b(hey|hi|hello|ok|arre|namaste)?\s*(agam|aagam|agum)\b/i.test(tLower);

                // Wake word activation
                if (hasWakeWord && !wakeDebounce) {
                    wakeDebounce = true;
                    setTimeout(() => { wakeDebounce = false; }, 2500);

                    console.log('[AGAM Wake Word Activated]:', interimTranscript);
                    playActivationChime();
                    toggleSidebar(true);
                    updateVoiceStatus('listening', 'Wake word detected!');
                    updateLiveCaption('"Hey Agam"');

                    const cleanQuery = interimTranscript.replace(/.*?\b(hey|hi|hello|ok|arre|namaste)?\s*(agam|aagam|agum)\b[,!\s]*/i, '').trim();
                    if (cleanQuery.length > 2) {
                        if (textInput) textInput.value = '';
                        playIndianActorVoice("Haan boss, checking that now!", () => {
                            sendMessage(cleanQuery);
                        });
                    } else {
                        // User said only "Hey Agam"
                        if (textInput) textInput.value = '';
                        appendMessage('user', 'Hey Agam');
                        const wakeGreetings = [
                            "Haan boss! Agam is listening. Tell me what you need!",
                            "Yes boss! All systems operational. Boliye sir, how can I help you?",
                            "Namaste sir! Agam ready hai. Aadesh kijiye!"
                        ];
                        const greeting = wakeGreetings[Math.floor(Math.random() * wakeGreetings.length)];
                        appendMessage('agam', greeting);
                        updateLiveCaption(greeting);
                        playIndianActorVoice(greeting, () => {
                            startListeningMode();
                        });
                    }
                    return;
                }

                // ── 2. CONTINUOUS TWO-WAY HANDS-FREE CONVERSATION ──
                if (state.isListening && !state.isSpeaking) {
                    if (silenceTimer) clearTimeout(silenceTimer);

                    if (res.isFinal) {
                        const finalQuery = interimTranscript.replace(/.*?\b(hey|hi|hello|ok|arre|namaste)?\s*(agam|aagam|agum)\b[,!\s]*/i, '').trim();
                        if (finalQuery.length > 1) {
                            if (textInput) textInput.value = '';
                            // Set isListening false to prevent double-firing
                            state.isListening = false;
                            updateVoiceStatus('thinking', 'Thinking...');
                            sendMessage(finalQuery);
                        }
                    } else {
                        // Auto-transmit after 1.2s pause
                        silenceTimer = setTimeout(() => {
                            const currentVal = (textInput ? textInput.value : interimTranscript).trim();
                            const finalQuery = currentVal.replace(/.*?\b(hey|hi|hello|ok|arre|namaste)?\s*(agam|aagam|agum)\b[,!\s]*/i, '').trim();
                            if (finalQuery.length > 1 && state.isListening && !state.isSpeaking) {
                                if (textInput) textInput.value = '';
                                state.isListening = false;
                                updateVoiceStatus('thinking', 'Thinking...');
                                sendMessage(finalQuery);
                            }
                        }, 1200);
                    }
                }
            }
        };

        state.recognition.onerror = (e) => {
            console.log('[AGAM Speech Rec Notice]', e.error);
            state._recRunning = false;
            if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
                state.isListening = false;
                state.wakeWordActive = false;
                updateVoiceStatus('idle', 'Mic blocked — allow microphone');
            }
            // For aborted/no-speech errors, just let onend handle restart
        };

        state.recognition.onend = () => {
            state._recRunning = false;
            // ALWAYS keep mic running as long as sidebar is open or wake word is active
            // This is the key fix — mic must never die silently
            if (state.wakeWordActive || state.isOpen || state.isListening) {
                setTimeout(() => {
                    if (!state._recRunning) {
                        try {
                            state.recognition.start();
                            state._recRunning = true;
                        } catch (e) {
                            // If it fails, try again in 500ms
                            setTimeout(() => {
                                try { state.recognition.start(); state._recRunning = true; } catch (_) {}
                            }, 500);
                        }
                    }
                }, 150);
            }
        };

        try {
            state.recognition.start();
            state._recRunning = true;
        } catch (e) {}

        document.addEventListener('click', function initMicOnClick() {
            if (state.recognition && state.wakeWordActive) {
                try { state.recognition.start(); } catch (e) {}
            }
            if (window.speechSynthesis) {
                window.speechSynthesis.getVoices();
            }
            document.removeEventListener('click', initMicOnClick);
        }, { once: true });
    }

    function playActivationChime() {
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return;
            const ctx = new AudioContext();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(587.33, ctx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(880, ctx.currentTime + 0.1);
            gain.gain.setValueAtTime(0.2, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.22);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.22);
        } catch (e) {}
    }


    function toggleVoiceRecognition() {
        if (!state.recognition) {
            alert('Speech Recognition is not available. Please use Chrome or Edge.');
            return;
        }

        // Tap while AGAM is speaking = instant barge-in, start listening
        if (state.isSpeaking || SpeechQueue.isPlaying || state.currentAudio) {
            SpeechQueue.queue = [];
            SpeechQueue.isPlaying = false;
            state.isSpeaking = false;
            if (state.currentAudio) {
                state.currentAudio.pause();
                state.currentAudio.currentTime = 0;
                state.currentAudio = null;
            }
            if (window.speechSynthesis) window.speechSynthesis.cancel();
            state.isListening = true;
            updateVoiceStatus('listening', 'Listening... Speak now');
            return;
        }

        if (state.isListening) {
            // Manually pause mic
            state.isListening = false;
            state.wakeWordActive = false;
            updateVoiceStatus('idle', 'Paused \u2022 Tap mic to resume');
            updateLiveCaption("Microphone paused. Tap mic or say 'Hey Agam' to speak.");
            try { state.recognition.stop(); state._recRunning = false; } catch (e) {}
        } else {
            // Resume mic
            state.wakeWordActive = true;
            startListeningMode();
        }
    }


    // ── 7. Hardware Vitals Polling ──
    async function fetchVitals() {
        try {
            const res = await fetch('/api/agam/vitals');
            if (!res.ok) return;
            const data = await res.json();
            if (data.status === 'success' && data.vitals) {
                state.vitals = data.vitals;
                renderVitals(data.vitals);
            }
        } catch (e) {}
    }

    function renderVitals(v) {
        const cpuEl = document.getElementById('vitalCpuVal');
        if (cpuEl) cpuEl.textContent = `${v.cpu.usage_percent}%`;

        const ramEl = document.getElementById('vitalRamVal');
        if (ramEl) ramEl.textContent = `${v.ram.percent}%`;

        const gpuEl = document.getElementById('vitalGpuVal');
        if (gpuEl && v.gpu && v.gpu.available) {
            gpuEl.textContent = `${v.gpu.vram_percent}%`;
        }

        const comfyEl = document.getElementById('vitalComfyVal');
        if (comfyEl) {
            const running = v.services?.comfyui?.running;
            comfyEl.textContent = running ? 'ONLINE (8188)' : 'READY';
            comfyEl.style.color = running ? 'var(--agam-emerald)' : '#ffaa00';
        }
    }

    function startVitalsPolling() {
        fetchVitals();
        setInterval(() => {
            if (state.isOpen) fetchVitals();
        }, 5000);
    }

    // ── 8. Settings Management ──
    async function openSettings() {
        const modal = document.getElementById('agamSettingsModal');
        modal.classList.add('active');

        const localOpenAI = localStorage.getItem('agam_openai_key') || '';
        if (localOpenAI) {
            document.getElementById('cfgOpenAIKey').value = localOpenAI;
        }

        const localGroq = localStorage.getItem('agam_groq_key') || '';
        if (localGroq) {
            document.getElementById('cfgGroqKey').value = localGroq;
        }

        try {
            const res = await fetch('/api/agam/config');
            const data = await res.json();
            if (data.status === 'success') {
                if (!localOpenAI && data.openai_key_set) {
                    document.getElementById('cfgOpenAIKey').placeholder = data.masked_openai_key;
                }
                if (!localGroq && data.groq_key_set) {
                    document.getElementById('cfgGroqKey').placeholder = data.masked_groq_key;
                }
                document.getElementById('cfgModel').value = data.current_model || 'gpt-4o';
                document.getElementById('cfgVoice').value = data.current_voice || 'openai_onyx';
            }
        } catch (e) {}
    }

    function closeSettings() {
        document.getElementById('agamSettingsModal').classList.remove('active');
    }

    async function saveSettings() {
        const openaiKey = document.getElementById('cfgOpenAIKey').value.trim();
        const groqKey = document.getElementById('cfgGroqKey').value.trim();
        const model = document.getElementById('cfgModel').value;
        const voice = document.getElementById('cfgVoice').value;

        if (openaiKey) localStorage.setItem('agam_openai_key', openaiKey);
        if (groqKey) localStorage.setItem('agam_groq_key', groqKey);
        localStorage.setItem('agam_model', model);

        try {
            await fetch('/api/agam/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    openai_api_key: openaiKey,
                    groq_api_key: groqKey,
                    model: model,
                    voice: voice
                })
            });
            alert('Settings saved successfully!');
            closeSettings();
        } catch (e) {
            alert('Failed to save settings: ' + e.message);
        }
    }

    // ── Skills Brain Transplant Panel ──
    async function loadSkillsPanel() {
        const list = document.getElementById('agamSkillsList');
        const count = document.getElementById('agamSkillsCount');
        if (!list) return;
        try {
            const res = await fetch('/api/agam/skills');
            if (!res.ok) return;
            const data = await res.json();
            if (data.status !== 'success') return;
            const skills = data.skills || [];
            const active = skills.filter(s => s.active).length;
            if (count) count.textContent = `${active}/${skills.length} active`;
            list.innerHTML = '';
            skills.forEach(skill => {
                const badge = document.createElement('div');
                badge.className = 'agam-skill-badge' + (skill.active ? ' active' : ' inactive');
                badge.dataset.skillId = skill.id;
                badge.title = skill.description;
                badge.innerHTML = `
                    <div class="agam-skill-badge-name">${skill.name}</div>
                    <div class="agam-skill-badge-meta">
                        <span class="agam-skill-by">${skill.created_by === 'system' ? 'Built-in' : skill.created_by === 'gpt-4o' ? 'GPT-4o Forged' : 'Custom'}</span>
                        <button class="agam-skill-toggle" data-id="${skill.id}" title="${skill.active ? 'Deactivate' : 'Activate'} skill">${skill.active ? 'ON' : 'OFF'}</button>
                    </div>
                `;
                list.appendChild(badge);
            });
            // Bind toggle buttons
            list.querySelectorAll('.agam-skill-toggle').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const sid = btn.dataset.id;
                    try {
                        await fetch('/api/agam/skills/activate', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ skill_id: sid })
                        });
                        loadSkillsPanel();
                    } catch (err) { console.warn('Skill toggle error', err); }
                });
            });
        } catch (e) {
            if (list) list.innerHTML = '<div class="agam-skill-loading">Could not load skills.</div>';
        }
    }

    function showSkillBanner(skillName) {
        let banner = document.getElementById('agamSkillBanner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'agamSkillBanner';
            banner.className = 'agam-skill-banner';
            const drawer = document.getElementById('agamTranscriptDrawer');
            if (drawer) drawer.prepend(banner);
        }
        banner.innerHTML = `<span class="agam-skill-banner-dot"></span> Brain loaded: <strong>${skillName}</strong>`;
        banner.classList.add('visible');
        clearTimeout(banner._hideTimer);
        banner._hideTimer = setTimeout(() => banner.classList.remove('visible'), 4000);
    }

    async function forgeNewSkill() {
        const domain = prompt('Enter domain to forge a skill for (e.g. "video generation", "React hooks", "database optimization"):');
        if (!domain || !domain.trim()) return;
        const description = prompt('Brief description (optional):') || '';
        const filesInput = prompt('Comma-separated file paths to analyze (optional, e.g. "src/backend/video_gen_ai.py"):') || '';
        const files = filesInput.split(',').map(f => f.trim()).filter(Boolean);

        const list = document.getElementById('agamSkillsList');
        if (list) list.innerHTML = '<div class="agam-skill-loading">Forging skill with GPT-4o... Please wait...</div>';

        try {
            const res = await fetch('/api/agam/skills/forge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ domain, description, files })
            });
            const data = await res.json();
            if (data.status === 'success') {
                alert(`Brain Transplant Complete!\nSkill "${data.skill.name}" has been forged and installed.\n\nAGAM will now be an expert in this domain.`);
                loadSkillsPanel();
            } else {
                alert('Skill forge failed: ' + (data.message || 'Unknown error'));
                loadSkillsPanel();
            }
        } catch (err) {
            alert('Skill forge error: ' + err.message);
            loadSkillsPanel();
        }
    }

    // Auto-init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDOM);
    } else {
        initDOM();
    }

})();
