// Chrome/Edge service worker. A service worker cannot play audio, so it keeps
// one offscreen document alive to host the stream (see host.js).

const OFFSCREEN_URL = "offscreen.html";
let creating = null;

async function ensureAudioHost() {
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
    documentUrls: [chrome.runtime.getURL(OFFSCREEN_URL)],
  });
  if (contexts.length) return;
  if (!creating) {
    creating = chrome.offscreen.createDocument({
      url: OFFSCREEN_URL,
      reasons: ["AUDIO_PLAYBACK"],
      justification: "Plays the internet radio stream and analyses it for the spectrum display.",
    }).finally(() => { creating = null; });
  }
  await creating;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "ensure-audio") {
    ensureAudioHost().then(() => sendResponse(true), (err) => sendResponse(String(err)));
    return true;                                   // async response
  }
  return false;
});
