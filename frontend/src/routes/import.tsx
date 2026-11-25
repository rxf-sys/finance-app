import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, ArrowLeft, Check, FileUp, Loader2 } from "lucide-react";
import { type DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { api, mutationErrorMessage, unwrap } from "@/api/client";
import {
  accountsQuery,
  categoriesQuery,
  importPresetsQuery,
  importProfilesQuery,
  importRunsQuery,
  invalidateLedger,
} from "@/api/queries";
import type { components } from "@/api/schema";
import { Amount } from "@/components/amount";
import { CategoryBadge } from "@/components/category-badge";
import { FormField } from "@/components/form-field";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { formatDate, formatDateTime } from "@/lib/format";
import {
  buildFormat,
  type CsvFormat,
  checkUploadFile,
  describeDateFormat,
  describeMissing,
  type FileSettings,
  fileToBase64,
  ROLE_LABEL,
  ROLES,
  type Role,
  type Roles,
  rolesFromFormat,
  settingsFromFormat,
} from "@/lib/import";
import { cn } from "@/lib/utils";

type Analysis = components["schemas"]["AnalyzeOut"];
type Preview = components["schemas"]["PreviewOut"];
type ImportRun = components["schemas"]["ImportRunOut"];

type UploadedFile = { name: string; size: number; base64: string };
type Step = 1 | 2 | 3 | 4;

const STEPS = ["Datei", "Format", "Vorschau", "Fertig"] as const;

const DEFAULT_SETTINGS: FileSettings = {
  delimiter: ";",
  dateFormat: "%d.%m.%Y",
  decimalSeparator: ",",
  headerLine: null,
};

const DELIMITERS = [
  { value: ";", label: "Semikolon (;)" },
  { value: ",", label: "Komma (,)" },
  { value: "\t", label: "Tabulator" },
];
const DECIMALS = [
  { value: ",", label: "Komma (1.234,56)" },
  { value: ".", label: "Punkt (1,234.56)" },
];
const DATE_FORMATS: { value: string; label: string }[] = [
  { value: "%d.%m.%Y", label: "TT.MM.JJJJ" },
  { value: "%d.%m.%y", label: "TT.MM.JJ" },
  { value: "%Y-%m-%d", label: "JJJJ-MM-TT" },
  { value: "%d/%m/%Y", label: "TT/MM/JJJJ" },
  { value: "%m/%d/%Y", label: "MM/TT/JJJJ" },
].map(({ value, label }) => ({ value: JSON.stringify(value), label }));

const CONFIDENCE_LABEL = { high: "hoch", medium: "mittel", low: "niedrig" } as const;

function Stepper({ step }: { step: Step }) {
  return (
    <ol className="flex items-center gap-2 text-sm" aria-label="Fortschritt">
      {STEPS.map((label, index) => {
        const number = index + 1;
        const done = number < step;
        const current = number === step;
        return (
          <li key={label} className="flex items-center gap-2" aria-current={current ? "step" : undefined}>
            <span
              className={cn(
                "flex size-6 items-center justify-center rounded-full border text-xs",
                done && "border-primary bg-primary text-on-primary",
                current && "border-primary text-primary",
                !done && !current && "border-border text-text-muted",
              )}
            >
              {done ? <Check className="size-3.5" aria-hidden /> : number}
            </span>
            <span className={cn("hidden sm:inline", current ? "font-medium" : "text-text-muted")}>
              {label}
            </span>
            {number < STEPS.length && <span className="h-px w-4 bg-border sm:w-8" aria-hidden />}
          </li>
        );
      })}
    </ol>
  );
}

export function ImportPage({ account: preselected }: { account?: string }) {
  const queryClient = useQueryClient();
  const { data: accounts = [] } = useQuery(accountsQuery);
  const { data: presets = [] } = useQuery(importPresetsQuery);
  const { data: profiles = [] } = useQuery(importProfilesQuery);

  const [step, setStep] = useState<Step>(1);
  const [accountId, setAccountId] = useState(preselected ?? "");
  const [file, setFile] = useState<UploadedFile | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [source, setSource] = useState("manual");
  const [base, setBase] = useState<CsvFormat | null>(null);
  const [roles, setRoles] = useState<Roles>([]);
  const [settings, setSettings] = useState<FileSettings>(DEFAULT_SETTINGS);
  const [dirty, setDirty] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [saveName, setSaveName] = useState("");
  const [result, setResult] = useState<{ run: ImportRun; from: string | null; to: string | null } | null>(
    null,
  );

  const activeAccounts = useMemo(() => accounts.filter((a) => !a.is_archived), [accounts]);
  // Default to the only account; an invalid preselection (deleted or archived) is dropped.
  useEffect(() => {
    if (accounts.length === 0) return;
    setAccountId((current) => {
      if (activeAccounts.some((a) => a.id === current)) return current;
      return activeAccounts.length === 1 ? activeAccounts[0].id : "";
    });
  }, [accounts.length, activeAccounts]);

  const headers = analysis?.headers ?? [];
  const built = useMemo(() => buildFormat(headers, roles, settings, base), [headers, roles, settings, base]);

  function applyFormat(format: CsvFormat, nextHeaders: string[]) {
    setBase(format);
    setRoles(rolesFromFormat(nextHeaders, format.columns));
    setSettings(settingsFromFormat(format));
    setDirty(false);
  }

  function chooseSource(value: string) {
    setSource(value);
    if (value === "manual") {
      setBase(null);
      setRoles(headers.map(() => "ignore"));
      setSettings(DEFAULT_SETTINGS);
      setDirty(false);
    } else if (value === "detected" && analysis?.format) {
      applyFormat(analysis.format, headers);
    } else if (value.startsWith("preset:")) {
      const preset = presets.find((p) => p.key === value.slice(7));
      if (preset) applyFormat(preset.format, headers);
    } else if (value.startsWith("profile:")) {
      const profile = profiles.find((p) => p.id === value.slice(8));
      if (profile) applyFormat(profile.format, headers);
    }
  }

  const analyze = useMutation({
    mutationFn: async (upload: UploadedFile) =>
      unwrap(
        await api.POST("/api/imports/analyze", {
          body: { content_base64: upload.base64, filename: upload.name },
        }),
      ),
    onSuccess: (data) => {
      setAnalysis(data);
      setPreview(null);
      setSaveName("");
      if (data.format) {
        setSource("detected");
        applyFormat(data.format, data.headers);
      } else {
        setSource("manual");
        setBase(null);
        setRoles(data.headers.map(() => "ignore"));
        setSettings(DEFAULT_SETTINGS);
        setDirty(false);
      }
      setStep(2);
    },
  });

  async function pickFile(chosen: File | undefined) {
    if (!chosen) return;
    setFileError(null);
    const problem = checkUploadFile(chosen);
    if (problem) {
      setFile(null);
      setFileError(problem);
      return;
    }
    try {
      const upload = { name: chosen.name, size: chosen.size, base64: await fileToBase64(chosen) };
      setFile(upload);
      analyze.mutate(upload);
    } catch {
      setFileError("Die Datei konnte nicht gelesen werden.");
    }
  }

  const requestBody = (format: CsvFormat) =>
    file && accountId
      ? { account_id: accountId, content_base64: file.base64, filename: file.name, format }
      : null;

  const previewMutation = useMutation({
    mutationFn: async (format: CsvFormat) => {
      const body = requestBody(format);
      if (!body) throw new Error("incomplete");
      return unwrap(await api.POST("/api/imports/preview", { body }));
    },
    onSuccess: (data) => {
      setPreview(data);
      setStep(3);
    },
  });

  const commit = useMutation({
    mutationFn: async (format: CsvFormat) => {
      const body = requestBody(format);
      if (!body || !preview) throw new Error("incomplete");
      const name = saveName.trim();
      if (name && showSave) {
        unwrap(await api.POST("/api/imports/profiles", { body: { name, format } }));
      }
      const presetLabel = source.startsWith("preset:")
        ? presets.find((p) => `preset:${p.key}` === source)?.label
        : null;
      const profileName = name || presetLabel || profiles.find((p) => `profile:${p.id}` === source)?.name;
      const run = unwrap(await api.POST("/api/imports", { body: { ...body, profile_name: profileName } }));
      const complete = preview.rows.length >= preview.rows_new + preview.rows_duplicate;
      const dates = preview.rows.map((r) => r.booking_date).sort();
      return {
        run,
        from: complete ? (dates[0] ?? null) : null,
        to: complete ? (dates[dates.length - 1] ?? null) : null,
      };
    },
    onSuccess: async (data) => {
      setResult(data);
      setStep(4);
      await invalidateLedger(queryClient);
    },
  });

  function reset() {
    setStep(1);
    setFile(null);
    setAnalysis(null);
    setPreview(null);
    setResult(null);
    setSaveName("");
    setFileError(null);
    analyze.reset();
    previewMutation.reset();
    commit.reset();
  }

  const unrecognized =
    analysis !== null && analysis.unmapped_required.length > 0 && source === "detected" && !dirty;
  const blockers = unrecognized
    ? [`Nicht erkannt: ${describeMissing(analysis.unmapped_required)}. Bitte prüfen oder anpassen.`]
    : built.problems;
  const showSave = !(
    !dirty &&
    (source.startsWith("preset:") || source.startsWith("profile:") || analysis?.preset_key)
  );

  function setRole(index: number, role: Role) {
    setRoles((current) => current.map((r, i) => (i === index ? role : r)));
    setDirty(true);
  }
  function updateSettings(patch: Partial<FileSettings>) {
    setSettings((current) => ({ ...current, ...patch }));
    setDirty(true);
  }

  const sourceOptions = [
    ...(analysis?.format ? [{ value: "detected", label: "Erkanntes Format" }] : []),
    { value: "manual", label: "Manuell zuordnen" },
    ...presets.map((p) => ({ value: `preset:${p.key}`, label: p.label })),
    ...profiles.map((p) => ({ value: `profile:${p.id}`, label: `Gespeichert: ${p.name}` })),
  ];
  const detectedPreset = analysis?.preset_key
    ? presets.find((p) => p.key === analysis.preset_key)
    : undefined;
  const dateKey = JSON.stringify(settings.dateFormat);
  const dateOptions = DATE_FORMATS.some((o) => o.value === dateKey)
    ? DATE_FORMATS
    : [
        {
          value: dateKey,
          label: `Wie erkannt (${describeDateFormat(settings.dateFormat)})`,
        },
        ...DATE_FORMATS,
      ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Import</h1>
        <Stepper step={step} />
      </div>

      {step === 1 && (
        <UploadStep
          accounts={activeAccounts}
          accountId={accountId}
          onAccount={setAccountId}
          onFile={pickFile}
          file={file}
          busy={analyze.isPending}
          error={
            fileError ??
            mutationErrorMessage(analyze.error, {
              413: "Die Datei ist größer als 5 MB und kann nicht importiert werden.",
              422: "Die Datei konnte nicht gelesen werden.",
            })
          }
        />
      )}

      {step === 2 && analysis && (
        <Card className="space-y-5">
          <div>
            <CardTitle>Spalten zuordnen</CardTitle>
            <CardDescription>
              {file?.name}
              {" · "}
              {detectedPreset && source === "detected" ? (
                <span className="font-medium text-positive">Erkannt: {detectedPreset.label}</span>
              ) : analysis.format ? (
                <>Format vermutet, Sicherheit: {CONFIDENCE_LABEL[analysis.confidence]}</>
              ) : (
                <>Das Format wurde nicht erkannt, bitte die Spalten selbst zuordnen.</>
              )}
            </CardDescription>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="import-source">Format</Label>
            <Select id="import-source" value={source} onValueChange={chooseSource} options={sourceOptions} />
          </div>

          {headers.length > 0 ? (
            <MappingTable
              headers={headers}
              rows={analysis.sample_rows.slice(0, 5)}
              roles={roles}
              onRole={setRole}
            />
          ) : (
            <Alert tone="error">
              In der Datei wurde keine Kopfzeile gefunden. Ist es wirklich eine CSV-Datei?
            </Alert>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="import-delimiter">Trennzeichen</Label>
              <Select
                id="import-delimiter"
                value={settings.delimiter}
                onValueChange={(v) => updateSettings({ delimiter: v as FileSettings["delimiter"] })}
                options={DELIMITERS}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="import-date">Datumsformat</Label>
              <Select
                id="import-date"
                value={dateKey}
                onValueChange={(v) => updateSettings({ dateFormat: JSON.parse(v) as string })}
                options={dateOptions}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="import-decimal">Dezimaltrennzeichen</Label>
              <Select
                id="import-decimal"
                value={settings.decimalSeparator}
                onValueChange={(v) =>
                  updateSettings({ decimalSeparator: v as FileSettings["decimalSeparator"] })
                }
                options={DECIMALS}
              />
            </div>
            <FormField
              label="Kopfzeile (Zeilennummer)"
              type="number"
              min={1}
              inputMode="numeric"
              placeholder="automatisch"
              value={settings.headerLine ?? ""}
              onChange={(e) => {
                const n = Number.parseInt(e.target.value, 10);
                updateSettings({ headerLine: Number.isFinite(n) && n >= 1 ? n : null });
              }}
              hint="Leer lassen, damit die Zeile automatisch gefunden wird."
            />
          </div>

          {blockers.length > 0 && (
            <Alert tone="error">
              <ul className="list-inside list-disc">
                {blockers.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            </Alert>
          )}
          {previewMutation.error && (
            <Alert tone="error">
              {mutationErrorMessage(previewMutation.error, {
                400: "Das Format passt nicht zur Datei. Bitte Zuordnung und Trennzeichen prüfen.",
                413: "Die Datei ist größer als 5 MB und kann nicht importiert werden.",
                422: "Das Format passt nicht zur Datei. Bitte Zuordnung und Trennzeichen prüfen.",
              })}
            </Alert>
          )}

          <div className="flex justify-between gap-2">
            <Button variant="secondary" onClick={reset}>
              <ArrowLeft aria-hidden /> Andere Datei
            </Button>
            <Button
              disabled={blockers.length > 0 || !built.format || !accountId || previewMutation.isPending}
              onClick={() => built.format && previewMutation.mutate(built.format)}
            >
              {previewMutation.isPending && <Loader2 className="animate-spin" aria-hidden />}
              Vorschau laden
            </Button>
          </div>
        </Card>
      )}

      {step === 3 && preview && (
        <PreviewStep
          preview={preview}
          showSave={showSave}
          saveName={saveName}
          onSaveName={setSaveName}
          pending={commit.isPending}
          error={mutationErrorMessage(commit.error, {
            409: "Ein gespeichertes Format mit diesem Namen gibt es schon.",
            413: "Die Datei ist größer als 5 MB und kann nicht importiert werden.",
          })}
          onBack={() => setStep(2)}
          onImport={() => built.format && commit.mutate(built.format)}
        />
      )}

      {step === 4 && result && <ResultStep result={result} accountId={accountId} onAgain={reset} />}

      {accountId && <ImportHistory accountId={accountId} />}
    </div>
  );
}

function UploadStep(props: {
  accounts: { id: string; name: string }[];
  accountId: string;
  onAccount: (id: string) => void;
  onFile: (file: File | undefined) => void;
  file: UploadedFile | null;
  busy: boolean;
  error: string | null;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  if (props.accounts.length === 0) {
    return (
      <Card className="flex flex-col items-center gap-3 py-10 text-center">
        <CardTitle>Zuerst ein Konto anlegen</CardTitle>
        <CardDescription>Importierte Buchungen gehören immer zu einem Konto.</CardDescription>
        <Button asChild>
          <Link to="/accounts">Zu den Konten</Link>
        </Button>
      </Card>
    );
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    props.onFile(event.dataTransfer.files[0]);
  }

  return (
    <Card className="space-y-5">
      <div>
        <CardTitle>Konto und Datei wählen</CardTitle>
        <CardDescription>
          CSV-Export deiner Bank, bis 5 MB. Die Datei wird nur zum Import hochgeladen.
        </CardDescription>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="import-account">Konto</Label>
        <Select
          id="import-account"
          value={props.accountId || "none"}
          onValueChange={props.onAccount}
          options={[
            ...(props.accountId ? [] : [{ value: "none", label: "Konto wählen" }]),
            ...props.accounts.map((a) => ({ value: a.id, label: a.name })),
          ]}
        />
      </div>
      {/* biome-ignore lint/a11y/noStaticElementInteractions: drop target; the button inside is the keyboard path */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
        className={cn(
          "flex flex-col items-center gap-3 rounded-xl border-2 border-dashed px-4 py-10 text-center",
          dragging ? "border-primary bg-primary/5" : "border-border",
        )}
      >
        {props.busy ? (
          <Loader2 className="size-8 animate-spin text-text-muted" aria-hidden />
        ) : (
          <FileUp className="size-8 text-text-muted" aria-hidden />
        )}
        <p className="text-sm">
          {props.busy ? `${props.file?.name} wird analysiert …` : "CSV-Datei hierher ziehen oder auswählen"}
        </p>
        <input
          ref={input}
          type="file"
          accept=".csv,.txt,text/csv,text/plain"
          className="sr-only"
          aria-label="CSV-Datei auswählen"
          onChange={(e) => {
            props.onFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <Button
          variant="secondary"
          disabled={props.busy || !props.accountId}
          onClick={() => input.current?.click()}
        >
          Datei auswählen
        </Button>
        {!props.accountId && <p className="text-xs text-text-muted">Bitte zuerst ein Konto wählen.</p>}
      </div>
      {props.error && <Alert tone="error">{props.error}</Alert>}
    </Card>
  );
}

function MappingTable(props: {
  headers: string[];
  rows: string[][];
  roles: Roles;
  onRole: (index: number, role: Role) => void;
}) {
  const options = ROLES.map((role) => ({ value: role, label: ROLE_LABEL[role] }));
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-max border-collapse text-sm">
        <thead>
          <tr className="bg-surface-muted">
            {props.headers.map((header, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: columns are positional
              <th key={index} className="max-w-56 px-3 py-2 text-left font-medium">
                <span className="block truncate">{header || `Spalte ${index + 1}`}</span>
              </th>
            ))}
          </tr>
          <tr>
            {props.headers.map((header, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: columns are positional
              <th key={index} className="px-2 py-2 text-left font-normal">
                <Select
                  aria-label={`Zuordnung für ${header || `Spalte ${index + 1}`}`}
                  className={cn("h-9 min-w-40", props.roles[index] !== "ignore" && "border-primary")}
                  value={props.roles[index] ?? "ignore"}
                  onValueChange={(role) => props.onRole(index, role as Role)}
                  options={options}
                />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {props.rows.map((row, rowIndex) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: sample rows have no id
            <tr key={rowIndex} className="border-t border-border">
              {props.headers.map((_, index) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: columns are positional
                <td key={index} className="max-w-56 px-3 py-1.5 text-text-muted">
                  <span className="block truncate">{row[index] ?? ""}</span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Count({ label, value, tone }: { label: string; value: number; tone?: "error" }) {
  return (
    <div className="rounded-lg border border-border px-3 py-2">
      <p className="text-xs text-text-muted">{label}</p>
      <p
        className={cn("text-xl font-semibold tabular-nums", tone === "error" && value > 0 && "text-negative")}
      >
        {value}
      </p>
    </div>
  );
}

function PreviewStep(props: {
  preview: Preview;
  showSave: boolean;
  saveName: string;
  onSaveName: (name: string) => void;
  pending: boolean;
  error: string | null;
  onBack: () => void;
  onImport: () => void;
}) {
  const { preview } = props;
  const { data: categories = [] } = useQuery(categoriesQuery);
  const byId = useMemo(() => new Map(categories.map((c) => [c.id, c])), [categories]);
  const shown = preview.rows.length;
  const total = preview.rows_new + preview.rows_duplicate;

  function suggestion(row: Preview["rows"][number]) {
    if (!row.suggested_category_id || !row.suggested_category_name) return null;
    const category = byId.get(row.suggested_category_id);
    return (
      <CategoryBadge
        category={{
          name: row.suggested_category_name,
          icon: category?.icon ?? null,
          color: category?.color ?? null,
        }}
      />
    );
  }

  return (
    <Card className="space-y-5">
      <div>
        <CardTitle>Vorschau</CardTitle>
        <CardDescription>Noch nichts gespeichert. Prüfe die Zeilen, dann importieren.</CardDescription>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Count label="Neu" value={preview.rows_new} />
        <Count label="Duplikate" value={preview.rows_duplicate} />
        <Count label="Übersprungen" value={preview.rows_skipped} />
        <Count label="Fehler" value={preview.errors_total} tone="error" />
      </div>

      {preview.errors_total > 0 && (
        <Alert tone="error">
          <p className="flex items-center gap-2 font-medium">
            <AlertTriangle className="size-4" aria-hidden /> {preview.errors_total} Zeilen konnten nicht
            gelesen werden
          </p>
          <ul className="mt-1 list-inside list-disc">
            {preview.errors.map((error) => (
              <li key={`${error.line_no}-${error.message}`}>
                Zeile {error.line_no}: {error.message}
              </li>
            ))}
          </ul>
          {preview.errors_total > preview.errors.length && (
            <p className="mt-1">… und {preview.errors_total - preview.errors.length} weitere.</p>
          )}
        </Alert>
      )}

      {shown > 0 && (
        <>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-text-muted">
                  <th className="py-2 pr-3 font-normal">Datum</th>
                  <th className="px-3 py-2 font-normal">Gegenpartei und Zweck</th>
                  <th className="px-3 py-2 font-normal">Kategorie</th>
                  <th className="py-2 pl-3 text-right font-normal">Betrag</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row) => (
                  <tr
                    key={row.line_no}
                    className={cn("border-b border-border", row.is_duplicate && "opacity-50")}
                  >
                    <td className="py-2 pr-3 whitespace-nowrap">{formatDate(row.booking_date)}</td>
                    <td className="max-w-xs px-3 py-2">
                      <span className="block truncate font-medium">{row.counterparty_name ?? "—"}</span>
                      <span className="block truncate text-xs text-text-muted">{row.purpose}</span>
                    </td>
                    <td className="px-3 py-2">
                      {row.is_duplicate ? <Badge>bereits vorhanden</Badge> : suggestion(row)}
                    </td>
                    <td className="py-2 pl-3 text-right">
                      <Amount cents={row.amount_cents} currency={row.currency} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="divide-y divide-border md:hidden">
            {preview.rows.map((row) => (
              <li key={row.line_no} className={cn("space-y-1 py-2.5", row.is_duplicate && "opacity-50")}>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0 truncate text-sm font-medium">{row.counterparty_name ?? "—"}</span>
                  <Amount cents={row.amount_cents} currency={row.currency} className="shrink-0 text-sm" />
                </div>
                <p className="truncate text-xs text-text-muted">{row.purpose}</p>
                <div className="flex items-center justify-between gap-2 text-xs text-text-muted">
                  <span>{formatDate(row.booking_date)}</span>
                  {row.is_duplicate ? <Badge>bereits vorhanden</Badge> : suggestion(row)}
                </div>
              </li>
            ))}
          </ul>
          {shown < total && (
            <p className="text-xs text-text-muted">
              Die Vorschau zeigt die ersten {shown} von {total} Zeilen.
            </p>
          )}
        </>
      )}

      {props.showSave && (
        <FormField
          label="Format speichern als …"
          value={props.saveName}
          onChange={(e) => props.onSaveName(e.target.value)}
          maxLength={100}
          placeholder="z. B. Sparkasse Girokonto"
          hint="Optional. Beim nächsten Import lässt sich das Format direkt auswählen."
        />
      )}

      {props.error && <Alert tone="error">{props.error}</Alert>}
      {preview.rows_new === 0 && preview.errors_total === 0 && (
        <Alert tone="info">Alle Zeilen sind bereits vorhanden, es gibt nichts Neues zu importieren.</Alert>
      )}

      <div className="flex justify-between gap-2">
        <Button variant="secondary" onClick={props.onBack}>
          <ArrowLeft aria-hidden /> Zurück
        </Button>
        <Button disabled={props.pending || preview.rows_new === 0} onClick={props.onImport}>
          {props.pending && <Loader2 className="animate-spin" aria-hidden />}
          {preview.rows_new} Buchungen importieren
        </Button>
      </div>
    </Card>
  );
}

function ResultStep(props: {
  result: { run: ImportRun; from: string | null; to: string | null };
  accountId: string;
  onAgain: () => void;
}) {
  const { run, from, to } = props.result;
  const failed = run.status === "failed";
  return (
    <Card className="space-y-4">
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "flex size-10 items-center justify-center rounded-full",
            failed ? "bg-negative/10 text-negative" : "bg-positive/10 text-positive",
          )}
        >
          {failed ? <AlertTriangle aria-hidden /> : <Check aria-hidden />}
        </span>
        <div>
          <CardTitle>{failed ? "Import fehlgeschlagen" : "Import abgeschlossen"}</CardTitle>
          <CardDescription className="mt-0">{run.filename}</CardDescription>
        </div>
      </div>
      {run.error && <Alert tone="error">{run.error}</Alert>}
      <div className="grid grid-cols-3 gap-3">
        <Count label="Neu importiert" value={run.rows_new} />
        <Count label="Duplikate" value={run.rows_duplicate} />
        <Count label="Übersprungen" value={run.rows_skipped} />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button asChild>
          <Link
            to="/transactions"
            search={
              from && to
                ? { account: props.accountId, from, to }
                : { account: props.accountId, period: "all" }
            }
          >
            Buchungen ansehen
          </Link>
        </Button>
        <Button variant="secondary" onClick={props.onAgain}>
          Weitere Datei importieren
        </Button>
      </div>
    </Card>
  );
}

function ImportHistory({ accountId }: { accountId: string }) {
  const { data: runs = [] } = useQuery(importRunsQuery(accountId));
  return (
    <Card>
      <CardTitle>Letzte Importe</CardTitle>
      {runs.length === 0 ? (
        <CardDescription>Für dieses Konto gab es noch keinen Import.</CardDescription>
      ) : (
        <ul className="mt-3 divide-y divide-border">
          {runs.slice(0, 10).map((run) => (
            <li key={run.id} className="space-y-0.5 py-2.5 text-sm">
              <div className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate font-medium">{run.filename ?? "Ohne Dateiname"}</span>
                {run.status === "failed" && <Badge className="text-negative">fehlgeschlagen</Badge>}
              </div>
              <p className="text-xs text-text-muted">
                {formatDateTime(run.started_at)} · {run.rows_new} neu · {run.rows_duplicate} Duplikate ·{" "}
                {run.rows_skipped} übersprungen
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
