import {
  Badge,
  Button,
  Card,
  CardHeader,
  Field,
  Input,
  Select,
  SpinButton,
  Spinner,
  Switch,
  Text,
} from "@fluentui/react-components";
import { useEffect, useState } from "react";
import { api, postJson } from "../api";
import { FeedbackRegion } from "../components/FeedbackRegion";
import { useAppStyles } from "../styles";
import type { Language } from "../i18n";
import type { JsonObject, PageProps } from "./types";
import { errorMessage } from "./types";

type OperationParameter = {
  key: string;
  label: string;
  summary?: string;
  type: "boolean" | "integer" | "choice" | "text";
  required?: boolean;
  default?: unknown;
  choices?: string[];
};

type Operation = {
  key: string;
  title?: string;
  summary?: string;
  risk?: string;
  command?: string;
  text?: Partial<Record<Language, { title?: string; summary?: string; risk?: string }>>;
  parameters?: OperationParameter[];
};

type OperationResult = { summary?: string; lines?: string[] };

function operationText(operation: Operation, language: Language, part: "title" | "summary" | "risk") {
  return operation.text?.[language]?.[part] ?? operation[part] ?? "";
}

function initialDraft(operation: Operation) {
  return Object.fromEntries((operation.parameters ?? []).map((parameter) => [
    parameter.key,
    parameter.type === "boolean" ? Boolean(parameter.default) : (parameter.default ?? ""),
  ]));
}

export function OperationsPage({ language, t }: PageProps) {
  const styles = useAppStyles();
  const [operations, setOperations] = useState<Operation[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, JsonObject>>({});
  const [results, setResults] = useState<Record<string, OperationResult>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [running, setRunning] = useState("");
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    api<{ operations?: Operation[] }>("/api/operations").then((data) => {
      const next = data.operations ?? [];
      setOperations(next);
      setDrafts(Object.fromEntries(next.map((operation) => [operation.key, initialDraft(operation)])));
    }).catch((error) => setLoadError(errorMessage(error)));
  }, []);

  const setValue = (operationKey: string, parameterKey: string, value: unknown) => {
    setDrafts((current) => ({
      ...current,
      [operationKey]: { ...(current[operationKey] ?? {}), [parameterKey]: value },
    }));
  };

  const run = async (operation: Operation) => {
    if (running) return;
    setRunning(operation.key);
    setErrors((value) => ({ ...value, [operation.key]: "" }));
    setResults((value) => {
      const next = { ...value };
      delete next[operation.key];
      return next;
    });
    const source = drafts[operation.key] ?? {};
    const parameters: JsonObject = {};
    for (const parameter of operation.parameters ?? []) {
      const value = source[parameter.key];
      if (parameter.type === "boolean") parameters[parameter.key] = Boolean(value);
      else if (value !== "" && value !== null && value !== undefined) parameters[parameter.key] = value;
    }
    try {
      const response = await postJson<{ result: OperationResult }>("/api/operations/run", { operation: operation.key, parameters });
      setResults((value) => ({ ...value, [operation.key]: response.result }));
    } catch (runError) {
      setErrors((value) => ({ ...value, [operation.key]: errorMessage(runError) }));
    } finally {
      setRunning("");
      requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(`[data-run-operation="${operation.key}"]`)?.focus());
    }
  };

  return (
    <div id="view-operations" className={styles.stack}>
      <FeedbackRegion message={loadError || null} intent="error" />
      {!operations && !loadError && <Spinner label={t("loading")} />}
      {(operations ?? []).map((operation) => {
        const result = results[operation.key];
        const operationError = errors[operation.key];
        const draft = drafts[operation.key] ?? {};
        const isRunning = running === operation.key;
        return (
          <Card className="panel" key={operation.key}>
            <CardHeader
              header={<Text weight="semibold" size={400}>{operationText(operation, language, "title")}</Text>}
              action={<Badge appearance="tint" color="warning">{operationText(operation, language, "risk")}</Badge>}
            />
            <div className={styles.cardBody}>
              <p className={styles.operationSummary} id={`operation-summary-${operation.key}`}>{operationText(operation, language, "summary")}</p>
              <code className={styles.code}>{operation.command ?? ""}</code>
              <div className={styles.stack}>
                {(operation.parameters ?? []).map((parameter) => (
                  <OperationField
                    key={parameter.key}
                    operationKey={operation.key}
                    parameter={parameter}
                    value={draft[parameter.key]}
                    setValue={setValue}
                    t={t}
                  />
                ))}
              </div>
              <div className={styles.pageToolbar}>
                <Button
                  appearance="primary"
                  data-run-operation={operation.key}
                  aria-describedby={`operation-summary-${operation.key}`}
                  aria-busy={isRunning || undefined}
                  disabled={Boolean(running)}
                  onClick={() => void run(operation)}
                >
                  {isRunning ? t("runningOperation") : t("run")}
                </Button>
              </div>
              <FeedbackRegion
                message={operationError || (result ? (result.summary ?? "") : null)}
                title={operationError ? t("operationFailed") : result ? t("operationComplete") : undefined}
                intent={operationError ? "error" : "success"}
              />
              {result && <pre className={styles.codeBlock}>{(result.lines ?? []).join("\n")}</pre>}
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function OperationField({ operationKey, parameter, value, setValue, t }: {
  operationKey: string;
  parameter: OperationParameter;
  value: unknown;
  setValue: (operationKey: string, parameterKey: string, value: unknown) => void;
  t: PageProps["t"];
}) {
  const styles = useAppStyles();
  const control = (() => {
    if (parameter.type === "boolean") {
      return <Switch aria-label={parameter.label} checked={Boolean(value)} label={t(Boolean(value) ? "enabled" : "disabled")} onChange={(_, data) => setValue(operationKey, parameter.key, data.checked)} />;
    }
    if (parameter.type === "integer") {
      return <SpinButton aria-label={parameter.label} value={Number(value ?? 0)} onChange={(_, data) => setValue(operationKey, parameter.key, data.value ?? 0)} />;
    }
    if (parameter.type === "choice") {
      return (
        <Select aria-label={parameter.label} value={String(value ?? "")} onChange={(_, data) => setValue(operationKey, parameter.key, data.value)}>
          {(parameter.choices ?? []).map((choice) => <option key={choice} value={choice}>{choice}</option>)}
        </Select>
      );
    }
    return <Input aria-label={parameter.label} value={String(value ?? "")} onChange={(_, data) => setValue(operationKey, parameter.key, data.value)} />;
  })();

  return (
    <div className={styles.fieldGrid}>
      <div className={styles.fieldIdentity}>
        <Text weight="semibold">{parameter.label}</Text>
        <code className={styles.code}>{parameter.key}</code>
        <Text size={200} className={styles.muted}>{parameter.summary ?? ""}</Text>
      </div>
      <Field required={parameter.required}>{control}</Field>
    </div>
  );
}
