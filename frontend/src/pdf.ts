export async function readPdfText(file: File, signal: AbortSignal): Promise<string> {
  const { getDocument, GlobalWorkerOptions, PasswordException } = await import('pdfjs-dist/legacy/build/pdf.mjs');
  if (typeof window !== 'undefined') {
    const { default: workerUrl } = await import('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url');
    GlobalWorkerOptions.workerSrc = workerUrl;
  }

  const data = await file.arrayBuffer();
  signal.throwIfAborted();
  const task = getDocument({ data, useWasm: false, stopAtErrors: true });
  let cleanup: Promise<void> | undefined;
  const destroy = () => cleanup ??= task.destroy().catch(() => {});
  const cancel = () => { void destroy(); };
  signal.addEventListener('abort', cancel, { once: true });

  const pages: string[] = [];
  try {
    const document = await task.promise;
    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber++) {
      signal.throwIfAborted();
      const page = await document.getPage(pageNumber);
      const { items } = await page.getTextContent();
      pages.push(items.map(item => 'str' in item ? item.str + (item.hasEOL ? '\n' : '') : '').join(''));
      page.cleanup();
    }
    signal.throwIfAborted();
  } catch (error) {
    signal.throwIfAborted();
    if (error instanceof PasswordException) throw new Error('This PDF is password-protected. Unlock it before analyzing.');
    throw new Error('Could not read this PDF. Choose a readable PDF or paste its text.');
  } finally {
    signal.removeEventListener('abort', cancel);
    await destroy();
  }

  const text = pages.join('\n').trim();
  if (!text) throw new Error('This PDF has no selectable text. Use OCR or paste the document text.');
  return text;
}
