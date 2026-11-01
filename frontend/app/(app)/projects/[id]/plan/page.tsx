"use client";
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowDown, ArrowUp, CheckCircle2, Plus, RefreshCw, Rocket, Trash2, Wand2 } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { useIdParam, useLoad } from "@/lib/hooks";
import type { AnalysisPlan, MLSpec } from "@/lib/types";
import { humanize } from "@/lib/format";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { PageSkeleton, Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { EmptyState, PageHeader, PathBadge, ProjectSteps } from "@/components/layout/common";
import { ChipListEditor, TextListEditor } from "@/components/project/ListEditor";

function Field({ id, label, children, hint }: { id: string; label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function MLSpecEditor({
  ml,
  onChange,
  columns,
  readOnly,
}: {
  ml: MLSpec;
  onChange: (m: MLSpec) => void;
  columns: string[];
  readOnly: boolean;
}) {
  const set = <K extends keyof MLSpec>(k: K, v: MLSpec[K]) => onChange({ ...ml, [k]: v });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Model specification <Badge variant="secondary">{humanize(ml.problem)}</Badge>
        </CardTitle>
        <CardDescription>What the model predicts, from which columns, and how it is validated.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="ml-target" label="Target column">
            <Input id="ml-target" list="plan-columns" value={ml.target ?? ""} readOnly={readOnly} onChange={(e) => set("target", e.target.value || null)} />
          </Field>
          <Field id="ml-model" label="Model family">
            <Input id="ml-model" value={ml.model_family} readOnly={readOnly} onChange={(e) => set("model_family", e.target.value)} />
          </Field>
          {(ml.time_column !== null || ml.problem === "forecasting") && (
            <Field id="ml-time" label="Time column">
              <Input id="ml-time" list="plan-columns" value={ml.time_column ?? ""} readOnly={readOnly} onChange={(e) => set("time_column", e.target.value || null)} />
            </Field>
          )}
          {(ml.horizon !== null || ml.problem === "forecasting") && (
            <Field id="ml-horizon" label="Forecast horizon (periods)">
              <Input
                id="ml-horizon"
                type="number"
                min={1}
                value={ml.horizon ?? ""}
                readOnly={readOnly}
                onChange={(e) => set("horizon", e.target.value ? Number(e.target.value) : null)}
              />
            </Field>
          )}
        </div>
        <datalist id="plan-columns">
          {columns.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
        <ChipListEditor label="Features" values={ml.features} onChange={(v) => set("features", v)} suggestions={columns} placeholder="Add feature column" readOnly={readOnly} />
        <ChipListEditor
          label="Excluded columns (leakage / IDs)"
          values={ml.excluded_columns}
          onChange={(v) => set("excluded_columns", v)}
          suggestions={columns}
          placeholder="Exclude a column"
          readOnly={readOnly}
        />
        <Field id="ml-validation" label="Validation strategy">
          <Textarea id="ml-validation" rows={2} value={ml.validation} readOnly={readOnly} onChange={(e) => set("validation", e.target.value)} />
        </Field>
        <ChipListEditor label="Metrics" values={ml.metrics} onChange={(v) => set("metrics", v)} placeholder="e.g. auc" readOnly={readOnly} />
        <Field id="ml-baseline" label="Baseline to beat">
          <Input id="ml-baseline" value={ml.baseline} readOnly={readOnly} onChange={(e) => set("baseline", e.target.value)} />
        </Field>
      </CardContent>
    </Card>
  );
}

export default function PlanPage() {
  const id = useIdParam();
  const router = useRouter();
  const toast = useToast();
  const project = useLoad(() => api.getProject(id), [id]);
  const planRow = useLoad(() => api.getPlan(id), [id]);
  const [draft, setDraft] = React.useState<AnalysisPlan | null>(null);
  const [generating, setGenerating] = React.useState(false);
  const [approving, setApproving] = React.useState(false);
  const [genError, setGenError] = React.useState<string | null>(null);
  const autoTried = React.useRef(false);

  React.useEffect(() => {
    if (planRow.data) setDraft(structuredClone(planRow.data.plan_json));
  }, [planRow.data]);

  const generate = React.useCallback(async () => {
    setGenerating(true);
    setGenError(null);
    try {
      const row = await api.generatePlan(id);
      planRow.setData(row);
      void project.reload();
    } catch (e) {
      setGenError(errorMessage(e));
    } finally {
      setGenerating(false);
    }
  }, [id, planRow, project]);

  // First visit after validation: propose a plan automatically.
  React.useEffect(() => {
    if (autoTried.current || planRow.loading || planRow.data || !project.data) return;
    if (project.data.status === "DATA_VALIDATED") {
      autoTried.current = true;
      void generate();
    }
  }, [planRow.loading, planRow.data, project.data, generate]);

  const approve = async () => {
    if (!draft) return;
    setApproving(true);
    try {
      const cleaned: AnalysisPlan = {
        ...draft,
        steps: draft.steps.filter((s) => s.title.trim() || s.detail.trim()),
        assumptions: draft.assumptions.filter((a) => a.trim()),
        expected_outputs: draft.expected_outputs.filter((a) => a.trim()),
      };
      const run = await api.approvePlan(id, cleaned);
      toast.success("Plan approved", "The analysis is running.");
      router.push(`/projects/${id}/run?run=${run.id}`);
    } catch (e) {
      toast.error("Could not approve plan", errorMessage(e));
      setApproving(false);
    }
  };

  if (project.loading && !project.data) return <PageSkeleton />;
  if (!project.data) return <Alert variant="destructive" title="Could not load project">{project.error}</Alert>;
  const p = project.data;
  const approved = !!planRow.data?.approved;
  const readOnly = approved;
  const columns = p.analysis?.data_spec?.columns.map((c) => c.name) ?? [];
  const set = <K extends keyof AnalysisPlan>(k: K, v: AnalysisPlan[K]) => setDraft((d) => (d ? { ...d, [k]: v } : d));
  const moveStep = (i: number, dir: -1 | 1) =>
    setDraft((d) => {
      if (!d) return d;
      const steps = [...d.steps];
      const j = i + dir;
      if (j < 0 || j >= steps.length) return d;
      [steps[i], steps[j]] = [steps[j], steps[i]];
      return { ...d, steps };
    });
  const dirty = !!draft && !!planRow.data && JSON.stringify(draft) !== JSON.stringify(planRow.data.plan_json);

  return (
    <>
      <ProjectSteps projectId={id} status={p.status} current="plan" />
      <PageHeader
        eyebrow="Step 3 · Plan"
        title={draft?.title || p.name}
        description="Review how Datrix will analyse your data. Edit anything, then approve to start the run. Nothing runs until you approve."
        actions={
          draft && (
            <>
              {!approved && (
                <Button variant="outline" onClick={() => void generate()} loading={generating} disabled={approving}>
                  <RefreshCw /> Regenerate
                </Button>
              )}
              {approved ? (
                <Link href={`/projects/${id}/run`} className={buttonVariants()}>
                  View run
                </Link>
              ) : (
                <Button onClick={() => void approve()} loading={approving} disabled={generating}>
                  <Rocket /> {dirty ? "Approve edited plan" : "Approve & run"}
                </Button>
              )}
            </>
          )
        }
      />

      {genError && (
        <Alert variant="destructive" title="Could not generate a plan" className="mb-4">
          {genError}{" "}
          {/validat/i.test(genError) && (
            <Link href={`/projects/${id}/data`} className="underline">
              Go to data
            </Link>
          )}
        </Alert>
      )}
      {approved && (
        <Alert variant="success" title="This plan was approved" className="mb-4">
          To change the analysis after a run, fork the pipeline from its page.
        </Alert>
      )}

      {(planRow.loading && !planRow.data) || (generating && !draft) ? (
        <div className="space-y-4" aria-busy="true">
          {generating && <p className="text-sm text-muted-foreground">The strategy planner is choosing between an ML model and an analysis script…</p>}
          <Skeleton className="h-32" />
          <Skeleton className="h-64" />
        </div>
      ) : !draft ? (
        <EmptyState
          icon={Wand2}
          title="No plan yet"
          description={p.status === "DATA_VALIDATED" || p.status === "PLAN_PROPOSED" ? "Generate a plan from your validated data." : "Validate your data first, then generate a plan."}
          action={
            p.status === "DATA_VALIDATED" || p.status === "PLAN_PROPOSED" ? (
              <Button onClick={() => void generate()} loading={generating}>
                <Wand2 /> Generate plan
              </Button>
            ) : (
              <Link href={`/projects/${id}/data`} className={buttonVariants({ variant: "outline" })}>
                Go to data
              </Link>
            )
          }
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center gap-2">
                  Approach <PathBadge path={draft.path} />
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <Field id="plan-title" label="Title">
                  <Input id="plan-title" value={draft.title} readOnly={readOnly} onChange={(e) => set("title", e.target.value)} />
                </Field>
                <Field id="plan-rationale" label="Why this approach">
                  <Textarea id="plan-rationale" rows={3} value={draft.rationale} readOnly={readOnly} onChange={(e) => set("rationale", e.target.value)} />
                </Field>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Steps</CardTitle>
                <CardDescription>What the generated code will do, in order.</CardDescription>
              </CardHeader>
              <CardContent>
                <ol className="space-y-3">
                  {draft.steps.map((s, i) => (
                    <li key={i} className="flex gap-3 rounded-lg border p-3">
                      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/12 text-xs font-semibold text-primary">
                        {i + 1}
                      </span>
                      <div className="min-w-0 flex-1 space-y-2">
                        {readOnly ? (
                          <>
                            <div className="font-medium">{s.title}</div>
                            <p className="text-sm text-muted-foreground">{s.detail}</p>
                          </>
                        ) : (
                          <>
                            <Input
                              aria-label={`Step ${i + 1} title`}
                              value={s.title}
                              onChange={(e) => set("steps", draft.steps.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))}
                              className="font-medium"
                            />
                            <Textarea
                              aria-label={`Step ${i + 1} detail`}
                              rows={2}
                              value={s.detail}
                              onChange={(e) => set("steps", draft.steps.map((x, j) => (j === i ? { ...x, detail: e.target.value } : x)))}
                            />
                          </>
                        )}
                      </div>
                      {!readOnly && (
                        <div className="flex shrink-0 flex-col gap-1">
                          <Button variant="ghost" size="icon" className="size-7" aria-label={`Move step ${i + 1} up`} disabled={i === 0} onClick={() => moveStep(i, -1)}>
                            <ArrowUp />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-7"
                            aria-label={`Move step ${i + 1} down`}
                            disabled={i === draft.steps.length - 1}
                            onClick={() => moveStep(i, 1)}
                          >
                            <ArrowDown />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-7 text-destructive"
                            aria-label={`Delete step ${i + 1}`}
                            onClick={() => set("steps", draft.steps.filter((_, j) => j !== i))}
                          >
                            <Trash2 />
                          </Button>
                        </div>
                      )}
                    </li>
                  ))}
                </ol>
                {!readOnly && (
                  <Button variant="outline" size="sm" className="mt-3" onClick={() => set("steps", [...draft.steps, { title: "", detail: "" }])}>
                    <Plus /> Add step
                  </Button>
                )}
              </CardContent>
            </Card>

            {draft.path === "ml" && draft.ml && (
              <MLSpecEditor ml={draft.ml} onChange={(m) => set("ml", m)} columns={columns} readOnly={readOnly} />
            )}
          </div>

          <div className="min-w-0 space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Assumptions</CardTitle>
              </CardHeader>
              <CardContent>
                <TextListEditor label="Assumptions" values={draft.assumptions} onChange={(v) => set("assumptions", v)} placeholder="Add assumption" readOnly={readOnly} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Expected outputs</CardTitle>
                <CardDescription>What the results will contain.</CardDescription>
              </CardHeader>
              <CardContent>
                <ChipListEditor label="Outputs" values={draft.expected_outputs} onChange={(v) => set("expected_outputs", v)} placeholder="Add output" readOnly={readOnly} />
              </CardContent>
            </Card>
            {!approved && (
              <Button size="lg" className="w-full" onClick={() => void approve()} loading={approving} disabled={generating}>
                <CheckCircle2 /> Approve & run
              </Button>
            )}
          </div>
        </div>
      )}
    </>
  );
}
