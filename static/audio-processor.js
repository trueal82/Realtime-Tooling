/**
 * Audio Processor Worklet
 * Processes microphone input and sends chunks to the main thread
 */

class AudioProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.bufferSize = 2400; // 100ms at 24kHz
        this.buffer = new Float32Array(this.bufferSize);
        this.bufferIndex = 0;
    }

    process(inputs, outputs, parameters) {
        const input = inputs[0];

        if (input.length > 0) {
            const channelData = input[0];

            for (let i = 0; i < channelData.length; i++) {
                this.buffer[this.bufferIndex++] = channelData[i];

                if (this.bufferIndex >= this.bufferSize) {
                    // Send the buffer to the main thread
                    this.port.postMessage({
                        type: 'audio',
                        audio: this.buffer.slice()
                    });

                    this.bufferIndex = 0;
                }
            }
        }

        return true;
    }
}

registerProcessor('audio-processor', AudioProcessor);
