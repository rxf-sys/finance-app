import { useQuery } from "@tanstack/react-query";
import { Copy, Mail, Printer } from "lucide-react";
import { cancellationLetterQuery } from "@/api/planning-queries";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { buildMailto, buildPrintHtml, type Letter } from "@/lib/letter";

type Props = { contractId: string; open: boolean; onOpenChange: (open: boolean) => void };

function LetterBody({ letter }: { letter: Letter }) {
  const toast = useToast();

  async function copy() {
    try {
      await navigator.clipboard.writeText(`${letter.subject}\n\n${letter.body}`);
      toast.show("In die Zwischenablage kopiert.");
    } catch {
      toast.show("Kopieren war nicht möglich. Bitte den Text von Hand markieren.", "error");
    }
  }

  function print() {
    const win = window.open("", "_blank");
    if (!win) {
      toast.show("Das Druckfenster wurde blockiert. Bitte Pop-ups für diese Seite erlauben.", "error");
      return;
    }
    win.document.open();
    win.document.write(buildPrintHtml(letter));
    win.document.close();
    win.focus();
    win.print();
  }

  return (
    <>
      <div className="mt-4 space-y-3">
        <div className="rounded-lg border border-border bg-surface-muted p-4">
          <p className="text-xs text-text-muted">An: {letter.recipient_name}</p>
          <p className="mt-2 text-sm font-semibold">{letter.subject}</p>
          <p className="mt-3 text-sm whitespace-pre-wrap">{letter.body}</p>
        </div>
        <Alert tone="info">
          Die App verschickt nichts selbst. Kopiere den Text, drucke ihn oder öffne ihn in deinem
          E-Mail-Programm. Die Adresse des Anbieters trägst du dort selbst ein. Prüfe Angaben und Fristen,
          bevor du sendest.
        </Alert>
      </div>
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <Button variant="secondary" onClick={() => void copy()}>
          <Copy aria-hidden />
          Kopieren
        </Button>
        <Button variant="secondary" onClick={print}>
          <Printer aria-hidden />
          Drucken
        </Button>
        <Button asChild>
          <a href={buildMailto(letter)}>
            <Mail aria-hidden />
            In E-Mail-Programm öffnen
          </a>
        </Button>
      </div>
    </>
  );
}

export function CancellationLetterDialog({ contractId, open, onOpenChange }: Props) {
  const { data, isPending, isError } = useQuery({ ...cancellationLetterQuery(contractId), enabled: open });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogTitle>Kündigungsschreiben</DialogTitle>
        <DialogDescription>Ein Entwurf, den du anpassen und selbst versenden kannst.</DialogDescription>
        {isPending && <p className="mt-4 text-sm text-text-muted">Lade …</p>}
        {isError && (
          <Alert tone="error" className="mt-4">
            Das Schreiben konnte nicht geladen werden.
          </Alert>
        )}
        {data && <LetterBody letter={data} />}
      </DialogContent>
    </Dialog>
  );
}
