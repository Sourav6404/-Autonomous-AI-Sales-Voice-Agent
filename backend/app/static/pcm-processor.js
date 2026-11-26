/**
 * Robust PCM16 AudioWorklet Processor for FortiSales AI.
 * 
 * Captures microphone input at any browser sample rate (16kHz, 44.1kHz, 48kHz, 96kHz),
 * resamples with fractional-phase linear interpolation to exactly 16,000 Hz mono PCM,
 * quantizes 32-bit float to 16-bit signed linear PCM (little-endian),
 * and emits consistent 20ms frames (320 samples = 640 bytes) to the main thread.
 */

class PCM16CaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetSampleRate = 16000;
    this.sourceSampleRate = sampleRate; // Browser context sample rate
    this.samplesPerFrame = 320; // 20ms at 16,000 Hz

    // Fractional phase accumulator for drift-free resampling
    this.resampleRatio = this.sourceSampleRate / this.targetSampleRate;
    this.phase = 0.0;
    this.lastSample = 0.0;

    // Pre-allocated ring buffer to eliminate memory allocations and GC pauses in audio thread
    this.bufferCapacity = 16384;
    this.ringBuffer = new Float32Array(this.bufferCapacity);
    this.writeIndex = 0;
    this.readIndex = 0;
    this.bufferedSamples = 0;

    // Pre-allocated frame buffer
    this.pcmBuffer = new ArrayBuffer(this.samplesPerFrame * 2);
    this.pcmView = new Int16Array(this.pcmBuffer);
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || !input[0] || input[0].length === 0) {
      return true;
    }

    const channelData = input[0];
    const inputLength = channelData.length;

    // Resample channelData to 16,000 Hz
    if (this.sourceSampleRate === this.targetSampleRate) {
      // 1:1 direct push
      for (let i = 0; i < inputLength; i++) {
        if (this.bufferedSamples < this.bufferCapacity) {
          this.ringBuffer[this.writeIndex] = channelData[i];
          this.writeIndex = (this.writeIndex + 1) % this.bufferCapacity;
          this.bufferedSamples++;
        }
      }
    } else {
      // High-quality linear interpolation with fractional phase preservation across 128-sample blocks
      let inIdx = 0;
      while (inIdx < inputLength) {
        const nextInIdx = Math.floor(this.phase);
        if (nextInIdx >= inputLength) {
          this.phase -= inputLength;
          break;
        }

        const frac = this.phase - nextInIdx;
        const currentSample = channelData[nextInIdx];
        const nextSample = (nextInIdx + 1 < inputLength) ? channelData[nextInIdx + 1] : currentSample;
        const interpolated = currentSample + frac * (nextSample - currentSample);

        if (this.bufferedSamples < this.bufferCapacity) {
          this.ringBuffer[this.writeIndex] = interpolated;
          this.writeIndex = (this.writeIndex + 1) % this.bufferCapacity;
          this.bufferedSamples++;
        }

        this.phase += this.resampleRatio;
      }
    }

    // Emit 20ms frames (320 samples = 640 bytes)
    while (this.bufferedSamples >= this.samplesPerFrame) {
      const outputBuffer = new ArrayBuffer(this.samplesPerFrame * 2);
      const outputView = new Int16Array(outputBuffer);

      for (let i = 0; i < this.samplesPerFrame; i++) {
        const sample = this.ringBuffer[this.readIndex];
        this.readIndex = (this.readIndex + 1) % this.bufferCapacity;

        // Clamp [-1.0, 1.0] and quantize to Int16 Little-Endian
        const clamped = Math.max(-1.0, Math.min(1.0, sample));
        outputView[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7FFF;
      }
      this.bufferedSamples -= this.samplesPerFrame;

      // Zero-copy transfer to main thread
      this.port.postMessage(outputBuffer, [outputBuffer]);
    }

    return true;
  }
}

registerProcessor("pcm16-capture-processor", PCM16CaptureProcessor);
