import { apiBaseUrl } from '../config/apiBaseUrl';

export function websocketUrl(path) {
  const apiBase = apiBaseUrl();
  const origin = /^https?:\/\//i.test(apiBase) ? new URL(apiBase).origin : window.location.origin;
  const target = new URL(path, origin);
  target.protocol = target.protocol === 'https:' ? 'wss:' : 'ws:';
  return target.toString();
}

export function openBearerWebSocket(path, token, onMessage) {
  if (!token || !window.WebSocket) return () => {};

  let socket;
  let stopped = false;
  let retryTimer;
  const connect = () => {
    if (stopped) return;
    socket = new WebSocket(websocketUrl(path), ['bearer', token]);
    socket.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        // Ignore malformed frames; the normal REST refresh remains available.
      }
    };
    socket.onclose = () => {
      if (!stopped) retryTimer = window.setTimeout(connect, 3000);
    };
  };
  connect();
  return () => {
    stopped = true;
    window.clearTimeout(retryTimer);
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000, 'component closed');
  };
}
