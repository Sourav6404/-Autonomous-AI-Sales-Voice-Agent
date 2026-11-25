/**
 * PCM16 AudioWorklet Processor for FortiSales AI.
 * 
 * Captures browser microphone input, resamples to 16,000 Hz mono,
 * quantizes 32-bit float to 16-bit signed linear PCM (little-endian),
 * and emits 20ms frames (320 samples = 640 bytes) to the main thread.
 */

class PCM16CaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetSampleRate = 16000;
    this.sourceSampleRate = sampleRate; // Browser audio context sample rate (e.g. 44100 or 48000)
    this.buffer = new Float32Array(0);
    this.samplesPerFrame = 320; // 20ms at 16,000 Hz
    this.resampleRatio = this.sourceSampleRate / this.targetSampleRate;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || !input[0] || input[0].length === 0) {
      return true;
    }

    const channelData = input[0];

    // Resample down to 16,000 Hz if needed
    let resampled;
    if (this.sourceSampleRate === this.targetSampleRate) {
      resampled = channelData;
    } else {
      const outputLength = Math.floor(channelData.length / this.resampleRatio);
      resampled = new Float32Array(outputLength);
      for (let i = 0; i < outputLength; i++) {
        const sourceIndex = Math.floor(i * this.resampleRatio);
        resampled[i] = channelData[sourceIndex];
      }
    }

    // Append to internal accumulation buffer
    const newBuffer = new Float32Array(this.buffer.length + resampled.length);
    newBuffer.set(this.buffer);
    newBuffer.set(resampled, this.buffer.length);
    this.buffer = newBuffer;

    // Emit full 20ms (320 samples) PCM16 frames
    while (this.buffer.length >= this.samplesPerFrame) {
      const frameSamples = this.buffer.subarray(0, this.samplesPerFrame);
      this.buffer = this.buffer.subarray(this.samplesPerFrame);

      // Quantize Float32 [-1.0, 1.0] to Int16 [-32768, 32767] Little-Endian
      const pcm16 = new Int16Array(this.samplesPerFrame);
      for (let i = 0; i < this.samplesPerFrame; i++) {
        const s = Math.max(-1, Math.min(1, frameSamples[i]));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }

      // Transfer ArrayBuffer to main thread
      this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
    }

    return true;
  }
}

registerProcessor("pcm16-capture-processor", PCM16CaptureProcessor);
