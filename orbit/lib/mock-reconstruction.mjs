// Gate A has no network adapter. All inputs stay in browser memory.
export function simulateGeneration(onProgress, signal) {
  return new Promise((resolve, reject) => {
    let value = 0;
    const abort = () => {clearInterval(timer); reject(new Error('Demo generation cancelled.'));};
    const timer = setInterval(() => {
      value += 10;
      onProgress(value);
      if (value >= 100) {clearInterval(timer); signal?.removeEventListener('abort', abort); resolve();}
    }, 120);
    if (signal?.aborted) abort(); else signal?.addEventListener('abort', abort, {once: true});
  });
}
