import { ref } from 'vue'
import { TTS_VOICE } from '../constants'

export function useVoice({ addLog }) {
  const voiceOn = ref(true)
  let edgeAudio = null

  function speakBrowserTts(text) {
    try {
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = 'zh-CN'
      utterance.rate = 1.05
      window.speechSynthesis.cancel()
      window.speechSynthesis.speak(utterance)
    } catch (error) { console.warn(error) }
  }

  function speakText(text) {
    // 优先 Edge TTS 神经音色（FE-36）：后端合成 mp3；外网波动/未安装时回落浏览器 speechSynthesis
    fetch(`/api/tts?text=${encodeURIComponent(text.slice(0, 300))}&voice=${TTS_VOICE}`)
      .then((response) => {
        if (!response.ok) throw new Error(`tts ${response.status}`)
        return response.blob()
      })
      .then((blob) => {
        if (edgeAudio) { edgeAudio.pause(); edgeAudio = null }
        edgeAudio = new Audio(URL.createObjectURL(blob))
        edgeAudio.play().catch(() => speakBrowserTts(text))
      })
      .catch(() => speakBrowserTts(text))
  }

  function toggleVoice() {
    voiceOn.value = !voiceOn.value
    if (!voiceOn.value) {
      try { window.speechSynthesis.cancel() } catch (error) { /* 浏览器不支持时静默 */ }
      if (edgeAudio) { edgeAudio.pause(); edgeAudio = null }
    }
    addLog(`疏散语音广播${voiceOn.value ? '开启' : '已静音'}`)
  }

  return { voiceOn, toggleVoice, speakText }
}
