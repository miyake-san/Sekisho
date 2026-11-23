function sekishoPlayground({ enabled }) {
  return {
    enabled,
    message: "",
    chatOutput: "",
    chatBusy: false,
    mediaRecorder: null,
    chunks: [],
    recording: false,
    sttBusy: false,
    transcript: "",
    speechText: "",
    ttsBusy: false,

    async sendChat() {
      if (!this.enabled || !this.message.trim()) return;
      this.chatBusy = true;
      this.chatOutput = "";
      try {
        const form = new FormData();
        form.append("message", this.message);
        const response = await fetch("/playground/chat", { method: "POST", body: form });
        if (!response.ok || !response.body) throw new Error(`Chat failed: ${response.status}`);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split(/\r?\n/);
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            const data = line.slice(5).trim();
            if (!data || data === "[DONE]") continue;
            this.chatOutput += this.extractToken(data);
          }
        }
      } catch (error) {
        this.chatOutput = error.message;
      } finally {
        this.chatBusy = false;
      }
    },

    extractToken(data) {
      try {
        const parsed = JSON.parse(data);
        return parsed.choices?.[0]?.delta?.content || parsed.choices?.[0]?.text || data;
      } catch {
        return data;
      }
    },

    async toggleRecording() {
      if (this.recording) {
        this.mediaRecorder.stop();
        this.recording = false;
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.chunks = [];
      this.mediaRecorder = new MediaRecorder(stream);
      this.mediaRecorder.ondataavailable = (event) => {
        if (event.data.size) this.chunks.push(event.data);
      };
      this.mediaRecorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        await this.transcribe(new Blob(this.chunks, { type: this.mediaRecorder.mimeType || "audio/webm" }));
      };
      this.mediaRecorder.start();
      this.recording = true;
    },

    async transcribe(blob) {
      this.sttBusy = true;
      try {
        const form = new FormData();
        form.append("file", blob, "recording.webm");
        const response = await fetch("/playground/transcribe", { method: "POST", body: form });
        if (!response.ok) throw new Error(`Transcription failed: ${response.status}`);
        const json = await response.json();
        this.transcript = json.text || JSON.stringify(json);
      } catch (error) {
        this.transcript = error.message;
      } finally {
        this.sttBusy = false;
      }
    },

    async speak() {
      if (!this.enabled || !this.speechText.trim()) return;
      this.ttsBusy = true;
      try {
        const form = new FormData();
        form.append("text", this.speechText);
        const response = await fetch("/playground/speak", { method: "POST", body: form });
        if (!response.ok) throw new Error(`Speech failed: ${response.status}`);
        const blob = await response.blob();
        this.$refs.audio.src = URL.createObjectURL(blob);
        await this.$refs.audio.play();
      } finally {
        this.ttsBusy = false;
      }
    },
  };
}
