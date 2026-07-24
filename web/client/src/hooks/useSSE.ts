import { useEffect, useRef, useCallback } from 'react';

type EventHandler = (type: string, data: any) => void;

export function useSSE(onEvent: EventHandler) {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    let es: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      es = new EventSource('/api/events');
      es.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          handlerRef.current(msg.type, msg.data);
        } catch {}
      };
      es.onerror = () => {
        es?.close();
        reconnectTimer = setTimeout(connect, 3000);
      };
    }

    connect();
    return () => {
      es?.close();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, []);
}
