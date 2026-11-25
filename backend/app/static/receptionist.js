/**
 * FortiSales AI - Autonomous Receptionist Voice Console Client.
 *
 * Implements:
 * 1. Single-use ticket acquisition via REST.
 * 2. WebSocket streaming with First-Frame authentication.
 * 3. AudioWorklet 16kHz PCM16 microphone capture.
 * 4. Jitter-buffered Web Audio API playback for server TTS stream.
 * 5. Instant audio buffer flushing on barge-in ("clear_audio").
 * 6. Live transcription rendering and call lifecycle management.
 */

class ReceptionistVoiceClient {
  constructor() {
    this.token = localStorage.getItem("fortisales_token") || "";
    this.ws = null;
    this.audioCtx = null;
    this.micStream = null;
    this.workletNode = null;

    // Audio Playback Queue
    this.activeAudioSources = [];
    this.nextPlaybackTime = 0;
    this.isMuted = false;
    this.recordingConsent = false;
    this.activeConversationId = null;
    this.activeCallId = null;

    this.initUI();
  }

  initUI() {
    this.btnStart = document.getElementById("btn-start");
    this.btnEnd = document.getElementById("btn-end");
    this.btnMute = document.getElementById("btn-mute");
    this.btnInterrupt = document.getElementById("btn-interrupt");
    this.consentToggle = document.getElementById("recording-consent");
    this.tokenInput = document.getElementById("auth-token");
    this.statusPill = document.getElementById("connection-status");
    this.agentStatePill = document.getElementById("agent-state");
    this.transcriptContainer = document.getElementById("transcript-list");
    this.errorBanner = document.getElementById("error-banner");

    if (this.tokenInput) {
      this.tokenInput.value = this.token;
      this.tokenInput.addEventListener("input", (e) => {
        this.token = e.target.value.trim();
        localStorage.setItem("fortisales_token", this.token);
      });
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

  appendTranscript(role, text, isFinal = true) {
    if (!this.transcriptContainer || !text) return;

    const div = document.createElement("div");
    div.className = `p-2 my-2 rounded ${
      role === "caller" ? "bg-light text-dark border-start border-4 border-primary" : "bg-primary-subtle text-dark border-start border-4 border-success"
    }`;

    const author = role === "caller" ? "Caller" : "AI Receptionist";
    div.innerHTML = `<strong>${author}:</strong> <span>${text}</span>`;
    this.transcriptContainer.appendChild(div);
    this.transcriptContainer.scrollTop = this.transcriptContainer.scrollHeight;
  }

  async startCall() {
    this.hideError();
    if (!this.token) {
      this.showError("Please enter a valid JWT token before starting a voice call.");
      return;
    }

    try {
      this.setStatus("Requesting Ticket...", "warning");
      this.btnStart.disabled = true;

      // 1. Obtain ephemeral single-use ticket
      const ticketRes = await fetch("/api/v1/voice/tickets", {
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

      if (!ticketRes.ok) {
        const err = await ticketRes.json();
        throw new Error(err.detail || `Failed to issue voice ticket (${ticketRes.status})`);
      }

      const ticketData = await ticketRes.json();
      const ticket = ticketData.ticket;

      // 2. Initialize Web Audio API and AudioWorklet
      this.setStatus("Initializing Audio...", "warning");
      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      await this.audioCtx.resume();
      await this.audioCtx.audioWorklet.addModule("/static/pcm-processor.js");

      this.micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      const micSource = this.audioCtx.createMediaStreamSource(this.micStream);
      this.workletNode = new AudioWorkletNode(this.audioCtx, "pcm16-capture-processor");

      // 3. Connect WebSocket Gateway
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${protocol}//${window.location.host}/api/v1/voice/stream`;
      this.setStatus("Connecting Gateway...", "warning");

      this.ws = new WebSocket(wsUrl);
      this.ws.binaryType = "arraybuffer";

      this.ws.onopen = () => {
        this.setStatus("Authenticating...", "warning");
        // Send First-Frame Authentication
        this.ws.send(JSON.stringify({
          type: "auth",
          ticket: ticket,
        }));
      };

      this.ws.onmessage = async (event) => {
        if (typeof event.data === "string") {
          this.handleControlMessage(JSON.parse(event.data));
        } else if (event.data instanceof ArrayBuffer) {
          // Binary audio chunk received from server TTS
          this.enqueueAudioForPlayback(event.data);
        }
      };

      this.ws.onerror = (err) => {
        console.error("WebSocket error:", err);
        this.showError("Voice stream WebSocket error occurred.");
      };

      this.ws.onclose = (event) => {
        console.info("WebSocket closed:", event.code, event.reason);
        this.cleanupAudio();
        this.setStatus(`Disconnected (${event.code})`, "secondary");
        this.setAgentState("Offline", "secondary");
        this.btnStart.disabled = false;
        this.btnEnd.disabled = true;
      };

      // 4. Pipe microphone frames to WebSocket
      this.workletNode.port.onmessage = (event) => {
        if (!this.isMuted && this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(event.data);
        }
      };

      micSource.connect(this.workletNode);
      this.btnEnd.disabled = false;

    } catch (err) {
      console.error("Failed to start voice call:", err);
      this.showError(err.message || "Failed to start voice call.");
      this.setStatus("Error", "danger");
      this.btnStart.disabled = false;
      this.cleanupAudio();
    }
  }

  handleControlMessage(msg) {
    switch (msg.type) {
      case "session_created":
        this.activeCallId = msg.call_id;
        this.activeConversationId = msg.conversation_id;
        this.setStatus("Call Active", "success");
        this.setAgentState("Listening", "info");

        // Send initial start frame with recording consent
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
        if (msg.speaker === "ai_agent") {
          if (msg.state === "speaking") {
            this.setAgentState("AI Speaking...", "primary");
          } else if (msg.state === "thinking") {
            this.setAgentState("AI Thinking...", "warning");
          } else {
            this.setAgentState("Listening...", "info");
          }
        }
        break;

      case "clear_audio":
        // Barge-in signaled: flush local playback buffers immediately!
        this.flushAudioPlaybackBuffer();
        this.setAgentState("Interrupted", "danger");
        break;

      case "session_ended":
        this.setStatus("Call Ended", "secondary");
        this.setAgentState("Offline", "secondary");
        this.appendTranscript("system", `Call duration: ${msg.duration_seconds}s (${msg.reason})`);
        break;

      case "error":
        this.showError(`[${msg.code}] ${msg.message}`);
        break;

      default:
        console.debug("Unhandled server frame:", msg);
    }
  }

  enqueueAudioForPlayback(arrayBuffer) {
    if (!this.audioCtx) return;

    // Convert raw 16kHz signed Int16 array to 32-bit Float32 buffer
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
    // Schedule seamlessly
    const startTime = Math.max(currentTime, this.nextPlaybackTime);
    source.start(startTime);
    this.nextPlaybackTime = startTime + audioBuffer.duration;

    this.activeAudioSources.push(source);
    source.onended = () => {
      const idx = this.activeAudioSources.indexOf(source);
      if (idx !== -1) this.activeAudioSources.splice(idx, 1);
    };
  }

  flushAudioPlaybackBuffer() {
    // Instantly mute and stop all queued audio nodes for zero-latency barge-in
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
  }

  triggerInterrupt() {
    this.flushAudioPlaybackBuffer();
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "interrupt", timestamp: new Date().toISOString() }));
    }
  }

  toggleMute() {
    this.isMuted = !this.isMuted;
    if (this.btnMute) {
      this.btnMute.textContent = this.isMuted ? "Unmute Mic" : "Mute Mic";
      this.btnMute.className = this.isMuted ? "btn btn-danger" : "btn btn-outline-secondary";
    }
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
    this.flushAudioPlaybackBuffer();
    if (this.micStream) {
      this.micStream.getTracks().forEach((track) => track.stop());
      this.micStream = null;
    }
    if (this.workletNode) {
      this.workletNode.disconnect();
      this.workletNode = null;
    }
    if (this.audioCtx && this.audioCtx.state !== "closed") {
      this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  window.receptionistClient = new ReceptionistVoiceClient();
});
