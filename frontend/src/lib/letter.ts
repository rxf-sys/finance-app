export type Letter = { subject: string; body: string; recipient_name: string };

export function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** Self-contained, print-friendly page for the letter (black on white, serif, no app chrome). */
export function buildPrintHtml(letter: Letter): string {
  return `<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>${escapeHtml(letter.subject)}</title>
<style>
  @page { margin: 25mm 20mm; }
  body { font: 12pt/1.5 Georgia, "Times New Roman", serif; color: #000; background: #fff; max-width: 170mm; margin: 0 auto; padding: 16px; }
  h1 { font-size: 13pt; margin: 2em 0 1.2em; }
  p { white-space: pre-wrap; margin: 0; }
  .to { margin-bottom: 3em; }
</style>
</head>
<body>
<p class="to">${escapeHtml(letter.recipient_name)}</p>
<h1>${escapeHtml(letter.subject)}</h1>
<p>${escapeHtml(letter.body)}</p>
</body>
</html>`;
}

export function buildMailto(letter: Letter): string {
  return `mailto:?subject=${encodeURIComponent(letter.subject)}&body=${encodeURIComponent(letter.body)}`;
}
