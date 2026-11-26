/**
 * FortiSales AI - Autonomous Receptionist Voice Console Client.
 *
 * Implements:
 * 1. Single-use ticket acquisition via REST.
 * 2. WebSocket streaming with First-Frame authentication.
 * 3. AudioWorklet 16kHz PCM16 microphone capture with GC protection.
 * 4. Jitter-buffered Web Audio API playback for server TTS stream.
 * 5. Instant audio buffer flushing on barge-in ("clear_audio").
 * 6. Live transcription rendering and call lifecycle management.
 * 7. Real-time microphone diagnostics, stall detection, and device switching.
 */

class ReceptionistVoiceClient {
  constructor() {
    this.token = localStorage.getItem("fortisales_token") || "";
    this.ws = null;
    this.audioCtx = null;
    this.micStream = null;
    this.micSource = null; // Stored as instance variable to prevent GC disconnection
    this.workletNode = null;
    this.silentGain = null;

    // Audio Playback Queue
    this.activeAudioSources = [];
    this.nextPlaybackTime = 0;
    this.isMuted = false;
    this.recordingConsent = false;
    this.activeConversationId = null;
    this.activeCallId = null;
    this.interimCallerEl = null;
    this.currentAiTurnEl = null;
    this.lastFinalCallerText = "";

    // Diagnostics & Stall Detection
    this.framesCaptured = 0;
    this.bytesTransmitted = 0;
    this.backendFramesReceived = 0;
    this.lastFrameTime = 0;
    this.diagnosticInterval = null;
    this.selectedDeviceId = "";

    this.initUI();
    this.initDeviceList();
    this.setupVisibilityHandler();
  }

  isTokenExpired(token) {
    if (!token) return true;
    try {
      const parts = token.split('.');
      if (parts.length !== 3) return true;
      const payload = JSON.parse(atob(parts[1]));
      if (payload.exp && Date.now() >= payload.exp * 1000) {
        return true;
      }
      return false;
    } catch (e) {
      return true;
    }
  }

  initUI() {
    this.btnStart = document.getElementById("btn-start");
    this.btnEnd = document.getElementById("btn-end");
    this.btnMute = document.getElementById("btn-mute");
    this.btnInterrupt = document.getElementById("btn-interrupt");
    this.consentToggle = document.getElementById("recording-consent");
    this.statusPill = document.getElementById("connection-status");
    this.agentStatePill = document.getElementById("agent-state");
    this.transcriptContainer = document.getElementById("transcript-list");
    this.errorBanner = document.getElementById("error-banner");
    this.micSelect = document.getElementById("mic-select");
    this.micStatusDot = document.getElementById("mic-status-dot");
    this.audioStatsEl = document.getElementById("audio-stats");
    this.stalledWarningEl = document.getElementById("stalled-warning");

    // Automatically check existing session authentication
    this.token = localStorage.getItem("fortisales_token") || "";
    const sessionBadge = document.getElementById("session-badge");
    const sessionInfo = document.getElementById("session-user-info");

    if (!this.token || this.isTokenExpired(this.token)) {
      if (sessionBadge) {
        sessionBadge.className = "badge bg-danger-subtle text-danger border border-danger-subtle";
        sessionBadge.textContent = "Session Inactive";
      }
      if (sessionInfo) {
        sessionInfo.innerHTML = 'Authentication required. <a href="/" class="alert-link fw-semibold">Click here to log in</a>.';
      }
      this.showError("Authentication required: Your session has expired or you are not logged in. Please log in before starting a voice call.");
      if (this.btnStart) this.btnStart.disabled = true;
    } else {
      try {
        const payload = JSON.parse(atob(this.token.split('.')[1]));
        if (sessionBadge) {
          sessionBadge.className = "badge bg-success-subtle text-success border border-success-subtle";
          sessionBadge.textContent = "Authenticated Session";
        }
        if (sessionInfo) {
          sessionInfo.textContent = `Logged in as: ${payload.email || 'Staff'} (${payload.role || 'Receptionist'})`;
        }
        if (this.btnStart) this.btnStart.disabled = false;
      } catch (e) {
        if (sessionInfo) sessionInfo.textContent = "Authenticated Session Active";
      }
    }

    if (this.btnStart) this.btnStart.addEventListener("click", () => this.startCall());
    if (this.btnEnd) this.btnEnd.addEventListener("click", () => this.endCall());
    if (this.btnMute) this.btnMute.addEventListener("click", () => this.toggleMute());
    if (this.btnInterrupt) this.btnInterrupt.addEventListener("click", () => this.triggerInterrupt());
    if (this.consentToggle) {
      this.consentToggle.addEventListener("change", (e) => {
        this.recordingConsent = e.target.checked;
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({
            type: "start",
            codec: "pcm16",
            sample_rate: 16000,
            channels: 1,
            recording_consent: this.recordingConsent,
          }));
        }
      });
    }

    if (this.micSelect) {
      this.micSelect.addEventListener("change", async (e) => {
        this.selectedDeviceId = e.target.value;
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          await this.switchMicrophoneDevice(this.selectedDeviceId);
        }
      });
    }
  }

  async initDeviceList() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = devices.filter(d => d.kind === "audioinput");
      if (this.micSelect) {
        this.micSelect.innerHTML = '<option value="">Default Microphone</option>';
        audioInputs.forEach((dev, idx) => {
          const opt = document.createElement("option");
          opt.value = dev.deviceId;
          opt.textContent = dev.label || `Microphone ${idx + 1}`;
          this.micSelect.appendChild(opt);
        });
      }
    } catch (e) {
      console.debug("Could not enumerate audio devices:", e);
    }

    navigator.mediaDevices.addEventListener("devicechange", () => {
      this.initDeviceList();
    });
  }

  setupVisibilityHandler() {
    document.addEventListener("visibilitychange", async () => {
      if (document.visibilityState === "visible" && this.audioCtx && this.audioCtx.state === "suspended") {
        try {
          await this.audioCtx.resume();
          console.info("Resumed AudioContext after tab became visible.");
        } catch (e) {
          console.warn("Failed to resume AudioContext on visibility change:", e);
        }
      }
    });
  }

  setStatus(status, type = "secondary") {
    if (this.statusPill) {
      this.statusPill.textContent = status;
      this.statusPill.className = `badge bg-${type} p-2`;
    }
  }

  setAgentState(state, type = "info") {
    if (this.agentStatePill) {
      this.agentStatePill.textContent = state;
      this.agentStatePill.className = `badge bg-${type} p-2`;
    }
  }

  showError(msg) {
    if (this.errorBanner) {
      this.errorBanner.textContent = msg;
      this.errorBanner.classList.remove("d-none");
    }
  }

  hideError() {
    if (this.errorBanner) {
      this.errorBanner.classList.add("d-none");
    }
  }

  escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  appendTranscript(role, text, isFinal = true) {
    if (!this.transcriptContainer || !text) return;

    if (role === "caller") {
      this.currentAiTurnEl = null;
      if (!isFinal) {
        if (!this.interimCallerEl) {
          const div = document.createElement("div");
          div.className = "p-2 my-2 rounded bg-light text-muted border-start border-4 border-warning fst-italic interim-caller";
          div.innerHTML = `<strong>Caller (speaking...):</strong> <span>${this.escapeHtml(text)}</span>`;
          this.transcriptContainer.appendChild(div);
          this.interimCallerEl = div;
        } else {
          const span = this.interimCallerEl.querySelector("span");
          if (span) span.textContent = text;
        }
        this.transcriptContainer.scrollTop = this.transcriptContainer.scrollHeight;
        return;
      }

      if (this.lastFinalCallerText === text) {
        if (this.interimCallerEl) {
          this.interimCallerEl.remove();
          this.interimCallerEl = null;
        }
        return;
      }

      this.lastFinalCallerText = text;

      if (this.interimCallerEl) {
        this.interimCallerEl.className = "p-2 my-2 rounded bg-light text-dark border-start border-4 border-primary";
        this.interimCallerEl.innerHTML = `<strong>Caller:</strong> <span>${this.escapeHtml(text)}</span>`;
        this.interimCallerEl = null;
      } else {
        const div = document.createElement("div");
        div.className = "p-2 my-2 rounded bg-light text-dark border-start border-4 border-primary";
        div.innerHTML = `<strong>Caller:</strong> <span>${this.escapeHtml(text)}</span>`;
        this.transcriptContainer.appendChild(div);
      }
      this.transcriptContainer.scrollTop = this.transcriptContainer.scrollHeight;
      return;
    }

    if (this.interimCallerEl) {
      this.interimCallerEl.remove();
      this.interimCallerEl = null;
    }

    this.lastFinalCallerText = "";

    if (role === "ai_agent") {
      if (this.currentAiTurnEl) {
        const textSpan = this.currentAiTurnEl.querySelector(".ai-spoken-text");
        if (textSpan) {
          textSpan.innerHTML += " " + this.escapeHtml(text);
        }
      } else {
        const div = document.createElement("div");
        div.className = "p-3 my-2 rounded bg-primary-subtle text-dark border-start border-4 border-success shadow-sm ai-response-card";
        div.innerHTML = `
          <div class="d-flex align-items-center justify-content-between mb-1">
            <span class="badge bg-success">🎙️ AI Receptionist</span>
            <span class="text-success small fw-semibold speaking-badge">
              <span class="spinner-grow spinner-grow-sm text-success me-1" role="status"></span>Speaking
            </span>
          </div>
          <div class="ai-spoken-text fs-6">${this.escapeHtml(text)}</div>
        `;
        this.transcriptContainer.appendChild(div);
        this.currentAiTurnEl = div;
      }
    } else {
      this.currentAiTurnEl = null;
      const div = document.createElement("div");
      div.className = "p-2 my-2 rounded bg-secondary-subtle text-muted border-start border-4 border-secondary small";
      div.innerHTML = `<em>${this.escapeHtml(text)}</em>`;
      this.transcriptContainer.appendChild(div);
    }
    this.transcriptContainer.scrollTop = this.transcriptContainer.scrollHeight;
  }

  async startCall() {
    this.hideError();
    this.token = localStorage.getItem("fortisales_token") || "";
    if (!this.token || this.isTokenExpired(this.token)) {
      this.showError("Authentication required: Your session has expired or you are not logged in. Please log in to start calls.");
      if (this.btnStart) this.btnStart.disabled = true;
      setTimeout(() => { window.location.href = "/"; }, 2000);
      return;
    }

    try {
      this.setStatus("Requesting Ticket...", "warning");
      this.btnStart.disabled = true;

      // 1. Obtain ephemeral single-use ticket
      let ticketRes = await fetch("/v1/voice/tickets", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${this.token}`,
        },
        body: JSON.stringify({
          language: "en",
          caller_phone: "+18005550199",
        }),
      });

      if (!ticketRes.ok && ticketRes.status === 404) {
        ticketRes = await fetch("/api/v1/voice/tickets", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${this.token}`,
          },
          body: JSON.stringify({
            language: "en",
            caller_phone: "+18005550199",
          }),
        });
      }

      if (ticketRes.status === 401) {
        localStorage.removeItem("fortisales_token");
        localStorage.removeItem("fortisales_role");
        this.showError("Your session has expired. Redirecting to login...");
        setTimeout(() => { window.location.href = "/"; }, 1500);
        return;
      }

      if (!ticketRes.ok) {
        const err = await ticketRes.json().catch(() => ({}));
        throw new Error(err.detail || `Failed to issue voice ticket (${ticketRes.status})`);
      }

      const ticketData = await ticketRes.json();
      const ticket = ticketData.ticket;

      // 2. Initialize Web Audio API at native 16kHz
      this.setStatus("Initializing Audio...", "warning");
      try {
        this.audioCtx = new (window.AudioContext || window.webkitAudioContext)({
          sampleRate: 16000,
          latencyHint: "interactive",
        });
      } catch (e) {
        // Fallback for browsers that enforce device sampleRate
        this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }

      if (this.audioCtx.state === "suspended") {
        await this.audioCtx.resume();
      }

      await this.audioCtx.audioWorklet.addModule("/static/pcm-processor.js");

      // 3. Request user media with selected device
      const audioConstraints = {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      };
      if (this.selectedDeviceId) {
        audioConstraints.deviceId = { exact: this.selectedDeviceId };
      }

      this.micStream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints });

      // Refresh device labels now that permission is granted
      this.initDeviceList();

      // IMPORTANT: Store micSource on instance to prevent Garbage Collection disconnect!
      this.micSource = this.audioCtx.createMediaStreamSource(this.micStream);
      this.workletNode = new AudioWorkletNode(this.audioCtx, "pcm16-capture-processor");

      // Connect worklet to zero-gain node connected to destination
      // This prevents Chrome from sleeping or throttling the audio worklet
      this.silentGain = this.audioCtx.createGain();
      this.silentGain.gain.value = 0;
      this.micSource.connect(this.workletNode);
      this.workletNode.connect(this.silentGain);
      this.silentGain.connect(this.audioCtx.destination);

      // Reset counters
      this.framesCaptured = 0;
      this.bytesTransmitted = 0;
      this.backendFramesReceived = 0;
      this.lastFrameTime = Date.now();
      this.isMuted = false;
      this.updateMicStatusVisual();

      // 4. Connect WebSocket Gateway
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${protocol}//${window.location.host}/v1/voice/stream`;
      this.setStatus("Connecting Gateway...", "warning");

      this.ws = new WebSocket(wsUrl);
      this.ws.binaryType = "arraybuffer";

      this.ws.onopen = () => {
        this.setStatus("Authenticating...", "warning");
        this.ws.send(JSON.stringify({
          type: "auth",
          ticket: ticket,
        }));
      };

      this.ws.onmessage = async (event) => {
        if (typeof event.data === "string") {
          this.handleControlMessage(JSON.parse(event.data));
        } else if (event.data instanceof ArrayBuffer) {
          await this.enqueueAudioForPlayback(event.data);
        } else if (event.data instanceof Blob) {
          const arrayBuffer = await event.data.arrayBuffer();
          await this.enqueueAudioForPlayback(arrayBuffer);
        }
      };

      this.ws.onerror = (err) => {
        console.error("WebSocket error:", err);
        this.showError("Voice stream WebSocket error occurred.");
      };

      this.ws.onclose = (event) => {
        console.warn("WebSocket closed. Code:", event.code, "Reason:", event.reason);
        this.cleanupAudio();
        const reasonText = event.reason ? ` - ${event.reason}` : "";
        this.setStatus(`Disconnected (${event.code}${reasonText})`, event.code === 1000 ? "secondary" : "danger");
        this.setAgentState("Offline", "secondary");
        this.btnStart.disabled = false;
        this.btnEnd.disabled = true;
      };

      // 5. Pipe microphone frames to WebSocket and track diagnostics
      this.workletNode.port.onmessage = (event) => {
        this.framesCaptured++;
        this.lastFrameTime = Date.now();

        if (!this.isMuted && this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(event.data);
          this.bytesTransmitted += event.data.byteLength;
        }
      };

      this.startDiagnosticsMonitor();
      this.btnEnd.disabled = false;

    } catch (err) {
      console.error("Failed to start voice call:", err);
      let userMsg = err.message || "Failed to start voice call.";
      if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
        userMsg = "Microphone access was denied. Please allow microphone permissions in your browser to speak with the AI Receptionist.";
      } else if (err.name === "NotFoundError" || err.name === "DevicesNotFoundError") {
        userMsg = "No microphone was detected on your system. Please connect an audio input device.";
      } else if (err.name === "NotReadableError" || err.name === "TrackStartError") {
        userMsg = "Microphone hardware is busy or in use by another application. Please close other software using the mic.";
      }
      this.showError(userMsg);
      this.setStatus("Error", "danger");
      this.btnStart.disabled = false;
      this.cleanupAudio();
    }
  }

  async switchMicrophoneDevice(deviceId) {
    if (!this.micStream) return;
    try {
      console.info("Switching microphone to device:", deviceId || "default");
      // Stop current tracks
      this.micStream.getTracks().forEach(t => t.stop());

      const constraints = {
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          deviceId: deviceId ? { exact: deviceId } : undefined,
        }
      };
      this.micStream = await navigator.mediaDevices.getUserMedia(constraints);
      if (this.micSource) {
        this.micSource.disconnect();
      }
      this.micSource = this.audioCtx.createMediaStreamSource(this.micStream);
      this.micSource.connect(this.workletNode);
      this.isMuted = false;
      this.updateMicStatusVisual();
      console.info("Microphone switched successfully.");
    } catch (e) {
      console.error("Failed to switch microphone device:", e);
      this.showError("Failed to switch microphone device: " + e.message);
    }
  }

  startDiagnosticsMonitor() {
    if (this.diagnosticInterval) clearInterval(this.diagnosticInterval);
    this.diagnosticInterval = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

      const kbSent = (this.bytesTransmitted / 1024).toFixed(1);
      if (this.audioStatsEl) {
        this.audioStatsEl.textContent = `Captured: ${this.framesCaptured} frames | Sent: ${kbSent} KB | Backend: ${this.backendFramesReceived}`;
      }

      // Stall detection: If call active and not muted, but no frame for > 2.5s
      const isStalled = !this.isMuted && (Date.now() - this.lastFrameTime > 2500);
      if (this.stalledWarningEl) {
        if (isStalled) {
          this.stalledWarningEl.classList.remove("d-none");
          this.stalledWarningEl.textContent = "⚠️ Microphone stream stalled: No audio captured in last 3s";
        } else {
          this.stalledWarningEl.classList.add("d-none");
        }
      }

      this.updateMicStatusVisual(isStalled);
    }, 500);
  }

  updateMicStatusVisual(isStalled = false) {
    if (!this.micStatusDot) return;
    if (this.isMuted) {
      this.micStatusDot.className = "badge rounded-pill bg-danger";
      this.micStatusDot.textContent = "Muted";
    } else if (isStalled) {
      this.micStatusDot.className = "badge rounded-pill bg-warning text-dark";
      this.micStatusDot.textContent = "Mic Stalled";
    } else if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.micStatusDot.className = "badge rounded-pill bg-success";
      this.micStatusDot.textContent = "Mic Live";
    } else {
      this.micStatusDot.className = "badge rounded-pill bg-secondary";
      this.micStatusDot.textContent = "Mic Idle";
    }
  }

  handleControlMessage(msg) {
    switch (msg.type) {
      case "session_created":
        this.activeCallId = msg.call_id;
        this.activeConversationId = msg.conversation_id;
        this.setStatus("Call Active", "success");
        this.setAgentState("Listening", "info");

        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({
            type: "start",
            codec: "pcm16",
            sample_rate: 16000,
            channels: 1,
            recording_consent: this.recordingConsent,
          }));
        }
        break;

      case "transcript":
        this.appendTranscript(msg.role, msg.text, msg.is_final);
        break;

      case "speech_state":
        if (msg.speaker === "caller" && msg.state === "speaking") {
          this.lastFinalCallerText = "";
          this.finalizeAiTurnVisual();
          this.flushAudioPlaybackBuffer();
          this.setAgentState("Caller Speaking...", "warning");
        } else if (msg.speaker === "ai_agent") {
          if (msg.state === "speaking") {
            this.setAgentState("AI Speaking...", "primary");
            if (this.currentAiTurnEl) {
              const badge = this.currentAiTurnEl.querySelector(".speaking-badge");
              if (badge) badge.classList.remove("d-none");
            }
          } else if (msg.state === "thinking") {
            this.setAgentState("AI Thinking...", "warning");
          } else {
            this.setAgentState(this.isMuted ? "Muted" : "Listening...", this.isMuted ? "danger" : "info");
            this.finalizeAiTurnVisual();
          }
        }
        break;

      case "audio_diagnostics":
        if (msg.backend_frames !== undefined) {
          this.backendFramesReceived = msg.backend_frames;
        }
        break;

      case "stt_state":
        if (msg.state === "disconnected") {
          this.setAgentState("STT Reconnecting...", "warning");
        } else if (msg.state === "connected") {
          this.setAgentState(this.isMuted ? "Muted" : "Listening...", this.isMuted ? "danger" : "info");
        }
        break;

      case "clear_audio":
        this.flushAudioPlaybackBuffer();
        this.finalizeAiTurnVisual();
        if (this.interimCallerEl) {
          this.interimCallerEl.remove();
          this.interimCallerEl = null;
        }
        this.lastFinalCallerText = "";
        this.setAgentState("Interrupted", "danger");
        break;

      case "session_ended":
        this.setStatus("Call Ended", "secondary");
        this.setAgentState("Offline", "secondary");
        this.finalizeAiTurnVisual();
        if (this.interimCallerEl) {
          this.interimCallerEl.remove();
          this.interimCallerEl = null;
        }
        this.lastFinalCallerText = "";
        this.appendTranscript("system", `Call duration: ${msg.duration_seconds}s (${msg.reason})`);
        break;

      case "latency_telemetry":
        const m = msg.metrics || {};
        console.info("Voice Latency Telemetry:", m);
        const latencyEl = document.getElementById("latency-metric");
        if (latencyEl) {
          latencyEl.textContent = `⚡ Latency: ${m.total_turn_to_first_audio_ms || 0}ms (STT: ${m.stt_final_ms || 0}ms, LLM: ${m.llm_first_token_ms || 0}ms, TTS: ${m.cartesia_first_chunk_ms || 0}ms)`;
          latencyEl.classList.remove("d-none");
        }
        break;

      case "error":
        this.showError(`[${msg.code}] ${msg.message}`);
        this.finalizeAiTurnVisual();
        break;

      default:
        console.debug("Unhandled server frame:", msg);
    }
  }

  finalizeAiTurnVisual() {
    if (this.currentAiTurnEl) {
      const badge = this.currentAiTurnEl.querySelector(".speaking-badge");
      if (badge) badge.remove();
      this.currentAiTurnEl = null;
    }
  }

  async enqueueAudioForPlayback(arrayBuffer) {
    if (!this.audioCtx) return;

    try {
      if (this.audioCtx.state === "suspended") {
        await this.audioCtx.resume();
      }

      const int16Array = new Int16Array(arrayBuffer);
      if (int16Array.length === 0) return;

      const audioBuffer = this.audioCtx.createBuffer(1, int16Array.length, 16000);
      const channelData = audioBuffer.getChannelData(0);

      for (let i = 0; i < int16Array.length; i++) {
        channelData[i] = int16Array[i] / 32768.0;
      }

      const source = this.audioCtx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(this.audioCtx.destination);

      const currentTime = this.audioCtx.currentTime;
      const startTime = Math.max(currentTime, this.nextPlaybackTime);
      source.start(startTime);
      this.nextPlaybackTime = startTime + audioBuffer.duration;

      this.activeAudioSources.push(source);
      source.onended = () => {
        const idx = this.activeAudioSources.indexOf(source);
        if (idx !== -1) this.activeAudioSources.splice(idx, 1);
      };
    } catch (err) {
      console.error("Audio playback error:", err);
      this.showError("Audio playback error: " + (err.message || err));
    }
  }

  flushAudioPlaybackBuffer() {
    for (const source of this.activeAudioSources) {
      try {
        source.stop(0);
        source.disconnect();
      } catch (e) {}
    }
    this.activeAudioSources = [];
    if (this.audioCtx) {
      this.nextPlaybackTime = this.audioCtx.currentTime;
    }
    this.finalizeAiTurnVisual();
  }

  triggerInterrupt() {
    this.flushAudioPlaybackBuffer();
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "interrupt", timestamp: new Date().toISOString() }));
    }
  }

  async toggleMute() {
    this.isMuted = !this.isMuted;

    // Toggle hardware audio tracks
    if (this.micStream) {
      this.micStream.getAudioTracks().forEach(track => {
        track.enabled = !this.isMuted;
      });
    }

    // Resume audio context if unmuting
    if (!this.isMuted && this.audioCtx && this.audioCtx.state === "suspended") {
      try {
        await this.audioCtx.resume();
      } catch (e) {}
    }

    if (this.btnMute) {
      this.btnMute.textContent = this.isMuted ? "Unmute Mic" : "Mute Mic";
      this.btnMute.className = this.isMuted ? "btn btn-danger" : "btn btn-outline-secondary";
    }

    if (this.isMuted) {
      this.setAgentState("Muted", "danger");
    } else {
      this.setAgentState("Listening...", "info");
      this.lastFrameTime = Date.now();
    }

    this.updateMicStatusVisual();

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "set_mic_state", is_muted: this.isMuted }));
    }
  }

  endCall() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "end_session", reason: "user_hangup" }));
    }
    this.cleanupAudio();
  }

  cleanupAudio() {
    if (this.diagnosticInterval) {
      clearInterval(this.diagnosticInterval);
      this.diagnosticInterval = null;
    }
    this.flushAudioPlaybackBuffer();
    if (this.micStream) {
      this.micStream.getTracks().forEach((track) => track.stop());
      this.micStream = null;
    }
    this.micSource = null;
    if (this.workletNode) {
      this.workletNode.disconnect();
      this.workletNode = null;
    }
    if (this.silentGain) {
      this.silentGain.disconnect();
      this.silentGain = null;
    }
    if (this.audioCtx && this.audioCtx.state !== "closed") {
      this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
    }
    this.updateMicStatusVisual();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  window.receptionistClient = new ReceptionistVoiceClient();
});
